"""Bounded, data-only ChatCard v1 values for the citizen conversation."""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Iterable
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

CARD_TYPES = ("route", "map", "event", "calendar_draft", "photo_report", "status", "info", "memory")
CARD_STATUSES = ("preparing", "needs_input", "ready", "awaiting_confirmation", "done", "unavailable", "error")
ACTION_KIND = {
    "use_location": "device", "type_place": "view", "expand_map": "view", "listen": "view",
    "remember_here": "device", "remember_always": "device", "change": "view", "forget": "device",
    "save_calendar": "nabiz", "export_ics": "device", "review_report": "view", "send": "nabiz",
    "open_official": "external", "add_outlook": "external", "confirm_resolved": "nabiz",
    "reopen": "nabiz", "cancel": "nabiz", "appeal": "nabiz", "share": "external",
}
CARD_ACTIONS = tuple(ACTION_KIND)
CONSENT_ACTIONS = frozenset({
    "use_location", "remember_here", "remember_always", "save_calendar", "send", "add_outlook",
    "confirm_resolved", "reopen", "cancel", "appeal", "share",
})
ACTION_ALIASES = {"add_calendar": "save_calendar", "download_ics": "export_ics",
                  "open_map": "expand_map", "remember": "remember_here"}
CARD_RESULTS = (None, "saved_nabiz", "ics_downloaded", "outlook_verifying", "outlook_added", "outlook_failed",
                "report_sent", "resolution_confirmed", "reopened", "cancelled", "appeal_sent")
RESTORED_ACTIONS = ("expand_map", "listen", "open_official")
FRESHNESS = ("guncel", "kayitli", "tarife", "dogrulanamadi")
MAX_CARDS = 6
_MAX_ITEMS = 20
_DROP_TAGS = frozenset({"script", "style", "template", "iframe", "object", "svg"})
_BAD_KEYS = frozenset({"__proto__", "prototype", "constructor"})
_LINK_PREFIX = {"event_id": "event", "report_code": "report", "operation_id": "op"}


class _PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.dropped = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _DROP_TAGS:
            self.dropped += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP_TAGS and self.dropped:
            self.dropped -= 1

    def handle_data(self, data: str) -> None:
        if not self.dropped:
            self.parts.append(data)


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    parser = _PlainText()
    parser.feed(value[:12_000])
    parser.close()
    plain = " ".join(" ".join(parser.parts).split())
    return plain.replace("<", "").replace(">", "")[:limit]


def _body_value(value: Any, depth: int = 0, item_cap: int = _MAX_ITEMS) -> Any:
    if depth > 6:
        return None
    if isinstance(value, str):
        return _text(value, 600)
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, list | tuple):
        return [_body_value(item, depth + 1) for item in value[:item_cap]]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if len(out) >= _MAX_ITEMS:
                break
            name = _text(key, 120)
            if name and name not in _BAD_KEYS:
                out[name] = _body_value(item, depth + 1, item_cap if depth == 0 and name == "points" else _MAX_ITEMS)
        return out
    return None


def _https_url(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 2_000:
        return None
    url = value.strip()
    if not url or any(char.isspace() or ord(char) < 32 or char in '<>"\'\\' for char in url):
        return None
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            return None
        _ = parts.port
    except ValueError:
        return None
    return url


def _date(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or "T" not in value or len(value) > 50:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _sources(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list | tuple):
        return []
    sources: list[dict[str, Any]] = []
    for raw in value[:_MAX_ITEMS]:
        if not isinstance(raw, dict):
            continue
        if not (label := _text(raw.get("label"), 120)):
            continue
        when = _date(raw.get("source_time"))
        sources.append({"label": label, "url": _https_url(raw.get("url")),
                        "source_time": when.isoformat(timespec="seconds") if when else None,
                        "freshness": raw.get("freshness") if raw.get("freshness") in FRESHNESS
                        else "dogrulanamadi"})
    return sources


def _stable_id(kind: str, title: str, linked_id: str | None) -> str:
    value = f"{kind}\0{title}\0{linked_id or ''}".encode()
    digest = 0x811C9DC5
    for byte in value:
        digest = ((digest ^ byte) * 0x01000193) & 0xFFFFFFFF
    return f"card-{kind}-{digest:08x}"


def _linked(raw: Any, legacy_id: Any) -> tuple[dict[str, str | None], str | None]:
    value = raw if isinstance(raw, dict) else {}
    linked = {key: _text(value.get(key), 120) or None for key in _LINK_PREFIX}
    if sum(value is not None for value in linked.values()) > 1:
        return dict.fromkeys(_LINK_PREFIX), None
    if not any(linked.values()):
        prefix, separator, value = _text(legacy_id, 120).partition(":")
        for key, expected in _LINK_PREFIX.items():
            if separator and prefix == expected and value:
                linked[key] = value
    for key, prefix in _LINK_PREFIX.items():
        if linked[key]:
            return linked, f"{prefix}:{linked[key]}"
    return linked, None


def normalize_action(raw: Any) -> dict[str, Any] | None:
    """Canonicalize a v0/v1 action; producer metadata cannot weaken the table."""
    value = {"id": raw} if isinstance(raw, str) else raw
    if not isinstance(value, dict) or not isinstance(value.get("id"), str):
        return None
    action_id = ACTION_ALIASES.get(value["id"], value["id"])
    kind = ACTION_KIND.get(action_id)
    if kind is None:
        return None
    return {
        "id": action_id, "label": _text(value.get("label"), 40), "kind": kind,
        "requires_consent": action_id in CONSENT_ACTIONS or value.get("requires_consent") is True,
        "operation_id": (_text(value.get("operation_id"), 120) or None)
        if kind in {"nabiz", "external"} else None,
    }


def _v0_source(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    return {"label": raw.get("name") or raw.get("label"), "url": raw.get("url"),
            "source_time": raw.get("observed_at") or raw.get("source_time"), "freshness": raw.get("freshness")}


def from_v0(raw: Any) -> dict[str, Any]:
    """Convert a v0 producer card without losing its linked or action metadata."""
    if not isinstance(raw, dict) or type(raw.get("v")) is not int or raw["v"] != 0:
        raise ValueError("Expected ChatCard v0")
    body = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    more = body.get("sources") if isinstance(body.get("sources"), list | tuple) else []
    sources = [converted for item in [raw.get("source"), *more[:5]]
               if (converted := _v0_source(item)) is not None]
    converted = {**raw, "v": 1, "body": body, "sources": sources}
    checked = validate_card(converted)
    if checked is None:
        raise ValueError("Invalid ChatCard v0 identity")
    return checked


def _actions(
    raw: dict[str, Any], sources: list[dict[str, Any]], restored: bool, sensitive: bool, health: bool,
) -> list[dict[str, Any]]:
    if raw.get("status") not in CARD_STATUSES or not isinstance(raw.get("actions"), list | tuple):
        return []
    actions: list[dict[str, Any]] = []
    for item in raw["actions"][:_MAX_ITEMS]:
        action = normalize_action(item)
        if action is None or any(existing["id"] == action["id"] for existing in actions):
            continue
        if action["id"] == "open_official" and not any(source["url"] for source in sources):
            continue
        if ((restored and action["id"] not in RESTORED_ACTIONS) or (health and action["id"] != "change")
                or (sensitive and (action["kind"] != "view" or action["requires_consent"]))):
            continue
        actions.append(action)
        if len(actions) == 4:
            break
    return actions


def validate_card(raw: Any, *, restored: bool = False) -> dict[str, Any] | None:
    """Return a safe ChatCard v1, or None when its identity cannot be trusted."""
    if isinstance(raw, dict) and type(raw.get("v")) is int and raw["v"] == 0:
        try:
            raw = from_v0(raw)
        except ValueError:
            return None
    if not isinstance(raw, dict) or type(raw.get("v")) is not int or raw["v"] != 1:
        return None
    kind = raw.get("type")
    title = _text(raw.get("title"), 120)
    if kind not in CARD_TYPES or not title:
        return None
    linked, linked_id = _linked(raw.get("linked"), raw.get("linked_id"))
    card_id = _text(raw.get("id"), 120) or _stable_id(kind, title, linked_id)
    sources = _sources(raw.get("sources"))
    dates = [item for item in [_date(raw.get("source_time")), *(_date(src["source_time"]) for src in sources)] if item]
    oldest = min(dates).isoformat(timespec="seconds") if dates else None
    status = raw.get("status") if raw.get("status") in CARD_STATUSES else "unavailable"
    body = _body_value(raw.get("body"), item_cap=60 if kind == "map" else _MAX_ITEMS)
    health = kind == "memory" and isinstance(body, dict) and body.get("kind") == "health"
    sensitive = raw.get("sensitive") is True or health
    actions = _actions(raw, sources, restored, sensitive, health)
    if isinstance(body, dict) and "result" in body and body["result"] not in CARD_RESULTS:
        body["result"] = None
    return {
        "v": 1, "id": card_id, "conversation_id": _text(raw.get("conversation_id"), 120) or None,
        "message_id": _text(raw.get("message_id"), 120) or None,
        "type": kind, "status": status, "title": title, "body": body if isinstance(body, dict) else {},
        "sources": sources, "source_time": oldest, "linked": linked, "linked_id": linked_id,
        "actions": actions, "sensitive": sensitive,
    }


def card(  # noqa: PLR0913 - public builder signature is part of the v1 contract
    type: str, title: str, *, body: dict[str, Any] | None = None,
    sources: Iterable[dict[str, Any]] = (), status: str = "ready",
    linked: dict[str, Any] | None = None, linked_id: str | None = None,
    actions: Iterable[str | dict[str, Any]] = (), sensitive: bool = False, card_id: str | None = None,
) -> dict[str, Any]:
    """Build one validated card for a trusted feature producer."""
    result = validate_card({
        "v": 1, "id": card_id, "type": type, "title": title, "body": body,
        "sources": list(sources or ()), "status": status, "linked": linked, "linked_id": linked_id,
        "actions": list(actions or ()), "sensitive": sensitive,
    })
    if result is None:
        raise ValueError("A card needs a known type and a nonempty title")
    return result


def cards_field(items: Any) -> list[dict[str, Any]]:
    """Bound and deduplicate the cards sent in one final event."""
    if isinstance(items, str | bytes | dict):
        return []
    try:
        iterator = iter(items)
    except TypeError:
        return []
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(iterator):
        if index >= 80 or len(cards) >= MAX_CARDS:
            break
        valid = validate_card(item)
        if valid and valid["id"] not in seen:
            cards.append(valid)
            seen.add(valid["id"])
    return cards
