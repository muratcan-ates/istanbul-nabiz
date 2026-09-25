"""POST /api/feedback: the G15 contract, counted in memory, nothing else accepted."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ibb_mcp.config import Settings
from nabiz.console.app import build_console_app
from nabiz.console.ports import Ports


@pytest.fixture
def client():
    app = build_console_app(Settings(offline=True), ports=Ports())
    with TestClient(app) as test_client:
        yield test_client


def test_an_opt_in_vote_is_counted_without_its_answer_id(client) -> None:
    response = client.post("/api/feedback", json={"answer_id": "a-0011223344556677", "vote": "down", "reason": "stale"})
    assert response.status_code == 204 and response.content == b""
    counts = client.app.state.feedback_counts
    assert counts == {("down", "stale"): 1}
    assert "a-0011223344556677" not in repr(counts)


@pytest.mark.parametrize(
    "body",
    [
        {"answer_id": "a-1", "vote": "up", "reason": None, "question": "Kadıköy'e nasıl giderim?"},
        {"answer_id": "a-1", "vote": "maybe"},
        {"answer_id": "a-1", "vote": "down", "reason": "because"},
        {"answer_id": "<script>", "vote": "up"},
        {"vote": "up"},
    ],
)
def test_anything_beyond_the_three_fields_is_refused(client, body) -> None:
    assert client.post("/api/feedback", json=body).status_code == 422
    assert not getattr(client.app.state, "feedback_counts", None)
