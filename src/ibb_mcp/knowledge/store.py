"""SQLite storage for versioned source pages, chunks, quotes and embeddings."""

from __future__ import annotations

import hashlib
import json
import logging
import pathlib
import sqlite3
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ibb_mcp.text import normalize_tr

log = logging.getLogger(__name__)

#: The join from a chunk to its quotes, on every search. Without it SQLite builds a throwaway automatic
#: index over all quotes per query (EXPLAIN QUERY PLAN: "AUTOMATIC COVERING INDEX (chunk_id=?)").
QUOTE_CHUNK_INDEX = "quotes_chunk_id"


@dataclass(frozen=True, slots=True)
class KnowledgePage:
    """One fetched source version and its provenance metadata."""

    url: str
    canonical_url: str
    title: str
    institution: str
    category: str
    fetched_at: str
    source_updated_at: str | None
    etag: str | None
    last_modified: str | None
    body: str
    content_type: str = "text/html"
    updated_at_method: str = "unknown"
    license_id: str | None = None
    parser_status: str = "ok"
    embedding_model: str | None = None


class KnowledgeStore:
    """A local SQLite index; inactive versions remain available for audit."""

    def __init__(self, path: str | pathlib.Path) -> None:
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fts_available = False
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _init_db(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY, canonical_url TEXT NOT NULL, url TEXT NOT NULL,
                    title TEXT NOT NULL, institution TEXT NOT NULL, service_category TEXT NOT NULL,
                    content_type TEXT NOT NULL, fetched_at TEXT NOT NULL, source_updated_at TEXT,
                    updated_at_method TEXT NOT NULL, etag TEXT, last_modified TEXT,
                    sha256 TEXT NOT NULL, license_id TEXT, parser_status TEXT NOT NULL,
                    body TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(canonical_url, sha256)
                );
                CREATE INDEX IF NOT EXISTS documents_active_url ON documents(canonical_url, active);
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(document_id),
                    ordinal INTEGER NOT NULL, text TEXT NOT NULL, normalized TEXT NOT NULL,
                    page_number INTEGER, section_title TEXT, embedding BLOB,
                    embedding_model TEXT, embedding_dim INTEGER, active INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(document_id, ordinal)
                );
                CREATE TABLE IF NOT EXISTS quotes (
                    quote_id TEXT PRIMARY KEY, chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id),
                    exact_text TEXT NOT NULL, page_no INTEGER, char_start INTEGER NOT NULL, char_end INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS embeddings_cache (
                    cache_key TEXT PRIMARY KEY, vector TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                """
            )
            _ensure_quote_index(db)
            try:
                db.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts "
                    "USING fts5(chunk_id UNINDEXED, normalized, tokenize='unicode61 remove_diacritics 2')"
                )
                db.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('optimize')")
                db.execute("SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH ? LIMIT 1", ('"knowledge-smoke"',))
                self._fts_available = True
            except sqlite3.OperationalError:
                self._fts_available = False

    @property
    def fts_available(self) -> bool:
        return self._fts_available

    def document(self, document_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM documents WHERE document_id=?", (document_id,)).fetchone()
        return dict(row) if row else None

    def current_document(self, url: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM documents WHERE canonical_url=? AND active=1 ORDER BY fetched_at DESC LIMIT 1", (url,)
            ).fetchone()
        return dict(row) if row else None

    def index_built_at(self) -> str | None:
        """Timestamp recorded in the local index metadata."""
        with self._connect() as db:
            row = db.execute("SELECT value FROM meta WHERE key='index_built_at'").fetchone()
            if row:
                return str(row[0])
            fallback = db.execute("SELECT MAX(fetched_at) FROM documents WHERE active=1").fetchone()
        return fallback[0] if fallback else None

    def chunk_count(self, document_id: str) -> int:
        """Count a source version's chunks for crawl reports."""
        with self._connect() as db:
            row = db.execute("SELECT COUNT(*) FROM chunks WHERE document_id=?", (document_id,)).fetchone()
        return int(row[0])

    def upsert_page(
        self,
        page: KnowledgePage,
        chunks: Sequence[Any],
        embeddings: Sequence[Sequence[float] | None],
    ) -> str:
        """Insert a content version once; changed pages deactivate prior versions."""
        content_hash = hashlib.sha256(page.body.encode("utf-8")).hexdigest()
        document_id = hashlib.sha256(f"{page.canonical_url}|{content_hash}".encode()).hexdigest()
        has_fts = self.fts_available
        with self._connect() as db:
            existing = db.execute("SELECT document_id FROM documents WHERE document_id=?", (document_id,)).fetchone()
            db.execute("UPDATE documents SET active=0 WHERE canonical_url=?", (page.canonical_url,))
            db.execute(
                "UPDATE chunks SET active=0 WHERE document_id IN (SELECT document_id FROM documents WHERE canonical_url=?)",
                (page.canonical_url,),
            )
            db.execute(
                """INSERT INTO documents(
                       document_id, canonical_url, url, title, institution, service_category,
                       content_type, fetched_at, source_updated_at, updated_at_method, etag,
                       last_modified, sha256, license_id, parser_status, body, active
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                   ON CONFLICT(document_id) DO UPDATE SET active=1, url=excluded.url,
                   title=excluded.title, institution=excluded.institution,
                   service_category=excluded.service_category, content_type=excluded.content_type,
                   fetched_at=excluded.fetched_at, source_updated_at=excluded.source_updated_at,
                   updated_at_method=excluded.updated_at_method, etag=excluded.etag,
                   last_modified=excluded.last_modified, license_id=excluded.license_id,
                   parser_status=excluded.parser_status""",
                (
                    document_id,
                    page.canonical_url,
                    page.url,
                    page.title,
                    page.institution,
                    page.category,
                    page.content_type,
                    page.fetched_at,
                    page.source_updated_at,
                    page.updated_at_method,
                    page.etag,
                    page.last_modified,
                    content_hash,
                    page.license_id,
                    page.parser_status,
                    page.body,
                ),
            )
            if existing:
                db.execute("UPDATE chunks SET active=1 WHERE document_id=?", (document_id,))
            else:
                page_indexes: dict[int | None, int] = {}
                for ordinal, chunk in enumerate(chunks):
                    page_index = page_indexes.get(chunk.page_number, 0)
                    page_indexes[chunk.page_number] = page_index + 1
                    chunk_id = hashlib.sha256(f"{document_id}|{chunk.page_number}|{page_index}".encode()).hexdigest()[:16]
                    vector = embeddings[ordinal] if ordinal < len(embeddings) else None
                    vector_blob = _encode_vector(vector) if vector is not None else None
                    vector_dim = len(vector) if vector is not None else None
                    db.execute(
                        """INSERT INTO chunks(
                               chunk_id, document_id, ordinal, text, normalized, page_number,
                               section_title, embedding, embedding_model, embedding_dim, active
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                        (
                            chunk_id,
                            document_id,
                            ordinal,
                            chunk.text,
                            normalize_tr(chunk.text),
                            chunk.page_number,
                            chunk.section_title,
                            vector_blob,
                            page.embedding_model if vector is not None else None,
                            vector_dim,
                        ),
                    )
                    if has_fts:
                        db.execute(
                            "INSERT INTO chunks_fts(chunk_id, normalized) VALUES (?, ?)", (chunk_id, normalize_tr(chunk.text))
                        )
                    for quote in chunk.quotes:
                        quote_id = hashlib.sha256(f"{chunk_id}|{quote.char_start}|{quote.char_end}".encode()).hexdigest()[:16]
                        db.execute(
                            "INSERT INTO quotes VALUES (?, ?, ?, ?, ?, ?)",
                            (quote_id, chunk_id, quote.exact_text, chunk.page_number, quote.char_start, quote.char_end),
                        )
            latest = db.execute("SELECT MAX(fetched_at) FROM documents WHERE active=1").fetchone()[0]
            db.execute("INSERT OR REPLACE INTO meta VALUES ('index_built_at', ?)", (latest or page.fetched_at,))
            if page.embedding_model:
                db.execute("INSERT OR REPLACE INTO meta VALUES ('embedder_name', ?)", (page.embedding_model,))
            dimension = next((len(vector) for vector in embeddings if vector is not None), None)
            if dimension:
                db.execute("INSERT OR REPLACE INTO meta VALUES ('dimension', ?)", (str(dimension),))
        return document_id

    def mark_inactive(self, url: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE documents SET active=0 WHERE canonical_url=?", (url,))
            db.execute(
                "UPDATE chunks SET active=0 WHERE document_id IN (SELECT document_id FROM documents WHERE canonical_url=?)",
                (url,),
            )

    def fts_candidates(self, expression: str, limit: int = 30) -> list[dict[str, Any]]:
        if not self.fts_available or not expression:
            return []
        with self._connect() as db:
            rows = db.execute(
                """SELECT c.*, d.url, d.canonical_url, d.title, d.institution,
                          d.service_category AS category, d.fetched_at,
                          d.source_updated_at, d.active AS document_active, q.quote_id, q.exact_text,
                          q.char_start, q.char_end, bm25(chunks_fts) AS rank
                   FROM chunks_fts f JOIN chunks c ON c.chunk_id=f.chunk_id
                   JOIN documents d ON d.document_id=c.document_id
                   LEFT JOIN quotes q ON q.chunk_id=c.chunk_id
                   WHERE chunks_fts MATCH ? AND c.active=1 AND d.active=1
                   ORDER BY rank, c.chunk_id LIMIT ?""",
                (expression, limit * 8),
            ).fetchall()
        return [dict(row) for row in rows]

    def dense_candidates(self, vector: Sequence[float], limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT c.*, d.url, d.canonical_url, d.title, d.institution,
                          d.service_category AS category, d.fetched_at,
                          d.source_updated_at, d.active AS document_active, q.quote_id, q.exact_text,
                          q.char_start, q.char_end
                   FROM chunks c JOIN documents d ON d.document_id=c.document_id
                   LEFT JOIN quotes q ON q.chunk_id=c.chunk_id WHERE c.active=1 AND d.active=1
                   AND c.embedding IS NOT NULL"""
            ).fetchall()
        scored = []
        for row in rows:
            stored = _decode_vector(row["embedding"], row["embedding_dim"])
            cosine = _cosine(vector, stored)
            scored.append((cosine, dict(row)))
        scored.sort(key=lambda pair: (-pair[0], pair[1]["chunk_id"]))
        return [{**row, "cosine": score} for score, row in scored[:limit]]

    def get_quote(self, quote_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                """SELECT q.*, c.document_id, c.active AS chunk_active, d.active AS document_active,
                          d.url, d.canonical_url, d.title, d.institution, d.fetched_at, d.source_updated_at
                   FROM quotes q JOIN chunks c ON c.chunk_id=q.chunk_id JOIN documents d ON d.document_id=c.document_id
                   WHERE q.quote_id=?""",
                (quote_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_embedding_cache(self, key: str) -> list[float] | None:
        with self._connect() as db:
            row = db.execute("SELECT vector FROM embeddings_cache WHERE cache_key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put_embedding_cache(self, key: str, vector: Sequence[float]) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO embeddings_cache VALUES (?, ?)",
                (key, json.dumps(list(vector))),
            )


def _ensure_quote_index(db: sqlite3.Connection) -> None:
    """Add the quotes(chunk_id) index, to an index file built before it existed too.

    Only a writable open or an ingest gets here: the read-only stores open with ``mode=ro`` and never run
    ``_init_db``. It is an optimisation, so it never blocks an open: a file that is read-only on disk, or
    one another writer holds, keeps working without it, as before, and the next writable open adds it.
    """
    try:
        db.execute(f"CREATE INDEX IF NOT EXISTS {QUOTE_CHUNK_INDEX} ON quotes(chunk_id)")
    except sqlite3.OperationalError as exc:
        log.debug("quotes(chunk_id) index not added: %s", exc)


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity with optional NumPy acceleration and a pure-Python fallback."""
    try:
        import numpy as np
    except ImportError:
        pass
    else:
        a, b = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
        denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
        return float(np.dot(a, b) / denominator) if denominator else 0.0
    dot = sum(float(a) * float(b) for a, b in zip(left, right, strict=False))
    denominator = (sum(float(a) ** 2 for a in left) * sum(float(b) ** 2 for b in right)) ** 0.5
    return dot / denominator if denominator else 0.0


def _encode_vector(vector: Sequence[float]) -> bytes:
    """Store normalized embeddings compactly as little-endian float32 values."""
    return struct.pack(f"<{len(vector)}f", *(float(value) for value in vector))


def _decode_vector(payload: bytes | str, dimension: int | None) -> list[float]:
    """Read the current BLOB format and legacy JSON vectors during local upgrades."""
    if isinstance(payload, str):
        return [float(value) for value in json.loads(payload)]
    if not dimension:
        return []
    return list(struct.unpack(f"<{dimension}f", payload))
