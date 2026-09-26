"""``/api/console/rules``: every rule NEXUS knows, in Turkish, and the operator's way to revoke a learned one.

The registry is read, never written, from two places the core already owns: the mission files
(``R-01`` ... through :attr:`nexus_core.router.Router.missions`) and the learned rules a person
adopted (``R-101`` ... through :meth:`nexus_core.rule_drafts.RuleDrafts.adopted`). The order is
the router's own: learned rules first, then the missions' rules in file order, so the first card
on the page is the first rule a signal is tried against. Approved-alternative bindings
(``OA-...``) are one outage's approved text, not rules, and are not listed.

Counts come from the ledger, per rule and per Istanbul day, never per person: how many signals a
rule matched today (``routed``) and how many of them it closed by itself (``reflex_closed``).

Revoking is the only write, and only for a learned rule that is still active: a mission rule
changes when its mission file is reviewed, not from a button. The core seals ``rule_revoked``;
this module checks the state first so the page gets a Turkish reason for each refusal.

Import direction: :mod:`nabiz.console.nexus_port` imports this module, never the reverse; the
signal kinds' Turkish names come in as ``kind_names``.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel, Field

from nabiz.console.operator import ID_PATTERN, console_port, port_answer, port_problem
from nabiz.console.ports import OPERATOR, PortConflict
from nexus_core import NexusEngine, Operator
from nexus_core.decisions import REASON_MAX
from nexus_core.ledger import EntryKind, LedgerEntry
from nexus_core.missions import ACTION_CATALOG, Condition, Mission, MissionRule
from nexus_core.rule_drafts import AdoptedRule
from nexus_core.signals import as_utc
from nexus_core.stats import ISTANBUL

#: A rule not reviewed for longer than this is shown as stale. A design parameter, not a measured value.
STALE_AFTER_DAYS = 7

FIELD_TR = {
    "equipment_type": "ekipman türü", "alternative_station": "alternatif istasyon", "alternative_line": "alternatif hat",
    "station": "istasyon", "extra_minutes": "ek dakika", "text": "uyarı metni", "source": "kaynak",
    "fault_count": "arıza sayısı", "outage_hours": "arıza süresi (saat)", "report_text": "bildirim metni",
}  # fmt: skip
VALUE_TR = {"elevator": "asansör", "escalator": "yürüyen merdiven", "metro_equipment": "Metro İstanbul arıza kaydı"}
PATH_TR = {"reflex": "refleks", "arena": "insan onayı"}

#: The first letter of a catalog text in the middle of a sentence. ``str.lower`` would turn "İ"
#: into "i̇" (i plus a combining dot); these two are the Turkish pairs, anything else non-ASCII stays.
_FIRST_LOWER = {"İ": "i", "I": "ı"}

_OPS = {
    "eq": "{f} {v}", "ne": "{f} {v} değil", "in": "{f} şunlardan biri: {v}", "not_in": "{f} şunlardan biri değil: {v}",
    "gt": "{f} {v} üstünde", "gte": "{f} en az {v}", "lt": "{f} {v} altında", "lte": "{f} en çok {v}",
    "present": "{f} bilgisi var", "absent": "{f} bilgisi yok", "true": "{f} evet", "false": "{f} hayır",
}  # fmt: skip


def _value_text(value: Any) -> str:
    if isinstance(value, tuple):
        return ", ".join(_value_text(v) for v in value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return VALUE_TR.get(value, str(value)) if isinstance(value, str) else str(value)


def condition_text(condition: Condition) -> str:
    """One condition as Turkish words; a field or value the tables do not know is shown as it is."""
    return _OPS[condition.op].format(f=FIELD_TR.get(condition.field, condition.field), v=_value_text(condition.value))


def _lower_first(text: str) -> str:
    if not text:
        return text
    first = text[0]
    first = _FIRST_LOWER.get(first, first.lower() if first.isascii() else first)
    return first + text[1:]


def rule_sentence(rule: MissionRule, kind_names: Mapping[str, str]) -> str:
    """The rule as one "Eğer ... ise: ..." sentence; on the human path it says so, never publishing alone."""
    kind = kind_names.get(rule.when.kind, rule.when.kind)
    action = ACTION_CATALOG.get(rule.then.action, rule.then.action)
    if rule.path == "arena":
        action = "insan onayıyla " + _lower_first(action)
    if not rule.when.conditions:
        return f"Eğer {kind} sinyali gelirse: {action}."
    conditions = " ve ".join(condition_text(c) for c in rule.when.conditions)
    return f"Eğer {kind} sinyalinde {conditions} ise: {action}."


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _status(rule: MissionRule, revoked_at: dt.datetime | None, now: dt.datetime) -> str:
    if revoked_at is not None:
        return "revoked"
    if rule.valid_from is not None and rule.valid_from > now:
        return "not_started"
    if rule.expires_at is not None and now >= rule.expires_at:
        return "expired"
    return "active"


def _clock_fields(rule: MissionRule, status: str, reviewed_at: dt.datetime | None, now: dt.datetime) -> dict[str, Any]:
    expires_at = rule.expires_at
    days_left = int((expires_at - now).total_seconds() // 86400) if status == "active" and expires_at else None
    age = now - reviewed_at if reviewed_at is not None else None
    return {
        "valid_from": _iso(rule.valid_from),
        "expires_at": _iso(expires_at),
        "days_left": days_left,
        "reviewed_at": _iso(reviewed_at),
        "age_days": int(age.total_seconds() // 86400) if age is not None else None,
        "stale": age is not None and age > dt.timedelta(days=STALE_AFTER_DAYS),
    }


class _Ledgered:
    """What the registry reads from the ledger in one pass: today's counts and the adoption details."""

    def __init__(self, entries: list[LedgerEntry], now: dt.datetime) -> None:
        today = now.astimezone(ISTANBUL).date()
        self.matched: dict[str, int] = {}
        self.reflex: dict[str, int] = {}
        self.adopted: dict[str, dict[str, Any]] = {}
        self.revoked: dict[str, dict[str, Any]] = {}
        for entry in entries:
            detail = entry.detail
            if entry.kind == EntryKind.RULE_ADOPTED:
                self.adopted[detail.get("rule_id", "")] = detail
            elif entry.kind == EntryKind.RULE_REVOKED:
                self.revoked[detail.get("rule_id", "")] = detail
            elif entry.at.astimezone(ISTANBUL).date() != today:
                continue
            elif entry.kind == EntryKind.ROUTED and (rule_id := detail.get("rule_id")):
                self.matched[rule_id] = self.matched.get(rule_id, 0) + 1
            elif entry.kind == EntryKind.REFLEX_CLOSED and (rule_id := (detail.get("action") or {}).get("rule_id")):
                self.reflex[rule_id] = self.reflex.get(rule_id, 0) + 1


def _base(rule: MissionRule, kind_names: Mapping[str, str], counts: _Ledgered) -> dict[str, Any]:
    return {
        "rule_id": rule.id,
        "path": rule.path,
        "path_label": PATH_TR.get(rule.path, rule.path),
        "sentence": rule_sentence(rule, kind_names),
        "when": {"kind": rule.when.kind, "conditions": [c.model_dump(mode="json") for c in rule.when.conditions]},
        "then": {"action": rule.then.action, "action_label": ACTION_CATALOG.get(rule.then.action, rule.then.action)},
        "matched_today": counts.matched.get(rule.id, 0),
        "reflex_today": counts.reflex.get(rule.id, 0),
    }


def _learned_row(adopted: AdoptedRule, now: dt.datetime, kind_names: Mapping[str, str], counts: _Ledgered) -> dict[str, Any]:
    rule = adopted.rule
    status = _status(rule, adopted.revoked_at, now)
    adoption = counts.adopted.get(adopted.rule_id, {})
    evidence = adoption.get("evidence_decisions")
    return {
        **_base(rule, kind_names, counts),
        "origin": "learned",
        "mission": None,
        "status": status,
        **_clock_fields(rule, status, adopted.adopted_at, now),
        "revocable": status == "active",
        "draft_id": adopted.draft_id,
        "adopted_reason": adoption.get("reason", adopted.reason),
        "evidence_count": len(evidence) if isinstance(evidence, list) else None,
        "revoked_at": _iso(adopted.revoked_at),
        "revoke_reason": counts.revoked.get(adopted.rule_id, {}).get("reason") if adopted.revoked_at else None,
    }


def _mission_row(
    mission: Mission, rule: MissionRule, now: dt.datetime, kind_names: Mapping[str, str], counts: _Ledgered
) -> dict[str, Any]:
    status = _status(rule, None, now)
    reviewed_at = rule.valid_from
    if reviewed_at is None and mission.reviewed_on is not None:
        reviewed_at = dt.datetime.combine(mission.reviewed_on, dt.time(0), tzinfo=dt.UTC)
    return {
        **_base(rule, kind_names, counts),
        "origin": "mission",
        "mission": {"id": mission.id, "title": mission.title, "source": mission.source},
        "status": status,
        **_clock_fields(rule, status, reviewed_at, now),
        "revocable": False,
        "draft_id": None,
        "adopted_reason": None,
        "evidence_count": None,
        "revoked_at": None,
        "revoke_reason": None,
    }


def rule_registry(engine: NexusEngine, now: dt.datetime, *, kind_names: Mapping[str, str]) -> dict[str, Any]:
    """Every rule, learned ones first (adoption order), then the missions' rules in file order."""
    now = as_utc(now)
    kinds = [EntryKind.ROUTED, EntryKind.REFLEX_CLOSED, EntryKind.RULE_ADOPTED, EntryKind.RULE_REVOKED]
    counts = _Ledgered(engine.ledger.entries(kinds=kinds), now)
    learned = [_learned_row(a, now, kind_names, counts) for a in engine.drafts.adopted()]
    missions = [_mission_row(m, r, now, kind_names, counts) for m in engine.router.missions for r in m.rules]
    rules = learned + missions
    return {
        "rules": rules,
        "counts": {
            "mission": len(missions),
            "learned": len(learned),
            "active": sum(1 for r in rules if r["status"] == "active"),
        },
        "stale_after_days": STALE_AFTER_DAYS,
        "generated_at": now.isoformat(),
    }


def revoke_learned(engine: NexusEngine, rule_id: str, reason: str, now: dt.datetime) -> dict[str, Any]:
    """Stop one active learned rule; the core seals ``rule_revoked``. Refusals follow the port's error contract."""
    if any(rule.id == rule_id for mission in engine.router.missions for rule in mission.rules):
        raise PortConflict("Görev dosyasındaki kural buradan geri alınmaz; görev dosyası gözden geçirilerek değişir.")
    adopted = next((a for a in engine.drafts.adopted() if a.rule_id == rule_id), None)
    if adopted is None:
        raise KeyError(rule_id)
    if adopted.revoked_at is not None:
        raise PortConflict("Bu kural zaten geri alınmış.")
    if not adopted.is_active(as_utc(now)):
        raise PortConflict("Bu kuralın süresi dolmuş; geri alınacak bir şey yok.")
    engine.drafts.revoke(rule_id, reason, Operator())
    entry = engine.ledger.entries(kinds=[EntryKind.RULE_REVOKED])[-1]
    return {"rule_id": rule_id, "status": "revoked", "revoked_at": entry.at.isoformat(), "ledger_entry_id": entry.id}


rules_routes = APIRouter(prefix="/api/console")


class RevokeBody(BaseModel):
    reason: str = Field(default="", max_length=REASON_MAX)


@rules_routes.get("/rules")
async def console_rules(request: Request):
    return await port_answer(console_port(request).rules())


@rules_routes.post("/rules/{rule_id}/revoke")
async def console_revoke_rule(request: Request, body: RevokeBody, rule_id: str = Path(pattern=ID_PATTERN)):
    reason = body.reason.strip()
    if not reason:
        return port_problem(400, "reason_required", "Kuralı geri almak için gerekçe zorunlu.")
    return await port_answer(console_port(request).revoke_rule(rule_id, reason=reason, actor=OPERATOR))
