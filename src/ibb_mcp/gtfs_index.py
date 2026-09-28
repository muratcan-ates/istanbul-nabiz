"""GTFS index: ``stops.csv`` and ``routes.csv`` parsed once per process, with the live join keys.

The join keys, both verified against live data on 2026-09-08:

* ``yakinDurakKodu`` -> ``stops.stop_code``   (31/31 matched for line 500T)
* ``guzergahkodu``   -> ``routes.route_code`` (2/2 matched)

Note the first: it is ``stop_code``, **not** ``stop_id``. Those are different number
spaces in the İBB export, and joining on ``stop_id`` matches nothing at all — the worst
kind of bug here, because the ETA tool would quietly answer "no buses".

The export needs repair before use: a ``;`` separator and a UTF-8 BOM; coordinates
written with thousands separators (``410.191.700.005.564`` means ``41.0191700005564``,
see :func:`models.repair_coordinate`); and mojibaked text in ``routes.csv``
(see :func:`_fix_mojibake`). The stop-order and timetable tables built on top of this
index live in :mod:`ibb_mcp.gtfs_sequences` and :mod:`ibb_mcp.gtfs_timetables`; the
public entry point for all of it stays :mod:`ibb_mcp.gtfs`.
"""

from __future__ import annotations

import csv
import datetime as dt
import logging
import math
import pathlib
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from ibb_mcp.config import Settings, display_path
from ibb_mcp.models import Route, Stop, demojibake, haversine_km, repair_coordinate, utcnow
from ibb_mcp.text import normalize_tr

log = logging.getLogger(__name__)

#: Spatial grid cell size. 0.01° is ~1.11 km of latitude and ~0.84 km of longitude at
#: İstanbul's 41°N: a 1 km query touches a handful of cells, and 15k stops fill ~1900.
GRID_DEG = 0.01
_KM_PER_DEG_LAT = 111.32

STOPS_FILE = "stops.csv"
ROUTES_FILE = "routes.csv"


# --------------------------------------------------------------------------------------
# text
# --------------------------------------------------------------------------------------
# Name matching folds through ibb_mcp.text.normalize_tr, the one Turkish fold the gazetteer
# and the agent use too; it is imported here (and stays importable as
# ``ibb_mcp.gtfs.normalize_tr``) because the stop and route indexes are keyed by it.
_MOJIBAKE_MARKERS = ("Ã", "Å", "Ä", "Ð", "Þ")


def _fix_mojibake(text: str) -> str:
    """Undo the double-encoding in ``routes.csv``, including the bytes cp1252 cannot hold.

    ``models.demojibake`` re-encodes as cp1252 and recovers ``KADIKÃ–Y`` -> ``KADIKÖY``.
    But the exporter also emitted raw latin-1 bytes: ``Ş`` (UTF-8 ``C5 9E``) comes back as
    ``Å`` + U+009E, which cp1252 cannot encode at all — so that path bails out and 500T's
    name stays broken. Encoding each character as latin-1 when it fits in one byte and as
    cp1252 otherwise repairs both halves.
    """
    fixed = demojibake(text) or text
    if not any(marker in fixed for marker in _MOJIBAKE_MARKERS):
        return fixed
    raw = bytearray()
    try:
        for char in fixed:
            code = ord(char)
            raw.extend(bytes((code,)) if code < 0x100 else char.encode("cp1252"))
        return raw.decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return fixed  # Not mojibake after all; leave the text exactly as İBB sent it.


def clean_field(value: str | None) -> str | None:
    """Repair and strip; empty becomes ``None`` so the optional model fields stay honest."""
    return (_fix_mojibake(value) if value else "").strip() or None


# --------------------------------------------------------------------------------------
# index
# --------------------------------------------------------------------------------------
@dataclass
class GtfsIndex:
    """In-memory GTFS index. Build it once per process through :func:`get_index`."""

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
    #: How many distinct routes serve a stop; a search tie-breaker only. Empty until stop
    #: sequences exist, and an empty dict degrades gracefully to "shortest name wins".
    stop_route_counts: dict[str, int] = field(init=False, default_factory=dict, repr=False)
    #: How many route variants :meth:`attach_stop_sequences` was given. Counted separately
    #: from ``stop_route_counts`` (which is keyed by *stop*), so ``stats()`` cannot report
    #: 15 000 "stop sequences" when it was handed 9 000 routes.
    stop_sequence_count: int = field(init=False, default=0, repr=False)
    _grid: dict[tuple[int, int], list[Stop]] = field(init=False, default_factory=dict, repr=False)
    _search_rows: list[tuple[str, frozenset[str], Stop]] = field(
        init=False, default_factory=list, repr=False
    )

    @classmethod
    def load(cls, settings: Settings) -> GtfsIndex:
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
        index = cls(directory, stops, routes, dropped_stops=dropped_stops, dropped_routes=dropped_routes)
        index._build()
        log.info("GTFS loaded from %s: %d stops (%d dropped), %d routes (%d dropped)",
                 display_path(directory), len(stops), dropped_stops, len(routes), dropped_routes)
        return index

    def _build(self) -> None:
        for stop in self.stops:
            if stop.stop_code:
                # setdefault, not assignment: stop_code is unique in the real file, and if
                # a future export duplicates one, the first row should stay authoritative.
                self.by_stop_code.setdefault(stop.stop_code, stop)
            if stop.stop_id:
                self.by_stop_id[stop.stop_id] = stop
            key = normalize_tr(stop.name)
            self._search_rows.append((key, frozenset(key.split()), stop))
            if stop.lat is not None and stop.lon is not None:
                self._grid.setdefault(_cell(stop.lat, stop.lon), []).append(stop)
        for route in self.routes:
            if route.route_code:
                self.by_route_code.setdefault(route.route_code.upper(), route)
            if short := normalize_tr(route.short_name):
                self.by_short_name.setdefault(short, []).append(route)

    def attach_stop_sequences(self, sequences: Mapping[str, Any]) -> None:
        """Feed in route stop orders once they exist, to sharpen search ranking.

        ``sequences`` is ``{route_code: RouteStopSequence}`` from :mod:`ibb_mcp.gtfs_sequences`;
        only ``stop_codes`` is read here, so the type is not imported (it would be a cycle).

        A stop served by twelve lines is nearly always the one the user meant. Until
        :func:`load_stop_sequences` can produce sequences, there is no honest way to know
        that, so this stays unused rather than being approximated.
        """
        counts: dict[str, int] = {}
        for sequence in sequences.values():
            for code in set(sequence.stop_codes):
                counts[code] = counts.get(code, 0) + 1
        self.stop_route_counts = counts
        self.stop_sequence_count = len(sequences)

    @property
    def is_loaded(self) -> bool:
        return bool(self.by_stop_code) and bool(self.by_route_code)

    def lookup_stop(self, stop_code: str) -> Stop | None:
        """Resolve a live bus's ``yakinDurakKodu``. Codes are opaque strings, not ints."""
        return self.by_stop_code.get(str(stop_code).strip()) if stop_code else None

    def lookup_stop_id(self, stop_id: str) -> Stop | None:
        """Resolve a GTFS ``stop_id`` — the key ``stop_times.csv`` will use, not the live one."""
        return self.by_stop_id.get(str(stop_id).strip()) if stop_id else None

    def search_stops(self, query: str, limit: int = 10) -> list[Stop]:
        """Rank stops: exact name, then prefix, then substring, then all-tokens-present.

        A query that is itself a stop code short-circuits to that stop. Within a tier the
        86 stops that carry no ``stop_code`` sort last: they are real places and worth
        showing, but they cannot join to a live bus, and ``iett_next_arrivals`` takes the
        first hit as its ETA target. Then route count when known
        (:meth:`attach_stop_sequences`), then the shorter name, so "KADIKÖY" outranks
        "KADIKÖY İSKELE YOLU" for the query "kadıköy".
        """
        needle = normalize_tr(query)
        if not needle:
            return []
        tokens = frozenset(needle.split())
        by_code = self.lookup_stop(str(query).strip())
        scored: list[tuple[tuple[int, int, int, int, str, str], Stop]] = []
        for name_key, name_tokens, stop in self._search_rows:
            if not name_key or stop is by_code:
                continue
            if name_key == needle:
                tier = 0
            elif name_key.startswith(needle):
                tier = 1
            elif needle in name_key:
                tier = 2
            elif tokens <= name_tokens:
                tier = 3  # same words, different order: "iskele kadikoy"
            else:
                continue
            popularity = -self.stop_route_counts.get(stop.stop_code, 0)
            unjoinable = 0 if stop.stop_code else 1
            scored.append(
                ((tier, unjoinable, popularity, len(name_key), name_key, stop.stop_code), stop)
            )
        scored.sort(key=lambda item: item[0])
        ordered = [stop for _, stop in scored]
        if by_code is not None:
            ordered.insert(0, by_code)
        return ordered[:limit]

    def nearest_stops(self, lat: float, lon: float, limit: int = 5, max_km: float = 1.0) -> list[Stop]:
        """Nearest stops within ``max_km``, each returned with ``distance_km`` filled in."""
        if lat is None or lon is None:
            return []
        scored = [
            (haversine_km(lat, lon, stop.lat, stop.lon), stop)  # type: ignore[arg-type]
            for stop in self._candidates(lat, lon, max_km)
        ]
        scored = [pair for pair in scored if pair[0] <= max_km]
        scored.sort(key=lambda item: (item[0], item[1].stop_code))
        return [stop.model_copy(update={"distance_km": round(km, 3)}) for km, stop in scored[:limit]]

    def _candidates(self, lat: float, lon: float, max_km: float) -> Iterator[Stop]:
        """Stops in every grid cell that could hold a point within ``max_km``."""
        lat_cells = math.ceil(max_km / (_KM_PER_DEG_LAT * GRID_DEG)) + 1
        km_per_deg_lon = max(_KM_PER_DEG_LAT * math.cos(math.radians(lat)), 1e-6)
        lon_cells = math.ceil(max_km / (km_per_deg_lon * GRID_DEG)) + 1
        base_y, base_x = _cell(lat, lon)
        for dy in range(-lat_cells, lat_cells + 1):
            for dx in range(-lon_cells, lon_cells + 1):
                yield from self._grid.get((base_y + dy, base_x + dx), ())

    def routes_for_short_name(self, short_name: str) -> list[Route]:
        """All variants of a line: ``"500T"`` returns its 27 direction/deviation rows."""
        return list(self.by_short_name.get(normalize_tr(short_name), ()))

    def route_by_code(self, route_code: str) -> Route | None:
        """Resolve a live bus's ``guzergahkodu`` (e.g. ``500T_G_D0``).

        The retry covers the mirror image of the CSV's defect: the index holds repaired
        codes, so a caller that hands over a *mojibaked* code (a future feed regression, a
        value copied out of the raw CSV) still resolves instead of silently missing.
        """
        if not route_code:
            return None
        key = str(route_code).strip().upper()
        hit = self.by_route_code.get(key)
        if hit is None:
            repaired = _fix_mojibake(key)
            if repaired != key:
                hit = self.by_route_code.get(repaired)
        return hit

    def line_codes(self) -> list[str]:
        """Distinct line short names, for validating tool input and suggesting corrections."""
        return sorted({route.short_name for route in self.routes if route.short_name})

    def source_vintage(self) -> str | None:
        """When ``stops.csv`` was last written — the closest honest proxy for its vintage.

        ``loaded_at`` is only when *this process* parsed the file, and it resets on every
        restart; quoting it as freshness would make a months-old snapshot look minutes old.
        """
        path = self.gtfs_dir / STOPS_FILE
        try:
            return dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.UTC).isoformat()
        except OSError:
            return None

    def stats(self) -> dict[str, Any]:
        """Diagnostics for the freshness/health tool and for the loader's own smoke test."""
        return {
            "loaded": self.is_loaded, "gtfs_dir": str(self.gtfs_dir),
            "loaded_at": self.loaded_at.isoformat(),
            "source_vintage": self.source_vintage(),
            "stops": len(self.stops), "stops_with_code": len(self.by_stop_code),
            "stops_without_code": sum(1 for stop in self.stops if not stop.stop_code),
            "stops_dropped": self.dropped_stops, "grid_cells": len(self._grid),
            "routes": len(self.routes), "routes_with_code": len(self.by_route_code),
            "routes_dropped": self.dropped_routes,
            "line_short_names": len(self.by_short_name),
            "stop_sequences": self.stop_sequence_count,
            "stops_with_route_counts": len(self.stop_route_counts),
        }


def _cell(lat: float, lon: float) -> tuple[int, int]:
    return int(math.floor(lat / GRID_DEG)), int(math.floor(lon / GRID_DEG))


def _read_stops(path: pathlib.Path) -> tuple[list[Stop], int]:
    """Parse ``stops.csv``, returning the stops plus how many rows were unusable.

    86 rows have an empty ``stop_code``: kept, because they are still searchable and
    locatable, but absent from the live-join index (``stats()["stops_without_code"]``).
    """
    stops: list[Stop] = []
    dropped = 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            lat = repair_coordinate(row.get("stop_lat"), "lat")
            lon = repair_coordinate(row.get("stop_lon"), "lon")
            if lat is None or lon is None:
                # 4 of 15390 rows have a shifted column or scientific notation. A stop we
                # cannot place is worse than no stop: it would poison "nearest".
                dropped += 1
                continue
            stops.append(Stop(
                stop_code=(row.get("stop_code") or "").strip(),
                stop_id=(row.get("stop_id") or "").strip() or None,
                name=clean_field(row.get("stop_name")),
                description=clean_field(row.get("stop_desc")),
                lat=lat,
                lon=lon,
            ))
    return stops, dropped


def _read_routes(path: pathlib.Path) -> tuple[list[Route], int]:
    """Parse ``routes.csv``. Every text column is repaired, ``route_short_name`` included."""
    routes: list[Route] = []
    dropped = 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            route_id = (row.get("route_id") or "").strip()
            if not route_id:
                dropped += 1
                continue
            routes.append(Route(
                route_id=route_id,
                # route_code is mojibaked too, in 529 of 9264 rows: the CSV holds
                # "11Ã‡B_D_D0" while the live feed sends a clean UTF-8 "11ÇB_D_D0".
                # Repairing it here is what makes the guzergahkodu join work for the
                # lines whose short name carries a Turkish letter (11ÇB, 133Ş, ...).
                route_code=clean_field(row.get("route_code")),
                short_name=clean_field(row.get("route_short_name")),
                long_name=clean_field(row.get("route_long_name")),
                description=clean_field(row.get("route_desc")),
            ))
    return routes, dropped


# --------------------------------------------------------------------------------------
# module-level accessor
# --------------------------------------------------------------------------------------
_INDEX: GtfsIndex | None = None
_INDEX_KEY: str | None = None
_INDEX_LOCK = threading.Lock()


def get_index(settings: Settings | None = None) -> GtfsIndex:
    """Return the process-wide index, loading it on first use.

    Parsing 15k stops takes under a second — pure waste per request in a long-lived
    server. The lock keeps two concurrent first calls from both paying it, and a different
    ``gtfs_dir`` rebuilds rather than silently serving another directory's data.
    """
    global _INDEX, _INDEX_KEY
    active = settings or Settings.from_env()
    key = str(pathlib.Path(active.gtfs_dir).resolve())
    with _INDEX_LOCK:
        if _INDEX is None or key != _INDEX_KEY:
            _INDEX = GtfsIndex.load(active)
            _INDEX_KEY = key
        return _INDEX


def reset_index_cache() -> None:
    """Drop the memoised index. For tests and after a fresh download."""
    global _INDEX, _INDEX_KEY
    with _INDEX_LOCK:
        _INDEX = None
        _INDEX_KEY = None

