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
#: Seed hosts that stay out after Q1 = A, Q2 = E and E26. Store apps, the central e-government portal and
#: login/booking subdomains are not reviewed sources; the last five rows are control records, not crawl seeds.
REJECTED_HOSTS = {
    "www.turkiye.gov.tr",
    "bireysel." + "istanbulkart" + ".istanbul",
    "online." + "spor" + ".istanbul",
    "event." + "spor" + ".istanbul",
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


#: E26: İBB affiliates' own public sites (İGDAŞ, Kültür AŞ, İstanbul Halk Ekmek), apex and www, exact.
AFFILIATE_HOSTS = tuple(
    prefix + name + ".istanbul" for name in ("igdas", "kultur", "ihe") for prefix in ("", "www.")
)
GROK_NEW_HOSTS = (
    "iski" + ".istanbul",
    "cdn." + "iski" + ".istanbul",
    "grafikgoster." + "iski" + ".gov.tr",
    "esube." + "iski" + ".gov.tr",
    "www." + "sehirhatlari" + ".istanbul",
    "files." + "sehirhatlari" + ".istanbul",
)


def test_seed_counts_after_q1() -> None:
    rows = parse_knowledge_sources(SOURCES)
    accepted = [row for row in rows if is_allowed_url(row.url)]
    rejected = [row for row in rows if not is_allowed_url(row.url)]
    assert (len(rows), len(accepted), len(rejected)) == (418, 407, 11)
    assert len({row.url for row in rows}) == len(rows), "duplicate URL in sources.txt"
    crawl = [row for row in accepted if row.crawlable]
    assert len(crawl) == 401
    # mevzuat.gov.tr has two rows, so 11 rejected rows cover 10 hosts.
    assert {urlsplit(row.url).hostname for row in rejected} == REJECTED_HOSTS
    # Q2 = E: the card's public site is in, exact host only.
    assert "www." + "istanbulkart" + ".istanbul" in {urlsplit(row.url).hostname for row in accepted}


def _section_urls() -> dict[str, list[str]]:
    """URL rows per ``# ===== BÖLÜM N`` header, in file order."""
    sections: dict[str, list[str]] = {}
    current = ""
    for line in SOURCES.read_text(encoding="utf-8").splitlines():
        if line.startswith("# ===== BÖLÜM "):
            current = line.removeprefix("# ===== BÖLÜM ").split(":", 1)[0]
            sections[current] = []
        elif line.startswith(("http://", "https://")):
            sections[current].append(line.split("\t", 1)[0])
    return sections


def test_row_counts_per_section() -> None:
    counts = {name: len(urls) for name, urls in _section_urls().items()}
    assert counts == {"1": 14, "2": 9, "3": 39, "4": 11, "5": 257, "6": 43, "7": 45}


def test_e26_section_is_crawlable_and_inside_the_allowlist() -> None:
    e26 = set(_section_urls()["5"])
    rows = [row for row in parse_knowledge_sources(SOURCES) if row.url in e26]
    assert len(rows) == len(e26) == 257
    assert all(row.crawlable and row.verified and is_allowed_url(row.url) for row in rows)


def test_gemini_section_is_unverified_crawlable_and_inside_the_allowlist() -> None:
    """Section 6 (26 Sep): Gemini's İSKİ/İGDAŞ/Şehir Hatları candidates, never opened; ingest weeds out 404s."""
    sections = _section_urls()
    gemini = set(sections["6"])
    earlier = {url for name, urls in sections.items() if name != "6" for url in urls}
    assert not gemini & earlier
    rows = [row for row in parse_knowledge_sources(SOURCES) if row.url in gemini]
    assert len(rows) == len(gemini) == 43
    assert all(row.crawlable and not row.verified and is_allowed_url(row.url) for row in rows)
    assert all(row.note.startswith("Gemini, doğrulanmadı: ") for row in rows)
    by_institution = {code: sum(row.institution == code for row in rows) for code in ("ISKI", "IGDAS", "SEHIR_HATLARI")}
    assert by_institution == {"ISKI": 15, "IGDAS": 15, "SEHIR_HATLARI": 13}
    hosts = {urlsplit(row.url).hostname for row in rows}
    assert hosts == {"www." + "iski" + ".istanbul", "www." + "igdas" + ".istanbul", "sehirhatlari" + ".istanbul"}
    assert not any("google." in row.url or "utm_" in row.url for row in rows)


@pytest.mark.parametrize("host", AFFILIATE_HOSTS)
def test_affiliate_hosts_are_exact_and_redirect_safe(host: str) -> None:
    assert is_allowed_url(f"https://{host}/")
    # Exact entries, so a server-chosen hop may land on them too.
    assert is_allowed_redirect(f"https://{host}/x")
    # Not suffix domains: a subdomain or a look-alike stays out.
    assert not is_allowed_url(f"https://intranet.{host}/")
    assert not is_allowed_url(f"https://evil{host}/")
    assert not is_allowed_url(f"https://{host}.evil.example/")


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


def test_grok_section_is_verified_https_and_inside_the_allowlist() -> None:
    grok_urls = set(_section_urls()["7"])
    rows = [row for row in parse_knowledge_sources(SOURCES) if row.url in grok_urls]
    assert len(rows) == len(grok_urls) == 45
    assert all(row.url.startswith("https://") for row in rows)
    assert all(row.verified and is_allowed_url(row.url) for row in rows)
    assert all(row.note.startswith("Grok, 26.09.2026 açtı: ") for row in rows)
    assert all("?" not in row.note for row in rows)
    assert {row.institution: sum(item.institution == row.institution for item in rows) for row in rows} == {
        "ISKI": 16,
        "IGDAS": 17,
        "SEHIR_HATLARI": 12,
    }
    non_crawlable = [row for row in rows if not row.crawlable]
    assert len(non_crawlable) == 1
    assert non_crawlable[0].category == "oturum"
    assert {urlsplit(row.url).hostname for row in rows} == {
        "iski" + ".istanbul",
        "cdn." + "iski" + ".istanbul",
        "grafikgoster." + "iski" + ".gov.tr",
        "esube." + "iski" + ".gov.tr",
        "igdas" + ".istanbul",
        "www." + "igdas" + ".istanbul",
        "sehirhatlari" + ".istanbul",
        "www." + "sehirhatlari" + ".istanbul",
        "files." + "sehirhatlari" + ".istanbul",
    }


def test_grok_section_repeats_no_earlier_row() -> None:
    sections = _section_urls()

    def canonical(url: str) -> tuple[str, str, str]:
        parts = urlsplit(url)
        return (parts.hostname.casefold(), parts.path.rstrip("/"), parts.query)

    grok = {canonical(url) for url in sections["7"]}
    earlier = {canonical(url) for name, urls in sections.items() if name != "7" for url in urls}
    assert not grok & earlier


@pytest.mark.parametrize("host", GROK_NEW_HOSTS)
def test_grok_hosts_are_exact_and_redirect_safe(host: str) -> None:
    assert is_allowed_url(f"https://{host}/")
    assert is_allowed_redirect(f"https://{host}/x")
    assert not is_allowed_url(f"https://intranet.{host}/")
    assert not is_allowed_url(f"https://evil{host}/")
    assert not is_allowed_url(f"https://{host}.evil.example/")


def test_a_session_page_is_listed_but_never_crawled(tmp_path) -> None:
    rows = parse_knowledge_sources(SOURCES)
    session_pages = [row for row in rows if row.category == "oturum"]
    assert len(session_pages) == 1
    assert session_pages[0].verified and not session_pages[0].crawlable

    sources = tmp_path / "sources.txt"
    sources.write_text(
        "https://login.example.test/\tISKI\toturum\thtml\tyuksek\tGrok, 26.09.2026 açtı: giriş sayfası\n"
        "https://water.example.test/\tISKI\tabonelik\thtml\torta\tGrok, 26.09.2026 açtı: abonelik bilgisi\n",
        encoding="utf-8",
    )
    parsed = parse_knowledge_sources(sources)
    assert [row.crawlable for row in parsed] == [False, True]
