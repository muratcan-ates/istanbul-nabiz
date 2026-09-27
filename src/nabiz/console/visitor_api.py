"""The public source-gated visitor catalog endpoint."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sqlite3
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request

from ibb_mcp.knowledge import open_from_env
from nabiz.console.operator import port_problem
from nabiz.console.visitor import FRESHNESS_ENV, QUOTES_ENV, visitor_payload

log = logging.getLogger(__name__)
visitor_routes = APIRouter()
ISTANBUL = ZoneInfo("Europe/Istanbul")
DEFAULT_FRESHNESS_S = 31_536_000


def _visitor_open_store(request: Request):
    """Reuse the app's index or open it with the shared knowledge configuration."""
    store = getattr(request.app.state, "knowledge_store", None)
    if store is not None:
        return store
    try:
        store, embedder = open_from_env()
    except sqlite3.Error as error:
        log.warning("visitor index open failed: %s", type(error).__name__)
        store, embedder = None, None
    request.app.state.knowledge_store = store
    request.app.state.knowledge_embedder = embedder
    return store


@visitor_routes.get("/api/visitor")
async def get_visitor_questions(request: Request):
    """Return only visitor questions whose reviewed source is still available."""
    store = _visitor_open_store(request)
    built_at = None
    if store is not None:
        try:
            built_at = store.index_built_at()
        except sqlite3.Error as error:
            log.warning("visitor index check failed: %s", type(error).__name__)
            request.app.state.knowledge_store = None
            request.app.state.knowledge_embedder = None
            store = None

    state = "missing" if store is None else "ready" if built_at is not None else "empty"
    quotes_enabled = os.getenv(QUOTES_ENV, "1") != "0"
    today = dt.datetime.now(ISTANBUL).date().isoformat()
    cache_key = (built_at, today, quotes_enabled)
    cached = getattr(request.app.state, "visitor_cache", None)
    if cached and cached[0] == cache_key:
        return cached[1]

    try:
        payload = visitor_payload(
            store,
            now=dt.datetime.now(dt.UTC),
            max_age_s=float(os.getenv(FRESHNESS_ENV, str(DEFAULT_FRESHNESS_S))),
            quotes_enabled=quotes_enabled,
        )
    except sqlite3.Error as error:
        log.warning("visitor index read failed: %s", type(error).__name__)
        request.app.state.knowledge_store = None
        request.app.state.knowledge_embedder = None
        state, built_at = "missing", None
        payload = visitor_payload(None, now=dt.datetime.now(dt.UTC), max_age_s=0, quotes_enabled=quotes_enabled)
        cache_key = (built_at, today, quotes_enabled)
    except (OSError, json.JSONDecodeError, ValueError):
        return port_problem(500, "visitor_questions_unreadable", "Ziyaretçi soruları şu an yüklenemedi.")

    payload["index"] = {"state": state, "built_at": built_at}
    request.app.state.visitor_cache = (cache_key, payload)
    ids = [item["id"] for item in payload["questions"]]
    log.info("visitor questions=%s index=%s", ",".join(ids), state)
    return payload
