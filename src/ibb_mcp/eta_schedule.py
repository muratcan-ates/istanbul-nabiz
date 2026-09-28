"""The timetable half of the ETA estimate: what to say when no live bus is approaching.

Two sources, tried in this order by :func:`ibb_mcp.eta.estimate_arrivals`: GTFS terminal
departures on a route that serves the target stop (:func:`timetable_arrivals`), then İETT's
planned departures (:func:`planned_arrivals`). Both are 'schedule' method, low confidence,
and count to the departure from the terminus, not to arrival at the stop.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

from ibb_mcp.eta_context import NO_VEHICLE, EtaContext, stop_positions
from ibb_mcp.models import ISTANBUL_TZ, BusArrival, PlannedDeparture, day_type_for


def timetable_arrivals(
    ctx: EtaContext,
    line_code: str,
    timetable: Mapping[str, Sequence[Any]] | None,
    service_days: Mapping[str, frozenset[str]] | None,
) -> list[BusArrival]:
    """Select upcoming terminal departures for the target's route and service day."""
    calendar_available = bool(service_days)
    ctx.diagnostics["schedule_day_filter"] = "calendar" if calendar_available else "none"
    if not calendar_available:
        ctx.note("schedule_day_filter_none_calendar_missing")
    if not timetable:
        ctx.note("no_gtfs_timetable_available")
        return []

    wanted_line = line_code.upper()
    route_codes = [
        code
        for code in timetable
        if code.upper().split("_", 1)[0] == wanted_line and ctx.target.stop_code in stop_positions(ctx.sequence_for(code))
    ]
    if not route_codes:
        ctx.note("no_gtfs_timetable_for_line_and_target_stop")
        return []

    local_now = ctx.moment.astimezone(ISTANBUL_TZ)
    today = day_type_for(local_now)
    upcoming = _upcoming_timetable(ctx, route_codes, timetable, service_days, today, local_now)
    if not upcoming:
        tomorrow = (local_now + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_type = day_type_for(tomorrow)
        upcoming = _upcoming_timetable(ctx, route_codes, timetable, service_days, tomorrow_type, tomorrow)
        ctx.note(
            "service_finished_today_showing_first_gtfs_departures_of_next_day"
            if upcoming
            else "gtfs_timetable_exhausted_for_today_and_next_day"
        )

    arrivals: list[BusArrival] = []
    scheduled_trips: list[dict[str, Any]] = []
    for when, trip, stop_position in upcoming[: max(1, ctx.params.max_scheduled)]:
        arrivals.append(
            BusArrival(
                line_code=line_code,
                stop_code=ctx.target.stop_code,
                stop_name=ctx.target.name,
                door_no=NO_VEHICLE,
                direction=trip.headsign,
                eta_minutes=round((when - local_now).total_seconds() / 60.0, 1),
                method="schedule",
                confidence="low",
            )
        )
        scheduled_trips.append(
            {
                "trip_id": trip.trip_id,
                "route_code": trip.route_code,
                "service_id": trip.service_id,
                "headsign": trip.headsign,
                "terminus_departure": trip.departure_time,
                "terminus_arrival": trip.arrival_time,
                "stop_position": stop_position,
                "stop_count": trip.stop_count,
            }
        )
    ctx.diagnostics["scheduled_trips"] = scheduled_trips
    if arrivals:
        ctx.note("eta_is_time_until_planned_terminal_departure_not_arrival_at_stop")
    return arrivals


def _upcoming_timetable(
    ctx: EtaContext,
    route_codes: Sequence[str],
    timetable: Mapping[str, Sequence[Any]],
    service_days: Mapping[str, frozenset[str]] | None,
    day_code: str,
    after: dt.datetime,
) -> list[tuple[dt.datetime, Any, int]]:
    """Resolve applicable timetable rows after a local clock moment."""
    resolved: list[tuple[dt.datetime, Any, int]] = []
    for route_code in route_codes:
        stop_position = stop_positions(ctx.sequence_for(route_code)).get(ctx.target.stop_code, 0)
        for trip in timetable[route_code]:
            if service_days and trip.service_id and day_code not in service_days.get(trip.service_id, frozenset()):
                continue
            when = resolve_clock(trip.departure_time, after)
            if when is not None and when >= after:
                resolved.append((when, trip, stop_position))
    resolved.sort(key=lambda item: (item[0], item[1].route_code, item[1].trip_id))
    return resolved


def planned_arrivals(scheduled: list[PlannedDeparture] | None, ctx: EtaContext) -> list[BusArrival]:
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
        ctx.note(
            "service_finished_today_showing_first_departures_of_next_day"
            if upcoming
            else f"schedule_exhausted_no_rows_for_day_type_{day_type_for(tomorrow)}"
        )

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
    if len({a.direction for a in arrivals if a.direction}) > 1:
        # Both directions of the line depart from their own terminus; without stop_times we
        # cannot tell which one passes the rider's stop, so say so rather than pick one.
        ctx.note("schedule_rows_cover_both_directions_not_filtered_to_this_stop")
    return arrivals


def _upcoming_departures(rows: list[PlannedDeparture], after: dt.datetime) -> list[tuple[dt.datetime, PlannedDeparture]]:
    """Resolve ``HH:MM`` strings against ``after``'s date, keeping only later departures."""
    resolved: list[tuple[dt.datetime, PlannedDeparture]] = []
    seen: set[str] = set()
    for row in rows:
        when = resolve_clock(row.departure_time, after)
        key = f"{row.route_code}|{row.departure_time}"
        if when is None or when < after or key in seen:
            continue
        seen.add(key)
        resolved.append((when, row))
    resolved.sort(key=lambda pair: pair[0])
    return resolved


def resolve_clock(clock: str | None, reference: dt.datetime) -> dt.datetime | None:
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


def planned_summary(departures: Sequence[PlannedDeparture], day_type: str) -> dict[str, Any]:
    """Summarise the first and last published departures for one İETT service day."""
    reference = dt.datetime(2000, 1, 1, tzinfo=ISTANBUL_TZ)
    ordered = [
        (when, departure)
        for departure in departures
        if departure.day_type == day_type
        and departure.departure_time
        and (when := resolve_clock(departure.departure_time, reference)) is not None
    ]
    ordered.sort(key=lambda pair: pair[0])
    return {
        "day_type": day_type,
        "first_departure": ordered[0][1].departure_time if ordered else None,
        "last_departure": ordered[-1][1].departure_time if ordered else None,
        "count": len(ordered),
    }
