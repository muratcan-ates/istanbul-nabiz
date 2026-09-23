"""Contract tests for :mod:`ibb_mcp.lines`.

Two kinds of test live here, for two different risks.

The behaviour tests run on a hand-built network of seven route variants. They can be read
in one screen, which matters because the thing being tested is a *direction* rule: a
network small enough to hold in your head is the only way to be sure a "no direct line"
result means the module refused correctly rather than missed something. The synthetic
routes deliberately include a line with two forward variants, a one-way feeder with no
return variant, and a route code corrupted the way ``routes.csv`` corrupts 23 of its rows.

The last tests then run against real İETT sequences, because a module built entirely on
invented data proves only that it is self-consistent. They use ``tests/fixtures/gtfs_mini``,
a byte-for-byte cut of the export (see its README), so they run in CI and on a fresh clone:
line 500T runs Şifa Sondurak (401351) to 4. Levent Metro (301341) over 64 stops, comes back
over 66, and does not call at the Kadıköy pier platform 406031, where 8A and 14ŞB do.
"""

from __future__ import annotations

import pytest
from conftest import offline_settings

from ibb_mcp.gtfs import RouteStopSequence, load_stop_sequences
from ibb_mcp.lines import (
    DirectLine,
    StopRouteIndex,
    direct_lines_between,
    lines_serving_stop,
    parse_route_code,
)

# ---------------------------------------------------------------------------------
# a network small enough to read
# ---------------------------------------------------------------------------------
# 1001 - 1002 - 1003 - 1004 - 1005   line 34, both directions
# 1001 - 1002 --------------- 1005   line 34 again, a short-turn variant
# 1001 --------------------- 1005    line 500T, express, both directions
# 2001 - 1002                        line 15F, a feeder that only runs one way
#        1002 - 1003                 line 5, so the ordering test has a number to sort
CORRUPTED_ROUTE_CODE = "SEFERLER MARMARA ÜNİV. R.T.E. YERLEŞKESİ - KÜÇÜKYALI METRO GÜZERGAHINDA HİZMET VERİR."


def sequence(route_code: str, *stop_codes: str) -> RouteStopSequence:
    return RouteStopSequence(route_code=route_code, stop_codes=stop_codes)


@pytest.fixture
def sequences() -> dict[str, RouteStopSequence]:
    return {
        "34_G_D0": sequence("34_G_D0", "1001", "1002", "1003", "1004", "1005"),
        "34_D_D0": sequence("34_D_D0", "1005", "1004", "1003", "1002", "1001"),
        "34_G_D9": sequence("34_G_D9", "1001", "1002", "1005"),
        "500T_G_D0": sequence("500T_G_D0", "1001", "1005"),
        "500T_D_D0": sequence("500T_D_D0", "1005", "1001"),
        "15F_G_D0": sequence("15F_G_D0", "2001", "1002"),
        "5_G_D0": sequence("5_G_D0", "1002", "1003"),
        CORRUPTED_ROUTE_CODE: sequence(CORRUPTED_ROUTE_CODE, "1001", "1005"),
    }


# ---------------------------------------------------------------------------------
# parse_route_code
# ---------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("route_code", "expected"),
    [
        ("500T_G_D0", ("500T", "G")),
        ("500T_D_D6074", ("500T", "D")),
        ("11ÇB_D_D0", ("11ÇB", "D")),  # the mojibake repair in gtfs.py happens before this
        ("1_G_D2783", ("1", "G")),
        ("3", None),  # a shifted column, not line 3
        ("500T_G", None),  # no variant part: not the shape the feed publishes
        (CORRUPTED_ROUTE_CODE, None),
        ("", None),
    ],
)
def test_parse_route_code(route_code: str, expected: tuple[str, str] | None) -> None:
    assert parse_route_code(route_code) == expected


# ---------------------------------------------------------------------------------
# lines_serving_stop
# ---------------------------------------------------------------------------------
def test_lines_serving_stop_deduplicates_variants(sequences: dict[str, RouteStopSequence]) -> None:
    """Stop 1001 is on four variants of two lines; a rider wants the two line numbers."""
    assert lines_serving_stop(sequences, "1001") == ("34", "500T")


def test_lines_serving_stop_sorts_numerically(sequences: dict[str, RouteStopSequence]) -> None:
    """Stop 1002 sees lines 5, 15F and 34. Plain string order would put "5" last."""
    assert lines_serving_stop(sequences, "1002") == ("5", "15F", "34")


def test_lines_serving_stop_ignores_unnameable_routes(sequences: dict[str, RouteStopSequence]) -> None:
    index = StopRouteIndex.build(sequences)
    assert index.unnamed_routes == 1
    assert index.route_count == 7
    assert CORRUPTED_ROUTE_CODE not in index.routes_serving("1001")
    assert all(not line.startswith("SEFERLER") for line in index.lines_serving("1001"))


def test_stop_codes_are_stripped(sequences: dict[str, RouteStopSequence]) -> None:
    assert lines_serving_stop(sequences, " 1001 ") == ("34", "500T")


# ---------------------------------------------------------------------------------
# direct_lines_between — direction is the whole point
# ---------------------------------------------------------------------------------
def test_finds_a_line_when_origin_precedes_destination(sequences: dict[str, RouteStopSequence]) -> None:
    found = direct_lines_between(sequences, ["1001"], ["1004"])
    assert found == [
        DirectLine(
            line="34",
            route_code="34_G_D0",
            origin_stop_code="1001",
            destination_stop_code="1004",
            stops_between=3,
            direction="G",
        )
    ]


def test_finds_nothing_when_the_destination_comes_first(sequences: dict[str, RouteStopSequence]) -> None:
    """The key correctness test: 15F runs 2001 -> 1002 and never the other way.

    The stop pair is on the line either way round, so anything matching on membership would
    answer "take the 15F" here. There is no 15F_D variant, so the honest answer is nothing
    at all.
    """
    assert direct_lines_between(sequences, ["2001"], ["1002"])  # the direction that exists
    assert direct_lines_between(sequences, ["1002"], ["2001"]) == []


def test_a_stop_is_not_a_ride_to_itself(sequences: dict[str, RouteStopSequence]) -> None:
    assert direct_lines_between(sequences, ["1001"], ["1001"]) == []


def test_a_loop_route_is_under_reported_not_guessed() -> None:
    """First visit wins, so boarding after a loop's turning point reads as "no direct line".

    Pinned deliberately: the alternative — counting the second visit — would send a rider to
    a stop the bus only reaches on its way out of the neighbourhood.
    """
    loop = {"99_G_D0": sequence("99_G_D0", "3001", "3002", "3003", "3001")}
    assert direct_lines_between(loop, ["3001"], ["3003"])[0].stops_between == 2
    assert direct_lines_between(loop, ["3003"], ["3001"]) == []


# ---------------------------------------------------------------------------------
# ranking and limits
# ---------------------------------------------------------------------------------
def test_candidates_are_sorted_by_stops_and_one_row_per_line(sequences: dict[str, RouteStopSequence]) -> None:
    """1001 -> 1005 rides on three forward variants of two lines; two rows come back.

    500T does it in one stop and 34 in two (its short-turn variant, not its five-stop one),
    so the shorter ride leads even though "34" sorts first alphabetically and numerically.
    """
    found = direct_lines_between(sequences, ["1001"], ["1005"])
    assert [(ride.line, ride.route_code, ride.stops_between) for ride in found] == [
        ("500T", "500T_G_D0", 1),
        ("34", "34_G_D9", 2),
    ]


def test_the_best_pair_of_stops_wins(sequences: dict[str, RouteStopSequence]) -> None:
    """With several stops in walking range, the reported pair is the shortest ride."""
    found = direct_lines_between(sequences, ["1001", "1003"], ["1004", "1005"])
    ride = next(item for item in found if item.line == "34")
    assert (ride.origin_stop_code, ride.destination_stop_code, ride.stops_between) == ("1003", "1004", 1)


def test_max_results_is_honoured(sequences: dict[str, RouteStopSequence]) -> None:
    assert len(direct_lines_between(sequences, ["1001"], ["1005"], max_results=1)) == 1
    assert direct_lines_between(sequences, ["1001"], ["1005"], max_results=1)[0].line == "500T"
    assert direct_lines_between(sequences, ["1001"], ["1005"], max_results=0) == []


# ---------------------------------------------------------------------------------
# empty and unknown input is an answer, not an error
# ---------------------------------------------------------------------------------
def test_unknown_and_empty_input_returns_empty(sequences: dict[str, RouteStopSequence]) -> None:
    assert lines_serving_stop(sequences, "") == ()
    assert lines_serving_stop(sequences, "   ") == ()
    assert lines_serving_stop(sequences, "9999") == ()
    assert lines_serving_stop({}, "1001") == ()

    assert direct_lines_between(sequences, [], ["1005"]) == []
    assert direct_lines_between(sequences, ["1001"], []) == []
    assert direct_lines_between(sequences, ["  "], ["1005"]) == []
    assert direct_lines_between(sequences, ["9999"], ["8888"]) == []
    assert direct_lines_between({}, ["1001"], ["1005"]) == []


# ---------------------------------------------------------------------------------
# a caller's own yardstick
# ---------------------------------------------------------------------------------
def test_a_cost_function_reorders_lines_and_picks_the_stop_pair(sequences: dict[str, RouteStopSequence]) -> None:
    """The route advisor ranks by minutes including the walk, not by stop count.

    Here boarding at 1001 is made expensive (a long walk), so the 34's ride from 1003 wins
    inside its line even though it is not the shortest in stops overall, and the 500T,
    which can only board at 1001, drops behind it.
    """
    walk = {"1001": 10.0, "1003": 0.0, "1004": 0.0, "1005": 0.0}

    def minutes(origin: str, destination: str, stops: int) -> float:
        return walk[origin] + walk[destination] + stops * 2.0

    plain = direct_lines_between(sequences, ["1001", "1003"], ["1005"])
    priced = direct_lines_between(sequences, ["1001", "1003"], ["1005"], cost=minutes)

    assert [ride.line for ride in plain] == ["500T", "34"]
    assert [(ride.line, ride.origin_stop_code, ride.stops_between) for ride in priced] == [("34", "1003", 2), ("500T", "1001", 1)]


def test_membership_means_some_nameable_variant_calls_there(sequences: dict[str, RouteStopSequence]) -> None:
    index = StopRouteIndex.build(sequences)
    assert "1001" in index and " 1001 " in index
    assert "9999" not in index and "" not in index and 1001 not in index


# ---------------------------------------------------------------------------------
# real İETT sequences, from the committed gtfs_mini cut
# ---------------------------------------------------------------------------------
SIFA_SONDURAK = "401351"
LEVENT_METRO = "301341"
#: A KADIKÖY pier platform: 8A and 14ŞB call here, 500T never does (gtfs_mini/README.md).
KADIKOY_PIER = "406031"


@pytest.fixture(scope="module")
def real_sequences() -> dict[str, RouteStopSequence]:
    return load_stop_sequences(offline_settings())


def test_real_sequences_reproduce_line_500T(real_sequences: dict[str, RouteStopSequence]) -> None:
    """500T, 64 stops Şifa Sondurak -> 4. Levent Metro, and the direction rule on real data."""
    assert len(real_sequences["500T_G_D0"]) == 64

    assert lines_serving_stop(real_sequences, SIFA_SONDURAK) == ("500T",)
    assert lines_serving_stop(real_sequences, LEVENT_METRO) == ("500T",)
    found = direct_lines_between(real_sequences, [SIFA_SONDURAK], [LEVENT_METRO])
    assert [(ride.route_code, ride.direction, ride.stops_between) for ride in found] == [("500T_G_D0", "G", 63)]
    back = direct_lines_between(real_sequences, [LEVENT_METRO], [SIFA_SONDURAK])
    assert [(ride.route_code, ride.direction, ride.stops_between) for ride in back] == [("500T_D_D0", "D", 65)]


def test_real_sequences_name_the_lines_at_the_kadikoy_pier(real_sequences: dict[str, RouteStopSequence]) -> None:
    """Numeric order, and 14ŞB spelled right — it is mojibaked in routes.csv until gtfs.py repairs it."""
    assert lines_serving_stop(real_sequences, KADIKOY_PIER) == ("8A", "14ŞB")
    assert "500T" not in lines_serving_stop(real_sequences, KADIKOY_PIER)
