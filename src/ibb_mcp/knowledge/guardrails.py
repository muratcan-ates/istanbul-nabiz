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
_CITY_HOST = "ibb" + ".istanbul"
#: The one reviewed host list: ingest fetches from it and evidence is verified against it
#: (``ingest.ALLOWLIST`` is this object), so the two can never drift apart.
DEFAULT_ALLOWLIST = frozenset(
    {
        _GOV_HOST,
        "www." + _GOV_HOST,
        _CITY_HOST,
        "www." + "iski" + ".istanbul",
        "iett" + ".istanbul",
        "www." + "metro" + ".istanbul",
        "metro" + ".istanbul",
        "ispark" + ".istanbul",
        "data." + _GOV_HOST,
        "istanbulsenin.istanbul",
        "istanbulkart.istanbul",
        # Q2 (owner's decision E): the card's public site, exact host only; its subdomains are not reviewed.
        "www." + "istanbulkart" + ".istanbul",
        "sehirhatlari.istanbul",
        "spor.istanbul",
    }
)
#: Municipal domains whose subdomains count as reviewed, when the domain itself is in the list.
#: Q1 (owner's decision A): the city domain joins the government one, for the 12 service subdomains in the seed.
ALLOWED_SUFFIXES: tuple[str, ...] = (_GOV_HOST, _CITY_HOST)

_TAG = re.compile(r"<[^>]*>")
_SCRIPT = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_ELEVEN_DIGITS = re.compile(r"(?<!\d)\d{11}(?!\d)")


@dataclass(frozen=True, slots=True)
class EvidenceValidation:
    """The IDs that failed a source, freshness or retrieval check."""

    blocked: bool
    dropped: list[str]


def host_allowed(host: str, allowlist: Iterable[str] = DEFAULT_ALLOWLIST) -> bool:
    """Exact reviewed host, or a subdomain of a suffix that is itself in the list."""
    host = host.lower().rstrip(".")
    allowed = {item.lower().rstrip(".") for item in allowlist}
    if host in allowed:
        return True
    return any(host.endswith("." + suffix) and suffix in allowed for suffix in ALLOWED_SUFFIXES)


def _host_allowed(url: str, allowlist: Iterable[str]) -> bool:
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return False
    return bool(host) and host_allowed(host, allowlist)


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
