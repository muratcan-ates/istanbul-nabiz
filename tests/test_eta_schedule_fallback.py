from __future__ import annotations

import datetime as dt

from ibb_mcp.eta import EtaParams, estimate_arrivals
from ibb_mcp.gtfs import ScheduledTrip
from ibb_mcp.models import ISTANBUL_TZ, BusPosition, PlannedDeparture, Stop


class FakeSequence:
    stop_codes = ("A", "B", "C", "D")


TARGET = Stop(stop_code="D", name="Target")


def moment(hour: int = 14, minute: int = 30) -> dt.datetime:
    return dt.datetime(2026, 9, 24, hour, minute, tzinfo=ISTANBUL_TZ)


def stale_bus(now: dt.datetime, age_s: int = 240) -> BusPosition:
    return BusPosition(
        door_no="C-479",
        line_code="500T",
        route_code="500T_G_D0",
        nearest_stop_code="A",
        reported_at=now - dt.timedelta(seconds=age_s),
    )


def trip(route_code: str = "500T_G_D0", departure: str = "14:40:00") -> ScheduledTrip:
    return ScheduledTrip(
        trip_id="445930705",
        route_code=route_code,
        service_id="6",
        headsign="4.LEVENT METRO",
        departure_time=departure,
        arrival_time="16:58:00",
        stop_count=64,
    )


def test_a_stale_position_is_not_served_as_a_minute() -> None:
    now = moment()
    arrivals, diagnostics = estimate_arrivals(
        buses=[stale_bus(now)], target=TARGET, sequences={"500T_G_D0": FakeSequence()}, now=now
    )

    assert arrivals == []
    assert diagnostics["mode"] == "unknown"
    assert diagnostics["stale_live"][0]["age_s"] == 240.0


def test_stale_positions_fall_back_to_the_gtfs_timetable() -> None:
    now = moment()
    arrivals, diagnostics = estimate_arrivals(
        buses=[stale_bus(now)],
        target=TARGET,
        sequences={"500T_G_D0": FakeSequence()},
        timetable={"500T_G_D0": (trip(),)},
        now=now,
    )

    assert arrivals[0].method == "schedule"
    assert arrivals[0].door_no == ""
    assert arrivals[0].eta_minutes == 10.0
    assert diagnostics["mode"] == "schedule"
    assert diagnostics["schedule_source"] == "gtfs_stop_times"
    assert diagnostics["scheduled_trips"][0]["stop_position"] == 3


def test_a_fresh_position_keeps_live_mode() -> None:
    now = moment()
    fresh = stale_bus(now, 60)
    arrivals, diagnostics = estimate_arrivals(
        buses=[fresh], target=TARGET, sequences={"500T_G_D0": FakeSequence()}, now=now
    )
    assert arrivals[0].method == "stop_sequence"
    assert diagnostics["mode"] == "live"

    older_but_allowed = stale_bus(now, 240)
    arrivals, diagnostics = estimate_arrivals(
        buses=[older_but_allowed],
        target=TARGET,
        sequences={"500T_G_D0": FakeSequence()},
        params=EtaParams(stale_after_s=300),
        now=now,
    )
    assert arrivals[0].method == "stop_sequence"
    assert diagnostics["mode"] == "live"


def test_unknown_age_is_not_fresh() -> None:
    now = moment()
    unknown_age = stale_bus(now)
    unknown_age.reported_at = None
    arrivals, diagnostics = estimate_arrivals(
        buses=[unknown_age], target=TARGET, sequences={"500T_G_D0": FakeSequence()}, now=now
    )

    assert arrivals == []
    assert diagnostics["mode"] == "unknown"
    assert diagnostics["stale_live"][0]["age_s"] is None


def test_the_calendar_filters_trips_when_present() -> None:
    now = moment()
    common = {
        "buses": [stale_bus(now)],
        "target": TARGET,
        "sequences": {"500T_G_D0": FakeSequence()},
        "timetable": {"500T_G_D0": (trip(),)},
        "now": now,
    }
    arrivals, diagnostics = estimate_arrivals(**common, service_days={"6": frozenset({"C"})})
    assert arrivals == []
    assert diagnostics["schedule_day_filter"] == "calendar"

    arrivals, diagnostics = estimate_arrivals(**common, service_days={})
    assert arrivals[0].method == "schedule"
    assert diagnostics["schedule_day_filter"] == "none"


def test_timetable_beats_planned_departures_and_planned_beats_nothing() -> None:
    now = moment()
    planned = PlannedDeparture(
        line_code="500T", direction="Planned", day_type="I", departure_time="14:41"
    )
    common = {
        "buses": [stale_bus(now)],
        "target": TARGET,
        "sequences": {"500T_G_D0": FakeSequence()},
        "scheduled": [planned],
        "line_code": "500T",
        "now": now,
    }
    arrivals, diagnostics = estimate_arrivals(**common, timetable={"500T_G_D0": (trip(),)})
    assert arrivals[0].direction == "4.LEVENT METRO"
    assert diagnostics["schedule_source"] == "gtfs_stop_times"

    arrivals, diagnostics = estimate_arrivals(**common)
    assert arrivals[0].direction == "Planned"
    assert diagnostics["schedule_source"] == "iett_planned"

    arrivals, diagnostics = estimate_arrivals(**{**common, "scheduled": []})
    assert arrivals == []
    assert diagnostics["mode"] == "unknown"


def test_only_the_lines_own_route_variants_are_used() -> None:
    now = moment()
    arrivals, diagnostics = estimate_arrivals(
        buses=[stale_bus(now)],
        target=TARGET,
        sequences={"8A_G_D0": FakeSequence()},
        timetable={"8A_G_D0": (trip("8A_G_D0"),)},
        line_code="500T",
        now=now,
    )

    assert arrivals == []
    assert diagnostics["mode"] == "unknown"


def test_post_midnight_departures_roll_to_the_next_day() -> None:
    now = moment(23, 50)
    after_midnight = trip(departure="24:00:00")
    arrivals, _ = estimate_arrivals(
        buses=[stale_bus(now)],
        target=TARGET,
        sequences={"500T_G_D0": FakeSequence()},
        timetable={"500T_G_D0": (after_midnight,)},
        now=now,
    )

    assert arrivals[0].eta_minutes == 10.0


async def test_the_arrival_tool_hands_the_estimator_the_timetable_and_the_callers_stale_limit(ctx, monkeypatch) -> None:
    """G12 wiring: ``iett_next_arrivals`` passes the GTFS timetable, the service days, the line code
    and the caller's stale limit to the estimator, and loads the tables once per facade."""
    import ibb_mcp.eta as eta_module
    from ibb_mcp.tools import Nabiz

    seen: list[dict] = []

    def spy(**kwargs):
        seen.append(kwargs)
        return estimate_arrivals(**kwargs)

    monkeypatch.setattr(eta_module, "estimate_arrivals", spy)
    app = Nabiz(ctx)
    served = await app.iett_next_arrivals(line_code="500t", stop="220641", limit=3, stale_after_s=240)
    await app.iett_next_arrivals(line_code="500T", stop="220641", limit=3)

    first, second = seen
    assert first["line_code"] == "500T"
    assert first["params"].stale_after_s == 240.0 and served.data["diagnostics"]["stale_after_s"] == 240.0
    assert second["params"].stale_after_s == EtaParams().stale_after_s
    # The mini GTFS has trips and stop times but no calendar.csv: timetables, and no day filter.
    assert any(code.startswith("500T_") for code in first["timetable"])
    assert first["service_days"] == {}
    assert first["timetable"] is second["timetable"], "the tables are read once per facade"
    assert served.data["diagnostics"]["mode"] in {"live", "schedule", "unknown"}
