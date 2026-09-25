"""Route advisor — "şu an trafik böyleyken arabayla mı, metroyla mı, otobüsle mi?"

**This is an estimate and a comparison, not navigation.** It produces no turn-by-turn
directions and knows no one-way street, junction or real road geometry; it must never be
presented as a replacement for a routing engine (OpenTripPlanner, Azure Maps, Google
Maps). What it does is answer the question a person asks before leaving the house —
*which mode is the better bet right now* — from data we already hold live: the city
traffic index and its own four-week history, İSPARK free spaces, the Metro İstanbul station
list and its disruption notices, and the İETT/GTFS stop sequences. The disclaimer travels
inside the payload (:data:`DISCLAIMER_TR`), so an agent quoting a number cannot drop the
caveat by accident.

The metro option rides a real network graph (:mod:`ibb_mcp.metro_graph`): Dijkstra over the
station list, transfers only where distance justifies one, and the Marmaray tube added from
four stations the feed already has, so Taksim → Kadıköy crosses the water on rails the way a
rider would. The bus option asks :mod:`ibb_mcp.lines` which single İETT line runs the right
way between the two ends, and names the other lines that also do.

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
``reason``, never with a guessed number that keeps the list looking complete. And a source
that could not be read is never read as good news: unread metro notices are not "no
disruption", an unread İSPARK list is not "no free space", and both say so in the notes.

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
from ibb_mcp.lines import DirectLine, StopRouteIndex, index_for
from ibb_mcp.metro_graph import (
    DEFAULT_METRO_PARAMS,
    MARMARAY_LINE,
    MARMARAY_TUBE,
    MetroGraph,
    MetroGraphParams,
    MetroLeg,
    MetroPath,
    marmaray_tube,
)
from ibb_mcp.models import ISTANBUL_TZ, MetroLineStatus, MetroStation, Provenance, Stop, day_type_for, haversine_km, utcnow
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.traffic_profile import BAND_UNKNOWN, TrafficBaseline, TrafficComparison, compare_to_typical

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


@dataclass(frozen=True)
class RoutingParams:
    """Every constant the advisor uses, in one place, so the output can name them.

    Only ``bus_seconds_per_stop`` has ever been measured (:mod:`ibb_mcp.eta_profile`, and
    only for the lines it has data for), and that measurement is served only on request
    because it did not hold up on other stops (DECISIONS #18). The rest are engineering
    assumptions and are returned as such: the lake holds traffic index, parking occupancy
    and bus positions but no journey times, so there is nothing to fit a speed curve
    against. ``road_winding`` and
    ``bus_seconds_per_stop`` default to :mod:`ibb_mcp.eta`'s values on purpose — they are
    the same quantities, and the two drifting apart would be a bug.

    The rail constants (speeds per mode, dwell, transfer penalty, interchange distances)
    live in ``rail``, the graph's own :class:`~ibb_mcp.metro_graph.MetroGraphParams`. Walking
    speed, the access radius and the headway stay here and are handed to the graph by
    :func:`rail_params`, so a walk to a platform costs the same as a walk to a bus stop and
    "the first train" waits the same half-headway it always did.
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
    rail: MetroGraphParams = DEFAULT_METRO_PARAMS
    #: Add the Marmaray tube to the graph (:func:`ibb_mcp.metro_graph.marmaray_tube`).
    #: Without it no rail journey crosses the Bosphorus, because Metro İstanbul's feed has none.
    include_marmaray: bool = True
    metro_headway_minutes: float = 6.0
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
    #: How many other direct lines the bus option names beside the one it costs.
    bus_other_lines: int = 4
    # comfort weights
    comfort_per_transfer: float = 8.0
    comfort_per_100m_walk: float = 2.5
    comfort_walk_cap: float = 30.0
    comfort_disruption: float = 25.0
    comfort_parking_full_scale: float = 25.0


DEFAULT_PARAMS = RoutingParams()


def slow_walk_params(base: RoutingParams = DEFAULT_PARAMS) -> RoutingParams:
    """Lower walking pace and raise the cost of transfers for a slow walker."""
    return dataclasses.replace(
        base,
        walk_kmh=base.walk_kmh * 0.6,
        max_walk_km=base.max_walk_km * 0.6,
        rail=dataclasses.replace(base.rail, transfer_seconds=base.rail.transfer_seconds * 2),
        comfort_per_transfer=base.comfort_per_transfer * 2,
    )

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
    "rail_ride": (
        "km/sa, sn",
        "İstasyonlar arası kuş uçuşu mesafe hat türünün ortalama hızına bölündü; her duruşa sabit bir süre eklendi.",
    ),
    "metro_headway_minutes": ("dk", "Varsayılan sefer aralığı; bekleme bunun yarısı alındı."),
    "rail_transfer": (
        "sn",
        "Aktarma başına yürüme ve bekleme payı; aktarma yalnızca iki peron gerçekten yürünecek kadar yakınsa kurulur.",
    ),
    "marmaray_tube": (
        "istasyon",
        "Marmaray bu veride yok; tüp geçişi Yenikapı, Sirkeci, Üsküdar ve Ayrılık Çeşmesi istasyonlarının "
        "canlı listedeki koordinatlarıyla, metro hızında modellendi.",
    ),
    "disruption_penalty_minutes": ("dk", "Metro İstanbul bir hatta bildirim yayımladığında eklenen gecikme."),
    "bus_seconds_per_stop": ("sn/durak", "Duraklar arası seyir süresi; ETA modeliyle aynı sabit."),
    "bus_headway": ("dk", "Sefer aralığı; bekleme bunun yarısı alındı."),
}


#: Said out loud whenever a *measured* per-stop rate is used. ``eta_profile`` fits its rate
#: against "how long until the bus reaches your stop", which absorbs dwell time, the
#: collector's 3-minute observation tick and the fact that ``yakinDurakKodu`` is the nearest
#: stop rather than a stop event. Reused here as a ride duration it is therefore an upper
#: bound. How loose: the constant-plus-rate fit in ``eta_profile``'s docstring puts the
#: marginal cost of a stop at 150 s, so over 23 stops the overall 235 s/stop rate says ~33
#: minutes more than that marginal cost would, and the evening 445 s/stop ~113 more — too big
#: to leave unsaid.
MEASURED_RATE_CAVEAT = (
    "Bu oran varış tahmini için kalibre edildi (bekleme ve algılama payı dahil); uzun yolculuklarda süre üst sınırdır."
)

#: The rate detail when the untuned default is served on purpose (DECISIONS #18): 500T has
#: a measured rate, but held out it did worse than this constant, so "no measurement" would
#: be untrue and "measured" would be worse.
DEFAULT_RATE_DETAIL = (
    "Kalibre edilmemiş varsayılan oran; ölçülen oranlar, ölçülmedikleri duraklarda daha büyük hata verdiği için "
    "kullanılmıyor."
)


class StopIndex(Protocol):
    """The slice of :class:`ibb_mcp.gtfs.GtfsIndex` this module needs.

    A Protocol for the same reason :mod:`ibb_mcp.eta` declares one: the advisor can then be
    exercised against a five-stop corridor in a test instead of a 150 MB ``stop_times.txt``,
    and it cannot quietly grow a dependency on the rest of the index. Line names come from
    the route code (:func:`ibb_mcp.lines.parse_route_code`), not from ``routes.csv``.
    """

    def nearest_stops(self, lat: float, lon: float, limit: int = ..., max_km: float = ...) -> list[Stop]: ...


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

    def model_dump(self, **_: Any) -> dict[str, Any]:
        """Alias for :meth:`to_dict`, so ``tools._dump`` yields the same payload the tool does.

        ``tools._dump`` prefers ``model_dump`` over its generic dataclass walk. The walk
        would drop every ``None`` — deleting the very fields that say a number is unknown —
        and miss the derived ``fastest_mode``/``most_comfortable_mode`` keys. Pydantic's
        keyword arguments (``mode``, ``exclude_none``) are accepted and ignored because
        :meth:`to_dict` is already JSON-safe.
        """
        return self.to_dict()

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
class _BusPick:
    """The single-line bus itinerary the scan chose, before it is costed.

    ``others`` are the next-best lines that also run the right way between the two ends,
    already shaped for the payload. They are named, never costed: a duration needs each
    line's own calibrated rate and timetable, and every extra timetable is one more request
    against İETT's shared budget of 100 an hour.
    """

    route_code: str
    line_code: str
    from_stop: Any
    to_stop: Any
    stops_between: int
    others: tuple[dict[str, Any], ...] = ()


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
def _drive_option(  # noqa: PLR0913 - debt, ratcheted in scripts/architecture_baseline.json
    origin: Waypoint,
    destination: Waypoint,
    *,
    traffic_index: int | None,
    traffic_reason: str | None,
    lots: Sequence[Any] | None,
    crossing: Waypoint | None,
    typical: TrafficComparison | None = None,
    params: RoutingParams = DEFAULT_PARAMS,
) -> TravelOption:
    """Distance over a traffic-derived speed, plus parking search, plus the walk from the car.

    ``lots`` is ``None`` when İSPARK could not be read and an empty list when it was read
    and nothing near the destination has a free space. Both cost the same search penalty,
    but only the second is evidence, so they are worded differently: "no free space
    reported" and "could not look" are not the same sentence.

    ``typical`` is the :class:`~ibb_mcp.traffic_profile.TrafficComparison` of the live index
    against this weekday and hour's measured median. It never changes the minutes — the
    live index already set the speed — but when the hour is measurably heavier or lighter
    than usual that is a checkable fact about driving right now, so it goes into the notes.
    """
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
    if typical is not None and typical.band not in (BAND_UNKNOWN, "typical"):
        notes.append(typical.description_tr)
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
        assumptions.append(_assume("park_search_minutes", f"{params.park_search_min_minutes}-{params.park_search_max_minutes}"))
    else:
        unread = lots is None
        no_parking = "Otopark arama (İSPARK okunamadı)" if unread else "Otopark arama (yakında boş yer bildirilmedi)"
        legs.append(Leg("park", no_parking, params.no_parking_penalty_minutes, "no_parking_penalty_minutes"))
        assumptions.append(_assume("no_parking_penalty_minutes", params.no_parking_penalty_minutes))
        parking_uncertainty = 1.0
        downgrades += 1
        if unread:
            notes.append(
                f"İSPARK verisi okunamadı; varıştaki otopark durumu bilinmiyor. {params.no_parking_penalty_minutes:.0f} dk "
                "arama varsayıldı, park yerinden yürüyüş hesaplanamadı."
            )
        else:
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
            "traffic_vs_typical": typical.band if typical is not None else None,
            "crossing": crossing.name if crossing else None,
            "parking_lot": _lot_detail(lot),
            "parking_read": lots is not None,
        },
    )


def rail_params(params: RoutingParams = DEFAULT_PARAMS) -> MetroGraphParams:
    """The graph's constants, with walking and the first wait taken from the advisor.

    The graph walks in straight lines, so it is handed the *effective* straight-line pace
    ``walk_kmh / walk_winding``: a 300 m walk to a platform then costs exactly what
    :func:`_walk_leg` charges for 300 m to a bus stop. The same pace applies to a walking
    interchange between two stations, which is slower than the graph's own 4.5 km/h default
    and deliberately so — one walking model for the whole comparison.
    """
    return dataclasses.replace(
        params.rail,
        walk_speed_kmh=params.walk_kmh / params.walk_winding,
        access_walk_km=params.metro_access_walk_km,
        mean_wait_seconds=params.metro_headway_minutes * 60.0 / 2.0,
    )


#: One-slot memo: the last station list's signature and the graph built from it.
_GRAPH_MEMO: tuple[tuple[Any, ...], MetroGraph] | None = None


def rail_graph(stations: Sequence[MetroStation], params: RoutingParams = DEFAULT_PARAMS) -> MetroGraph:
    """The rail network for this station list, with the Marmaray tube added.

    Building takes about 4 ms on the recorded 248-station list (3.8 ms, mean of 20 builds,
    measured 2026-09-23), so it would be affordable per request; the one-slot memo exists
    because the list changes once a day at most. It is keyed on the stations' content, not
    on the list object — :meth:`~ibb_mcp.sources.metro.MetroSource.stations` parses a fresh
    list from the cached payload on every call. Two concurrent builds race harmlessly: the
    graphs are equal and the later assignment wins.
    """
    global _GRAPH_MEMO
    graph_params = rail_params(params)
    key = (graph_params, params.include_marmaray, tuple((s.name, s.line_name, s.order, s.lat, s.lon) for s in stations))
    memo = _GRAPH_MEMO
    if memo is not None and memo[0] == key:
        return memo[1]
    added = marmaray_tube(stations) if params.include_marmaray else []
    graph = MetroGraph.from_stations(stations, params=graph_params, added=added)
    _GRAPH_MEMO = (key, graph)
    return graph


def line_code(name: str | None) -> str | None:
    """First token of a line name, folded to a comparable code: ``"M7 Yıldız-Mahmutbey"`` -> ``"M7"``.

    The station list and the notice feed name lines their own way, and matching them loosely
    is how a disruption on one line gets pinned to a different one. Taking only the leading
    token and keeping just its letters and digits fails *closed*: a notice named after its
    termini matches nothing, which loses a notice. Losing one is recoverable — unmatched
    names are reported in the notes — whereas inventing one is not.
    """
    if not name:
        return None
    head = name.strip().split()
    if not head:
        return None
    token = "".join(ch for ch in head[0] if ch.isalnum()).upper()
    return token or None


def _looks_like_line_code(code: str) -> bool:
    """``M4``, ``M1A``, ``T5``, ``TF2``, ``F1`` — a letter, a digit, and nothing long."""
    return 2 <= len(code) <= 4 and code[0].isalpha() and any(ch.isdigit() for ch in code)


def _disruptions_on(
    lines: Sequence[str], statuses: Sequence[MetroLineStatus]
) -> tuple[list[tuple[str, MetroLineStatus]], list[str]]:
    """Live notices on the lines this path rides, and the notices that could not be placed.

    Metro İstanbul's feed carries a row only for a line that *has* a notice, and
    ``IsActive`` says whether that notice is still live — so ``is_active is not False`` is a
    disruption, the reading :func:`ibb_mcp.sources.metro.summarise_disruptions` uses too. A
    retired notice therefore costs nothing. A row whose name does not fold to something
    shaped like a line code is handed back as unmatched rather than dropped: we cannot tell
    whether it concerns this journey, and saying so beats implying the route is clear.
    """
    wanted = {code for line in lines if (code := line_code(line))}
    hits: list[tuple[str, MetroLineStatus]] = []
    unmatched: list[str] = []
    for status in statuses:
        if status.is_active is False:
            continue
        code = line_code(status.line_name)
        if code is None or not _looks_like_line_code(code):
            unmatched.append(status.line_name or "?")
            continue
        if code in wanted:
            hits.append((code, status))
    return hits, unmatched


def _rail_refusal(reason: str | None, graph: MetroGraph, params: RoutingParams) -> str:
    """The Turkish reason a door-to-door rail path does not exist."""
    reach = params.metro_access_walk_km
    if reason == "no_station_near_origin":
        return f"Başlangıç noktasının {reach:.1f} km yakınında raylı sistem istasyonu yok."
    if reason == "no_station_near_destination":
        return f"Varış noktasının {reach:.1f} km yakınında raylı sistem istasyonu yok."
    network = "Metro İstanbul hatları ve Marmaray tüpü" if graph.added_lines else "Metro İstanbul hatları"
    return (
        f"Raylı sistem ağı ({network}) iki ucun yakınındaki istasyonları birbirine bağlamıyor; "
        "Metrobüs ve vapur bu veride yok."
    )


def _network_tr(graph: MetroGraph) -> str:
    """What the rail graph contains, said the way the agent will repeat it."""
    added = " ve Marmaray tüpü (" + ", ".join(MARMARAY_TUBE) + ")" if MARMARAY_LINE in graph.added_lines else ""
    return f"Metro İstanbul hatları{added}; Metrobüs ve vapur bu veride yok."


def _rail_legs(path: MetroPath, params: RoutingParams) -> tuple[list[Leg], float]:
    """Turn the graph's per-hop legs into the advisor's legs, and count interchange walking.

    One ``rail`` leg per line ridden (``"M2: Taksim → Yenikapı, 4 durak"``) and one
    ``transfer`` leg per change, so the agent can read the itinerary off the legs without
    inventing anything. The graph emits one leg per hop so no station name is lost; the
    advisor merges them because nobody says "Taksim to Şişhane, then Şişhane to Haliç".
    The second value is the metres walked *between* stations, which the comfort score must
    see even though those legs are transfers rather than walks.
    """
    access, *middle, egress = path.legs
    legs: list[Leg] = [
        _walk_leg(f"{access.to_station} istasyonuna yürüyüş", access.km or 0.0, params),
        Leg("wait", "Sefer beklemesi", round(path.wait_seconds / 60.0, 1), "metro_headway_minutes"),
    ]
    run: list[MetroLeg] = []
    interchange_m = 0.0

    def close_run() -> None:
        if not run:
            return
        first, last = run[0], run[-1]
        stops = sum(leg.stops for leg in run)
        minutes = round(sum(leg.seconds for leg in run) / 60.0, 1)
        description = f"{first.line}: {first.from_station} → {last.to_station}, {stops} durak"
        legs.append(Leg("rail", description, minutes, "rail_ride", round(sum(leg.km or 0.0 for leg in run), 2)))
        run.clear()

    previous_line: str | None = None
    for leg in middle:
        if leg.kind == "ride":
            if run and run[-1].line != leg.line:
                close_run()
            run.append(leg)
            previous_line = leg.line
            continue
        close_run()
        km = leg.km or 0.0
        where = leg.from_station if leg.from_station == leg.to_station else f"{leg.from_station} → {leg.to_station}"
        change = f"{previous_line} → {leg.line}" if previous_line else f"{leg.line} hattına"
        walked = f", {round(km * 1000)} m yürüme" if km >= 0.05 else ""
        minutes = round(leg.seconds / 60.0, 1)
        legs.append(Leg("transfer", f"{where}: {change} aktarması{walked}", minutes, "rail_transfer", km or None))
        interchange_m += km * 1000.0
    close_run()
    legs.append(_walk_leg(f"{egress.from_station} istasyonundan yürüyüş", egress.km or 0.0, params))
    return legs, interchange_m


def _metro_option(
    origin: Waypoint,
    destination: Waypoint,
    *,
    graph: MetroGraph,
    statuses: Sequence[MetroLineStatus] | None,
    params: RoutingParams = DEFAULT_PARAMS,
) -> TravelOption:
    """Walk to a platform, ride the network graph, walk off.

    The path is the cheapest one :class:`~ibb_mcp.metro_graph.MetroGraph` finds over every
    station inside the access radius at both ends, so a longer walk to a faster line can win
    over the nearest platform. Transfers exist only where two platforms are close enough to
    walk between — the rule that stops the graph "changing" from T3 Bahariye to M9 Bahariye,
    20.7 km apart. The Bosphorus is crossed only through the Marmaray tube, and saying so
    costs the option one confidence notch, because Marmaray's rows are ours, not İBB's.

    A notice on *any* line the path rides costs the penalty, not only a notice at either end;
    an unreadable notice feed is reported as unknown, never as "no disruption".
    """
    label = "Metro / raylı sistem"
    result = graph.path_between_points((origin.lat, origin.lon), (destination.lat, destination.lon))
    if result.path is None:
        return _unavailable("metro", label, _rail_refusal(result.reason, graph, params))
    path = result.path
    if not any(leg.kind == "ride" for leg in path.legs):
        same_station = "Başlangıç ve varış aynı istasyonun yürüme mesafesinde; raylı sistemle gidilecek bir yol yok."
        return _unavailable("metro", label, same_station)

    legs, interchange_m = _rail_legs(path, params)
    via_marmaray = MARMARAY_LINE in path.lines
    downgrades = 1 if via_marmaray else 0
    notes: list[str] = []
    disrupted: list[str] = []
    if statuses is None:
        notes.append("Metro İstanbul bildirimleri okunamadı; bu güzergâhın hatlarında aksaklık olup olmadığı bilinmiyor.")
        downgrades += 1
    else:
        hits, unmatched = _disruptions_on([line for line in path.lines if line != MARMARAY_LINE], statuses)
        disrupted = [code for code, _ in hits]
        if hits:
            notice = f"{', '.join(disrupted)} hattında bildirilen aksaklık"
            legs.append(Leg("delay", notice, params.disruption_penalty_minutes, "disruption_penalty_minutes"))
            notes.extend(f"{code}: {(status.description or 'ayrıntı verilmedi').strip()}" for code, status in hits)
            downgrades += 1
        if unmatched:
            notes.append(
                "Hat adı eşlenemeyen bildirimler var; bu güzergâhı etkileyip etkilemedikleri bilinmiyor: "
                + ", ".join(unmatched)
                + "."
            )
    if via_marmaray:
        notes.append("Marmaray Metro İstanbul'un bildirim akışında yer almaz; tüpteki aksaklıklar bu veride görünmez.")

    rail = graph.params
    speeds = (
        f"metro {rail.metro_speed_kmh:g}, tramvay {rail.tram_speed_kmh:g}, füniküler {rail.funicular_speed_kmh:g} km/sa; "
        f"duruş {rail.dwell_seconds:g} sn"
    )
    assumptions = [_assume("rail_ride", speeds), _assume("metro_headway_minutes", params.metro_headway_minutes)]
    if path.transfer_count:
        rule = (
            f"Aktarma başına {rail.transfer_seconds:g} sn yürüme ve bekleme. Aktarma yalnızca peronlar "
            f"{rail.in_station_transfer_km * 1000:.0f} m içindeyse, ya da aynı adlı istasyonlar "
            f"{rail.max_named_walk_km * 1000:.0f} m, farklı adlılar {rail.max_unnamed_walk_km * 1000:.0f} m içindeyse kurulur."
        )
        assumptions.append(_assume("rail_transfer", rail.transfer_seconds, rule))
    if via_marmaray:
        assumptions.append(_assume("marmaray_tube", ", ".join(MARMARAY_TUBE)))
    if disrupted:
        assumptions.append(_assume("disruption_penalty_minutes", params.disruption_penalty_minutes))

    first_ride = next(leg for leg in path.legs if leg.kind == "ride")
    last_ride = next(leg for leg in reversed(path.legs) if leg.kind == "ride")
    return TravelOption(
        mode="metro",
        label=label,
        available=True,
        total_minutes=_total(legs),
        legs=legs,
        comfort=comfort_score(
            transfers=path.transfer_count,
            walking_m=_walking_m(legs) + interchange_m,
            disruption=bool(disrupted),
            parking_uncertainty=0.0,
            params=params,
        ),
        confidence=_confidence(downgrades),
        assumptions=_ensure_bases(assumptions, legs, params),
        notes=notes,
        detail={
            "origin_station": first_ride.from_station,
            "destination_station": last_ride.to_station,
            "lines": list(path.lines),
            "transfers": path.transfer_count,
            "stops": path.stop_count,
            "via_marmaray": via_marmaray,
            "disrupted_lines": disrupted,
            "network": _network_tr(graph),
        },
    )


def find_bus_pick(
    origin: Waypoint,
    destination: Waypoint,
    *,
    index: StopIndex | None,
    sequences: Mapping[str, Any] | None,
    params: RoutingParams = DEFAULT_PARAMS,
    line_index: StopRouteIndex | None = None,
) -> tuple[_BusPick | None, str | None]:
    """The single İETT line whose stop order passes a stop near the origin *then* one near the end.

    No transfer is invented. If no one line joins the two ends, the caller is told why: we
    hold stop sequences, not a transfer graph, and a fabricated two-bus itinerary is exactly
    the kind of number this project refuses to print.

    The direction-aware scan is :meth:`ibb_mcp.lines.StopRouteIndex.direct_lines`, the one
    implementation of "origin before destination on the same variant" in the project. This
    function only prices the candidates: by provisional minutes — walk in, ride, walk out —
    at the untuned per-stop rate rather than by stop count alone, because counting stops
    boards the traveller at a stop 700 m away to save one of them. The per-line calibrated
    rate is applied afterwards, when the line is known; it scales every candidate of a line
    equally, so it cannot reorder them, and scanning twice to get it would cost more than it
    buys. ``line_index`` is the prebuilt inverted index (``tools.Nabiz`` builds it once);
    without one, :func:`ibb_mcp.lines.index_for` builds and memoises it for these sequences.
    """
    if index is None or not sequences:
        return None, "GTFS durak sıraları yüklü olmadığı için otobüs seçeneği hesaplanamadı."
    reach, limit = params.bus_access_walk_km, params.bus_stop_candidates
    near_origin = index.nearest_stops(origin.lat, origin.lon, limit=limit, max_km=reach)
    near_destination = index.nearest_stops(destination.lat, destination.lon, limit=limit, max_km=reach)
    origin_stops = {s.stop_code.strip(): s for s in near_origin if s.stop_code and s.stop_code.strip()}
    destination_stops = {s.stop_code.strip(): s for s in near_destination if s.stop_code and s.stop_code.strip()}
    if not origin_stops or not destination_stops:
        end = "Başlangıç" if not origin_stops else "Varış"
        return None, f"{end} noktasının {reach:.1f} km yakınında otobüs durağı yok."

    per_minute_km = params.walk_kmh / (60.0 * params.walk_winding)

    def provisional_minutes(origin_code: str, destination_code: str, stops_between: int) -> float:
        walk_km = (origin_stops[origin_code].distance_km or 0.0) + (destination_stops[destination_code].distance_km or 0.0)
        return walk_km / per_minute_km + stops_between * params.bus_seconds_per_stop / 60.0

    scanner = line_index if line_index is not None else index_for(sequences)
    rides = scanner.direct_lines(
        origin_stops, destination_stops, max_results=1 + max(0, params.bus_other_lines), cost=provisional_minutes
    )
    if not rides:
        return None, (
            "İki ucun yakınındaki durakları aynı sırada geçen tek bir İETT hattı yok; "
            "aktarmalı güzergâh bu veriyle hesaplanamıyor."
        )
    best, others = rides[0], rides[1:]
    return (
        _BusPick(
            route_code=best.route_code,
            line_code=best.line,
            from_stop=origin_stops[best.origin_stop_code],
            to_stop=destination_stops[best.destination_stop_code],
            stops_between=best.stops_between,
            others=tuple(_other_line(ride, origin_stops, destination_stops) for ride in others),
        ),
        None,
    )


def _other_line(ride: DirectLine, origin_stops: Mapping[str, Any], destination_stops: Mapping[str, Any]) -> dict[str, Any]:
    """A runner-up direct line, as plain JSON: where to board, where to get off, how many stops."""
    board, alight = origin_stops[ride.origin_stop_code], destination_stops[ride.destination_stop_code]
    return {
        "line_code": ride.line,
        "route_code": ride.route_code,
        "direction": ride.direction,
        "from_stop": {"stop_code": board.stop_code, "name": board.name, "distance_km": board.distance_km},
        "to_stop": {"stop_code": alight.stop_code, "name": alight.name, "distance_km": alight.distance_km},
        "stops_between": ride.stops_between,
    }


def _implied_speed_kmh(pick: _BusPick, ride_minutes: float) -> float | None:
    """Average speed the ride estimate implies, over the straight line between the stops.

    Returned so a reader can sanity-check the per-stop rate against the corridor: an
    express line that comes out at 9 km/h is telling you the rate needs re-fitting, not
    that the bus is that slow.
    """
    first, second = pick.from_stop, pick.to_stop
    if None in (first.lat, first.lon, second.lat, second.lon) or ride_minutes <= 0:
        return None
    return round(haversine_km(first.lat, first.lon, second.lat, second.lon) / (ride_minutes / 60.0), 1)


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
    notes = ["Tek hatlı güzergâh; aktarmalı seçenekler bu veriyle hesaplanmıyor."]
    if pick.others:
        # Named so "is there another bus?" has an answer, and left without minutes because
        # pricing them honestly needs their own rate and timetable (see _BusPick).
        names = ", ".join(f"{other['line_code']} ({other['stops_between']} durak)" for other in pick.others)
        notes.append(f"Aynı yönde aktarmasız giden başka hatlar da var: {names}; süreleri hesaplanmadı.")
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
        notes=notes,
        detail={
            "line_code": pick.line_code,
            "route_code": pick.route_code,
            "implied_speed_kmh": _implied_speed_kmh(pick, ride_minutes),
            "from_stop": {"stop_code": pick.from_stop.stop_code, "name": pick.from_stop.name},
            "to_stop": {"stop_code": pick.to_stop.stop_code, "name": pick.to_stop.name},
            "stops_between": pick.stops_between,
            "other_direct_lines": list(pick.others),
        },
    )


def seconds_per_stop_for(
    line_code: str, moment: dt.datetime, settings: Any, params: RoutingParams = DEFAULT_PARAMS
) -> tuple[float, str]:
    """The per-stop rate and a Turkish sentence saying where it came from.

    The same choice ``iett_next_arrivals`` makes, through :func:`ibb_mcp.eta_profile.served_rate`
    (DECISIONS #18): the untuned ``params.bus_seconds_per_stop`` unless the operator set
    ``NABIZ_ETA_PROFILE_MODE=calibrated``, because the calibrated profile scored worse on
    stops it was not fitted on. Quoting the provenance matters: "500T, ölçülen 60 varıştan",
    "hiç ölçüm yok" and "ölçüm var ama kullanılmıyor" deserve different wording from the agent.
    """
    from ibb_mcp.eta_profile import MODE_DEFAULT, served_rate

    choice = served_rate(line_code, moment, settings)
    if choice.mode == MODE_DEFAULT:
        return params.bus_seconds_per_stop, DEFAULT_RATE_DETAIL
    if choice.source == "default":
        return choice.seconds_per_stop, "Bu hat için ölçüm yok; kalibre edilmemiş varsayılan oran."
    if choice.source.startswith("global"):
        # The pool is the lines the calibration measured (500T alone in the committed
        # profile); "measured for this line" or "measured across all lines" would both
        # overstate it, and the agent repeats this sentence verbatim.
        pooled = f"{line_code} için ayrı ölçüm yok; {choice.pooled_qualifier} oran ({choice.source})."
        return choice.seconds_per_stop, f"{pooled} {MEASURED_RATE_CAVEAT}"
    return choice.seconds_per_stop, f"{line_code} için ölçülen oran ({choice.source}). {MEASURED_RATE_CAVEAT}"


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
async def compare_options(  # noqa: PLR0913 - debt, ratcheted in scripts/architecture_baseline.json
    origin: Any,
    destination: Any,
    ctx: SourceContext,
    *,
    index: StopIndex | None = None,
    sequences: Mapping[str, Any] | None = None,
    params: RoutingParams = DEFAULT_PARAMS,
    now: dt.datetime | None = None,
    with_timetable: bool = True,
    line_index: StopRouteIndex | None = None,
    traffic_baseline: TrafficBaseline | None = None,
    traffic_baseline_provenance: Provenance | None = None,
) -> RouteAdvice:
    """Compare driving, metro, a single bus line and walking between two points.

    ``origin``/``destination`` may be a :class:`Waypoint`, a ``(lat, lon)`` pair or any
    object carrying ``lat``/``lon`` (``sources.places.Place`` does). ``index`` and
    ``sequences`` are the GTFS index and its route stop orders; without them the bus option
    is withdrawn with a reason rather than guessed. ``line_index`` is the prebuilt
    :class:`~ibb_mcp.lines.StopRouteIndex` over those sequences, a shortcut that never
    changes the answer. ``traffic_baseline`` is the weekday × hour history of the index
    (:mod:`ibb_mcp.traffic_profile`); when given, the live index is compared with it and the
    comparison travels as the ``traffic_typical`` reading, "unknown" included.
    ``traffic_baseline_provenance`` is the stamp of the history read behind it; when given it
    is cited in ``provenance`` and gives that reading its age.

    Nothing here reaches İBB directly — the readings come from the existing sources through
    the shared cache and ``PoliteClient``, so N callers still cost at most one upstream call
    per cache window. A source that fails removes the options that depended on it and
    leaves the rest standing.
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
    traffic_index, traffic_reason, traffic_at = _read_traffic(traffic, readings, provenance)
    stations = _read_payload(station_list, "metro istasyon listesi", provenance)
    statuses = _read_payload(status, "metro bildirimleri", provenance)
    lots = _read_payload(parking, "İSPARK", provenance)

    typical = None
    if traffic_index is not None and traffic_baseline is not None:
        typical = compare_to_typical(traffic_index, traffic_at or moment, traffic_baseline)
        measured = typical.typical if typical.typical is not None else "bilinmiyor"
        age = None
        if traffic_baseline_provenance is not None:
            provenance.append(traffic_baseline_provenance)
            age = round(traffic_baseline_provenance.age_seconds, 1)
        readings.append(Reading("traffic_typical", measured, "1-99", "traffic_history", age, typical.description_tr))
    if statuses is not None:
        active = [line for line in statuses if line.is_active is not False]
        empty_means = "Bildirimi olan hatlar; boş liste bildirilmiş aksaklık yok demektir."
        readings.append(Reading("metro_disruptions", len(active), "hat", "metro_status", detail=empty_means))
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
            lots=lots,
            crossing=_best_crossing(start, end) if crosses else None,
            typical=typical,
            params=params,
        ),
        _metro_option(start, end, graph=rail_graph(stations, params), statuses=statuses, params=params)
        if stations
        else _unavailable("metro", "Metro / raylı sistem", "Metro istasyon listesi okunamadı."),
        await _resolve_bus(start, end, ctx, index, sequences, params, moment, with_timetable, readings, line_index),
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


async def _resolve_bus(  # noqa: PLR0913 - debt, ratcheted in scripts/architecture_baseline.json
    start: Waypoint,
    end: Waypoint,
    ctx: SourceContext,
    index: StopIndex | None,
    sequences: Mapping[str, Any] | None,
    params: RoutingParams,
    moment: dt.datetime,
    with_timetable: bool,
    readings: list[Reading],
    line_index: StopRouteIndex | None = None,
) -> TravelOption:
    """Choose the line, then price it with the served per-stop rate and the real headway."""
    pick, reason = find_bus_pick(start, end, index=index, sequences=sequences, params=params, line_index=line_index)
    if pick is None:
        return _unavailable("bus", "Otobüs (tek hat)", reason or "Otobüs seçeneği hesaplanamadı.")
    # Off the event loop: in the calibrated mode the profile is a JSON file read, and this
    # runs inside a request.
    seconds_per_stop, rate_detail = await asyncio.to_thread(seconds_per_stop_for, pick.line_code, moment, ctx.settings, params)
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


def _read_traffic(
    result: Any, readings: list[Reading], provenance: list[Provenance]
) -> tuple[int | None, str | None, dt.datetime | None]:
    """The live traffic index and when İBB stamped it, or a Turkish reason it is unusable.

    The stamp travels with the index because the weekday × hour comparison must file the
    reading under the hour it was *taken*, not the hour the question was asked.
    """
    if isinstance(result, BaseException):
        log.info("routing: trafik indeksi okunamadı: %r", result)
        return None, f"Trafik indeksi okunamadı ({type(result).__name__}).", None
    point, prov = result
    provenance.append(prov)
    if point is None:
        return None, "Trafik indeksi serisi boş döndü.", None
    if not _valid_traffic_index(point.index):
        # ``TrafficIndexPoint.from_raw`` leaves a null or unparseable index as None, and İBB's
        # scale is 1–99, so a 0 is no reading either. Costing a drive at free-flow speed from
        # a missing reading would be the invented number we refuse.
        return None, "Trafik indeksi geçerli bir değer döndürmedi (İBB ölçeği 1-99); sürüş süresi hesaplanmadı.", None
    what = "İBB şehir geneli trafik yoğunluk indeksi."
    readings.append(Reading("traffic_index", point.index, "1-99", "traffic", round(prov.age_seconds, 1), what))
    return point.index, None, point.at


def _valid_traffic_index(index: Any) -> bool:
    """Whether a traffic reading is on İBB's documented 1–99 scale."""
    return isinstance(index, int | float) and 1 <= index <= 99


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
