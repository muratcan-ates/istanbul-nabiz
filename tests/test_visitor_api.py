from __future__ import annotations

import asyncio
import datetime as dt
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ibb_mcp.knowledge.chunking import PageBlock, chunk_blocks
from ibb_mcp.knowledge.embed import HashingEmbedder
from ibb_mcp.knowledge.store import KnowledgePage, KnowledgeStore
from nabiz.console import culture_api, visitor
from nabiz.console.visitor_api import visitor_routes


def _visitor_client(store: KnowledgeStore | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(visitor_routes)
    if store is not None:
        app.state.knowledge_store = store
        app.state.knowledge_embedder = None
    return TestClient(app)


def _seed_api_pages(store: KnowledgeStore) -> None:
    quotes_by_url: dict[str, list[dict]] = {}
    for question in visitor.load_visitor_questions():
        for quote in question.get("quotes", []):
            quotes_by_url.setdefault(quote["source_url"], []).append(quote)
    for url, quotes in quotes_by_url.items():
        body = "\n\n".join(quote["tr"] for quote in quotes) + "\n\nWitness paragraph is not approved for display."
        host = url.split("/", 3)[2]
        institution = "IETT" if host == "iett.istanbul" else "METRO_ISTANBUL" if "metro.istanbul" in host else "SEHIR_HATLARI"
        embedder = HashingEmbedder()
        chunks = chunk_blocks([PageBlock(body, 1, "Official page")])
        vectors = asyncio.run(embedder.embed_documents([chunk.text for chunk in chunks]))
        store.upsert_page(
            KnowledgePage(
                url=url,
                canonical_url=url,
                title="Official source",
                institution=institution,
                category="visitor",
                fetched_at=dt.datetime.now(dt.UTC).isoformat(),
                source_updated_at=None,
                etag=None,
                last_modified=None,
                body=body,
                embedding_model=embedder.name,
            ),
            chunks,
            vectors,
        )


@pytest.fixture(autouse=True)
def visitor_api_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NABIZ_OFFLINE", "1")
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(tmp_path / "unused.db"))
    monkeypatch.delenv(visitor.QUOTES_ENV, raising=False)
    monkeypatch.delenv(visitor.FRESHNESS_ENV, raising=False)
    visitor.load_visitor_questions.cache_clear()
    culture_api.load_venues.cache_clear()


def test_endpoint_returns_only_the_five_pinned_questions(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    _seed_api_pages(store)
    response = _visitor_client(store).get("/api/visitor")
    body = response.json()
    assert response.status_code == 200
    assert [item["id"] for item in body["questions"]] == ["museums", "airport", "emergency", "istanbulkart", "step_free"]
    assert body["index"]["state"] == "ready" and body["index"]["built_at"]
    rendered = json.dumps(body, ensure_ascii=False).casefold()
    assert "witness paragraph" not in rendered
    by_id = {item["id"]: item for item in body["questions"]}
    assert sum(len(source["quotes"]) for source in by_id["airport"]["sources"]) == 10
    assert by_id["airport"]["sources"][0]["page_date"] is not None
    assert len(by_id["step_free"]["sources"]) == 2


def test_missing_index_keeps_museums_and_emergency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(tmp_path / "missing.db"))
    body = _visitor_client().get("/api/visitor").json()
    assert [item["id"] for item in body["questions"]] == ["museums", "emergency"]
    assert body["index"] == {"state": "missing", "built_at": None}


def test_quotes_can_be_disabled_without_hiding_local_questions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(visitor.QUOTES_ENV, "0")
    store = KnowledgeStore(tmp_path / "knowledge.db")
    _seed_api_pages(store)
    body = _visitor_client(store).get("/api/visitor").json()
    assert [item["id"] for item in body["questions"]] == ["museums", "emergency"]
    assert body["quotes_enabled"] is False


def test_missing_museum_capture_hides_only_the_museum_question(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(culture_api, "CULTURE_DIR", tmp_path / "empty")
    culture_api.load_venues.cache_clear()
    body = _visitor_client().get("/api/visitor").json()
    assert [item["id"] for item in body["questions"]] == ["emergency"]


def test_unreadable_catalog_returns_a_controlled_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad_catalog = tmp_path / "broken.json"
    bad_catalog.write_text("{", encoding="utf-8")
    monkeypatch.setattr(visitor, "QUESTIONS_PATH", bad_catalog)
    visitor.load_visitor_questions.cache_clear()
    response = _visitor_client().get("/api/visitor")
    assert response.status_code == 500
    assert response.json()["error"] == "visitor_questions_unreadable"
    assert response.json()["message"] == "Ziyaretçi soruları şu an yüklenemedi."


def test_second_request_uses_the_app_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    _seed_api_pages(store)
    calls = 0
    original = KnowledgeStore.current_document

    def counted(instance: KnowledgeStore, url: str):
        nonlocal calls
        calls += 1
        return original(instance, url)

    monkeypatch.setattr(KnowledgeStore, "current_document", counted)
    client = _visitor_client(store)
    first = client.get("/api/visitor").json()
    first_calls = calls
    second = client.get("/api/visitor").json()
    assert first == second
    assert calls == first_calls == 4


def test_endpoint_makes_no_outbound_requests(_no_outbound_network: list[str]) -> None:
    response = _visitor_client().get("/api/visitor")
    assert response.status_code == 200
    assert _no_outbound_network == []
