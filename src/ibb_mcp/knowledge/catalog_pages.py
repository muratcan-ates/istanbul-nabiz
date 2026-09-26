"""The İBB Open Data catalogue as knowledge pages: "İstanbul'a Sor" can quote which dataset holds what.

``scripts/knowledge_ingest.py --catalog data/reference/ibb_catalog.json`` turns each dataset of the
local catalogue (``ibb_mcp.catalog``, written by ``make capture-catalog``) into one page of the
service-page index: its title and description, then who publishes it, its categories, tags, formats
and licence, each a sentence the answer can quote. The page's URL is the dataset's own page on
``data.ibb.gov.tr`` (an allowlisted host), its ``fetched_at`` the catalogue's capture time and its
``source_updated_at`` CKAN's ``metadata_modified``.

No request is made: everything comes from the file. A dataset whose description talks to a model
keeps its title and facts but not its description.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from ibb_mcp.config import PORTAL
from ibb_mcp.text import looks_like_instruction

from .chunking import PageBlock, chunk_blocks
from .embed import Embedder
from .parsers import clean_text
from .store import KnowledgePage, KnowledgeStore

INSTITUTION = "IBB_OPEN_DATA"
CATEGORY = "acik-veri-katalog"


def _sentence(label: str, values: list[str]) -> str:
    return f"{label}: {', '.join(values)}." if values else ""


def dataset_page(record: Mapping[str, Any], captured_at: str) -> tuple[KnowledgePage, list[PageBlock]]:
    """One catalogue record as a page and its two blocks: the description, then the facts."""
    title = str(record.get("title") or record["name"])
    notes = str(record.get("notes") or "")
    formats = sorted({str(r.get("format")) for r in record.get("resources") or [] if r.get("format")})
    description = f"{title}. {'' if looks_like_instruction(notes) else notes}".strip()
    facts = " ".join(
        part
        for part in (
            f"{title} veri seti İBB Açık Veri Portalı'nda yayımlanır.",
            _sentence("Yayımlayan kurum", [str(record.get("organization"))] if record.get("organization") else []),
            _sentence("Kategori", [str(g) for g in record.get("groups") or []]),
            _sentence("Etiketler", [str(t) for t in record.get("tags") or []]),
            _sentence("Biçimler", formats),
            _sentence("Lisans", [str(record.get("license_title"))] if record.get("license_title") else []),
        )
        if part
    )
    blocks = [PageBlock(text=description, section_title=title), PageBlock(text=facts, section_title=title)]
    url = f"{PORTAL}/dataset/{record['name']}"
    page = KnowledgePage(
        url=url,
        canonical_url=url,
        title=title,
        institution=INSTITUTION,
        category=CATEGORY,
        fetched_at=captured_at,
        source_updated_at=record.get("metadata_modified"),
        etag=None,
        last_modified=None,
        body=clean_text("\n\n".join(block.text for block in blocks)),
        content_type="application/json",
        updated_at_method="ckan_metadata_modified",
        license_id=record.get("license_title") or None,
    )
    return page, blocks


async def index_catalog(path: pathlib.Path, store: KnowledgeStore, embedder: Embedder | None) -> list[tuple[str, str, int]]:
    """Index every dataset of the catalogue file; ``(url, status, chunks)`` per dataset, as the page ingest reports."""
    raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    captured_at = str((raw.get("meta") or {}).get("captured_at_utc") or "")
    if not captured_at:
        raise ValueError("catalogue file has no meta.captured_at_utc")
    rows: list[tuple[str, str, int]] = []
    for record in raw.get("datasets") or []:
        if not isinstance(record, dict) or not record.get("name"):
            continue
        page, blocks = dataset_page(record, captured_at)
        chunks = chunk_blocks(blocks)
        existing = store.current_document(page.url)
        if existing and existing.get("body") == page.body:
            rows.append((page.url, "unchanged", store.chunk_count(existing["document_id"])))
            continue
        page = page if embedder is None else replace(page, embedding_model=embedder.name)
        vectors = await embedder.embed_documents([c.text for c in chunks]) if embedder else [None] * len(chunks)
        store.upsert_page(page, chunks, vectors)
        rows.append((page.url, "ok", len(chunks)))
    return rows

