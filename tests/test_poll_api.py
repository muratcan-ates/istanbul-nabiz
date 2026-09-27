from __future__ import annotations

import datetime as dt
import json

import pytest
from conftest import offline_settings
from fastapi.testclient import TestClient

from ibb_mcp.models import ISTANBUL_TZ
from nabiz.agent import llm
from nabiz.console.access import OperatorAccess
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.poll_api import poll_desk, poll_routes
from nexus_core.ledger import Ledger

DEVICE = "0123456789abcdef0123456789abcdef"
OPERATOR = {"X-Nabiz-Operator": "poll-secret"}


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "nexus.db"))
    monkeypatch.setenv("NABIZ_POLLS_DB_PATH", str(tmp_path / "polls.db"))
    monkeypatch.setenv("NABIZ_POLL_VOTES_PER_HOUR", "30")
    app = build_console_app(
        settings=offline_settings(),
        llm_config=llm.LlmConfig(),
        guard=SpendGuard(BudgetConfig(state_path=None)),
        access=OperatorAccess(token="poll-secret"),
    )
    if not any(getattr(route, "path", None) == "/api/polls/active" for route in app.router.routes):
        app.include_router(poll_routes)
    static = next((route for route in app.router.routes if getattr(route, "name", None) == "static"), None)
    if static is not None and app.router.routes[-1] is not static:
        app.router.routes.remove(static)
        app.router.routes.append(static)
    return TestClient(app, base_url="http://testserver")


def payload() -> dict:
    tomorrow = (dt.datetime.now(ISTANBUL_TZ).date() + dt.timedelta(days=1)).isoformat()
    return {
        "question": "İstanbul ulaşımı nasıl?",
        "options": ["Daha iyi", "Aynı"],
        "closes_on": tomorrow,
        "target": {"kind": "all", "district": None},
    }


def test_console_door_and_complete_poll_flow(client: TestClient, tmp_path) -> None:
    assert client.get("/api/console/polls").status_code == 401
    assert client.get("/api/console/polls", headers=OPERATOR).status_code == 200

    created = client.post("/api/console/polls", json=payload(), headers=OPERATOR)
    assert created.status_code == 201, created.text
    draft = created.json()["draft"]
    assert "salt" not in json.dumps(created.json())
    poll_id = draft["id"]

    unconfirmed = client.post(
        f"/api/console/polls/{poll_id}/publish",
        json={"confirm": False, "digest": draft["digest"]},
        headers=OPERATOR,
    )
    assert unconfirmed.status_code == 400 and unconfirmed.json()["error"] == "confirm_required"
    wrong = client.post(
        f"/api/console/polls/{poll_id}/publish",
        json={"confirm": True, "digest": "0" * 64},
        headers=OPERATOR,
    )
    assert wrong.status_code == 409 and "önizlemeyi" in wrong.json()["message"]
    published = client.post(
        f"/api/console/polls/{poll_id}/publish",
        json={"confirm": True, "digest": draft["digest"]},
        headers=OPERATOR,
    )
    assert published.status_code == 200 and published.json()["active"]["status"] == "active"

    active = client.get("/api/polls/active")
    assert active.status_code == 200 and active.headers["cache-control"] == "no-store"
    visible = active.json()["poll"]
    assert visible["id"] == poll_id and visible["simulated"] is True
    assert not {"salt", "digest", "audit", "results", "tallies"} & set(visible)
    assert "no-store" in active.headers["cache-control"]

    vote_headers = {"X-Nabiz-Device": DEVICE}
    first = client.post(f"/api/polls/{poll_id}/vote", json={"choice": "o1"}, headers=vote_headers)
    assert first.status_code == 201 and first.json()["message"] == "Oyunuz alındı. Teşekkürler."
    assert first.headers["cache-control"] == "no-store"
    duplicate = client.post(f"/api/polls/{poll_id}/vote", json={"choice": "o2"}, headers=vote_headers)
    assert duplicate.status_code == 409 and duplicate.json()["error"] == "already_voted"
    assert client.post(f"/api/polls/{poll_id}/vote", json={"choice": "o1"}).status_code == 400
    assert (
        client.post(
            f"/api/polls/{poll_id}/vote",
            json={"choice": "o1"},
            headers={"X-Nabiz-Device": "bad"},
        ).status_code
        == 400
    )
    assert client.post(f"/api/polls/{poll_id}/vote", json={"choice": "bad"}, headers={**vote_headers, **{}}).status_code == 400

    desk = poll_desk(client.app)
    desk.limit.limit = 3
    limited = client.post(f"/api/polls/{poll_id}/vote", json={"choice": "o2"}, headers={"X-Nabiz-Device": "fedcba9876543210"})
    assert limited.status_code == 429 and limited.json()["error"] == "too_many_votes"

    queue = client.get("/api/console/polls", headers=OPERATOR).json()
    assert queue["active"]["results"]["total"] == 1
    assert queue["active"]["results"]["rows"][0]["percent"] is None
    no_reason = client.post(f"/api/console/polls/{poll_id}/close", json={"reason": "  "}, headers=OPERATOR)
    assert no_reason.status_code == 400 and no_reason.json()["error"] == "reason_required"
    closed = client.post(
        f"/api/console/polls/{poll_id}/close",
        json={"reason": "Operatör kararı"},
        headers=OPERATOR,
    )
    assert closed.status_code == 200 and closed.json()["closed"]["status"] == "closed"
    history = client.get("/api/console/polls", headers=OPERATOR).json()["last_closed"]
    assert history["id"] == poll_id and history["results"]["total"] == 1
    assert history["audit"][-1]["how"] == "operator"
    assert client.get("/api/polls/active").json() == {"poll": None}
    desk.limit = desk.limit.__class__(30)
    gone = client.post(f"/api/polls/{poll_id}/vote", json={"choice": "o1"}, headers={"X-Nabiz-Device": "abcdef0123456789"})
    assert gone.status_code == 404
    entries = Ledger(tmp_path / "nexus.db").entries(entity_id=f"poll:{poll_id}")
    assert [entry.kind for entry in entries] == ["poll_published", "poll_closed"]
    assert Ledger(tmp_path / "nexus.db").verify().ok


def test_poll_paths_are_public_but_console_paths_require_the_door(client: TestClient) -> None:
    assert client.get("/api/polls/active").status_code == 200
    assert client.post("/api/console/polls", json=payload()).status_code == 401


def test_ledger_failure_returns_503_and_leaves_the_draft_unpublished(client: TestClient, monkeypatch) -> None:
    created = client.post("/api/console/polls", json=payload(), headers=OPERATOR).json()["draft"]

    def refuse_append(*args, **kwargs):
        raise OSError("ledger unavailable")

    monkeypatch.setattr(Ledger, "append", refuse_append)
    failed = client.post(
        f"/api/console/polls/{created['id']}/publish",
        json={"confirm": True, "digest": created["digest"]},
        headers=OPERATOR,
    )
    assert failed.status_code == 503 and failed.json()["error"] == "not_recorded"
    queue = client.get("/api/console/polls", headers=OPERATOR).json()
    assert queue["draft"]["status"] == "draft" and queue["active"] is None
