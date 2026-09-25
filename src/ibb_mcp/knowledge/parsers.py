# Ported from DOU-Synapse apps/api/app/modules/ingestion/parsers.py (github.com/muratcan-ates/DOU-Synapse @ 2cbe1ea, MIT, Copyright (c) 2026 Muratcan Ates)  # noqa: E501
"""Static HTML and text-based PDF parsers for approved source pages."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from html.parser import HTMLParser

from .chunking import PageBlock

_DISALLOWED_TAGS = frozenset({"script", "style", "nav", "header", "footer", "aside", "form"})


class KnowledgeUnavailable(RuntimeError):
    """A required parser is unavailable or the source format cannot be read."""

    def __init__(self, message: str, *, parser_status: str = "unsupported_pdf") -> None:
        super().__init__(message)
        self.parser_status = parser_status


@dataclass(frozen=True, slots=True)
class ParsedPage:
    """Parser output, including the reason a page was not indexable."""

    blocks: tuple[PageBlock, ...]
    title: str = ""
    parser_status: str = "ok"
    source_updated_at: str | None = None
    updated_at_method: str = "unknown"


def clean_text(text: str) -> str:
    """Normalize line endings and horizontal whitespace without folding Turkish text."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(char for char in text if char in "\n\t" or ord(char) >= 32)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


class _TextParser(HTMLParser):
    """Collect visible prose blocks and preserve headings and table row boundaries."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ignore_depth = 0
        self.tag_stack: list[str] = []
        self.title_parts: list[str] = []
        self.current: list[str] = []
        self.current_tag = ""
        self.section = ""
        self.blocks: list[PageBlock] = []
        self.in_title = False
        self.source_updated_at: str | None = None

    def _flush(self) -> None:
        value = clean_text("".join(self.current))
        if value:
            self.blocks.append(PageBlock(value, section_title=self.section or None))
        self.current.clear()
        self.current_tag = ""

    def _handle_metadata(self, attrs: list[tuple[str, str | None]]) -> None:
        metadata = {key.lower(): value or "" for key, value in attrs}
        name = (metadata.get("property") or metadata.get("name") or metadata.get("itemprop") or "").casefold()
        if name in {"article:modified_time", "datemodified", "dcterms.modified", "last-modified", "modified"}:
            self.source_updated_at = metadata.get("content") or self.source_updated_at

    def _handle_content_start(self, tag: str) -> None:
        if tag not in {"p", "li", "tr", "td", "th", "br"}:
            return
        if tag in {"p", "li", "tr"}:
            self._flush()
        if tag == "tr":
            self.current = []
            self.current_tag = "tr"
        elif tag in {"td", "th"} and self.current:
            self.current.append(" | ")
        elif tag == "br":
            self.current.append(" ")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _DISALLOWED_TAGS:
            self.ignore_depth += 1
            return
        if self.ignore_depth:
            return
        if tag == "meta":
            self._handle_metadata(attrs)
        elif tag == "title":
            self.in_title = True
        elif tag in {"h1", "h2", "h3"}:
            self._flush()
            self.current_tag = tag
        else:
            self._handle_content_start(tag)
        self.tag_stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _DISALLOWED_TAGS:
            self.ignore_depth = max(0, self.ignore_depth - 1)
            return
        if self.ignore_depth:
            return
        if tag == "title":
            self.in_title = False
        elif tag in {"h1", "h2", "h3"}:
            heading = clean_text("".join(self.current))
            if heading:
                self.section = heading
            self.current.clear()
            self.current_tag = ""
        elif tag in {"p", "li"}:
            self._flush()
        elif tag == "tr":
            value = clean_text("".join(self.current))
            if value:
                self.blocks.append(PageBlock(value, section_title=self.section or None, table_rows=(value,)))
            self.current.clear()
            self.current_tag = ""
        if tag in self.tag_stack:
            self.tag_stack.remove(tag)

    def handle_data(self, data: str) -> None:
        if self.ignore_depth:
            return
        if self.in_title:
            self.title_parts.append(data)
        elif self.current_tag:
            self.current.append(data)
        elif data.strip():
            self.current.extend((data, " "))


def html_to_blocks(document: str, url: str = "") -> ParsedPage:
    """Parse static HTML with the standard library; JS-only pages are reported."""
    del url  # URL is intentionally not used to fetch or resolve page-supplied links.
    parser = _TextParser()
    parser.feed(document)
    parser._flush()
    blocks = tuple(block for block in parser.blocks if len(block.text.strip()) > 1)
    title = clean_text("".join(parser.title_parts))
    return ParsedPage(
        blocks,
        title,
        "ok" if blocks else "unsupported_js",
        parser.source_updated_at,
        "meta" if parser.source_updated_at else "unknown",
    )


def pdf_to_blocks(content: bytes) -> list[PageBlock]:
    """Extract PDF text with BSD pypdf, then the system Poppler ``pdftotext`` utility."""
    extracted: list[PageBlock] = []
    try:
        from io import BytesIO

        import pypdf

        reader = pypdf.PdfReader(BytesIO(content))
        for number, page in enumerate(reader.pages, start=1):
            text = clean_text(page.extract_text() or "")
            if text:
                extracted.append(PageBlock(text, page_number=number))
        if extracted:
            return extracted
    except Exception:
        pass
    executable = shutil.which("pdftotext")
    if executable:
        try:
            result = subprocess.run([executable, "-layout", "-", "-"], input=content, capture_output=True, check=True, timeout=30)
            pages = result.stdout.decode("utf-8", errors="replace").split("\f")
            return [PageBlock(clean_text(text), page_number=n) for n, text in enumerate(pages, 1) if clean_text(text)]
        except (OSError, subprocess.SubprocessError):
            pass
    raise KnowledgeUnavailable("No supported PDF text parser is available.", parser_status="unsupported_pdf")
