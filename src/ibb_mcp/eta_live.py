"""The live half of the ETA estimate: fresh vehicle positions to per-bus arrivals.

Two methods, ``stop_sequence`` and ``distance`` (their trade-offs are in the docstring of
:mod:`ibb_mcp.eta`). The orchestration and the timetable fallback live elsewhere; this
module never reads a clock — every age is measured against ``ctx.moment``.
"""

from __future__ import annotations

import statistics
from typing import Any

from ibb_mcp.eta_context import (
    DEFAULT_SPEED_KMH,
    EtaContext,
    cap_confidence,
    downgrade_confidence,
    resolve_stop,
    stop_positions,
)
from ibb_mcp.eta_profile import confidence_ceiling
from ibb_mcp.models import BusArrival, BusPosition, Stop, haversine_km


def drop_stale_positions(buses: list[BusPosition], ctx: EtaContext) -> list[BusPosition]:
    """Discard positions older than ``max_bus_age_s``; record the ages of those we keep.

    A ten-minute-old position has moved several stops since; pretending otherwise is
    exactly the confident-but-wrong number this project refuses to emit. Positions with no
    timestamp are kept but counted, and their arrivals lose a notch of confidence later.

    A timestamp in the *future* is the same problem in disguise: İETT stamps the fleet feed
    with a bare clock ("09:08:55") that ``parse_ibb_datetime`` must date to today in
    Istanbul, so a reading taken at 23:59 and fetched a minute after midnight lands almost
    a full day ahead. Clamping that age to zero would let a day-old position through as the
    freshest thing on the line, so the timestamp is discarded and the bus is treated as
    having none at all — kept, counted, downgraded.
    """
    diagnostics, kept, ages = ctx.diagnostics, [], []
    for bus in buses:
        if bus.reported_at is None:
            diagnostics["unknown_age"] += 1
            kept.append(bus)
            continue
        age = (ctx.moment - bus.reported_at).total_seconds()
        if age < -ctx.params.max_bus_age_s:
            diagnostics["future_dated"] = diagnostics.get("future_dated", 0) + 1
            diagnostics["unknown_age"] += 1
            kept.append(bus.model_copy(update={"reported_at": None}))
            continue
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
    if diagnostics.get("future_dated"):
        ctx.note(f"{diagnostics['future_dated']}_positions_dated_in_the_future_timestamp_discarded")
    if diagnostics["unknown_age"]:
        ctx.note("positions_without_timestamp_were_downgraded")
    return kept


def split_fresh_arrivals(arrivals: list[BusArrival], ctx: EtaContext) -> list[BusArrival]:
    """Remove live estimates whose source age exceeds the rider-facing stale limit."""
    fresh: list[BusArrival] = []
    ages: list[float] = []
    stale_live: list[dict[str, Any]] = []
    for arrival in arrivals:
        age = max(0.0, (ctx.moment - arrival.reported_at).total_seconds()) if arrival.reported_at is not None else None
        if age is None or age > ctx.params.stale_after_s:
            stale_live.append(
                {
                    "door_no": arrival.door_no,
                    "age_s": round(age, 1) if age is not None else None,
                    "method": arrival.method,
                    "eta_minutes": arrival.eta_minutes,
                    "stops_away": arrival.stops_away,
                }
            )
            continue
        fresh.append(arrival)
        ages.append(age)

    ctx.diagnostics["stale_live"] = stale_live
    if ages:
        ctx.diagnostics["freshest_live_age_s"] = round(min(ages), 1)
    if stale_live:
        ctx.note("live_estimate_exceeded_stale_limit_or_had_unknown_age")
    return fresh


def estimate_live_arrival(bus: BusPosition, ctx: EtaContext) -> BusArrival | None:
    """One bus, one stop: sequence method when the route order allows it, else distance."""
    positions = stop_positions(ctx.sequence_for(bus.route_code))
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
        confidence = downgrade_confidence(confidence)
    # Do not override the preferred method with a global speed guess — an express line's
    # seconds_per_stop is legitimately large. But if the estimate implies a speed no bus
    # sustains, the constant is wrong for this route: flag it so eval can retune it rather
    # than letting a confident, too-early number reach the rider.
    if straight_km and minutes > 0 and straight_km / (minutes / 60.0) > ctx.params.implausible_speed_kmh:
        confidence = downgrade_confidence(confidence)
        ctx.note(f"seconds_per_stop_looks_low_for_{bus.route_code}")
    confidence = cap_confidence(confidence, confidence_ceiling("stop_sequence"))
    return _arrival(
        bus,
        ctx.target,
        stops_away=stops_away,
        distance_km=straight_km,
        eta_minutes=round(minutes, 1),
        method="stop_sequence",
        confidence=confidence,
    )


def _claim_is_credible(bus: BusPosition, ctx: EtaContext) -> bool:
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
    claimed = resolve_stop(ctx.index, bus.nearest_stop_code)
    if claimed is None or claimed.lat is None or claimed.lon is None:
        return True
    if haversine_km(bus.lat, bus.lon, claimed.lat, claimed.lon) <= ctx.params.max_stop_claim_km:
        return True
    ctx.diagnostics["stop_claim_rejected"] = ctx.diagnostics.get("stop_claim_rejected", 0) + 1
    ctx.note("stale_yakinDurakKodu_ignored_bus_position_used_instead")
    return False


def _distance_arrival(bus: BusPosition, ctx: EtaContext) -> BusArrival | None:
    """Great-circle distance × winding factor ÷ assumed speed.

    Blind to direction of travel: a bus 2 km away driving the other way scores the same as
    one about to arrive. The method's measured ceiling caps its confidence, and the
    diagnostics note lets the agent hedge the wording without bending the number.
    """
    target, params = ctx.target, ctx.params
    lat, lon = bus.lat, bus.lon
    borrowed = False
    if lat is None or lon is None:
        # Last resort: stand the bus at the stop it says it is nearest to. On the recorded
        # 500T snapshot that claim was up to 6.4 km out (see :func:`_claim_is_credible`),
        # so a position borrowed this way costs a notch of confidence.
        proxy = resolve_stop(ctx.index, bus.nearest_stop_code)
        lat, lon = (proxy.lat, proxy.lon) if proxy else (None, None)
        borrowed = lat is not None and lon is not None
    if lat is None or lon is None or target.lat is None or target.lon is None:
        ctx.diagnostics["dropped_unlocatable"] += 1
        return None

    straight_km = haversine_km(lat, lon, target.lat, target.lon)
    road_km = straight_km * params.winding_factor
    speed = params.speed_kmh if params.speed_kmh > 0 else DEFAULT_SPEED_KMH
    confidence = "low" if road_km > params.low_confidence_km else "medium"
    ctx.note("distance_method_is_direction_blind")
    if borrowed:
        ctx.diagnostics["position_from_claimed_stop"] = ctx.diagnostics.get("position_from_claimed_stop", 0) + 1
        ctx.note("position_borrowed_from_yakinDurakKodu_not_the_vehicle")
        confidence = downgrade_confidence(confidence)
    if not bus.reported_at:
        confidence = downgrade_confidence(confidence)
    confidence = cap_confidence(confidence, confidence_ceiling("distance"))
    return _arrival(
        bus,
        target,
        stops_away=None,
        distance_km=round(straight_km, 2),
        eta_minutes=round(road_km / speed * 60.0, 1),
        method="distance",
        confidence=confidence,
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
