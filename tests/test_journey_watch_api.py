"""Offline HTTP behavior for the stateless check and separately consented account rows."""

from __future__ import annotations

import httpx
import pytest
from conftest import offline_settings, refuse_network
from fastapi.testclient import TestClient
from starlette.routing import Mount

from ibb_mcp.cache import TTLCache
from ibb_mcp.http import PoliteClient
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.console.accounts import AccountStore
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.journey_watch import JourneyStore
from nabiz.console.journey_watch_api import journey_watch_routes
from nabiz.console.ports import PortNotWired


def make_app(tmp_path):
    settings = offline_settings()
    nabiz = Nabiz(
        SourceContext.create(
            client=PoliteClient(transport=httpx.MockTransport(refuse_network)),
            cache=TTLCache(),
            settings=settings,
        )
    )
    app = build_console_app(
        settings=settings,
        nabiz=nabiz,
        llm_config=llm.LlmConfig(),
        guard=SpendGuard(BudgetConfig(state_path=None)),
    )
    first_new_route = len(app.router.routes)
    app.include_router(journey_watch_routes)
    new_routes = app.router.routes[first_new_route:]
    del app.router.routes[first_new_route:]
    static_mount = next(
        index for index, route in enumerate(app.router.routes) if isinstance(route, Mount) and route.path in {"", "/"}
    )
    app.router.routes[static_mount:static_mount] = new_routes
    app.state.accounts = AccountStore(tmp_path / "accounts.sqlite")
    app.state.journey_watch_store = JourneyStore(tmp_path / "journeys.sqlite")
    return app, nabiz


def journey(index: int, origin: str, destination: str, need: str = "step_free") -> dict[str, object]:
    return {"id": f"j{index}", "from": origin, "to": destination, "time": "08:30", "needs": [need]}


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"id": "bad1", "from": "41.0123,29.0123", "to": "Levent", "needs": ["step_free"]}, "konum"),
        ({"id": "bad2", "from": "0532 " + "123 45 67", "to": "Levent", "needs": ["step_free"]}, "kişisel bilgi"),
        ({"id": "bad3", "from": "Kadıköy", "to": "kadikoy", "needs": ["step_free"]}, "aynı"),
        ({"id": "bad4", "from": "Kadıköy", "to": "Levent", "time": "25:90", "needs": ["step_free"]}, "Saat"),
    ],
)
def test_invalid_journey_is_a_row_result(payload, message, tmp_path) -> None:
    app, nabiz = make_app(tmp_path)
    try:
        with TestClient(app) as client:
            response = client.post("/api/journey-watch/check", json={"journeys": [payload]})
        assert response.status_code == 200, response.text
        row = response.json()["results"][0]
        assert row["level"] == "invalid" and message in row["error"]
    finally:
        import asyncio

        asyncio.run(nabiz.aclose())


def test_real_offline_demo_pairs_return_their_measured_levels(tmp_path) -> None:
    app, nabiz = make_app(tmp_path)
    pairs = [
        ("Zeytinburnu", "Bağcılar", "clear"),
        ("Bostancı", "Kartal", "clear"),
        ("Maltepe", "Pendik", "clear"),
        ("Kadıköy", "Levent", "affected"),
        ("Kabataş", "Taksim", "affected"),
        ("Üsküdar", "Yenikapı", "affected"),
        ("Mecidiyeköy", "Mahmutbey", "affected"),
    ]
    measured = []
    try:
        with TestClient(app) as client:
            for start in range(0, len(pairs), 3):
                batch = pairs[start : start + 3]
                response = client.post(
                    "/api/journey-watch/check",
                    json={
                        "journeys": [
                            journey(start + offset + 1, origin, destination)
                            for offset, (origin, destination, _) in enumerate(batch)
                        ],
                    },
                )
                assert response.status_code == 200, response.text
                measured.extend(response.json()["results"])
        assert [item["level"] for item in measured] == [level for _, _, level in pairs]
        assert all(item["provenance"]["source"] == "metro_equipment" for item in measured)
        assert all(item["reasons"][0]["observed_at"] for item in measured)
        assert measured[-1]["reasons"][0]["source"] == "Metro İstanbul duyurusu"
        assert measured[-1]["reasons"][0]["line"] == "M7"
        assert measured[-1]["reasons"][0]["observed_at"]
    finally:
        import asyncio

        asyncio.run(nabiz.aclose())


def test_one_invalid_row_does_not_drop_another_and_device_check_writes_no_database(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "must-not-exist.sqlite"
    monkeypatch.setenv("NABIZ_JOURNEY_WATCH_DB_PATH", str(db_path))
    app, nabiz = make_app(tmp_path)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/journey-watch/check",
                json={
                    "journeys": [
                        {"id": "bad", "from": "Kadıköy", "to": "kadikoy", "needs": ["step_free"]},
                        journey(2, "Zeytinburnu", "Bağcılar"),
                    ]
                },
            )
        assert response.status_code == 200, response.text
        assert [item["level"] for item in response.json()["results"]] == ["invalid", "clear"]
        assert response.json()["stored"] is False
        assert not db_path.exists()
    finally:
        import asyncio

        asyncio.run(nabiz.aclose())


def test_a_device_request_cannot_exceed_the_three_journey_limit(tmp_path) -> None:
    app, nabiz = make_app(tmp_path)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/journey-watch/check",
                json={
                    "journeys": [
                        journey(1, "A1", "B1"),
                        journey(2, "A2", "B2"),
                        journey(3, "A3", "B3"),
                        journey(4, "A4", "B4"),
                    ]
                },
            )
        assert response.status_code == 422
    finally:
        import asyncio

        asyncio.run(nabiz.aclose())


def test_account_routes_require_separate_consent_and_keep_accounts_separate(tmp_path) -> None:
    app, nabiz = make_app(tmp_path)
    try:
        account_a, token_a = app.state.accounts.create(email="journey-a@example.com", provider="ibb", consent=True)
        account_b, token_b = app.state.accounts.create(email="journey-b@example.com", provider="ibb", consent=True)
        headers_a = {"x-nabiz-account": token_a}
        headers_b = {"x-nabiz-account": token_b}
        saved = journey(1, "Kadıköy", "Levent")
        with TestClient(app) as client:
            assert client.get("/api/account/journeys").status_code == 401
            refused = client.post("/api/account/journeys", json={"journey": saved, "consent": False}, headers=headers_a)
            assert refused.status_code == 400 and refused.json()["error"] == "consent_required"
            assert app.state.journey_watch_store.items(account_a.id) == []
            assert (
                client.post("/api/account/journeys", json={"journey": saved, "consent": True}, headers=headers_a).status_code
                == 200
            )
            assert (
                client.post("/api/account/journeys", json={"journey": saved, "consent": True}, headers=headers_b).status_code
                == 200
            )
            assert len(client.get("/api/account/journeys", headers=headers_a).json()["journeys"]) == 1
            assert len(client.get("/api/account/journeys", headers=headers_b).json()["journeys"]) == 1
            checked = client.post("/api/account/journeys/check", json={}, headers=headers_a)
            assert checked.status_code == 200 and "changed" in checked.json()
            assert client.delete("/api/account/journeys/j1", headers=headers_a).json() == {"deleted": True}
            assert client.get("/api/account/journeys", headers=headers_a).json()["journeys"] == []
            assert len(client.get("/api/account/journeys", headers=headers_b).json()["journeys"]) == 1
        assert app.state.journey_watch_store.delete_account(account_b.id) == 1
    finally:
        import asyncio

        asyncio.run(nabiz.aclose())


def test_account_check_maps_an_unwired_journey_port_to_503(tmp_path, monkeypatch) -> None:
    async def unavailable(*args, **kwargs):
        raise PortNotWired("journey source is not wired")

    monkeypatch.setattr("nabiz.console.journey_watch_api._check", unavailable)
    app, nabiz = make_app(tmp_path)
    _, token = app.state.accounts.create(email="journey-port@example.com", provider="ibb", consent=True)
    try:
        with TestClient(app) as client:
            response = client.post("/api/account/journeys/check", json={}, headers={"x-nabiz-account": token})
        assert response.status_code == 503
        assert response.json()["error"] == "not_wired"
    finally:
        import asyncio

        asyncio.run(nabiz.aclose())
