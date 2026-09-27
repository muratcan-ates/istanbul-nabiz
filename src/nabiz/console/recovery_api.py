"""Read-only public endpoint for source-verified digital access steps."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sqlite3
from typing import Any

from fastapi import APIRouter, Request

from ibb_mcp.knowledge import open_from_env
from nabiz.console import recovery
from nabiz.console.operator import port_problem
from nexus_core.stats import ISTANBUL

log = logging.getLogger("nabiz.console.recovery_api")
recovery_routes = APIRouter()


def _open_store(request: Request):
    """Reuse the app index or open it once using the shared local-index settings."""
    store = getattr(request.app.state, "knowledge_store", None)
    if store is None:
        try:
            store, embedder = open_from_env()
        except sqlite3.Error as exc:
            log.warning("recovery index open failed: %s", type(exc).__name__)
            store, embedder = None, None
        request.app.state.knowledge_store = store
        request.app.state.knowledge_embedder = embedder
    return store


def _index_state(request: Request, store: Any) -> tuple[Any, dict[str, Any]]:
    if store is None:
        return None, {"state": "missing", "built_at": None}
    try:
        built_at = store.index_built_at()
    except sqlite3.Error as exc:
        log.warning("recovery index check failed: %s", type(exc).__name__)
        request.app.state.knowledge_store = None
        return None, {"state": "missing", "built_at": None}
    return store, {"state": "ready" if built_at else "empty", "built_at": built_at}


def _max_age_s() -> float:
    try:
        return float(os.environ.get(recovery.FRESHNESS_ENV, "31536000"))
    except ValueError:
        return 31_536_000


def _quotes_enabled() -> bool:
    return os.environ.get(recovery.QUOTES_ENV, "1") != "0"


def _capture_metadata(path, security_url: str) -> dict[str, Any]:
    data, captured_at = {}, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        captured_at = data.get("captured_at") if isinstance(data, dict) else None
        stamp = dt.datetime.fromisoformat(captured_at.replace("Z", "+00:00")) if isinstance(captured_at, str) else None
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        stamp = None
    ok = stamp is not None and data.get("schema") == 1 and security_url in recovery.load_capture(path)
    return {"state": "ok" if ok else "missing", "captured_at": captured_at if ok else None}


@recovery_routes.get("/api/erisim/flows")
async def recovery_flow_payload(request: Request):
    """Return the local decision tree; only verified public sentences are enabled by default.

    Quick-question chips default closed because they search and select knowledge answers. This
    route defaults open because it returns only pre-reviewed verbatim sentences that still occur
    on their own fresh, allowlisted source page; it performs no search and accepts no answer data.
    """
    try:
        flows = recovery.load_recovery_flows()
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        return port_problem(500, "recovery_flows_unreadable", "Erişim adımları şu an yüklenemedi.")

    store, index = _index_state(request, _open_store(request))
    capture_status = _capture_metadata(recovery.CAPTURE_PATH, flows["sources"]["g_guvenlik"]["url"])
    capture = recovery.load_capture(recovery.CAPTURE_PATH)
    enabled = _quotes_enabled()
    istanbul_day = dt.datetime.now(ISTANBUL).date().isoformat()
    cache_key = (index["built_at"], capture_status["captured_at"], istanbul_day, enabled)
    cached = getattr(request.app.state, "erisim_cache", None)
    if cached is not None and cached[0] == cache_key:
        return cached[1]

    try:
        payload = recovery.recovery_flows_payload(
            store, capture, now=dt.datetime.now(dt.UTC), max_age_s=_max_age_s(), quotes_enabled=enabled,
        )
    except sqlite3.Error as exc:
        log.warning("recovery index lookup failed: %s", type(exc).__name__)
        request.app.state.knowledge_store = None
        store = None
        index = {"state": "missing", "built_at": None}
        payload = recovery.recovery_flows_payload(
            None, capture, now=dt.datetime.now(dt.UTC), max_age_s=_max_age_s(), quotes_enabled=enabled,
        )
        cache_key = (index["built_at"], capture_status["captured_at"], istanbul_day, enabled)

    payload["index"] = index
    payload["capture"] = capture_status
    request.app.state.erisim_cache = (cache_key, payload)
    log.info(
        "recovery flows quotes=%d/%d index=%s capture=%s",
        len(payload["quotes"]), len(flows["quotes"]), index["state"], capture_status["state"],
    )
    return payload
