"""Read-only API for source-verified İstanbulkart troubleshooting flows."""

from __future__ import annotations

import datetime as dt
import logging
import os
import sqlite3
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request

from ibb_mcp.knowledge import open_from_env
from nabiz.console.operator import port_problem
from nabiz.console.troubleshoot import FRESHNESS_ENV, QUOTES_ENV, flows_payload, load_contact, load_flows

log = logging.getLogger(__name__)
troubleshoot_routes = APIRouter()
ISTANBUL = ZoneInfo("Europe/Istanbul")
UNREADABLE = "İstanbulkart adımları şu an yüklenemedi."


def _open_store(request: Request):
    """Reuse an app index or open the configured local index once."""
    store = getattr(request.app.state, "knowledge_store", None)
    if store is None:
        try:
            store, embedder = open_from_env()
        except sqlite3.Error as exc:
            log.warning("istanbulkart index open failed: %s", type(exc).__name__)
            store, embedder = None, None
        request.app.state.knowledge_store = store
        request.app.state.knowledge_embedder = embedder
    return store


def _index_details(store) -> tuple[str, str | None]:
    if store is None:
        return "missing", None
    try:
        built_at = store.index_built_at()
    except sqlite3.Error as exc:
        log.warning("istanbulkart index check failed: %s", type(exc).__name__)
        return "empty", None
    return ("ready" if built_at else "empty"), built_at


def _freshness() -> float:
    try:
        return max(0.0, float(os.environ.get(FRESHNESS_ENV, "31536000")))
    except ValueError:
        return 31_536_000.0


@troubleshoot_routes.get("/api/istanbulkart/flows")
async def get_istanbulkart_flows(request: Request):
    """Return a public, parameter-free flow; no user answers are accepted or stored.

    The reviewed-quote gate is enabled by default because it only checks whether fixed,
    reviewed sentences remain on their own current source pages; it performs no search.
    """
    try:
        flows = load_flows()
        load_contact()
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        return port_problem(500, "istanbulkart_flows_unreadable", UNREADABLE)
    enabled = os.environ.get(QUOTES_ENV, "1") != "0"
    store = _open_store(request)
    state, built_at = _index_details(store)
    day = dt.datetime.now(ISTANBUL).date().isoformat()
    cache_key = (built_at, day, enabled)
    cached = getattr(request.app.state, "ikart_cache", None)
    if cached is not None and cached[0] == cache_key:
        return cached[1]
    try:
        payload = flows_payload(store, now=dt.datetime.now(dt.UTC), max_age_s=_freshness(), quotes_enabled=enabled)
    except sqlite3.Error as exc:
        log.warning("istanbulkart quote check failed: %s", type(exc).__name__)
        payload = flows_payload(None, now=dt.datetime.now(dt.UTC), max_age_s=_freshness(), quotes_enabled=enabled)
        state, built_at = ("empty", built_at)
    payload["index"] = {"state": state, "built_at": built_at}
    log.info("istanbulkart flows quotes=%d/%d index=%s", len(payload["quotes"]), len(flows["quotes"]), state)
    request.app.state.ikart_cache = (cache_key, payload)
    return payload
