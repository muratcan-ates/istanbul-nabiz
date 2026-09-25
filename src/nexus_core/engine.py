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
from typing import Literal

from pydantic import BaseModel, ConfigDict

from nexus_core.approved import (
    APPROVED_BINDING,
    BINDING_CHECK_FAILED,
    BOUND_ACTION,
    Binding,
    binding_of,
    find_binding,
    outage_of,
    revalidate,
)
from nexus_core.arena import DEFAULT_STALE_AFTER_S, ArenaPort, EvidenceItem, RuleBasedSeats, convene
from nexus_core.decisions import (
    DO_NOTHING,
    Alternative,
    Approval,
    Decision,
    ProposedAction,
    Status,
    published_text,
    settle,
)
from nexus_core.escalation import CRITICAL, REFLEX_FAILED, REPEAT, Escalation
from nexus_core.ledger import EntryKind, Ledger, Trace, VerifyResult
from nexus_core.missions import EscalationSettings, Mission, MissionRule
from nexus_core.reflex import Action, CardDraft, MissingField, ReflexEngine, render, signal_values
from nexus_core.router import RouteDecision, Router
from nexus_core.rule_drafts import RuleDrafts
from nexus_core.signals import Clock, Signal, system_clock
from nexus_core.state import SignalState, replay
from nexus_core.stats import Stats, compute_stats

ROUTER_ACTOR = "yönlendirici"
PROPOSAL_DAYS = 30


class DecisionNotFound(KeyError):
    """No Arena card for that signal id."""


class ProcessResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    signal_id: str
    path: Literal["reflex", "arena"]
    status: Status
    rule_id: str | None = None
    reasons: tuple[str, ...] = ()
    action: Action | None = None
    decision: Decision | None = None
    reflex_ms: float | None = None
    duplicate: bool = False


class DecisionReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    signal_id: str
    status: Status
    ledger_entry_id: int
    published_text: str | None


def default_evidence(signal: Signal) -> tuple[EvidenceItem, ...]:
    """The signal itself as the one piece of evidence, with its own provenance."""
    where = signal.payload.get("station") or signal.entity_id
    return (EvidenceItem(text=f"{signal.title}: {where}", provenance=signal.provenance),)


def default_alternatives(proposal: ProposedAction) -> list[Alternative]:
    return [
        Alternative(label="A · Önerilen metni yayımla", detail=proposal.text),
        Alternative(label="C · Beklet ve doğrula", detail="Kart yayımlanmaz; kaynak yeniden okununca tekrar değerlendirilir."),
    ]


def with_do_nothing(alternatives: Sequence[Alternative]) -> tuple[Alternative, ...]:
    label, detail = DO_NOTHING
    if any(a.label == label for a in alternatives):
        return tuple(alternatives)
    return (*alternatives, Alternative(label=label, detail=detail))


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


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
    ) -> None:
        self.ledger = ledger
        self._clock = clock
        self.stale_after_s = stale_after_s
        self.arena: ArenaPort = arena or RuleBasedSeats(stale_after_s=stale_after_s, clock=clock)
        self.drafts = drafts or RuleDrafts(ledger, clock=clock)
        settings = EscalationSettings.merged(m.escalation for m in missions)
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
        with self._lock:
            if self.ledger.has_signal(signal.signal_id):
                return self._existing(signal.signal_id)
            ids = {"signal_id": signal.signal_id, "entity_id": signal.entity_id}
            detail = {"signal": signal.model_dump(mode="json")}
            self.ledger.append(EntryKind.SIGNAL, actor=f"kaynak: {signal.provenance.source}", detail=detail, **ids)
            route = self.router.explain(signal)
            binding = self._binding(signal, route)
            if binding is not None:
                outcome: ProcessResult | RouteDecision = self._run_binding(signal, route, binding, ids)
            elif route.path == "reflex" and route.rule is not None:
                outcome = self._run_reflex(signal, route, route.rule, ids)
            else:
                outcome = route
            if isinstance(outcome, ProcessResult):
                return outcome
            return self._escalate(signal, outcome, ids, evidence, alternatives)

    def _binding(self, signal: Signal, route: RouteDecision) -> Binding | None:
        """An approved alternative for this outage, unless an escalation trigger fired."""
        if outage_of(signal) is None or {CRITICAL, REPEAT} & set(route.reasons):
            return None
        return find_binding(self.states().values(), signal, self._clock())

    def _run_binding(
        self, signal: Signal, route: RouteDecision, binding: Binding, ids: dict[str, str]
    ) -> ProcessResult | RouteDecision:
        """R-05: publish the approved text if the snapshot still supports it, else back to a person."""
        started = time.perf_counter()
        failures = revalidate(binding, signal, self._clock(), self.stale_after_s)
        actor = f"onaylı alternatif {binding.binding_id}"
        if failures:
            detail = {"rule_id": binding.binding_id, "failure": ",".join(failures), "elapsed_ms": _ms(started)}
            self.ledger.append(EntryKind.REFLEX_FAILED, actor=actor, detail=detail, **ids)
            return route.model_copy(update={"path": "arena", "reasons": (BINDING_CHECK_FAILED, *failures)})
        card = CardDraft(kind="alternative", title=signal.title, body=binding.text)
        action = Action(kind=BOUND_ACTION, rule_id=binding.binding_id, signal_id=signal.signal_id, card=card)
        bound = route.model_copy(update={"path": "reflex", "reasons": (APPROVED_BINDING,)})
        return self._close(signal, bound, action, _ms(started), actor, ids)

    def _run_reflex(
        self, signal: Signal, route: RouteDecision, rule: MissionRule, ids: dict[str, str]
    ) -> ProcessResult | RouteDecision:
        """The closed result, or the route turned to the Arena when the rule could not run."""
        result = self.reflex.run(rule, signal)
        actor = f"kural {rule.id}"
        if result.ok and result.action is not None:
            return self._close(signal, route, result.action, result.elapsed_ms, actor, ids)
        detail = {"rule_id": rule.id, "failure": result.failure, "elapsed_ms": result.elapsed_ms}
        self.ledger.append(EntryKind.REFLEX_FAILED, actor=actor, detail=detail, **ids)
        return route.model_copy(update={"path": "arena", "reasons": (*route.reasons, REFLEX_FAILED)})

    def _close(
        self, signal: Signal, route: RouteDecision, action: Action, elapsed_ms: float, actor: str, ids: dict[str, str]
    ) -> ProcessResult:
        self._seal_route(route, ids, rule_id=action.rule_id)
        detail = {"action": action.model_dump(mode="json"), "elapsed_ms": elapsed_ms}
        self.ledger.append(EntryKind.REFLEX_CLOSED, actor=actor, detail=detail, **ids)
        return ProcessResult(
            signal_id=signal.signal_id,
            path="reflex",
            status="closed_by_reflex",
            rule_id=action.rule_id,
            reasons=route.reasons,
            action=action,
            reflex_ms=elapsed_ms,
        )

    def _escalate(
        self,
        signal: Signal,
        route: RouteDecision,
        ids: dict[str, str],
        evidence: Sequence[EvidenceItem] | None,
        alternatives: Sequence[Alternative] | None,
    ) -> ProcessResult:
        self._seal_route(route, ids)
        decision = self._draft(signal, route, evidence, alternatives)
        detail = {"decision": decision.model_dump(mode="json")}
        self.ledger.append(EntryKind.ARENA_DRAFTED, actor=f"Arena ({decision.author})", detail=detail, **ids)
        return ProcessResult(
            signal_id=signal.signal_id,
            path="arena",
            status="awaiting_approval",
            rule_id=decision.rule_id,
            reasons=route.reasons,
            decision=decision,
        )

    def _seal_route(self, route: RouteDecision, ids: dict[str, str], rule_id: str | None = None) -> None:
        rule_id = rule_id or (route.rule.id if route.rule else None)
        detail = {"path": route.path, "rule_id": rule_id, "reasons": list(route.reasons), "repeats": route.repeats}
        self.ledger.append(EntryKind.ROUTED, actor=ROUTER_ACTOR, detail=detail, **ids)

    def _draft(
        self,
        signal: Signal,
        route: RouteDecision,
        evidence: Sequence[EvidenceItem] | None,
        alternatives: Sequence[Alternative] | None,
    ) -> Decision:
        now = self._clock()
        items = tuple(evidence) if evidence is not None else default_evidence(signal)
        outcome = convene(self.arena, signal, items, now, self.stale_after_s)
        proposal = self._proposal(signal, route.rule, now)
        options = alternatives if alternatives is not None else default_alternatives(proposal)
        return Decision(
            signal_id=signal.signal_id,
            rule_id=route.rule.id if route.rule else None,
            reasons=route.reasons,
            evidence=items,
            alternatives=with_do_nothing(options),
            opinions=outcome.opinions,
            dissent_summary=outcome.dissent_summary,
            proposed_action=proposal,
            confidence=outcome.confidence,
            author=outcome.author,
            arena_label=outcome.label,
            created_at=now,
        )

    @staticmethod
    def _proposal(signal: Signal, rule: MissionRule | None, now: dt.datetime) -> ProposedAction:
        """The rule's own card text when it renders; otherwise a fixed text the operator can edit."""
        expires = now + dt.timedelta(days=(rule.expires_days if rule and rule.expires_days else PROPOSAL_DAYS))
        if rule is not None:
            try:
                text = render(rule.then.card_template, signal_values(signal))
                return ProposedAction(kind=rule.then.action, text=text, expires_at=expires, template=rule.then.card_template)
            except MissingField:
                pass
        where = signal.payload.get("station") or signal.entity_id
        text = f"{signal.title}: {where}. Son bilinen durum; kaynak ve veri yaşı kartta. Metni düzenleyerek onaylayın."
        return ProposedAction(kind="publish_card", text=text, expires_at=expires)

    def decide(self, approval: Approval) -> DecisionReceipt:
        """Seal a human's ruling on a card. The only path from a draft to a published text."""
        if not isinstance(approval, Approval):
            raise TypeError("only a human Approval settles a decision")
        with self._lock:
            state = self.states().get(approval.signal_id)
            if state is None or state.decision is None:
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
            duplicate=True,
        )

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
