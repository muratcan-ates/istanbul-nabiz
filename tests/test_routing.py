"""Tests for the route advisor.

Every journey here runs against ``tests/fixtures`` through the offline ``ctx`` fixture,
whose transport turns any outbound request into a failure — so these also prove the
advisor adds no upstream call path.

The bus corridor is a hand-built five-stop stub rather than the real GTFS index, for two
reasons: ``data/reference/gtfs/`` is git-ignored (CI has no 150 MB ``stop_times.txt``), and
a test that parses it would take seconds instead of milliseconds. The stop codes, names and
coordinates below are copied verbatim from the real 500T sequence ``500T_G_D0``, so the
corridor the advisor walks is İBB's own, only shorter.

The metro option runs on the rail graph built from the recorded station list, with the
Marmaray tube added. The tests in "the rail graph inside the advisor" pin what that bought:
one leg per line ridden, notices matched on every line of the path, and an unreadable
notice feed or İSPARK list reported as unknown rather than as good news.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from ibb_mcp.gtfs import RouteStopSequence
from ibb_mcp.http import UpstreamUnavailable
from ibb_mcp.lines import StopRouteIndex
from ibb_mcp.models import MetroLineStatus, Provenance, Stop, TrafficIndexPoint, haversine_km, utcnow
from ibb_mcp.routing import (
    ASSUMPTION_TEXT,
    DEFAULT_PARAMS,
    ROAD_CROSSINGS,
    RoutingParams,
    Waypoint,
    comfort_score,
    compare_options,
    drive_speed_kmh,
    line_code,
    side_of_bosphorus,
)
from ibb_mcp.sources.base import make_provenance
from ibb_mcp.sources.ispark import IsparkSource
from ibb_mcp.sources.metro import MetroSource
from ibb_mcp.sources.traffic import TrafficSource
from ibb_mcp.traffic_profile import build_baseline

# Real places (places.csv landmarks and Metro İstanbul station coordinates).
TAKSIM = Waypoint("Taksim Meydanı", 41.037, 28.985)
KADIKOY = Waypoint("Kadıköy İskele", 40.9908, 29.0233)
GALATA = Waypoint("Galata Kulesi", 41.0256, 28.9744)
KARTAL = Waypoint("Kartal", 40.906818, 29.211026)
LEVENT4 = Waypoint("4.Levent", 41.086008, 29.00709)
MECIDIYEKOY = Waypoint("Mecidiyeköy", 41.066141, 28.99458)
MAHMUTBEY = Waypoint("Mahmutbey", 41.054845, 28.830524)
AKSARAY_T1 = Waypoint("Aksaray T1", 41.0095939384, 28.9538598842)
KABATAS_F1 = Waypoint("Kabataş F1", 41.0338745666, 28.9922350785)
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


async def test_the_prebuilt_route_index_is_only_a_shortcut(ctx, corridor) -> None:
    # The inverted index exists to skip route variants, never to change which one wins.
    plain = await compare_options(KARTAL, LEVENT4, ctx, index=corridor, sequences=CORRIDOR_SEQUENCES)
    prebuilt = StopRouteIndex.build(CORRIDOR_SEQUENCES)
    indexed = await compare_options(KARTAL, LEVENT4, ctx, index=corridor, sequences=CORRIDOR_SEQUENCES, line_index=prebuilt)

    assert option(indexed, "bus").detail == option(plain, "bus").detail
    assert option(indexed, "bus").total_minutes == option(plain, "bus").total_minutes
    assert prebuilt.routes_serving("225761") == ("500T_G_D0",)
    assert "225761" in prebuilt and "999999" not in prebuilt


async def test_the_stop_gap_matches_the_gtfs_sequence(ctx, corridor) -> None:
    # The scan reads positions from a dict for speed; it must still agree with the
    # RouteStopSequence method the rest of the project uses.
    bus = option(await compare_options(KARTAL, LEVENT4, ctx, index=corridor, sequences=CORRIDOR_SEQUENCES), "bus")
    sequence = CORRIDOR_SEQUENCES[bus.detail["route_code"]]

    assert bus.detail["stops_between"] == sequence.stops_between(
        bus.detail["from_stop"]["stop_code"], bus.detail["to_stop"]["stop_code"]
    )


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


async def test_the_tool_layers_dump_helper_can_serialise_the_result(ctx) -> None:
    # tools._dump prefers model_dump; without the alias it would take its generic dataclass
    # walk, which drops every None (the "unknown" markers) and the derived fastest_mode keys.
    from ibb_mcp.tools import _dump

    advice = await compare_options(TAKSIM, GALATA, ctx)
    dumped = _dump(advice)

    assert isinstance(dumped, dict)
    assert dumped == advice.to_dict()
    assert dumped["options"][0]["mode"] == "drive"


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


# --------------------------------------------------------------------------------------
# the rail graph inside the advisor
# --------------------------------------------------------------------------------------
def notices(*rows: MetroLineStatus):
    """A stand-in for ``MetroSource.service_status`` returning exactly these notices."""

    async def service_status(self):
        return list(rows), make_provenance("metro_status")

    return service_status


async def test_each_line_ridden_is_one_leg_and_each_change_is_named(ctx) -> None:
    metro = option(await compare_options(TAKSIM, KADIKOY, ctx), "metro")

    assert metro.detail["lines"] == ["M2", "Marmaray", "M4"]
    assert [leg.description for leg in metro.legs if leg.kind == "rail"] == [
        "M2: Taksim → Yenikapı, 4 durak",
        "Marmaray: Yenikapı → Ayrılık Çeşmesi, 3 durak",
        "M4: Ayrılık Çeşmesi → Kadıköy, 1 durak",
    ]
    assert [leg.description for leg in metro.legs if leg.kind == "transfer"] == [
        "Yenikapı: M2 → Marmaray aktarması",
        "Ayrılık Çeşmesi: Marmaray → M4 aktarması",
    ]
    assert metro.detail["stops"] == 8
    # Name-matched transfers would have crossed at Bahariye (T3 in Kadıköy, M9 in Bağcılar).
    assert not {"T3", "M9"} & set(metro.detail["lines"])
    assert {a.key for a in metro.assumptions} >= {"rail_ride", "rail_transfer", "marmaray_tube", "metro_headway_minutes"}


async def test_without_the_marmaray_rows_the_water_cannot_be_crossed_by_rail(ctx) -> None:
    metro = option(await compare_options(TAKSIM, KADIKOY, ctx, params=RoutingParams(include_marmaray=False)), "metro")

    assert metro.available is False
    assert "Metrobüs ve vapur bu veride yok" in metro.reason
    assert "Marmaray" not in metro.reason


async def test_a_notice_on_a_line_in_the_middle_of_the_path_counts(ctx, monkeypatch) -> None:
    """Aksaray T1 → Kabataş F1 rides T1, M2 and F1; neither end is on M2."""
    notice = MetroLineStatus(line_id=2, line_name="M2", description="Vezneciler'de çalışma var.", is_active=True)
    monkeypatch.setattr(MetroSource, "service_status", notices(notice))
    metro = option(await compare_options(AKSARAY_T1, KABATAS_F1, ctx), "metro")

    assert metro.detail["lines"] == ["T1", "M2", "F1"]
    assert metro.detail["disrupted_lines"] == ["M2"]
    assert any(leg.basis == "disruption_penalty_minutes" for leg in metro.legs)
    assert "M2: Vezneciler'de çalışma var." in metro.notes


async def test_a_retired_notice_costs_nothing(ctx, monkeypatch) -> None:
    retired = MetroLineStatus(line_id=7, line_name="M7", description="Çalışma tamamlandı.", is_active=False)
    monkeypatch.setattr(MetroSource, "service_status", notices(retired))
    advice = await compare_options(MECIDIYEKOY, MAHMUTBEY, ctx)
    metro = option(advice, "metro")

    assert metro.detail["disrupted_lines"] == []
    assert not any(leg.kind == "delay" for leg in metro.legs)
    assert next(r for r in advice.readings if r.key == "metro_disruptions").value == 0


async def test_an_unplaceable_notice_is_reported_not_dropped(ctx, monkeypatch) -> None:
    odd = MetroLineStatus(line_id=99, line_name="Yıldız-Mahmutbey", description="Aksama var.", is_active=True)
    monkeypatch.setattr(MetroSource, "service_status", notices(odd))
    metro = option(await compare_options(MECIDIYEKOY, MAHMUTBEY, ctx), "metro")

    assert metro.detail["disrupted_lines"] == []
    assert any("eşlenemeyen" in note and "Yıldız-Mahmutbey" in note for note in metro.notes)


async def test_unread_notices_are_unknown_not_all_clear(ctx, monkeypatch) -> None:
    async def down(self):
        raise UpstreamUnavailable("metro bildirimleri yanıt vermedi", source="metro_status")

    monkeypatch.setattr(MetroSource, "service_status", down)
    advice = await compare_options(MECIDIYEKOY, MAHMUTBEY, ctx)
    metro = option(advice, "metro")

    assert metro.available is True
    assert not any(leg.kind == "delay" for leg in metro.legs)
    assert any("okunamadı" in note and "bilinmiyor" in note for note in metro.notes)
    assert metro.confidence == "medium"  # one notch for not knowing, as the M7 notice itself would cost
    assert all(reading.key != "metro_disruptions" for reading in advice.readings)


async def test_unread_parking_is_unknown_not_full(ctx, monkeypatch) -> None:
    async def down(self, *args, **kwargs):
        raise UpstreamUnavailable("İSPARK yanıt vermedi", source="ispark")

    monkeypatch.setattr(IsparkSource, "find_near", down)
    drive = option(await compare_options(KARTAL, LEVENT4, ctx), "drive")

    assert drive.detail["parking_read"] is False
    assert any("İSPARK verisi okunamadı" in note for note in drive.notes)
    assert not any("boş yer bildiren açık İSPARK otoparkı yok" in note for note in drive.notes)
    assert any(leg.basis == "no_parking_penalty_minutes" for leg in drive.legs)


def test_line_codes_fold_the_way_both_feeds_spell_them() -> None:
    assert line_code("M7 Yıldız-Mahmutbey") == "M7"
    assert line_code("m1a") == "M1A"
    assert line_code("  ") is None and line_code(None) is None


# --------------------------------------------------------------------------------------
# the traffic baseline and the other direct lines
# --------------------------------------------------------------------------------------
#: The recorded traffic fixture's newest point: 60, stamped Tuesday 2026-09-08 09:00 İstanbul.
FIXTURE_READING_AT = dt.datetime(2026, 9, 8, 6, 0, tzinfo=dt.UTC)


async def test_a_measurably_heavier_hour_is_a_reading_and_a_drive_note(ctx) -> None:
    earlier = [TrafficIndexPoint(index=40, at=FIXTURE_READING_AT - dt.timedelta(weeks=w)) for w in (1, 2, 3, 4)]
    advice = await compare_options(TAKSIM, LEVENT4, ctx, traffic_baseline=build_baseline(earlier))
    drive = option(advice, "drive")
    reading = next(r for r in advice.readings if r.key == "traffic_typical")

    assert reading.value == 40.0 and reading.source == "traffic_history"
    assert drive.detail["traffic_vs_typical"] == "much_heavier"
    assert any("Salı 09:00" in note and "olağandan belirgin biçimde yoğun" in note for note in drive.notes)
    # A fact beside the estimate, never a second speed curve: the minutes do not move.
    plain = option(await compare_options(TAKSIM, LEVENT4, ctx), "drive")
    assert drive.total_minutes == plain.total_minutes


async def test_the_typical_reading_carries_the_history_reads_source_and_age(ctx) -> None:
    earlier = [TrafficIndexPoint(index=40, at=FIXTURE_READING_AT - dt.timedelta(weeks=w)) for w in (1, 2, 3, 4)]
    stamp = Provenance(
        source="traffic",
        source_url="TrafficIndexHistory/28/H",
        observed_at=utcnow() - dt.timedelta(hours=2),
    )
    advice = await compare_options(
        TAKSIM, LEVENT4, ctx, traffic_baseline=build_baseline(earlier), traffic_baseline_provenance=stamp
    )
    reading = next(r for r in advice.readings if r.key == "traffic_typical")

    assert stamp in advice.provenance
    assert reading.age_seconds is not None and reading.age_seconds >= 7_000


async def test_an_hour_without_a_norm_says_so(ctx) -> None:
    advice = await compare_options(TAKSIM, LEVENT4, ctx, traffic_baseline=build_baseline([]))
    reading = next(r for r in advice.readings if r.key == "traffic_typical")

    assert reading.value == "bilinmiyor"
    assert "0 gözlem" in reading.detail
    assert option(advice, "drive").detail["traffic_vs_typical"] == "unknown"
    assert not any("olağan" in note for note in option(advice, "drive").notes)


async def test_no_baseline_means_no_typical_reading(ctx) -> None:
    advice = await compare_options(TAKSIM, LEVENT4, ctx)
    assert all(r.key != "traffic_typical" for r in advice.readings)


async def test_other_direct_lines_are_named_but_not_timed(ctx, corridor) -> None:
    # A second, invented line over real corridor stops: fewer stops, but a 0.7 km walk to board.
    sequences = {**CORRIDOR_SEQUENCES, "E10_G_D0": RouteStopSequence("E10_G_D0", ("227461", "206031", "220641", "301341"))}
    bus = option(await compare_options(KARTAL, LEVENT4, ctx, index=corridor, sequences=sequences), "bus")

    assert bus.detail["line_code"] == "500T", "the shorter walk wins on minutes, not on stop count"
    others = bus.detail["other_direct_lines"]
    assert [(o["line_code"], o["from_stop"]["stop_code"], o["to_stop"]["stop_code"], o["stops_between"]) for o in others] == [
        ("E10", "227461", "301341", 3)
    ]
    assert "minutes" not in others[0] and "total_minutes" not in others[0]
    assert any("E10 (3 durak)" in note and "süreleri hesaplanmadı" in note for note in bus.notes)


async def test_a_route_code_that_names_no_line_is_never_offered(ctx, corridor) -> None:
    """``routes.csv`` shifts a column on 23 rows; 7 reach the sequences with prose as their code."""
    prose = "SEFERLER MARMARA ÜNİV. R.T.E. YERLEŞKESİ - KÜÇÜKYALI METRO GÜZERGAHINDA HİZMET VERİR."
    sequences = {prose: RouteStopSequence(prose, tuple(code for code, *_ in CORRIDOR_STOPS))}
    bus = option(await compare_options(KARTAL, LEVENT4, ctx, index=corridor, sequences=sequences), "bus")

    assert bus.available is False
    assert "tek bir İETT hattı yok" in bus.reason
