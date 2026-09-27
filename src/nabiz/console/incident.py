"""Pure read-model helpers for operator incident files."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from types import SimpleNamespace
from typing import Any

from ibb_mcp.text import fold_tr, squash_punctuation
from nabiz.console.report_api import REPORT_KIND
from nabiz.console.report_link import photo_ref
from nabiz.console.report_triage import SUPPORT_MANY, record_conflict, report_priority

# These are design parameters, not measured thresholds or counts.
WAIT_HOURS = 4
MAX_INCIDENTS = 100
LEVELS = ("high", "medium", "normal")
MEMBER_KINDS = ("report", "photo", "equipment")
_LEVEL_RANK = {level: index for index, level in enumerate(LEVELS)}
_OPEN = frozenset({"awaiting_approval", "deferred"})


class IncidentList(list[dict[str, Any]]):
    """A normal list with diagnostics for persisted actions whose members have expired."""

    def __init__(self, values: Iterable[dict[str, Any]] = (), *, skipped_actions: list[int] | None = None) -> None:
        super().__init__(values)
        self.skipped_actions = skipped_actions or []


def _time(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo is not None and value.utcoffset() is not None else None
    if isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None
    return None


def _iso(value: Any) -> str | None:
    parsed = _time(value)
    return parsed.isoformat() if parsed else None


def _state_parts(state: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    signal = state.get("signal") if isinstance(state.get("signal"), Mapping) else state
    payload = signal.get("payload") if isinstance(signal.get("payload"), Mapping) else {}
    return signal, payload


def _base_incident(key: str, members: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    incident = {
        "id": f"inc-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:10]}",
        "station_key": key,
        "members": {kind: list(members[kind]) for kind in MEMBER_KINDS},
    }
    _refresh_incident(incident)
    return incident


def _station_key(name: str) -> str:
    """Match the report map's punctuation and Turkish casing normalization."""
    return squash_punctuation(fold_tr(name))


def report_members(
    states: Iterable[Mapping[str, Any]],
    support_counts: Mapping[str, int],
    now: dt.datetime,
    window_hours: int,
) -> list[dict[str, Any]]:
    """Project report-card dictionaries into safe incident members."""
    cutoff = now - dt.timedelta(hours=window_hours)
    members: list[dict[str, Any]] = []
    for state in states:
        signal, payload = _state_parts(state)
        if signal.get("kind") != REPORT_KIND:
            continue
        signal_id = str(signal.get("signal_id") or "")
        received = _time(state.get("received_at"))
        status = str(state.get("status") or "received")
        station = str(payload.get("station") or "")
        key = _station_key(station)
        if not signal_id or not key or (status not in _OPEN and (received is None or received < cutoff)):
            continue
        support = max(1, int(support_counts.get(signal_id, 1)))
        priority_state = SimpleNamespace(
            reasons=tuple(state.get("reasons") or ()),
            repeats=max(1, int(state.get("repeats") or 1)),
            signal=SimpleNamespace(payload=dict(payload)),
        )
        priority = report_priority(priority_state, support, window_hours)
        members.append(
            {
                "ref": f"report:{signal_id}",
                "signal_id": signal_id,
                "station": station,
                "station_key": key,
                "report_kind": payload.get("report_kind"),
                "kind_text": str(payload.get("kind_text") or ""),
                "status": status,
                "received_at": _iso(received),
                "support": support,
                "lift_status": payload.get("lift_status"),
                "lift_text": payload.get("lift_text"),
                "codes": list(priority.get("codes") or ()),
                "priority": priority,
                "window_hours": window_hours,
            }
        )
    return sorted(members, key=lambda item: (item["received_at"] or "", item["signal_id"]))


def equipment_members(states: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep the newest equipment fault card for each source entity."""
    newest: dict[str, dict[str, Any]] = {}
    for state in states:
        signal, payload = _state_parts(state)
        kind = signal.get("kind")
        if kind not in {"equipment_fault", "long_outage"}:
            continue
        signal_id = str(signal.get("signal_id") or "")
        station = str(payload.get("station") or "")
        key = _station_key(station)
        if not signal_id or not key:
            continue
        entity = str(signal.get("entity_id") or signal_id)
        provenance = signal.get("provenance") if isinstance(signal.get("provenance"), Mapping) else {}
        observed = _iso(provenance.get("observed_at") or signal.get("observed_at"))
        member = {
            "ref": f"equipment:{signal_id}",
            "signal_id": signal_id,
            "station": station,
            "station_key": key,
            "line": payload.get("line"),
            "equipment_type": payload.get("equipment_type"),
            "status_class": payload.get("status_class"),
            "status_type": payload.get("status_type"),
            "ibb_date": payload.get("ibb_date"),
            "outage_hours": payload.get("outage_hours"),
            "date_semantics_unknown": bool(payload.get("date_semantics_unknown")),
            "observed_at": observed,
            "source": provenance.get("source"),
            "entity_id": entity,
        }
        current = newest.get(entity)
        if current is None or (member["observed_at"] or "") > (current["observed_at"] or ""):
            newest[entity] = member
    return sorted(newest.values(), key=lambda item: (item["station_key"], item["entity_id"]))


def photo_members(items: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Project photo reports: station-level ones, and any photo the citizen linked to a report (P07)."""
    members: list[dict[str, Any]] = []
    for item in items:
        place = item.get("place") if isinstance(item.get("place"), Mapping) else {}
        code, linked = str(item.get("code") or ""), item.get("linked_signal_id")
        station = str(place.get("name") or "") if place.get("kind") == "station" else ""
        key = _station_key(station)
        if not code or not (key or linked):
            continue
        members.append({
            "ref": photo_ref(code), "photo_code": code, "station": station, "station_key": key,
            "linked_ref": f"report:{linked}" if linked else None, "report_code": item.get("linked_report_code"),
            "category": item.get("category"), "status": item.get("status"),
            "created_at": _iso(item.get("created_at")), "has_photo": bool(item.get("has_photo", True)),
        })
    return sorted(members, key=lambda item: (item["created_at"] or "", item["ref"]))


def auto_incidents(
    reports: Iterable[dict[str, Any]],
    photos: Iterable[dict[str, Any]],
    equipment: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Group only citizen reports or station photos; equipment enriches those groups.

    A photo linked to a report joins that report's incident even when its station name differs.
    """
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {kind: [] for kind in MEMBER_KINDS})
    reports = list(reports)
    report_keys = {member["ref"]: member.get("station_key") for member in reports}
    for kind, values in (("report", reports), ("photo", photos)):
        for member in values:
            key = report_keys.get(member.get("linked_ref")) or member.get("station_key")
            key = str(key or _station_key(str(member.get("station") or "")))
            if key:
                grouped[key][kind].append(dict(member))
    for member in equipment:
        key = str(member.get("station_key") or _station_key(str(member.get("station") or "")))
        if key in grouped:
            grouped[key]["equipment"].append(dict(member))
    return [_base_incident(key, grouped[key]) for key in sorted(grouped)]


def _action_data(action: Mapping[str, Any]) -> dict[str, Any]:
    value = action.get("data") or {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _refresh_incident(incident: dict[str, Any]) -> None:
    members = incident["members"]
    incident["stations"] = sorted({str(m["station"]) for k in MEMBER_KINDS for m in members[k] if m.get("station")}, key=fold_tr)
    incident["title_station"] = incident["stations"][0] if incident["stations"] else ""
    report_times = [
        parsed
        for member in members["report"]
        if member.get("status") in _OPEN and (parsed := _time(member.get("received_at"))) is not None
    ]
    incident["oldest_open_at"] = min(report_times).isoformat() if report_times else None


def apply_actions(incidents: Iterable[dict[str, Any]], actions: Iterable[Mapping[str, Any]]) -> IncidentList:
    """Replay effective merge/split actions in order without mutating the input snapshot."""
    result = {
        item["id"]: {
            **item,
            "stations": list(item["stations"]),
            "members": {kind: [dict(member) for member in item["members"][kind]] for kind in MEMBER_KINDS},
        }
        for item in incidents
    }
    active = [row for row in actions if not row.get("undone_at")]
    active.sort(key=lambda row: (str(row.get("at") or ""), int(row.get("id") or 0)))
    skipped: list[int] = []
    for action in active:
        action_id = int(action.get("id") or 0)
        kind = action.get("kind")
        parent_id = str(action.get("incident_id") or "")
        data = _action_data(action)
        if kind == "split":
            source = result.get(parent_id)
            ref = str(data.get("ref") or "")
            found = (
                next(
                    (
                        (group, index, member)
                        for group in MEMBER_KINDS
                        for index, member in enumerate(source["members"][group])
                        if source and member.get("ref") == ref
                    ),
                    None,
                )
                if source
                else None
            )
            if source is None or found is None:
                skipped.append(action_id)
                continue
            group, index, member = found
            del source["members"][group][index]
            _refresh_incident(source)
            new_id = f"inc-a{action_id}"
            split_members = {name: [] for name in MEMBER_KINDS}
            split_members[group] = [dict(member)]
            split_item = _base_incident(str(data.get("station_key") or member.get("station_key") or ""), split_members)
            split_item.update(id=new_id)
            result[new_id] = split_item
        elif kind == "merge":
            source_id = str(data.get("source") or parent_id)
            target_id = str(data.get("target") or "")
            source, target = result.get(source_id), result.get(target_id)
            if source is None or target is None or source_id == target_id:
                skipped.append(action_id)
                continue
            for group in MEMBER_KINDS:
                target["members"][group].extend(source["members"][group])
            del result[source_id]
            _refresh_incident(target)
        else:
            skipped.append(action_id)
    return IncidentList(result.values(), skipped_actions=skipped)


def _base_level(reports: list[dict[str, Any]]) -> str:
    levels = [member.get("priority", {}).get("level") for member in reports]
    return min((level for level in levels if level in _LEVEL_RANK), key=_LEVEL_RANK.get, default="normal")


def suggest_priority(incident: Mapping[str, Any], now: dt.datetime) -> dict[str, Any]:
    """Explain one deterministic priority suggestion from ledger and institution records."""
    members = incident.get("members") or {}
    reports = list(members.get("report") or [])
    equipment = list(members.get("equipment") or [])
    base = _base_level(reports)
    support = sum(max(1, int(item.get("support") or 1)) for item in reports)
    repeat_code = any("REPEAT" in (item.get("codes") or []) for item in reports)
    window = max((int(item.get("window_hours") or 168) for item in reports), default=168)
    repeat = {
        "people": support,
        "cards": len(reports),
        "repeat_code": repeat_code,
        "window_hours": window,
        "threshold_people": SUPPORT_MANY,
    }
    factors: list[dict[str, Any]] = [
        {
            "key": "repeat",
            "values": repeat,
            "source": "ledger",
            "observed_at": max((item.get("received_at") or "" for item in reports), default=None) or None,
            "verified": None,
        }
    ]

    open_reports = [item for item in reports if item.get("status") in _OPEN and _time(item.get("received_at"))]
    oldest = min((_time(item["received_at"]) for item in open_reports), default=None)
    hours = max(0.0, (now - oldest).total_seconds() / 3600) if oldest else None
    waiting_over = hours is not None and hours >= WAIT_HOURS
    factors.append(
        {
            "key": "waiting",
            "values": {
                "hours": round(hours, 1) if hours is not None else None,
                "threshold_hours": WAIT_HOURS,
                "over": waiting_over,
                "oldest_open_at": oldest.isoformat() if oldest else None,
            },
            "source": "ledger",
            "observed_at": oldest.isoformat() if oldest else None,
            "verified": None,
        }
    )

    verified_equipment = next((item for item in equipment if item.get("equipment_type") == "elevator"), None)
    recorded_report = next((item for item in reports if item.get("lift_status") == "out_of_service"), None)
    access_member = verified_equipment or recorded_report
    verified = access_member is not None
    interchange = any("CRITICAL" in (item.get("codes") or []) for item in reports)
    line = next((item.get("line") for item in reports + equipment if item.get("line")), None)
    equipment_type = (verified_equipment or {}).get("equipment_type") or ("elevator" if recorded_report else None)
    status_type = (verified_equipment or {}).get("status_type") or (recorded_report or {}).get("lift_text")
    escalator = any(item.get("equipment_type") == "escalator" for item in equipment)
    access_values = {
        "equipment_type": equipment_type,
        "status_type": status_type,
        "interchange": interchange,
        "line": line,
        "verified_step_free": bool(verified and equipment_type == "elevator"),
        "access_unverified": not verified,
        "escalator_recorded": escalator,
    }
    factors.append(
        {
            "key": "access",
            "values": access_values,
            "source": "ibb_record" if verified else "citizen",
            "observed_at": ((verified_equipment or {}).get("observed_at") or (recorded_report or {}).get("received_at")),
            "verified": verified,
        }
    )

    conflicts = [
        record_conflict({"report_kind": item.get("report_kind"), "lift_status": item.get("lift_status")}) for item in reports
    ]
    conflict_text = next((value for value in conflicts if value), None)
    if conflict_text:
        report = next(
            item
            for item in reports
            if record_conflict(
                {
                    "report_kind": item.get("report_kind"),
                    "lift_status": item.get("lift_status"),
                }
            )
        )
        factors.append(
            {
                "key": "conflict",
                "values": {"text": conflict_text, "needs_check": True},
                "source": "ibb_record",
                "observed_at": report.get("received_at"),
                "verified": None,
                "needs_check": True,
            }
        )

    raised: list[str] = []
    if verified and base != "high":
        if support >= SUPPORT_MANY:
            raised.append("repeat")
        if waiting_over:
            raised.append("waiting")
    if raised:
        raised.insert(0, "access")
        level = "high"
    else:
        level = base
    return {"level": level, "base_level": base, "raised_by": raised, "factors": factors, "suggested": True}


def effective_priority(suggestion: Mapping[str, Any], override: Mapping[str, Any] | None) -> dict[str, Any]:
    """Keep the current operator choice beside its original computed suggestion."""
    if not override:
        return {
            "level": suggestion["level"],
            "by": "suggestion",
            "suggested_level": suggestion["level"],
            "reason": None,
            "at": None,
            "actor": None,
        }
    return {
        "level": override["level"],
        "by": "operator",
        "suggested_level": suggestion["level"],
        "reason": override["reason"],
        "at": override["at"],
        "actor": override["actor"],
    }


def build_incidents(
    reports: Iterable[dict[str, Any]],
    photos: Iterable[dict[str, Any]],
    equipment: Iterable[dict[str, Any]],
    actions: Iterable[Mapping[str, Any]],
    overrides: Mapping[str, Mapping[str, Any]],
    now: dt.datetime,
) -> IncidentList:
    """Build, replay and rank the operator incident list."""
    incidents = apply_actions(auto_incidents(reports, photos, equipment), actions)
    for incident in incidents:
        incident["suggestion"] = suggest_priority(incident, now)
        incident["priority"] = effective_priority(incident["suggestion"], overrides.get(incident["id"]))
    incidents.sort(
        key=lambda item: (
            _LEVEL_RANK.get(item["priority"]["level"], len(LEVELS)),
            item.get("oldest_open_at") or "9999",
            item["id"],
        )
    )
    limited = IncidentList(incidents[:MAX_INCIDENTS], skipped_actions=incidents.skipped_actions)
    return limited
