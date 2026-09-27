"""P00 D2a (P06): the server calendar is mounted for accounts only, and Outlook stays closed."""

from __future__ import annotations

import pathlib

import pytest
from conftest import offline_settings
from fastapi.testclient import TestClient

from nabiz.agent import llm
from nabiz.console.access import OperatorAccess
from nabiz.console.accounts import AccountStore
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.email_sender import OutboxEmailSender

PLAN = {
    "title": "Sergi", "starts_at": "2026-10-03", "ends_at": "2026-10-04", "all_day": True,
    "time_zone": "Europe/Istanbul", "place": None, "source_url": None, "source_date": None,
    "conversation_id": None, "operation_id": "op-1", "consent": True,
}


@pytest.fixture
def client(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "nexus.db"))
    app = build_console_app(
        settings=offline_settings(), llm_config=llm.LlmConfig(), guard=SpendGuard(BudgetConfig(state_path=None)),
        access=OperatorAccess(token="test-operator-token", bound_host="0.0.0.0"),
    )
    app.state.accounts = AccountStore(tmp_path / "accounts.sqlite")
    app.state.outbox = OutboxEmailSender(tmp_path / "outbox")
    return TestClient(app, base_url="http://127.0.0.1:8090")


def test_a_visitor_gets_no_server_calendar(client: TestClient) -> None:
    assert client.post("/api/plans", json=PLAN).status_code == 503
    assert client.get("/api/plans").status_code == 503


def test_an_account_saves_a_plan_and_outlook_stays_closed(client: TestClient) -> None:
    signed = client.post("/api/account/signin", json={"provider": "ibb", "email": "ornek@example.org", "consent": True})
    headers = {"X-Nabiz-Account": signed.json()["token"]}
    saved = client.post("/api/plans", json=PLAN, headers=headers).json()
    assert saved["result"] == "saved_nabiz"
    listed = client.get("/api/plans", headers=headers).json()
    assert [plan["title"] for plan in listed["plans"]] == ["Sergi"]
    outlook = client.post(f"/api/plans/{saved['plan']['id']}/outlook", json={"operation_id": "op-2", "consent": True},
                          headers=headers).json()
    assert outlook["result"] == "outlook_failed" and outlook["message"] == "Outlook bağlantısı kapalı"
    assert client.get("/api/plans").status_code == 503
