#!/usr/bin/env python3
"""Fetch the reviewed source inventory and build the local SQLite knowledge index.

With ``--catalog data/reference/ibb_catalog.json`` it fetches nothing: every dataset of the local İBB Open Data
catalogue (``make capture-catalog``) becomes one page of the same index (``ibb_mcp.knowledge.catalog_pages``).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import email.utils
import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from ibb_mcp.http import PoliteClient  # noqa: E402
from ibb_mcp.knowledge.catalog_pages import index_catalog  # noqa: E402
from ibb_mcp.knowledge.chunking import chunk_blocks  # noqa: E402
from ibb_mcp.knowledge.embed import embedder_from_env  # noqa: E402
from ibb_mcp.knowledge.ingest import (  # noqa: E402
    KnowledgeUnavailable,
    canonical_url,
    clean_text,
    fetch_all,
    html_to_blocks,
    parse_knowledge_sources,
    pdf_to_blocks,
)  # noqa: E402
from ibb_mcp.knowledge.store import KnowledgePage, KnowledgeStore  # noqa: E402


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


async def run(args: argparse.Namespace) -> int:
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
    return parser


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parser().parse_args())))
