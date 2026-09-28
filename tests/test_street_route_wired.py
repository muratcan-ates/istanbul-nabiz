"""P00 D2a (P03): the street route is mounted on the product app, off without its key, and logs no place."""

from __future__ import annotations

import inspect
import logging
import pathlib

import httpx
import pytest
from conftest import offline_settings
from fastapi.testclient import TestClient

from nabiz.agent import llm
from nabiz.console import app as console_app
from nabiz.console.access import OperatorAccess
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard

BODY = {
    "origin": {"name": "A", "lat": 40.9, "lon": 29.19},
    "destination": {"name": "B", "lat": 40.9009, "lon": 29.1911},
    "needs": ["step_free"], "lang": "tr", "consent": True,
}


@pytest.fixture
def client(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "nexus.db"))
    monkeypatch.delenv("NABIZ_AZURE_MAPS_KEY", raising=False)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: (_ for _ in ()).throw(AssertionError("network")))
    app = build_console_app(
        settings=offline_settings(), llm_config=llm.LlmConfig(), guard=SpendGuard(BudgetConfig(state_path=None)),
        access=OperatorAccess(token="test-operator-token", bound_host="0.0.0.0"),
    )
    return TestClient(app, base_url="http://127.0.0.1:8090")


def test_the_street_route_answers_off_without_its_key_and_logs_no_coordinate(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        result = client.post("/api/route/street", json=BODY)
    assert result.status_code == 200
    body = result.json()
    assert body["provider_status"] == "kapalı" and body["geometry"] == [] and body["card"]["data"]["legs"] == []
    lines = [record.getMessage() for record in caplog.records]
    assert any(line.startswith("POST /api/route/street -> 200") for line in lines)
    assert not any("40.9" in line or "29.19" in line for line in lines)


def test_main_quiets_httpx_before_serving() -> None:
    source = inspect.getsource(console_app.main)
    assert source.index('logging.getLogger("httpx").setLevel(logging.WARNING)') < source.index("uvicorn.run(")
    routers = console_app.PRODUCT_ROUTERS
    assert routers.index(console_app.street_route_router) == routers.index(console_app.route_steps_routes) + 1
