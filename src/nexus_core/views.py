# Adapted from CloudSentinel app/analytics.py (github.com/muratcan-ates/cloudsentinel @ 80938ae), MIT License,
# Copyright (c) 2026 CloudSentinel Team (YZTA Bootcamp 2026, Group 60). See NOTICE.md.
"""The console API's JSON shapes, built from replayed state.

The console (``nabiz.console``) serves ``/api/console/*``; these functions give it the exact
objects the API contract names (queue items, the decision card, the trace, the stats, the
drafts), with every provenance aged at the moment of the request. Keeping the shapes here
means the console never reaches into the models' internals, and a contract change is one diff.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any

from nexus_core.ledger import Trace
from nexus_core.receipts import receipt_of
from nexus_core.rule_drafts import RuleDraft
from nexus_core.state import SignalState
from nexus_core.stats import Stats


def queue_item(state: SignalState) -> dict[str, Any] | None:
    """One row of ``GET /api/console/queue``; ``None`` for a signal whose processing never finished."""
    if state.path is None or state.status == "received":
        return None
    if state.action is not None:
        summary = state.action.card.body
    elif state.decision is not None:
        summary = state.decision.proposed_action.text
    else:
        summary = ""
    return {
        "signal_id": state.signal.signal_id,
        "kind": state.signal.kind,
        "title": state.signal.title,
        "severity": state.signal.severity,
        "path": state.path,
        "status": state.status,
        "created_at": state.received_at.isoformat(),
        "summary": summary,
        "rule_id": state.rule_id,
        "reflex_ms": state.reflex_ms,
        "expires_at": state.decision.expires_at.isoformat() if state.decision and state.decision.expires_at else None,
    }


def queue_payload(states: Iterable[SignalState]) -> dict[str, Any]:
    """Newest first; the console sorts further if it wants the awaiting cards on top."""
    items = [item for state in states if (item := queue_item(state)) is not None]
    return {"items": sorted(items, key=lambda item: item["created_at"], reverse=True)}


def decision_payload(state: SignalState, now: dt.datetime) -> dict[str, Any]:
    """``GET /api/console/decisions/{signal_id}``. Raises ``ValueError`` for a signal with no card."""
    decision = state.decision
    if decision is None:
        raise ValueError(f"{state.signal.signal_id} has no decision card")
    proposal = decision.proposed_action
    receipt = receipt_of(state)
    return {
        "signal_id": decision.signal_id,
        "signal": state.signal.model_dump(mode="json"),
        "status": state.status,
        "reasons": list(decision.reasons),
        "evidence": [{"text": e.text, "provenance": e.provenance.as_provenance(now)} for e in decision.evidence],
        "freshness_s": decision.freshness_s(now),
        "alternatives": [a.model_dump() for a in decision.alternatives],
        "opinions": [
            {
                "role": o.role,
                "stance": o.stance,
                "rationale": o.rationale,
                "citations": [c.as_provenance(now) for c in o.citations],
            }
            for o in decision.opinions
        ],
        "dissent_summary": decision.dissent_summary,
        "proposed_action": {
            "kind": proposal.kind,
            "text": proposal.text,
            "expires_at": proposal.expires_at.isoformat() if proposal.expires_at else None,
        },
        "panel": {
            "verdict": decision.panel.verdict,
            "votes": decision.panel.votes.model_dump(),
            "answered": decision.panel.answered,
            "quorum": decision.panel.quorum,
            "rounds": decision.panel.rounds,
        },
        "confidence": {
            "level": decision.confidence.level,
            "reasons": list(decision.confidence.reasons),
            "uncertainty": [item.model_dump() for item in decision.uncertainties],
        },
        "receipt": (
            {
                "reflex_ms": receipt.reflex_ms,
                "arena_ms": receipt.arena_ms,
                "wall_ms": receipt.wall_ms,
                "llm_calls": receipt.llm_calls,
                "usd": receipt.usd,
            }
            if receipt is not None
            else None
        ),
        "expires_at": decision.expires_at.isoformat() if decision.expires_at else None,
        "author": decision.author,
        "arena_label": decision.arena_label,
    }


def trace_payload(trace: Trace) -> dict[str, Any]:
    """``GET /api/console/ledger/{signal_id}/trace``."""
    steps = [{"at": s.at.isoformat(), "actor": s.actor, "kind": s.kind, "detail": s.detail} for s in trace.steps]
    return {"steps": steps, "hash_ok": trace.hash_ok}


def stats_payload(stats: Stats) -> dict[str, Any]:
    """``GET /api/console/stats``: the five contract fields plus the rubber-stamp flag."""
    return stats.model_dump()


def drafts_payload(drafts: Iterable[RuleDraft]) -> dict[str, Any]:
    """``GET /api/console/rule-drafts``."""
    return {
        "drafts": [
            {
                "draft_id": d.draft_id,
                "pattern": d.pattern.text,
                "evidence_decisions": list(d.evidence_decisions),
                "proposed_rule_toml": d.proposed_rule_toml,
                "expires_days": d.expires_days,
            }
            for d in drafts
        ]
    }
