"""One allowlist for ingest and evidence, the Q1/Q2 host decisions, and redirect hops (B06).

Host names are written in pieces, as in the source, so the raw-İBB-call guardrail keeps matching only real calls.
"""

from __future__ import annotations

import asyncio
import pathlib
from urllib.parse import urlsplit

import pytest
from test_knowledge_ingest import FakeClient, _redirecting, source
from test_knowledge_store import seed_page

from ibb_mcp.knowledge import guardrails, ingest
from ibb_mcp.knowledge.answer import answer
from ibb_mcp.knowledge.embed import HashingEmbedder
from ibb_mcp.knowledge.ingest import fetch_all, is_allowed_redirect, is_allowed_url, parse_knowledge_sources
from ibb_mcp.knowledge.store import KnowledgeStore

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCES = ROOT / "data" / "knowledge" / "sources.txt"
CITY = "ibb" + ".istanbul"
GOV = "ibb" + ".gov.tr"
SUBDOMAINS = (
    "cozummerkezi",
    "depremzemin",
    "enstitu",
    "finansman",
    "gencuniversiteli",
    "istanbulseninhaber",
    "kariyer",
    "mezarliklar",
    "senokudiye",
    "tarim",
    "uploads",
    "yuvamiz",
)
#: Seed hosts that stay out after Q1 = A and Q2 = E. Store apps, other utilities and the card's
#: account subdomain are not reviewed sources; the last five rows are control records, not crawl seeds.
REJECTED_HOSTS = {
    "www.turkiye.gov.tr",
    "bireysel." + "istanbulkart" + ".istanbul",
    "www." + "igdas" + ".istanbul",
    "online." + "spor" + ".istanbul",
    "event." + "spor" + ".istanbul",
    "kultur" + ".istanbul",
    "www." + "ihe" + ".istanbul",
    "apps.apple.com",
    "play.google.com",
    "www.iski.gov.tr",
    "www.mevzuat.gov.tr",
    "docs.ckan.org",
    "www.rfc-editor.org",
}


def test_parsers_never_shell_out() -> None:
    text = (ROOT / "src" / "ibb_mcp" / "knowledge" / "parsers.py").read_text(encoding="utf-8")
    for needle in ("pdftotext", "subprocess", "shutil.which"):
        assert needle not in text, needle


def test_seed_counts_after_q1() -> None:
    rows = parse_knowledge_sources(SOURCES)
    accepted = [row for row in rows if is_allowed_url(row.url)]
    rejected = [row for row in rows if not is_allowed_url(row.url)]
    assert (len(rows), len(accepted), len(rejected)) == (73, 59, 14)
    # mevzuat.gov.tr has two rows, so 14 rejected rows cover 13 hosts.
    assert {urlsplit(row.url).hostname for row in rejected} == REJECTED_HOSTS
    # Q2 = E: the card's public site is in, exact host only.
    assert "www." + "istanbulkart" + ".istanbul" in {urlsplit(row.url).hostname for row in accepted}


def test_every_ibb_istanbul_seed_host_is_accepted() -> None:
    seed_hosts = {urlsplit(row.url).hostname for row in parse_knowledge_sources(SOURCES)}
    for name in SUBDOMAINS:
        host = f"{name}.{CITY}"
        assert host in seed_hosts, f"{host} is no longer in the seed; update this list"
        assert is_allowed_url(f"https://{host}/"), host


def test_evidence_and_ingest_share_one_allowlist() -> None:
    assert ingest.ALLOWLIST is guardrails.DEFAULT_ALLOWLIST
    for row in parse_knowledge_sources(SOURCES):
        assert guardrails._host_allowed(row.url, guardrails.DEFAULT_ALLOWLIST) == ingest.is_allowed_url(row.url), row.url


@pytest.mark.parametrize(
    "url",
    [
        "https://evil" + CITY + "/",
        f"https://{CITY}.evil.example/",
        f"https://{CITY}@evil.example/",
        "https://evil.example\\@" + CITY + "/",
        "http://127.0.0.1/",
        "http://[::1]/",
        "https://169.254.169.254/latest/meta-data/",
        f"https://{CITY}:8443/",
        f"ftp://{CITY}/",
        "file:///etc/passwd",
        f"gopher://{CITY}/",
        f"https://data.{GOV}.evil.example/",
    ],
)
def test_lookalike_and_internal_targets_are_rejected(url: str) -> None:
    assert not is_allowed_url(url)
    assert not is_allowed_redirect(url)
    assert not is_allowed_redirect(url, from_host=CITY)


def test_same_host_redirect_on_a_subdomain_is_followed(tmp_path) -> None:
    client = FakeClient(_redirecting({"/a": "/b"}))
    page = f"https://gencuniversiteli.{CITY}/a"
    rows = asyncio.run(fetch_all([source(page)], client, tmp_path / "cache", 0))
    assert rows[0].status == "ok"
    assert [url for url, _ in client.calls][-2:] == [page, page[:-1] + "b"]


def test_cross_host_redirect_to_an_unlisted_subdomain_is_refused(tmp_path) -> None:
    client = FakeClient(_redirecting({"/a": f"https://intranet.{CITY}/x"}))
    rows = asyncio.run(fetch_all([source(f"https://gencuniversiteli.{CITY}/a")], client, tmp_path / "cache", 0))
    assert rows[0].status == "redirect-refused" and rows[0].body is None
    assert not any("intranet" in url for url, _ in client.calls)


def test_redirect_to_metadata_ip_is_refused_before_it_is_requested(tmp_path) -> None:
    client = FakeClient(_redirecting({"/a": "http://169.254.169.254/latest/meta-data/"}))
    rows = asyncio.run(fetch_all([source(f"https://gencuniversiteli.{CITY}/a")], client, tmp_path / "cache", 0))
    assert rows[0].status == "redirect-refused"
    assert not any("169.254" in url for url, _ in client.calls)


def test_a_subdomain_source_is_quoted_not_bilmiyorum(tmp_path) -> None:
    url = f"https://gencuniversiteli.{CITY}/"
    store = KnowledgeStore(tmp_path / "knowledge.db")
    seed_page(store, "Burs başvurusu resmî kaynakta açıklanır.", url=url)
    result = asyncio.run(answer("Burs başvurusu nasıl yapılır?", store=store, embedder=HashingEmbedder()))
    assert result.mode == "answer"
    assert url in result.text
