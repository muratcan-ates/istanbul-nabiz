from __future__ import annotations

import datetime as dt

import pytest
from nexus_helpers import T0, Clock, approve, build_engine, elevator

from nexus_core.decisions import DecisionConflict
from nexus_core.missions import EscalationSettings, Mission
from nexus_core.views import decision_payload, queue_payload


def ttl_missions(hours: int) -> list[Mission]:
    return [Mission(id="ttl-test", title="TTL test", escalation=EscalationSettings(ttl_hours=hours))]


def test_stale_cards_expire_with_the_system_actor(tmp_path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock, mission_list=ttl_missions(1))
    signal_id = engine.process(elevator()).signal_id
    clock.advance(hours=1, seconds=1)
    assert engine.expire() == [signal_id]
    state = engine.states()[signal_id]
    assert state.status == "expired" and state.expired_at == clock.now
    assert engine.trace(signal_id).steps[-1].actor == "system:timeout"
    assert engine.stats().approval_rate is None


def test_expiry_disabled_with_zero_ttl(tmp_path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock, mission_list=ttl_missions(0))
    signal_id = engine.process(elevator()).signal_id
    clock.advance(days=10)
    assert engine.expire() == [] and engine.states()[signal_id].status == "awaiting_approval"


def test_a_deferred_card_never_expires(tmp_path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock, mission_list=ttl_missions(1))
    signal_id = engine.process(elevator()).signal_id
    engine.decide(approve(signal_id, "defer", "Kaynak yeniden okunacak"))
    clock.advance(days=2)
    assert engine.expire() == [] and engine.states()[signal_id].status == "deferred"


def test_an_expired_card_cannot_be_decided(tmp_path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock, mission_list=ttl_missions(1))
    signal_id = engine.process(elevator()).signal_id
    clock.advance(hours=2)
    engine.expire()
    with pytest.raises(DecisionConflict):
        engine.decide(approve(signal_id))


def test_the_card_and_queue_expose_the_ttl_deadline(tmp_path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock, mission_list=ttl_missions(24))
    signal_id = engine.process(elevator()).signal_id
    expected = (T0 + dt.timedelta(hours=24)).isoformat()
    assert decision_payload(engine.states()[signal_id], clock.now)["expires_at"] == expected
    assert queue_payload(engine.states().values())["items"][0]["expires_at"] == expected
