"""HTTP contract for GET /api/journey/accessible, using only offline recordings."""

from __future__ import annotations

import httpx
from conftest import offline_settings, refuse_network
from fastapi.testclient import TestClient

from ibb_mcp.cache import TTLCache
from ibb_mcp.http import PoliteClient
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard


def test_accessible_journey_route_returns_provenance_and_an_honest_answer() -> None:
    settings = offline_settings()
    nabiz = Nabiz(SourceContext.create(
        client=PoliteClient(transport=httpx.MockTransport(refuse_network)),
        cache=TTLCache(),
        settings=settings,
    ))
    app = build_console_app(
        settings=settings,
        nabiz=nabiz,
        llm_config=llm.LlmConfig(),
        guard=SpendGuard(BudgetConfig(state_path=None)),
    )
    with TestClient(app) as client:
        response = client.get("/api/journey/accessible", params={"from": "Kadıköy", "to": "Levent"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert {"available", "from", "to", "needs", "steps", "extra_minutes", "alternative_used",
            "operator_approved", "provenance", "uncertainty", "disclaimer"} <= set(body)
    assert body["needs"] == ["step_free"]
    assert set(body["provenance"]) == {"source", "url", "observed_at", "age_s", "mode"}
    assert body["provenance"]["mode"] in {"recorded", "unknown"}
    if not body["available"]:
        assert body["steps"] == [] and body["reason"]
