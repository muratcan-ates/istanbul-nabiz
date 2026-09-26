"""A small HTTP endpoint for the deterministic institution router.

Entegratör: app.py'de \
"from nabiz.console.agency_api import agency_routes" ve build_console_app içinde \
app.include_router(agency_routes) (knowledge_routes satırının hemen altına, statik mount'tan önce).
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query

from nabiz.console.agency_router import route
from nabiz.console.operator import port_problem

agency_routes = APIRouter()


@agency_routes.get("/api/agency")
async def agency_lookup(
    q: str = Query(..., min_length=1, max_length=300),
    district: str | None = Query(None, max_length=40),
) -> Any:
    try:
        return route(q, district).to_dict()
    except (FileNotFoundError, json.JSONDecodeError):
        return port_problem(503, "agency_data_missing", "Kurum listesi bu sunucuda yok; 153'ü arayın.")
