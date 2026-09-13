"""Tests for the route advisor.

Every journey here runs against ``tests/fixtures`` through the offline ``ctx`` fixture,
whose transport turns any outbound request into a failure — so these also prove the
advisor adds no upstream call path.

The bus corridor is a hand-built five-stop stub rather than the real GTFS index, for two
reasons: ``data/reference/gtfs/`` is git-ignored (CI has no 150 MB ``stop_times.txt``), and
a test that parses it would take seconds instead of milliseconds. The stop codes, names and
coordinates below are copied verbatim from the real 500T sequence ``500T_G_D0``, so the
corridor the advisor walks is İBB's own, only shorter.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from ibb_mcp.gtfs import RouteStopSequence
from ibb_mcp.http import UpstreamUnavailable
from ibb_mcp.models import Stop, haversine_km
from ibb_mcp.routing import (
    ASSUMPTION_TEXT,
    DEFAULT_PARAMS,
    ROAD_CROSSINGS,
    RoutingParams,
    Waypoint,
    comfort_score,
    compare_options,
    drive_speed_kmh,
    side_of_bosphorus,
)
from ibb_mcp.sources.traffic import TrafficSource

# Real places (places.csv landmarks and Metro İstanbul station coordinates).
TAKSIM = Waypoint("Taksim Meydanı", 41.037, 28.985)
KADIKOY = Waypoint("Kadıköy İskele", 40.9908, 29.0233)
GALATA = Waypoint("Galata Kulesi", 41.0256, 28.9744)
KARTAL = Waypoint("Kartal", 40.906818, 29.211026)
LEVENT4 = Waypoint("4.Levent", 41.086008, 29.00709)
MECIDIYEKOY = Waypoint("Mecidiyeköy", 41.066141, 28.99458)
MAHMUTBEY = Waypoint("Mahmutbey", 41.054845, 28.830524)
BAHCESEHIR = Waypoint("Bahçeşehir Gölet", 41.0719, 28.6901)
ARNAVUTKOY = Waypoint("Arnavutköy Meydan", 41.1838, 28.7396)

# Stops of route 500T_G_D0 (ŞİFA SONDURAK - 4.LEVENT METRO), positions 38-63 of the real
# sequence, with İBB's own coordinates.
CORRIDOR_STOPS = (
    ("225761", "KARTAL KÖPRÜSÜ", 40.9058340005389, 29.2121149999932),
    ("227461", "KARTAL BÖLGE TRAFİK", 40.9093840005395, 29.2033509999931),
    ("206031", "SOĞANLIK METRO", 40.91281900054, 29.192490999993),
    ("225731", "MALTEPE KÖPRÜSÜ", 40.9366680005438, 29.1382249999922),
    ("225652", "KOZYATAĞI METRO", 40.9757180005499, 29.0992389999915),
    ("220641", "KAVACIK KÖPRÜSÜ", 41.0874860005678, 29.0934459999912),
    ("113326", "4.LEVENT", 41.0877610005678, 29.0070519999895),
    ("301341", "4.LEVENT METRO", 41.0841700160994, 29.0073090167211),
)
CORRIDOR_SEQUENCES = {"500T_G_D0": RouteStopSequence("500T_G_D0", tuple(code for code, *_ in CORRIDOR_STOPS))}


class CorridorIndex:
    """The two GTFS lookups :class:`ibb_mcp.routing.StopIndex` declares, over a stop list."""

    def __init__(self, rows: tuple[tuple[str, str, float, float], ...] = CORRIDOR_STOPS) -> None:
        self.stops = [Stop(stop_code=code, stop_id=code, name=name, lat=lat, lon=lon) for code, name, lat, lon in rows]

    def nearest_stops(self, lat: float, lon: float, limit: int = 5, max_km: float = 1.0) -> list[Stop]:
        scored = [(haversine_km(lat, lon, s.lat, s.lon), s) for s in self.stops]
        near = sorted((pair for pair in scored if pair[0] <= max_km), key=lambda pair: pair[0])
        return [stop.model_copy(update={"distance_km": round(km, 3)}) for km, stop in near[:limit]]

    def route_by_code(self, route_code: str):
        return type("Route", (), {"route_code": route_code, "short_name": "500T"})()


@pytest.fixture
def corridor() -> CorridorIndex:
    return CorridorIndex()


def option(advice, mode: str):
    return next(o for o in advice.options if o.mode == mode)


# --------------------------------------------------------------------------------------
# Taksim -> Kadıköy: the cross-Bosphorus case
# --------------------------------------------------------------------------------------
async def test_taksim_kadikoy_is_a_crossing_and_costs_drive_and_metro(ctx) -> None:
    advice = await compare_options(TAKSIM, KADIKOY, ctx)

    assert advice.crosses_bosphorus is True
    assert option(advice, "drive").available is True
    assert option(advice, "metro").available is True
    # The bridge is named, never folded into the total in silence.
    assert option(advice, "drive").detail["crossing"] in {crossing.name for crossing in ROAD_CROSSINGS}
    assert any(leg.kind == "delay" for leg in option(advice, "drive").legs)


async def test_taksim_kadikoy_metro_routes_through_marmaray_with_two_transfers(ctx) -> None:
    metro = option(await compare_options(TAKSIM, KADIKOY, ctx), "metro")

    assert metro.detail["via_marmaray"] is True
    assert metro.detail["transfers"] == 2
    assert "Marmaray" in metro.detail["lines"]
    # Three rail hops: to the tube, through it, and on to the destination station.
    assert sum(1 for leg in metro.legs if leg.kind == "rail") == 3
    assert metro.comfort.transfers == 2
    assert metro.confidence in {"medium", "low"}  # the crossing is an approximation, and says so


async def test_walking_across_the_bosphorus_is_refused_with_a_reason(ctx) -> None:
    walk = option(await compare_options(TAKSIM, KADIKOY, ctx), "walk")

    assert walk.available is False
    assert walk.total_minutes is None
    assert "Boğaz" in walk.reason


async def test_option_totals_equal_the_sum_of_their_legs(ctx) -> None:
    advice = await compare_options(TAKSIM, KADIKOY, ctx)

    for candidate in advice.available:
        assert candidate.total_minutes == pytest.approx(sum(leg.minutes for leg in candidate.legs), abs=0.05)


# --------------------------------------------------------------------------------------
# Kartal -> 4.Levent: the 500T corridor
# --------------------------------------------------------------------------------------
async def test_kartal_to_4levent_finds_the_500t_corridor(ctx, corridor) -> None:
    advice = await compare_options(KARTAL, LEVENT4, ctx, index=corridor, sequences=CORRIDOR_SEQUENCES)
    bus = option(advice, "bus")

    assert bus.available is True
    assert bus.detail["line_code"] == "500T"
    assert bus.detail["from_stop"]["stop_code"] == "225761"  # KARTAL KÖPRÜSÜ, 0.14 km from the station
    assert bus.detail["to_stop"]["stop_code"] in {"113326", "301341"}
    assert bus.detail["stops_between"] >= 1
    assert [leg.kind for leg in bus.legs] == ["walk", "wait", "ride", "walk"]


async def test_bus_option_needs_stop_sequences_and_says_so(ctx) -> None:
    bus = option(await compare_options(KARTAL, LEVENT4, ctx), "bus")

    assert bus.available is False
    assert "GTFS" in bus.reason


async def test_no_single_line_in_the_right_direction_is_reported_not_invented(ctx, corridor) -> None:
    # The recorded sequence runs Kartal -> 4.Levent. Asking for the reverse must not produce
    # a made-up return trip: stops_between is None when the target is behind the origin.
    bus = option(await compare_options(LEVENT4, KARTAL, ctx, index=corridor, sequences=CORRIDOR_SEQUENCES), "bus")

    assert bus.available is False
    assert "tek bir İETT hattı yok" in bus.reason


async def test_parking_with_live_free_spaces_is_quoted_by_name(ctx, corridor) -> None:
    advice = await compare_options(KARTAL, LEVENT4, ctx, index=corridor, sequences=CORRIDOR_SEQUENCES)
    drive = option(advice, "drive")

    assert drive.detail["parking_lot"]["empty"] > 0
    assert drive.comfort.parking_uncertainty < 1.0
    assert any(leg.basis == "ispark_free_spaces" for leg in drive.legs)
    assert any(reading.key == "ispark_free_spaces" for reading in advice.readings)


# --------------------------------------------------------------------------------------
# short trips, missing infrastructure
# --------------------------------------------------------------------------------------
async def test_a_short_trip_offers_walking(ctx) -> None:
    walk = option(await compare_options(TAKSIM, GALATA, ctx), "walk")

    assert walk.available is True
    assert walk.detail["distance_km"] <= DEFAULT_PARAMS.max_walk_km
    assert walk.comfort.transfers == 0
    assert walk.confidence == "high"


async def test_walking_is_refused_beyond_the_distance_limit(ctx) -> None:
    walk = option(await compare_options(TAKSIM, LEVENT4, ctx), "walk")  # same side, ~6 km

    assert walk.available is False
    assert "2.5 km" in walk.reason


async def test_no_metro_near_either_end_leaves_the_other_options_standing(ctx) -> None:
    advice = await compare_options(BAHCESEHIR, ARNAVUTKOY, ctx)
    metro = option(advice, "metro")

    assert metro.available is False
    assert "raylı sistem istasyonu yok" in metro.reason
    assert option(advice, "drive").available is True  # one missing mode never removes the rest


async def test_a_disrupted_metro_line_is_penalised_and_named(ctx) -> None:
    # The recorded metro_status fixture carries one notice, on M7 — the line joining
    # Mecidiyeköy to Mahmutbey.
    metro = option(await compare_options(MECIDIYEKOY, MAHMUTBEY, ctx), "metro")

    assert metro.available is True
    assert metro.detail["lines"] == ["M7"]
    assert metro.comfort.disruption is True
    assert metro.comfort.penalties["disruption"] == DEFAULT_PARAMS.comfort_disruption
    assert any(leg.basis == "disruption_penalty_minutes" for leg in metro.legs)
    assert any(note.startswith("M7:") for note in metro.notes)


async def test_no_free_parking_nearby_adds_a_penalty_and_says_so(ctx) -> None:
    # Nothing in the recorded İSPARK sample sits within 0.8 km of the Kadıköy pier.
    drive = option(await compare_options(TAKSIM, KADIKOY, ctx), "drive")

    assert drive.detail["parking_lot"] is None
    assert drive.comfort.parking_uncertainty == 1.0
    assert any(leg.basis == "no_parking_penalty_minutes" for leg in drive.legs)
    assert any("boş yer bildiren açık İSPARK otoparkı yok" in note for note in drive.notes)
    assert drive.confidence == "low"  # a bridge guess and a parking guess, stacked


async def test_drive_is_withdrawn_when_the_traffic_index_cannot_be_read(ctx, monkeypatch) -> None:
    async def boom(self):
        raise UpstreamUnavailable("trafik servisi yanıt vermedi", source="traffic")

    monkeypatch.setattr(TrafficSource, "current", boom)
    advice = await compare_options(TAKSIM, KADIKOY, ctx)
    drive = option(advice, "drive")

    assert drive.available is False
    assert drive.total_minutes is None
    assert "Trafik indeksi okunamadı" in drive.reason
    assert option(advice, "metro").available is True
    assert all(reading.key != "traffic_index" for reading in advice.readings)


# --------------------------------------------------------------------------------------
# the honesty contract, comfort, serialisation
# --------------------------------------------------------------------------------------
async def test_every_option_explains_every_number_it_prints(ctx, corridor) -> None:
    advice = await compare_options(KARTAL, LEVENT4, ctx, index=corridor, sequences=CORRIDOR_SEQUENCES)
    reading_keys = {reading.key for reading in advice.readings}

    assert advice.available, "fixtures should cost at least one option"
    for candidate in advice.available:
        assert candidate.assumptions, f"{candidate.mode} lists no assumptions"
        named = {assumption.key for assumption in candidate.assumptions} | reading_keys
        for leg in candidate.legs:
            assert leg.basis in named, f"{candidate.mode}: leg '{leg.description}' cites unexplained '{leg.basis}'"
        for assumption in candidate.assumptions:
            assert assumption.unit and assumption.detail


async def test_unavailable_options_carry_a_reason_and_no_numbers(ctx) -> None:
    advice = await compare_options(TAKSIM, KADIKOY, ctx)

    for candidate in advice.options:
        if candidate.available:
            continue
        assert candidate.reason, f"{candidate.mode} is unavailable without saying why"
        assert candidate.total_minutes is None
        assert candidate.legs == []
        assert candidate.comfort is None


def test_comfort_is_ordered_by_its_four_named_factors() -> None:
    plain = comfort_score(transfers=0, walking_m=200, disruption=False, parking_uncertainty=0.0)
    with_transfer = comfort_score(transfers=1, walking_m=200, disruption=False, parking_uncertainty=0.0)
    with_walk = comfort_score(transfers=0, walking_m=800, disruption=False, parking_uncertainty=0.0)
    with_notice = comfort_score(transfers=0, walking_m=200, disruption=True, parking_uncertainty=0.0)
    with_parking = comfort_score(transfers=0, walking_m=200, disruption=False, parking_uncertainty=1.0)

    assert plain.score > with_transfer.score > 0
    assert plain.score - with_transfer.score == DEFAULT_PARAMS.comfort_per_transfer
    assert plain.score > with_walk.score
    assert plain.score - with_notice.score == DEFAULT_PARAMS.comfort_disruption
    assert plain.score - with_parking.score == DEFAULT_PARAMS.comfort_parking_full_scale
    # The walking penalty is capped so distance can never swamp the other three.
    assert comfort_score(transfers=0, walking_m=50_000, disruption=False, parking_uncertainty=0.0).penalties["walking"] == (
        DEFAULT_PARAMS.comfort_walk_cap
    )


async def test_the_most_comfortable_option_is_not_always_the_fastest(ctx) -> None:
    advice = await compare_options(TAKSIM, GALATA, ctx)

    assert advice.fastest is not None and advice.most_comfortable is not None
    for candidate in advice.available:
        assert candidate.total_minutes >= advice.fastest.total_minutes
        assert candidate.comfort.score <= advice.most_comfortable.comfort.score


def test_the_speed_curve_hits_its_documented_anchors() -> None:
    assert drive_speed_kmh(1) == DEFAULT_PARAMS.free_flow_kmh
    assert drive_speed_kmh(99) == DEFAULT_PARAMS.jam_kmh
    assert drive_speed_kmh(60) == pytest.approx(24.5, abs=0.1)  # the recorded weekday-morning index
    speeds = [drive_speed_kmh(index) for index in range(1, 100, 7)]
    assert speeds == sorted(speeds, reverse=True)
    # Out-of-range input is clamped, never extrapolated into a fantasy speed.
    assert drive_speed_kmh(0) == drive_speed_kmh(1)
    assert drive_speed_kmh(1000) == drive_speed_kmh(99)
    slow = RoutingParams(free_flow_kmh=30.0, jam_kmh=5.0)
    assert drive_speed_kmh(1, slow) == 30.0


def test_the_bosphorus_side_test_agrees_with_the_map() -> None:
    for name, point in (("Taksim", TAKSIM), ("4.Levent", LEVENT4), ("Bahçeşehir", BAHCESEHIR)):
        assert side_of_bosphorus(point.lat, point.lon) == "european", name
    for name, point in (("Kadıköy", KADIKOY), ("Kartal", KARTAL)):
        assert side_of_bosphorus(point.lat, point.lon) == "asian", name
    assert side_of_bosphorus(41.0256, 29.0151) == "asian"  # Üsküdar iskele, right on the shore
    assert side_of_bosphorus(41.0330, 28.9950) == "european"  # Kabataş, facing it


async def test_the_result_is_json_serialisable_and_carries_the_disclaimer(ctx, corridor) -> None:
    advice = await compare_options(KARTAL, LEVENT4, ctx, index=corridor, sequences=CORRIDOR_SEQUENCES)
    payload = json.loads(json.dumps(advice.to_dict(), ensure_ascii=False))

    assert payload["kind"] == "estimate"
    assert "adım adım yol tarifi değildir" in payload["disclaimer"]
    assert payload["fastest_mode"] in {o.mode for o in advice.available}
    assert payload["provenance"] and all("source_url" in stamp for stamp in payload["provenance"])
    assert payload["readings"], "a result with no live reading would have nothing to cite"
    assert isinstance(payload["generated_at"], str)


async def test_coordinates_and_places_are_both_accepted(ctx) -> None:
    from ibb_mcp.sources.places import Place

    at_noon = dt.datetime(2026, 9, 13, 9, 0, tzinfo=dt.UTC)
    from_tuple = await compare_options((TAKSIM.lat, TAKSIM.lon), (GALATA.lat, GALATA.lon), ctx, now=at_noon)
    from_place = await compare_options(
        Place("Taksim Meydanı", TAKSIM.lat, TAKSIM.lon, "landmark", "Beyoğlu"),
        Place("Galata Kulesi", GALATA.lat, GALATA.lon, "landmark", "Beyoğlu"),
        ctx,
        now=at_noon,
    )

    assert from_place.origin.name == "Taksim Meydanı (Beyoğlu)"  # Place.label wins when present
    assert from_tuple.straight_km == from_place.straight_km
    assert option(from_tuple, "walk").total_minutes == option(from_place, "walk").total_minutes


def test_every_assumption_key_has_wording_for_the_agent() -> None:
    for key, (unit, detail) in ASSUMPTION_TEXT.items():
        assert unit and detail.endswith("."), key
