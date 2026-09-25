from __future__ import annotations

import asyncio
import hashlib
import json
import pathlib

import httpx
import pytest

from ibb_mcp.http import UpstreamUnavailable
from ibb_mcp.knowledge.ingest import (
    KnowledgeUnavailable,
    Source,
    _write_cache,
    fetch_all,
    html_to_blocks,
    pdf_to_blocks,
)

ALLOW_ROBOTS = "User-agent: *\nAllow: /\n"


class FakeClient:
    def __init__(self, handler=None):
        self.calls = []
        self.handler = handler

    async def request(self, method, url, *, source, headers=None):
        self.calls.append((url, headers or {}))
        if self.handler:
            return await self.handler(method, url, headers or {})
        return httpx.Response(
            200,
            text=ALLOW_ROBOTS if url.endswith("robots.txt") else "<p>Su aboneliği başvurusu.</p>",
            request=httpx.Request(method, url),
        )


def source(url: str, *, category="abonelik", crawlable=True) -> Source:
    return Source(url, "ISKI", category, "orta", "", True, "html", crawlable)


def test_html_to_blocks_drops_script_and_keeps_headings() -> None:
    page = html_to_blocks(
        "<html><head><title>Abonelik</title><meta property='article:modified_time' "
        "content='2026-09-24T12:30:00Z'><script>secret()</script></head>"
        "<body><nav>menu</nav><h1>Su hizmeti</h1><p>Başvuru yapılır.</p></body></html>"
    )
    assert page.title == "Abonelik"
    assert page.blocks[0].section_title == "Su hizmeti"
    assert page.source_updated_at == "2026-09-24T12:30:00Z" and page.updated_at_method == "meta"
    assert "secret" not in " ".join(block.text for block in page.blocks)
    assert "menu" not in " ".join(block.text for block in page.blocks)


def test_html_to_blocks_flags_js_only_page_as_unsupported() -> None:
    page = html_to_blocks("<html><body><div id='root'></div><script>hydrate()</script></body></html>")
    assert page.parser_status == "unsupported_js" and not page.blocks


def test_pdf_to_blocks_keeps_page_numbers(monkeypatch) -> None:
    pytest.importorskip("pypdf")
    import pypdf

    class Page:
        def __init__(self, text):
            self.text = text

        def extract_text(self):
            return self.text

    class Reader:
        pages = [Page("Page one text."), Page("Page two text.")]

    monkeypatch.setattr(pypdf, "PdfReader", lambda _stream: Reader())
    blocks = pdf_to_blocks(b"mock pdf")
    assert [(block.page_number, block.text) for block in blocks] == [(1, "Page one text."), (2, "Page two text.")]


def test_pdf_falls_back_to_pdftotext_when_pypdf_missing(monkeypatch) -> None:
    class Result:
        stdout = b"one\ftwo\f"

    monkeypatch.setattr("ibb_mcp.knowledge.parsers.shutil.which", lambda _name: "/usr/bin/pdftotext")
    monkeypatch.setattr("ibb_mcp.knowledge.parsers.subprocess.run", lambda *a, **k: Result())
    blocks = pdf_to_blocks(b"%PDF fake")
    assert [(block.page_number, block.text) for block in blocks] == [(1, "one"), (2, "two")]


def test_pdf_reports_unsupported_when_no_parser_available(monkeypatch) -> None:
    monkeypatch.setattr("ibb_mcp.knowledge.parsers.shutil.which", lambda _name: None)
    with pytest.raises(KnowledgeUnavailable) as error:
        pdf_to_blocks(b"%PDF fake")
    assert error.value.parser_status == "unsupported_pdf"


def test_robots_disallow_skips_url(tmp_path) -> None:
    async def handler(method, url, _headers):
        text = "User-agent: *\nDisallow: /private" if url.endswith("robots.txt") else "page"
        return httpx.Response(200, text=text, request=httpx.Request(method, url))

    client = FakeClient(handler)
    rows = asyncio.run(fetch_all([source("https://www.iski.istanbul/private")], client, tmp_path / "cache", 0))
    assert rows[0].status == "robots"
    assert len(client.calls) == 1


def test_same_host_waits_two_seconds(monkeypatch, tmp_path) -> None:
    clock = {"now": 0.0}
    waits = []

    async def sleep(seconds):
        waits.append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr("ibb_mcp.knowledge.ingest.time.monotonic", lambda: clock["now"])
    monkeypatch.setattr("ibb_mcp.knowledge.ingest.asyncio.sleep", sleep)
    rows = asyncio.run(fetch_all([source("https://www.iski.istanbul/a")], FakeClient(), tmp_path / "cache", 2.0))
    assert rows[0].status == "ok"
    assert waits and waits[0] == 2.0


def test_cache_hit_makes_no_request(tmp_path) -> None:
    url = "https://www.iski.istanbul/"
    _write_cache(
        tmp_path / "cache", url, b"<p>cached</p>", {"fetched_at": "2026-09-25T00:00:00+00:00", "content_type": "text/html"}
    )
    client = FakeClient()
    rows = asyncio.run(fetch_all([source(url)], client, tmp_path / "cache", 0))
    assert rows[0].status == "cached" and rows[0].body == b"<p>cached</p>"
    assert not client.calls


def test_etag_conditional_request_returns_304_skips_embed(tmp_path) -> None:
    url = "https://www.iski.istanbul/"
    _write_cache(
        tmp_path / "cache",
        url,
        b"<p>old body</p>",
        {"fetched_at": "2026-09-25T00:00:00+00:00", "content_type": "text/html", "etag": "v1"},
    )

    async def handler(method, target, headers):
        if target.endswith("robots.txt"):
            return httpx.Response(200, text=ALLOW_ROBOTS, request=httpx.Request(method, target))
        assert headers["If-None-Match"] == "v1"
        raise UpstreamUnavailable("not modified", source="knowledge", status=304)

    rows = asyncio.run(fetch_all([source(url)], FakeClient(handler), tmp_path / "cache", 0, refresh=True))
    assert rows[0].status == "not-modified" and rows[0].body == b"<p>old body</p>"


def test_robots_and_terms_snapshot_is_recorded_before_crawl(tmp_path) -> None:
    events = []

    async def handler(method, url, _headers):
        events.append(url)
        if url.endswith("robots.txt"):
            text = ALLOW_ROBOTS
        elif url.endswith("license"):
            text = "Terms snapshot"
        else:
            text = "<p>page body</p>"
        return httpx.Response(200, text=text, request=httpx.Request(method, url))

    sources = [
        source("https://data.ibb.gov.tr/dataset/example"),
        source("https://data.ibb.gov.tr/license", category="lisans", crawlable=False),
    ]
    asyncio.run(fetch_all(sources, FakeClient(handler), tmp_path / "cache", 0))
    assert [url.rsplit("/", 1)[-1] for url in events] == ["robots.txt", "license", "example"]
    assert list((tmp_path / "robots").glob("*.txt"))
    snapshot = json.loads((tmp_path / "robots" / "data.ibb.gov.tr.json").read_text(encoding="utf-8"))
    assert snapshot["robots_snapshot"]["body_sha256"] == hashlib.sha256(ALLOW_ROBOTS.encode()).hexdigest()
    assert snapshot["terms_url"].endswith("/license")
    assert snapshot["terms_sha256"] == hashlib.sha256(b"Terms snapshot").hexdigest()
    assert snapshot["terms_status"] == 200
    assert "Terms snapshot" not in json.dumps(snapshot)


def test_no_ibb_host_literal_in_knowledge_python() -> None:
    root = pathlib.Path(__file__).parents[1] / "src/ibb_mcp/knowledge"
    sources = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    assert "api." + "ibb.gov.tr" not in sources
