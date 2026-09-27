from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_knowledge_store import seed_page

from ibb_mcp.knowledge.answer import KnowledgeAnswer, answer
from ibb_mcp.knowledge.citation_map import (
    CONFLICT_COVERAGE,
    LABELS,
    citation_map,
    labels,
    source_freshness,
    split_sentences,
    support_for,
    value_tokens,
)
from ibb_mcp.knowledge.embed import HashingEmbedder
from ibb_mcp.knowledge.retrieve import Hit
from ibb_mcp.knowledge.store import KnowledgeStore
from nabiz.console.citation_api import citation_routes

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_INDEX = REPO_ROOT / "data/knowledge/knowledge.db"


def _hit(
    quote: str,
    *,
    quote_id: str = "q1",
    url: str = "https://www.iski.istanbul/tarife-a",
    fetched_at: str = "2026-09-26T12:00:00+00:00",
    source_updated_at: str | None = None,
    title: str = "Tarife",
) -> Hit:
    return Hit(
        chunk_id=f"c-{quote_id}", quote_id=quote_id, url=url, title=title, quote=quote, score=1.0,
        fetched_at=fetched_at, source_updated_at=source_updated_at, institution="ISKI", page_number=1,
        section_title="Tarife",
    )


def _map(text: str, citations: tuple[Hit, ...], *, mode: str = "answer", author: str = "kural"):
    result = KnowledgeAnswer(mode, text, citations, author=author)
    return citation_map(result, now=datetime(2026, 9, 27, tzinfo=UTC))


def test_split_sentences_keeps_source_lines_and_referral_tail() -> None:
    parts = split_sentences(
        "Ücret 500 TL olarak uygulanır. Kaynak: https://www.iski.istanbul/tarife-a (2026-09-26). "
        "Doğrulamak için 153 Çözüm Merkezi'ni ara."
    )
    assert [part["kind"] for part in parts] == ["claim", "source_line", "claim"]
    assert parts[1]["text"] == "Kaynak: https://www.iski.istanbul/tarife-a (2026-09-26)."
    assert "153" in parts[2]["text"]
    embedded_word = split_sentences("Kaynak: hizmet rehberinde süreç anlatılır. Kaynak: https://iski.istanbul (2026-09-26).")
    assert [part["kind"] for part in embedded_word] == ["claim", "source_line"]


def test_support_prefers_exact_quote_and_orders_by_coverage() -> None:
    exact = _hit("Öğrenci aylık abonman ücreti 500 TL olarak uygulanır.")
    lexical = _hit(
        "Öğrenci aylık abonman ücreti 650 TL olarak uygulanır.",
        quote_id="q2",
        url="https://www.iski.istanbul/tarife-b",
    )
    support = support_for("Öğrenci aylık abonman ücreti 500 TL olarak uygulanır.", [exact, lexical])
    assert support[0]["match"] == "verbatim" and support[0]["coverage"] == 1.0
    assert support[1]["match"] == "lexical" and support[1]["coverage"] >= CONFLICT_COVERAGE


def test_value_tokens_normalize_values_and_skip_call_numbers_and_url_digits() -> None:
    values = value_tokens("Ücret 500 TL, saat 09:30, tarih 13.01.2025, indirim %15; 153. https://site.test/2026/650")
    assert values == {"500 TL", "09:30", "13.01.2025", "15%"}
    assert value_tokens("Ücret 650,50 ₺") == {"650.50 ₺"}


def test_labels_support_turkish_and_english_and_fallback() -> None:
    assert labels("tr") == LABELS["tr"]
    assert labels("en") == LABELS["en"]
    assert labels("ar") == LABELS["tr"]
    visible = " ".join(value for language in LABELS.values() for value in language.values())
    assert all(mark not in visible for mark in ("—", "–"))
    assert "ETA" not in visible and "canlı" not in visible


def test_unknown_answer_has_an_empty_map() -> None:
    hit = _hit("Ücret 500 TL.")
    result = citation_map(
        KnowledgeAnswer("unknown", "cevap bulunamadı", (hit,)),
        now=datetime(2026, 9, 27, tzinfo=UTC),
    )
    assert result["mode"] == "unknown" and result["note"] == "unknown"
    assert result["sentences"] == result["sources"] == result["conflicts"] == []
    assert result["summary"] == {
        "sentences": 0, "supported": 0, "no_source": 0, "referral": 0, "sources": 0, "conflicts": 0, "stale": 0,
    }


def test_freshness_uses_store_method_and_unknown_bad_dates(tmp_path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    seed_page(store, "Su aboneliği başvurusu resmî kaynakta açıklanır.")
    with store._connect() as db:
        row = db.execute("SELECT quote_id FROM quotes LIMIT 1").fetchone()
    hit = _hit("Su aboneliği başvurusu resmî kaynakta açıklanır.", quote_id=row["quote_id"])
    current = datetime.fromisoformat(hit.fetched_at)
    freshness = source_freshness(hit, store=store, now=current + timedelta(seconds=120), sla_s=60)
    assert freshness["updated_at_method"] == "unknown"
    assert freshness["age_days"] == 0 and freshness["stale"] is True

    malformed = _hit("Kaynak tarihi yok.", fetched_at="tarih yok", quote_id="missing")
    freshness = source_freshness(malformed, store=None, now=datetime(2026, 9, 27, tzinfo=UTC), sla_s=60)
    assert freshness["fetched_at"] == "tarih yok"
    assert freshness["age_days"] is None and freshness["stale"] is None
    assert freshness["updated_at_method"] is None


def test_seeded_conflict_is_reported_once_and_same_values_are_not_a_conflict(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NABIZ_KNOWLEDGE_FTS_MIN", "0")
    monkeypatch.delenv("NABIZ_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("NABIZ_LLM_API_KEY", raising=False)
    store = KnowledgeStore(tmp_path / "knowledge.db")
    seed_page(store, "Öğrenci aylık abonman ücreti 500 TL olarak uygulanır.", "https://www.iski.istanbul/tarife-a")
    seed_page(store, "Öğrenci aylık abonman ücreti 650 TL olarak uygulanır.", "https://www.iski.istanbul/tarife-b")
    result = asyncio.run(answer("Öğrenci aylık abonman ücreti ne kadar?", store=store, embedder=None))
    mapped = citation_map(result, store=store)
    assert result.mode == "answer" and len(result.citations) == 2
    assert len(mapped["conflicts"]) == 1
    expected_newer = max(
        range(2),
        key=lambda index: datetime.fromisoformat(result.citations[index].fetched_at),
    )
    assert mapped["conflicts"] == [
        {
            "sentence": 0,
            "between": [0, 1],
            "kind": "value",
            "values": [["500 TL"], ["650 TL"]],
            "newer": expected_newer,
        }
    ]
    assert mapped["sentences"][0]["conflict"] == 0
    assert mapped["sentences"][1]["conflict"] is None
    same = [
        _hit("Öğrenci aylık abonman ücreti 500 TL olarak uygulanır.", quote_id="q1"),
        _hit(
            "Öğrenci aylık abonman ücreti 500 TL olarak uygulanır.",
            quote_id="q2", url="https://www.iski.istanbul/tarife-b",
        ),
    ]
    same_map = _map(
        "Öğrenci aylık abonman ücreti 500 TL olarak uygulanır.", tuple(same)
    )
    assert same_map["conflicts"] == []
    same_document = (
        same[0],
        _hit(
            "Öğrenci aylık abonman ücreti 650 TL olarak uygulanır.",
            quote_id="q3",
            url=same[0].url,
        ),
    )
    same_document_map = _map("Öğrenci aylık abonman ücreti 500 TL olarak uygulanır.", same_document)
    assert same_document_map["conflicts"] == []


def test_unmatched_claim_is_reported_without_filling_it_in() -> None:
    mapped = _map(
        "İade başvurusu pazartesi başlar.",
        (_hit("Öğrenci aylık abonman ücreti 500 TL olarak uygulanır."),),
    )
    assert mapped["sentences"][0]["status"] == "no_source"
    assert mapped["summary"]["no_source"] == 1


def test_conflict_prefers_page_update_time_over_fetch_time() -> None:
    citations = (
        _hit(
            "Öğrenci aylık abonman ücreti 500 TL olarak uygulanır.",
            fetched_at="2026-09-27T00:00:00+00:00",
            source_updated_at="2025-01-01T00:00:00+00:00",
        ),
        _hit(
            "Öğrenci aylık abonman ücreti 650 TL olarak uygulanır.",
            quote_id="q2",
            url="https://www.iski.istanbul/tarife-b",
            fetched_at="2026-09-26T00:00:00+00:00",
            source_updated_at="2026-01-01T00:00:00+00:00",
        ),
    )
    mapped = _map("Öğrenci aylık abonman ücreti 500 TL olarak uygulanır.", citations)
    assert mapped["conflicts"][0]["newer"] == 1


def test_single_document_and_referral_never_create_conflicts() -> None:
    hit = _hit("Öğrenci aylık abonman ücreti 500 TL olarak uygulanır.")
    mapped = _map(
        "Öğrenci aylık abonman ücreti 500 TL olarak uygulanır. "
        "Doğrulamak için 153 Çözüm Merkezi'ni ara.",
        (hit,),
        mode="quote_only",
    )
    assert mapped["summary"]["referral"] == 1
    assert mapped["sentences"][1]["kind"] == "referral"
    assert mapped["sentences"][1]["status"] == "n/a"
    assert mapped["conflicts"] == []


def test_model_answer_maps_multiple_sources_and_lexical_support(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NABIZ_KNOWLEDGE_FTS_MIN", "0")
    monkeypatch.delenv("NABIZ_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("NABIZ_LLM_API_KEY", raising=False)
    store = KnowledgeStore(tmp_path / "knowledge.db")
    seed_page(store, "Başvuru formu çevrimiçi olarak tamamlanır.", "https://www.iski.istanbul/basvuru-a")
    seed_page(store, "Başvuru formu çevrimiçi olarak tamamlanır.", "https://www.iski.istanbul/basvuru-b")

    async def generate(_messages: list[dict[str, str]]) -> str:
        return json.dumps(
            {
                "mode": "answer",
                "claims": [
                    {
                        "text": "Başvuru çevrimiçi form üzerinden tamamlanır. Ücret 999 TL'dir.",
                        "evidence_ids": [
                            hit["quote_id"] for hit in store.fts_candidates('"basvuru"', 10)
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )

    result = asyncio.run(
        answer("Başvuru formu nereden tamamlanır?", store=store, embedder=HashingEmbedder(), generate=generate)
    )
    assert result.mode == "answer" and result.author == "model"
    mapped = citation_map(result, store=store)
    assert mapped["sentences"][0]["kind"] == "claim"
    assert mapped["sentences"][0]["status"] == "supported"
    assert {item["match"] for item in mapped["sentences"][0]["support"]} == {"lexical"}
    assert "999" not in result.text
    assert mapped["summary"]["no_source"] == 0

    import ibb_mcp.knowledge.citation_map as module

    assert not any(name in module.__dict__ for name in ("_display_text", "_terms", "_supported_claim"))
    assert all(not name.startswith("nabiz.") for name in module.__dict__)


def _read_only_store(path: Path) -> KnowledgeStore:
    class ReadOnlyStore(KnowledgeStore):
        def __init__(self, database: Path) -> None:
            self.path = database
            self._fts_available = True

        def _connect(self):
            connection = sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True, timeout=15)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            return connection

    return ReadOnlyStore(path)


def test_real_index_targets_and_calibration_structure(monkeypatch) -> None:
    if not REAL_INDEX.is_file():
        pytest.skip("gerçek dizin kopyası yok")
    monkeypatch.delenv("NABIZ_KNOWLEDGE_FTS_MIN", raising=False)
    monkeypatch.delenv("NABIZ_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("NABIZ_LLM_API_KEY", raising=False)
    store = _read_only_store(REAL_INDEX)
    with store._connect() as db:
        has_fts = db.execute("SELECT 1 FROM sqlite_master WHERE name='chunks_fts'").fetchone()
    if not has_fts:
        pytest.skip("gerçek dizinde FTS indeksi yok")

    questions = [json.loads(line) for line in (REPO_ROOT / "eval/knowledge_calibration.jsonl").read_text().splitlines()]
    results = {
        row["id"]: asyncio.run(answer(row["question"], store=store, embedder=None))
        for row in questions
    }
    target = results["h-15"]
    mapped = citation_map(target, store=store)
    assert target.mode == "answer" and len(target.citations) == 3
    assert len({hit.url for hit in target.citations}) == 3
    assert all(sentence["status"] == "supported" for sentence in mapped["sentences"] if sentence["kind"] == "claim")
    assert all(sentence["support"][0]["match"] == "verbatim" for sentence in mapped["sentences"] if sentence["kind"] == "claim")
    assert all(
        source["fetched_at"] and source["updated_at_method"] in {"meta", "heuristic", "unknown"}
        for source in mapped["sources"]
    )
    assert len(mapped["sources"]) == len(target.citations)

    for target_id in ("h-13", "k-14"):
        target_result = results[target_id]
        target_map = citation_map(target_result, store=store)
        assert target_result.mode == "answer"
        assert all(
            sentence["status"] == "supported"
            for sentence in target_map["sentences"]
            if sentence["kind"] == "claim"
        )

    for result in results.values():
        evidence_map = citation_map(result, store=store)
        assert len(evidence_map["sources"]) == len(result.citations)
        assert evidence_map["summary"]["sentences"] == len(evidence_map["sentences"])
        assert evidence_map["summary"]["conflicts"] == len(evidence_map["conflicts"])
        assert all(
            0 <= support["citation"] < len(result.citations)
            for sentence in evidence_map["sentences"]
            for support in sentence["support"]
        )
        for sentence in evidence_map["sentences"]:
            if sentence["kind"] == "source_line":
                assert sentence["citation"] is not None
                assert result.citations[sentence["citation"]].url in sentence["text"]
        if result.mode == "answer":
            assert all(
                sentence["status"] == "supported"
                for sentence in evidence_map["sentences"]
                if sentence["kind"] == "claim"
            )
        visible = " ".join(value for language in LABELS.values() for value in language.values())
        assert all(mark not in visible for mark in ("—", "–"))


def _client(store: KnowledgeStore | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(citation_routes)
    if store is not None:
        app.state.knowledge_store = store
        app.state.knowledge_embedder = None
    return TestClient(app)


def test_citation_endpoint_returns_answer_map_and_labels(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NABIZ_KNOWLEDGE_FTS_MIN", "0")
    store = KnowledgeStore(tmp_path / "knowledge.db")
    seed_page(store, "Su aboneliği başvurusu resmî kaynakta açıklanır.")
    response = _client(store).post(
        "/api/knowledge/citations",
        json={"question": "Su aboneliği başvurusu nasıl yapılır?", "lang": "en"},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"mode", "answer", "citations", "steps", "citation_map", "labels"}
    assert body["citation_map"]["sources"][0]["fetched_at"]
    assert body["labels"]["no_source"] == "No source yet for this sentence"


@pytest.mark.parametrize(
    "body",
    [{}, {"question": " "}, {"question": "x" * 201}, {"question": "su", "lang": "ar"}],
)
def test_citation_endpoint_rejects_invalid_body(body) -> None:
    response = _client().post("/api/knowledge/citations", json=body)
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_question"


def test_citation_endpoint_rejects_unreadable_body() -> None:
    response = _client().post(
        "/api/knowledge/citations", content=b"not json", headers={"content-type": "application/json"}
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_body"


def test_citation_endpoint_reports_missing_index(monkeypatch) -> None:
    import nabiz.console.citation_api as module

    monkeypatch.setattr(module, "open_from_env", lambda: (None, None))
    response = _client().post("/api/knowledge/citations", json={"question": "Su aboneliği nasıl yapılır?"})
    assert response.status_code == 503
    assert response.json()["error"] == "knowledge_index_missing"
