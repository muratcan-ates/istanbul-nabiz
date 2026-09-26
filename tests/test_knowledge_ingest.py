from __future__ import annotations

import asyncio
import hashlib
import json
import pathlib
import sys
import types

import httpx
import pytest

from ibb_mcp.http import PoliteClient, UpstreamUnavailable
from ibb_mcp.knowledge.ingest import (
    MAX_REDIRECTS,
    KnowledgeUnavailable,
    Source,
    _write_cache,
    fetch_all,
    html_to_blocks,
    is_allowed_redirect,
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

    async def get_hop(self, url, *, source, headers=None):
        """The ingest's only entry: a GET whose redirect comes back unfollowed (PoliteClient.get_hop)."""
        return await self.request("GET", url, source=source, headers=headers)


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


def test_pdf_without_pypdf_is_skipped(monkeypatch) -> None:
    # A None entry in sys.modules makes "import pypdf" raise ImportError, as on a machine without the extra.
    monkeypatch.setitem(sys.modules, "pypdf", None)
    with pytest.raises(KnowledgeUnavailable) as error:
        pdf_to_blocks(b"%PDF fake")
    assert error.value.parser_status == "skipped"


def test_pdf_with_no_text_is_unsupported(monkeypatch) -> None:
    class Reader:
        pages = []

    monkeypatch.setitem(sys.modules, "pypdf", types.SimpleNamespace(PdfReader=lambda _s: Reader()))
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


# -- redirects: every hop is vetted before it is requested (G14 SSRF note) ---------------------
def _redirecting(routes: dict[str, str]):
    """A handler that answers 302 -> ``routes[path]`` for listed paths, robots and pages otherwise."""

    async def handler(method, url, _headers):
        path = httpx.URL(url).path
        if path in routes:
            return httpx.Response(302, headers={"location": routes[path]}, request=httpx.Request(method, url))
        text = ALLOW_ROBOTS if url.endswith("robots.txt") else "<p>Su aboneliği başvurusu.</p>"
        return httpx.Response(200, text=text, request=httpx.Request(method, url))

    return handler


def test_redirect_off_the_allowlist_is_refused_before_it_is_requested(tmp_path, caplog) -> None:
    client = FakeClient(_redirecting({"/a": "https://example.org/steal"}))
    with caplog.at_level("WARNING", logger="ibb_mcp.knowledge.ingest"):
        rows = asyncio.run(fetch_all([source("https://www.iski.istanbul/a")], client, tmp_path / "cache", 0))
    assert rows[0].status == "redirect-refused" and rows[0].body is None
    assert not any("example.org" in url for url, _ in client.calls)
    assert "refused redirect" in caplog.text and "example.org" in caplog.text


def test_redirect_inside_the_allowlist_is_followed(tmp_path) -> None:
    client = FakeClient(_redirecting({"/a": "/b"}))
    rows = asyncio.run(fetch_all([source("https://www.iski.istanbul/a")], client, tmp_path / "cache", 0))
    assert rows[0].status == "ok" and b"abonel" in rows[0].body
    assert [url for url, _ in client.calls][-2:] == ["https://www.iski.istanbul/a", "https://www.iski.istanbul/b"]


def test_redirect_to_an_unlisted_subdomain_is_refused() -> None:
    gov = "ibb" + ".gov.tr"
    assert is_allowed_redirect(f"https://data.{gov}/x")
    assert not is_allowed_redirect(f"https://intranet.{gov}/x"), "a hop must land on an exact reviewed host"
    assert not is_allowed_redirect("http://127.0.0.1/admin")
    assert not is_allowed_redirect(f"https://data.{gov}:8443/x")


def test_more_than_the_redirect_limit_is_refused(tmp_path) -> None:
    hops = {f"/h{i}": f"/h{i + 1}" for i in range(MAX_REDIRECTS + 1)}
    client = FakeClient(_redirecting(hops))
    rows = asyncio.run(fetch_all([source("https://www.iski.istanbul/h0")], client, tmp_path / "cache", 0))
    assert rows[0].status == "redirect-refused"
    pages = [url for url, _ in client.calls if not url.endswith("robots.txt")]
    assert len(pages) == MAX_REDIRECTS + 1


async def test_polite_client_get_hop_returns_the_redirect_unfollowed() -> None:
    seen: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://example.org/next"})

    client = PoliteClient(transport=httpx.MockTransport(answer))
    try:
        response = await client.get_hop("https://www.iski.istanbul/a", source="knowledge")
    finally:
        await client.aclose()
    assert response.status_code == 302 and response.headers["location"] == "https://example.org/next"
    assert seen == ["https://www.iski.istanbul/a"]
