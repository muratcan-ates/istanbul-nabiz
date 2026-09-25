"""Small helpers for composing the evidence and alternatives carried by a decision card."""

from __future__ import annotations

from collections.abc import Sequence

from nexus_core.arena import EvidenceItem
from nexus_core.decisions import DO_NOTHING, PROPOSAL_MAX, Alternative, ProposedAction
from nexus_core.signals import Signal


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


def clip(text: str, limit: int = PROPOSAL_MAX) -> str:
    """A proposal the card can hold: long text is cut, never allowed to fail the draft."""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
