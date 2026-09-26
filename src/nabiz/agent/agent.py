"""The Nabız city agent: a tool loop over ``ibb_mcp.tools.Nabiz`` that cannot invent numbers.

Three decisions shape this file.

**The tools are the MCP server's tools.** The agent calls :class:`~ibb_mcp.tools.Nabiz`
in-process rather than over MCP, but the function schemas are built from those same method
signatures and carry the same Turkish descriptions the MCP server advertises. One surface,
two transports: whatever VS Code Copilot can ask, this agent can ask, except
``check_alerts``, which needs a subscription only the caller holds
(:data:`nabiz.agent.schemas.NOT_OFFERED`).

**Every answer is checked before it is returned.** After the model writes prose we run
:mod:`nabiz.agent.faithfulness` over it with the raw tool payloads as the evidence. A
failure buys exactly one repair attempt — the model is told which numbers are unsupported
and asked to rewrite. A second failure returns the answer with ``faithfulness.passed`` False
and a warning attached, because silently returning an unverified number is the one outcome
this project exists to prevent.

**The agent runs without a model at all.** Azure for Students may have zero Azure OpenAI
quota (DECISIONS #5). When :func:`nabiz.agent.llm.available` is False, :meth:`NabizAgent.ask`
switches to ``deterministic`` mode: keyword routing to a single tool plus a templated answer
built only from that tool's payload. It is not a language model and does not pretend to be —
it answers the four demo journeys, states its sources and ages, and passes the same
faithfulness check. That is what keeps the demo alive with no quota.
"""

from __future__ import annotations

import itertools
import json
import logging
import pathlib
import re
import time
from dataclasses import dataclass, field
from typing import Any

from ibb_mcp.http import RateLimitExceeded, UpstreamUnavailable
from ibb_mcp.models import ToolResult
from ibb_mcp.telemetry import Span, span
from ibb_mcp.text import normalize_tr
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.agent.faithfulness import FaithfulnessReport, check_faithfulness
from nabiz.agent.minutes import with_shown_minutes
from nabiz.agent.schemas import TOOL_DESCRIPTIONS, build_tool_schemas
from nabiz.agent.templates import (
    ATTRIBUTION_LINE,
    DETERMINISTIC_NOTE,
    HELP_NUMBERS,
    NO_DATA,
    UNROUTED,
    recorded_stamp,
    render_answer,
)

log = logging.getLogger("nabiz.agent")

PROMPT_PATH = pathlib.Path(__file__).with_name("system_prompt.md")

#: Turn ordinal within this process, so a trace can be read in the order the questions
#: were asked. It is not a conversation id and must never become one: the agent keeps no
#: per-user state, and a trace that could be grouped by user is a trace that identifies one.
_turns = itertools.count(1)


@dataclass
class ToolCallRecord:
    """One tool invocation, kept so the eval harness can score the chain."""

    name: str
    arguments: dict[str, Any]
    ok: bool
    payload: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: float = 0.0


@dataclass
class AgentAnswer:
    """Everything a run produced: the prose, the evidence and the verdict on it."""

    text: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    faithfulness: FaithfulnessReport | None = None
    mode: str = "llm"
    lang: str = "tr"
    steps: int = 0
    repaired: bool = False
    warnings: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    model: str | None = None
    provider: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)

    @property
    def tool_names(self) -> list[str]:
        return [call.name for call in self.tool_calls]


def _payload(result: ToolResult) -> dict[str, Any]:
    """The JSON a tool result becomes for the model — provenance always included.

    Deliberately re-implemented rather than imported from ``ibb_mcp.server``: that renderer
    is a private helper of a module this agent must not depend on, and the agent needs the
    dict itself (for the faithfulness check), not a string.
    """
    provenance = result.provenance
    return {
        # An arrival carries the single-minute text the card shows ("7 dk"), so the model and
        # the templates say what the card says (nabiz.agent.minutes).
        "data": with_shown_minutes(result.data, stale=provenance.cached),
        "provenance": {
            "source": provenance.source,
            "source_url": provenance.source_url,
            "reported_at": provenance.reported_at.isoformat() if provenance.reported_at else None,
            "observed_at": provenance.observed_at.isoformat() if provenance.observed_at else None,
            "age": None if provenance.unread else provenance.describe_age(),
            "stale": provenance.cached,
            "license": provenance.license,
        },
        **({"note": result.note} if result.note else {}),
    }


def detect_language(text: str) -> str:
    """Turkish unless the question looks English. Cheap on purpose — no model call."""
    if re.search(r"[çğıöşüÇĞİÖŞÜ]", text):
        return "tr"
    words = set(re.findall(r"[a-zçğıöşü]+", text.lower()))
    turkish = {"var", "mi", "mı", "nasil", "nasıl", "nerede", "ne", "kac", "kaç", "hangi", "otopark", "durak", "hava"}
    english = {"the", "is", "are", "how", "what", "where", "when", "which", "parking", "air", "quality", "bus", "near"}
    return "en" if len(words & english) > len(words & turkish) else "tr"


# --------------------------------------------------------------------------------------
# deterministic mode: keyword routing + templates, for when there is no model quota
# --------------------------------------------------------------------------------------
#: A metro/tram/funicular code. The trailing guard is ``(?!\d)`` rather than ``\b`` so a
#: Turkish case ending still resolves: "M4'te", "M4te" and "M4ün" all name line M4.
_METRO_LINE_RE = re.compile(r"\b(M\d{1,2}[AB]?|T\d|F\d|MARMARAY)(?!\d)", re.IGNORECASE)
_BUS_LINE_RE = re.compile(r"\b(\d{1,3}[A-ZÇĞİÖŞÜ]{1,2})\b")
_BUS_NUMBER_RE = re.compile(r"\b(\d{2,3})\s*(?:hat|numaral[ıi]|line|otob[üu]s)", re.IGNORECASE)
_STOP_RE = re.compile(r"([\w'’.\- ]{2,32}?)\s*dura[ğg]", re.UNICODE)

_KEYWORDS: dict[str, tuple[str, ...]] = {
    "air": ("hava kalitesi", "hava kirlil", "air quality", "hava", "aqi", "pm10", "pollution", "smog"),
    "window": ("ne zaman", "en iyi", "en uygun", "best time", "best window", "kosu", "spor", "yuruyus", "forecast", "tahmin"),
    "parking": ("park yeri", "car park", "otopark", "parking", "ispark"),
    "metro": ("metro", "marmaray", "tramvay", "funikuler"),
    "station": ("yuruyen merdiven", "istasyon", "asansor", "engelli", "station", "lift", "elevator", "escalator", "wc"),
    "arrival": ("ne zaman gelir", "kac dakika", "next bus", "when does", "varis", "gelir", "arrive", "arrival"),
    "stop": ("durak", "duragi", "stop"),
    "traffic": ("trafik", "traffic", "yogunluk", "congestion", "sikisik"),
    # "verinin yasi" is spelled out beside "veri yasi": a multi-word key is an exact
    # substring test, and Turkish declines the first word too, so the genitive form does
    # not match the nominative one.
    "fresh": (
        "veri yasi",
        "verinin yasi",
        "veri ne kadar",
        "ne kadar guncel",
        "guncel mi",
        "how old",
        "data age",
        "tazelik",
        "freshness",
    ),
}

#: Tokens that would otherwise trip a keyword prefix: an airport question is not an
#: air-quality question.
_NOT_KEYWORD = {"havalimani", "havaalani", "havacilik", "havuz"}


def _has(text: str, group: str) -> bool:
    """Keyword test over the folded question.

    Multi-word keys match as substrings; single words match as token *prefixes*, because
    Turkish glues its case endings on ("otoparkta", "trafikte", "havada") and an exact
    token test would miss every real sentence.
    """
    tokens = text.split()
    for word in _KEYWORDS[group]:
        if " " in word:
            if word in text:
                return True
        elif any(token.startswith(word) and not _excluded(token) for token in tokens):
            return True
    return False


def _excluded(token: str) -> bool:
    """Is this token one of the false friends?

    The exclusion has to be a **prefix** test for the same reason the keyword test is:
    "havalimanına", "havalimanında" and "havaalanına" are the forms people actually write,
    and an exact-token exclusion let every one of them through as an air-quality question.
    """
    return any(token.startswith(bad) for bad in _NOT_KEYWORD)


#: Folded tokens that introduce a line rather than belong to a stop name. "metro" is
#: deliberately absent: "4.LEVENT METRO" really is the stop's name.
_LINE_FILLER = {"otobus", "otobusu", "otobusun", "hat", "hatti", "hattin", "bus", "line", "numarali", "sefer"}
_FOLDED_BUS_LINE_RE = re.compile(r"\d{1,3}[a-z]{1,2}")
_FOLDED_METRO_LINE_RE = re.compile(r"m\d{1,2}[ab]?|t\d|f\d|marmaray")


def _is_line_or_filler(word: str) -> bool:
    """Is this leading word part of the *line*, not of the stop name?"""
    folded = normalize_tr(word)
    if not folded:
        return True
    return bool(
        folded in _LINE_FILLER
        or _FOLDED_BUS_LINE_RE.fullmatch(folded)
        or _FOLDED_METRO_LINE_RE.fullmatch(folded)
    )


def _bus_line(question: str) -> str | None:
    match = _BUS_LINE_RE.search(question.upper())
    if match and not _METRO_LINE_RE.fullmatch(match.group(1)):
        return match.group(1)
    numeric = _BUS_NUMBER_RE.search(question)
    return numeric.group(1) if numeric else None


def _stop_name(question: str) -> str | None:
    """The stop named before "durağı", with the line that precedes it stripped off.

    "500T otobüsü 4. Levent durağı" names *one* stop. The lazy capture reaches back to
    the start of the sentence, so without this the line code and the word introducing
    it are handed to the stop search, which then finds nothing at all — the question
    fails for a reason that has nothing to do with the data.
    """
    match = _STOP_RE.search(question)
    if not match:
        return None
    words = match.group(1).strip().split()
    while words and _is_line_or_filler(words[0]):
        words.pop(0)
    return " ".join(words[-3:]) if words else None


#: Words that ask about a station's lifts or escalators: İBB's fault record answers those, not
#: the station list (whose lift count says nothing about whether one is out of service).
_EQUIPMENT_WORDS = ("asansor", "yuruyen merdiven", "yuruyen bant", "lift", "elevator", "escalator")


def _station_route(text: str, place: str) -> tuple[str, dict[str, Any]]:
    """A station question: its fault record when it names a lift or an escalator, else its facilities."""
    if any(word in text for word in _EQUIPMENT_WORDS):
        return "metro_equipment_status", {"station": place}
    return "metro_station_info", {"name": place}


class NabizAgent:
    """A city agent over the İBB tools of :data:`TOOL_DESCRIPTIONS`, with or without a language model."""

    def __init__(
        self,
        nabiz: Nabiz | None = None,
        *,
        config: llm.LlmConfig | None = None,
        system_prompt: str | None = None,
        tools: list[str] | None = None,
    ) -> None:
        self.nabiz = nabiz or Nabiz()
        self.config = config if config is not None else llm.LlmConfig.from_env()
        self.schemas = build_tool_schemas(tools)
        self._prompt = system_prompt

    @property
    def system_prompt(self) -> str:
        if self._prompt is None:
            self._prompt = PROMPT_PATH.read_text(encoding="utf-8")
        return self._prompt

    async def aclose(self) -> None:
        await self.nabiz.aclose()

    # -- public entry point -------------------------------------------------------
    async def ask(
        self, question: str, lang: str | None = None, max_steps: int = 4, *, context: list[dict[str, str]] | None = None
    ) -> AgentAnswer:
        """Answer one question, then verify every number in the answer against the tools.

        ``context`` is earlier conversation as its own ``user`` messages, before the question:
        never in the system prompt, where a visitor's text would speak with the system's voice.
        When the model fails mid-run, the rule answer carries the tokens spent before it
        failed, so a spend ceiling can count them.
        """
        lang = lang or detect_language(question)
        warnings: list[str] = []
        spent: dict[str, Any] = {}
        # The question is not an attribute of this span and never will be: it is the
        # user's own words, and a span is shipped to a cloud log (docs/NABIZ.md §1.3).
        with span(
            "nabiz.agent.turn",
            **{
                "nabiz.agent.turn": next(_turns),
                "nabiz.agent.lang": lang,
                "nabiz.agent.provider": self.config.provider,
            },
        ) as turn:
            if llm.available(self.config):
                try:
                    return _describe_turn(turn, await self._ask_model(question, lang, max_steps, spent, context or []))
                except llm.LlmError as exc:
                    # The kind only: an SDK's message can quote a response body or a masked key.
                    log.warning("model unavailable mid-run, falling back to deterministic mode: %s", type(exc).__name__)
                    warnings.append(f"Model çağrısı başarısız ({type(exc).__name__}); deterministic moda düşüldü.")
            answer = await self._ask_deterministic(question, lang)
            answer.warnings, answer.usage = warnings + answer.warnings, spent
            return _describe_turn(turn, answer)

    # -- model path ---------------------------------------------------------------
    async def _ask_model(
        self, question: str, lang: str, max_steps: int, usage: dict[str, Any], context: list[dict[str, str]]
    ) -> AgentAnswer:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            *context,
            {"role": "user", "content": question},
        ]
        calls: list[ToolCallRecord] = []
        text, model_name, provider, steps = "", None, None, 0
        #: True while the model is still mid-chain. A reply that asks for tools may also
        #: carry prose ("Trafiğe bakıyorum…") — that prose was written *before* the tool
        #: results existed, so it must never survive as the answer.
        pending_tools = False

        for _ in range(max(1, max_steps)):
            steps += 1
            with span("nabiz.llm.chat", **{"nabiz.agent.step": steps}):
                response = await _chat(self.config, usage, messages, tools=self.schemas)
            model_name, provider = response.get("model") or model_name, response.get("provider") or provider
            text = (response.get("content") or "").strip()
            requested = response.get("tool_calls") or []
            pending_tools = bool(requested)
            if not requested:
                break
            messages.append(_assistant_message(response.get("content"), requested))
            for call in requested:
                record = await self._call_tool(call["name"], call["arguments"])
                calls.append(record)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "name": call["name"],
                        "content": json.dumps(
                            record.payload if record.ok else {"error": record.error},
                            ensure_ascii=False,
                            default=str,
                        ),
                    }
                )
        if pending_tools or not text:
            # Step budget spent while still calling tools: ask once more for prose only.
            with span("nabiz.llm.chat", **{"nabiz.agent.step": steps + 1, "nabiz.agent.forced": True}):
                response = await _chat(self.config, usage, [*messages, {"role": "user", "content": _FORCE_PROSE[lang]}])
            steps += 1
            model_name, provider = response.get("model") or model_name, response.get("provider") or provider
            text = (response.get("content") or "").strip() or text

        evidence = [call.payload for call in calls if call.payload]
        # A tool error is evidence too. The system prompt orders the model to relay one
        # verbatim ("bu durağa uğrayan hatlar: 153, 154, …"); flagging the numbers inside
        # it as fabrications would punish the model for obeying.
        errors = [call.error for call in calls if call.error]
        report = check_faithfulness(text, evidence, question=question, extra_sources=errors or None)
        warnings: list[str] = []
        repaired = False
        if not report.passed:
            log.info("faithfulness failed, repairing: %s", report.unsupported_texts)
            messages += [
                {"role": "assistant", "content": text},
                {"role": "user", "content": report.repair_instruction(lang)},
            ]
            with span("nabiz.llm.chat", **{"nabiz.agent.step": steps + 1, "nabiz.agent.repair": True}):
                response = await _chat(self.config, usage, messages)
            steps += 1
            model_name, provider = response.get("model") or model_name, response.get("provider") or provider
            retry = (response.get("content") or "").strip()
            if retry:
                repaired, text = True, retry
                report = check_faithfulness(text, evidence, question=question, extra_sources=errors or None)
            if not report.passed:
                warnings.append(
                    "Sayısal sadakat denetimi geçilemedi; şu sayılar araç sonuçlarında yok: "
                    + ", ".join(report.unsupported_texts)
                )
        return AgentAnswer(
            text=text,
            tool_calls=calls,
            citations=_citations(calls),
            faithfulness=report,
            mode="llm",
            lang=lang,
            steps=steps,
            repaired=repaired,
            warnings=warnings,
            usage=usage,
            model=model_name or self.config.model,
            provider=provider or self.config.provider,
            messages=messages,
        )

    # -- tool execution -----------------------------------------------------------
    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> ToolCallRecord:
        """Run one tool. A tool never raises out of here; a failure is data for the model."""
        started = time.perf_counter()
        arguments = dict(arguments or {})
        error: str | None = None
        payload: dict[str, Any] | None = None
        # Argument *names*, never their values: `place` is a label, "Taksim" is what the
        # user typed. The error message is left off the span for the same reason (it
        # quotes the input back: "Bilinmeyen yer: …"), so only its kind is recorded.
        with span(
            "nabiz.tool",
            **{"nabiz.tool.name": name, "nabiz.tool.arg_names": ",".join(sorted(arguments))},
        ) as tool_span:
            error_kind: str | None = None
            if name not in TOOL_DESCRIPTIONS:
                error = f"Bilinmeyen araç: {name}. Kullanılabilir araçlar: {', '.join(TOOL_DESCRIPTIONS)}."
                error_kind = "unknown_tool"
            else:
                try:
                    result: ToolResult = await getattr(self.nabiz, name)(**arguments)
                    payload = _payload(result)
                    tool_span.set(
                        **{
                            "nabiz.tool.cached": result.provenance.cached,
                            "nabiz.tool.data_age_s": round(result.provenance.age_seconds, 1),
                        }
                    )
                except (ValueError, TypeError) as exc:
                    error, error_kind = str(exc), type(exc).__name__
                except RateLimitExceeded as exc:
                    error, error_kind = f"İstek bütçesi doldu: {exc}", type(exc).__name__
                except UpstreamUnavailable as exc:
                    error, error_kind = f"İBB servisi şu anda yanıt vermiyor: {exc}", type(exc).__name__
                except Exception as exc:  # noqa: BLE001 - a tool must never end the turn
                    log.exception("tool %s failed", name)
                    error, error_kind = f"Beklenmeyen hata: {type(exc).__name__}", type(exc).__name__
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            tool_span.set(
                **{"nabiz.tool.ok": error is None, "nabiz.tool.duration_ms": duration_ms, "nabiz.tool.error_kind": error_kind}
            )
        return ToolCallRecord(
            name=name,
            arguments=arguments,
            ok=error is None,
            payload=payload,
            error=error,
            duration_ms=duration_ms,
        )

    # -- deterministic path -------------------------------------------------------
    def route(self, question: str) -> tuple[str, dict[str, Any]]:  # noqa: C901, PLR0912 - debt, ratcheted in scripts/architecture_baseline.json
        """Pick one tool by keyword. The whole of "no LLM" mode's intelligence lives here."""
        text = normalize_tr(question)
        place = self._find_place(question)
        if _has(text, "air"):
            if not place:
                return "", _NEEDS_PLACE_REASON
            return ("air_quality_forecast" if _has(text, "window") else "air_quality_now"), {"place": place}
        if _has(text, "station") and place and not _has(text, "stop"):
            return _station_route(text, place)
        # A bus line code outranks the word "metro": "500T 4. Levent metroya ne zaman
        # gelir" is a bus question whose destination happens to be a metro station.
        line_code = _bus_line(question)
        if line_code and (_has(text, "arrival") or _has(text, "stop")):
            stop = _stop_name(question) or place or ""
            if stop:
                return "iett_next_arrivals", {"line_code": line_code, "stop": stop}
        if _has(text, "metro") or _METRO_LINE_RE.search(question):
            line = _METRO_LINE_RE.search(question)
            return "metro_status", {"line": line.group(1).upper() if line else None}
        if _has(text, "parking"):
            if not place:
                return "", _NEEDS_PLACE_REASON
            return "ispark_find_parking", {"place": place}
        if line_code:
            return "iett_line_buses", {"line_code": line_code}
        if _has(text, "stop"):
            return "iett_stops_search", {"query": _stop_name(question) or place or question}
        if _has(text, "traffic"):
            return "traffic_index", {"window": "24h" if "dun" in text or "yesterday" in text else "now"}
        if _has(text, "fresh"):
            return "city_freshness", {}
        if place:
            return "places_resolve", {"query": place}
        # Nothing matched and no place was named. Answering "how old is the data?" to
        # "how do I get to the airport?" is not a fallback, it is a non sequitur dressed
        # up as an answer; say what this agent can and cannot do instead.
        return "", _OUT_OF_SCOPE_REASON

    def _find_place(self, question: str) -> str | None:
        """Longest gazetteer name contained in the question, suffixes and all.

        ``PlaceIndex.resolve`` scores a *query*; here the place is buried inside a sentence
        and glued to Turkish case endings ("Taksim'e", "Kadıköy'den"), so a containment
        scan over the normalised gazetteer is the reliable move.
        """
        haystack = f" {normalize_tr(question)} "
        best: tuple[int, str] | None = None
        for place in self.nabiz.places.places:
            needle = normalize_tr(place.name)
            if len(needle) < 4 or needle not in haystack:
                continue
            if best is None or len(needle) > best[0]:
                best = (len(needle), place.name)
        return best[1] if best else None

    async def _ask_deterministic(self, question: str, lang: str) -> AgentAnswer:
        """Route to one tool and render a template. No model, no free-form generation."""
        tool, arguments = self.route(question)
        if not tool:
            # Routed nowhere on purpose: either the question needs a place and named none
            # (guessing one would answer about a district the user never mentioned), or no
            # tool covers it at all.
            message = UNROUTED["scope" if arguments.get("reason") == "scope" else "place"][lang]
            return AgentAnswer(
                text=message,
                faithfulness=check_faithfulness(message, None, question=question, extra_sources=HELP_NUMBERS),
                mode="deterministic", lang=lang,
                warnings=[DETERMINISTIC_NOTE[lang]],
                provider="none",
            )
        with span("nabiz.agent.deterministic", **{"nabiz.tool.name": tool}):
            record = await self._call_tool(tool, arguments)
        if record.ok and record.payload is not None:
            text = render_answer(tool, record.payload, lang, recorded=self.nabiz.settings.offline)
        else:
            text = f"{record.error}\n\n{ATTRIBUTION_LINE}" if record.error else NO_DATA[lang]
        # The error is relayed verbatim, so its own numbers ("bu durağa uğrayan hatlar:
        # 153, 154 …") came from the tool and are not this agent's invention.
        # The recording's own time ("kayıtlı · 26.09 05:15") is put there by this template from
        # the tool's provenance, so its digits are sourced too.
        stamp = recorded_stamp(record.payload["provenance"]) if record.ok and record.payload is not None else None
        extra = [record.error, stamp] if stamp else record.error
        report = check_faithfulness(text, [record.payload], question=question, extra_sources=extra)
        # A template is hand-written Turkish, so a numeric constant can creep into one and
        # then no number in it came from the payload. The model path warns when the check
        # fails; this path must warn too, or a failed check is invisible here.
        warnings = [DETERMINISTIC_NOTE[lang]] + (
            ["Sayısal sadakat denetimi geçilemedi; şu sayılar araç sonuçlarında yok: " + ", ".join(report.unsupported_texts)]
            if not report.passed
            else []
        )
        return AgentAnswer(
            text=text,
            tool_calls=[record],
            citations=_citations([record]),
            faithfulness=report,
            mode="deterministic", lang=lang,
            steps=1, warnings=warnings,
            provider="none",
        )


def _describe_turn(turn: Span, answer: AgentAnswer) -> AgentAnswer:
    """Summarise a finished turn onto its span and hand the answer straight back.

    Shapes and verdicts only: how many tools ran, which ones, and whether the faithfulness
    check believed the result. The prose itself stays out: it answers a question a person
    asked, and the trace it would land in is a server-side store.
    """
    turn.set(
        **{
            "nabiz.agent.mode": answer.mode,
            "nabiz.agent.steps": answer.steps,
            "nabiz.agent.tool_calls": len(answer.tool_calls),
            "nabiz.agent.tools": ",".join(answer.tool_names),
            "nabiz.agent.repaired": answer.repaired,
            "nabiz.agent.model": answer.model,
            "nabiz.agent.provider": answer.provider,
            "nabiz.agent.faithful": None if answer.faithfulness is None else answer.faithfulness.passed,
        }
    )
    return answer


def _assistant_message(content: str | None, calls: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [
            {
                "id": call["id"],
                "type": "function",
                "function": {"name": call["name"], "arguments": json.dumps(call["arguments"], ensure_ascii=False)},
            }
            for call in calls
        ],
    }


async def _chat(config: llm.LlmConfig, usage: dict[str, Any], messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    """One model call: counted in ``usage["model_calls"]`` before it is made (a failed call is
    still a paid attempt) and its tokens added after."""
    usage["model_calls"] = usage.get("model_calls", 0) + 1
    response = await llm.chat(config, messages, **kwargs)
    _merge_usage(usage, response.get("usage"))
    return response


def _merge_usage(total: dict[str, Any], usage: Any) -> None:
    total.update({key: total.get(key, 0) + value for key, value in (usage or {}).items() if isinstance(value, (int, float))})


def _citations(calls: list[ToolCallRecord]) -> list[dict[str, Any]]:
    """One entry per distinct source reading, so the UI can print "İSPARK · 8 dk önce"."""
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for call in calls:
        if not call.payload:
            continue
        provenance = call.payload["provenance"]
        as_of = provenance.get("reported_at") or provenance["observed_at"]
        key = (provenance["source"], str(as_of))
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "tool": call.name,
                "source": provenance["source"],
                "source_url": provenance["source_url"],
                "as_of": as_of,
                "age": provenance["age"],
                "stale": provenance["stale"],
                "license": provenance["license"],
            }
        )
    return out


#: Why :meth:`NabizAgent.route` declined to pick a tool. Carried in the (unused) argument
#: slot so the caller can say which of the two refusals it is without a second signature.
_NEEDS_PLACE_REASON = {"reason": "place"}
_OUT_OF_SCOPE_REASON = {"reason": "scope"}
_FORCE_PROSE = {
    "tr": "Adım bütçesi doldu. Elindeki araç sonuçlarıyla, yeni araç çağırmadan cevabı şimdi yaz.",
    "en": "The step budget is spent. Write the answer now from the tool results you already have.",
}
