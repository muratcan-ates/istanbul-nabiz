"""Decisions and approvals: the card the Arena drafts, and the human act that settles it.

A :class:`Decision` is a draft waiting for a person: the evidence, the alternatives, the
seats' opinions, the dissent, the proposed action and a rule-computed confidence. It is data,
and nothing in it can change its own status.

An :class:`Approval` is the only thing that settles a decision, and it can only be made by a
human at the console. That is structural, not a convention:

* :class:`Approval` requires an :class:`Operator` actor, whose ``kind`` can only be ``"human"``;
  an actor claiming to be a model or an agent fails validation.
* the Arena port sees the signal and the evidence, never the engine, the ledger or this module
  (``arena.ArenaPort``); the engine's ``process()`` only ever leaves an Arena card
  ``awaiting_approval``, whatever the seats say.
* only ``engine.decide()`` records a ruling, and it takes an :class:`Approval`, nothing else.

Friction is symmetric where it matters: rejecting and deferring need a written reason; editing
needs the edited text. A second ruling on a settled card is a :class:`DecisionConflict` (the
console's 409); a deferred card can still be decided.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nexus_core.arena import Author, Confidence, EvidenceItem, Opinion
from nexus_core.missions import ACTION_CATALOG

Status = Literal["closed_by_reflex", "awaiting_approval", "approved", "rejected", "deferred"]
ApprovalAction = Literal["approve", "edit", "reject", "defer"]

#: Settled: no further ruling. A deferred card goes back to the queue and can still be decided.
FINAL_STATUSES = frozenset({"closed_by_reflex", "approved", "rejected"})
REASON_MAX = 280
#: The longest text a card publishes (a proposal or a person's edit).
PROPOSAL_MAX = 600
OPERATOR_ROLE = "Simüle operatör"
STATUS_BY_ACTION: dict[str, Status] = {"approve": "approved", "edit": "approved", "reject": "rejected", "defer": "deferred"}
#: Every card offers doing nothing, so approving is never the only way to clear the queue.
DO_NOTHING = ("D · Hiçbir şey yapma", "Kart yayımlanmaz; sinyal defterde kalır. Sonraki sinyal yeniden değerlendirilir.")


class DecisionConflict(Exception):
    """A ruling on a card that is already settled (approved, rejected or closed by a reflex)."""


class Alternative(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str = Field(min_length=1, max_length=120)
    detail: str = Field(min_length=1, max_length=600)


class ProposedAction(BaseModel):
    """What happens if the human approves: a catalog action and the exact text it publishes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    text: str = Field(min_length=1, max_length=PROPOSAL_MAX)
    expires_at: dt.datetime | None = None
    #: The rule template the text came from; ``None`` for a fallback text. Rule drafts need it.
    template: str | None = None

    @field_validator("kind")
    @classmethod
    def _in_catalog(cls, value: str) -> str:
        if value not in ACTION_CATALOG:
            raise ValueError(f"action {value!r} is not in the reflex catalog")
        return value


class Decision(BaseModel):
    """The Arena's card for one escalated signal, waiting for a human."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signal_id: str
    rule_id: str | None = None
    reasons: tuple[str, ...] = ()
    evidence: tuple[EvidenceItem, ...] = ()
    alternatives: tuple[Alternative, ...] = ()
    opinions: tuple[Opinion, ...] = ()
    dissent_summary: str
    proposed_action: ProposedAction
    confidence: Confidence
    author: Author
    arena_label: str
    created_at: dt.datetime

    def freshness_s(self, now: dt.datetime) -> int | None:
        """Age of the stalest evidence item with a known time; the card's worst case."""
        ages = [age for item in self.evidence if (age := item.provenance.age_s(now)) is not None]
        return max(ages) if ages else None


class Operator(BaseModel):
    """A person at the console. In the prototype, the simulated operator."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["human"] = "human"
    handle: str = Field(default="simule-operator", pattern=r"^[a-z0-9][a-z0-9._-]{0,39}$")
    role: str = OPERATOR_ROLE

    @property
    def label(self) -> str:
        return f"{self.role} ({self.handle})"


class Approval(BaseModel):
    """A human's ruling on one card: approve, approve with an edit, reject or defer.

    It carries no time: the ledger stamps the moment it seals the ruling.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    signal_id: str = Field(min_length=1)
    action: ApprovalAction
    reason: str = Field(default="", max_length=REASON_MAX)
    edited_text: str | None = Field(default=None, max_length=PROPOSAL_MAX)
    actor: Operator

    @model_validator(mode="after")
    def _friction(self) -> Approval:
        if self.action in ("reject", "defer") and not self.reason.strip():
            raise ValueError(f"{self.action} needs a written reason")
        if self.action == "edit" and not (self.edited_text or "").strip():
            raise ValueError("edit needs the edited text")
        if self.action != "edit" and (self.edited_text or "").strip():
            raise ValueError("edited_text is only for an edit")
        return self

    @property
    def status(self) -> Status:
        return STATUS_BY_ACTION[self.action]


def settle(current: str, approval: Approval) -> Status:
    """The status after ``approval``; a settled card raises :class:`DecisionConflict`."""
    if current in FINAL_STATUSES:
        raise DecisionConflict(f"{approval.signal_id} is already {current}")
    return approval.status


def published_text(decision: Decision, approval: Approval) -> str | None:
    """What the citizen face shows after the ruling: the proposal, the human's edit, or nothing."""
    if approval.action == "edit":
        return approval.edited_text
    if approval.action == "approve":
        return decision.proposed_action.text
    return None
