"""nexus_core.stats: the time NEXUS gives back, for the team, and the rubber-stamp warning."""

from __future__ import annotations

import datetime as dt
import pathlib

from nexus_helpers import T0, Clock, approve, build_engine, elevator, escalator, make_signal

from nexus_core.engine import NexusEngine
from nexus_core.stats import MIN_RULINGS_FOR_WARNING, RUBBER_STAMP_RATE, compute_stats


def outage(n: int, when: dt.datetime):
    return make_signal(entity=f"E-{n:03d}", observed_at=when, **elevator(f"O-{n:03d}").payload)


def rule(engine: NexusEngine, clock: Clock, count: int, action: str, *, start: int = 0, wait_s: float = 30) -> None:
    for n in range(start, start + count):
        signal_id = engine.process(outage(n, clock.now)).signal_id
        clock.advance(seconds=wait_s)
        engine.decide(approve(signal_id, action, "" if action == "approve" else "Gerekçe"))


def test_an_empty_ledger_has_no_numbers_to_invent(tmp_path: pathlib.Path) -> None:
    stats = build_engine(tmp_path, Clock()).stats()
    assert stats.reflex_closed_today == 0 and stats.awaiting_approval == 0
    assert stats.median_decision_s is None and stats.citizen_update_latency_s is None and stats.approval_rate is None
    assert stats.rubber_stamp_warning is False and stats.rulings_counted == 0


def test_today_is_the_istanbul_day(tmp_path: pathlib.Path) -> None:
    clock = Clock(dt.datetime(2026, 9, 25, 20, 30, tzinfo=dt.UTC))  # 23:30 in İstanbul on the 25th
    engine = build_engine(tmp_path, clock)
    engine.process(escalator())
    clock.now = dt.datetime(2026, 9, 25, 21, 30, tzinfo=dt.UTC)  # 00:30 in İstanbul, the 26th
    engine.process(make_signal(entity="M4-X", observed_at=clock.now, station="Ünalan", equipment_type="escalator"))
    assert engine.stats().reflex_closed_today == 1
    clock.now = dt.datetime(2026, 9, 26, 20, 59, tzinfo=dt.UTC)  # 23:59 in İstanbul, still the 26th
    assert engine.stats().reflex_closed_today == 1


def test_decision_time_and_citizen_latency_are_medians(tmp_path: pathlib.Path) -> None:
    clock = Clock(T0 + dt.timedelta(minutes=2))  # the snapshot arrives two minutes after the source saw it
    engine = build_engine(tmp_path, clock)
    for n, wait in enumerate((10, 60, 300)):
        signal_id = engine.process(outage(n, T0)).signal_id
        clock.advance(seconds=wait)
        engine.decide(approve(signal_id))
    stats = engine.stats()
    assert stats.median_decision_s == 60.0
    # observed at T0; published at 2 min + 10 s, 2 min + 70 s, 2 min + 370 s
    assert stats.citizen_update_latency_s == 190.0


def test_deferrals_are_not_verdicts_and_rejections_lower_the_rate(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    rule(engine, clock, 3, "approve")
    rule(engine, clock, 1, "reject", start=3)
    rule(engine, clock, 2, "defer", start=4)
    stats = engine.stats()
    assert stats.approval_rate == 0.75 and stats.rulings_counted == 4 and stats.awaiting_approval == 0
    assert stats.deferred == 2, "a deferred card is still in the queue and is counted on its own"


def test_approving_everything_raises_the_rubber_stamp_warning(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    rule(engine, clock, MIN_RULINGS_FOR_WARNING - 1, "approve")
    small = engine.stats()
    assert small.approval_rate == 1.0 and small.rubber_stamp_warning is False  # nine of nine is a small sample
    rule(engine, clock, 1, "approve", start=MIN_RULINGS_FOR_WARNING)
    assert engine.stats().rubber_stamp_warning is True and RUBBER_STAMP_RATE == 0.98


def test_a_mix_of_verdicts_raises_no_warning(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    rule(engine, clock, 9, "approve")
    rule(engine, clock, 1, "reject", start=9)
    stats = engine.stats()
    assert stats.approval_rate == 0.9 and stats.rubber_stamp_warning is False


def test_stats_carry_no_operator(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    rule(engine, clock, 2, "approve")
    fields = set(compute_stats(engine.states().values(), clock.now).model_dump())
    assert fields == {
        "reflex_closed_today",
        "awaiting_approval",
        "deferred",
        "median_decision_s",
        "citizen_update_latency_s",
        "approval_rate",
        "rulings_counted",
        "rubber_stamp_warning",
    }


def test_latency_counts_only_what_the_citizen_face_shows(tmp_path: pathlib.Path) -> None:
    """An escalator reflex (R-03) or an approved R-06 card reaches no citizen page yet: no latency."""
    clock = Clock(T0 + dt.timedelta(minutes=2))
    engine = build_engine(tmp_path, clock)
    engine.process(escalator())
    long_outage = make_signal("long_outage", entity="E-LONG", station="Kartal", outage_id="L@1", outage_hours=48.0, text="K.")
    clock.advance(seconds=20)
    engine.decide(approve(engine.process(long_outage).signal_id))
    assert engine.stats().citizen_update_latency_s is None


def test_a_replay_is_timed_from_when_the_core_received_it(tmp_path: pathlib.Path) -> None:
    """A recording observed days ago must not show days of latency."""
    from nexus_helpers import origin

    clock = Clock(T0 + dt.timedelta(days=5))
    engine = build_engine(tmp_path, clock)
    recorded = elevator(observed_at=T0)
    recorded = recorded.model_copy(update={"provenance": origin(T0, mode="recorded")})
    signal_id = engine.process(recorded).signal_id
    clock.advance(seconds=45)
    engine.decide(approve(signal_id))
    assert engine.stats().citizen_update_latency_s == 45.0
