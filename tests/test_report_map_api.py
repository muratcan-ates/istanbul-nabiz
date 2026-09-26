"""E28: operator-only station counts for recent citizen lift reports."""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
from typing import Any

import pytest
from conftest import FIXTURES_DIR, offline_settings
from fastapi.testclient import TestClient
from nexus_helpers import Clock, approve, build_engine
from test_map_layers_api import offline_nabiz, record, write_recordings

from nabiz.agent import llm
from nabiz.console.access import OperatorAccess, TurnLimiter
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.nexus_port import NexusConsole
from nabiz.console.ports import Ports
from nabiz.console.published import PublishedCards
from nabiz.console.report_api import REPORT_KIND, report_routes
from nabiz.console.report_map_api import report_map_routes, report_map_rows

STATIC = pathlib.Path(__file__).parents[1] / "src" / "nabiz" / "console" / "static"


def put_static_last(app: Any) -> None:
    mount = next(route for route in app.router.routes if getattr(route, "name", None) == "static")
    app.router.routes.remove(mount)
    app.router.routes.append(mount)


def build_report_map_client(directory: pathlib.Path, *, recording: bool = True):
    if recording:
        write_recordings(directory, {"Asansör": [record()]}, None)
    else:
        directory.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURES_DIR / "metro_stations.json", directory / "metro_stations.json")
    clock = Clock()
    engine = build_engine(directory, clock)
    nabiz = offline_nabiz(directory)
    console = NexusConsole(
        engine, nabiz=nabiz, recorded=lambda: None, offline=True, ingest_every_s=0, clock=clock
    )
    published = PublishedCards(engine, offline=True, stale_after_s=engine.stale_after_s, clock=clock)
    app = build_console_app(
        nabiz=nabiz,
        settings=offline_settings(),
        llm_config=llm.LlmConfig(),
        ports=Ports(console=console, published=published),
        guard=SpendGuard(BudgetConfig(state_path=None)),
        access=OperatorAccess(),
    )
    app.include_router(report_routes)
    app.include_router(report_map_routes)
    put_static_last(app)
    app.state.report_clock = clock
    app.state.report_limiter = TurnLimiter(60)
    return TestClient(app, base_url="http://127.0.0.1:8090"), engine, clock


@pytest.fixture
def report_map_client(tmp_path: pathlib.Path):
    client, engine, clock = build_report_map_client(tmp_path)
    with client:
        yield client, engine, clock


@pytest.fixture
def unread_report_map_client(tmp_path: pathlib.Path):
    client, engine, clock = build_report_map_client(tmp_path, recording=False)
    with client:
        yield client, engine, clock


def post_report(client: TestClient, station: str, kind: str):
    return client.post("/api/report", json={"station": station, "kind": kind, "bucket": "now"})


def report_rows(client: TestClient, window: str = "30m") -> dict[str, Any]:
    response = client.get("/api/console/report-map", params={"window": window})
    assert response.status_code == 200
    return response.json()


def report_states(engine):
    return {
        signal_id: state
        for signal_id, state in engine.states().items()
        if state.signal.kind == REPORT_KIND
    }


def test_counts_and_conflicts_per_station(report_map_client) -> None:
    client, _, clock = report_map_client
    for _ in range(3):
        assert post_report(client, "Yenikapı", "not_working").status_code == 200
        clock.advance(minutes=1)
    assert post_report(client, "Kartal", "data_wrong").status_code == 200

    body = report_rows(client)

    assert [row["station"] for row in body["stations"]] == ["Yenikapı", "Kartal"]
    yenikapi, kartal = body["stations"]
    assert yenikapi["reports"] == 3
    assert yenikapi["by_kind"] == {"not_working": 3, "data_wrong": 0}
    assert yenikapi["conflict"] is True
    assert yenikapi["record_text"] == "İBB kaydında arıza yok"
    assert kartal["reports"] == 1
    assert kartal["conflict"] is True
    assert kartal["record_text"] == "İBB kaydında arıza var"


def test_the_window_drops_old_reports(report_map_client) -> None:
    client, _, clock = report_map_client
    for _ in range(3):
        post_report(client, "Yenikapı", "not_working")
    post_report(client, "Kartal", "data_wrong")
    clock.advance(minutes=31)

    assert report_rows(client, "30m")["total_reports"] == 0
    assert report_rows(client, "24h")["total_reports"] == 4
    clock.advance(hours=25)
    assert report_rows(client, "24h")["total_reports"] == 0


def test_folded_reports_count_one_by_one(report_map_client) -> None:
    client, _, _ = report_map_client
    for _ in range(3):
        post_report(client, "Yenikapı", "not_working")

    row, = report_rows(client)["stations"]

    assert row["reports"] == 3
    assert row["cards"] == 1


def test_the_answer_carries_no_personal_trace(report_map_client) -> None:
    client, _, _ = report_map_client
    post_report(client, "Yenikapı", "not_working")

    body = report_rows(client)
    features = client.get("/api/map/stations").json()["features"]
    coordinates = {
        feature["properties"]["name"]: feature["geometry"]["coordinates"] for feature in features
    }
    encoded = json.dumps(body, ensure_ascii=False).lower()
    forbidden_keys = {"ip", "client", "device", "transcript", "lift_text", "operator_text"}

    def check_keys(value: Any) -> None:
        if isinstance(value, dict):
            assert not forbidden_keys.intersection(key.lower() for key in value)
            for child in value.values():
                check_keys(child)
        elif isinstance(value, list):
            for child in value:
                check_keys(child)

    check_keys(body)
    assert "testclient" not in encoded
    assert "çalışıyor" not in encoded
    assert "—" not in encoded and "–" not in encoded
    for row in body["stations"]:
        assert [row["lon"], row["lat"]] == coordinates[row["station"]]


def test_a_station_without_a_point_is_listed_unplaced() -> None:
    counts = {
        "haydarpasa": {
            "station": "Haydarpaşa",
            "reports": 2,
            "by_kind": {"not_working": 2, "data_wrong": 0},
            "cards": 1,
            "open_signal_id": "signal-1",
        }
    }

    placed, unplaced = report_map_rows(counts, [])

    assert placed == []
    assert unplaced == [{
        "station": "Haydarpaşa",
        "reports": 2,
        "by_kind": {"not_working": 2, "data_wrong": 0},
        "cards": 1,
        "open_signal_id": "signal-1",
    }]


def test_an_unread_record_never_claims_a_conflict(unread_report_map_client) -> None:
    client, _, _ = unread_report_map_client
    post_report(client, "Yenikapı", "not_working")

    row, = report_rows(client)["stations"]

    assert row["lift_record"] == "unread"
    assert row["conflict"] is False
    assert row["record_text"] == "İBB kaydı okunamadı; karşılaştırılamadı"


def test_a_decided_card_keeps_its_count_but_loses_its_link(report_map_client) -> None:
    client, engine, clock = report_map_client
    post_report(client, "Yenikapı", "not_working")
    first_id, = report_states(engine)
    engine.decide(approve(first_id, action="reject", reason="Saha teyidi yok"))

    decided, = report_rows(client)["stations"]
    assert decided["reports"] == 1
    assert decided["open_signal_id"] is None
    clock.advance(minutes=1)
    post_report(client, "Yenikapı", "not_working")

    reopened, = report_rows(client)["stations"]

    assert reopened["reports"] == 2
    assert reopened["cards"] == 2
    assert reopened["open_signal_id"] != first_id


def test_the_map_is_behind_the_operator_door_and_needs_the_core(tmp_path: pathlib.Path) -> None:
    app = build_console_app(
        settings=offline_settings(),
        llm_config=llm.LlmConfig(),
        ports=Ports(),
        guard=SpendGuard(BudgetConfig(state_path=None)),
        access=OperatorAccess(bound_host="0.0.0.0"),
    )
    app.include_router(report_map_routes)
    put_static_last(app)
    with TestClient(app, base_url="http://127.0.0.1:8090") as client:
        locked = client.get("/api/console/report-map")
        assert locked.status_code == 503 and locked.json()["error"] == "console_locked"

    app = build_console_app(
        settings=offline_settings(),
        llm_config=llm.LlmConfig(),
        ports=Ports(),
        guard=SpendGuard(BudgetConfig(state_path=None)),
        access=OperatorAccess(),
    )
    app.include_router(report_map_routes)
    put_static_last(app)
    with TestClient(app, base_url="http://127.0.0.1:8090") as client:
        unwired = client.get("/api/console/report-map")
        invalid = client.get("/api/console/report-map", params={"window": "7d"})
        assert unwired.status_code == 503 and unwired.json()["error"] == "not_wired"
        assert invalid.status_code == 422 and invalid.json()["error"] == "invalid_request"

    client, engine, _ = build_report_map_client(tmp_path / "wired")
    with client:
        before = len(engine.ledger.entries())
        assert report_rows(client)["total_reports"] == 0
        assert report_rows(client, "24h")["total_reports"] == 0
        assert len(engine.ledger.entries()) == before


def test_row_markup_in_node(tmp_path: pathlib.Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    module = (STATIC / "js" / "console_report_map.js").as_uri()
    harness = tmp_path / "report_map_node.mjs"
    harness.write_text(
        "globalThis.window = {location:{search:'?mock=0',origin:'http://127.0.0.1'}};\n"
        f"const map = await import({json.dumps(module)});\n"
        "const open = map.rowMarkup({station:'<script>',reports:1,by_kind:{not_working:1},"
        "open_signal_id:'sig-1',record_text:'İBB kaydında arıza yok',conflict:true,lat:41,lon:29});\n"
        "const closed = map.rowMarkup({station:'Kartal',reports:1,by_kind:{data_wrong:1},"
        "open_signal_id:null,record_text:'İBB kaydında arıza var',conflict:false,lat:41,lon:29});\n"
        "console.log(JSON.stringify([open,closed,map.dotRadius(1),map.dotRadius(100)]));\n",
        encoding="utf-8",
    )
    result = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    open_row, closed_row, one, hundred = json.loads(result.stdout)
    assert '<button type="button" class="rm-row" data-open="sig-1">' in open_row
    assert "&lt;script&gt;" in open_row and "<script>" not in open_row
    assert '<li class="rm-row is-closed">' in closed_row and "karar verildi" in closed_row
    assert one == 10 and hundred == 24


def test_the_map_files_follow_the_page_rules() -> None:
    script = (STATIC / "js" / "console_report_map.js").read_text(encoding="utf-8")
    css = (STATIC / "css" / "console_report_map.css").read_text(encoding="utf-8")
    assert "'/api/console/report-map'" in script
    assert "L.circleMarker" in script
    assert "'/vendor/leaflet/leaflet.js'" in script
    assert "aria-pressed" in script and 'role="status"' in script
    assert "Vatandaş bildirimi, doğrulanmamış. Simüle operatör." in script
    assert ".queue-item[data-id=" in script
    for forbidden in ("navigator.geolocation", "leaflet.heat", "markercluster", "heatLayer", "fetch("):
        assert forbidden not in script
    assert "min-height: var(--tap)" in css
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(", css)
