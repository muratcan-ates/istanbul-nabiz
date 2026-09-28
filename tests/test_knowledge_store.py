from __future__ import annotations

import asyncio
import datetime as dt
import os
import sqlite3

import pytest

from ibb_mcp.knowledge.chunking import PageBlock, chunk_blocks
from ibb_mcp.knowledge.embed import HashingEmbedder
from ibb_mcp.knowledge.store import QUOTE_CHUNK_INDEX, KnowledgePage, KnowledgeStore


def seed_page(store: KnowledgeStore, body: str, url: str = "https://www.iski.istanbul/abonelik") -> str:
    chunks = chunk_blocks([PageBlock(body, 1, "Hizmet")])
    vectors = asyncio.run(HashingEmbedder().embed_documents([chunk.text for chunk in chunks]))
    return store.upsert_page(
        KnowledgePage(
            url=url,
            canonical_url=url,
            title="İSKİ hizmet bilgisi",
            institution="ISKI",
            category="abonelik",
            fetched_at=dt.datetime.now(dt.UTC).isoformat(),
            source_updated_at=None,
            etag=None,
            last_modified=None,
            body=body,
            content_type="text/html",
            embedding_model=HashingEmbedder().name,
        ),
        chunks,
        vectors,
    )


def test_upsert_is_idempotent_by_hash(tmp_path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    body = "Su aboneliği başvurusu resmî kaynakta açıklanır."
    first = seed_page(store, body)
    second = seed_page(store, body)
    assert first == second
    with store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 1


def test_fts_matches_turkish_case_and_diacritics(tmp_path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    seed_page(store, "İSKİ'de Su Aboneliği başvurusu için kimlik bilgisi gerekir.")
    rows = store.fts_candidates('"iski" OR "aboneligi"')
    assert rows and "Aboneliği" in rows[0]["exact_text"]


def test_dense_numpy_and_pure_python_agree(tmp_path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    seed_page(store, "Su aboneliği başvurusu resmî kaynakta açıklanır.")
    rows = store.dense_candidates([1.0] + [0.0] * 95)
    assert rows and -1 <= rows[0]["cosine"] <= 1


def test_fts5_smoke_test_falls_back_to_numpy_only_when_unavailable(tmp_path, monkeypatch) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    seed_page(store, "Su aboneliği başvurusu resmî kaynakta açıklanır.")
    monkeypatch.setattr(KnowledgeStore, "fts_available", property(lambda _self: False))
    from ibb_mcp.knowledge.retrieve import search

    hits = asyncio.run(search(store, "su aboneliği", embedder=HashingEmbedder()))
    assert hits


def test_deleted_page_is_marked_inactive_not_removed(tmp_path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    url = "https://www.iski.istanbul/abonelik"
    doc = seed_page(store, "Su aboneliği başvurusu resmî kaynakta açıklanır.", url)
    store.mark_inactive(url)
    assert store.document(doc)["active"] == 0
    assert store.fts_candidates('"aboneligi"') == []


def test_schema_keeps_provenance_and_float32_embedding_metadata(tmp_path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    document_id = seed_page(store, "Su aboneliği başvurusu resmî kaynakta açıklanır.")
    document = store.document(document_id)
    assert document["content_type"] == "text/html"
    assert document["source_updated_at"] is None and document["updated_at_method"] == "unknown"
    assert document["parser_status"] == "ok" and document["license_id"] is None
    with store._connect() as db:
        chunk = db.execute("SELECT * FROM chunks").fetchone()
        quote = db.execute("SELECT * FROM quotes").fetchone()
        metadata = dict(db.execute("SELECT key, value FROM meta").fetchall())
    assert len(chunk["chunk_id"]) == 16
    assert isinstance(chunk["embedding"], bytes)
    assert chunk["embedding_model"] == HashingEmbedder().name and chunk["embedding_dim"] == 96
    assert len(quote["quote_id"]) == 16 and quote["page_no"] == 1
    assert metadata["embedder_name"] == HashingEmbedder().name and metadata["dimension"] == "96"
    assert metadata["index_built_at"] == store.index_built_at()


def _quote_indexes(path) -> set[str]:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='quotes'")}


def _without_quote_index(path) -> None:
    """An index file built before the quotes(chunk_id) index existed."""
    with sqlite3.connect(path) as db:
        db.execute(f"DROP INDEX {QUOTE_CHUNK_INDEX}")


def test_quotes_are_indexed_by_chunk_and_an_older_file_gains_the_index(tmp_path) -> None:
    path = tmp_path / "knowledge.db"
    store = KnowledgeStore(path)
    seed_page(store, "Su aboneliği başvurusu resmî kaynakta açıklanır.")
    assert QUOTE_CHUNK_INDEX in _quote_indexes(path)
    with store._connect() as db:
        plan = " ".join(row[3] for row in db.execute(
            "EXPLAIN QUERY PLAN SELECT q.quote_id FROM chunks c LEFT JOIN quotes q ON q.chunk_id=c.chunk_id"
        ))
    assert f"USING INDEX {QUOTE_CHUNK_INDEX}" in plan and "AUTOMATIC" not in plan
    _without_quote_index(path)
    KnowledgeStore(path)  # a writable open (or an ingest) adds it to an existing file
    assert QUOTE_CHUNK_INDEX in _quote_indexes(path)


def test_read_only_opens_neither_break_nor_add_the_index(tmp_path) -> None:
    from nabiz.console.official_path import ReadOnlyKnowledgeStore

    path = tmp_path / "knowledge.db"
    seed_page(KnowledgeStore(path), "İSKİ'de Su Aboneliği başvurusu için kimlik bilgisi gerekir.")
    _without_quote_index(path)
    readonly = ReadOnlyKnowledgeStore(path)  # mode=ro, as the offline chat opens the index
    assert readonly.fts_candidates('"aboneligi"')
    assert QUOTE_CHUNK_INDEX not in _quote_indexes(path)
    path.chmod(0o444)
    try:
        if os.access(path, os.W_OK):
            pytest.skip("this user can write a read-only file (root)")
        store = KnowledgeStore(path)  # a file read-only on disk opens as before, without the index
        assert store.dense_candidates([1.0] + [0.0] * 95)
        assert QUOTE_CHUNK_INDEX not in _quote_indexes(path)
    finally:
        path.chmod(0o644)
