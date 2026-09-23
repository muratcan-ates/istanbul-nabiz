"""Contract tests for the web layer.

The whole suite runs against ``Settings(offline=True)`` *and* an HTTP client bolted to a
transport that raises, for the reason spelled out in ``conftest.py``: reaching İBB from a
test is not a slow test, it is a real-world side effect on a shared public gateway. So
every assertion below is about the shape of the response — the envelope, the status codes,
the age stamp the UI depends on — never about a live value.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from conftest import FIXTURES_DIR, GTFS_MINI_DIR, REPO_ROOT, offline_settings, refuse_network
from fastapi.testclient import TestClient

from ibb_mcp.cache import TTLCache
from ibb_mcp.http import PoliteClient
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.web.main import STATIC_DIR, create_app

# GTFS comes from tests/fixtures/gtfs_mini (see its README), cut from İBB's export so these
# tests run the same in CI as on a laptop. ŞİFA SONDURAK is the 500T's southern terminus:
# first on the 4.Levent-bound sequence, last on the Şifa-bound one. Asking about a stop the
# line does not call at is a different test (the tool refuses it, deliberately).
LINE = "500T"
STOP_CODE = "401351"
# A Kadıköy pier platform. 500T never calls there; 8A and 14ŞB, also in the fixture, do.
PIER_STOP_CODE = "406031"
# The recorded 500T positions are stamped 09:08:48-09:08:59 İstanbul time on 2026-09-08
# (tests/fixtures/iett_hat_500T.json); "now" is a minute later, inside the 600 s freshness cap.
FIXTURE_CAPTURED_AT = dt.datetime(2026, 9, 8, 6, 10, tzinfo=dt.UTC)


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


def test_every_response_carries_the_security_headers(client: TestClient) -> None:
    """The page, its script and an API answer all carry the same policy."""
    for path in ("/", "/app.js", "/api/places?q=Taksim"):
        headers = client.get(path).headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["referrer-policy"] == "no-referrer"
        policy = headers["content-security-policy"]
        assert "script-src 'self' https://cdnjs.cloudflare.com" in policy
        assert "'unsafe-inline'" not in policy.split("script-src", 1)[1].split(";", 1)[0]
        assert "frame-ancestors 'none'" in policy


def test_the_page_has_no_inline_script_the_policy_would_block() -> None:
    """script-src has no 'unsafe-inline', so an inline handler or script would silently not run."""
    import re

    page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"\son[a-z]+\s*=", page), "inline event handler in index.html"
    assert all("src=" in tag for tag in re.findall(r"<script\b[^>]*>", page)), "inline <script> in index.html"


def test_cross_origin_is_closed_by_default(client: TestClient) -> None:
    """No allow-origin header for a stranger: the SPA is served from this very origin."""
    response = client.get("/healthz", headers={"Origin": "https://evil.example"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in {k.lower() for k in response.headers}


# --------------------------------------------------------------------------------------
# the tool endpoints
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


def test_parking_typical_occupancy_admits_it_has_no_history(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # Pointed at a profile that does not exist, as on a fresh deployment. Reading the
    # committed data/reference/occupancy_profile.json instead would make this test flip the
    # day scripts/build_profiles.py is re-run on enough history to fill park 758's cells.
    monkeypatch.setenv("NABIZ_OCCUPANCY_PROFILE", str(tmp_path / "absent.json"))
    body = envelope_of(client.get("/api/parking/typical", params={"park_id": 758}))
    # No history has been collected for this profile, so the honest answer is "not yet".
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
    assert body["data"]["count"] == 5
    assert {"stop_code", "name"} <= set(body["data"]["stops"][0])
    # The same top five the full export gives (checked when the fixture was cut): exact
    # name matches first, and the "Kadıköy" typed with dotless ı still finds "KADIKÖY".
    assert [stop["stop_code"] for stop in body["data"]["stops"]] == ["202951", "401031", "402031", "403031", "404031"]
    assert all(stop["name"] == "KADIKÖY" for stop in body["data"]["stops"])


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


def test_an_unknown_line_is_refused_before_it_spends_a_request(
    client: TestClient, nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each line-position read spends one of İETT's 100 requests an hour. A code İETT's own
    route list does not know must be refused before that read, not after it."""
    source = nabiz._source("iett")
    real = source.line_positions
    asked: list[str] = []

    async def spy(line_code: str, *args: Any, **kwargs: Any) -> Any:
        asked.append(line_code)
        return await real(line_code, *args, **kwargs)

    monkeypatch.setattr(source, "line_positions", spy)
    response = client.get("/api/buses", params={"line": "999X"})
    assert response.status_code == 400
    assert "GTFS hat listesinde yok" in response.json()["message"]
    assert asked == []
    envelope_of(client.get("/api/buses", params={"line": LINE}))
    assert asked == [LINE]


def test_arrivals_for_an_unknown_line_are_refused_before_any_iett_read(
    client: TestClient, nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The most expensive tool: without the check an invented code cost three İETT reads
    (positions, the schedule because no bus came back, the fleet) and answered "no bus
    approaching" for a line that does not exist."""
    source = nabiz._source("iett")
    asked: list[str] = []
    for name in ("line_positions", "schedule", "fleet_positions"):
        real = getattr(source, name)

        async def spy(*args: Any, _name: str = name, _real: Any = real, **kwargs: Any) -> Any:
            asked.append(_name)
            return await _real(*args, **kwargs)

        monkeypatch.setattr(source, name, spy)
    response = client.get("/api/arrivals", params={"line": "999X", "stop": STOP_CODE})
    assert response.status_code == 400
    assert "GTFS hat listesinde yok" in response.json()["message"]
    assert asked == []
    envelope_of(client.get("/api/arrivals", params={"line": LINE, "stop": STOP_CODE}))
    assert "line_positions" in asked


def test_arrivals_are_labelled_as_estimates(client: TestClient) -> None:
    body = envelope_of(client.get("/api/arrivals", params={"line": LINE, "stop": STOP_CODE}))
    data = body["data"]
    assert data["stop"]["stop_code"] == STOP_CODE
    assert "tahmin" in data["disclaimer"].lower()
    for arrival in data["arrivals"]:
        assert arrival["method"] in {"stop_sequence", "distance", "schedule"}
        assert arrival["confidence"] in {"high", "medium", "low"}


def test_arrivals_follow_the_gtfs_stop_sequence(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The fixture's trips and stop_times must reach the ETA engine as stop sequences.

    Without a frozen clock every recorded position is days old and is dropped as stale,
    so the loop in the test above never runs. Pinning "now" to just after the capture is
    what lets this assert that the high-confidence method was actually used.
    """
    import ibb_mcp.eta

    monkeypatch.setattr(ibb_mcp.eta, "utcnow", lambda: FIXTURE_CAPTURED_AT)
    data = envelope_of(client.get("/api/arrivals", params={"line": LINE, "stop": STOP_CODE}))["data"]
    diagnostics = data["diagnostics"]
    assert sorted(diagnostics["sequence_routes"]) == ["500T_D_D0", "500T_G_D0"]
    assert diagnostics["methods"]["stop_sequence"] > 0
    assert data["arrivals"], "fresh positions on a served stop must produce at least one estimate"
    assert any(arrival["method"] == "stop_sequence" for arrival in data["arrivals"])


def test_arrivals_refuse_a_stop_the_line_does_not_serve(client: TestClient) -> None:
    # 500T runs Şifa Sondurak <-> 4.Levent Metro; none of its stops is named Kadıköy.
    response = client.get("/api/arrivals", params={"line": LINE, "stop": "Kadıköy"})
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "bad_request"
    assert body["message"].startswith("500T hattı 'KADIKÖY' durağına uğramıyor.")


def test_arrivals_refusal_names_the_lines_that_do_serve_the_stop(client: TestClient) -> None:
    # 14ŞB is mojibaked in routes.csv; the hint only reads "14ŞB" if the repair worked.
    response = client.get("/api/arrivals", params={"line": LINE, "stop": PIER_STOP_CODE})
    assert response.status_code == 400
    assert response.json()["message"] == "500T hattı 'KADIKÖY' durağına uğramıyor. Bu durağa uğrayan hatlar: 14ŞB, 8A."


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


def test_gtfs_comes_from_the_committed_fixture_and_never_writes_to_it(client: TestClient, nabiz: Nabiz) -> None:
    """The gitignored export must not be read, and the committed fixture must not be written.

    Reading ``data/reference/gtfs`` is what kept CI red: it exists on a laptop and nowhere
    else. Writing to ``tests/fixtures/gtfs_mini`` would leave a stray sequence cache in the
    repository after every run, because ``load_stop_sequences`` caches beside the tables.
    """
    gtfs_dir = nabiz.settings.gtfs_dir.resolve()
    assert (REPO_ROOT / "data" / "reference") not in gtfs_dir.parents
    assert not gtfs_dir.is_relative_to(GTFS_MINI_DIR.resolve()), "tests must use a copy of the fixture"
    assert client.get("/api/arrivals", params={"line": LINE, "stop": STOP_CODE}).status_code == 200
    assert (gtfs_dir / "route_sequences.json.gz").is_file(), "the arrivals call should have built and cached sequences"
    assert not (GTFS_MINI_DIR / "route_sequences.json.gz").exists()


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
