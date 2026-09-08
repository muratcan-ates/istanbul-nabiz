"""GTFS reference layer: the static backbone under every transit answer.

Live İETT telemetry is almost content-free on its own: a bus reports a door number, a
coordinate and a ``yakinDurakKodu``. No stop name, no route geometry, nothing a user
would recognise. GTFS supplies that context, and two join keys make it work — both
verified against live data on 2026-09-08:

* ``yakinDurakKodu`` -> ``stops.stop_code``   (31/31 matched for line 500T)
* ``guzergahkodu``   -> ``routes.route_code`` (2/2 matched)

Note the first one: it is ``stop_code``, **not** ``stop_id``. Those are two different
number spaces in the İBB export, and joining on ``stop_id`` silently matches nothing —
which is the worst kind of bug, because the ETA tool would just answer "no buses".

The export needs repair before it is usable:

* ``;`` separator and a UTF-8 BOM, hence ``encoding='utf-8-sig'``;
* ``stop_lat``/``stop_lon`` carry thousands separators — ``410.191.700.005.564`` means
  ``41.0191700005564`` (:func:`models.repair_coordinate`); 4 of 15390 rows are corrupt
  beyond repair (a shifted column, scientific notation) and are dropped;
* ``routes.csv`` text is double-encoded mojibake — ``KADIKÃ–Y`` is ``KADIKÖY``
  (:func:`models.demojibake`). ``stops.csv`` text is clean UTF-8 and passes through
  ``demojibake`` untouched, so it is safe to apply everywhere.
"""

from __future__ import annotations

import csv
import datetime as dt
import logging
import math
import pathlib
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from ibb_mcp.config import Settings
from ibb_mcp.models import Route, Stop, demojibake, haversine_km, repair_coordinate, utcnow

log = logging.getLogger(__name__)

#: Spatial grid cell size in degrees. 0.01° is ~1.11 km of latitude and ~0.84 km of
#: longitude at İstanbul's 41°N — small enough that a 1 km query touches a handful of
#: cells, large enough that 15k stops do not shard into noise.
GRID_DEG = 0.01
_KM_PER_DEG_LAT = 111.32

STOPS_FILE = "stops.csv"
ROUTES_FILE = "routes.csv"
#: stop_times.csv is 26 MB and trips.csv 5.8 MB; neither is needed for the live join,
#: so neither is downloaded by default. See :func:`load_stop_sequences`.
DEFAULT_GTFS_RESOURCES: tuple[str, ...] = ("stops", "routes")


# --------------------------------------------------------------------------------------
# Turkish-insensitive text normalisation
# --------------------------------------------------------------------------------------
# str.lower() is wrong for Turkish: "I".lower() is "i", but the Turkish lowercase of I
# is "ı". Map the six special pairs first, then fold diacritics away so that a user
# typing "kadikoy" on an English keyboard still finds "KADIKÖY".
_TR_LOWER = str.maketrans({"I": "ı", "İ": "i", "Ş": "ş", "Ğ": "ğ", "Ü": "ü", "Ö": "ö", "Ç": "ç"})
_TR_FOLD = str.maketrans({"ı": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c"})
_TOKEN_RE = re.compile(r"[0-9a-z]+")


def normalize_tr(text: str | None) -> str:
    """Fold Turkish text to a lowercase ASCII key for matching.

    ``"KADIKÖY İSKELE"`` and ``"kadikoy iskele"`` both become ``"kadikoy iskele"``.
    Punctuation collapses to single spaces, so ``"4. LEVENT"`` becomes ``"4 levent"``.
    """
    if not text:
        return ""
    lowered = text.translate(_TR_LOWER).lower().translate(_TR_FOLD)
    decomposed = unicodedata.normalize("NFKD", lowered)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(_TOKEN_RE.findall(stripped))


def _clean(value: str | None) -> str | None:
    """Demojibake + strip; empty becomes ``None`` so pydantic optionals stay honest."""
    return (demojibake(value) or "").strip() or None


# --------------------------------------------------------------------------------------
# stop sequence placeholder
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class RouteStopSequence:
    """The ordered stops of one route variant (``route_code`` -> stop_code list)."""

    route_code: str
    stop_codes: tuple[str, ...] = ()

    def position_of(self, stop_code: str) -> int | None:
        try:
            return self.stop_codes.index(stop_code)
        except ValueError:
            return None

    def stops_between(self, from_code: str, to_code: str) -> int | None:
        """Stops the bus still has to pass, or ``None`` if either stop is off this route."""
        a, b = self.position_of(from_code), self.position_of(to_code)
        if a is None or b is None or b < a:
            return None
        return b - a

    def __len__(self) -> int:
        return len(self.stop_codes)


def load_stop_sequences(settings: Settings) -> dict[str, RouteStopSequence]:
    """Return ``{route_code: RouteStopSequence}`` — currently always empty. Deliberately.

    Building real sequences needs ``stop_times.csv`` (26 MB) joined to ``trips.csv``
    (5.8 MB) on ``trip_id``, and neither file has been downloaded or inspected yet. We
    have therefore never seen their real column names, separator or encoding quirks, and
    guessing at them would produce a stop order that *looks* authoritative while being
    invented. This project does not ship invented numbers.

    Consequence for the ETA engine: with no sequence, ``stops_away`` is unavailable and
    the engine must fall back to straight-line distance between the bus and the stop
    (``BusArrival.method == "distance"``, lower confidence), or to the planned timetable.

    To finish this: download both files with :func:`download_gtfs`, verify their headers
    the way stops/routes were verified, then group ``stop_times`` by ``trip_id``, order by
    ``stop_sequence``, map ``stop_id`` -> ``stop_code`` through :class:`GtfsIndex`, and
    keep the longest trip per ``route_code`` as its canonical sequence.
    """
    path = settings.gtfs_dir / "stop_times.csv"
    if path.exists():
        log.warning(
            "%s is present but its schema has never been verified; returning no stop "
            "sequences so the ETA engine keeps its distance fallback.", path,
        )
    return {}


# --------------------------------------------------------------------------------------
# the index
# --------------------------------------------------------------------------------------
@dataclass
class GtfsIndex:
    """In-memory GTFS index. Build it once per process via :func:`get_index`."""

    gtfs_dir: pathlib.Path
    stops: list[Stop] = field(default_factory=list)
    routes: list[Route] = field(default_factory=list)
    loaded_at: dt.datetime = field(default_factory=utcnow)
    dropped_stops: int = 0
    dropped_routes: int = 0

    by_stop_code: dict[str, Stop] = field(init=False, default_factory=dict, repr=False)
    by_stop_id: dict[str, Stop] = field(init=False, default_factory=dict, repr=False)
    by_route_code: dict[str, Route] = field(init=False, default_factory=dict, repr=False)
    by_short_name: dict[str, list[Route]] = field(init=False, default_factory=dict, repr=False)
    _grid: dict[tuple[int, int], list[Stop]] = field(init=False, default_factory=dict, repr=False)
    _search_rows: list[tuple[str, Stop]] = field(init=False, default_factory=list, repr=False)
    #: How many distinct routes serve a stop. Empty until stop sequences exist; used only
    #: as a search tie-breaker, so an empty dict degrades to "shortest name wins".
    stop_route_counts: dict[str, int] = field(init=False, default_factory=dict, repr=False)

    # -- loading -----------------------------------------------------------------------
    @classmethod
    def load(cls, settings: Settings) -> "GtfsIndex":
        """Read ``stops.csv`` and ``routes.csv`` from ``settings.gtfs_dir``."""
        directory = pathlib.Path(settings.gtfs_dir)
        missing = [name for name in (STOPS_FILE, ROUTES_FILE) if not (directory / name).exists()]
        if missing:
            raise FileNotFoundError(
                f"GTFS reference files missing from {directory}: {', '.join(missing)}. "
                "Run ibb_mcp.gtfs.download_gtfs(settings) to fetch them."
            )
        stops, dropped_stops = _read_stops(directory / STOPS_FILE)
        routes, dropped_routes = _read_routes(directory / ROUTES_FILE)
        index = cls(
            gtfs_dir=directory,
            stops=stops,
            routes=routes,
            dropped_stops=dropped_stops,
            dropped_routes=dropped_routes,
        )
        index._build()
        log.info(
            "GTFS loaded: %d stops (%d dropped), %d routes from %s",
            len(stops), dropped_stops, len(routes), directory,
        )
        return index

    def _build(self) -> None:
        for stop in self.stops:
            if stop.stop_code:
                # First row wins: stop_code is unique in the real file apart from blanks.
                self.by_stop_code.setdefault(stop.stop_code, stop)
            if stop.stop_id:
                self.by_stop_id[stop.stop_id] = stop
            self._search_rows.append((normalize_tr(stop.name), stop))
            if stop.lat is not None and stop.lon is not None:
                self._grid.setdefault(_cell(stop.lat, stop.lon), []).append(stop)
        for route in self.routes:
            if route.route_code:
                self.by_route_code.setdefault(route.route_code.upper(), route)
            key = normalize_tr(route.short_name)
            if key:
                self.by_short_name.setdefault(key, []).append(route)

    def attach_stop_sequences(self, sequences: dict[str, RouteStopSequence]) -> None:
        """Feed in route stop orders once they exist, to sharpen search ranking.

        A stop served by twelve lines is almost always the one the user meant; without
        :func:`load_stop_sequences` we cannot know that, so this stays empty for now.
        """
        counts: dict[str, int] = {}
        for sequence in sequences.values():
            for code in set(sequence.stop_codes):
                counts[code] = counts.get(code, 0) + 1
        self.stop_route_counts = counts

    # -- lookups -----------------------------------------------------------------------
    @property
    def is_loaded(self) -> bool:
        return bool(self.by_stop_code) and bool(self.by_route_code)

    def lookup_stop(self, stop_code: str) -> Stop | None:
        """Resolve the live feed's ``yakinDurakKodu``. Leading zeros are preserved as-is."""
        if not stop_code:
            return None
        return self.by_stop_code.get(str(stop_code).strip())

    def lookup_stop_id(self, stop_id: str) -> Stop | None:
        return self.by_stop_id.get(str(stop_id).strip()) if stop_id else None

    def search_stops(self, query: str, limit: int = 10) -> list[Stop]:
        """Rank stops by name: exact, then prefix, then substring.

        A query that is itself a stop code short-circuits to that stop, so
        ``search_stops("228421")`` behaves like :meth:`lookup_stop`.
        """
        needle = normalize_tr(query)
        if not needle:
            return []
        exact_code = self.lookup_stop(str(query).strip())
        results: list[tuple[tuple[int, int, int, str], Stop]] = []
        for name_key, stop in self._search_rows:
            if not name_key:
                continue
            if name_key == needle:
                tier = 0
            elif name_key.startswith(needle):
                tier = 1
            elif needle in name_key:
                tier = 2
            else:
                continue
            if exact_code is not None and stop is exact_code:
                continue
            popularity = -self.stop_route_counts.get(stop.stop_code, 0)
            results.append(((tier, popularity, len(name_key), name_key), stop))
        results.sort(key=lambda item: item[0])
        ordered = [stop for _, stop in results]
        if exact_code is not None:
            ordered.insert(0, exact_code)
        return ordered[:limit]

    def nearest_stops(self, lat: float, lon: float, limit: int = 5, max_km: float = 1.0) -> list[Stop]:
        """Nearest stops within ``max_km``, each carrying ``distance_km``."""
        if lat is None or lon is None:
            return []
        candidates = self._cells_within(lat, lon, max_km)
        scored: list[tuple[float, Stop]] = []
        for stop in candidates:
            distance = haversine_km(lat, lon, stop.lat, stop.lon)  # type: ignore[arg-type]
            if distance <= max_km:
                scored.append((distance, stop))
        scored.sort(key=lambda item: item[0])
        return [
            stop.model_copy(update={"distance_km": round(distance, 3)})
            for distance, stop in scored[:limit]
        ]

    def _cells_within(self, lat: float, lon: float, max_km: float) -> Iterable[Stop]:
        """Every stop in the grid cells that could hold a point within ``max_km``."""
        lat_cells = math.ceil(max_km / (_KM_PER_DEG_LAT * GRID_DEG)) + 1
        km_per_deg_lon = max(_KM_PER_DEG_LAT * math.cos(math.radians(lat)), 1e-6)
        lon_cells = math.ceil(max_km / (km_per_deg_lon * GRID_DEG)) + 1
        base_lat, base_lon = _cell(lat, lon)
        for dy in range(-lat_cells, lat_cells + 1):
            for dx in range(-lon_cells, lon_cells + 1):
                yield from self._grid.get((base_lat + dy, base_lon + dx), ())

    def routes_for_short_name(self, short_name: str) -> list[Route]:
        """All route variants of a line: ``"500T"`` returns its 27 direction/variant rows."""
        return list(self.by_short_name.get(normalize_tr(short_name), ()))

    def route_by_code(self, route_code: str) -> Route | None:
        """Resolve the live feed's ``guzergahkodu`` (e.g. ``500T_G_D0``)."""
        if not route_code:
            return None
        return self.by_route_code.get(str(route_code).strip().upper())

    def line_codes(self) -> list[str]:
        """Distinct line short names, for tool input validation and suggestions."""
        return sorted({route.short_name for route in self.routes if route.short_name})

    def stats(self) -> dict[str, Any]:
        return {
            "loaded": self.is_loaded,
            "gtfs_dir": str(self.gtfs_dir),
            "loaded_at": self.loaded_at.isoformat(),
            "stops": len(self.stops),
            "stops_with_code": len(self.by_stop_code),
            "stops_without_code": sum(1 for stop in self.stops if not stop.stop_code),
            "stops_dropped": self.dropped_stops,
            "stops_geocoded": sum(len(bucket) for bucket in self._grid.values()),
            "grid_cells": len(self._grid),
            "routes": len(self.routes),
            "routes_with_code": len(self.by_route_code),
            "routes_dropped": self.dropped_routes,
            "line_short_names": len(self.by_short_name),
            "stop_sequences": len(self.stop_route_counts),
        }


def _cell(lat: float, lon: float) -> tuple[int, int]:
    return int(math.floor(lat / GRID_DEG)), int(math.floor(lon / GRID_DEG))


def _read_stops(path: pathlib.Path) -> tuple[list[Stop], int]:
    """Parse ``stops.csv``. Returns the stops plus the count dropped as unusable."""
    stops: list[Stop] = []
    dropped = 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            lat = repair_coordinate(row.get("stop_lat"), "lat")
            lon = repair_coordinate(row.get("stop_lon"), "lon")
            if lat is None or lon is None:
                # 4 of 15390 rows have a shifted column or scientific notation; a stop we
                # cannot place is worse than no stop, because it would poison "nearest".
                dropped += 1
                continue
            stops.append(
                Stop(
                    stop_code=(row.get("stop_code") or "").strip(),
                    stop_id=(row.get("stop_id") or "").strip() or None,
                    name=_clean(row.get("stop_name")),
                    description=_clean(row.get("stop_desc")),
                    lat=lat,
                    lon=lon,
                )
            )
    return stops, dropped


def _read_routes(path: pathlib.Path) -> tuple[list[Route], int]:
    """Parse ``routes.csv``. Every text column is demojibaked, ``VÄ°P`` included."""
    routes: list[Route] = []
    dropped = 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            route_id = (row.get("route_id") or "").strip()
            if not route_id:
                dropped += 1
                continue
            routes.append(
                Route(
                    route_id=route_id,
                    route_code=(row.get("route_code") or "").strip() or None,
                    short_name=_clean(row.get("route_short_name")),
                    long_name=_clean(row.get("route_long_name")),
                    description=_clean(row.get("route_desc")),
                )
            )
    return routes, dropped


# --------------------------------------------------------------------------------------
# module-level accessor
# --------------------------------------------------------------------------------------
_INDEX: GtfsIndex | None = None
_INDEX_KEY: str | None = None
_INDEX_LOCK = threading.Lock()


def get_index(settings: Settings | None = None) -> GtfsIndex:
    """Return the process-wide index, loading it on first use.

    Parsing 15k stops costs well under a second but is pure waste per request, and the
    MCP server is long-lived. The lock keeps two concurrent first calls from each paying
    that cost; a different ``gtfs_dir`` (tests, fixtures) rebuilds rather than silently
    serving another directory's data.
    """
    global _INDEX, _INDEX_KEY
    active = settings or Settings.from_env()
    key = str(pathlib.Path(active.gtfs_dir).resolve())
    with _INDEX_LOCK:
        if _INDEX is None or _INDEX_KEY != key:
            _INDEX = GtfsIndex.load(active)
            _INDEX_KEY = key
        return _INDEX


def reset_index_cache() -> None:
    """Drop the memoised index. For tests and for a post-download reload."""
    global _INDEX, _INDEX_KEY
    with _INDEX_LOCK:
        _INDEX = None
        _INDEX_KEY = None


def ensure_gtfs(settings: Settings) -> bool:
    """Whether the reference CSVs are present and non-empty. Never touches the network."""
    directory = pathlib.Path(settings.gtfs_dir)
    return all(
        (directory / name).is_file() and (directory / name).stat().st_size > 0
        for name in (STOPS_FILE, ROUTES_FILE)
    )


def download_gtfs(
    settings: Settings,
    resources: Sequence[str] = DEFAULT_GTFS_RESOURCES,
) -> dict[str, pathlib.Path]:
    """Download named GTFS resources into ``settings.gtfs_dir``.

    URLs come from ``tests/fixtures/gtfs_resources.json``, captured from the open data
    portal's package listing, so this does not depend on the CKAN API being up. Only the
    CSV variants are used. ``stop_times`` (26 MB) is never in the default set — ask for it
    by name if you really want it.
    """
    import httpx  # local import: the index itself must work without the HTTP stack

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
            destination.write_bytes(response.content)
            written[name] = destination
    if written:
        reset_index_cache()
    return written


def _resource_catalogue(settings: Settings) -> dict[str, str]:
    """``{resource name: CSV url}`` from the recorded portal listing."""
    import json

    path = pathlib.Path(settings.fixtures_dir) / "gtfs_resources.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    return {
        entry["name"]: entry["url"]
        for entry in entries
        if str(entry.get("format", "")).upper() == "CSV" and entry.get("url")
    }
