"""Evidence-gated quick questions for the citizen console."""

from __future__ import annotations

import json
import logging
import os
import pathlib
import sqlite3
from functools import lru_cache
from urllib.parse import urlsplit

from fastapi import APIRouter, Request

from ibb_mcp.knowledge import answer, open_from_env
from nabiz.console.operator import port_problem

log = logging.getLogger(__name__)
quick_routes = APIRouter()
QUESTIONS_PATH = pathlib.Path(__file__).resolve().parents[3] / "data" / "knowledge" / "quick_questions.json"
#: Chips shown without the knowledge index: a live tool answers, or the institution router (/api/agency) does.
ALWAYS_SHOWN = frozenset({"live", "agency"})


@lru_cache(maxsize=1)
def load_questions() -> dict:
    """Load the reviewed quick-question catalog once per process."""
    return json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))


def _same_page(a: str, b: str) -> bool:
    """Compare source pages without folding their query strings."""
    left, right = urlsplit(a), urlsplit(b)
    return (
        left.scheme.lower(), left.netloc.lower(), left.path.rstrip("/"), left.query
    ) == (
        right.scheme.lower(), right.netloc.lower(), right.path.rstrip("/"), right.query
    )


def _payload(questions: dict, state: str, built_at: str | None, enabled: bool, shown: set[str]) -> dict:
    """Build the public response in catalog order, omitting empty categories."""
    grouped = {category["id"]: [] for category in questions["kategoriler"]}
    for item in questions["sorular"]:
        if item["kind"] in ALWAYS_SHOWN or item["id"] in shown:
            grouped[item["kategori"]].append(
                {
                    "id": item["id"],
                    "kind": item["kind"],
                    "text_tr": item["soru_tr"],
                    "text_en": item["soru_en"],
                    "source_url": item["source_url"],
                }
            )
    categories = [
        {
            "id": category["id"],
            "label_tr": category["ad_tr"],
            "label_en": category["ad_en"],
            "chips": grouped[category["id"]],
        }
        for category in questions["kategoriler"]
        if grouped[category["id"]]
    ]
    live_count = sum(item["kind"] == "live" for item in questions["sorular"])
    agency_count = sum(item["kind"] == "agency" for item in questions["sorular"])
    knowledge_count = sum(item["kind"] == "knowledge" for item in questions["sorular"])
    return {
        "categories": categories,
        "index": {"state": state, "built_at": built_at, "knowledge_enabled": enabled},
        "counts": {
            "live": live_count, "agency": agency_count, "knowledge_listed": knowledge_count, "knowledge_shown": len(shown),
        },
    }


def _open_store(request: Request):
    """Reuse the app index or open it once using the shared local-index settings."""
    store = getattr(request.app.state, "knowledge_store", None)
    if store is None:
        try:
            store, embedder = open_from_env()
        except sqlite3.Error as exc:
            log.warning("quick index open failed: %s", type(exc).__name__)
            store, embedder = None, None
        request.app.state.knowledge_store = store
        request.app.state.knowledge_embedder = embedder
    return store


def _index_details(store) -> tuple[str, str | None, bool]:
    """Read the index generation and mark a damaged database unusable for chips."""
    if store is None:
        return "missing", None, False
    try:
        built_at = store.index_built_at()
    except sqlite3.Error as exc:
        log.warning("quick index check failed: %s", type(exc).__name__)
        return "empty", None, True
    return ("ready" if built_at is not None else "empty"), built_at, False


async def _verified_chips(questions: dict, store, enabled: bool) -> set[str]:
    """Keep only questions whose verified answer cites the configured source page."""
    if not enabled:
        return set()
    shown = set()
    try:
        for item in questions["sorular"]:
            if item["kind"] != "knowledge":
                continue
            result = await answer(item["soru_tr"], store=store, embedder=None, sensitive=False)
            if result.mode == "answer" and any(
                _same_page(hit.url, item["source_url"]) for hit in result.citations
            ):
                shown.add(item["id"])
    except sqlite3.Error as exc:
        log.warning("quick evidence lookup failed: %s", type(exc).__name__)
        return set()
    return shown


@quick_routes.get("/api/quick")
async def quick_cards(request: Request):
    """Return live chips and knowledge chips backed by their own source page."""
    try:
        questions = load_questions()
    except (OSError, UnicodeError, json.JSONDecodeError):
        return port_problem(500, "quick_questions_unreadable", "Hazır sorular şu an yüklenemedi.")

    store = _open_store(request)
    index_state, built_at, index_failed = _index_details(store)

    cached = getattr(request.app.state, "quick_cache", None)
    if not index_failed and cached is not None and cached[0] == built_at:
        return cached[1]

    enabled = index_state == "ready" and os.environ.get("NABIZ_QUICK_KNOWLEDGE") == "1"
    shown = await _verified_chips(questions, store, enabled and not index_failed)
    payload = _payload(questions, index_state, built_at, enabled, shown)
    request.app.state.quick_cache = (built_at, payload)
    return payload
