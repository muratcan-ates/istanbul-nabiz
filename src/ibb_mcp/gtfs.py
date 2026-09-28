"""GTFS reference layer: the static backbone under every transit answer.

Live İETT telemetry is nearly content-free on its own — a door number, a coordinate and
a ``yakinDurakKodu``. GTFS supplies the names, and two join keys make it work; both were
verified against live data on 2026-09-08:

* ``yakinDurakKodu`` -> ``stops.stop_code``   (31/31 matched for line 500T)
* ``guzergahkodu``   -> ``routes.route_code`` (2/2 matched)

This module is the public entry point (``from ibb_mcp.gtfs import ...`` keeps working) and
owns what crosses the process boundary: the on-disk caches of the built tables and the
download of the CSVs. The parsing lives one level down, split by responsibility
(ENGINEERING §13, MOD-7):

* :mod:`ibb_mcp.gtfs_index` — ``stops.csv`` and ``routes.csv``, the repaired text, the
  spatial grid and the process-wide :func:`get_index`;
* :mod:`ibb_mcp.gtfs_sequences` — one ordered stop list per route variant;
* :mod:`ibb_mcp.gtfs_timetables` — terminal times per trip and the service calendar.
"""

from __future__ import annotations

import gzip
import json
import logging
import pathlib
from collections.abc import Sequence
from dataclasses import asdict

from ibb_mcp.config import Settings
from ibb_mcp.gtfs_index import (
    GRID_DEG,
    ROUTES_FILE,
    STOPS_FILE,
    GtfsIndex,
    clean_field,
    get_index,
    reset_index_cache,
)
from ibb_mcp.gtfs_sequences import EXCEL_ROW_LIMIT, RouteStopSequence, build_stop_sequences, stop_times_path
from ibb_mcp.gtfs_timetables import ScheduledTrip, build_route_timetables, load_service_days
from ibb_mcp.text import normalize_tr

__all__ = [
    "DEFAULT_GTFS_RESOURCES",
    "EXCEL_ROW_LIMIT",
    "GRID_DEG",
    "ROUTES_FILE",
    "SEQUENCE_CACHE_NAME",
    "STOPS_FILE",
    "TIMETABLE_CACHE_NAME",
    "GtfsIndex",
    "RouteStopSequence",
    "ScheduledTrip",
    "build_route_timetables",
    "build_stop_sequences",
    "clean_field",
    "download_gtfs",
    "ensure_gtfs",
    "get_index",
    "load_route_timetables",
    "load_service_days",
    "load_stop_sequences",
    "normalize_tr",
    "reset_index_cache",
    "save_route_timetables",
    "save_stop_sequences",
    "stop_times_path",
]

log = logging.getLogger(__name__)

#: stop_times.csv is 26 MB and trips.csv 5.8 MB; neither is needed for the live join, so
#: neither is downloaded by default. See :func:`load_stop_sequences`.
DEFAULT_GTFS_RESOURCES: tuple[str, ...] = ("stops", "routes")

#: Where the built sequence index is cached. Building it parses a 150 MB file, which is
#: fine once at deploy time but not on every cold start of a scale-to-zero container.
SEQUENCE_CACHE_NAME = "route_sequences.json.gz"
TIMETABLE_CACHE_NAME = "route_timetables.json.gz"


def _cache_path(settings: Settings) -> pathlib.Path:
    return pathlib.Path(settings.gtfs_dir) / SEQUENCE_CACHE_NAME


def save_stop_sequences(settings: Settings, sequences: dict[str, RouteStopSequence]) -> pathlib.Path:
    """Persist the built index so later processes start instantly."""
    path = _cache_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {code: list(seq.stop_codes) for code, seq in sequences.items()}
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


def load_stop_sequences(settings: Settings) -> dict[str, RouteStopSequence]:
    """Return ``{route_code: RouteStopSequence}``, from cache when possible.

    Falls back to an empty dict rather than raising: a missing sequence index costs the
    ETA engine its high-confidence path, it does not break the answer.
    """
    path = _cache_path(settings)
    if path.exists():
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                payload = json.load(fh)
            return {
                code: RouteStopSequence(route_code=code, stop_codes=tuple(codes))
                for code, codes in payload.items()
            }
        except (OSError, ValueError) as exc:
            log.warning("stop sequence cache at %s unreadable (%r); rebuilding", path, exc)

    sequences = build_stop_sequences(settings)
    if sequences:
        try:
            save_stop_sequences(settings, sequences)
        except OSError as exc:  # a read-only container filesystem must not be fatal
            log.info("could not cache stop sequences: %r", exc)
    return sequences


def _timetable_cache_path(settings: Settings) -> pathlib.Path:
    return pathlib.Path(settings.gtfs_dir) / TIMETABLE_CACHE_NAME


def save_route_timetables(settings: Settings, timetables: dict[str, tuple[ScheduledTrip, ...]]) -> pathlib.Path:
    """Persist route timetable summaries for subsequent processes."""
    path = _timetable_cache_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {code: [asdict(trip) for trip in trips] for code, trips in timetables.items()}
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    return path


def load_route_timetables(settings: Settings) -> dict[str, tuple[ScheduledTrip, ...]]:
    """Load cached timetable summaries or build and cache them from the GTFS tables."""
    path = _timetable_cache_path(settings)
    if path.exists():
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                payload = json.load(fh)
            return {
                code: tuple(ScheduledTrip(**trip) for trip in trips)
                for code, trips in payload.items()
            }
        except (KeyError, OSError, TypeError, ValueError) as exc:
            log.warning("route timetable cache at %s unreadable (%r); rebuilding", path, exc)

    timetables = build_route_timetables(settings)
    if timetables:
        try:
            save_route_timetables(settings, timetables)
        except OSError as exc:  # a read-only container filesystem must not be fatal
            log.info("could not cache route timetables: %r", exc)
    return timetables


def ensure_gtfs(settings: Settings) -> bool:
    """Whether the reference CSVs are present and non-empty. Never touches the network."""
    directory = pathlib.Path(settings.gtfs_dir)
    return all(
        (directory / name).is_file() and (directory / name).stat().st_size > 0
        for name in (STOPS_FILE, ROUTES_FILE)
    )


def download_gtfs(settings: Settings, resources: Sequence[str] = DEFAULT_GTFS_RESOURCES) -> dict[str, pathlib.Path]:
    """Download named GTFS resources into ``settings.gtfs_dir``.

    URLs come from the recorded portal listing in ``tests/fixtures/gtfs_resources.json``,
    so this does not depend on the CKAN package endpoint being up; only CSV variants are
    considered. ``stop_times`` (26 MB) is never in the default set — ask for it by name.
    """
    import httpx  # local import: the index must work without the HTTP stack installed

    catalogue = _resource_catalogue(settings)
    target_dir = pathlib.Path(settings.gtfs_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, pathlib.Path] = {}
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        for name in resources:
            url = catalogue.get(name)
            if not url:
                raise KeyError(f"No CSV resource named {name!r} in the GTFS catalogue.")
            destination = target_dir / f"{name}.csv"
            log.info("Downloading GTFS %s -> %s", name, destination)
            response = client.get(url)
            response.raise_for_status()
            if not response.content:
                raise ValueError(f"GTFS resource {name!r} came back empty from {url}")
            # Write beside the target and rename: a connection dropped mid-body would
            # otherwise leave a truncated stops.csv that ensure_gtfs() calls present and
            # load() parses happily, silently serving a partial index.
            staging = destination.with_name(destination.name + ".part")
            staging.write_bytes(response.content)
            staging.replace(destination)
            written[name] = destination
    if written:
        reset_index_cache()  # otherwise the process keeps serving the previous files
    return written


def _resource_catalogue(settings: Settings) -> dict[str, str]:
    """``{resource name: CSV url}`` from the recorded open data portal listing."""
    import json

    path = pathlib.Path(settings.fixtures_dir) / "gtfs_resources.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    return {
        entry["name"]: entry["url"]
        for entry in entries
        if str(entry.get("format", "")).upper() == "CSV" and entry.get("url")
    }
