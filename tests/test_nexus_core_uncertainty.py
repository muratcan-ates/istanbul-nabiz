from __future__ import annotations

import datetime as dt

import pytest
from nexus_helpers import T0, Clock, approve, build_engine, elevator, origin

from nexus_core.arena import EvidenceItem, PanelVerdict, PanelVotes, RuleBasedSeats
from nexus_core.uncertainty import UNCERTAINTY_TEXT, CardUncertaintyContext, card_uncertainties, uncertainty


def test_every_code_has_a_label() -> None:
    assert len(UNCERTAINTY_TEXT) == 16
    assert all(uncertainty(code).label for code in UNCERTAINTY_TEXT)


def test_an_unknown_code_is_a_typo_not_a_finding() -> None:
    with pytest.raises(KeyError):
        uncertainty("misspelled_uncertainty")


def test_the_rule_based_seats_name_their_own_simulation(tmp_path) -> None:
    result = build_engine(tmp_path, Clock()).process(elevator())
    assert "rule_based_seats" in {item.code for item in result.decision.uncertainties}
    assert RuleBasedSeats.author == "kural"


def test_no_precedent_and_a_split_precedent_are_named(tmp_path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    first = engine.process(elevator("O-1", observed_at=clock.now)).signal_id
    assert "no_precedent" in {item.code for item in engine.decision(first).uncertainties}
    engine.decide(approve(first, "approve"))
    clock.advance(minutes=1)
    second = engine.process(elevator("O-2", observed_at=clock.now)).signal_id
    engine.decide(approve(second, "reject", "Kanıt doğrulanmadı"))
    clock.advance(minutes=1)
    third = engine.process(elevator("O-3", observed_at=clock.now)).decision
    assert "contested_precedent" in {item.code for item in third.uncertainties}


def test_a_figure_not_in_the_evidence_is_named() -> None:
    signal = elevator()
    evidence = [EvidenceItem(text="Asansör arızalı", provenance=origin(T0))]
    panel = PanelVerdict(
        verdict="publish",
        votes=PanelVotes(support=2, oppose=0, conditional=1),
        answered=3,
    )
    items = card_uncertainties(
        CardUncertaintyContext(
            signal=signal,
            evidence=evidence,
            panel=panel,
            author="model",
            proposed_action="publish_card",
            proposed_text="Asansör 12 dakika içinde açılacak.",
            confidence_codes=(),
            states=[],
            now=T0,
            precedent_window=dt.timedelta(days=30),
        )
    )
    assert "unverified_figures" in {item.code for item in items}
