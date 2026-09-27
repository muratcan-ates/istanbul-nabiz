from __future__ import annotations

import datetime as dt
import json
import pathlib
from types import SimpleNamespace

import pytest
from conftest import offline_settings
from fastapi.testclient import TestClient
from nexus_helpers import Clock, build_engine

from nabiz.agent import llm
from nabiz.console.access import OperatorAccess
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.citizen_requests import ledger_reply, ledger_request
from nabiz.console.nexus_port import NexusConsole
from nabiz.console.outcomes import SnapshotStore
from nabiz.console.outcomes_api import outcome_board_routes
from nabiz.console.ports import Ports


def put_static_last(app) -> None:
    mount = next(route for route in app.router.routes if getattr(route, "name", None) == "static")
    app.router.routes.remove(mount)
    app.router.routes.append(mount)


@pytest.fixture
def outcome_api(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    clock = Clock(dt.datetime(2026, 9, 27, 12, tzinfo=dt.UTC))
    monkeypatch.setenv("NABIZ_REPORT_TIMELINE_DB_PATH", str(tmp_path / "timeline-not-created.db"))
    engine = build_engine(tmp_path / "core", clock)
    console = NexusConsole(engine, nabiz=None, recorded=lambda: None, offline=True, clock=clock)
    app = build_console_app(
        settings=offline_settings(), llm_config=llm.LlmConfig(), ports=Ports(console=console),
        guard=SpendGuard(BudgetConfig(state_path=None)), access=OperatorAccess(token="t", bound_host="0.0.0.0"),
    )
    app.include_router(outcome_board_routes)
    put_static_last(app)
    app.state.outcome_snapshots = SnapshotStore(tmp_path / "outcomes.db", clock=clock)
    app.state.request_desk = SimpleNamespace(ledger=engine.ledger)
    with TestClient(app, base_url="http://127.0.0.1:8090") as client:
        yield client, app, engine, clock, tmp_path


def test_get_board_returns_five_groups_no_store_and_rejects_other_windows(outcome_api) -> None:
    client, _, _, _, _ = outcome_api
    response = client.get("/api/console/outcomes", headers={"X-Nabiz-Operator": "t"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert [group["key"] for group in response.json()["board"]["groups"]] == ["O1", "O2", "O3", "O4", "O5"]
    assert response.json()["board"]["window_days"] == 30
    assert client.get("/api/console/outcomes?days=14", headers={"X-Nabiz-Operator": "t"}).status_code == 400


def test_board_without_engine_marks_core_metrics_unmeasured(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nabiz.console.app import build_console_app
    from nabiz.console.ports import Ports

    clock = Clock()
    monkeypatch.setenv("NABIZ_REPORT_TIMELINE_DB_PATH", str(tmp_path / "not-created.db"))
    app = build_console_app(settings=offline_settings(), llm_config=llm.LlmConfig(), ports=Ports(),
                            access=OperatorAccess(token="t", bound_host="0.0.0.0"))
    app.include_router(outcome_board_routes)
    put_static_last(app)
    app.state.outcome_snapshots = SnapshotStore(tmp_path / "outcomes.db", clock=clock)
    with TestClient(app, base_url="http://127.0.0.1:8090") as client:
        response = client.get("/api/console/outcomes", headers={"X-Nabiz-Operator": "t"})
    groups = {group["key"]: group for group in response.json()["board"]["groups"]}
    assert response.status_code == 200
    assert all(metric["status"] == "unmeasured" for key in ("O1", "O2") for metric in groups[key]["metrics"])
    assert all(metric["status"] == "measured" for metric in groups["O5"]["metrics"])


def test_missing_timeline_stays_missing_and_is_not_created(outcome_api) -> None:
    client, _, _, _, tmp_path = outcome_api
    response = client.get("/api/console/outcomes", headers={"X-Nabiz-Operator": "t"})
    groups = {group["key"]: group for group in response.json()["board"]["groups"]}
    assert response.status_code == 200
    assert all(metric["status"] == "unmeasured" for key in ("O3", "O4") for metric in groups[key]["metrics"])
    assert all(metric["reason"] == "Bildirim zaman çizgisi bu sürümde yok."
               for key in ("O3", "O4") for metric in groups[key]["metrics"])
    assert not (tmp_path / "timeline-not-created.db").exists()


def test_snapshot_is_recomputed_and_enforces_five_minute_cooldown(outcome_api) -> None:
    client, _, _, clock, _ = outcome_api
    headers = {"X-Nabiz-Operator": "t"}
    first = client.post("/api/console/outcomes/snapshot", json={"days": 30}, headers=headers)
    second = client.post("/api/console/outcomes/snapshot", json={"days": 30}, headers=headers)
    assert first.status_code == 200 and first.headers["cache-control"] == "no-store"
    assert first.json()["saved"]["window_days"] == 30
    assert second.status_code == 429 and second.json()["error"] == "too_soon"
    clock.advance(minutes=5)
    after = client.post("/api/console/outcomes/snapshot", json={"days": 30}, headers=headers)
    current = client.get("/api/console/outcomes", headers=headers)
    assert after.status_code == 200
    assert current.json()["previous"]["taken_at"] == after.json()["saved"]["taken_at"]


def test_snapshot_rejects_client_measurements(outcome_api) -> None:
    client, _, _, _, _ = outcome_api
    response = client.post("/api/console/outcomes/snapshot", json={"days": 30, "numerator": 99},
                           headers={"X-Nabiz-Operator": "t"})
    assert response.status_code == 422 and response.headers["cache-control"] == "no-store"


def test_operator_gate_requires_the_configured_header(outcome_api) -> None:
    client, _, _, _, _ = outcome_api
    assert client.get("/api/console/outcomes").status_code == 401
    assert client.get("/api/console/outcomes", headers={"X-Nabiz-Operator": "t"}).status_code == 200


def test_response_and_logs_contain_no_request_or_operator_details(outcome_api, caplog: pytest.LogCaptureFixture) -> None:
    client, _, engine, clock, _ = outcome_api
    row = {"code": "PRIVATE-CODE", "signal_id": "private-signal", "original_masked": "PRIVATE QUESTION",
           "masked_count": 0, "lang": "tr", "category": "test", "translation_status": "not_needed"}
    ledger_request(engine.ledger, row)
    ledger_reply(engine.ledger, row, {"lang": "tr", "translation": "not_needed", "text_tr": "PRIVATE REPLY"},
                 "PRIVATE OPERATOR")
    response = client.get("/api/console/outcomes", headers={"X-Nabiz-Operator": "t"})
    serialized = json.dumps(response.json(), ensure_ascii=False)
    for value in ("PRIVATE-CODE", "private-signal", "PRIVATE QUESTION", "PRIVATE REPLY", "PRIVATE OPERATOR"):
        assert value not in serialized
        assert value not in caplog.text
    assert response.status_code == 200 and response.json()["board"]["generated_at"] == clock.now.isoformat()
