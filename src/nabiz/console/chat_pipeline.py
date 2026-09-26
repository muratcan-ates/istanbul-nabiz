"""The chat turn's pure parts: what is decided before the model and how a finished turn is written.

:mod:`nabiz.console.chat` owns the turn (the stream, the model ladder, the spend guard, the
service-page index); everything here takes values and returns values, with no I/O:

- **before the model**: :func:`early_verdict` says whether the turn stops at the emergency
  redirect or at the refusal rule. The refusal rule sees the person's earlier questions too, so a
  fee question split over two messages is still caught. Looking up a verified quote for a refused
  question reads the index, so it stays in :class:`~nabiz.console.chat.ChatService`.
- **what the model sees of the conversation**: :func:`earlier_questions` keeps only the person's
  own earlier questions (never an "assistant" turn, which the page could forge, never a refused
  one) and :func:`context_messages` hands them over as one ``user`` message, not inside the
  system prompt.
- **after**: :func:`final_body`, :func:`how_block`, :func:`refusal_events` and
  :func:`emergency_events` write the ``token`` and ``final`` events.

Policy functions are reached through the :mod:`~nabiz.console.policy` module, not imported by
name, so a test can record the order in which a turn consults them.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

from nabiz.console import policy

if TYPE_CHECKING:
    from nabiz.agent.agent import AgentAnswer

#: How much of the conversation the page may send back, and how much of it reaches the model.
HISTORY_TURNS_KEPT = 8
HISTORY_CHARS_KEPT = 600
_WORDS_PER_TOKEN_EVENT = 3

EarlyVerdict = Literal["emergency", "sensitive"]


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


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def text_pieces(text: str) -> list[str]:
    """The answer cut into small runs of words, whitespace kept, so joining them gives it back."""
    words = re.findall(r"\s*\S+", text)
    return ["".join(words[i : i + _WORDS_PER_TOKEN_EVENT]) for i in range(0, len(words), _WORDS_PER_TOKEN_EVENT)]


def early_verdict(message: str, earlier: Sequence[str]) -> EarlyVerdict | None:
    """Whether the turn ends before any tool or model: an emergency first, then the refusal rule."""
    if policy.emergency_intent(message):
        return "emergency"
    if policy.refuses_in_context(message, earlier):
        return "sensitive"
    return None


def earlier_questions(history: Sequence[Turn]) -> list[str]:
    """The person's own earlier questions: never an assistant turn, never a refused question."""
    asked = [turn.content[:HISTORY_CHARS_KEPT] for turn in history if turn.role == "user"]
    return [text for text in asked if not policy.refuses(text)][-HISTORY_TURNS_KEPT:]


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


def how_block(answer: AgentAnswer | None, started: float, *, rule_id: str | None) -> dict[str, Any]:
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
    }


def empty_how(started: float, *, rule_id: str | None) -> dict[str, Any]:
    return how_block(None, started, rule_id=rule_id)


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
    }


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


def emergency_events(suggestion: Any, started: float) -> list[str]:
    """The emergency redirect: one ``final`` with no text; the page shows 112 itself."""
    fields = FinalFields(refused=False, how=empty_how(started, rule_id=None), mode="redirect", emergency=True)
    return [sse("final", final_body("", [], "kural", suggestion, fields))]
