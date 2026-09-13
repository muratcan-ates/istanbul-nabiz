"""The alert engine: turn a client-held subscription into alerts, and remember nothing.

The shape of this module is dictated by one constraint from the project charter: **no user
location, profile or history may be stored server-side** (KVKK; ``docs/NABIZ.md`` §1.3). So:

* the *subscription* — home/work coordinates, watched lines, thresholds — lives in the
  browser's ``localStorage`` and travels with each request;
* :func:`build_context` reads only data the server already holds for everybody (through the
  shared ``PoliteClient`` and TTL cache), plus, for air quality, the nearest station to a
  coordinate that exists in memory for the duration of one request;
* :func:`evaluate_subscription` is a pure function of ``(subscription, context)`` — it opens
  no file, writes no database row and logs no coordinate;
* **the cooldown is enforced by the client.** The server returns a ``dedupe_key`` and a
  ``cooldown_seconds`` per alert and forgets both. To suppress a repeat server-side we would
  have to keep "this user already saw key K at time T", which is a per-user history — the one
  thing this design refuses to hold. The client stores the last-seen time per key in
  ``localStorage``, which also makes the suppression survive a server restart and a scale-out
  to several replicas, neither of which a process-local table would.

A request may carry ``muted_keys``: the keys the client is currently sitting on. They are used
to filter this response and are discarded with the request — request-scoped input, not state.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import pathlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from ibb_mcp.config import ATTRIBUTION, ATTRIBUTION_EN
from ibb_mcp.models import ISTANBUL_TZ, LAT_RANGE, LON_RANGE, Provenance, utcnow
from ibb_mcp.sources.base import SourceContext
from nabiz.alerts.rules import (
    AirQualityObservation,
    AirQualityRule,
    Alert,
    AlertContext,
    BunchingObservation,
    BusBunchingRule,
    MetroDisruptionRule,
    MetroObservation,
    ParkingFillingRule,
    ParkingObservation,
    Rule,
    TrafficObservation,
    TrafficRule,
    evaluate_rules,
    reliability_module,
)

log = logging.getLogger("nabiz.alerts")

#: Suggested client-side cooldown per rule kind, in seconds. Tuned to how fast the underlying
#: number can legitimately change: parking occupancy moves in minutes, an air-quality index
#: built on a 24-hour mean moves in hours.
DEFAULT_COOLDOWNS: dict[str, int] = {
    "metro_disruption": 3600,
    "parking_filling": 1800,
    "air_quality": 10_800,
    "traffic": 3600,
    "bus_bunching": 1800,
}
MIN_COOLDOWN_S = 300
MAX_COOLDOWN_S = 86_400

#: Bounds on one subscription. They cap the work a single request can ask for — the upstream
#: budget is shared with every other user of İBB's gateway, not ours to spend freely.
MAX_RULES = 20
MAX_PLACES = 5
MAX_PARK_IDS = 10

KNOWN_KINDS = frozenset(DEFAULT_COOLDOWNS)


@dataclass(frozen=True)
class Place:
    """One of the user's places, as sent by the client. Never persisted, never logged."""

    key: str
    label: str
    lat: float
    lon: float


@dataclass(frozen=True)
class ParsedSubscription:
    rules: tuple[Rule, ...] = ()
    places: Mapping[str, Place] = field(default_factory=dict)
    muted_keys: frozenset[str] = frozenset()
    #: Rule kinds present in the payload that this server does not implement. Skipped rather
    #: than rejected, so a newer client talking to an older server still gets its other alerts.
    skipped_kinds: tuple[str, ...] = ()

    def kinds(self) -> set[str]:
        return {rule.kind for rule in self.rules}


# --------------------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------------------
def _as_float(value: Any, *, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"'{field_name}' sayı olmalı.") from None


def _cooldown_for(kind: str, raw: Mapping[str, Any]) -> int:
    """Client-supplied cooldown, clamped. A zero-cooldown rule would be a spam machine."""
    value = raw.get("cooldown_seconds")
    if value is None:
        return DEFAULT_COOLDOWNS[kind]
    seconds = int(_as_float(value, field_name="cooldown_seconds"))
    return max(MIN_COOLDOWN_S, min(MAX_COOLDOWN_S, seconds))


def _parse_places(subscription: Mapping[str, Any]) -> dict[str, Place]:
    """Read the client's places. Coordinates are validated but never echoed in an error.

    An error string reaches the web layer and could reach a log; a place key ("home") is
    enough to tell the user which entry is wrong, and carries nothing about where they live.
    """
    raw_places = subscription.get("places") or []
    if not isinstance(raw_places, Sequence) or isinstance(raw_places, (str, bytes)):
        raise ValueError("'places' bir liste olmalı.")
    if len(raw_places) > MAX_PLACES:
        raise ValueError(f"En fazla {MAX_PLACES} konum tanımlanabilir.")

    places: dict[str, Place] = {}
    for entry in raw_places:
        if not isinstance(entry, Mapping):
            raise ValueError("Her konum bir nesne olmalı: {key, label, lat, lon}.")
        key = str(entry.get("key") or "").strip()
        if not key:
            raise ValueError("Her konumun bir 'key' alanı olmalı (örnek: 'home').")
        lat = _as_float(entry.get("lat"), field_name=f"places[{key}].lat")
        lon = _as_float(entry.get("lon"), field_name=f"places[{key}].lon")
        if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
            raise ValueError(f"'{key}' konumu İstanbul sınırları dışında; bu servis yalnızca İstanbul verisi sunar.")
        label = str(entry.get("label") or key).strip()
        places[key] = Place(key=key, label=label, lat=lat, lon=lon)
    return places


def _parse_rule(raw: Mapping[str, Any], places: Mapping[str, Place]) -> Rule | None:
    """Build one typed rule. Returns ``None`` for a kind this server does not implement."""
    kind = str(raw.get("kind") or "").strip()
    if kind not in KNOWN_KINDS:
        return None
    cooldown = _cooldown_for(kind, raw)

    if kind == "metro_disruption":
        lines = tuple(str(line).strip() for line in (raw.get("lines") or []) if str(line).strip())
        if not lines:
            raise ValueError("metro_disruption kuralı için en az bir hat adı gerekli (örnek: 'M4').")
        return MetroDisruptionRule(lines=lines, cooldown_seconds=cooldown)

    if kind == "parking_filling":
        ids = raw.get("park_ids") or []
        if not isinstance(ids, Sequence) or isinstance(ids, (str, bytes)) or not ids:
            raise ValueError("parking_filling kuralı için en az bir otopark id'si gerekli.")
        if len(ids) > MAX_PARK_IDS:
            raise ValueError(f"Bir kuralda en fazla {MAX_PARK_IDS} otopark izlenebilir.")
        park_ids = tuple(int(_as_float(pid, field_name="park_ids")) for pid in ids)
        threshold = _as_float(raw.get("threshold_pct", 85), field_name="threshold_pct")
        if not 1 <= threshold <= 100:
            raise ValueError("threshold_pct 1 ile 100 arasında olmalı.")
        return ParkingFillingRule(park_ids=park_ids, threshold_pct=threshold, cooldown_seconds=cooldown)

    if kind == "air_quality":
        place = str(raw.get("place") or "").strip()
        if place not in places:
            raise ValueError(f"air_quality kuralının 'place' alanı tanımlı konumlardan biri olmalı: {sorted(places)}")
        threshold = _as_float(raw.get("aqi_threshold", 100), field_name="aqi_threshold")
        if not 1 <= threshold <= 500:
            raise ValueError("aqi_threshold 1 ile 500 arasında olmalı.")
        return AirQualityRule(place=place, aqi_threshold=threshold, cooldown_seconds=cooldown)

    if kind == "traffic":
        threshold = int(_as_float(raw.get("threshold_index", 60), field_name="threshold_index"))
        if not 1 <= threshold <= 99:
            raise ValueError("threshold_index 1 ile 99 arasında olmalı (İBB indeksi bu aralıkta).")
        return TrafficRule(threshold_index=threshold, cooldown_seconds=cooldown)

    line = str(raw.get("line") or "").strip()  # bus_bunching
    if not line:
        raise ValueError("bus_bunching kuralı için bir hat kodu gerekli (örnek: '500T').")
    return BusBunchingRule(line=line, cooldown_seconds=cooldown)


def parse_subscription(subscription: Mapping[str, Any]) -> ParsedSubscription:
    """Validate the client's payload into typed rules. Raises :class:`ValueError` on bad input.

    Unknown rule *kinds* are skipped instead of rejected: a subscription written by a newer
    client must not lose its metro alerts because this server has never heard of its new
    fifth rule.
    """
    if not isinstance(subscription, Mapping):
        raise ValueError("Abonelik bir nesne olmalı.")
    raw_rules = subscription.get("rules") or []
    if not isinstance(raw_rules, Sequence) or isinstance(raw_rules, (str, bytes)):
        raise ValueError("'rules' bir liste olmalı.")
    if len(raw_rules) > MAX_RULES:
        raise ValueError(f"Bir abonelikte en fazla {MAX_RULES} kural olabilir.")

    places = _parse_places(subscription)
    rules: list[Rule] = []
    skipped: list[str] = []
    for entry in raw_rules:
        if not isinstance(entry, Mapping):
            raise ValueError("Her kural bir nesne olmalı: {kind: ...}.")
        rule = _parse_rule(entry, places)
        if rule is None:
            skipped.append(str(entry.get("kind") or "?"))
            continue
        rules.append(rule)

    muted = subscription.get("muted_keys") or []
    if not isinstance(muted, Iterable) or isinstance(muted, (str, bytes)):
        raise ValueError("'muted_keys' bir liste olmalı.")
    return ParsedSubscription(
        rules=tuple(rules),
        places=places,
        muted_keys=frozenset(str(key) for key in muted),
        skipped_kinds=tuple(skipped),
    )


def describe_subscription(parsed: ParsedSubscription) -> str:
    """A log-safe summary: rule kinds and counts only — no coordinates, no labels, no keys."""
    counts: dict[str, int] = {}
    for rule in parsed.rules:
        counts[rule.kind] = counts.get(rule.kind, 0) + 1
    kinds = ", ".join(f"{kind}x{count}" for kind, count in sorted(counts.items())) or "yok"
    return f"rules=[{kinds}] places={len(parsed.places)}"


# --------------------------------------------------------------------------------------
# evaluation (pure)
# --------------------------------------------------------------------------------------
def _ensure_parsed(subscription: Mapping[str, Any] | ParsedSubscription) -> ParsedSubscription:
    """Accept either the raw client payload or an already-validated one.

    :func:`check_alerts` parses once and passes the result to both halves; a caller holding a
    plain dict (the MCP tool, a test) still gets it validated.
    """
    return subscription if isinstance(subscription, ParsedSubscription) else parse_subscription(subscription)


def evaluate_subscription(
    subscription: Mapping[str, Any] | ParsedSubscription, ctx: AlertContext
) -> list[Alert]:
    """Evaluate one subscription against one snapshot. Pure: no I/O, no persistence.

    Alerts whose ``dedupe_key`` the client says it is already sitting on are dropped here, so
    a quiet response costs the client nothing to ignore.
    """
    parsed = _ensure_parsed(subscription)
    alerts = [alert for alert in evaluate_rules(parsed.rules, ctx) if alert.dedupe_key not in parsed.muted_keys]
    # Log-safe by construction: counts and rule kinds only. Never the subscription itself.
    log.debug("alerts evaluated: %s -> %d alert", describe_subscription(parsed), len(alerts))
    return alerts


# --------------------------------------------------------------------------------------
# context building (I/O, shared data only)
# --------------------------------------------------------------------------------------
async def _metro_observation(source_ctx: SourceContext) -> MetroObservation:
    from ibb_mcp.sources.metro import MetroSource

    statuses, provenance = await MetroSource(source_ctx).service_status()
    return MetroObservation(statuses=tuple(statuses), provenance=provenance)


async def _parking_observations(source_ctx: SourceContext, park_ids: set[int]) -> dict[int, ParkingObservation]:
    """One list call for every watched lot; ``ParkDetay`` is not needed for occupancy."""
    from ibb_mcp.sources.ispark import IsparkSource

    lots, provenance = await IsparkSource(source_ctx).list_parks()
    return {lot.park_id: ParkingObservation(lot=lot, provenance=provenance) for lot in lots if lot.park_id in park_ids}


async def _air_quality_observations(
    source_ctx: SourceContext, places: Iterable[Place]
) -> dict[str, AirQualityObservation]:
    """Resolve each place to its nearest station and read that station's latest measurement.

    This is the only place a user coordinate is touched at all. It stays in local variables
    for the length of the call: it is not written to the cache key, not logged, and not part
    of the returned observation, which carries the *station* instead.
    """
    from ibb_mcp.sources.airquality import AirQualitySource

    source = AirQualitySource(source_ctx)
    observations: dict[str, AirQualityObservation] = {}
    for place in places:
        station = await source.nearest_station(place.lat, place.lon)
        if station is None:
            continue
        reading, provenance = await source.latest(station.station_id)
        observations[place.key] = AirQualityObservation(
            place_key=place.key,
            place_label=place.label,
            station=station,
            reading=reading,
            provenance=provenance,
        )
    return observations


async def _traffic_observation(source_ctx: SourceContext) -> TrafficObservation:
    from ibb_mcp.sources.traffic import TrafficSource

    point, provenance = await TrafficSource(source_ctx).current()
    return TrafficObservation(point=point, provenance=provenance)


def _coerce_bunching(line: str, hour: int, cell: Any, provenance: Provenance) -> BunchingObservation | None:
    """Map one ``ibb_mcp.reliability`` cell onto our own typed observation.

    That module is written by another chat and may still move, so fields are read by name
    from either a mapping (``describe_cell``) or an object (``LineHourStats``) and anything
    unfamiliar is dropped. A cell the module marks unavailable — too few samples, capture
    rate too low — is *not* an absence of bunching and must not become an alert either way:
    it becomes ``None``.
    """
    if cell is None:
        return None

    def pick(*names: str) -> Any:
        for name in names:
            if isinstance(cell, Mapping):
                if name in cell:
                    return cell[name]
            elif hasattr(cell, name):
                return getattr(cell, name)
        return None

    if not pick("available"):
        return None
    label = pick("bunching_label", "label")
    bunched_label = getattr(reliability_module(), "LABEL_BUNCHED", "kümelenme var")
    return BunchingObservation(
        line_code=line.upper(),
        bunched=str(label) == str(bunched_label),
        hour=hour,
        label=str(label) if label else None,
        headway_cv=(float(v) if (v := pick("headway_cv")) is not None else None),
        median_headway_min=(float(v) if (v := pick("median_headway_min")) is not None else None),
        samples=(int(v) if (v := pick("samples")) is not None else None),
        window_note=_window_note(pick("observation_window")),
        provenance=provenance,
    )


def _window_note(window: Any) -> str | None:
    """Turn the reliability table's observation window into one Turkish clause.

    A reliability figure without the span it was measured over invites the reader to hear
    "always"; two partial days are not always.
    """
    if not isinstance(window, Mapping):
        return None
    days = window.get("days_covered") or []
    hours = window.get("hours")
    if not days and hours is None:
        return None
    parts = []
    if days:
        parts.append(f"{len(days)} gün")
    if hours is not None:
        parts.append(f"{hours} saatlik gözlem")
    return f"Ölçüm penceresi: {', '.join(parts)}."


@lru_cache(maxsize=4)
def _cached_table(path: str, mtime_ns: int) -> Any:
    """Load the reliability table once per file version, not once per request.

    Keyed on the file's mtime so a freshly rebuilt table is picked up without a restart.
    This caches a *public* measurement table; nothing here is user state.
    """
    from ibb_mcp.reliability import load_table

    return load_table(path)


def _reliability_table() -> tuple[Any, str | None]:
    module = reliability_module()
    if module is None:
        return None, "Hat düzenlilik modülü bu sürümde yok."
    path = pathlib.Path(getattr(module, "DEFAULT_TABLE_PATH", ""))
    if not path.exists():
        return None, "Hat düzenlilik tablosu henüz üretilmedi (scripts/reliability_report.py)."
    table = _cached_table(str(path), path.stat().st_mtime_ns)
    if table is None:
        return None, "Hat düzenlilik tablosu okunamadı."
    return table, None


async def _bunching_observations(
    lines: set[str], now: dt.datetime
) -> tuple[dict[str, BunchingObservation], str | None]:
    """Look each watched line up in the measured reliability table for the current hour.

    Reads a local JSON file, never İBB: the table is built offline by
    ``scripts/reliability_report.py`` from snapshots we already collected.
    """
    module = reliability_module()
    table, problem = _reliability_table()
    if table is None:
        return {}, problem
    describe = getattr(module, "describe_cell", None)
    if describe is None:
        return {}, "Hat düzenlilik modülü beklenen arayüzü sunmuyor."

    hour = now.astimezone(ISTANBUL_TZ).hour
    generated = getattr(table, "observed_to", None) or getattr(table, "generated_at", None)
    provenance = Provenance(
        source="nabiz_reliability",
        source_url=f"local:{getattr(module, 'DEFAULT_TABLE_PATH', 'line_reliability.json')}",
        reported_at=generated if isinstance(generated, dt.datetime) else None,
    )
    observations: dict[str, BunchingObservation] = {}
    for line in lines:
        cell = await asyncio.to_thread(describe, table, line, hour)
        observation = _coerce_bunching(line, hour, cell, provenance)
        if observation is not None:
            observations[observation.line_code] = observation
    return observations, None if observations else "İzlenen hatlar için ölçülmüş düzenlilik verisi yok."


async def build_context(
    source_ctx: SourceContext,
    subscription: Mapping[str, Any] | ParsedSubscription,
    *,
    now: dt.datetime | None = None,
) -> AlertContext:
    """Fetch exactly the shared data this subscription's rules need, and nothing else.

    Every fetch is individually guarded: one dead upstream costs the user that one class of
    alert (reported in ``unavailable``) instead of the whole check. Nothing here writes to
    disk, and the only user-derived values that appear are the coordinates handed to the
    nearest-station search, which never leave the call.
    """
    parsed = _ensure_parsed(subscription)
    kinds = parsed.kinds()
    unavailable: dict[str, str] = {}

    metro = traffic = None
    parking: dict[int, ParkingObservation] = {}
    air_quality: dict[str, AirQualityObservation] = {}
    bunching: dict[str, BunchingObservation] = {}

    if "metro_disruption" in kinds:
        try:
            metro = await _metro_observation(source_ctx)
        except Exception as exc:  # noqa: BLE001 - an unreadable source must not fail the check
            unavailable["metro_status"] = f"Metro durum servisi okunamadı ({type(exc).__name__})."

    if "parking_filling" in kinds:
        park_ids = {pid for rule in parsed.rules if isinstance(rule, ParkingFillingRule) for pid in rule.park_ids}
        try:
            parking = await _parking_observations(source_ctx, park_ids)
        except Exception as exc:  # noqa: BLE001
            unavailable["ispark"] = f"İSPARK listesi okunamadı ({type(exc).__name__})."

    if "air_quality" in kinds:
        wanted = {rule.place for rule in parsed.rules if isinstance(rule, AirQualityRule)}
        try:
            air_quality = await _air_quality_observations(
                source_ctx, [place for key, place in parsed.places.items() if key in wanted]
            )
        except Exception as exc:  # noqa: BLE001
            unavailable["aq_readings"] = f"Hava kalitesi servisi okunamadı ({type(exc).__name__})."

    if "traffic" in kinds:
        try:
            traffic = await _traffic_observation(source_ctx)
        except Exception as exc:  # noqa: BLE001
            unavailable["traffic"] = f"Trafik indeksi okunamadı ({type(exc).__name__})."

    if "bus_bunching" in kinds:
        lines = {rule.line.upper() for rule in parsed.rules if isinstance(rule, BusBunchingRule)}
        try:
            bunching, problem = await _bunching_observations(lines, now or utcnow())
        except Exception as exc:  # noqa: BLE001
            bunching, problem = {}, f"Hat düzenliliği hesaplanamadı ({type(exc).__name__})."
        if problem:
            unavailable["reliability"] = problem

    return AlertContext(
        metro=metro,
        parking=parking,
        air_quality=air_quality,
        traffic=traffic,
        bunching=bunching,
        now=now or utcnow(),
        unavailable=unavailable,
    )


# --------------------------------------------------------------------------------------
# the call the MCP tool and the web route both make
# --------------------------------------------------------------------------------------
COOLDOWN_POLICY = {
    "enforced_by": "client",
    "why_tr": (
        "Sunucu hiçbir kullanıcı kaydı tutmadığı için 'bu uyarıyı zaten gördü' bilgisini de tutmaz. "
        "İstemci her dedupe_key için son gösterim zamanını localStorage'da saklar ve cooldown_seconds "
        "dolmadan aynı uyarıyı tekrar göstermez."
    ),
    "why_en": (
        "The server keeps no user record, so it cannot keep 'already seen' either. The client stores the "
        "last shown time per dedupe_key in localStorage and suppresses the same key until cooldown_seconds "
        "have passed."
    ),
    "min_seconds": MIN_COOLDOWN_S,
    "max_seconds": MAX_COOLDOWN_S,
}

PRIVACY_SUMMARY = {
    "stored_server_side": "none",
    "logged": "kural türleri ve sayıları; konum, etiket veya eşik değeri loglanmaz",
    "retention": "0",
    "document": "docs/privacy.md",
}


async def check_alerts(
    source_ctx: SourceContext, subscription: Mapping[str, Any] | ParsedSubscription
) -> dict[str, Any]:
    """Build the snapshot, evaluate the subscription and return a JSON-ready payload.

    This is the whole server side of E2: the MCP tool and the FastAPI route are two thin
    wrappers around this one call, and neither of them has anywhere to write a user record
    even if it wanted to.
    """
    parsed = _ensure_parsed(subscription)
    ctx = await build_context(source_ctx, parsed)
    alerts = evaluate_subscription(parsed, ctx)
    return {
        "checked_at": ctx.now.isoformat(),
        "alert_count": len(alerts),
        "alerts": [alert.model_dump(mode="json") for alert in alerts],
        "unavailable": dict(ctx.unavailable),
        "skipped_rule_kinds": list(parsed.skipped_kinds),
        "cooldown_policy": COOLDOWN_POLICY,
        "privacy": PRIVACY_SUMMARY,
        "attribution": {"tr": ATTRIBUTION, "en": ATTRIBUTION_EN},
        "disclaimer": "Uyarılar tahminidir ve resmi İBB duyurusu değildir; sağlık tavsiyesi içermez.",
    }
