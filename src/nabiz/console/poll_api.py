"""Citizen and operator routes for İstanbul'a Sor.

The citizen API never returns voter keys, salts, audit entries or raw counts. Operator routes sit
behind the console access middleware because they share the ``/api/console/`` prefix.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictBool

from ibb_mcp.models import ISTANBUL_TZ
from nabiz.console.citizen_requests import HourlyLimit
from nabiz.console.poll import (
    DISTRICTS,
    MIN_FOR_PERCENT,
    PollStore,
    polls_path,
    validate_draft,
    votes_per_hour,
)
from nabiz.console.quota import DEVICE_ID, address_key
from nabiz.console.wiring import ledger_path
from nexus_core.decisions import REASON_MAX, Operator
from nexus_core.ledger import Ledger

poll_routes = APIRouter()


class PollTarget(BaseModel):
    kind: Literal["all", "district"]
    district: str | None = None


class PollCreateBody(BaseModel):
    question: str = Field(max_length=1000)
    options: list[str] = Field(max_length=5)
    closes_on: str = Field(min_length=10, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$")
    target: PollTarget


class PollPublishBody(BaseModel):
    confirm: StrictBool
    digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class PollVoteBody(BaseModel):
    choice: str


class PollCloseBody(BaseModel):
    reason: str = Field(max_length=REASON_MAX)


class _PollDesk:
    """The app's one poll store, ledger and in-memory address limiter."""

    def __init__(self, store: PollStore, ledger: Ledger, limit: HourlyLimit) -> None:
        self.store = store
        self.ledger = ledger
        self.limit = limit


def poll_desk(app: FastAPI) -> _PollDesk:
    """Build the app's poll services once, following the request desk's state-cache pattern."""
    desk = getattr(app.state, "poll_desk", None)
    if desk is None:
        ledger = Ledger(ledger_path())
        desk = _PollDesk(PollStore(polls_path(), ledger=ledger), ledger, HourlyLimit(votes_per_hour()))
        app.state.poll_desk = desk
    return desk


def _active_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "question": row["question"],
        "options": row["options"],
        "target": row["target"],
        "closes_at": row["closes_at"],
        "simulated": True,
    }


def _operator_view(row: dict[str, Any], result: dict[str, Any] | None = None) -> dict[str, Any]:
    view = {
        "id": row["id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "closes_at": row["closes_at"],
        "expires_at": row["expires_at"],
        "question": row["question"],
        "options": row["options"],
        "target": row["target"],
        "closes_on": row.get("closes_on"),
        "digest": row["digest"],
        "audit": row["audit"],
    }
    if result is not None:
        view["results"] = result
    return view


def _response(status: int, body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status, content=body, headers={"Cache-Control": "no-store"})


def _storage_error() -> JSONResponse:
    return _response(503, {"error": "not_stored", "message": "Anket şu an kaydedilemedi. Biraz sonra yeniden deneyin."})


@poll_routes.get("/api/polls/active")
async def get_active_poll(request: Request) -> JSONResponse:
    try:
        row = poll_desk(request.app).store.active()
    except (OSError, sqlite3.Error):
        return _storage_error()
    return _response(200, {"poll": _active_view(row) if row else None})


@poll_routes.post("/api/polls/{poll_id}/vote")
async def vote_poll(request: Request, body: PollVoteBody, poll_id: str = Path(pattern=r"^[a-f0-9]{32}$")) -> JSONResponse:
    device_id = request.headers.get("x-nabiz-device", "")
    if not DEVICE_ID.fullmatch(device_id):
        return _response(
            400,
            {
                "error": "no_device",
                "message": (
                    "Oy için tarayıcınızın bu siteye küçük bir kayıt tutmasına izin vermesi gerekir. "
                    "Gizli pencerede çalışmayabilir."
                ),
            },
        )
    desk = poll_desk(request.app)
    address = address_key(request.client.host if request.client else None)
    if not desk.limit.allow(address):
        return _response(
            429,
            {
                "error": "too_many_votes",
                "message": f"Bu bağlantıdan bir saatte en çok {desk.limit.limit} oy verilebilir. Biraz sonra yeniden deneyin.",
            },
        )
    try:
        result = desk.store.vote(poll_id, device_id, body.choice)
    except (OSError, sqlite3.Error):
        return _storage_error()
    messages = {
        "ok": (201, {"ok": True, "message": "Oyunuz alındı. Teşekkürler."}),
        "already": (409, {"error": "already_voted", "message": "Bu cihazdan bu ankete zaten oy verildi."}),
        "closed": (404, {"error": "not_found", "message": "Bu anket bitti ya da bulunamadı."}),
        "bad_choice": (400, {"error": "bad_choice", "message": "Bu anket için geçerli bir seçenek seçin."}),
    }
    status, payload = messages[result]
    return _response(status, payload)


@poll_routes.get("/api/console/polls")
async def get_console_polls(request: Request) -> JSONResponse:
    try:
        desk = poll_desk(request.app)
        current = desk.store.current()
        draft = _operator_view(current["draft"]) if current["draft"] else None
        active = None
        last_closed = None
        if current["active"]:
            row = current["active"]
            active = _operator_view(row, desk.store.results(row["id"]))
        else:
            row = desk.store.last_closed()
            last_closed = _operator_view(row, row["results"]) if row else None
        return _response(
            200,
            {
                "draft": draft,
                "active": active,
                "last_closed": last_closed,
                "districts": list(DISTRICTS),
                "min_for_percent": MIN_FOR_PERCENT,
                "read_at": desk.store.now().isoformat(),
            },
        )
    except (OSError, sqlite3.Error):
        return _storage_error()


@poll_routes.post("/api/console/polls")
async def create_poll(request: Request, body: PollCreateBody) -> JSONResponse:
    desk = poll_desk(request.app)
    today = desk.store.now().astimezone(ISTANBUL_TZ).date()
    draft = validate_draft(body.question, body.options, body.closes_on, body.target.model_dump(), today=today)
    if isinstance(draft, str):
        return _response(400, {"error": "invalid", "message": draft})
    try:
        row = desk.store.create_draft(draft, Operator().label)
    except ValueError as exc:
        return _response(409, {"error": "conflict", "message": str(exc)})
    except (OSError, sqlite3.Error):
        return _storage_error()
    return _response(201, {"draft": _operator_view(row)})


@poll_routes.post("/api/console/polls/{poll_id}/publish")
async def publish_poll(
    request: Request,
    body: PollPublishBody,
    poll_id: str = Path(pattern=r"^[a-f0-9]{32}$"),
) -> JSONResponse:
    if body.confirm is not True:
        return _response(400, {"error": "confirm_required", "message": "Yayımlamak için onay kutusunu işaretleyin."})
    desk = poll_desk(request.app)
    try:
        row = desk.store.publish(poll_id, body.digest, Operator().label, desk.ledger)
    except LookupError as exc:
        return _response(404, {"error": "not_found", "message": str(exc)})
    except ValueError as exc:
        return _response(409, {"error": "conflict", "message": str(exc)})
    except (OSError, sqlite3.Error):
        return _response(503, {"error": "not_recorded", "message": "Yayın deftere yazılamadı; anket yayımlanmadı."})
    return _response(200, {"active": _operator_view(row, desk.store.results(poll_id))})


@poll_routes.post("/api/console/polls/{poll_id}/close")
async def close_poll(
    request: Request,
    body: PollCloseBody,
    poll_id: str = Path(pattern=r"^[a-f0-9]{32}$"),
) -> JSONResponse:
    reason = body.reason.strip()
    if not reason:
        return _response(400, {"error": "reason_required", "message": "Anketi bitirmek için gerekçe yazın."})
    desk = poll_desk(request.app)
    try:
        row = desk.store.close(poll_id, reason, Operator().label, desk.ledger)
    except LookupError as exc:
        return _response(404, {"error": "not_found", "message": str(exc)})
    except (OSError, sqlite3.Error):
        return _response(503, {"error": "not_recorded", "message": "Bitiş deftere yazılamadı; anket sürüyor."})
    return _response(200, {"closed": _operator_view(row, row["results"])})


__all__ = ["poll_desk", "poll_routes"]
