"""Map answer sentences to their evidence without deciding which source is right."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from typing import Any

from ibb_mcp.text import normalize_tr

from .answer import UNKNOWN_TEXT, KnowledgeAnswer, lexical_coverage
from .retrieve import Hit
from .store import KnowledgeStore

SUPPORT_COVERAGE = 0.5
CONFLICT_COVERAGE = 0.7

LABELS = {
    "tr": {
        "verbatim": "Birebir alıntı",
        "lexical": "Sözcüklerle destekleniyor",
        "no_source": "Bu cümle için kaynak henüz yok",
        "source_line": "Kaynak satırı",
        "referral": "Yönlendirme",
        "date_meta": "Sayfa tarihi sayfanın meta verisinden",
        "date_heuristic": "Sayfa tarihi tahmini",
        "date_unknown": "Sayfa tarih vermiyor",
        "conflict": "İki kaynak farklı değer veriyor; hangisinin geçerli olduğu doğrulanmadı. 153'e sorun.",
    },
    "en": {
        "verbatim": "Verbatim quote",
        "lexical": "Supported by wording",
        "no_source": "No source yet for this sentence",
        "source_line": "Source line",
        "referral": "Referral",
        "date_meta": "Page date from the page's metadata",
        "date_heuristic": "Page date is an estimate",
        "date_unknown": "The page gives no date",
        "conflict": "Two sources give different values; which one applies has not been verified. Ask 153.",
    },
}

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_URL = re.compile(r"https?://[^\s()]+", re.IGNORECASE)
_SOURCE_MARKER = re.compile(r"Kaynak:\s*https?://", re.IGNORECASE)
_CURRENCY = re.compile(r"(?<![\w/])\d+(?:[.,]\d+)?\s*(?:TL|₺)(?!\w)", re.IGNORECASE)
_DATE = re.compile(r"(?<!\d)\d{1,2}\.\d{1,2}\.\d{4}(?!\d)")
_TIME = re.compile(r"(?<!\d)\d{1,2}[:.]\d{2}(?!\d)")
_PERCENT = re.compile(r"(?<![\w/])(?:\d+(?:[.,]\d+)?\s*%|%\s*\d+(?:[.,]\d+)?)(?!\w)")
_NUMBER = re.compile(r"(?<![\w/])\d+(?:[.,]\d+)?(?![\w/])")
_DEFAULT_FRESHNESS_SLA_S = 31_536_000.0
_CALL_NUMBERS = {"112", "153", "185", "187"}


def labels(lang: str) -> dict[str, str]:
    """Return the supported display labels, falling back to Turkish."""
    return dict(LABELS.get(lang, LABELS["tr"]))


def _split_regular(text: str) -> list[dict[str, str]]:
    return [{"text": part.strip(), "kind": "claim"} for part in _SENTENCE_END.split(text.strip()) if part.strip()]


def split_sentences(text: str) -> list[dict[str, str]]:
    """Split answer text while preserving citation lines and their following referral text."""
    result: list[dict[str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        while line:
            marker = _SOURCE_MARKER.search(line)
            if marker:
                source_start = marker.start()
                prefix = line[:source_start].strip()
                if prefix:
                    result.extend(_split_regular(prefix))
                line = line[source_start:]
                marker = line.find(").")
                end = marker + 2 if marker >= 0 else len(line)
                result.append({"text": line[:end].strip(), "kind": "source_line"})
                line = line[end:].strip()
            else:
                result.extend(_split_regular(line))
                break
    return result


def support_for(sentence: str, citations: tuple[Hit, ...] | list[Hit]) -> list[dict[str, Any]]:
    """Return source matches for one sentence, ordered by measured coverage."""
    normalized_sentence = normalize_tr(sentence)
    support: list[dict[str, Any]] = []
    for index, hit in enumerate(citations):
        normalized_quote = normalize_tr(hit.quote)
        if normalized_sentence and normalized_sentence in normalized_quote:
            match = "verbatim"
            coverage = 1.0
        else:
            coverage = lexical_coverage(sentence, [hit])
            if coverage < SUPPORT_COVERAGE:
                continue
            match = "lexical"
        support.append(
            {"citation": index, "quote_id": hit.quote_id, "match": match, "coverage": round(coverage, 6)}
        )
    return sorted(support, key=lambda item: (-item["coverage"], item["citation"]))


def value_tokens(text: str) -> set[str]:
    """Extract comparable monetary, time, date, percentage and numeric values."""
    url_spans = [match.span() for match in _URL.finditer(text)]
    selected: list[tuple[int, int, str, str]] = []
    occupied: list[tuple[int, int]] = []
    for pattern, kind in ((_CURRENCY, "currency"), (_DATE, "date"), (_TIME, "time"), (_PERCENT, "percent")):
        for match in pattern.finditer(text):
            if _overlaps(match.span(), url_spans) or _overlaps(match.span(), occupied):
                continue
            selected.append((*match.span(), kind, match.group()))
            occupied.append(match.span())
    for match in _NUMBER.finditer(text):
        if _overlaps(match.span(), url_spans) or _overlaps(match.span(), occupied):
            continue
        if match.group() in _CALL_NUMBERS and re.fullmatch(r"\d{3}", match.group()):
            continue
        selected.append((*match.span(), "number", match.group()))
        occupied.append(match.span())
    return {_normalize_value(kind, value) for _, _, kind, value in selected}


def _overlaps(span: tuple[int, int], others: list[tuple[int, int]]) -> bool:
    return any(span[0] < end and start < span[1] for start, end in others)


def _normalize_value(kind: str, value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value.strip())
    if kind == "currency":
        amount, unit = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(TL|₺)", cleaned, re.IGNORECASE).groups()
        return f"{amount.replace(',', '.')} {unit.upper()}"
    if kind == "percent":
        return f"{cleaned.replace(' ', '').removeprefix('%')}%"
    if kind == "time":
        return cleaned.replace(".", ":")
    if kind == "number":
        return cleaned.replace(",", ".")
    return cleaned


def _parse_datetime(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def source_freshness(
    hit: Hit,
    *,
    store: KnowledgeStore | None,
    now: datetime,
    sla_s: float,
) -> dict[str, Any]:
    """Expose stored source dates and their age; unparseable dates remain unknown."""
    method = None
    if store is not None:
        quote = store.get_quote(hit.quote_id)
        document = store.document(quote["document_id"]) if quote and quote.get("document_id") else None
        method = document.get("updated_at_method", "unknown") if document else "unknown"
    fetched = _parse_datetime(hit.fetched_at)
    age = _utc(now) - fetched if fetched is not None else None
    return {
        "fetched_at": hit.fetched_at,
        "source_updated_at": hit.source_updated_at,
        "updated_at_method": method,
        "age_days": age.days if age is not None else None,
        "stale": age.total_seconds() > sla_s if age is not None else None,
    }


def _freshness_sla() -> float:
    try:
        value = float(os.environ.get("NABIZ_KNOWLEDGE_FRESHNESS_SLA_S", _DEFAULT_FRESHNESS_SLA_S))
    except (TypeError, ValueError):
        return _DEFAULT_FRESHNESS_SLA_S
    return value if value >= 0 else _DEFAULT_FRESHNESS_SLA_S


def _source_url(source_line: str) -> str | None:
    match = _URL.search(source_line)
    return match.group().rstrip(".,;:") if match else None


def _source_index(source_line: str, citations: tuple[Hit, ...], cursor: int) -> int | None:
    url = _source_url(source_line)
    if url is None:
        return None
    for indices in (range(cursor, len(citations)), range(0, cursor)):
        for index in indices:
            if citations[index].url == url:
                return index
    return None


def _newer(left: Hit, right: Hit, left_index: int, right_index: int) -> int | None:
    left_date = _parse_datetime(left.source_updated_at)
    right_date = _parse_datetime(right.source_updated_at)
    if left_date is not None and right_date is not None:
        return left_index if left_date > right_date else right_index if right_date > left_date else None
    if left.source_updated_at or right.source_updated_at:
        return None
    left_fetch = _parse_datetime(left.fetched_at)
    right_fetch = _parse_datetime(right.fetched_at)
    if left_fetch is None or right_fetch is None:
        return None
    return left_index if left_fetch > right_fetch else right_index if right_fetch > left_fetch else None


def find_conflicts(sentences: list[dict[str, Any]], citations: tuple[Hit, ...] | list[Hit]) -> list[dict[str, Any]]:
    """Flag distinct values found in different documents supporting the same claim."""
    conflicts: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for sentence in sentences:
        if sentence.get("kind") != "claim" or sentence.get("status") != "supported":
            continue
        supports = sentence.get("support", [])
        for left_pos, left_support in enumerate(supports):
            left_index = left_support["citation"]
            if left_support["coverage"] < CONFLICT_COVERAGE:
                continue
            for right_support in supports[left_pos + 1 :]:
                right_index = right_support["citation"]
                if right_support["coverage"] < CONFLICT_COVERAGE or citations[left_index].url == citations[right_index].url:
                    continue
                pair = (min(left_index, right_index), max(left_index, right_index))
                if pair in seen:
                    continue
                left_values = value_tokens(citations[left_index].quote)
                right_values = value_tokens(citations[right_index].quote)
                if not left_values or not right_values or left_values & right_values:
                    continue
                seen.add(pair)
                if left_index > right_index:
                    left_values, right_values = right_values, left_values
                conflicts.append(
                    {
                        "sentence": sentence["i"],
                        "between": list(pair),
                        "kind": "value",
                        "values": [sorted(left_values), sorted(right_values)],
                        "newer": _newer(citations[pair[0]], citations[pair[1]], pair[0], pair[1]),
                    }
                )
    return conflicts


def _empty_summary() -> dict[str, int]:
    return {"sentences": 0, "supported": 0, "no_source": 0, "referral": 0, "sources": 0, "conflicts": 0, "stale": 0}


def citation_map(
    answer: KnowledgeAnswer,
    *,
    store: KnowledgeStore | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Map each answer sentence to source evidence and observed source dates."""
    checked_moment = _utc(now or datetime.now(UTC))
    checked_at = checked_moment.isoformat()
    if answer.mode == "unknown" or normalize_tr(answer.text) == normalize_tr(UNKNOWN_TEXT):
        return {
            "mode": "unknown",
            "author": answer.author,
            "note": "unknown",
            "sentences": [],
            "sources": [],
            "conflicts": [],
            "summary": _empty_summary(),
            "checked_at": checked_at,
        }

    citations = answer.citations
    sentences: list[dict[str, Any]] = []
    source_cursor = 0
    for index, part in enumerate(split_sentences(answer.text)):
        text, kind = part["text"], part["kind"]
        if kind == "source_line":
            citation = _source_index(text, citations, source_cursor)
            if citation is not None:
                source_cursor = citation + 1
            sentences.append(
                {"i": index, "text": text, "kind": kind, "status": "n/a", "support": [], "citation": citation, "conflict": None}
            )
            continue
        support = support_for(text, citations)
        sentence_kind = "claim" if support else "referral" if "153" in text else "claim"
        status = "supported" if support else "n/a" if sentence_kind == "referral" else "no_source"
        sentences.append(
            {"i": index, "text": text, "kind": sentence_kind, "status": status, "support": support, "conflict": None}
        )

    conflicts = find_conflicts(sentences, citations)
    for conflict_index, conflict in enumerate(conflicts):
        sentences[conflict["sentence"]]["conflict"] = conflict_index

    sources: list[dict[str, Any]] = []
    for index, hit in enumerate(citations):
        freshness = source_freshness(hit, store=store, now=checked_moment, sla_s=_freshness_sla())
        linked = [
            sentence["i"]
            for sentence in sentences
            if any(item["citation"] == index for item in sentence["support"])
            or sentence.get("citation") == index
        ]
        sources.append(
            {
                "citation": index,
                "quote_id": hit.quote_id,
                "url": hit.url,
                "title": hit.title,
                "institution": hit.institution,
                **freshness,
                "sentences": linked,
            }
        )

    summary = {
        "sentences": len(sentences),
        "supported": sum(sentence["status"] == "supported" for sentence in sentences),
        "no_source": sum(sentence["status"] == "no_source" for sentence in sentences),
        "referral": sum(sentence["kind"] == "referral" for sentence in sentences),
        "sources": len(sources),
        "conflicts": len(conflicts),
        "stale": sum(source["stale"] is True for source in sources),
    }
    return {
        "mode": answer.mode,
        "author": answer.author,
        "note": None,
        "sentences": sentences,
        "sources": sources,
        "conflicts": conflicts,
        "summary": summary,
        "checked_at": checked_at,
    }
