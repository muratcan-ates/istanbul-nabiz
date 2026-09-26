"""Read-only daily spend and NEXUS service receipts for the operator console."""

from __future__ import annotations

import asyncio
import datetime as dt
import statistics
from collections.abc import Iterable, Mapping
from typing import Any

from fastapi import APIRouter, Query, Request

from nabiz.agent import llm
from nabiz.console.budget import FREE_PROVIDERS, SpendGuard
from nabiz.console.model_api import active_rung, provider_label
from nabiz.console.nexus_port import titled
from nabiz.console.operator import port_problem
from nexus_core import NexusEngine
from nexus_core.receipts import receipt_of
from nexus_core.signals import system_clock
from nexus_core.state import SignalState

receipt_routes = APIRouter(prefix="/api/console")

WARN_AT = 0.75  # R05's 75% warning point is a design parameter, not a measured threshold.

RESULT_TR = {
    "closed_by_reflex": "refleksle kapandı",
    "awaiting_approval": "onay bekliyor",
    "approved": "onaylandı",
    "rejected": "reddedildi",
    "deferred": "ertelendi",
    "expired": "süresi doldu",
    "received": "alındı",
}
PATH_TR = {"reflex": "refleks", "arena": "Arena"}


def money(value: float) -> str:
    """Format a configured estimate in Turkish decimal notation."""
    return f"{value:.2f}".replace(".", ",") + " $"


def ratio_of(spent: float, ceiling: float) -> float:
    """Return the share of today's ceiling, treating a zero ceiling as full."""
    return 1.0 if ceiling <= 0 else round(spent / ceiling, 4)


def level_of(ratio: float) -> str:
    """Map the share to a text-backed status level."""
    if ratio >= 1:
        return "full"
    if ratio >= WARN_AT:
        return "warn"
    return "ok"


def guard_view(today: dict[str, Any], *, prefix: str) -> dict[str, Any]:
    """Turn one spend guard snapshot into a compact, priced-or-call-count view."""
    ceiling = today["ceiling"]
    kind = ceiling["kind"]
    ceiling_value = ceiling["value"]
    spent = today["usd"] if kind == "usd" else today["calls"]
    text = f"{prefix} {money(spent)} / {money(ceiling_value)}" if kind == "usd" else (
        f"{prefix} {spent} / {ceiling_value} model çağrısı"
    )
    ratio = ratio_of(spent, ceiling_value)
    return {
        "kind": kind,
        "spent": spent,
        "ceiling": ceiling_value,
        "calls": today["calls"],
        "ratio": ratio,
        "level": level_of(ratio),
        "priced": kind == "usd",
        "text": text,
    }


def badge_of(chat_view: Mapping[str, Any], active_label: str) -> dict[str, str] | None:
    """Describe a near or exhausted cloud ceiling with both an icon and words."""
    if chat_view["level"] == "warn":
        return {"level": "warn", "icon": "alert-triangle", "text": "Günlük model tavanının %75'i kullanıldı"}
    if chat_view["level"] == "full" and active_label == "kural":
        return {"level": "full", "icon": "cloud-off", "text": "Model tavanı doldu: cevaplar kural yolundan"}
    if chat_view["level"] == "full" and active_label == "yerel model":
        return {"level": "full", "icon": "cloud-off", "text": "Bulut tavanı doldu: cevaplar yerel modelden"}
    return None


def _authors_view(counts: Any) -> tuple[dict[str, int] | None, str | None]:
    if not isinstance(counts, Mapping):
        return None, "bağlanmadı"
    authors = {name: value if type(value) is int and value >= 0 else 0 for name in ("model", "yerel model", "kural")
               for value in [counts.get(name, 0)]}
    return authors, None


def _arena_view(engine: NexusEngine | None) -> dict[str, Any]:
    if engine is None:
        return {"wired": False, "text": "Arena: karar çekirdeği bağlı değil"}
    arena_guard = getattr(engine.arena, "guard", None)
    if not isinstance(arena_guard, SpendGuard):
        return {"wired": False, "text": "Arena: kural koltukları (model çağrısı yok)"}
    view = guard_view(arena_guard.today(), prefix="Arena")
    view["wired"] = True
    view["remaining"] = max(0, view["ceiling"] - view["spent"]) if view["kind"] == "calls" else None
    if view["kind"] == "calls":
        view["text"] = f"Arena {view['spent']}/{view['ceiling']}"
    return view


def _engine_from(request: Request) -> NexusEngine | None:
    engine = getattr(request.app.state.ports.console, "engine", None)
    return engine if isinstance(engine, NexusEngine) else None


@receipt_routes.get("/spend")
async def console_spend(request: Request) -> dict[str, Any]:
    """Return the chat and Arena ceilings without exposing keys or model deployment names."""
    state = request.app.state
    guard: SpendGuard = state.guard
    config: llm.LlmConfig = state.chat_config
    today = guard.today()
    chat = guard_view(today, prefix="Bugün")
    active = active_rung(config, guard.allows)
    active_label = provider_label(active.provider if active else None)
    active_author = llm.author_of(active.provider if active else None)
    engine = _engine_from(request)
    usd_per_call = engine.usd_per_call if engine else None
    authors, authors_note = _authors_view(getattr(state, "author_counts", None))
    badge = None if config.provider in FREE_PROVIDERS else badge_of(chat, active_label)
    arena = _arena_view(engine)
    return {
        "day": today["day"],
        "chat": chat,
        "active_author": active_author,
        "active_label": active_label,
        "badge": badge,
        "arena": arena,
        "authors": authors,
        "authors_note": authors_note,
        "usd_per_call": usd_per_call,
        "price_note": "fiyat tanımsız" if usd_per_call is None else "tahmin: çağrı sayısı × tanımlı fiyat",
        "line": " · ".join((chat["text"], f"aktif: {active_label}", arena["text"])),
    }


def receipt_row(state: SignalState, usd_per_call: float | None) -> dict[str, Any] | None:
    """Render one sealed receipt without changing the ledger or consulting a model."""
    receipt = receipt_of(state, usd_per_call)
    if receipt is None:
        return None
    at = state.closed_at or state.drafted_at or state.received_at
    result_label = RESULT_TR.get(str(state.status), "alındı")
    path_label = PATH_TR.get(receipt.path, receipt.path)
    usd_label = "fiyat tanımsız" if receipt.usd is None else "tahmin"
    usd_text = usd_label if receipt.usd is None else f"{receipt.usd:.4f}".replace(".", ",") + " $ (tahmin)"
    wall_ms = f"{receipt.wall_ms:.1f}".replace(".", ",")
    line = f"Sonuç: {result_label} · yol: {path_label} · {wall_ms} ms · model çağrısı: {receipt.llm_calls} · {usd_text}"
    return {
        "signal_id": receipt.signal_id,
        "title": titled(state.signal.title, state),
        "at": at.isoformat(),
        "status": str(state.status),
        "result_label": result_label,
        "path": receipt.path,
        "path_label": path_label,
        "reflex_ms": receipt.reflex_ms,
        "arena_ms": receipt.arena_ms,
        "wall_ms": receipt.wall_ms,
        "llm_calls": receipt.llm_calls,
        "usd": receipt.usd,
        "usd_label": usd_label,
        "line": line,
    }


def receipts_payload(
    states: Iterable[SignalState],
    usd_per_call: float | None,
    limit: int,
    now: dt.datetime,
) -> dict[str, Any]:
    """Build a newest-first receipt list and totals from an in-memory state snapshot."""
    rows = [row for state in states if (row := receipt_row(state, usd_per_call)) is not None]
    rows.sort(key=lambda row: dt.datetime.fromisoformat(row["at"]).timestamp(), reverse=True)
    usd_total = round(sum(row["usd"] for row in rows), 6) if rows and all(row["usd"] is not None for row in rows) else None
    totals = {
        "signals": len(rows),
        "reflex": sum(row["path"] == "reflex" for row in rows),
        "arena": sum(row["path"] == "arena" for row in rows),
        "llm_calls": sum(row["llm_calls"] for row in rows),
        "wall_ms_median": statistics.median(row["wall_ms"] for row in rows) if rows else None,
        "usd": usd_total,
    }
    return {
        "generated_at": now.isoformat(),
        "usd_per_call": usd_per_call,
        "price_note": "fiyat tanımsız" if usd_per_call is None else "tahmin: çağrı sayısı × tanımlı fiyat",
        "totals": totals,
        "receipts": rows[:limit],
    }


@receipt_routes.get("/receipts")
async def console_receipts(request: Request, limit: int = Query(default=20, ge=1, le=100)) -> Any:
    """Read the ledger off the event loop and return its latest service receipts."""
    engine = _engine_from(request)
    if engine is None:
        return port_problem(503, "not_wired", "Karar çekirdeği bu süreçte bağlı değil.")
    states = await asyncio.to_thread(engine.states)
    return receipts_payload(states.values(), engine.usd_per_call, limit, system_clock())
