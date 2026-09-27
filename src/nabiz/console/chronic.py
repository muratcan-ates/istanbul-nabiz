"""Count recurring Metro observations from Nabız's discontinuous archive reads."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from ibb_mcp.text import fold_tr, squash_punctuation
from nabiz.console.notice_age import FAULT_CLASSES
from nexus_core.stats import ISTANBUL

# These are design parameters, not measurements.
WINDOWS = ("7", "30")
CHRONIC_MIN_DAYS = 3
MAX_ROWS = 200
EQUIPMENT_TYPES = ("elevator", "escalator", "moving_walkway")
STATUS_ORDER = ("fault", "revision", "not_operated")


def _utc(value: dt.datetime) -> dt.datetime:
    return (value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value).astimezone(dt.UTC)


def _stamp(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return _utc(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _utc(dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
    except ValueError:
        return None


def _snapshot_rows(rows: list[dict[str, Any]], start: dt.datetime, now: dt.datetime) -> dict[dt.datetime, list[dict[str, Any]]]:
    snapshots: dict[dt.datetime, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        stamp = _stamp(row.get("snapshot_ts_utc"))
        if stamp is not None and start <= stamp <= now:
            snapshots[stamp].append(row)
    return dict(snapshots)


def _station(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _has_readable_equipment_row(snapshot: list[dict[str, Any]]) -> bool:
    return any(
        row.get("has_record") is False
        or (row.get("has_record") is True and _station(row.get("station_name")) is not None)
        for row in snapshot
    )


def _readable_equipment(rows: Mapping[dt.datetime, list[dict[str, Any]]]) -> tuple[dict[dt.datetime, list[dict[str, Any]]], int]:
    readable: dict[dt.datetime, list[dict[str, Any]]] = {}
    unreadable = 0
    for stamp, snapshot in rows.items():
        if _has_readable_equipment_row(snapshot):
            readable[stamp] = snapshot
        elif snapshot and all(row.get("has_record") is True and _station(row.get("station_name")) is None for row in snapshot):
            unreadable += 1
    return readable, unreadable


def _coverage(reads: Mapping[dt.datetime, list[dict[str, Any]]], unreadable: int = 0) -> dict[str, Any]:
    stamps = sorted(reads)
    return {
        "read_days": len({stamp.astimezone(ISTANBUL).date() for stamp in stamps}),
        "reads": len(stamps),
        "unreadable_reads": unreadable,
        "first_read": stamps[0].isoformat() if stamps else None,
        "last_read": stamps[-1].isoformat() if stamps else None,
    }


def _equipment_groups(
    reads: Mapping[dt.datetime, list[dict[str, Any]]],
) -> dict[tuple[str, str, str], dict[dt.datetime, list[dict[str, Any]]]]:
    groups: dict[tuple[str, str, str], dict[dt.datetime, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for stamp, snapshot in reads.items():
        for row in snapshot:
            station = _station(row.get("station_name"))
            kind = row.get("equipment_type")
            status = row.get("status_class")
            if row.get("has_record") is not True or station is None or kind not in EQUIPMENT_TYPES or status not in FAULT_CLASSES:
                continue
            line = row.get("line_name")
            line = line.strip() if isinstance(line, str) else ""
            groups[(line, chronic_station_key(station), kind)][stamp].append(row)
    return groups


def _equipment_row(
    key: tuple[str, str, str],
    snapshots: Mapping[dt.datetime, list[dict[str, Any]]],
    coverage: Mapping[str, Any],
    latest: dt.datetime | None,
    reports: Mapping[str, int] | None,
) -> dict[str, Any]:
    stamps = sorted(snapshots)
    last_rows = snapshots[stamps[-1]]
    line, station_key, kind = key
    station = _station(last_rows[-1].get("station_name")) or station_key
    statuses = {str(row.get("status_class")) for values in snapshots.values() for row in values}
    reads_by_day = {stamp.astimezone(ISTANBUL).date() for stamp in stamps}
    report_count = None if reports is None else int(reports.get(station_key, 0)) if kind == "elevator" else None
    return {
        "kind": "equipment",
        "line": line or None,
        "station": station,
        "equipment_type": kind,
        "days_seen": len(reads_by_day),
        "read_days": int(coverage["read_days"]),
        "reads_seen": len(stamps),
        "reads_total": int(coverage["reads"]),
        "first_seen": stamps[0].isoformat(),
        "last_seen": stamps[-1].isoformat(),
        "in_latest_read": latest is not None and latest in snapshots,
        "max_at_once": max(len(values) for values in snapshots.values()),
        "statuses": [status for status in STATUS_ORDER if status in statuses],
        "notice": None,
        "chronic": len(reads_by_day) >= CHRONIC_MIN_DAYS,
        "reports": report_count,
    }


def _line_groups(
    reads: Mapping[dt.datetime, list[dict[str, Any]]],
) -> dict[str, dict[dt.datetime, str | None]]:
    groups: dict[str, dict[dt.datetime, str | None]] = defaultdict(dict)
    for stamp, snapshot in reads.items():
        for row in snapshot:
            line = row.get("line_name")
            if row.get("has_notice") is not True or not isinstance(line, str) or not line.strip():
                continue
            description = row.get("description")
            groups[line.strip()][stamp] = description if isinstance(description, str) else None
    return groups


def _line_row(
    line: str,
    snapshots: Mapping[dt.datetime, str | None],
    coverage: Mapping[str, Any],
    latest: dt.datetime | None,
) -> dict[str, Any]:
    stamps = sorted(snapshots)
    days_seen = len({stamp.astimezone(ISTANBUL).date() for stamp in stamps})
    return {
        "kind": "line",
        "line": line,
        "station": None,
        "equipment_type": None,
        "days_seen": days_seen,
        "read_days": int(coverage["read_days"]),
        "reads_seen": len(stamps),
        "reads_total": int(coverage["reads"]),
        "first_seen": stamps[0].isoformat(),
        "last_seen": stamps[-1].isoformat(),
        "in_latest_read": latest is not None and latest in snapshots,
        "max_at_once": None,
        "statuses": [],
        "notice": snapshots[stamps[-1]],
        "chronic": days_seen >= CHRONIC_MIN_DAYS,
        "reports": None,
    }


def _sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    reports = row.get("reports") or 0
    return (
        -int(row["days_seen"]),
        -int(row["reads_seen"]),
        -int(reports),
        fold_tr(str(row.get("line") or "")),
        chronic_station_key(str(row.get("station") or "")),
        str(row.get("equipment_type") or ""),
    )


def window_start(now: dt.datetime, days: int | str) -> dt.datetime:
    """Return local midnight at the start of a calendar-day window as UTC."""
    count = int(days)
    if str(count) not in WINDOWS:
        raise ValueError("days must be 7 or 30")
    local_today = _utc(now).astimezone(ISTANBUL).date()
    first_day = local_today - dt.timedelta(days=count - 1)
    return dt.datetime.combine(first_day, dt.time.min, tzinfo=ISTANBUL).astimezone(dt.UTC)


def chronic_station_key(name: str) -> str:
    """Normalize a station name with the same key used by the report map."""
    return squash_punctuation(fold_tr(name))


def chronic_summary(
    metro_rows: list[dict[str, Any]],
    equipment_rows: list[dict[str, Any]],
    *,
    now: dt.datetime,
    days: int | str,
    reports: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Summarize distinct archive reads and the units seen in those reads."""
    current = _utc(now)
    start = window_start(current, days)
    equipment_snapshots = _snapshot_rows(equipment_rows, start, current)
    equipment_reads, unreadable = _readable_equipment(equipment_snapshots)
    metro_reads = _snapshot_rows(metro_rows, start, current)
    equipment_coverage = _coverage(equipment_reads, unreadable)
    lines_coverage = _coverage(metro_reads)
    latest_equipment = max(equipment_reads, default=None)
    latest_line = max(metro_reads, default=None)

    rows = [
        _equipment_row(key, snapshots, equipment_coverage, latest_equipment, reports)
        for key, snapshots in _equipment_groups(equipment_reads).items()
    ]
    rows.extend(
        _line_row(line, snapshots, lines_coverage, latest_line)
        for line, snapshots in _line_groups(metro_reads).items()
    )
    rows.sort(key=_sort_key)
    total_rows = len(rows)
    note_codes: list[str] = []
    if equipment_coverage["read_days"] < CHRONIC_MIN_DAYS:
        note_codes.append("equipment_thin")
    if lines_coverage["read_days"] < CHRONIC_MIN_DAYS:
        note_codes.append("lines_thin")
    if total_rows == 0 and max(equipment_coverage["read_days"], lines_coverage["read_days"]) >= CHRONIC_MIN_DAYS:
        note_codes.append("no_rows")
    if reports is None:
        note_codes.append("reports_unavailable")
    return {
        "window_start": start.isoformat(),
        "coverage": {"equipment": equipment_coverage, "lines": lines_coverage},
        "rows": rows[:MAX_ROWS],
        "total_rows": total_rows,
        "note_codes": note_codes,
    }


__all__ = [
    "CHRONIC_MIN_DAYS", "EQUIPMENT_TYPES", "MAX_ROWS", "STATUS_ORDER", "WINDOWS",
    "chronic_station_key", "chronic_summary", "window_start",
]
