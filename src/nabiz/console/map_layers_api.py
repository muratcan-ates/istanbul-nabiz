"""GeoJSON responses for the citizen map's rail station and lift layers."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request

from ibb_mcp.models import LAT_RANGE, LON_RANGE
from ibb_mcp.text import fold_tr, squash_punctuation
from nabiz.console.cards import display_text, provenance_view, unknown_provenance

log = logging.getLogger("nabiz.console.map_layers")
map_layers_routes = APIRouter()

MAX_RESOLVE = 40
LIFT_RECORD_TEXT = {
    "recorded_fault": "İBB kaydında asansör arızası var",
    "no_fault_record": "İBB kaydında arıza yok",
    "unread": "Asansör kaydı okunamadı",
}
NOTE_UNREAD = "Asansör kaydı yok: Metro İstanbul ekipman kaydı okunamadı, asansör durumu doğrulanamadı."
NOTE_EMPTY = "İBB kaydında kullanılamayan asansör yok. Bu, asansörlerin kullanılabilir olduğunu kanıtlamaz."
NOTE_STALE = "Veri bayat: gösterilen, son bilinen durumdur."
_GAZETTEER_URL = "local:data/reference/places.csv"
_SAFE_STATUSES = {"Arıza", "Revizyon", "Çalıştırılmıyor", "bilinmiyor"}


@dataclass(frozen=True)
class LiftRead:
    """One read of the façade plus the records that could be placed on gazetteer points."""

    readable: bool
    records: tuple[dict[str, Any], ...]
    provenance: dict[str, Any]
    stale: bool
    uncertainty: tuple[str, ...]
    date_label: str | None
    disclaimer: str | None


def offline_flag(request: Request) -> bool:
    """Follow the console's runtime freshness switch, with settings as a test-safe fallback."""
    fresh = getattr(request.app.state, "fresh", None)
    if fresh is not None:
        return bool(fresh.offline)
    return bool(request.app.state.nabiz.settings.offline)


def _station_key(name: str | None) -> str:
    return squash_punctuation(fold_tr(name))


def _places(nabiz: Any) -> list[Any]:
    return sorted(
        (
            place
            for place in nabiz.places.places
            if place.kind == "metro_station" and place.name
            and place.lat is not None and place.lon is not None
            and LAT_RANGE[0] <= place.lat <= LAT_RANGE[1]
            and LON_RANGE[0] <= place.lon <= LON_RANGE[1]
        ),
        key=lambda place: (fold_tr(place.name), place.name),
    )


def _place_index(places: list[Any]) -> dict[str, Any]:
    index: dict[str, Any] = {}
    for place in places:
        index.setdefault(_station_key(place.name), place)
    return index


async def _filtered_station_place(nabiz: Any, record: dict[str, Any], index: dict[str, Any]) -> Any | None:
    """Use only the façade's station-filtered records as evidence for a fallback match."""
    name = str(record.get("station") or "").strip()
    if not name:
        return None
    try:
        result = await nabiz.metro_equipment_status(station=name, group="Asansör")
        data = result.data if isinstance(result.data, dict) else {}
        rows = [row for row in data.get("records", []) if isinstance(row, dict)]
        code = str(record.get("code") or "").strip()
        count = int(data.get("count") or 0)
        bound = any(str(row.get("code") or "").strip() == code for row in rows) if code else count > 0
        if not bound:
            return None
        station = data.get("station")
        station_name = station.get("name") if isinstance(station, dict) else None
        return index.get(_station_key(station_name))
    except Exception as exc:  # noqa: BLE001 - an unresolved record stays in the text list
        log.warning("map lift station lookup failed: %s", type(exc).__name__)
        return None


async def read_lifts(nabiz: Any, *, offline: bool) -> LiftRead:
    """Read the façade once, placing only records the same façade associates to stations."""
    try:
        result = await nabiz.metro_equipment_status(group="Asansör")
        data = result.data if isinstance(result.data, dict) else {}
        readable = data.get("available") is True and "Asansör" in (data.get("groups_read") or [])
    except Exception as exc:  # noqa: BLE001 - an unread source is an unknown, not a server error
        log.warning("map lift read failed: %s", type(exc).__name__)
        return LiftRead(False, (), unknown_provenance("metro_equipment"), False, (), None, None)

    if not readable:
        return LiftRead(
            False,
            (),
            unknown_provenance("metro_equipment"),
            False,
            tuple(str(item) for item in data.get("uncertainty", []) if isinstance(item, str)),
            display_text(data["date_label"]) if isinstance(data.get("date_label"), str) else None,
            display_text(data["disclaimer"]) if isinstance(data.get("disclaimer"), str) else None,
        )

    provenance = provenance_view(result.provenance, offline=offline)
    places = _places(nabiz)
    index = _place_index(places)
    raw_records = [
        row for row in data.get("records", [])
        if isinstance(row, dict) and row.get("equipment_type") == "elevator"
    ]
    resolved: dict[str, Any | None] = {}
    resolve_count = 0
    records: list[dict[str, Any]] = []
    for raw in raw_records:
        station_name = str(raw.get("station") or "").strip()
        key = _station_key(station_name)
        place = index.get(key)
        if place is None and key and key not in resolved and resolve_count < MAX_RESOLVE:
            resolve_count += 1
            resolved[key] = await _filtered_station_place(nabiz, raw, index)
        if place is None:
            place = resolved.get(key)
        record = dict(raw)
        record["placed"] = place is not None
        record["geometry"] = (
            {"type": "Point", "coordinates": [float(place.lon), float(place.lat)]} if place is not None else None
        )
        record["map_station"] = place.name if place is not None else station_name
        records.append(record)

    return LiftRead(
        True,
        tuple(records),
        provenance,
        bool(data.get("stale")),
        tuple(str(item) for item in data.get("uncertainty", []) if isinstance(item, str)),
        display_text(data["date_label"]) if isinstance(data.get("date_label"), str) else None,
        display_text(data["disclaimer"]) if isinstance(data.get("disclaimer"), str) else None,
    )


def _station_id(name: str, seen: dict[str, int]) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", fold_tr(name)).strip("-") or "istasyon"
    seen[slug] = seen.get(slug, 0) + 1
    suffix = "" if seen[slug] == 1 else f"-{seen[slug]}"
    return f"station-{slug}{suffix}"


def _station_faults(lifts: LiftRead) -> set[str]:
    return {
        _station_key(str(record.get("map_station") or ""))
        for record in lifts.records
        if record.get("placed") is True
    }


def _station_feature(place: Any, feature_id: str, lift_record: str) -> dict[str, Any]:
    return {
        "type": "Feature",
        "id": feature_id,
        "geometry": {"type": "Point", "coordinates": [float(place.lon), float(place.lat)]},
        "properties": {
            "kind": "station",
            "name": display_text(str(place.name)),
            "lift_record": lift_record,
            "text": display_text(LIFT_RECORD_TEXT[lift_record]),
        },
    }


async def stations_collection(nabiz: Any, *, offline: bool) -> dict[str, Any]:
    """Build the stable, sorted FeatureCollection used by the station layer."""
    places = _places(nabiz)
    if not places:
        return {
            "type": "FeatureCollection",
            "count": 0,
            "lift_record": "unread",
            "features": [],
            "provenance": unknown_provenance("gazetteer", _GAZETTEER_URL),
            "lift_provenance": unknown_provenance("metro_equipment"),
            "note": "İstasyon listesi bu sunucuda yok.",
        }

    lifts = await read_lifts(nabiz, offline=offline)
    faults = _station_faults(lifts)
    seen: dict[str, int] = {}
    features = []
    for place in places:
        status = "unread" if not lifts.readable else (
            "recorded_fault" if _station_key(place.name) in faults else "no_fault_record"
        )
        features.append(_station_feature(place, _station_id(place.name, seen), status))
    return {
        "type": "FeatureCollection",
        "count": len(features),
        "lift_record": "read" if lifts.readable else "unread",
        "features": features,
        "provenance": unknown_provenance("gazetteer", _GAZETTEER_URL),
        "lift_provenance": lifts.provenance,
        "note": None,
    }


def _lift_feature(record: dict[str, Any], ordinal: int) -> dict[str, Any]:
    status = record.get("status_type")
    status = display_text(status if status in _SAFE_STATUSES else "Belirsiz kayıt")
    text = record.get("text")
    text = display_text(text if isinstance(text, str) and text.strip() else "İBB kaydındaki asansör kaydı.")
    location = record.get("location")
    return {
        "type": "Feature",
        "id": f"lift-{ordinal}",
        "geometry": record.get("geometry"),
        "properties": {
            "kind": "lift",
            "station": display_text(str(record.get("map_station") or "Bilinmeyen istasyon")),
            "line": display_text(str(record.get("line") or "")),
            "status": status,
            "ibb_date": record.get("ibb_date"),
            "location": display_text(str(location)) if location else None,
            "text": text,
            "placed": record.get("placed") is True,
        },
    }


async def lifts_collection(nabiz: Any, *, offline: bool) -> dict[str, Any]:
    """Build the lift FeatureCollection, retaining unplaced records in the accessible list."""
    lifts = await read_lifts(nabiz, offline=offline)
    features = [_lift_feature(record, index) for index, record in enumerate(lifts.records, start=1)]
    note = NOTE_UNREAD if not lifts.readable else NOTE_STALE if lifts.stale else NOTE_EMPTY if not features else None
    return {
        "type": "FeatureCollection",
        "count": len(features),
        "lift_record": "read" if lifts.readable else "unread",
        "stale": lifts.stale,
        "features": features,
        "note": display_text(note) if note else None,
        "provenance": lifts.provenance,
        "uncertainty": list(lifts.uncertainty),
        "date_label": lifts.date_label,
        "disclaimer": lifts.disclaimer,
    }


@map_layers_routes.get("/api/map/stations")
async def map_stations(request: Request) -> dict[str, Any]:
    """Expose rail stations and their evidence-backed lift record state."""
    return await stations_collection(request.app.state.nabiz, offline=offline_flag(request))


@map_layers_routes.get("/api/map/lifts")
async def map_lifts(request: Request) -> dict[str, Any]:
    """Expose Metro İstanbul's recorded unusable lifts without failing the page."""
    return await lifts_collection(request.app.state.nabiz, offline=offline_flag(request))
