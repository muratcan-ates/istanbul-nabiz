"""A private, text-free citizen report that always waits for a simulated operator."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ibb_mcp.text import fold_tr, squash_punctuation
from nabiz.console.access import TurnLimiter
from nabiz.console.operator import port_problem
from nabiz.console.signals import origin_from
from nexus_core import EvidenceItem, NexusEngine, Origin, Signal
from nexus_core.signals import Severity, system_clock
from nexus_core.state import SignalState
from nexus_core.stats import ISTANBUL

log = logging.getLogger("nabiz.console.report")

# These are design parameters, not measurements.
REPORT_KIND = "citizen_report"
SUPPORT_ENTRY = "citizen_support"
REPORT_SOURCE = "Vatandaş bildirimi (Nabız)"
FOLD_WINDOW = dt.timedelta(minutes=30)
REPORTS_PER_MIN = 3
REPORT_WAIT_S = 3.0
#: A report at a station whose name carries this many lines (an interchange) is critical: the
#: router's own ``critical`` trigger then seals it (E29). A design parameter, not a measurement.
HUB_MIN_LINES = 2

KIND_TR_TEXT = {"not_working": "asansör kapalıydı", "data_wrong": "kayıt yanlış görünüyor"}
BUCKET_TR = {"now": "şimdi", "today": "bugün"}
PUBLIC_NOTE = "Kamu kartı, bir İBB çalışanı (simüle operatör) onaylamadan değişmez."
REPORT_TEXT = {
    ("not_working", "now"): "asansörün kapalı olduğu bildirildi",
    ("not_working", "today"): "bugün asansörün kapalı olduğu bildirildi",
    ("data_wrong", "now"): "asansör kaydının yerindeki durumla uyuşmadığı bildirildi",
    ("data_wrong", "today"): "bugün asansör kaydının yerindeki durumla uyuşmadığı bildirildi",
}

report_routes = APIRouter()


class ReportBody(BaseModel):
    """Only the station, report category and time bucket cross the request boundary."""

    model_config = ConfigDict(extra="forbid")

    station: str = Field(min_length=2, max_length=60, pattern=r"^[\w .\-]+$")
    kind: Literal["not_working", "data_wrong"]
    bucket: Literal["now", "today"]


def report_limiter(app: Any) -> TurnLimiter:
    """Create the in-memory address bucket on first use."""
    limiter = getattr(app.state, "report_limiter", None)
    if limiter is None:
        limiter = app.state.report_limiter = TurnLimiter(REPORTS_PER_MIN)
    return limiter


def report_engine(request: Request) -> NexusEngine | None:
    """Return only the wired decision engine, including when an unwired port is present."""
    engine = getattr(request.app.state.ports.console, "engine", None)
    return engine if isinstance(engine, NexusEngine) else None


async def canonical_station(nabiz: Any, station: str) -> tuple[str, list[str]] | None:
    """Resolve a full station name; prefix matches from the catalogue are not accepted."""
    try:
        result = await nabiz.metro_station_info(station)
    except ValueError:
        return None
    wanted = squash_punctuation(fold_tr(station))
    matches = [
        item for item in result.data.get("stations", [])
        if squash_punctuation(fold_tr(str(item.get("name") or ""))) == wanted
    ]
    if not matches:
        return None
    name = str(matches[0]["name"])
    lines = sorted(
        {str(item["line_name"]) for item in matches if item.get("line_name")},
        key=fold_tr,
    )
    return name, lines


def report_entity(station: str, kind: str) -> str:
    """The same station and report category share one approval card."""
    return f"citizen-report:{squash_punctuation(fold_tr(station))}:{kind}"


def report_text(kind: str, bucket: str) -> str:
    """Build a fixed, bounded sentence without accepting visitor-written text."""
    return REPORT_TEXT[(kind, bucket)]


def report_severity(lines: Sequence[str]) -> Severity:
    """``critical`` at an interchange (same station name on ≥ 2 lines), else ``warning`` as in E24."""
    return "critical" if len({line for line in lines if line}) >= HUB_MIN_LINES else "warning"


def support_summary(state: SignalState, count: int) -> str:
    """Summarize the first observation and its current folded count for the operator."""
    payload = state.signal.payload
    station = payload.get("station", "İstasyon")
    report_kind = KIND_TR_TEXT.get(payload.get("report_kind"), "asansör bildirimi")
    bucket = BUCKET_TR.get(payload.get("bucket"), "zaman bilinmiyor")
    lift_text = payload.get("lift_text") or "okunamadı"
    first_seen = state.received_at.astimezone(ISTANBUL).strftime("%H:%M")
    summary = (
        f"Vatandaş bildirimi: {station} · {report_kind} · {bucket}. "
        f"İBB kaydı: {lift_text}. {count} kişi bildirdi; ilk bildirim {first_seen}."
    )
    return summary[:300]


def report_signal(
    station: str,
    lines: list[str],
    kind: str,
    bucket: str,
    now: dt.datetime,
    lift: tuple[str | None, str | None, Origin | None],
) -> tuple[Signal, tuple[EvidenceItem, ...]]:
    """Create the bounded report signal and its source evidence."""
    lift_status, lift_text, lift_origin = lift
    payload: dict[str, Any] = {
        "station": station,
        "line": ", ".join(lines) or None,
        "report_kind": kind,
        "bucket": bucket,
        "report_text": report_text(kind, bucket),
        "lift_status": lift_status,
        "lift_text": lift_text,
        "operator_text": "",
    }
    origin = Origin(source=REPORT_SOURCE, url=None, observed_at=now, mode="live")
    signal = Signal.create(
        kind=REPORT_KIND,
        entity_id=report_entity(station, kind),
        severity=report_severity(lines),
        observed_at=now,
        provenance=origin,
        payload=payload,
    )
    first_state = SignalState(signal=signal, received_at=now)
    payload["operator_text"] = support_summary(first_state, 1)
    signal = signal.model_copy(update={"payload": payload})
    evidence = [
        EvidenceItem(
            text=f"Vatandaş bildirimi: {station} · {KIND_TR_TEXT[kind]} · {BUCKET_TR[bucket]}",
            provenance=signal.provenance,
        )
    ]
    if lift_text and lift_origin is not None:
        evidence.append(EvidenceItem(text=f"İBB kaydı: {lift_text}"[:600], provenance=lift_origin))
    return signal, tuple(evidence)


def fold_target(
    states: Mapping[str, SignalState], entity_id: str, now: dt.datetime
) -> SignalState | None:
    """Find the newest same-entity card still awaiting a person inside the fold window."""
    candidates = [
        state for state in states.values()
        if state.signal.kind == REPORT_KIND
        and state.signal.entity_id == entity_id
        and state.status == "awaiting_approval"
        and dt.timedelta(0) <= now - state.received_at < FOLD_WINDOW
    ]
    return max(candidates, key=lambda state: state.received_at, default=None)


def support_count(engine: NexusEngine, signal_id: str) -> int:
    """Count the first report and each sealed support entry."""
    return 1 + len(engine.ledger.entries(signal_id=signal_id, kinds=[SUPPORT_ENTRY]))


def support_counts(engine: NexusEngine) -> dict[str, int]:
    """Count all report cards with one support-entry scan for the operator queue."""
    states = engine.states()
    counts = {
        signal_id: 1
        for signal_id, state in states.items()
        if state.signal.kind == REPORT_KIND
    }
    for entry in engine.ledger.entries(kinds=[SUPPORT_ENTRY]):
        if entry.signal_id in counts:
            counts[entry.signal_id] += 1
    return counts


def support_step_text(detail: Mapping[str, Any]) -> str:
    """Describe a support entry in the operator's ledger trace."""
    count = detail.get("support_count")
    if not isinstance(count, int) or isinstance(count, bool):
        return "Vatandaş bildirimi katlandı."
    return f"Vatandaş bildirimi katlandı: toplam {count} kişi."


def confirmation(count: int) -> str:
    """The response sentence stays truthful while a card awaits a human decision."""
    return f"Bildiriminiz İBB çalışanının kuyruğuna düştü (simüle operatör) · {count} kişi"


def _app_lock(app: Any) -> asyncio.Lock:
    lock = getattr(app.state, "report_lock", None)
    if lock is None:
        lock = app.state.report_lock = asyncio.Lock()
    return lock


def _pending_reports(app: Any) -> dict[str, tuple[str, dt.datetime]]:
    pending = getattr(app.state, "report_pending", None)
    if pending is None:
        pending = app.state.report_pending = {}
    return pending


def _report_tasks(app: Any) -> set[asyncio.Task[Any]]:
    tasks = getattr(app.state, "report_tasks", None)
    if tasks is None:
        tasks = app.state.report_tasks = set()
    return tasks


def _track_task(app: Any, task: asyncio.Task[Any], entity_id: str, signal_id: str) -> None:
    """Keep processing alive and log only an exception type if it fails."""
    tasks = _report_tasks(app)
    tasks.add(task)

    def finished(done: asyncio.Task[Any]) -> None:
        tasks.discard(done)
        if done.cancelled():
            return
        error = done.exception()
        if error is not None:
            pending = _pending_reports(app)
            if pending.get(entity_id, (None, None))[0] == signal_id:
                pending.pop(entity_id, None)
            log.warning("citizen report processing failed: %s", type(error).__name__)

    task.add_done_callback(finished)


def _clear_expired_pending(pending: dict[str, tuple[str, dt.datetime]], now: dt.datetime) -> None:
    for entity_id, (_, opened_at) in list(pending.items()):
        if now - opened_at >= FOLD_WINDOW:
            pending.pop(entity_id, None)


def _pending_target(
    pending: dict[str, tuple[str, dt.datetime]],
    states: Mapping[str, SignalState],
    entity_id: str,
) -> str | None:
    item = pending.get(entity_id)
    if item is None:
        return None
    signal_id, _ = item
    state = states.get(signal_id)
    # Not in the ledger yet, or sealed but still in the Arena ("received"): processing is running,
    # so the card will reach the queue and a new report folds into it instead of opening a twin.
    if state is None or state.status in ("received", "awaiting_approval"):
        return signal_id
    pending.pop(entity_id, None)
    return None


async def record_report(
    request: Request,
    engine: NexusEngine,
    body: ReportBody,
    canonical: tuple[str, list[str]],
    lift: tuple[str | None, str | None, Origin | None],
    now: dt.datetime,
) -> dict[str, Any]:
    """Fold a report into an open card or start processing one new card."""
    app = request.app
    station, lines = canonical
    entity_id = report_entity(station, body.kind)
    task: asyncio.Task[Any] | None = None
    async with _app_lock(app):
        states = await asyncio.to_thread(engine.states)
        pending = _pending_reports(app)
        _clear_expired_pending(pending, now)
        target_id = _pending_target(pending, states, entity_id)
        if target_id is None:
            target = fold_target(states, entity_id, now)
            target_id = target.signal.signal_id if target else None
        if target_id is not None:
            count = await asyncio.to_thread(support_count, engine, target_id) + 1
            await asyncio.to_thread(
                engine.ledger.append,
                SUPPORT_ENTRY,
                actor="vatandaş (anonim)",
                detail={"report_kind": body.kind, "bucket": body.bucket, "support_count": count},
                signal_id=target_id,
                entity_id=entity_id,
            )
            folded = True
        else:
            signal, evidence = report_signal(
                station, lines, body.kind, body.bucket, now, lift
            )
            pending[entity_id] = (signal.signal_id, now)
            task = asyncio.create_task(asyncio.to_thread(engine.process, signal, evidence))
            _track_task(app, task, entity_id, signal.signal_id)
            count = 1
            folded = False
    if task is not None:
        await asyncio.wait({task}, timeout=REPORT_WAIT_S)
    _clear_expired_pending(_pending_reports(app), now)
    return {
        "status": "queued",
        "folded": folded,
        "support_count": count,
        "station": station,
        "kind": body.kind,
        "bucket": body.bucket,
        "window_min": int(FOLD_WINDOW.total_seconds() // 60),
        "message": confirmation(count),
        "note": PUBLIC_NOTE,
    }


async def _lift_evidence(nabiz: Any, station: str) -> tuple[str | None, str | None, Origin | None]:
    try:
        alternative = await nabiz.accessible_alternative(station, ["step_free"])
        data = alternative.data
        status = data.get("lift_status", "unknown")
        text = data.get("text")
        origin = origin_from(alternative.provenance, data.get("mode", "live"))
        return status, text, origin
    except Exception:  # noqa: BLE001 - unreadable records do not block a citizen report
        return None, None, None


def _ready_engine(request: Request) -> tuple[NexusEngine | None, Any, Response | None]:
    engine = report_engine(request)
    nabiz = getattr(request.app.state, "nabiz", None)
    if engine is None or nabiz is None:
        return None, nabiz, port_problem(503, "not_wired", "Bildirim şu an alınamıyor; karar çekirdeği bağlı değil.")
    return engine, nabiz, None


def _allowed(request: Request) -> bool:
    address = request.client.host if request.client else "unknown"
    return report_limiter(request.app).allow(address)


@report_routes.post("/api/report")
async def citizen_report(request: Request, body: ReportBody) -> Any:
    """Accept one short report; no free text, location, identity or public state change."""
    engine, nabiz, problem = _ready_engine(request)
    if problem is not None:
        return problem
    if not _allowed(request):
        return port_problem(429, "too_many_reports", "Çok sık bildirim geldi. Bir dakika sonra yeniden deneyin.")
    canonical = await canonical_station(nabiz, body.station)
    if canonical is None:
        return port_problem(422, "unknown_station", "Bu istasyon adı İBB istasyon listesinde yok.")
    lift = await _lift_evidence(nabiz, canonical[0])
    now = getattr(request.app.state, "report_clock", system_clock)()
    result = await record_report(request, engine, body, canonical, lift, now)
    log.info("citizen report kind=%s bucket=%s folded=%s", body.kind, body.bucket, result["folded"])
    return result


@report_routes.get("/api/report/status")
async def citizen_report_status(
    request: Request,
    station: str = Query(..., min_length=2, max_length=60),
    kind: str = Query(..., pattern=r"^(not_working|data_wrong)$"),
) -> Any:
    """Return the current count for a pending card without recording or rate-limiting a vote."""
    engine, nabiz, problem = _ready_engine(request)
    if problem is not None:
        return problem
    canonical = await canonical_station(nabiz, station)
    if canonical is None:
        return port_problem(422, "unknown_station", "Bu istasyon adı İBB istasyon listesinde yok.")
    now = getattr(request.app.state, "report_clock", system_clock)()
    target = fold_target(await asyncio.to_thread(engine.states), report_entity(canonical[0], kind), now)
    count = await asyncio.to_thread(support_count, engine, target.signal.signal_id) if target else 0
    return {
        "station": canonical[0],
        "kind": kind,
        "support_count": count,
        "window_min": int(FOLD_WINDOW.total_seconds() // 60),
    }
