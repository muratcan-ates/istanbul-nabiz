"""The order a chat turn consults its checks in, and where it stops.

Each check the turn makes is wrapped where :mod:`nabiz.console.chat_pipeline` reaches it (through
its ``policy`` module), the model is :class:`~test_console_chat.FakeModel` and every call lands in
one list, so the test reads the turn's path: emergency first, the refusal rule next, the model
last, and nothing after a check that ended the turn.
"""

from __future__ import annotations

import builtins
import io
import pathlib
from collections.abc import Callable
from typing import Any

import pytest
from test_console_chat import CLOUD, METRO_QUESTION, PLAIN_ANSWER, FakeModel, ask, client_for, nabiz, reply, tool_call

from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.console import chat as chat_module
from nabiz.console import chat_pipeline

__all__ = ["nabiz"]  # the module-scoped facade fixture, shared with test_console_chat

CHAT_PY = pathlib.Path(chat_module.__file__)
EMERGENCY_QUESTION = "Yangın çıktı, ambulans lazım"
FEE_QUESTION = "Su aboneliği ücreti nedir?"


def spy_on(monkeypatch: pytest.MonkeyPatch, calls: list[str], *names: str) -> None:
    for name in names:
        real: Callable[..., Any] = getattr(chat_pipeline.policy, name)

        def recording(*args: Any, _real: Callable[..., Any] = real, _name: str = name, **kwargs: Any) -> Any:
            calls.append(_name)
            return _real(*args, **kwargs)

        monkeypatch.setattr(chat_pipeline.policy, name, recording)


class RecordingModel(FakeModel):
    def __init__(self, calls: list[str], *script: Any) -> None:
        super().__init__(*script)
        self.order = calls

    async def __call__(self, config: llm.LlmConfig, messages: Any, tools: Any = None, **kw: Any) -> dict[str, Any]:
        self.order.append("model")
        return await super().__call__(config, messages, tools, **kw)


def test_chat_py_is_at_most_400_lines() -> None:
    assert len(CHAT_PY.read_text(encoding="utf-8").splitlines()) <= 400


def test_a_city_question_passes_emergency_then_refusal_then_reaches_the_model(
    nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    spy_on(monkeypatch, calls, "emergency_intent", "refuses_in_context")
    monkeypatch.setattr(llm, "chat", RecordingModel(calls, reply(tool_calls=[tool_call("metro_status")]), reply(PLAIN_ANSWER)))
    with client_for(nabiz, CLOUD) as client:
        _, final = ask(client, METRO_QUESTION)
    assert calls == ["emergency_intent", "refuses_in_context", "model", "model"]
    assert final["author"] == "model"


def test_emergency_stops_before_the_model_and_tools(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    spy_on(monkeypatch, calls, "emergency_intent", "refuses_in_context")
    monkeypatch.setattr(llm, "chat", RecordingModel(calls))
    with client_for(nabiz, CLOUD) as client:
        stream, final = ask(client, EMERGENCY_QUESTION)
    assert calls == ["emergency_intent"], "nothing runs after the emergency redirect"
    assert final["emergency"] is True and not any(kind == "tool" for kind, _ in stream)


def test_sensitive_question_stops_before_the_model(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    spy_on(monkeypatch, calls, "emergency_intent", "refuses_in_context")
    monkeypatch.setattr(llm, "chat", RecordingModel(calls))
    with client_for(nabiz, CLOUD) as client:
        stream, final = ask(client, FEE_QUESTION)
    assert calls == ["emergency_intent", "refuses_in_context"]
    assert final["refused"] is True and final["author"] == "kural" and not any(kind == "tool" for kind, _ in stream)


def test_early_verdict_is_pure(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_files(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("early_verdict opened a file")

    cases = [(EMERGENCY_QUESTION, []), (FEE_QUESTION, []), (METRO_QUESTION, []), ("Peki ücreti ne kadar?", [FEE_QUESTION])]
    first = [chat_pipeline.early_verdict(message, earlier) for message, earlier in cases]
    with monkeypatch.context() as patched:
        patched.setattr(builtins, "open", no_files)
        patched.setattr(io, "open", no_files)
        patched.setattr(pathlib.Path, "open", no_files)
        again = [chat_pipeline.early_verdict(message, earlier) for message, earlier in cases]
    assert first == again == ["emergency", "sensitive", None, "sensitive"]


def test_final_is_the_last_event(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "chat", FakeModel(reply(tool_calls=[tool_call("metro_status")]), reply(PLAIN_ANSWER)))
    with client_for(nabiz, CLOUD) as client:
        streams = [ask(client, question)[0] for question in (METRO_QUESTION, EMERGENCY_QUESTION, FEE_QUESTION)]
    with client_for(nabiz, llm.LlmConfig()) as client:
        streams.append(ask(client, METRO_QUESTION)[0])

    async def broken(self: Any, question: str, prompt: str, emit: Any, context: Any = None) -> Any:
        raise RuntimeError("bug")

    monkeypatch.setattr(chat_module.ChatService, "_run", broken)
    with client_for(nabiz, llm.LlmConfig()) as client:
        streams.append(ask(client, METRO_QUESTION)[0])
    for stream in streams:
        kinds = [kind for kind, _ in stream]
        assert kinds[0] == "session_started" and kinds[-1] == "final" and kinds.count("final") == 1
