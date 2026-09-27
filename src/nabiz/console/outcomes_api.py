"""Operator-only API for the five outcome measures and aggregate snapshots."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from nabiz.console import outcomes
from nabiz.console.citizen_requests import REPLY_KIND, REQUEST_KIND
from nexus_core.engine import NexusEngine

log = logging.getLogger("nabiz.console.outcomes")
outcome_board_routes = APIRouter(prefix="/api/console")
_store_lock = threading.Lock()
_NO_STORE = {"Cache-Control": "no-store"}


def _response(status: int, payload: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status, content=payload, headers=_NO_STORE)


def _store(app: Any) -> outcomes.SnapshotStore:
    store = getattr(app.state, "outcome_snapshots", None)
    if store is not None:
        return store
    with _store_lock:
        store = getattr(app.state, "outcome_snapshots", None)
        if store is None:
            store = outcomes.SnapshotStore()
            app.state.outcome_snapshots = store
    return store


def _sources(app: Any, days: int, now: Any) -> dict[str, Any]:
    port = getattr(getattr(app.state, "ports", None), "console", None)
    engine = getattr(port, "engine", None)
    engine = engine if isinstance(engine, NexusEngine) else None
    desk = getattr(app.state, "request_desk", None)
    desk_ledger = getattr(desk, "ledger", None)
    engine_ledger = getattr(engine, "ledger", None)
    desk_has_separate_ledger = desk_ledger is not None and (
        engine_ledger is None or getattr(desk_ledger, "path", None) != getattr(engine_ledger, "path", None)
    )
    request_ledger = desk_ledger if desk_has_separate_ledger else engine_ledger
    entries = request_ledger.entries(kinds=[REQUEST_KIND, REPLY_KIND]) if request_ledger is not None else None
    states = list(engine.states().values()) if engine is not None else None
    return outcomes.board(
        entries=entries, states=states, timeline_rows=outcomes.read_timeline(),
        fidelity_md=outcomes.read_fidelity(), now=now, days=days,
    )


def _measured_count(data: dict[str, Any]) -> int:
    return sum(metric["status"] == "measured" for group in data["groups"] for metric in group["metrics"])


@outcome_board_routes.get("/outcomes")
async def get_outcome_board(request: Request) -> JSONResponse:
    """Read a board and the last saved totals for one supported window."""
    raw_days = request.query_params.get("days", str(outcomes.DEFAULT_WINDOW))
    if raw_days not in {str(day) for day in outcomes.WINDOWS}:
        return _response(400, {"error": "bad_request", "message": "Pencere 7 ya da 30 gün olmalı."})
    days = int(raw_days)
    store = await asyncio.to_thread(_store, request.app)
    now = store.now()
    data = await asyncio.to_thread(_sources, request.app, days, now)
    previous, next_save = await asyncio.gather(
        asyncio.to_thread(store.latest, days), asyncio.to_thread(store.next_save_at)
    )
    log.info("outcome board days=%s measured=%s", days, _measured_count(data))
    return _response(200, {
        "board": data, "previous": previous,
        "can_save": next_save is None or now >= next_save,
        "next_save_at": next_save.isoformat() if next_save else None,
    })


@outcome_board_routes.post("/outcomes/snapshot")
async def save_outcome_snapshot(request: Request) -> JSONResponse:
    """Recompute and save totals; the caller may choose a window but never supply measurements."""
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        body = None
    if not isinstance(body, dict) or set(body) != {"days"} or type(body.get("days")) is not int:
        return _response(422, {"error": "bad_request", "message": "Yalnız 7 ya da 30 günlük pencere seçilebilir."})
    days = body["days"]
    if days not in outcomes.WINDOWS:
        return _response(422, {"error": "bad_request", "message": "Pencere 7 ya da 30 gün olmalı."})
    store = await asyncio.to_thread(_store, request.app)
    now = store.now()
    data = await asyncio.to_thread(_sources, request.app, days, now)
    previous = await asyncio.to_thread(store.latest, days)
    try:
        saved = await asyncio.to_thread(store.save, data)
    except outcomes.TooSoon:
        next_save = await asyncio.to_thread(store.next_save_at)
        return _response(429, {
            "error": "too_soon", "message": "Son kayıttan bu yana 5 dakika geçmedi.",
            "next_save_at": next_save.isoformat() if next_save else None,
        })
    log.info("outcome board days=%s measured=%s", days, _measured_count(data))
    return _response(200, {"saved": saved, "board": data, "previous": previous})
