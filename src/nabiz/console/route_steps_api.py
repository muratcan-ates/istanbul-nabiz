"""HTTP adapter for bilingual, speakable cards over the existing accessible route."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from nabiz.console.journey_api import accessible_journey_route
from nabiz.console.route_steps import route_view

log = logging.getLogger(__name__)
route_steps_routes = APIRouter()


@route_steps_routes.get("/api/route/steps")
async def route_steps_endpoint(
    request: Request,
    from_place: str = Query(..., alias="from", min_length=1, max_length=120),
    to: str = Query(..., min_length=1, max_length=120),
    needs: str = Query("step_free"),
    lang: str = Query("tr", pattern="^(tr|en)$"),
) -> Any:
    """Reuse the accessible journey handler; do not add another route-planning path."""
    try:
        result = await accessible_journey_route(request, from_place, to, needs)
    except Exception as exc:  # noqa: BLE001 - keep names and exception text out of logs and replies
        log.warning("route steps unavailable: %s", type(exc).__name__)
        return JSONResponse(
            status_code=503,
            content={"error": "route_unavailable", "message": "Rota adımları şu anda alınamadı."},
        )
    if not isinstance(result, dict):
        return result
    return route_view(result, lang)
