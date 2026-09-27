"""The router is stand-alone; integration must inject a trusted subject and a provider."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nabiz.console.access import HEADER, OperatorAccess
from nabiz.console.appeal_api import appeal_routes
from nabiz.console.appeals import AppealBook
from nabiz.console.restriction import RestrictionBook

TOKEN = "test-operator-token"
APPEAL_BODY = {"category": "mistake", "consent": True, "operation_id": "op-0123456789abcdef"}


def client(*, wired: bool = True) -> tuple[TestClient, RestrictionBook]:
    app = FastAPI()
    app.state.access = OperatorAccess(token=TOKEN, bound_host="0.0.0.0")
    restrictions = RestrictionBook()
    if wired:
        app.state.appeal_book = AppealBook(restrictions)
        # Only the fake test adapter reads this header. The production router does not.
        app.state.restriction_subject = lambda request: request.headers.get("x-test-session", "")
    app.include_router(appeal_routes)
    return TestClient(app), restrictions


def test_unwired_features_are_closed_and_operator_requires_token() -> None:
    web, _ = client(wired=False)
    assert web.get("/api/console/appeals").status_code == 401
    assert web.post("/api/console/appeals/a/decision", json={"action": "bad"}).status_code == 401
    assert web.get("/api/console/appeals", headers={HEADER: TOKEN}).status_code == 503
    assert web.post("/api/appeals", json=APPEAL_BODY).status_code == 503


def test_citizen_appeal_queue_and_reasoned_reopen() -> None:
    web, restrictions = client()
    restrictions.restrict("session-one", reason="automated_burst", hours=24, human=False)
    citizen = {"x-test-session": "session-one"}
    other = {"x-test-session": "session-two"}
    assert web.get("/api/restriction", headers=citizen).json()["restricted"] is True
    assert web.post("/api/appeals", headers=citizen, json={**APPEAL_BODY, "consent": False}).status_code == 400
    assert web.post("/api/appeals", headers=citizen, json={"category": "mistake"}).status_code == 422
    sent = web.post("/api/appeals", headers=citizen, json=APPEAL_BODY)
    assert sent.status_code == 202
    appeal_id = sent.json()["id"]
    assert web.get(f"/api/appeals/{appeal_id}", headers=other).status_code == 404
    assert web.get("/api/console/appeals").status_code == 401
    queue = web.get("/api/console/appeals", headers={HEADER: TOKEN})
    assert queue.status_code == 200 and queue.json()["appeals"][0]["id"] == appeal_id
    path = f"/api/console/appeals/{appeal_id}/decision"
    assert web.post(path, json={"action": "reopen", "reason": ""}, headers={HEADER: TOKEN}).status_code == 400
    opened = web.post(path, json={"action": "reopen", "reason": "mistaken_restriction"}, headers={HEADER: TOKEN})
    assert opened.status_code == 200 and opened.json()["status"] == "reopened"
    assert web.get("/api/restriction", headers=citizen).json()["restricted"] is False
    assert web.get("/api/console/appeals", headers={HEADER: TOKEN}).json()["appeals"] == []
