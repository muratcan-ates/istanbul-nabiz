"""P00 D2a (P08): restriction and appeals on the product app, keyed by the person, never by the address."""

from __future__ import annotations

import json
import pathlib

import pytest
from conftest import offline_settings
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from nabiz.agent import llm
from nabiz.console.access import OperatorAccess
from nabiz.console.app import _person_key, build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard

TOKEN = "test-operator-token"
ONE, TWO = {"X-Nabiz-Device": "a" * 24}, {"X-Nabiz-Device": "b" * 24}


@pytest.fixture
def app(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "nexus.db"))
    monkeypatch.setenv("NABIZ_CHAT_TURNS_PER_MIN", "1")
    return build_console_app(
        settings=offline_settings(), llm_config=llm.LlmConfig(), guard=SpendGuard(BudgetConfig(state_path=None)),
        access=OperatorAccess(token=TOKEN, bound_host="0.0.0.0"),
    )


def final(response) -> dict:
    assert response.status_code == 200, response.text
    return json.loads(response.text.split("event: final\ndata: ", 1)[1].split("\n", 1)[0])


def test_a_restriction_needs_a_device_or_account_key_never_the_address(app) -> None:
    with TestClient(app, base_url="http://127.0.0.1:8090") as client:
        assert client.get("/api/restriction").status_code == 401
        status = client.get("/api/restriction", headers=ONE)
    assert status.status_code == 200 and status.json() == {"restricted": False, "restriction": None}


def test_the_turn_limiter_counts_each_person_on_a_shared_address(app) -> None:
    with TestClient(app, base_url="http://127.0.0.1:8090") as client:
        assert client.post("/api/chat", json={"message": "Merhaba"}, headers=ONE).status_code == 200
        assert client.post("/api/chat", json={"message": "Merhaba"}, headers=ONE).status_code == 429
        assert client.post("/api/chat", json={"message": "Merhaba"}, headers=TWO).status_code == 200


def test_a_restricted_person_gets_the_rules_and_153_and_can_appeal(app) -> None:
    with TestClient(app, base_url="http://127.0.0.1:8090") as client:
        client.get("/api/quota", headers=ONE)
        subject = app.state.quota.holder(device="a" * 24, host="testclient").key
        app.state.appeal_book.restrictions.restrict(subject, reason="reviewed_abuse", hours=24, human=True)
        assert client.get("/api/restriction", headers=ONE).json()["restricted"] is True
        turn = final(client.post("/api/chat", json={"message": "Metro çalışıyor mu?"}, headers=ONE))
        assert turn["quota"]["model_open_this_turn"] is False
        appeal = client.post("/api/appeals", headers=ONE,
                             json={"category": "shared_device", "consent": True, "operation_id": "op-0123456789abcdef"})
        assert appeal.status_code == 202
        queue = client.get("/api/console/appeals", headers={"x-nabiz-operator": TOKEN}).json()
    assert [item["id"] for item in queue["appeals"]] == [appeal.json()["id"]]


def test_the_person_key_is_the_quota_pseudonym(app) -> None:
    class Request:
        client = type("Client", (), {"host": "192.0.2.1"})()

        def __init__(self, headers: dict[str, str]) -> None:
            self.headers = Headers(headers)
            self.app = app

    key = _person_key(Request({"X-Nabiz-Device": "a" * 24}))
    assert key is not None and key.startswith("cihaz:") and "a" * 24 not in key
    assert _person_key(Request({})) is None
