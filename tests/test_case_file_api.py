"""HTTP contracts for the case-file API, isolated in each test application."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nabiz.console import accounts_api, case_file_api
from nabiz.console.accounts import AccountStore
from nabiz.console.case_file import CaseFileStore
from nabiz.console.citizen_requests import HourlyLimit

# a week ahead: the store accepts reminders from today on, so a fixed date ages out
REMIND_ON = (dt.date.today() + dt.timedelta(days=7)).isoformat()


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[tuple[TestClient, FastAPI, AccountStore]]:
    accounts_path = tmp_path / "accounts.sqlite"
    monkeypatch.setenv("NABIZ_CASE_FILES_DB_PATH", str(tmp_path / "case_files.sqlite"))
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(tmp_path / "missing-knowledge.sqlite"))
    monkeypatch.setattr(case_file_api, "create_limit", HourlyLimit(10))
    app = FastAPI()
    accounts = AccountStore(accounts_path)
    app.state.accounts = accounts
    app.state.case_files = None
    app.state.life_events = None
    app.include_router(accounts_api.account_routes)
    app.include_router(case_file_api.case_file_routes)
    with TestClient(app) as test_client:
        yield test_client, app, accounts
    if app.state.case_files is not None:
        app.state.case_files.close()
    accounts.close()


def _file(response):
    assert response.status_code == 200, response.text
    return response.json()["file"]


def _walk_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def test_plans_are_public_and_missing_index_is_explicit(client) -> None:
    c, _, _ = client
    response = c.get("/api/case-file/plans")
    assert response.status_code == 200
    data = response.json()
    assert data["plans"][0]["id"] == "tasinma"
    assert data["band"].startswith("Örnek iş dosyası")
    water = data["plans"][0]["steps"][0]
    assert water["source_missing"] is True
    assert water["sources"] and all(not source["indexed"] and source["url"] is None for source in water["sources"])
    assert not any(source.get("quotes") or source.get("documents") for source in water["sources"])
    assert c.post("/api/case-file/open", json={}).json()["error"] == "no_owner"
    assert c.post("/api/case-file/anything/step", json={"step_id": "su", "done": True}).json()["error"] == "no_owner"


def test_device_create_answer_step_refresh_and_delete_flow(client, tmp_path) -> None:
    c, app, _ = client
    created = c.post("/api/case-file", json={"plan_id": "tasinma", "consent": True})
    assert created.status_code == 200, created.text
    data = created.json()
    key = data["key"]
    file = data["file"]
    headers = {"X-Nabiz-Case": key}
    assert "owner_ref" not in tuple(_walk_keys(data))
    assert "token_hash" not in tuple(_walk_keys(data))
    assert "key" not in tuple(_walk_keys(file))
    assert file["steps"][0]["verified"] is False and file["steps"][0]["added_by"] == "user"
    opened = c.post("/api/case-file/open", headers=headers, json={})
    assert opened.status_code == 200 and opened.json()["files"][0]["id"] == file["id"]
    answer = c.post(f"/api/case-file/{file['id']}/answer", headers=headers, json={"step_id": "su", "choice": "yenileme"})
    assert _file(answer)["answers"] == {"su": "yenileme"}
    updated = c.post(
        f"/api/case-file/{file['id']}/step",
        headers=headers,
        json={
            "step_id": "su",
            "done": True,
            "note": "İşlem notum",
            "ref_code": "AB-421",
            "remind_on": REMIND_ON,
        },
    )
    step = next(item for item in _file(updated)["steps"] if item["step_id"] == "su")
    assert step["done_at"] and step["note"] == "İşlem notum" and step["ref_code"] == "AB-421"
    assert step["remind_on"] == REMIND_ON
    path = app.state.case_files.path
    app.state.case_files.close()
    app.state.case_files = None

    restarted = FastAPI()
    accounts = app.state.accounts
    restarted.state.accounts = accounts
    restarted.state.case_files = CaseFileStore(path, accounts_path=accounts.path)
    restarted.state.life_events = None
    restarted.include_router(case_file_api.case_file_routes)
    with TestClient(restarted) as reopened:
        persisted = reopened.post("/api/case-file/open", headers=headers, json={})
        assert persisted.status_code == 200 and persisted.json()["files"][0]["answers"] == {"su": "yenileme"}
        assert next(item for item in persisted.json()["files"][0]["steps"] if item["step_id"] == "su")["ref_code"] == "AB-421"
        deleted = reopened.delete(f"/api/case-file/{file['id']}", headers=headers)
        assert deleted.status_code == 200 and deleted.json()["deleted"] is True
    restarted.state.case_files.close()
    app.state.case_files = None


def test_account_flow_has_no_device_key_in_response(client) -> None:
    c, _, accounts = client
    account, token = accounts.create(email="person@example.org", provider="ibb", consent=True)
    headers = {"X-Nabiz-Account": token}
    created = c.post("/api/case-file", headers=headers, json={"plan_id": "tasinma", "consent": True})
    assert created.status_code == 200
    assert "key" not in created.json()
    opened = c.post("/api/case-file/open", headers=headers, json={})
    assert opened.status_code == 200 and opened.json()["files"][0]["plan_id"] == "tasinma"
    assert account.email not in str(opened.json())


def test_key_occurs_only_in_the_create_response(client) -> None:
    c, _, _ = client
    created = c.post("/api/case-file", json={"plan_id": "tasinma", "consent": True}).json()
    key = created["key"]
    headers = {"X-Nabiz-Case": key}
    opened = c.post("/api/case-file/open", headers=headers, json={}).json()
    answer = c.post(
        f"/api/case-file/{created['file']['id']}/answer", headers=headers, json={"step_id": "su", "choice": "iptal"}
    ).json()
    for response in (opened, answer):
        keys = tuple(_walk_keys(response))
        assert not {"owner_ref", "token_hash", "email", "token", "key"}.intersection(keys)


def test_routes_have_expected_prefix_no_query_and_safe_errors(client) -> None:
    c, app, _ = client
    routes = [route for route in case_file_api.case_file_routes.routes if getattr(route, "path", "")]
    assert routes and all(route.path.startswith("/api/case-file") for route in routes)
    assert all(not route.dependant.query_params for route in routes)
    failed = c.post("/api/case-file", json={"plan_id": "unknown", "consent": True})
    assert failed.status_code == 400 and set(failed.json()) == {"error", "message"}
    message = failed.json()["message"]
    assert "\N{EM DASH}" not in message and "\N{EN DASH}" not in message


def test_eleventh_create_from_one_client_is_limited(client) -> None:
    c, _, _ = client
    statuses = [c.post("/api/case-file", json={"plan_id": "tasinma", "consent": True}).status_code for _ in range(11)]
    assert statuses[:10] == [200] * 10
    assert statuses[10] == 429
