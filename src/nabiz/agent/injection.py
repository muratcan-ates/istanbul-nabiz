"""What the model may read as conversation, and what a knowledge hit may carry to it.

Two gates in front of the model, both built on :func:`ibb_mcp.text.looks_like_instruction`:

* :func:`safe_context` is the client's history. Only ``user`` and ``assistant`` turns pass, with
  only their text: a ``system``, ``tool`` or ``developer`` turn from a browser would speak with a
  voice the visitor does not have. The console already sends one merged ``user`` message
  (``nabiz.console.chat.context_messages``); this is the second line behind it.
* :func:`screen_tool_payload` is a service-search result. A quoted page that talks to a model is
  dropped before the model sees it, and so is its URL, which would otherwise ride along in
  ``provenance.source_url`` into the answer's "how" panel.

Logs carry counts only: never a question, a history turn, a quote or a URL.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from ibb_mcp.text import looks_like_instruction

#: Earlier turns kept, newest last. The console sends at most one merged message today.
MAX_CONTEXT_MESSAGES = 8
#: Characters kept per turn. The console's merged message is 8 questions of at most 600
#: characters plus a header, about 4.9 thousand, so this cuts nothing it sends today.
MAX_CONTEXT_CHARS = 6000

_CONTEXT_ROLES = frozenset({"user", "assistant"})
_SEARCH_TOOL = "ibb_services_search"
#: The empty-result provenance of ``ibb_services_search`` (``ibb_mcp.knowledge.tool``).
_NO_HIT_SOURCE = "data/knowledge/sources.txt"

log = logging.getLogger(__name__)


def safe_context(context: Sequence[Mapping[str, Any]] | None) -> list[dict[str, str]]:
    """Client history as plain ``user``/``assistant`` text; anything else, or anything instruction-like, is dropped."""
    kept: list[dict[str, str]] = []
    dropped = 0
    for item in context or []:
        role, content = item.get("role"), item.get("content")
        if role not in _CONTEXT_ROLES or not isinstance(content, str) or looks_like_instruction(content):
            dropped += 1
            continue
        kept.append({"role": role, "content": content[:MAX_CONTEXT_CHARS]})
    if dropped:
        log.warning("context: dropped %d message(s)", dropped)
    return kept[-MAX_CONTEXT_MESSAGES:]


def screen_tool_payload(name: str, payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """A service-search payload without the hits whose quote talks to a model; other payloads unchanged."""
    if name != _SEARCH_TOOL or not payload:
        return payload
    data = payload.get("data")
    hits = data.get("hits") if isinstance(data, dict) else None
    if not isinstance(hits, list):
        return payload
    kept = [hit for hit in hits if not (isinstance(hit, dict) and looks_like_instruction(hit.get("quote")))]
    dropped = len(hits) - len(kept)
    if not dropped:
        return payload
    log.warning("knowledge: dropped %d instruction-like hit(s)", dropped)
    screened = {**payload, "data": {**data, "hits": kept, "instruction_like_dropped": dropped}}
    provenance = payload.get("provenance")
    if isinstance(provenance, dict):
        # Recomputed like the tool does (first hit's URL), so a dropped page's URL is gone from the payload.
        first = kept[0].get("url") if kept and isinstance(kept[0], dict) else None
        screened["provenance"] = {**provenance, "source_url": first or _NO_HIT_SOURCE}
    return screened
