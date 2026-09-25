"""Rule drafts: a decision people keep approving becomes a proposed reflex rule, never a rule.

The learning loop, in three steps, each one a human act or a count of human acts:

1. **Draft.** When the same pattern (signal kind, equipment type, proposed action) has been
   approved at least ``min_approvals`` times within ``window_days`` and rejected not once in
   that window, the machine writes a TOML draft of a reflex rule from the proposal's template.
   One event never makes a rule (the anti-overfitting principle): two approvals are a
   coincidence, three in thirty days are a pattern worth a person's look. An edited approval
   counts, but the draft keeps the rule's own template: the edits are one-off texts, and the
   decisions listed with the draft show them to the person deciding whether to adopt it.
2. **Adopt.** A person adopts the draft with a written reason. The rule gets an id
   (``R-101``, ``R-102``, ...), starts now and expires after ``expires_days``; the adoption is
   sealed in the ledger with the decisions it came from. Nothing adopts automatically.
3. **Revoke.** A person can withdraw an adopted rule at any time, with a reason. An expired or
   revoked rule does not come back by itself; the pattern must earn a new draft.

Adopted rules are read back from the ledger on every route (:meth:`RuleDrafts.active_rules`),
so the rule the router uses is always the one the ledger says a person adopted.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import tomllib
from collections import Counter
from collections.abc import Iterable, Sequence

from pydantic import BaseModel, ConfigDict

from nexus_core.decisions import REASON_MAX, Operator
from nexus_core.ledger import EntryKind, Ledger
from nexus_core.missions import MissionRule, parse_rules, template_fields
from nexus_core.reflex import SIGNAL_FIELDS
from nexus_core.signals import Clock, system_clock
from nexus_core.state import SignalState, replay

MIN_APPROVALS = 3
WINDOW_DAYS = 30
EXPIRES_DAYS = 30
FIRST_LEARNED_ID = 101


class DraftNotFound(KeyError):
    """No current draft with that id (it never existed, or no longer qualifies)."""


class Pattern(BaseModel):
    """What makes two decisions "the same kind of decision"."""

    model_config = ConfigDict(frozen=True)

    kind: str
    equipment_type: str | None
    action: str

    @property
    def text(self) -> str:
        return " · ".join(part for part in (self.kind, self.equipment_type, self.action) if part)


class RuleDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    draft_id: str
    pattern: Pattern
    evidence_decisions: tuple[str, ...]
    template: str
    proposed_rule_toml: str
    expires_days: int


class AdoptedRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_id: str
    draft_id: str
    adopted_at: dt.datetime
    expires_at: dt.datetime
    reason: str
    rule: MissionRule
    revoked_at: dt.datetime | None = None

    def is_active(self, now: dt.datetime) -> bool:
        return self.revoked_at is None and self.rule.is_active(now)


def pattern_of(state: SignalState) -> Pattern | None:
    if state.decision is None:
        return None
    equipment = state.signal.payload.get("equipment_type")
    return Pattern(
        kind=state.signal.kind,
        equipment_type=equipment if isinstance(equipment, str) else None,
        action=state.decision.proposed_action.kind,
    )


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{k} = {_toml_value(v)}" for k, v in value.items()) + " }"
    if isinstance(value, dt.datetime):
        return value.isoformat()
    # A JSON string is a valid TOML basic string (same quotes and escapes), except that TOML
    # also forbids a raw DEL, which JSON leaves alone.
    return json.dumps(str(value), ensure_ascii=False).replace("\x7f", "\\u007f")


def rule_toml(rule_id: str, pattern: Pattern, template: str, expires_days: int, valid_from: dt.datetime | None = None) -> str:
    """A ``[[rules]]`` table for the pattern. Every field the card needs is a ``present`` condition."""
    conditions: list[dict[str, object]] = []
    if pattern.equipment_type:
        conditions.append({"field": "equipment_type", "op": "eq", "value": pattern.equipment_type})
    needed = [name for name in dict.fromkeys(template_fields(template)) if name not in SIGNAL_FIELDS]
    conditions += [{"field": name, "op": "present"} for name in needed]
    lines = ["[[rules]]", f"id = {_toml_value(rule_id)}", 'path = "reflex"', f"expires_days = {expires_days}"]
    if valid_from is not None:
        lines.append(f"valid_from = {_toml_value(valid_from)}")
    else:
        # A draft does not run; its clock starts when a person adopts it.
        lines.append("# valid_from: kural benimsendiği an yazılır")
    lines += ["[rules.when]", f"kind = {_toml_value(pattern.kind)}", f"conditions = {_toml_value(conditions)}"]
    lines += ["[rules.then]", f"action = {_toml_value(pattern.action)}", f"card_template = {_toml_value(template)}"]
    return "\n".join(lines) + "\n"


def parse_rule_toml(text: str) -> MissionRule:
    (rule,) = parse_rules(tomllib.loads(text)["rules"])
    return rule


def _draft_id(pattern: Pattern, template: str) -> str:
    return "draft-" + hashlib.sha256(f"{pattern.text}|{template}".encode()).hexdigest()[:10]


class RuleDrafts:
    """Finds drafts in the ledger, and records adoptions and revocations in it."""

    def __init__(
        self,
        ledger: Ledger,
        *,
        clock: Clock = system_clock,
        min_approvals: int = MIN_APPROVALS,
        window_days: int = WINDOW_DAYS,
        expires_days: int = EXPIRES_DAYS,
    ) -> None:
        self.ledger = ledger
        self._clock = clock
        self.min_approvals = min_approvals
        self.window = dt.timedelta(days=window_days)
        self.expires_days = expires_days

    def drafts(self, states: Iterable[SignalState] | None = None) -> list[RuleDraft]:
        """Patterns approved often enough, never rejected in the window, with no active rule yet."""
        now = self._clock()
        states = list(states) if states is not None else list(replay(self.ledger.entries()).values())
        covered = {r.draft_id for r in self.adopted() if r.is_active(now)}
        approved, rejected = self._rulings_in_window(states, now - self.window)
        drafts = []
        for pattern, decided in approved.items():
            if pattern in rejected or len(decided) < self.min_approvals:
                continue
            template = Counter(s.decision.proposed_action.template for s in decided if s.decision).most_common(1)[0][0]
            draft_id = _draft_id(pattern, template)
            if draft_id in covered:
                continue
            evidence = tuple(s.signal.signal_id for s in decided)
            toml_text = rule_toml(draft_id, pattern, template, self.expires_days)
            drafts.append(
                RuleDraft(
                    draft_id=draft_id,
                    pattern=pattern,
                    evidence_decisions=evidence,
                    template=template,
                    proposed_rule_toml=toml_text,
                    expires_days=self.expires_days,
                )
            )
        return drafts

    @staticmethod
    def _rulings_in_window(
        states: Sequence[SignalState], since: dt.datetime
    ) -> tuple[dict[Pattern, list[SignalState]], set[Pattern]]:
        approved: dict[Pattern, list[SignalState]] = {}
        rejected: set[Pattern] = set()
        for state in states:
            pattern = pattern_of(state)
            ruling = state.rulings[-1] if state.rulings else None  # the ruling that set the status
            if pattern is None or ruling is None or ruling.at < since or state.decision is None:
                continue
            if state.status == "rejected":
                rejected.add(pattern)
            elif state.status == "approved" and state.decision.proposed_action.template:
                approved.setdefault(pattern, []).append(state)
        return approved, rejected

    def adopt(self, draft_id: str, reason: str, actor: Operator) -> AdoptedRule:
        """A person turns a current draft into a time-bound reflex rule."""
        reason = _required(reason, "adopting a rule")
        draft = next((d for d in self.drafts() if d.draft_id == draft_id), None)
        if draft is None:
            raise DraftNotFound(draft_id)
        now = self._clock()
        rule_id = f"R-{FIRST_LEARNED_ID + len(self.ledger.entries(kinds=[EntryKind.RULE_ADOPTED]))}"
        text = rule_toml(rule_id, draft.pattern, draft.template, draft.expires_days, valid_from=now)
        rule = parse_rule_toml(text)
        detail = {
            "rule_id": rule_id,
            "draft_id": draft_id,
            "rule_toml": text,
            "reason": reason,
            "evidence_decisions": list(draft.evidence_decisions),
            "expires_at": rule.expires_at.isoformat() if rule.expires_at else None,
            "actor": actor.model_dump(),
        }
        entry = self.ledger.append(EntryKind.RULE_ADOPTED, actor=actor.label, detail=detail)
        return AdoptedRule(
            rule_id=rule_id, draft_id=draft_id, adopted_at=entry.at, expires_at=rule.expires_at or now, reason=reason, rule=rule
        )

    def revoke(self, rule_id: str, reason: str, actor: Operator) -> None:
        """A person withdraws an adopted rule. It stops matching at once and does not come back."""
        reason = _required(reason, "revoking a rule")
        if rule_id not in {r.rule_id for r in self.adopted() if r.revoked_at is None}:
            raise KeyError(rule_id)
        detail = {"rule_id": rule_id, "reason": reason, "actor": actor.model_dump()}
        self.ledger.append(EntryKind.RULE_REVOKED, actor=actor.label, detail=detail)

    def adopted(self) -> list[AdoptedRule]:
        """Every adoption in the ledger, with its revocation if there was one."""
        rules: dict[str, AdoptedRule] = {}
        for entry in self.ledger.entries(kinds=[EntryKind.RULE_ADOPTED, EntryKind.RULE_REVOKED]):
            detail = entry.detail
            if entry.kind == EntryKind.RULE_ADOPTED:
                rule = parse_rule_toml(detail["rule_toml"])
                rules[rule.id] = AdoptedRule(
                    rule_id=rule.id,
                    draft_id=detail["draft_id"],
                    adopted_at=entry.at,
                    expires_at=rule.expires_at or entry.at,
                    reason=detail["reason"],
                    rule=rule,
                )
            elif detail["rule_id"] in rules:
                rules[detail["rule_id"]] = rules[detail["rule_id"]].model_copy(update={"revoked_at": entry.at})
        return list(rules.values())

    def active_rules(self) -> list[MissionRule]:
        """The adopted rules the router may use right now."""
        now = self._clock()
        return [r.rule for r in self.adopted() if r.is_active(now)]


def _required(reason: str, what: str) -> str:
    text = (reason or "").strip()
    if not text:
        raise ValueError(f"{what} needs a written reason")
    if len(text) > REASON_MAX:
        raise ValueError(f"reason is longer than {REASON_MAX} characters")
    return text
