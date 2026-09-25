"""nexus_core.decisions: only a human settles a card, and saying no costs a written reason."""

from __future__ import annotations

import datetime as dt

import pytest
from nexus_helpers import OPERATOR, T0, approve, origin
from pydantic import ValidationError

from nexus_core.arena import Confidence, EvidenceItem
from nexus_core.decisions import (
    REASON_MAX,
    Approval,
    Decision,
    DecisionConflict,
    Operator,
    ProposedAction,
    published_text,
    settle,
)


def decision() -> Decision:
    return Decision(
        signal_id="sig-1",
        evidence=(
            EvidenceItem(text="a", provenance=origin(T0)),
            EvidenceItem(text="b", provenance=origin(T0 - dt.timedelta(minutes=10))),
            EvidenceItem(text="c", provenance=origin(None)),
        ),
        dissent_summary="İtiraz yok: üç koltuk da destekliyor.",
        proposed_action=ProposedAction(kind="publish_alternative", text="Şişhane +4 dk"),
        confidence=Confidence(level="high", reasons=("Kanıt taze",)),
        author="kural",
        arena_label="Koltuklar kural tabanlı (model yok)",
        created_at=T0,
    )


@pytest.mark.parametrize("action", ["reject", "defer"])
@pytest.mark.parametrize("reason", ["", "   "])
def test_rejecting_or_deferring_needs_a_written_reason(action: str, reason: str) -> None:
    with pytest.raises(ValidationError, match="needs a written reason"):
        approve("sig-1", action, reason)
    assert approve("sig-1", action, "Kaynak 40 dk eski").status == {"reject": "rejected", "defer": "deferred"}[action]


def test_approving_needs_no_reason_and_editing_needs_the_text() -> None:
    assert approve("sig-1").status == "approved"
    with pytest.raises(ValidationError, match="edited text"):
        approve("sig-1", "edit")
    assert approve("sig-1", "edit", edited_text="Şişhane, +5 dk").status == "approved"
    with pytest.raises(ValidationError, match="only for an edit"):
        approve("sig-1", "approve", edited_text="gizli değişiklik")


def test_a_reason_is_at_most_280_characters() -> None:
    assert REASON_MAX == 280
    with pytest.raises(ValidationError):
        approve("sig-1", "reject", "x" * 281)


@pytest.mark.parametrize("kind", ["model", "agent", "yerel model", "system"])
def test_a_model_cannot_be_the_actor_of_an_approval(kind: str) -> None:
    with pytest.raises(ValidationError):
        Operator(kind=kind)
    with pytest.raises(ValidationError):
        Approval(signal_id="sig-1", action="approve", actor={"kind": kind, "handle": "gpt"})


def test_the_operator_is_labelled_simulated() -> None:
    assert OPERATOR.kind == "human" and OPERATOR.label == "Simüle operatör (op-1)"
    with pytest.raises(ValidationError):
        Operator(handle="Ad Soyad")  # a handle, not a name


@pytest.mark.parametrize("current", ["approved", "rejected", "closed_by_reflex"])
def test_a_settled_card_takes_no_second_ruling(current: str) -> None:
    with pytest.raises(DecisionConflict):
        settle(current, approve("sig-1"))


def test_a_deferred_or_waiting_card_can_still_be_decided() -> None:
    assert settle("deferred", approve("sig-1")) == "approved"
    assert settle("awaiting_approval", approve("sig-1", "defer", "Doğrulanacak")) == "deferred"


def test_what_the_citizen_face_publishes_after_each_ruling() -> None:
    card = decision()
    assert published_text(card, approve("sig-1")) == "Şişhane +4 dk"
    assert published_text(card, approve("sig-1", "edit", edited_text="Şişhane, +5 dk")) == "Şişhane, +5 dk"
    assert published_text(card, approve("sig-1", "reject", "Alternatif uygun değil")) is None
    assert published_text(card, approve("sig-1", "defer", "Doğrulanacak")) is None


def test_freshness_is_the_stalest_known_evidence() -> None:
    assert decision().freshness_s(T0 + dt.timedelta(minutes=1)) == 660


def test_a_proposal_uses_only_catalog_actions() -> None:
    with pytest.raises(ValidationError, match="not in the reflex catalog"):
        ProposedAction(kind="approve", text="x")
