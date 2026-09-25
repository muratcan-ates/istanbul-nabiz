"""Metro equipment faults as NEXUS signal candidates: plain dictionaries the console wraps.

``ibb_mcp`` never imports ``nexus_core`` (DECISIONS #21), so this module builds only
``{kind, entity_id, severity, payload}``; ``nabiz.console`` adds the provenance and turns each
into a ``nexus_core`` signal. The payload field names are the ones
``missions/erisilebilir_yolculuk.toml`` reads (``missions/README.md`` lists them).

Four kinds come out of one snapshot:

* ``equipment_fault`` per record, with the nearest step-free alternative for a lift
  (:func:`ibb_mcp.accessibility.find_alternative`);
* ``long_outage`` when İBB's recorded date is more than :data:`LONG_OUTAGE_HOURS` old. The
  date's meaning is undocumented, so the payload says what the hours count from;
* ``hub_faults`` when an interchange has :data:`HUB_FAULT_THRESHOLD` or more records;
* ``source_stale`` when live data is past its age limit (:func:`stale_signal`).

Split from ``ibb_mcp.accessibility`` on 2026-09-25 so both stay under the module-size cap.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any

from ibb_mcp.accessibility import (
    PlatformKey,
    StepFreeAlternative,
    faults_by_platform,
    find_alternative,
    is_stale,
    platform_key,
    status_note,
)
from ibb_mcp.http import UpstreamUnavailable
from ibb_mcp.metro_graph import DEFAULT_METRO_PARAMS, MetroGraph
from ibb_mcp.models import MetroStation, Provenance, ToolResult, haversine_km
from ibb_mcp.sources.metro import MetroSource
from ibb_mcp.sources.metro_equipment import (
    EQUIPMENT_GROUPS,
    EquipmentRecord,
    EquipmentSnapshot,
    MetroEquipmentSource,
    line_key,
    match_station,
    station_key,
    unread_provenance,
)

#: This many faults at one interchange go to a person (rule R-05).
HUB_FAULT_THRESHOLD = 2
#: A fault İBB dated longer ago than this goes to a person (rule R-06).
LONG_OUTAGE_HOURS = 24


def transfer_hubs(stations: Sequence[MetroStation]) -> dict[PlatformKey, str]:
    """Platform -> interchange name, by :mod:`ibb_mcp.metro_graph`'s walking rule.

    Two platforms of different lines form an interchange when they share a name and are within
    ``max_named_walk_km``, or are within ``max_unnamed_walk_km`` whatever their names. A shared
    name alone is never enough (Bahariye T3 and M9 are 20.7 km apart).
    """
    hubs: dict[PlatformKey, str] = {}
    located = [s for s in stations if s.lat is not None and s.lon is not None and s.line_name]
    for i, a in enumerate(located):
        for b in located[i + 1 :]:
            if line_key(a.line_name) == line_key(b.line_name):
                continue
            km = haversine_km(a.lat or 0.0, a.lon or 0.0, b.lat or 0.0, b.lon or 0.0)
            same = station_key(a.name) == station_key(b.name)
            if km <= (DEFAULT_METRO_PARAMS.max_named_walk_km if same else DEFAULT_METRO_PARAMS.max_unnamed_walk_km):
                hub = hubs.get(platform_key(a)) or hubs.get(platform_key(b)) or (a.name or "")
                hubs[platform_key(a)] = hubs[platform_key(b)] = hub
    return hubs


def _fault_signal(record: EquipmentRecord, alternative: StepFreeAlternative | None, now: dt.datetime) -> dict[str, Any]:
    hours = None if record.ibb_date is None else round(max(0.0, (now - record.ibb_date).total_seconds()) / 3600, 1)
    payload: dict[str, Any] = {
        "equipment_type": record.equipment_type,
        "equipment_code": record.code,
        "station": record.station_name,
        "line": record.line_name,
        "status_type": record.status_label,
        "status_class": record.status_class,
        "outage_id": record.outage_id,
        "ibb_date": record.ibb_date.isoformat() if record.ibb_date else None,
        "outage_hours": hours,
        "down_days": None if hours is None else int(hours // 24),
        "outage_hours_basis": "ibb_date" if hours is not None else None,
        "date_semantics_unknown": record.ibb_date_raw is not None,
        "text": record.describe(),
    }
    if alternative is not None:
        payload.update(
            alternative_station=alternative.station,
            alternative_line=alternative.line,
            # Chosen from this snapshot's stations with no lift listed, so explicitly not faulty
            # here: nexus_core's approved-alternative check reads it (approved.revalidate).
            alternative_faulty=False,
            extra_minutes=alternative.extra_minutes,
            extra_minutes_text=f"{alternative.extra_minutes} dk" if alternative.extra_minutes is not None else "hesaplanamadı",
            alternative_reason=alternative.reason,
        )
    entity = f"metro-equipment:{record.code or record.outage_id.split('@', 1)[0]}"
    severity = "warning" if record.equipment_type == "elevator" else "info"
    return {"kind": "equipment_fault", "entity_id": entity, "severity": severity, "payload": payload}


def signal_candidates(
    snapshot: EquipmentSnapshot, stations: Sequence[MetroStation], *, now: dt.datetime, graph: MetroGraph | None = None
) -> list[dict[str, Any]]:
    """``equipment_fault`` per record, ``long_outage`` past :data:`LONG_OUTAGE_HOURS`, ``hub_faults`` per busy interchange.

    Each item is ``{kind, entity_id, severity, payload}``; the console adds the time and the
    provenance and wraps it as a ``nexus_core`` signal.
    """
    graph = graph or MetroGraph.from_stations(stations)
    faults = faults_by_platform(snapshot.records, stations)
    hubs = transfer_hubs(stations)
    out: list[dict[str, Any]] = []
    at_hub: dict[str, list[EquipmentRecord]] = {}
    for record in snapshot.records:
        platform = match_station(record, stations)
        alternative = None
        if record.equipment_type == "elevator" and platform is not None:
            alternative = find_alternative(platform.name or "", [platform], stations, faults, graph)
        signal = _fault_signal(record, alternative, now)
        out.append(signal)
        hours = signal["payload"]["outage_hours"]
        if hours is not None and hours > LONG_OUTAGE_HOURS:
            out.append({**signal, "kind": "long_outage"})
        hub = hubs.get(platform_key(platform)) if platform is not None else None
        if hub:
            at_hub.setdefault(hub, []).append(record)
    for hub, records in sorted(at_hub.items()):
        if len(records) >= HUB_FAULT_THRESHOLD:
            listing = "; ".join(f"{r.line_name} {r.group}: {r.status_label}" for r in records)
            payload = {
                "hub": hub,
                "fault_count": len(records),
                "equipment_list": listing,
                "lines": sorted({r.line_name for r in records if r.line_name}),
            }
            entity = f"metro-hub:{station_key(hub)}"
            out.append({"kind": "hub_faults", "entity_id": entity, "severity": "warning", "payload": payload})
    return out


def snapshot_summary_tr(snapshot: EquipmentSnapshot) -> str:
    """Counts per group read, in one Turkish sentence ("İBB kaydında 14 asansör, ... kullanılamıyor.")."""
    if not snapshot.available:
        return "Metro ekipman kaydı okunamadı."
    counts = [f"{sum(1 for r in snapshot.records if r.group == g)} {g.lower()}" for g in snapshot.groups_read]
    return "İBB kaydında " + ", ".join(counts) + " kullanılamıyor."


def stale_signal(snapshot: EquipmentSnapshot, provenance: Provenance, *, offline: bool) -> dict[str, Any] | None:
    """A ``source_stale`` signal (rule R-04) when live equipment data is past its age limit, else ``None``."""
    if not is_stale(provenance, offline=offline):
        return None
    payload = {
        "source": "metro_equipment",
        "age_text": provenance.describe_age(),
        "age_minutes": int(provenance.age_seconds // 60),
        "last_known_text": snapshot_summary_tr(snapshot),
    }
    return {"kind": "source_stale", "entity_id": "source:metro_equipment", "severity": "info", "payload": payload}


async def equipment_signals(equipment: MetroEquipmentSource, metro: MetroSource) -> ToolResult:
    """Every group's snapshot as NEXUS signal candidates, for the console (not an MCP tool).

    ``data.signals`` holds :func:`signal_candidates` plus :func:`stale_signal` when it fires;
    ``data.observed_at`` is the snapshot's own time, which the console stamps on each signal so
    replaying one recording gives the same signal ids. Outage hours count to that time, not to
    the wall clock: a recording read a week later still says what İBB's record said then.
    """
    offline = equipment.ctx.settings.offline
    try:
        snapshot, provenance = await equipment.snapshot(EQUIPMENT_GROUPS)
    except UpstreamUnavailable:
        provenance = unread_provenance()
        data = {"available": False, "mode": "recorded" if offline else "live", "signals": [], "observed_at": None}
        return ToolResult(data=data, provenance=provenance, note="Metro ekipman kaydı okunamadı.")
    stations, _ = await metro.stations()
    observed = provenance.reported_at or provenance.observed_at
    found = signal_candidates(snapshot, stations, now=observed) if snapshot.available else []
    if (stale := stale_signal(snapshot, provenance, offline=offline)) is not None:
        found.append(stale)
    data = {
        "available": snapshot.available,
        "mode": "recorded" if offline else "live",
        "signals": found,
        "observed_at": observed.isoformat() if observed else None,
    }
    return ToolResult(data=data, provenance=provenance, note=None if snapshot.available else status_note({"available": False}))
