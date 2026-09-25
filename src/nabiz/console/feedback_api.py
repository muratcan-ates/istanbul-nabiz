"""Opt-in answer feedback (G15): a vote and a reason code, counted in memory and nowhere else.

The page sends only when the visitor ticks "Anonim olarak gönder", and then only
``{answer_id, vote, reason}`` (``js/feedback.js``). The server keeps a per-process count of
(vote, reason) pairs: no question, no answer text, no address, and the random ``answer_id`` is
checked for shape and dropped. Nothing is written to disk; a restart clears the counts.
"""

from __future__ import annotations

import collections
import logging
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger("nabiz.console.feedback")

feedback_routes = APIRouter()


class FeedbackBody(BaseModel):
    """Exactly the three fields ``feedbackPayload`` sends; anything more is refused."""

    model_config = ConfigDict(extra="forbid")

    answer_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    vote: Literal["up", "down"]
    reason: Literal["wrong", "stale", "misunderstood", "other"] | None = None


def feedback_counts(request: Request) -> collections.Counter[tuple[str, str]]:
    """The process's (vote, reason) counter, created on first use."""
    counts = getattr(request.app.state, "feedback_counts", None)
    if counts is None:
        counts = request.app.state.feedback_counts = collections.Counter()
    return counts


@feedback_routes.post("/api/feedback", status_code=204)
async def citizen_feedback(request: Request, body: FeedbackBody) -> Response:
    """Count one opt-in vote; 204 with no body, so the page has nothing to render."""
    reason = body.reason if body.vote == "down" else None
    feedback_counts(request)[(body.vote, reason or "none")] += 1
    log.info("feedback vote=%s reason=%s", body.vote, reason or "none")
    return Response(status_code=204)
