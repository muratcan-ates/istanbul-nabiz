"""Location-scoped nearby cards for the citizen console.

The browser sends its position only with the request that needs it. This module neither logs
nor stores coordinates; source failures become unknown provenance so one broken feed cannot
blank the page.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from ibb_mcp.models import LAT_RANGE, LON_RANGE, Provenance, haversine_km, utcnow
from nabiz.console.brief import split_csv
from nabiz.console.cards import mode_for, provenance_view, unknown_provenance
from nabiz.console.policy import functional_needs

log = logging.getLogger("nabiz.console.nearby")
nearby_router = APIRouter()
_UNKNOWN_LIFT = {"working", "out_of_service", "unknown"}


class JourneyRequest(BaseModel):
    """The two points needed by the existing journey comparison tool."""

    origin_lat: float = Field(ge=LAT_RANGE[0], le=LAT_RANGE[1])
    origin_lon: float = Field(ge=LON_RANGE[0], le=LON_RANGE[1])
    destination_lat: float = Field(ge=LAT_RANGE[0], le=LAT_RANGE[1])
    destination_lon: float = Field(ge=LON_RANGE[0], le=LON_RANGE[1])
    destination_name: str = Field(min_length=1, max_length=120)


def _unknown(source: str) -> dict[str, Any]:
    return unknown_provenance(source)


def _gtfs_provenance(index: Any, *, offline: bool) -> dict[str, Any]:
    vintage = index.source_vintage()
    if not vintage:
        return _unknown("gtfs")
    try:
        reported_at = dt.datetime.fromisoformat(vintage)
    except ValueError:
        return _unknown("gtfs")
    prov = Provenance(
        source="gtfs",
        source_url="local:data/reference/gtfs/stops.csv",
        observed_at=utcnow(),
        reported_at=reported_at,
    )
    return provenance_view(prov, offline=offline, mode=mode_for(offline))


def _stop_rows(index: Any, lat: float, lon: float, *, offline: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    provenance = _gtfs_provenance(index, offline=offline)
    rows = []
    for stop in index.nearest_stops(lat, lon, limit=3):
        rows.append(
            {
                "name": stop.name,
                "stop_code": stop.stop_code,
                "distance_m": int(round(stop.distance_km * 1000)) if stop.distance_km is not None else None,
                "lat": stop.lat,
                "lon": stop.lon,
                "provenance": dict(provenance),
            }
        )
    return rows, provenance


def _nearby_stations(stations: list[Any], lat: float, lon: float) -> list[tuple[float, Any]]:
    nearest: dict[str, tuple[float, Any]] = {}
    for station in stations:
        if not station.name or station.lat is None or station.lon is None:
            continue
        distance = haversine_km(lat, lon, station.lat, station.lon)
        key = station.name.casefold()
        if key not in nearest or distance < nearest[key][0]:
            nearest[key] = (distance, station)
    return sorted(nearest.values(), key=lambda row: (row[0], row[1].name or ""))


async def _metro_card(
    nabiz: Any,
    lat: float,
    lon: float,
    *,
    needs: list[str],
    offline: bool,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    try:
        stations = [place for place in nabiz.places.places if place.kind == "metro_station"]
    except Exception as exc:  # noqa: BLE001 - local gazetteer failure is an unknown card
        log.warning("nearby metro list failed: %s", type(exc).__name__)
        return None, _unknown("gazetteer")
    candidates = _nearby_stations(stations, lat, lon)
    if not candidates:
        return None, _unknown("gazetteer")

    first: tuple[dict[str, Any], dict[str, Any]] | None = None
    for distance, station in candidates:
        station_data: dict[str, Any] = {}
        try:
            result = await nabiz.metro_equipment_status(station=station.name, group="Asansör")
            data = result.data if isinstance(result.data, dict) else {}
            station_data = data.get("station") or {}
            provenance = provenance_view(result.provenance, offline=offline)
            readable = data.get("available") is True and "Asansör" in (data.get("groups_read") or [])
            station_status = "unknown" if not readable else station_data.get("lift_status", "unknown")
        except Exception as exc:  # noqa: BLE001 - an unreadable source is an unknown card
            log.warning("nearby metro equipment failed: %s", type(exc).__name__)
            provenance = _unknown("metro_equipment")
            station_status, readable = "unknown", False
        if station_status not in _UNKNOWN_LIFT:
            station_status = "unknown"
        card = {
            "station": station.name,
            "line": (station_data.get("lines") or [None])[0],
            "distance_m": int(round(distance * 1000)),
            "lift_status": station_status,
            "lat": station.lat,
            "lon": station.lon,
            "provenance": dict(provenance),
        }
        if first is None:
            first = (card, provenance)
        if not readable or "step_free" not in needs or station_status == "working":
            return card, provenance
    return first if first is not None else (None, _unknown("metro_stations"))


async def _parking_card(nabiz: Any, lat: float, lon: float, *, offline: bool) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    try:
        result = await nabiz.ispark_find_parking(lat=lat, lon=lon, min_free=1, with_tariff=False)
    except Exception as exc:  # noqa: BLE001 - this source must not break nearby results
        log.warning("nearby parking failed: %s", type(exc).__name__)
        return None, _unknown("ispark")
    provenance = provenance_view(result.provenance, offline=offline)
    parks = result.data.get("parks") or []
    if not parks:
        return None, provenance
    park = parks[0]
    distance = park.get("distance_km")
    if distance is None and park.get("lat") is not None and park.get("lon") is not None:
        distance = haversine_km(lat, lon, park["lat"], park["lon"])
    if distance is None:
        return None, provenance
    return (
        {
            "name": park.get("name") or "İSPARK",
            "distance_m": int(round(distance * 1000)),
            "empty": park.get("empty"),
            "lat": park.get("lat"),
            "lon": park.get("lon"),
            "provenance": provenance,
        },
        provenance,
    )


async def nearby_view(
    nabiz: Any,
    lat: float,
    lon: float,
    *,
    needs: list[str],
    offline: bool,
) -> dict[str, Any]:
    """Build the nearby response while keeping each source failure local to its card."""
    try:
        index = await nabiz.gtfs()
        stops, stops_prov = _stop_rows(index, lat, lon, offline=offline)
    except Exception as exc:  # noqa: BLE001 - absent GTFS means unverified stops, not HTTP 500
        log.warning("nearby GTFS failed: %s", type(exc).__name__)
        stops, stops_prov = [], _unknown("gtfs")

    metro, metro_prov = await _metro_card(nabiz, lat, lon, needs=needs, offline=offline)
    parking, parking_prov = await _parking_card(nabiz, lat, lon, offline=offline)
    for stop in stops:
        stop["provenance"] = dict(stops_prov)
    return {
        "stops": stops,
        "stops_provenance": stops_prov,
        "metro": metro,
        "metro_provenance": metro_prov,
        "parking": parking,
        "parking_provenance": parking_prov,
        "charging": {"status": "planlanan"},
    }


@nearby_router.get("/api/nearby")
async def citizen_nearby(
    request: Request,
    lat: float = Query(..., ge=LAT_RANGE[0], le=LAT_RANGE[1]),
    lon: float = Query(..., ge=LON_RANGE[0], le=LON_RANGE[1]),
    needs: str = Query(default="", max_length=960),
) -> dict[str, Any]:
    state = request.app.state
    return await nearby_view(
        state.nabiz,
        lat,
        lon,
        needs=functional_needs(split_csv(needs, limit=16)),
        offline=state.fresh.offline,
    )


@nearby_router.post("/api/nearby/journey")
async def nearby_journey(request: Request, body: JourneyRequest) -> dict[str, Any]:
    """Pass a nearby card's coordinates into the shared journey comparison tool."""
    state = request.app.state
    try:
        result = await state.nabiz.plan_journey(
            origin="Konumum",
            destination=body.destination_name,
            origin_lat=body.origin_lat,
            origin_lon=body.origin_lon,
            destination_lat=body.destination_lat,
            destination_lon=body.destination_lon,
        )
    except ValueError as exc:
        return {"error": "bad_request", "message": str(exc), "provenance": _unknown("nabiz_routing")}
    except Exception as exc:  # noqa: BLE001 - journey source failures are shown in the chat panel
        log.warning("nearby journey failed: %s", type(exc).__name__)
        return {"error": "unverified", "message": "Yolculuk karşılaştırması doğrulanamadı.",
                "provenance": _unknown("nabiz_routing")}
    return {
        "data": result.data,
        "note": result.note,
        "provenance": provenance_view(result.provenance, offline=state.fresh.offline),
    }
