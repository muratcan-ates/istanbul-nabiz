# Ported from DOU-Synapse apps/api/app/modules/ingestion/chunking.py (github.com/muratcan-ates/DOU-Synapse @ 2cbe1ea, MIT, Copyright (c) 2026 Muratcan Ates)  # noqa: E501
"""Character-bounded, page-safe chunks and exact sentence evidence."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass

TARGET_CHARS_MIN = 1800
TARGET_CHARS_MAX = 2400
HARD_MAX_CHARS = 3200
OVERLAP_CHARS_MIN = 250
OVERLAP_CHARS_MAX = 350
CHARS_PER_TOKEN = 3.0  # Turkish estimate for telemetry only; not measured.


@dataclass(frozen=True, slots=True)
class PageBlock:
    """A text block that belongs to one source page and section."""

    text: str
    page_number: int | None = None
    section_title: str | None = None
    table_rows: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class QuoteSpan:
    """A verbatim sentence span, with offsets into the unnormalised block text."""

    exact_text: str
    char_start: int
    char_end: int
    quote_id: str


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    """A bounded chunk and the sentence evidence contained in it."""

    text: str
    char_start: int
    char_end: int
    page_number: int | None
    section_title: str | None
    token_estimate: int
    content_hash: str
    quotes: tuple[QuoteSpan, ...]


_SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+|\n{2,}")


def estimate_tokens(text: str) -> int:
    """Return a deliberately rough Turkish token estimate for telemetry."""
    return max(1, round(len(text) / CHARS_PER_TOKEN))


def _split_units(text: str) -> list[tuple[int, int]]:
    """Split at paragraphs and sentence boundaries, retaining original offsets."""
    units: list[tuple[int, int]] = []
    cursor = 0
    ranges = []
    for paragraph in re.finditer(r"\n[ \t\r]*\n+", text):
        ranges.append((cursor, paragraph.start()))
        cursor = paragraph.end()
    ranges.append((cursor, len(text)))
    for raw_start, raw_end in ranges:
        start, end = raw_start, raw_end
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start >= end:
            continue
        cursor = start
        for match in _SENTENCE_END.finditer(text, start, end):
            if text[cursor : match.start()].strip():
                units.append((cursor, match.start()))
            cursor = match.end()
        if text[cursor:end].strip():
            units.append((cursor, end))
    return units or ([(0, len(text))] if text else [])


def _split_long_unit(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Split an overlong sentence on whitespace without exceeding the hard cap."""
    result: list[tuple[int, int]] = []
    cursor = start
    while end - cursor > HARD_MAX_CHARS:
        boundary = text.rfind(" ", cursor, cursor + HARD_MAX_CHARS + 1)
        if boundary <= cursor:
            boundary = cursor + HARD_MAX_CHARS
        result.append((cursor, boundary))
        cursor = boundary
        while cursor < end and text[cursor].isspace():
            cursor += 1
    if cursor < end:
        result.append((cursor, end))
    return result


def _pack_units(text: str, units: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Pack sentence units near the character target and carry sentence overlap."""
    pieces: list[tuple[int, int]] = []
    for start, end in units:
        pieces.extend(_split_long_unit(text, start, end))
    groups: list[tuple[int, int]] = []
    index = 0
    while index < len(pieces):
        first = index
        start = pieces[first][0]
        end = pieces[first][1]
        index += 1
        while index < len(pieces):
            candidate_end = pieces[index][1]
            size = candidate_end - start
            if size > TARGET_CHARS_MAX and end - start >= TARGET_CHARS_MIN:
                break
            if size > HARD_MAX_CHARS:
                break
            end = candidate_end
            index += 1
        groups.append((start, end))
        if index >= len(pieces):
            break
        overlap_start = index - 1
        overlap_chars = 0
        while overlap_start > first and overlap_chars < OVERLAP_CHARS_MIN:
            overlap_start -= 1
            overlap_chars = pieces[index - 1][1] - pieces[overlap_start][0]
        if overlap_chars > OVERLAP_CHARS_MAX and overlap_start < index - 1:
            overlap_start += 1
        index = max(first + 1, overlap_start)
    return groups


def _group_blocks(blocks: Iterable[PageBlock]) -> list[PageBlock]:
    """Join adjacent paragraphs in one page section while keeping table boundaries."""
    grouped: list[PageBlock] = []
    for block in blocks:
        if grouped:
            previous = grouped[-1]
            same_source_section = (
                previous.page_number == block.page_number
                and previous.section_title == block.section_title
                and bool(previous.table_rows) == bool(block.table_rows)
            )
            if same_source_section:
                rows = previous.table_rows + block.table_rows
                grouped[-1] = PageBlock(f"{previous.text}\n\n{block.text}", previous.page_number, previous.section_title, rows)
                continue
        grouped.append(block)
    return grouped


def chunk_blocks(blocks: Iterable[PageBlock]) -> list[KnowledgeChunk]:
    """Chunk each page and section separately; source offsets remain exact."""
    chunks: list[KnowledgeChunk] = []
    for block in _group_blocks(blocks):
        text = block.text
        units: list[tuple[int, int]] = []
        if block.table_rows:
            cursor = 0
            for row in block.table_rows:
                at = text.find(row, cursor)
                if at < 0:
                    continue
                units.append((at, at + len(row)))
                cursor = at + len(row)
        else:
            units = _split_units(text)
        quote_units = [piece for unit_start, unit_end in units for piece in _split_long_unit(text, unit_start, unit_end)]
        for start, end in _pack_units(text, units):
            chunk_text = text[start:end]
            spans = []
            for q_start, q_end in quote_units:
                if q_start < start or q_end > end:
                    continue
                exact = text[q_start:q_end].strip()
                if exact:
                    absolute_start = q_start + len(text[q_start:q_end]) - len(text[q_start:q_end].lstrip())
                    absolute_end = absolute_start + len(exact)
                    quote_id = hashlib.sha256(f"{absolute_start}:{absolute_end}:{exact}".encode()).hexdigest()[:24]
                    spans.append(QuoteSpan(exact, absolute_start, absolute_end, quote_id))
            chunks.append(
                KnowledgeChunk(
                    text=chunk_text,
                    char_start=start,
                    char_end=end,
                    page_number=block.page_number,
                    section_title=block.section_title,
                    token_estimate=estimate_tokens(chunk_text),
                    content_hash=hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
                    quotes=tuple(spans),
                )
            )
    return chunks
