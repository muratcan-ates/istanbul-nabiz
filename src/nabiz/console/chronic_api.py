"""Operator-only read API for recurring Metro list observations."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, Request

from ibb_mcp.text import fold_tr
from nabiz.console import notice_age
from nabiz.console.agency_router import route
from nabiz.console.chronic import CHRONIC_MIN_DAYS, chronic_station_key, chronic_summary, window_start
from nabiz.console.report_api import report_engine
from nabiz.console.report_map_api import report_map_counts
from nexus_core.signals import system_clock

log = logging.getLogger("nabiz.console.chronic")
chronic_routes = APIRouter()

TYPE_QUERY = {
    "elevator": "asansör",
    "escalator": "yürüyen merdiven",
    "moving_walkway": "yürüyen bant",
}


def _utc(value: dt.datetime) -> dt.datetime:
    return (value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value).astimezone(dt.UTC)


def _agency_query(row: dict[str, Any]) -> str:
    line = str(row.get("line") or "").strip()
    if row.get("kind") == "line":
        return f"{line} hattı".strip()
    kind = TYPE_QUERY.get(str(row.get("equipment_type") or ""), "")
    return f"{line} {kind}".strip()


def _add_agencies(rows: list[dict[str, Any]]) -> None:
    per_request: dict[str, dict[str, Any] | None] = {}
    for row in rows:
        query = _agency_query(row)
        if query not in per_request:
            try:
                result = route(query)
            except (FileNotFoundError, json.JSONDecodeError):
                per_request[query] = None
            else:
                per_request[query] = (
                    {"id": result.agency, "name": result.name, "url": result.url}
                    if result.agency is not None else None
                )
        row["agency"] = per_request[query]


def _empty_coverage() -> dict[str, dict[str, Any]]:
    empty = {"read_days": 0, "reads": 0, "unreadable_reads": 0, "first_read": None, "last_read": None}
    return {"equipment": dict(empty), "lines": dict(empty)}


async def _report_counts(
    request: Request, now: dt.datetime, start: dt.datetime,
) -> tuple[dict[str, int] | None, int | None, dict[str, dict[str, Any]] | None]:
    ports = getattr(request.app.state, "ports", None)
    if ports is None or getattr(ports, "console", None) is None:
        return None, None, None
    engine = report_engine(request)
    if engine is None:
        return None, None, None
    try:
        counts = await asyncio.to_thread(report_map_counts, engine, now, now - start)
    except (sqlite3.Error, OSError) as exc:
        log.warning("chronic report ledger unavailable: %s", type(exc).__name__)
        return None, None, None
    reports = {key: int(row.get("reports", 0)) for key, row in counts.items()}
    return reports, sum(reports.values()), counts


def _stamp(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed.replace(tzinfo=dt.UTC) if parsed.tzinfo is None else parsed).astimezone(dt.UTC)


def _seen_elevator_stations(rows: list[dict[str, Any]], start: dt.datetime, now: dt.datetime) -> set[str]:
    seen: set[str] = set()
    for row in rows:
        stamp = _stamp(row.get("snapshot_ts_utc"))
        station = row.get("station_name")
        if (
            stamp is not None and start <= stamp <= now
            and row.get("has_record") is True
            and row.get("equipment_type") == "elevator"
            and row.get("status_class") in notice_age.FAULT_CLASSES
            and isinstance(station, str) and station.strip()
        ):
            seen.add(chronic_station_key(station))
    return seen


def _reports_only(
    counts: dict[str, dict[str, Any]] | None, seen_stations: set[str],
) -> list[dict[str, Any]]:
    if counts is None:
        return []
    rows = [
        {"station": str(row["station"]), "reports": int(row["reports"])}
        for key, row in counts.items()
        if key not in seen_stations and row.get("station") and int(row.get("reports", 0)) > 0
    ]
    rows.sort(key=lambda row: (-row["reports"], fold_tr(row["station"]), row["station"]))
    return rows[:10]


@chronic_routes.get("/api/console/chronic", response_model=None)
async def chronic(request: Request, days: Literal["7", "30"] = "7") -> dict[str, Any]:
    """Return archive-based recurring counts; this read model never changes the ledger."""
    now = _utc(getattr(request.app.state, "report_clock", system_clock)())
    day_count = int(days)
    start = window_start(now, day_count)
    root = notice_age.lake_root()
    sources = (notice_age.METRO_SOURCE, notice_age.EQUIPMENT_SOURCE)
    archive_exists = any((root / source).is_dir() for source in sources)
    if not archive_exists:
        log.info("chronic days=%d rows=0", day_count)
        return {
            "days": day_count,
            "window_start": start.isoformat(),
            "generated_at": now.isoformat(),
            "chronic_min_days": CHRONIC_MIN_DAYS,
            "coverage": _empty_coverage(),
            "rows": [],
            "total_rows": 0,
            "reports_total": None,
            "reports_only": [],
            "note_codes": ["archive_missing"],
        }

    metro_rows, equipment_rows = await asyncio.gather(*(
        asyncio.to_thread(notice_age.cached_rows, source, now=now) for source in sources
    ))
    reports, reports_total, report_rows = await _report_counts(request, now, start)
    summary = chronic_summary(metro_rows, equipment_rows, now=now, days=day_count, reports=reports)
    _add_agencies(summary["rows"])
    reports_only = _reports_only(report_rows, _seen_elevator_stations(equipment_rows, start, now))
    log.info("chronic days=%d rows=%d", day_count, summary["total_rows"])
    return {
        **summary,
        "days": day_count,
        "generated_at": now.isoformat(),
        "chronic_min_days": CHRONIC_MIN_DAYS,
        "reports_total": reports_total,
        "reports_only": reports_only,
    }


__all__ = ["chronic_routes"]
