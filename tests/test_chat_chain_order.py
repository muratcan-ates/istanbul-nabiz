"""The order a chat turn consults its checks in, and where it stops.

Each check the turn makes is wrapped where :mod:`nabiz.console.chat_pipeline` reaches it (through
its ``policy`` module), the model is :class:`~test_console_chat.FakeModel` and every call lands in
one list, so the test reads the turn's path: emergency first, the refusal rule next, the model
last, and nothing after a check that ended the turn.
"""

from __future__ import annotations

import builtins
import io
import json
import pathlib
import shutil
import subprocess
from collections.abc import Callable
from typing import Any

import pytest
from conftest import REPO_ROOT
from test_console_chat import (
    CLOUD,
    FEE_QUOTE,
    METRO_QUESTION,
    PLAIN_ANSWER,
    SERVICE_QUOTE,
    FakeModel,
    ask,
    client_for,
    nabiz,
    reply,
    tool_call,
    with_index,
)

from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.console import chat as chat_module
from nabiz.console import chat_pipeline

__all__ = ["nabiz"]  # the module-scoped facade fixture, shared with test_console_chat

CHAT_PY = pathlib.Path(chat_module.__file__)
STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
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


# --------------------------------------------------------------------------------------
# the trace in final.how (PR2)
# --------------------------------------------------------------------------------------
def chain_of(final: dict[str, Any]) -> list[tuple[str, str]]:
    return [(step["name"], step["status"]) for step in final["how"]["chain"]]


def broken_run(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(self: Any, question: str, prompt: str, emit: Any, context: Any = None) -> Any:
        raise RuntimeError("bug")

    monkeypatch.setattr(chat_module.ChatService, "_run", broken)


def test_how_carries_chain_and_checks(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setattr(llm, "chat", FakeModel(reply(tool_calls=[tool_call("metro_status")]), reply(PLAIN_ANSWER)))
    finals: dict[str, dict[str, Any]] = {}
    with client_for(nabiz, CLOUD) as client:
        finals["model"] = ask(client, METRO_QUESTION)[1]
        finals["emergency"] = ask(client, EMERGENCY_QUESTION)[1]
        finals["refusal"] = ask(client, FEE_QUESTION)[1]
    with client_for(nabiz, llm.LlmConfig()) as client:
        finals["rule"] = ask(client, METRO_QUESTION)[1]
    with_index(monkeypatch, tmp_path, SERVICE_QUOTE, FEE_QUOTE)
    with client_for(nabiz, llm.LlmConfig()) as client:
        finals["knowledge"] = ask(client, FEE_QUESTION)[1]
    broken_run(monkeypatch)
    with client_for(nabiz, llm.LlmConfig()) as client:
        finals["error"] = ask(client, METRO_QUESTION)[1]

    for kind, final in finals.items():
        assert isinstance(final["how"]["chain"], list) and final["how"]["chain"], kind
        assert set(final["how"]["checks"]) == {"girdi", "hassas", "sayi", "kanit", "cikti"}, kind
        assert final["how"]["checks"]["girdi"] is None, "E16 is not wired in B01"
        assert {"tools", "tool_calls", "elapsed_s", "rule_id", "uncertainty", "latency_ms"} <= set(final["how"]), kind
    assert chain_of(finals["model"]) == [("acil", "gecti"), ("hassas", "gecti"), ("arac_bilgi", "cevapladi"), ("cikti", "gecti")]
    assert finals["model"]["how"]["checks"] == {"girdi": None, "hassas": True, "sayi": True, "kanit": None, "cikti": True}
    assert chain_of(finals["emergency"]) == [("acil", "cevapladi")]
    assert chain_of(finals["refusal"]) == [("acil", "gecti"), ("hassas", "cevapladi")]
    assert finals["refusal"]["how"]["checks"]["hassas"] is False
    assert chain_of(finals["rule"]) == [("acil", "gecti"), ("hassas", "gecti"), ("arac_bilgi", "cevapladi")]
    assert finals["rule"]["how"]["checks"]["cikti"] is None, "the price filter reads model answers only"
    assert finals["knowledge"]["mode"] == "quote_only" and finals["knowledge"]["how"]["checks"]["kanit"] is True
    assert chain_of(finals["error"])[-1] == ("arac_bilgi", "hata")


def test_a_priced_model_answer_is_stopped_at_the_output_check(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    priced = "Metro biniş ücreti ₺ ile ödenir; M7 aktarmalı."  # no number, so the numeric check passes it
    monkeypatch.setattr(llm, "chat", FakeModel(reply(tool_calls=[tool_call("metro_status")]), reply(priced)))
    with client_for(nabiz, CLOUD) as client:
        _, final = ask(client, METRO_QUESTION)
    assert final["refused"] is True
    assert chain_of(final)[-2:] == [("arac_bilgi", "gecti"), ("cikti", "cevapladi")]
    assert final["how"]["checks"]["cikti"] is False


def test_how_chain_has_no_raw_text_or_personal_data(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    message = "zebra42 10000000146 Metro hattında arıza var mı?"
    monkeypatch.setattr(llm, "chat", FakeModel(reply(tool_calls=[tool_call("metro_status")]), reply(PLAIN_ANSWER)))
    finals = []
    with client_for(nabiz, CLOUD) as client:
        finals.append(ask(client, message, history=[{"role": "user", "content": "zebra42 ücreti nedir"}])[1])
        finals.append(ask(client, f"zebra42 10000000146 {FEE_QUESTION}")[1])
        finals.append(ask(client, f"zebra42 10000000146 {EMERGENCY_QUESTION}")[1])
    for final in finals:
        trace = json.dumps({"chain": final["how"]["chain"], "checks": final["how"]["checks"]}, ensure_ascii=False)
        assert "zebra42" not in trace and "10000000146" not in trace
        assert "Metro" not in trace and "http" not in trace


def test_chain_lists_only_stages_that_ran(nabiz: Nabiz) -> None:
    with client_for(nabiz, llm.LlmConfig()) as client:
        _, emergency = ask(client, EMERGENCY_QUESTION)
        _, refused = ask(client, FEE_QUESTION)
    assert "arac_bilgi" not in {name for name, _ in chain_of(emergency)}
    assert "hassas" not in {name for name, _ in chain_of(emergency)}, "the emergency redirect ends the turn first"
    assert "arac_bilgi" not in {name for name, _ in chain_of(refused)}
    for final in (emergency, refused):
        assert {name for name, _ in chain_of(final)} <= {"acil", "hassas", "arac_bilgi", "cikti"}, "B01b's stages are not faked"


def test_no_separate_trace_event(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "chat", FakeModel(reply(tool_calls=[tool_call("metro_status")]), reply(PLAIN_ANSWER)))
    with client_for(nabiz, CLOUD) as client:
        stream, _ = ask(client, METRO_QUESTION)
    assert {kind for kind, _ in stream} <= {"session_started", "tool", "token", "final"}


def test_trace_marks_a_stage_that_raised() -> None:
    trace = chat_pipeline.TurnTrace()
    with pytest.raises(RuntimeError), trace.step("arac_bilgi"):
        raise RuntimeError("bug")
    assert trace.how_fields()["chain"] == [{"name": "arac_bilgi", "status": "hata"}]
    with pytest.raises(ValueError), trace.step("uydurma"):
        pass


def node_json(tmp_path: Any, modules: dict[str, str], body: str) -> Any:
    # Copied from tests/test_static_a11y.py, not imported: each test file owns its harness.
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    imports = "\n".join(f"import * as {name} from {json.dumps((STATIC / path).as_uri())};" for name, path in modules.items())
    harness = tmp_path / "how_harness.mjs"
    harness.write_text(f"{imports}\n{body}\n", encoding="utf-8")
    result = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_how_panel_renders_chain_rows(tmp_path: Any) -> None:
    how = {
        "tools": [], "rule_id": None, "uncertainty": [], "latency_ms": 12,
        "chain": [{"name": "acil", "status": "gecti"}, {"name": "hassas", "status": "gecti"},
                  {"name": "arac_bilgi", "status": "cevapladi"}, {"name": "<yeni>", "status": "hata"}],
        "checks": {"girdi": None, "hassas": True, "sayi": True, "kanit": None, "cikti": False},
    }  # fmt: skip
    html, bare = node_json(
        tmp_path,
        {"provenance": "js/provenance.js"},
        f"const how = {json.dumps(how)};"
        "const bare = {tools: [], rule_id: null, uncertainty: [], latency_ms: 1};"
        "console.log(JSON.stringify([provenance.howPanel(how, 't1'), provenance.howPanel(bare, 't2')]));",
    )
    assert "Adımlar: Acil geçti · Hassas geçti · Araç/bilgi cevapladı · &lt;yeni&gt; hata verdi" in html
    checks = "Girdi uygulanmadı · Hassas konu doğrulandı · Sayılar doğrulandı · Kanıt uygulanmadı · Çıktı takıldı"
    assert f"Kontroller: {checks}" in html
    assert "Sistem gecikmesi: 12 ms" in html and "Bu nasıl bulundu?" in html
    assert "Adımlar" not in bare and "Kontroller" not in bare, "a card without a trace keeps its old rows"
