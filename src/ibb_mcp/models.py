"""Typed models for every İBB source.

Design rules that the whole project depends on:

* Every model that leaves a tool carries a :class:`Provenance`, so the agent can
  cite a source and a timestamp for every number it says out loud. The numeric
  faithfulness checker in the eval harness relies on this.
* Raw İBB payloads are messy (numbers as strings, Turkish decimals, corrupted
  coordinates, double-encoded text). Parsing lives in the ``from_raw``
  classmethods so the rest of the codebase only ever sees clean types.
* The İETT fleet feed exposes bus number plates. We deliberately never store or
  return them; see ``BusPosition.from_raw`` and COMPLIANCE.md.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from typing import Any

from pydantic import BaseModel, Field

ISTANBUL_TZ = dt.timezone(dt.timedelta(hours=3))  # Türkiye is fixed UTC+3 (no DST since 2016)

# İBB bounding box, used to reject coordinates that survive repair but are absurd.
LAT_RANGE = (40.7, 41.7)
LON_RANGE = (27.9, 29.95)


# --------------------------------------------------------------------------------------
# parsing helpers
# --------------------------------------------------------------------------------------
def parse_number(value: Any) -> float | None:
    """Parse a number that may arrive as a string, with Turkish or English separators."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    # Turkish formatting: "1.234,5" -> 1234.5
    if "," in text:
        try:
            return float(text.replace(".", "").replace(",", "."))
        except ValueError:
            return None
    return None


def repair_coordinate(value: Any, kind: str) -> float | None:
    """Repair coordinates that İBB exports with thousands separators.

    The GTFS feed writes ``41.0191700005564`` as ``410.191.700.005.564``. Stripping the
    dots and re-inserting the decimal point after two digits recovers the value. Values
    that are already well formed pass through untouched.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        candidate = float(value)
    else:
        text = str(value).strip()
        if not text:
            return None
        # Already sane: a single dot and a plausible magnitude.
        if text.count(".") <= 1:
            try:
                candidate = float(text)
            except ValueError:
                return None
        else:
            digits = text.replace(".", "").replace(",", "")
            if not digits.isdigit():
                return None
            candidate = float(f"{digits[:2]}.{digits[2:]}")
    lo, hi = LAT_RANGE if kind == "lat" else LON_RANGE
    return candidate if lo <= candidate <= hi else None


def demojibake(text: str | None) -> str | None:
    """Undo the double-encoding in İBB's GTFS ``routes.csv`` (``KADIKÃ–Y`` -> ``KADIKÖY``)."""
    if not text:
        return text
    if not any(marker in text for marker in ("Ã", "Å", "Ä", "Ð")):
        return text
    try:
        return text.encode("cp1252").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text


def parse_wkt_point(value: str | None) -> tuple[float | None, float | None]:
    """``POINT (29.0245 41.1000)`` -> ``(41.1000, 29.0245)``. Note the WKT lon/lat order."""
    if not value:
        return None, None
    match = re.search(r"POINT\s*\(\s*([\d.\-]+)\s+([\d.\-]+)\s*\)", value, re.IGNORECASE)
    if not match:
        return None, None
    lon, lat = float(match.group(1)), float(match.group(2))
    return lat, lon


def parse_ibb_datetime(value: str | None) -> dt.datetime | None:
    """Parse the several timestamp shapes İBB uses, always returning an aware UTC datetime.

    Naive timestamps are Istanbul local time; İSPARK uses ``dd.MM.yyyy HH:mm:ss``,
    İETT uses ``yyyy-MM-dd HH:mm:ss`` or a bare ``HH:mm:ss``, Metro uses ISO 8601.
    """
    if not value:
        return None
    text = str(value).strip()
    formats = ("%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S")
    for fmt in formats:
        try:
            return dt.datetime.strptime(text, fmt).replace(tzinfo=ISTANBUL_TZ).astimezone(dt.UTC)
        except ValueError:
            continue
    # Bare clock time (İETT fleet "Saat"): assume today in Istanbul.
    try:
        clock = dt.datetime.strptime(text, "%H:%M:%S").time()
    except ValueError:
        return None
    today = dt.datetime.now(ISTANBUL_TZ).date()
    return dt.datetime.combine(today, clock, tzinfo=ISTANBUL_TZ).astimezone(dt.UTC)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


# --------------------------------------------------------------------------------------
# provenance
# --------------------------------------------------------------------------------------
class Provenance(BaseModel):
    """Where a payload came from and how stale it is.

    ``observed_at`` is when we fetched it; ``reported_at`` is the timestamp İBB itself
    put on the data, when one exists. The agent quotes ``reported_at`` to the user.
    """

    source: str = Field(description="Short source key, e.g. 'ispark' or 'iett'.")
    source_url: str
    observed_at: dt.datetime = Field(default_factory=utcnow)
    reported_at: dt.datetime | None = None
    cached: bool = False
    license: str = "İBB Açık Veri Lisansı (CC BY 4.0)"

    @property
    def age_seconds(self) -> float:
        reference = self.reported_at or self.observed_at
        return max(0.0, (utcnow() - reference).total_seconds())

    def describe_age(self) -> str:
        """Data age in the largest unit a person would use.

        The agent says this out loud after every live number, so it has to stay readable
        at both ends of the range. A Metro disruption notice can legitimately be six weeks
        old, and "1034.3 saat önce" is technically right and useless.
        """
        seconds = self.age_seconds
        if seconds < 90:
            return f"{int(seconds)} sn önce"
        if seconds < 5400:
            return f"{int(seconds // 60)} dk önce"
        if seconds < 172_800:  # under two days, hours still read naturally
            return f"{seconds / 3600:.1f} saat önce"
        days = seconds / 86_400
        if days < 60:
            return f"{int(days)} gün önce"
        return f"{days / 30:.0f} ay önce"


class ToolResult(BaseModel):
    """Envelope every MCP tool returns: data plus the provenance needed to cite it."""

    data: Any
    provenance: Provenance
    note: str | None = None


# --------------------------------------------------------------------------------------
# İSPARK
# --------------------------------------------------------------------------------------
class ParkingLot(BaseModel):
    park_id: int
    name: str
    lat: float | None = None
    lon: float | None = None
    capacity: int | None = None
    empty: int | None = None
    park_type: str | None = None
    district: str | None = None
    work_hours: str | None = None
    free_minutes: int | None = None
    is_open: bool | None = None
    # ParkDetay only
    address: str | None = None
    tariff: str | None = None
    monthly_fee: float | None = None
    updated_at: dt.datetime | None = None
    # computed
    distance_km: float | None = None

    @property
    def occupancy_pct(self) -> float | None:
        if not self.capacity or self.empty is None:
            return None
        return round(100.0 * (self.capacity - self.empty) / self.capacity, 1)

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> ParkingLot:
        return cls(
            park_id=int(raw["parkID"]),
            name=str(raw.get("parkName") or "").strip(),
            lat=repair_coordinate(raw.get("lat"), "lat"),
            lon=repair_coordinate(raw.get("lng"), "lon"),
            capacity=int(parse_number(raw.get("capacity")) or 0) or None,
            empty=int(v) if (v := parse_number(raw.get("emptyCapacity"))) is not None else None,
            park_type=(raw.get("parkType") or "").strip() or None,
            district=(raw.get("district") or "").strip() or None,
            work_hours=(raw.get("workHours") or "").strip() or None,
            free_minutes=int(v) if (v := parse_number(raw.get("freeTime"))) is not None else None,
            is_open=bool(parse_number(raw.get("isOpen"))) if raw.get("isOpen") is not None else None,
            address=(raw.get("address") or "").strip() or None,
            tariff=(raw.get("tariff") or "").strip() or None,
            monthly_fee=parse_number(raw.get("monthlyFee")),
            updated_at=parse_ibb_datetime(raw.get("updateDate")),
        )


# --------------------------------------------------------------------------------------
# İETT
# --------------------------------------------------------------------------------------
class BusPosition(BaseModel):
    """One bus on a line.

    The upstream payload contains a number plate (``Plaka``). We drop it here and never
    persist it: the door number identifies the vehicle well enough for every feature we
    build, and storing plates would put an identifier we do not need into the lake.
    """

    door_no: str
    lat: float | None = None
    lon: float | None = None
    line_code: str | None = None
    route_code: str | None = None
    line_name: str | None = None
    direction: str | None = None
    nearest_stop_code: str | None = None
    speed_kmh: float | None = None
    reported_at: dt.datetime | None = None
    operator: str | None = None

    @classmethod
    def from_line_raw(cls, raw: dict[str, Any]) -> BusPosition:
        """Parse a ``GetHatOtoKonum_json`` record (per-line query)."""
        return cls(
            door_no=str(raw.get("kapino") or "").strip(),
            lat=repair_coordinate(raw.get("enlem"), "lat"),
            lon=repair_coordinate(raw.get("boylam"), "lon"),
            line_code=(raw.get("hatkodu") or "").strip() or None,
            route_code=(raw.get("guzergahkodu") or "").strip() or None,
            line_name=demojibake((raw.get("hatad") or "").strip()) or None,
            direction=demojibake((raw.get("yon") or "").strip()) or None,
            nearest_stop_code=(str(raw.get("yakinDurakKodu")).strip() or None) if raw.get("yakinDurakKodu") else None,
            reported_at=parse_ibb_datetime(raw.get("son_konum_zamani")),
        )

    @classmethod
    def from_fleet_raw(cls, raw: dict[str, Any]) -> BusPosition:
        """Parse a ``GetFiloAracKonum_json`` record (whole fleet). Plate is discarded."""
        return cls(
            door_no=str(raw.get("KapiNo") or "").strip(),
            lat=repair_coordinate(raw.get("Enlem"), "lat"),
            lon=repair_coordinate(raw.get("Boylam"), "lon"),
            speed_kmh=parse_number(raw.get("Hiz")),
            reported_at=parse_ibb_datetime(raw.get("Saat")),
            operator=demojibake((raw.get("Operator") or "").strip()) or None,
        )


class Stop(BaseModel):
    """A GTFS stop.

    ``stop_code`` is the join key to live vehicle telemetry: a bus reports
    ``yakinDurakKodu``, which matches ``stop_code`` (not ``stop_id``). Verified against
    live data for line 500T: 31/31 matched.
    """

    stop_code: str
    stop_id: str | None = None
    name: str | None = None
    description: str | None = None
    lat: float | None = None
    lon: float | None = None
    distance_km: float | None = None


class Route(BaseModel):
    """A GTFS route. ``route_code`` matches the live feed's ``guzergahkodu``."""

    route_id: str
    route_code: str | None = None
    short_name: str | None = None
    long_name: str | None = None
    description: str | None = None


class PlannedDeparture(BaseModel):
    """A scheduled departure from ``GetPlanlananSeferSaati_json``.

    ``day_type`` uses İETT's single-letter codes; see :data:`DAY_TYPE_LABELS`.
    """

    line_code: str
    route_code: str | None = None
    line_name: str | None = None
    direction: str | None = None
    day_type: str | None = None
    departure_time: str | None = None
    service_type: str | None = None

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> PlannedDeparture:
        return cls(
            line_code=str(raw.get("SHATKODU") or "").strip(),
            route_code=(raw.get("SGUZERAH") or "").strip() or None,
            line_name=demojibake((raw.get("HATADI") or "").strip()) or None,
            direction=(raw.get("SYON") or "").strip() or None,
            day_type=(raw.get("SGUNTIPI") or "").strip() or None,
            departure_time=(raw.get("DT") or "").strip() or None,
            service_type=demojibake((raw.get("SSERVISTIPI") or "").strip()) or None,
        )


DAY_TYPE_LABELS = {"I": "Hafta içi", "C": "Cumartesi", "P": "Pazar"}


def day_type_for(moment: dt.datetime | None = None) -> str:
    """İETT day-type code for a moment in Istanbul time."""
    local = (moment or utcnow()).astimezone(ISTANBUL_TZ)
    return {5: "C", 6: "P"}.get(local.weekday(), "I")


class BusArrival(BaseModel):
    """A predicted arrival of one bus at one stop."""

    line_code: str
    stop_code: str
    stop_name: str | None = None
    door_no: str
    direction: str | None = None
    stops_away: int | None = None
    distance_km: float | None = None
    eta_minutes: float | None = None
    method: str = Field(description="How the ETA was produced: 'stop_sequence', 'distance', or 'schedule'.")
    confidence: str = "medium"
    reported_at: dt.datetime | None = None


# --------------------------------------------------------------------------------------
# Metro İstanbul
# --------------------------------------------------------------------------------------
class MetroLineStatus(BaseModel):
    line_id: int | None = None
    line_name: str | None = None
    description: str | None = None
    is_active: bool | None = None
    updated_at: dt.datetime | None = None
    color: str | None = None

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> MetroLineStatus:
        return cls(
            line_id=int(v) if (v := parse_number(raw.get("LineId"))) is not None else None,
            line_name=(raw.get("LineName") or "").strip() or None,
            description=(raw.get("Description") or "").strip() or None,
            is_active=raw.get("IsActive"),
            updated_at=parse_ibb_datetime(raw.get("UpdateDate")),
            color=(raw.get("LineColor") or "").strip() or None,
        )


class MetroStation(BaseModel):
    station_id: int | None = None
    name: str | None = None
    line_name: str | None = None
    order: int | None = None
    lat: float | None = None
    lon: float | None = None
    escalators: int | None = None
    lifts: int | None = None
    baby_room: bool | None = None
    wc: bool | None = None
    masjid: bool | None = None

    @property
    def step_free(self) -> bool | None:
        """Whether the station has at least one lift, the usual proxy for step-free access."""
        return None if self.lifts is None else self.lifts > 0

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> MetroStation:
        detail = raw.get("DetailInfo") or {}
        return cls(
            station_id=int(v) if (v := parse_number(raw.get("Id"))) is not None else None,
            name=(raw.get("Description") or raw.get("Name") or "").strip() or None,
            line_name=(raw.get("LineName") or "").strip() or None,
            order=int(v) if (v := parse_number(raw.get("Order"))) is not None else None,
            lat=repair_coordinate(detail.get("Latitude"), "lat"),
            lon=repair_coordinate(detail.get("Longitude"), "lon"),
            escalators=int(v) if (v := parse_number(detail.get("Escolator"))) is not None else None,
            lifts=int(v) if (v := parse_number(detail.get("Lift"))) is not None else None,
            baby_room=detail.get("BabyRoom"),
            wc=detail.get("WC"),
            masjid=detail.get("Masjid"),
        )


# --------------------------------------------------------------------------------------
# Traffic
# --------------------------------------------------------------------------------------
class TrafficIndexPoint(BaseModel):
    index: int
    at: dt.datetime | None = None

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> TrafficIndexPoint:
        return cls(
            index=int(parse_number(raw.get("TrafficIndex")) or 0),
            at=parse_ibb_datetime(raw.get("TrafficIndexDate")),
        )


def describe_traffic(index: int) -> str:
    if index <= 20:
        return "akıcı"
    if index <= 40:
        return "hafif yoğun"
    if index <= 60:
        return "yoğun"
    if index <= 80:
        return "çok yoğun"
    return "kilitli"


# --------------------------------------------------------------------------------------
# Air quality
# --------------------------------------------------------------------------------------
class AirQualityStation(BaseModel):
    station_id: str
    name: str
    address: str | None = None
    lat: float | None = None
    lon: float | None = None
    distance_km: float | None = None

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> AirQualityStation:
        lat, lon = parse_wkt_point(raw.get("Location"))
        return cls(
            station_id=str(raw["Id"]),
            name=(raw.get("Name") or "").strip(),
            address=(raw.get("Adress") or "").strip() or None,
            lat=lat,
            lon=lon,
        )


class AirQualityReading(BaseModel):
    """One hourly reading.

    İBB computes the PM10 sub-index over a rolling 24-hour mean (O3 and CO over 8 hours),
    so ``aqi_index`` reacts slowly compared with ``pm10``. Anything that needs an
    hour-by-hour signal should use the concentration, not the index.
    """

    read_time: dt.datetime | None = None
    pm10: float | None = None
    so2: float | None = None
    o3: float | None = None
    no2: float | None = None
    co: float | None = None
    aqi_index: float | None = None
    dominant: str | None = None
    state: str | None = None
    color: str | None = None

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> AirQualityReading:
        conc = raw.get("Concentration") or {}
        aqi = raw.get("AQI") or {}
        return cls(
            read_time=parse_ibb_datetime(raw.get("ReadTime")),
            pm10=parse_number(conc.get("PM10")),
            so2=parse_number(conc.get("SO2")),
            o3=parse_number(conc.get("O3")),
            no2=parse_number(conc.get("NO2")),
            co=parse_number(conc.get("CO")),
            aqi_index=parse_number(aqi.get("AQIIndex")),
            dominant=(aqi.get("ContaminantParameter") or "").strip() or None,
            state=(aqi.get("State") or "").strip() or None,
            color=(aqi.get("Color") or "").strip() or None,
        )


AQI_BANDS = [
    (50, "İyi", "good"),
    (100, "Orta", "moderate"),
    (150, "Hassas gruplar için sağlıksız", "unhealthy_sensitive"),
    (200, "Sağlıksız", "unhealthy"),
    (300, "Kötü", "very_unhealthy"),
    (500, "Tehlikeli", "hazardous"),
]


def aqi_band(index: float | None) -> tuple[str, str] | None:
    if index is None:
        return None
    for upper, label, key in AQI_BANDS:
        if index <= upper:
            return label, key
    return "Tehlikeli", "hazardous"


class FreshnessEntry(BaseModel):
    source: str
    last_success: dt.datetime | None = None
    age_seconds: float | None = None
    healthy: bool = True
    detail: str | None = None
