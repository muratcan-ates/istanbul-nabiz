"""Contract tests for the web layer.

The whole suite runs against ``Settings(offline=True)`` *and* an HTTP client bolted to a
transport that raises, for the reason spelled out in ``conftest.py``: reaching İBB from a
test is not a slow test, it is a real-world side effect on a shared public gateway. So
every assertion below is about the shape of the response — the envelope, the status codes,
the age stamp the UI depends on — never about a live value.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from conftest import FIXTURES_DIR, offline_settings, refuse_network
from fastapi.testclient import TestClient

from ibb_mcp.cache import TTLCache
from ibb_mcp.http import PoliteClient
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.web.main import STATIC_DIR, create_app

# A stop the 500T really serves, taken from the recorded GTFS sequence. Asking about a stop
# the line does not call at is a different test (the tool refuses it, deliberately).
LINE = "500T"
STOP_CODE = "401351"


@pytest.fixture(scope="module")
def nabiz() -> Iterator[Nabiz]:
    app = Nabiz(
        SourceContext.create(
            client=PoliteClient(transport=httpx.MockTransport(refuse_network)),
            cache=TTLCache(),
            settings=offline_settings(),
        )
    )
    yield app


@pytest.fixture(scope="module")
def client(nabiz: Nabiz) -> Iterator[TestClient]:
    with TestClient(create_app(nabiz=nabiz)) as test_client:
        yield test_client


def envelope_of(response: httpx.Response) -> dict[str, Any]:
    """Assert the common envelope and hand back the parsed body."""
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"data", "provenance", "note"}
    prov = body["provenance"]
    for key in ("source", "source_url", "observed_at", "age", "age_seconds", "stale", "license"):
        assert key in prov, f"provenance is missing {key}"
    # The UI prints this string verbatim on every card, so it must never be empty.
    assert prov["age"]
    assert isinstance(prov["age_seconds"], (int, float))
    return body


# --------------------------------------------------------------------------------------
# health and plumbing
# --------------------------------------------------------------------------------------
def test_healthz_reports_version_and_sources(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert "sources" in body
    assert "request_budget_remaining" in body["sources"]


def test_every_response_carries_a_duration_header(client: TestClient) -> None:
    response = client.get("/healthz")
    assert float(response.headers["X-Response-Time-ms"]) >= 0.0


def test_config_js_exposes_map_key_slot(client: TestClient) -> None:
    response = client.get("/config.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert "window.NABIZ_MAPS_KEY" in response.text
    assert "window.NABIZ_VERSION" in response.text


def test_single_page_and_assets_are_served(client: TestClient) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert "resmî değildir" in page.text
    # the four journeys from PLAN.md §1 must be one tap away
    for chip in ("Taksim'de otopark var mı?", "500T ne zaman gelir?", "M4'te arıza var mı?", "Beşiktaş'ta hava nasıl?"):
        assert chip in page.text
    assert "CC BY 4.0" in page.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/style.css").status_code == 200


def test_cross_origin_is_closed_by_default(client: TestClient) -> None:
    """No allow-origin header for a stranger: the SPA is served from this very origin."""
    response = client.get("/healthz", headers={"Origin": "https://evil.example"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in {k.lower() for k in response.headers}


# --------------------------------------------------------------------------------------
# the twelve tools
# --------------------------------------------------------------------------------------
def test_places_resolves_a_landmark(client: TestClient) -> None:
    body = envelope_of(client.get("/api/places", params={"q": "Taksim"}))
    assert body["data"]["query"] == "Taksim"
    assert body["data"]["matches"], "Taksim is in data/reference/places.csv"
    assert {"name", "lat", "lon"} <= set(body["data"]["matches"][0])


def test_parking_returns_lots_with_free_space(client: TestClient) -> None:
    body = envelope_of(client.get("/api/parking", params={"place": "Taksim", "radius_km": 3}))
    data = body["data"]
    assert data["count"] == len(data["parks"])
    for lot in data["parks"]:
        assert lot["empty"] is None or lot["empty"] >= 1
        assert {"park_id", "name", "distance_km"} <= set(lot)


def test_parking_typical_occupancy_admits_it_has_no_history(client: TestClient) -> None:
    body = envelope_of(client.get("/api/parking/typical", params={"park_id": 758}))
    # The collector has not run in a test environment, so the honest answer is "not yet".
    assert body["data"]["available"] is False
    assert body["note"]


def test_unknown_place_is_a_400_with_a_turkish_explanation(client: TestClient) -> None:
    response = client.get("/api/parking", params={"place": "Zzzyx"})
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "bad_request"
    assert "bulamadım" in body["message"]


def test_unknown_place_is_a_400_for_air_quality_too(client: TestClient) -> None:
    response = client.get("/api/air", params={"place": "Zzzyx"})
    assert response.status_code == 400
    assert response.json()["error"] == "bad_request"


def test_stops_search_returns_gtfs_stops(client: TestClient) -> None:
    body = envelope_of(client.get("/api/stops", params={"q": "Kadıköy", "limit": 5}))
    assert body["data"]["count"] <= 5
    assert {"stop_code", "name"} <= set(body["data"]["stops"][0])


def test_line_buses_never_leak_a_number_plate(client: TestClient) -> None:
    """Privacy rule from NOTICE.md, enforced at the HTTP boundary as well."""
    body = envelope_of(client.get("/api/buses", params={"line": LINE}))
    data = body["data"]
    assert data["line_code"] == LINE
    assert data["count"] == len(data["buses"])
    serialised = str(data).casefold()
    assert "plaka" not in serialised and "plate" not in serialised
    for bus in data["buses"]:
        assert bus["door_no"]


def test_arrivals_are_labelled_as_estimates(client: TestClient) -> None:
    body = envelope_of(client.get("/api/arrivals", params={"line": LINE, "stop": STOP_CODE}))
    data = body["data"]
    assert data["stop"]["stop_code"] == STOP_CODE
    assert "tahmin" in data["disclaimer"].lower()
    for arrival in data["arrivals"]:
        assert arrival["method"] in {"stop_sequence", "distance", "schedule"}
        assert arrival["confidence"] in {"high", "medium", "low"}


def test_arrivals_refuse_a_stop_the_line_does_not_serve(client: TestClient) -> None:
    response = client.get("/api/arrivals", params={"line": LINE, "stop": "Kadıköy"})
    assert response.status_code == 400
    assert "uğramıyor" in response.json()["message"]


def test_metro_status_lists_live_notices(client: TestClient) -> None:
    body = envelope_of(client.get("/api/metro"))
    assert body["data"]["count"] == len(body["data"]["lines"])


def test_metro_status_for_a_quiet_line_says_so_instead_of_returning_nothing(client: TestClient) -> None:
    body = envelope_of(client.get("/api/metro", params={"line": "M4"}))
    assert body["data"]["count"] == 0
    assert "M4" in body["note"]


def test_metro_station_reports_step_free_access(client: TestClient) -> None:
    body = envelope_of(client.get("/api/metro/station", params={"name": "Kartal"}))
    station = body["data"]["stations"][0]
    assert station["line_name"] == "M4"
    assert {"lifts", "escalators", "wc"} <= set(station)


def test_unknown_station_is_a_400(client: TestClient) -> None:
    response = client.get("/api/metro/station", params={"name": "Zzzyx"})
    assert response.status_code == 400


def test_traffic_now_and_history(client: TestClient) -> None:
    now = envelope_of(client.get("/api/traffic", params={"window": "now"}))
    assert 1 <= now["data"]["index"] <= 99
    assert now["data"]["description"]
    history = envelope_of(client.get("/api/traffic", params={"window": "24h"}))
    assert history["data"]["history"]


def test_traffic_rejects_an_unknown_window(client: TestClient) -> None:
    response = client.get("/api/traffic", params={"window": "haftalık"})
    assert response.status_code == 400
    assert response.json()["error"] == "bad_request"


def test_air_quality_now_carries_a_band_and_a_disclaimer(client: TestClient) -> None:
    body = envelope_of(client.get("/api/air", params={"place": "Beşiktaş"}))
    data = body["data"]
    assert data["band"]["key"] in {"good", "moderate", "unhealthy_sensitive", "unhealthy", "very_unhealthy", "hazardous"}
    assert data["disclaimer"] == "Sağlık tavsiyesi değildir."
    assert data["station"]["distance_km"] is not None


def test_air_quality_forecast_declares_its_method(client: TestClient) -> None:
    body = envelope_of(client.get("/api/air/forecast", params={"place": "Beşiktaş", "hours": 6}))
    data = body["data"]
    assert data["horizon_hours"] == 6
    for point in data["forecast"]:
        assert point["method"] == "seasonal_naive_24h"
        assert point["confidence"] == "low"
    assert body["note"], "a baseline forecast must say that it is a baseline"


def test_freshness_lists_sources_and_the_remaining_request_budget(client: TestClient) -> None:
    body = envelope_of(client.get("/api/freshness"))
    data = body["data"]
    assert "sources" in data
    assert data["request_budget_remaining"]["iett"] <= 80
    assert data["attribution"]["tr"].startswith("Kamu sektörü")


def test_missing_required_parameter_is_rejected_not_crashed(client: TestClient) -> None:
    response = client.get("/api/places")
    assert response.status_code == 422
    assert response.json()["detail"]


def test_unknown_api_path_is_a_404(client: TestClient) -> None:
    assert client.get("/api/teleport").status_code == 404


def test_fixtures_directory_is_the_one_the_tests_pin(nabiz: Nabiz) -> None:
    """Guard rail: if this drifts, the suite would silently start hitting the network."""
    assert nabiz.settings.offline is True
    assert nabiz.settings.fixtures_dir == FIXTURES_DIR


# --------------------------------------------------------------------------------------
# the free-text router
# --------------------------------------------------------------------------------------
# The question box is the one piece of logic that lives only in the browser, and it is
# where the wrong-answer bugs are: a misroute sends a bus-stop question to the place
# gazetteer and the user gets "bulamadım" for a stop that exists. Node runs the real
# app.js against a DOM stub so these cases are checked rather than assumed.
ROUTER_HARNESS = """
const fs = require('fs');
const stub = {{ setAttribute() {{}}, addEventListener() {{}}, innerHTML: '', textContent: '', hidden: false }};
global.document = {{
  querySelector: () => stub,
  querySelectorAll: () => [],
  addEventListener: () => {{}},
  createElement: () => stub,
}};
global.window = {{ location: {{ origin: 'http://localhost' }} }};
const src = fs.readFileSync({app_js!r}, 'utf8');
const {{ route }} = eval(src + '\\n;({{ route }});');
const questions = {questions!r};
console.log(JSON.stringify(questions.map((q) => {{
  const r = route(q);
  return [q, r && r.journey, (r && r.args) || {{}}];
}})));
"""

ROUTER_CASES = [
    ("Taksim'de otopark var mı?", "parking", {"place": "Taksim"}),
    ("Beşiktaş'ta hava nasıl?", "air", {"place": "Beşiktaş"}),
    ("Levent'in havası nasıl", "air", {"place": "Levent"}),
    ("M4'te arıza var mı?", "metro", {"line": "M4"}),
    ("Kartal istasyonunda asansör var mı?", "station", {"name": "Kartal"}),
    ("500T Şifa Sondurak", "arrivals", {"line": "500T", "stop": "Şifa Sondurak"}),
    ("500T ne zaman gelir?", "bus", {"line": "500T"}),
    ("trafik nasıl", "traffic", {}),
    ("veri tazeliği", "freshness", {}),
    # Turkish softens the final k to ğ before a vowel; "X durağı" is how the question is
    # actually asked, and matching only "durak" sent it to the place gazetteer instead.
    ("Kadıköy durağı", "stops", {"q": "Kadıköy"}),
    ("Kadıköy durakları", "stops", {"q": "Kadıköy"}),
    # "hava" must not swallow the airport: this is a parking question about a place.
    ("Havalimanı'nda otopark var mı?", "parking", {"place": "Havalimanı"}),
]


def test_free_text_router_picks_the_right_journey(tmp_path) -> None:
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:  # pragma: no cover - CI without node still runs the rest of the suite
        pytest.skip("node is not installed; the router harness needs it")

    app_js = str(STATIC_DIR / "app.js")
    harness = tmp_path / "router_harness.js"
    harness.write_text(
        ROUTER_HARNESS.format(app_js=app_js, questions=[case[0] for case in ROUTER_CASES]),
        encoding="utf-8",
    )
    proc = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    decisions = json.loads(proc.stdout)

    for (question, journey, args), (_, got_journey, got_args) in zip(ROUTER_CASES, decisions, strict=True):
        assert got_journey == journey, f"{question!r} -> {got_journey} (beklenen {journey})"
        for key, value in args.items():
            assert got_args.get(key) == value, f"{question!r} -> {key}={got_args.get(key)!r} (beklenen {value!r})"
