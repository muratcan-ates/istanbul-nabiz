from __future__ import annotations

import json
from pathlib import Path

from conftest import REPO_ROOT
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_knowledge_store import seed_page

from ibb_mcp.knowledge.store import KnowledgeStore
from nabiz.console import recovery, recovery_api
from nabiz.console.recovery_api import recovery_routes


def client(store: KnowledgeStore | None = None) -> TestClient:
    app = FastAPI()
    if store is not None:
        app.state.knowledge_store = store
    app.include_router(recovery_routes)
    return TestClient(app)


def reset_catalogs() -> None:
    recovery.load_recovery_flows.cache_clear()
    recovery.load_recovery_agencies.cache_clear()


def quote_parts_for(data: dict, url: str) -> list[str]:
    return [
        part for quote in data["quotes"].values()
        if data["sources"][quote["source"]]["url"] == url
        for part in quote["parts"]
    ]


def offline(monkeypatch, db_path: Path) -> None:
    monkeypatch.setenv("NABIZ_OFFLINE", "1")
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(db_path))
    monkeypatch.delenv("NABIZ_ERISIM_QUOTES", raising=False)
    reset_catalogs()


def seed_sources(store: KnowledgeStore, capture_path: Path) -> None:
    data = json.loads((REPO_ROOT / "data/knowledge/recovery_flows.json").read_text(encoding="utf-8"))
    capture_entries = []
    for source in data["sources"].values():
        parts = quote_parts_for(data, source["url"])
        body = "\n\n".join([*parts, "witness sentence never returned"])
        if source["from"] == "index":
            seed_page(store, body, source["url"])
        else:
            capture_entries.append({
                "url": source["url"], "final_url": source["url"], "status": "ok", "text": body,
                "fetched_at": "2026-09-27T00:00:00+00:00",
            })
    capture_path.write_text(json.dumps({
        "schema": 1, "captured_at": "2026-09-27T00:00:00+00:00", "entries": capture_entries,
    }), encoding="utf-8")


def test_endpoint_returns_only_fresh_source_quotes_and_caches(tmp_path, monkeypatch) -> None:
    offline(monkeypatch, tmp_path / "unused.db")
    capture_path = tmp_path / "capture.json"
    monkeypatch.setattr(recovery, "CAPTURE_PATH", capture_path)
    store = KnowledgeStore(tmp_path / "knowledge.db")
    seed_sources(store, capture_path)
    app_client = client(store)
    first = app_client.get("/api/erisim/flows")
    second = app_client.get("/api/erisim/flows?unused=ignored")
    assert first.status_code == second.status_code == 200
    body = first.json()
    assert len(body["quotes"]) == 18 and body["contact"]["call"] == "153"
    assert body["index"]["state"] == "ready" and body["capture"]["state"] == "ok"
    assert body["disclaimer"] == "Resmî İBB hizmeti değildir."
    assert "witness sentence" not in json.dumps(body)
    assert second.json() == body
    assert app_client.post("/api/erisim/flows").status_code == 405


def test_missing_index_and_capture_still_return_a_safe_tree(tmp_path, monkeypatch) -> None:
    offline(monkeypatch, tmp_path / "missing.db")
    monkeypatch.setattr(recovery, "CAPTURE_PATH", tmp_path / "capture.json")
    response = client().get("/api/erisim/flows")
    assert response.status_code == 200
    body = response.json()
    assert body["quotes"] == {} and body["index"] == {"state": "missing", "built_at": None}
    assert body["capture"] == {"state": "missing", "captured_at": None}
    assert all(node["kind"] == "skip" for node in body["nodes"].values() if node["kind"] in {"skip", "check"})


def test_quote_kill_switch_hides_all_quotes(tmp_path, monkeypatch) -> None:
    offline(monkeypatch, tmp_path / "missing.db")
    monkeypatch.setenv("NABIZ_ERISIM_QUOTES", "0")
    monkeypatch.setattr(recovery, "CAPTURE_PATH", tmp_path / "capture.json")
    body = client().get("/api/erisim/flows").json()
    assert body["quotes"] == {} and body["quotes_enabled"] is False


def test_unreadable_flow_file_returns_a_localized_problem(tmp_path, monkeypatch) -> None:
    offline(monkeypatch, tmp_path / "missing.db")
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    monkeypatch.setattr(recovery, "FLOWS_PATH", broken)
    body = client().get("/api/erisim/flows").json()
    assert body["error"] == "recovery_flows_unreadable"
    assert body["message"] == "Erişim adımları şu an yüklenemedi."


def test_capture_info_does_not_expose_its_page_text(tmp_path) -> None:
    path = tmp_path / "capture.json"
    path.write_text(json.dumps({
        "schema": 1, "captured_at": "2026-09-27T00:00:00+00:00", "entries": [{
            "url": "https://www.istanbulkart.istanbul/guvenlik", "final_url": "https://www.istanbulkart.istanbul/guvenlik",
            "status": "ok", "text": "private test sentence", "fetched_at": "2026-09-27T00:00:00+00:00",
        }],
    }), encoding="utf-8")
    metadata = recovery_api._capture_metadata(path, "https://www.istanbulkart.istanbul/guvenlik")
    assert metadata == {"state": "ok", "captured_at": "2026-09-27T00:00:00+00:00"}
