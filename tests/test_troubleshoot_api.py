from __future__ import annotations

import json
from pathlib import Path

from conftest import REPO_ROOT
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_knowledge_store import seed_page

from ibb_mcp.knowledge.store import KnowledgeStore
from nabiz.console import troubleshoot
from nabiz.console.troubleshoot_api import troubleshoot_routes


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(troubleshoot_routes)
    return TestClient(app)


def _setup(monkeypatch, db_path: Path) -> None:
    monkeypatch.setenv("NABIZ_OFFLINE", "1")
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(db_path))
    monkeypatch.delenv("NABIZ_IKART_QUOTES", raising=False)
    troubleshoot.load_flows.cache_clear()
    troubleshoot.load_contact.cache_clear()


def _seed_all(store: KnowledgeStore) -> None:
    flows = json.loads((REPO_ROOT / "data/knowledge/istanbulkart_flows.json").read_text(encoding="utf-8"))
    for source_id, source in flows["sources"].items():
        parts = [part for quote in flows["quotes"].values() if quote["source"] == source_id for part in quote["parts"]]
        body = "\n\n".join([source["page_date_raw"], "Observer paragraph must stay private.", *parts])
        seed_page(store, body, source["url"])


def _app_with_store(store: KnowledgeStore) -> TestClient:
    app = FastAPI()
    app.include_router(troubleshoot_routes)
    app.state.knowledge_store = store
    return TestClient(app)


def test_ready_index_returns_only_current_official_sentences(tmp_path, monkeypatch, _no_outbound_network) -> None:
    _setup(monkeypatch, tmp_path / "knowledge.db")
    store = KnowledgeStore(tmp_path / "knowledge.db")
    _seed_all(store)
    response = _app_with_store(store).get("/api/istanbulkart/flows")
    assert response.status_code == 200
    body = response.json()
    assert len(body["quotes"]) == 18
    assert body["contact"]["call"] == "153"
    assert body["index"]["state"] == "ready"
    assert body["disclaimer"] == "Resmî İBB hizmeti değildir."
    assert "Observer paragraph" not in json.dumps(body, ensure_ascii=False)
    assert _no_outbound_network == []


def test_missing_index_keeps_the_flow_but_skips_unsupported_checks(tmp_path, monkeypatch) -> None:
    _setup(monkeypatch, tmp_path / "not-created.db")
    body = _client().get("/api/istanbulkart/flows").json()
    assert body["quotes"] == {}
    assert body["index"]["state"] == "missing"
    assert all(node["kind"] != "check" for node in body["nodes"].values())
    assert any(node["kind"] == "skip" for node in body["nodes"].values())


def test_quote_switch_can_hide_all_quotes(tmp_path, monkeypatch) -> None:
    _setup(monkeypatch, tmp_path / "knowledge.db")
    monkeypatch.setenv("NABIZ_IKART_QUOTES", "0")
    store = KnowledgeStore(tmp_path / "knowledge.db")
    _seed_all(store)
    body = _app_with_store(store).get("/api/istanbulkart/flows").json()
    assert body["quotes"] == {} and body["quotes_enabled"] is False


def test_bad_flow_catalog_returns_a_stable_server_error(tmp_path, monkeypatch) -> None:
    _setup(monkeypatch, tmp_path / "knowledge.db")
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    monkeypatch.setattr(troubleshoot, "FLOWS_PATH", broken)
    response = _client().get("/api/istanbulkart/flows")
    assert response.status_code == 500
    assert response.json() == {
        "error": "istanbulkart_flows_unreadable",
        "message": "İstanbulkart adımları şu an yüklenemedi.",
    }


def test_route_is_read_only_and_ignores_query_parameters(tmp_path, monkeypatch) -> None:
    _setup(monkeypatch, tmp_path / "knowledge.db")
    client = _client()
    plain = client.get("/api/istanbulkart/flows")
    queried = client.get("/api/istanbulkart/flows?answer=private")
    assert plain.status_code == 200 and queried.json() == plain.json()
    assert client.post("/api/istanbulkart/flows", json={"answer": "private"}).status_code == 405


def test_second_request_uses_the_application_cache(tmp_path, monkeypatch) -> None:
    _setup(monkeypatch, tmp_path / "knowledge.db")
    store = KnowledgeStore(tmp_path / "knowledge.db")
    _seed_all(store)
    calls = 0
    original = KnowledgeStore.current_document

    def counted(self, url):
        nonlocal calls
        calls += 1
        return original(self, url)

    monkeypatch.setattr(KnowledgeStore, "current_document", counted)
    client = _app_with_store(store)
    first = client.get("/api/istanbulkart/flows").json()
    checked = calls
    second = client.get("/api/istanbulkart/flows").json()
    assert checked > 0 and calls == checked
    assert second == first
