from __future__ import annotations

import asyncio
import json

from test_knowledge_store import seed_page

from ibb_mcp.knowledge.answer import answer
from ibb_mcp.knowledge.embed import HashingEmbedder
from ibb_mcp.knowledge.store import KnowledgeStore


def make_store(tmp_path, body: str) -> KnowledgeStore:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    seed_page(store, body)
    return store


def test_a_sensitive_question_quotes_the_source_and_153(tmp_path) -> None:
    quote = "Su abonelik ücreti başvuru sırasında resmî kaynakta açıklanır."
    result = asyncio.run(
        answer("Su abonelik ücreti nedir?", store=make_store(tmp_path, quote), embedder=HashingEmbedder(), sensitive=True)
    )
    assert result.mode == "quote_only" and result.refused and result.author == "kural"
    assert quote in result.text and "https://www.iski.istanbul/abonelik" in result.text
    assert result.citations[0].fetched_at[:10] in result.text and "153" in result.text


def test_sensitivity_is_decided_by_the_caller_not_the_package(tmp_path) -> None:
    store = make_store(tmp_path, "Su abonelik ücreti başvuru sırasında resmî kaynakta açıklanır.")
    result = asyncio.run(answer("Su abonelik ücreti nedir?", store=store, embedder=HashingEmbedder(), sensitive=False))
    assert result.mode == "answer" and not result.refused
    import ibb_mcp.knowledge.answer as module

    assert "policy" not in module.__dict__
    assert all(not name.startswith("nabiz.") for name in module.__dict__)


def test_out_of_scope_says_bilmiyorum_153(tmp_path) -> None:
    store = make_store(tmp_path, "Su abonelik başvurusu kurumun kaynak sayfasında yazılıdır.")
    result = asyncio.run(answer("Kutup ayısı nerede yaşar?", store=store, embedder=HashingEmbedder()))
    assert result.mode == "unknown" and "153" in result.text and not result.citations


def test_extractive_answer_carries_url_and_date(tmp_path) -> None:
    store = make_store(tmp_path, "Su aboneliği başvurusu resmî kaynakta açıklanır.")
    result = asyncio.run(answer("Su aboneliği başvurusu nasıl yapılır?", store=store, embedder=HashingEmbedder()))
    assert result.mode == "answer"
    assert "https://www.iski.istanbul/abonelik" in result.text
    assert result.citations[0].fetched_at[:10] in result.text


def test_text_has_no_eta_or_long_dash(tmp_path) -> None:
    store = make_store(tmp_path, "Su aboneliği başvurusu için güncel bilgi ETA — resmî kaynakta açıklanır.")
    result = asyncio.run(answer("Su aboneliği başvurusu ETA", store=store, embedder=HashingEmbedder()))
    assert "ETA" not in result.text and "—" not in result.text and "–" not in result.text


def test_model_never_writes_url_or_quote_only_evidence_ids(tmp_path) -> None:
    store = make_store(tmp_path, "Su aboneliği başvurusu resmî kaynakta açıklanır.")
    prompts = []

    async def generate(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps(
            {
                "mode": "answer",
                "claims": [{"text": "Su aboneliği için https://fake.invalid başvur.", "evidence_ids": ["fabricated"]}],
            }
        )

    result = asyncio.run(
        answer("Su aboneliği başvurusu nasıl yapılır?", store=store, embedder=HashingEmbedder(), generate=generate)
    )
    assert result.mode == "unknown"
    assert prompts and "untrusted evidence data" in prompts[0]
