"""No em or en dash in the text the server hands the page (docs/design/DESIGN.md §9, rule 7).

``scripts/check_web_budget.py`` reads the page's own files: ``index.html``, the string literals
of its scripts and CSS ``content``. The rest of what a visitor reads comes from the server: a
route's network sentence and assumptions, the traffic norm sentence, a car park's typical
occupancy note, error messages. On 2026-09-23 several of those carried a dash the static gate
could not see ("oran 1,14 — olağandan daha yoğun", "Yenikapı–Sirkeci–Üsküdar", "1–99"). So this
file holds the server half: every string field of every offline ``/api/*`` response, and the
sentence builders whose inputs the recorded fixtures never reach. The charter's attribution
line is the one allowed dash (owner decision 1, ``ibb_mcp.config.ATTRIBUTION``).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from conftest import offline_settings, refuse_network
from fastapi.testclient import TestClient

from ibb_mcp.cache import TTLCache
from ibb_mcp.config import ATTRIBUTION
from ibb_mcp.http import PoliteClient
from ibb_mcp.models import TrafficIndexPoint
from ibb_mcp.occupancy import build_profile
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from ibb_mcp.traffic_profile import build_baseline, compare_to_typical
from nabiz.web.main import create_app

DASHES = ("—", "–")

#: One call per route the page uses, plus the refusals it renders as answers.
GETS: list[tuple[str, dict[str, Any]]] = [
    ("/api/places", {"q": "Taksim"}),
    ("/api/parking", {"place": "Taksim"}),
    ("/api/parking/typical", {"park_id": 3068, "weekday": 1, "hour": 18}),
    ("/api/route", {"from": "Kadıköy", "to": "Taksim"}),
    ("/api/route", {"from": "Beşiktaş", "to": "Üsküdar"}),
    ("/api/stops", {"q": "Kadıköy"}),
    ("/api/buses", {"line": "500T"}),
    ("/api/arrivals", {"line": "500T", "stop": "401351"}),
    ("/api/arrivals", {"line": "500T", "stop": "406031"}),  # a stop the line does not serve: a refusal
    ("/api/reliability", {"line": "500T"}),
    ("/api/metro", {}),
    ("/api/metro", {"line": "M4"}),
    ("/api/metro/station", {"name": "Kartal"}),
    ("/api/metro/station", {"name": "Hiçyok"}),
    ("/api/traffic", {"window": "now"}),
    ("/api/traffic", {"window": "24h"}),
    ("/api/traffic", {"window": "7d"}),
    ("/api/air", {"place": "Beşiktaş"}),
    ("/api/air/forecast", {"place": "Kadıköy", "hours": 6}),
    ("/api/parking", {"place": "Hiçyokköy"}),
    ("/api/freshness", {}),
    ("/healthz", {}),
]
SUBSCRIPTION = {
    "version": 1,
    "places": [{"key": "home", "label": "Ev", "lat": 40.99, "lon": 29.03}],
    "rules": [
        {"kind": "metro_disruption", "lines": ["M7"]},
        {"kind": "parking_filling", "park_ids": [3068], "threshold_pct": 1},
        {"kind": "air_quality", "place": "home", "aqi_threshold": 1},
        {"kind": "traffic", "threshold_index": 1},
    ],
}


def dashed(value: Any, path: str = "") -> Iterator[tuple[str, str]]:
    """Every string in a JSON value that holds a dash, with its path; the charter line removed first."""
    if isinstance(value, str):
        if any(dash in value.replace(ATTRIBUTION, "") for dash in DASHES):
            yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from dashed(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from dashed(item, f"{path}[{index}]")


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    nabiz = Nabiz(
        SourceContext.create(
            client=PoliteClient(transport=httpx.MockTransport(refuse_network)), cache=TTLCache(), settings=offline_settings()
        )
    )
    with TestClient(create_app(nabiz=nabiz)) as test_client:
        yield test_client


def test_no_api_response_carries_an_em_or_en_dash(client: TestClient) -> None:
    found = []
    for path, params in GETS:
        response = client.get(path, params=params)
        found += [(path, params, where, text) for where, text in dashed(response.json())]
    response = client.post("/api/alerts/check", json=SUBSCRIPTION)
    assert response.status_code == 200, response.text
    found += [("/api/alerts/check", {}, where, text) for where, text in dashed(response.json())]
    assert found == [], found


def test_the_one_allowed_dash_is_the_charter_line_verbatim(client: TestClient) -> None:
    """The allowance is the exact line, so a second dash inside it would still be caught."""
    assert list(dashed(client.get("/api/freshness").json())) == []
    assert "—" in ATTRIBUTION
    assert list(dashed(ATTRIBUTION + " — ek")) != []
    assert client.get("/config.js").text.replace(ATTRIBUTION, "").count("—") == 0


@pytest.mark.parametrize("index", [30, 43, 50, 58, 70])
def test_the_traffic_norm_sentence_has_no_dash_in_any_band(index: int) -> None:
    """The recorded fixture holds one day, so offline the norm is always "unknown"; build one."""
    tuesday = dt.date(2026, 9, 8)
    history = [
        TrafficIndexPoint(
            index=50, at=dt.datetime(tuesday.year, tuesday.month, tuesday.day, 15, 30, tzinfo=dt.UTC) - dt.timedelta(weeks=week)
        )
        for week in range(4)
    ]
    comparison = compare_to_typical(index, dt.datetime(2026, 9, 8, 15, 30, tzinfo=dt.UTC), build_baseline(history))
    assert comparison.typical == 50.0
    for sentence in (comparison.description_tr, comparison.description_en):
        assert not any(dash in sentence for dash in DASHES), sentence


def test_typical_occupancy_notes_have_no_dash() -> None:
    """Both the answer (quartiles, a range) and the one-afternoon refusal, which fixtures cannot reach."""

    def row(day: int, minute: int, occupancy: float) -> dict[str, Any]:
        stamp = dt.datetime(2026, 9, day, 15, minute, tzinfo=dt.UTC).isoformat().replace("+00:00", "Z")
        return {
            "park_id": 501,
            "ts_utc": stamp,
            "snapshot_ts_utc": stamp,
            "capacity": 200,
            "empty": 100,
            "occupancy_pct": occupancy,
            "is_open": True,
            "district": "KADIKÖY",
        }

    two_days = [row(1, 0, 40.0), row(1, 10, 50.0), row(1, 20, 60.0), row(2, 0, 45.0), row(2, 10, 55.0)]
    one_afternoon = [row(1, minute * 10, 50.0 + minute) for minute in range(6)]
    when = dt.datetime(2026, 9, 15, 18, 0)
    answered = build_profile(two_days).lookup(501, when)
    refused = build_profile(one_afternoon).lookup(501, when)
    assert answered["available"] is True and refused["reason"] == "single_window"
    for note in (answered["note"], refused["note"]):
        assert not any(dash in note for dash in DASHES), note
