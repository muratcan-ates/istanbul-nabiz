from __future__ import annotations

import asyncio
import datetime as dt
import json
import pathlib

from ibb_mcp.knowledge.answer import answer
from ibb_mcp.knowledge.chunking import PageBlock, chunk_blocks
from ibb_mcp.knowledge.embed import HashingEmbedder
from ibb_mcp.knowledge.ingest import html_to_blocks
from ibb_mcp.knowledge.store import KnowledgePage, KnowledgeStore


def test_twenty_question_fixture_all_cited_quotes_verbatim_in_source(tmp_path, monkeypatch) -> None:
    # A one-page index scores BM25 near zero; the FTS floor is the real index's scale (DECISIONS #36).
    monkeypatch.setenv("NABIZ_KNOWLEDGE_FTS_MIN", "0")
    root = pathlib.Path(__file__).parent / "fixtures/knowledge"
    page = html_to_blocks((root / "services.html").read_text(encoding="utf-8"))
    source = "\n\n".join(block.text for block in page.blocks)
    chunks = chunk_blocks([PageBlock(source, section_title="İstanbul hizmet başvuruları")])
    store = KnowledgeStore(tmp_path / "knowledge.db")
    vectors = asyncio.run(HashingEmbedder().embed_documents([chunk.text for chunk in chunks]))
    store.upsert_page(
        KnowledgePage(
            url="https://www.iski.istanbul/hizmetler",
            canonical_url="https://www.iski.istanbul/hizmetler",
            title=page.title,
            institution="ISKI",
            category="fixture",
            fetched_at=dt.datetime.now(dt.UTC).isoformat(),
            source_updated_at=None,
            etag=None,
            last_modified=None,
            body=source,
        ),
        chunks,
        vectors,
    )
    questions = [json.loads(line) for line in (root / "questions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(questions) == 20
    for row in questions:
        result = asyncio.run(answer(row["question"], store=store, embedder=HashingEmbedder()))
        assert result.mode == "answer", row["question"]
        assert row["quote"] in source
        assert any(hit.quote == row["quote"] for hit in result.citations), row["question"]
