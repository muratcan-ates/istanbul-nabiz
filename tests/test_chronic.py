from __future__ import annotations

import datetime as dt

from nabiz.console.chronic import (
    CHRONIC_MIN_DAYS,
    MAX_ROWS,
    chronic_station_key,
    chronic_summary,
    window_start,
)

NOW = dt.datetime(2026, 9, 27, 0, 30, tzinfo=dt.UTC)


def equipment(stamp: str, station: str | None, *, kind: str = "elevator", status: str = "fault", **extra):
    # Sentetik arşiv satırı; gerçek İBB verisi değildir.
    return {
        "snapshot_ts_utc": stamp,
        "has_record": station is not None,
        "equipment_type": kind,
        "equipment_code": "ASANSOR",
        "line_name": "M2",
        "station_name": station,
        "status_class": status,
        "status_type": "Arıza",
        "uncertainty": [],
        **extra,
    }


def metro(stamp: str, *, notice: bool, line: str = "M7", description: str = "Sefer bilgisi"):
    # Sentetik nabız veya hat duyurusu satırı; İBB'den alınmamıştır.
    return {
        "snapshot_ts_utc": stamp,
        "has_notice": notice,
        "line_name": line if notice else None,
        "description": description if notice else None,
    }


def test_same_equipment_unit_counts_distinct_istanbul_days_and_peak_rows() -> None:
    stamps = [f"2026-09-{day:02d}T21:30:00Z" for day in (22, 23, 24, 25)]
    statuses = ("fault", "revision", "not_operated", "fault")
    rows = [equipment(stamp, "Hacıosman", status=status) for stamp, status in zip(stamps, statuses, strict=True)]
    rows.append(equipment(stamps[0], "Hacıosman", kind="elevator", status="revision"))

    result = chronic_summary([], rows, now=NOW, days=30, reports={})
    item = result["rows"][0]

    assert item["days_seen"] == 4
    assert item["reads_seen"] == 4
    assert item["max_at_once"] == 2
    assert item["statuses"] == ["fault", "revision", "not_operated"]
    assert item["chronic"] is True


def test_utc_snapshot_at_2130_is_the_next_istanbul_calendar_day() -> None:
    result = chronic_summary([], [equipment("2026-09-25T21:30:00Z", "Kartal")], now=NOW, days=30, reports={})
    item = result["rows"][0]

    assert item["days_seen"] == 1
    assert item["first_seen"] == "2026-09-25T21:30:00+00:00"


def test_windows_start_at_istanbul_midnight_and_filter_old_reads() -> None:
    ten_days_ago = "2026-09-16T22:00:00Z"
    row = equipment(ten_days_ago, "Kartal")

    seven = chronic_summary([], [row], now=NOW, days="7", reports={})
    thirty = chronic_summary([], [row], now=NOW, days="30", reports={})

    assert window_start(NOW, 7) == dt.datetime(2026, 9, 20, 21, tzinfo=dt.UTC)
    assert seven["rows"] == []
    assert thirty["rows"][0]["station"] == "Kartal"


def test_unreadable_stationless_read_is_not_a_read_day_or_denominator() -> None:
    stamp = "2026-09-25T21:30:00Z"
    next_day = "2026-09-26T21:30:00Z"
    rows = [equipment(stamp, "Kartal"), equipment(next_day, None, has_record=True)]

    result = chronic_summary([], rows, now=NOW, days=30, reports={})

    assert result["coverage"]["equipment"] == {
        "read_days": 1,
        "reads": 1,
        "unreadable_reads": 1,
        "first_read": stamp.replace("Z", "+00:00"),
        "last_read": stamp.replace("Z", "+00:00"),
    }


def test_heartbeat_reads_count_but_do_not_create_units_or_seen_days() -> None:
    unit_stamp = "2026-09-24T20:00:00Z"
    heartbeat_stamp = "2026-09-25T20:00:00Z"
    metro_rows = [metro(unit_stamp, notice=True), metro(heartbeat_stamp, notice=False)]
    equipment_rows = [equipment(unit_stamp, "Kartal"), equipment(heartbeat_stamp, None)]

    result = chronic_summary(metro_rows, equipment_rows, now=NOW, days=30, reports={})
    equipment_coverage = result["coverage"]["equipment"]
    item = next(row for row in result["rows"] if row["kind"] == "equipment")

    assert equipment_coverage["reads"] == equipment_coverage["read_days"] == 2
    assert item["days_seen"] == 1 < item["read_days"]
    assert item["in_latest_read"] is False
    assert len(result["rows"]) == 2


def test_identical_group_codes_at_two_stations_remain_separate_units() -> None:
    stamp = "2026-09-25T20:00:00Z"
    result = chronic_summary([], [equipment(stamp, "Kartal"), equipment(stamp, "Yenikapı")], now=NOW, days=30, reports={})

    assert {row["station"] for row in result["rows"]} == {"Kartal", "Yenikapı"}
    assert len(result["rows"]) == 2


def test_line_notice_and_equipment_are_separate_units_and_latest_notice_wins() -> None:
    first = "2026-09-24T20:00:00Z"
    last = "2026-09-25T20:00:00Z"
    result = chronic_summary(
        [metro(first, notice=True, description="Önceki metin"), metro(last, notice=True, description="Son metin")],
        [equipment(first, "Kartal")],
        now=NOW,
        days=30,
        reports={},
    )
    line = next(row for row in result["rows"] if row["kind"] == "line")
    item = next(row for row in result["rows"] if row["kind"] == "equipment")

    assert line["notice"] == "Son metin"
    assert line["statuses"] == [] and line["station"] is None
    assert line["reads_total"] == 2
    assert item["reads_total"] == 1


def test_reports_attach_only_to_elevators_and_missing_ledger_is_explicit() -> None:
    stamp = "2026-09-25T20:00:00Z"
    rows = [equipment(stamp, "Kartal"), equipment(stamp, "Kartal", kind="escalator")]
    counted = chronic_summary([], rows, now=NOW, days=30, reports={chronic_station_key("Kartal"): 2})
    unavailable = chronic_summary([], rows, now=NOW, days=30, reports=None)

    assert next(row for row in counted["rows"] if row["equipment_type"] == "elevator")["reports"] == 2
    assert next(row for row in counted["rows"] if row["equipment_type"] == "escalator")["reports"] is None
    assert all(row["reports"] is None for row in unavailable["rows"])
    assert "reports_unavailable" in unavailable["note_codes"]


def test_threshold_and_thin_data_notes_are_design_parameters() -> None:
    stamps = ["2026-09-24T20:00:00Z", "2026-09-25T20:00:00Z"]
    thin = chronic_summary([], [equipment(stamp, "Kartal") for stamp in stamps], now=NOW, days=30, reports={})
    empty_stamps = [f"2026-09-{day:02d}T20:00:00Z" for day in (23, 24, 25)]
    no_rows = chronic_summary(
        [metro(stamp, notice=False) for stamp in empty_stamps], [], now=NOW, days=30, reports={}
    )

    assert CHRONIC_MIN_DAYS == 3
    assert thin["rows"][0]["chronic"] is False
    assert "equipment_thin" in thin["note_codes"]
    assert "lines_thin" in thin["note_codes"]
    assert "no_rows" in no_rows["note_codes"]


def test_station_key_matches_report_map_normalization() -> None:
    assert chronic_station_key("4.Levent") == chronic_station_key("4. Levent")
    assert chronic_station_key("Yakacık-Adnan Kahveci") == chronic_station_key("Yakacık - Adnan Kahveci")


def test_rows_are_sorted_and_capped_without_losing_total() -> None:
    stamp = "2026-09-25T20:00:00Z"
    rows = [equipment(stamp, f"İstasyon {index:03d}") for index in range(MAX_ROWS + 5)]
    result = chronic_summary([], rows, now=NOW, days=30, reports={})

    assert len(result["rows"]) == MAX_ROWS
    assert result["total_rows"] == MAX_ROWS + 5
    assert result["rows"] == sorted(result["rows"], key=lambda row: (
        -row["days_seen"], -row["reads_seen"], 0, "m2", chronic_station_key(row["station"]), row["equipment_type"],
    ))[:MAX_ROWS]
