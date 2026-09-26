"""Who wrote the answer comes from the rung that wrote it, and a capped cloud drops to the local rung.

``chat._run`` starts on :func:`nabiz.agent.llm.pick_rung` and holds room for a whole turn
(:data:`~nabiz.console.chat.TURN_CALLS`) on it; a cloud rung that has room for one call but not a
turn drops to the free Foundry Local rung, unless ``NABIZ_LADDER_LOCAL_ON_CAP=0``. No test here
reaches a model: ``llm.chat`` or ``llm._chat_rung`` is replaced, and ``conftest`` refuses any
outbound connection.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from test_console_chat import CLOUD, LOCAL, METRO_QUESTION, PLAIN_ANSWER, FakeModel, ask, client_for, nabiz, reply, tool_call
from test_console_wiring import answer, evidence, fault

from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.console import arena_seats, chat
from nabiz.console.arena_seats import ModelSeats
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.chat import TURN_CALLS

__all__ = ["nabiz"]  # the module-scoped facade fixture, shared with test_console_chat

LADDER = dataclasses.replace(CLOUD, fallback=LOCAL)


def model_turn() -> FakeModel:
    return FakeModel(reply(tool_calls=[tool_call("metro_status")]), reply(PLAIN_ANSWER))


def guard_with(daily_calls: int) -> SpendGuard:
    return SpendGuard(BudgetConfig(daily_calls=daily_calls, state_path=None))


def test_cloud_answer_is_labelled_model(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = model_turn()
    monkeypatch.setattr(llm, "chat", fake)
    with client_for(nabiz, LADDER) as client:
        _, final = ask(client, METRO_QUESTION)
    assert final["author"] == "model"
    assert fake.calls and all(call["config"].provider == CLOUD.provider for call in fake.calls)


def test_cloud_failure_answered_by_the_local_rung_is_labelled_local(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    local_script = [reply(tool_calls=[tool_call("metro_status")]), reply(PLAIN_ANSWER)]
    asked: list[str] = []

    async def rung_call(config: llm.LlmConfig, messages: Any, tools: Any, **kw: Any) -> dict[str, Any]:
        asked.append(config.provider)
        if config.provider != "foundry_local":
            raise llm.LlmError("cloud endpoint said no")
        return local_script.pop(0)

    monkeypatch.setattr(llm, "_chat_rung", rung_call)
    with client_for(nabiz, LADDER) as client:
        _, final = ask(client, METRO_QUESTION)
    assert final["author"] == "yerel model"
    assert asked[:2] == [CLOUD.provider, "foundry_local"], "the cloud is tried first, the ladder moves the call down"


def test_cloud_ceiling_reached_tries_the_local_rung(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = model_turn()
    monkeypatch.setattr(llm, "chat", fake)
    guard = guard_with(0)
    with client_for(nabiz, LADDER, guard) as client:
        _, final = ask(client, METRO_QUESTION)
    assert final["author"] == "yerel model"
    assert fake.calls and not [call for call in fake.calls if call["config"].provider == CLOUD.provider]
    assert guard.today()["calls"] == 0


def test_room_for_less_than_a_turn_tries_the_local_rung(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = model_turn()
    monkeypatch.setattr(llm, "chat", fake)
    guard = guard_with(TURN_CALLS - 1)
    assert guard.allows(CLOUD.provider) and not guard.reserve(CLOUD.provider, TURN_CALLS)
    with client_for(nabiz, LADDER, guard) as client:
        _, final = ask(client, METRO_QUESTION)
    assert final["author"] == "yerel model"
    assert fake.calls and not [call for call in fake.calls if call["config"].provider == CLOUD.provider]
    assert guard.today()["calls"] == 0


def test_local_rung_is_called_with_its_own_config(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = model_turn()
    monkeypatch.setattr(llm, "chat", fake)
    guard = guard_with(0)
    recorded: list[str] = []
    real_record = guard.record

    def spy(provider: str, usage: Any, calls: int) -> None:
        recorded.append(provider)
        real_record(provider, usage, calls)

    monkeypatch.setattr(guard, "record", spy)
    with client_for(nabiz, LADDER, guard) as client:
        ask(client, METRO_QUESTION)
    assert fake.calls and all(call["config"].provider == "foundry_local" for call in fake.calls)
    assert recorded == ["foundry_local"], "the local turn is never billed to the cloud"


@pytest.mark.parametrize("daily_calls", [0, TURN_CALLS - 1])
def test_local_on_cap_can_be_switched_off(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch, daily_calls: int) -> None:
    fake = FakeModel()
    monkeypatch.setattr(llm, "chat", fake)
    monkeypatch.setenv(llm.LOCAL_ON_CAP_ENV, "0")
    with client_for(nabiz, LADDER, guard_with(daily_calls)) as client:
        _, final = ask(client, METRO_QUESTION)
    assert final["author"] == "kural" and fake.calls == []


def test_no_local_rung_and_ceiling_reached_answers_by_rule(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeModel()
    monkeypatch.setattr(llm, "chat", fake)
    with client_for(nabiz, CLOUD, guard_with(0)) as client:
        _, final = ask(client, METRO_QUESTION)
    assert final["author"] == "kural" and fake.calls == []


def test_pick_rung_keeps_the_first_rung_and_its_fallbacks_when_allowed() -> None:
    assert llm.pick_rung(LADDER, lambda provider: True) is LADDER
    assert llm.pick_rung(LADDER, lambda provider: provider == "foundry_local") is LOCAL
    assert llm.pick_rung(LADDER, lambda provider: provider == "foundry_local", env={llm.LOCAL_ON_CAP_ENV: "false"}) is None
    assert llm.pick_rung(llm.LlmConfig(), lambda provider: True) is None


@pytest.mark.parametrize(("value", "on"), [(None, True), ("", True), ("1", True), ("0", False), ("false", False), ("No", False)])
def test_local_on_cap_is_on_unless_switched_off(value: str | None, on: bool) -> None:
    env = {} if value is None else {llm.LOCAL_ON_CAP_ENV: value}
    assert llm.local_on_cap(env) is on


def test_author_for_is_an_alias_of_author_of() -> None:
    assert chat.author_for(LOCAL) == llm.author_of("foundry_local") == "yerel model"
    assert chat.author_for(CLOUD) == llm.author_of(CLOUD.provider) == "model"


@pytest.mark.parametrize(
    ("providers", "author"),
    [
        (["foundry_local"] * 3, "yerel model"),
        (["openai_compatible"] * 3, "model"),
        (["foundry_local", "openai_compatible", "foundry_local"], "model"),
    ],
)
def test_arena_seats_are_labelled_by_the_rung_that_wrote_them(
    monkeypatch: pytest.MonkeyPatch, providers: list[str], author: str
) -> None:
    written = iter(providers)

    async def fake_chat(config: llm.LlmConfig, messages: Any, **_: Any) -> dict[str, Any]:
        return {"content": answer(citations=(1,)), "usage": {}, "provider": next(written)}

    monkeypatch.setattr(arena_seats.llm, "chat", fake_chat)
    seats = ModelSeats(LADDER, SpendGuard(BudgetConfig(state_path=None)))
    assert seats.author == "model", "before any call the label is the configuration's"
    assert len(seats.opinions(fault(), evidence())) == 3
    assert seats.author == author
