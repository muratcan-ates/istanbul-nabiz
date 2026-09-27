"""Source-pinned visitor questions for the English citizen page."""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
from collections import defaultdict
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

from ibb_mcp.config import REPO_ROOT
from ibb_mcp.knowledge.guardrails import host_allowed
from ibb_mcp.text import looks_like_instruction
from nabiz.console import culture_api
from nabiz.console.culture_api import load_venues

QUESTIONS_PATH = REPO_ROOT / "data" / "knowledge" / "visitor_questions.json"
KINDS = ("museums", "knowledge", "emergency")
MIN_QUESTIONS = 3
MAX_QUESTIONS = 5
QUOTE_MAX = 600
ROLES = ("text", "page_date")
SOURCE_NAMES = {"IETT": "İETT", "METRO_ISTANBUL": "Metro İstanbul", "SEHIR_HATLARI": "Şehir Hatları"}
FRESHNESS_ENV = "NABIZ_KNOWLEDGE_FRESHNESS_SLA_S"
QUOTES_ENV = "NABIZ_VISITOR_QUOTES"
_VISITOR_FORBIDDEN_TEXT = re.compile(r"—|–|\bETA\b|canlı|\blive\b", re.IGNORECASE)
_VISITOR_ID = re.compile(r"^[a-z_]+$")


def normalize(text: str) -> str:
    """Collapse all Unicode whitespace to one ordinary space."""
    return " ".join(text.split())


def _validate_visitor_quote_source(source_url: Any) -> None:
    try:
        host = urlsplit(source_url).hostname if isinstance(source_url, str) else None
    except ValueError:
        host = None
    if not isinstance(source_url, str) or not source_url.startswith("https://") or not host or not host_allowed(host):
        raise ValueError("Quote source must use HTTPS and a reviewed host.")


def _validate_visitor_quote_copy(quote: dict[str, Any], role: str) -> None:
    turkish = quote.get("tr")
    english = quote.get("en")
    if not isinstance(turkish, str) or not turkish.strip() or len(turkish) > QUOTE_MAX or normalize(turkish) != turkish:
        raise ValueError("Turkish quote must be non-empty, normalized and within the length limit.")
    if english is not None and (not isinstance(english, str) or not english.strip()):
        raise ValueError("English quote must be null or a non-empty string.")
    if role == "page_date" and english is None:
        raise ValueError("Page dates need an English translation.")
    for value in (turkish, english):
        if value is not None and _VISITOR_FORBIDDEN_TEXT.search(value):
            raise ValueError("Visitor quote contains forbidden wording or punctuation.")
    if looks_like_instruction(turkish):
        raise ValueError("Visitor quote must not contain instructions.")


def _validate_visitor_quote(quote: Any) -> bool:
    if not isinstance(quote, dict):
        raise ValueError("Each quote must be an object.")
    role = quote.get("role", "text")
    if role not in ROLES:
        raise ValueError("Quote role is not supported.")
    _validate_visitor_quote_source(quote.get("source_url"))
    _validate_visitor_quote_copy(quote, role)
    return role == "text"


def _validate_visitor_question(question: Any, ids: set[str], kind_counts: dict[str, int]) -> None:
    if not isinstance(question, dict):
        raise ValueError("Each visitor question must be an object.")
    question_id, kind = question.get("id"), question.get("kind")
    if not isinstance(question_id, str) or not _VISITOR_ID.fullmatch(question_id) or question_id in ids:
        raise ValueError("Visitor question IDs must be unique lowercase identifiers.")
    ids.add(question_id)
    if kind not in KINDS:
        raise ValueError("Visitor question kind is not supported.")
    kind_counts[kind] += 1
    if kind_counts[kind] > 1 and kind in {"museums", "emergency"}:
        raise ValueError("Museum and emergency questions may appear only once.")
    quotes = question.get("quotes", [])
    if not isinstance(quotes, list):
        raise ValueError("Question quotes must be a list.")
    text_quote_found = False
    for quote in quotes:
        text_quote_found = _validate_visitor_quote(quote) or text_quote_found
    if kind == "knowledge" and not text_quote_found:
        raise ValueError("Knowledge questions need at least one source quote.")


def validate_questions(data: Any) -> list[dict[str, Any]]:
    """Validate the fixed catalog before any of its copy can reach a response."""
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Visitor question catalog must have version 1.")
    questions = data.get("questions")
    if not isinstance(questions, list) or not MIN_QUESTIONS <= len(questions) <= MAX_QUESTIONS:
        raise ValueError("Visitor question catalog must contain three to five questions.")

    ids: set[str] = set()
    kind_counts: dict[str, int] = defaultdict(int)
    for question in questions:
        _validate_visitor_question(question, ids, kind_counts)
    return questions


@lru_cache(maxsize=1)
def load_visitor_questions() -> list[dict[str, Any]]:
    """Load and validate the reviewed visitor-question catalog once per process."""
    data = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    return validate_questions(data)


def _visitor_timestamp(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def verified_sources(
    store: Any,
    question: dict[str, Any],
    *,
    now: dt.datetime,
    max_age_s: float,
) -> list[dict[str, Any]]:
    """Return catalog quotes only when their exact text remains in a fresh active page."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for quote in question.get("quotes", []):
        grouped.setdefault(quote["source_url"], []).append(quote)

    current_time = now.replace(tzinfo=dt.UTC) if now.tzinfo is None else now.astimezone(dt.UTC)
    sources = []
    for url, quotes in grouped.items():
        document = store.current_document(url)
        if not document:
            continue
        fetched = _visitor_timestamp(document.get("fetched_at"))
        if fetched is None or (current_time - fetched).total_seconds() > max_age_s:
            continue
        body = normalize(document.get("body") or "")
        verified_quotes = []
        page_date = None
        for quote in quotes:
            if normalize(quote["tr"]) not in body:
                continue
            if quote.get("role", "text") == "page_date":
                page_date = {"tr": quote["tr"], "en": quote["en"]}
            else:
                verified_quotes.append({"tr": quote["tr"], "en": quote["en"]})
        if not verified_quotes:
            continue
        host = urlsplit(url).hostname or ""
        sources.append(
            {
                "url": url,
                "host": host,
                "name": SOURCE_NAMES.get(document.get("institution"), host),
                "fetched_at": document["fetched_at"],
                "page_date": page_date,
                "quotes": verified_quotes,
            }
        )
    return sources


def knowledge_question(
    store: Any,
    question: dict[str, Any],
    *,
    now: dt.datetime,
    max_age_s: float,
) -> dict[str, Any] | None:
    """Return a knowledge question only while at least one pinned quote survives."""
    sources = verified_sources(store, question, now=now, max_age_s=max_age_s)
    return {"id": question["id"], "kind": "knowledge", "sources": sources} if sources else None


def museum_question() -> dict[str, Any] | None:
    """List only districts represented by the current museum capture."""
    venues, metadata = load_venues(pathlib.Path(culture_api.CULTURE_DIR))
    museum_metadata = metadata.get("museum")
    museums = [venue for venue in venues if venue.kind == "museum" and venue.district]
    if not museum_metadata or not museums:
        return None
    counts: dict[str, int] = defaultdict(int)
    for venue in museums:
        district = culture_api.district_name(venue.district)
        if district:
            counts[district] += 1
    districts = [
        {"name": name, "count": count}
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], culture_api.turkish_order(item[0])))
    ]
    if not districts:
        return None
    return {
        "id": "museums",
        "kind": "museums",
        "districts": districts,
        "captured_at": museum_metadata.get("captured_at"),
        "recorded_at": museum_metadata.get("resource_last_modified"),
    }


def visitor_payload(
    store: Any,
    *,
    now: dt.datetime,
    max_age_s: float,
    quotes_enabled: bool,
) -> dict[str, Any]:
    """Assemble available source-bound questions in the order reviewed in the catalog."""
    questions = []
    for question in load_visitor_questions():
        if question["kind"] == "museums":
            available = museum_question()
        elif question["kind"] == "emergency":
            available = {"id": question["id"], "kind": "emergency"}
        elif quotes_enabled and store is not None:
            available = knowledge_question(store, question, now=now, max_age_s=max_age_s)
        else:
            available = None
        if available is not None:
            questions.append(available)
    return {"questions": questions, "quotes_enabled": quotes_enabled, "disclaimer": culture_api.DISCLAIMER}
