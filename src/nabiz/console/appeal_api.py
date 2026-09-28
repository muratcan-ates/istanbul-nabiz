"""Unbound appeal routes. P00 must attach trusted identity and a durable provider."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictBool, ValidationError

from nabiz.console.access import OperatorAccess
from nabiz.console.appeals import APPEAL_REASONS, DECISION_REASONS, AppealBook
from nabiz.console.operator import port_problem
from nabiz.console.restriction import validate_subject

appeal_routes = APIRouter()


class AppealBody(BaseModel):
    category: Literal["mistake", "shared_device", "other"]
    consent: StrictBool
    operation_id: str = Field(pattern=r"^op-[0-9a-f]{16}$")


class AppealDecisionBody(BaseModel):
    action: Literal["reopen", "uphold"]
    reason: str


def _provider(request: Request) -> AppealBook | JSONResponse:
    book = getattr(request.app.state, "appeal_book", None)
    if not isinstance(book, AppealBook):
        return port_problem(503, "not_wired", "İtiraz kaydı henüz bağlı değil.")
    return book


def _subject(request: Request) -> str | JSONResponse:
    resolver: Callable[[Request], str] | None = getattr(request.app.state, "restriction_subject", None)
    if not callable(resolver):
        return port_problem(503, "not_wired", "Güvenilir oturum henüz bağlı değil.")
    try:
        subject = resolver(request)
        # The book validates the shape; a client header is never read here.
        return validate_subject(subject)
    except (TypeError, ValueError):
        return port_problem(401, "session_required", "İtiraz için oturum gerekli.")


def _operator(request: Request) -> JSONResponse | None:
    access = getattr(request.app.state, "access", None)
    if not isinstance(access, OperatorAccess) or access.token is None:
        return port_problem(401, "unauthorized", "Operatör belirteci gerekli.")
    return access.refusal(request)


@appeal_routes.get("/api/restriction")
async def restriction_status(request: Request) -> JSONResponse:
    subject = _subject(request)
    if isinstance(subject, JSONResponse):
        return subject
    book = _provider(request)
    if isinstance(book, JSONResponse):
        return book
    active = await asyncio.to_thread(book.restrictions.current, subject)
    return JSONResponse({"restricted": active is not None, "restriction": active.public() if active else None},
                        headers={"Cache-Control": "no-store"})


@appeal_routes.post("/api/appeals")
async def submit_appeal(request: Request, body: AppealBody) -> JSONResponse:
    if not body.consent:
        return port_problem(400, "consent_required", "İtirazı göndermek için onay gerekli.")
    subject = _subject(request)
    if isinstance(subject, JSONResponse):
        return subject
    book = _provider(request)
    if isinstance(book, JSONResponse):
        return book
    try:
        appeal = await asyncio.to_thread(book.submit, subject, body.category)
    except ValueError as exc:
        return port_problem(409, "no_restriction", str(exc))
    return JSONResponse(appeal.citizen_view(), status_code=202, headers={"Cache-Control": "no-store"})


@appeal_routes.get("/api/appeals/{appeal_id}")
async def appeal_status(request: Request, appeal_id: str) -> JSONResponse:
    subject = _subject(request)
    if isinstance(subject, JSONResponse):
        return subject
    book = _provider(request)
    if isinstance(book, JSONResponse):
        return book
    try:
        appeal = await asyncio.to_thread(book.for_subject, appeal_id, subject)
    except LookupError:
        return port_problem(404, "not_found", "İtiraz bulunamadı.")
    return JSONResponse(appeal.citizen_view(), headers={"Cache-Control": "no-store"})


@appeal_routes.get("/api/console/appeals")
async def appeal_queue(request: Request) -> JSONResponse:
    if (refusal := _operator(request)) is not None:
        return refusal
    book = _provider(request)
    if isinstance(book, JSONResponse):
        return book
    queue = await asyncio.to_thread(book.queue)
    return JSONResponse({"appeals": [item.citizen_view() for item in queue], "reasons": DECISION_REASONS,
                         "categories": APPEAL_REASONS}, headers={"Cache-Control": "no-store"})


@appeal_routes.post("/api/console/appeals/{appeal_id}/decision")
async def appeal_decision(request: Request, appeal_id: str) -> JSONResponse:
    if (refusal := _operator(request)) is not None:
        return refusal
    try:
        body = AppealDecisionBody.model_validate(await request.json())
    except (json.JSONDecodeError, TypeError, ValidationError):
        return port_problem(422, "invalid_request", "İstek geçersiz: karar ve gerekçe gerekli.")
    book = _provider(request)
    if isinstance(book, JSONResponse):
        return book
    try:
        appeal = await asyncio.to_thread(book.decide, appeal_id, action=body.action, reason=body.reason)
    except LookupError:
        return port_problem(404, "not_found", "İtiraz bulunamadı.")
    except RuntimeError as exc:
        return port_problem(409, "already_decided", str(exc))
    except ValueError as exc:
        return port_problem(400, "reason_required", str(exc))
    return JSONResponse(appeal.citizen_view(), headers={"Cache-Control": "no-store"})
