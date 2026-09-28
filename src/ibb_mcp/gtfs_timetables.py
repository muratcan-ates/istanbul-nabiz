"""Route timetables: terminal departure and arrival times per GTFS trip, plus the service calendar.

İBB's ``stop_times.txt`` carries a time only at the first and last stop of a trip, so this
is all the schedule the export can honestly give (:mod:`ibb_mcp.timetables` reads it).
Cached by :func:`ibb_mcp.gtfs.load_route_timetables`.
"""

from __future__ import annotations

import csv
import logging
import pathlib
from dataclasses import dataclass
from typing import Any

from ibb_mcp.config import Settings
from ibb_mcp.gtfs_index import GtfsIndex, clean_field, get_index
from ibb_mcp.gtfs_sequences import stop_times_path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScheduledTrip:
    """A GTFS trip summarized by its terminal times and route metadata."""

    trip_id: str
    route_code: str
    service_id: str
    headsign: str
    departure_time: str
    arrival_time: str
    stop_count: int



def _route_trip_metadata(trips_path: pathlib.Path, index: GtfsIndex) -> dict[str, tuple[str, str, str]]:
    """Join each named trip to its route, service id and headsign."""
    route_code_by_id = {route.route_id: route.route_code for route in index.routes if route.route_code}
    trip_metadata: dict[str, tuple[str, str, str]] = {}
    with trips_path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            trip_id = (row.get("trip_id") or "").strip()
            route_code = route_code_by_id.get((row.get("route_id") or "").strip())
            if trip_id and route_code:
                trip_metadata[trip_id] = (
                    route_code,
                    (row.get("service_id") or "").strip(),
                    clean_field(row.get("trip_headsign")) or "",
                )
    return trip_metadata


def _route_trip_times(
    times_path: pathlib.Path,
    trip_metadata: dict[str, tuple[str, str, str]],
) -> dict[str, dict[str, Any]]:
    """Stream stop times once and retain each trip's first and last populated arrival."""
    # Keep only five values per trip while streaming the large stop_times file once.
    per_trip: dict[str, dict[str, Any]] = {}
    delimiter = "," if times_path.suffix == ".txt" else ";"
    with times_path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh, delimiter=delimiter):
            trip_id = (row.get("trip_id") or "").strip()
            if trip_id not in trip_metadata:
                continue
            details = per_trip.setdefault(
                trip_id,
                {"stop_count": 0, "first_sequence": None, "departure_time": None,
                 "last_sequence": None, "arrival_time": None},
            )
            details["stop_count"] += 1
            try:
                sequence = int(row.get("stop_sequence") or "")
            except ValueError:
                continue
            arrival_time = (row.get("arrival_time") or "").strip()
            if not arrival_time:
                continue
            first_sequence = details["first_sequence"]
            if first_sequence is None or sequence < first_sequence:
                details["first_sequence"] = sequence
                details["departure_time"] = arrival_time
            last_sequence = details["last_sequence"]
            if last_sequence is None or sequence > last_sequence:
                details["last_sequence"] = sequence
                details["arrival_time"] = arrival_time
    return per_trip


def build_route_timetables(settings: Settings, *, index: GtfsIndex | None = None) -> dict[str, tuple[ScheduledTrip, ...]]:
    """Read route departures from the first and last timed rows of each GTFS trip.

    İBB's ``stop_times.txt`` contains a time only at the first and last stops. These
    summaries therefore support departures from route termini; no intermediate stop time
    can be inferred from the file.
    """
    gtfs_dir = pathlib.Path(settings.gtfs_dir)
    trips_path = gtfs_dir / "trips.csv"
    times_path = stop_times_path(gtfs_dir)
    if not trips_path.exists() or times_path is None:
        log.info("route timetables unavailable: trips.csv or a stop_times file is missing under %s", gtfs_dir)
        return {}

    index = index or get_index(settings)
    trip_metadata = _route_trip_metadata(trips_path, index)
    per_trip = _route_trip_times(times_path, trip_metadata)
    by_route: dict[str, list[ScheduledTrip]] = {}
    for trip_id, details in per_trip.items():
        metadata = trip_metadata[trip_id]
        if not details["departure_time"] or not details["arrival_time"]:
            continue
        trip = ScheduledTrip(
            trip_id=trip_id,
            route_code=metadata[0],
            service_id=metadata[1],
            headsign=metadata[2],
            departure_time=details["departure_time"],
            arrival_time=details["arrival_time"],
            stop_count=details["stop_count"],
        )
        by_route.setdefault(trip.route_code, []).append(trip)

    result = {
        code: tuple(sorted(trips, key=lambda trip: (trip.departure_time, trip.trip_id)))
        for code, trips in by_route.items()
    }
    log.info("built route timetables for %d routes from %d trips", len(result), sum(map(len, result.values())))
    return result


def load_service_days(settings: Settings) -> dict[str, frozenset[str]]:
    """Read GTFS ``calendar.csv`` and map service ids to I/C/P day types."""
    path = pathlib.Path(settings.gtfs_dir) / "calendar.csv"
    if not path.exists():
        log.info("GTFS service calendar unavailable: %s is missing", path.name)
        return {}

    rows: list[dict[str, str]] | None = None
    for delimiter in (";", ","):
        with path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh, delimiter=delimiter)
            headers = [name.strip() for name in (reader.fieldnames or [])]
            if "service_id" not in headers:
                continue
            reader.fieldnames = headers
            rows = [{(key or "").strip(): (value or "").strip() for key, value in row.items()} for row in reader]
            break
    if rows is None:
        log.info("GTFS service calendar has no service_id column")
        return {}

    result: dict[str, frozenset[str]] = {}
    weekdays = ("monday", "tuesday", "wednesday", "thursday", "friday")
    for row in rows:
        service_id = row.get("service_id", "")
        if not service_id:
            continue
        active: set[str] = set()
        if any(row.get(day) == "1" for day in weekdays):
            active.add("I")
        if row.get("saturday") == "1":
            active.add("C")
        if row.get("sunday") == "1":
            active.add("P")
        result[service_id] = frozenset(active)
    return result
