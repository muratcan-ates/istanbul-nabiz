"""Routes for the operator pause switch and the citizen-safe service status.

The ledger's SQLite append uses ``BEGIN IMMEDIATE``, so separate Ledger instances can append
to the same chain without taking the same in-process lock.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictBool

from nabiz.console.kill_switch import HELP_LINE, PAUSED_MESSAGE, ChatPause, PauseStore, SameState, pause_path, set_chat_pause
from nabiz.console.operator import port_problem
from nabiz.console.ports import OPERATOR
from nabiz.console.wiring import ledger_path
from nexus_core.decisions import REASON_MAX
from nexus_core.ledger import Ledger

log = logging.getLogger(__name__)
kill_switch_routes = APIRouter()
REASON_REQUIRED = "Sohbeti durdurmak ve açmak için gerekçe zorunlu."


class ChatPauseBody(BaseModel):
    """One operator's explicit requested state and reason."""

    paused: StrictBool
    reason: str = Field(default="", max_length=REASON_MAX)


def pause_store(app: FastAPI) -> PauseStore:
    """Reuse the app's store, or create one at the configured ignored state path."""
    store = getattr(app.state, "chat_pause_store", None)
    if store is None:
        store = PauseStore(pause_path())
        app.state.chat_pause_store = store
    return store


def pause_ledger(app: FastAPI) -> Ledger:
    """Reuse the app's ledger, or open the same path used by the rest of the console."""
    ledger = getattr(app.state, "chat_pause_ledger", None)
    if ledger is None:
        ledger = Ledger(ledger_path())
        app.state.chat_pause_ledger = ledger
    return ledger


@kill_switch_routes.get("/api/console/chat-pause")
async def read_chat_pause(request: Request) -> dict[str, object]:
    """Return the operator view; the app's console middleware protects this path."""
    return pause_store(request.app).read().operator_view()


@kill_switch_routes.post("/api/console/chat-pause")
async def write_chat_pause(request: Request, body: ChatPauseBody) -> JSONResponse:
    """Seal the reason before making the new state visible to other workers."""
    reason = body.reason.strip()
    if not reason:
        return port_problem(400, "reason_required", REASON_REQUIRED)
    try:
        state = await asyncio.to_thread(
            set_chat_pause, pause_store(request.app), pause_ledger(request.app),
            paused=body.paused, reason=reason, by_role=OPERATOR,
        )
    except SameState as exc:
        return port_problem(409, "conflict", str(exc))
    except ValueError as exc:
        return port_problem(400, "bad_request", str(exc))
    except (OSError, sqlite3.Error) as exc:
        log.error("chat pause could not be recorded (%s)", type(exc).__name__)
        return port_problem(503, "not_recorded", "Karar deftere yazılamadı; sohbetin durumu değişmedi.")
    message = "Sohbet durduruldu." if state.paused else "Sohbet yeniden açıldı."
    return JSONResponse(content={**state.operator_view(), "message": message})


@kill_switch_routes.get("/api/service-status")
async def service_status(request: Request) -> JSONResponse:
    """Expose only the citizen-safe state and prevent caches from keeping a pause stale."""
    state: ChatPause = pause_store(request.app).read()
    return JSONResponse(content=state.citizen_view(), headers={"Cache-Control": "no-store"})


def chat_gate(request: Request) -> JSONResponse | None:
    """Return a 503 before streaming; bind as the first line of citizen_chat, before TurnLimiter:
    ``if (paused := chat_gate(request)) is not None: return paused``.
    """
    if not pause_store(request.app).read().paused:
        return None
    return JSONResponse(
        status_code=503,
        content={"error": "chat_paused", "message": PAUSED_MESSAGE, "tel": HELP_LINE},
        headers={"Cache-Control": "no-store"},
    )
