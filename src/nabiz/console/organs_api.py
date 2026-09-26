"""Live NEXUS organ counts and the learning loop, read from the decision ledger."""

from __future__ import annotations

import asyncio
import datetime as dt
import re
from collections import Counter
from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Request

from nabiz.console.operator import port_problem
from nexus_core.approved import BINDING_PREFIX
from nexus_core.engine import NexusEngine
from nexus_core.ledger import LedgerEntry, VerifyResult
from nexus_core.rule_drafts import FIRST_LEARNED_ID
from nexus_core.signals import as_utc, system_clock
from nexus_core.state import SignalState, replay
from nexus_core.stats import ISTANBUL, Stats, compute_stats

organs_routes = APIRouter(prefix="/api/console")

# These are ledger kinds, kept as strings so new core kinds do not silently join an organ.
ORGANS: tuple[dict[str, Any], ...] = (
    {
        "key": "router", "name": "Yönlendirici",
        "what": "Her sinyali kurala bakıp refleks ya da insan yoluna ayırır.", "kinds": ("routed",),
    },
    {
        "key": "reflex", "name": "Refleks", "what": "İzinli eylem kataloğundan kuralı çalıştırır; insan beklemez.",
        "kinds": ("reflex_closed", "reflex_failed"),
    },
    {
        "key": "arena", "name": "Arena", "what": "Üç koltuğun görüşüyle kanıtlı öneri kartı hazırlar.",
        "kinds": ("arena_drafted",),
    },
    {
        "key": "approval", "name": "İnsan onayı", "what": "Kararı insan verir: onaylar, düzenler, reddeder ya da erteler.",
        "kinds": ("approval", "chat_pause", "chat_paused", "chat_resumed"),
    },
    {
        "key": "rules", "name": "Kural taslakları", "what": "Tekrarlanan insan kararlarını incelenecek taslağa çevirir.",
        "kinds": ("rule_adopted", "rule_revoked"),
    },
    {"key": "lifecycle", "name": "Yaşam döngüsü", "what": "Yanıtsız kalan kartın süresi dolunca kapatır.", "kinds": ("expired",)},
    {"key": "ledger", "name": "Defter", "what": "Her adımı mühürler; zinciri her okumada doğrular.", "kinds": ()},
)

LOOP_STAGES = (
    ("signals", "Sinyal"),
    ("reflex", "Refleksle kapanan"),
    ("arena", "Arena kartı"),
    ("approved", "İnsan onayı"),
    ("bound_closed", "Onaylı alternatifle kendiliğinden kapanan"),
    ("drafts", "Kural taslağı"),
    ("adopted", "Benimsenen kural"),
    ("learned_closed", "Öğrenilmiş kuralla kapanan"),
)

METRO_SIGNAL_KINDS = frozenset({"equipment_fault", "long_outage", "hub_faults", "source_stale"})
LEARNED_RULE_ID = re.compile(r"^R-(\d+)$")
LOOP_KIND_STAGES = {
    "signal_received": "signals", "reflex_closed": "reflex", "arena_drafted": "arena", "rule_adopted": "adopted",
}


def _detail(entry: LedgerEntry) -> dict[str, Any]:
    return entry.detail if isinstance(entry.detail, dict) else {}


def _today(entry: LedgerEntry, day: dt.date) -> bool:
    return entry.at.astimezone(ISTANBUL).date() == day


def _organ_row(
    organ: dict[str, Any], entries: Sequence[LedgerEntry], today: dt.date, stats: Stats,
    drafts: int, active_rules: int, verify: VerifyResult,
) -> dict[str, Any]:
    key = organ["key"]
    matches = list(entries) if key == "ledger" else [entry for entry in entries if entry.kind in organ["kinds"]]
    today_count = sum(_today(entry, today) for entry in matches)
    last = matches[-1].at.isoformat() if matches else None
    row = {
        "key": key, "name": organ["name"], "what": organ["what"],
        "state": "active" if today_count else "idle",
        "state_label": "bugün çalıştı" if today_count else "bugün boş",
        "today_count": today_count, "total_count": len(matches), "last_activity": last,
    }
    if key == "reflex":
        row["failed_today"] = sum(entry.kind == "reflex_failed" and _today(entry, today) for entry in matches)
    elif key == "approval":
        row["awaiting"] = stats.awaiting_approval
    elif key == "rules":
        row.update(drafts=drafts, active_rules=active_rules)
    elif key == "ledger":
        row.update(
            state="ok" if verify.ok else "broken",
            state_label="zincir sağlam" if verify.ok else "zincir kırık",
            entries=verify.entries, head_short=verify.head[:12],
        )
    return row


def _status_map(
    engine: NexusEngine, ledger_entries: Sequence[LedgerEntry], current_states: dict[str, SignalState],
    instant: dt.datetime, checked: VerifyResult,
) -> dict[str, dict[str, Any]]:
    stats = compute_stats(current_states.values(), instant)
    drafts = len(engine.drafts.drafts(current_states.values()))
    active_rules = len(engine.drafts.active_rules())
    today = instant.astimezone(ISTANBUL).date()
    return {
        organ["key"]: _organ_row(organ, ledger_entries, today, stats, drafts, active_rules, checked)
        for organ in ORGANS
    }


def organ_status(engine: NexusEngine, *, now: dt.datetime | None = None) -> dict[str, dict[str, Any]]:
    """Return seven ledger-backed organ rows keyed by organ, counting today in İstanbul time."""
    entries = engine.ledger.entries()
    states = replay(entries)
    instant = as_utc(now or system_clock())
    return _status_map(engine, entries, states, instant, engine.verify())


def _count_reflex_rule(entry: LedgerEntry, counts: Counter[str]) -> None:
    action = _detail(entry).get("action")
    rule_id = action.get("rule_id") if isinstance(action, dict) else None
    if not isinstance(rule_id, str):
        return
    if rule_id.startswith(BINDING_PREFIX):
        counts["bound_closed"] += 1
    match = LEARNED_RULE_ID.fullmatch(rule_id)
    if match and int(match.group(1)) >= FIRST_LEARNED_ID:
        counts["learned_closed"] += 1


def _count_human_approval(entry: LedgerEntry, counts: Counter[str]) -> None:
    action = _detail(entry).get("action")
    if isinstance(action, str) and action in {"approve", "edit"}:
        counts["approved"] += 1


def _loop_counts(engine: NexusEngine, entries: Sequence[LedgerEntry], states: dict[str, SignalState]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for entry in entries:
        stage = LOOP_KIND_STAGES.get(entry.kind)
        if stage:
            counts[stage] += 1
        if entry.kind == "reflex_closed":
            _count_reflex_rule(entry, counts)
        elif entry.kind == "approval":
            _count_human_approval(entry, counts)
    counts["drafts"] = len(engine.drafts.drafts(states.values()))
    return counts


def _learning_loop(engine: NexusEngine, ledger_entries: Sequence[LedgerEntry], states: dict[str, SignalState]) -> dict[str, Any]:
    counts = _loop_counts(engine, ledger_entries, states)
    empty = not ledger_entries
    return {
        "empty": empty,
        "stages": [{"key": key, "label": label, "count": None if empty else counts[key]} for key, label in LOOP_STAGES],
    }


def learning_loop(engine: NexusEngine) -> dict[str, Any]:
    """Count each learning-loop stage from the full ledger; use null only for an empty ledger."""
    entries = engine.ledger.entries()
    return _learning_loop(engine, entries, replay(entries))


def organs_payload(engine: NexusEngine, *, now: dt.datetime | None = None) -> dict[str, Any]:
    """Assemble the console response from one ledger snapshot without writing to it."""
    entries = engine.ledger.entries()
    states = replay(entries)
    instant = as_utc(now or system_clock())
    verified = engine.verify()
    organs = list(_status_map(engine, entries, states, instant, verified).values())
    metro_signals = sum(
        1 for entry in entries
        if entry.kind == "signal_received"
        and isinstance((signal := _detail(entry).get("signal")), dict)
        and isinstance(signal.get("kind"), str)
        and signal.get("kind") in METRO_SIGNAL_KINDS
    )
    return {
        "generated_at": instant.isoformat(), "empty": not entries, "metro_signals": metro_signals,
        "organs": organs, "loop": _learning_loop(engine, entries, states),
    }


def public_summary(engine: NexusEngine | None, *, now: dt.datetime | None = None) -> dict[str, Any] | None:
    """Return the identity-free organ map intended for the public how-it-works page."""
    if engine is None:
        return None
    payload = organs_payload(engine, now=now)
    return {
        "organs": [
            {key: row[key] for key in ("key", "name", "state", "state_label", "today_count")}
            for row in payload["organs"]
        ],
        "loop": [
            {key: stage[key] for key in ("key", "label", "count")}
            for stage in payload["loop"]["stages"]
        ],
        "ledger_ok": next(row["state"] == "ok" for row in payload["organs"] if row["key"] == "ledger"),
    }


def engine_of(request: Request) -> NexusEngine | None:
    """Find a wired engine while treating the unwired port's dynamic callables as absent."""
    ports = getattr(request.app.state, "ports", None)
    console = getattr(ports, "console", None)
    engine = getattr(console, "engine", None)
    return engine if isinstance(engine, NexusEngine) else None


@organs_routes.get("/organs")
async def console_organs(request: Request) -> Any:
    engine = engine_of(request)
    if engine is None:
        return port_problem(503, "not_wired", "Karar çekirdeği bu süreçte bağlı değil.")
    return await asyncio.to_thread(organs_payload, engine)
