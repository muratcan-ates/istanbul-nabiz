"""A metro question about how the service runs goes to the service pages, not to the live announcements.

26 Sep: "Gece metrosu hangi günler çalışıyor?" matched the word "metro", went to ``metro_status`` and
showed an unrelated M7 notice. The rule path now sends service questions out of scope, where the chat
looks them up in the service-page index; disruption questions keep ``metro_status``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from conftest import offline_settings, refuse_network
from test_console_chat import ask, client_for, with_index

from ibb_mcp.cache import TTLCache
from ibb_mcp.http import PoliteClient
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.text import normalize_tr
from ibb_mcp.tools import Nabiz
from nabiz.agent import LlmConfig, NabizAgent
from nabiz.agent.metro_route import asks_about_service, metro_route
from nabiz.agent.templates import OUT_OF_SCOPE

SERVICE_QUESTIONS = (
    "Gece metrosu hangi günler çalışıyor?",
    "Gece metrosu seferleri saat kaçta başlıyor?",
    "M4 24 saat açık mı?",
    "Metro hafta sonu çalışıyor mu?",
    "Metroya evcil hayvanla binebilir miyim?",
    "Metro İstanbul'a şikâyet nasıl iletilir?",
    "Metro istasyonlarında erişilebilirlik hizmetleri neler?",
    "M2'nin son seferi kaçta?",
)
DISRUPTION_QUESTIONS = (
    "M2 metro hattında arıza var mı?", "Metro çalışıyor mu?", "M4'te arıza var mı?", "Marmaray'da aksaklık var mı?",
)  # fmt: skip


@pytest.fixture(scope="module")
def nabiz() -> Iterator[Nabiz]:
    client = PoliteClient(transport=httpx.MockTransport(refuse_network))
    yield Nabiz(SourceContext.create(client=client, cache=TTLCache(), settings=offline_settings()))


@pytest.fixture
def agent(ctx) -> NabizAgent:
    return NabizAgent(Nabiz(ctx), config=LlmConfig(), system_prompt="test prompt")


@pytest.mark.parametrize("question", SERVICE_QUESTIONS)
def test_a_service_question_leaves_the_announcement_tool(agent: NabizAgent, question: str) -> None:
    assert asks_about_service(normalize_tr(question))
    assert agent.route(question) == ("", {"reason": "scope"})


@pytest.mark.parametrize("question", DISRUPTION_QUESTIONS)
def test_a_disruption_question_keeps_metro_status(agent: NabizAgent, question: str) -> None:
    assert agent.route(question)[0] == "metro_status"


def test_the_line_code_still_reaches_metro_status() -> None:
    line = re.search(r"(M\d)", "M4 arıza")
    assert metro_route("m4 ariza", line) == ("metro_status", {"line": "M4"})
    assert metro_route("gece metrosu m4", line) == ("", {"reason": "scope"})


async def test_the_rule_path_answers_a_service_question_out_of_scope(agent: NabizAgent) -> None:
    answer = await agent.ask("Gece metrosu hangi günler çalışıyor?")
    assert answer.tool_names == [] and answer.text == OUT_OF_SCOPE[answer.lang]


def test_the_chat_looks_a_night_metro_question_up_in_the_service_pages(
    nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    quote = "Gece Metrosu, Cuma'yı Cumartesi'ye ve Cumartesi'yi Pazar'a bağlayan gecelerde gerçekleştirilecektir."
    with_index(monkeypatch, tmp_path, quote)
    with client_for(nabiz, LlmConfig()) as client:
        stream, final = ask(client, "Gece metrosu hangi günler çalışıyor?")
    tools = [data["name"] for kind, data in stream if kind == "tool" and data["status"] == "start"]
    assert "metro_status" not in tools and tools == ["ibb_services_search"]
    assert final["how"]["rule_id"] == "knowledge"
