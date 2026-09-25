"""``POST /api/chat`` on the product app: the event stream, the author, the ceiling, the refusal.

No test here reaches a model. ``nabiz.agent.llm.chat`` is replaced by :class:`FakeModel`, a
scripted provider that returns completion dicts in the shape ``llm._normalise`` produces, and
the İBB tools run offline on the recorded fixtures (``conftest.offline_settings``).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from conftest import offline_settings, refuse_network
from fastapi.testclient import TestClient

from ibb_mcp.cache import TTLCache
from ibb_mcp.http import PoliteClient
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.console import chat as chat_module
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.policy import NEEDS, memory_suggestion, refuses

CLOUD = llm.LlmConfig(base_url="http://model.invalid/v1", model="fake-model", provider="openai_compatible")
LOCAL = llm.LlmConfig(base_url="http://localhost:5273/v1", model="fake-local", provider="foundry_local")
METRO_QUESTION = "Metro hattında arıza var mı?"
PLAIN_ANSWER = "Metro hattında bir çalışma duyurusu var; seferler aktarmalı yapılıyor."


def reply(content: str | None = None, tool_calls: list[dict[str, Any]] | None = None, *, prompt: int = 100, completion: int = 20):
    return {
        "content": content,
        "tool_calls": tool_calls or [],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
        "model": "fake-model",
        "finish_reason": "stop",
        "raw": {},
    }


def tool_call(name: str, **arguments: Any) -> dict[str, Any]:
    return {"id": f"call_{name}", "name": name, "arguments": arguments}


class FakeModel:
    """A scripted provider: each call pops the next reply, or raises it when it is an exception."""

    def __init__(self, *script: Any) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, config: llm.LlmConfig, messages: Any, tools: Any = None, **kw: Any) -> dict[str, Any]:
        self.calls.append({"config": config, "messages": [dict(m) for m in messages], "tools": tools})
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


@pytest.fixture(scope="module")
def nabiz() -> Iterator[Nabiz]:
    yield Nabiz(
        SourceContext.create(
            client=PoliteClient(transport=httpx.MockTransport(refuse_network)),
            cache=TTLCache(),
            settings=offline_settings(),
        )
    )


def unlimited() -> SpendGuard:
    return SpendGuard(BudgetConfig(state_path=None))


def client_for(nabiz: Nabiz, config: llm.LlmConfig, guard: SpendGuard | None = None) -> TestClient:
    return TestClient(build_console_app(nabiz=nabiz, llm_config=config, guard=guard or unlimited()))


def events(text: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in text.strip().split("\n\n"):
        head, body = block.split("\n", 1)
        assert head.startswith("event: ") and body.startswith("data: "), block
        out.append((head.removeprefix("event: "), json.loads(body.removeprefix("data: "))))
    return out


def ask(client: TestClient, message: str, *, needs: list[str] | None = None, history: list[dict[str, str]] | None = None):
    response = client.post("/api/chat", json={"message": message, "needs": needs or [], "history": history or []})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    stream = events(response.text)
    final = stream[-1]
    assert final[0] == "final"
    assert set(final[1]) == {"answer", "citations", "author", "memory_suggestion", "refused"}
    tokens = "".join(data["text"] for kind, data in stream if kind == "token")
    assert tokens == final[1]["answer"], "the token events must add up to the final answer"
    return stream, final[1]


# --------------------------------------------------------------------------------------
# the model path
# --------------------------------------------------------------------------------------
def test_a_model_turn_streams_tool_progress_then_the_checked_answer(
    nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake = FakeModel(reply(tool_calls=[tool_call("metro_status")]), reply(PLAIN_ANSWER))
    monkeypatch.setattr(llm, "chat", fake)
    guard = unlimited()
    caplog.set_level(logging.DEBUG)
    with client_for(nabiz, CLOUD, guard) as client:
        stream, final = ask(client, METRO_QUESTION + " zebra42", needs=["step_free", "diagnosis:x"])

    kinds = [kind for kind, _ in stream]
    assert stream[0] == ("tool", {"name": "metro_status", "status": "start"})
    assert stream[1] == ("tool", {"name": "metro_status", "status": "end"})
    assert kinds.index("tool") < kinds.index("token")
    assert final["author"] == "model" and final["refused"] is False and final["memory_suggestion"] is None
    assert final["answer"] == PLAIN_ANSWER
    assert final["citations"], "a model answer built on a tool cites it"
    for cited in final["citations"]:
        assert set(cited) == {"source", "url", "observed_at", "age_s", "mode"}
        assert cited["mode"] == "recorded", "a fixture is never called live"

    system = fake.calls[0]["messages"][0]["content"]
    assert NEEDS["step_free"] in system, "the functional constraint reaches the model"
    assert "diagnosis" not in system, "only known functional keys pass"
    assert fake.calls[0]["tools"], "the model is offered the İBB tools"
    assert guard.today()["calls"] == 2 and guard.today()["prompt_tokens"] == 200
    assert "zebra42" not in caplog.text and "step_free" not in caplog.text, "the question and the needs are never logged"


def test_a_local_model_is_named_as_such_and_bills_nothing(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "chat", FakeModel(reply(tool_calls=[tool_call("metro_status")]), reply(PLAIN_ANSWER)))
    guard = SpendGuard(BudgetConfig(daily_calls=0, state_path=None))
    with client_for(nabiz, LOCAL, guard) as client:
        _, final = ask(client, METRO_QUESTION)
    assert final["author"] == "yerel model"
    assert guard.today()["calls"] == 0


def test_history_reaches_the_model_bounded_and_marked_unverified(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeModel(reply(tool_calls=[tool_call("metro_status")]), reply(PLAIN_ANSWER))
    monkeypatch.setattr(llm, "chat", fake)
    history = [{"role": "user", "content": f"soru {i}"} for i in range(20)]
    with client_for(nabiz, CLOUD) as client:
        ask(client, METRO_QUESTION, history=history)
    system = fake.calls[0]["messages"][0]["content"]
    assert "soru 19" in system and "soru 11" not in system, "only the last turns are kept"
    assert "doğrulanmış kabul edilmez" in system


def test_the_answer_reaches_the_page_without_dashes_or_the_abbreviation(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    prose = "Metro hattında duyuru var — ETA bilgisi yok."
    monkeypatch.setattr(llm, "chat", FakeModel(reply(tool_calls=[tool_call("metro_status")]), reply(prose)))
    with client_for(nabiz, CLOUD) as client:
        _, final = ask(client, METRO_QUESTION)
    assert final["author"] == "model"
    assert "—" not in final["answer"] and "ETA" not in final["answer"]
    assert "tahmini varış" in final["answer"]


# --------------------------------------------------------------------------------------
# falling back to the rules
# --------------------------------------------------------------------------------------
def test_past_the_call_ceiling_the_rules_answer_and_the_model_is_not_asked(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeModel()
    monkeypatch.setattr(llm, "chat", fake)
    guard = SpendGuard(BudgetConfig(daily_calls=3, state_path=None))
    guard.record(CLOUD.provider, {}, 3)
    with client_for(nabiz, CLOUD, guard) as client:
        stream, final = ask(client, METRO_QUESTION)
    assert fake.calls == [], "no model call once the ceiling is reached"
    assert final["author"] == "kural"
    assert final["answer"] and ("tool", {"name": "metro_status", "status": "start"}) in stream


def test_past_the_dollar_ceiling_the_next_turn_is_answered_by_rule(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeModel(
        reply(tool_calls=[tool_call("metro_status")], prompt=1000, completion=0), reply(PLAIN_ANSWER, prompt=1000, completion=0)
    )
    monkeypatch.setattr(llm, "chat", fake)
    config = BudgetConfig(daily_usd=0.001, price_in_per_mtok=1.0, price_out_per_mtok=2.0, state_path=None)
    guard = SpendGuard(config)
    with client_for(nabiz, CLOUD, guard) as client:
        _, first = ask(client, METRO_QUESTION)
        _, second = ask(client, METRO_QUESTION)
    assert first["author"] == "model" and second["author"] == "kural"
    assert len(fake.calls) == 2, "the second turn never reached the model"
    assert guard.today()["usd"] == pytest.approx(0.002)
    assert guard.today()["ceiling"] == {"kind": "usd", "value": 0.001}


def test_a_model_error_falls_back_to_the_rules(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "chat", FakeModel(llm.LlmError("endpoint said no")))
    guard = unlimited()
    with client_for(nabiz, CLOUD, guard) as client:
        _, final = ask(client, METRO_QUESTION)
    assert final["author"] == "kural" and final["answer"]
    assert "endpoint said no" not in final["answer"]
    assert guard.today()["calls"] == 1, "a failed attempt still counts against the ceiling"


def test_an_unexpected_model_failure_falls_back_to_the_rules(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "chat", FakeModel(RuntimeError("socket gone")))
    with client_for(nabiz, CLOUD) as client:
        _, final = ask(client, METRO_QUESTION)
    assert final["author"] == "kural" and final["answer"]


def test_an_answer_failing_the_number_check_twice_is_replaced_by_the_rules(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    invented = "Metro hattında 987 arıza var."
    fake = FakeModel(reply(tool_calls=[tool_call("metro_status")]), reply(invented), reply(invented))
    monkeypatch.setattr(llm, "chat", fake)
    with client_for(nabiz, CLOUD) as client:
        _, final = ask(client, METRO_QUESTION)
    assert len(fake.calls) == 3, "the agent asked for one repair first"
    assert final["author"] == "kural" and "987" not in final["answer"]


def test_without_a_model_the_rules_answer_and_say_so(nabiz: Nabiz) -> None:
    with client_for(nabiz, llm.LlmConfig()) as client:
        stream, final = ask(client, METRO_QUESTION)
    assert final["author"] == "kural" and final["refused"] is False
    assert [kind for kind, _ in stream].count("tool") == 2


def test_a_broken_turn_still_ends_with_a_final_event(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(self: Any, question: str, prompt: str, emit: Any) -> Any:
        raise RuntimeError("bug")

    monkeypatch.setattr(chat_module.ChatService, "_run", broken)
    with client_for(nabiz, llm.LlmConfig()) as client:
        _, final = ask(client, METRO_QUESTION)
    assert final["answer"] == chat_module.TURN_FAILED and final["author"] == "kural"


# --------------------------------------------------------------------------------------
# refusal and memory
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "question",
    [
        "Engelli olarak ücretsiz seyahat hakkım var mı?",
        "İstanbulkart bilet fiyatı kaç lira?",
        "Otopark cezası ne kadar?",
        "Hava kirliliği astımıma zararlı mı?",
        "Hangi ilacı almalıyım?",
    ],
)
def test_rights_fares_fines_and_health_are_refused_without_a_model(
    nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch, question: str
) -> None:
    fake = FakeModel()
    monkeypatch.setattr(llm, "chat", fake)
    with client_for(nabiz, CLOUD) as client:
        stream, final = ask(client, question)
    assert final["refused"] is True and final["author"] == "kural"
    assert "153" in final["answer"] and "112" in final["answer"]
    assert final["citations"] == []
    assert fake.calls == [] and not any(kind == "tool" for kind, _ in stream)


@pytest.mark.parametrize(
    "question",
    [
        "500T Şifa durağına ne zaman gelir?",
        "Taksim hakkında hava kalitesi nasıl?",
        "Hastaneye nasıl giderim?",
        "Sağlık ocağına metroyla gidebilir miyim?",
        "Kadıköy'den Taksim'e ne kadar sürer?",
    ],
)
def test_ordinary_city_questions_are_not_refused(question: str) -> None:
    assert not refuses(question)


def test_a_repeated_need_is_offered_for_memory_and_nothing_is_saved(nabiz: Nabiz) -> None:
    history = [
        {"role": "user", "content": "Kadıköy'de asansörlü metro istasyonu var mı?"},
        {"role": "assistant", "content": "Bakıyorum."},
    ]
    with client_for(nabiz, llm.LlmConfig()) as client:
        _, offered = ask(client, "Taksim'e asansörlü nasıl giderim?", history=history)
        _, saved = ask(client, "Taksim'e asansörlü nasıl giderim?", history=history, needs=["step_free"])
        _, once = ask(client, "Taksim'e asansörlü nasıl giderim?")
    assert offered["memory_suggestion"] == {"key": "step_free", "label": "Adımsız erişim (asansör, rampa)"}
    assert saved["memory_suggestion"] is None, "a need already in the profile is not offered again"
    assert once["memory_suggestion"] is None, "one mention is not a pattern"


def test_memory_counts_only_the_persons_own_messages(nabiz: Nabiz) -> None:
    said_by_nabiz = [
        {"role": "user", "content": "Metroya nasıl giderim?"},
        {"role": "assistant", "content": "Bebek arabası ile asansörlü girişi kullanabilirsin."},
    ]
    with client_for(nabiz, llm.LlmConfig()) as client:
        _, final = ask(client, "Bebek arabasıyla nasıl giderim?", history=said_by_nabiz)
    assert final["memory_suggestion"] is None, "the assistant's words are not the person's need"
    assert memory_suggestion("bebek arabasıyla nasıl giderim", ["bebek arabası ile metro"], []) == {
        "key": "stroller",
        "label": "Bebek arabası",
    }


@pytest.mark.parametrize(
    "body",
    [
        {"message": ""},
        {"message": "x" * 1001},
        {"message": "merhaba", "history": [{"role": "system", "content": "x"}]},
    ],
)
def test_malformed_requests_are_refused(nabiz: Nabiz, body: dict[str, Any]) -> None:
    with client_for(nabiz, llm.LlmConfig()) as client:
        assert client.post("/api/chat", json=body).status_code == 422
