"""Read-only day view for the simulated operator's decision ledger."""

from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import Iterable, Mapping
from typing import Any

from fastapi import APIRouter, Query, Request

from nabiz.console.nexus_port import ACTION_TR, OPEN, titled
from nabiz.console.operator import port_problem
from nabiz.console.ports import OPERATOR
from nexus_core import NexusEngine
from nexus_core.ledger import EntryKind, LedgerEntry
from nexus_core.router import REASON_TEXT
from nexus_core.rule_drafts import AdoptedRule
from nexus_core.signals import as_utc, system_clock
from nexus_core.state import SignalState
from nexus_core.stats import ISTANBUL

day_routes = APIRouter(prefix="/api/console")
HANDOFF_MAX = 1200
EXPIRING_WITHIN = dt.timedelta(days=3)
EXPIRED_KIND = "expired"


def istanbul_day(at: dt.datetime) -> dt.date:
    """Return the İstanbul calendar day for an aware instant."""
    return as_utc(at).astimezone(ISTANBUL).date()


def summarize_day(entries: Iterable[LedgerEntry], day: dt.date, *, label: str = "Dün") -> dict[str, Any]:
    """Count sealed human decisions and reflex closures for one İstanbul day."""
    counts = {"reflex_closed": 0, "approved": 0, "rejected": 0, "deferred": 0, "expired": 0}
    for entry in entries:
        if istanbul_day(entry.at) != day:
            continue
        if entry.kind == EntryKind.REFLEX_CLOSED:
            counts["reflex_closed"] += 1
        elif entry.kind == EntryKind.APPROVAL:
            status = entry.detail.get("status")
            if status in counts:
                counts[status] += 1
        elif entry.kind == EXPIRED_KIND:
            counts["expired"] += 1
    total = sum(counts.values())
    empty = total == 0
    sentence = (
        f"{label} kayıt yok."
        if empty
        else (
            f"{label}: {counts['approved']} onay, {counts['rejected']} red, {counts['deferred']} erteleme, "
            f"{counts['expired']} süresi dolan kart; refleksle kapanan {counts['reflex_closed']}."
        )
    )
    return {"date": day.isoformat(), **counts, "total": total, "empty": empty, "sentence": sentence}


def day_decisions(entries: Iterable[LedgerEntry], states: Mapping[str, SignalState], day: dt.date) -> list[dict[str, Any]]:
    """Format human ruling entries for one day, newest first and without actor details."""
    rows = []
    for entry in entries:
        if entry.kind != EntryKind.APPROVAL or istanbul_day(entry.at) != day:
            continue
        signal_id = entry.signal_id or ""
        state = states.get(signal_id)
        detail = entry.detail
        action = detail.get("action", "")
        drafted_at = state.drafted_at if state is not None else None
        decision_s = None if drafted_at is None else round(max(0.0, (entry.at - drafted_at).total_seconds()), 1)
        rows.append(
            {
                "entry_id": entry.id,
                "at": entry.at.isoformat(),
                "signal_id": signal_id,
                "kind": state.signal.kind if state is not None else "bilinmiyor",
                "title": titled(state.signal.title, state) if state is not None else signal_id,
                "action": action,
                "action_label": ACTION_TR.get(action, action),
                "status": detail.get("status", ""),
                "reason": detail.get("reason") or "",
                "decision_s": decision_s,
            }
        )
    return sorted(rows, key=lambda row: row["entry_id"], reverse=True)


def open_cards(states: Mapping[str, SignalState]) -> list[dict[str, Any]]:
    """Describe pending and deferred cards in arrival order with their recorded reason."""
    rows = []
    for signal_id, state in states.items():
        if state.status not in OPEN:
            continue
        deferred = state.status == "deferred"
        reason = state.rulings[-1].reason if deferred and state.rulings else ""
        if not deferred:
            reason = "; ".join(REASON_TEXT.get(code, code) for code in state.reasons) or "gerekçe yok"
        rows.append(
            {
                "signal_id": signal_id,
                "title": titled(state.signal.title, state),
                "status": state.status,
                "status_label": "ertelendi" if deferred else "onay bekliyor",
                "since": state.received_at.isoformat(),
                "reason": reason,
                "_received_at": state.received_at,
            }
        )
    rows.sort(key=lambda row: (row["_received_at"], row["signal_id"]))
    return [{key: value for key, value in row.items() if key != "_received_at"} for row in rows]


def expiring_rules(adopted: Iterable[AdoptedRule], now: dt.datetime) -> list[dict[str, Any]]:
    """List adopted, unrevoked rules whose expiry falls in the next three days."""
    start = as_utc(now)
    end = start + EXPIRING_WITHIN
    rows = []
    for rule in adopted:
        expires = as_utc(rule.expires_at)
        if rule.revoked_at is not None or not start < expires <= end:
            continue
        rows.append(
            {
                "rule_id": rule.rule_id,
                "expires_at": rule.expires_at.isoformat(),
                "days_left": (istanbul_day(expires) - istanbul_day(start)).days,
                "_expires": expires,
            }
        )
    rows.sort(key=lambda row: row["_expires"])
    return [{key: value for key, value in row.items() if key != "_expires"} for row in rows]


def _open_line(index: int, item: dict[str, Any]) -> str:
    reason = str(item.get("reason") or "gerekçe yok")
    if len(reason) > 120:
        reason = reason[:119] + "…"
    return f"{index}. {item.get('title', '')} ({item.get('status_label', '')}): {reason}"


def _rule_line(expiring: list[dict[str, Any]]) -> str:
    if not expiring:
        return "3 gün içinde dolacak kural yok."
    rules = ", ".join(
        f"{rule['rule_id']} ({dt.datetime.fromisoformat(rule['expires_at']).astimezone(ISTANBUL):%d.%m.%Y})" for rule in expiring
    )
    return f"3 gün içinde dolacak kurallar: {rules}."


def _verify_line(verify: dict[str, Any]) -> str:
    if not verify.get("ok"):
        return f"Defter: DOĞRULANAMADI, ilk bozuk kayıt {verify.get('first_bad_id')}."
    head = str(verify.get("head") or "")[:12]
    return f"Defter: doğrulandı, {verify.get('entries', 0)} kayıt, son mühür {head}."


def handoff_text(
    *,
    now: dt.datetime,
    today: dict[str, Any],
    open_items: list[dict[str, Any]],
    expiring: list[dict[str, Any]],
    verify: dict[str, Any],
) -> str:
    """Build a deterministic, bounded shift note from the supplied ledger summaries."""
    local_now = as_utc(now).astimezone(ISTANBUL)
    header = [
        f"Vardiya devri · {local_now:%d.%m.%Y %H:%M} (İstanbul saati)",
        "Hazırlayan: simüle operatör. Resmî İBB hizmeti değildir.",
        today["sentence"],
        f"Açık kartlar ({len(open_items)}):" if open_items else "Açık kart yok.",
    ]
    fixed = [*_rule_line(expiring).splitlines(), _verify_line(verify)]
    visible = len(open_items)
    while True:
        items = [_open_line(index, item) for index, item in enumerate(open_items[:visible], start=1)]
        omitted = len(open_items) - visible
        if omitted:
            items.append(f"+{omitted} kart daha (konsolda).")
        lines = [*header, *items, *fixed]
        result = "\n".join(lines)
        if len(result) <= HANDOFF_MAX or visible == 0:
            return result[:HANDOFF_MAX] if len(result) > HANDOFF_MAX else result
        visible -= 1


def day_payload(engine: NexusEngine, day: dt.date, now: dt.datetime) -> dict[str, Any]:
    """Read the ledger and return the complete day panel response."""
    entries = engine.ledger.entries()
    states = engine.states()
    today = summarize_day(entries, day, label="Bugün")
    yesterday = summarize_day(entries, day - dt.timedelta(days=1))
    decisions = day_decisions(entries, states, day)
    opened = open_cards(states)
    rules = expiring_rules(engine.drafts.adopted(), now)
    verified = engine.verify().model_dump(mode="json")
    return {
        "date": day.isoformat(),
        "generated_at": as_utc(now).isoformat(),
        "role": OPERATOR,
        "decisions": decisions,
        "today": today,
        "yesterday": yesterday,
        "open": opened,
        "expiring_rules": rules,
        "verify": verified,
        "handoff": handoff_text(now=now, today=today, open_items=opened, expiring=rules, verify=verified),
    }


@day_routes.get("/day")
async def console_day(
    request: Request,
    date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> Any:
    """Serve one day of sealed decisions without reading sources or writing the ledger."""
    engine = getattr(request.app.state.ports.console, "engine", None)
    if not isinstance(engine, NexusEngine):
        return port_problem(503, "not_wired", "Karar çekirdeği bu süreçte bağlı değil.")
    now = system_clock()
    try:
        day = dt.date.fromisoformat(date) if date else istanbul_day(now)
    except ValueError:
        return port_problem(400, "bad_request", "Tarih YYYY-AA-GG biçiminde olmalı.")
    return await asyncio.to_thread(day_payload, engine, day, now)
