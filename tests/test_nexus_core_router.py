"""nexus_core.router and escalation: reflex or Arena, deterministic, with a reason for each."""

from __future__ import annotations

import datetime as dt

from nexus_helpers import T0, Clock, elevator, escalator, make_signal, missions

from nexus_core.escalation import CRITICAL, REPEAT, Escalation, outage_key
from nexus_core.missions import EscalationSettings, MissionRule
from nexus_core.router import NO_RULE, REASON_TEXT, RULE_EXPIRED, RULE_PATH, Router
from nexus_core.signals import Signal


def router(clock: Clock | None = None, history: list[Signal] | None = None, learned: list[MissionRule] | None = None) -> Router:
    signals = history or []
    escalation = Escalation(
        EscalationSettings.merged(m.escalation for m in missions()),
        history=lambda entity, since: [s for s in signals if s.entity_id == entity and s.observed_at >= since],
    )
    return Router(missions(), escalation, learned=(lambda: learned or []), clock=clock or Clock())


def test_a_routine_signal_takes_the_reflex_path() -> None:
    decision = router().explain(escalator())
    assert decision.path == "reflex" and decision.rule.id == "R-03" and decision.reasons == ()


def test_a_rule_can_send_its_signal_to_a_person() -> None:
    decision = router().explain(elevator())
    assert decision.path == "arena" and decision.rule.id == "R-01" and decision.reasons == (RULE_PATH,)


def test_a_signal_no_rule_knows_goes_to_a_person() -> None:
    decision = router().explain(make_signal("parking_full"))
    assert decision.path == "arena" and decision.rule is None and decision.reasons == (NO_RULE,)
    assert router().route(make_signal("parking_full")) == "arena"


def test_critical_severity_escalates_whatever_the_rule_says() -> None:
    signal = make_signal(severity="critical", entity="M4-KADIKOY-YM-07", station="Kadıköy", equipment_type="escalator")
    decision = router().explain(signal)
    assert decision.path == "arena" and decision.rule.id == "R-03" and CRITICAL in decision.reasons


def test_a_critical_kind_escalates() -> None:
    decision = router().explain(make_signal("hub_faults", station="Yenikapı", fault_count=2))
    assert decision.path == "arena" and CRITICAL in decision.reasons


def test_an_expired_rule_no_longer_closes_anything() -> None:
    late = Clock(dt.datetime(2026, 10, 26, tzinfo=dt.UTC))
    decision = router(late).explain(escalator())
    assert decision.path == "arena" and decision.rule is None and decision.reasons == (RULE_EXPIRED,)


def escalator_at(outage: str, when: dt.datetime) -> Signal:
    return make_signal(
        entity="M4-KADIKOY-YM-07", observed_at=when, station="Kadıköy", equipment_type="escalator", outage_id=outage
    )


def test_three_separate_outages_in_the_window_escalate() -> None:
    history = [escalator_at("o-1", T0 - dt.timedelta(days=10)), escalator_at("o-2", T0 - dt.timedelta(days=3))]
    decision = router(history=history).explain(escalator_at("o-3", T0))
    assert decision.path == "arena" and REPEAT in decision.reasons and decision.repeats == 3


def test_one_long_outage_reported_many_times_is_one_event() -> None:
    history = [escalator_at("o-1", T0 - dt.timedelta(minutes=15 * n)) for n in range(1, 40)]
    decision = router(history=history).explain(escalator_at("o-1", T0))
    assert decision.path == "reflex" and decision.repeats == 1


def test_outages_outside_the_window_are_not_counted() -> None:
    history = [escalator_at("o-1", T0 - dt.timedelta(days=20)), escalator_at("o-2", T0 - dt.timedelta(days=15))]
    decision = router(history=history).explain(escalator_at("o-3", T0))
    assert decision.path == "reflex" and decision.repeats == 1


def test_a_signal_without_an_outage_id_counts_as_its_own_event() -> None:
    plain = make_signal(station="Taksim")
    assert outage_key(plain) == f"signal:{plain.signal_id}"
    assert outage_key(escalator()) == "outage:YM-07@2026-09-25"


def test_learned_rules_are_tried_first() -> None:
    learned = MissionRule.model_validate(
        {
            "id": "R-101",
            "path": "reflex",
            "expires_days": 30,
            "valid_from": T0,
            "when": {"kind": "equipment_fault", "conditions": [{"field": "equipment_type", "op": "eq", "value": "elevator"}]},
            "then": {"action": "publish_alternative", "card_template": "{station}: {alternative_station}"},
        }
    )
    decision = router(learned=[learned]).explain(elevator())
    assert decision.path == "reflex" and decision.rule.id == "R-101"


def test_every_reason_code_has_turkish_text() -> None:
    codes = (NO_RULE, RULE_EXPIRED, RULE_PATH, CRITICAL, REPEAT, "reflex_failed", "approved_binding", "binding_check_failed")
    for code in (*codes, "alternative_changed", "alternative_unverified", "stale_data"):
        assert REASON_TEXT[code]
