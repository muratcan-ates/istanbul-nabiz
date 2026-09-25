"""A stateless alert for unusable Metro İstanbul equipment at watched stations or lines."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ibb_mcp.accessibility import LIFT_COUNT_UNKNOWN, faults_by_platform, lift_state, platform_key, resolve_platforms
from ibb_mcp.alerts.rules import (
    Alert,
    AlertContext,
    Citation,
    LiftObservation,
    Rule,
    Severity,
    alert_age_en,
    alert_age_tr,
    alert_digest,
)
from ibb_mcp.models import ISTANBUL_TZ
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.sources.metro_equipment import EquipmentRecord, line_key, match_station, station_key

MAX_LINES_PER_RULE = 20
MAX_STATIONS_PER_RULE = 10
MAX_LABEL_CHARS = 120
LIFT_EQUIPMENT = ("elevator", "escalator", "moving_walkway")

_EQUIPMENT_EN = {
    "elevator": "elevator",
    "escalator": "escalator",
    "moving_walkway": "moving walkway",
}
_STATUS_EN = {
    "Arıza": "Fault",
    "Revizyon": "Revision",
    "Çalıştırılmıyor": "Not operated",
    "bilinmiyor": "unknown",
}
_SEVERITY_RANK: dict[Severity, int] = {"critical": 0, "warning": 1, "info": 2}


@dataclass(frozen=True)
class LiftOutageRule:
    """Notify about recorded outages on watched stations or lines.

    The severity thresholds are a design parameter: a recorded outage is critical when every
    registered lift at a station is listed as unusable, warning when step-free access may
    remain or its count is unknown, and info for escalators or moving walkways alone.
    """

    stations: tuple[str, ...] = ()
    lines: tuple[str, ...] = ()
    equipment: tuple[str, ...] = ("elevator",)
    cooldown_seconds: int = 3600
    kind: str = field(default="lift_outage", init=False)

    @property
    def rule_id(self) -> str:
        station_part = ",".join(sorted({station_key(name) for name in self.stations if station_key(name)}))
        line_part = ",".join(sorted({line_key(name) for name in self.lines if line_key(name)}))
        equipment_part = ",".join(sorted(set(self.equipment)))
        return f"lift_outage:{station_part}|{line_part}|{equipment_part}"

    def evaluate(self, ctx: AlertContext) -> Alert | None:
        observation = ctx.lift
        if observation is None or not observation.groups_read:
            return None
        grouped = _matching_station_records(self, observation)
        if not grouped:
            return None
        faults = faults_by_platform(observation.records, observation.stations)
        station_alerts = [
            _station_alert(name, records, observation, faults) for name, records in grouped.values()
        ]
        return _alert_from_stations(self, observation, station_alerts)


def _parse_lift_names(raw: Any, *, field_name: str, maximum: int) -> tuple[str, ...]:
    values = raw or []
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise ValueError(f"'{field_name}' bir liste olmalı.")
    if len(values) > maximum:
        label = "istasyon" if field_name == "stations" else "hat"
        raise ValueError(f"Bir kuralda en fazla {maximum} {label} izlenebilir.")
    if any(not isinstance(value, str) for value in values):
        raise ValueError(f"'{field_name}' öğeleri metin olmalı.")
    if field_name == "stations" and any(len(value) > MAX_LABEL_CHARS for value in values):
        raise ValueError(f"'stations' öğeleri en fazla {MAX_LABEL_CHARS} karakter olabilir.")
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


def _parse_lift_equipment(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ("elevator",)
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ValueError("'equipment' bir liste olmalı.")
    invalid = sorted(set(str(value) for value in raw) - set(LIFT_EQUIPMENT))
    if invalid:
        raise ValueError(f"'equipment' yalnızca şu değerleri alabilir: {', '.join(LIFT_EQUIPMENT)}.")
    if not raw:
        raise ValueError("lift_outage kuralı için en az bir ekipman türü gerekli.")
    return tuple(dict.fromkeys(str(value) for value in raw))


def parse_lift_rule(raw: Mapping[str, Any], cooldown: int) -> LiftOutageRule:
    """Validate a watched Metro station/line rule without keeping caller data."""
    stations = _parse_lift_names(raw.get("stations"), field_name="stations", maximum=MAX_STATIONS_PER_RULE)
    raw_lines = _parse_lift_names(raw.get("lines"), field_name="lines", maximum=MAX_LINES_PER_RULE)
    if any(not line_key(name) for name in raw_lines):
        raise ValueError("'lines' geçerli metro hat kodları içermeli (örnek: 'M4').")
    lines = tuple(dict.fromkeys(line_key(name) for name in raw_lines))
    if not stations and not lines:
        raise ValueError(
            "lift_outage kuralı için en az bir istasyon ya da hat gerekli (örnek: 'Kartal' ya da 'M4')."
        )
    equipment = _parse_lift_equipment(raw.get("equipment"))
    return LiftOutageRule(stations=stations, lines=lines, equipment=equipment, cooldown_seconds=cooldown)


async def build_lift_observation(source_ctx: SourceContext, equipment: Sequence[str]) -> LiftObservation:
    """Read only requested equipment groups and the station counts needed to classify them."""
    from ibb_mcp.accessibility import STALE_DATA, is_stale
    from ibb_mcp.sources.metro import MetroSource
    from ibb_mcp.sources.metro_equipment import EQUIPMENT_GROUPS, EQUIPMENT_TYPES, MetroEquipmentSource
    from ibb_mcp.text import normalize_tr

    wanted = set(equipment)
    groups = tuple(group for group in EQUIPMENT_GROUPS if EQUIPMENT_TYPES.get(normalize_tr(group)) in wanted)
    snapshot, provenance = await MetroEquipmentSource(source_ctx).snapshot(groups)
    stale = is_stale(provenance, offline=source_ctx.settings.offline)
    uncertainty = set(snapshot.uncertainty)
    if stale:
        uncertainty.add(STALE_DATA)
    if not snapshot.available:
        return LiftObservation(
            records=tuple(snapshot.records),
            stations=(),
            provenance=provenance,
            groups_read=tuple(snapshot.groups_read),
            stale=stale,
            uncertainty=tuple(sorted(uncertainty)),
        )
    stations, _ = await MetroSource(source_ctx).stations()
    return LiftObservation(
        records=tuple(snapshot.records),
        stations=tuple(stations),
        provenance=provenance,
        groups_read=tuple(snapshot.groups_read),
        stale=stale,
        uncertainty=tuple(sorted(uncertainty)),
    )


async def build_lift_context(
    source_ctx: SourceContext,
    rules: Sequence[Rule],
    kinds: set[str],
    unavailable: dict[str, str],
) -> LiftObservation | None:
    if "lift_outage" not in kinds:
        return None
    equipment = {item for rule in rules if isinstance(rule, LiftOutageRule) for item in rule.equipment}
    try:
        observation = await build_lift_observation(source_ctx, sorted(equipment))
    except Exception as exc:  # noqa: BLE001 - an unreadable source must not fail the check
        unavailable["metro_equipment"] = f"Metro ekipman kaydı okunamadı ({type(exc).__name__})."
        return None
    if not observation.groups_read:
        unavailable["metro_equipment"] = "Metro ekipman kaydı yok; asansör durumu doğrulanamadı."
        return None
    return observation


@dataclass(frozen=True)
class _StationAlert:
    name: str
    records: tuple[EquipmentRecord, ...]
    severity: Severity
    message_tr: tuple[str, ...]
    message_en: tuple[str, ...]
    citations: tuple[Citation, ...]
    uncertainty: tuple[str, ...]


def _matching_station_records(
    rule: LiftOutageRule, observation: LiftObservation
) -> dict[str, tuple[str, tuple[EquipmentRecord, ...]]]:
    watched_platforms = {
        platform_key(platform)
        for name in rule.stations
        for platform in resolve_platforms(name, observation.stations)
    }
    watched_lines = {line_key(name) for name in rule.lines if line_key(name)}
    grouped: dict[str, tuple[str, list[EquipmentRecord]]] = {}
    for record in observation.records:
        if record.equipment_type not in rule.equipment:
            continue
        matched = match_station(record, observation.stations)
        by_station = matched is not None and platform_key(matched) in watched_platforms
        by_line = line_key(record.line_name) in watched_lines
        if not (by_station or by_line):
            continue
        name = (matched.name if matched is not None else None) or record.station_name or "Bilinmeyen istasyon"
        key = station_key(name) or f"?{line_key(record.line_name)}"
        if key not in grouped:
            grouped[key] = (name, [])
        grouped[key][1].append(record)
    return {
        key: (name, tuple(sorted(records, key=lambda record: record.outage_id)))
        for key, (name, records) in sorted(grouped.items())
    }


def _station_alert(
    name: str,
    records: tuple[EquipmentRecord, ...],
    observation: LiftObservation,
    faults: dict[tuple[str, str], list[EquipmentRecord]],
) -> _StationAlert:
    platforms = resolve_platforms(name, observation.stations)
    state = lift_state(name, platforms, faults)
    elevator_records = any(record.equipment_type == "elevator" for record in records)
    uncertainty = set(code for record in records for code in record.uncertainty())
    if not elevator_records:
        severity: Severity = "info"
    elif not platforms or state.lift_count is None:
        severity = "warning"
        uncertainty.add(LIFT_COUNT_UNKNOWN)
    elif state.lift_status == "out_of_service" and state.unavailable_lift_count >= state.lift_count:
        severity = "critical"
    else:
        severity = "warning"

    message_tr = [record.describe() for record in records]
    message_en = [_describe_en(record, name) for record in records]
    citations = [
        Citation(label=f"{name} {record.group or 'Ekipman'}", value=record.status_label, provenance=observation.provenance)
        for record in records
    ]
    if platforms and state.lift_count is not None:
        citations.append(
            Citation(
                label=f"{name} kayıtlı asansör",
                value=state.lift_count,
                unit="adet",
                provenance=observation.provenance,
            )
        )
    if severity == "critical":
        count = state.lift_count
        message_tr.append(
            f"İstasyonda kayıtlı {count} asansörün {count}'i kullanılamıyor; İBB kaydına göre adımsız erişim yok."
        )
        message_en.append(
            f"Of the {count} lifts registered at the station, {count} are unavailable; "
            "according to the İBB record, step-free access is unavailable."
        )
    return _StationAlert(
        name=name,
        records=records,
        severity=severity,
        message_tr=tuple(message_tr),
        message_en=tuple(message_en),
        citations=tuple(citations),
        uncertainty=tuple(sorted(uncertainty)),
    )


def _alert_from_stations(
    rule: LiftOutageRule, observation: LiftObservation, station_alerts: list[_StationAlert]
) -> Alert:
    severity = min((item.severity for item in station_alerts), key=_SEVERITY_RANK.__getitem__)
    records = [record for item in station_alerts for record in item.records]
    uncertainty = sorted(
        set(observation.uncertainty).union(code for item in station_alerts for code in item.uncertainty)
    )
    prefix_tr = "Son bilinen durum, doğrulanamadı: " if observation.stale else ""
    prefix_en = "Last known status, not verified: " if observation.stale else ""
    message_tr = prefix_tr + " ".join(sentence for item in station_alerts for sentence in item.message_tr)
    message_en = prefix_en + " ".join(sentence for item in station_alerts for sentence in item.message_en)
    message_tr += f" (Metro İstanbul arızalı ekipman kaydı, {alert_age_tr(observation.provenance)})"
    message_en += f" (Metro İstanbul faulty equipment record, {alert_age_en(observation.provenance)})"
    outage_ids = sorted(record.outage_id for record in records)
    citations = [citation for item in station_alerts for citation in item.citations]
    return Alert(
        rule_id=rule.rule_id,
        kind=rule.kind,
        severity=severity,
        message_tr=message_tr,
        message_en=message_en,
        dedupe_key=f"lift:{alert_digest(*outage_ids)}:{severity}",
        cooldown_seconds=rule.cooldown_seconds,
        citations=citations,
        uncertainty=uncertainty,
    )


def _describe_en(record: EquipmentRecord, station: str) -> str:
    line = f" ({record.line_name})" if record.line_name else ""
    equipment = _EQUIPMENT_EN.get(record.equipment_type, "equipment")
    status = _STATUS_EN.get(record.status_label, record.status_label)
    sentence = f"{station}{line}: {equipment} unavailable; status in the İBB record: {status}."
    if record.ibb_date is not None:
        sentence += f" Date in the İBB record: {record.ibb_date.astimezone(ISTANBUL_TZ):%d.%m.%Y}."
    return sentence
