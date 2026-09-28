"""Disconnected calendar router; P00 and P13 must bind its principal and session ports."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from nabiz.console.graph_calendar import GraphCalendar
from nabiz.console.ms_oauth import OAuthConfig, TokenStore
from nabiz.console.operation_ledger import OperationConflict
from nabiz.console.plan_store import PlanNotFound, PlanStore

plans_routes = APIRouter(prefix="/api/plans")


class PlanFields(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    starts_at: str
    ends_at: str
    all_day: bool = False
    time_zone: str = "Europe/Istanbul"
    place: str | None = Field(default=None, max_length=200)
    source_url: str | None = Field(default=None, max_length=2048)
    source_date: str | None = None
    conversation_id: str | None = Field(default=None, max_length=128)


class PlanWrite(PlanFields):
    operation_id: str = Field(min_length=1, max_length=128)
    consent: bool = False
    sensitive: bool = False


class OutlookWrite(BaseModel):
    operation_id: str = Field(min_length=1, max_length=128)
    consent: bool = False
    sensitive: bool = False


def _owner(request: Request) -> str:
    resolver: Callable[[Request], str | None] | None = getattr(request.app.state, "plan_principal", None)
    owner_id = resolver(request) if callable(resolver) else None
    if not owner_id:
        raise HTTPException(503, "Takvim bağlantısı kapalı")
    return owner_id


def _store(request: Request) -> PlanStore:
    store = getattr(request.app.state, "plan_store", None)
    if store is None:
        store = PlanStore.from_env()
        request.app.state.plan_store = store
    return store


def _require_consent(consent: bool, sensitive: bool) -> None:
    if sensitive:
        raise HTTPException(400, "Hassas kart takvime kaydedilemez")
    if not consent:
        raise HTTPException(400, "Açık onay gerekli")


def _fields(body: PlanWrite) -> dict[str, Any]:
    return body.model_dump(include=set(PlanFields.model_fields))


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, PlanNotFound):
        return HTTPException(404, str(exc))
    if isinstance(exc, OperationConflict):
        return HTTPException(409, str(exc))
    return HTTPException(422, str(exc))


@plans_routes.get("")
def list_plans(request: Request) -> dict[str, Any]:
    owner = _owner(request)
    return {"plans": _store(request).list(owner)}


@plans_routes.get("/{plan_id}")
def get_plan(plan_id: str, request: Request) -> dict[str, Any]:
    try:
        owner = _owner(request)
        return {"plan": _store(request).get(owner, plan_id)}
    except PlanNotFound as exc:
        raise _error(exc) from exc


@plans_routes.post("")
def save_plan(body: PlanWrite, request: Request) -> dict[str, Any]:
    _require_consent(body.consent, body.sensitive)
    try:
        owner = _owner(request)
        plan = _store(request).save(owner, body.operation_id, _fields(body))
    except (ValueError, PlanNotFound) as exc:
        raise _error(exc) from exc
    return {"result": "saved_nabiz", "message": "Nabız'a kaydedildi", "plan": plan, "operation_id": body.operation_id}


@plans_routes.patch("/{plan_id}")
def update_plan(plan_id: str, body: PlanWrite, request: Request) -> dict[str, Any]:
    _require_consent(body.consent, body.sensitive)
    try:
        owner = _owner(request)
        plan = _store(request).update(owner, plan_id, body.operation_id, _fields(body))
    except (ValueError, PlanNotFound) as exc:
        raise _error(exc) from exc
    return {"result": "saved_nabiz", "message": "Nabız'a kaydedildi", "plan": plan, "operation_id": body.operation_id}


@plans_routes.post("/{plan_id}/outlook")
def add_outlook(plan_id: str, body: OutlookWrite, request: Request) -> dict[str, Any]:
    _require_consent(body.consent, body.sensitive)
    owner = _owner(request)
    store = _store(request)
    try:
        plan = store.get(owner, plan_id)
        operation = store.outlook_operation(owner, plan_id, body.operation_id)
    except (ValueError, PlanNotFound) as exc:
        raise _error(exc) from exc
    if operation.state in {"added", "failed"}:
        return {**operation.result, "operation_id": body.operation_id}
    config = OAuthConfig.from_env()
    tokens: TokenStore | None = getattr(request.app.state, "plan_tokens", None)
    token = tokens.get(owner) if tokens else None
    if config is None or not token:
        result = {"result": "outlook_failed", "message": "Outlook bağlantısı kapalı", "event_id": None}
        return {**result, "operation_id": body.operation_id}
    client: httpx.Client | None = getattr(request.app.state, "plan_graph_client", None)
    if client is None:
        result = {"result": "outlook_failed", "message": "Outlook bağlantısı kapalı", "event_id": None}
        return {**result, "operation_id": body.operation_id}
    result = GraphCalendar(client).add(plan, body.operation_id, token).as_dict()
    state = {"outlook_added": "added", "outlook_failed": "failed"}.get(result["result"], "verifying")
    store.set_outlook_result(owner, body.operation_id, state, result)
    return {**result, "operation_id": body.operation_id}
