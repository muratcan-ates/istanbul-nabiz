"""A step-free rail journey joined to Metro İstanbul's lift fault record.

The graph estimates walking and rail legs, not a timetable. Missing fault records do not prove a
lift works. This module has no NEXUS binding, so it cannot assert operator approval.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from ibb_mcp import accessibility
from ibb_mcp.http import RateLimitExceeded, UpstreamUnavailable
from ibb_mcp.metro_graph import MARMARAY_LINE, PATH_FAILURE_REASONS, MetroGraph, MetroLeg, MetroPath, marmaray_tube
from ibb_mcp.models import MetroStation, Provenance, haversine_km
from ibb_mcp.routing import Waypoint
from ibb_mcp.sources.metro_equipment import EquipmentSnapshot
from ibb_mcp.text import fold_tr
from ibb_mcp.tools import Nabiz

DISCLAIMER_TR = (
    "Bu bir tahmindir, adım adım yol tarifi değildir. Süreler istasyon mesafesi modeline dayanır ve tarife içermez. "
    "Asansör bilgisi İBB'nin arıza kaydına dayanır."
)

_PATH_REASONS_TR = {
    "unknown_origin": "Başlangıç yeri metro istasyonlarıyla eşleşmedi.",
    "unknown_destination": "Varış yeri metro istasyonlarıyla eşleşmedi.",
    "no_station_near_origin": "Başlangıç noktasının yakınında metro istasyonu bulunamadı.",
    "no_station_near_destination": "Varış noktasının yakınında metro istasyonu bulunamadı.",
    "disconnected": "Bu iki nokta arasında doğrulanabilir bir raylı sistem bağlantısı bulunamadı.",
}


@dataclass(frozen=True)
class JourneyResult:
    """A response body and the source stamp used by the console view."""

    data: dict[str, Any]
    provenance: Provenance | None


def _maps_links(lat: float, lon: float, label: str) -> dict[str, str]:
    """Create walking links containing only the destination coordinate and public label."""
    destination = f"{lat:.6f},{lon:.6f}"
    apple = urlencode({"daddr": destination, "dirflg": "w", "q": label})
    google = urlencode({"api": "1", "destination": destination, "travelmode": "walking"})
    return {"apple": f"https://maps.apple.com/?{apple}", "google": f"https://www.google.com/maps/dir/?{google}"}


def _endpoint(nabiz: Nabiz, value: str | tuple[float, float], *, role: str) -> Waypoint:
    if isinstance(value, str):
        return nabiz._endpoint(value, None, None, role=role)
    if isinstance(value, tuple) and len(value) == 2:
        return nabiz._endpoint(None, float(value[0]), float(value[1]), role=role)
    raise ValueError(f"{role} için bir yer adı ya da (enlem, boylam) çifti verin.")


def _failure(
    origin: str,
    destination: str,
    needs: Sequence[str],
    reason: str,
    uncertainty: Sequence[str] = (),
    provenance: Provenance | None = None,
) -> JourneyResult:
    return JourneyResult(
        {
            "available": False,
            "from": origin,
            "to": destination,
            "needs": list(needs),
            "steps": [],
            "extra_minutes": None,
            "alternative_used": None,
            "operator_approved": False,
            "reason": reason,
            "provenance": None,
            "uncertainty": list(dict.fromkeys(uncertainty)),
            "disclaimer": DISCLAIMER_TR,
        },
        provenance,
    )


def _station_names(path: MetroPath) -> list[str]:
    names: dict[str, str] = {}
    for leg in path.legs:
        if leg.kind in {"ride", "transfer", "walk"}:
            for name in (leg.from_station, leg.to_station):
                if name:
                    names.setdefault(fold_tr(name), name)
    return list(names.values())


def _lift_states(
    names: Sequence[str], stations: Sequence[MetroStation], snapshot: EquipmentSnapshot
) -> dict[str, accessibility.LiftState]:
    faults = accessibility.faults_by_platform(snapshot.records, stations)
    states: dict[str, accessibility.LiftState] = {}
    for name in names:
        platforms = accessibility.resolve_platforms(name, stations)
        state = accessibility.lift_state(name, platforms, faults) if platforms else accessibility.unreadable_state(name)
        states[fold_tr(name)] = state
    return states


def _connected_transfer(
    station_name: str,
    arriving_line: str | None,
    leaving_line: str | None,
    stations: Sequence[MetroStation],
    graph: MetroGraph,
) -> MetroLeg | None:
    if not arriving_line or not leaving_line or fold_tr(arriving_line) == fold_tr(leaving_line):
        return None
    platforms = accessibility.resolve_platforms(station_name, stations)
    arrivals = [p for p in platforms if fold_tr(p.line_name or "") == fold_tr(arriving_line)]
    departures = [p for p in platforms if fold_tr(p.line_name or "") == fold_tr(leaving_line)]
    distances = [
        haversine_km(a.lat or 0.0, a.lon or 0.0, b.lat or 0.0, b.lon or 0.0)
        for a in arrivals
        for b in departures
        if a.lat is not None and a.lon is not None and b.lat is not None and b.lon is not None
    ]
    if not distances:
        return None
    distance = min(distances)
    params = graph.params
    if distance <= params.in_station_transfer_km:
        kind, seconds = "transfer", params.transfer_seconds
    elif distance <= params.max_named_walk_km:
        kind = "walk"
        seconds = params.transfer_seconds + distance / params.walk_speed_kmh * 3600.0
    else:
        return None
    return MetroLeg(kind, leaving_line, station_name, station_name, 0, round(seconds, 1), round(distance, 3))


def _rebuild_path(
    original: MetroPath,
    first: MetroPath,
    second: MetroPath,
    station_name: str,
    stations: Sequence[MetroStation],
    graph: MetroGraph,
) -> MetroPath | None:
    access = next((leg for leg in original.legs if leg.kind == "access"), None)
    egress = next((leg for leg in reversed(original.legs) if leg.kind == "egress"), None)
    if access is None or egress is None:
        return None
    middle = list(first.legs)
    first_ride = next((leg for leg in second.legs if leg.kind == "ride"), None)
    last_line = next((leg.line for leg in reversed(middle) if leg.line), None)
    if first_ride is not None and last_line and last_line != first_ride.line:
        transfer = _connected_transfer(station_name, last_line, first_ride.line, stations, graph)
        if transfer is None:
            return None
        middle.append(transfer)
    middle.extend(second.legs)
    legs = (access, *middle, egress)
    wait_seconds = original.wait_seconds
    return MetroPath(
        legs=legs,
        total_seconds=round(sum(leg.seconds for leg in legs) + wait_seconds, 1),
        ride_seconds=round(sum(leg.seconds for leg in legs if leg.kind == "ride"), 1),
        wait_seconds=wait_seconds,
        transfer_count=sum(1 for leg in legs if leg.kind in {"transfer", "walk"}),
        lines=tuple(dict.fromkeys(leg.line for leg in legs if leg.line)),
        stop_count=sum(leg.stops for leg in legs),
    )


def _route_via_alternative(
    graph: MetroGraph,
    path: MetroPath,
    alternative: dict[str, Any],
    avoided_station: str,
    stations: Sequence[MetroStation],
) -> MetroPath | None:
    access = next((leg for leg in path.legs if leg.kind == "access"), None)
    egress = next((leg for leg in reversed(path.legs) if leg.kind == "egress"), None)
    if access is None or egress is None:
        return None
    via = str(alternative.get("station") or "")
    if not via:
        return None
    first = graph.path_between_stations(access.to_station, via).path
    second = graph.path_between_stations(via, egress.from_station).path
    if first is None or second is None:
        return None
    rebuilt = _rebuild_path(path, first, second, via, stations, graph)
    if rebuilt is None:
        return None
    avoided = fold_tr(avoided_station)
    if any(avoided in {fold_tr(leg.from_station), fold_tr(leg.to_station)} for leg in rebuilt.legs):
        return None
    return rebuilt


def _map_for_station(name: str, stations: Sequence[MetroStation]) -> dict[str, str] | None:
    for station in accessibility.resolve_platforms(name, stations):
        if station.lat is not None and station.lon is not None:
            return _maps_links(station.lat, station.lon, name)
    return None


def _steps(
    path: MetroPath,
    states: dict[str, accessibility.LiftState],
    stations: Sequence[MetroStation],
    destination: Waypoint,
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for leg in path.legs:
        if leg.kind == "access":
            steps.append(
                {
                    "kind": "walk",
                    "description": f"{leg.to_station} istasyonuna yürüyüş",
                    "minutes": math.ceil(leg.seconds / 60),
                    "map_links": _map_for_station(leg.to_station, stations),
                }
            )
        elif leg.kind == "ride":
            start = states.get(fold_tr(leg.from_station), accessibility.unreadable_state(leg.from_station))
            end = states.get(fold_tr(leg.to_station), accessibility.unreadable_state(leg.to_station))
            steps.append(
                {
                    "kind": "ride",
                    "line": leg.line,
                    "from_station": leg.from_station,
                    "to_station": leg.to_station,
                    "minutes": math.ceil(leg.seconds / 60),
                    "lift_status": end.lift_status,
                    "stations": [
                        {"name": leg.from_station, "lift_status": start.lift_status, "text": start.text},
                        {"name": leg.to_station, "lift_status": end.lift_status, "text": end.text},
                    ],
                }
            )
        elif leg.kind == "walk":
            state = states.get(fold_tr(leg.to_station), accessibility.unreadable_state(leg.to_station))
            steps.append(
                {
                    "kind": "walk",
                    "description": f"{leg.from_station} ile {leg.to_station} arasında yürüme",
                    "minutes": math.ceil(leg.seconds / 60),
                    "lift_status": state.lift_status,
                    "map_links": _map_for_station(leg.to_station, stations),
                }
            )
        elif leg.kind == "transfer":
            state = states.get(fold_tr(leg.to_station), accessibility.unreadable_state(leg.to_station))
            steps.append(
                {
                    "kind": "transfer",
                    "at_station": leg.to_station,
                    "line": leg.line,
                    "minutes": math.ceil(leg.seconds / 60),
                    "lift_status": state.lift_status,
                    "note": state.text,
                }
            )
        elif leg.kind == "egress":
            steps.append(
                {
                    "kind": "walk",
                    "description": f"{leg.from_station} istasyonundan {destination.name} noktasına yürüyüş",
                    "minutes": math.ceil(leg.seconds / 60),
                    "map_links": _maps_links(destination.lat, destination.lon, destination.name),
                }
            )
    return steps


async def _read_sources(
    nabiz: Nabiz, start: Waypoint, end: Waypoint, needs: Sequence[str]
) -> tuple[list[MetroStation], EquipmentSnapshot, Provenance, list[str]] | JourneyResult:
    metro = nabiz._source("metro")
    equipment = nabiz._source("metro_equipment")
    try:
        stations, station_provenance = await metro.stations()
    except (RateLimitExceeded, UpstreamUnavailable):
        return _failure(start.name, end.name, needs, "Metro istasyon verisi okunamadı; yolculuk doğrulanamadı.",
                        ("station_data_unavailable",))
    try:
        snapshot, provenance = await equipment.snapshot(("Asansör",))
    except (RateLimitExceeded, UpstreamUnavailable):
        return _failure(start.name, end.name, needs, "Asansör verisi okunamadı; erişilebilirlik doğrulanamadı.",
                        (accessibility.EQUIPMENT_DATA_UNAVAILABLE,))
    uncertainty = list(snapshot.uncertainty)
    if station_provenance.cached:
        uncertainty.append("station_data_cached")
    if accessibility.is_stale(provenance, offline=nabiz.settings.offline):
        uncertainty.append(accessibility.STALE_DATA)
    if not accessibility.lifts_readable(snapshot):
        uncertainty.extend((accessibility.EQUIPMENT_DATA_UNAVAILABLE, *snapshot.uncertainty))
        return _failure(start.name, end.name, needs, "Asansör verisi okunamadı; erişilebilirlik doğrulanamadı.",
                        uncertainty, provenance if snapshot.available else None)
    return stations, snapshot, provenance, uncertainty


def _finish_route(
    graph: MetroGraph,
    path: MetroPath,
    stations: Sequence[MetroStation],
    snapshot: EquipmentSnapshot,
    provenance: Provenance,
    uncertainty: Sequence[str],
    request: tuple[Waypoint, Waypoint, Sequence[str]],
) -> JourneyResult:
    start, end, needs = request
    original_seconds = path.total_seconds
    alternatives: list[dict[str, Any]] = []
    reported_uncertainty = list(uncertainty)
    for _ in range(len(stations) + 1):
        names = _station_names(path)
        states = _lift_states(names, stations, snapshot)
        blocked = next(
            ((name, states[fold_tr(name)]) for name in names if states[fold_tr(name)].lift_status != "working"),
            None,
        )
        if blocked is None:
            break
        station_name, state = blocked
        reported_uncertainty.extend(state.codes)
        answer = accessibility.accessible_alternative(
            station_name, needs, stations=stations, snapshot=snapshot, graph=graph
        )
        candidate = answer.get("alternative")
        detour = _route_via_alternative(graph, path, candidate or {}, station_name, stations) if candidate else None
        if detour is None:
            codes = [*reported_uncertainty, *answer.get("uncertainty", []), accessibility.NO_ALTERNATIVE]
            return _failure(
                start.name,
                end.name,
                needs,
                f"{station_name} istasyonundaki asansör durumu doğrulanamadı ve bu istasyonu atlayan bir alternatif bulunamadı.",
                codes,
                provenance,
            )
        path = detour
        alternatives.append({
            "station": candidate["station"], "line": candidate["line"],
            "avoided_station": station_name, "reason": candidate["reason"],
        })
    else:
        return _failure(start.name, end.name, needs, "Güzergâhtaki asansör durumları doğrulanamadı.",
                        [*uncertainty, accessibility.NO_ALTERNATIVE], provenance)

    names = _station_names(path)
    states = _lift_states(names, stations, snapshot)
    if any(state.lift_status != "working" for state in states.values()):
        return _failure(start.name, end.name, needs, "Güzergâhtaki asansör durumları doğrulanamadı.",
                        [*uncertainty, accessibility.NO_ALTERNATIVE], provenance)
    extra = max(0, math.ceil((path.total_seconds - original_seconds) / 60))
    data = {
        "available": True, "from": start.name, "to": end.name, "needs": list(needs),
        "steps": _steps(path, states, stations, end), "extra_minutes": extra,
        "alternative_used": alternatives[0] if alternatives else None, "alternatives_used": alternatives,
        "operator_approved": False, "provenance": None,
        "uncertainty": list(dict.fromkeys(reported_uncertainty)),
        "disclaimer": DISCLAIMER_TR + (" Marmaray bağlantısı bu grafikte simüle edilir." if MARMARAY_LINE in path.lines else ""),
    }
    return JourneyResult(data, provenance)


async def plan_accessible_journey(
    nabiz: Nabiz,
    origin: str | tuple[float, float],
    destination: str | tuple[float, float],
    needs: Sequence[str] | None = None,
) -> JourneyResult:
    """Plan an accessible rail trip with per-station lifts and a checked detour if needed.

    Place names use the same ``Nabiz._endpoint`` gazetteer path as ``plan_journey``. One
    station list and one lift snapshot feed the whole route; no per-station upstream calls or
    user location storage are introduced. A detour is accepted only when its graph path omits
    the station it replaces. NEXUS is deliberately not imported here, so its simulated
    operator-approval badge cannot be asserted by this module.
    """
    asked = accessibility.check_needs(needs)
    try:
        start = _endpoint(nabiz, origin, role="origin")
        end = _endpoint(nabiz, destination, role="destination")
    except (TypeError, ValueError) as exc:
        return _failure(str(origin), str(destination), asked, str(exc))

    source_data = await _read_sources(nabiz, start, end, asked)
    if isinstance(source_data, JourneyResult):
        return source_data
    stations, snapshot, provenance, uncertainty = source_data

    graph = MetroGraph.from_stations(stations, added=marmaray_tube(stations))
    result = graph.path_between_points((start.lat, start.lon), (end.lat, end.lon))
    if result.path is None:
        reason = _PATH_REASONS_TR.get(result.reason or "")
        if result.reason not in PATH_FAILURE_REASONS or reason is None:
            reason = "Raylı sistem yolu doğrulanamadı."
        return _failure(start.name, end.name, asked, reason, uncertainty, provenance)
    path = result.path
    if not any(leg.kind == "ride" for leg in path.legs):
        return _failure(start.name, end.name, asked, "Başlangıç ve varış arasında doğrulanabilir bir raylı yol yok.",
                        uncertainty, provenance)

    return _finish_route(graph, path, stations, snapshot, provenance, uncertainty, (start, end, asked))
