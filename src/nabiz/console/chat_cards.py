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
CARD_ACTIONS = (
    "use_location", "type_place", "expand_map", "listen", "remember_here", "remember_always",
    "change", "forget", "save_calendar", "export_ics", "review_report", "send", "open_official",
)
FRESHNESS = ("guncel", "kayitli", "tarife", "dogrulanamadi")
MAX_CARDS = 6
_MAX_ITEMS = 20
_MAX_DEPTH = 6
_DROP_TAGS = frozenset({"script", "style", "template", "iframe", "object", "svg"})
_BAD_KEYS = frozenset({"__proto__", "prototype", "constructor"})


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


def _body_value(value: Any, depth: int = 0) -> Any:
    if depth > _MAX_DEPTH:
        return None
    if isinstance(value, str):
        return _text(value, 600)
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, list | tuple):
        return [_body_value(item, depth + 1) for item in value[:_MAX_ITEMS]]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if len(out) >= _MAX_ITEMS:
                break
            name = _text(key, 120)
            if name and name not in _BAD_KEYS:
                out[name] = _body_value(item, depth + 1)
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
        label = _text(raw.get("label"), 120)
        if not label:
            continue
        when = _date(raw.get("source_time"))
        freshness = raw.get("freshness")
        sources.append({
            "label": label,
            "url": _https_url(raw.get("url")),
            "source_time": when.isoformat(timespec="seconds") if when else None,
            "freshness": freshness if freshness in FRESHNESS else "dogrulanamadi",
        })
    return sources


def _stable_id(kind: str, title: str, linked_id: str | None) -> str:
    value = f"{kind}\0{title}\0{linked_id or ''}".encode()
    digest = 0x811C9DC5
    for byte in value:
        digest = ((digest ^ byte) * 0x01000193) & 0xFFFFFFFF
    return f"card-{kind}-{digest:08x}"


def validate_card(raw: Any) -> dict[str, Any] | None:
    """Return a safe ChatCard v1, or None when its identity cannot be trusted."""
    if not isinstance(raw, dict) or type(raw.get("v")) is not int or raw["v"] != 1:
        return None
    kind = raw.get("type")
    title = _text(raw.get("title"), 120)
    if kind not in CARD_TYPES or not title:
        return None

    linked_id = _text(raw.get("linked_id"), 120) or None
    card_id = _text(raw.get("id"), 120) or _stable_id(kind, title, linked_id)
    sources = _sources(raw.get("sources"))
    dates = [item for item in [_date(raw.get("source_time")), *(_date(src["source_time"]) for src in sources)] if item]
    oldest = min(dates).isoformat(timespec="seconds") if dates else None
    status = raw.get("status")
    if status not in CARD_STATUSES:
        status = "unavailable"

    actions: list[str] = []
    proposed = raw.get("actions")
    if isinstance(proposed, list | tuple):
        for action in proposed:
            if action in CARD_ACTIONS and action not in actions and (
                action != "open_official" or any(source["url"] for source in sources)
            ):
                actions.append(action)
    sensitive = raw.get("sensitive") is True
    if sensitive or raw.get("status") not in CARD_STATUSES:
        actions = []

    body = _body_value(raw.get("body"))
    return {
        "v": 1,
        "id": card_id,
        "conversation_id": _text(raw.get("conversation_id"), 120) or None,
        "message_id": _text(raw.get("message_id"), 120) or None,
        "type": kind,
        "status": status,
        "title": title,
        "body": body if isinstance(body, dict) else {},
        "sources": sources,
        "source_time": oldest,
        "linked_id": linked_id,
        "actions": actions,
        "sensitive": sensitive,
    }


def card(  # noqa: PLR0913 - public ChatCard builder signature is part of the v1 contract
    type: str,
    title: str,
    *,
    body: dict[str, Any] | None = None,
    sources: Iterable[dict[str, Any]] = (),
    status: str = "ready",
    linked_id: str | None = None,
    actions: Iterable[str] = (),
    sensitive: bool = False,
    card_id: str | None = None,
) -> dict[str, Any]:
    """Build one validated card for a trusted feature producer."""
    result = validate_card({
        "v": 1, "id": card_id, "type": type, "title": title, "body": body,
        "sources": list(sources or ()), "status": status, "linked_id": linked_id,
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
