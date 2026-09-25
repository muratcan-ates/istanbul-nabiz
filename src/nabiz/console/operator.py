"""``/api/console/*``: the simulated İBB operator's side, over :class:`~nabiz.console.ports.ConsolePort`.

The routes validate what a person sends and translate the port's errors; the decisions, the
ledger and the rule drafts belong to the decision core behind the port. Two rules are held
here because they are about the request, not the store:

- a rejection or a deferral carries a reason, and an edit carries the edited text; a request
  without one is refused before the core sees it
- the actor is always :data:`~nabiz.console.ports.OPERATOR`, the human role. Nothing a model
  writes reaches these routes: approval is an HTTP call a person makes from the console page
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import Any, Literal

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from nabiz.console.ports import OPERATOR, ConsolePort, PortNotWired

log = logging.getLogger("nabiz.console.operator")

operator_routes = APIRouter(prefix="/api/console")

#: Ids are opaque to this layer; the pattern only keeps them printable and short.
ID_PATTERN = r"^[A-Za-z0-9_.:-]{1,80}$"


class DecisionBody(BaseModel):
    action: Literal["approve", "edit", "reject", "defer"]
    reason: str = Field(default="", max_length=1000)
    edited_text: str | None = Field(default=None, max_length=2000)


class AdoptBody(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class SimulateBody(BaseModel):
    fixture: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")


def port_problem(status: int, kind: str, message: str) -> JSONResponse:
    """A failure the page can show as a card: ``{error, message}``."""
    return JSONResponse(status_code=status, content={"error": kind, "message": message})


async def port_answer(call: Awaitable[dict[str, Any]]) -> Any:
    """Await one port call and translate its error contract into HTTP."""
    try:
        return await call
    except PortNotWired as exc:
        return port_problem(503, "not_wired", str(exc))
    except LookupError:
        return port_problem(404, "not_found", "Bu kayıt bulunamadı.")
    except ValueError as exc:
        return port_problem(400, "bad_request", str(exc))


def console_port(request: Request) -> ConsolePort:
    return request.app.state.ports.console


@operator_routes.get("/queue")
async def console_queue(request: Request):
    return await port_answer(console_port(request).queue())


@operator_routes.get("/decisions/{signal_id}")
async def console_decision(request: Request, signal_id: str = Path(pattern=ID_PATTERN)):
    return await port_answer(console_port(request).decision(signal_id))


@operator_routes.post("/decisions/{signal_id}")
async def console_decide(request: Request, body: DecisionBody, signal_id: str = Path(pattern=ID_PATTERN)):
    reason = body.reason.strip()
    edited = (body.edited_text or "").strip() or None
    if body.action in {"reject", "defer"} and not reason:
        return port_problem(400, "reason_required", "Reddetme ve erteleme için gerekçe zorunlu.")
    if body.action == "edit" and edited is None:
        return port_problem(400, "edited_text_required", "Düzenleme için yeni metin zorunlu.")
    port = console_port(request)
    return await port_answer(port.decide(signal_id, action=body.action, reason=reason, edited_text=edited, actor=OPERATOR))


@operator_routes.get("/ledger/verify")
async def console_ledger_verify(request: Request):
    return await port_answer(console_port(request).verify())


@operator_routes.get("/ledger/{signal_id}/trace")
async def console_ledger_trace(request: Request, signal_id: str = Path(pattern=ID_PATTERN)):
    return await port_answer(console_port(request).trace(signal_id))


@operator_routes.get("/stats")
async def console_stats(request: Request):
    return await port_answer(console_port(request).stats())


@operator_routes.get("/rule-drafts")
async def console_rule_drafts(request: Request):
    return await port_answer(console_port(request).rule_drafts())


@operator_routes.post("/rule-drafts/{draft_id}/adopt")
async def console_adopt_rule(request: Request, body: AdoptBody, draft_id: str = Path(pattern=ID_PATTERN)):
    reason = body.reason.strip()
    if not reason:
        return port_problem(400, "reason_required", "Kuralı benimsemek için gerekçe zorunlu.")
    return await port_answer(console_port(request).adopt_rule(draft_id, reason=reason, actor=OPERATOR))


@operator_routes.post("/simulate")
async def console_simulate(request: Request, body: SimulateBody):
    return await port_answer(console_port(request).simulate(body.fixture))
