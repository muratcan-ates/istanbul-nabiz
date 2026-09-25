from __future__ import annotations

import asyncio

from test_knowledge_store import seed_page

from ibb_mcp.knowledge.embed import HashingEmbedder
from ibb_mcp.knowledge.retrieve import fts_match_expression, reciprocal_rank_fusion, search, uses_explicit_operators
from ibb_mcp.knowledge.store import KnowledgeStore


def test_rrf_hand_computed() -> None:
    assert reciprocal_rank_fusion([["a", "b"], ["b", "a"]]) == [("a", 1 / 61 + 1 / 62), ("b", 1 / 62 + 1 / 61)]


def test_rrf_ties_are_deterministic() -> None:
    assert reciprocal_rank_fusion([["b", "a"], ["a", "b"]]) == [("b", 1 / 61 + 1 / 62), ("a", 1 / 62 + 1 / 61)]


def test_explicit_operators_detected() -> None:
    assert uses_explicit_operators('"su aboneliği" -iptal')
    assert uses_explicit_operators("su OR abonelik")


def test_plain_query_relaxes_to_or() -> None:
    assert fts_match_expression("su aboneliği") == '"su" OR "aboneligi"'


def test_search_returns_quote_with_source_metadata(tmp_path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    seed_page(store, "Su aboneliği başvurusu resmî kaynak sayfasında açıklanır.")
    hits = asyncio.run(search(store, "su aboneliği", embedder=HashingEmbedder()))
    assert hits and hits[0].quote == "Su aboneliği başvurusu resmî kaynak sayfasında açıklanır."
    assert hits[0].fetched_at and hits[0].url.startswith("https://")
