from __future__ import annotations

import asyncio
import json

from test_knowledge_store import seed_page

from ibb_mcp.knowledge.answer import answer, assess_evidence, evidence_thresholds, lexical_coverage
from ibb_mcp.knowledge.embed import HashingEmbedder
from ibb_mcp.knowledge.retrieve import Hit
from ibb_mcp.knowledge.stopwords_tr import FOLDED_FUNCTION_WORDS_TR
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

    async def generate(messages: list[dict[str, str]]) -> str:
        prompts.append(messages)
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
    assert prompts and [message["role"] for message in prompts[0]] == ["system", "user"]
    assert "untrusted evidence data" in prompts[0][0]["content"]


# -- the evidence thresholds, measured 26 Sep (DECISIONS #36) -------------------------------------
def _hit(quote: str, *, bm25: float | None = None, cosine: float | None = None, quote_id: str = "q1") -> Hit:
    return Hit(
        chunk_id="c1", quote_id=quote_id, url="https://www.iski.istanbul/abonelik", title="t", quote=quote, score=1.0,
        fetched_at="2026-09-26T00:00:00+00:00", source_updated_at=None, institution="ISKI", page_number=None,
        section_title=None, cosine=cosine, bm25=bm25,
    )  # fmt: skip


STATEMENT = "Gece Metrosu, Cuma'yı Cumartesi'ye ve Cumartesi'yi Pazar'a bağlayan gecelerde gerçekleştirilecektir."


def test_a_stronger_bm25_match_is_better_evidence_not_worse() -> None:
    """FTS5 scores are negative, and their magnitude grows with the match; the first version compared the
    smallest magnitude against a ceiling, so on the real index nothing was sufficient."""
    query = "Gece metrosu hangi günler çalışıyor?"
    strong = assess_evidence([_hit(STATEMENT, bm25=17.2), _hit(STATEMENT, bm25=3.0, quote_id="q2")], query=query)
    weak = assess_evidence([_hit(STATEMENT, bm25=9.0)], query=query)
    assert strong.level == "sufficient" and strong.best_bm25 == 17.2
    assert weak.level == "weak"


def test_function_words_are_folded_before_coverage() -> None:
    """"nasıl" folds to "nasil"; unfolded, it counted as a distinctive word and any "... nasıl yapılır?"
    heading covered the question."""
    unrelated = _hit("Spor okulu iade işlemleri nasıl yapılır diye sorulur.")
    assert lexical_coverage("Pasaport başvurusu nasıl yapılır?", [unrelated]) == 0.0
    assert {"nasil", "icin", "yapilir", "cok"} <= FOLDED_FUNCTION_WORDS_TR


def test_the_first_quote_carries_the_verdict() -> None:
    """Coverage is read on the first quote, the one an answer shows first; a better quote further down the
    list does not lift a first quote that misses the question."""
    query = "Gece metrosu hangi günler çalışıyor?"
    off_topic = _hit("Spor salonu üyelik iade işlemleri şubelerden yapılır.", bm25=20.0)
    assert assess_evidence([off_topic, _hit(STATEMENT, bm25=19.0, quote_id="q2")], query=query).level != "sufficient"
    assert assess_evidence([_hit(STATEMENT, bm25=20.0), off_topic], query=query).level == "sufficient"


def test_a_sensitive_question_with_weak_evidence_gets_no_quote(tmp_path, monkeypatch) -> None:
    """A weak match on a fare question is not quoted: a wrong page's sentence would read like İBB's answer."""
    monkeypatch.setenv("NABIZ_KNOWLEDGE_FTS_MIN", "1000")
    store = make_store(tmp_path, "Su abonelik ücreti başvuru sırasında resmî kaynakta açıklanır.")
    result = asyncio.run(answer("Su abonelik ücreti nedir?", store=store, embedder=None, sensitive=True))
    assert result.mode == "unknown" and result.refused and not result.citations


def test_the_thresholds_are_knobs_with_measured_defaults(monkeypatch) -> None:
    for knob in ("MIN_COSINE", "FTS_MIN", "MIN_COVERAGE", "COVERAGE_CEILING"):
        monkeypatch.delenv(f"NABIZ_KNOWLEDGE_{knob}", raising=False)
    assert evidence_thresholds() == {"min_cosine": 0.35, "fts_min": 16.0, "min_coverage": 0.5, "coverage_ceiling": 0.27}
    monkeypatch.setenv("NABIZ_KNOWLEDGE_FTS_MIN", "9")
    assert evidence_thresholds()["fts_min"] == 9.0
