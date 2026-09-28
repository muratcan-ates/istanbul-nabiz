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
    or the Bosphorus, so its confidence is limited by the measured method ceiling.

``schedule``
    No fresh live estimate exists. Prefer a GTFS terminal departure on a route that serves
    the target stop, then fall back to İETT's planned departures. Both are low confidence.

Fallback chain:
fresh live position -> live estimate
stale or unavailable live estimate -> matching GTFS terminal departure
no matching GTFS trip -> İETT planned departure
no usable source -> unknown

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
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any

# The public vocabulary stays importable from here (ENGINEERING §13, MOD-7: paths kept by re-export).
from ibb_mcp.eta_context import (  # noqa: F401 - re-exported public API
    DEFAULT_PARAMS,
    DEFAULT_SPEED_KMH,
    MODE_LIVE,
    MODE_SCHEDULE,
    MODE_UNKNOWN,
    NO_VEHICLE,
    SCHEDULE_GTFS,
    SCHEDULE_IETT,
    EtaContext,
    EtaParams,
    GtfsLookup,
    as_aware,
)
from ibb_mcp.eta_live import drop_stale_positions, estimate_live_arrival, split_fresh_arrivals
from ibb_mcp.eta_profile import confidence_basis_tr, confidence_ceiling
from ibb_mcp.eta_schedule import planned_arrivals, planned_summary, timetable_arrivals  # noqa: F401 - planned_summary re-exported
from ibb_mcp.models import BusArrival, BusPosition, PlannedDeparture, Stop, utcnow


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


def estimate_arrivals(  # noqa: PLR0913 - debt, ratcheted in scripts/architecture_baseline.json
    *,
    buses: list[BusPosition],
    target: Stop,
    index: GtfsLookup | None = None,
    sequences: Mapping[str, Any] | None = None,
    scheduled: list[PlannedDeparture] | None = None,
    speed_profile: Mapping[str, float] | None = None,
    line_code: str | None = None,
    timetable: Mapping[str, Sequence[Any]] | None = None,
    service_days: Mapping[str, frozenset[str]] | None = None,
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
    # One clock read: the moment written to eta_log must be the moment the maths used.
    moment = as_aware(now) if now is not None else utcnow()
    ctx = EtaContext(
        target=target,
        index=index,
        sequences=sequences,
        speed_profile=speed_profile,
        params=params,
        moment=moment,
        diagnostics=_fresh_diagnostics(target, buses, params, moment),
    )

    fresh = drop_stale_positions(buses, ctx)
    arrivals = [a for bus in fresh if (a := estimate_live_arrival(bus, ctx)) is not None]
    arrivals = split_fresh_arrivals(arrivals, ctx)
    if arrivals:
        ctx.diagnostics["mode"] = MODE_LIVE
    else:
        if fresh:
            ctx.note("live_buses_present_but_none_approaching")
        resolved_line_code = line_code or next((bus.line_code for bus in buses if bus.line_code), None)
        gtfs_arrivals = timetable_arrivals(ctx, resolved_line_code, timetable, service_days) if resolved_line_code else []
        if not resolved_line_code:
            ctx.note("timetable_needs_line_code")
        if gtfs_arrivals:
            arrivals = gtfs_arrivals
            ctx.diagnostics["mode"] = MODE_SCHEDULE
            ctx.diagnostics["schedule_source"] = SCHEDULE_GTFS
        else:
            arrivals = planned_arrivals(scheduled, ctx)
            if arrivals:
                ctx.diagnostics["mode"] = MODE_SCHEDULE
                ctx.diagnostics["schedule_source"] = SCHEDULE_IETT
            else:
                ctx.diagnostics["mode"] = MODE_UNKNOWN

    arrivals.sort(key=lambda a: (a.eta_minutes if a.eta_minutes is not None else 1e9, a.stops_away or 0))

    capped = arrivals[: max(1, params.max_results)]
    for arrival in capped:
        ctx.diagnostics["methods"][arrival.method] = ctx.diagnostics["methods"].get(arrival.method, 0) + 1
    ctx.diagnostics["estimated"] = len(arrivals)
    ctx.diagnostics["returned"] = len(capped)
    return capped, ctx.diagnostics


def _fresh_diagnostics(target: Stop, buses: list[BusPosition], params: EtaParams, moment: dt.datetime) -> dict[str, Any]:
    """The diagnostics skeleton every estimate starts from; key order is what eta_log readers expect."""
    return {
        "now": moment.isoformat(),
        "target_stop_code": target.stop_code,
        "buses_received": len(buses),
        "dropped_stale": 0,
        "dropped_unlocatable": 0,
        "dropped_passed_target": 0,
        "unknown_age": 0,
        "methods": {"stop_sequence": 0, "distance": 0, "schedule": 0},
        "mode": MODE_UNKNOWN,
        "stale_after_s": params.stale_after_s,
        "freshest_live_age_s": None,
        "stale_live": [],
        "schedule_source": None,
        "schedule_day_filter": "none",
        "scheduled_trips": [],
        "confidence_ceiling": {
            "stop_sequence": confidence_ceiling("stop_sequence"),
            "distance": confidence_ceiling("distance"),
            "schedule": "low",
        },
        "confidence_basis": {method: confidence_basis_tr(method) for method in ("stop_sequence", "distance", "schedule")},
        "sequence_routes": [],
        "notes": [],
        "params": asdict(params),
    }
