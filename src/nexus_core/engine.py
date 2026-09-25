# Adapted from CloudSentinel app/actions.py (github.com/muratcan-ates/cloudsentinel @ 80938ae), MIT License,
# Copyright (c) 2026 CloudSentinel Team (YZTA Bootcamp 2026, Group 60). See NOTICE.md.
"""The engine: one signal in, a closed reflex or a card for a human out, every step sealed.

:meth:`NexusEngine.process` is the whole nervous system in one call:

1. seal the signal in the ledger (a signal seen before is not processed twice);
2. route it (``router.py``): a matching rule and no escalation trigger means reflex;
3. reflex: run the rule, seal the action, done; the console publishes the card. If the rule
   cannot run, seal the failure and go on to the Arena with ``reflex_failed``;
4. Arena: the seats give their opinions, a proposal is rendered from the rule's template (or a
   fixed fallback text), and the card is sealed ``awaiting_approval``.

:meth:`NexusEngine.decide` is the only way a card is settled, and it takes a human
:class:`~nexus_core.decisions.Approval`. Nothing in ``process`` ever approves.

The engine performs no I/O besides the ledger. Evidence and alternatives come from the caller
(the console, which has the İBB facade), so this package stays a library.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from nexus_core.approved import Binding, binding_of, find_binding, outage_of
from nexus_core.arena import DEFAULT_STALE_AFTER_S, ArenaPort, EvidenceItem, RuleBasedSeats
from nexus_core.decisions import (
    FINAL_STATUSES,
    Alternative,
    Approval,
    Decision,
    DecisionConflict,
    Status,
    published_text,
    settle,
)
from nexus_core.escalation import CRITICAL, REPEAT, Escalation
from nexus_core.ledger import EntryKind, Ledger, Trace, VerifyResult
from nexus_core.lifecycle import expire_cards
from nexus_core.missions import EscalationSettings, Mission
from nexus_core.processing import escalate_signal, run_binding, run_reflex
from nexus_core.proposals import default_evidence as default_evidence
from nexus_core.reflex import ReflexEngine
from nexus_core.results import ProcessResult
from nexus_core.router import RouteDecision, Router
from nexus_core.rule_drafts import RuleDrafts
from nexus_core.signals import Clock, Signal, system_clock
from nexus_core.state import SignalState, replay
from nexus_core.stats import Stats, compute_stats

__all__ = ["DecisionNotFound", "DecisionReceipt", "NexusEngine", "ProcessResult", "default_evidence"]


class DecisionNotFound(KeyError):
    """No Arena card for that signal id."""


class DecisionReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    signal_id: str
    status: Status
    ledger_entry_id: int
    published_text: str | None


class NexusEngine:
    """Processes signals and records rulings over one ledger and a set of missions."""

    def __init__(
        self,
        ledger: Ledger,
        missions: Sequence[Mission],
        *,
        arena: ArenaPort | None = None,
        clock: Clock = system_clock,
        stale_after_s: int = DEFAULT_STALE_AFTER_S,
        drafts: RuleDrafts | None = None,
        usd_per_call: float | None = None,
    ) -> None:
        if usd_per_call is not None and usd_per_call < 0:
            raise ValueError("usd_per_call must be non-negative")
        self.ledger = ledger
        self._clock = clock
        self.stale_after_s = stale_after_s
        self.usd_per_call = usd_per_call
        self.arena: ArenaPort = arena or RuleBasedSeats(stale_after_s=stale_after_s, clock=clock)
        self.drafts = drafts or RuleDrafts(ledger, clock=clock)
        settings = EscalationSettings.merged(m.escalation for m in missions)
        self.ttl_hours = settings.ttl_hours
        escalation = Escalation(settings, history=self._history)
        self.router = Router(missions, escalation, learned=self.drafts.active_rules, clock=clock)
        self.reflex = ReflexEngine()
        self._lock = threading.RLock()

    def _history(self, entity_id: str, since: dt.datetime) -> list[Signal]:
        signals = [
            Signal.model_validate(e.detail["signal"]) for e in self.ledger.entries(entity_id=entity_id, kinds=[EntryKind.SIGNAL])
        ]
        return [s for s in signals if s.observed_at >= since]

    # ------------------------------------------------------------------ writing
    def process(
        self,
        signal: Signal,
        evidence: Sequence[EvidenceItem] | None = None,
        alternatives: Sequence[Alternative] | None = None,
    ) -> ProcessResult:
        """Route one signal to a reflex or to a card for a human, sealing every step."""
        process_started = time.perf_counter()
        with self._lock:
            if self.ledger.has_signal(signal.signal_id):
                return self._existing(signal.signal_id)
            ids = {"signal_id": signal.signal_id, "entity_id": signal.entity_id}
            detail = {"signal": signal.model_dump(mode="json")}
            self.ledger.append(EntryKind.SIGNAL, actor=f"kaynak: {signal.provenance.source}", detail=detail, **ids)
            route = self.router.explain(signal)
            binding = self._binding(signal, route)
            if binding is not None:
                outcome: ProcessResult | RouteDecision = run_binding(self, signal, route, binding, ids, process_started)
            elif route.path == "reflex" and route.rule is not None:
                outcome = run_reflex(self, signal, route, route.rule, ids, process_started)
            else:
                outcome = route
            if isinstance(outcome, ProcessResult):
                return outcome
            return escalate_signal(self, signal, outcome, ids, evidence, alternatives, process_started)

    def _binding(self, signal: Signal, route: RouteDecision) -> Binding | None:
        """An approved alternative for this outage, unless an escalation trigger fired."""
        if outage_of(signal) is None or {CRITICAL, REPEAT} & set(route.reasons):
            return None
        return find_binding(self.states().values(), signal, self._clock())

    def decide(self, approval: Approval) -> DecisionReceipt:
        """Seal a human's ruling on a card. The only path from a draft to a published text."""
        if not isinstance(approval, Approval):
            raise TypeError("only a human Approval settles a decision")
        with self._lock:
            self.expire()
            state = self.states().get(approval.signal_id)
            if state is None:
                raise DecisionNotFound(approval.signal_id)
            if state.decision is None:
                # A rule closed it: settled, with nothing a person could rule on (the console's 409).
                if state.status in FINAL_STATUSES:
                    raise DecisionConflict(f"{approval.signal_id} is already {state.status}")
                raise DecisionNotFound(approval.signal_id)
            status = settle(state.status, approval)
            text = published_text(state.decision, approval)
            detail = {
                "action": approval.action,
                "status": status,
                "reason": approval.reason.strip(),
                "edited_text": approval.edited_text if approval.action == "edit" else None,
                "published_text": text,
                "actor": approval.actor.model_dump(),
            }
            ids = {"signal_id": approval.signal_id, "entity_id": state.signal.entity_id}
            entry = self.ledger.append(EntryKind.APPROVAL, actor=approval.actor.label, detail=detail, **ids)
            return DecisionReceipt(signal_id=approval.signal_id, status=status, ledger_entry_id=entry.id, published_text=text)

    # ------------------------------------------------------------------ reading
    def states(self) -> dict[str, SignalState]:
        return replay(self.ledger.entries())

    def _existing(self, signal_id: str) -> ProcessResult:
        state = self.states()[signal_id]
        return ProcessResult(
            signal_id=signal_id,
            path=state.path or "arena",
            status=state.status if state.status != "received" else "awaiting_approval",
            rule_id=state.rule_id,
            reasons=state.reasons,
            action=state.action,
            decision=state.decision,
            reflex_ms=state.reflex_ms,
            receipt=state.receipt,
            duplicate=True,
        )

    def expire(self, now: dt.datetime | None = None) -> list[str]:
        """Seal expired unanswered cards; a deferred card remains a human-owned choice."""
        with self._lock:
            return expire_cards(self.ledger, self.states().values(), self.ttl_hours, now or self._clock())

    def bindings(self) -> list[Binding]:
        """Active approved alternatives (OA), newest first: what earns the "operatör onaylı" badge."""
        now = self._clock()
        found = [b for state in self.states().values() if (b := binding_of(state)) is not None and b.is_active(now)]
        return sorted(found, key=lambda b: b.approved_at, reverse=True)

    def decision(self, signal_id: str) -> Decision:
        state = self.states().get(signal_id)
        if state is None or state.decision is None:
            raise DecisionNotFound(signal_id)
        return state.decision

    def stats(self) -> Stats:
        return compute_stats(self.states().values(), self._clock())

    def trace(self, signal_id: str) -> Trace:
        return self.ledger.trace(signal_id)

    def verify(self) -> VerifyResult:
        return self.ledger.verify()
