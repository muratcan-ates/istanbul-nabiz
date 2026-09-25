"""Step-free answers from İBB's own data: which lifts are out, and where else to get on or off.

Two questions, both answered only from what Metro İstanbul publishes:

* :func:`equipment_status_data`: what ``GetFaultyEquipmentDetails`` lists, filtered by
  station, line or group, with the uncertainty codes of
  :mod:`ibb_mcp.sources.metro_equipment` and a card status for the page.
* :func:`accessible_alternative`: when a station's lift is listed as unusable, the nearest
  station on the same line or one change away whose lifts are not listed, and roughly how many
  more minutes the ride to it takes.

No profile comes in. The caller passes a functional need (``step_free``) and nothing about the
person; who needs it, and why, never reaches this module or the server (charter §1.3).

Two limits are said in every answer rather than hidden. A lift that is not on İBB's list is not
proven usable, so the most this module says is "İBB kaydında arıza yok", never that a lift
works. And the extra minutes are :mod:`ibb_mcp.metro_graph`'s estimate of the ride between the
two stations: distance over an assumed speed, no timetable, and nothing for the trip from the
alternative station back to where the person meant to be.

:func:`signal_candidates` turns one snapshot into plain dictionaries the console can wrap as
NEXUS signals; the field names are the ones ``missions/erisilebilir_yolculuk.toml`` reads.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ibb_mcp.config import METRO_FAULTY_EQUIPMENT_DETAILS
from ibb_mcp.http import UpstreamUnavailable
from ibb_mcp.metro_graph import DEFAULT_METRO_PARAMS, MetroGraph
from ibb_mcp.models import MetroStation, Provenance, ToolResult, haversine_km
from ibb_mcp.sources.base import make_provenance
from ibb_mcp.sources.metro import MetroSource
from ibb_mcp.sources.metro_equipment import (
    DATE_LABEL_TR,
    EQUIPMENT_DISCLAIMER_TR,
    EQUIPMENT_GROUPS,
    EQUIPMENT_STALE_AFTER_S,
    STATION_UNMATCHED,
    EquipmentRecord,
    EquipmentSnapshot,
    MetroEquipmentSource,
    line_key,
    match_station,
    resolve_group,
    station_key,
)
from ibb_mcp.text import fold_tr, rank_match_loose, squash_punctuation

#: The only functional needs understood today. Anything else is refused, not ignored.
SUPPORTED_NEEDS: tuple[str, ...] = ("step_free",)
#: "Aynı hatta ya da aktarmada": the same line, or one change.
MAX_TRANSFERS = 1
#: Straight-line nearest candidates whose rail path is actually measured.
CANDIDATE_POOL = 25
#: This many faults at one interchange go to a person (rule R-05).
HUB_FAULT_THRESHOLD = 2
#: A fault İBB dated longer ago than this goes to a person (rule R-06).
LONG_OUTAGE_HOURS = 24

NO_ALTERNATIVE = "no_alternative_found"
EQUIPMENT_DATA_UNAVAILABLE = "equipment_data_unavailable"
NO_LIFT_RECORDED = "no_lift_recorded"
LIFT_COUNT_UNKNOWN = "lift_count_unknown"
STALE_DATA = "stale_data"

ALTERNATIVE_NOTE_TR = (
    "Ek süre, iki istasyon arasındaki raylı yolculuğun mesafeye dayalı tahminidir; tarife değildir ve "
    "alternatif istasyondan varış noktasına dönüşü içermez. Öneri yalnız İBB verisinden türetilmiştir, "
    "operatör onayı taşımaz."
)

PlatformKey = tuple[str, str]


def platform_key(station: MetroStation) -> PlatformKey:
    return station_key(station.name), line_key(station.line_name)


def check_needs(needs: Sequence[str] | None) -> tuple[str, ...]:
    """The needs asked for, each one supported; an empty list means ``step_free``."""
    asked = tuple(dict.fromkeys(n.strip() for n in (needs or ()) if n and n.strip())) or SUPPORTED_NEEDS
    unknown = [n for n in asked if n not in SUPPORTED_NEEDS]
    if unknown:
        raise ValueError(f"Desteklenmeyen ihtiyaç: {', '.join(unknown)}. Desteklenen: {', '.join(SUPPORTED_NEEDS)}.")
    return asked


def resolve_platforms(name: str, stations: Sequence[MetroStation]) -> list[MetroStation]:
    """Every platform of the best-matching station name: an interchange is several rows."""
    query = fold_tr(name)
    if not query:
        return []
    loose = squash_punctuation(query)
    ranked = [(rank, s) for s in stations if (rank := rank_match_loose(query, loose, s.name)) is not None]
    if not ranked:
        return []
    best = min(rank for rank, _ in ranked)
    return [s for rank, s in ranked if rank == best]


def faults_by_platform(
    records: Sequence[EquipmentRecord], stations: Sequence[MetroStation]
) -> dict[PlatformKey, list[EquipmentRecord]]:
    """Records grouped under the platform they match; unmatched ones under their own names."""
    grouped: dict[PlatformKey, list[EquipmentRecord]] = {}
    for record in records:
        station = match_station(record, stations)
        key = platform_key(station) if station else (station_key(record.station_name), line_key(record.line_name))
        grouped.setdefault(key, []).append(record)
    return grouped


@dataclass(frozen=True)
class LiftState:
    lift_status: str  # "working" (no fault record) | "out_of_service" | "unknown"
    lift_count: int | None
    unavailable_lift_count: int
    text: str
    codes: tuple[str, ...] = ()


def lift_state(name: str, platforms: Sequence[MetroStation], faults: dict[PlatformKey, list[EquipmentRecord]]) -> LiftState:
    """What İBB's records say about the lifts of one station, in words that never overclaim."""
    counts = [p.lifts for p in platforms]
    lift_count = None if any(c is None for c in counts) else sum(c or 0 for c in counts)
    out = sum(1 for p in platforms for r in faults.get(platform_key(p), []) if r.equipment_type == "elevator")
    if out:
        total = f" ({lift_count} asansör kayıtlı)" if lift_count else ""
        text = f"İBB kaydına göre {name} istasyonunda {out} asansör kullanılamıyor{total}."
        return LiftState("out_of_service", lift_count, out, text)
    if lift_count is None:
        return LiftState("unknown", None, 0, f"{name} için asansör bilgisi İBB tarafından paylaşılmamış.", (LIFT_COUNT_UNKNOWN,))
    if lift_count == 0:
        return LiftState("unknown", 0, 0, f"İBB kaydına göre {name} istasyonunda asansör yok.", (NO_LIFT_RECORDED,))
    return LiftState("working", lift_count, 0, f"İBB kaydında {name} istasyonu için asansör arızası yok.")


def lifts_readable(snapshot: EquipmentSnapshot | None) -> bool:
    """Whether the snapshot can speak about lifts at all: the lift group was read."""
    return snapshot is not None and "Asansör" in snapshot.groups_read


def unreadable_state(name: str) -> LiftState:
    return LiftState("unknown", None, 0, f"{name} için asansör kaydı okunamadı; doğrulanamadı.", (EQUIPMENT_DATA_UNAVAILABLE,))


@dataclass(frozen=True)
class Alternative:
    station: str
    line: str
    extra_minutes: int | None
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"station": self.station, "line": self.line, "extra_minutes": self.extra_minutes, "reason": self.reason}


def _candidates(
    platforms: Sequence[MetroStation], stations: Sequence[MetroStation], faults: dict[PlatformKey, list[EquipmentRecord]]
) -> list[MetroStation]:
    """Other stations with lifts and none of them listed, nearest in a straight line first."""
    own = {station_key(p.name) for p in platforms}
    anchor = next((p for p in platforms if p.lat is not None and p.lon is not None), None)
    pool = [
        s
        for s in stations
        if s.lifts and station_key(s.name) not in own and s.lat is not None and s.lon is not None
        and not any(r.equipment_type == "elevator" for r in faults.get(platform_key(s), []))
    ]
    if anchor is not None:
        pool.sort(key=lambda s: haversine_km(anchor.lat or 0.0, anchor.lon or 0.0, s.lat or 0.0, s.lon or 0.0))
    return pool[:CANDIDATE_POOL]


def _start_lines(platforms: Sequence[MetroStation], faults: dict[PlatformKey, list[EquipmentRecord]]) -> set[str]:
    """The lines a rider is stuck on: those whose platform here has a listed lift, else every line here."""
    def lift_out(p: MetroStation) -> bool:
        return any(r.equipment_type == "elevator" for r in faults.get(platform_key(p), []))

    stuck = {line_key(p.line_name) for p in platforms if lift_out(p)}
    return stuck or {line_key(p.line_name) for p in platforms}


def find_alternative(
    name: str,
    platforms: Sequence[MetroStation],
    stations: Sequence[MetroStation],
    faults: dict[PlatformKey, list[EquipmentRecord]],
    graph: MetroGraph,
) -> Alternative | None:
    """The candidate with the shortest estimated ride, at most :data:`MAX_TRANSFERS` changes away.

    The ride must begin on a line whose platform here has the unusable lift: a rider who cannot
    leave that platform cannot change trains here either, so an in-station transfer (Yenikapı M2
    to M1A, say) is no alternative. The graph resolves a name to every platform that carries it,
    hence the check on the first and last legs.
    """
    origin = platforms[0].name or name
    start = _start_lines(platforms, faults)
    best: tuple[float, MetroStation] | None = None
    for candidate in _candidates(platforms, stations, faults):
        path = graph.path_between_stations(origin, candidate.name or "").path
        if path is None or path.transfer_count > MAX_TRANSFERS or not path.legs:
            continue
        first, last = path.legs[0], path.legs[-1]
        if first.kind != "ride" or line_key(first.line) not in start or line_key(last.line) != line_key(candidate.line_name):
            continue
        if best is None or path.total_seconds < best[0]:
            best = (path.total_seconds, candidate)
    if best is None:
        return None
    seconds, station = best
    minutes = max(1, math.ceil(seconds / 60))
    reason = (
        f"{station.name} ({station.line_name}) istasyonunda {station.lifts} asansör kayıtlı ve İBB kaydında "
        f"asansör arızası yok. {origin} ile arası tahminen {minutes} dk. {ALTERNATIVE_NOTE_TR}"
    )
    return Alternative(station.name or "", station.line_name or "", minutes, reason)


def accessible_alternative(
    station: str,
    needs: Sequence[str] | None = ("step_free",),
    *,
    stations: Sequence[MetroStation],
    snapshot: EquipmentSnapshot | None,
    graph: MetroGraph | None = None,
) -> dict[str, Any]:
    """The contract's ``/api/alternative`` body, minus ``provenance`` and ``operator_approved``.

    ``snapshot`` is ``None`` or empty when the lift list could not be read: then nothing is
    claimed about the lifts and no alternative is offered, because it could not be checked.
    """
    asked = check_needs(needs)
    platforms = resolve_platforms(station, stations)
    if not platforms:
        raise ValueError(f"'{station}' adlı bir metro istasyonu bulamadım.")
    name = platforms[0].name or station
    lines = sorted({p.line_name for p in platforms if p.line_name})
    if snapshot is None or not lifts_readable(snapshot):
        state = unreadable_state(name)
        return _answer(name, lines, asked, state, None, state.codes)
    faults = faults_by_platform(snapshot.records, stations)
    state = lift_state(name, platforms, faults)
    codes = list(state.codes)
    alternative = None
    if state.lift_status != "working":
        alternative = find_alternative(name, platforms, stations, faults, graph or MetroGraph.from_stations(stations))
        if alternative is None:
            codes.append(NO_ALTERNATIVE)
    return _answer(name, lines, asked, state, alternative, tuple(codes))


def _answer(
    name: str, lines: list[str], needs: tuple[str, ...], state: LiftState, alternative: Alternative | None, codes: tuple[str, ...]
) -> dict[str, Any]:
    return {
        "station": name,
        "lines": lines,
        "needs": list(needs),
        "lift_status": state.lift_status,
        "lift_count": state.lift_count,
        "unavailable_lift_count": state.unavailable_lift_count,
        "alternative": alternative.as_dict() if alternative else None,
        "text": state.text,
        "uncertainty": list(codes),
    }


# --------------------------------------------------------------------------------------
# the equipment tool's answer
# --------------------------------------------------------------------------------------
def is_stale(provenance: Provenance, *, offline: bool) -> bool:
    """Live data past :data:`EQUIPMENT_STALE_AFTER_S`, or served stale after an error.

    A recording is "kayıtlı", never stale: its age is shown as its capture time instead.
    """
    return not offline and (provenance.cached or provenance.age_seconds > EQUIPMENT_STALE_AFTER_S)


def _record_row(record: EquipmentRecord) -> dict[str, Any]:
    return {
        "code": record.code,
        "group": record.group,
        "equipment_type": record.equipment_type,
        "line": record.line_name,
        "station": record.station_name,
        "location": record.location,
        "status_type": record.status_label,
        "status_class": record.status_class,
        "ibb_date": record.ibb_date.isoformat() if record.ibb_date else None,
        "ibb_date_raw": record.ibb_date_raw,
        "description": record.description,
        "text": record.describe(),
    }


def _filter(
    snapshot: EquipmentSnapshot, stations: Sequence[MetroStation], station: str | None, line: str | None
) -> tuple[list[EquipmentRecord], list[MetroStation]]:
    records = list(snapshot.records)
    platforms: list[MetroStation] = []
    if station:
        platforms = resolve_platforms(station, stations)
        if not platforms:
            raise ValueError(f"'{station}' adlı bir metro istasyonu bulamadım.")
        keys = {platform_key(p) for p in platforms}
        faults = faults_by_platform(records, stations)
        records = [r for key in keys for r in faults.get(key, [])]
    if line:
        wanted = line_key(line)
        records = [r for r in records if line_key(r.line_name) == wanted]
    return records, platforms


def card_status(snapshot: EquipmentSnapshot, records: Sequence[EquipmentRecord], stale: bool) -> str:
    """The contract's card status: no data is ``unverified``, old data ``stale``, any listed fault ``warning``."""
    if not snapshot.available:
        return "unverified"
    if stale:
        return "stale"
    return "warning" if records else "ok"


def equipment_status_data(
    snapshot: EquipmentSnapshot,
    provenance: Provenance,
    stations: Sequence[MetroStation],
    *,
    station: str | None = None,
    line: str | None = None,
    offline: bool = False,
) -> dict[str, Any]:
    """The ``metro_equipment_status`` payload for one snapshot and one set of filters."""
    records, platforms = _filter(snapshot, stations, station, line)
    stale = is_stale(provenance, offline=offline)
    codes = list(snapshot.uncertainty) + ([STALE_DATA] if stale else [])
    if any(match_station(r, stations) is None for r in records) and STATION_UNMATCHED not in codes:
        codes.append(STATION_UNMATCHED)
    data: dict[str, Any] = {
        "available": snapshot.available,
        "mode": "recorded" if offline else "live",
        "stale": stale,
        "card_status": card_status(snapshot, records, stale),
        "count": len(records),
        "affected_stations": len({station_key(r.station_name) for r in records}),
        "records": [_record_row(r) for r in records],
        "summary": [row.model_dump(mode="json") for row in snapshot.summary],
        "groups_read": snapshot.groups_read,
        "groups_missing": snapshot.groups_missing,
        "uncertainty": codes,
        "date_label": DATE_LABEL_TR,
        "disclaimer": EQUIPMENT_DISCLAIMER_TR,
    }
    if platforms:
        name = platforms[0].name or station or ""
        if lifts_readable(snapshot):
            state = lift_state(name, platforms, faults_by_platform(snapshot.records, stations))
        else:
            state = unreadable_state(name)
        data["station"] = {"name": name, "lines": sorted({p.line_name for p in platforms if p.line_name}),
                           "lift_status": state.lift_status, "lift_count": state.lift_count,
                           "unavailable_lift_count": state.unavailable_lift_count, "text": state.text}
    return data


def status_note(data: dict[str, Any]) -> str | None:
    """The one sentence an agent must relay, when there is one."""
    if not data["available"]:
        return "Metro ekipman kaydı okunamadı; asansör durumu doğrulanamadı."
    if data["stale"]:
        return "Veri bayat: gösterilen, son bilinen durumdur; doğrulanamadı."
    if data["count"] == 0:
        return "İBB kaydında bu filtre için kullanılamayan ekipman yok. Bu, ekipmanın kullanılabilir olduğunu kanıtlamaz."
    return None


# --------------------------------------------------------------------------------------
# signals for NEXUS (plain dictionaries; this package does not import nexus_core)
# --------------------------------------------------------------------------------------
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


def _fault_signal(record: EquipmentRecord, alternative: Alternative | None, now: dt.datetime) -> dict[str, Any]:
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
            payload = {"hub": hub, "fault_count": len(records), "equipment_list": listing,
                       "lines": sorted({r.line_name for r in records if r.line_name})}
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


# --------------------------------------------------------------------------------------
# what the façade calls
# --------------------------------------------------------------------------------------
async def equipment_status(
    equipment: MetroEquipmentSource,
    metro: MetroSource,
    *,
    station: str | None = None,
    line: str | None = None,
    group: str | None = None,
) -> ToolResult:
    """The ``metro_equipment_status`` tool: the snapshot, filtered, with the station list beside it."""
    wanted = resolve_group(group)
    snapshot, provenance = await equipment.snapshot((wanted,) if wanted else EQUIPMENT_GROUPS)
    stations, _ = await metro.stations()
    offline = equipment.ctx.settings.offline
    data = equipment_status_data(snapshot, provenance, stations, station=station, line=line, offline=offline)
    data["filters"] = {"station": station, "line": line, "group": wanted}
    return ToolResult(data=data, provenance=provenance, note=status_note(data))


async def alternative_answer(
    equipment: MetroEquipmentSource, metro: MetroSource, *, station: str, needs: Sequence[str] | None = None
) -> ToolResult:
    """The ``/api/alternative`` body: the station's lifts and, when needed, the nearest alternative."""
    check_needs(needs)
    stations, _ = await metro.stations()
    offline = equipment.ctx.settings.offline
    try:
        snapshot, provenance = await equipment.snapshot(("Asansör",))
    except UpstreamUnavailable:
        snapshot, provenance = None, make_provenance("metro_equipment", url=METRO_FAULTY_EQUIPMENT_DETAILS)
    data = accessible_alternative(station, needs, stations=stations, snapshot=snapshot)
    stale = snapshot is not None and snapshot.available and is_stale(provenance, offline=offline)
    if stale:
        data["uncertainty"].append(STALE_DATA)
    data.update(mode="recorded" if offline else "live", stale=stale)
    return ToolResult(data=data, provenance=provenance, note=ALTERNATIVE_NOTE_TR if data["alternative"] else None)
