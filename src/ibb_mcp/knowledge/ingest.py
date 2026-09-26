# Ported from DOU-Synapse apps/api/app/modules/ingestion/parsers.py (github.com/muratcan-ates/DOU-Synapse @ 2cbe1ea, MIT, Copyright (c) 2026 Muratcan Ates)  # noqa: E501
"""Allowlisted, polite source ingestion with robots checks and a conditional cache."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import logging
import pathlib
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from ibb_mcp.http import PoliteClient

from .guardrails import DEFAULT_ALLOWLIST, host_allowed
from .parsers import KnowledgeUnavailable, ParsedPage, clean_text, html_to_blocks, pdf_to_blocks  # noqa: F401

#: The same object as ``guardrails.DEFAULT_ALLOWLIST``: one reviewed list for fetching and for evidence.
ALLOWLIST = DEFAULT_ALLOWLIST
TERMS_CATEGORIES = frozenset({"lisans", "terms", "kullanim-kosullari"})
#: Hops followed for one page. Each is vetted before it is requested (``is_allowed_redirect``);
#: the HTTP client never follows a redirect on its own here.
MAX_REDIRECTS = 3

log = logging.getLogger(__name__)


class RedirectRefused(Exception):
    """A redirect pointed off the reviewed hosts, or a page redirected more than ``MAX_REDIRECTS`` times."""


@dataclass(frozen=True, slots=True)
class Source:
    """One tab-separated source row from the reviewed seed inventory."""

    url: str
    institution: str
    category: str
    risk: str
    note: str
    verified: bool
    content_type: str = "html"
    crawlable: bool = True


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Fetched or cached body and reporting fields for one source."""

    source: Source
    status: str
    body: bytes | None = None
    fetched_at: str | None = None
    content_type: str | None = None
    etag: str | None = None
    last_modified: str | None = None


def is_allowed_url(url: str, allowlist: frozenset[str] = ALLOWLIST) -> bool:
    """Allow only safe HTTP(S) URLs on an exact reviewed host or an approved subdomain."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port
    except ValueError:
        return False
    if parts.scheme not in {"http", "https"} or not host or parts.username or parts.password:
        return False
    if port is not None and port != (443 if parts.scheme == "https" else 80):
        return False
    return host_allowed(host, allowlist)


def is_allowed_redirect(url: str, allowlist: frozenset[str] = ALLOWLIST, *, from_host: str | None = None) -> bool:
    """A redirect target must be a safe URL on an *exact* reviewed host, or stay on the host it left.

    Stricter than :func:`is_allowed_url`, which also admits subdomains of the municipal domains
    (``ALLOWED_SUFFIXES``) for seed rows a person reviewed: a ``Location`` header is chosen by the
    server, so a hop may only land on a host that is itself in the list, or on ``from_host``, the
    already-vetted host that answered with it (``/a`` to ``/b`` on a reviewed subdomain).
    """
    if not is_allowed_url(url, allowlist):
        return False
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    return host in allowlist or (from_host is not None and host == from_host.lower().rstrip("."))


def canonical_url(url: str) -> str:
    """Drop fragments while retaining the page's query, path and scheme."""
    parts = urlsplit(url)
    return parts._replace(fragment="").geturl()


#: A note containing any of these marks its row as unverified in the ingest report ("doğrulanmadı":
#: section 6, Gemini's candidates that nobody opened).
UNVERIFIED_NOTE_MARKERS = ("erişilemedi", "?", "doğrulanamadı", "doğrulanmadı", "unverified")


def parse_knowledge_sources(path: str | pathlib.Path) -> list[Source]:
    """Read tabular source metadata, preserving uncertain rows for transparent reports."""
    rows = []
    section = ""
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("# ====="):
            section = line.partition(":")[2].strip().lower()
        if not line or line.startswith("#") or not line.startswith(("http://", "https://")):
            continue
        cells = line.split("\t", 5)
        if len(cells) < 6:
            continue
        url, institution, category, content_type, risk, note = cells
        normalized_note = note.casefold()
        verified = not any(marker in normalized_note for marker in UNVERIFIED_NOTE_MARKERS)
        crawlable = "crawl tohumu değil" not in section and category not in {
            "robots",
            "mevzuat-fsek",
            "mevzuat-bilgi-edinme",
            "ckan-api-doc",
            "robots-rfc",
        }
        rows.append(Source(url, institution, category, risk, note, verified, content_type, crawlable))
    return rows


def _read_cache(cache_dir: pathlib.Path, url: str) -> tuple[bytes, dict] | None:
    digest = hashlib.sha256(url.encode()).hexdigest()
    body_path, meta_path = cache_dir / f"{digest}.body", cache_dir / f"{digest}.json"
    try:
        return body_path.read_bytes(), json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_cache(cache_dir: pathlib.Path, url: str, body: bytes, metadata: dict) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(url.encode()).hexdigest()
    (cache_dir / f"{digest}.body").write_bytes(body)
    (cache_dir / f"{digest}.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


class _FetchSession:
    """Crawl state shared by one fetch run."""

    def __init__(self, client: PoliteClient, cache: pathlib.Path, interval: float, refresh: bool, user_agent: str) -> None:
        self.client = client
        self.cache = cache
        self.interval = interval
        self.refresh = refresh
        self.user_agent = user_agent
        self.host_last: dict[str, float] = {}
        self.blocked: dict[str, str] = {}
        self.robots: dict[str, RobotFileParser] = {}
        self.snapshots: dict[str, dict] = {}

    async def _pace(self, host: str) -> None:
        delay = self.interval - (time.monotonic() - self.host_last.get(host, -1e9))
        if host in self.host_last and delay > 0:
            await asyncio.sleep(delay)
        self.host_last[host] = time.monotonic()

    async def request(self, url: str, host: str, headers: dict[str, str] | None = None):
        """GET ``url``, following at most ``MAX_REDIRECTS`` hops, each vetted before it is requested.

        The client is told not to follow redirects: an automatic follow would fetch the target
        first and leave the allowlist check to run on a response that already arrived (G14's
        SSRF note). A hop off the exact reviewed hosts, or one a known robots file disallows, is
        refused and logged by host only.
        """
        current, current_host = url, host
        for hop in range(MAX_REDIRECTS + 1):
            await self._pace(current_host)
            response = await self.client.get_hop(current, source="knowledge", headers=headers)
            if not response.is_redirect:
                return response
            target = urljoin(current, response.headers.get("location", ""))
            target_host = (urlsplit(target).hostname or "").lower().rstrip(".")
            if hop == MAX_REDIRECTS:
                log.warning("knowledge: more than %d redirects from %s; refused", MAX_REDIRECTS, host)
                raise RedirectRefused(f"more than {MAX_REDIRECTS} redirects")
            robots = self.robots.get(target_host)
            allowed = is_allowed_redirect(target, from_host=current_host)
            if not allowed or (robots is not None and not robots.can_fetch(self.user_agent, target)):
                log.warning("knowledge: refused redirect from %s to %s", current_host, target_host or "?")
                raise RedirectRefused(f"redirect to {target_host or '?'} is not allowed")
            current, current_host = target, target_host
        raise RedirectRefused("unreachable")  # pragma: no cover - the loop returns or raises

    async def _robots(self, host: str, scheme: str) -> RobotFileParser | None:
        digest = hashlib.sha256(host.encode()).hexdigest()
        path = self.cache.parent / "robots" / f"{digest}.txt"
        snapshot_path = self.cache.parent / "robots" / f"{host}.json"
        try:
            if path.is_file():
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                snapshot = json.loads(snapshot_path.read_text(encoding="utf-8")) if snapshot_path.is_file() else {}
            else:
                response = await self.request(f"{scheme}://{host}/robots.txt", host)
                body = response.content
                lines = response.text.splitlines()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
                snapshot = {
                    "robots_snapshot": {
                        "fetched_at": dt.datetime.now(dt.UTC).isoformat(),
                        "status": response.status_code,
                        "body_sha256": hashlib.sha256(body).hexdigest(),
                    },
                    "status": "ok",
                }
        except Exception as exc:
            snapshot = {
                "robots_snapshot": {
                    "fetched_at": dt.datetime.now(dt.UTC).isoformat(),
                    "status": getattr(exc, "status", "error"),
                    "body_sha256": None,
                },
                "status": "robots-unavailable",
            }
            if getattr(exc, "status", None) != 404:
                self.blocked[host] = "robots"
                path.parent.mkdir(parents=True, exist_ok=True)
                snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
                return None
            lines = []
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        if not snapshot:
            body = path.read_bytes()
            snapshot = {
                "robots_snapshot": {
                    "fetched_at": dt.datetime.now(dt.UTC).isoformat(),
                    "status": "cached",
                    "body_sha256": hashlib.sha256(body).hexdigest(),
                },
                "status": "ok",
            }
        self.snapshots[host] = snapshot
        path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        parser = RobotFileParser()
        parser.set_url(f"{scheme}://{host}/robots.txt")
        parser.parse(lines)
        self.robots[host] = parser
        return parser

    async def _terms(self, host: str, parser: RobotFileParser, sources: list[Source]) -> None:
        snapshot = self.snapshots[host]
        if snapshot.get("terms_checked_at"):
            return
        terms = next(
            (row for row in sources if (urlsplit(row.url).hostname or "") == host and row.category in TERMS_CATEGORIES),
            None,
        )
        if terms is None or not is_allowed_url(terms.url) or not parser.can_fetch(self.user_agent, terms.url):
            snapshot.update(
                {
                    "terms_url": terms.url if terms else None,
                    "terms_sha256": None,
                    "terms_checked_at": dt.datetime.now(dt.UTC).isoformat(),
                    "terms_status": "not-listed",
                }
            )
        else:
            try:
                response = await self.request(terms.url, host)
                snapshot.update(
                    {
                        "terms_url": terms.url,
                        "terms_sha256": hashlib.sha256(response.content).hexdigest(),
                        "terms_checked_at": dt.datetime.now(dt.UTC).isoformat(),
                        "terms_status": response.status_code,
                    }
                )
            except Exception as exc:
                snapshot.update(
                    {
                        "terms_url": terms.url,
                        "terms_sha256": None,
                        "terms_checked_at": dt.datetime.now(dt.UTC).isoformat(),
                        "terms_status": getattr(exc, "status", "error"),
                    }
                )
        snapshot_path = self.cache.parent / "robots" / f"{host}.json"
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    def _conditional_headers(self, source: Source) -> tuple[dict[str, str], tuple[bytes, dict] | None]:
        cached = _read_cache(self.cache, source.url)
        headers: dict[str, str] = {}
        if self.refresh and cached:
            metadata = cached[1]
            if metadata.get("etag"):
                headers["If-None-Match"] = metadata["etag"]
            if metadata.get("last_modified"):
                headers["If-Modified-Since"] = metadata["last_modified"]
        return headers, cached

    def _failure(self, source: Source, host: str, error: Exception, cached: tuple[bytes, dict] | None) -> FetchResult:
        status = getattr(error, "status", None)
        if status == 304 and cached:
            body, meta = cached
            return FetchResult(
                source,
                "not-modified",
                body,
                meta.get("fetched_at"),
                meta.get("content_type"),
                meta.get("etag"),
                meta.get("last_modified"),
            )
        if status in {429, 503}:
            self.blocked[host] = "429-503-durdu"
            return FetchResult(source, "429-503-durdu")
        return FetchResult(source, "404" if status == 404 else ("hata" if status else "timeout"))

    def _accept_response(self, source: Source, response) -> FetchResult:
        allowed_redirects = all(
            is_allowed_url(str(hop.url)) and is_allowed_url(urljoin(str(hop.url), hop.headers.get("location", "")))
            for hop in response.history
        )
        if not is_allowed_url(str(response.url)) or not allowed_redirects:
            return FetchResult(source, "robots")
        metadata = {
            "fetched_at": dt.datetime.now(dt.UTC).isoformat(),
            "content_type": response.headers.get("content-type", ""),
            "status": response.status_code,
            "etag": response.headers.get("etag"),
            "last_modified": response.headers.get("last-modified"),
        }
        _write_cache(self.cache, source.url, response.content, metadata)
        return FetchResult(
            source,
            "ok",
            response.content,
            metadata["fetched_at"],
            metadata["content_type"],
            metadata["etag"],
            metadata["last_modified"],
        )

    async def fetch_one(self, source: Source, host: str) -> FetchResult:
        if host in self.blocked:
            return FetchResult(source, self.blocked[host])
        if not self.robots[host].can_fetch(self.user_agent, source.url):
            return FetchResult(source, "robots")
        headers, cached = self._conditional_headers(source)
        try:
            response = await self.request(source.url, host, headers)
        except RedirectRefused:
            return FetchResult(source, "redirect-refused")
        except Exception as exc:
            return self._failure(source, host, exc, cached)
        return self._accept_response(source, response)

    async def run(self, sources: list[Source]) -> list[FetchResult]:
        self.cache.mkdir(parents=True, exist_ok=True)
        results: list[FetchResult | None] = [None] * len(sources)
        pending: dict[str, list[int]] = {}
        for index, source in enumerate(sources):
            if not source.crawlable:
                results[index] = FetchResult(source, "control-record")
                continue
            if not is_allowed_url(source.url):
                results[index] = FetchResult(source, "robots")
                continue
            cached = _read_cache(self.cache, source.url)
            if cached and not self.refresh:
                body, meta = cached
                results[index] = FetchResult(
                    source,
                    "cached",
                    body,
                    meta.get("fetched_at"),
                    meta.get("content_type"),
                    meta.get("etag"),
                    meta.get("last_modified"),
                )
            else:
                pending.setdefault(urlsplit(source.url).hostname or "", []).append(index)
        for host, indexes in pending.items():
            scheme = urlsplit(sources[indexes[0]].url).scheme
            parser = await self._robots(host, scheme)
            if parser:
                await self._terms(host, parser, sources)
            for index in indexes:
                results[index] = await self.fetch_one(sources[index], host)
        return [result or FetchResult(source, "hata") for source, result in zip(sources, results, strict=True)]


async def fetch_all(
    sources: list[Source],
    client: PoliteClient,
    cache_dir: str | pathlib.Path,
    min_interval_s: float = 2.0,
    *,
    refresh: bool = False,
    user_agent: str = "NabizKnowledgeBot",
) -> list[FetchResult]:
    """Fetch reviewed sources politely; robots policy precedes uncached page requests."""
    session = _FetchSession(client, pathlib.Path(cache_dir), min_interval_s, refresh, user_agent)
    return await session.run(sources)
