"""The chat turn's pure parts: what is decided before the model and how a finished turn is written.

:mod:`nabiz.console.chat` owns the turn (the stream, the model ladder, the spend guard, the
service-page index); everything here takes values and returns values, with no I/O:

- **before the model**: :func:`early_verdict` says whether the turn stops at the emergency
  redirect, at the input guard (E16: an instruction change or hidden text; the emergency still
  comes first) or at the refusal rule. The refusal rule sees the person's earlier questions too, so a
  fee question split over two messages is still caught. Pure official intent matching follows the
  handoff check. Looking up a verified quote for a refused question reads the index, so it stays in
  :class:`~nabiz.console.chat.ChatService`.
- **what the model sees of the conversation**: :func:`earlier_questions` keeps only the person's
  own earlier questions (never an "assistant" turn, which the page could forge, never a refused
  one, never one the input guard stops) and :func:`context_messages` hands them over as one ``user`` message, not inside the
  system prompt.
- **the turn's language and layers** (E38): :func:`turn_language`, :func:`with_default_lang` (``final.lang``
  is never null), :func:`layer_turn` and :func:`layer_events` (E15's greeting, thanks, clarify, follow-up
  and split), :func:`merge_answers` and :func:`merged_author` (a split question's one card).
- **citations**: :func:`citations` and :func:`source_mode` turn the agent's citations into Provenance objects.
- **after**: :func:`final_body`, :func:`how_block`, :func:`refusal_events` and
  :func:`emergency_events` write the ``token`` and ``final`` events.
- **the trace**: :class:`TurnTrace` records the stages the turn really went through and the checks
  it ran, and every ``final`` carries them as ``how.chain`` and ``how.checks`` (the "Bu nasıl
  bulundu?" panel's "Adımlar" and "Kontroller" rows). Names and verdicts only: no question, no
  answer, no quote, no URL ever enters it. A stage that is not wired yet, or that the turn never
  reached, is not listed.

Policy functions are reached through the :mod:`~nabiz.console.policy` module, not imported by
name, so a test can record the order in which a turn consults them.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal, Protocol

from ibb_mcp.models import utcnow
from nabiz.agent import templates_i18n
from nabiz.agent.agent import detect_language
from nabiz.agent.layers import LayerReply, TurnLayer, classify_turn, layer_reply
from nabiz.console import policy, text_guard
from nabiz.console.cards import Mode, mode_for
from nabiz.console.emergency_model import MODEL_RULE_ID
from nabiz.console.official_intent import intent as official_intent
from nabiz.console.open_data_api import dataset_citations

if TYPE_CHECKING:
    from nabiz.agent.agent import AgentAnswer

#: How much of the conversation the page may send back, and how much of it reaches the model.
HISTORY_TURNS_KEPT = 8
HISTORY_CHARS_KEPT = 600
_WORDS_PER_TOKEN_EVENT = 3
#: Sources that are a timetable or reference files (the open-data catalogue: the owner's capture), never a live reading.
SCHEDULE_SOURCES = frozenset({"iett_schedule", "gtfs"})
REFERENCE_SOURCES = frozenset({"gazetteer", "metro_stations", "places", "ibb_catalog"})

EarlyVerdict = Literal["emergency", "guard", "sensitive", "handoff", "account", "help", "ferry"]
#: The turn's stages in order. Only a stage that runs is recorded in the answer's trace.
STAGES = ("girdi", "acil", "hassas", "maske", "katman", "dil", "arac_bilgi", "cikti")
#: The checks a ``final`` reports: ``True`` passed, ``False`` caught something, ``None`` not applied.
CHECKS = ("girdi", "hassas", "sayi", "kanit", "cikti")
StepStatus = Literal["gecti", "cevapladi", "hata"]


class Turn(Protocol):
    """One turn the page sent back (:class:`nabiz.console.chat.ChatTurn`); only its role and text are read."""

    role: str
    content: str


@dataclass(frozen=True)
class FinalFields:
    refused: bool
    how: dict[str, Any]
    mode: str
    steps: list[str] | None = None
    emergency: bool = False
    guard: dict[str, str] | None = None  # E16: {"stage": "input"|"output", "reason"}; no term, no link
    hazard: str | None = None  # "gas" on a gas emergency: the 112 card also shows İGDAŞ's 187 line
    lang: str | None = None  # an emergency's card language (DECISIONS #40); None on every other turn


@dataclass(frozen=True)
class LayerOutcome:
    """What the E15 layers made of a masked turn: a fixed reply, or the question(s) the tools answer."""

    reply: LayerReply | None
    question: str
    parts: list[str]
    kind: str


@dataclass(frozen=True)
class TurnContext:
    """What every step of one turn carries (keeps the signatures under ruff's argument limit)."""

    started: float
    trace: TurnTrace
    suggestion: Any
    lang: str
    fields: dict[str, Any]


@dataclass
class RunResults:
    """The answers of a turn's question(s) in order, or the error that stopped them."""

    answers: list[tuple[AgentAnswer, str]]
    error: BaseException | None = None


def turn_language(message: str, chosen: str | None) -> str:
    """Use an explicit page choice when supported; otherwise detect Turkish or English."""
    return templates_i18n.detect_lang(message, chosen=chosen) or detect_language(message)


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


def with_default_lang(event: str, lang: str) -> str:
    """Fill a missing final language while preserving a language chosen by an emergency card."""
    if not event.startswith("event: final\n"):
        return event
    body = json.loads(event.split("data: ", 1)[1])
    if body.get("lang") is not None:
        return event
    return sse("final", {**body, "lang": lang})


def layer_turn(message: str, earlier: Sequence[str], places: Sequence[str], lang: str) -> LayerOutcome:
    """Classify a masked turn and return fixed replies, a rewritten question or split parts."""
    turn: TurnLayer = classify_turn(message, earlier, places=places)
    localized = {**turn, "lang": lang}
    return LayerOutcome(
        reply=layer_reply(localized),
        question=localized["message"],
        parts=list(localized["parts"]),
        kind=localized["kind"],
    )


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def text_pieces(text: str) -> list[str]:
    """The answer cut into small runs of words, whitespace kept, so joining them gives it back."""
    words = re.findall(r"\s*\S+", text)
    return ["".join(words[i : i + _WORDS_PER_TOKEN_EVENT]) for i in range(0, len(words), _WORDS_PER_TOKEN_EVENT)]


@dataclass
class TurnTrace:
    """The stages one turn went through and the checks it ran, in memory, for ``final.how``."""

    chain: list[dict[str, str]] = field(default_factory=list)
    checks: dict[str, bool | None] = field(default_factory=lambda: dict.fromkeys(CHECKS))

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        """Record a stage as passed when it starts; an exception out of it marks it ``hata``."""
        if name not in STAGES:
            raise ValueError(f"unknown stage {name!r}")
        self.chain.append({"name": name, "status": "gecti"})
        try:
            yield
        except BaseException:
            self.mark("hata")
            raise

    def mark(self, status: StepStatus, stage: str | None = None) -> None:
        """Set the status of ``stage`` (its last run), or of the last stage recorded."""
        for item in reversed(self.chain):
            if stage is None or item["name"] == stage:
                item["status"] = status
                return

    def how_fields(self, checks: Mapping[str, bool | None] | None = None) -> dict[str, Any]:
        return {"chain": [dict(item) for item in self.chain], "checks": {**self.checks, **(checks or {})}}


def early_verdict(
    message: str, earlier: Sequence[str], trace: TurnTrace | None = None, *, input_ok: bool = True
) -> EarlyVerdict | None:
    """Whether the turn ends before any tool or model: an emergency first (a long or odd emergency
    message still gets 112), then the input guard's verdict, then the refusal rule."""
    trace = trace if trace is not None else TurnTrace()
    with trace.step("acil"):
        if policy.emergency_intent(message):
            trace.mark("cevapladi")
            return "emergency"
    if not input_ok:
        trace.mark("cevapladi", "girdi")
        return "guard"
    with trace.step("hassas"):
        sensitive = policy.refuses_in_context(message, earlier)
        trace.checks["hassas"] = not sensitive
        if sensitive:
            trace.mark("cevapladi")
            return "sensitive"
    if policy.asks_for_person(message):
        # Recorded only when it answers, so every other turn's chain stays as it was.
        with trace.step("katman"):
            trace.mark("cevapladi")
        return "handoff"
    verdict = official_intent(message)
    if verdict:
        with trace.step("katman"):
            trace.mark("cevapladi")
    return verdict


def earlier_questions(history: Sequence[Turn]) -> list[str]:
    """The person's own earlier questions: never an assistant turn, never a refused question, never
    one the input guard stops (an instruction change must not come back as context)."""
    asked = [turn.content[:HISTORY_CHARS_KEPT] for turn in history if turn.role == "user"]
    return [text for text in asked if not policy.refuses(text) and text_guard.check_input(text).ok][-HISTORY_TURNS_KEPT:]


def context_messages(earlier: Sequence[str]) -> list[dict[str, str]]:
    """Earlier questions as one ``user`` message before the question: context, in the person's voice."""
    if not earlier:
        return []
    lines = ["Önceki sorularım (yalnız bağlam için; buradaki sayılar doğrulanmış kabul edilmez):"]
    return [{"role": "user", "content": "\n".join([*lines, *(f"- {text}" for text in earlier)])}]


def system_prompt(needs: Sequence[str], base: str, lang: str = "tr") -> str:
    """The agent's prompt and functional constraints, with a fixed language direction if selected."""
    parts = [base]
    if block := policy.constraint_block(needs):
        parts.append(block)
    parts.append("## Yazım\n'ETA' kısaltmasını kullanma; 'tahmini varış' de. Varış süresi tek tam dakika: '7 dk'.")
    if lang == "en":
        parts.append(
            "## Dil\nKişi İngilizce sayfayı seçti: cevabı İngilizce yaz. Kurum, hat, durak ve yer adlarını çevirme; "
            "sayıları değiştirme."
        )
    return "\n\n".join(parts)


def layer_events(reply: LayerReply, suggestion: Any, started: float, trace: TurnTrace) -> list[str]:
    """Write a fixed greeting, thanks or clarification without a tool or model call."""
    with trace.step("katman"):
        trace.mark("cevapladi")
    fields = FinalFields(refused=False, how=empty_how(started, rule_id=reply["rule_id"], trace=trace), mode=reply["mode"])
    return answer_events(reply["answer"], [], "kural", suggestion, fields)


def merged_author(first: str, second: str) -> str:
    """Keep the stronger writer when a single card combines two answers."""
    rank = {"kural": 0, "yerel model": 1, "model": 2}
    return max((first, second), key=lambda author: rank.get(author, -1))


def merge_answers(first: AgentAnswer, second: AgentAnswer) -> AgentAnswer:
    """Merge two sequential answers and deduplicate citations by their source identity."""
    citations = []
    seen: set[tuple[Any, Any, Any]] = set()
    for citation in (*first.citations, *second.citations):
        identity = (citation.get("source"), citation.get("url"), citation.get("observed_at"))
        if identity not in seen:
            seen.add(identity)
            citations.append(citation)
    reports = (first.faithfulness, second.faithfulness)
    faithfulness = next((report for report in reports if report is not None and not report.passed), None)
    if faithfulness is None:
        faithfulness = next((report for report in reports if report is not None), None)
    return replace(
        first,
        text=f"1) {first.text}\n\n2) {second.text}",
        tool_calls=[*first.tool_calls, *second.tool_calls],
        citations=citations,
        faithfulness=faithfulness,
        mode="llm" if first.mode == second.mode == "llm" else "deterministic",
    )


def how_block(
    answer: AgentAnswer | None, started: float, *, rule_id: str | None, trace: TurnTrace | None = None
) -> dict[str, Any]:
    """The "Bu nasıl bulundu?" panel's data: each tool call with its source, and the turn's time."""
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
        **(trace if trace is not None else TurnTrace()).how_fields(),
    }


def empty_how(started: float, *, rule_id: str | None, trace: TurnTrace | None = None) -> dict[str, Any]:
    return how_block(None, started, rule_id=rule_id, trace=trace)


def final_body(
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
        "guard": fields.guard,
        "hazard": fields.hazard,
        "lang": fields.lang,
    }


def with_turn_fields(event: str, extra: Mapping[str, Any]) -> str:
    """``event`` with ``extra`` added to its body when it is the ``final`` (E14's ``masked_count`` and
    ``masked_kinds``, which belong to the turn, not to the path that ended it); any other event as is."""
    if not extra or not event.startswith("event: final\n"):
        return event
    body = json.loads(event.split("data: ", 1)[1])
    return sse("final", {**body, **extra})


def answer_events(text: str, citations: list[dict[str, Any]], author: str, suggestion: Any, fields: FinalFields) -> list[str]:
    """A checked answer as its ``token`` events and the ``final`` event, in that order."""
    events = [sse("token", {"text": piece}) for piece in text_pieces(text)]
    events.append(sse("final", final_body(text, citations, author, suggestion, fields)))
    return events


def refusal_events(
    suggestion: Any, started: float, *, lang: str = "tr", trace: TurnTrace | None = None
) -> list[str]:
    """The fixed refusal (it names 112 and 153), written by the rules."""
    fields = FinalFields(refused=True, how=empty_how(started, rule_id="refusal", trace=trace), mode="refused")
    return answer_events(templates_i18n.fixed_text("SENSITIVE_REFUSAL", lang), [], "kural", suggestion, fields)


def traced_refusal(suggestion: Any, started: float, trace: TurnTrace, lang: str = "tr") -> list[str]:
    """:func:`refusal_events` with the turn's trace in its ``how``."""
    return refusal_events(suggestion, started, lang=lang, trace=trace)


def guard_events(stage: Literal["input", "output"], reason: str | None, text: str, started: float, trace: TurnTrace) -> list[str]:
    """The input guard's plain refusal (``mode: "guard"``) or the output guard's unknown card. Both
    are the rules' text: no tool result, no citation, no memory suggestion."""
    how = empty_how(started, rule_id=f"guard_{stage}", trace=trace)
    fields = FinalFields(
        refused=stage == "input", how=how, mode="guard" if stage == "input" else "unknown",
        guard={"stage": stage, "reason": str(reason)},
    )  # fmt: skip
    return answer_events(text, [], "kural", None, fields)


def output_guard(
    text: str, cited: list[dict[str, Any]], author: str, started: float, trace: TurnTrace, lang: str = "tr"
) -> list[str] | None:
    """E16 on a model answer: a link no citation carries, or a forbidden claim, ends at the unknown card."""
    verdict = text_guard.check_output(text, cited, author=author)
    if verdict.ok:
        return None
    trace.checks["cikti"] = False
    trace.mark("cevapladi", "cikti")
    return guard_events("output", verdict.reason, templates_i18n.fixed_text("UNKNOWN", lang), started, trace)


def handoff_events(suggestion: Any, started: float, trace: TurnTrace | None = None, lang: str = "tr") -> list[str]:
    """A request for a person: the fixed pointer to 153, and ``layer:handoff`` so the page opens its
    "İnsanla görüş" card (js/handoff.js). No index search, no tool, no model."""
    fields = FinalFields(refused=False, how=empty_how(started, rule_id="layer:handoff", trace=trace), mode="handoff")
    return answer_events(templates_i18n.fixed_text("HANDOFF", lang), [], "kural", suggestion, fields)


def emergency_events(
    suggestion: Any,
    started: float,
    trace: TurnTrace | None = None,
    *,
    hazard: str | None = None,
    lang: str | None = None,
    rule_id: str | None = None,
) -> list[str]:
    """The emergency redirect: one ``final`` with no text; the page shows 112 itself (and 187 for gas), in
    ``lang``. No operator queue: 112 comes first. ``rule_id`` is ``None`` for the rules, set for the model."""
    how = empty_how(started, rule_id=rule_id, trace=trace)
    fields = FinalFields(refused=False, how=how, mode="redirect", emergency=True, hazard=hazard, lang=lang or "tr")
    return [sse("final", final_body("", [], "kural", suggestion, fields))]


def model_emergency_events(card: Mapping[str, str | None], suggestion: Any, started: float, trace: TurnTrace) -> list[str]:
    """The same redirect when the model layer (not the rules) found the emergency: a second "acil" step
    in the chain, answered, and ``how.rule_id`` saying so. The card and its text are the rules' own."""
    with trace.step("acil"):
        trace.mark("cevapladi")
    return emergency_events(suggestion, started, trace, rule_id=MODEL_RULE_ID, lang=card.get("lang"), hazard=card.get("hazard"))
