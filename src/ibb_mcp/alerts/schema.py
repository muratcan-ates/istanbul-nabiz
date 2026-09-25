"""The typed shape of an alert subscription, as the MCP ``check_alerts`` tool advertises it.

The MCP SDK derives a tool's JSON schema from its signature. Typed as ``dict`` the
subscription would reach a model as an opaque ``{"type": "object"}``, and the model would
have to guess field names that :func:`ibb_mcp.alerts.engine.parse_subscription` then rejects.
These classes exist only to *describe* the payload: after the SDK has validated it into them
it is dumped back to a plain dict and handed to the engine, which stays the single source of
truth for validation. That is why numeric ranges live in the field descriptions rather than
as ``ge``/``le`` constraints — the engine's Turkish refusal is the one the user should see,
and it never echoes a coordinate back (``docs/privacy.md`` §4).

Every limit quoted here is imported from the module that enforces it, so the description
cannot drift from its parser.

String and list *lengths* are the exception, and are enforced here: they bound the work a
request can cause, not the meaning of a field, and the engine has no reason to see a
100 000-character place key. Refusing those at the schema echoes back no coordinate.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from ibb_mcp.alerts.engine import (
    AQI_THRESHOLD_RANGE,
    DEFAULT_AQI_THRESHOLD,
    DEFAULT_COOLDOWNS,
    DEFAULT_PARKING_THRESHOLD_PCT,
    DEFAULT_TRAFFIC_THRESHOLD,
    MAX_COOLDOWN_S,
    MAX_PARK_IDS,
    MAX_PLACES,
    MAX_RULES,
    MIN_COOLDOWN_S,
    PARKING_THRESHOLD_RANGE,
    TRAFFIC_THRESHOLD_RANGE,
)
from ibb_mcp.alerts.lift import LIFT_EQUIPMENT, MAX_LABEL_CHARS, MAX_LINES_PER_RULE, MAX_STATIONS_PER_RULE
from ibb_mcp.models import LAT_RANGE, LON_RANGE

#: A place key is a short handle ("ev", "is"), and a label is what a person reads.
MAX_KEY_CHARS = 32
#: Rail and bus line codes; the longest GTFS ``route_short_name`` is 12 characters.
MAX_LINE_CHARS = 16
#: ``muted_keys`` are the dedupe keys a client is sitting on. One rule yields one alert per
#: request, but a key changes with the situation it describes (a new notice, a new AQI
#: band), so a client can hold several per rule inside one cooldown window: bounded
#: generously rather than at MAX_RULES.
MAX_MUTED_KEYS = 5 * MAX_RULES
MAX_DEDUPE_KEY_CHARS = 200

LineCode = Annotated[str, Field(min_length=1, max_length=MAX_LINE_CHARS)]
DedupeKey = Annotated[str, Field(max_length=MAX_DEDUPE_KEY_CHARS)]


class AlertPlace(BaseModel):
    """One of the user's places. Used for one request, never stored, never logged."""

    key: str = Field(
        min_length=1,
        max_length=MAX_KEY_CHARS,
        description="Kısa anahtar; kurallar konuma bununla bağlanır (ör. 'ev', 'is'). Kişisel bilgi yazmayın.",
    )
    label: str | None = Field(
        default=None,
        max_length=MAX_LABEL_CHARS,
        description="Uyarı metninde görünen ad (ör. 'Ev'). Verilmezse key kullanılır.",
    )
    lat: float = Field(description=f"Enlem, derece (WGS84). İstanbul içinde olmalı: {LAT_RANGE[0]}–{LAT_RANGE[1]}.")
    lon: float = Field(description=f"Boylam, derece (WGS84). İstanbul içinde olmalı: {LON_RANGE[0]}–{LON_RANGE[1]}.")


def _cooldown(kind: str) -> str:
    return (
        "İstemcinin aynı uyarıyı yeniden göstermeden önce bekleyeceği süre, saniye. "
        f"{MIN_COOLDOWN_S}–{MAX_COOLDOWN_S} aralığına kırpılır; verilmezse {DEFAULT_COOLDOWNS[kind]}."
    )


class MetroDisruptionRuleSpec(BaseModel):
    """Metro İstanbul publishes a notice on one of these lines."""

    kind: Literal["metro_disruption"]
    lines: list[LineCode] = Field(
        min_length=1, max_length=MAX_LINES_PER_RULE, description="İzlenen raylı sistem hatları, ör. ['M4', 'Marmaray']."
    )
    cooldown_seconds: int | None = Field(default=None, description=_cooldown("metro_disruption"))


class ParkingFillingRuleSpec(BaseModel):
    """One of these İSPARK car parks passes an occupancy threshold."""

    kind: Literal["parking_filling"]
    park_ids: list[int] = Field(
        min_length=1,
        max_length=MAX_PARK_IDS,
        description="İSPARK park_id'leri (ispark_find_parking sonucundaki park_id alanı).",
    )
    threshold_pct: float | None = Field(
        default=None,
        description=(
            f"Doluluk eşiği, yüzde ({PARKING_THRESHOLD_RANGE[0]}–{PARKING_THRESHOLD_RANGE[1]}); "
            f"verilmezse {DEFAULT_PARKING_THRESHOLD_PCT}."
        ),
    )
    cooldown_seconds: int | None = Field(default=None, description=_cooldown("parking_filling"))


class AirQualityRuleSpec(BaseModel):
    """The station nearest one of the places reports an AQI at or above a threshold."""

    kind: Literal["air_quality"]
    place: str = Field(
        max_length=MAX_KEY_CHARS,
        description="places listesindeki bir key; en yakın ölçüm istasyonu bu konuma göre seçilir.",
    )
    aqi_threshold: float | None = Field(
        default=None,
        description=(
            f"Hava kalitesi indeksi eşiği ({AQI_THRESHOLD_RANGE[0]}–{AQI_THRESHOLD_RANGE[1]}); "
            f"verilmezse {DEFAULT_AQI_THRESHOLD}. Sağlık tavsiyesi değildir."
        ),
    )
    cooldown_seconds: int | None = Field(default=None, description=_cooldown("air_quality"))


class TrafficRuleSpec(BaseModel):
    """The city-wide İBB traffic index reaches a threshold."""

    kind: Literal["traffic"]
    threshold_index: int | None = Field(
        default=None,
        description=(
            f"İBB şehir geneli trafik indeksi eşiği ({TRAFFIC_THRESHOLD_RANGE[0]}–{TRAFFIC_THRESHOLD_RANGE[1]}); "
            f"verilmezse {DEFAULT_TRAFFIC_THRESHOLD}."
        ),
    )
    cooldown_seconds: int | None = Field(default=None, description=_cooldown("traffic"))


class BusBunchingRuleSpec(BaseModel):
    """A watched line's *measured history* shows bunching at the current hour — never a live detection."""

    kind: Literal["bus_bunching"]
    line: str = Field(
        min_length=1,
        max_length=MAX_LINE_CHARS,
        description="İETT hat kodu, ör. '500T'. Ölçülmüş geçmiş düzenlilik tablosuna bakar.",
    )
    cooldown_seconds: int | None = Field(default=None, description=_cooldown("bus_bunching"))


class LiftOutageRuleSpec(BaseModel):
    """A recorded lift, escalator or moving-walkway outage at a watched station or line."""

    kind: Literal["lift_outage"]
    stations: list[Annotated[str, Field(min_length=1, max_length=MAX_LABEL_CHARS)]] | None = Field(
        default=None,
        max_length=MAX_STATIONS_PER_RULE,
        description=(
            f"İzlenen metro istasyonları; en fazla {MAX_STATIONS_PER_RULE} ad, "
            f"her biri en fazla {MAX_LABEL_CHARS} karakter."
        ),
    )
    lines: list[LineCode] | None = Field(
        default=None,
        max_length=MAX_LINES_PER_RULE,
        description=f"İzlenen raylı sistem hat kodları; en fazla {MAX_LINES_PER_RULE} hat.",
    )
    equipment: list[Literal["elevator", "escalator", "moving_walkway"]] | None = Field(
        default=None,
        min_length=1,
        max_length=len(LIFT_EQUIPMENT),
        description="İzlenecek ekipman türleri; verilmezse yalnız asansör.",
    )
    cooldown_seconds: int | None = Field(default=None, description=_cooldown("lift_outage"))


#: One rule, told apart by ``kind``. A discriminated union gives the model one object shape
#: per kind instead of a bag of optional fields that are each valid for only one of them.
AlertRuleSpec = Annotated[
    MetroDisruptionRuleSpec
    | ParkingFillingRuleSpec
    | AirQualityRuleSpec
    | TrafficRuleSpec
    | BusBunchingRuleSpec
    | LiftOutageRuleSpec,
    Field(discriminator="kind"),
]


class AlertSubscription(BaseModel):
    """A client-held alert subscription, evaluated in memory for one request and then forgotten."""

    places: list[AlertPlace] = Field(
        default_factory=list,
        max_length=MAX_PLACES,
        description="Kullanıcının konumları. Yalnızca air_quality kuralı kullanır; en yakın istasyonu bulmak için.",
    )
    rules: list[AlertRuleSpec] = Field(min_length=1, max_length=MAX_RULES, description="Değerlendirilecek kurallar.")
    muted_keys: list[DedupeKey] = Field(
        default_factory=list,
        max_length=MAX_MUTED_KEYS,
        description=(
            "İstemcinin şu an bekleme süresinde tuttuğu dedupe_key'ler; bu yanıttan çıkarılır ve istekle birlikte unutulur."
        ),
    )
