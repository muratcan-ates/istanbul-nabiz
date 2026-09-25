"""nabiz.console.access: the operator's door, the chat's turn limit and the sample data switch.

The app runs on the recorded fixtures with a fake console port; no model, no İBB call. The
token below is a test value.
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import offline_settings
from fastapi.testclient import TestClient

from nabiz.agent import llm
from nabiz.console.access import COOKIE, HEADER, OperatorAccess, TurnLimiter, host_name
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.ports import Ports

TOKEN = "test-operator-token"


class Console:
    async def stats(self) -> dict[str, Any]:
        return {"ok": True}


def client(access: OperatorAccess, *, base_url: str = "http://127.0.0.1:8090", settings: Any = None) -> TestClient:
    app = build_console_app(
        settings=settings or offline_settings(),
        llm_config=llm.LlmConfig(),
        ports=Ports(console=Console()),  # type: ignore[arg-type]
        guard=SpendGuard(BudgetConfig(state_path=None)),
        access=access,
    )
    return TestClient(app, base_url=base_url)


def test_without_a_token_only_this_machine_may_open_the_console() -> None:
    local = client(OperatorAccess())
    assert local.get("/api/console/stats").json() == {"ok": True}
    assert local.get("/console").status_code == 200
    with client(OperatorAccess(), base_url="http://evil.example:8090") as rebound:
        refused = rebound.get("/api/console/stats")
        assert refused.status_code == 403 and refused.json()["error"] == "forbidden_host"
        for path in ("/console", "/console.html", "/css/../console.html", "/api/console/../console/stats"):
            assert rebound.get(path).status_code == 403, path
        assert rebound.get("/healthz").status_code == 200, "the citizen side does not check the host"


def test_bound_to_a_network_without_a_token_the_console_stays_shut() -> None:
    public = client(OperatorAccess(bound_host="0.0.0.0"))
    shut = public.get("/api/console/stats")
    assert shut.status_code == 503 and shut.json()["error"] == "console_locked"


def test_with_a_token_the_header_or_the_sign_in_cookie_opens_it() -> None:
    access = OperatorAccess(token=TOKEN, bound_host="0.0.0.0")
    web = client(access, base_url="https://nabiz.example")
    assert web.get("/api/console/stats").status_code == 401
    page = web.get("/console")
    assert page.status_code == 401 and 'action="/console/login"' in page.text and "Resmî İBB hizmeti değildir" in page.text
    assert web.get("/api/console/stats", headers={HEADER: TOKEN}).json() == {"ok": True}
    assert web.get("/api/console/stats", headers={HEADER: TOKEN + "x"}).status_code == 401

    wrong = web.post("/console/login", data={"token": "nope"}, follow_redirects=False)
    assert wrong.status_code == 401 and COOKIE not in wrong.cookies
    signed = web.post("/console/login", data={"token": TOKEN}, follow_redirects=False)
    assert signed.status_code == 303 and signed.headers["location"] == "/console"
    set_cookie = signed.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=strict" in set_cookie and "secure" in set_cookie
    assert TOKEN not in signed.headers["set-cookie"], "the cookie is an HMAC, never the token"
    assert web.get("/api/console/stats").json() == {"ok": True}


def test_host_names_are_read_without_their_port() -> None:
    assert host_name("127.0.0.1:8090") == "127.0.0.1" and host_name("[::1]:8090") == "::1"
    assert host_name("LOCALHOST") == "localhost" and host_name("::1") == "::1"


def test_the_chat_turn_limit_refills_over_a_minute() -> None:
    limiter = TurnLimiter(2, clients=2)
    assert limiter.allow("a", now=0.0) and limiter.allow("a", now=0.0)
    assert not limiter.allow("a", now=1.0), "the burst is spent"
    assert limiter.allow("b", now=1.0), "another address has its own bucket"
    assert limiter.allow("a", now=31.0), "one turn back after half a minute"
    limiter.allow("c", now=31.0)
    assert list(limiter._buckets) == ["a", "c"], "the oldest address is forgotten first"


def test_the_chat_answers_429_past_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NABIZ_CHAT_TURNS_PER_MIN", "1")
    with client(OperatorAccess()) as chat:
        first = chat.post("/api/chat", json={"message": "Metro bileti ne kadar?"})
        assert first.status_code == 200
        second = chat.post("/api/chat", json={"message": "Metro bileti ne kadar?"})
        assert second.status_code == 429 and second.json()["error"] == "too_many_turns"


def test_sample_data_is_served_offline_only(monkeypatch: pytest.MonkeyPatch) -> None:
    import dataclasses

    offline = client(OperatorAccess())
    assert offline.get("/mock/brief.json").status_code == 200
    live = client(OperatorAccess(), settings=dataclasses.replace(offline_settings(), offline=False))
    for path in ("/mock/brief.json", "/mock/x/../brief.json", "/js/../mock/brief.json"):
        assert live.get(path).status_code == 404, path
    monkeypatch.setenv("NABIZ_UI_MOCK", "1")
    assert live.get("/mock/brief.json").status_code == 200


def test_a_too_long_reason_or_edit_gets_a_turkish_sentence_not_pydantic() -> None:
    class Deciding(Console):
        async def decide(self, signal_id: str, **kwargs: Any) -> dict[str, Any]:
            raise AssertionError("the route must refuse before the core")

    app = build_console_app(settings=offline_settings(), llm_config=llm.LlmConfig(), ports=Ports(console=Deciding()),  # type: ignore[arg-type]
                            guard=SpendGuard(BudgetConfig(state_path=None)), access=OperatorAccess())  # fmt: skip
    web = TestClient(app, base_url="http://127.0.0.1:8090")
    for body in ({"action": "reject", "reason": "x" * 281}, {"action": "edit", "edited_text": "y" * 601}):
        answer = web.post("/api/console/decisions/s1", json=body)
        assert answer.status_code == 422 and answer.json()["error"] == "invalid_request"
        assert "pydantic" not in answer.text and "İstek geçersiz" in answer.json()["message"]
