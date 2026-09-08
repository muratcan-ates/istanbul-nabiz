"""Pure snapshot builders: one İBB read in, a list of flat rows out.

This module is the whole reason the project has a collector. İBB publishes *current
state* and keeps no public history, so "bu otoparkta salı 18:00'de genelde ne kadar yer
olur", "bu hatta bu saatte ortalama hız" and the measured ETA error can only ever come
from snapshots we take ourselves. Every function here turns one upstream read into rows
that :mod:`nabiz.collector.lake` and :mod:`nabiz.collector.kusto` can write without
knowing anything about İBB.

Three rules hold for every function:

* **No Azure imports.** Nothing here touches storage, so the interesting logic stays
  unit-testable against ``tests/fixtures`` with ``Settings(offline=True)``.
* **A failure returns ``[]``, never an exception.** These run on timers. A raised
  exception marks the invocation failed and buys nothing: the next tick is two to ten
  minutes away and will read the same endpoint again. What matters is that a bad tick
  writes *nothing* rather than writing something wrong.
* **A stale read is not a snapshot.** :class:`~ibb_mcp.cache.TTLCache` deliberately
  serves an expired entry when the gateway fails, so a live answer degrades instead of
  breaking. For a collector that same behaviour would re-record a reading we already
  have under a new timestamp — inventing history. ``Provenance.cached`` is exactly the
  "this is stale, upstream failed" flag, so those ticks are dropped.

Timestamps in every row are ISO-8601 UTC with a ``Z`` suffix. Two are carried:

``ts_utc``
    when the *measurement* was taken, as the source reports it.
``snapshot_ts_utc``
    when *we* read it. Identical for sources that publish no timestamp of their own
    (İSPARK), and the key that groups every row written by one timer tick.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from ibb_mcp.cache import TTLCache
from ibb_mcp.config import Settings
from ibb_mcp.http import PoliteClient
from ibb_mcp.models import Provenance, utcnow
from ibb_mcp.sources.airquality import AirQualitySource
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.sources.iett import IettSource
from ibb_mcp.sources.ispark import IsparkSource
from ibb_mcp.sources.metro import MetroSource
from ibb_mcp.sources.traffic import TrafficSource

log = logging.getLogger("nabiz.collector.snapshots")

#: Cache TTL used by the collector, in seconds.
#:
#: Short, but deliberately not zero. Zero would make every freshly stored entry compare
#: as expired, and :func:`_read` would then discard every tick as stale. Five seconds is
#: long enough for that check to pass and far shorter than the fastest timer (two
#: minutes), so a tick always re-reads İBB rather than re-recording the previous answer.
COLLECTOR_TTL_SECONDS = 5.0

#: Sources whose TTL the collector overrides. Station lists and timetables are excluded
#: on purpose: they are static reference data and re-fetching them every tick would spend the
#: İETT hourly budget for nothing.
_FAST_TTL_SOURCES = ("ispark", "iett_fleet", "metro_status", "traffic", "aq_readings")

#: Hourly traffic points kept per tick. The endpoint always returns the last 24 hours, so
#: re-writing all 25 points every hour would store the same reading 25 times. Three keeps
#: the write small while still healing one or two missed ticks; ``(ts_utc)`` is the
#: natural key that makes the overlap harmless.
TRAFFIC_HOURS = 3


def build_collector_context(settings: Settings | None = None) -> SourceContext:
    """A :class:`SourceContext` tuned for collection rather than for serving answers.

    The MCP server wants long TTLs — N users must cost one upstream call. The collector
    wants the opposite: each tick is a fresh observation, so the cache is reduced to a
    few seconds for the live sources. Everything else (one client, per-host 6 s spacing,
    the İETT hourly budget) is shared machinery we very much do want.
    """
    resolved = settings or Settings.from_env()
    cache = TTLCache(ttl_by_source=dict.fromkeys(_FAST_TTL_SOURCES, COLLECTOR_TTL_SECONDS))
    return SourceContext.create(client=PoliteClient(), cache=cache, settings=resolved)


def iso_utc(moment: dt.datetime | None) -> str | None:
    """Render a moment as ISO-8601 UTC with a ``Z``. Naive input is assumed to be UTC."""
    if moment is None:
        return None
    aware = moment.replace(tzinfo=dt.UTC) if moment.tzinfo is None else moment
    return aware.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _observed_at(provenance: Provenance) -> dt.datetime:
    """The moment the snapshot was taken, as the source recorded it."""
    return provenance.observed_at


async def _read[T](
    name: str,
    loader: Callable[[], Awaitable[tuple[T, Provenance]]],
) -> tuple[T, Provenance] | None:
    """Run one source read, returning ``None`` for both failure modes.

    Collapsing "upstream raised" and "cache served a stale entry after upstream failed"
    into one ``None`` is the point: from the collector's side they are the same event —
    we learned nothing new this tick — and both must produce zero rows rather than a
    duplicate of the last good reading stamped with the current time.
    """
    try:
        value, provenance = await loader()
    except Exception as exc:  # noqa: BLE001 - a timer must never die on an upstream wobble
        log.error("collector/%s: read failed, tick skipped: %r", name, exc)
        return None
    if provenance.cached:
        log.warning("collector/%s: upstream unavailable, stale cache not re-recorded", name)
        return None
    return value, provenance


# --------------------------------------------------------------------------------------
# İSPARK — every 10 minutes
# --------------------------------------------------------------------------------------
async def snapshot_ispark(ctx: SourceContext) -> list[dict[str, Any]]:
    """Occupancy of every İSPARK car park. One row per lot.

    This is the series behind ``ispark_typical_occupancy``: İBB publishes the current
    free-space count and nothing else, so a "genelde bu saatte" answer exists only if
    somebody keeps the readings. ``/ispark/Park`` returns all 249 lots in one call, so a
    whole-city snapshot costs exactly one gateway request.

    Schema (stable, ``ispark_snapshot``):

    park_id             int      İSPARK ``parkID``
    ts_utc              str      reading time — see the note below
    snapshot_ts_utc     str      timer tick that produced the row
    capacity            int?     total bays
    empty               int?     free bays as reported
    occupancy_pct       float?   ``100 * (capacity - empty) / capacity``, 1 decimal
    is_open             bool?    barrier state; ``None`` when İSPARK omits it
    district            str?     ilçe

    ``ts_utc`` equals ``snapshot_ts_utc``: the list endpoint publishes no timestamp —
    only ``/ispark/ParkDetay`` carries ``updateDate``, and fetching that for 249 lots
    would cost 249 gateway calls at 6 s spacing. Reading time is therefore our own
    observation time, and can lag by up to the ~10 minute İSPARK refresh.
    """
    read = await _read("ispark", IsparkSource(ctx).list_parks)
    if read is None:
        return []
    lots, provenance = read
    stamp = iso_utc(_observed_at(provenance))
    return [
        {
            "park_id": lot.park_id,
            "ts_utc": stamp,
            "snapshot_ts_utc": stamp,
            "capacity": lot.capacity,
            "empty": lot.empty,
            "occupancy_pct": lot.occupancy_pct,
            "is_open": lot.is_open,
            "district": lot.district,
        }
        for lot in lots
    ]


# --------------------------------------------------------------------------------------
# İETT fleet — every 2 minutes
# --------------------------------------------------------------------------------------
async def snapshot_fleet(ctx: SourceContext) -> list[dict[str, Any]]:
    """Position and speed of every reporting bus. One row per vehicle.

    ``GetFiloAracKonum_json`` returns the whole fleet (6 911 vehicles, 1.1 MB) in one
    call, so a two-minute cadence costs 30 of the 100 requests İETT allows per hour and
    still yields both the line-hour speed profile the ETA engine needs and the ground
    truth for the ETA accuracy log.

    **The plate never appears here.** The upstream record carries ``Plaka``;
    ``BusPosition.from_fleet_raw`` drops it at the parsing boundary (DECISIONS.md §7,
    NOTICE.md) and this function only ever reads parsed models, so there is no field for
    it to reappear in. Door number is the vehicle identity.

    Schema (stable, ``iett_fleet_snapshot``):

    door_no             str      ``KapiNo``, the vehicle identity
    ts_utc              str?     the vehicle's own clock
    snapshot_ts_utc     str      timer tick that produced the row
    lat / lon           float?   WGS84, repaired for the misplaced decimal point
    speed_kmh           float?   instantaneous speed as reported

    ``ts_utc`` can be ``None``: the fleet feed sends a bare clock ("23:03:07") with no
    date, and ``iett._redate_future_clocks`` moves a stamp that lands in the future back a
    day. A vehicle whose clock cannot be read keeps a null rather than borrowing the tick
    time, so a unit parked since last night can never be mistaken for a live one.
    """
    read = await _read("iett_fleet", IettSource(ctx).fleet_positions)
    if read is None:
        return []
    buses, provenance = read
    stamp = iso_utc(_observed_at(provenance))
    return [
        {
            "door_no": bus.door_no,
            "ts_utc": iso_utc(bus.reported_at),
            "snapshot_ts_utc": stamp,
            "lat": bus.lat,
            "lon": bus.lon,
            "speed_kmh": bus.speed_kmh,
        }
        for bus in buses
    ]


# --------------------------------------------------------------------------------------
# Metro İstanbul — hourly
# --------------------------------------------------------------------------------------
async def snapshot_metro(ctx: SourceContext) -> list[dict[str, Any]]:
    """Live line notices, plus a heartbeat row when there are none.

    ``GetServiceStatuses`` lists only the lines that currently carry a notice, so an
    empty response means "hiçbir hatta bildirim yok". Writing nothing for that tick would
    make it indistinguishable from a tick that failed, and the difference is the entire
    value of the table: "M4 was fine at 09:00" is provable only if the successful empty
    read was recorded. Hence ``has_notice`` and the single heartbeat row.

    Schema (stable, ``metro_status``):

    line_id             int?     Metro İstanbul line id (null on a heartbeat row)
    line_name           str?     e.g. ``M7`` (null on a heartbeat row)
    description         str?     the notice text as published
    is_active           bool?    whether the notice is currently in force
    has_notice          bool     ``False`` only on the heartbeat row
    ts_utc              str      notice ``UpdateDate``, or the tick for a heartbeat
    snapshot_ts_utc     str      timer tick that produced the row
    color               str?     line colour, ``#RRGGBB``
    """
    read = await _read("metro_status", MetroSource(ctx).service_status)
    if read is None:
        return []
    statuses, provenance = read
    stamp = iso_utc(_observed_at(provenance))

    if not statuses:
        return [
            {
                "line_id": None,
                "line_name": None,
                "description": None,
                "is_active": None,
                "has_notice": False,
                "ts_utc": stamp,
                "snapshot_ts_utc": stamp,
                "color": None,
            }
        ]

    return [
        {
            "line_id": status.line_id,
            "line_name": status.line_name,
            "description": status.description,
            "is_active": status.is_active,
            "has_notice": True,
            "ts_utc": iso_utc(status.updated_at) or stamp,
            "snapshot_ts_utc": stamp,
            "color": status.color,
        }
        for status in statuses
    ]


# --------------------------------------------------------------------------------------
# Traffic index — hourly
# --------------------------------------------------------------------------------------
async def snapshot_traffic(ctx: SourceContext, hours: int = TRAFFIC_HOURS) -> list[dict[str, Any]]:
    """The city-wide traffic index for the last ``hours`` hourly buckets.

    The bucket is fixed to ``H`` and the window to one day — the same call the MCP server
    caches, so the two share a payload. Only the newest ``hours`` points are kept; see
    :data:`TRAFFIC_HOURS` for why re-writing all 25 would be waste rather than history.

    Schema (stable, ``traffic_index_hourly``):

    traffic_index       int      1–99, İBB's own congestion index
    ts_utc              str      ``TrafficIndexDate`` of the bucket
    snapshot_ts_utc     str      timer tick that produced the row
    """
    read = await _read("traffic", lambda: TrafficSource(ctx).index_history(days=1, period="H"))
    if read is None:
        return []
    points, provenance = read
    stamp = iso_utc(_observed_at(provenance))
    dated = [point for point in points if point.at is not None]
    window = dated[-hours:] if hours > 0 else dated
    return [
        {
            "traffic_index": point.index,
            "ts_utc": iso_utc(point.at),
            "snapshot_ts_utc": stamp,
        }
        for point in window
    ]


# --------------------------------------------------------------------------------------
# Air quality — hourly
# --------------------------------------------------------------------------------------
async def snapshot_air_quality(ctx: SourceContext, hours: int = 2) -> list[dict[str, Any]]:
    """Hourly readings from every station over the last ``hours`` hours, deduplicated.

    Two hours rather than one because ``EndDate`` is inclusive and readings arrive late:
    the overlap re-reads an hour we already have and heals a missed tick, while
    ``(station_id, ts_utc)`` makes the repeat harmless. The 28 stations are read one at a
    time behind the shared 6 s gateway gate, so a tick is about three minutes of mostly
    waiting — affordable hourly, and the reason this is not a two-minute timer. A station
    that fails is logged and skipped, so the other 27 are still recorded.

    **PM2.5 is not in this API** (only PM10, SO2, O3, NO2, CO) and no column is invented
    for it. ``aqi_index`` is İBB's published index, whose PM10 sub-index is a rolling
    24-hour mean — the hourly ``pm10`` concentration is the honest short-horizon signal,
    and both are stored side by side.

    Schema (stable, ``aq_hourly``):

    station_id          str      İBB station GUID
    station_name        str      e.g. ``Maslak``
    ts_utc              str      ``ReadTime`` of the hourly reading
    snapshot_ts_utc     str      timer tick that produced the row
    pm10 … co           float?   concentrations in µg/m³ (CO in mg/m³), often null
    aqi_index           float?   published index — a rolling mean, not an hourly value
    dominant            str?     ``ContaminantParameter`` driving the index
    """
    source = AirQualitySource(ctx)
    listing = await _read("aq_stations", source.stations)
    if listing is None:
        return []
    stations, _ = listing

    # The window is anchored to *now*, deliberately not to the station list's provenance:
    # that list is static reference data cached for a day, so its observation time can be
    # 23 hours old and would silently make every tick re-read yesterday's readings.
    end = utcnow()
    start = end - dt.timedelta(hours=max(1, hours))
    stamp = iso_utc(end)

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()
    for station in stations:
        read = await _read(
            f"aq_readings/{station.station_id}",
            lambda station=station: source.readings(station.station_id, start, end),
        )
        if read is None:
            continue
        readings, _ = read
        for reading in readings:
            key = (station.station_id, iso_utc(reading.read_time))
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "station_id": station.station_id,
                    "station_name": station.name,
                    "ts_utc": key[1],
                    "snapshot_ts_utc": stamp,
                    "pm10": reading.pm10,
                    "so2": reading.so2,
                    "o3": reading.o3,
                    "no2": reading.no2,
                    "co": reading.co,
                    "aqi_index": reading.aqi_index,
                    "dominant": reading.dominant,
                }
            )
    return rows


#: Snapshot builders by lake/ADX source key, so a caller can iterate the whole collector.
SNAPSHOTS: dict[str, Callable[[SourceContext], Awaitable[list[dict[str, Any]]]]] = {
    "ispark_snapshot": snapshot_ispark,
    "iett_fleet_snapshot": snapshot_fleet,
    "metro_status": snapshot_metro,
    "traffic_index_hourly": snapshot_traffic,
    "aq_hourly": snapshot_air_quality,
}
