"""Bus arrival estimation for İETT lines — explainable arithmetic, deliberately no ML.

Everything here is an **ESTIMATE**. İETT publishes live vehicle positions and a planned
timetable but no official arrival prediction, so we build one from the two signals we
have. Three methods, tried in this order of preference and always recorded in
``BusArrival.method`` so the agent — and the person reading the answer — can tell which
one produced a number:

``stop_sequence``
    A bus reports the stop it is nearest to (``yakinDurakKodu``), which joins to GTFS
    ``stops.stop_code`` (verified 31/31 on line 500T). When that stop and the target both
    sit on the ordered stop list of the bus's route and the bus is *before* the target,
    the gap between their positions is how many stops away it is; multiply by a per-route
    seconds-per-stop figure. This one follows the road the bus really drives.

``distance``
    No usable stop order — unknown route, missing stop codes, or the bus is already past
    the target. Fall back to great-circle distance inflated by a road-winding factor and
    divided by an assumed city speed. It cannot see direction of travel, one-way streets
    or the Bosphorus, so it never earns better than 'medium'.

``schedule``
    No live bus is approaching at all. Fall back to the planned *departures* for today's
    day type: "there is a 500T booked for 14:40", not "a bus reaches your stop at 14:40".
    The gap between those is the run time from the terminus, which we do not know. 'low'.

Why no model: on day one there is no history to train on, and a wrong minute the user
cannot interrogate is worse than a rough minute they can. Instead every estimate is
logged to ``eta_log`` with the method and inputs behind it; the collector later marks the
vehicle's real arrival (that door number turning up with the target stop as its
``yakinDurakKodu``), turning the log into a measured ETA error — PLAN.md section 8.3. The
MAE that falls out of that is what should move the constants in :class:`EtaParams`, not
intuition. The ``diagnostics`` dict returned beside the arrivals is JSON-serialisable
precisely so it can be written to that log.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import asdict, dataclass, field
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

    ``seconds_per_stop`` is the day-one placeholder from PLAN.md section 7 (2 min/stop);
    once the collector has line×hour history, pass a per-route override through
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
    #: How far a bus may sit from the stop it calls ``yakinDurakKodu`` before we stop
    #: believing that claim locates it. See :func:`_claim_is_credible`.
    max_stop_claim_km: float = 1.5
    #: An average speed no İstanbul bus sustains. If a stop-sequence estimate implies more,
    #: ``seconds_per_stop`` is miscalibrated for that route; say so instead of hiding it.
    implausible_speed_kmh: float = 60.0
    #: How many planned departures to offer when falling back to the timetable.
    max_scheduled: int = 3


DEFAULT_PARAMS = EtaParams()


class GtfsLookup(Protocol):
    """The one hook this module needs from ``ibb_mcp.gtfs.GtfsIndex``.

    A protocol rather than an import, so the ETA maths can be unit-tested without loading
    15 000 stops and a change to the index's constructor cannot break it. Route stop
    orders are *not* fetched through here — ``gtfs.load_stop_sequences()`` returns them as
    a plain dict that the caller passes in as ``sequences``, which keeps this module
    working on the day those sequences are still empty for want of ``stop_times.csv``.
    """

    def lookup_stop(self, stop_code: str) -> Stop | None: ...


def _lookup_stop(index: GtfsLookup | None, stop_code: str | None) -> Stop | None:
    """Resolve a stop code through the index, tolerating either accessor it exposes."""
    if index is None or not stop_code:
        return None
    getter = getattr(index, "lookup_stop", None) or getattr(index, "stop_by_code", None)
    if callable(getter):
        return getter(stop_code)
    mapping = getattr(index, "by_stop_code", None)
    return mapping.get(stop_code) if isinstance(mapping, Mapping) else None


def _stop_positions(sequence: Any) -> dict[str, int]:
    """Map ``stop_code`` -> position along the route.

    On a loop route a stop appears twice; first occurrence wins, which keeps "stops away"
    positive for a bus approaching the first time and under-counts one on its second pass.
    Under-counting is the safer error: being wrong by a whole loop shows up loudly in
    ``eta_log`` instead of hiding as a plausible number.
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


@dataclass(frozen=True)
class _Ctx:
    """Everything the per-bus helpers need, so their signatures stay readable."""

    target: Stop
    index: GtfsLookup | None
    sequences: Mapping[str, Any] | None
    speed_profile: Mapping[str, float] | None
    params: EtaParams
    moment: dt.datetime
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def note(self, text: str) -> None:
        if text not in self.diagnostics["notes"]:
            self.diagnostics["notes"].append(text)

    def sequence_for(self, route_code: str | None) -> Any:
        """Ordered stop list for a route, or None while ``stop_times.csv`` is absent."""
        if not route_code or not self.sequences:
            return None
        return self.sequences.get(route_code) or self.sequences.get(route_code.upper())

    def seconds_per_stop(self, route_code: str | None) -> float:
        profile = self.speed_profile
        if profile and route_code and (value := float(profile.get(route_code) or 0)) > 0:
            return value
        return self.params.seconds_per_stop


def estimate_arrivals(
    *,
    buses: list[BusPosition],
    target: Stop,
    index: GtfsLookup | None = None,
    sequences: Mapping[str, Any] | None = None,
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
    invented: an empty list with populated diagnostics is a legitimate answer, one the
    agent should read out as "I cannot tell you right now".
    """
    ctx = _Ctx(
        target=target,
        index=index,
        sequences=sequences,
        speed_profile=speed_profile,
        params=params,
        moment=now or utcnow(),
        diagnostics={
            "now": (now or utcnow()).isoformat(),
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
        },
    )

    fresh = _drop_stale(buses, ctx)
    arrivals = [a for bus in fresh if (a := _estimate_one(bus, ctx)) is not None]
    if not arrivals:
        if fresh:
            ctx.note("live_buses_present_but_none_approaching")
        arrivals = _from_schedule(scheduled, ctx)

    for arrival in arrivals:
        ctx.diagnostics["methods"][arrival.method] = ctx.diagnostics["methods"].get(arrival.method, 0) + 1
    arrivals.sort(key=lambda a: (a.eta_minutes if a.eta_minutes is not None else 1e9, a.stops_away or 0))

    capped = arrivals[: max(1, params.max_results)]
    ctx.diagnostics["estimated"] = len(arrivals)
    ctx.diagnostics["returned"] = len(capped)
    return capped, ctx.diagnostics


def _drop_stale(buses: list[BusPosition], ctx: _Ctx) -> list[BusPosition]:
    """Discard positions older than ``max_bus_age_s``; record the ages of those we keep.

    A ten-minute-old position has moved several stops since; pretending otherwise is
    exactly the confident-but-wrong number this project refuses to emit. Positions with no
    timestamp are kept but counted, and their arrivals lose a notch of confidence later.
    """
    diagnostics, kept, ages = ctx.diagnostics, [], []
    for bus in buses:
        if bus.reported_at is None:
            diagnostics["unknown_age"] += 1
            kept.append(bus)
            continue
        age = (ctx.moment - bus.reported_at).total_seconds()
        if age > ctx.params.max_bus_age_s:
            diagnostics["dropped_stale"] += 1
            continue
        ages.append(max(0.0, age))
        kept.append(bus)
    if ages:
        diagnostics["oldest_used_age_s"] = round(max(ages), 1)
        diagnostics["median_age_s"] = round(statistics.median(ages), 1)
    if diagnostics["dropped_stale"]:
        ctx.note(f"dropped_{diagnostics['dropped_stale']}_positions_older_than_{ctx.params.max_bus_age_s:.0f}s")
    if diagnostics["unknown_age"]:
        ctx.note("positions_without_timestamp_were_downgraded")
    return kept


def _estimate_one(bus: BusPosition, ctx: _Ctx) -> BusArrival | None:
    """One bus, one stop: sequence method when the route order allows it, else distance."""
    positions = _stop_positions(ctx.sequence_for(bus.route_code))
    if positions and bus.route_code and bus.route_code not in ctx.diagnostics["sequence_routes"]:
        ctx.diagnostics["sequence_routes"].append(bus.route_code)

    target_index = positions.get(ctx.target.stop_code)
    bus_index = positions.get(bus.nearest_stop_code) if bus.nearest_stop_code else None
    if target_index is None or bus_index is None or not _claim_is_credible(bus, ctx):
        return _distance_arrival(bus, ctx)
    if bus_index > target_index:
        # Past the stop in this route direction; it is not coming back on this trip.
        ctx.diagnostics["dropped_passed_target"] += 1
        return None

    stops_away = target_index - bus_index
    if stops_away == 0:
        # "Zero stops away" carries no time information — the bus shares a nearest stop
        # with the rider, which on a line with 2 km spacing can still be a kilometre of
        # driving. Multiplying zero by anything says "0 dakika", the one answer guaranteed
        # to be wrong. Fall through to geometry, keeping the honest stops_away=0.
        near = _distance_arrival(bus, ctx)
        return near.model_copy(update={"stops_away": 0}) if near else None

    straight_km = _straight_km(bus.lat, bus.lon, ctx.target)
    minutes = stops_away * ctx.seconds_per_stop(bus.route_code) / 60.0
    confidence = "high" if stops_away <= ctx.params.high_confidence_stops else "medium"
    if not bus.reported_at:
        confidence = _downgrade(confidence)
    # Do not override the preferred method with a global speed guess — an express line's
    # seconds_per_stop is legitimately large. But if the estimate implies a speed no bus
    # sustains, the constant is wrong for this route: flag it so eval can retune it rather
    # than letting a confident, too-early number reach the rider.
    if straight_km and minutes > 0 and straight_km / (minutes / 60.0) > ctx.params.implausible_speed_kmh:
        confidence = _downgrade(confidence)
        ctx.note(f"seconds_per_stop_looks_low_for_{bus.route_code}")
    return _arrival(
        bus,
        ctx.target,
        stops_away=stops_away,
        distance_km=straight_km,
        eta_minutes=round(minutes, 1),
        method="stop_sequence",
        confidence=confidence,
    )


def _claim_is_credible(bus: BusPosition, ctx: _Ctx) -> bool:
    """Is the bus actually near the stop its ``yakinDurakKodu`` names?

    Measured on the recorded 500T snapshot: of five buses all reporting stop 225652
    (Kozyatağı Metro), two sat within a kilometre of it and three were 4.7-6.4 km past it,
    northbound. So the field is not "the stop I am nearest to" — it lags, holding the last
    stop the vehicle registered at. The code still joins cleanly to ``stops.stop_code``,
    but using a stale claim as a position puts the bus several stops behind where it is and
    quietly inflates every ETA on the line. When the vehicle's own coordinates contradict
    the claim by more than ``max_stop_claim_km``, we trust the coordinates and fall back to
    the distance method. Buses with no coordinates get the benefit of the doubt: the claim
    is then the only position we have.
    """
    if bus.lat is None or bus.lon is None:
        return True
    claimed = _lookup_stop(ctx.index, bus.nearest_stop_code)
    if claimed is None or claimed.lat is None or claimed.lon is None:
        return True
    if haversine_km(bus.lat, bus.lon, claimed.lat, claimed.lon) <= ctx.params.max_stop_claim_km:
        return True
    ctx.diagnostics["stop_claim_rejected"] = ctx.diagnostics.get("stop_claim_rejected", 0) + 1
    ctx.note("stale_yakinDurakKodu_ignored_bus_position_used_instead")
    return False


def _distance_arrival(bus: BusPosition, ctx: _Ctx) -> BusArrival | None:
    """Great-circle distance × winding factor ÷ assumed speed.

    Blind to direction of travel: a bus 2 km away driving the other way scores the same as
    one about to arrive. Hence the 'medium' ceiling and the diagnostics note — the agent
    should hedge the wording, not bend the number.
    """
    target, params = ctx.target, ctx.params
    lat, lon = bus.lat, bus.lon
    if lat is None or lon is None:
        # Last resort: stand the bus at the stop it says it is nearest to.
        proxy = _lookup_stop(ctx.index, bus.nearest_stop_code)
        lat, lon = (proxy.lat, proxy.lon) if proxy else (None, None)
    if lat is None or lon is None or target.lat is None or target.lon is None:
        ctx.diagnostics["dropped_unlocatable"] += 1
        return None

    straight_km = haversine_km(lat, lon, target.lat, target.lon)
    road_km = straight_km * params.winding_factor
    speed = params.speed_kmh if params.speed_kmh > 0 else DEFAULT_SPEED_KMH
    confidence = "low" if road_km > params.low_confidence_km else "medium"
    ctx.note("distance_method_is_direction_blind")
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


def _from_schedule(scheduled: list[PlannedDeparture] | None, ctx: _Ctx) -> list[BusArrival]:
    """Next planned departures for today's day type, when no live bus is approaching.

    ``eta_minutes`` counts to the *departure from the terminus*, not to arrival at the
    target; without ``stop_times.csv`` we cannot add the run time, so the honest move is
    to label the method 'schedule' and let the agent word it as a planned departure.
    """
    if not scheduled:
        ctx.note("no_schedule_fallback_available")
        return []

    today_code = day_type_for(ctx.moment)
    ctx.diagnostics["schedule_day_type"] = today_code
    todays = [d for d in scheduled if d.day_type == today_code and d.departure_time]
    if not todays:
        # Never silently borrow another day's timetable: Sunday headways are not Tuesday's.
        ctx.note(f"schedule_has_no_rows_for_day_type_{today_code}")
        return []

    local_now = ctx.moment.astimezone(ISTANBUL_TZ)
    upcoming = _upcoming_departures(todays, local_now)
    if not upcoming:
        tomorrow = (local_now + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        rows = [d for d in scheduled if d.day_type == day_type_for(tomorrow) and d.departure_time]
        upcoming = _upcoming_departures(rows, tomorrow)
        if upcoming:
            ctx.note("service_finished_today_showing_first_departures_of_next_day")

    arrivals = [
        BusArrival(
            line_code=departure.line_code,
            stop_code=ctx.target.stop_code,
            stop_name=ctx.target.name,
            door_no=NO_VEHICLE,
            direction=departure.direction,
            eta_minutes=round((when - local_now).total_seconds() / 60.0, 1),
            method="schedule",
            confidence="low",
        )
        for when, departure in upcoming[: max(1, ctx.params.max_scheduled)]
    ]
    if arrivals:
        ctx.note("eta_is_time_until_planned_departure_not_arrival_at_stop")
    return arrivals


def _upcoming_departures(rows: list[PlannedDeparture], after: dt.datetime) -> list[tuple[dt.datetime, PlannedDeparture]]:
    """Resolve ``HH:MM`` strings against ``after``'s date, keeping only later departures."""
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
    """İETT writes post-midnight runs as hours >= 24 ("24:30"), which roll into the next day."""
    if not clock:
        return None
    parts = clock.strip().split(":")
    if len(parts) < 2 or not all(p.strip().isdigit() for p in parts[:2]):
        return None
    hour, minute = int(parts[0]), int(parts[1])
    if minute > 59:
        return None
    day_offset, hour = divmod(hour, 24)
    return reference.replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(
        days=day_offset, hours=hour, minutes=minute
    )
