"""Pure, one-shot distance from a position to a route polyline."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

EARTH_RADIUS_M = 6371008.8
DEFAULT_THRESHOLD_M = 50.0


@dataclass(frozen=True)
class Deviation:
    distance_m: float | None
    suggest_new_route: bool


def _valid(point: Sequence[float]) -> bool:
    try:
        lat, lon = point
    except (TypeError, ValueError):
        return False
    return (
        isinstance(lat, (int, float))
        and not isinstance(lat, bool)
        and isinstance(lon, (int, float))
        and not isinstance(lon, bool)
        and math.isfinite(lat)
        and math.isfinite(lon)
        and abs(lat) <= 90
        and abs(lon) <= 180
    )


def _xy(point: Sequence[float], center: Sequence[float]) -> tuple[float, float]:
    lat, lon = point
    center_lat, center_lon = center
    return (
        math.radians(lon - center_lon) * EARTH_RADIUS_M * math.cos(math.radians(center_lat)),
        math.radians(lat - center_lat) * EARTH_RADIUS_M,
    )


def route_deviation(
    position: Sequence[float],
    geometry: Sequence[Sequence[float]],
    *,
    threshold_m: float = DEFAULT_THRESHOLD_M,
) -> Deviation:
    """Compute distance once; invalid or absent geometry yields no recommendation."""
    if (
        not _valid(position)
        or len(geometry) < 2
        or len(geometry) > 10000
        or not all(_valid(point) for point in geometry)
        or not math.isfinite(threshold_m)
        or threshold_m <= 0
    ):
        return Deviation(distance_m=None, suggest_new_route=False)
    xy = [_xy(point, position) for point in geometry]
    closest = math.inf
    for start, end in zip(xy, xy[1:], strict=False):
        dx, dy = end[0] - start[0], end[1] - start[1]
        length_squared = dx * dx + dy * dy
        fraction = 0.0 if length_squared == 0 else max(0.0, min(1.0, -(start[0] * dx + start[1] * dy) / length_squared))
        closest = min(closest, math.hypot(start[0] + fraction * dx, start[1] + fraction * dy))
    return Deviation(distance_m=closest, suggest_new_route=closest > threshold_m)
