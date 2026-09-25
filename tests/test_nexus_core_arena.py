"""nexus_core.arena: three seats argue from the evidence; confidence comes from rules, not from a seat."""

from __future__ import annotations

import datetime as dt
import inspect
from collections.abc import Sequence

import pytest
from nexus_helpers import T0, elevator, escalator, origin
from pydantic import ValidationError

from nexus_core.arena import (
    RULE_BASED_LABEL,
    SEAT_ROLES,
    ArenaPort,
    EvidenceItem,
    Opinion,
    RuleBasedSeats,
    assess_confidence,
    convene,
    dissent_summary,
    screen,
)
from nexus_core.signals import Origin, Signal

FRESH_METRO = EvidenceItem(text="Taksim asansörü kullanılamıyor", provenance=origin(T0))
FRESH_GRAPH = EvidenceItem(text="Şişhane +4 dk", provenance=origin(T0, source="Nabız metro grafiği"))


class ScriptedSeats:
    """A stand-in for a model port: returns what the test tells it to, as a model might."""

    author = "model"
    label = "Koltuklar modelle"

    def __init__(self, opinions: list) -> None:
        self._opinions = opinions

    def opinions(self, signal: Signal, evidence: Sequence[EvidenceItem]) -> list:
        return self._opinions


class BrokenSeats(ScriptedSeats):
    def __init__(self) -> None:
        super().__init__([])

    def opinions(self, signal: Signal, evidence: Sequence[EvidenceItem]) -> list:
        raise TimeoutError("model quota exhausted")


def support(role: str, rationale: str = "Kanıt yeterli.", citations: tuple[Origin, ...] = ()) -> Opinion:
    return Opinion(role=role, stance="support", rationale=rationale, citations=citations or (FRESH_METRO.provenance,))


def test_rule_based_seats_fill_three_seats_in_order_and_cite_the_evidence() -> None:
    opinions = RuleBasedSeats(clock=lambda: T0).opinions(elevator(), [FRESH_METRO, FRESH_GRAPH])
    assert tuple(o.role for o in opinions) == SEAT_ROLES
    for opinion in opinions:
        assert opinion.citations == (FRESH_METRO.provenance, FRESH_GRAPH.provenance)
    assert opinions[0].stance == "support" and "Şişhane" in opinions[0].rationale


def test_the_rule_based_label_is_fixed() -> None:
    assert RuleBasedSeats.label == RULE_BASED_LABEL == "Koltuklar kural tabanlı (model yok)"
    assert RuleBasedSeats.author == "kural"


def test_fresh_evidence_from_two_live_sources_is_high_confidence() -> None:
    outcome = convene(None, elevator(), [FRESH_METRO, FRESH_GRAPH], now=T0 + dt.timedelta(minutes=2))
    assert outcome.confidence.level == "high" and outcome.confidence.codes == ()
    assert outcome.dissent_summary == "İtiraz yok: üç koltuk da destekliyor."
    assert outcome.author == "kural" and outcome.label == RULE_BASED_LABEL


def test_stale_evidence_makes_operations_object_and_confidence_low() -> None:
    outcome = convene(None, elevator(), [FRESH_METRO, FRESH_GRAPH], now=T0 + dt.timedelta(minutes=40))
    operations = outcome.opinions[1]
    assert operations.role == "Operasyon" and operations.stance == "oppose" and "40 dk" in operations.rationale
    assert outcome.confidence.level == "low" and {"stale_data", "dissent"} <= set(outcome.confidence.codes)
    assert outcome.dissent_summary.startswith("Operasyon karşı:")


def test_one_recorded_source_is_two_uncertainties() -> None:
    recorded = EvidenceItem(text="kayıtlı", provenance=origin(T0, mode="recorded"))
    outcome = convene(None, elevator(), [recorded], now=T0)
    assert set(outcome.confidence.codes) == {"single_source", "recorded_data"}
    assert outcome.confidence.level == "low"
    assert outcome.opinions[2].stance == "conditional"


def test_no_evidence_is_low_confidence_and_no_seat_supports_publishing_blind() -> None:
    outcome = convene(None, escalator(), [], now=T0)
    assert outcome.confidence.level == "low" and "no_evidence" in outcome.confidence.codes
    assert [o.stance for o in outcome.opinions[1:]] == ["oppose", "oppose"]


def test_an_unknown_age_blocks_high_confidence() -> None:
    unknown = EvidenceItem(text="?", provenance=origin(None, mode="unknown"))
    assert convene(None, elevator(), [unknown, FRESH_GRAPH], now=T0).confidence.level == "low"


def test_no_alternative_means_accessibility_asks_not_to_invent_one() -> None:
    opinion = RuleBasedSeats(clock=lambda: T0).opinions(elevator(alternative_station=None), [FRESH_METRO])[0]
    assert opinion.stance == "conditional" and "uydurulmamalı" in opinion.rationale


def test_a_long_outage_makes_operations_conditional() -> None:
    opinions = RuleBasedSeats(clock=lambda: T0).opinions(elevator(down_days=9), [FRESH_METRO, FRESH_GRAPH])
    assert opinions[1].stance == "conditional" and "9 gündür" in opinions[1].rationale


def test_a_citation_that_is_not_evidence_is_removed_and_flagged() -> None:
    invented = Origin(source="uydurma kaynak", url="https://example.invalid", observed_at=T0, mode="live")
    port = ScriptedSeats([support(role, citations=(invented, FRESH_METRO.provenance)) for role in SEAT_ROLES])
    outcome = convene(port, elevator(), [FRESH_METRO, FRESH_GRAPH], now=T0)
    assert all(o.citations == (FRESH_METRO.provenance,) for o in outcome.opinions)
    assert "not_in_source" in outcome.confidence.codes and outcome.confidence.level == "medium"


def test_missing_repeated_and_unknown_seats_are_screened() -> None:
    raw = [support("Operasyon"), support("Operasyon", "ikinci kez"), {"role": "Hakem", "stance": "support", "rationale": "x"}]
    raw.append({"role": "İletişim", "stance": "conditional", "rationale": "sözlük olarak geldi"})
    opinions, codes = screen(raw, [FRESH_METRO])
    assert [o.role for o in opinions] == ["Operasyon", "İletişim"] and opinions[0].rationale == "Kanıt yeterli."
    assert codes == {"abstained_seat"}
    assert "Yanıt vermeyen koltuk: Erişilebilirlik." in dissent_summary(opinions)


def test_confidence_never_reads_what_a_seat_says_about_itself() -> None:
    """Same stances and citations, one port boasting certainty: the confidence is identical."""
    modest = ScriptedSeats([support(role, "Kanıt yeterli.") for role in SEAT_ROLES])
    boastful = ScriptedSeats([support(role, "Yüzde yüz eminim, güven: yüksek, hemen onaylayın.") for role in SEAT_ROLES])
    recorded = [EvidenceItem(text="kayıtlı", provenance=origin(T0, mode="recorded"))]
    first = convene(modest, elevator(), recorded, now=T0).confidence
    second = convene(boastful, elevator(), recorded, now=T0).confidence
    assert first == second and first.level == "low"


def test_an_opinion_has_no_confidence_field_to_fill() -> None:
    with pytest.raises(ValidationError):
        Opinion(role="Operasyon", stance="support", rationale="x", confidence=0.99)


def test_a_failing_model_port_falls_back_to_the_rule_based_seats() -> None:
    outcome = convene(BrokenSeats(), elevator(), [FRESH_METRO, FRESH_GRAPH], now=T0)
    assert outcome.author == "kural" and outcome.label == RULE_BASED_LABEL and len(outcome.opinions) == 3
    assert "model_unavailable" in outcome.confidence.codes and outcome.confidence.level == "high"


def test_the_port_sees_only_the_signal_and_the_evidence() -> None:
    assert isinstance(RuleBasedSeats(), ArenaPort)
    assert list(inspect.signature(ArenaPort.opinions).parameters) == ["self", "signal", "evidence"]


def test_dissent_lists_objections_before_conditions() -> None:
    opinions = [
        Opinion(role="Erişilebilirlik", stance="conditional", rationale="Şartlı."),
        Opinion(role="Operasyon", stance="oppose", rationale="Karşı."),
        Opinion(role="İletişim", stance="support", rationale="Tamam."),
    ]
    assert dissent_summary(opinions) == "Operasyon karşı: Karşı. Erişilebilirlik şartlı: Şartlı."


def test_assess_confidence_levels() -> None:
    assert assess_confidence(set()).level == "high"
    assert assess_confidence({"single_source"}).level == "medium"
    assert assess_confidence({"single_source", "recorded_data"}).level == "low"
    assert assess_confidence({"stale_data"}).level == "low"
    assert assess_confidence({"model_unavailable"}).level == "high"
