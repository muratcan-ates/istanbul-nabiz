#!/usr/bin/env python3
"""Fetch the reviewed source inventory and build the local SQLite knowledge index.

With ``--catalog data/reference/ibb_catalog.json`` it fetches nothing: every dataset of the local İBB Open Data
catalogue (``make capture-catalog``) becomes one page of the same index (``ibb_mcp.knowledge.catalog_pages``).

With ``--candidates data/knowledge/source_candidates.jsonl`` it reads the knowledge editor's decisions (E74):
only candidates whose last line is an approval and that are not indexed yet are fetched. The default is a dry
run: the plan, the allowlist and cached robots decisions and the requests per host are printed, and nothing
goes on the network. ``--fetch`` fetches through ``PoliteClient`` with robots.txt first and at least
:data:`CANDIDATE_INTERVAL_S` seconds between requests to one host, indexes the pages and appends an "indexed"
line per candidate; an approval undone after indexing is taken out of the index with a "removed" line. The
candidate file is appended to, never rewritten. ``--fetch`` refuses to run under ``NABIZ_OFFLINE=1``.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import email.utils
import hashlib
import json
import os
import pathlib
import sys
from collections import Counter
from urllib.robotparser import RobotFileParser

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from ibb_mcp.http import PoliteClient  # noqa: E402
from ibb_mcp.knowledge.catalog_pages import index_catalog  # noqa: E402
from ibb_mcp.knowledge.chunking import chunk_blocks  # noqa: E402
from ibb_mcp.knowledge.embed import embedder_from_env  # noqa: E402
from ibb_mcp.knowledge.ingest import (  # noqa: E402
    INDEXED,
    REMOVED,
    CandidateStep,
    KnowledgeUnavailable,
    candidate_source,
    canonical_url,
    clean_text,
    fetch_all,
    html_to_blocks,
    parse_knowledge_sources,
    pdf_to_blocks,
    plan_candidates,
    read_candidates,
)  # noqa: E402
from ibb_mcp.knowledge.store import KnowledgePage, KnowledgeStore  # noqa: E402
from ibb_mcp.text import looks_like_instruction  # noqa: E402

#: Seconds between two requests to one host for candidates: a person approved one page, nobody is waiting.
CANDIDATE_INTERVAL_S = 10.0
OFFLINE_REFUSAL = "NABIZ_OFFLINE=1: --fetch ağa çıkar, çevrimdışı modda çalışmaz. Önce --dry-run ile planı okuyun."


def _source_updated(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        parsed = None
    if parsed is None:
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC).isoformat()


def _parse_result(result):
    if result.source.content_type == "pdf" or (result.content_type or "").lower().startswith("application/pdf"):
        return pdf_to_blocks(result.body), result.source.category, "ok", None, "unknown"
    page = html_to_blocks(result.body.decode("utf-8", errors="replace"), result.source.url)
    return (
        list(page.blocks),
        page.title or result.source.category,
        page.parser_status,
        page.source_updated_at,
        page.updated_at_method,
    )


async def _index_result(result, store: KnowledgeStore, embedder) -> tuple[str, str, int]:
    if result.status == "not-modified" or not result.body:
        return result.source.url, result.status, 0
    if result.status == "cached" and (document := store.current_document(result.source.url)):
        return result.source.url, "cached", store.chunk_count(document["document_id"])
    try:
        blocks, title, parser_status, page_updated_at, metadata_method = _parse_result(result)
        if parser_status != "ok":
            return result.source.url, parser_status, 0
        chunks = chunk_blocks(blocks)
        if not chunks:
            return result.source.url, "unsupported_js", 0
        body = clean_text("\n\n".join(block.text for block in blocks))
        page_updated = _source_updated(page_updated_at)
        server_updated = _source_updated(result.last_modified)
        source_updated = page_updated or server_updated
        updated_method = metadata_method if page_updated else ("heuristic" if server_updated else "unknown")
        page = KnowledgePage(
            url=result.source.url,
            canonical_url=result.source.url,
            title=title,
            institution=result.source.institution,
            category=result.source.category,
            fetched_at=result.fetched_at or dt.datetime.now(dt.UTC).isoformat(),
            source_updated_at=source_updated,
            etag=result.etag,
            last_modified=result.last_modified,
            body=body,
            content_type=result.content_type or ("application/pdf" if result.source.content_type == "pdf" else "text/html"),
            updated_at_method=updated_method,
            parser_status=parser_status,
            embedding_model=embedder.name if embedder else None,
        )
        existing = store.current_document(result.source.url)
        if existing and existing.get("sha256") == hashlib.sha256(body.encode("utf-8")).hexdigest():
            document_id = store.upsert_page(page, [], [])
            return result.source.url, "unchanged", store.chunk_count(document_id)
        vectors = await embedder.embed_documents([chunk.text for chunk in chunks]) if embedder else [None] * len(chunks)
        store.upsert_page(page, chunks, vectors)
        return result.source.url, result.status, len(chunks)
    except KnowledgeUnavailable as exc:
        return result.source.url, exc.parser_status, 0
    except Exception:
        return result.source.url, "hata", 0


def _print_rows(rows: list[tuple[str, str, int]]) -> None:
    print("URL\tDurum\tParça")
    for url, status, count in rows:
        print(f"{url}\t{status}\t{count}")


def _cached_robots(cache: pathlib.Path, host: str) -> RobotFileParser | None:
    """The robots.txt the last fetch kept for ``host`` (``fetch_all``'s own file), or ``None``."""
    path = cache.parent / "robots" / f"{hashlib.sha256(host.encode()).hexdigest()}.txt"
    if not path.is_file():
        return None
    parser = RobotFileParser()
    parser.parse(path.read_text(encoding="utf-8", errors="replace").splitlines())
    return parser


def candidate_plan(steps: list[CandidateStep], cache: pathlib.Path) -> tuple[list[tuple[str, str, str]], Counter]:
    """Rows (URL, decision, robots) and the requests per host a ``--fetch`` would make; no network."""
    rows, requests, robots_needed = [], Counter(), set()
    for step in steps:
        robots = "-"
        if step.action == "fetch":
            parser = _cached_robots(cache, step.host)
            if parser is None:
                robots = "fetch'te okunur"
                robots_needed.add(step.host)
            else:
                robots = "izin (önbellek)" if parser.can_fetch("NabizKnowledgeBot", step.url) else "ret (önbellek)"
            if robots != "ret (önbellek)":
                requests[step.host] += 1
        rows.append((step.url, step.action, robots))
    for host in robots_needed:
        requests[host] += 1
    return rows, requests


def _append(path: pathlib.Path, lines: list[dict]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        for line in lines:
            stream.write(json.dumps(line, ensure_ascii=False) + "\n")


def candidate_mark(step: CandidateStep, event: str, detail: str, now: dt.datetime | None = None) -> dict:
    """The new line for ``event`` ("indexed" or "removed"); the candidate file is appended to, never rewritten."""
    at = (now or dt.datetime.now(dt.UTC)).isoformat()
    label = {INDEXED: "dizine alındı", REMOVED: "dizinden çıkarıldı"}[event]
    return {"schema": 1, "event": event, "candidate_id": step.candidate_id, "url": step.url, "host": step.host,
            "at": at, "detail": detail, "note": f"{label} {at[:10]}", "source": "scripts/knowledge_ingest.py"}  # fmt: skip


async def run_candidates(args: argparse.Namespace, fetcher=fetch_all, client_factory=PoliteClient) -> int:
    """``--candidates``: the dry-run plan, or with ``--fetch`` the fetch, the index and the appended lines."""
    steps = plan_candidates(read_candidates(args.candidates))
    rows, requests = candidate_plan(steps, args.cache)
    print("URL\tKarar\tRobots")
    for url, action, robots in rows:
        print(f"{url}\t{action}\t{robots}")
    print("Host başına istek: " + (", ".join(f"{host}={count}" for host, count in sorted(requests.items())) or "0"))
    if not args.fetch:
        print("Kuru koşu: ağ isteği 0. Çekmek için aynı komuta --fetch ekleyin (MURAT ONAYI).")
        return 0
    if os.environ.get("NABIZ_OFFLINE") == "1":
        print(OFFLINE_REFUSAL, file=sys.stderr)
        return 2
    store = KnowledgeStore(args.db)
    embedder = None if args.no_embed else embedder_from_env(store=store)
    todo = [step for step in steps if step.action == "fetch"]
    async with client_factory(max_attempts=1) as client:
        fetched = await fetcher([candidate_source(step) for step in todo], client, args.cache, CANDIDATE_INTERVAL_S)
    marks = []
    for step, result in zip(todo, fetched, strict=True):
        url, status, count = await _index_result(result, store, embedder)
        if count:
            flagged = bool(result.body) and looks_like_instruction(result.body.decode("utf-8", errors="replace"))
            note = "; talimat içeriyor: kaynak olarak dizinde, cevapta uygulanmaz" if flagged else ""
            marks.append(candidate_mark(step, INDEXED, f"{status}, {count} parça{note}"))
        print(f"{url}\t{status}\t{count}")
    for step in steps:
        if step.action == "remove":
            store.mark_inactive(canonical_url(step.url))
            marks.append(candidate_mark(step, REMOVED, "onay geri alındı"))
    _append(args.candidates, marks)
    print(f"Dizine alınan: {sum(m['event'] == INDEXED for m in marks)}; çıkarılan: {sum(m['event'] == REMOVED for m in marks)}")
    return 0


async def run(args: argparse.Namespace) -> int:
    if getattr(args, "candidates", None):
        return await run_candidates(args)
    store = KnowledgeStore(args.db)
    embedder = None if args.no_embed else embedder_from_env(store=store)
    if args.catalog:
        rows = await index_catalog(args.catalog, store, embedder)
        _print_rows(rows)
        print(f"Katalog veri seti sayfası: {len(rows)}; ağ isteği yok")
        return 0
    sources = parse_knowledge_sources(args.sources)
    async with PoliteClient(max_attempts=1) as client:
        fetched = await fetch_all(sources, client, args.cache, refresh=args.refresh)
    for result in fetched:
        if result.status == "404":
            store.mark_inactive(canonical_url(result.source.url))
    rows = [await _index_result(result, store, embedder) for result in fetched]
    _print_rows(rows)
    unverified = [source for source in sources if not source.verified]
    print(f"Doğrulanmış envanter satırı: {len(sources) - len(unverified)}; doğrulanmamış: {len(unverified)}")
    if unverified:
        print("Doğrulanmamış notlu satırlar: " + ", ".join(source.category for source in unverified))
    return 0


def parser() -> argparse.ArgumentParser:
    """Create the script options without touching network or environment credentials."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=pathlib.Path, default=ROOT / "data/knowledge/sources.txt")
    parser.add_argument("--db", type=pathlib.Path, default=ROOT / "data/knowledge/knowledge.db")
    parser.add_argument("--cache", type=pathlib.Path, default=ROOT / "data/knowledge/cache")
    parser.add_argument("--refresh", action="store_true", help="Revalidate cached pages with conditional requests")
    parser.add_argument("--no-embed", action="store_true", help="Build only the FTS index")
    parser.add_argument(
        "--catalog", type=pathlib.Path, help="Index the local İBB Open Data catalogue file instead of fetching pages (no network)"
    )
    parser.add_argument("--candidates", type=pathlib.Path, help="The knowledge editor's approved candidates (E74), JSONL")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="With --candidates: print the plan, no network (the default)")
    mode.add_argument("--fetch", action="store_true", help="With --candidates: fetch, index and mark (network; owner only)")
    return parser


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parser().parse_args())))
