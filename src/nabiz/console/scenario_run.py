"""Run the accessible journey planner twice against one in-memory equipment snapshot."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from ibb_mcp.http import RateLimitExceeded, UpstreamUnavailable
from ibb_mcp.models import MetroStation
from ibb_mcp.tools import Nabiz
from nabiz.console.cards import provenance_view, unknown_provenance
from nabiz.console.scenario import (
    ASSUMPTIONS,
    EFFECTS,
    SAVED_ASSUMPTIONS,
    classify,
    closure_info,
    closure_records,
    line_key,
    resolve_platforms,
    summarize,
)
from nabiz.console.scenario_store import SavedJourneyBatch, SavedJourneys


class _MetroView:
    def __init__(self, source: Any, cache: dict[str, Any]) -> None:
        self.source, self.cache = source, cache

    async def stations(self):
        if "stations" not in self.cache:
            self.cache["stations"] = await self.source.stations()
        return self.cache["stations"]


class _EquipmentView:
    def __init__(self, source: Any, cache: dict[str, Any], closed: Sequence[Any]) -> None:
        self.source, self.cache, self.closed = source, cache, closed

    async def snapshot(self, groups=("Asansör",)):
        key = ("equipment", tuple(groups))
        if key not in self.cache:
            self.cache[key] = await self.source.snapshot(groups)
        snapshot, provenance = self.cache[key]
        if not self.closed:
            return snapshot, provenance
        return snapshot.model_copy(update={"records": [*snapshot.records, *self.closed]}), provenance


class ScenarioFacade:
    """Narrow wrapper that overlays scenario rows without mutating a real source or cache."""

    def __init__(self, nabiz: Any, closed: Sequence[Any] | None, cache: dict[str, Any]) -> None:
        self._nabiz = nabiz
        self._closed = tuple(closed or ())
        self._cache = cache
        self.settings = nabiz.settings

    def _source(self, name: str):
        if name == "metro" and "metro_source" in self._cache:
            source = self._cache["metro_source"]
        elif name == "metro_equipment" and "equipment_source" in self._cache:
            source = self._cache["equipment_source"]
        else:
            source = self._nabiz._source(name)
        if name == "metro":
            return _MetroView(source, self._cache)
        if name == "metro_equipment":
            return _EquipmentView(source, self._cache, self._closed)
        return source

    def _endpoint(self, name, lat, lon, *, role):
        return self._nabiz._endpoint(name, lat, lon, role=role)


def _stamp(provenance: Any, nabiz: Any) -> dict[str, Any]:
    if provenance is None:
        return unknown_provenance("metro_equipment")
    return provenance_view(provenance, offline=nabiz.settings.offline)


def _unverified_route(route: Mapping[str, Any], reason: str) -> dict[str, Any]:
    empty = {"available": None, "extra_minutes": None, "reason": reason, "uncertainty": ["source_unavailable"]}
    return {
        **dict(route),
        "label": f"{route['from']} > {route['to']}",
        "effect": "unverified",
        "before": {"available": None, "extra_minutes": None, "reason": reason},
        "after": {"available": None, "extra_minutes": None, "reason": reason, "alternative": None},
        "added_minutes": None,
        "uncertainty": empty["uncertainty"],
        "error": None,
    }


async def _planner_pair(
    nabiz: Any,
    route: Mapping[str, Any],
    station: str,
    closed: Sequence[Any],
    cache: dict[str, Any],
):
    before = await Nabiz.accessible_journey(ScenarioFacade(nabiz, (), cache), route["from"], route["to"], route["needs"])
    after = await Nabiz.accessible_journey(ScenarioFacade(nabiz, closed, cache), route["from"], route["to"], route["needs"])
    return before, after


def _station_lift_count(platforms: Sequence[MetroStation]) -> int | None:
    values = [item.lifts for item in platforms]
    return None if any(value is None for value in values) else sum(value or 0 for value in values)


def _closure_without_snapshot(stations: Sequence[MetroStation], station: str, line: str | None) -> dict[str, Any]:
    platforms = resolve_platforms(station, stations)
    if line:
        platforms = [item for item in platforms if line_key(item.line_name) == line_key(line)]
    if not platforms:
        raise LookupError(station)
    count = _station_lift_count(platforms)
    return {
        "station": platforms[0].name or station,
        "lines": sorted({item.line_name for item in platforms if item.line_name}),
        "lift_count": count,
        "already_faulty": False,
        "no_lift_record": any(item.lifts in (None, 0) for item in platforms),
        "hypothetical": True,
    }


def _saved_placeholder(status: str) -> dict[str, Any]:
    return {"status": status, "considered": None, "effects": None, "truncated": False}


async def _read_sources(nabiz: Any, cache: dict[str, Any]):
    metro_source = nabiz._source("metro")
    equipment_source = nabiz._source("metro_equipment")
    cache["metro_source"] = metro_source
    cache["equipment_source"] = equipment_source
    stations = None
    snapshot = None
    provenance = None
    source_error = None
    try:
        stations, stamp = await metro_source.stations()
        cache["stations"] = (stations, stamp)
    except (RateLimitExceeded, UpstreamUnavailable) as exc:
        source_error = exc
    try:
        snapshot, provenance = await equipment_source.snapshot(("Asansör",))
        cache[("equipment", ("Asansör",))] = (snapshot, provenance)
    except (RateLimitExceeded, UpstreamUnavailable) as exc:
        source_error = source_error or exc
    return stations, snapshot, provenance, source_error


def _closure(
    stations: Sequence[MetroStation] | None,
    snapshot: Any,
    station: str,
    line: str | None,
) -> tuple[dict[str, Any], list[Any]]:
    if stations is None:
        return (
            {
                "station": station,
                "lines": [],
                "lift_count": None,
                "already_faulty": False,
                "no_lift_record": True,
                "hypothetical": True,
            },
            [],
        )
    closed = closure_records(stations, station, line)
    info = (
        closure_info(stations, station, line, snapshot)
        if snapshot is not None
        else _closure_without_snapshot(stations, station, line)
    )
    return info, closed


async def _compare_routes(
    nabiz: Any,
    station: str,
    routes: Sequence[Mapping[str, Any]],
    closed: Sequence[Any],
    cache: dict[str, Any],
    sample: bool,
    source_error: Exception | None,
) -> tuple[list[dict[str, Any]], str | None]:
    rows = []
    disclaimer = None
    for raw in routes:
        route = {**raw, "sample": bool(sample or raw.get("sample"))}
        route["label"] = f"{route['from']} > {route['to']}"
        if source_error is not None:
            rows.append(_unverified_route(route, "Kaynak verisi okunamadı; güzergâh doğrulanamadı."))
            continue
        try:
            before, after = await _planner_pair(nabiz, route, station, closed, cache)
            disclaimer = disclaimer or after.data.get("disclaimer")
            rows.append({**route, **classify(before.data, after.data, station), "error": None})
        except (LookupError, ValueError) as exc:
            rows.append(
                {
                    **route,
                    "effect": "unverified",
                    "before": {"available": None, "extra_minutes": None, "reason": str(exc)},
                    "after": {"available": None, "extra_minutes": None, "reason": str(exc), "alternative": None},
                    "added_minutes": None,
                    "uncertainty": [],
                    "error": str(exc),
                }
            )
    return rows, disclaimer


async def _count_saved(
    nabiz: Any,
    station: str,
    closed: Sequence[Any],
    cache: dict[str, Any],
    batch: SavedJourneyBatch,
    source_error: Exception | None = None,
) -> dict[str, Any]:
    if batch.status != "ok":
        return _saved_placeholder(batch.status)
    effects: Counter[str] = Counter()
    if source_error is not None:
        effects["unverified"] = batch.considered
        return {
            "status": "ok",
            "considered": batch.considered,
            "effects": {effect: effects.get(effect, 0) for effect in EFFECTS},
            "truncated": batch.truncated,
        }
    for route, count in batch.pairs:
        before, after = await _planner_pair(nabiz, route, station, closed, cache)
        effect = classify(before.data, after.data, station)["effect"]
        effects[effect] += count
    return {
        "status": "ok",
        "considered": batch.considered,
        "effects": {effect: effects.get(effect, 0) for effect in EFFECTS},
        "truncated": batch.truncated,
    }


async def run_scenario(
    nabiz: Any,
    station: str,
    line: str | None,
    routes: Sequence[Mapping[str, Any]],
    *,
    include_saved: bool = False,
    sample: bool = False,
    saved_source: SavedJourneys | None = None,
) -> dict[str, Any]:
    """Return route comparisons from two plans per row, reusing one source snapshot."""
    cache: dict[str, Any] = {}
    stations, snapshot, provenance, source_error = await _read_sources(nabiz, cache)
    closure, closed = _closure(stations, snapshot, station, line)
    saved_reader = saved_source or SavedJourneys()
    if include_saved:
        batch = saved_reader.read()
        saved = await _count_saved(nabiz, station, closed, cache, batch, source_error)
    else:
        saved = _saved_placeholder(saved_reader.status())

    output_rows, disclaimer = await _compare_routes(nabiz, station, routes, closed, cache, sample, source_error)
    summary = summarize(output_rows, saved)
    assumptions = list(ASSUMPTIONS)
    if include_saved and saved["status"] == "ok":
        assumptions.extend(SAVED_ASSUMPTIONS)
    return {
        "closure": closure,
        "assumptions": assumptions,
        "routes": output_rows,
        "counts": summary["counts"],
        "saved": summary["saved"],
        "provenance": _stamp(provenance, nabiz),
        "disclaimer": disclaimer,
    }
