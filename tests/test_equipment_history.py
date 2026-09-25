from __future__ import annotations

import datetime as dt
import pathlib
from typing import Any

from nabiz.collector import lake
from nabiz.console.history_api import EQUIPMENT_HISTORY_SOURCE, read_equipment_snapshots, station_history

NOW = dt.datetime(2026, 9, 25, 12, tzinfo=dt.UTC)


def row(
    stamp: dt.datetime,
    *,
    station: str = "Kartal",
    code: str = "TEST-ASN-01",
    status: str = "fault",
    outage: str | None = "outage-1",
    has_record: bool = True,
) -> dict[str, Any]:
    return {
        "snapshot_ts_utc": stamp.isoformat(),
        "ts_utc": stamp.isoformat(),
        "has_record": has_record,
        "station_name": station if has_record else None,
        "equipment_code": code if has_record else None,
        "outage_id": outage if has_record else None,
        "status_class": status,
    }


def test_station_history_counts_distinct_faulty_snapshots() -> None:
    stamps = [NOW - dt.timedelta(days=3), NOW - dt.timedelta(days=2), NOW - dt.timedelta(days=1)]
    rows = [row(stamp) for stamp in stamps] + [row(stamps[0], code="OTHER-ASN-02")]

    result = station_history(rows, station="Kartal", now=NOW)

    assert result["fault_count"] == 3


def test_station_history_averages_outage_duration_across_runs() -> None:
    start = NOW - dt.timedelta(days=6)
    rows = [
        row(start, outage="first"),
        row(start + dt.timedelta(hours=2), outage="first"),
        row(start + dt.timedelta(days=1), outage="second"),
        row(start + dt.timedelta(days=1, hours=4), outage="second"),
    ]

    result = station_history(rows, station="Kartal", now=NOW)

    assert result["avg_duration_hours"] == 3.0


def test_station_history_reports_current_status_from_latest_snapshot() -> None:
    older = NOW - dt.timedelta(hours=3)
    latest = NOW - dt.timedelta(hours=1)
    rows = [row(older, status="fault"), row(latest, status="revision", outage="outage-2")]

    result = station_history(rows, station="KARTAL", now=NOW)

    assert result["current_status"] == "revision"


def test_station_history_with_no_rows_returns_none_counts() -> None:
    result = station_history([], station="Kartal", now=NOW)

    assert result["fault_count"] is None
    assert result["avg_duration_hours"] is None
    assert result["current_status"] == "unknown"
    assert result["data_since"] is None


def test_read_equipment_snapshots_merges_every_partition_file(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setenv("NABIZ_LAKE_DIR", str(tmp_path))
    first = NOW - dt.timedelta(days=2)
    second = NOW - dt.timedelta(days=1)
    lake.write_rows(EQUIPMENT_HISTORY_SOURCE, [row(first)], snapshot_ts=first, backend="local-json")
    lake.write_rows(EQUIPMENT_HISTORY_SOURCE, [row(second, code="TEST-ASN-02")], snapshot_ts=second, backend="local-json")

    rows = read_equipment_snapshots(tmp_path)

    assert [item["equipment_code"] for item in rows] == ["TEST-ASN-01", "TEST-ASN-02"]
