"""The chat turn's pure parts: what is decided before the model and how a finished turn is written.

:mod:`nabiz.console.chat` owns the turn (the stream, the model ladder, the spend guard, the
service-page index); everything here takes values and returns values, with no I/O:

- **before the model**: :func:`early_verdict` says whether the turn stops at the emergency
  redirect, at the input guard (E16: an instruction change or hidden text; the emergency still
  comes first) or at the refusal rule. The refusal rule sees the person's earlier questions too, so a
  fee question split over two messages is still caught. Looking up a verified quote for a refused
  question reads the index, so it stays in :class:`~nabiz.console.chat.ChatService`.
- **what the model sees of the conversation**: :func:`earlier_questions` keeps only the person's
  own earlier questions (never an "assistant" turn, which the page could forge, never a refused
  one, never one the input guard stops) and :func:`context_messages` hands them over as one ``user`` message, not inside the
  system prompt.
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

import json
import re
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

from ibb_mcp.knowledge.answer import UNKNOWN_TEXT
from nabiz.console import policy, text_guard

if TYPE_CHECKING:
    from nabiz.agent.agent import AgentAnswer

#: How much of the conversation the page may send back, and how much of it reaches the model.
HISTORY_TURNS_KEPT = 8
HISTORY_CHARS_KEPT = 600
_WORDS_PER_TOKEN_EVENT = 3

EarlyVerdict = Literal["emergency", "guard", "sensitive", "handoff"]
#: The turn's stages in order. Wired: girdi (E16), acil, hassas, maske (E14), arac_bilgi, cikti; katman
#: (E15) and dil (E06) are still B01b's.
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
    return None


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


def system_prompt(needs: Sequence[str], base: str) -> str:
    """The agent's prompt, plus the person's functional constraints. Nothing a visitor typed."""
    parts = [base]
    if block := policy.constraint_block(needs):
        parts.append(block)
    parts.append("## Yazım\n'ETA' kısaltmasını kullanma; 'tahmini varış' de. Varış süresi tek tam dakika: '7 dk'.")
    return "\n\n".join(parts)


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
    suggestion: Any,
    started: float,
    *,
    cited: list[dict[str, Any]] | None = None,
    how: dict[str, Any] | None = None,
    answer_text: str | None = None,
    mode: str = "refused",
    steps: list[str] | None = None,
) -> list[str]:
    """The fixed refusal (it names 112 and 153), written by the rules."""
    answer = answer_text or policy.REFUSAL_TEXT
    fields = FinalFields(refused=True, how=how or empty_how(started, rule_id="refusal"), mode=mode, steps=steps)
    return answer_events(answer, cited or [], "kural", suggestion, fields)


def traced_refusal(suggestion: Any, started: float, trace: TurnTrace) -> list[str]:
    """:func:`refusal_events` with the turn's trace in its ``how``."""
    return refusal_events(suggestion, started, how=empty_how(started, rule_id="refusal", trace=trace))


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
    text: str, cited: list[dict[str, Any]], author: str, started: float, trace: TurnTrace
) -> list[str] | None:
    """E16 on a model answer: a link no citation carries, or a forbidden claim, ends at the unknown card."""
    verdict = text_guard.check_output(text, cited, author=author)
    if verdict.ok:
        return None
    trace.checks["cikti"] = False
    trace.mark("cevapladi", "cikti")
    return guard_events("output", verdict.reason, UNKNOWN_TEXT, started, trace)


def handoff_events(suggestion: Any, started: float, trace: TurnTrace | None = None) -> list[str]:
    """A request for a person: the fixed pointer to 153, and ``layer:handoff`` so the page opens its
    "İnsanla görüş" card (js/handoff.js). No index search, no tool, no model."""
    fields = FinalFields(refused=False, how=empty_how(started, rule_id="layer:handoff", trace=trace), mode="handoff")
    return answer_events(policy.HANDOFF_TEXT, [], "kural", suggestion, fields)


def emergency_events(suggestion: Any, started: float, trace: TurnTrace | None = None, *, hazard: str | None = None) -> list[str]:
    """The emergency redirect: one ``final`` with no text; the page shows 112 itself (and 187 for gas)."""
    how = empty_how(started, rule_id=None, trace=trace)
    fields = FinalFields(refused=False, how=how, mode="redirect", emergency=True, hazard=hazard)
    return [sse("final", final_body("", [], "kural", suggestion, fields))]
