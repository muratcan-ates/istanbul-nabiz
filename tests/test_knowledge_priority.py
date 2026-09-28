"""KARAR 2: the E78 window stays as it is unless the switch is on (nabiz.console.knowledge_priority)."""

from __future__ import annotations

import pytest

from nabiz.agent.templates import OUT_OF_SCOPE
from nabiz.console.knowledge_priority import (
    KNOWLEDGE_MODEL_FIRST_ENV,
    asks_how_a_service_works,
    knowledge_before_tools,
    knowledge_window,
    model_first,
)

ON = {KNOWLEDGE_MODEL_FIRST_ENV: "1"}
SERVICE = ("Engelli kartına nasıl başvururum?", "65 yaş kartı için hangi belgeler gerekli?", "How do I apply for a student card?")
LIVE = ("M4 çalışıyor mu?", "Kadıköy'de otopark doluluk nasıl?", "500T ne zaman gelir?", "Is it running today?")


def test_the_default_window_is_todays_out_of_scope_answer() -> None:
    assert knowledge_window("kural", OUT_OF_SCOPE["tr"], OUT_OF_SCOPE["tr"])
    assert not knowledge_window("model", OUT_OF_SCOPE["tr"], OUT_OF_SCOPE["tr"])
    assert not knowledge_window("kural", "M4 için bildirilmiş bir arıza yok.", OUT_OF_SCOPE["tr"])


@pytest.mark.parametrize("question", SERVICE + LIVE)
def test_off_by_default_nothing_goes_first(question: str) -> None:
    assert not model_first({}) and not knowledge_before_tools(question, {})
    assert not knowledge_before_tools(question, {KNOWLEDGE_MODEL_FIRST_ENV: "0"})


@pytest.mark.parametrize("question", SERVICE)
def test_with_the_switch_a_service_question_goes_to_the_index_first(question: str) -> None:
    assert asks_how_a_service_works(question) and knowledge_before_tools(question, ON)


@pytest.mark.parametrize("question", LIVE)
def test_with_the_switch_a_live_question_still_goes_to_its_tool(question: str) -> None:
    assert not knowledge_before_tools(question, ON)
