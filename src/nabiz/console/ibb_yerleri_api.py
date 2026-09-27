"""Read-only API for the recorded İBB place lists shown on the citizen map."""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from ibb_mcp.config import REPO_ROOT
from ibb_mcp.models import LAT_RANGE, LON_RANGE
from ibb_mcp.text import fold_tr
from nabiz.console.cards import display_text
from nabiz.console.culture_api import DISCLAIMER

ibb_yerleri_routes = APIRouter()
DATA_ENV = "NABIZ_IBB_PLACES_DIR"
CATEGORIES = ("halk_ekmek", "kent_lokantasi", "sosyal_tesis", "wifi")
MAX_POINTS = 60
MAX_SPAN = 0.25
_DEFAULT_DIR = REPO_ROOT / "data" / "reference" / "ibb_places"
_DISTRICTS = REPO_ROOT / "data" / "agencies.json"
_CACHE: dict[Path, tuple[int, dict[str, Any]]] = {}


def _data_dir() -> Path:
    return Path(os.environ.get(DATA_ENV) or _DEFAULT_DIR)


def _text(value: Any) -> str:
    return display_text(str(value).strip()) if value is not None else ""


def _portal_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    return value if parsed.scheme == "https" and parsed.hostname == "data.ibb.gov.tr" else None


def _date(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=dt.UTC) if parsed.tzinfo is None else parsed.astimezone(dt.UTC)


def _stale(value: Any) -> bool:
    modified = _date(value)
    return bool(modified and dt.datetime.now(dt.UTC) - modified > dt.timedelta(days=365))


def _unavailable(reason: str = "Kayıt dosyası okunamadı.") -> dict[str, Any]:
    return {"status": "veri_alinamadi", "reason": display_text(reason), "rows": [], "metadata": {}}


def _load(category: str) -> dict[str, Any]:
    path = _data_dir() / f"{category}.json"
    try:
        modified = path.stat().st_mtime_ns
    except OSError:
        return _unavailable()
    cached = _CACHE.get(path)
    if cached and cached[0] == modified:
        return cached[1]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("root is not an object")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        loaded = _unavailable()
    else:
        metadata = {
            "title": _text(payload.get("title")) or None,
            "dataset_url": _portal_url(payload.get("dataset_url")),
            "license": _text(payload.get("license")) or None,
            "license_url": _portal_url(payload.get("license_url")),
            "resource_last_modified": (
                payload.get("resource_last_modified") if _date(payload.get("resource_last_modified")) else None
            ),
            "captured_at": payload.get("captured_at") if _date(payload.get("captured_at")) else None,
        }
        rows = payload.get("rows")
        if payload.get("status") != "alindi" or not isinstance(rows, list):
            loaded = _unavailable(_text(payload.get("reason")) or "Bu liste alınamadı.")
            loaded["metadata"] = metadata
        else:
            loaded = {"status": "alindi", "reason": None, "rows": rows, "metadata": metadata}
    _CACHE[path] = (modified, loaded)
    return loaded


def _source(category: str, loaded: dict[str, Any]) -> dict[str, Any]:
    return {"id": category, **loaded["metadata"], "stale": _stale(loaded["metadata"].get("resource_last_modified"))}


def _districts() -> list[str]:
    try:
        payload = json.loads(_DISTRICTS.read_text(encoding="utf-8"))
        values = payload.get("districts", [])
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
        return []
    return [display_text(value) for value in values if isinstance(value, str)] if isinstance(values, list) else []


def _district_lookup() -> dict[str, str]:
    """Folded district names and ``district_aliases`` from data/agencies.json, to the published name."""
    known = {fold_tr(value): value for value in _districts()}
    try:
        aliases = json.loads(_DISTRICTS.read_text(encoding="utf-8")).get("district_aliases", {})
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
        aliases = {}
    if isinstance(aliases, dict):
        known.update({fold_tr(alias): display_text(value) for alias, value in aliases.items() if isinstance(value, str)})
    return known


def _district_of(name: str, district: str, address: str, known: dict[str, str]) -> str:
    """The row's own district; else the last district named in its address, else its name's first word.

    Three of the four İBB files leave the district column out: Kent Lokantası and sosyal tesis
    rows end their address with it ("... 34345 Beşiktaş/İstanbul", "... SARIYER") and ibbWiFi
    rows carry it as their location group. Nothing is guessed from coordinates.
    """
    if district:
        return district
    for token in reversed(re.split(r"\W+", address)):
        if fold_tr(token) in known:
            return known[fold_tr(token)]
    words = name.split()
    return known.get(fold_tr(words[0]), "") if words else ""


def _records(category: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    loaded = _load(category)
    points = []
    if loaded["status"] != "alindi":
        return loaded, points
    known = _district_lookup()
    for index, row in enumerate(loaded["rows"]):
        if not isinstance(row, list) or len(row) != 5:
            continue
        name, district, address, lat, lon = row
        if not isinstance(name, str) or not name.strip():
            continue
        if isinstance(lat, bool) or isinstance(lon, bool):
            continue
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(lat) or not math.isfinite(lon):
            continue
        if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
            continue
        points.append(
            {
                "id": f"{category}-{index}",
                "name": _text(name),
                "district": _district_of(_text(name), _text(district), _text(address), known),
                "address": _text(address),
                "lat": lat,
                "lon": lon,
            }
        )
    return loaded, points


def _distance_m(left: tuple[float, float], right: tuple[float, float]) -> float:
    lat1, lat2 = math.radians(left[0]), math.radians(right[0])
    dlat, dlon = lat2 - lat1, math.radians(right[1] - left[1])
    haversine = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))


def _bad_request(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": "bad_request", "message": display_text(message)},
        headers={"Cache-Control": "no-store"},
    )


@ibb_yerleri_routes.get("/api/ibb-places")
def list_ibb_places(response: Response) -> dict[str, Any]:
    """Return category metadata and the published district names without exposing place rows."""
    response.headers["Cache-Control"] = "max-age=300"
    categories = []
    for category in CATEGORIES:
        loaded, points = _records(category)
        metadata = _source(category, loaded)
        categories.append(
            {
                **metadata,
                "status": loaded["status"],
                "reason": loaded["reason"],
                "count": len(points),
            }
        )
    return {"categories": categories, "districts": _districts(), "disclaimer": display_text(DISCLAIMER)}


@ibb_yerleri_routes.get("/api/ibb-places/{category}", response_model=None)
def get_ibb_places(
    category: str,
    request: Request,
    response: Response,
    bbox: str | None = Query(default=None),
    district: str | None = Query(default=None),
) -> Any:
    """Filter a recorded category by a rounded box or a selected İstanbul district."""
    response.headers["Cache-Control"] = "no-store"
    # Uvicorn access logs may include the query string. FastAPI has already parsed it, so
    # clear it from the shared ASGI scope before the response reaches the access logger.
    request.scope["query_string"] = b""
    if category not in CATEGORIES:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "message": "Kategori bulunamadı."},
            headers={"Cache-Control": "no-store"},
        )
    if (bbox is None) == (district is None):
        return _bad_request("Bir kutu ya da ilçe seçin.")
    box: tuple[float, float, float, float] | None = None
    if bbox is not None:
        try:
            values = tuple(float(item) for item in bbox.split(","))
        except ValueError:
            return _bad_request("Arama kutusu geçersiz.")
        if len(values) != 4 or not all(math.isfinite(value) for value in values):
            return _bad_request("Arama kutusu geçersiz.")
        min_lon, min_lat, max_lon, max_lat = values
        if (
            min_lon >= max_lon
            or min_lat >= max_lat
            or max_lon - min_lon > MAX_SPAN
            or max_lat - min_lat > MAX_SPAN
            or min_lon < LON_RANGE[0]
            or max_lon > LON_RANGE[1]
            or min_lat < LAT_RANGE[0]
            or max_lat > LAT_RANGE[1]
        ):
            return _bad_request("Arama kutusu İstanbul sınırlarının dışında ya da çok geniş.")
        box = values  # type: ignore[assignment]
    elif not district or fold_tr(district) not in {fold_tr(name) for name in _districts()}:
        return _bad_request("İlçe seçimi geçersiz.")

    loaded, points = _records(category)
    source = _source(category, loaded)
    if loaded["status"] != "alindi":
        return {
            "category": category,
            "status": loaded["status"],
            "reason": loaded["reason"],
            "points": [],
            "total": 0,
            "shown": 0,
            "truncated": False,
            "source": source,
        }
    if box is not None:
        min_lon, min_lat, max_lon, max_lat = box
        center = ((min_lat + max_lat) / 2, (min_lon + max_lon) / 2)
        matches = [p for p in points if min_lon <= p["lon"] <= max_lon and min_lat <= p["lat"] <= max_lat]
        matches.sort(key=lambda p: (_distance_m(center, (p["lat"], p["lon"])), fold_tr(p["name"]), p["name"]))
    else:
        district_key = fold_tr(district)
        matches = [p for p in points if fold_tr(p["district"]) == district_key]
        matches.sort(key=lambda p: (fold_tr(p["name"]), p["name"]))
    result = matches[:MAX_POINTS]
    return {
        "category": category,
        "status": "alindi",
        "reason": None,
        "points": result,
        "total": len(matches),
        "shown": len(result),
        "truncated": len(matches) > MAX_POINTS,
        "source": source,
    }
