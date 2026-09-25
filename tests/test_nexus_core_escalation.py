from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from nexus_helpers import T0, Clock, build_engine, elevator, origin

from nexus_core.arena import EvidenceItem, Opinion, convene, vote
from nexus_core.signals import Signal


def opinion(role: str, stance: str) -> Opinion:
    return Opinion(role=role, stance=stance, rationale="Kanıt gözden geçirildi.", citations=(origin(T0),))


class ScriptedSeats:
    author = "model"
    label = "Model koltukları"

    def __init__(self, first: list[Opinion], second: list[Opinion] | None = None) -> None:
        self.first = first
        self.second = second
        self.revisions = 0

    def opinions(self, signal: Signal, evidence: Sequence[EvidenceItem]) -> list[Opinion]:
        return self.first

    def revise(self, signal: Signal, evidence: Sequence[EvidenceItem], prior: Sequence[Opinion]) -> list[Opinion]:
        self.revisions += 1
        return self.second or list(prior)


class OneRoundSeats(ScriptedSeats):
    revise = None


def test_the_panel_majority_labels_the_card_and_conditional_is_not_a_vote() -> None:
    panel = vote([opinion("Erişilebilirlik", "support"), opinion("Operasyon", "support"), opinion("İletişim", "conditional")])
    assert panel.verdict == "publish"
    assert panel.votes.model_dump() == {"support": 2, "oppose": 0, "conditional": 1}
    assert panel.answered == 3 and panel.quorum == 2 and panel.rounds == 1


def test_a_dead_seat_abstains_instead_of_voting() -> None:
    panel = vote([opinion("Operasyon", "support")])
    assert panel.verdict == "no_quorum" and panel.answered == 1
    assert panel.votes.model_dump() == {"support": 1, "oppose": 0, "conditional": 0}


def test_below_quorum_or_a_tie_keeps_the_draft() -> None:
    assert vote([opinion("Operasyon", "support")]).verdict == "no_quorum"
    assert vote([opinion("Operasyon", "support"), opinion("İletişim", "oppose")]).verdict == "tie"


def test_dissent_gets_one_optional_revision_round() -> None:
    seats = ScriptedSeats(
        [opinion("Erişilebilirlik", "oppose"), opinion("Operasyon", "support"), opinion("İletişim", "conditional")],
        [opinion("Erişilebilirlik", "support"), opinion("Operasyon", "support")],
    )
    outcome = convene(seats, elevator(), [EvidenceItem(text="Asansör", provenance=origin(T0))], T0)
    assert seats.revisions == 1 and outcome.panel.rounds == 2 and outcome.panel.verdict == "publish"


def test_a_port_without_revise_gets_one_round() -> None:
    seats = OneRoundSeats([opinion("Operasyon", "oppose")])
    outcome = convene(seats, elevator(), [EvidenceItem(text="Asansör", provenance=origin(T0))], T0)
    assert outcome.panel.rounds == 1 and outcome.panel.verdict == "no_quorum"


def test_the_verdict_never_changes_the_status(tmp_path: Path) -> None:
    seats = OneRoundSeats([opinion(role, "oppose") for role in ("Erişilebilirlik", "Operasyon", "İletişim")])
    result = build_engine(tmp_path, Clock(), arena=seats).process(elevator())
    assert result.decision.panel.verdict == "hold"
    assert result.status == "awaiting_approval"
