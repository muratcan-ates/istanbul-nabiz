"""P00 D2a (H): deleting an account reaches every store in the owner's order, or says it did not."""

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
from nabiz.console.erasure import REQUIRED_HOOKS, ErasureChain

PLAN = {
    "title": "Sergi", "starts_at": "2026-10-03", "ends_at": "2026-10-04", "all_day": True,
    "time_zone": "Europe/Istanbul", "place": None, "source_url": None, "source_date": None,
    "conversation_id": None, "operation_id": "op-1", "consent": True,
}


def test_the_hooks_run_in_the_owners_order_and_an_unknown_one_is_refused() -> None:
    assert REQUIRED_HOOKS == (
        "calendar_plans", "outlook_tokens", "appeals", "bookings", "journeys", "photo_reports", "account_memory",
        "citizen_requests", "email_outbox", "family_links", "quota", "sessions", "account",
    )
    with pytest.raises(ValueError, match="Unknown erasure hook: photos"):
        ErasureChain({"photos": lambda account_id: 0})


@pytest.fixture
def app(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "nexus.db"))
    monkeypatch.setenv("NABIZ_JOURNEY_WATCH_DB_PATH", str(tmp_path / "journeys.sqlite"))
    app = build_console_app(
        settings=offline_settings(), llm_config=llm.LlmConfig(), guard=SpendGuard(BudgetConfig(state_path=None)),
        access=OperatorAccess(token="test-operator-token", bound_host="0.0.0.0"),
    )
    app.state.accounts = AccountStore(tmp_path / "accounts.sqlite")
    app.state.outbox = OutboxEmailSender(tmp_path / "outbox")
    return app


def signed_in(client: TestClient, app) -> tuple[str, dict[str, str]]:
    body = client.post("/api/account/signin", json={"provider": "ibb", "email": "ornek@example.org", "consent": True}).json()
    return app.state.accounts.by_token(body["token"]).id, {"X-Nabiz-Account": body["token"]}


def test_every_store_forgets_the_account(app) -> None:
    with TestClient(app, base_url="http://127.0.0.1:8090") as client:
        account_id, headers = signed_in(client, app)
        assert client.post("/api/plans", json=PLAN, headers=headers).json()["result"] == "saved_nabiz"
        state = app.state
        subject = state.quota.pseudonym("hesap", account_id)
        state.appeal_book.restrictions.restrict(subject, reason="reviewed_abuse", hours=24, human=True)
        appeal = client.post("/api/appeals", headers=headers,
                             json={"category": "mistake", "consent": True, "operation_id": "op-0123456789abcdef"})
        assert appeal.status_code == 202
        family = client.post("/api/account/family/code", json={"display_name": "Ev", "consent": True}, headers=headers)
        assert family.status_code == 200, family.text
        state.sessions.create(account_id, "google", "subject-1")
        holder = state.quota.holder(device=None, host="testclient", account_id=account_id, tier="ibb")
        assert state.quota.reserve_calls(holder, 2)
        gone = client.delete("/api/account", headers=headers)
        again = client.get("/api/account", headers=headers)
    assert gone.status_code == 200
    body = gone.json()
    assert body["deleted"] is True and body["plans_deleted"] == 1 and body["appeals_deleted"] == 1
    assert body["sessions_deleted"] == 1 and body["family_deleted"] == 1
    assert state.plan_store.list(account_id) == []
    assert state.appeal_book.restrictions.current(subject) is None
    assert state.quota.status(holder)["model_calls_left"] == holder.tier.model_calls
    assert again.status_code == 401


def test_a_store_that_cannot_be_cleared_keeps_the_account_and_says_so(app, monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(app, base_url="http://127.0.0.1:8090") as client:
        account_id, headers = signed_in(client, app)

        def broken(account_id: str) -> int:
            raise OSError("disk")

        monkeypatch.setattr(app.state.sessions, "revoke_account", broken)
        refused = client.delete("/api/account", headers=headers)
        still = client.get("/api/account", headers=headers)
    assert refused.status_code == 503 and refused.json()["error"] == "erasure_incomplete"
    assert refused.headers["cache-control"] == "no-store"
    assert still.status_code == 200 and app.state.accounts.by_token(headers["X-Nabiz-Account"]).id == account_id
