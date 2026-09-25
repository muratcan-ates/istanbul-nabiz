from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_knowledge_store import seed_page

from ibb_mcp.knowledge.store import KnowledgeStore
from nabiz.console.knowledge_api import knowledge_routes


def client() -> TestClient:
    app = FastAPI()
    app.include_router(knowledge_routes)
    return TestClient(app)


def test_search_returns_hit_schema(tmp_path, monkeypatch) -> None:
    store_path = tmp_path / "knowledge.db"
    seed_page(KnowledgeStore(store_path), "Su aboneliği başvurusu resmî kaynak sayfasında açıklanır.")
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(store_path))
    monkeypatch.delenv("NABIZ_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("NABIZ_LLM_API_KEY", raising=False)
    response = client().get("/api/knowledge/search", params={"q": "su aboneliği"})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "hybrid" or body["mode"] == "fts"
    assert set(body["hits"][0]) == {
        "chunk_id",
        "quote_id",
        "url",
        "title",
        "quote",
        "score",
        "fetched_at",
        "source_updated_at",
        "institution",
        "page_number",
        "section_title",
    }


def test_ask_returns_answer_schema(tmp_path, monkeypatch) -> None:
    store_path = tmp_path / "knowledge.db"
    seed_page(KnowledgeStore(store_path), "Su aboneliği başvurusu resmî kaynak sayfasında açıklanır.")
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(store_path))
    monkeypatch.delenv("NABIZ_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("NABIZ_LLM_API_KEY", raising=False)
    response = client().post("/api/knowledge/ask", json={"question": "Su aboneliği başvurusu nasıl yapılır?", "lang": "tr"})
    assert response.status_code == 200
    assert set(response.json()) == {"mode", "answer", "citations", "steps"}


def test_missing_index_answers_503(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(tmp_path / "missing.db"))
    monkeypatch.delenv("NABIZ_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("NABIZ_LLM_API_KEY", raising=False)
    response = client().get("/api/knowledge/search", params={"q": "su aboneliği"})
    assert response.status_code == 503 and response.json() == {"error": "knowledge_index_missing"}


def test_empty_query_is_a_bad_request() -> None:
    assert client().get("/api/knowledge/search", params={"q": " "}).status_code == 400
