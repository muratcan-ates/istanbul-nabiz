"""Read-only, deterministic priority context for citizen report cards."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Request

from nabiz.console.agency_router import route
from nabiz.console.operator import port_problem
from nabiz.console.report_api import KIND_TR_TEXT, REPORT_KIND, support_counts
from nexus_core import NexusEngine
from nexus_core.escalation import CRITICAL, REPEAT
from nexus_core.router import REASON_TEXT
from nexus_core.state import SignalState

#: Thresholds and display words are design parameters, not measured results.
PRIORITY_TR = {"high": "Yüksek", "medium": "Orta", "normal": "Olağan"}
SUPPORT_MANY = 3
TRIAGE_NOTE = "Öneri. Nabız hiçbir ekibe iş atamaz; karar ve iletme İBB çalışanınındır."
REPORT_AGENCY_QUERY = "metro istasyonu asansör"
AGENCY_WHY = "raylı istasyon asansörü"

triage_routes = APIRouter()


def record_conflict(payload: Mapping[str, Any]) -> str | None:
    """Name only a direct contradiction between a report and the recorded lift status."""
    report_kind = payload.get("report_kind")
    lift_status = payload.get("lift_status")
    if report_kind == "not_working" and lift_status == "working":
        return "İBB kaydında arıza yok"
    if report_kind == "data_wrong" and lift_status == "out_of_service":
        return "İBB kaydında arıza var"
    return None


def report_priority(state: SignalState, support: int, window_hours: int) -> dict[str, Any]:
    """Explain priority from sealed router reasons, folded reports and a direct record conflict."""
    codes = tuple(code for code in state.reasons if code in (CRITICAL, REPEAT))
    payload = state.signal.payload
    reasons: list[str] = []
    if CRITICAL in codes:
        line = payload.get("line")
        reasons.append(f"aktarma istasyonu ({line})" if line else "aktarma istasyonu")
    if REPEAT in codes:
        reasons.append(f"son {window_hours // 24} günde bu istasyonda {state.repeats}. kart")
    reasons.append(f"{support} kişi bildirdi")
    conflict = record_conflict(payload)
    if conflict:
        reasons.append(f"İBB kaydıyla çelişiyor: {conflict}")
    level = "high" if codes else "medium" if support >= SUPPORT_MANY or conflict else "normal"
    return {
        "level": level,
        "label": PRIORITY_TR[level],
        "reasons": reasons,
        "codes": list(codes),
        "code_text": [REASON_TEXT[code] for code in codes],
    }


def report_agency() -> dict[str, Any]:
    """Suggest the institution found by the existing fixed, local routing table."""
    try:
        result = route(REPORT_AGENCY_QUERY)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"id": None, "name": None, "url": None,
                "why": "Kurum listesi okunamadı; 153 doğru kuruma yönlendirir."}
    if result.agency is None:
        return {"id": None, "name": None, "url": None,
                "why": "Kurum çıkarılamadı; 153 doğru kuruma yönlendirir."}
    return {
        "id": result.agency,
        "name": result.name,
        "url": result.url,
        "why": AGENCY_WHY,
        "rule": result.matched,
    }


def triage_of(state: SignalState, support: int, window_hours: int) -> dict[str, Any]:
    """Build the operator-only read model for one citizen report."""
    payload = state.signal.payload
    return {
        "signal_id": state.signal.signal_id,
        "station": payload.get("station"),
        "kind_text": KIND_TR_TEXT.get(payload.get("report_kind"), "asansör bildirimi"),
        "priority": report_priority(state, support, window_hours),
        "agency": report_agency(),
        "note": TRIAGE_NOTE,
    }


def triage_items(engine: NexusEngine) -> dict[str, dict[str, Any]]:
    """Return up to 200 newest citizen reports with their folded support count."""
    states = sorted(
        (state for state in engine.states().values() if state.signal.kind == REPORT_KIND),
        key=lambda state: state.received_at,
        reverse=True,
    )[:200]
    counts = support_counts(engine)
    hours = engine.router.escalation.settings.window_hours
    return {
        state.signal.signal_id: triage_of(state, counts.get(state.signal.signal_id, 1), hours)
        for state in states
    }


@triage_routes.get("/api/console/report-triage")
async def report_triage(request: Request) -> Any:
    """Read current report priority context without writing to the ledger."""
    engine = getattr(request.app.state.ports.console, "engine", None)
    if not isinstance(engine, NexusEngine):
        return port_problem(503, "not_wired", "Önceliklendirme şu an okunamıyor; karar çekirdeği bağlı değil.")
    items = await asyncio.to_thread(triage_items, engine)
    return {"items": items, "note": TRIAGE_NOTE}
