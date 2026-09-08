"""İBB air quality: 28 stations, hourly readings back to at least 2023 (journey J4).

Two honesty constraints drive the design of this module:

1. **``AQIIndex`` is a rolling average, not an hourly value.** İBB computes the PM10
   sub-index over a rolling **24-hour** mean (O3 and CO over 8 hours), following the
   national index regulation. The published index therefore lags the air you would
   actually breathe on a run in the next hour, sometimes by a wide margin: on
   2026-09-08 09:00 at Maslak the hourly PM10 concentration had fallen to 5 µg/m³ while
   the index still read 25. For short-horizon questions ("koşuya şimdi çıkayım mı?") the
   hourly **concentration** is the honest signal, and :func:`best_window` ranks on it;
   the index is reported alongside as the official band, never as the hourly truth.
2. **PM2.5 is absent from this API.** Only PM10, SO2, O3, NO2 and CO are published, and
   NO2/CO are frequently null. Nothing here may present a PM2.5 figure, and the README
   lists this under Limitations.

Endpoint mechanics verified 2026-09-08: ``GetAQIByStationId`` wants
``dd.MM.yyyy HH:mm:ss`` timestamps in **Istanbul local time**, percent-encoded;
``EndDate`` is **inclusive**, so a window that abuts a previous one repeats an hour —
:meth:`AirQualitySource.readings` deduplicates on ``ReadTime``. A 30-day window returned
all 744 rows, so there is no small per-call cap to work around.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Sequence
from urllib.parse import quote

from ibb_mcp.config import AQ_READINGS, AQ_STATIONS
from ibb_mcp.models import (
    ISTANBUL_TZ,
    AirQualityReading,
    AirQualityStation,
    Provenance,
    aqi_band,
    haversine_km,
    utcnow,
)
from ibb_mcp.sources.base import SourceContext, make_provenance
# Turkish-insensitive folding and match ranking live in metro.py; one copy, shared.
from ibb_mcp.sources.metro import normalize_tr, rank_match

#: Station coordinates and names are static; one day is plenty.
STATIONS_TTL = 86400.0

#: The exact timestamp shape the handler parses. Anything else returns an empty array.
IBB_DATETIME_FORMAT = "%d.%m.%Y %H:%M:%S"

#: Look-back for :meth:`AirQualitySource.latest`. Readings land hourly but occasionally
#: skip an hour, so six hours gives room without pulling a pointlessly large window.
LATEST_LOOKBACK_HOURS = 6

#: Two readings are contiguous if their timestamps are within this gap (hourly + slack).
CONTIGUITY_GAP_SECONDS = 5400.0

_MEASURED_FIELDS = ("pm10", "so2", "o3", "no2", "co", "aqi_index")


def _format_ibb(moment: dt.datetime) -> str:
    """Render a moment the way the handler expects: Istanbul local, ``dd.MM.yyyy HH:mm:ss``."""
    local = moment.astimezone(ISTANBUL_TZ) if moment.tzinfo else moment.replace(tzinfo=ISTANBUL_TZ)
    return local.strftime(IBB_DATETIME_FORMAT)


def _floor_hour(moment: dt.datetime) -> dt.datetime:
    local = moment.astimezone(ISTANBUL_TZ) if moment.tzinfo else moment.replace(tzinfo=ISTANBUL_TZ)
    return local.replace(minute=0, second=0, microsecond=0)


def _tr_number(value: float | None, digits: int = 1) -> str:
    """Turkish decimal comma, so the agent quotes '12,4' and the faithfulness check passes."""
    if value is None:
        return "—"
    return f"{value:.{digits}f}".replace(".", ",")


def _has_measurement(reading: AirQualityReading) -> bool:
    return any(getattr(reading, field) is not None for field in _MEASURED_FIELDS)


class AirQualitySource:
    """Reads the İBB air-quality handler through the shared client and cache."""

    def __init__(self, ctx: SourceContext) -> None:
        self.ctx = ctx

    # -- stations ----------------------------------------------------------------------
    async def stations(self) -> tuple[list[AirQualityStation], Provenance]:
        """All measuring stations, with WKT ``Location`` parsed into lat/lon."""

        async def load() -> list[dict[str, Any]]:
            if self.ctx.settings.offline:
                return self.ctx.load_fixture("aq_stations")
            payload = await self.ctx.client.get_json(AQ_STATIONS, source="aq_stations")
            return payload if isinstance(payload, list) else []

        raw, entry = await self.ctx.cached("aq:stations", load, source="aq_stations", ttl=STATIONS_TTL)
        stations = [AirQualityStation.from_raw(item) for item in raw]
        return stations, make_provenance("aq_stations", entry=entry, url=AQ_STATIONS)

    async def nearest_station(self, lat: float, lon: float) -> AirQualityStation | None:
        """Closest station to a point, with ``distance_km`` filled in.

        Returns a copy so the cached station list is never mutated with one caller's
        distance.
        """
        stations, _ = await self.stations()
        located = [s for s in stations if s.lat is not None and s.lon is not None]
        if not located:
            return None
        best = min(located, key=lambda s: haversine_km(lat, lon, s.lat, s.lon))
        distance = haversine_km(lat, lon, best.lat, best.lon)
        return best.model_copy(update={"distance_km": round(distance, 2)})

    async def find_station(self, name_or_district: str) -> AirQualityStation | None:
        """Turkish-insensitive lookup by station name, then by address.

        Station names are neighbourhoods ("Maslak", "Kadıköy"), while the district a user
        names often appears only in ``Adress`` ("İstanbul / Sarıyer - Turkey"), so both
        are searched — name first, because an exact name beats an address substring.
        """
        query = normalize_tr(name_or_district)
        if not query:
            return None
        stations, _ = await self.stations()

        best: tuple[int, int, AirQualityStation] | None = None
        for field_weight, attribute in ((0, "name"), (1, "address")):
            for station in stations:
                rank = rank_match(query, normalize_tr(getattr(station, attribute)))
                if rank is None:
                    continue
                candidate = (field_weight, rank, station)
                if best is None or candidate[:2] < best[:2]:
                    best = candidate
        return best[2] if best else None

    # -- readings ----------------------------------------------------------------------
    async def readings(
        self,
        station_id: str,
        start: dt.datetime,
        end: dt.datetime,
    ) -> tuple[list[AirQualityReading], Provenance]:
        """Hourly readings for one station, oldest → newest, deduplicated.

        ``start``/``end`` may be aware or naive; naive values are read as Istanbul local
        time, which is what the endpoint speaks. The cache key is rounded to the hour so
        that two requests a few minutes apart share one upstream call.
        """
        if start > end:
            raise ValueError("start, end'den sonra olamaz")

        start_local, end_local = _floor_hour(start), _floor_hour(end)
        # Query params are built by hand: the verified request percent-encodes the space
        # as %20 and the colons as %3A, and we reproduce that byte for byte rather than
        # trusting the client's default form encoding ('+') against a .NET handler.
        url = (
            f"{AQ_READINGS}?StationId={quote(str(station_id), safe='')}"
            f"&StartDate={quote(_format_ibb(start))}"
            f"&EndDate={quote(_format_ibb(end))}"
        )

        async def load() -> list[dict[str, Any]]:
            if self.ctx.settings.offline:
                return self.ctx.load_fixture("aq_readings")
            payload = await self.ctx.client.get_json(url, source="aq_readings")
            return payload if isinstance(payload, list) else []

        key = f"aq:readings:{station_id}:{start_local:%Y%m%d%H}:{end_local:%Y%m%d%H}"
        raw, entry = await self.ctx.cached(key, load, source="aq_readings")

        # EndDate is inclusive, so adjacent windows overlap by one hour; keep the first
        # record for each timestamp and drop rows we cannot place in time.
        seen: dict[dt.datetime, AirQualityReading] = {}
        for item in raw:
            reading = AirQualityReading.from_raw(item)
            if reading.read_time is None or reading.read_time in seen:
                continue
            seen[reading.read_time] = reading
        ordered = [seen[stamp] for stamp in sorted(seen)]

        newest = ordered[-1].read_time if ordered else None
        return ordered, make_provenance("aq_readings", entry=entry, reported_at=newest, url=url)

    async def latest(self, station_id: str) -> tuple[AirQualityReading | None, Provenance]:
        """Newest reading that actually carries a measurement, from the last six hours.

        The most recent row is sometimes published with every value null while the
        instrument reports; walking backwards avoids answering "veri yok" when a usable
        reading exists one hour earlier.
        """
        end = utcnow()
        start = end - dt.timedelta(hours=LATEST_LOOKBACK_HOURS)
        readings, provenance = await self.readings(station_id, start, end)
        for reading in reversed(readings):
            if _has_measurement(reading):
                return reading, provenance.model_copy(update={"reported_at": reading.read_time})
        return None, provenance


def best_window(
    readings: Sequence[AirQualityReading],
    hours: int = 12,
    window_hours: int = 2,
) -> dict[str, Any]:
    """Find the cleanest contiguous stretch of air in the last ``hours`` readings.

    ``hours`` is the horizon considered and ``window_hours`` the length of the block we
    look for (two hours ≈ one run plus warm-up). Ranking uses hourly **PM10
    concentration** when it is available, because the published ``AQIIndex`` is a rolling
    24-hour mean for PM10 and would flatten exactly the variation this question asks
    about; the index is still reported, as the official band label.

    Returns ``{}``-safe fields with ``found: False`` when the series cannot answer.
    """
    ordered = sorted((r for r in readings if r.read_time is not None), key=lambda r: r.read_time)
    horizon = ordered[-hours:] if hours > 0 else ordered

    metric = "pm10" if any(r.pm10 is not None for r in horizon) else "aqi_index"
    scored = [(r, getattr(r, metric)) for r in horizon if getattr(r, metric) is not None]
    if not scored:
        return {
            "found": False,
            "metric": metric,
            "considered_hours": len(horizon),
            "label": "Bu istasyonda değerlendirilecek ölçüm yok.",
        }

    # Split into runs of consecutive hours so a data gap never joins two separate blocks.
    runs: list[list[tuple[AirQualityReading, float]]] = [[scored[0]]]
    for previous, current in zip(scored, scored[1:]):
        gap = (current[0].read_time - previous[0].read_time).total_seconds()
        if gap > CONTIGUITY_GAP_SECONDS:
            runs.append([current])
        else:
            runs[-1].append(current)

    best: tuple[float, dt.datetime, list[tuple[AirQualityReading, float]]] | None = None
    for run in runs:
        size = min(window_hours, len(run))
        for start_index in range(len(run) - size + 1):
            window = run[start_index : start_index + size]
            mean_score = sum(value for _, value in window) / len(window)
            # Ties go to the earlier window: deterministic, and the earlier slot is the
            # one a person can still act on.
            candidate = (mean_score, window[0][0].read_time, window)
            if best is None or candidate[:2] < best[:2]:
                best = candidate

    assert best is not None  # scored is non-empty, so at least one window exists
    mean_score, _, window = best
    first, last = window[0][0], window[-1][0]
    start_local = first.read_time.astimezone(ISTANBUL_TZ)
    end_local = last.read_time.astimezone(ISTANBUL_TZ) + dt.timedelta(hours=1)

    aqi_values = [r.aqi_index for r, _ in window if r.aqi_index is not None]
    mean_aqi = sum(aqi_values) / len(aqi_values) if aqi_values else None
    band = aqi_band(mean_aqi)

    unit = "µg/m³" if metric == "pm10" else "AQI"
    label = (
        f"En temiz aralık {start_local:%d.%m %H:%M}–{end_local:%H:%M} "
        f"({'PM10' if metric == 'pm10' else 'AQI'} ort. {_tr_number(mean_score)} {unit}"
    )
    if band is not None:
        label += f", hava kalitesi: {band[0]}"
    label += ")."

    return {
        "found": True,
        "metric": metric,
        "start_utc": first.read_time.isoformat(),
        "end_utc": (last.read_time + dt.timedelta(hours=1)).isoformat(),
        "start_local": start_local.isoformat(),
        "end_local": end_local.isoformat(),
        "hours": len(window),
        "mean_value": round(mean_score, 1),
        "mean_aqi": None if mean_aqi is None else round(mean_aqi, 1),
        "band": band[0] if band else None,
        "band_key": band[1] if band else None,
        "considered_hours": len(horizon),
        "label": label,
        "note": (
            "Sıralama saatlik PM10 derişimine göre yapıldı; İBB'nin yayımladığı AQI "
            "değeri PM10 için 24 saatlik hareketli ortalamadır ve saatlik değişimi geç "
            "yansıtır. PM2.5 bu serviste yayımlanmıyor."
        ),
    }
