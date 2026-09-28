"""P00 D2a (I): quota, sessions, plans, restrictions and appeals survive a restart of the product app."""

from __future__ import annotations

import pathlib

import pytest
from conftest import offline_settings
from fastapi.testclient import TestClient

from nabiz.agent import llm
from nabiz.console.access import OperatorAccess
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard

PLAN = {
    "title": "Sergi", "starts_at": "2026-10-03", "ends_at": "2026-10-04", "all_day": True,
    "time_zone": "Europe/Istanbul", "place": None, "source_url": None, "source_date": None,
    "conversation_id": None, "operation_id": "op-1", "consent": True,
}


def product_app():
    return build_console_app(
        settings=offline_settings(), llm_config=llm.LlmConfig(), guard=SpendGuard(BudgetConfig(state_path=None)),
        access=OperatorAccess(token="test-operator-token", bound_host="0.0.0.0"),
    )


def test_a_restart_keeps_what_the_stores_hold(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Only the root is named: every store the round wired finds its file under it (and none under data/).
    for name in ("NABIZ_QUOTA_DB", "NABIZ_SESSIONS_DB", "NABIZ_PLAN_DB_PATH", "NABIZ_APPEALS_DB", "NABIZ_ACCOUNTS_DB"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NABIZ_DATA_ROOT", str(tmp_path / "share"))
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "nexus.db"))
    first = product_app()
    with TestClient(first, base_url="http://127.0.0.1:8090") as client:
        signed = client.post("/api/account/signin", json={"provider": "ibb", "email": "ornek@example.org", "consent": True})
        headers = {"X-Nabiz-Account": signed.json()["token"]}
        account_id = first.state.accounts.by_token(headers["X-Nabiz-Account"]).id
        assert client.post("/api/plans", json=PLAN, headers=headers).json()["result"] == "saved_nabiz"
        holder = first.state.quota.holder(device=None, host="testclient", account_id=account_id, tier="ibb")
        assert first.state.quota.reserve_calls(holder, 3)
        token = first.state.sessions.create(account_id, "google", "subject-1")
        subject = first.state.quota.pseudonym("hesap", account_id)
        first.state.appeal_book.restrictions.restrict(subject, reason="reviewed_abuse", hours=24, human=True)
        appeal = first.state.appeal_book.submit(subject, "mistake")
    first.state.accounts.close()

    second = product_app()
    with TestClient(second, base_url="http://127.0.0.1:8090") as client:
        plans = client.get("/api/plans", headers=headers).json()["plans"]
    state = second.state
    assert [plan["title"] for plan in plans] == ["Sergi"]
    assert state.quota.pseudonym("hesap", account_id) == subject  # the salt is the file's, not the process's
    assert state.quota.calls_left(holder) == holder.tier.model_calls - 3
    assert state.sessions.get(token).account_id == account_id
    assert state.appeal_book.restrictions.current(subject) is not None
    assert [item.id for item in state.appeal_book.queue()] == [appeal.id]
    assert sorted(path.name for path in (tmp_path / "share" / "accounts").iterdir()) == [
        "accounts.sqlite", "appeals.sqlite", "quota.sqlite", "sessions.sqlite",
    ]
    assert (tmp_path / "share" / "nexus" / "plans.sqlite3").is_file()
