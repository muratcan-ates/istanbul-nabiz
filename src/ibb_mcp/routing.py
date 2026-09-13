"""Route advisor — "şu an trafik böyleyken arabayla mı, metroyla mı, otobüsle mi?"

**This is an estimate and a comparison, not navigation.** It produces no turn-by-turn
directions and knows no one-way street, junction or real road geometry; it must never be
presented as a replacement for a routing engine (OpenTripPlanner, Azure Maps, Google
Maps). What it does is answer the question a person asks before leaving the house —
*which mode is the better bet right now* — from data we already hold live: the city
traffic index, İSPARK free spaces, the Metro İstanbul station list and its disruption
notices, and the İETT/GTFS stop sequences. The disclaimer travels inside the payload
(:data:`DISCLAIMER_TR`), so an agent quoting a number cannot drop the caveat by accident.

Why not a routing engine: OTP2 needs a graph server and an OSM extract, Azure Maps'
*transit* routing was retired, and a paid driving API would put a per-user network call on
the critical path — which decision 3 of ``DECISIONS.md`` forbids. Straight-line distance
with a documented winding factor is a coarse model, but every constant in it is visible,
testable and swappable, and it costs no upstream request beyond the cached ones the server
already makes.

**Honesty contract.** Every minute in the output traces to one of two things: a **live
reading** (an İBB number, in :attr:`RouteAdvice.readings` with its source and age) or a
**named assumption** (a constant of :class:`RoutingParams`, in
:attr:`TravelOption.assumptions` with its value, unit and a Turkish explanation). Each
:class:`Leg` names the one behind its minutes in ``basis``, so no total is unattributable.
When an option cannot be computed — no metro near either end, no single bus line joining
the two, an unreadable traffic index — it comes back with ``available=False`` and a Turkish
``reason``, never with a guessed number that keeps the list looking complete.

Comfort is defined, not vibed; :func:`comfort_score` carries the formula and its weights.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from ibb_mcp.eta import DEFAULT_PARAMS as _ETA_PARAMS
from ibb_mcp.models import ISTANBUL_TZ, Provenance, Stop, day_type_for, haversine_km, utcnow
from ibb_mcp.sources.base import SourceContext

log = logging.getLogger("ibb_mcp.routing")

Mode = Literal["drive", "metro", "bus", "walk"]
Confidence = Literal["high", "medium", "low"]

DISCLAIMER_TR = (
    "Bu bir tahmindir, adım adım yol tarifi değildir: mesafeler kuş uçuşu ölçülüp yol katsayısıyla çarpılır, "
    "hız canlı trafik indeksinden türetilir. Gerçek süre trafiğe, aktarma beklemesine ve yol çalışmalarına "
    "göre değişir."
)
DISCLAIMER_EN = (
    "An estimate for comparing modes, not turn-by-turn navigation: distances are straight-line figures "
    "scaled by a winding factor and speeds are derived from the city traffic index."
)

#: Approximate mid-channel line of the Boğaziçi, south (Marmara) to north (Black Sea). Used only
#: to decide which side of the water a point is on: the sign of the cross product against the
#: nearest segment is negative on the European side, positive on the Asian one. Degrees are
#: treated as a flat plane, which distorts distance (1° of longitude is ~84 km here against 111 km
#: for latitude) but not that sign. A waterfront point can still land on the wrong side by a few
#: hundred metres; the consequence is a crossing detour wrongly added or missed, which is why the
#: crossing is always named in the result rather than folded silently into a total.
BOSPHORUS_CENTRELINE: tuple[tuple[float, float], ...] = (
    (41.0055, 29.0000),  # Marmara mouth, between Sarayburnu and Haydarpaşa
    (41.0293, 29.0051),  # Kabataş ↔ Üsküdar narrows
    (41.0451, 29.0335),  # 15 Temmuz Şehitler Köprüsü
    (41.0700, 29.0490),  # Arnavutköy ↔ Kandilli
    (41.0912, 29.0614),  # Fatih Sultan Mehmet Köprüsü
    (41.1150, 29.0650),  # Emirgan ↔ Kanlıca
    (41.1600, 29.0850),  # Sarıyer ↔ Beykoz
    (41.2005, 29.1153),  # Yavuz Sultan Selim Köprüsü
    (41.2400, 29.1400),  # Black Sea mouth
)


@dataclass(frozen=True)
class Waypoint:
    """A named point. ``name`` is what the agent says out loud."""

    name: str
    lat: float
    lon: float


#: Road crossings a car can use, as fixed reference points (bridge mid-spans) — a named
#: assumption, not live data. The Avrasya Tüneli is deliberately absent: it is tolled and
#: car-only, and we cannot know whether the user would pay, so offering it would be a guess
#: dressed as a route.
ROAD_CROSSINGS: tuple[Waypoint, ...] = (
    Waypoint("15 Temmuz Şehitler Köprüsü", 41.0451, 29.0335),
    Waypoint("Fatih Sultan Mehmet Köprüsü", 41.0912, 29.0614),
    Waypoint("Yavuz Sultan Selim Köprüsü", 41.2005, 29.1153),
)

#: Station names anchoring the rail crossing, resolved against the *live* Metro station list
#: so the coordinates are İBB's and not ours. Tried in order; the metro option is withdrawn
#: with a reason if neither pair resolves.
RAIL_CROSSING_ANCHORS: tuple[tuple[str, str], ...] = (
    ("Yenikapı", "Ayrılık Çeşmesi"),  # M2/M1 ↔ Marmaray ↔ M4
    ("Sirkeci", "Üsküdar"),  # the Marmaray tube itself
)


@dataclass(frozen=True)
class RoutingParams:
    """Every constant the advisor uses, in one place, so the output can name them.

    Only ``bus_seconds_per_stop`` has ever been measured (:mod:`ibb_mcp.eta_profile`, and
    only for the lines it has data for). The rest are engineering assumptions and are
    returned as such: the lake holds traffic index, parking occupancy and bus positions but
    no journey times, so there is nothing to fit a speed curve against. ``road_winding`` and
    ``bus_seconds_per_stop`` default to :mod:`ibb_mcp.eta`'s values on purpose — they are
    the same quantities, and the two drifting apart would be a bug.
    """

    # driving
    free_flow_kmh: float = 48.0
    jam_kmh: float = 9.0
    road_winding: float = _ETA_PARAMS.winding_factor
    bosphorus_queue_minutes: float = 8.0
    #: Traffic index the queue above is quoted at; the queue scales with the live index.
    queue_reference_index: int = 60
    # parking
    park_search_radius_km: float = 0.8
    park_search_min_minutes: float = 2.0
    park_search_max_minutes: float = 10.0
    no_parking_penalty_minutes: float = 15.0
    # walking
    walk_kmh: float = 4.8
    walk_winding: float = 1.25
    max_walk_km: float = 2.5
    # metro
    metro_kmh: float = 32.0
    rail_winding: float = 1.15
    metro_headway_minutes: float = 6.0
    metro_transfer_minutes: float = 5.0
    metro_access_walk_km: float = 1.2
    disruption_penalty_minutes: float = 10.0
    # bus
    bus_access_walk_km: float = 0.8
    #: How many stops near each end to consider. İBB registers a separate ``stop_code`` per
    #: platform and direction, so a major interchange has fifteen-plus codes inside 250 m:
    #: at Kartal the five nearest are all "KARTAL KÖPRÜSÜ". A small candidate list therefore
    #: silently drops the code the line actually serves — with 8, the 500T corridor to
    #: 4.Levent disappears because its stop sits eighth-nearest at 0.195 km.
    bus_stop_candidates: int = 24
    bus_seconds_per_stop: float = _ETA_PARAMS.seconds_per_stop
    bus_default_headway_minutes: float = 20.0
    # comfort weights
    comfort_per_transfer: float = 8.0
    comfort_per_100m_walk: float = 2.5
    comfort_walk_cap: float = 30.0
    comfort_disruption: float = 25.0
    comfort_parking_full_scale: float = 25.0


DEFAULT_PARAMS = RoutingParams()

#: Unit and Turkish wording for every ``basis`` a leg can name. Keeping the text here rather
#: than at the call sites is what makes the honesty contract checkable: a leg whose basis is
#: not the key of a live reading must resolve to an entry in this table.
ASSUMPTION_TEXT: dict[str, tuple[str, str]] = {
    "road_winding": ("çarpan", "Kuş uçuşu mesafe, sürülen yola bu katsayıyla çevrildi."),
    "drive_speed_curve": ("km/sa", "Trafik indeksini ortalama sürüş hızına çeviren doğrusal eğri."),
    "bosphorus_queue_minutes": ("dk", "Köprü yaklaşımı için canlı trafik indeksiyle ölçeklenen bekleme."),
    "park_search_minutes": ("dk", "Otopark arama süresi; en yakın otoparkın doluluğuyla doğrusal artar."),
    "no_parking_penalty_minutes": ("dk", "Yarıçap içinde boş yer bildiren otopark yoksa eklenen arama cezası."),
    "walk_kmh": ("km/sa", "Ortalama yürüme hızı."),
    "walk_winding": ("çarpan", "Kuş uçuşu mesafeyi sokak ağına çeviren katsayı."),
    "metro_kmh": ("km/sa", "Duraklamalar dahil ortalama raylı sistem hızı."),
    "rail_winding": ("çarpan", "Kuş uçuşu mesafeyi hat güzergâhına çeviren katsayı."),
    "metro_headway_minutes": ("dk", "Varsayılan sefer aralığı; bekleme bunun yarısı alındı."),
    "metro_transfer_minutes": ("dk", "Aktarma başına yürüme ve bekleme payı."),
    "disruption_penalty_minutes": ("dk", "Metro İstanbul bir hatta bildirim yayımladığında eklenen gecikme."),
    "bus_seconds_per_stop": ("sn/durak", "Duraklar arası seyir süresi; ETA modeliyle aynı sabit."),
    "bus_headway": ("dk", "Sefer aralığı; bekleme bunun yarısı alındı."),
}


class StopIndex(Protocol):
    """The slice of :class:`ibb_mcp.gtfs.GtfsIndex` this module needs.

    A Protocol for the same reason :mod:`ibb_mcp.eta` declares one: the advisor can then be
    exercised against a five-stop corridor in a test instead of a 150 MB ``stop_times.txt``,
    and it cannot quietly grow a dependency on the rest of the index.
    """

    def nearest_stops(self, lat: float, lon: float, limit: int = ..., max_km: float = ...) -> list[Stop]: ...

    def route_by_code(self, route_code: str) -> Any: ...


@dataclass(frozen=True)
class Assumption:
    """A constant we chose, said out loud so the agent can repeat it."""

    key: str
    value: float | str
    unit: str
    detail: str


@dataclass(frozen=True)
class Reading:
    """A live İBB number that fed the estimate, with its source and age."""

    key: str
    value: float | str
    unit: str
    source: str
    age_seconds: float | None = None
    detail: str | None = None


@dataclass(frozen=True)
class Leg:
    """One stretch of a journey. ``basis`` names the reading or assumption behind ``minutes``."""

    kind: Literal["walk", "drive", "rail", "ride", "wait", "transfer", "park", "delay"]
    description: str
    minutes: float
    basis: str
    distance_km: float | None = None


@dataclass(frozen=True)
class Comfort:
    """A comfort score with its arithmetic attached, never a bare number."""

    score: float
    transfers: int
    walking_m: float
    disruption: bool
    parking_uncertainty: float
    penalties: dict[str, float]


@dataclass(frozen=True)
class TravelOption:
    """One mode, costed. ``available=False`` carries a ``reason`` and no numbers."""

    mode: Mode
    label: str
    available: bool
    total_minutes: float | None = None
    legs: list[Leg] = field(default_factory=list)
    comfort: Comfort | None = None
    confidence: Confidence = "medium"
    assumptions: list[Assumption] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RouteAdvice:
    """The whole comparison: options, the live readings behind them, and the disclaimer.

    Returned instead of the bare ``list[TravelOption]`` the brief sketched, because a list
    has nowhere to put the three things the tool layer needs: one provenance stamp per
    ``ToolResult``, the readings shared by several options (one traffic index feeds both the
    drive time and the bridge queue), and the disclaimer that must travel with the numbers.
    ``advice.options`` is that list.
    """

    origin: Waypoint
    destination: Waypoint
    straight_km: float
    crosses_bosphorus: bool
    options: list[TravelOption]
    readings: list[Reading]
    provenance: list[Provenance]
    generated_at: dt.datetime
    disclaimer: str = DISCLAIMER_TR
    disclaimer_en: str = DISCLAIMER_EN

    @property
    def available(self) -> list[TravelOption]:
        """Costed options, fastest first."""
        return sorted(
            (o for o in self.options if o.available and o.total_minutes is not None),
            key=lambda o: o.total_minutes or 0.0,
        )

    @property
    def fastest(self) -> TravelOption | None:
        options = self.available
        return options[0] if options else None

    @property
    def most_comfortable(self) -> TravelOption | None:
        """Highest comfort; ties broken by the shorter journey."""
        options = [o for o in self.available if o.comfort is not None]
        if not options:
            return None
        return max(options, key=lambda o: (o.comfort.score if o.comfort else 0.0, -(o.total_minutes or 0.0)))

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly payload for the MCP tool layer."""
        payload = dataclasses.asdict(self)
        payload["generated_at"] = self.generated_at.isoformat()
        payload["provenance"] = [p.model_dump(mode="json", exclude_none=True) for p in self.provenance]
        fastest, comfiest = self.fastest, self.most_comfortable
        payload["fastest_mode"] = fastest.mode if fastest else None
        payload["most_comfortable_mode"] = comfiest.mode if comfiest else None
        payload["kind"] = "estimate"
        return payload


@dataclass(frozen=True)
class _NearStation:
    """A station plus the walk to it.

    A wrapper rather than ``MetroStation.model_copy(update={"distance_km": ...})``: the
    shared model declares no such field, and bolting one on at runtime would put a value
    into ``model_dump()`` that nothing else in the project expects.
    """

    station: Any
    distance_km: float

    @property
    def name(self) -> str:
        return self.station.name or "İstasyon"

    @property
    def line_name(self) -> str | None:
        return self.station.line_name

    @property
    def lat(self) -> float:
        return self.station.lat

    @property
    def lon(self) -> float:
        return self.station.lon


@dataclass(frozen=True)
class _BusPick:
    """The single-line bus itinerary the scan chose, before it is costed."""

    route_code: str
    line_code: str
    from_stop: Any
    to_stop: Any
    stops_between: int


# --------------------------------------------------------------------------------------
# geometry, the documented curves, comfort
# --------------------------------------------------------------------------------------
def _assume(key: str, value: float | str, detail: str | None = None) -> Assumption:
    unit, text = ASSUMPTION_TEXT[key]
    return Assumption(key, value, unit, detail or text)


def _as_waypoint(value: Any, fallback_name: str) -> Waypoint:
    """Accept a :class:`Waypoint`, a ``(lat, lon)`` pair, or anything with ``lat``/``lon``.

    ``ibb_mcp.sources.places.Place`` satisfies the last case, which is how the tool layer
    hands over a resolved place name without this module importing the gazetteer.
    """
    if isinstance(value, Waypoint):
        return value
    if isinstance(value, (tuple, list)) and len(value) == 2:
        return Waypoint(fallback_name, float(value[0]), float(value[1]))
    lat, lon = getattr(value, "lat", None), getattr(value, "lon", None)
    if lat is None or lon is None:
        raise ValueError("origin/destination bir Waypoint, (lat, lon) çifti veya lat/lon taşıyan bir nesne olmalı")
    name = getattr(value, "label", None) or getattr(value, "name", None) or fallback_name
    return Waypoint(str(name), float(lat), float(lon))


def side_of_bosphorus(lat: float, lon: float) -> Literal["european", "asian"]:
    """Which side of the water a point is on, from :data:`BOSPHORUS_CENTRELINE`."""
    best_distance, best_sign = math.inf, -1.0
    for (y1, x1), (y2, x2) in zip(BOSPHORUS_CENTRELINE, BOSPHORUS_CENTRELINE[1:], strict=False):
        dy, dx = y2 - y1, x2 - x1
        length_sq = dy * dy + dx * dx
        t = 0.0 if length_sq == 0 else max(0.0, min(1.0, ((lat - y1) * dy + (lon - x1) * dx) / length_sq))
        distance = (lat - (y1 + t * dy)) ** 2 + (lon - (x1 + t * dx)) ** 2
        if distance < best_distance:
            best_distance, best_sign = distance, dy * (lon - x1) - dx * (lat - y1)
    return "asian" if best_sign > 0 else "european"


def drive_speed_kmh(index: int, params: RoutingParams = DEFAULT_PARAMS) -> float:
    """Map İBB's 1–99 traffic index to an average door-to-door driving speed.

    A straight line between two anchors — free flow (index 1) at ``free_flow_kmh``, gridlock
    (index 99) at ``jam_kmh``::

        speed = free_flow − (free_flow − jam) × (index − 1) / 98

    With the defaults the 60 the city reported on a recorded weekday morning becomes
    ~24.5 km/h and the 17 of an early morning ~41 km/h. The shape is deliberately linear: a
    fancier curve would imply a calibration nobody has done — this project collects no
    journey times, so there is nothing to fit — and each extra parameter would be one more
    number in the answer that cannot be defended. Recalibrate here, against measured travel
    times, before anyone calls this a model.
    """
    clamped = max(1, min(99, int(index)))
    return round(params.free_flow_kmh - (params.free_flow_kmh - params.jam_kmh) * (clamped - 1) / 98.0, 2)


def comfort_score(
    *,
    transfers: int,
    walking_m: float,
    disruption: bool,
    parking_uncertainty: float,
    params: RoutingParams = DEFAULT_PARAMS,
) -> Comfort:
    """Comfort on 0–100, from four things that can actually be measured.

    ``100`` minus, with the default weights:

    * **transfers** — 8 points each: every interchange is a chance to wait, to climb stairs
      and to get it wrong.
    * **walking** — 2.5 points per 100 m of total walking, capped at 30, so a long walk
      hurts without swamping the score.
    * **reported disruption** — 25 points when Metro İstanbul has a notice on a line this
      option uses.
    * **parking uncertainty** — 0–25 points, drive only. ``parking_uncertainty`` is 0.0 when
      a nearby lot reports free spaces, rises towards 1.0 as that lot fills, and is 1.0 when
      no free space is known inside the search radius.

    Clamped to 0–100. The weights are judgement, not measurement, which is why every
    component comes back in :attr:`Comfort.penalties`: someone who disagrees can re-add the
    points instead of arguing with a black box.
    """
    penalties = {
        "transfers": params.comfort_per_transfer * max(0, transfers),
        "walking": min(params.comfort_walk_cap, params.comfort_per_100m_walk * max(0.0, walking_m) / 100.0),
        "disruption": params.comfort_disruption if disruption else 0.0,
        "parking": params.comfort_parking_full_scale * max(0.0, min(1.0, parking_uncertainty)),
    }
    return Comfort(
        score=round(max(0.0, min(100.0, 100.0 - sum(penalties.values()))), 1),
        transfers=transfers,
        walking_m=round(walking_m),
        disruption=disruption,
        parking_uncertainty=round(parking_uncertainty, 2),
        penalties={key: round(value, 1) for key, value in penalties.items()},
    )


def _walk_leg(description: str, straight_km: float, params: RoutingParams) -> Leg:
    road_km = (straight_km or 0.0) * params.walk_winding
    return Leg("walk", description, round(road_km / params.walk_kmh * 60.0, 1), "walk_kmh", round(road_km, 3))


def _confidence(downgrades: int) -> Confidence:
    """'high' when nothing beyond the model itself was approximated, a notch down per caveat."""
    return "high" if downgrades <= 0 else ("medium" if downgrades == 1 else "low")


def _total(legs: Sequence[Leg]) -> float:
    return round(sum(leg.minutes for leg in legs), 1)


def _walking_m(legs: Sequence[Leg]) -> float:
    return sum((leg.distance_km or 0.0) for leg in legs if leg.kind == "walk") * 1000.0


def _unavailable(mode: Mode, label: str, reason: str) -> TravelOption:
    return TravelOption(mode=mode, label=label, available=False, reason=reason)


def _ensure_bases(assumptions: list[Assumption], legs: Sequence[Leg], params: RoutingParams) -> list[Assumption]:
    """Guarantee the honesty contract: every leg basis is either a live reading or listed here.

    Walk legs are the reason this exists. They appear inside the drive, metro and bus
    options, and it would be easy for a future edit to add one whose ``walk_kmh`` basis is
    explained nowhere in that option — so the gap is closed mechanically rather than by
    remembering. Keys that name a live reading (``ispark_free_spaces``) are absent from
    :data:`ASSUMPTION_TEXT` and are left for :attr:`RouteAdvice.readings` to carry.
    """
    listed = {assumption.key for assumption in assumptions}
    for leg in legs:
        if leg.basis in listed or leg.basis not in ASSUMPTION_TEXT:
            continue
        assumptions.append(_assume(leg.basis, getattr(params, leg.basis, "n/a")))
        listed.add(leg.basis)
        if leg.basis == "walk_kmh" and "walk_winding" not in listed:
            # The walk distance is a winding-corrected straight line; quoting the speed
            # without the factor would leave half the arithmetic unexplained.
            assumptions.append(_assume("walk_winding", params.walk_winding))
            listed.add("walk_winding")
    return assumptions


def _between(first: Any, second: Any) -> float:
    """Great-circle kilometres between two things carrying ``lat``/``lon``."""
    return haversine_km(first.lat, first.lon, second.lat, second.lon)


def _lot_detail(lot: Any) -> dict[str, Any] | None:
    """The car park a drive estimate leaned on, as plain JSON types."""
    if lot is None:
        return None
    return {
        "park_id": lot.park_id,
        "name": lot.name,
        "empty": lot.empty,
        "capacity": lot.capacity,
        "distance_km": lot.distance_km,
    }


# --------------------------------------------------------------------------------------
# the four options
# --------------------------------------------------------------------------------------
def _drive_option(
    origin: Waypoint,
    destination: Waypoint,
    *,
    traffic_index: int | None,
    traffic_reason: str | None,
    lots: Sequence[Any],
    crossing: Waypoint | None,
    params: RoutingParams = DEFAULT_PARAMS,
) -> TravelOption:
    """Distance over a traffic-derived speed, plus parking search, plus the walk from the car."""
    label = "Araba"
    if traffic_index is None:
        return _unavailable("drive", label, traffic_reason or "Trafik indeksi okunamadı; sürüş süresi hesaplanamıyor.")

    speed = drive_speed_kmh(traffic_index, params)
    curve = f"Trafik indeksi {traffic_index}, bu doğrusal eğride {speed} km/sa ortalama hız."
    assumptions = [
        _assume("road_winding", params.road_winding),
        _assume("drive_speed_curve", f"{params.free_flow_kmh}→{params.jam_kmh}", curve),
    ]
    legs: list[Leg] = []
    downgrades = 0

    if crossing is None:
        road_km = haversine_km(origin.lat, origin.lon, destination.lat, destination.lon) * params.road_winding
        description = "Sürüş"
    else:
        to_bridge = haversine_km(origin.lat, origin.lon, crossing.lat, crossing.lon)
        from_bridge = haversine_km(crossing.lat, crossing.lon, destination.lat, destination.lon)
        road_km = (to_bridge + from_bridge) * params.road_winding
        description = f"{crossing.name} üzerinden sürüş"
    legs.append(Leg("drive", description, round(road_km / speed * 60.0, 1), "drive_speed_curve", round(road_km, 2)))
    if crossing is not None:
        queue = params.bosphorus_queue_minutes * max(0.5, traffic_index / params.queue_reference_index)
        legs.append(Leg("delay", f"{crossing.name} yaklaşımı", round(queue, 1), "bosphorus_queue_minutes"))
        assumptions.append(_assume("bosphorus_queue_minutes", params.bosphorus_queue_minutes))
        downgrades += 1  # picking one of three fixed bridges is the coarsest part of this model

    notes: list[str] = []
    lot = lots[0] if lots else None
    within_radius = lot is not None and (lot.distance_km or 0.0) <= params.park_search_radius_km
    usable = within_radius and lot.capacity and lot.empty is not None
    if lot is not None and usable:
        free_ratio = max(0.0, min(1.0, lot.empty / lot.capacity))
        spread = params.park_search_max_minutes - params.park_search_min_minutes
        parking_uncertainty = 1.0 - free_ratio
        search = round(params.park_search_min_minutes + spread * (1 - free_ratio), 1)
        legs.append(Leg("park", f"Otopark arama ({lot.name}, {lot.empty} boş yer)", search, "ispark_free_spaces"))
        legs.append(_walk_leg(f"{lot.name} otoparkından yürüyüş", lot.distance_km, params))
        assumptions.append(_assume("park_search_minutes", f"{params.park_search_min_minutes}–{params.park_search_max_minutes}"))
    else:
        no_parking = "Otopark arama (yakında boş yer bildirilmedi)"
        legs.append(Leg("park", no_parking, params.no_parking_penalty_minutes, "no_parking_penalty_minutes"))
        assumptions.append(_assume("no_parking_penalty_minutes", params.no_parking_penalty_minutes))
        parking_uncertainty = 1.0
        downgrades += 1
        notes.append(
            f"Varışın {params.park_search_radius_km:.1f} km yakınında boş yer bildiren açık İSPARK otoparkı yok; "
            f"{params.no_parking_penalty_minutes:.0f} dk arama eklendi, park yerinden yürüyüş hesaplanamadı."
        )
    notes.append("Köprü/tünel ücretleri ve vapur seçeneği bu karşılaştırmaya dahil değildir.")

    return TravelOption(
        mode="drive",
        label=label,
        available=True,
        total_minutes=_total(legs),
        legs=legs,
        comfort=comfort_score(
            transfers=0, walking_m=_walking_m(legs), disruption=False, parking_uncertainty=parking_uncertainty, params=params
        ),
        confidence=_confidence(downgrades),
        assumptions=_ensure_bases(assumptions, legs, params),
        notes=notes,
        detail={
            "traffic_index": traffic_index,
            "effective_speed_kmh": speed,
            "crossing": crossing.name if crossing else None,
            "parking_lot": _lot_detail(lot),
        },
    )


def _near_stations(stations: Sequence[Any], point: Waypoint, reach_km: float) -> list[_NearStation]:
    """Stations within ``reach_km``, nearest first."""
    hits = [
        _NearStation(station, round(distance, 3))
        for station in stations
        if (distance := haversine_km(point.lat, point.lon, station.lat, station.lon)) <= reach_km
    ]
    hits.sort(key=lambda hit: hit.distance_km)
    return hits


def _pick_station_pair(
    origin_near: Sequence[_NearStation], destination_near: Sequence[_NearStation]
) -> tuple[_NearStation, _NearStation, bool]:
    """Nearest usable pair, preferring one that shares a line so no transfer is needed.

    Someone standing at Mecidiyeköy can walk to both the M2 and the M7 platform; which one
    they should use depends on where they are going, not on which pin is three metres nearer.
    """
    for origin_station in origin_near:
        for destination_station in destination_near:
            if origin_station.line_name and origin_station.line_name == destination_station.line_name:
                return origin_station, destination_station, True
    return origin_near[0], destination_near[0], False


def _resolve_rail_anchors(stations: Sequence[Any]) -> tuple[Any, Any] | None:
    """Find a Marmaray transfer pair in the live station list, European side first."""
    from ibb_mcp.sources.metro import normalize_tr

    by_name: dict[str, Any] = {}
    for station in stations:
        by_name.setdefault(normalize_tr(station.name), station)
    for european_name, asian_name in RAIL_CROSSING_ANCHORS:
        european, asian = by_name.get(normalize_tr(european_name)), by_name.get(normalize_tr(asian_name))
        if european is not None and asian is not None:
            return european, asian
    return None


def _metro_option(
    origin: Waypoint,
    destination: Waypoint,
    *,
    stations: Sequence[Any],
    disrupted_lines: Mapping[str, str],
    crosses: bool,
    params: RoutingParams = DEFAULT_PARAMS,
) -> TravelOption:
    """Nearest station at each end, straight rail distance over an average metro speed.

    The network is modelled as distance, not as a graph: we hold no line-to-line
    connectivity, so a shared-line pair is costed as a direct ride and anything else as one
    transfer. Crossing the Bosphorus is the exception, because there the route is forced
    through the Marmaray tube — distance is measured via the anchors in
    :data:`RAIL_CROSSING_ANCHORS` and a second transfer is charged.
    """
    label = "Metro / raylı sistem"
    reach = params.metro_access_walk_km
    with_coords = [s for s in stations if s.lat is not None and s.lon is not None]
    origin_near = _near_stations(with_coords, origin, reach)
    destination_near = _near_stations(with_coords, destination, reach)
    if not origin_near or not destination_near:
        end = "Başlangıç" if not origin_near else "Varış"
        return _unavailable("metro", label, f"{end} noktasının {reach:.1f} km yakınında raylı sistem istasyonu yok.")

    origin_station, destination_station, same_line = _pick_station_pair(origin_near, destination_near)
    legs = [
        _walk_leg(f"{origin_station.name} istasyonuna yürüyüş", origin_station.distance_km, params),
        Leg("wait", "Sefer beklemesi", round(params.metro_headway_minutes / 2.0, 1), "metro_headway_minutes"),
    ]
    lines_used = {origin_station.line_name, destination_station.line_name} - {None}
    downgrades = 0

    if crosses:
        anchors = _resolve_rail_anchors(with_coords)
        if anchors is None:
            missing = "Boğaz geçişi için Marmaray aktarma istasyonları canlı listede bulunamadı."
            return _unavailable("metro", label, missing)
        european, asian = anchors
        first, second = (european, asian) if side_of_bosphorus(origin.lat, origin.lon) == "european" else (asian, european)
        hops = [
            (f"{origin_station.name} → {first.name}", _between(origin_station, first)),
            (f"{first.name} → {second.name} (Marmaray)", _between(first, second)),
            (f"{second.name} → {destination_station.name}", _between(second, destination_station)),
        ]
        transfers = 2
        lines_used.add("Marmaray")
        downgrades += 1  # only the tube is modelled; the lines feeding it are approximated
    else:
        straight = haversine_km(origin_station.lat, origin_station.lon, destination_station.lat, destination_station.lon)
        hops = [(f"{origin_station.name} → {destination_station.name}", straight)]
        transfers = 0 if same_line else 1

    for description, straight_km in hops:
        rail_km = straight_km * params.rail_winding
        legs.append(Leg("rail", description, round(rail_km / params.metro_kmh * 60.0, 1), "metro_kmh", round(rail_km, 2)))
    if transfers:
        change = round(transfers * params.metro_transfer_minutes, 1)
        legs.append(Leg("transfer", f"{transfers} aktarma", change, "metro_transfer_minutes"))
    legs.append(_walk_leg(f"{destination_station.name} istasyonundan yürüyüş", destination_station.distance_km, params))

    notes: list[str] = []
    hit = next(((line, disrupted_lines[line]) for line in sorted(lines_used) if line in disrupted_lines), None)
    if hit is not None:
        notice = f"{hit[0]} hattında bildirilen aksaklık"
        legs.append(Leg("delay", notice, params.disruption_penalty_minutes, "disruption_penalty_minutes"))
        notes.append(f"{hit[0]}: {hit[1]}")
        downgrades += 1

    assumptions = [
        _assume("metro_kmh", params.metro_kmh),
        _assume("rail_winding", params.rail_winding),
        _assume("metro_headway_minutes", params.metro_headway_minutes),
    ]
    if transfers:
        assumptions.append(_assume("metro_transfer_minutes", params.metro_transfer_minutes))
    if hit is not None:
        assumptions.append(_assume("disruption_penalty_minutes", params.disruption_penalty_minutes))

    return TravelOption(
        mode="metro",
        label=label,
        available=True,
        total_minutes=_total(legs),
        legs=legs,
        comfort=comfort_score(
            transfers=transfers, walking_m=_walking_m(legs), disruption=hit is not None, parking_uncertainty=0.0, params=params
        ),
        confidence=_confidence(downgrades),
        assumptions=_ensure_bases(assumptions, legs, params),
        notes=notes,
        detail={
            "origin_station": origin_station.name,
            "destination_station": destination_station.name,
            "lines": sorted(lines_used),
            "transfers": transfers,
            "via_marmaray": crosses,
        },
    )


def find_bus_pick(
    origin: Waypoint,
    destination: Waypoint,
    *,
    index: StopIndex | None,
    sequences: Mapping[str, Any] | None,
    params: RoutingParams = DEFAULT_PARAMS,
) -> tuple[_BusPick | None, str | None]:
    """The single İETT line whose stop order passes a stop near the origin *then* one near the end.

    No transfer is invented. If no one line joins the two ends, the caller is told why: we
    hold stop sequences, not a transfer graph, and a fabricated two-bus itinerary is exactly
    the kind of number this project refuses to print.

    Candidates are ranked by provisional minutes — walk in, ride, walk out — using the
    untuned per-stop rate rather than by stop count alone, because counting stops boards the
    traveller at a stop 700 m away to save one of them. The per-line calibrated rate is
    applied afterwards, when the line is known; it scales every candidate of a line equally,
    so it cannot reorder them, and scanning twice to get it would cost more than it buys.
    """
    if index is None or not sequences:
        return None, "GTFS durak sıraları yüklü olmadığı için otobüs seçeneği hesaplanamadı."
    reach, limit = params.bus_access_walk_km, params.bus_stop_candidates
    near_origin = index.nearest_stops(origin.lat, origin.lon, limit=limit, max_km=reach)
    near_destination = index.nearest_stops(destination.lat, destination.lon, limit=limit, max_km=reach)
    origin_stops = {s.stop_code: s for s in near_origin if s.stop_code}
    destination_stops = {s.stop_code: s for s in near_destination if s.stop_code}
    if not origin_stops or not destination_stops:
        end = "Başlangıç" if not origin_stops else "Varış"
        return None, f"{end} noktasının {reach:.1f} km yakınında otobüs durağı yok."

    per_minute_km = params.walk_kmh / (60.0 * params.walk_winding)
    best: tuple[float, _BusPick] | None = None
    for route_code, sequence in sequences.items():
        codes = set(sequence.stop_codes)
        # Reject in two set operations before touching the ordering: 2 876 route variants
        # times two dozen candidate stops at each end is a lot of tuple scanning otherwise.
        boarding = origin_stops.keys() & codes
        if not boarding or not (alighting := destination_stops.keys() & codes):
            continue
        positions: dict[str, int] = {}
        for position, code in enumerate(sequence.stop_codes):
            positions.setdefault(code, position)  # first occurrence, as stops_between reads it
        for origin_code in boarding:
            for destination_code in alighting:
                gap = positions[destination_code] - positions[origin_code]
                if gap <= 0:  # the target is behind the bus on this variant
                    continue
                origin_stop, destination_stop = origin_stops[origin_code], destination_stops[destination_code]
                walk_km = (origin_stop.distance_km or 0.0) + (destination_stop.distance_km or 0.0)
                minutes = walk_km / per_minute_km + gap * params.bus_seconds_per_stop / 60.0
                if best is not None and minutes >= best[0]:
                    continue
                line_code = getattr(index.route_by_code(route_code), "short_name", None) or route_code
                best = (minutes, _BusPick(route_code, line_code, origin_stop, destination_stop, gap))
    if best is None:
        return None, (
            "İki ucun yakınındaki durakları aynı sırada geçen tek bir İETT hattı yok; "
            "aktarmalı güzergâh bu veriyle hesaplanamıyor."
        )
    return best[1], None


def _bus_option(
    pick: _BusPick,
    *,
    seconds_per_stop: float,
    rate_detail: str,
    headway_minutes: float | None,
    params: RoutingParams = DEFAULT_PARAMS,
) -> TravelOption:
    """Cost the chosen line: walk in, wait half a headway, ride N stops, walk out."""
    headway_value = round(headway_minutes, 1) if headway_minutes else params.bus_default_headway_minutes
    wait = headway_value / 2.0
    ride_minutes = round(pick.stops_between * seconds_per_stop / 60.0, 1)
    legs = [
        _walk_leg(f"{pick.from_stop.name} durağına yürüyüş", pick.from_stop.distance_km or 0.0, params),
        Leg("wait", f"{pick.line_code} beklemesi", round(wait, 1), "bus_headway"),
        Leg("ride", f"{pick.line_code} ile {pick.stops_between} durak", ride_minutes, "bus_seconds_per_stop"),
        _walk_leg(f"{pick.to_stop.name} durağından yürüyüş", pick.to_stop.distance_km or 0.0, params),
    ]
    headway_detail = (
        f"{pick.line_code} planlanan sefer saatlerinden hesaplandı; bekleme bunun yarısı."
        if headway_minutes
        else "Sefer saatleri okunamadığı için varsayılan sefer aralığı kullanıldı."
    )
    return TravelOption(
        mode="bus",
        label=f"Otobüs {pick.line_code}",
        available=True,
        total_minutes=_total(legs),
        legs=legs,
        comfort=comfort_score(transfers=0, walking_m=_walking_m(legs), disruption=False, parking_uncertainty=0.0, params=params),
        confidence=_confidence(0 if headway_minutes else 1),
        assumptions=_ensure_bases(
            [
                _assume("bus_seconds_per_stop", seconds_per_stop, rate_detail),
                _assume("bus_headway", headway_value, headway_detail),
            ],
            legs,
            params,
        ),
        notes=["Tek hatlı güzergâh; aktarmalı seçenekler bu veriyle hesaplanmıyor."],
        detail={
            "line_code": pick.line_code,
            "route_code": pick.route_code,
            "from_stop": {"stop_code": pick.from_stop.stop_code, "name": pick.from_stop.name},
            "to_stop": {"stop_code": pick.to_stop.stop_code, "name": pick.to_stop.name},
            "stops_between": pick.stops_between,
        },
    )


def seconds_per_stop_for(
    line_code: str, moment: dt.datetime, settings: Any, params: RoutingParams = DEFAULT_PARAMS
) -> tuple[float, str]:
    """The per-stop rate and a Turkish sentence saying where it came from.

    :mod:`ibb_mcp.eta_profile` holds the rate measured from collected arrivals (epic E5) and
    reports which cell produced it; the import is optional so this module keeps working on a
    checkout where that work has not landed. Quoting the provenance matters: "500T, ölçülen
    60 varıştan" and "hiç ölçüm yok, varsayılan" deserve different wording from the agent.
    """
    try:  # optional: the calibration module and its JSON are both allowed to be absent
        from ibb_mcp.eta_profile import load_profile
    except ImportError:
        return params.bus_seconds_per_stop, "Kalibrasyon modülü yok; ETA modelinin varsayılan oranı."
    profile = load_profile(settings)
    seconds, provenance = profile.seconds_per_stop_for(line_code, moment)
    if provenance == "default":
        return seconds, "Bu hat için ölçüm yok; kalibre edilmemiş varsayılan oran."
    if provenance.startswith("global"):
        # Saying "500T için ölçülen" when the number came from every line pooled together
        # would overstate what was measured; the agent repeats this sentence verbatim.
        return seconds, f"{line_code} için ayrı ölçüm yok; tüm hatlardan ölçülen genel oran ({provenance})."
    return seconds, f"{line_code} için ölçülen oran ({provenance})."


def _walk_option(
    origin: Waypoint, destination: Waypoint, *, crosses: bool, params: RoutingParams = DEFAULT_PARAMS
) -> TravelOption:
    """Offered for short, same-side trips only — there is no pedestrian Bosphorus crossing."""
    label = "Yürüyüş"
    straight = haversine_km(origin.lat, origin.lon, destination.lat, destination.lon)
    road_km = straight * params.walk_winding
    if crosses:
        return _unavailable("walk", label, "Boğaz'ın iki yakası arasında yürünemez.")
    if road_km > params.max_walk_km:
        too_far = f"Yürüme mesafesi {road_km:.1f} km; {params.max_walk_km:.1f} km sınırının üzerinde."
        return _unavailable("walk", label, too_far)
    leg = _walk_leg(f"{origin.name} → {destination.name}", straight, params)
    return TravelOption(
        mode="walk",
        label=label,
        available=True,
        total_minutes=leg.minutes,
        legs=[leg],
        comfort=comfort_score(transfers=0, walking_m=road_km * 1000.0, disruption=False, parking_uncertainty=0.0, params=params),
        confidence="high",
        assumptions=[_assume("walk_kmh", params.walk_kmh), _assume("walk_winding", params.walk_winding)],
        detail={"distance_km": round(road_km, 2)},
    )


# --------------------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------------------
async def compare_options(
    origin: Any,
    destination: Any,
    ctx: SourceContext,
    *,
    index: StopIndex | None = None,
    sequences: Mapping[str, Any] | None = None,
    params: RoutingParams = DEFAULT_PARAMS,
    now: dt.datetime | None = None,
    with_timetable: bool = True,
) -> RouteAdvice:
    """Compare driving, metro, a single bus line and walking between two points.

    ``origin``/``destination`` may be a :class:`Waypoint`, a ``(lat, lon)`` pair or any
    object carrying ``lat``/``lon`` (``sources.places.Place`` does). ``index`` and
    ``sequences`` are the GTFS index and its route stop orders; without them the bus option
    is withdrawn with a reason rather than guessed. Nothing here reaches İBB directly — the
    readings come from the existing sources through the shared cache and ``PoliteClient``,
    so N callers still cost at most one upstream call per cache window. A source that fails
    removes the options that depended on it and leaves the rest standing.
    """
    from ibb_mcp.sources.ispark import IsparkSource
    from ibb_mcp.sources.metro import MetroSource
    from ibb_mcp.sources.traffic import TrafficSource

    start, end = _as_waypoint(origin, "Başlangıç"), _as_waypoint(destination, "Varış")
    moment = now or utcnow()
    crosses = side_of_bosphorus(start.lat, start.lon) != side_of_bosphorus(end.lat, end.lon)
    metro = MetroSource(ctx)
    traffic, station_list, status, parking = await asyncio.gather(
        TrafficSource(ctx).current(),
        metro.stations(),
        metro.service_status(),
        IsparkSource(ctx).find_near(end.lat, end.lon, radius_km=params.park_search_radius_km, min_free=1, open_now=True),
        return_exceptions=True,
    )

    readings: list[Reading] = []
    provenance: list[Provenance] = []
    traffic_index, traffic_reason = _read_traffic(traffic, readings, provenance)
    stations = _read_payload(station_list, "metro istasyon listesi", provenance)
    statuses = _read_payload(status, "metro bildirimleri", provenance)
    lots = _read_payload(parking, "İSPARK", provenance)

    disrupted = {line.line_name: (line.description or "").strip() for line in (statuses or []) if line.line_name}
    if statuses is not None:
        empty_means = "Bildirimi olan hatlar; boş liste bildirilmiş aksaklık yok demektir."
        readings.append(Reading("metro_disruptions", len(disrupted), "hat", "metro_status", detail=empty_means))
    if stations:
        readings.append(Reading("metro_stations", len(stations), "istasyon", "metro_stations"))
    if lots:
        where = f"{lots[0].name}, varışa {lots[0].distance_km} km."
        readings.append(Reading("ispark_free_spaces", lots[0].empty or 0, "araç", "ispark", detail=where))

    options = [
        _drive_option(
            start,
            end,
            traffic_index=traffic_index,
            traffic_reason=traffic_reason,
            lots=lots or [],
            crossing=_best_crossing(start, end) if crosses else None,
            params=params,
        ),
        _metro_option(start, end, stations=stations, disrupted_lines=disrupted, crosses=crosses, params=params)
        if stations
        else _unavailable("metro", "Metro / raylı sistem", "Metro istasyon listesi okunamadı."),
        await _resolve_bus(start, end, ctx, index, sequences, params, moment, with_timetable, readings),
        _walk_option(start, end, crosses=crosses, params=params),
    ]
    return RouteAdvice(
        origin=start,
        destination=end,
        straight_km=round(haversine_km(start.lat, start.lon, end.lat, end.lon), 3),
        crosses_bosphorus=crosses,
        options=options,
        readings=readings,
        provenance=provenance,
        generated_at=moment,
    )


async def _resolve_bus(
    start: Waypoint,
    end: Waypoint,
    ctx: SourceContext,
    index: StopIndex | None,
    sequences: Mapping[str, Any] | None,
    params: RoutingParams,
    moment: dt.datetime,
    with_timetable: bool,
    readings: list[Reading],
) -> TravelOption:
    """Choose the line, then price it with that line's measured rate and real headway."""
    pick, reason = find_bus_pick(start, end, index=index, sequences=sequences, params=params)
    if pick is None:
        return _unavailable("bus", "Otobüs (tek hat)", reason or "Otobüs seçeneği hesaplanamadı.")
    seconds_per_stop, rate_detail = seconds_per_stop_for(pick.line_code, moment, ctx.settings, params)
    headway = await _headway_for(ctx, pick.line_code, moment) if with_timetable else None
    if headway is not None:
        timetable = f"{pick.line_code} planlanan sefer saatleri."
        readings.append(Reading("bus_headway_minutes", round(headway, 1), "dk", "iett_schedule", detail=timetable))
    return _bus_option(pick, seconds_per_stop=seconds_per_stop, rate_detail=rate_detail, headway_minutes=headway, params=params)


def _read_payload(result: Any, what: str, provenance: list[Provenance]) -> Any:
    """Unpack a ``(data, provenance)`` gather result; ``None`` when that source failed."""
    if isinstance(result, BaseException):
        log.info("routing: %s okunamadı: %r", what, result)
        return None
    data, prov = result
    provenance.append(prov)
    return data


def _read_traffic(result: Any, readings: list[Reading], provenance: list[Provenance]) -> tuple[int | None, str | None]:
    """The live traffic index, or a Turkish reason why the drive option cannot be costed."""
    if isinstance(result, BaseException):
        log.info("routing: trafik indeksi okunamadı: %r", result)
        return None, f"Trafik indeksi okunamadı ({type(result).__name__})."
    point, prov = result
    provenance.append(prov)
    if point is None:
        return None, "Trafik indeksi serisi boş döndü."
    what = "İBB şehir geneli trafik yoğunluk indeksi."
    readings.append(Reading("traffic_index", point.index, "1-99", "traffic", round(prov.age_seconds, 1), what))
    return point.index, None


def _best_crossing(origin: Waypoint, destination: Waypoint) -> Waypoint:
    """The bridge giving the shortest two-leg path. A named assumption, not a route."""
    return min(
        ROAD_CROSSINGS,
        key=lambda bridge: haversine_km(origin.lat, origin.lon, bridge.lat, bridge.lon)
        + haversine_km(bridge.lat, bridge.lon, destination.lat, destination.lon),
    )


async def _headway_for(ctx: SourceContext, line_code: str, moment: dt.datetime) -> float | None:
    """Mean gap between planned departures around ``moment``, from the İETT timetable.

    The timetable is cached for hours by :class:`~ibb_mcp.sources.iett.IettSource`, so on a
    warm cache this costs no upstream request. A failure is swallowed and the caller falls
    back to the documented default headway: a missing timetable should cost precision, not
    the whole option.
    """
    if not line_code:
        return None
    from ibb_mcp.sources.iett import IettSource
    from ibb_mcp.sources.iett import departure_minutes as _minutes

    try:
        departures, _ = await IettSource(ctx).schedule(line_code, day_type=None)
    except Exception as error:  # noqa: BLE001 - any upstream failure degrades to the default
        log.info("routing: %s sefer saatleri okunamadı: %r", line_code, error)
        return None

    wanted = day_type_for(moment)
    local = moment.astimezone(ISTANBUL_TZ)
    reference = local.hour * 60 + local.minute
    window: list[int] = []
    for departure in departures:
        if (departure.day_type or "").upper() != wanted:
            continue
        minutes = _minutes(departure.departure_time)
        # A ±60 minute window, so an evening question gets the evening headway rather than the
        # day's average: İETT thins these lines out sharply after the peak.
        if minutes is not None and abs(minutes - reference) <= 60:
            window.append(minutes)
    times = sorted(window)
    gaps = [b - a for a, b in zip(times, times[1:], strict=False) if b > a]
    return sum(gaps) / len(gaps) if gaps else None
