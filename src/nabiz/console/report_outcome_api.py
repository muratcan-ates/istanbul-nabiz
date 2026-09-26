"""Read a citizen report's decision through a code derived from its signal id."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import logging
from typing import Any

from fastapi import APIRouter, Query, Request, Response

from nabiz.console.citizen_requests import CODE_ALPHABET, CODE_LENGTH, normal_code
from nabiz.console.operator import port_problem
from nabiz.console.report_api import (
    KIND_TR_TEXT,
    REPORT_KIND,
    canonical_station,
    fold_target,
    report_engine,
    report_entity,
    support_count,
)
from nexus_core import NexusEngine
from nexus_core.signals import system_clock
from nexus_core.state import SignalState

log = logging.getLogger("nabiz.console.report_outcome")

CODE_SALT = "nabiz-report-code|"
OUTCOME_TEXT = {
    "waiting": "Onay bekliyor: simüle operatör henüz karar vermedi.",
    "approved": "Simüle operatör onayladı; bildirim {station} kartında yayımlandı.",
    "not_published": "Simüle operatör bu bildirimi yayımlamadı.",
    "expired": "Karar verilmeden süresi doldu; yayımlanmadı. Resmî kayıt için 153.",
}
OUTCOME_LABEL = {
    "waiting": "Onay bekliyor",
    "approved": "Onaylandı",
    "not_published": "Yayımlanmadı",
    "expired": "Süresi doldu",
}

outcome_routes = APIRouter()


def report_code(signal_id: str) -> str:
    """Return the same short, non-stored code for the same report card."""
    digest = hashlib.sha256(f"{CODE_SALT}{signal_id}".encode()).digest()
    return "".join(CODE_ALPHABET[value % len(CODE_ALPHABET)] for value in digest[:CODE_LENGTH])


def find_outcome(engine: NexusEngine, code: str) -> SignalState | None:
    """Find only citizen-report signals whose derived code matches."""
    return next(
        (
            state
            for signal_id, state in engine.states().items()
            if state.signal.kind == REPORT_KIND and report_code(signal_id) == code
        ),
        None,
    )


def outcome_view(state: SignalState, support: int, ttl_hours: int, now: dt.datetime) -> dict[str, Any]:
    """Map ledger state to the four citizen-safe outcomes without writing to the ledger."""
    status = state.status
    if status in {"received", "awaiting_approval", "deferred"}:
        status = "waiting"
        cutoff = now - dt.timedelta(hours=ttl_hours) if ttl_hours > 0 else None
        if (
            state.status == "awaiting_approval"
            and state.drafted_at is not None
            and cutoff is not None
            and state.drafted_at <= cutoff
        ):
            status = "expired"
    elif status in {"rejected", "closed_by_reflex"} or status not in {"approved", "expired"}:
        status = "not_published"

    payload = state.signal.payload
    station = payload.get("station")
    kind = payload.get("report_kind")
    text = OUTCOME_TEXT[status].format(station=station) if status == "approved" else OUTCOME_TEXT[status]
    return {
        "code": report_code(state.signal.signal_id),
        "station": station,
        "kind": kind,
        "kind_text": KIND_TR_TEXT.get(kind, "asansör bildirimi"),
        "status": status,
        "label": OUTCOME_LABEL[status],
        "text": text,
        "support_count": support,
        "note": "Resmî İBB başvurusu değildir; resmî kayıt için 153.",
    }


def _no_store(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store"
    return response


def _ready(request: Request) -> tuple[NexusEngine | None, Any, Response | None]:
    engine = report_engine(request)
    nabiz = getattr(request.app.state, "nabiz", None)
    if engine is None or nabiz is None:
        problem = port_problem(503, "not_wired", "Bildirim durumu şu an okunamıyor; karar çekirdeği bağlı değil.")
        return None, nabiz, _no_store(problem)
    return engine, nabiz, None


@outcome_routes.get("/api/report/code")
async def citizen_report_code(
    request: Request,
    response: Response,
    station: str = Query(..., min_length=2, max_length=60),
    kind: str = Query(..., pattern=r"^(not_working|data_wrong)$"),
) -> Any:
    """Return a derived code for the current open card, without spending report quota."""
    engine, nabiz, problem = _ready(request)
    if problem is not None:
        return problem
    canonical = await canonical_station(nabiz, station)
    if canonical is None:
        problem = port_problem(422, "unknown_station", "Bu istasyon adı İBB istasyon listesinde yok.")
        return _no_store(problem)

    now = getattr(request.app.state, "report_clock", system_clock)()
    entity = report_entity(canonical[0], kind)
    states = await asyncio.to_thread(engine.states)
    target_id = None
    pending = getattr(request.app.state, "report_pending", {}).get(entity)
    if pending is not None:
        pending_id, opened_at = pending
        age = now - opened_at
        pending_state = states.get(pending_id)
        if dt.timedelta(0) <= age < dt.timedelta(minutes=30) and (
            pending_state is None or pending_state.status == "awaiting_approval"
        ):
            target_id = pending_id
    if target_id is None:
        target = fold_target(states, entity, now)
        target_id = target.signal.signal_id if target is not None else None
    if target_id is None:
        problem = port_problem(
            404,
            "no_open_report",
            "Bu istasyon için son 30 dakikada onay bekleyen bildirim yok.",
        )
        return _no_store(problem)

    log.info("report code kind=%s found=%s", kind, True)
    response.headers["Cache-Control"] = "no-store"
    return {"code": report_code(target_id), "station": canonical[0], "kind": kind}


@outcome_routes.get("/api/report/outcome/{code}")
async def report_outcome(request: Request, code: str, response: Response) -> Any:
    """Read a citizen-safe decision view without exposing the signal or operator record."""
    engine, _, problem = _ready(request)
    if problem is not None:
        return problem
    normalized = normal_code(code)
    if normalized is None:
        problem = port_problem(422, "invalid_code", "Bildirim kimliği geçersiz.")
        return _no_store(problem)

    state = await asyncio.to_thread(find_outcome, engine, normalized)
    if state is None:
        problem = port_problem(404, "report_not_found", "Bu bildirim bulunamadı ya da süresi doldu.")
        return _no_store(problem)
    now = getattr(request.app.state, "report_clock", system_clock)()
    support = await asyncio.to_thread(support_count, engine, state.signal.signal_id)
    response.headers["Cache-Control"] = "no-store"
    return outcome_view(state, support, engine.ttl_hours, now)


__all__ = [
    "CODE_SALT",
    "OUTCOME_LABEL",
    "OUTCOME_TEXT",
    "citizen_report_code",
    "find_outcome",
    "outcome_routes",
    "outcome_view",
    "report_code",
    "report_outcome",
]
