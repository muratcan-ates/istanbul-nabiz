"""Derived answers that need history rather than a live reading: the air-quality outlook.

Every function here returns a dict containing ``available``. When it is ``False`` the
``note`` explains why, and the agent is instructed to relay that instead of inventing a
number.

This module once also held a parking-occupancy profile and a ``HistoryStore`` meant to read
it from Azure Data Explorer or a local Delta lake. The store never read anything (it always
answered "no samples"), and ``ispark_typical_occupancy`` now reads the committed profile
through :mod:`ibb_mcp.occupancy`, so both were removed rather than left to look like a
second, working path.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from ibb_mcp.models import ISTANBUL_TZ, AirQualityReading, aqi_band, utcnow
from ibb_mcp.sources.base import SourceContext

log = logging.getLogger("ibb_mcp.analytics")


def _seasonal_naive(readings: list[AirQualityReading], horizon_hours: int) -> list[dict[str, Any]]:
    """Baseline forecast: repeat the value observed at the same hour yesterday.

    This is the honest starting point. PLAN.md section 7 timeboxes the gradient-boosted
    model to three hours; whatever it produces has to beat this baseline to be used, and
    the README reports both.
    """
    by_hour: dict[dt.datetime, AirQualityReading] = {
        r.read_time.astimezone(ISTANBUL_TZ).replace(minute=0, second=0, microsecond=0): r
        for r in readings
        if r.read_time is not None
    }
    if not by_hour:
        return []
    now = max(by_hour)
    out: list[dict[str, Any]] = []
    for step in range(1, horizon_hours + 1):
        target = now + dt.timedelta(hours=step)
        reference = by_hour.get(target - dt.timedelta(hours=24))
        if reference is None or reference.pm10 is None:
            continue
        out.append(
            {
                "at": target.isoformat(),
                "pm10": round(reference.pm10, 1),
                "method": "seasonal_naive_24h",
                "confidence": "low",
            }
        )
    return out


async def air_quality_forecast(ctx: SourceContext, *, station, horizon_hours: int = 6) -> dict[str, Any]:
    """Short-horizon PM10 outlook and the cleanest upcoming window.

    Forecasts the hourly PM10 *concentration*, not the published index: İBB derives the
    PM10 sub-index from a rolling 24-hour mean, so the index barely moves within a
    six-hour horizon and would make any model look deceptively accurate.
    """
    from ibb_mcp.sources.airquality import AirQualitySource

    source = AirQualitySource(ctx)
    end = utcnow()
    start = end - dt.timedelta(hours=48)
    try:
        readings, _ = await source.readings(station.station_id, start, end)
    except Exception as exc:  # noqa: BLE001 - upstream failure must not fabricate a forecast
        log.warning("air quality history unavailable for %s: %r", station.station_id, exc)
        return {
            "available": False,
            "horizon_hours": horizon_hours,
            "forecast": [],
            "note": "Geçmiş ölçümler alınamadığı için tahmin üretilemedi.",
        }

    forecast = _seasonal_naive(readings, horizon_hours)
    latest = next((r for r in reversed(readings) if r.pm10 is not None), None)

    best = None
    if forecast:
        cheapest = min(forecast, key=lambda item: item["pm10"])
        best = {"at": cheapest["at"], "pm10": cheapest["pm10"]}

    band = aqi_band(latest.aqi_index) if latest else None
    return {
        "available": bool(forecast),
        "horizon_hours": horizon_hours,
        "latest": {
            "at": latest.read_time.isoformat() if latest and latest.read_time else None,
            "pm10": latest.pm10 if latest else None,
            "aqi_index": latest.aqi_index if latest else None,
            "band": band[0] if band else None,
        },
        "forecast": forecast,
        "best_window": best,
        "baseline_only": True,
        "note": (
            "Tahmin şu an yalnızca mevsimsel-naif temel modeldir (24 saat önceki aynı saat). "
            "Eğitilmiş model bunu geçtiğinde değiştirilecek ve iki sonuç da README'de raporlanacak. "
            "Sağlık tavsiyesi değildir."
        )
        if forecast
        else "Tahmin üretmek için yeterli geçmiş ölçüm yok.",
    }
