"""``POST /api/chat``: one agent turn, streamed to the page as server-sent events.

    event: tool   data {"name", "status": "start"|"end"}      live, as the agent calls İBB tools
    event: token  data {"text"}                                the answer, in order
    event: final  data {"answer", "citations", "author", "memory_suggestion", "refused"}

**The answer streams after it is checked.** :class:`~nabiz.agent.NabizAgent` verifies every
number in the model's prose against the tool results before it returns (and asks the model
once to repair a failure). Streaming the model's raw tokens would put an unverified number on
the screen first, which is the one thing the agent exists to prevent. So the page sees tool
progress live, and the verified text as a run of ``token`` events.

**Who wrote the answer is always said** (``author``): "model", "yerel model" (Foundry Local)
or "kural" (the agent's keyword-routed templates). The rule path answers when no model is
configured, when today's spend ceiling is reached (:mod:`nabiz.console.budget`), when the
model call fails, and when a model answer still fails the numeric check after its repair:
a sentence built from the tool payload is better than a number nobody can back.

Nothing here logs the question, the history or the needs.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import re
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from ibb_mcp.models import utcnow
from nabiz.agent import llm
from nabiz.agent.agent import PROMPT_PATH, AgentAnswer, NabizAgent
from nabiz.agent.schemas import TOOL_DESCRIPTIONS
from nabiz.console.budget import SpendGuard
from nabiz.console.cards import display_text, mode_for
from nabiz.console.policy import REFUSAL_TEXT, constraint_block, functional_needs, memory_suggestion, refuses

log = logging.getLogger("nabiz.console.chat")

#: How much of the conversation the page may send back, and how much of it reaches the model.
HISTORY_TURNS_KEPT = 8
HISTORY_CHARS_KEPT = 600
_WORDS_PER_TOKEN_EVENT = 3
TURN_FAILED = "Şu anda bu soruya cevap veremiyorum. Biraz sonra yeniden dene; acil bir durumdaysan 112'yi ara."

Emit = Callable[[str, dict[str, Any]], None]


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    needs: list[str] = Field(default_factory=list, max_length=16)
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def text_pieces(text: str) -> list[str]:
    """The answer cut into small runs of words, whitespace kept, so joining them gives it back."""
    words = re.findall(r"\s*\S+", text)
    return ["".join(words[i : i + _WORDS_PER_TOKEN_EVENT]) for i in range(0, len(words), _WORDS_PER_TOKEN_EVENT)]


class ToolEvents:
    """A view of the shared ``Nabiz`` facade that reports each tool call as it starts and ends.

    Everything else (``places``, ``settings``) passes through. ``aclose`` does nothing: the app
    owns the facade, and one turn must never close it for every other visitor.
    """

    def __init__(self, nabiz: Any, emit: Emit) -> None:
        self._nabiz = nabiz
        self._emit = emit

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._nabiz, name)
        if name not in TOOL_DESCRIPTIONS or not callable(attr):
            return attr

        async def call(**kwargs: Any) -> Any:
            self._emit("tool", {"name": name, "status": "start"})
            try:
                return await attr(**kwargs)
            finally:
                self._emit("tool", {"name": name, "status": "end"})

        return call

    async def aclose(self) -> None:
        return None


def _age_s(as_of: Any) -> int | None:
    try:
        moment = dt.datetime.fromisoformat(str(as_of))
    except ValueError:
        return None
    moment = moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)
    return int(max(0.0, (utcnow() - moment).total_seconds()))


def citations(answer: AgentAnswer, *, offline: bool) -> list[dict[str, Any]]:
    """The agent's citations as the contract's Provenance objects."""
    return [
        {
            "source": item.get("source"),
            "url": item.get("source_url") or None,
            "observed_at": item.get("as_of"),
            "age_s": _age_s(item.get("as_of")),
            "mode": mode_for(offline),
        }
        for item in answer.citations
    ]


def system_prompt(needs: Sequence[str], history: Sequence[ChatTurn], base: str) -> str:
    """The agent's prompt, plus the person's functional constraints and a bounded recent history."""
    parts = [base]
    if block := constraint_block(needs):
        parts.append(block)
    recent = list(history)[-HISTORY_TURNS_KEPT:]
    if recent:
        lines = [
            "## Önceki konuşma (yalnız bağlam için)",
            "Buradaki sayılar doğrulanmış kabul edilmez; bir sayıyı yeniden söyleyeceksen aracı yeniden çağır.",
        ]
        speaker = {"user": "Kullanıcı", "assistant": "Nabız"}
        lines += [f"{speaker[turn.role]}: {turn.content[:HISTORY_CHARS_KEPT]}" for turn in recent]
        parts.append("\n".join(lines))
    parts.append("## Yazım\n'ETA' kısaltmasını kullanma; 'tahmini varış' de.")
    return "\n\n".join(parts)


def author_for(config: llm.LlmConfig) -> str:
    return "yerel model" if config.provider == "foundry_local" else "model"


class ChatService:
    """Runs chat turns over one shared facade, one model configuration and one spend guard."""

    def __init__(self, nabiz: Any, config: llm.LlmConfig, guard: SpendGuard, *, offline: bool) -> None:
        self.nabiz = nabiz
        self.config = config
        self.guard = guard
        self.offline = offline
        self._base_prompt: str | None = None

    @property
    def base_prompt(self) -> str:
        if self._base_prompt is None:
            self._base_prompt = PROMPT_PATH.read_text(encoding="utf-8")
        return self._base_prompt

    async def events(self, request: ChatRequest) -> AsyncIterator[str]:
        """The whole turn as SSE text: tool events while it runs, then the answer and the final event."""
        earlier = [turn.content for turn in request.history if turn.role == "user"]
        needs = functional_needs(request.needs)
        suggestion = memory_suggestion(request.message, earlier, needs)
        if refuses(request.message):
            for piece in text_pieces(REFUSAL_TEXT):
                yield sse("token", {"text": piece})
            yield sse("final", self._final(REFUSAL_TEXT, [], "kural", suggestion, refused=True))
            return

        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        prompt = system_prompt(needs, request.history, self.base_prompt)
        task = asyncio.create_task(self._run(request.message, prompt, lambda kind, data: queue.put_nowait((kind, data))))
        task.add_done_callback(lambda done: queue.put_nowait(("done", None)))
        try:
            while True:
                kind, data = await queue.get()
                if kind == "done":
                    break
                yield sse(kind, data)
        finally:
            if not task.done():
                task.cancel()
        if task.exception() is not None:
            log.error("chat turn failed: %s", type(task.exception()).__name__)
            yield sse("token", {"text": TURN_FAILED})
            yield sse("final", self._final(TURN_FAILED, [], "kural", suggestion, refused=False))
            return
        answer, author = task.result()
        text = display_text(answer.text)
        for piece in text_pieces(text):
            yield sse("token", {"text": piece})
        yield sse("final", self._final(text, citations(answer, offline=self.offline), author, suggestion, refused=False))

    @staticmethod
    def _final(answer: str, cited: list[dict[str, Any]], author: str, suggestion: Any, *, refused: bool) -> dict[str, Any]:
        return {"answer": answer, "citations": cited, "author": author, "memory_suggestion": suggestion, "refused": refused}

    async def _run(self, question: str, prompt: str, emit: Emit) -> tuple[AgentAnswer, str]:
        """The model when it is configured, allowed today and trustworthy on this answer; else the rules."""
        tools = ToolEvents(self.nabiz, emit)
        if llm.available(self.config) and self.guard.allows(self.config.provider):
            answer = await self._ask_model(tools, question, prompt)
            if answer is not None and answer.mode == "llm" and (answer.faithfulness is None or answer.faithfulness.passed):
                return answer, author_for(self.config)
            if answer is not None and answer.mode != "llm":
                # The agent already fell back to its rules after a model error.
                return answer, "kural"
        rules = NabizAgent(tools, config=llm.LlmConfig(), system_prompt=prompt)
        return await rules.ask(question), "kural"

    async def _ask_model(self, tools: ToolEvents, question: str, prompt: str) -> AgentAnswer | None:
        answer: AgentAnswer | None = None
        try:
            answer = await NabizAgent(tools, config=self.config, system_prompt=prompt).ask(question)
        except Exception as exc:  # noqa: BLE001 - any failure falls back to the rule path
            log.warning("model turn failed, answering by rule: %s", type(exc).__name__)
        finally:
            used = answer is not None and answer.mode == "llm"
            self.guard.record(self.config.provider, answer.usage if used else {}, answer.steps if used else 1)
        return answer
