"""Opt-in street-route API router; the integrator decides when to mount it."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from nabiz.console.route_provider_azure import AzureMapsRouteProvider
from nabiz.console.street_route import make_street_route

street_route_router = APIRouter()


class StreetRoutePlace(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class StreetRouteRequest(BaseModel):
    origin: StreetRoutePlace
    destination: StreetRoutePlace
    needs: list[str] = Field(default_factory=list, max_length=2)
    lang: str = Field(default="tr", pattern="^(tr|en)$")
    consent: bool = False


@street_route_router.post("/api/route/street")
async def street_route(request: Request, body: StreetRouteRequest) -> dict:
    """Route only after express location sharing; never retain coordinates."""
    if any(need not in {"step_free", "slow_walk"} for need in body.needs):
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="Unknown route need")
    provider = getattr(request.app.state, "street_route_provider", None) or AzureMapsRouteProvider()
    return await make_street_route(
        provider,
        (body.origin.lat, body.origin.lon),
        (body.destination.lat, body.destination.lon),
        (body.origin.name, body.destination.name),
        needs=body.needs,
        lang=body.lang,
        consent=body.consent,
    )
