"""The quota strip's route and the chat turn's quota hook (DECISIONS #38).

``GET /api/quota`` answers what the page's strip shows ("Bugün kalan: 14/20 soru").

:func:`plan_turn` runs before a chat turn. An emergency (the same verdict the chat's first stage
gives) is never counted and never limited: it bypasses the per-minute limiter and the daily quota,
and its card comes from the rules like always. Any other turn is admitted against the daily
question count; past it the turn still runs, with the model rung closed (:class:`~nabiz.console.
quota.Meter`), so the rules keep answering and every card still names 153 and 112. A request for a
person (153) is answered by the rules and the page's handoff card whatever the quota says.

The turn's ``final`` event gains ``quota`` (what is left, whether the model was open) and, when the
question asked to follow something, ``follow_suggestion`` (:mod:`nabiz.console.follow`), read from
the masked question.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request

from nabiz.console import text_guard
from nabiz.console.accounts_api import current_account, holder_for, quota_status
from nabiz.console.chat_pipeline import with_turn_fields
from nabiz.console.follow import suggest_follow
from nabiz.console.pii_guard import mask
from nabiz.console.policy import emergency_intent
from nabiz.console.quota import CURRENT_METER, Holder, Meter, QuotaBook

quota_routes = APIRouter()


@quota_routes.get("/api/quota")
async def quota_view(request: Request) -> dict[str, Any]:
    return quota_status(request)


def is_emergency(message: str) -> bool:
    """The chat's own first verdict, on the text the input guard hands on. Imported by name: the
    chain-order test records what the turn itself consults, and this runs before the turn."""
    return emergency_intent(text_guard.check_input(message).text)


@dataclass
class TurnPlan:
    emergency: bool
    book: QuotaBook
    holder: Holder
    message: str

    async def events(self, service: Any, body: Any) -> AsyncIterator[str]:
        """The chat's events, counted against the holder; an emergency is neither counted nor metered."""
        admitted = False if self.emergency else self.book.admit(self.holder)
        meter = None if self.emergency else Meter(self.book, self.holder, model_open=admitted)
        CURRENT_METER.set(meter)
        topic = None if self.emergency else suggest_follow(mask(self.message)[0])
        try:
            async for event in service.events(body):
                if event.startswith("event: final\n"):
                    quota = {**self.book.status(self.holder), "counted": not self.emergency, "model_open_this_turn": admitted}
                    extra: dict[str, Any] = {"quota": quota}
                    if topic is not None and _plain_answer(event):
                        extra["follow_suggestion"] = topic.as_suggestion()
                    event = with_turn_fields(event, extra)
                yield event
        finally:
            # A turn cut off mid-way (the page closed) still holds its claim: give it back (P13).
            if meter is not None:
                meter.refund(meter.held)
            CURRENT_METER.set(None)


def _plain_answer(event: str) -> bool:
    """A final that is no emergency, no guard stop and no rights/fees refusal: only then is a follow offered."""
    body = json.loads(event.split("data: ", 1)[1])
    return not body.get("emergency") and body.get("mode") not in ("guard", "refused", "redirect")


def plan_turn(request: Request, message: str) -> TurnPlan:
    """Who the turn counts against, and whether it is an emergency. Counts nothing yet."""
    account = current_account(request)
    return TurnPlan(is_emergency(message), request.app.state.quota, holder_for(request, account), message)
