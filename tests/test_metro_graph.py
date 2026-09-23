"""Regression tests for the rail graph, written around the way it can silently lie.

The dangerous failure here is not an exception, it is a plausible answer: match transfers
on station names and the graph gains a 20.7 km hop across the Bosphorus at Bahariye, after
which Kadıköy → Taksim returns a confident 64 minutes that no train can deliver.
Nothing crashes, no number looks odd, and the agent repeats it. So the assertions below
are mostly about connections that must **not** exist and journeys that must stay
impossible, and the timing checks are ranges rather than equalities — the constants in
:class:`MetroGraphParams` are a calibration that may be retuned, while "Kartal to Kadıköy
is fifteen stops on M4 alone" is a fact about the network that may not.

Everything runs off ``tests/fixtures/metro_stations.json``, the recorded ``GetStations``
payload. No network, no clock, no randomness.

The Marmaray tests at the end pin the one crossing the route advisor adds on purpose: rows
the caller vouches for, placed on four stations the feed already has, and subject to the
same distance rule as everything else — so adding them must not resurrect Bahariye.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import fields
from typing import Any

import pytest

from ibb_mcp.metro_graph import (
    DEFAULT_METRO_PARAMS,
    MARMARAY_LINE,
    MARMARAY_TUBE,
    MetroGraph,
    MetroGraphParams,
    MetroLeg,
    marmaray_tube,
    mode_for_line,
)
from ibb_mcp.models import MetroStation

#: Every line Metro İstanbul reports in the recorded payload.
EXPECTED_LINES = (
    "F1", "F4", "M1A", "M1B", "M2", "M3", "M4", "M5",
    "M6", "M7", "M8", "M9", "T1", "T3", "T4", "T5", "TF1", "TF2",
)


@pytest.fixture(scope="module")
def stations(load_fixture: Any) -> list[MetroStation]:
    return [MetroStation.from_raw(row) for row in load_fixture("metro_stations")["Data"]]


@pytest.fixture(scope="module")
def graph(stations: list[MetroStation]) -> MetroGraph:
    """One graph for the whole module: it is immutable once built, and building is the slow part."""
    return MetroGraph.from_stations(stations)


def station_on(graph: MetroGraph, name: str, line: str) -> MetroStation:
    """The platform of ``name`` that belongs to ``line``, failing loudly if the fixture changed."""
    for station in graph.find_stations(name):
        if station.line_name == line:
            return station
    raise AssertionError(f"fixture has no {name} on {line}")


def neighbours(graph: MetroGraph, station: MetroStation) -> Iterator[MetroStation]:
    """Stations one edge away.

    This reaches into the edge table on purpose. The phantom-transfer regression is about a
    single edge existing; asserting only on paths would also pass if the edge were built and
    merely never chosen.
    """
    index = graph._stations.index(station)
    for edge in graph._edges[index]:
        yield graph._stations[edge.to_node]


def ride_legs(legs: tuple[MetroLeg, ...]) -> list[MetroLeg]:
    return [leg for leg in legs if leg.kind == "ride"]


# -- 1. what the fixture actually contains ---------------------------------------------
def test_graph_loads_every_usable_station_and_line(graph: MetroGraph) -> None:
    assert graph.station_count == 245
    assert graph.lines == EXPECTED_LINES
    assert len(graph.lines) == 18
    # 248 rows in, 3 dropped: the M5 Sultanbeyli extension ships without coordinates.
    assert graph.dropped_stations == 3


# -- 2. the phantom transfer ------------------------------------------------------------
def test_bahariye_is_two_places_and_the_graph_knows_it(graph: MetroGraph) -> None:
    tram, metro = station_on(graph, "Bahariye", "T3"), station_on(graph, "Bahariye", "M9")

    assert metro not in list(neighbours(graph, tram))
    assert tram not in list(neighbours(graph, metro))

    rejected = [r for r in graph.rejected_transfers if r.name == "Bahariye"]
    assert len(rejected) == 1
    assert {rejected[0].line_a, rejected[0].line_b} == {"T3", "M9"}
    assert rejected[0].km == pytest.approx(20.677, abs=0.01)


def test_the_phantom_is_real_when_names_are_trusted(stations: list[MetroStation]) -> None:
    """Why the distance rule exists: trust every shared name and the strait disappears.

    A 100 km "named walk" allowance, walked at an absurd speed, makes every same-name pair a
    plain four-minute transfer — the graph a name-matching implementation would build.
    """
    trusting = MetroGraph.from_stations(stations, params=MetroGraphParams(max_named_walk_km=100.0, walk_speed_kmh=1e9))
    path = trusting.path_between_stations("Kadıköy", "Taksim").path

    assert path is not None
    assert {"T3", "M9"} <= set(path.lines)
    assert round(path.total_seconds / 60) == 64


def test_a_t3_station_cannot_reach_an_m9_station(graph: MetroGraph) -> None:
    """The consequence of the edge above, stated as a journey: T3 is in Kadıköy, M9 in Bağcılar."""
    result = graph.path_between_stations("Moda", "MASKO")
    assert result.path is None
    assert result.reason == "disconnected"


def test_every_rejected_transfer_is_a_shared_name_beyond_walking_range(graph: MetroGraph) -> None:
    assert graph.rejected_transfers, "the phantom log should not be empty for this dataset"
    for rejected in graph.rejected_transfers:
        assert rejected.km > DEFAULT_METRO_PARAMS.max_named_walk_km
        assert rejected.line_a != rejected.line_b
    # Aksaray M1A/T1 is 557 m apart: a real walking interchange, so it must not be rejected.
    assert "Aksaray" not in {r.name for r in graph.rejected_transfers}


# -- 3. the crossing this dataset does not have ----------------------------------------
def test_kadikoy_to_taksim_has_no_rail_path(graph: MetroGraph) -> None:
    """Correct answer, not a bug: Marmaray and the ferries are not in Metro İstanbul's feed."""
    result = graph.path_between_stations("Kadıköy", "Taksim")
    assert result.path is None
    assert result.reason == "disconnected"


# -- 4-6. journeys that are real --------------------------------------------------------
def test_kartal_to_kadikoy_runs_the_length_of_m4(graph: MetroGraph) -> None:
    result = graph.path_between_stations("Kartal", "Kadıköy")
    assert result.reason is None
    path = result.path
    assert path is not None

    assert path.lines == ("M4",)
    assert path.transfer_count == 0
    assert len(ride_legs(path.legs)) == 15
    assert path.stop_count == 15
    assert 35 < path.total_seconds / 60 < 50


def test_yenikapi_to_taksim_stays_on_m2(graph: MetroGraph) -> None:
    """Yenikapı is on M1A, M1B and M2; naming it must not force the wrong platform."""
    result = graph.path_between_stations("Yenikapı", "Taksim")
    assert result.reason is None
    path = result.path
    assert path is not None

    assert path.lines == ("M2",)
    assert path.transfer_count == 0
    assert path.total_seconds / 60 < 15


def test_aksaray_to_kabatas_changes_line(graph: MetroGraph) -> None:
    """No single line joins them, so the answer has to be an interchange or nothing."""
    result = graph.path_between_stations("Aksaray", "Kabataş")
    assert result.reason is None
    path = result.path
    assert path is not None

    assert len(path.lines) > 1
    assert path.transfer_count >= 1
    assert path.ride_seconds < path.total_seconds


def test_an_unknown_name_is_named_as_such(graph: MetroGraph) -> None:
    assert graph.path_between_stations("Zümrüt Sokak", "Taksim").reason == "unknown_origin"
    assert graph.path_between_stations("Taksim", "Zümrüt Sokak").reason == "unknown_destination"


# -- 7. name normalisation --------------------------------------------------------------
def test_the_three_spellings_of_4_levent_are_one_station(graph: MetroGraph) -> None:
    spellings = ["4. Levent", "4.Levent", "4 levent"]
    resolved = [graph.find_stations(spelling) for spelling in spellings]

    for spelling, matches in zip(spellings, resolved, strict=True):
        assert matches, f"{spelling!r} matched nothing"
    best = [matches[0] for matches in resolved]
    assert {(s.name, s.line_name, s.order) for s in best} == {("4.Levent", "M2", 10)}
    # And the plain "Levent" two stops down the line is a different station, not a near miss.
    assert station_on(graph, "Levent", "M2").order == 9


# -- 8. door to door --------------------------------------------------------------------
def test_path_between_points_walks_on_at_one_end_and_off_at_the_other(graph: MetroGraph) -> None:
    kartal, kadikoy = station_on(graph, "Kartal", "M4"), station_on(graph, "Kadıköy", "M4")
    assert kartal.lat is not None and kartal.lon is not None
    assert kadikoy.lat is not None and kadikoy.lon is not None
    origin = (kartal.lat + 0.003, kartal.lon + 0.003)
    destination = (kadikoy.lat - 0.002, kadikoy.lon + 0.002)

    result = graph.path_between_points(origin, destination)
    assert result.reason is None
    path = result.path
    assert path is not None

    assert path.legs[0].kind == "access"
    assert path.legs[0].to_station == "Kartal"
    assert path.legs[-1].kind == "egress"
    assert path.legs[-1].from_station == "Kadıköy"
    assert path.lines == ("M4",)
    # One headway is charged for the first boarding, and the walking adds to the ride.
    assert path.wait_seconds == DEFAULT_METRO_PARAMS.mean_wait_seconds
    assert path.total_seconds > path.ride_seconds + path.wait_seconds


def test_a_point_far_from_every_station_says_so(graph: MetroGraph) -> None:
    """Şile, on the Black Sea coast, has no rail within the access walk."""
    kadikoy = station_on(graph, "Kadıköy", "M4")
    assert kadikoy.lat is not None and kadikoy.lon is not None
    result = graph.path_between_points((41.1756, 29.6128), (kadikoy.lat, kadikoy.lon))
    assert result.path is None
    assert result.reason == "no_station_near_origin"


def test_stations_near_is_sorted_and_bounded(graph: MetroGraph) -> None:
    kadikoy = station_on(graph, "Kadıköy", "M4")
    assert kadikoy.lat is not None and kadikoy.lon is not None
    near = graph.stations_near(kadikoy.lat, kadikoy.lon, radius_km=2.0)

    assert near[0][0].name == "Kadıköy"
    assert near[0][1] == pytest.approx(0.0, abs=1e-9)
    assert [km for _, km in near] == sorted(km for _, km in near)
    assert all(km <= 2.0 for _, km in near)


# -- 9. disclosure ----------------------------------------------------------------------
def test_assumptions_publishes_every_tunable_constant(graph: MetroGraph) -> None:
    """If a constant can move an answer, the tool layer has to be able to print it."""
    disclosed = graph.assumptions()
    for field in fields(MetroGraphParams):
        assert field.name in disclosed
        assert disclosed[field.name] == getattr(DEFAULT_METRO_PARAMS, field.name)
    assert "distance" in str(disclosed["transfer_rule"])


def test_params_are_honoured_rather_than_hardcoded(stations: list[MetroStation]) -> None:
    """A tighter named-walk allowance must move the phantom log, not just the docstring."""
    strict = MetroGraph.from_stations(stations, params=MetroGraphParams(max_named_walk_km=0.1))

    assert "Aksaray" in {r.name for r in strict.rejected_transfers}
    assert strict.assumptions()["max_named_walk_km"] == 0.1


def test_line_codes_map_to_the_right_rolling_stock() -> None:
    assert mode_for_line("TF1") == "funicular"
    assert mode_for_line("F1") == "funicular"
    assert mode_for_line("T3") == "tram"
    assert mode_for_line("M9") == "metro"


# -- 10. the one published run time in the repository ------------------------------------
def test_m7_end_to_end_lands_near_metro_istanbuls_published_36_minutes(graph: MetroGraph, load_fixture: Any) -> None:
    """The recorded M7 notice carries Metro İstanbul's own line card: 17 stations, 36 minutes.

    The only published run time in the fixtures, so it is the one place the rail constants
    can be checked against something other than a guess. ±15 % leaves room for a retune; a
    constant that moved the answer further than that would need this test rewritten, loudly.
    """
    card = next(row["LineContent"] for row in load_fixture("metro_status")["Data"] if row["LineName"] == "M7")
    assert "İstasyon Sayısı: 17" in card and "36 Dakika (Tek Y&ouml;nde)" in card

    path = graph.path_between_stations("Yıldız", "Mahmutbey").path
    assert path is not None and path.lines == ("M7",)
    assert path.stop_count == 16  # 17 stations, 16 hops
    assert 36 * 0.85 <= path.total_seconds / 60 <= 36 * 1.15


# -- 11. Marmaray, added on purpose -----------------------------------------------------
@pytest.fixture(scope="module")
def with_marmaray(stations: list[MetroStation]) -> MetroGraph:
    return MetroGraph.from_stations(stations, added=marmaray_tube(stations))


def test_the_tube_is_built_from_four_stations_the_feed_already_has(stations: list[MetroStation]) -> None:
    rows = marmaray_tube(stations)

    assert [row.name for row in rows] == list(MARMARAY_TUBE)
    assert [row.order for row in rows] == [1, 2, 3, 4]
    assert {row.line_name for row in rows} == {MARMARAY_LINE}
    assert all(row.station_id is None for row in rows), "our rows must not pass for Metro İstanbul records"
    for row in rows:
        twin = next(s for s in stations if s.name == row.name and s.lat is not None)
        assert (row.lat, row.lon) == (twin.lat, twin.lon)


def test_too_few_anchors_build_no_line(stations: list[MetroStation]) -> None:
    only_yenikapi = [s for s in stations if s.name == "Yenikapı"]
    assert marmaray_tube(only_yenikapi) == []
    assert marmaray_tube([]) == []


def test_marmaray_crosses_the_water_and_bahariye_stays_rejected(with_marmaray: MetroGraph) -> None:
    result = with_marmaray.path_between_stations("Kadıköy", "Taksim")
    assert result.reason is None and result.path is not None

    assert result.path.lines == ("M4", MARMARAY_LINE, "M2")
    assert result.path.transfer_count == 2
    assert not {"T3", "M9"} & set(result.path.lines), "the crossing must be Marmaray, never the Bahariye phantom"
    assert "Bahariye" in {r.name for r in with_marmaray.rejected_transfers}
    # The transfers are in-station: each Marmaray row shares its coordinate with a feed platform.
    assert all(leg.km == 0.0 for leg in result.path.legs if leg.kind == "transfer")


def test_added_lines_are_disclosed(graph: MetroGraph, with_marmaray: MetroGraph) -> None:
    assert graph.added_lines == ()
    assert with_marmaray.added_lines == (MARMARAY_LINE,)
    assert "no Marmaray" in str(graph.assumptions()["network"])
    assert "Marmaray" in str(with_marmaray.assumptions()["network"])
    assert with_marmaray.station_count == graph.station_count + len(MARMARAY_TUBE)
    assert with_marmaray.dropped_stations == graph.dropped_stations
