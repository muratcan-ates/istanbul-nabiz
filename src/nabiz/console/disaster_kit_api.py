"""Read-only endpoint for the reviewed household disaster-kit catalogue."""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from nabiz.console import disaster_kit
from nabiz.console.operator import port_problem

disaster_kit_routes = APIRouter()
UNAVAILABLE = "Afet hazırlık listesi bu sunucuda hazır değil; İBB'nin resmî sayfasına ya da 153'e başvurun."


def _problem(status: int, kind: str, message: str) -> JSONResponse:
    response = port_problem(status, kind, message)
    response.headers["Cache-Control"] = "no-store"
    return response


@disaster_kit_routes.get("/api/disaster-kit")
def get_disaster_kit(lang: str = Query(default="tr")) -> JSONResponse:
    """Return the public source catalogue in the requested display language."""
    if lang not in {"tr", "en"}:
        return _problem(400, "invalid_lang", "Dil tr ya da en olmalı.")
    try:
        kit = disaster_kit.load_kit(disaster_kit.DISASTER_KIT_PATH)
        errors = disaster_kit.validate_kit(kit)
        if errors:
            return _problem(503, "disaster_kit_unavailable", UNAVAILABLE)
        payload = disaster_kit.public_kit(kit, lang)
    except (disaster_kit.KitError, KeyError, TypeError, ValueError):
        return _problem(503, "disaster_kit_unavailable", UNAVAILABLE)
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})
