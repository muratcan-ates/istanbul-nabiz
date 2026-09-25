"""İBB data in, ``nexus_core`` signals out: the console's two small adapters.

The decision core never fetches anything (DECISIONS #21); the console hands it signals and the
evidence each one rests on. Two sources feed it, both through the shared facade and its cache,
so no visitor's request ever becomes an upstream call of its own (DECISIONS #3):

* **Metro equipment** (:func:`equipment_incoming`): ``Nabiz.metro_equipment_signals`` gives
  the candidates ``ibb_mcp.equipment_signals`` builds from one snapshot (a lift or escalator
  out, a long outage, several faults at one interchange, stale data). The record's own text is
  the evidence, and a lift's alternative adds the metro graph's reasoning as a second item.
* **The city watch** (:func:`alert_incoming`): the alert engine (``ibb_mcp.alerts``) run over
  :data:`CITY_WATCH`, the console's fixed list of car parks, one place for air quality and one
  bus line. Each alert becomes one signal whose ``text`` is the alert's own message, with every
  number it cites as a piece of evidence carrying that number's provenance.

A signal's time is the time its data was observed (the snapshot, the cited reading), never the
time the console looked, so replaying one recording gives the same signal ids and the ledger
does not count a re-read as a new event.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ibb_mcp.models import Provenance, ToolResult
from nexus_core import EvidenceItem, Origin, Signal

#: The source name shown for the alternative's reasoning: Nabız's own estimate over İBB's
#: station list, not a second İBB feed.
GRAPH_SOURCE = "Nabız metro grafiği (tahmin)"
EVIDENCE_MAX = 600

#: Alert kinds (``ibb_mcp.alerts``) and the signal kinds ``missions/sehir_nabzi.toml`` routes.
ALERT_KINDS: dict[str, str] = {
    "parking_filling": "parking_full",
    "air_quality": "air_quality",
    "bus_bunching": "bus_bunching",
}
OPERATOR_LEAD = {
    "parking_full": "İzlenen otopark eşiği geçti",
    "air_quality": "İzlenen yerde hava kalitesi eşiği geçti (sağlık tavsiyesi değildir)",
    "bus_bunching": "İzlenen hatta ölçülmüş yığılma geçmişi (canlı tespit değildir)",
}

#: The console's watch list. A design parameter, not a measurement: two large İSPARK car parks
#: that are in the recorded fixtures, Taksim Meydanı (``data/reference/places.csv``) for the
#: nearest air-quality station, and 500T, the line the recorded fixtures follow. The car parks
#: can be replaced with ``NABIZ_CONSOLE_WATCH_PARKS`` (comma-separated İSPARK park ids).
DEFAULT_WATCH_PARKS: tuple[int, ...] = (3068, 2916)
WATCH_PLACE = {"key": "taksim", "label": "Taksim Meydanı", "lat": 41.037, "lon": 28.985}
WATCH_LINE = "500T"


@dataclass(frozen=True)
class Incoming:
    """One signal and the evidence the Arena reads if it goes to a person."""

    signal: Signal
    evidence: tuple[EvidenceItem, ...]


def watch_parks(env: Mapping[str, str] | None = None) -> tuple[int, ...]:
    raw = (os.environ if env is None else env).get("NABIZ_CONSOLE_WATCH_PARKS", "")
    ids = tuple(int(part) for part in raw.split(",") if part.strip().isdigit())
    return ids or DEFAULT_WATCH_PARKS


def city_watch(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """The alert subscription the console evaluates. Public places only; nothing about a person."""
    return {
        "places": [WATCH_PLACE],
        "rules": [
            {"kind": "parking_filling", "park_ids": list(watch_parks(env))},
            {"kind": "air_quality", "place": WATCH_PLACE["key"]},
            {"kind": "bus_bunching", "line": WATCH_LINE},
        ],
    }


CITY_WATCH = city_watch({})


def origin_from(prov: Provenance, mode: str) -> Origin:
    """The decision core's :class:`Origin` for an İBB provenance: İBB's own time when it gave one."""
    return Origin(
        source=prov.source,
        url=prov.source_url or None,
        observed_at=prov.reported_at or prov.observed_at,
        mode="recorded" if mode == "recorded" else "live",
    )


def _trim(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= EVIDENCE_MAX else text[: EVIDENCE_MAX - 1] + "…"


def _parse_time(value: Any, default: dt.datetime) -> dt.datetime:
    if isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value)
        except ValueError:
            return default
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
    return default


# --------------------------------------------------------------------------------------
# Metro equipment
# --------------------------------------------------------------------------------------
def equipment_evidence(signal: Signal) -> tuple[EvidenceItem, ...]:
    """The record's own words first; for a lift with an alternative, the graph's reasoning second."""
    payload = signal.payload
    if signal.kind == "hub_faults":
        text = f"{payload.get('hub')}: {payload.get('equipment_list')}"
    elif signal.kind == "source_stale":
        text = f"Metro ekipman kaydı en son {payload.get('age_text')} okundu. {payload.get('last_known_text')}"
    else:
        text = payload.get("text") or f"{signal.title}: {payload.get('station') or signal.entity_id}"
    items = [EvidenceItem(text=_trim(text), provenance=signal.provenance)]
    reason = payload.get("alternative_reason")
    if isinstance(reason, str) and reason:
        graph = signal.provenance.model_copy(update={"source": GRAPH_SOURCE, "url": None})
        items.append(EvidenceItem(text=_trim(reason), provenance=graph))
    return tuple(items)


def equipment_incoming(result: ToolResult) -> list[Incoming]:
    """Signals from one ``metro_equipment_signals`` answer; none when the record could not be read."""
    data = result.data or {}
    origin = origin_from(result.provenance, data.get("mode", "live"))
    observed = _parse_time(data.get("observed_at"), origin.observed_at or dt.datetime.now(dt.UTC))
    out: list[Incoming] = []
    for raw in data.get("signals") or []:
        signal = Signal.create(
            kind=raw["kind"],
            entity_id=raw["entity_id"],
            severity=raw["severity"],
            observed_at=observed,
            provenance=origin,
            payload=raw.get("payload") or {},
        )
        out.append(Incoming(signal, equipment_evidence(signal)))
    return out


# --------------------------------------------------------------------------------------
# the city watch (ibb_mcp.alerts)
# --------------------------------------------------------------------------------------
def _citation_text(citation: Mapping[str, Any]) -> str:
    value, unit = citation.get("value"), citation.get("unit")
    shown = "bilinmiyor" if value is None else f"{value}{' ' + unit if unit else ''}"
    return _trim(f"{citation.get('label')}: {shown}")


def operator_text(kind: str, citations: Sequence[Mapping[str, Any]]) -> str:
    """An operator-facing alert summary, separate from the citizen publication text."""
    lead = OPERATOR_LEAD.get(kind, "İzlenen şehir eşiği geçti")
    details = "; ".join(_citation_text(citation) for citation in citations)
    return _trim(f"{lead}: {details}")


def _alert_signal(alert: Mapping[str, Any], mode: str) -> Incoming | None:
    kind = ALERT_KINDS.get(str(alert.get("kind")))
    message = str(alert.get("message_tr") or "").strip()
    if kind is None or not message:
        return None
    citations: Sequence[Mapping[str, Any]] = alert.get("citations") or []
    origins = [origin_from(Provenance.model_validate(c["provenance"]), mode) for c in citations if c.get("provenance")]
    created = _parse_time(alert.get("created_at"), dt.datetime.now(dt.UTC))
    origin = origins[0] if origins else Origin(source="nabiz_alerts", url=None, observed_at=created, mode="unknown")
    observed = max((o.observed_at for o in origins if o.observed_at is not None), default=created)
    payload = {
        "text": message,
        "operator_text": operator_text(kind, citations),
        "alert_rule": alert.get("rule_id"),
        "dedupe_key": alert.get("dedupe_key"),
    }
    severity = alert.get("severity") if alert.get("severity") in {"info", "warning", "critical"} else "warning"
    signal = Signal.create(
        kind=kind,
        entity_id=f"alert:{alert.get('dedupe_key') or kind}"[:200],
        severity=severity,
        observed_at=observed,
        provenance=origin,
        payload=payload,
    )
    evidence = tuple(EvidenceItem(text=_citation_text(c), provenance=o) for c, o in zip(citations, origins, strict=False)) or (
        EvidenceItem(text=_trim(message), provenance=origin),
    )
    return Incoming(signal, evidence)


def alert_incoming(result: ToolResult, *, offline: bool) -> list[Incoming]:
    """Signals from one ``check_alerts`` answer over :data:`CITY_WATCH`; unknown alert kinds are skipped."""
    mode = "recorded" if offline else "live"
    alerts = (result.data or {}).get("alerts") or []
    return [one for alert in alerts if (one := _alert_signal(alert, mode)) is not None]
