"""Tests for per-line reliability statistics.

The fixtures are synthetic on purpose. Real snapshots cannot answer "is this cv right?",
because the true headway of a real line at 14:00 last Tuesday is unknown — that is the
whole reason the module exists. A generated service whose headway *is* known by
construction can: a metronome line must come out at cv 0, a line dispatched in pairs must
come out near 1, and everything in between has to fall where the arithmetic says.

:func:`metronome` builds that generator. One vehicle per departure, one stop advanced per
tick, so every stop passage is witnessed and the capture rate is 1.0 — which isolates the
statistics from the sampling artefact that dominates the real archive.
"""

from __future__ import annotations

import datetime as dt
import json
import math

import pytest

from ibb_mcp.gtfs import RouteStopSequence
from ibb_mcp.models import ISTANBUL_TZ
from ibb_mcp.reliability import (
    CV_BUNCHED,
    CV_REGULAR,
    LABEL_BUNCHED,
    LABEL_REGULAR,
    LABEL_SOMEWHAT,
    MAX_HEADWAY_MINUTES,
    MIN_SAMPLES,
    MIN_STOPS_FOR_CV,
    BunchingVerdict,
    LineHourStats,
    ReliabilityTable,
    arrival_events,
    build_table,
    bunching_score,
    compute_line_stats,
    describe_cell,
    load_table,
    sampling_cv_floor,
    save_table,
)

LINE = "T1"
ROUTE = "T1_G_D0"
STOPS = tuple(f"S{i:02d}" for i in range(24))
SEQUENCES = {ROUTE: RouteStopSequence(route_code=ROUTE, stop_codes=STOPS)}
#: 11:00 İstanbul time on a Monday, so every generated arrival lands in one local hour.
START = dt.datetime(2026, 9, 14, 8, 0, tzinfo=dt.UTC)


def metronome(
    departures_min: list[float],
    *,
    tick_minutes: float = 1.0,
    minutes_per_stop: float = 1.0,
    ticks: int = 60,
    line: str = LINE,
    route: str = ROUTE,
    stops: tuple[str, ...] = STOPS,
    start: dt.datetime = START,
    with_coords: bool = True,
) -> list[dict]:
    """Snapshots for a service whose headways are exactly ``departures_min`` apart.

    Vehicle *i* leaves the first stop ``departures_min[i]`` minutes after ``start`` and
    takes ``minutes_per_stop`` to reach each next stop, so the gap between two vehicles at
    every stop equals the gap between their departures. That makes the expected median
    headway and cv exact. Sampling faster than the buses move (``tick_minutes`` below
    ``minutes_per_stop``) witnesses every passage; sampling slower misses some, which is
    how the capture rate is exercised.
    """
    rows: list[dict] = []
    for index, offset in enumerate(departures_min):
        door = f"C-{index:03d}"
        for step in range(ticks):
            stamp = start + dt.timedelta(minutes=step * tick_minutes)
            position = int((step * tick_minutes - offset) // minutes_per_stop)
            if position < 0 or position >= len(stops):
                continue
            row = {
                "line_code": line,
                "route_code": route,
                "door_no": door,
                "nearest_stop_code": stops[position],
                "direction": "TEST",
                "ts_utc": stamp.isoformat().replace("+00:00", "Z"),
                "snapshot_ts_utc": stamp.isoformat().replace("+00:00", "Z"),
            }
            if with_coords:
                # ~1 km of longitude per stop at 41°N; enough for a stable km/h.
                row["lat"] = 41.0
                row["lon"] = 29.0 + position * 0.0119
            rows.append(row)
    return rows


def one_cell(rows: list[dict], hour: int | None = None) -> LineHourStats:
    cells = compute_line_stats(rows, SEQUENCES)
    hour = START.astimezone(ISTANBUL_TZ).hour if hour is None else hour
    return cells[(LINE, hour)]


# --------------------------------------------------------------------------------------
# headway reconstruction
# --------------------------------------------------------------------------------------
def test_headway_of_an_evenly_dispatched_service_is_the_dispatch_interval() -> None:
    cell = one_cell(metronome([0, 10, 20, 30, 40, 50]))
    assert cell.available is True
    assert cell.median_headway_min == 10.0
    assert cell.headway_cv == 0.0
    assert cell.bunching_label == LABEL_REGULAR
    assert cell.vehicles_seen == 6


def test_buses_dispatched_in_pairs_read_as_bunching() -> None:
    # 1 minute apart, then a 19-minute hole: the textbook convoy.
    cell = one_cell(metronome([0, 1, 20, 21, 40, 41]))
    assert cell.available is True
    assert cell.bunching_label == LABEL_BUNCHED
    assert cell.headway_cv > 0.9
    assert cell.bunching_score == pytest.approx(min(cell.headway_cv, 1.0))


def test_headway_cv_matches_the_textbook_formula() -> None:
    """cv is std/mean of the gaps; with a 5/15 alternation that is exactly sqrt(2)/2."""
    cell = one_cell(metronome([0, 5, 20, 25, 40, 45]))
    gaps = [5.0, 15.0, 5.0, 15.0]
    expected = (sum((g - 10.0) ** 2 for g in gaps) / (len(gaps) - 1)) ** 0.5 / 10.0
    assert cell.headway_cv == pytest.approx(round(expected, 3), abs=0.06)


def test_consecutive_sightings_at_one_stop_collapse_into_a_single_arrival() -> None:
    """A bus loitering at a stop for four ticks arrived once, not four times."""
    rows = []
    for step in range(4):
        stamp = START + dt.timedelta(minutes=step)
        rows.append(
            {
                "line_code": LINE, "route_code": ROUTE, "door_no": "C-001",
                "nearest_stop_code": "S05", "direction": "TEST",
                "snapshot_ts_utc": stamp.isoformat().replace("+00:00", "Z"),
            }
        )
    events = arrival_events(rows, SEQUENCES)
    assert events[(LINE, "G", "S05")] == [(START, "C-001")]


def test_the_two_directions_of_a_line_are_never_mixed() -> None:
    """Same stop code, opposite runs: two series, not one interleaved one."""
    outbound = metronome([0, 10, 20, 30, 40, 50])
    inbound = [dict(row, route_code="T1_D_D0", door_no="D" + row["door_no"]) for row in outbound]
    events = arrival_events(outbound + inbound, {**SEQUENCES, "T1_D_D0": SEQUENCES[ROUTE]})
    assert (LINE, "G", "S10") in events
    assert (LINE, "D", "S10") in events
    assert {door for _, door in events[(LINE, "G", "S10")]}.isdisjoint(
        {door for _, door in events[(LINE, "D", "S10")]}
    )


def test_the_same_vehicle_returning_is_a_cycle_time_not_a_headway() -> None:
    """One bus alone can never produce a headway, however often it is seen."""
    rows = metronome([0])
    rows += [dict(row, snapshot_ts_utc=(START + dt.timedelta(minutes=90 + i)).isoformat().replace("+00:00", "Z"))
             for i, row in enumerate(metronome([0], ticks=10))]
    cells = compute_line_stats(rows, SEQUENCES)
    assert all(cell.samples == 0 for cell in cells.values())


def _sighting(minutes: float, door: str, stop: str = "S05") -> dict:
    stamp = START + dt.timedelta(minutes=minutes)
    return {
        "line_code": LINE, "route_code": ROUTE, "door_no": door, "nearest_stop_code": stop,
        "direction": "TEST", "snapshot_ts_utc": stamp.isoformat().replace("+00:00", "Z"),
    }


def test_a_gap_spanning_a_collector_outage_is_discarded() -> None:
    """A wait we did not watch is our hole, not the rider's.

    Four buses reach one stop at minutes 0, 5, 45 and 50. Whether the 40-minute gap in the
    middle is a headway depends entirely on whether the collector was awake for it, so the
    same arrivals are scored twice: once with nothing collected in between, once with the
    ticks filled in.
    """
    arrivals = [_sighting(0, "C-000"), _sighting(5, "C-001"), _sighting(45, "C-002"), _sighting(50, "C-003")]
    events = arrival_events(arrivals, SEQUENCES)
    assert len(events[(LINE, "G", "S05")]) == 4

    outage = compute_line_stats(arrivals, SEQUENCES)[(LINE, 11)]
    assert outage.samples == 2  # 0->5 and 45->50; the 40-minute hole is not a wait

    # Same arrivals, but the collector kept ticking (an idle bus parked elsewhere on the
    # line), so the 40-minute gap is now something a rider really endured.
    watched = arrivals + [_sighting(minute, "C-900", stop="S00") for minute in range(0, 55, 3)]
    covered = compute_line_stats(watched, SEQUENCES)[(LINE, 11)]
    assert covered.samples == 3  # the same two, plus the 40-minute wait that is now evidence


def test_an_absurd_gap_is_not_a_headway() -> None:
    assert MAX_HEADWAY_MINUTES == 120.0
    rows = metronome([0, 10], ticks=200, tick_minutes=1.0, stops=tuple(f"S{i:02d}" for i in range(200)))
    sequences = {ROUTE: RouteStopSequence(route_code=ROUTE, stop_codes=tuple(f"S{i:02d}" for i in range(200)))}
    cells = compute_line_stats(rows, sequences)
    assert all((cell.median_headway_min or 0) <= MAX_HEADWAY_MINUTES for cell in cells.values())


# --------------------------------------------------------------------------------------
# bunching score and thresholds
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("cv", "label"),
    [
        (0.0, LABEL_REGULAR),
        (0.299, LABEL_REGULAR),
        (CV_REGULAR, LABEL_SOMEWHAT),          # the band is closed below, open above
        (0.599, LABEL_SOMEWHAT),
        (CV_BUNCHED, LABEL_BUNCHED),
        (3.0, LABEL_BUNCHED),
    ],
)
def test_bunching_thresholds_are_exactly_where_they_are_documented(cv: float, label: str) -> None:
    assert bunching_score(cv).label == label


def test_bunching_score_saturates_at_one_and_never_exceeds_it() -> None:
    assert bunching_score(0.42) == BunchingVerdict(cv=0.42, score=0.42, label=LABEL_SOMEWHAT)
    assert bunching_score(1.0).score == 1.0
    assert bunching_score(7.5).score == 1.0  # worse than random is not more informative


def test_a_negative_cv_is_a_caller_bug_and_is_refused() -> None:
    with pytest.raises(ValueError, match="negative"):
        bunching_score(-0.01)


def test_sampling_floor_is_the_cv_that_missed_passages_alone_would_produce() -> None:
    assert sampling_cv_floor(1.0) == 0.0                      # see everything, invent nothing
    assert sampling_cv_floor(0.5) == pytest.approx(math.sqrt(0.5), abs=5e-4)
    assert sampling_cv_floor(0.0) == 1.0                      # see nothing, look Poisson
    assert sampling_cv_floor(1.5) == 0.0                      # nonsense input cannot go imaginary


def test_full_capture_leaves_no_sampling_floor_to_clear() -> None:
    cell = one_cell(metronome([0, 1, 20, 21, 40, 41]))
    assert cell.stop_capture_rate == 1.0
    assert cell.cv_sampling_floor == 0.0
    assert cell.cv_exceeds_floor is True


def test_capture_rate_measures_the_passages_the_sampling_missed() -> None:
    """Sampled every third stop, two passages in three are never witnessed."""
    cell = one_cell(metronome([0, 9, 18, 27, 36, 45], tick_minutes=3.0, minutes_per_stop=1.0, ticks=20))
    assert cell.stop_capture_rate == pytest.approx(1 / 3, abs=0.02)
    assert cell.cv_sampling_floor == pytest.approx(math.sqrt(1 - 1 / 3), abs=0.02)


# --------------------------------------------------------------------------------------
# guards: what the module refuses to say
# --------------------------------------------------------------------------------------
def test_too_few_headways_refuses_with_a_reason_and_no_numbers() -> None:
    cell = one_cell(metronome([0, 25], ticks=30))
    assert cell.available is False
    assert cell.median_headway_min is None
    assert cell.headway_cv is None
    assert cell.bunching_label is None
    assert str(MIN_SAMPLES) in (cell.reason or "") or "araç" in (cell.reason or "")


def test_a_single_vehicle_refuses_before_anything_else() -> None:
    cell = one_cell(metronome([0]))
    assert cell.available is False
    assert "araç" in (cell.reason or "")
    assert cell.samples == 0


def test_headways_at_too_few_stops_refuse_the_cv() -> None:
    """Plenty of gaps, but all at one stop: a median of one cv is not a measurement."""
    short_route = tuple(f"S{i:02d}" for i in range(3))
    sequences = {ROUTE: RouteStopSequence(route_code=ROUTE, stop_codes=short_route)}
    rows = metronome([i * 4 for i in range(14)], stops=short_route, ticks=60)
    cells = compute_line_stats(rows, sequences)
    cell = cells[(LINE, START.astimezone(ISTANBUL_TZ).hour)]
    assert cell.available is False
    assert cell.stops_measured <= MIN_STOPS_FOR_CV
    assert "durak" in (cell.reason or "")


def test_empty_input_produces_no_cells_and_no_exception() -> None:
    assert compute_line_stats([], SEQUENCES) == {}
    assert compute_line_stats([]) == {}
    assert arrival_events([]) == {}
    table = build_table([])
    assert table.cells == []
    assert table.observed_from is None and table.span_hours is None


def test_rows_missing_the_fields_we_need_are_skipped_not_guessed() -> None:
    rows = metronome([0, 10, 20, 30, 40, 50])
    broken = [dict(row, nearest_stop_code=None) for row in rows[:50]]
    broken += [{"line_code": LINE, "door_no": "C-999"}]           # no timestamp at all
    broken += [dict(row, snapshot_ts_utc="not a timestamp") for row in rows[50:60]]
    cell = one_cell(rows + broken)
    assert cell.available is True  # the good rows still answer
    assert cell.median_headway_min == 10.0


def test_without_stop_sequences_the_module_degrades_instead_of_failing() -> None:
    cells = compute_line_stats(metronome([0, 10, 20, 30, 40, 50]), None)
    cell = cells[(LINE, START.astimezone(ISTANBUL_TZ).hour)]
    assert cell.samples > 0
    assert cell.stops_per_hour_median is None      # needs the sequence
    assert cell.stop_capture_rate is None          # and so does the capture rate


def test_speed_is_reported_only_when_coordinates_are_present() -> None:
    with_coords = one_cell(metronome([0, 10, 20, 30, 40, 50]))
    without = one_cell(metronome([0, 10, 20, 30, 40, 50], with_coords=False))
    assert with_coords.median_speed_kmh is not None and with_coords.median_speed_kmh > 0
    assert with_coords.stops_per_hour_median == pytest.approx(60.0, abs=1.0)
    assert without.median_speed_kmh is None
    assert without.stops_per_hour_median == pytest.approx(60.0, abs=1.0)


# --------------------------------------------------------------------------------------
# the table: persistence, span, lookup
# --------------------------------------------------------------------------------------
def test_the_table_records_the_span_it_was_measured_over(tmp_path) -> None:
    table = build_table(metronome([0, 10, 20, 30, 40, 50]), SEQUENCES)
    assert table.observed_from == START
    assert table.span_hours == pytest.approx(1.0, abs=0.05)
    assert table.days_covered == ["2026-09-14"]
    assert table.snapshots_read > 0


def test_save_and_load_round_trip_preserves_every_published_number(tmp_path) -> None:
    table = build_table(metronome([0, 1, 20, 21, 40, 41]), SEQUENCES)
    path = save_table(table, tmp_path / "line_reliability.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["observation_span"]["days_covered"] == ["2026-09-14"]
    assert payload["thresholds"]["cv_bunched"] == CV_BUNCHED

    restored = load_table(path)
    assert restored is not None
    assert restored.observed_from == table.observed_from
    assert [cell.to_dict() for cell in restored.cells] == [cell.to_dict() for cell in table.cells]


def test_a_missing_or_corrupt_table_loads_as_none_rather_than_raising(tmp_path) -> None:
    assert load_table(tmp_path / "absent.json") is None
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert load_table(corrupt) is None


def test_describe_cell_always_answers_in_turkish_even_when_it_cannot_answer() -> None:
    table = build_table(metronome([0, 10, 20, 30, 40, 50]), SEQUENCES)
    hour = START.astimezone(ISTANBUL_TZ).hour

    published = describe_cell(table, LINE, hour)
    assert published["available"] is True
    assert "dk ortanca sefer aralığı" in published["note"]
    assert published["observation_window"]["days_covered"] == ["2026-09-14"]

    unknown_hour = describe_cell(table, LINE, (hour + 5) % 24)
    assert unknown_hour["available"] is False and "gözlem yok" in unknown_hour["note"]

    unknown_line = describe_cell(table, "999X", hour)
    assert unknown_line["available"] is False and LINE in unknown_line["note"]

    assert describe_cell(None, LINE, hour)["available"] is False


def test_no_output_field_can_carry_a_number_plate_or_any_personal_data() -> None:
    """KVKK, and NABIZ.md 1.3: the vehicle identifier is a door number, full stop."""
    table = build_table(metronome([0, 1, 20, 21, 40, 41]), SEQUENCES)
    published = json.dumps(table.to_dict(), ensure_ascii=False)
    assert "plaka" not in published.lower()
    assert "C-000" not in published  # not even the door number leaves the module
    assert set(LineHourStats("x", 0, False).to_dict()) == {
        "line_code", "hour", "available", "samples", "vehicles_seen", "stops_measured",
        "stops_with_cv", "days", "median_headway_min", "headway_cv", "bunching_score",
        "bunching_label", "stops_per_hour_median", "median_speed_kmh", "stop_capture_rate",
        "cv_sampling_floor", "cv_exceeds_floor", "reason",
    }


def test_cells_are_keyed_by_istanbul_local_hour_not_utc() -> None:
    """UTC+3 is the whole point: 08:00Z is 11:00 for the rider asking the question."""
    cells = compute_line_stats(metronome([0, 10, 20, 30, 40, 50]), SEQUENCES)
    assert (LINE, 11) in cells
    assert (LINE, 8) not in cells


def test_the_table_round_trips_through_from_dict_with_unknown_keys_ignored() -> None:
    table = ReliabilityTable.from_dict(
        {
            "schema_version": 1,
            "generated_at": "2026-09-13T10:00:00Z",
            "observation_span": {"from": "2026-09-13T07:00:00Z", "to": "2026-09-13T09:00:00Z", "days_covered": ["x"]},
            "cells": [{"line_code": "500T", "hour": 12, "available": False, "reason": "yok", "unexpected": 1}],
        }
    )
    assert table.span_hours == 2.0
    assert table.get("500T", 12) is not None
    assert table.get("500T", 13) is None
    assert table.lines() == ["500T"]
