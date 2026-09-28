"""Route stop orders: ``trips.csv`` joined to ``stop_times`` into one stop sequence per route variant.

Built once at deploy time and cached by :func:`ibb_mcp.gtfs.load_stop_sequences`; the ETA
engine's high-confidence path (``BusArrival.method == "stop_sequence"``) depends on it.
"""

from __future__ import annotations

import csv
import logging
import pathlib
from dataclasses import dataclass

from ibb_mcp.config import Settings
from ibb_mcp.gtfs_index import GtfsIndex, get_index

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RouteStopSequence:
    """The ordered stops of one route variant: ``route_code`` plus its stop_code list."""

    route_code: str
    stop_codes: tuple[str, ...] = ()

    def position_of(self, stop_code: str) -> int | None:
        try:
            return self.stop_codes.index(stop_code)
        except ValueError:
            return None

    def stops_between(self, from_code: str, to_code: str) -> int | None:
        """Stops still to pass, or ``None`` when either stop is not ahead on this route."""
        start, end = self.position_of(from_code), self.position_of(to_code)
        if start is None or end is None or end < start:
            return None
        return end - start

    def __len__(self) -> int:
        return len(self.stop_codes)



#: Excel's worksheet limit, and the reason ``stop_times.csv`` cannot be trusted.
EXCEL_ROW_LIMIT = 1_048_575


def stop_times_path(gtfs_dir: pathlib.Path) -> pathlib.Path | None:
    """Pick the usable ``stop_times`` file, preferring the complete one.

    İBB publishes this table twice and the two disagree badly:

    * ``stop_times.csv`` (26 MB, ``;`` separated) stops at exactly 1,048,575 data rows —
      Excel's worksheet limit. It was clearly exported through a spreadsheet and silently
      truncated, so it holds only 18,934 of 135,625 trips (14%). Line 500T has **zero**
      rows in it, which is how this was noticed: every arrival estimate silently fell back
      to straight-line distance.
    * The ZIP resource unpacks to ``stop_times.txt`` (150 MB, comma separated, standard
      GTFS) with 6,155,693 rows and full coverage.

    So the ``.txt`` wins whenever it is present, and the truncated ``.csv`` is used only as
    a last resort with a loud warning.
    """
    full = gtfs_dir / "stop_times.txt"
    if full.exists():
        return full
    truncated = gtfs_dir / "stop_times.csv"
    if truncated.exists():
        log.warning(
            "only the truncated %s is present (Excel-limited to %d rows, ~14%% of trips); "
            "download the ZIP resource for stop_times.txt to get complete stop sequences",
            truncated.name,
            EXCEL_ROW_LIMIT,
        )
        return truncated
    return None


def build_stop_sequences(settings: Settings, *, index: GtfsIndex | None = None) -> dict[str, RouteStopSequence]:
    """Join ``stop_times.csv`` to ``trips.csv`` and produce one stop order per route variant.

    Verified schema (2026-09-08, both files ``;`` separated with a UTF-8 BOM):

    * ``trips.csv``      -> ``trip_id;route_id;service_id;trip_headsign;direction_id``
    * ``stop_times.csv`` -> ``trip_id;stop_id;stop_sequence;arrival_time;departure_time;timepoint``

    A route runs many trips that mostly repeat the same stop order, so the longest trip
    per ``route_code`` is kept as that route's canonical sequence. Stop ids are translated
    to ``stop_code`` because that is the key live vehicle telemetry reports.

    Returns an empty dict when the optional files are absent; the ETA engine then falls
    back to straight-line distance and says so in ``BusArrival.method``.
    """
    gtfs_dir = pathlib.Path(settings.gtfs_dir)
    trips_path = gtfs_dir / "trips.csv"
    times_path = stop_times_path(gtfs_dir)
    if not (trips_path.exists() and times_path is not None):
        log.info("stop sequences unavailable: trips.csv or a stop_times file is missing under %s", gtfs_dir)
        return {}

    index = index or get_index(settings)
    route_code_by_id: dict[str, str] = {
        route.route_id: route.route_code for route in index.routes if route.route_code
    }
    stop_code_by_id: dict[str, str] = {
        stop.stop_id: stop.stop_code for stop in index.stops if stop.stop_id and stop.stop_code
    }
    trip_route = _trip_routes(trips_path, route_code_by_id)
    per_trip = _stop_orders_per_trip(times_path, trip_route, stop_code_by_id)
    sequences = _canonical_sequences(per_trip, trip_route)
    log.info("built %d route stop sequences from %d trips", len(sequences), len(per_trip))
    return sequences


def _trip_routes(trips_path: pathlib.Path, route_code_by_id: dict[str, str]) -> dict[str, str]:
    """``trip_id -> route_code``, keeping only trips whose route we can name."""
    trip_route: dict[str, str] = {}
    with trips_path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            code = route_code_by_id.get((row.get("route_id") or "").strip())
            if code:
                trip_route[(row.get("trip_id") or "").strip()] = code
    return trip_route


def _stop_orders_per_trip(
    times_path: pathlib.Path, trip_route: dict[str, str], stop_code_by_id: dict[str, str]
) -> dict[str, list[tuple[int, str]]]:
    """Collect ``(sequence, stop_code)`` per trip. One pass, no sorting of the whole file."""
    per_trip: dict[str, list[tuple[int, str]]] = {}
    delimiter = "," if times_path.suffix == ".txt" else ";"
    with times_path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh, delimiter=delimiter):
            trip_id = (row.get("trip_id") or "").strip()
            if trip_id not in trip_route:
                continue
            stop_code = stop_code_by_id.get((row.get("stop_id") or "").strip())
            if not stop_code:
                continue
            try:
                order = int(row.get("stop_sequence") or 0)
            except ValueError:
                continue
            per_trip.setdefault(trip_id, []).append((order, stop_code))
    return per_trip


def _canonical_sequences(
    per_trip: dict[str, list[tuple[int, str]]], trip_route: dict[str, str]
) -> dict[str, RouteStopSequence]:
    """Longest trip wins per route variant; ties keep the first seen for determinism."""
    best: dict[str, list[tuple[int, str]]] = {}
    for trip_id, entries in per_trip.items():
        code = trip_route[trip_id]
        if len(entries) > len(best.get(code, ())):
            best[code] = entries

    sequences: dict[str, RouteStopSequence] = {}
    for code, entries in best.items():
        ordered = [stop_code for _, stop_code in sorted(entries, key=lambda item: item[0])]
        deduped: list[str] = []
        for stop_code in ordered:  # a loop route can repeat a stop; keep the first visit
            if not deduped or deduped[-1] != stop_code:
                deduped.append(stop_code)
        sequences[code] = RouteStopSequence(route_code=code, stop_codes=tuple(deduped))
    return sequences
