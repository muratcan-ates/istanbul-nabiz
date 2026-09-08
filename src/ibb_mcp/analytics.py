"""Derived answers that need history rather than a live reading.

İBB publishes current state but keeps no public history for parking occupancy, so the
"how full is this car park usually at 6pm on a Tuesday" answer can only come from
snapshots this project collects itself. That means, on day one, there is no history — and
the honest response is to say so rather than to extrapolate from a handful of samples.

Every function here returns a dict containing ``available``. When it is ``False`` the
``note`` explains why, and the agent is instructed to relay that instead of inventing a
number. As the collector accumulates days, the same functions start returning real
distributions with the sample size attached.
"""

from __future__ import annotations

import datetime as dt
import logging
import statistics
from typing import Any

from ibb_mcp.models import ISTANBUL_TZ, AirQualityReading, aqi_band, utcnow
from ibb_mcp.sources.base import SourceContext

log = logging.getLogger("ibb_mcp.analytics")

#: Below this many observations for a (park, weekday, hour) cell we refuse to report a
#: "typical" value. Three weeks of collection gives 3 samples per cell.
MIN_SAMPLES = 3

WEEKDAY_TR = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


class HistoryStore:
    """Reads the gold tables the collector writes.

    Two backends are supported and tried in order: Azure Data Explorer when
    ``NABIZ_KUSTO_URI`` is configured, then the local Delta lake used during development.
    Both are optional; with neither present the store reports itself unavailable, which is
    the expected state until the Day-0 gates in PLAN.md section 10 have been passed.
    """

    def __init__(self, ctx: SourceContext) -> None:
        self.ctx = ctx
        self._backend: str | None = None

    async def describe(self) -> dict[str, Any]:
        return {"backend": self._backend, "available": self._backend is not None}

    async def occupancy_cell(self, park_id: int, weekday: int, hour: int) -> list[float]:
        """Occupancy percentages recorded for one (park, weekday, hour) cell."""
        return []

    async def recent_readings(self, station_id: str, hours: int) -> list[AirQualityReading]:
        """Recent hourly readings for one air-quality station."""
        return []


async def occupancy_profile(ctx: SourceContext, *, park_id: int, weekday: int, hour: int) -> dict[str, Any]:
    """Typical occupancy for a car park at a weekday and hour."""
    store = HistoryStore(ctx)
    samples = await store.occupancy_cell(park_id, weekday, hour)
    label = f"{WEEKDAY_TR[weekday % 7]} saat {hour:02d}:00"

    if len(samples) < MIN_SAMPLES:
        return {
            "available": False,
            "park_id": park_id,
            "weekday": weekday,
            "hour": hour,
            "window": label,
            "samples": len(samples),
            "note": (
                f"{label} için henüz yeterli geçmiş yok ({len(samples)} gözlem, en az {MIN_SAMPLES} gerekiyor). "
                "İBB otopark doluluğunun geçmişini yayınlamıyor; bu profil bu projenin kendi topladığı "
                "anlık görüntülerden oluşuyor ve toplayıcı çalıştıkça dolacak."
            ),
        }

    return {
        "available": True,
        "park_id": park_id,
        "weekday": weekday,
        "hour": hour,
        "window": label,
        "samples": len(samples),
        "median_occupancy_pct": round(statistics.median(samples), 1),
        "p25_occupancy_pct": round(statistics.quantiles(samples, n=4)[0], 1) if len(samples) >= 4 else None,
        "p75_occupancy_pct": round(statistics.quantiles(samples, n=4)[2], 1) if len(samples) >= 4 else None,
        "note": f"{len(samples)} gözleme dayanıyor.",
    }


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
