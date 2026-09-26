# Ported from DOU-Synapse apps/api/app/modules/ingestion/parsers.py (github.com/muratcan-ates/DOU-Synapse @ 2cbe1ea, MIT, Copyright (c) 2026 Muratcan Ates)  # noqa: E501
"""Static HTML and text-based PDF parsers for approved source pages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO

from .chunking import PageBlock

_DISALLOWED_TAGS = frozenset({"script", "style", "nav", "header", "footer", "aside", "form"})
#: Page-form mode (below): the page-wrapping ``<form>`` is read, its controls are not.
_PAGE_FORM_DISALLOWED = (_DISALLOWED_TAGS - {"form"}) | {"select", "textarea", "button", "label"}
_VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"})
#: A page-form page must yield at least this much text, or it stays ``unsupported_js``.
PAGE_FORM_MIN_CHARS = 200


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

    def __init__(self, *, page_form: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        # page_form: ASP.NET WebForms pages wrap the whole body in one <form> (E39, Şehir Hatları).
        # In this mode that form is read, and boilerplate the strict mode never reached is dropped:
        # list items made only of link text (menus, breadcrumbs) and a cookie-consent container.
        self.page_form = page_form
        self.disallowed = _PAGE_FORM_DISALLOWED if page_form else _DISALLOWED_TAGS
        self.form_seen = False
        self.skip_tag = ""
        self.skip_nesting = 0
        self.link_depth = 0
        self.current_plain = False
        self.block_in_li = False
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
        link_list_item = self.page_form and self.block_in_li and not self.current_plain
        if value and not link_list_item:
            self.blocks.append(PageBlock(value, section_title=self.section or None))
        self.current.clear()
        self.current_tag = ""
        self.current_plain = False

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
            self.block_in_li = tag == "li"
        if tag == "tr":
            self.current = []
            self.current_tag = "tr"
        elif tag in {"td", "th"} and self.current:
            self.current.append(" | ")
        elif tag == "br":
            self.current.append(" ")

    def _skipping(self, tag: str, attrs: list[tuple[str, str | None]], *, start: bool) -> bool:
        """Page-form mode: skip a cookie-consent container, counting nested tags of its own name."""
        if self.skip_tag:
            if tag == self.skip_tag:
                self.skip_nesting += 1 if start else -1
                if not self.skip_nesting:
                    self.skip_tag = ""
            return True
        if not (start and self.page_form and not self.ignore_depth) or tag in _VOID_TAGS:
            return False
        marks = " ".join(value or "" for key, value in attrs if key in {"id", "class"}).casefold()
        if "cookie" in marks:
            self.skip_tag, self.skip_nesting = tag, 1
            return True
        return False

    def _embedded_markdown(self, attrs: list[tuple[str, str | None]]) -> None:
        """Nuxt pages (İSKİ) carry the page body as HTML in ``<vue-markdown source='...'>``, not as text."""
        source = dict(attrs).get("source") or ""
        if not source.strip():
            return
        self._flush()
        child = _TextParser(page_form=self.page_form)
        child.section = self.section
        child.feed(source if "<" in source else "".join(f"<p>{line}</p>" for line in source.splitlines()))
        child._flush()
        self.blocks.extend(child.blocks)
        self.section = child.section

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._skipping(tag, attrs, start=True):
            return
        self.form_seen = self.form_seen or tag == "form"
        if tag in self.disallowed:
            self.ignore_depth += 1
            return
        if self.ignore_depth:
            return
        if tag == "a":
            self.link_depth += 1
        elif tag == "vue-markdown":
            self._embedded_markdown(attrs)
        elif tag == "meta":
            self._handle_metadata(attrs)
        elif tag == "title":
            self.in_title = True
        elif tag in {"h1", "h2", "h3"}:
            self._flush()
            self.block_in_li = False
            self.current_tag = tag
        else:
            self._handle_content_start(tag)
        self.tag_stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._skipping(tag, [], start=False):
            return
        if tag in self.disallowed:
            self.ignore_depth = max(0, self.ignore_depth - 1)
            return
        if self.ignore_depth:
            return
        if tag == "a":
            self.link_depth = max(0, self.link_depth - 1)
        elif tag == "title":
            self.in_title = False
        else:
            self._close_block(tag)
        if tag in self.tag_stack:
            self.tag_stack.remove(tag)

    def _close_block(self, tag: str) -> None:
        if tag in {"h1", "h2", "h3"}:
            heading = clean_text("".join(self.current))
            if heading:
                self.section = heading
            self.current.clear()
            self.current_tag = ""
        elif tag in {"p", "li"}:
            self._flush()
            self.block_in_li = False
        elif tag == "tr":
            value = clean_text("".join(self.current))
            if value:
                self.blocks.append(PageBlock(value, section_title=self.section or None, table_rows=(value,)))
            self.current.clear()
            self.current_tag = ""

    def handle_data(self, data: str) -> None:
        if self.ignore_depth or self.skip_tag:
            return
        if not self.in_title and not self.link_depth and data.strip():
            self.current_plain = True
        if self.in_title:
            self.title_parts.append(data)
        elif self.current_tag:
            self.current.append(data)
        elif data.strip():
            self.current.extend((data, " "))


def _parse(document: str, *, page_form: bool) -> tuple[_TextParser, tuple[PageBlock, ...]]:
    parser = _TextParser(page_form=page_form)
    parser.feed(document)
    parser._flush()
    return parser, tuple(block for block in parser.blocks if len(block.text.strip()) > 1)


def html_to_blocks(document: str, url: str = "") -> ParsedPage:
    """Parse static HTML with the standard library; JS-only pages are reported.

    Forms are skipped. When that leaves nothing and the page had a ``<form>``, the page is read
    again in page-form mode (the ASP.NET WebForms shell wraps every page in one form); that reading
    counts only if it yields ``PAGE_FORM_MIN_CHARS`` of text. Pages the strict reading accepts are
    unchanged, so their stored bodies and embeddings stay valid.
    """
    del url  # URL is intentionally not used to fetch or resolve page-supplied links.
    parser, blocks = _parse(document, page_form=False)
    if not blocks and parser.form_seen:
        page_parser, page_blocks = _parse(document, page_form=True)
        if sum(len(block.text) for block in page_blocks) >= PAGE_FORM_MIN_CHARS:
            parser, blocks = page_parser, page_blocks
    title = clean_text("".join(parser.title_parts))
    return ParsedPage(
        blocks,
        title,
        "ok" if blocks else "unsupported_js",
        parser.source_updated_at,
        "meta" if parser.source_updated_at else "unknown",
    )


def pdf_to_blocks(content: bytes) -> list[PageBlock]:
    """Extract PDF text with BSD pypdf only; Poppler (GPL) is never called.

    Without pypdf the row reports ``skipped`` rather than falling back to a GPL tool, so the licence stays
    visible in the ingest report instead of silently changing with what the machine has installed.
    """
    try:
        import pypdf
    except ImportError as exc:
        raise KnowledgeUnavailable("pypdf kurulu değil; PDF atlandı.", parser_status="skipped") from exc
    try:
        reader = pypdf.PdfReader(BytesIO(content))
        blocks = [PageBlock(t, page_number=n) for n, p in enumerate(reader.pages, 1) if (t := clean_text(p.extract_text() or ""))]
    except Exception as exc:  # noqa: BLE001 - pypdf's own errors vary by version
        raise KnowledgeUnavailable("PDF okunamadı.", parser_status="unsupported_pdf") from exc
    if not blocks:
        raise KnowledgeUnavailable("PDF'te okunur metin yok.", parser_status="unsupported_pdf")
    return blocks
