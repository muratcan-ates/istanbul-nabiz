from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from conftest import REPO_ROOT
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_knowledge_store import seed_page

from ibb_mcp.knowledge.store import KnowledgeStore
from nabiz.console import audience_api, quick_api

CATALOG_PATH = REPO_ROOT / "data/knowledge/audience_suggestions.json"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(audience_api.audience_routes)
    return TestClient(app)


def _offline(monkeypatch, database: Path) -> None:
    monkeypatch.setenv("NABIZ_OFFLINE", "1")
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(database))
    monkeypatch.delenv("NABIZ_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("NABIZ_LLM_API_KEY", raising=False)
    monkeypatch.delenv("NABIZ_QUICK_KNOWLEDGE", raising=False)
    monkeypatch.delenv("NABIZ_KNOWLEDGE_FTS_MIN", raising=False)


def _one_page_floor(monkeypatch) -> None:
    monkeypatch.setenv("NABIZ_KNOWLEDGE_FTS_MIN", "0")


def _shown(response) -> set[str]:
    return {item["id"] for item in response.json()["suggestions"]}


def _student_question() -> dict:
    item = next(row for row in json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["oneriler"] if row["id"] == "b-ogrenci-kart")
    return {"kind": "knowledge", "id": item["id"], "soru_tr": item["metin_tr"], "source_url": item["source_url"]}


def test_missing_index_returns_all_non_knowledge_recommendations(tmp_path, monkeypatch) -> None:
    audience_api.load_audience_catalog.cache_clear()
    _offline(monkeypatch, tmp_path / "missing.db")
    monkeypatch.setenv("NABIZ_QUICK_KNOWLEDGE", "1")
    response = _client().get("/api/audience")
    assert response.status_code == 200
    body = response.json()
    assert body["index"] == {"state": "missing", "built_at": None, "knowledge_enabled": False}
    assert body["counts"] == {"listed": 29, "shown": 21, "knowledge_shown": 0}
    assert all(item["kind"] != "knowledge" for item in body["suggestions"])
    by_id = {item["id"] for item in body["suggestions"]}
    assert all(len(group["suggestions"]) >= 3 for group in body["groups"])
    assert all(set(group["suggestions"]) <= by_id for group in body["groups"])


def test_source_page_evidence_opens_only_its_information_suggestion(tmp_path, monkeypatch) -> None:
    database = tmp_path / "knowledge.db"
    seed_page(
        KnowledgeStore(database),
        "Öğrenci İstanbulkart başvurusu için resmî sayfada kart başvuru adımları açıklanır. "
        "Öğrenci İstanbulkart'a nasıl başvururum sorusunun yanıtı bu sayfada yer alır.",
        url="https://www.istanbulkart.istanbul/",
    )
    _offline(monkeypatch, database)
    _one_page_floor(monkeypatch)
    monkeypatch.setenv("NABIZ_QUICK_KNOWLEDGE", "1")
    audience_api.load_audience_catalog.cache_clear()
    response = _client().get("/api/audience")
    assert response.status_code == 200
    assert "b-ogrenci-kart" in _shown(response)
    assert response.json()["groups"][0]["suggestions"][0] == "b-ogrenci-kart"
    question = _student_question()
    correct_decision = asyncio.run(quick_api._verified_chips({"sorular": [question]}, KnowledgeStore(database), True))
    assert ("b-ogrenci-kart" in _shown(response)) == ("b-ogrenci-kart" in correct_decision)

    other_database = tmp_path / "other.db"
    seed_page(
        KnowledgeStore(other_database),
        "Öğrenci İstanbulkart başvurusu için resmî sayfada kart başvuru adımları açıklanır. "
        "Öğrenci İstanbulkart'a nasıl başvururum sorusunun yanıtı bu sayfada yer alır.",
        url="https://example.org/student-card",
    )
    _offline(monkeypatch, other_database)
    audience_api.load_audience_catalog.cache_clear()
    wrong_page = _client().get("/api/audience")
    assert wrong_page.status_code == 200
    assert "b-ogrenci-kart" not in _shown(wrong_page)
    wrong_decision = asyncio.run(quick_api._verified_chips({"sorular": [question]}, KnowledgeStore(other_database), True))
    assert ("b-ogrenci-kart" in _shown(wrong_page)) == ("b-ogrenci-kart" in wrong_decision)

    _offline(monkeypatch, database)
    monkeypatch.delenv("NABIZ_QUICK_KNOWLEDGE", raising=False)
    audience_api.load_audience_catalog.cache_clear()
    closed = _client().get("/api/audience")
    assert "b-ogrenci-kart" not in _shown(closed)


def test_query_parameters_are_ignored_and_route_accepts_no_query_fields(tmp_path, monkeypatch) -> None:
    _offline(monkeypatch, tmp_path / "missing.db")
    audience_api.load_audience_catalog.cache_clear()
    app = FastAPI()
    app.include_router(audience_api.audience_routes)
    client = TestClient(app)
    baseline = client.get("/api/audience")
    with_query = client.get("/api/audience?age=yas65&needs=gorme")
    assert baseline.status_code == with_query.status_code == 200
    assert baseline.json() == with_query.json()
    (route,) = audience_api.audience_routes.routes
    assert route.path == "/api/audience" and route.methods == {"GET"}
    assert route.dependant.query_params == []


def test_response_has_only_the_public_contract_fields(tmp_path, monkeypatch) -> None:
    _offline(monkeypatch, tmp_path / "missing.db")
    audience_api.load_audience_catalog.cache_clear()
    body = _client().get("/api/audience").json()
    assert set(body) == {"version", "groups", "suggestions", "shortcuts", "index", "counts"}
    assert all(set(group) == {"id", "kind", "suggestions", "shortcuts", "profile", "kolay"} for group in body["groups"])
    assert all(set(item) == {"id", "kind", "text_tr", "text_en", "url"} for item in body["suggestions"])
    assert all(set(item) == {"id", "target", "text_tr", "text_en"} for item in body["shortcuts"])
    assert all((item["url"] is not None) == (item["kind"] == "page") for item in body["suggestions"])


def test_catalog_read_failure_is_a_plain_500(tmp_path, monkeypatch) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    monkeypatch.setattr(audience_api, "CATALOG_PATH", broken)
    audience_api.load_audience_catalog.cache_clear()
    response = _client().get("/api/audience")
    assert response.status_code == 500
    assert response.json() == {"error": "audience_catalog_unreadable", "message": "Öneriler şu an yüklenemedi."}


def test_evidence_gate_calls_no_model_and_matches_the_quick_gate(tmp_path, monkeypatch) -> None:
    database = tmp_path / "knowledge.db"
    seed_page(
        KnowledgeStore(database),
        "Öğrenci İstanbulkart başvurusu için resmî sayfada kart başvuru adımları açıklanır. "
        "Öğrenci İstanbulkart'a nasıl başvururum sorusunun yanıtı bu sayfada yer alır.",
        url="https://www.istanbulkart.istanbul/",
    )
    _offline(monkeypatch, database)
    _one_page_floor(monkeypatch)
    monkeypatch.setenv("NABIZ_QUICK_KNOWLEDGE", "1")
    audience_api.load_audience_catalog.cache_clear()
    calls = []

    async def answer_without_a_model(question, **kwargs):
        calls.append((question, kwargs.copy()))
        return SimpleNamespace(mode="not_answered", citations=[])

    monkeypatch.setattr(audience_api, "answer", answer_without_a_model)
    result = _client().get("/api/audience")
    assert result.status_code == 200 and calls
    assert all(kwargs.get("embedder") is None and "generate" not in kwargs for _, kwargs in calls)
    assert {question for question, _ in calls} == {
        row["metin_tr"] for row in json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["oneriler"] if row["tur"] == "bilgi"
    }

    monkeypatch.setattr(audience_api, "answer", quick_api.answer)
    question = _student_question()
    store = KnowledgeStore(database)
    expected = asyncio.run(quick_api._verified_chips({"sorular": [question]}, store, True))
    assert ("b-ogrenci-kart" in _shown(_client().get("/api/audience"))) == ("b-ogrenci-kart" in expected)


def test_the_product_app_serves_the_audience_catalogue() -> None:
    """P00 G4: the router is wired into the real app, ahead of the static files."""
    from conftest import offline_settings

    from nabiz.console.app import build_console_app

    with TestClient(build_console_app(settings=offline_settings())) as client:
        response = client.get("/api/audience")
    assert response.status_code == 200 and len(response.json()["groups"]) == 8
