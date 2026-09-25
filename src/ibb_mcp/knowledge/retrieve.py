# Ported from DOU-Synapse apps/api/app/modules/retrieval/fusion.py (github.com/muratcan-ates/DOU-Synapse @ 2cbe1ea, MIT, Copyright (c) 2026 Muratcan Ates)  # noqa: E501
# FTS policy adapted from apps/api/app/modules/retrieval/fts.py at the same revision.
"""Hybrid local retrieval; a future Azure AI Search adapter stays outside the critical path."""

from __future__ import annotations

import re
from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from typing import Protocol

from ibb_mcp.text import normalize_tr

from .embed import Embedder
from .stopwords_tr import FUNCTION_WORDS_TR
from .store import KnowledgeStore

DEFAULT_RRF_K = 60


@dataclass(frozen=True, slots=True)
class Hit:
    """A source-backed search result using the public knowledge contract."""

    chunk_id: str
    quote_id: str
    url: str
    title: str
    quote: str
    score: float
    fetched_at: str
    source_updated_at: str | None
    institution: str
    page_number: int | None
    section_title: str | None
    cosine: float | None = None
    bm25: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "quote_id": self.quote_id,
            "url": self.url,
            "title": self.title,
            "quote": self.quote,
            "score": self.score,
            "fetched_at": self.fetched_at,
            "source_updated_at": self.source_updated_at,
            "institution": self.institution,
            "page_number": self.page_number,
            "section_title": self.section_title,
        }


class Retriever(Protocol):
    """Search adapter boundary; Azure AI Search may be added here outside the critical path."""

    async def search(self, query: str, *, limit: int) -> list[Hit]: ...


def uses_explicit_operators(query: str) -> bool:
    """Return whether a user deliberately supplied FTS phrase, NOT, or OR syntax."""
    return bool(re.search(r'"[^"\n]+"|(?:^|\s)-\w+|\bOR\b', query, flags=re.IGNORECASE))


def fts_match_expression(query: str) -> str:
    """Build safe FTS5 syntax; plain Turkish queries relax to OR between terms."""
    if uses_explicit_operators(query):
        terms = re.findall(r'"[^"\n]+"|-?[\w]+|\bOR\b', query, flags=re.IGNORECASE)
        clean: list[str] = []
        for term in terms:
            if term.upper() == "OR":
                clean.append("OR")
            elif term.startswith('"'):
                clean.append('"' + normalize_tr(term[1:-1]).replace(" ", " ") + '"')
            else:
                clean.append(("NOT " if term.startswith("-") else "") + '"' + normalize_tr(term.lstrip("-")) + '"')
        expression = " ".join(part for part in clean if part not in {"", '""'})
        return expression.removeprefix("NOT ")
    words = [word for word in normalize_tr(query).split() if word not in FUNCTION_WORDS_TR]
    return " OR ".join(f'"{word}"' for word in words)


def reciprocal_rank_fusion[T: Hashable](rankings: Sequence[Sequence[T]], *, k: int = DEFAULT_RRF_K) -> list[tuple[T, float]]:
    """Fuse ordered result lists with deterministic ties, preserving first-seen order."""
    scores: dict[T, float] = {}
    best_rank: dict[T, int] = {}
    first_seen: dict[T, int] = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            best_rank[key] = min(best_rank.get(key, rank), rank)
            first_seen.setdefault(key, len(first_seen))
    return sorted(scores.items(), key=lambda item: (-item[1], best_rank[item[0]], first_seen[item[0]]))


def max_possible_score(ranking_count: int, *, k: int = DEFAULT_RRF_K) -> float:
    """Return the maximum RRF score when every ranking agrees on rank one."""
    return ranking_count / (k + 1)


def _representative(rows: Sequence[dict], query: str, *, score: float) -> Hit | None:
    if not rows:
        return None
    rows = [row for row in rows if row.get("exact_text") and len(row["exact_text"]) <= 300]
    if not rows:
        return None
    terms = set(normalize_tr(query).split()) - FUNCTION_WORDS_TR
    row = max(
        rows,
        key=lambda item: (
            len(terms & set(normalize_tr(item.get("exact_text") or "").split())),
            -(abs(float(item.get("rank", 0.0)))),
            item.get("quote_id") or "",
        ),
    )
    if not row.get("quote_id") or not row.get("exact_text"):
        return None
    return Hit(
        chunk_id=row["chunk_id"],
        quote_id=row["quote_id"],
        url=row["url"],
        title=row["title"],
        quote=row["exact_text"],
        score=score,
        fetched_at=row["fetched_at"],
        source_updated_at=row.get("source_updated_at"),
        institution=row["institution"],
        page_number=row.get("page_number"),
        section_title=row.get("section_title"),
        cosine=max((float(item["cosine"]) for item in rows if item.get("cosine") is not None), default=None),
        bm25=min((abs(float(item["rank"])) for item in rows if item.get("rank") is not None), default=None),
    )


async def search(
    store: KnowledgeStore,
    query: str,
    *,
    embedder: Embedder | None,
    limit: int = 5,
) -> list[Hit]:
    """Search top-30 lexical and dense candidates, then return source-backed evidence."""
    if not query.strip() or limit < 1:
        return []
    expression = fts_match_expression(query)
    fts_rows = store.fts_candidates(expression, 30) if store.fts_available else []
    dense_rows = store.dense_candidates(await embedder.embed_query(query), 30) if embedder else []
    by_chunk: dict[str, list[dict]] = {}
    for row in [*fts_rows, *dense_rows]:
        by_chunk.setdefault(row["chunk_id"], []).append(row)
    fts_ids = list(dict.fromkeys(row["chunk_id"] for row in fts_rows))
    dense_ids = list(dict.fromkeys(row["chunk_id"] for row in dense_rows))
    ranked = (
        reciprocal_rank_fusion([fts_ids, dense_ids])
        if fts_ids and dense_ids
        else [(chunk_id, 1.0 / (DEFAULT_RRF_K + rank)) for rank, chunk_id in enumerate(fts_ids or dense_ids, start=1)]
    )
    hits = []
    for chunk_id, score in ranked:
        hit = _representative(by_chunk[chunk_id], query, score=score)
        if hit:
            hits.append(hit)
        if len(hits) >= min(limit, 8):
            break
    return hits
