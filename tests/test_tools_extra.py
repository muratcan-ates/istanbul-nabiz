"""The three derived tools — travel-mode comparison, line reliability, typical occupancy — at
every layer a client can reach them: the ``Nabiz`` façade, the MCP server and the web app.

Each test runs with ``data/lake`` and ``data/reference/gtfs`` *sealed*: any attempt to open,
stat or list a path inside them raises ``FileNotFoundError``, exactly as on a fresh clone or
in CI where neither directory exists. Both are gitignored, so a test that quietly leaned on
either would pass on the laptop that collected the data and fail everywhere else. The
derived tables the tools read are written per test into ``tmp_path`` and pointed at through
their ``NABIZ_*`` overrides, so no answer below depends on what the collector happened to
have gathered when the committed tables were last rebuilt.
"""

from __future__ import annotations

import builtins
import datetime as dt
import errno
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from conftest import FIXTURES_DIR, REPO_ROOT, refuse_network
from test_routing import CORRIDOR_SEQUENCES, KARTAL, LEVENT4, CorridorIndex

from ibb_mcp.cache import TTLCache
from ibb_mcp.config import Settings
from ibb_mcp.http import PoliteClient
from ibb_mcp.occupancy import OccupancyCell, OccupancyProfile, save_profile
from ibb_mcp.reliability import LineHourStats, ReliabilityTable, save_table
from ibb_mcp.routing import DISCLAIMER_TR
from ibb_mcp.server import build_server
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz

#: The two gitignored directories no test may depend on.
SEALED_DIRS = (REPO_ROOT / "data" / "lake", REPO_ROOT / "data" / "reference" / "gtfs")

NEW_TOOLS = {"plan_journey", "line_reliability", "check_alerts"}


# --------------------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------------------
@pytest.fixture
def sealed(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> Iterator[list[str]]:
    """Make ``data/lake`` and ``data/reference/gtfs`` unavailable without touching them.

    ``open``, ``os.stat``, ``os.scandir`` and ``os.listdir`` are wrapped so a path inside
    either directory behaves as missing; everything else passes through. ``Path.exists``,
    ``Path.open``, ``gzip.open`` and ``json`` loading all bottom out in these calls. The
    yielded list records every attempt, so a test can also assert nothing even looked.
    The environment overrides point the same two locations at empty temporary paths.
    """
    forbidden = tuple(str(path) for path in SEALED_DIRS)
    attempts: list[str] = []

    def is_sealed(target: Any) -> bool:
        try:
            text = os.fsdecode(os.fspath(target))
        except TypeError:  # a file descriptor, not a path
            return False
        full = os.path.abspath(text)
        return any(full == root or full.startswith(root + os.sep) for root in forbidden)

    def guard(real: Any) -> Any:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            target = args[0] if args else kwargs.get("path", kwargs.get("file", "."))
            if is_sealed(target):
                attempts.append(os.fsdecode(os.fspath(target)))
                raise FileNotFoundError(errno.ENOENT, "sealed by the test suite", os.fsdecode(os.fspath(target)))
            return real(*args, **kwargs)

        return wrapper

    guarded_open = guard(builtins.open)
    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(io, "open", guarded_open)
    monkeypatch.setattr(os, "stat", guard(os.stat))
    monkeypatch.setattr(os, "scandir", guard(os.scandir))
    monkeypatch.setattr(os, "listdir", guard(os.listdir))
    monkeypatch.setenv("NABIZ_LAKE_DIR", str(tmp_path / "no-lake"))
    monkeypatch.setenv("NABIZ_GTFS_DIR", str(tmp_path / "no-gtfs"))
    # Derived tables: absent unless a test writes one. Never the committed copies.
    monkeypatch.setenv("NABIZ_RELIABILITY_TABLE", str(tmp_path / "line_reliability.json"))
    monkeypatch.setenv("NABIZ_OCCUPANCY_PROFILE", str(tmp_path / "occupancy_profile.json"))
    monkeypatch.setenv("NABIZ_ETA_PROFILE", str(tmp_path / "eta_profile.json"))
    yield attempts


def sealed_nabiz(tmp_path: pathlib.Path) -> Nabiz:
    """A façade over recorded fixtures whose HTTP transport refuses the network."""
    settings = Settings(offline=True, fixtures_dir=FIXTURES_DIR, gtfs_dir=tmp_path / "no-gtfs")
    return Nabiz(
        SourceContext.create(
            client=PoliteClient(transport=httpx.MockTransport(refuse_network)),
            cache=TTLCache(),
            settings=settings,
        )
    )


@pytest.fixture
def nabiz(sealed: list[str], tmp_path: pathlib.Path) -> Nabiz:
    return sealed_nabiz(tmp_path)


def test_the_seal_really_hides_both_directories(sealed: list[str]) -> None:
    """Guard rail for everything below: if the seal leaks, every other test proves nothing."""
    for directory in SEALED_DIRS:
        assert not directory.exists()
        assert not os.path.isdir(directory)
        with pytest.raises(FileNotFoundError):
            open(directory / "anything.csv")  # noqa: SIM115 - the call itself is the assertion
    assert len(sealed) >= len(SEALED_DIRS)


# --------------------------------------------------------------------------------------
# small derived tables, written per test
# --------------------------------------------------------------------------------------
OBSERVED_FROM = dt.datetime(2026, 9, 8, 17, 30, tzinfo=dt.UTC)
OBSERVED_TO = dt.datetime(2026, 9, 13, 15, 23, tzinfo=dt.UTC)


def write_reliability_table(tmp_path: pathlib.Path) -> ReliabilityTable:
    """One reportable cell (500T at 08) and one the module refused (500T at 09)."""
    table = ReliabilityTable(
        cells=[
            LineHourStats(
                line_code="500T",
                hour=8,
                available=True,
                samples=40,
                vehicles_seen=12,
                stops_measured=20,
                stops_with_cv=9,
                days=2,
                median_headway_min=9.6,
                headway_cv=0.42,
                bunching_score=0.42,
                bunching_label="biraz düzensiz",
                stop_capture_rate=0.5,
                cv_sampling_floor=0.707,
                cv_exceeds_floor=False,
            ),
            LineHourStats(
                line_code="500T",
                hour=9,
                available=False,
                samples=3,
                vehicles_seen=2,
                reason="Yeterli gözlem yok: 3 sefer aralığı ölçülebildi, en az 12 gerekiyor.",
            ),
        ],
        observed_from=OBSERVED_FROM,
        observed_to=OBSERVED_TO,
        days_covered=["2026-09-08", "2026-09-13"],
        snapshots_read=100,
        generated_at=OBSERVED_TO + dt.timedelta(minutes=5),
    )
    save_table(table, tmp_path / "line_reliability.json")
    return table


def write_occupancy_profile(tmp_path: pathlib.Path) -> OccupancyProfile:
    """Park 758 on weekday mornings at 09: nine samples over three days, so it is reportable."""
    first = dt.datetime(2026, 9, 14, 6, 0, tzinfo=dt.UTC)
    last = dt.datetime(2026, 9, 16, 6, 50, tzinfo=dt.UTC)
    cell = OccupancyCell(758, "weekday", 9, 9, 62.0, 55.0, 70.0, first, last, 3)
    profile = OccupancyProfile(
        cells={(758, "weekday", 9): cell},
        built_at_utc=last + dt.timedelta(minutes=10),
        rows_read=9,
        first_sample_utc=first,
        last_sample_utc=last,
    )
    save_profile(profile, tmp_path / "occupancy_profile.json")
    return profile


# --------------------------------------------------------------------------------------
# plan_journey — the façade
# --------------------------------------------------------------------------------------
async def test_journey_without_gtfs_withdraws_only_the_bus_and_says_why(nabiz: Nabiz, sealed: list[str]) -> None:
    result = await nabiz.plan_journey(origin="Taksim", destination="Kadıköy")
    data = result.data

    costed = {option["mode"] for option in data["options"]}
    withdrawn = {option["mode"]: option["reason"] for option in data["unavailable_options"]}
    assert costed == {"drive", "metro"}
    assert set(withdrawn) == {"bus", "walk"}
    assert "GTFS" in withdrawn["bus"]
    assert "Boğaz" in withdrawn["walk"]
    # Every withdrawn option reaches the note with its reason, not just its name.
    assert withdrawn["bus"] in result.note and withdrawn["walk"] in result.note
    assert all(option["total_minutes"] > 0 for option in data["options"])
    assert data["disclaimer"] == DISCLAIMER_TR
    assert data["kind"] == "estimate"
    json.dumps(data)  # crosses a JSON boundary in both the MCP and the web layer
    assert sealed == [], f"journey planning reached into a sealed directory: {sealed}"


async def test_journey_provenance_is_the_oldest_live_input_not_the_request(nabiz: Nabiz) -> None:
    result = await nabiz.plan_journey(origin="Taksim", destination="Kadıköy")
    inputs = result.data["provenance"]

    assert result.provenance.source == "nabiz_routing"
    assert inputs, "every live reading keeps its own stamp in data.provenance"
    # The 28-day traffic history behind "usually at this hour" is cited too, but it is not a
    # live input: it never moves the minutes, so it does not age the envelope.
    history = [item for item in inputs if item["source_url"].endswith("/28/H")]
    live = [item for item in inputs if item not in history]
    assert len(history) == 1
    oldest = min(dt.datetime.fromisoformat(item["observed_at"]) for item in live)
    assert result.provenance.observed_at == oldest


async def test_journey_takes_coordinates_and_rides_the_corridor_when_gtfs_exists(nabiz: Nabiz) -> None:
    # The corridor stub stands in for the GTFS index; the façade builds its stop->route
    # index from whatever sequences it holds, once.
    nabiz._gtfs = CorridorIndex()
    nabiz._sequences = CORRIDOR_SEQUENCES

    result = await nabiz.plan_journey(
        origin_lat=KARTAL.lat,
        origin_lon=KARTAL.lon,
        destination_lat=LEVENT4.lat,
        destination_lon=LEVENT4.lon,
    )
    bus = next(option for option in result.data["options"] if option["mode"] == "bus")

    assert bus["detail"]["line_code"] == "500T"
    assert nabiz._stop_routes is not None and "225761" in nabiz._stop_routes
    # No eta_profile.json in this sealed run: the rate must say it is the untuned default.
    rate = next(a for a in bus["assumptions"] if a["key"] == "bus_seconds_per_stop")
    assert rate["value"] == 120.0 and "ölçüm yok" in rate["detail"]
    assert result.data["origin"]["name"] == f"{KARTAL.lat:.4f}, {KARTAL.lon:.4f}"


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"origin": "Taksim"}, "destination için bir yer adı"),
        ({"origin": "Taksim", "destination_lat": 41.0}, "birlikte verilmeli"),
        ({"origin": "Taksim", "destination_lat": 52.52, "destination_lon": 13.40}, "İstanbul sınırları dışında"),
        ({"origin": "Zzzyx", "destination": "Kadıköy"}, "bir yer bulamadım"),
    ],
)
async def test_journey_refuses_an_incomplete_or_foreign_end(nabiz: Nabiz, kwargs: dict, fragment: str) -> None:
    with pytest.raises(ValueError, match=fragment) as caught:
        await nabiz.plan_journey(**kwargs)
    assert "52.52" not in str(caught.value), "a refused coordinate must not be echoed back"


async def test_a_missing_traffic_index_withdraws_the_drive_instead_of_assuming_free_flow(
    nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A null TrafficIndex parses to 0 (see the xfail in test_models.py); 0 is not on İBB's 1–99 scale."""
    from ibb_mcp.models import TrafficIndexPoint, utcnow
    from ibb_mcp.sources.base import make_provenance

    async def missing(self: Any) -> Any:
        return TrafficIndexPoint(index=0, at=utcnow()), make_provenance("traffic")

    monkeypatch.setattr("ibb_mcp.sources.traffic.TrafficSource.current", missing)

    journey = await nabiz.plan_journey(origin="Taksim", destination="Kadıköy")
    withdrawn = {option["mode"]: option["reason"] for option in journey.data["unavailable_options"]}
    assert "drive" in withdrawn and "1–99" in withdrawn["drive"]
    assert not any(reading["key"] == "traffic_index" for reading in journey.data["readings"])

    now = await nabiz.traffic_index("now")
    assert now.data["index"] is None and now.data["description"] is None  # never "akıcı"
    assert "geçerli bir trafik indeksi" in now.note


# --------------------------------------------------------------------------------------
# line_reliability — the façade
# --------------------------------------------------------------------------------------
async def test_a_reportable_cell_comes_back_with_its_window_and_its_caveat(nabiz: Nabiz, tmp_path: pathlib.Path) -> None:
    write_reliability_table(tmp_path)
    result = await nabiz.line_reliability("500t", hour=8)

    assert result.data["available"] is True
    assert result.data["line_code"] == "500T"
    assert result.data["median_headway_min"] == 9.6
    assert result.data["observation_window"]["days_covered"] == ["2026-09-08", "2026-09-13"]
    assert result.data["kind"] == "measured_history"
    assert "üst sınır" in result.note  # missed passages inflate both numbers; the note says so
    # The age an agent quotes is the age of the measurement, not of the request.
    assert result.provenance.reported_at == OBSERVED_TO
    assert result.provenance.source == "nabiz_reliability"


async def test_a_cell_the_module_refused_is_reported_unavailable(nabiz: Nabiz, tmp_path: pathlib.Path) -> None:
    """The bug this replaces reported ``available: true`` whenever a cell merely *existed*."""
    write_reliability_table(tmp_path)
    result = await nabiz.line_reliability("500T", hour=9)

    assert result.data["available"] is False
    assert result.data["median_headway_min"] is None
    assert result.note.startswith("Yeterli gözlem yok")


async def test_an_unwatched_line_and_a_missing_table_both_answer_with_a_reason(nabiz: Nabiz, tmp_path: pathlib.Path) -> None:
    missing = await nabiz.line_reliability("500T", hour=8)
    assert missing.data["available"] is False
    assert "scripts/reliability_report.py" in missing.note  # the real script, not a make target that does not exist

    write_reliability_table(tmp_path)
    unwatched = await nabiz.line_reliability("34BZ", hour=8)
    assert unwatched.data["available"] is False
    assert unwatched.data["observed_lines"] == ["500T"]
    assert "500T" in unwatched.note


async def test_reliability_cites_its_file_without_a_home_path(nabiz: Nabiz, tmp_path: pathlib.Path) -> None:
    write_reliability_table(tmp_path)
    result = await nabiz.line_reliability("500T", hour=8)

    url = result.provenance.source_url
    assert url == "local:line_reliability.json", url  # outside the repo: the file name only
    assert str(pathlib.Path.home()) not in url and str(tmp_path) not in url


@pytest.mark.parametrize("hour", [-1, 24])
async def test_reliability_refuses_an_hour_that_does_not_exist(nabiz: Nabiz, hour: int) -> None:
    with pytest.raises(ValueError, match="0 ile 23"):
        await nabiz.line_reliability("500T", hour=hour)


# --------------------------------------------------------------------------------------
# ispark_typical_occupancy — the façade, rewired onto ibb_mcp.occupancy
# --------------------------------------------------------------------------------------
async def test_occupancy_reports_a_reportable_cell_with_the_profiles_age(nabiz: Nabiz, tmp_path: pathlib.Path) -> None:
    profile = write_occupancy_profile(tmp_path)
    result = await nabiz.ispark_typical_occupancy(758, weekday=2, hour=9)

    assert result.data["available"] is True
    assert result.data["median_occupancy_pct"] == 62.0
    assert result.data["weekday_class"] == "weekday"
    assert result.provenance.reported_at == profile.last_sample_utc
    assert result.provenance.source_url == "local:occupancy_profile.json"


async def test_occupancy_without_a_profile_says_so_instead_of_guessing(nabiz: Nabiz) -> None:
    result = await nabiz.ispark_typical_occupancy(758, weekday=2, hour=9)

    assert result.data["available"] is False
    assert result.data["reason"] == "no_profile"
    assert "build_profiles.py" in result.note
    assert result.provenance.reported_at is None


@pytest.mark.parametrize(("weekday", "hour", "fragment"), [(7, 9, "Pazartesi"), (-1, 9, "Pazartesi"), (2, 24, "0 ile 23")])
async def test_occupancy_refuses_a_slot_that_does_not_exist(nabiz: Nabiz, weekday: int, hour: int, fragment: str) -> None:
    # weekday=7 used to wrap silently to Monday: a plausible answer to a question nobody asked.
    with pytest.raises(ValueError, match=fragment):
        await nabiz.ispark_typical_occupancy(758, weekday=weekday, hour=hour)


# --------------------------------------------------------------------------------------
# the MCP layer
# --------------------------------------------------------------------------------------
EXPECTED_PARAMETERS = {
    "plan_journey": {"origin", "destination", "origin_lat", "origin_lon", "destination_lat", "destination_lon"},
    "line_reliability": {"line_code", "hour"},
    "check_alerts": {"subscription"},
}


async def test_the_server_advertises_the_new_tools_with_real_signatures(nabiz: Nabiz) -> None:
    tools = {tool.name: tool for tool in await build_server(app=nabiz).list_tools()}

    assert set(tools) >= NEW_TOOLS
    assert len(tools) == 15
    for name, parameters in EXPECTED_PARAMETERS.items():
        schema = tools[name].input_schema
        assert set(schema["properties"]) == parameters, f"{name} lost its signature (functools.wraps)"
        assert tools[name].description and len(tools[name].description) > 200, f"{name} needs a real description"
    assert tools["line_reliability"].input_schema["required"] == ["line_code"]
    assert tools["line_reliability"].input_schema["properties"]["hour"]["anyOf"][0]["type"] == "integer"
    assert "navigasyon" in tools["plan_journey"].description.lower() or "yol tarifi" in tools["plan_journey"].description


async def call(server: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = await server.call_tool(name, arguments)
    assert result.content, f"{name} returned no content"
    return json.loads(result.content[0].text)


async def test_plan_journey_renders_through_the_server(nabiz: Nabiz, sealed: list[str]) -> None:
    payload = await call(build_server(app=nabiz), "plan_journey", {"origin": "Taksim", "destination": "Kadıköy"})

    assert {option["mode"] for option in payload["data"]["options"]} == {"drive", "metro"}
    assert payload["provenance"]["source"] == "nabiz_routing"
    assert payload["provenance"]["age"]
    assert "GTFS" in payload["note"]
    assert sealed == []


async def test_line_reliability_renders_through_the_server(nabiz: Nabiz, tmp_path: pathlib.Path) -> None:
    write_reliability_table(tmp_path)
    server = build_server(app=nabiz)

    measured = await call(server, "line_reliability", {"line_code": "500T", "hour": 8})
    assert measured["data"]["available"] is True
    assert measured["provenance"]["reported_at"] == OBSERVED_TO.isoformat()

    refused = await call(server, "line_reliability", {"line_code": "500T", "hour": 25})
    assert refused["error"] == "bad_request"


async def test_typical_occupancy_renders_through_the_server(nabiz: Nabiz, tmp_path: pathlib.Path) -> None:
    write_occupancy_profile(tmp_path)
    payload = await call(build_server(app=nabiz), "ispark_typical_occupancy", {"park_id": 758, "weekday": 2, "hour": 9})

    assert payload["data"]["available"] is True
    assert payload["provenance"]["source_url"] == "local:occupancy_profile.json"


# --------------------------------------------------------------------------------------
# the web layer, and the page that calls it
# --------------------------------------------------------------------------------------
@pytest.fixture
def client(nabiz: Nabiz) -> Iterator[Any]:
    from fastapi.testclient import TestClient

    from nabiz.web.main import create_app

    with TestClient(create_app(nabiz=nabiz)) as test_client:
        yield test_client


def test_route_endpoint_compares_modes_by_place_name(client: Any) -> None:
    response = client.get("/api/route", params={"from": "Taksim", "to": "Kadıköy"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert {option["mode"] for option in body["data"]["options"]} == {"drive", "metro"}
    assert body["provenance"]["source"] == "nabiz_routing"

    unknown = client.get("/api/route", params={"from": "Zzzyx", "to": "Kadıköy"})
    assert unknown.status_code == 400
    assert "bulamadım" in unknown.json()["message"]


def test_reliability_endpoint_answers_for_a_line(client: Any, tmp_path: pathlib.Path) -> None:
    write_reliability_table(tmp_path)
    body = client.get("/api/reliability", params={"line": "500T", "hour": 8}).json()
    assert body["data"]["available"] is True
    assert client.get("/api/reliability", params={"line": "500T", "hour": 24}).status_code == 422


APP_JS = pathlib.Path(__file__).resolve().parents[1] / "src" / "nabiz" / "web" / "static" / "app.js"


def test_every_endpoint_the_page_calls_exists_with_that_method(client: Any) -> None:
    """The page used to probe three endpoints nobody had shipped and hide their panels on 404."""
    source = APP_JS.read_text(encoding="utf-8")
    calls = {("GET", path) for path in re.findall(r"(?:api|probe)\('(/api/[a-z/]+)'", source)}
    calls |= {("POST", path) for path in re.findall(r"apiPost\('(/api/[a-z/]+)'", source)}
    routes = {(method, route.path) for route in client.app.routes for method in getattr(route, "methods", None) or ()}

    assert ("POST", "/api/alerts/check") in calls and ("GET", "/api/route") in calls
    missing = sorted(call for call in calls if call not in routes)
    assert not missing, f"app.js calls endpoints the server does not have: {missing}"


def test_the_page_reads_origin_and_destination_from_a_turkish_question(tmp_path: pathlib.Path) -> None:
    node = shutil.which("node")
    if node is None:  # pragma: no cover - CI without node still runs the rest of the suite
        pytest.skip("node is not installed")
    questions = [
        "Kadıköy'den Taksim'e nasıl giderim?",
        "Kartal’dan 4.Levent’e nasıl giderim",
        "Beşiktaş Meydanı'ndan Levent'e nasıl gidilir",
        "Taksim'e nasıl giderim",
    ]
    harness = tmp_path / "journey.js"
    harness.write_text(
        "const fs = require('fs');\n"
        "const stub = { setAttribute() {}, addEventListener() {}, innerHTML: '', textContent: '', hidden: false };\n"
        "global.document = { querySelector: () => stub, querySelectorAll: () => [], addEventListener: () => {} };\n"
        "global.window = { location: { origin: 'http://localhost' } };\n"
        f"const src = fs.readFileSync({json.dumps(str(APP_JS))}, 'utf8');\n"
        "const { route } = eval(src + '\\n;({ route });');\n"
        f"console.log(JSON.stringify({json.dumps(questions, ensure_ascii=False)}.map((q) => route(q))));\n",
        encoding="utf-8",
    )
    proc = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    decisions = json.loads(proc.stdout)

    assert [d["journey"] for d in decisions] == ["route"] * 4
    assert (decisions[0]["args"]["from"], decisions[0]["args"]["to"]) == ("Kadıköy", "Taksim")
    assert (decisions[1]["args"]["from"], decisions[1]["args"]["to"]) == ("Kartal", "4.Levent")
    assert (decisions[2]["args"]["from"], decisions[2]["args"]["to"]) == ("Beşiktaş Meydanı", "Levent")
    # One end only: the page asks for both rather than guessing where the user starts.
    assert "from" not in decisions[3]["args"]
