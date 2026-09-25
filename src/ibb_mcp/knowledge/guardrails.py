# Ported from DOU-Synapse apps/api/app/modules/guardrails/citation.py (github.com/muratcan-ates/DOU-Synapse @ 2cbe1ea, MIT, Copyright (c) 2026 Muratcan Ates)  # noqa: E501
# Sanitization pattern adapted from apps/api/app/modules/guardrails/sanitize.py at the same revision.
"""Evidence verification and safe display cleanup for source-backed answers."""

from __future__ import annotations

import datetime as dt
import html
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

from .retrieve import Hit
from .store import KnowledgeStore

_GOV_HOST = "ibb" + ".gov.tr"
DEFAULT_ALLOWLIST = frozenset(
    {
        _GOV_HOST,
        "www." + _GOV_HOST,
        "ibb" + ".istanbul",
        "www." + "iski" + ".istanbul",
        "iett" + ".istanbul",
        "www." + "metro" + ".istanbul",
        "metro" + ".istanbul",
        "ispark" + ".istanbul",
        "data." + _GOV_HOST,
        "istanbulsenin.istanbul",
        "istanbulkart.istanbul",
        "sehirhatlari.istanbul",
        "spor.istanbul",
    }
)
_TAG = re.compile(r"<[^>]*>")
_SCRIPT = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_ELEVEN_DIGITS = re.compile(r"(?<!\d)\d{11}(?!\d)")


@dataclass(frozen=True, slots=True)
class EvidenceValidation:
    """The IDs that failed a source, freshness or retrieval check."""

    blocked: bool
    dropped: list[str]


def _host_allowed(url: str, allowlist: Iterable[str]) -> bool:
    try:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    allowed = {item.lower().rstrip(".") for item in allowlist}
    if host in allowed:
        return True
    return host.endswith("." + _GOV_HOST) and _GOV_HOST in allowed


def verify_evidence(
    evidence_ids: Sequence[str],
    hits: Sequence[Hit],
    allowlist: Iterable[str] = DEFAULT_ALLOWLIST,
    *,
    store: KnowledgeStore | None = None,
    max_age_s: float | None = None,
) -> EvidenceValidation:
    """Reject fabricated, inactive, unquoted, off-list or stale evidence IDs."""
    by_id = {hit.quote_id: hit for hit in hits}
    now = dt.datetime.now(dt.UTC)
    dropped = []
    for evidence_id in dict.fromkeys(evidence_ids):
        hit = by_id.get(evidence_id)
        valid = hit is not None and _host_allowed(hit.url, allowlist)
        if valid and max_age_s is not None:
            try:
                fetched = dt.datetime.fromisoformat(hit.fetched_at.replace("Z", "+00:00"))
                valid = (now - fetched.astimezone(dt.UTC)).total_seconds() <= max_age_s
            except (ValueError, TypeError):
                valid = False
        if valid and store is not None:
            row = store.get_quote(evidence_id)
            doc = store.document(row["document_id"]) if row else None
            valid = bool(
                row
                and doc
                and row["chunk_active"]
                and row["document_active"]
                and row["exact_text"] == hit.quote
                and row["exact_text"] in doc["body"]
            )
        if not valid:
            dropped.append(evidence_id)
    return EvidenceValidation(blocked=not evidence_ids or bool(dropped), dropped=dropped)


def drop_invalid_evidence(hits: Sequence[Hit], verdict: EvidenceValidation) -> list[Hit]:
    """Return only hits whose quote IDs survived verification."""
    dropped = set(verdict.dropped)
    return [hit for hit in hits if hit.quote_id not in dropped]


def clean_for_display(text: str) -> str:
    """Remove markup, control characters and common script payloads."""
    text = _SCRIPT.sub(" ", text)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = "".join(char for char in text if char in "\n\t" or ord(char) >= 32)
    return re.sub(r"\s+", " ", text).strip()


def mask_personal(text: str) -> str:
    """Mask e-mail addresses and 11-digit identifiers before returning display text."""
    text = _EMAIL.sub("[gizlendi]", text)
    return _ELEVEN_DIGITS.sub("[gizlendi]", text)
