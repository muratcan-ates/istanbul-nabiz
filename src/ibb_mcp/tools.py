"""The tool layer: one façade that turns sources into answers an agent can cite.

Every method returns a :class:`ToolResult` whose ``data`` is plain JSON-friendly types and
whose ``provenance`` carries the source URL and the age of the reading. That envelope is
what makes the numeric-faithfulness check in the eval harness possible: the agent may only
say a number that appears in a tool result.

Tools are deliberately parametric. There is no free-form query tool and no natural-language
to KQL/SQL path, because a tool the model can shape arbitrarily is a tool whose output
nobody can verify.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Any

from ibb_mcp.config import ATTRIBUTION, ATTRIBUTION_EN, Settings
from ibb_mcp.http import UpstreamUnavailable
from ibb_mcp.models import (
    ISTANBUL_TZ,
    ToolResult,
    aqi_band,
    day_type_for,
    describe_traffic,
    utcnow,
)
from ibb_mcp.sources.base import SourceContext, make_provenance
from ibb_mcp.sources.places import Place, get_place_index

log = logging.getLogger("ibb_mcp.tools")


def _dump(model: Any) -> Any:
    """Serialise pydantic models (and lists of them) for a tool response."""
    if isinstance(model, list):
        return [_dump(item) for item in model]
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json", exclude_none=True)
    if isinstance(model, dt.datetime):
        return model.isoformat()
    return model


class Nabiz:
    """Holds one context and one instance of each source for the process lifetime."""

    def __init__(self, ctx: SourceContext | None = None) -> None:
        self.ctx = ctx or SourceContext.create()
        self.settings: Settings = self.ctx.settings
        self.places = get_place_index(self.settings)
        self._sources: dict[str, Any] = {}
        self._gtfs = None
        self._gtfs_lock = asyncio.Lock()

    # -- lazy source construction -------------------------------------------------
    def _source(self, name: str):
        """Import sources lazily so a broken optional module cannot break the server."""
        if name not in self._sources:
            if name == "ispark":
                from ibb_mcp.sources.ispark import IsparkSource

                self._sources[name] = IsparkSource(self.ctx)
            elif name == "iett":
                from ibb_mcp.sources.iett import IettSource

                self._sources[name] = IettSource(self.ctx)
            elif name == "metro":
                from ibb_mcp.sources.metro import MetroSource

                self._sources[name] = MetroSource(self.ctx)
            elif name == "traffic":
                from ibb_mcp.sources.traffic import TrafficSource

                self._sources[name] = TrafficSource(self.ctx)
            elif name == "aq":
                from ibb_mcp.sources.airquality import AirQualitySource

                self._sources[name] = AirQualitySource(self.ctx)
            else:  # pragma: no cover - programming error
                raise KeyError(name)
        return self._sources[name]

    async def gtfs(self):
        """Load the GTFS index once, off the event loop (it parses a 1.5 MB CSV)."""
        if self._gtfs is None:
            async with self._gtfs_lock:
                if self._gtfs is None:
                    from ibb_mcp.gtfs import get_index

                    self._gtfs = await asyncio.to_thread(get_index, self.settings)
        return self._gtfs

    async def aclose(self) -> None:
        await self.ctx.aclose()

    # -- helpers ------------------------------------------------------------------
    def _resolve_place(self, query: str) -> Place:
        place = self.places.resolve_one(query)
        if place is None:
            raise ValueError(
                f"'{query}' için bir yer bulamadım. Semt, ilçe veya metro istasyonu adı deneyin "
                "(örnek: Taksim, Kadıköy, Levent)."
            )
        return place

    @staticmethod
    def _attribution() -> dict[str, str]:
        return {"tr": ATTRIBUTION, "en": ATTRIBUTION_EN}

    # -- 1. places ----------------------------------------------------------------
    async def places_resolve(self, query: str, limit: int = 5) -> ToolResult:
        """Turn a place name into coordinates."""
        matches = self.places.resolve(query, limit=limit)
        return ToolResult(
            data={
                "query": query,
                "matches": [
                    {"name": p.name, "label": p.label, "lat": p.lat, "lon": p.lon, "kind": p.kind, "district": p.district}
                    for p in matches
                ],
            },
            provenance=make_provenance("gazetteer", url="local:data/reference/places.csv"),
            note=None if matches else "Eşleşme yok.",
        )

    # -- 2. parking ---------------------------------------------------------------
    async def ispark_find_parking(
        self,
        place: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius_km: float | None = None,
        min_free: int = 1,
        open_now: bool = True,
        with_tariff: bool = True,
    ) -> ToolResult:
        """Car parks near a place, with live free-space counts."""
        if lat is None or lon is None:
            if not place:
                raise ValueError("place ya da lat/lon vermelisiniz.")
            resolved = self._resolve_place(place)
            lat, lon, label = resolved.lat, resolved.lon, resolved.label
        else:
            label = f"{lat:.4f}, {lon:.4f}"

        source = self._source("ispark")
        radius = radius_km or self.settings.default_radius_km
        lots, prov = await source.find_near(lat, lon, radius_km=radius, min_free=min_free, open_now=open_now)

        notes: list[str] = []
        if with_tariff and lots:
            enriched = await source.enrich(lots)
            # The per-lot detail endpoint is fresher than the bulk list, so a lot that had
            # space a moment ago can come back full. Re-applying the filter here keeps the
            # promise the caller made ("at least min_free spaces") instead of quietly
            # returning a full car park with a tariff attached.
            if min_free > 0:
                kept = [lot for lot in enriched if lot.empty is None or lot.empty >= min_free]
                filled = [lot for lot in enriched if lot not in kept]
                if filled:
                    notes.append(
                        f"{len(filled)} otopark ({', '.join(lot.name for lot in filled[:3])}) "
                        "güncel detay verisinde dolu göründüğü için listeden çıkarıldı; "
                        "detay ölçümü toplu listeden daha tazedir."
                    )
                lots = kept
            else:
                lots = enriched

        if not lots:
            notes.append(f"{label} çevresinde {radius:.1f} km içinde boş yeri olan açık otopark bulunamadı.")
        elif any(lot.distance_km is not None and lot.distance_km > radius for lot in lots):
            notes.append(f"En yakın uygun otopark istenen {radius:.1f} km yarıçapın dışında kaldı.")

        return ToolResult(
            data={"near": label, "lat": lat, "lon": lon, "radius_km": radius, "count": len(lots), "parks": _dump(lots)},
            provenance=prov,
            note=" ".join(notes) or None,
        )

    async def ispark_typical_occupancy(self, park_id: int, weekday: int | None = None, hour: int | None = None) -> ToolResult:
        """Historical occupancy for a car park at a given weekday and hour.

        The profile is built from snapshots this project collects itself, because İBB
        publishes only the current occupancy and keeps no history. Until the collector has
        run for a few days the answer says so instead of guessing.
        """
        from ibb_mcp.analytics import occupancy_profile  # local import: optional dependency

        now = utcnow().astimezone(ISTANBUL_TZ)
        weekday = now.weekday() if weekday is None else weekday
        hour = now.hour if hour is None else hour
        profile = await occupancy_profile(self.ctx, park_id=park_id, weekday=weekday, hour=hour)
        return ToolResult(
            data=profile,
            provenance=make_provenance("nabiz_history", url="local:gold/ispark_profile"),
            note=profile.get("note"),
        )

    # -- 3. buses -----------------------------------------------------------------
    async def iett_stops_search(self, query: str, limit: int = 8) -> ToolResult:
        """Find bus stops by name."""
        index = await self.gtfs()
        stops = index.search_stops(query, limit=limit)
        return ToolResult(
            data={"query": query, "count": len(stops), "stops": _dump(stops)},
            provenance=make_provenance("gtfs", url="https://data.ibb.gov.tr/dataset/iett-gtfs-verisi"),
            note=None if stops else f"'{query}' için durak bulunamadı.",
        )

    async def iett_line_buses(self, line_code: str, direction: str | None = None) -> ToolResult:
        """Where the buses on a line are right now."""
        from ibb_mcp.sources.iett import buses_towards

        buses, prov = await self._source("iett").line_positions(line_code)
        if direction:
            buses = buses_towards(buses, direction)
        return ToolResult(
            data={
                "line_code": line_code.upper().strip(),
                "count": len(buses),
                "directions": sorted({b.direction for b in buses if b.direction}),
                "buses": _dump(buses),
            },
            provenance=prov,
            note=None if buses else f"{line_code} hattında şu anda konum bildiren araç yok.",
        )

    async def iett_next_arrivals(self, line_code: str, stop: str, limit: int = 3) -> ToolResult:
        """Estimated arrivals of a line at a stop.

        These are estimates, not a published timetable guarantee; the method used for each
        estimate is returned so the agent can say how it was derived.
        """
        from ibb_mcp.eta import EtaParams, estimate_arrivals, speed_profile_from_fleet

        index = await self.gtfs()
        target = index.lookup_stop(stop) if stop.isdigit() else None
        if target is None:
            candidates = index.search_stops(stop, limit=1)
            if not candidates:
                raise ValueError(f"'{stop}' için durak bulunamadı. Durak adını veya durak kodunu deneyin.")
            target = candidates[0]

        source = self._source("iett")
        buses, prov = await source.line_positions(line_code)
        scheduled = None
        if not buses:
            scheduled, _ = await source.schedule(line_code, day_type=day_type_for())

        params = EtaParams(max_results=limit)
        try:
            fleet, _ = await source.fleet_positions()
            params = EtaParams(max_results=limit, speed_kmh=speed_profile_from_fleet(fleet))
        except (UpstreamUnavailable, Exception) as exc:  # noqa: BLE001 - the fleet call is optional
            log.info("fleet speed profile unavailable, using default: %r", exc)

        sequences = None
        try:
            from ibb_mcp.gtfs import load_stop_sequences

            sequences = await asyncio.to_thread(load_stop_sequences, self.settings)
        except Exception as exc:  # noqa: BLE001 - stop_times.csv is optional
            log.info("stop sequences unavailable: %r", exc)

        arrivals, diagnostics = estimate_arrivals(
            buses=buses, target=target, index=index, sequences=sequences, scheduled=scheduled, params=params
        )
        return ToolResult(
            data={
                "line_code": line_code.upper().strip(),
                "stop": _dump(target),
                "arrivals": _dump(arrivals),
                "diagnostics": diagnostics,
                "disclaimer": "Varış saatleri tahminidir; resmi İETT bilgisi değildir.",
            },
            provenance=prov,
            note=None if arrivals else "Yaklaşan araç bulunamadı.",
        )

    # -- 4. metro -----------------------------------------------------------------
    async def metro_status(self, line: str | None = None) -> ToolResult:
        """Live disruption notices. An absent line means no reported disruption."""
        statuses, prov = await self._source("metro").service_status()
        if line:
            wanted = line.strip().casefold()
            statuses = [s for s in statuses if (s.line_name or "").casefold() == wanted]
            note = (
                f"{line.upper()} için bildirilmiş bir arıza/çalışma duyurusu yok."
                if not statuses
                else None
            )
        else:
            note = "Bildirilmiş arıza/çalışma duyurusu yok." if not statuses else None
        return ToolResult(
            data={"count": len(statuses), "lines": _dump(statuses)},
            provenance=prov,
            note=note,
        )

    async def metro_station_info(self, name: str) -> ToolResult:
        """Station details including step-free access."""
        source = self._source("metro")
        matches = await source.find_station(name)
        if not matches:
            raise ValueError(f"'{name}' adlı bir metro istasyonu bulamadım.")
        _, prov = await source.stations()
        return ToolResult(data={"query": name, "count": len(matches), "stations": _dump(matches)}, provenance=prov)

    # -- 5. traffic ---------------------------------------------------------------
    async def traffic_index(self, window: str = "now") -> ToolResult:
        """City-wide traffic index, 1 (free flowing) to 99 (gridlocked)."""
        source = self._source("traffic")
        if window == "now":
            point, prov = await source.current()
            data: dict[str, Any] = {
                "index": point.index if point else None,
                "at": _dump(point.at) if point else None,
                "description": describe_traffic(point.index) if point else None,
            }
        else:
            points, prov = await source.index_history(days=1, period="H")
            comparison = source.compare_with_yesterday(points)
            data = {"history": _dump(points[:24]), **comparison}
        return ToolResult(data=data, provenance=prov)

    # -- 6. air quality -----------------------------------------------------------
    async def air_quality_now(self, place: str) -> ToolResult:
        """Latest air-quality reading at the station nearest a place."""
        source = self._source("aq")
        resolved = self._resolve_place(place)
        station = await source.nearest_station(resolved.lat, resolved.lon)
        if station is None:
            raise ValueError(f"{resolved.label} yakınında hava kalitesi istasyonu bulunamadı.")
        reading, prov = await source.latest(station.station_id)
        band = aqi_band(reading.aqi_index) if reading else None
        return ToolResult(
            data={
                "place": resolved.label,
                "station": _dump(station),
                "reading": _dump(reading),
                "band": {"label": band[0], "key": band[1]} if band else None,
                "disclaimer": "Sağlık tavsiyesi değildir.",
            },
            provenance=prov,
            note=None if reading else "İstasyondan güncel ölçüm gelmiyor.",
        )

    async def air_quality_forecast(self, place: str, horizon_hours: int = 6) -> ToolResult:
        """Short-horizon forecast and the cleanest upcoming window."""
        from ibb_mcp.analytics import air_quality_forecast as forecast_impl

        resolved = self._resolve_place(place)
        source = self._source("aq")
        station = await source.nearest_station(resolved.lat, resolved.lon)
        if station is None:
            raise ValueError(f"{resolved.label} yakınında hava kalitesi istasyonu bulunamadı.")
        result = await forecast_impl(self.ctx, station=station, horizon_hours=horizon_hours)
        return ToolResult(
            data={"place": resolved.label, "station": _dump(station), **result},
            provenance=make_provenance("nabiz_forecast", url="local:gold/aq_forecast"),
            note=result.get("note"),
        )

    # -- 7. freshness -------------------------------------------------------------
    async def city_freshness(self) -> ToolResult:
        """How old the data behind each source is. The agent quotes this when hedging."""
        freshness = self.ctx.cache.freshness()
        budgets = {name: budget.remaining for name, budget in self.ctx.client.budgets.items()}
        return ToolResult(
            data={
                "sources": freshness,
                "request_budget_remaining": budgets,
                "attribution": self._attribution(),
                "checked_at": _dump(utcnow()),
            },
            provenance=make_provenance("nabiz_runtime", url="local:cache"),
            note=None if freshness else "Henüz hiçbir kaynak sorgulanmadı.",
        )
