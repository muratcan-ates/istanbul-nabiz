"""Citizen and operator endpoints for the report processing timeline."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from nabiz.console.citizen_requests import HourlyLimit, normal_code
from nabiz.console.emergency import classify
from nabiz.console.operator import port_problem
from nabiz.console.policy import emergency_intent
from nabiz.console.report_api import REPORT_KIND, report_engine
from nabiz.console.report_outcome_api import find_outcome, outcome_view, report_code
from nabiz.console.report_timeline import (
    TimelineStore,
    TimelineTransitionError,
    load_agencies,
    timeline_view,
)
from nabiz.console.requests_api import EMERGENCY_TEXT
from nexus_core.signals import system_clock
from nexus_core.state import SignalState

log = logging.getLogger("nabiz.console.report_timeline")


class _TimelineRoute(APIRoute):
    """Apply the cache boundary even when FastAPI rejects a request body."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def no_store(request: Request) -> Response:
            try:
                response = await handler(request)
            except RequestValidationError:
                response = port_problem(422, "invalid_request", "İstek geçersiz: bir alan eksik, çok uzun ya da tanınmıyor.")
            response.headers["Cache-Control"] = "no-store"
            return response

        return no_store


timeline_routes = APIRouter(route_class=_TimelineRoute)


class CitizenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["fixed", "ongoing", "info"]
    text: str | None = Field(default=None, max_length=500)
    consent: StrictBool | None = None


class OperatorAdvance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str = Field(min_length=1, max_length=40)
    note: str | None = Field(default=None, max_length=200)
    agency_id: str | None = Field(default=None, max_length=80)


def _no_store(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store"
    return response


def _problem(response: Response, status: int, kind: str, message: str) -> Response:
    return _no_store(port_problem(status, kind, message))


def _ready(request: Request, response: Response) -> tuple[Any, TimelineStore | None, Response | None]:
    engine = report_engine(request)
    if engine is None or getattr(request.app.state, "nabiz", None) is None:
        issue = _problem(response, 503, "not_wired", "Bildirim durumu şu an okunamıyor; karar çekirdeği bağlı değil.")
        return None, None, issue
    store = getattr(request.app.state, "report_timeline", None)
    if store is None:
        store = request.app.state.report_timeline = TimelineStore()
    return engine, store, None


def _now(request: Request) -> dt.datetime:
    return getattr(request.app.state, "report_clock", system_clock)()


def _publication_status(engine: Any, state: SignalState, now: dt.datetime) -> str:
    return outcome_view(state, 0, engine.ttl_hours, now)["status"]


def _row(store: TimelineStore, state: SignalState, code: str) -> dict[str, Any]:
    payload = state.signal.payload
    return store.get(code) or store.virtual_view(
        code, state.signal.signal_id, str(payload.get("station") or ""),
        str(payload.get("report_kind") or ""), state.received_at,
    )


def _view(store: TimelineStore, state: SignalState, code: str, status: str, now: dt.datetime) -> dict[str, Any]:
    return timeline_view(_row(store, state, code), status, now, load_agencies())


async def _find(engine: Any, code: str) -> SignalState | None:
    return await asyncio.to_thread(find_outcome, engine, code)


def _validated_code(response: Response, code: str) -> tuple[str | None, Response | None]:
    normalized = normal_code(code)
    if normalized is None:
        return None, _problem(response, 422, "invalid_code", "Bildirim kimliği geçersiz.")
    return normalized, None


@timeline_routes.get("/api/report/timeline/{code}")
async def citizen_timeline(request: Request, code: str, response: Response) -> Any:
    engine, store, issue = _ready(request, response)
    if issue:
        return issue
    normalized, issue = _validated_code(response, code)
    if issue:
        return issue
    state = await _find(engine, normalized)
    if state is None:
        return _problem(response, 404, "report_not_found", "Bu bildirim bulunamadı ya da süresi doldu.")
    now = _now(request)
    publication = _publication_status(engine, state, now)
    response.headers["Cache-Control"] = "no-store"
    return _view(store, state, normalized, publication, now)


def _emergency(text: str | None) -> bool:
    return bool(text) and (emergency_intent(text) or classify(text)["emergency"])


def _is_untracked(status: str) -> bool:
    return status in {"not_published", "expired"}


def _citizen_gate(request: Request, code: str, body: CitizenResponse, response: Response) -> Any | None:
    if _emergency(body.text):
        response.headers["Cache-Control"] = "no-store"
        return {"emergency": True, "text": EMERGENCY_TEXT}
    if body.text and body.consent is not True:
        return _problem(response, 400, "consent_required", "Metnin saklanması için açık rıza gerekir.")
    limiter = getattr(request.app.state, "report_timeline_limiter", None)
    if limiter is None:
        limiter = request.app.state.report_timeline_limiter = HourlyLimit(3)
    if not limiter.allow(code):
        return _problem(response, 429, "too_many", "Bu bildirim için çok sık yanıt verildi. Resmî kayıt için 153.")
    return None


def _apply_citizen(store: TimelineStore, state: SignalState, code: str, body: CitizenResponse, now: dt.datetime):
    payload = state.signal.payload
    store.ensure(code, state.signal.signal_id, str(payload.get("station") or ""),
                 str(payload.get("report_kind") or ""), state.received_at)
    try:
        row = store.apply(code, "citizen", body.action, text=body.text)
    except TimelineTransitionError:
        return None, port_problem(409, "not_now", "Bu adımda bu yanıt verilemez.")
    except ValueError:
        return None, port_problem(400, "note_required", "Lütfen en az 5 karakter yazın.")
    log.info("report timeline %s stage=%s", body.action, row["stage"])
    return row, None


@timeline_routes.post("/api/report/timeline/{code}/respond")
async def citizen_respond(request: Request, code: str, body: CitizenResponse, response: Response) -> Any:
    engine, store, issue = _ready(request, response)
    if issue:
        return issue
    normalized, issue = _validated_code(response, code)
    if issue:
        return issue
    state = await _find(engine, normalized)
    if state is None:
        return _problem(response, 404, "report_not_found", "Bu bildirim bulunamadı ya da süresi doldu.")
    issue = _citizen_gate(request, normalized, body, response)
    if issue:
        return _no_store(issue) if isinstance(issue, Response) else issue
    now = _now(request)
    publication = _publication_status(engine, state, now)
    if _is_untracked(publication):
        return _problem(response, 409, "not_tracked", "Yayımlanmayan bildirim takip edilmez.")
    row, issue = _apply_citizen(store, state, normalized, body, now)
    if issue:
        return _no_store(issue)
    response.headers["Cache-Control"] = "no-store"
    return timeline_view(row, publication, now, load_agencies())


def _recent_reports(engine: Any, store: TimelineStore, now: dt.datetime) -> list[dict[str, Any]]:
    cutoff = now - dt.timedelta(days=30)
    agencies = load_agencies()
    states = [state for state in engine.states().values()
              if state.signal.kind == REPORT_KIND and cutoff <= state.received_at <= now]
    states.sort(key=lambda state: state.received_at, reverse=True)
    items = []
    for state in states:
        code = report_code(state.signal.signal_id)
        publication = _publication_status(engine, state, now)
        row = _row(store, state, code)
        view = timeline_view(row, publication, now, agencies)
        view["updated_at"] = row["updated_at"]
        view["history"] = [
            {**event, "text_masked": event.get("note_masked")} for event in row["data"]["history"]
        ]
        items.append(view)
    items.sort(key=lambda item: item["updated_at"], reverse=True)
    items.sort(key=lambda item: item["waiting_on"] != "operator")
    return items[:100]


@timeline_routes.get("/api/console/report-timeline")
async def console_timelines(request: Request, response: Response) -> Any:
    engine, store, issue = _ready(request, response)
    if issue:
        return issue
    items = await asyncio.to_thread(_recent_reports, engine, store, _now(request))
    response.headers["Cache-Control"] = "no-store"
    agencies = load_agencies()["agencies"]
    return {"items": items, "agencies": agencies}


@timeline_routes.post("/api/console/report-timeline/{code}/advance")
async def console_advance(request: Request, code: str, body: OperatorAdvance, response: Response) -> Any:
    engine, store, issue = _ready(request, response)
    if issue:
        return issue
    normalized, issue = _validated_code(response, code)
    if issue:
        return issue
    state = await _find(engine, normalized)
    if state is None:
        return _problem(response, 404, "report_not_found", "Bu bildirim bulunamadı ya da süresi doldu.")
    now = _now(request)
    publication = _publication_status(engine, state, now)
    if _is_untracked(publication):
        return _problem(response, 409, "not_tracked", "Yayımlanmayan bildirim takip edilmez.")
    payload = state.signal.payload
    store.ensure(normalized, state.signal.signal_id, str(payload.get("station") or ""),
                 str(payload.get("report_kind") or ""), state.received_at)
    try:
        row = store.apply(normalized, "operator", body.to, to=body.to, text=body.note, agency_id=body.agency_id)
    except TimelineTransitionError:
        return _problem(response, 409, "not_allowed", "Bu adım bu bildirim için kullanılamaz.")
    except ValueError:
        return _problem(response, 400, "details_required", "Not veya geçerli kurum bilgisi gerekli.")
    log.info("report timeline %s stage=%s", body.to, row["stage"])
    response.headers["Cache-Control"] = "no-store"
    return timeline_view(row, publication, now, load_agencies())


__all__ = ["timeline_routes"]
