from __future__ import annotations

from dataclasses import replace

import pytest
from conftest import offline_settings
from fastapi.testclient import TestClient

from nabiz.agent import llm
from nabiz.console.access import OperatorAccess
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.model_api import (
    NOTE_CAP_LOCAL,
    NOTE_CAP_RULES,
    NOTE_NO_MODEL,
    active_rung,
    model_routes,
)
from nabiz.console.ports import Ports


def make_app(*, config=None, guard=None, ports=None, access=None):
    app = build_console_app(
        settings=offline_settings(),
        llm_config=config if config is not None else llm.LlmConfig(),
        ports=ports if ports is not None else Ports(),
        guard=guard if guard is not None else SpendGuard(BudgetConfig(state_path=None)),
        access=access if access is not None else OperatorAccess(),
    )
    app.include_router(model_routes)
    mount = next(route for route in app.router.routes if getattr(route, "name", None) == "static")
    app.router.routes.remove(mount)
    app.router.routes.append(mount)
    return app


def client(*, config=None, guard=None, ports=None, access=None):
    return TestClient(make_app(config=config, guard=guard, ports=ports, access=access), base_url="http://127.0.0.1:8090")


def cloud_config() -> llm.LlmConfig:
    # These are synthetic endpoint values; they are not prices or live credentials.
    return llm.LlmConfig(
        base_url="https://example.invalid/v1",
        api_key="test-key-not-a-secret",
        model="test-model",
        provider="openai_compatible",
    )


def test_no_rung_means_the_rules_answer() -> None:
    config = llm.LlmConfig()
    status = client(config=config).get("/api/model/status").json()
    assert status["rungs"] == []
    assert status["first_rung"] is None
    assert status["active_author"] == "kural"
    assert status["note"] == NOTE_NO_MODEL
    assert "kural yolu" not in status["note"]


def test_a_cloud_rung_within_budget_prints_no_note() -> None:
    status = client(config=cloud_config()).get("/api/model/status").json()
    assert status["note"] is None
    assert status["within_budget"] is True
    assert status["active_label"] == "bulut modeli"


def test_a_full_ceiling_without_a_local_rung_turns_to_rules() -> None:
    guard = SpendGuard(BudgetConfig(daily_calls=0, state_path=None))
    status = client(config=cloud_config(), guard=guard).get("/api/model/status").json()
    assert status["within_budget"] is False
    assert status["active_author"] == "kural"
    assert status["note"] == NOTE_CAP_RULES


def test_a_full_ceiling_with_a_local_rung_follows_the_chat() -> None:
    cloud = cloud_config()
    local = llm.LlmConfig(base_url="http://127.0.0.1:5273/v1", provider="foundry_local")
    config = replace(cloud, fallback=local)
    guard = SpendGuard(BudgetConfig(daily_calls=0, state_path=None))
    from nabiz.console.model_api import model_status

    if hasattr(llm, "pick_rung"):
        local_status = model_status(config, guard, offline=True, env={})
        assert local_status["active_label"] == "yerel model"
        assert local_status["note"] == NOTE_CAP_LOCAL
        assert local_status["ladder"] is True
    else:
        assert active_rung(config, guard.allows, env={}) is None
        assert active_rung(config, guard.allows, env={"NABIZ_LADDER_LOCAL_ON_CAP": "0"}) is None
        assert NOTE_CAP_RULES

    env_off = {llm.LOCAL_ON_CAP_ENV: "0"} if hasattr(llm, "LOCAL_ON_CAP_ENV") else {"NABIZ_LADDER_LOCAL_ON_CAP": "0"}
    rules_status = model_status(config, guard, offline=True, env=env_off)
    assert rules_status["active_label"] == "kural"
    assert rules_status["note"] == NOTE_CAP_RULES
    assert rules_status["ladder"] is False


def test_the_body_carries_no_key_and_no_url() -> None:
    response = client(config=cloud_config()).get("/api/model/status")
    for value in ("test-key", "test-model", "example.invalid", "127.0.0.1", "http", "api_key", "base_url", '"model":'):
        assert value not in response.text


def test_nothing_is_probed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args, **kwargs):
        raise AssertionError("provider discovery must not run")

    for name in ("models_reachable", "foundry_status_url", "foundry_local_running", "discover_model"):
        if hasattr(llm, name):
            monkeypatch.setattr(llm, name, fail)
    assert client(config=cloud_config()).get("/api/model/status").status_code == 200


def test_offline_is_reported() -> None:
    assert client().get("/api/model/status").json()["offline"] is True


def test_within_budget_is_the_healthz_expression() -> None:
    config = cloud_config()
    for calls in (0, 1):
        guard = SpendGuard(BudgetConfig(daily_calls=1, state_path=None))
        guard.record("openai_compatible", {}, calls)
        status = client(config=config, guard=guard).get("/api/model/status").json()
        assert status["within_budget"] == guard.allows(config.provider)


def test_the_status_is_open_to_the_citizen() -> None:
    access = OperatorAccess(bound_host="0.0.0.0")
    web = client(access=access)
    assert web.get("/api/model/status").status_code == 200
    spend = web.get("/api/console/spend")
    assert spend.status_code == 503 and spend.json()["error"] == "console_locked"


def test_there_is_no_probe_route() -> None:
    app = make_app()
    assert all("probe" not in getattr(route, "path", "") for route in app.router.routes)
    assert TestClient(app, base_url="http://127.0.0.1:8090").post("/api/model/status").status_code == 405
