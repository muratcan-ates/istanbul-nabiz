# Adapted from CloudSentinel app/actions.py (github.com/muratcan-ates/cloudsentinel @ 80938ae), MIT License,
# Copyright (c) 2026 CloudSentinel Team (YZTA Bootcamp 2026, Group 60). See NOTICE.md.
"""Replay: every signal's current state, read back from the ledger and nothing else.

The ledger is the only record. The queue, a decision card, the stats and the rule drafts are
all computed by folding its entries in chain order, so what the console shows is always what
was sealed, and yesterday's state is the same fold stopped earlier (the "time machine").
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from nexus_core.decisions import Decision, Operator, Status
from nexus_core.ledger import EntryKind, LedgerEntry
from nexus_core.receipts import RunReceipt
from nexus_core.reflex import Action
from nexus_core.signals import Signal


class Ruling(BaseModel):
    """A human's recorded ruling on a card, as the ledger sealed it."""

    model_config = ConfigDict(frozen=True)

    entry_id: int
    at: dt.datetime
    action: str
    status: Status
    reason: str
    edited_text: str | None
    published_text: str | None
    actor: Operator


class SignalState(BaseModel):
    """Everything the ledger says about one signal so far."""

    model_config = ConfigDict(frozen=False)

    signal: Signal
    received_at: dt.datetime
    path: Literal["reflex", "arena"] | None = None
    rule_id: str | None = None
    reasons: tuple[str, ...] = ()
    repeats: int = 1
    status: Status | Literal["received"] = "received"
    action: Action | None = None
    reflex_ms: float | None = None
    reflex_failure: str | None = None
    closed_at: dt.datetime | None = None
    decision: Decision | None = None
    receipt: RunReceipt | None = None
    drafted_at: dt.datetime | None = None
    expired_at: dt.datetime | None = None
    rulings: list[Ruling] = []

    @property
    def first_ruling(self) -> Ruling | None:
        return self.rulings[0] if self.rulings else None

    @property
    def published_at(self) -> dt.datetime | None:
        """When the citizen face got this signal's text: the reflex, or the first approving ruling."""
        if self.closed_at is not None:
            return self.closed_at
        return next((r.at for r in self.rulings if r.status == "approved"), None)


def _routed(state: SignalState, entry: LedgerEntry) -> None:
    detail = entry.detail
    state.path = detail["path"]
    state.rule_id = detail.get("rule_id")
    state.reasons = tuple(detail.get("reasons", ()))
    state.repeats = detail.get("repeats", 1)


def _reflex_closed(state: SignalState, entry: LedgerEntry) -> None:
    state.action = Action.model_validate(entry.detail["action"])
    state.reflex_ms = entry.detail.get("elapsed_ms")
    state.closed_at = entry.at
    if entry.detail.get("receipt") is not None:
        state.receipt = RunReceipt.model_validate(entry.detail["receipt"])
    state.status = "closed_by_reflex"


def _reflex_failed(state: SignalState, entry: LedgerEntry) -> None:
    state.reflex_failure = entry.detail.get("failure")
    state.reflex_ms = entry.detail.get("elapsed_ms")


def _arena_drafted(state: SignalState, entry: LedgerEntry) -> None:
    state.decision = Decision.model_validate(entry.detail["decision"])
    state.receipt = state.decision.receipt
    state.drafted_at = entry.at
    state.status = "awaiting_approval"


def _expired(state: SignalState, entry: LedgerEntry) -> None:
    state.expired_at = entry.at
    state.status = "expired"


def _approval(state: SignalState, entry: LedgerEntry) -> None:
    detail: dict[str, Any] = entry.detail
    ruling = Ruling(
        entry_id=entry.id,
        at=entry.at,
        action=detail["action"],
        status=detail["status"],
        reason=detail.get("reason", ""),
        edited_text=detail.get("edited_text"),
        published_text=detail.get("published_text"),
        actor=Operator.model_validate(detail["actor"]),
    )
    state.rulings.append(ruling)
    state.status = ruling.status


_FOLD: dict[str, Callable[[SignalState, LedgerEntry], None]] = {
    EntryKind.ROUTED: _routed,
    EntryKind.REFLEX_CLOSED: _reflex_closed,
    EntryKind.REFLEX_FAILED: _reflex_failed,
    EntryKind.ARENA_DRAFTED: _arena_drafted,
    EntryKind.APPROVAL: _approval,
    EntryKind.EXPIRED: _expired,
}


def replay(entries: Iterable[LedgerEntry]) -> dict[str, SignalState]:
    """Signal id to state, in the order the signals arrived. Entries without a signal are skipped."""
    states: dict[str, SignalState] = {}
    for entry in entries:
        if entry.signal_id is None:
            continue
        if entry.kind == EntryKind.SIGNAL:
            signal = Signal.model_validate(entry.detail["signal"])
            states[entry.signal_id] = SignalState(signal=signal, received_at=entry.at)
            continue
        state = states.get(entry.signal_id)
        handler = _FOLD.get(entry.kind)
        if state is not None and handler is not None:
            handler(state, entry)
    return states
