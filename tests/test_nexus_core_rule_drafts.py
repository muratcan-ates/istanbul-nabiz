"""nexus_core.rule_drafts: three approvals in thirty days make a draft; only a person makes a rule."""

from __future__ import annotations

import datetime as dt
import pathlib
import tomllib

import pytest
from nexus_helpers import OPERATOR, Clock, approve, build_engine, elevator, make_signal

from nexus_core.engine import NexusEngine
from nexus_core.ledger import EntryKind
from nexus_core.missions import parse_rules
from nexus_core.rule_drafts import DraftNotFound, Pattern, parse_rule_toml, rule_toml
from nexus_core.signals import Signal


def outage(n: int, when: dt.datetime) -> Signal:
    """An elevator outage at its own elevator: separate elevators, so no repeat trigger fires."""
    return make_signal(entity=f"M2-TAKSIM-ASN-{n:02d}", observed_at=when, **elevator(f"ASN-{n:02d}@2026-09").payload)


def spread(engine: NexusEngine, clock: Clock, count: int, *, start: int = 0, action: str = "approve") -> list[str]:
    """``count`` outages, each ruled ``action`` by the operator, a day apart."""
    ids = []
    for n in range(start, start + count):
        signal_id = engine.process(outage(n, clock.now)).signal_id
        engine.decide(approve(signal_id, action, "" if action == "approve" else "Alternatif uygun değil"))
        ids.append(signal_id)
        clock.advance(days=1)
    return ids


def test_one_or_two_approvals_make_no_draft(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    spread(engine, clock, 2)
    assert engine.drafts.drafts() == []


def test_three_approvals_make_a_draft_of_a_time_bound_reflex_rule(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    ids = spread(engine, clock, 3)
    (draft,) = engine.drafts.drafts()
    assert draft.pattern == Pattern(kind="equipment_fault", equipment_type="elevator", action="publish_alternative")
    assert draft.pattern.text == "equipment_fault · elevator · publish_alternative"
    assert draft.evidence_decisions == tuple(ids) and draft.expires_days == 30
    data = tomllib.loads(draft.proposed_rule_toml)["rules"]
    assert "valid_from" not in data[0]  # a draft does not run; adoption starts its clock
    (rule,) = parse_rules(data, reviewed_on=clock.now.date())
    assert rule.path == "reflex" and rule.id == draft.draft_id and rule.expires_days == 30
    fields = {(c.field, c.op) for c in rule.when.conditions}
    assert ("equipment_type", "eq") in fields and ("alternative_station", "present") in fields
    assert rule.then.card_template == engine.decision(ids[0]).proposed_action.template


def test_a_rejection_in_the_window_blocks_the_draft(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    spread(engine, clock, 3)
    spread(engine, clock, 1, start=3, action="reject")
    assert engine.drafts.drafts() == []


def test_approvals_older_than_the_window_do_not_count(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    spread(engine, clock, 2)
    clock.advance(days=40)
    spread(engine, clock, 1, start=2)
    assert engine.drafts.drafts() == []


def test_adopting_needs_a_person_and_a_reason_and_makes_a_rule_the_router_uses(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    spread(engine, clock, 3)
    (draft,) = engine.drafts.drafts()
    with pytest.raises(ValueError, match="written reason"):
        engine.drafts.adopt(draft.draft_id, "  ", OPERATOR)
    with pytest.raises(DraftNotFound):
        engine.drafts.adopt("draft-0000000000", "Neden", OPERATOR)
    adopted = engine.drafts.adopt(draft.draft_id, "Üç ayrı arızada aynı alternatif onaylandı", OPERATOR)
    assert adopted.rule_id == "R-101" and adopted.expires_at == clock.now + dt.timedelta(days=30)
    (entry,) = engine.ledger.entries(kinds=[EntryKind.RULE_ADOPTED])
    assert entry.actor == OPERATOR.label and entry.detail["evidence_decisions"] == list(draft.evidence_decisions)
    assert engine.drafts.drafts() == []  # the pattern is covered while the rule lives
    result = engine.process(outage(77, clock.now))
    assert result.path == "reflex" and result.rule_id == "R-101" and result.status == "closed_by_reflex"


def test_a_revoked_or_expired_rule_stops_at_once(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    spread(engine, clock, 3)
    (draft,) = engine.drafts.drafts()
    engine.drafts.adopt(draft.draft_id, "Üç onay", OPERATOR)
    with pytest.raises(ValueError, match="written reason"):
        engine.drafts.revoke("R-101", "", OPERATOR)
    engine.drafts.revoke("R-101", "Alternatif istasyonda bakım başladı", OPERATOR)
    assert engine.drafts.active_rules() == []
    with pytest.raises(KeyError):
        engine.drafts.revoke("R-101", "ikinci kez", OPERATOR)
    assert engine.process(outage(78, clock.now)).path == "arena"


def test_an_adopted_rule_expires_and_is_not_renewed_by_itself(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    spread(engine, clock, 3)
    (draft,) = engine.drafts.drafts()
    engine.drafts.adopt(draft.draft_id, "Üç onay", OPERATOR)
    assert [r.id for r in engine.drafts.active_rules()] == ["R-101"]
    clock.advance(days=31)
    assert engine.drafts.active_rules() == []
    assert [r.rule_id for r in engine.drafts.adopted()] == ["R-101"]


def test_rule_toml_escapes_text_and_round_trips() -> None:
    pattern = Pattern(kind="equipment_fault", equipment_type="elevator", action="publish_alternative")
    template = 'Taksim "M2"\\ {station}:\n{alternative_station}\x7f'
    start = dt.datetime(2026, 9, 25, 9, 0, tzinfo=dt.UTC)
    text = rule_toml("R-101", pattern, template, 30, valid_from=start)
    tomllib.loads(text)
    rule = parse_rule_toml(text)
    assert rule.then.card_template == template and rule.valid_from == start and rule.expires_at == start + dt.timedelta(days=30)


def long_outage(outage_id: str, when: dt.datetime, n: int = 0) -> Signal:
    return make_signal(
        "long_outage",
        entity=f"M4-KARTAL-ASN-{n:02d}",
        observed_at=when,
        station="Kartal",
        outage_id=outage_id,
        outage_hours=48.0,
        text="Kartal (M4): asansör kullanılamıyor.",
    )


def test_one_event_approved_three_times_is_still_one_event(tmp_path: pathlib.Path) -> None:
    """Three snapshots of one outage, each approved, must not make a rule (one event never does)."""
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    for _ in range(3):
        engine.decide(approve(engine.process(long_outage("ASN-9@2026-09-20", clock.now)).signal_id))
        clock.advance(hours=6)
    assert engine.drafts.drafts() == []
    for n in (1, 2):
        engine.decide(approve(engine.process(long_outage(f"ASN-{n}@2026-09-2{n}", clock.now, n)).signal_id))
        clock.advance(hours=6)
    (draft,) = engine.drafts.drafts()
    assert len(draft.evidence_decisions) == 3, "three separate outages, one decision each"


def test_one_alert_approved_three_times_makes_no_draft(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    for _ in range(3):
        alert = make_signal("parking_full", entity="alert:p1", observed_at=clock.now, text="Otopark dolu.", dedupe_key="p1")
        engine.decide(approve(engine.process(alert).signal_id))
        clock.advance(hours=2)
    assert engine.drafts.drafts() == []


def test_a_revoked_rule_needs_new_approvals_for_a_new_draft(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    spread(engine, clock, 3)
    (draft,) = engine.drafts.drafts()
    adopted = engine.drafts.adopt(draft.draft_id, "Üç onay", OPERATOR)
    engine.drafts.revoke(adopted.rule_id, "Yanlış benimsendi", OPERATOR)
    clock.advance(minutes=1)
    assert engine.drafts.drafts() == [], "the same evidence must not bring the revoked rule straight back"
    spread(engine, clock, 3, start=10)
    (again,) = engine.drafts.drafts()
    assert again.draft_id == draft.draft_id and not set(again.evidence_decisions) & set(draft.evidence_decisions)
