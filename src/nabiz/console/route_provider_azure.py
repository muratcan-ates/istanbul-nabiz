"""Azure Maps pedestrian directions boundary and an offline sample provider."""

from __future__ import annotations

import logging
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

AZURE_DIRECTIONS_URL = "https://atlas.microsoft.com/route/directions/json"


class _DropRouteRequestLog(logging.Filter):
    """httpx logs each request URL at INFO; this URL carries the citizen's coordinates."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "atlas.microsoft.com/route" not in record.getMessage()


logging.getLogger("httpx").addFilter(_DropRouteRequestLog())


@dataclass(frozen=True)
class Directions:
    """Only validated provider geometry and maneuver codes cross this boundary."""

    points: tuple[tuple[float, float], ...]
    maneuvers: tuple[str, ...]
    sample: bool


class RouteProvider(Protocol):
    async def directions(
        self, origin: tuple[float, float], destination: tuple[float, float], *, consent: bool
    ) -> Directions | None: ...

    @property
    def status(self) -> str: ...


def parse_directions(payload: Mapping[str, Any], *, sample: bool) -> Directions | None:
    """Accept the small Route Directions response subset needed for a walk card."""
    try:
        route = payload["routes"][0]
        legs = route["legs"]
        raw_points = [point for leg in legs for point in leg["points"]]
        raw_instructions = route["guidance"]["instructions"]
        points = tuple((float(point["latitude"]), float(point["longitude"])) for point in raw_points)
        maneuvers = tuple(str(item["maneuverType"]) for item in raw_instructions)
        indexes = tuple(item["pointIndex"] for item in raw_instructions)
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return None
    if len(points) < 2 or not maneuvers or len(points) > 10000 or len(maneuvers) > 20:
        return None
    if any(not math.isfinite(lat) or not math.isfinite(lon) or abs(lat) > 90 or abs(lon) > 180 for lat, lon in points):
        return None
    if any(not isinstance(index, int) or isinstance(index, bool) or index < 0 or index >= len(points) for index in indexes):
        return None
    if indexes != tuple(sorted(indexes)):
        return None
    return Directions(points=points, maneuvers=maneuvers, sample=sample)


class AzureMapsRouteProvider:
    """A request-scoped read; no coordinate, response or key is logged or stored."""

    def __init__(self, *, key: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self._key = (key if key is not None else os.environ.get("NABIZ_AZURE_MAPS_KEY", "")).strip()
        self._client = client

    @property
    def status(self) -> str:
        return "kapalı" if not self._key or os.environ.get("NABIZ_OFFLINE") == "1" else "hazır"

    async def directions(
        self, origin: tuple[float, float], destination: tuple[float, float], *, consent: bool
    ) -> Directions | None:
        if self.status != "hazır" or not consent:
            return None
        params = {
            "api-version": "1.0",
            "travelMode": "pedestrian",
            "query": f"{origin[0]},{origin[1]}:{destination[0]},{destination[1]}",
        }
        headers = {"subscription-key": self._key}
        try:
            if self._client is not None:
                response = await self._client.get(AZURE_DIRECTIONS_URL, params=params, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    response = await client.get(AZURE_DIRECTIONS_URL, params=params, headers=headers)
            response.raise_for_status()
            return parse_directions(response.json(), sample=False)
        except (httpx.HTTPError, ValueError):
            return None


class SampleRouteProvider:
    """Inject a hand-written example into tests; never claims real street geometry."""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self._directions = parse_directions(payload, sample=True) if payload.get("ornek") is True else None

    @property
    def status(self) -> str:
        return "örnek" if self._directions is not None else "kapalı"

    async def directions(
        self, origin: tuple[float, float], destination: tuple[float, float], *, consent: bool
    ) -> Directions | None:
        return self._directions if consent else None
