# Adapted from CloudSentinel app/actions.py (github.com/muratcan-ates/cloudsentinel @ 80938ae), MIT License,
# Copyright (c) 2026 CloudSentinel Team (YZTA Bootcamp 2026, Group 60). See NOTICE.md.
"""Write-side steps that keep the engine facade small and make every transition explicit."""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from nexus_core.approved import APPROVED_BINDING, BINDING_CHECK_FAILED, BOUND_ACTION, Binding, revalidate
from nexus_core.arena import SEAT_ROLES, EvidenceItem, convene
from nexus_core.decisions import Alternative, Decision, ProposedAction
from nexus_core.escalation import REFLEX_FAILED
from nexus_core.ledger import EntryKind
from nexus_core.missions import MissionRule
from nexus_core.proposals import clip, default_alternatives, default_evidence, with_do_nothing
from nexus_core.receipts import calls_made, count_calls, elapsed_ms, make_receipt
from nexus_core.reflex import Action, CardDraft, MissingField, render, signal_values
from nexus_core.results import ProcessResult
from nexus_core.router import RouteDecision
from nexus_core.signals import Signal
from nexus_core.uncertainty import CardUncertaintyContext, card_uncertainties

ROUTER_ACTOR = "yönlendirici"
PROPOSAL_DAYS = 30


@dataclass(frozen=True)
class CloseContext:
    signal: Signal
    route: RouteDecision
    action: Action
    reflex_ms: float
    actor: str
    ids: dict[str, str]
    process_started: float


def run_binding(
    engine: Any, signal: Signal, route: RouteDecision, binding: Binding, ids: dict[str, str], process_started: float
) -> ProcessResult | RouteDecision:
    """Publish an approved alternative if the current snapshot still supports it."""
    started = time.perf_counter()
    failures = revalidate(binding, signal, engine._clock(), engine.stale_after_s)
    actor = f"onaylı alternatif {binding.binding_id}"
    if failures:
        detail = {"rule_id": binding.binding_id, "failure": ",".join(failures), "elapsed_ms": elapsed_ms(started)}
        engine.ledger.append(EntryKind.REFLEX_FAILED, actor=actor, detail=detail, **ids)
        return route.model_copy(update={"path": "arena", "reasons": (BINDING_CHECK_FAILED, *failures)})
    card = CardDraft(kind="alternative", title=signal.title, body=binding.text)
    action = Action(kind=BOUND_ACTION, rule_id=binding.binding_id, signal_id=signal.signal_id, card=card)
    bound = route.model_copy(update={"path": "reflex", "reasons": (APPROVED_BINDING,)})
    return close_signal(
        engine, CloseContext(signal, bound, action, elapsed_ms(started), actor, ids, process_started)
    )


def run_reflex(
    engine: Any, signal: Signal, route: RouteDecision, rule: MissionRule, ids: dict[str, str], process_started: float
) -> ProcessResult | RouteDecision:
    """Run a reflex rule, or turn a failed rule into an Arena card."""
    result = engine.reflex.run(rule, signal)
    actor = f"kural {rule.id}"
    if result.ok and result.action is not None:
        return close_signal(engine, CloseContext(signal, route, result.action, result.elapsed_ms, actor, ids, process_started))
    detail = {"rule_id": rule.id, "failure": result.failure, "elapsed_ms": result.elapsed_ms}
    engine.ledger.append(EntryKind.REFLEX_FAILED, actor=actor, detail=detail, **ids)
    return route.model_copy(update={"path": "arena", "reasons": (*route.reasons, REFLEX_FAILED)})


def close_signal(engine: Any, context: CloseContext) -> ProcessResult:
    seal_route(engine.ledger, context.route, context.ids, rule_id=context.action.rule_id)
    receipt = make_receipt(
        signal_id=context.signal.signal_id,
        path="reflex",
        reflex_ms=context.reflex_ms,
        arena_ms=None,
        wall_ms=elapsed_ms(context.process_started),
        llm_calls=0,
        usd_per_call=engine.usd_per_call,
    )
    detail = {
        "action": context.action.model_dump(mode="json"),
        "elapsed_ms": context.reflex_ms,
        "receipt": receipt.model_dump(mode="json"),
    }
    engine.ledger.append(EntryKind.REFLEX_CLOSED, actor=context.actor, detail=detail, **context.ids)
    return ProcessResult(
        signal_id=context.signal.signal_id,
        path="reflex",
        status="closed_by_reflex",
        rule_id=context.action.rule_id,
        reasons=context.route.reasons,
        action=context.action,
        reflex_ms=context.reflex_ms,
        receipt=receipt,
    )


def escalate_signal(
    engine: Any,
    signal: Signal,
    route: RouteDecision,
    ids: dict[str, str],
    evidence: Sequence[EvidenceItem] | None,
    alternatives: Sequence[Alternative] | None,
    process_started: float,
) -> ProcessResult:
    seal_route(engine.ledger, route, ids)
    decision = draft_decision(engine, signal, route, evidence, alternatives, process_started)
    engine.ledger.append(
        EntryKind.ARENA_DRAFTED,
        actor=f"Arena ({decision.author})",
        detail={"decision": decision.model_dump(mode="json")},
        **ids,
    )
    return ProcessResult(
        signal_id=signal.signal_id,
        path="arena",
        status="awaiting_approval",
        rule_id=decision.rule_id,
        reasons=route.reasons,
        decision=decision,
        receipt=decision.receipt,
    )


def seal_route(ledger: Any, route: RouteDecision, ids: dict[str, str], rule_id: str | None = None) -> None:
    rule_id = rule_id or (route.rule.id if route.rule else None)
    detail = {"path": route.path, "rule_id": rule_id, "reasons": list(route.reasons), "repeats": route.repeats}
    ledger.append(EntryKind.ROUTED, actor=ROUTER_ACTOR, detail=detail, **ids)


def draft_decision(
    engine: Any,
    signal: Signal,
    route: RouteDecision,
    evidence: Sequence[EvidenceItem] | None,
    alternatives: Sequence[Alternative] | None,
    process_started: float,
) -> Decision:
    now = engine._clock()
    items = tuple(evidence) if evidence is not None else default_evidence(signal)
    calls_before = calls_made(engine.arena)
    arena_started = time.perf_counter()
    outcome = convene(engine.arena, signal, items, now, engine.stale_after_s)
    arena_ms = elapsed_ms(arena_started)
    proposal = proposal_for(signal, route.rule, now)
    options = alternatives if alternatives is not None else default_alternatives(proposal)
    uncertainties = card_uncertainties(
        CardUncertaintyContext(
            signal=signal,
            evidence=items,
            panel=outcome.panel,
            author=outcome.author,
            proposed_action=proposal.kind,
            proposed_text=proposal.text,
            confidence_codes=outcome.confidence.codes,
            states=engine.states().values(),
            now=now,
            precedent_window=engine.drafts.window,
        )
    )
    receipt = make_receipt(
        signal_id=signal.signal_id,
        path="arena",
        reflex_ms=None,
        arena_ms=arena_ms,
        wall_ms=elapsed_ms(process_started),
        llm_calls=count_calls(calls_before, calls_made(engine.arena), outcome.author, len(SEAT_ROLES)),
        usd_per_call=engine.usd_per_call,
    )
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
        panel=outcome.panel,
        uncertainties=uncertainties,
        receipt=receipt,
        expires_at=now + dt.timedelta(hours=engine.ttl_hours) if engine.ttl_hours else None,
    )


def proposal_for(signal: Signal, rule: MissionRule | None, now: dt.datetime) -> ProposedAction:
    """Render the matched rule's text or use a fixed editable fallback."""
    expires = now + dt.timedelta(days=(rule.expires_days if rule and rule.expires_days else PROPOSAL_DAYS))
    if rule is not None:
        try:
            text = clip(render(rule.then.card_template, signal_values(signal)))
            return ProposedAction(kind=rule.then.action, text=text, expires_at=expires, template=rule.then.card_template)
        except MissingField:
            pass
    where = signal.payload.get("station") or signal.entity_id
    text = f"{signal.title}: {where}. Son bilinen durum; kaynak ve veri yaşı kartta. Metni düzenleyerek onaylayın."
    return ProposedAction(kind="publish_card", text=clip(text), expires_at=expires)
