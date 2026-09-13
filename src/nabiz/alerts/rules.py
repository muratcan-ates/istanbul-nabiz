"""Alert rules: one pure function of a data snapshot per user-visible concern.

**Why the rules are pure.** Every rule takes an :class:`AlertContext` — a snapshot of data
the server already fetched for everybody through the shared ``PoliteClient`` and TTL cache —
and returns an :class:`Alert` or ``None``. A rule performs no I/O, opens no file, keeps no
state between calls and holds no reference to a user, because there is no user record to
hold: the subscription lives in the browser and arrives with the request (see
``docs/privacy.md``). That is what makes each rule testable from a hand-built snapshot, and
what lets the server stay stateless and therefore forgetful by construction.

**Why absent data can never fire an alert.** Every rule reads a missing number as ``None``
and returns ``None``. An alert that fires because İBB was unreachable teaches the user to
ignore alerts, which is worse than sending nothing at all; and the project rule "never
fabricate a number" bites harder when the message is pushed at somebody rather than asked
for.

**Why every alert carries citations.** ``Alert.citations`` names each number the message
says out loud together with the :class:`~ibb_mcp.models.Provenance` it came from, so the
numeric-faithfulness check the eval harness runs over agent answers also works over a
pushed alert.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from ibb_mcp.models import (
    AirQualityReading,
    AirQualityStation,
    MetroLineStatus,
    ParkingLot,
    Provenance,
    TrafficIndexPoint,
    aqi_band,
    describe_traffic,
    utcnow,
)
from ibb_mcp.sources.metro import normalize_tr

Severity = Literal["info", "warning", "critical"]

#: Sort order for a list of alerts; the client shows the worst first.
SEVERITY_ORDER: dict[str, int] = {"critical": 0, "warning": 1, "info": 2}

#: Turkish traffic bands (:func:`~ibb_mcp.models.describe_traffic`) in English.
TRAFFIC_EN = {
    "akıcı": "free flowing",
    "hafif yoğun": "light",
    "yoğun": "busy",
    "çok yoğun": "heavy",
    "kilitli": "gridlocked",
}

AQI_BAND_EN = {
    "good": "good",
    "moderate": "moderate",
    "unhealthy_sensitive": "unhealthy for sensitive groups",
    "unhealthy": "unhealthy",
    "very_unhealthy": "very unhealthy",
    "hazardous": "hazardous",
}

HEALTH_DISCLAIMER_TR = "Sağlık tavsiyesi değildir."
HEALTH_DISCLAIMER_EN = "Not health advice."


# --------------------------------------------------------------------------------------
# alert envelope
# --------------------------------------------------------------------------------------
class Citation(BaseModel):
    """One number an alert states, with the provenance that backs it."""

    label: str
    value: float | int | str | None
    unit: str | None = None
    provenance: Provenance


class Alert(BaseModel):
    """What the server hands back. It is a message, not a record: nothing is persisted.

    ``dedupe_key`` and ``cooldown_seconds`` exist so the *client* can suppress repeats. The
    server cannot do it: remembering "this user already saw this" is precisely the per-user
    state we refuse to keep (``docs/privacy.md``).
    """

    rule_id: str
    kind: str
    severity: Severity = "warning"
    message_tr: str
    message_en: str
    dedupe_key: str
    cooldown_seconds: int
    citations: list[Citation] = Field(default_factory=list)
    created_at: dt.datetime = Field(default_factory=utcnow)

    @property
    def provenance(self) -> list[Provenance]:
        """Provenance of every number cited, in citation order."""
        return [citation.provenance for citation in self.citations]

    def sort_key(self) -> tuple[int, str]:
        return SEVERITY_ORDER.get(self.severity, 9), self.rule_id


# --------------------------------------------------------------------------------------
# the snapshot rules read
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class MetroObservation:
    """Disruption notices as returned by Metro İstanbul.

    An **empty** tuple means "no line carries a notice" — the documented meaning of an empty
    response. A missing observation (``AlertContext.metro is None``) means the service could
    not be read at all, which is a different thing and fires nothing.
    """

    statuses: tuple[MetroLineStatus, ...]
    provenance: Provenance


@dataclass(frozen=True)
class ParkingObservation:
    lot: ParkingLot
    provenance: Provenance


@dataclass(frozen=True)
class AirQualityObservation:
    """The station nearest one of the user's places, resolved server-side, never stored."""

    place_key: str
    place_label: str
    station: AirQualityStation
    reading: AirQualityReading | None
    provenance: Provenance


@dataclass(frozen=True)
class TrafficObservation:
    point: TrafficIndexPoint | None
    provenance: Provenance


@dataclass(frozen=True)
class BunchingObservation:
    """How regular one line's headways were measured to be, for one hour of the day.

    It comes from ``ibb_mcp.reliability``, which reconstructs arrivals from the position
    snapshots this project collects, so it is a **history** figure — "bu hat bu saatte
    genelde kümeleniyor" — and never a live detection. İETT publishes no headway feed, and
    claiming a live one from 60-second position samples would be exactly the invented number
    the charter forbids. The alert says which of the two it is.

    Kept as our own type so :class:`BusBunchingRule` stays pure and testable whether or not
    that module is present; the adapter that fills it lives in :mod:`nabiz.alerts.engine`.
    """

    line_code: str
    bunched: bool
    hour: int | None = None
    label: str | None = None
    headway_cv: float | None = None
    median_headway_min: float | None = None
    samples: int | None = None
    window_note: str | None = None
    provenance: Provenance | None = None


@dataclass(frozen=True)
class AlertContext:
    """Everything the rules may look at. Built once per request, discarded with it."""

    metro: MetroObservation | None = None
    parking: Mapping[int, ParkingObservation] = field(default_factory=dict)
    air_quality: Mapping[str, AirQualityObservation] = field(default_factory=dict)
    traffic: TrafficObservation | None = None
    bunching: Mapping[str, BunchingObservation] = field(default_factory=dict)
    now: dt.datetime = field(default_factory=utcnow)
    #: Sources that could not be read, by source key — reported to the user as "kontrol
    #: edilemedi" instead of being silently treated as "her şey yolunda".
    unavailable: Mapping[str, str] = field(default_factory=dict)


@runtime_checkable
class Rule(Protocol):
    """What the engine needs from a rule. Implementations are frozen dataclasses."""

    @property
    def rule_id(self) -> str: ...

    @property
    def kind(self) -> str: ...

    def evaluate(self, ctx: AlertContext) -> Alert | None: ...


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------
def _digest(*parts: str) -> str:
    """Short, stable hash of free text, for dedupe keys that must not carry a timestamp."""
    joined = "|".join(part.strip() for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:10]


def _age_tr(provenance: Provenance | None) -> str:
    return provenance.describe_age() if provenance else "yaşı bilinmiyor"


def _age_en(provenance: Provenance | None) -> str:
    """English mirror of :meth:`Provenance.describe_age`, same thresholds."""
    if provenance is None:
        return "age unknown"
    seconds = provenance.age_seconds
    if seconds < 90:
        return f"{int(seconds)}s ago"
    if seconds < 5400:
        return f"{int(seconds // 60)} min ago"
    if seconds < 172_800:
        return f"{seconds / 3600:.1f} h ago"
    days = seconds / 86_400
    if days < 60:
        return f"{int(days)} days ago"
    return f"{days / 30:.0f} months ago"


def _tr_number(value: float | None, digits: int = 1) -> str:
    """Format a number the way a Turkish reader expects (comma as the decimal mark)."""
    if value is None:
        return "?"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.{digits}f}".replace(".", ",")


# --------------------------------------------------------------------------------------
# 1. metro disruption
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class MetroDisruptionRule:
    """Fires when Metro İstanbul publishes a notice on one of the watched lines.

    ``GetServiceStatuses`` returns *only* lines that currently carry a notice, so a watched
    line's absence is the answer "bildirilmiş aksaklık yok" and must stay silent. Line names
    are compared with :func:`~ibb_mcp.sources.metro.normalize_tr`, so "m4", "M4" and "M 4"
    are one line.
    """

    lines: tuple[str, ...]
    severity: Severity = "warning"
    cooldown_seconds: int = 3600

    kind: str = field(default="metro_disruption", init=False)

    @property
    def rule_id(self) -> str:
        return f"metro_disruption:{','.join(sorted(line.upper() for line in self.lines))}"

    def evaluate(self, ctx: AlertContext) -> Alert | None:
        if ctx.metro is None:  # service unreadable: silence beats a guess
            return None
        watched = {normalize_tr(line) for line in self.lines if normalize_tr(line)}
        if not watched:
            return None
        hits = [s for s in ctx.metro.statuses if normalize_tr(s.line_name) in watched]
        if not hits:
            return None

        provenance = ctx.metro.provenance
        names = ", ".join(s.line_name or "?" for s in hits)
        details = " ".join((s.description or "").strip() for s in hits if s.description).strip()
        citations = [
            Citation(
                label=f"{s.line_name or '?'} duyurusu",
                value=(s.description or "").strip() or "(açıklama yok)",
                provenance=provenance.model_copy(update={"reported_at": s.updated_at or provenance.reported_at}),
            )
            for s in hits
        ]
        return Alert(
            rule_id=self.rule_id,
            kind=self.kind,
            severity=self.severity,
            message_tr=(
                f"{names} hattında bildirilen aksaklık var."
                f"{' ' + details if details else ''} (Metro İstanbul duyurusu, {_age_tr(provenance)})"
            ),
            message_en=(
                f"Reported disruption on {names}."
                f"{' ' + details if details else ''} (Metro İstanbul notice, {_age_en(provenance)})"
            ),
            dedupe_key=f"metro:{'+'.join(sorted(s.line_name or '?' for s in hits))}:{_digest(details)}",
            cooldown_seconds=self.cooldown_seconds,
            citations=citations,
        )


# --------------------------------------------------------------------------------------
# 2. parking filling up
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ParkingFillingRule:
    """Fires when a watched car park is at or above ``threshold_pct`` occupancy.

    A lot whose ``capacity`` or ``empty`` is missing is skipped rather than assumed full, and
    so is a lot that is not reported open: "kapalı" and "dolu" are different news and only
    one of them is worth interrupting somebody for. Severity is part of the dedupe key, so a
    lot going from 85% to effectively full reaches the user again instead of being swallowed
    by the earlier warning's cooldown.
    """

    park_ids: tuple[int, ...]
    threshold_pct: float = 85.0
    critical_pct: float = 95.0
    cooldown_seconds: int = 1800

    kind: str = field(default="parking_filling", init=False)

    @property
    def rule_id(self) -> str:
        return f"parking_filling:{','.join(str(pid) for pid in sorted(self.park_ids))}@{self.threshold_pct:g}"

    def evaluate(self, ctx: AlertContext) -> Alert | None:
        crossing: list[tuple[ParkingObservation, float]] = []
        for park_id in self.park_ids:
            observation = ctx.parking.get(park_id)
            if observation is None:
                continue
            lot = observation.lot
            if lot.is_open is not True:  # unknown counts as "not reported open"
                continue
            occupancy = lot.occupancy_pct
            if occupancy is None:  # capacity or free count missing
                continue
            if occupancy + 1e-9 >= self.threshold_pct:
                crossing.append((observation, occupancy))
        if not crossing:
            return None

        crossing.sort(key=lambda pair: pair[1], reverse=True)
        worst = crossing[0][1]
        severity: Severity = "critical" if worst + 1e-9 >= self.critical_pct else "warning"

        parts_tr: list[str] = []
        parts_en: list[str] = []
        citations: list[Citation] = []
        for observation, occupancy in crossing:
            lot = observation.lot
            free = lot.empty if lot.empty is not None else 0
            parts_tr.append(f"{lot.name} %{_tr_number(occupancy)} dolu ({lot.capacity} yerin {free} tanesi boş)")
            parts_en.append(f"{lot.name} is {occupancy:g}% full ({free} of {lot.capacity} spaces free)")
            citations.append(
                Citation(label=f"{lot.name} doluluk", value=occupancy, unit="%", provenance=observation.provenance)
            )
            citations.append(
                Citation(label=f"{lot.name} boş yer", value=free, unit="araç", provenance=observation.provenance)
            )

        provenance = crossing[0][0].provenance
        ids = "+".join(str(observation.lot.park_id) for observation, _ in crossing)
        return Alert(
            rule_id=self.rule_id,
            kind=self.kind,
            severity=severity,
            message_tr=f"Takip ettiğiniz otopark doluyor: {'; '.join(parts_tr)}. (İSPARK, {_age_tr(provenance)})",
            message_en=f"A car park you watch is filling up: {'; '.join(parts_en)}. (İSPARK, {_age_en(provenance)})",
            dedupe_key=f"parking:{ids}:ge{self.threshold_pct:g}:{severity}",
            cooldown_seconds=self.cooldown_seconds,
            citations=citations,
        )


# --------------------------------------------------------------------------------------
# 3. air quality
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class AirQualityRule:
    """Fires when the station nearest a place reports an AQI at or above the threshold.

    ``place`` is a *key* into the subscription's own list of places ("home", "work"), never a
    coordinate: the engine resolves the nearest station before the rules run, so no rule ever
    sees a latitude. The dedupe key carries the AQI band rather than the index, so the user
    hears about "orta → sağlıksız" once per step instead of once per hourly wobble.

    İBB computes the PM10 sub-index over a rolling 24-hour mean, so when PM10 dominates the
    message says so — an index that reacts slowly must not be read as "right now".
    """

    place: str
    aqi_threshold: float = 100.0
    cooldown_seconds: int = 10_800

    kind: str = field(default="air_quality", init=False)

    @property
    def rule_id(self) -> str:
        return f"air_quality:{self.place}@{self.aqi_threshold:g}"

    def evaluate(self, ctx: AlertContext) -> Alert | None:
        observation = ctx.air_quality.get(self.place)
        if observation is None or observation.reading is None:
            return None
        reading = observation.reading
        index = reading.aqi_index
        if index is None or index + 1e-9 < self.aqi_threshold:
            return None

        band = aqi_band(index)
        band_label, band_key = band if band else ("bilinmiyor", "unknown")
        severity: Severity = {
            "unhealthy_sensitive": "warning",
            "unhealthy": "critical",
            "very_unhealthy": "critical",
            "hazardous": "critical",
        }.get(band_key, "info")

        provenance = observation.provenance
        citations = [Citation(label="AKİ (AQI)", value=index, provenance=provenance)]
        pm10_tr = pm10_en = ""
        if reading.pm10 is not None:
            citations.append(Citation(label="PM10", value=reading.pm10, unit="µg/m³", provenance=provenance))
            pm10_tr = f" PM10 {_tr_number(reading.pm10)} µg/m³."
            pm10_en = f" PM10 {reading.pm10:g} µg/m³."
        rolling_tr = rolling_en = ""
        if (reading.dominant or "").upper() == "PM10":
            rolling_tr = " İndeks PM10 için 24 saatlik yürüyen ortalamadır, anlık değer değildir."
            rolling_en = " The PM10 sub-index is a rolling 24-hour mean, not an instantaneous value."

        return Alert(
            rule_id=self.rule_id,
            kind=self.kind,
            severity=severity,
            message_tr=(
                f"{observation.place_label} çevresinde hava kalitesi indeksi {_tr_number(index)} "
                f"({band_label}); eşiğiniz {_tr_number(self.aqi_threshold)}.{pm10_tr}"
                f" Ölçüm: {observation.station.name} istasyonu, {_age_tr(provenance)}.{rolling_tr} "
                f"{HEALTH_DISCLAIMER_TR}"
            ),
            message_en=(
                f"Air quality index near {observation.place_label} is {index:g} "
                f"({AQI_BAND_EN.get(band_key, band_key)}); your threshold is {self.aqi_threshold:g}.{pm10_en}"
                f" Measured at {observation.station.name} station, {_age_en(provenance)}.{rolling_en} "
                f"{HEALTH_DISCLAIMER_EN}"
            ),
            dedupe_key=f"air:{self.place}:{band_key}",
            cooldown_seconds=self.cooldown_seconds,
            citations=citations,
        )


# --------------------------------------------------------------------------------------
# 4. traffic
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class TrafficRule:
    """Fires when the city-wide traffic index is at or above the user's threshold.

    The index is one number for the whole city, which is exactly why it needs no location: it
    is the one alert that is useful while knowing nothing at all about the user.
    """

    threshold_index: int = 60
    critical_index: int = 80
    cooldown_seconds: int = 3600

    kind: str = field(default="traffic", init=False)

    @property
    def rule_id(self) -> str:
        return f"traffic:@{self.threshold_index}"

    def evaluate(self, ctx: AlertContext) -> Alert | None:
        if ctx.traffic is None or ctx.traffic.point is None:
            return None
        index = ctx.traffic.point.index
        if index < self.threshold_index:
            return None
        label_tr = describe_traffic(index)
        severity: Severity = "critical" if index >= self.critical_index else "warning"
        provenance = ctx.traffic.provenance
        return Alert(
            rule_id=self.rule_id,
            kind=self.kind,
            severity=severity,
            message_tr=(
                f"İstanbul trafik yoğunluk indeksi {index} ({label_tr}); eşiğiniz {self.threshold_index}. "
                f"(İBB Trafik Yoğunluk İndeksi, {_age_tr(provenance)})"
            ),
            message_en=(
                f"İstanbul traffic index is {index} ({TRAFFIC_EN.get(label_tr, label_tr)}); "
                f"your threshold is {self.threshold_index}. (İBB traffic index, {_age_en(provenance)})"
            ),
            dedupe_key=f"traffic:city:ge{self.threshold_index}:{severity}",
            cooldown_seconds=self.cooldown_seconds,
            citations=[Citation(label="Trafik indeksi", value=index, provenance=provenance)],
        )


# --------------------------------------------------------------------------------------
# 5. bus bunching (optional: needs ibb_mcp.reliability)
# --------------------------------------------------------------------------------------
def reliability_module() -> Any | None:
    """Return ``ibb_mcp.reliability`` if that module exists yet, else ``None``.

    It is being written on another branch. Importing it inside a function, and tolerating its
    absence, is what lets this package ship before it lands — and what keeps a broken
    optional module from taking the whole alert engine down with it.
    """
    try:
        import ibb_mcp.reliability as module
    except Exception:  # noqa: BLE001 - absent *or* broken both mean "not usable"
        return None
    return module


@dataclass(frozen=True)
class BusBunchingRule:
    """Fires when a watched line's measured headways for the current hour are bunched.

    Pure like the others: it reads a :class:`BunchingObservation` the engine put in the
    context. Three things keep it quiet rather than wrong:

    * ``ibb_mcp.reliability`` absent, or its table not built yet — the engine never fills the
      slot, :meth:`available` reports ``False`` and nothing fires;
    * the module's own refusal (too few samples, poor capture rate) — it reports the cell as
      unavailable and the engine does not mark it bunched;
    * an observation with no provenance — a number we cannot attribute is a number we do not
      say, so the rule returns ``None`` instead of an unciteable alert.
    """

    line: str
    min_samples: int = 1
    cooldown_seconds: int = 1800
    severity: Severity = "info"

    kind: str = field(default="bus_bunching", init=False)

    @property
    def rule_id(self) -> str:
        return f"bus_bunching:{self.line.upper()}"

    @staticmethod
    def available() -> bool:
        return reliability_module() is not None

    def evaluate(self, ctx: AlertContext) -> Alert | None:
        observation = ctx.bunching.get(self.line.upper()) or ctx.bunching.get(self.line)
        if observation is None or not observation.bunched or observation.provenance is None:
            return None
        if observation.samples is not None and observation.samples < self.min_samples:
            return None

        provenance = observation.provenance
        line = self.line.upper()
        citations: list[Citation] = []
        facts_tr: list[str] = []
        facts_en: list[str] = []
        if observation.median_headway_min is not None:
            citations.append(
                Citation(
                    label="Ortanca sefer aralığı", value=observation.median_headway_min, unit="dk", provenance=provenance
                )
            )
            facts_tr.append(f"ortanca aralık {_tr_number(observation.median_headway_min)} dk")
            facts_en.append(f"median headway {observation.median_headway_min:g} min")
        if observation.headway_cv is not None:
            citations.append(Citation(label="Aralık değişkenliği (cv)", value=observation.headway_cv, provenance=provenance))
            facts_tr.append(f"değişkenlik cv {_tr_number(observation.headway_cv, digits=2)}")
            facts_en.append(f"headway cv {observation.headway_cv:g}")
        if observation.samples is not None:
            citations.append(Citation(label="Gözlem sayısı", value=observation.samples, provenance=provenance))

        hour_tr = f"saat {observation.hour:02d} civarında " if observation.hour is not None else ""
        hour_en = f"around {observation.hour:02d}:00 " if observation.hour is not None else ""
        label = observation.label or "kümelenme var"
        detail_tr = f": {', '.join(facts_tr)}" if facts_tr else ""
        detail_en = f": {', '.join(facts_en)}" if facts_en else ""
        window_tr = f" {observation.window_note}" if observation.window_note else ""
        return Alert(
            rule_id=self.rule_id,
            kind=self.kind,
            severity=self.severity,
            message_tr=(
                f"{line} hattında {hour_tr}ölçülen sefer aralıkları düzensiz ({label}){detail_tr}. "
                "Bu, geçmiş gözlemlerin özetidir; canlı bir arıza bildirimi değildir."
                f"{window_tr} (Nabız hat düzenlilik ölçümü, {_age_tr(provenance)})"
            ),
            message_en=(
                f"Headways measured on {line} {hour_en}are irregular ({label}){detail_en}. "
                "This summarises past observations; it is not a live disruption notice. "
                f"(Nabız headway measurement, {_age_en(provenance)})"
            ),
            dedupe_key=f"bunching:{line}:{observation.hour if observation.hour is not None else 'any'}",
            cooldown_seconds=self.cooldown_seconds,
            citations=citations,
        )


def evaluate_rules(rules: Sequence[Rule], ctx: AlertContext) -> list[Alert]:
    """Run every rule over one snapshot, worst severity first. No I/O, no state."""
    alerts = [alert for rule in rules if (alert := rule.evaluate(ctx)) is not None]
    alerts.sort(key=lambda alert: alert.sort_key())
    return alerts
