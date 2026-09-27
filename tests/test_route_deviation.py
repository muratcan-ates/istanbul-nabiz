"""One-shot deviation decisions stay local and have no network or storage."""

from __future__ import annotations

from nabiz.console.route_deviation import route_deviation


def test_sixty_meters_suggests_and_ten_does_not() -> None:
    line = [(41.0, 29.0), (41.01, 29.0)]
    sixty = route_deviation((41.005, 29.000715), line)
    ten = route_deviation((41.005, 29.000119), line)
    assert sixty.distance_m is not None and 58 < sixty.distance_m < 62
    assert sixty.suggest_new_route is True
    assert ten.distance_m is not None and 9 < ten.distance_m < 11
    assert ten.suggest_new_route is False


def test_endpoints_and_invalid_geometry() -> None:
    line = [(41.0, 29.0), (41.001, 29.0)]
    assert route_deviation((41.002, 29.0), line).suggest_new_route is True
    assert route_deviation((41.0, 29.0), line).distance_m == 0
    assert route_deviation((41.0, 29.0), []).distance_m is None
    assert route_deviation((41.0, 29.0), [(float("nan"), 29.0), (41.0, 29.0)]).suggest_new_route is False
