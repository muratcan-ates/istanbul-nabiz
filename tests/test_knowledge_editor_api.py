"""API flow with isolated request, ledger, editor and knowledge databases."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_knowledge_store import seed_page

from ibb_mcp.knowledge.store import KnowledgeStore
from nabiz.console.citizen_requests import NewRequest, RequestStore
from nabiz.console.knowledge_editor_api import _BASE, knowledge_editor_routes
from nexus_core.ledger import Ledger
from nexus_core.state import replay


def _request(text: str) -> NewRequest:
    return NewRequest(
        original_masked=text, masked_count=0, masked_kinds=(), lang="tr", lang_source="visitor",
        chosen_lang=None, turkish=text, translation_status="not_needed", translation_author=None,
        category="Genel bilgi", guard=None,
    )


@pytest.fixture
def editor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    index_path = tmp_path / "knowledge.db"
    requests_db = tmp_path / "requests.db"
    editor_db = tmp_path / "knowledge_editor.db"
    ledger_db = tmp_path / "nexus.db"
    candidates_path = tmp_path / "source_candidates.jsonl"
    monkeypatch.setenv("NABIZ_OFFLINE", "1")
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(index_path))
    monkeypatch.setenv("NABIZ_REQUESTS_DB_PATH", str(requests_db))
    monkeypatch.setenv("NABIZ_KNOWLEDGE_EDITOR_DB_PATH", str(editor_db))
    monkeypatch.setenv("NABIZ_SOURCE_CANDIDATES_PATH", str(candidates_path))
    monkeypatch.setenv("NEXUS_DB_PATH", str(ledger_db))
    index = KnowledgeStore(index_path)
    seed_page(index, "İstanbul'da toplu ulaşım hizmetleri ve sefer bilgisi kurum sayfalarında yayımlanır.")
    question = "Antarktika örnek sorusu nasıl çözülecek?"
    request_row = RequestStore(requests_db).create(_request(question))
    request_ref = "request:" + hashlib.sha256(request_row["code"].encode()).hexdigest()[:12]
    app = FastAPI()
    app.include_router(knowledge_editor_routes)
    with TestClient(app, base_url="http://127.0.0.1:8090") as client:
        yield {
            "client": client, "question": question, "raw_code": request_row["code"], "ref": request_ref,
            "editor_db": editor_db, "index_path": index_path, "index_mtime": index_path.stat().st_mtime_ns,
            "ledger_db": ledger_db, "candidates_path": candidates_path,
        }


def test_gap_list_scan_tag_and_request_masking(editor) -> None:
    client, ref = editor["client"], editor["ref"]
    first = client.get(_BASE)
    assert first.status_code == 200 and ref in first.text
    assert editor["raw_code"] not in first.text
    detail = client.get(f"{_BASE}/gaps/{ref}")
    assert detail.status_code == 200 and detail.json()["source"] == "request"
    assert detail.json()["question"] == editor["question"] and editor["raw_code"] not in detail.text
    scanned = client.post(f"{_BASE}/scan", json={})
    assert scanned.status_code == 200 and scanned.json()["last_scan"]
    assert scanned.json()["gaps"]["groups"]
    tagged = client.post(f"{_BASE}/gaps/{ref}/tag", json={"tag": "stale"})
    visible = [item for group in tagged.json()["gaps"]["groups"] for item in group["items"]]
    assert tagged.status_code == 200 and next(item for item in visible if item["ref"] == ref)["tag_by"] == "operator"


def test_candidate_review_undo_privacy_and_read_only_index(editor, caplog) -> None:
    client, ref = editor["client"], editor["ref"]
    assert client.post(f"{_BASE}/scan", json={}).status_code == 200
    rejected = client.post(f"{_BASE}/candidates", json={
        "url": "https://www.igdas.istanbul/hizmet", "gap_refs": [ref], "note": "Public page candidate",
    })
    assert rejected.status_code == 422 and any(row["key"] == "not_igdas" for row in rejected.json()["checks"])
    proposed = client.post(f"{_BASE}/candidates", json={
        "url": "https://iett.istanbul/hizmetler", "gap_refs": [ref], "note": "Public page candidate",
    })
    candidate_id = proposed.json()["id"]
    assert proposed.status_code == 201
    tried = client.post(f"{_BASE}/candidates/{candidate_id}/trial", json={})
    assert tried.status_code == 200 and tried.json()["status"] == "tried"
    with sqlite3.connect(editor["editor_db"]) as db:
        trial_rows = db.execute("SELECT rows FROM ked_trials WHERE candidate_id=?", (candidate_id,)).fetchone()[0]
        scan_rows = db.execute("SELECT rows FROM ked_scans ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert editor["question"] not in trial_rows and editor["raw_code"] not in trial_rows
    assert editor["question"] not in scan_rows and editor["raw_code"] not in scan_rows
    phone = "0532" + " 123 45 67"
    pii = client.post(f"{_BASE}/candidates/{candidate_id}/decide", json={
        "action": "approve", "reason": f"Reviewed {phone}",
    })
    assert pii.status_code == 422 and pii.json()["message"] == "Kişisel bilgi yazmayın."
    approved = client.post(f"{_BASE}/candidates/{candidate_id}/decide", json={
        "action": "approve", "reason": "Reviewed against the current index",
    })
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    approval = next(event for event in approved.json()["events"] if event["kind"] == "approved")
    undone = client.post(f"{_BASE}/candidates/{candidate_id}/events/{approval['id']}/undo", json={
        "reason": "Return to trial state",
    })
    assert undone.status_code == 200 and undone.json()["status"] == "tried"
    repeated = client.post(f"{_BASE}/candidates/{candidate_id}/events/{approval['id']}/undo", json={
        "reason": "Return to trial state",
    })
    assert repeated.status_code == 409

    lines = [json.loads(line) for line in editor["candidates_path"].read_text(encoding="utf-8").splitlines()]
    assert [line["event"] for line in lines] == ["proposed", "approved", "undone"]
    assert all(editor["ref"] not in json.dumps(line) and editor["question"] not in json.dumps(line) for line in lines)
    assert all(editor["raw_code"] not in json.dumps(line) for line in lines)
    ledger = Ledger(editor["ledger_db"])
    assert ledger.verify().ok and replay(ledger.entries()) == {}
    assert editor["index_path"].stat().st_mtime_ns == editor["index_mtime"]
    assert all(value not in caplog.text for value in (
        editor["question"], editor["raw_code"], "Public page candidate", "Reviewed against the current index",
        "Return to trial state",
    ))
