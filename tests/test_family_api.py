"""HTTP contract tests for the self-installing family router."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nabiz.console.accounts import AccountStore
from nabiz.console.accounts_api import account_routes
from nabiz.console.family_api import family_routes


def private_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"email", "account_id", "token", "tier", "consent_at"}:
                found.add(key)
            found.update(private_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.update(private_keys(item))
    return found


def make_client(tmp_path):
    app = FastAPI()
    app.include_router(account_routes)
    app.include_router(family_routes)
    app.state.accounts = AccountStore(tmp_path / "accounts.sqlite")
    return TestClient(app), app


def create_account(accounts: AccountStore, name: str) -> tuple[str, str]:
    account, token = accounts.create(email=f"{name}@example.com", provider="google", consent=True)
    return account.id, token


def test_every_family_path_requires_an_account(tmp_path) -> None:
    client, app = make_client(tmp_path)
    paths = (
        ("GET", "/api/account/family"),
        ("POST", "/api/account/family/code"),
        ("POST", "/api/account/family/code/renew"),
        ("POST", "/api/account/family/join"),
        ("DELETE", "/api/account/family/join"),
        ("POST", "/api/account/family/requests/request-id/approve"),
        ("POST", "/api/account/family/requests/request-id/reject"),
        ("DELETE", "/api/account/family/members/member-id"),
        ("POST", "/api/account/family/leave"),
        ("POST", "/api/account/family/shares"),
    )
    try:
        with client:
            for method, path in paths:
                response = client.request(method, path, json={} if method == "POST" else None)
                assert response.status_code == 401, (method, path, response.text)
                assert response.json()["error"] == "no_account"
    finally:
        app.state.accounts.close()


def test_http_flow_has_two_sided_consent_and_safe_responses(tmp_path) -> None:
    client, app = make_client(tmp_path)
    owner_id, owner_token = create_account(app.state.accounts, "owner")
    member_id, member_token = create_account(app.state.accounts, "member")
    owner_headers = {"X-Nabiz-Account": owner_token}
    member_headers = {"X-Nabiz-Account": member_token}
    try:
        with client:
            refused = client.post(
                "/api/account/family/code",
                json={"display_name": "Anne", "consent": False},
                headers=owner_headers,
            )
            assert refused.status_code == 400 and refused.json()["error"] == "consent_required"
            with app.state.accounts._lock:
                assert app.state.accounts._db.execute("SELECT COUNT(*) FROM family_groups").fetchone()[0] == 0

            created = client.post(
                "/api/account/family/code",
                json={"display_name": "Anne", "consent": True},
                headers=owner_headers,
            )
            assert created.status_code == 200
            code = created.json()["family"]["code"]["code"]
            joined = client.post(
                "/api/account/family/join",
                json={"code": code, "display_name": "Can", "consent": True},
                headers=member_headers,
            )
            assert joined.status_code == 200 and joined.json()["state"] == "pending"
            assert joined.json()["family"] is None
            assert "Anne" not in str(joined.json())

            pending = client.get("/api/account/family", headers=owner_headers).json()["family"]["requests"][0]
            assert pending["check"] == joined.json()["pending"]["check"]
            approved = client.post(
                f"/api/account/family/requests/{pending['id']}/approve",
                json={},
                headers=owner_headers,
            )
            assert approved.status_code == 200 and approved.json()["family"]["count"] == 2

            follow = app.state.accounts.add_follow(
                member_id,
                kind="metro_line",
                value="M2",
                label="M2 hattı",
            )
            shared = client.post(
                "/api/account/family/shares",
                json={"follow_ids": [follow["id"]], "stops": [{"line": "M2", "stop": "Şişli-Mecidiyeköy"}]},
                headers=member_headers,
            )
            assert shared.status_code == 200
            owner_view = client.get("/api/account/family", headers=owner_headers).json()
            member_view = client.get("/api/account/family", headers=member_headers).json()
            assert owner_view["family"]["members"][1]["shares"]["follows"] == [
                {"kind": "metro_line", "value": "M2", "label": "M2 hattı"},
            ]
            assert private_keys(owner_view) == private_keys(member_view) == set()

            left = client.post("/api/account/family/leave", json={}, headers=member_headers)
            assert left.status_code == 200 and left.json()["state"] == "none"
            assert left.json()["dissolved"] is False
            owner_after_leave = client.get("/api/account/family", headers=owner_headers).json()
            assert owner_after_leave["family"]["count"] == 1
            assert all(member["display_name"] != "Can" for member in owner_after_leave["family"]["members"])

            dissolved = client.post("/api/account/family/leave", json={}, headers=owner_headers)
            assert dissolved.status_code == 200 and dissolved.json()["state"] == "none"
            assert dissolved.json()["dissolved"] is True
    finally:
        if getattr(app.state, "family", None):
            app.state.family.close()
        app.state.accounts.close()


def test_family_router_uses_only_body_or_path_parameters(tmp_path) -> None:
    del tmp_path
    for route in family_routes.routes:
        assert route.path.startswith("/api/account/family")
        assert not route.dependant.query_params
