"""``POST /api/chat``: one agent turn, streamed to the page as server-sent events.

    event: tool   data {"name", "status": "start"|"end"}      live, as the agent calls İBB tools
    event: token  data {"text"}                                the answer, in order, after it was checked
    event: final  data {"answer", "answer_text", "citations", "author", "memory_suggestion", "refused", "how", "mode",
                        "steps", "emergency", "guard", "hazard", "lang", "cards", "masked_count", "masked_kinds"}

:class:`~nabiz.agent.NabizAgent` verifies every number against the tool results before the text streams. ``author``
is the rung that wrote the answer ("model", "yerel model", "kural"); a turn reserves :data:`TURN_CALLS` on the first
rung with room (Foundry Local when the cloud ceiling is reached), at most :data:`MODEL_TURNS_AT_ONCE` run at once, and
the rules answer when no rung is left, the model fails, or its answer fails the numeric check after one repair.
A question no tool covers, or a refused one, may be answered from İBB's service pages (:mod:`ibb_mcp.knowledge`).

The input guard (E16), then the emergency and refusal verdicts read the unmasked text; everything after them (the
E15 layers, the index, the model, the earlier questions) sees it masked (E14). The page's ``lang`` (``tr``/``en``,
else detected) sets the fixed sentences, the model's language block and ``final.lang``, which is never null: an
emergency's card language, else the turn's. The layers answer a greeting, thanks or an unclear turn without a tool
or the model, rewrite a follow-up and split a two-topic question into one card with two numbered answers; a
rewritten question or part meets the refusal check again. A model answer with a link its sources do not carry, or
a forbidden claim, becomes the unknown card; an İBB failure reaches the page as one sentence and its body stays in
the server log. The pure parts live in :mod:`nabiz.console.chat_pipeline`. Nothing here logs the question, the
history or the needs.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from ibb_mcp.http import RateLimitExceeded, UpstreamUnavailable
from ibb_mcp.knowledge import open_from_env
from nabiz.agent import llm
from nabiz.agent.agent import PROMPT_PATH, AgentAnswer, NabizAgent
from nabiz.agent.schemas import TOOL_DESCRIPTIONS
from nabiz.agent.templates import OUT_OF_SCOPE
from nabiz.agent.templates_i18n import fixed_text, quote_frame
from nabiz.console import chat_pipeline as pipeline
from nabiz.console import official_path, policy, text_guard
from nabiz.console.budget import FREE_PROVIDERS, SpendGuard
from nabiz.console.cards import display_text
from nabiz.console.chat_pipeline import FinalFields, context_messages, earlier_questions, sse, system_prompt
from nabiz.console.emergency_model import model_emergency
from nabiz.console.knowledge_turn import knowledge_turn
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
    lang: str | None = Field(default=None, max_length=8)


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
        self._places: tuple[str, ...] | None = None

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
        lang = pipeline.turn_language(checked.text, request.lang)
        earlier = [turn.content for turn in request.history if turn.role == "user"]
        masked = mask_turn(checked.text, earlier)
        needs = functional_needs(request.needs)
        turn = pipeline.TurnContext(
            started, trace, memory_suggestion(masked.message, list(masked.history), needs), lang, pii_final_fields(masked)
        )
        early = await self._early_events(checked, earlier, masked.message, turn)
        if early is not None:
            for event in early:
                yield pipeline.with_default_lang(pipeline.with_turn_fields(event, turn.fields), turn.lang)
            return
        async for event in self._turn_events(request, masked.message, needs, turn):
            yield pipeline.with_default_lang(pipeline.with_turn_fields(event, turn.fields), turn.lang)

    async def _turn_events(
        self, request: ChatRequest, question: str, needs: list[str], turn: pipeline.TurnContext
    ) -> AsyncIterator[str]:
        earlier, context, layer = self._prepare_layer(request, question, turn)
        if layer.reply is not None:
            for event in pipeline.layer_events(layer.reply, turn.suggestion, turn.started, turn.trace):
                yield event
            return
        questions = layer.parts if layer.kind == "split" else [layer.question]
        if layer.kind in {"followup", "split"} and any(policy.refuses_in_context(part, earlier) for part in questions):
            for event in pipeline.traced_refusal(turn.suggestion, turn.started, turn.trace, turn.lang):
                yield event
            return
        prompt = system_prompt(needs, self.base_prompt, turn.lang)
        results = pipeline.RunResults([])
        with turn.trace.step("arac_bilgi"):
            async for event in self._run_questions(questions, prompt, context, turn, results):
                yield event
        if results.error is not None:
            for event in self._failed_events(results.error, turn):
                yield event
            return
        if layer.kind == "split":
            answer = pipeline.merge_answers(results.answers[0][0], results.answers[1][0])
            author = pipeline.merged_author(results.answers[0][1], results.answers[1][1])
            rule_id = "layer:split"  # the index and the price filter read the whole masked question
        else:
            answer, author = results.answers[0]
            question, rule_id = layer.question, None
        for event in await self._answer_events(question, answer, author, turn, rule_id=rule_id):
            yield event

    def _prepare_layer(
        self, request: ChatRequest, question: str, turn: pipeline.TurnContext
    ) -> tuple[list[str], list[dict[str, str]], pipeline.LayerOutcome]:
        with turn.trace.step("maske"):
            earlier = [mask(text)[0] for text in earlier_questions(request.history)]
            layer = pipeline.layer_turn(question, earlier, self._place_names(), turn.lang)
            context = context_messages(earlier) if layer.keep_context else []
        if layer.kind in {"followup", "split"}:
            with turn.trace.step("katman"):
                turn.trace.mark("gecti")
        if turn.lang == "en" and layer.reply is None:
            with turn.trace.step("dil"):
                pass
        return earlier, context, layer

    async def _run_questions(
        self, questions: list[str], prompt: str, context: list[dict[str, str]], turn: pipeline.TurnContext,
        results: pipeline.RunResults,
    ) -> AsyncIterator[str]:
        for question in questions:
            queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
            def emit(kind: str, data: dict[str, Any], target: asyncio.Queue[tuple[str, Any]] = queue) -> None:
                target.put_nowait((kind, data))

            task = asyncio.create_task(self._run(question, prompt, emit, context, lang=turn.lang))
            task.add_done_callback(lambda done, target=queue: target.put_nowait(("done", None)))
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
                results.error = task.exception()
                return
            results.answers.append(task.result())

    def _failed_events(self, error: BaseException, turn: pipeline.TurnContext) -> list[str]:
        log.error("chat turn failed: %s", type(error).__name__)
        turn.trace.mark("hata", "arac_bilgi")
        how = pipeline.empty_how(turn.started, rule_id=None, trace=turn.trace)
        fields = FinalFields(refused=False, how=how, mode="unknown")
        return pipeline.answer_events(fixed_text("TURN_FAILED", turn.lang), [], "kural", turn.suggestion, fields)

    def _place_names(self) -> tuple[str, ...]:
        if self._places is None:
            self._places = tuple(place.name for place in self.nabiz.places.places)
        return self._places

    async def _answer_events(
        self,
        question: str,
        answer: AgentAnswer,
        author: str,
        turn: pipeline.TurnContext,
        *,
        rule_id: str | None = None,
    ) -> list[str]:
        """The finished answer as events, after the price filter and the service-page index."""
        trace = turn.trace
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
                return pipeline.traced_refusal(turn.suggestion, turn.started, trace, turn.lang)
        if author == "kural" and answer.text == OUT_OF_SCOPE.get(answer.lang):
            quoted = await self._from_knowledge(question, sensitive=False, turn=turn)
            if quoted:
                return quoted
        cited, shown = pipeline.citations(answer, offline=self.offline), display_text(answer.text)
        if (stopped := pipeline.output_guard(shown, cited, author, turn.started, trace, turn.lang)) is not None:
            return stopped  # checked as the page would show it: display_text already spells out "ETA"
        how = pipeline.how_block(answer, turn.started, rule_id=rule_id, trace=trace)
        fields = FinalFields(refused=False, how=how, mode="answer")
        return pipeline.answer_events(shown, cited, author, turn.suggestion, fields)

    async def _early_events(
        self,
        checked: text_guard.InputVerdict,
        earlier: Sequence[str],
        masked: str,
        turn: pipeline.TurnContext,
    ) -> list[str] | None:
        """The verdicts read the checked, unmasked text; a quote for a refused question is looked up masked."""
        trace = turn.trace
        verdict = pipeline.early_verdict(checked.text, earlier, trace, input_ok=checked.ok)
        if verdict == "emergency":
            return pipeline.emergency_events(turn.suggestion, turn.started, trace, **emergency_card(checked.text))
        # An official-path verdict still gets the model's emergency check: a help or account question can carry one.
        if verdict in {None, "sensitive", "account", "help", "ferry"} and checked.ok and (
            card := await model_emergency(masked, self.config, self.guard)
        ):
            return pipeline.model_emergency_events(card, turn.suggestion, turn.started, trace)
        if verdict == "guard":
            return pipeline.guard_events("input", checked.reason, checked.message or "", turn.started, trace)
        if verdict == "handoff":
            return pipeline.handoff_events(turn.suggestion, turn.started, trace, turn.lang)
        if verdict in {"account", "help", "ferry"}:
            return await official_path.early_events(self, checked.text, masked, verdict, turn)
        if verdict == "sensitive":
            quoted = await self._from_knowledge(masked, sensitive=True, turn=turn)
            return quoted or pipeline.traced_refusal(turn.suggestion, turn.started, trace, turn.lang)
        return None

    def knowledge_index(self) -> tuple[Any, Any]:
        """The service-page index once it is built, else ``(None, None)``; offline, lexical search only."""
        if self._knowledge is None:
            # Offline the index is opened read-only (mode=ro): a turn never writes the service-page index.
            store, embedder = official_path.readonly_index() if self.offline else open_from_env()
            if store is None:
                return None, None
            self._knowledge = (store, None if self.offline else embedder)
        return self._knowledge

    async def _from_knowledge(self, question: str, *, sensitive: bool, turn: pipeline.TurnContext) -> list[str] | None:
        """Quotes from İBB's service pages, or ``None`` for the fixed text: no index, no quote for a
        refused question, or an index that failed. ``trace.checks["kanit"]`` says whether a verified
        quote came back; it stays ``None`` when no index answered."""
        trace = turn.trace
        store, embedder = self.knowledge_index()
        if store is None:
            return None
        try:
            found, author, extra = await knowledge_turn(
                self, question, store=store, embedder=embedder, sensitive=sensitive, lang=turn.lang
            )
        except Exception as exc:  # noqa: BLE001 - a broken index must not break the turn
            log.warning("knowledge answer failed, keeping the fixed text: %s", type(exc).__name__)
            return None
        cited = [{**item, "source": KNOWLEDGE_SOURCE} for item in found.to_dict()["citations"]]
        if turn.lang != "tr":
            for item in cited:
                frame = quote_frame(turn.lang, item["quote"], item["url"])
                item.update(quote_lang=frame["quote_lang"], label=frame["label"])
        trace.checks["kanit"] = bool(cited) and (not sensitive or found.mode == "quote_only")
        if sensitive and found.mode != "quote_only":
            return None  # no verified quote: the refusal, which also names 112
        # E08: the page names the search it waited on, like any tool.
        searched = [sse("tool", {"name": "ibb_services_search", "status": status}) for status in ("start", "end")]
        if fallback := official_path.unknown_fallback(question, found, turn, searched):
            return fallback
        text = fixed_text("UNKNOWN", turn.lang) if found.mode == "unknown" else found.text
        if (stopped := pipeline.output_guard(
            display_text(text), cited, author, turn.started, trace, turn.lang
        )) is not None:
            return searched + stopped
        how = pipeline.empty_how(turn.started, rule_id="knowledge", trace=trace)
        how |= {**extra, "uncertainty": how["uncertainty"] + extra["uncertainty"]}  # E63 map, E78 generation
        fields = FinalFields(refused=found.refused, how=how, mode=found.mode, steps=list(found.steps) or None)
        return searched + pipeline.answer_events(display_text(text), cited, author, turn.suggestion, fields)

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
        self, question: str, prompt: str, emit: Emit, context: list[dict[str, str]] | None = None, *, lang: str = "tr"
    ) -> tuple[AgentAnswer, str]:
        """The model when a rung has room today and the answer is trustworthy; else the rules."""
        tools = ToolEvents(self.nabiz, emit)
        rung = self._reserve_rung()
        if rung is not None:
            try:
                async with self._model_turns:
                    answer = await self._ask_model(tools, question, prompt, context or [], rung, lang)
            finally:
                self.guard.release(rung.provider, TURN_CALLS)
            if answer is not None and answer.mode == "llm" and (answer.faithfulness is None or answer.faithfulness.passed):
                # Who wrote it: the rung that answered, which a failed call may have moved down the ladder.
                return answer, llm.author_of(answer.provider or rung.provider)
            if answer is not None and answer.mode != "llm":
                # The agent already fell back to its rules after a model error.
                return answer, "kural"
        rules = NabizAgent(tools, config=llm.LlmConfig(), system_prompt=prompt)
        return await rules.ask(question, lang=lang), "kural"

    async def _ask_model(
        self, tools: ToolEvents, question: str, prompt: str, context: list[dict[str, str]], rung: llm.LlmConfig,
        lang: str = "tr",
    ) -> AgentAnswer | None:
        answer: AgentAnswer | None = None
        try:
            answer = await NabizAgent(tools, config=rung, system_prompt=prompt).ask(question, lang=lang, context=context)
        except Exception as exc:  # noqa: BLE001 - any failure falls back to the rule path
            log.warning("model turn failed, answering by rule: %s", type(exc).__name__)
        finally:
            usage = answer.usage if answer is not None else {}
            # The calls the agent counted, failed ones included; nothing counted is the worst case.
            calls = usage.get("model_calls") or (answer.steps if answer is not None and answer.mode == "llm" else TURN_CALLS)
            self.guard.record(rung.provider, usage, calls)
        return answer
