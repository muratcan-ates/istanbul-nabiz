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

**The spend ceiling holds under load.** A model turn reserves room for the most calls it can
make (:data:`TURN_CALLS`) before it starts, at most :data:`MODEL_TURNS_AT_ONCE` model turns
run at a time, and what a turn spent is recorded even when the model failed half-way: the
calls made (``usage["model_calls"]``) and their tokens, or :data:`TURN_CALLS` when nothing
could be counted.

**What a visitor sends stays a visitor's words.** Only the person's own earlier questions
are kept, never an "assistant" turn the page sends back (the page could forge one), and
never a question the refusal rule caught; they reach the model as one ``user`` message
before the question, not inside the system prompt. An İBB failure reaches the model and the
page as one Turkish sentence; its body (an HTML page, a SOAP fault, a URL) stays in the
server log as its kind and status.

Nothing here logs the question, the history or the needs.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from ibb_mcp.http import RateLimitExceeded, UpstreamUnavailable
from ibb_mcp.models import utcnow
from ibb_mcp.text import normalize_tr
from nabiz.agent import llm
from nabiz.agent.agent import PROMPT_PATH, AgentAnswer, NabizAgent
from nabiz.agent.schemas import TOOL_DESCRIPTIONS
from nabiz.console.budget import SpendGuard
from nabiz.console.cards import Mode, display_text, mode_for
from nabiz.console.policy import (
    EMERGENCY_TERMS,
    REFUSAL_TEXT,
    constraint_block,
    functional_needs,
    memory_suggestion,
    names_a_price,
    refuses,
    refuses_in_context,
)

log = logging.getLogger("nabiz.console.chat")

#: How much of the conversation the page may send back, and how much of it reaches the model.
HISTORY_TURNS_KEPT = 8
HISTORY_CHARS_KEPT = 600
_WORDS_PER_TOKEN_EVENT = 3
TURN_FAILED = "Şu anda bu soruya cevap veremiyorum. Biraz sonra yeniden dene; acil bir durumdaysan 112'yi ara."
#: The most model calls one turn can make: the agent's four steps, one forced answer, one repair.
TURN_CALLS = 6
#: Model turns running at once; the rest wait their turn. A design parameter.
MODEL_TURNS_AT_ONCE = 3
#: What an İBB failure becomes, for the model and for the page.
UPSTREAM_DOWN = "doğrulanamadı"
#: Sources that are a timetable or this repository's own reference files, never a live reading.
SCHEDULE_SOURCES = frozenset({"iett_schedule", "gtfs"})
REFERENCE_SOURCES = frozenset({"gazetteer", "metro_stations", "places"})
#: A model answer may name a price only when the person asked about car parks (İSPARK's tariff).
_TARIFF_TOOLS = frozenset({"ispark_find_parking", "ispark_park_detail", "ispark_typical_occupancy"})

Emit = Callable[[str, dict[str, Any]], None]


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    needs: list[str] = Field(default_factory=list, max_length=16)
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)


@dataclass(frozen=True)
class FinalFields:
    refused: bool
    how: dict[str, Any]
    mode: str
    steps: list[str] | None = None
    emergency: bool = False


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
            except UpstreamUnavailable as exc:
                # Its message can carry İBB's response body or a URL: kind and status to the log,
                # one fixed word to the model and the page.
                log.warning("tool %s: %s (source %s, status %s)", name, type(exc).__name__, exc.source, exc.status)
                kind = RateLimitExceeded if isinstance(exc, RateLimitExceeded) else UpstreamUnavailable
                raise kind(UPSTREAM_DOWN, source=exc.source, status=exc.status) from None
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


def source_mode(source: Any, *, offline: bool) -> Mode:
    """A citation's mode: a timetable is "schedule", a reference file "recorded", a reading live or recorded."""
    if source in SCHEDULE_SOURCES:
        return "schedule"
    if source in REFERENCE_SOURCES or str(source).startswith("local:"):
        return "recorded"
    return mode_for(offline)


def citations(answer: AgentAnswer, *, offline: bool) -> list[dict[str, Any]]:
    """The agent's citations as the contract's Provenance objects."""
    result = []
    for item in answer.citations:
        if any(key in item for key in ("fetched_at", "source_updated_at", "institution", "quote")):
            result.append(dict(item))
            continue
        result.append({
            "source": item.get("source"),
            "url": item.get("source_url") or None,
            "observed_at": item.get("as_of"),
            "age_s": _age_s(item.get("as_of")),
            "mode": source_mode(item.get("source"), offline=offline),
        })
    return result


def emergency_intent(message: str) -> bool:
    """Recognize the small, explicit emergency vocabulary before any agent or tool is called."""
    words = normalize_tr(message).split()
    return any(word.startswith(term) for term in EMERGENCY_TERMS["acil"] for word in words)


def _how(answer: AgentAnswer | None, started: float, *, rule_id: str | None) -> dict[str, Any]:
    tools = []
    for call in answer.tool_calls if answer is not None else []:
        provenance = (call.payload or {}).get("provenance") or {}
        tools.append({
            "name": call.name,
            "ok": call.ok,
            "duration_ms": call.duration_ms,
            "source": provenance.get("source"),
            "source_url": provenance.get("source_url") or provenance.get("url"),
            "observed_at": provenance.get("observed_at") or provenance.get("reported_at"),
        })
    elapsed_s = max(0.0, time.perf_counter() - started)
    return {
        "tools": tools,
        "tool_calls": len(tools),
        "elapsed_s": round(elapsed_s, 3),
        "rule_id": rule_id,
        "uncertainty": [],
        "latency_ms": round(elapsed_s * 1000, 1),
    }


def _empty_how(started: float, *, rule_id: str | None) -> dict[str, Any]:
    return _how(None, started, rule_id=rule_id)


def earlier_questions(history: Sequence[ChatTurn]) -> list[str]:
    """The person's own earlier questions: never an assistant turn, never a refused question."""
    asked = [turn.content[:HISTORY_CHARS_KEPT] for turn in history if turn.role == "user"]
    return [text for text in asked if not refuses(text)][-HISTORY_TURNS_KEPT:]


def context_messages(earlier: Sequence[str]) -> list[dict[str, str]]:
    """Earlier questions as one ``user`` message before the question: context, in the person's voice."""
    if not earlier:
        return []
    lines = ["Önceki sorularım (yalnız bağlam için; buradaki sayılar doğrulanmış kabul edilmez):"]
    return [{"role": "user", "content": "\n".join([*lines, *(f"- {text}" for text in earlier)])}]


def system_prompt(needs: Sequence[str], base: str) -> str:
    """The agent's prompt, plus the person's functional constraints. Nothing a visitor typed."""
    parts = [base]
    if block := constraint_block(needs):
        parts.append(block)
    parts.append("## Yazım\n'ETA' kısaltmasını kullanma; 'tahmini varış' de. Varış süresi tek tam dakika: '7 dk'.")
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
        self._model_turns = asyncio.Semaphore(MODEL_TURNS_AT_ONCE)

    @property
    def base_prompt(self) -> str:
        if self._base_prompt is None:
            self._base_prompt = PROMPT_PATH.read_text(encoding="utf-8")
        return self._base_prompt

    async def events(self, request: ChatRequest) -> AsyncIterator[str]:
        """The whole turn as SSE text: tool events while it runs, then the answer and the final event."""
        started = time.perf_counter()
        yield sse("session_started", {})
        earlier = [turn.content for turn in request.history if turn.role == "user"]
        needs = functional_needs(request.needs)
        suggestion = memory_suggestion(request.message, earlier, needs)
        early = self._early_events(request, earlier, suggestion, started)
        if early is not None:
            for event in early:
                yield event
            return

        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        prompt = system_prompt(needs, self.base_prompt)
        context = context_messages(earlier_questions(request.history))
        task = asyncio.create_task(
            self._run(request.message, prompt, lambda kind, data: queue.put_nowait((kind, data)), context)
        )
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
            yield sse("final", self._final(
                TURN_FAILED, [], "kural", suggestion,
                FinalFields(refused=False, how=_empty_how(started, rule_id=None), mode="unknown"),
            ))
            return
        answer, author = task.result()
        if author != "kural" and names_a_price(answer.text) and not _TARIFF_TOOLS & set(answer.tool_names):
            # The last line of R-06: a model answer that states a price is not shown.
            for event in self._refusal(suggestion, started):
                yield event
            return
        text = display_text(answer.text)
        for piece in text_pieces(text):
            yield sse("token", {"text": piece})
        yield sse("final", self._final(
            text, citations(answer, offline=self.offline), author, suggestion,
            FinalFields(refused=False, how=_how(answer, started, rule_id=None), mode="answer"),
        ))

    def _early_events(
        self,
        request: ChatRequest,
        earlier: Sequence[str],
        suggestion: Any,
        started: float,
    ) -> list[str] | None:
        if emergency_intent(request.message):
            fields = FinalFields(refused=False, how=_empty_how(started, rule_id=None), mode="redirect", emergency=True)
            return [sse("final", self._final("", [], "kural", suggestion, fields))]
        if refuses_in_context(request.message, earlier):
            return self._refusal(suggestion, started)
        return None

    def _refusal(
        self,
        suggestion: Any,
        started: float,
        *,
        cited: list[dict[str, Any]] | None = None,
        how: dict[str, Any] | None = None,
        answer_text: str | None = None,
        mode: str = "refused",
        steps: list[str] | None = None,
    ) -> list[str]:
        answer = answer_text or REFUSAL_TEXT
        fields = FinalFields(refused=True, how=how or _empty_how(started, rule_id="refusal"), mode=mode, steps=steps)
        events = [sse("token", {"text": piece}) for piece in text_pieces(answer)]
        events.append(sse("final", self._final(answer, cited or [], "kural", suggestion, fields)))
        return events

    @staticmethod
    def _final(
        answer: str,
        citations: list[dict[str, Any]],
        author: str,
        suggestion: Any,
        fields: FinalFields,
    ) -> dict[str, Any]:
        return {
            "answer": answer,
            "answer_text": answer,
            "citations": citations,
            "author": author,
            "memory_suggestion": suggestion,
            "refused": fields.refused,
            "how": fields.how,
            "mode": fields.mode,
            "steps": fields.steps,
            "emergency": fields.emergency,
        }

    async def _run(
        self, question: str, prompt: str, emit: Emit, context: list[dict[str, str]] | None = None
    ) -> tuple[AgentAnswer, str]:
        """The model when it is configured, allowed today and trustworthy on this answer; else the rules."""
        tools = ToolEvents(self.nabiz, emit)
        if llm.available(self.config) and self.guard.reserve(self.config.provider, TURN_CALLS):
            try:
                async with self._model_turns:
                    answer = await self._ask_model(tools, question, prompt, context or [])
            finally:
                self.guard.release(self.config.provider, TURN_CALLS)
            if answer is not None and answer.mode == "llm" and (answer.faithfulness is None or answer.faithfulness.passed):
                return answer, author_for(self.config)
            if answer is not None and answer.mode != "llm":
                # The agent already fell back to its rules after a model error.
                return answer, "kural"
        rules = NabizAgent(tools, config=llm.LlmConfig(), system_prompt=prompt)
        return await rules.ask(question), "kural"

    async def _ask_model(
        self, tools: ToolEvents, question: str, prompt: str, context: list[dict[str, str]]
    ) -> AgentAnswer | None:
        answer: AgentAnswer | None = None
        try:
            answer = await NabizAgent(tools, config=self.config, system_prompt=prompt).ask(question, context=context)
        except Exception as exc:  # noqa: BLE001 - any failure falls back to the rule path
            log.warning("model turn failed, answering by rule: %s", type(exc).__name__)
        finally:
            usage = answer.usage if answer is not None else {}
            # The calls the agent counted, failed ones included; nothing counted is the worst case.
            calls = usage.get("model_calls") or (answer.steps if answer is not None and answer.mode == "llm" else TURN_CALLS)
            self.guard.record(self.config.provider, usage, calls)
        return answer
