import dataclasses

import pytest
from conftest import offline_settings

from ibb_mcp.gtfs import (
    TIMETABLE_CACHE_NAME,
    build_route_timetables,
    load_route_timetables,
    load_service_days,
)


def test_route_timetables_use_terminal_times_and_cache_in_fixture_copy() -> None:
    settings = offline_settings()
    timetables = build_route_timetables(settings)

    assert len(timetables) == 6
    trip = next(trip for trips in timetables.values() for trip in trips if trip.trip_id == "445950218")
    assert trip.route_code == "500T_D_D0"
    assert trip.departure_time == "24:00:00"
    assert trip.arrival_time == "26:16:00"
    assert trip.stop_count == 66
    assert trip.service_id == "6"
    assert trip.headsign == "ŞİFA SONDURAK"

    cache_path = settings.gtfs_dir / TIMETABLE_CACHE_NAME
    assert load_route_timetables(settings) == timetables
    assert load_route_timetables(settings) == timetables
    assert cache_path.is_file()


def test_the_mini_fixture_has_no_calendar() -> None:
    assert load_service_days(offline_settings()) == {}


@pytest.mark.parametrize("delimiter", [";", ","])
def test_service_days_accept_both_gtfs_calendar_delimiters(tmp_path, delimiter: str) -> None:
    settings = dataclasses.replace(offline_settings(), gtfs_dir=tmp_path)
    headings = ("service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    rows = (
        ("weekday", "1", "1", "1", "1", "1", "0", "0"),
        ("saturday", "0", "0", "0", "0", "0", "1", "0"),
        ("sunday", "0", "0", "0", "0", "0", "0", "1"),
    )
    content = delimiter.join(headings) + "\n" + "\n".join(delimiter.join(row) for row in rows) + "\n"
    (tmp_path / "calendar.csv").write_text(content, encoding="utf-8")

    assert load_service_days(settings) == {
        "weekday": frozenset({"I"}),
        "saturday": frozenset({"C"}),
        "sunday": frozenset({"P"}),
    }
