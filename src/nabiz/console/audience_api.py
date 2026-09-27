"""Device-local age and needs suggestions for the citizen console."""

from __future__ import annotations

import json
import logging
import os
import pathlib
import re
import sqlite3
from functools import lru_cache
from urllib.parse import urlsplit

from fastapi import APIRouter, Request

from ibb_mcp.knowledge import answer, open_from_env
from nabiz.console.operator import port_problem

log = logging.getLogger("nabiz.console.audience")
audience_routes = APIRouter()
CATALOG_PATH = pathlib.Path(__file__).resolve().parents[3] / "data" / "knowledge" / "audience_suggestions.json"
GROUP_KINDS = frozenset({"yas", "ihtiyac"})
SUGGESTION_KINDS = {"arac": "tool", "kurum": "agency", "bilgi": "knowledge", "sayfa": "page"}
PROFILE_NEEDS = frozenset({"step_free", "low_vision", "hearing", "plain_language"})
IDENTIFIER = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_catalog(data: object) -> None:
    """Reject malformed audience data before it reaches either the API or a page."""
    _require(isinstance(data, dict), "catalog must be an object")
    _require(set(data) == {"version", "gruplar", "oneriler", "kisayollar"}, "catalog keys are invalid")
    _require(type(data["version"]) is int and data["version"] == 1, "catalog version is invalid")
    groups, suggestions, shortcuts = data["gruplar"], data["oneriler"], data["kisayollar"]
    _require(
        isinstance(groups, list) and isinstance(suggestions, list) and isinstance(shortcuts, list), "catalog rows must be lists"
    )

    group_ids: set[str] = set()
    suggestion_ids: set[str] = set()
    shortcut_ids: set[str] = set()
    suggestion_fields = {
        "arac": {"id", "tur", "arac", "metin_tr", "metin_en"},
        "kurum": {"id", "tur", "kurum", "metin_tr", "metin_en"},
        "bilgi": {"id", "tur", "eval_id", "metin_tr", "metin_en", "source_url"},
        "sayfa": {"id", "tur", "url", "metin_tr", "metin_en"},
    }
    for row in groups:
        _require(
            isinstance(row, dict) and set(row) == {"id", "tur", "oneriler", "kisayollar", "profil", "kolay"},
            "group shape is invalid",
        )
        _require(isinstance(row["id"], str) and IDENTIFIER.fullmatch(row["id"]) is not None, "group id is invalid")
        _require(row["id"] not in group_ids, "group id is repeated")
        _require(isinstance(row["tur"], str) and row["tur"] in GROUP_KINDS, "group kind is invalid")
        _require(
            all(isinstance(row[key], list) for key in ("oneriler", "kisayollar", "profil")), "group references must be lists"
        )
        _require(
            all(isinstance(value, str) for key in ("oneriler", "kisayollar", "profil") for value in row[key]),
            "group references must be text",
        )
        _require(set(row["profil"]) <= PROFILE_NEEDS and len(row["profil"]) == len(set(row["profil"])), "profile need is invalid")
        _require(isinstance(row["kolay"], bool), "easy-screen flag is invalid")
        group_ids.add(row["id"])

    for row in suggestions:
        _require(
            isinstance(row, dict) and isinstance(row.get("tur"), str) and row["tur"] in suggestion_fields,
            "suggestion kind is invalid",
        )
        _require(set(row) == suggestion_fields[row["tur"]], "suggestion shape is invalid")
        _require(isinstance(row["id"], str) and IDENTIFIER.fullmatch(row["id"]) is not None, "suggestion id is invalid")
        _require(row["id"] not in suggestion_ids, "suggestion id is repeated")
        _require(isinstance(row["metin_tr"], str) and 0 < len(row["metin_tr"]) <= 90, "Turkish suggestion text is invalid")
        if row["tur"] == "bilgi":
            _require(row["metin_en"] is None and isinstance(row["eval_id"], str), "knowledge suggestion fields are invalid")
            _require(
                isinstance(row["source_url"], str) and row["source_url"].startswith("https://"), "knowledge source is invalid"
            )
        else:
            _require(isinstance(row["metin_en"], str) and 0 < len(row["metin_en"]) <= 90, "English suggestion text is invalid")
        if row["tur"] == "sayfa":
            _require(isinstance(row["url"], str), "page URL is invalid")
            parts = urlsplit(row["url"])
            _require(parts.scheme == "https" and bool(parts.netloc), "page URL is invalid")
        else:
            key = "arac" if row["tur"] == "arac" else "kurum" if row["tur"] == "kurum" else "eval_id"
            _require(isinstance(row[key], str) and bool(row[key]), "suggestion target is invalid")
        suggestion_ids.add(row["id"])

    for row in shortcuts:
        _require(
            isinstance(row, dict) and set(row) == {"id", "hedef", "dosya", "metin_tr", "metin_en"}, "shortcut shape is invalid"
        )
        _require(isinstance(row["id"], str) and row["id"] == row["hedef"], "shortcut id is invalid")
        _require(row["id"] not in shortcut_ids, "shortcut id is repeated")
        _require(
            all(isinstance(row[key], str) and 0 < len(row[key]) <= 90 for key in ("dosya", "metin_tr", "metin_en")),
            "shortcut text is invalid",
        )
        shortcut_ids.add(row["id"])

    _require(bool(groups) and bool(suggestions) and bool(shortcuts), "catalog must not be empty")
    _require(
        all(set(row["oneriler"]) <= suggestion_ids and set(row["kisayollar"]) <= shortcut_ids for row in groups),
        "group target is unknown",
    )
    _require(all(any(row["id"] in group["oneriler"] for group in groups) for row in suggestions), "unreferenced suggestion")
    _require(all(any(row["id"] in group["kisayollar"] for group in groups) for row in shortcuts), "unreferenced shortcut")


@lru_cache(maxsize=1)
def load_audience_catalog() -> dict:
    """Load and validate the reviewed catalog once per process."""
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    validate_catalog(data)
    return data


def _same_audience_page(left: str, right: str) -> bool:
    """Compare source pages while preserving meaningful query strings."""
    first, second = urlsplit(left), urlsplit(right)
    first_key = (first.scheme.lower(), first.netloc.lower(), first.path.rstrip("/"), first.query)
    second_key = (second.scheme.lower(), second.netloc.lower(), second.path.rstrip("/"), second.query)
    return first_key == second_key


def _open_audience_store(request: Request):
    state = request.app.state
    store = getattr(state, "knowledge_store", None)
    if store is None:
        try:
            store, embedder = open_from_env()
        except sqlite3.Error as exc:
            log.warning("audience index open failed: %s", type(exc).__name__)
            store, embedder = None, None
        state.knowledge_store = store
        state.knowledge_embedder = embedder
    return store


def _audience_index_state(store) -> tuple[str, str | None, bool]:
    if store is None:
        return "missing", None, False
    try:
        built_at = store.index_built_at()
    except sqlite3.Error as exc:
        log.warning("audience index check failed: %s", type(exc).__name__)
        return "empty", None, True
    return ("ready" if built_at is not None else "empty"), built_at, False


async def _verified_audience_items(catalog: dict, store, enabled: bool) -> tuple[set[str], bool]:
    if not enabled:
        return set(), False
    shown: set[str] = set()
    try:
        for item in catalog["oneriler"]:
            if item["tur"] != "bilgi":
                continue
            result = await answer(item["metin_tr"], store=store, embedder=None, sensitive=False)
            if result.mode == "answer" and any(_same_audience_page(hit.url, item["source_url"]) for hit in result.citations):
                shown.add(item["id"])
    except sqlite3.Error as exc:
        log.warning("audience evidence lookup failed: %s", type(exc).__name__)
        return set(), True
    return shown, False


def _audience_payload(catalog: dict, state: str, built_at: str | None, enabled: bool, shown: set[str]) -> dict:
    visible = [item for item in catalog["oneriler"] if item["tur"] != "bilgi" or item["id"] in shown]
    visible_ids = {item["id"] for item in visible}
    suggestions = [
        {"id": item["id"], "kind": SUGGESTION_KINDS[item["tur"]], "text_tr": item["metin_tr"],
         "text_en": item["metin_en"], "url": item.get("url")}
        for item in visible
    ]
    groups = [
        {
            "id": group["id"], "kind": "age" if group["tur"] == "yas" else "need",
            "suggestions": [key for key in group["oneriler"] if key in visible_ids],
            "shortcuts": group["kisayollar"], "profile": group["profil"], "kolay": group["kolay"],
        }
        for group in catalog["gruplar"]
    ]
    return {
        "version": 1,
        "groups": groups,
        "suggestions": suggestions,
        "shortcuts": [{"id": item["id"], "target": item["hedef"], "text_tr": item["metin_tr"],
                       "text_en": item["metin_en"]} for item in catalog["kisayollar"]],
        "index": {"state": state, "built_at": built_at, "knowledge_enabled": enabled},
        "counts": {"listed": len(catalog["oneriler"]), "shown": len(visible), "knowledge_shown": len(shown)},
    }


@audience_routes.get("/api/audience")
async def audience_suggestions(request: Request):
    """Return the same catalog to every visitor, filtering knowledge by local evidence only."""
    try:
        catalog = load_audience_catalog()
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return port_problem(500, "audience_catalog_unreadable", "Öneriler şu an yüklenemedi.")
    store = _open_audience_store(request)
    index_state, built_at, index_failed = _audience_index_state(store)
    enabled = index_state == "ready" and os.environ.get("NABIZ_QUICK_KNOWLEDGE") == "1"
    cached = getattr(request.app.state, "audience_cache", None)
    if not index_failed and cached is not None and cached[:2] == (built_at, enabled):
        return cached[2]

    shown, evidence_failed = await _verified_audience_items(catalog, store, enabled and not index_failed)
    payload = _audience_payload(catalog, index_state, built_at, enabled, shown)
    if not index_failed and not evidence_failed:
        request.app.state.audience_cache = (built_at, enabled, payload)
    return payload
