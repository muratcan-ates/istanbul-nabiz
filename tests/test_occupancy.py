"""Tests for the history-backed "genelde bu saatte ne kadar yer olur" profile.

The interesting assertions here are the *refusals*. Anyone can test that a median of five
numbers is the third one; the value of this module is that it declines to answer when the
history behind a cell is one afternoon, a closed shutter, or nothing at all — and that the
decline carries a Turkish reason a person can act on. Each guard therefore gets a test that
would fail if the guard were quietly removed.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest

from ibb_mcp.occupancy import (
    MIN_SAMPLES,
    MIN_SPAN_HOURS,
    SCHEMA,
    OccupancyProfile,
    build_profile,
    load_profile,
    lookup,
    lookup_weekday,
    profile_path,
    save_profile,
    to_istanbul,
    weekday_class,
    weekday_class_of,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# 2026-09-01 is a Tuesday, 2026-09-05 a Saturday, 2026-09-06 a Sunday. Every fixture below
# is anchored to those so the weekday class of a row is obvious from its date.
TUESDAY = dt.date(2026, 9, 1)
WEDNESDAY = dt.date(2026, 9, 2)
SATURDAY = dt.date(2026, 9, 5)
SUNDAY = dt.date(2026, 9, 6)


def row(
    *,
    park_id: int = 501,
    day: dt.date = TUESDAY,
    hour_utc: int = 15,
    minute: int = 0,
    occupancy: float | None = 50.0,
    is_open: bool = True,
    district: str = "KADIKÖY",
    capacity: int = 200,
) -> dict:
    """One ``ispark_snapshot`` lake row, in the shape the collector actually writes.

    ``hour_utc`` is deliberately in UTC: İstanbul is UTC+3, so a row written at 15:00Z
    belongs in the 18:00 cell, and the tests should have to get that right.
    """
    stamp = dt.datetime(day.year, day.month, day.day, hour_utc, minute, tzinfo=dt.UTC)
    return {
        "park_id": park_id,
        "ts_utc": stamp.isoformat().replace("+00:00", "Z"),
        "snapshot_ts_utc": stamp.isoformat().replace("+00:00", "Z"),
        "capacity": capacity,
        "empty": int(capacity * (100 - (occupancy or 0)) / 100),
        "occupancy_pct": occupancy,
        "is_open": is_open,
        "district": district,
    }


def two_day_rows(**overrides) -> list[dict]:
    """Five open readings for one cell spread over a Tuesday and a Wednesday.

    This is the smallest history that passes every guard: 5 >= MIN_SAMPLES, and the span
    between the first and last reading is a day, so it cannot be a single sitting.
    """
    values_by_day = {TUESDAY: [40.0, 50.0, 60.0], WEDNESDAY: [45.0, 55.0]}
    rows: list[dict] = []
    for day, values in values_by_day.items():
        for index, value in enumerate(values):
            rows.append(row(day=day, minute=index * 10, occupancy=value, **overrides))
    return rows


# --- weekday classification ----------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (dt.date(2026, 8, 31), "weekday"),  # Monday
        (TUESDAY, "weekday"),
        (WEDNESDAY, "weekday"),
        (dt.date(2026, 9, 3), "weekday"),  # Thursday
        (dt.date(2026, 9, 4), "weekday"),  # Friday
        (SATURDAY, "saturday"),
        (SUNDAY, "sunday"),
    ],
)
def test_weekday_class_splits_the_week_into_three_demand_curves(day: dt.date, expected: str) -> None:
    assert weekday_class(dt.datetime(day.year, day.month, day.day, 12, 0)) == expected


def test_saturday_and_sunday_are_separate_cells_from_the_working_week() -> None:
    """A Saturday reading must not leak into the weekday cell, or into Sunday's."""
    rows = [row(day=TUESDAY), row(day=SATURDAY), row(day=SUNDAY)]
    profile = build_profile(rows)
    assert {key[1] for key in profile.cells} == {"weekday", "saturday", "sunday"}
    assert all(cell.samples == 1 for cell in profile.cells.values())


def test_naive_datetimes_are_read_as_istanbul_wall_clock() -> None:
    naive = dt.datetime(2026, 9, 1, 18, 0)
    assert to_istanbul(naive).hour == 18
    # The same instant expressed in UTC must land on the same local hour.
    assert to_istanbul(dt.datetime(2026, 9, 1, 15, 0, tzinfo=dt.UTC)).hour == 18


def test_rows_are_bucketed_by_istanbul_hour_not_utc_hour() -> None:
    profile = build_profile([row(hour_utc=15)])
    assert (501, "weekday", 18) in profile.cells
    assert (501, "weekday", 15) not in profile.cells


# --- the happy path ------------------------------------------------------------------


def test_a_cell_seen_on_two_days_reports_median_and_quartiles() -> None:
    profile = build_profile(two_day_rows())
    # 2026-09-15 is a Tuesday; the question is about 18:00 local.
    answer = profile.lookup(501, dt.datetime(2026, 9, 15, 18, 30))

    assert answer["available"] is True
    assert answer["window"] == "Salı 18:00"
    assert answer["weekday_class"] == "weekday"
    assert answer["samples"] == 5
    assert answer["observed_days"] == 2
    assert answer["median_occupancy_pct"] == 50.0
    assert answer["p25_occupancy_pct"] == 45.0
    assert answer["p75_occupancy_pct"] == 55.0
    assert answer["district"] == "KADIKÖY"
    assert "%50" in answer["note"]


def test_an_answer_never_borrows_a_neighbouring_hour() -> None:
    """17:00 has no history of its own; 18:00's median must not be presented as its.

    Interpolating here would be the single easiest way to make the feature look finished
    and the single most dishonest, because nothing in the output would say it happened.
    """
    profile = build_profile(two_day_rows())
    answer = profile.lookup(501, dt.datetime(2026, 9, 15, 17, 30))
    assert answer["available"] is False
    assert answer["reason"] == "no_observations"
    assert "median_occupancy_pct" not in answer


def test_the_weekday_index_entry_point_matches_the_datetime_one() -> None:
    """``analytics.occupancy_profile`` is keyed by weekday index, so both doors must agree."""
    profile = build_profile(two_day_rows())
    by_moment = profile.lookup(501, dt.datetime(2026, 9, 15, 18, 30))  # a Tuesday
    by_index = profile.lookup_weekday(501, 1, 18)  # Monday is 0, so 1 is Tuesday

    assert by_index["available"] is by_moment["available"] is True
    assert by_index["window"] == by_moment["window"] == "Salı 18:00"
    assert by_index["median_occupancy_pct"] == by_moment["median_occupancy_pct"]
    # Only the moment-shaped call knows a date, so only it reports one.
    assert by_index["at_local"] is None and by_moment["at_local"] is not None


def test_weekday_class_of_agrees_with_the_datetime_form() -> None:
    for day in (TUESDAY, SATURDAY, SUNDAY):
        moment = dt.datetime(day.year, day.month, day.day, 9, 0)
        assert weekday_class_of(moment.weekday()) == weekday_class(moment)


def test_module_level_lookup_by_weekday_refuses_without_a_profile(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NABIZ_OCCUPANCY_PROFILE", str(tmp_path / "absent.json"))
    answer = lookup_weekday(501, 5, 12)
    assert answer["available"] is False
    assert answer["reason"] == "no_profile"
    assert answer["weekday_class"] == "saturday"
    assert answer["window"] == "Cumartesi 12:00"


# --- the guards ----------------------------------------------------------------------


def test_a_cell_below_min_samples_is_refused_with_a_turkish_reason() -> None:
    """Two readings, but on two different days, so only the sample floor can reject it."""
    rows = [row(day=TUESDAY, occupancy=40.0), row(day=WEDNESDAY, occupancy=60.0)]
    answer = build_profile(rows).lookup(501, dt.datetime(2026, 9, 15, 18, 0))

    assert answer["available"] is False
    assert answer["reason"] == "too_few_samples"
    assert answer["samples"] == 2
    assert f"en az {MIN_SAMPLES}" in answer["note"]
    assert "median_occupancy_pct" not in answer


def test_one_afternoon_is_refused_however_many_samples_it_holds() -> None:
    """Six readings of a single Tuesday evening are six views of one Tuesday evening."""
    rows = [row(day=TUESDAY, minute=index * 10, occupancy=50.0 + index) for index in range(6)]
    profile = build_profile(rows)
    cell = profile.cell(501, "weekday", 18)

    assert cell is not None
    assert cell.samples == 6 > MIN_SAMPLES  # the sample floor alone would have let it through
    assert cell.span_hours < MIN_SPAN_HOURS
    assert cell.observed_days == 1

    answer = profile.lookup(501, dt.datetime(2026, 9, 15, 18, 0))
    assert answer["available"] is False
    assert answer["reason"] == "single_window"
    assert "tek bir gün" in answer["note"]


def test_the_span_guard_passes_once_a_second_day_arrives() -> None:
    """The same six readings plus one on the next day become a usable cell."""
    rows = [row(day=TUESDAY, minute=index * 10, occupancy=50.0 + index) for index in range(6)]
    assert build_profile(rows).lookup(501, dt.datetime(2026, 9, 15, 18, 0))["available"] is False

    rows.append(row(day=WEDNESDAY, occupancy=52.0))
    answer = build_profile(rows).lookup(501, dt.datetime(2026, 9, 15, 18, 0))
    assert answer["available"] is True
    assert answer["observed_days"] == 2
    assert answer["span_hours"] >= MIN_SPAN_HOURS


def test_a_lot_closed_every_time_we_looked_is_reported_as_closed_not_as_empty() -> None:
    rows = [row(day=TUESDAY, minute=index * 10, occupancy=0.0, is_open=False) for index in range(5)]
    rows += [row(day=WEDNESDAY, minute=index * 10, occupancy=0.0, is_open=False) for index in range(5)]
    answer = build_profile(rows).lookup(501, dt.datetime(2026, 9, 15, 18, 0))

    assert answer["available"] is False
    assert answer["reason"] == "closed"
    assert "kapalı" in answer["note"]


def test_closed_readings_are_excluded_from_the_median_but_counted() -> None:
    """A shut lot keeps publishing its last count; that number describes the shutter."""
    rows = two_day_rows()
    rows.append(row(day=WEDNESDAY, minute=50, occupancy=100.0, is_open=False))
    profile = build_profile(rows)
    cell = profile.cell(501, "weekday", 18)

    assert cell is not None
    assert cell.samples == 5  # the closed reading is not a sample
    assert cell.closed_samples == 1
    assert cell.median == 50.0  # unchanged by the 100.0 the shut lot reported


def test_a_missing_is_open_field_is_treated_as_open() -> None:
    """Early snapshots predate the field; assuming "closed" would delete that history."""
    rows = [dict(item) for item in two_day_rows()]
    for item in rows:
        item.pop("is_open")
    assert build_profile(rows).lookup(501, dt.datetime(2026, 9, 15, 18, 0))["available"] is True


def test_malformed_rows_are_skipped_without_losing_the_good_ones() -> None:
    rows = two_day_rows() + [
        {"park_id": 501},  # no timestamp
        {"ts_utc": "2026-09-01T15:00:00Z"},  # no park id
        {"park_id": "not-a-number", "ts_utc": "2026-09-01T15:00:00Z", "occupancy_pct": 10},
        {"park_id": 501, "ts_utc": "yesterday afternoon", "occupancy_pct": 10},
    ]
    profile = build_profile(rows)
    assert profile.rows_read == 5
    assert profile.lookup(501, dt.datetime(2026, 9, 15, 18, 0))["available"] is True


# --- persistence ---------------------------------------------------------------------


def test_profile_survives_a_save_load_round_trip(tmp_path: pathlib.Path) -> None:
    original = build_profile(two_day_rows())
    target = save_profile(original, tmp_path / "occupancy_profile.json")
    restored = load_profile(path=target)

    assert restored is not None
    assert restored.cells == original.cells
    assert restored.parks == original.parks
    assert restored.rows_read == original.rows_read
    assert restored.min_samples == original.min_samples
    assert restored.min_span_hours == original.min_span_hours
    assert restored.lookup(501, dt.datetime(2026, 9, 15, 18, 0)) == original.lookup(501, dt.datetime(2026, 9, 15, 18, 0))


def test_the_written_file_is_self_describing(tmp_path: pathlib.Path) -> None:
    """A reader must be able to decode the positional cell rows from the file alone."""
    target = save_profile(build_profile(two_day_rows()), tmp_path / "p.json")
    payload = json.loads(target.read_text(encoding="utf-8"))

    assert payload["schema"] == SCHEMA
    assert payload["cell_fields"][0] == "samples"
    assert len(payload["cells"]["501:weekday:18"]) == len(payload["cell_fields"])


def test_missing_profile_file_yields_a_refusal_not_a_crash(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The normal state of a fresh clone before the collector has run."""
    absent = tmp_path / "never-built.json"
    assert load_profile(path=absent) is None

    monkeypatch.setenv("NABIZ_OCCUPANCY_PROFILE", str(absent))
    answer = lookup(501, dt.datetime(2026, 9, 15, 18, 0))
    assert answer["available"] is False
    assert answer["reason"] == "no_profile"
    assert "build_profiles.py" in answer["note"]
    assert answer["window"] == "Salı 18:00"


def test_a_corrupt_profile_file_is_logged_and_ignored(tmp_path: pathlib.Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json at all", encoding="utf-8")
    assert load_profile(path=broken) is None


def test_a_profile_from_an_older_schema_is_rejected() -> None:
    with pytest.raises(ValueError, match="schema"):
        OccupancyProfile.from_dict({"schema": "nabiz.occupancy_profile/0", "cells": {}})


def test_the_cached_profile_is_reparsed_when_the_file_changes(tmp_path: pathlib.Path) -> None:
    target = tmp_path / "p.json"
    save_profile(build_profile(two_day_rows()), target)
    assert load_profile(path=target) is not None

    save_profile(build_profile([row(day=SUNDAY), row(day=SUNDAY, minute=10)]), target)
    reloaded = load_profile(path=target)
    assert reloaded is not None
    assert {key[1] for key in reloaded.cells} == {"sunday"}


def test_profile_path_follows_the_reference_directory_and_the_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NABIZ_OCCUPANCY_PROFILE", raising=False)
    assert profile_path().name == "occupancy_profile.json"
    assert profile_path().parent.name == "reference"

    monkeypatch.setenv("NABIZ_OCCUPANCY_PROFILE", "/tmp/elsewhere.json")
    assert profile_path() == pathlib.Path("/tmp/elsewhere.json")


# --- coverage reporting --------------------------------------------------------------


def test_coverage_counts_separate_the_sample_floor_from_the_span_floor() -> None:
    """The distinction the build report hangs on: "enough rows" is not "enough days"."""
    rows = [row(park_id=1, day=TUESDAY, minute=index * 10) for index in range(6)]  # one sitting
    rows += two_day_rows(park_id=2)  # two days
    coverage = build_profile(rows).coverage()

    assert coverage["parks_with_any_cell"] == 2
    assert coverage["parks_with_usable_cell"] == 1
    assert coverage["cells_meeting_min_samples"] == 2
    assert coverage["cells_usable"] == 1
    assert coverage["observation_span_hours"] > 24


def test_an_empty_profile_says_so_rather_than_reporting_zeroes() -> None:
    profile = build_profile([])
    assert profile.coverage()["cells"] == 0
    assert "boş" in profile.coverage_note()
    assert profile.lookup(501, dt.datetime(2026, 9, 15, 18, 0))["available"] is False


def test_build_profile_honours_custom_thresholds() -> None:
    """The integrator can tighten the guards without editing the module."""
    rows = [row(day=TUESDAY, minute=index * 10) for index in range(6)]
    relaxed = build_profile(rows, min_span_hours=0.0)
    assert relaxed.lookup(501, dt.datetime(2026, 9, 15, 18, 0))["available"] is True

    strict = build_profile(two_day_rows(), min_samples=99)
    assert strict.lookup(501, dt.datetime(2026, 9, 15, 18, 0))["reason"] == "too_few_samples"


# --- the committed artefact ----------------------------------------------------------


def test_the_checked_in_profile_parses_if_it_has_been_built() -> None:
    """Guards against committing a profile a future schema change cannot read."""
    target = REPO_ROOT / "data" / "reference" / "occupancy_profile.json"
    if not target.exists():
        pytest.skip("occupancy_profile.json has not been built in this checkout")

    profile = load_profile(path=target)
    assert profile is not None
    assert profile.rows_read > 0
    answer = profile.lookup(next(iter(profile.parks)), dt.datetime(2026, 9, 15, 18, 0))
    assert isinstance(answer["available"], bool)
    assert answer["note"]
