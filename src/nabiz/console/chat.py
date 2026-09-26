"""``POST /api/chat``: one agent turn, streamed to the page as server-sent events.

    event: tool   data {"name", "status": "start"|"end"}      live, as the agent calls İBB tools
    event: token  data {"text"}                                the answer, in order
    event: final  data {"answer", "answer_text", "citations", "author", "memory_suggestion",
                        "refused", "how", "mode", "steps", "emergency", "guard", "hazard", "lang",
                        "masked_count", "masked_kinds"}

**The answer streams after it is checked.** :class:`~nabiz.agent.NabizAgent` verifies every
number in the model's prose against the tool results before it returns (and asks the model
once to repair a failure). Streaming the model's raw tokens would put an unverified number on
the screen first, which is the one thing the agent exists to prevent. So the page sees tool
progress live, and the verified text as a run of ``token`` events.

**Who wrote the answer is always said** (``author``): "model", "yerel model" (Foundry Local)
or "kural" (the agent's keyword-routed templates), taken from the rung that actually wrote the
answer (``AgentAnswer.provider``), not from the configuration. A turn starts on the first rung of
the model ladder (:func:`nabiz.agent.llm.pick_rung`); when today's cloud ceiling is reached, or
has room for a call but not a whole turn, it drops to the free Foundry Local rung
(``NABIZ_LADDER_LOCAL_ON_CAP=0`` switches that off). The rule path answers when no rung is left,
when the model call fails, and when a model answer still fails the numeric check after its
repair: a sentence built from the tool payload is better than a number nobody can back.

**A service question goes to the service-page index when one is built** (:mod:`ibb_mcp.knowledge`).
A refused question gets İBB's own sentence as a quote (``quote_only``) when a verified one
exists, else the refusal; a question no tool covers gets an ``answer`` from quotes or an
``unknown`` that points to 153. With no index, both keep their fixed text.

**The spend ceiling holds under load.** A model turn reserves room for the most calls it can
make (:data:`TURN_CALLS`) before it starts, at most :data:`MODEL_TURNS_AT_ONCE` model turns
run at a time, and what a turn spent is recorded even when the model failed half-way: the
calls made (``usage["model_calls"]``) and their tokens, or :data:`TURN_CALLS` when nothing
could be counted.

**What a visitor sends is checked, then masked**: the input guard (:mod:`~nabiz.console.text_guard`,
E16) strips invisible text and stops an instruction change; the emergency and refusal verdicts read
the unmasked text on this server; everything after them (the service-page index, the model, the
earlier questions, the memory suggestion) sees it masked (:mod:`~nabiz.console.pii_guard`, E14), and
every ``final`` says how much was masked (``masked_count``, ``masked_kinds``). A model answer with a
link its sources do not carry, or a forbidden claim, becomes the unknown card. The pure parts of the turn (the emergency and
refusal verdict, the earlier questions the model may see, the prompt, the events a finished turn
writes) live in :mod:`nabiz.console.chat_pipeline`. An İBB failure reaches the model and the page
as one Turkish sentence; its body (an HTML page, a SOAP fault, a URL) stays in the server log as
its kind and status.

Nothing here logs the question, the history or the needs.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from ibb_mcp.http import RateLimitExceeded, UpstreamUnavailable
from ibb_mcp.knowledge import answer as knowledge_answer
from ibb_mcp.knowledge import open_from_env
from ibb_mcp.models import utcnow
from nabiz.agent import llm
from nabiz.agent.agent import PROMPT_PATH, AgentAnswer, NabizAgent
from nabiz.agent.schemas import TOOL_DESCRIPTIONS
from nabiz.agent.templates import OUT_OF_SCOPE
from nabiz.console import chat_pipeline as pipeline
from nabiz.console import text_guard
from nabiz.console.budget import FREE_PROVIDERS, SpendGuard
from nabiz.console.cards import Mode, display_text, mode_for
from nabiz.console.chat_pipeline import FinalFields, context_messages, earlier_questions, sse, system_prompt
from nabiz.console.emergency_model import model_emergency
from nabiz.console.open_data_api import dataset_citations
from nabiz.console.pii_guard import mask, mask_turn, pii_final_fields
from nabiz.console.policy import emergency_card, functional_needs, memory_suggestion, names_a_price

log = logging.getLogger("nabiz.console.chat")

TURN_FAILED = "Şu anda bu soruya cevap veremiyorum. Biraz sonra yeniden dene; acil bir durumdaysan 112'yi ara."
#: The most model calls one turn can make: the agent's four steps, one forced answer, one repair.
TURN_CALLS = 6
#: Model turns running at once; the rest wait their turn. A design parameter.
MODEL_TURNS_AT_ONCE = 3
#: What an İBB failure becomes, for the model and for the page.
UPSTREAM_DOWN = "doğrulanamadı"
#: Sources that are a timetable or this repository's own reference files, never a live reading.
SCHEDULE_SOURCES = frozenset({"iett_schedule", "gtfs"})
#: The open-data catalogue is a copy made by the owner, as old as its capture: "recorded", never "live".
REFERENCE_SOURCES = frozenset({"gazetteer", "metro_stations", "places", "ibb_catalog"})
#: A model answer may name a price only when the person asked about car parks (İSPARK's tariff).
_TARIFF_TOOLS = frozenset({"ispark_find_parking", "ispark_park_detail", "ispark_typical_occupancy"})
#: The citation source of a service-page quote (the page's label: "Hizmet sayfaları (yerel dizin)").
KNOWLEDGE_SOURCE = "local:knowledge"

Emit = Callable[[str, dict[str, Any]], None]


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    needs: list[str] = Field(default_factory=list, max_length=16)
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)


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
        as_of = item.get("as_of")
        result.append({
            "source": item.get("source"),
            "url": item.get("source_url") or None,
            "observed_at": as_of,
            # Nothing was read (an unread stamp): no age and no mode, never "0 sn önce".
            "age_s": _age_s(as_of) if as_of else None,
            "mode": source_mode(item.get("source"), offline=offline) if as_of else "unknown",
        })
    return result + dataset_citations(answer.tool_calls)


def author_for(config: llm.LlmConfig) -> str:
    """The label a configuration would get. Kept only until B02's ``how_api.py`` labels with
    ``llm.author_of(rung.provider)``; B01b deletes it. Nothing in this module calls it: a card's
    author is the rung that wrote the answer."""
    return llm.author_of(config.provider)


class ChatService:
    """Runs chat turns over one shared facade, one model configuration and one spend guard."""

    def __init__(self, nabiz: Any, config: llm.LlmConfig, guard: SpendGuard, *, offline: bool) -> None:
        self.nabiz = nabiz
        self.config = config
        self.guard = guard
        self.offline = offline
        self._base_prompt: str | None = None
        self._model_turns = asyncio.Semaphore(MODEL_TURNS_AT_ONCE)
        self._knowledge: tuple[Any, Any] | None = None

    @property
    def base_prompt(self) -> str:
        if self._base_prompt is None:
            self._base_prompt = PROMPT_PATH.read_text(encoding="utf-8")
        return self._base_prompt

    async def events(self, request: ChatRequest) -> AsyncIterator[str]:
        """The whole turn as SSE text: tool events while it runs, then the answer and the final event."""
        started = time.perf_counter()
        trace = pipeline.TurnTrace()
        yield sse("session_started", {})
        with trace.step("girdi"):
            checked = text_guard.check_input(request.message)
            trace.checks["girdi"] = checked.ok
        earlier = [turn.content for turn in request.history if turn.role == "user"]
        masked = mask_turn(checked.text, earlier)
        turn_fields = pii_final_fields(masked)
        needs = functional_needs(request.needs)
        suggestion = memory_suggestion(masked.message, list(masked.history), needs)
        early = await self._early_events(checked, earlier, masked.message, suggestion, started, trace)
        if early is not None:
            for event in early:
                yield pipeline.with_turn_fields(event, turn_fields)
            return
        async for event in self._turn_events(request, masked.message, needs, suggestion, started, trace):
            yield pipeline.with_turn_fields(event, turn_fields)

    async def _turn_events(
        self, request: ChatRequest, question: str, needs: list[str], suggestion: Any, started: float, trace: pipeline.TurnTrace
    ) -> AsyncIterator[str]:
        """Tools, model and answer on the masked question; the earlier questions masked the same way."""
        with trace.step("maske"):
            context = context_messages([mask(text)[0] for text in earlier_questions(request.history)])
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        prompt = system_prompt(needs, self.base_prompt)
        task = asyncio.create_task(self._run(question, prompt, lambda kind, data: queue.put_nowait((kind, data)), context))
        task.add_done_callback(lambda done: queue.put_nowait(("done", None)))
        with trace.step("arac_bilgi"):
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
            trace.mark("hata", "arac_bilgi")
            how = pipeline.empty_how(started, rule_id=None, trace=trace)
            fields = FinalFields(refused=False, how=how, mode="unknown")
            for event in pipeline.answer_events(TURN_FAILED, [], "kural", suggestion, fields):
                yield event
            return
        answer, author = task.result()
        for event in await self._answer_events(question, answer, author, suggestion, started, trace):
            yield event

    async def _answer_events(
        self,
        question: str,
        answer: AgentAnswer,
        author: str,
        suggestion: Any,
        started: float,
        trace: pipeline.TurnTrace | None = None,
    ) -> list[str]:
        """The finished answer as events, after the price filter and the service-page index."""
        trace = trace if trace is not None else pipeline.TurnTrace()
        trace.mark("cevapladi", "arac_bilgi")
        trace.checks["sayi"] = answer.faithfulness.passed if answer.faithfulness is not None else None
        if author != "kural":
            with trace.step("cikti"):
                priced = names_a_price(answer.text) and not _TARIFF_TOOLS & set(answer.tool_names)
                trace.checks["cikti"] = not priced
            if priced:
                # The last line of R-06: a model answer that states a price is not shown.
                trace.mark("gecti", "arac_bilgi")
                trace.mark("cevapladi", "cikti")
                return pipeline.traced_refusal(suggestion, started, trace)
        if author == "kural" and answer.text == OUT_OF_SCOPE.get(answer.lang):
            quoted = await self._from_knowledge(question, sensitive=False, suggestion=suggestion, started=started, trace=trace)
            if quoted:
                return quoted
        cited, shown = citations(answer, offline=self.offline), display_text(answer.text)
        if (stopped := pipeline.output_guard(shown, cited, author, started, trace)) is not None:
            return stopped  # checked as the page would show it: display_text already spells out "ETA"
        how = pipeline.how_block(answer, started, rule_id=None, trace=trace)
        fields = FinalFields(refused=False, how=how, mode="answer")
        return pipeline.answer_events(shown, cited, author, suggestion, fields)

    async def _early_events(
        self,
        checked: text_guard.InputVerdict,
        earlier: Sequence[str],
        masked: str,
        suggestion: Any,
        started: float,
        trace: pipeline.TurnTrace,
    ) -> list[str] | None:
        """The verdicts read the checked, unmasked text; a quote for a refused question is looked up masked."""
        verdict = pipeline.early_verdict(checked.text, earlier, trace, input_ok=checked.ok)
        if verdict == "emergency":
            return pipeline.emergency_events(suggestion, started, trace, **emergency_card(checked.text))
        if verdict in {None, "sensitive"} and checked.ok and (card := await model_emergency(masked, self.config, self.guard)):
            return pipeline.model_emergency_events(card, suggestion, started, trace)
        if verdict == "guard":
            return pipeline.guard_events("input", checked.reason, checked.message or "", started, trace)
        if verdict == "handoff":
            return pipeline.handoff_events(suggestion, started, trace)
        if verdict == "sensitive":
            quoted = await self._from_knowledge(masked, sensitive=True, suggestion=suggestion, started=started, trace=trace)
            return quoted or pipeline.traced_refusal(suggestion, started, trace)
        return None

    def knowledge_index(self) -> tuple[Any, Any]:
        """The service-page index once it is built, else ``(None, None)``; offline, lexical search only."""
        if self._knowledge is None:
            store, embedder = open_from_env()
            if store is None:
                return None, None
            self._knowledge = (store, None if self.offline else embedder)
        return self._knowledge

    async def _from_knowledge(
        self, question: str, *, sensitive: bool, suggestion: Any, started: float, trace: pipeline.TurnTrace | None = None
    ) -> list[str] | None:
        """Quotes from İBB's service pages, or ``None`` for the fixed text: no index, no quote for a
        refused question, or an index that failed. ``trace.checks["kanit"]`` says whether a verified
        quote came back; it stays ``None`` when no index answered."""
        trace = trace if trace is not None else pipeline.TurnTrace()
        store, embedder = self.knowledge_index()
        if store is None:
            return None
        try:
            found = await knowledge_answer(question, store=store, embedder=embedder, sensitive=sensitive)
        except Exception as exc:  # noqa: BLE001 - a broken index must not break the turn
            log.warning("knowledge answer failed, keeping the fixed text: %s", type(exc).__name__)
            return None
        cited = [{**item, "source": KNOWLEDGE_SOURCE} for item in found.to_dict()["citations"]]
        trace.checks["kanit"] = bool(cited) and (not sensitive or found.mode == "quote_only")
        if sensitive and found.mode != "quote_only":
            return None  # no verified quote: the refusal, which also names 112
        # E08: the page names the search it waited on, like any tool.
        searched = [sse("tool", {"name": "ibb_services_search", "status": status}) for status in ("start", "end")]
        if (stopped := pipeline.output_guard(display_text(found.text), cited, found.author, started, trace)) is not None:
            return searched + stopped
        how = pipeline.empty_how(started, rule_id="knowledge", trace=trace)
        fields = FinalFields(refused=found.refused, how=how, mode=found.mode, steps=list(found.steps) or None)
        return searched + pipeline.answer_events(display_text(found.text), cited, found.author, suggestion, fields)

    def _reserve_rung(self) -> llm.LlmConfig | None:
        """The rung this turn runs on, with room for a whole turn held on it; ``None`` for the rules.

        ``allows`` asks for room for one call, the reservation for :data:`TURN_CALLS`: a cloud rung
        that is allowed but cannot hold a whole turn drops to the free local rung too, unless
        ``NABIZ_LADDER_LOCAL_ON_CAP`` is off. Only one reservation is ever held.
        """
        rung = llm.pick_rung(self.config, self.guard.allows)
        if rung is None or self.guard.reserve(rung.provider, TURN_CALLS):
            return rung
        if not llm.local_on_cap():
            return None
        local = llm.first_rung(self.config, lambda provider: provider in FREE_PROVIDERS)
        return local if local is not None and self.guard.reserve(local.provider, TURN_CALLS) else None

    async def _run(
        self, question: str, prompt: str, emit: Emit, context: list[dict[str, str]] | None = None
    ) -> tuple[AgentAnswer, str]:
        """The model when a rung has room today and the answer is trustworthy; else the rules."""
        tools = ToolEvents(self.nabiz, emit)
        rung = self._reserve_rung()
        if rung is not None:
            try:
                async with self._model_turns:
                    answer = await self._ask_model(tools, question, prompt, context or [], rung)
            finally:
                self.guard.release(rung.provider, TURN_CALLS)
            if answer is not None and answer.mode == "llm" and (answer.faithfulness is None or answer.faithfulness.passed):
                # Who wrote it: the rung that answered, which a failed call may have moved down the ladder.
                return answer, llm.author_of(answer.provider or rung.provider)
            if answer is not None and answer.mode != "llm":
                # The agent already fell back to its rules after a model error.
                return answer, "kural"
        rules = NabizAgent(tools, config=llm.LlmConfig(), system_prompt=prompt)
        return await rules.ask(question), "kural"

    async def _ask_model(
        self, tools: ToolEvents, question: str, prompt: str, context: list[dict[str, str]], rung: llm.LlmConfig
    ) -> AgentAnswer | None:
        answer: AgentAnswer | None = None
        try:
            answer = await NabizAgent(tools, config=rung, system_prompt=prompt).ask(question, context=context)
        except Exception as exc:  # noqa: BLE001 - any failure falls back to the rule path
            log.warning("model turn failed, answering by rule: %s", type(exc).__name__)
        finally:
            usage = answer.usage if answer is not None else {}
            # The calls the agent counted, failed ones included; nothing counted is the worst case.
            calls = usage.get("model_calls") or (answer.steps if answer is not None and answer.mode == "llm" else TURN_CALLS)
            self.guard.record(rung.provider, usage, calls)
        return answer
