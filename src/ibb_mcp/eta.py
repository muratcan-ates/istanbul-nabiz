"""Bus arrival estimation for İETT lines — explainable arithmetic, deliberately no ML.

Everything here is an **ESTIMATE**. İETT publishes live vehicle positions and a planned
timetable but no official arrival prediction, so we build one from the two signals we
have. Three methods, tried in this order of preference and always recorded in
``BusArrival.method`` so the agent — and the person reading the answer — can tell which
one produced a number:

``stop_sequence``
    A bus reports the stop it is nearest to (``yakinDurakKodu``), which joins to GTFS
    ``stops.stop_code`` (verified 31/31 on line 500T). When that stop and the target
    both sit on the ordered stop list of the bus's route and the bus is *before* the
    target, the difference of their positions is how many stops away it is; multiply by
    a per-route seconds-per-stop figure. This one follows the road the bus really drives.

``distance``
    No usable stop order — unknown route, missing stop codes, or the bus is already past
    the target. Fall back to great-circle distance inflated by a road-winding factor and
    divided by an assumed city speed. It cannot see direction of travel, one-way streets
    or the Bosphorus, so it never earns better than 'medium'.

``schedule``
    No live bus is approaching at all. Fall back to the planned *departures* for today's
    day type. That answers "there is a 500T booked for 14:40", not "a bus reaches your
    stop at 14:40" — the gap is the run time from the terminus, which we do not know.
    Always 'low'.

Why no model: on day one there is no history to train on, and a wrong minute the user
cannot interrogate is worse than a rough minute they can. Instead every estimate is
logged to ``eta_log`` with the method and inputs that produced it; the collector later
marks the vehicle's real arrival (that door number turning up with the target stop as
its ``yakinDurakKodu``), turning the log into a measured ETA error — PLAN.md section
8.3. The MAE that falls out of that is what should move the constants in
:class:`EtaParams`, not intuition. The ``diagnostics`` dict returned beside the arrivals
is JSON-serialisable precisely so it can be written to that log.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Protocol, Sequence

from ibb_mcp.models import (
    ISTANBUL_TZ,
    BusArrival,
    BusPosition,
    PlannedDeparture,
    Stop,
    day_type_for,
    haversine_km,
    utcnow,
)

#: A scheduled row describes a departure, not a vehicle, so it carries no door number.
NO_VEHICLE = ""

#: Fallback city speed when the fleet tells us nothing (see :func:`speed_profile_from_fleet`).
DEFAULT_SPEED_KMH = 16.0

_CONFIDENCE_ORDER = ("high", "medium", "low")


def _downgrade(confidence: str) -> str:
    """One notch less certain, floored at 'low'."""
    position = _CONFIDENCE_ORDER.index(confidence) if confidence in _CONFIDENCE_ORDER else 1
    return _CONFIDENCE_ORDER[min(position + 1, len(_CONFIDENCE_ORDER) - 1)]


@dataclass(frozen=True)
class EtaParams:
    """Tunable constants. Every one is a guess until ``eta_log`` says otherwise.

    ``seconds_per_stop`` is the day-one placeholder from PLAN.md section 7 (2 minutes per
    stop); once the collector has line×hour history, pass a per-route override through
    ``speed_profile`` rather than editing this default.
    """

    seconds_per_stop: float = 120.0
    speed_kmh: float = DEFAULT_SPEED_KMH
    winding_factor: float = 1.35
    max_bus_age_s: float = 600.0
    max_results: int = 3
    #: At or below this many stops the sequence method is trustworthy enough to say 'high'.
    high_confidence_stops: int = 8
    #: Beyond this road distance the straight-line method is little better than a guess.
    low_confidence_km: float = 6.0
    #: How many planned departures to offer when falling back to the timetable.
    max_scheduled: int = 3


DEFAULT_PARAMS = EtaParams()


class StopSequenceLike(Protocol):
    """One route direction's ordered stops (``ibb_mcp.gtfs.RouteStopSequence``).

    Either a ``stop_codes`` sequence or a ``stops`` list of :class:`Stop` satisfies it.
    """

    route_code: str


class GtfsLookup(Protocol):
    """The two hooks this module needs from ``ibb_mcp.gtfs.GtfsIndex``.

    A protocol rather than an import: the ETA maths can then be unit-tested without
    loading 15 000 stops, and a change to the index's constructor cannot break it.
    """

    def stop_by_code(self, stop_code: str) -> Stop | None: ...

    def sequence_for_route(self, route_code: str) -> StopSequenceLike | None: ...


def _hook(index: GtfsLookup | None, method: str, table: str, key: str) -> Any:
    """Call ``index.<method>(key)``, or fall back to a ``index.<table>`` mapping."""
    if index is None or not key:
        return None
    getter = getattr(index, method, None)
    if callable(getter):
        return getter(key)
    mapping = getattr(index, table, None)
    return mapping.get(key) if isinstance(mapping, Mapping) else None


def _resolve_sequence(
    route_code: str | None,
    sequences: Mapping[str, StopSequenceLike] | None,
    index: GtfsLookup | None,
) -> StopSequenceLike | None:
    """Ordered stop list for a route, preferring the caller's own mapping."""
    if route_code and sequences and route_code in sequences:
        return sequences[route_code]
    return _hook(index, "sequence_for_route", "sequences", route_code or "")


def _stop_positions(sequence: StopSequenceLike | None) -> dict[str, int]:
    """Map ``stop_code`` -> position along the route.

    On a loop route a stop appears twice; first occurrence wins, which keeps "stops away"
    positive for a bus approaching the first time and under-counts one on its second pass.
    Under-counting is the safer error: it is wrong by a whole loop, so ``eta_log`` exposes
    it loudly instead of it hiding as a plausible number.
    """
    if sequence is None:
        return {}
    codes: Sequence[Any] | None = getattr(sequence, "stop_codes", None)
    if codes is None:
        codes = [getattr(stop, "stop_code", None) for stop in (getattr(sequence, "stops", None) or [])]
    positions: dict[str, int] = {}
    for position, code in enumerate(codes):
        if code is not None:
            positions.setdefault(str(code), position)
    return positions


def _seconds_per_stop(route_code: str | None, speed_profile: Mapping[str, float] | None, params: EtaParams) -> float:
    """Per-route seconds between consecutive stops, else the global default."""
    if speed_profile and route_code and (value := float(speed_profile.get(route_code) or 0)) > 0:
        return value
    return params.seconds_per_stop


def speed_profile_from_fleet(fleet: list[BusPosition]) -> float:
    """Median non-zero fleet speed in km/h, clamped to ``[8, 40]``.

    Feeds the 'distance' method so it tracks the city instead of a constant. Zeros are
    excluded on purpose: a bus reporting 0 km/h is almost always dwelling at a stop or
    stuck at a light, not broken, and a large share of any snapshot reads zero — keep them
    and the median collapses toward zero, turning every straight-line ETA into hours.
    Dropping them biases the figure optimistically instead, which is why the result is
    clamped and why anything derived from it is 'medium' at best.
    """
    speeds = [b.speed_kmh for b in fleet if b.speed_kmh is not None and b.speed_kmh > 0]
    if not speeds:
        return DEFAULT_SPEED_KMH
    return round(min(40.0, max(8.0, statistics.median(speeds))), 1)


# --------------------------------------------------------------------------------------
# the estimator
# --------------------------------------------------------------------------------------
def estimate_arrivals(
    *,
    buses: list[BusPosition],
    target: Stop,
    index: GtfsLookup | None = None,
    sequences: Mapping[str, StopSequenceLike] | None = None,
    scheduled: list[PlannedDeparture] | None = None,
    speed_profile: Mapping[str, float] | None = None,
    params: EtaParams = DEFAULT_PARAMS,
    now: dt.datetime | None = None,
) -> tuple[list[BusArrival], dict[str, Any]]:
    """Estimate when the next buses reach ``target``.

    ``speed_profile`` maps ``route_code`` -> **seconds per stop** for the 'stop_sequence'
    method. It is not the km/h figure from :func:`speed_profile_from_fleet`; that one
    belongs in ``params.speed_kmh`` and drives the 'distance' method.

    Returns arrivals sorted soonest-first and capped at ``params.max_results``, plus a
    JSON-serialisable diagnostics dict explaining what was discarded and why. Nothing is
    invented: an empty list with populated diagnostics is a legitimate answer that the
    agent should read out as "I cannot tell you right now".
    """
    moment = now or utcnow()
    diagnostics: dict[str, Any] = {
        "now": moment.isoformat(),
        "target_stop_code": target.stop_code,
        "buses_received": len(buses),
        "dropped_stale": 0,
        "dropped_unlocatable": 0,
        "dropped_passed_target": 0,
        "unknown_age": 0,
        "methods": {"stop_sequence": 0, "distance": 0, "schedule": 0},
        "sequence_routes": [],
        "notes": [],
        "params": asdict(params),
    }

    fresh = _drop_stale(buses, moment, params, diagnostics)
    arrivals = [
        arrival
        for bus in fresh
        if (arrival := _estimate_one(bus, target, index, sequences, speed_profile, params, diagnostics)) is not None
    ]

    if not arrivals:
        if fresh:
            diagnostics["notes"].append("live_buses_present_but_none_approaching")
        arrivals = _from_schedule(scheduled, target, moment, params, diagnostics)

    for arrival in arrivals:
        diagnostics["methods"][arrival.method] = diagnostics["methods"].get(arrival.method, 0) + 1
    arrivals.sort(key=lambda a: (a.eta_minutes if a.eta_minutes is not None else 1e9, a.stops_away or 0))

    capped = arrivals[: max(1, params.max_results)]
    diagnostics["estimated"] = len(arrivals)
    diagnostics["returned"] = len(capped)
    return capped, diagnostics


def _drop_stale(
    buses: list[BusPosition],
    moment: dt.datetime,
    params: EtaParams,
    diagnostics: dict[str, Any],
) -> list[BusPosition]:
    """Discard positions older than ``max_bus_age_s``; record the ages of those we kept.

    A ten-minute-old position has moved several stops since. Pretending otherwise is
    exactly the confident-but-wrong number this project refuses to emit. Positions with no
    timestamp are kept but counted, and their arrivals lose a notch of confidence later.
    """
    kept: list[BusPosition] = []
    ages: list[float] = []
    for bus in buses:
        if bus.reported_at is None:
            diagnostics["unknown_age"] += 1
            kept.append(bus)
            continue
        age = (moment - bus.reported_at).total_seconds()
        if age > params.max_bus_age_s:
            diagnostics["dropped_stale"] += 1
            continue
        ages.append(max(0.0, age))
        kept.append(bus)
    if ages:
        diagnostics["oldest_used_age_s"] = round(max(ages), 1)
        diagnostics["median_age_s"] = round(statistics.median(ages), 1)
    if diagnostics["dropped_stale"]:
        diagnostics["notes"].append(
            f"dropped_{diagnostics['dropped_stale']}_positions_older_than_{params.max_bus_age_s:.0f}s"
        )
    if diagnostics["unknown_age"]:
        diagnostics["notes"].append("positions_without_timestamp_were_downgraded")
    return kept


def _estimate_one(
    bus: BusPosition,
    target: Stop,
    index: GtfsLookup | None,
    sequences: Mapping[str, StopSequenceLike] | None,
    speed_profile: Mapping[str, float] | None,
    params: EtaParams,
    diagnostics: dict[str, Any],
) -> BusArrival | None:
    """One bus, one stop: sequence method when the route order allows it, else distance."""
    positions = _stop_positions(_resolve_sequence(bus.route_code, sequences, index))
    if positions and bus.route_code and bus.route_code not in diagnostics["sequence_routes"]:
        diagnostics["sequence_routes"].append(bus.route_code)

    target_index = positions.get(target.stop_code)
    bus_index = positions.get(bus.nearest_stop_code) if bus.nearest_stop_code else None

    if target_index is None or bus_index is None:
        return _distance_arrival(bus, target, index, params, diagnostics)
    if bus_index > target_index:
        # Past the stop in this route direction; it is not coming back on this trip.
        diagnostics["dropped_passed_target"] += 1
        return None

    stops_away = target_index - bus_index
    seconds = stops_away * _seconds_per_stop(bus.route_code, speed_profile, params)
    confidence = "high" if stops_away <= params.high_confidence_stops else "medium"
    return _arrival(
        bus,
        target,
        stops_away=stops_away,
        distance_km=_straight_km(bus.lat, bus.lon, target),
        eta_minutes=round(seconds / 60.0, 1),
        method="stop_sequence",
        confidence=confidence if bus.reported_at else _downgrade(confidence),
    )


def _distance_arrival(
    bus: BusPosition,
    target: Stop,
    index: GtfsLookup | None,
    params: EtaParams,
    diagnostics: dict[str, Any],
) -> BusArrival | None:
    """Great-circle distance × winding factor ÷ assumed speed.

    Blind to direction of travel: a bus 2 km away driving the other way scores the same as
    one about to arrive. Hence the 'medium' ceiling and the diagnostics note — the agent
    should hedge the wording, not bend the number.
    """
    lat, lon = bus.lat, bus.lon
    if lat is None or lon is None:
        # Last resort: stand the bus at the stop it says it is nearest to.
        proxy = _hook(index, "stop_by_code", "stops_by_code", bus.nearest_stop_code or "")
        lat, lon = (proxy.lat, proxy.lon) if proxy else (None, None)
    if lat is None or lon is None or target.lat is None or target.lon is None:
        diagnostics["dropped_unlocatable"] += 1
        return None

    straight_km = haversine_km(lat, lon, target.lat, target.lon)
    road_km = straight_km * params.winding_factor
    speed = params.speed_kmh if params.speed_kmh > 0 else DEFAULT_SPEED_KMH
    confidence = "low" if road_km > params.low_confidence_km else "medium"
    if "distance_method_is_direction_blind" not in diagnostics["notes"]:
        diagnostics["notes"].append("distance_method_is_direction_blind")
    return _arrival(
        bus,
        target,
        stops_away=None,
        distance_km=round(straight_km, 2),
        eta_minutes=round(road_km / speed * 60.0, 1),
        method="distance",
        confidence=confidence if bus.reported_at else _downgrade(confidence),
    )


def _arrival(bus: BusPosition, target: Stop, **fields: Any) -> BusArrival:
    return BusArrival(
        line_code=bus.line_code or "",
        stop_code=target.stop_code,
        stop_name=target.name,
        door_no=bus.door_no,
        direction=bus.direction,
        reported_at=bus.reported_at,
        **fields,
    )


def _straight_km(lat: float | None, lon: float | None, target: Stop) -> float | None:
    if lat is None or lon is None or target.lat is None or target.lon is None:
        return None
    return round(haversine_km(lat, lon, target.lat, target.lon), 2)


# --------------------------------------------------------------------------------------
# timetable fallback
# --------------------------------------------------------------------------------------
def _from_schedule(
    scheduled: list[PlannedDeparture] | None,
    target: Stop,
    moment: dt.datetime,
    params: EtaParams,
    diagnostics: dict[str, Any],
) -> list[BusArrival]:
    """Next planned departures for today's day type, when no live bus is approaching.

    ``eta_minutes`` counts to the *departure from the terminus*, not to arrival at
    ``target``; without ``stop_times.csv`` we cannot add the run time, so the honest move
    is to label the method 'schedule' and let the agent word it as a planned departure.
    """
    if not scheduled:
        diagnostics["notes"].append("no_schedule_fallback_available")
        return []

    today_code = day_type_for(moment)
    diagnostics["schedule_day_type"] = today_code
    todays = [d for d in scheduled if d.day_type == today_code and d.departure_time]
    if not todays:
        # Never silently borrow another day's timetable: Sunday headways are not Tuesday's.
        diagnostics["notes"].append(f"schedule_has_no_rows_for_day_type_{today_code}")
        return []

    local_now = moment.astimezone(ISTANBUL_TZ)
    upcoming = _upcoming_departures(todays, local_now)
    if not upcoming:
        tomorrow = (local_now + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        rows = [d for d in scheduled if d.day_type == day_type_for(tomorrow) and d.departure_time]
        upcoming = _upcoming_departures(rows, tomorrow)
        if upcoming:
            diagnostics["notes"].append("service_finished_today_showing_first_departures_of_next_day")

    arrivals = [
        BusArrival(
            line_code=departure.line_code,
            stop_code=target.stop_code,
            stop_name=target.name,
            door_no=NO_VEHICLE,
            direction=departure.direction,
            stops_away=None,
            distance_km=None,
            eta_minutes=round((when - local_now).total_seconds() / 60.0, 1),
            method="schedule",
            confidence="low",
            reported_at=None,
        )
        for when, departure in upcoming[: max(1, params.max_scheduled)]
    ]
    if arrivals:
        diagnostics["notes"].append("eta_is_time_until_planned_departure_not_arrival_at_stop")
    return arrivals


def _upcoming_departures(
    rows: list[PlannedDeparture],
    after: dt.datetime,
) -> list[tuple[dt.datetime, PlannedDeparture]]:
    """Resolve ``HH:MM`` strings against ``after``'s date, keeping only later departures.

    İETT writes post-midnight runs as hours >= 24 ("24:30"), which roll into the next day.
    """
    resolved: list[tuple[dt.datetime, PlannedDeparture]] = []
    seen: set[str] = set()
    for row in rows:
        when = _resolve_clock(row.departure_time, after)
        key = f"{row.route_code}|{row.departure_time}"
        if when is None or when < after or key in seen:
            continue
        seen.add(key)
        resolved.append((when, row))
    resolved.sort(key=lambda pair: pair[0])
    return resolved


def _resolve_clock(clock: str | None, reference: dt.datetime) -> dt.datetime | None:
    if not clock:
        return None
    parts = clock.strip().split(":")
    if len(parts) < 2 or not all(p.strip().isdigit() for p in parts[:2]):
        return None
    hour, minute = int(parts[0]), int(parts[1])
    if minute > 59:
        return None
    day_offset, hour = divmod(hour, 24)
    base = reference.replace(hour=0, minute=0, second=0, microsecond=0)
    return base + dt.timedelta(days=day_offset, hours=hour, minutes=minute)
