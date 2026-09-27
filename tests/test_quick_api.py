from __future__ import annotations

import json
import re
from pathlib import Path

from conftest import REPO_ROOT
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_knowledge_store import seed_page

from ibb_mcp.knowledge.store import KnowledgeStore
from ibb_mcp.tools import Nabiz
from nabiz.agent import LlmConfig, NabizAgent
from nabiz.console import quick_api
from nabiz.console.agency_router import route as agency_route
from nabiz.console.official_intent import intent
from nabiz.console.official_path import select_path
from nabiz.console.policy import emergency_intent, refuses_in_context
from nabiz.console.quick_api import quick_routes

QUESTIONS_PATH = REPO_ROOT / "data" / "knowledge" / "quick_questions.json"
STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"


def _catalog() -> dict:
    return json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(quick_routes)
    return TestClient(app)


def _offline(monkeypatch, db_path: Path) -> None:
    monkeypatch.setenv("NABIZ_OFFLINE", "1")
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(db_path))
    monkeypatch.delenv("NABIZ_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("NABIZ_LLM_API_KEY", raising=False)
    monkeypatch.delenv("NABIZ_QUICK_KNOWLEDGE", raising=False)
    monkeypatch.delenv("NABIZ_KNOWLEDGE_FTS_MIN", raising=False)


def _one_page_floor(monkeypatch) -> None:
    """A one-page index scores far below the calibrated BM25 floor, which belongs to the real index.

    DECISIONS #36: "One-page test indexes set NABIZ_KNOWLEDGE_FTS_MIN=0". The knob is set for this
    test only; the product path keeps FTS_MIN (see test_the_calibrated_floor_still_applies_by_default).
    """
    monkeypatch.setenv("NABIZ_KNOWLEDGE_FTS_MIN", "0")


def _seed_askida_fatura(db_path: Path, url: str) -> None:
    seed_page(KnowledgeStore(db_path), "Askıda Fatura destek bilgisi bu test sayfasında yer alır.", url=url)


def _chips(response) -> dict[str, dict]:
    body = response.json() if hasattr(response, "json") else response
    return {
        chip["id"]: chip
        for category in body["categories"]
        for chip in category["chips"]
    }


def test_questions_file_has_five_categories_and_no_events() -> None:
    data = _catalog()
    assert [category["id"] for category in data["kategoriler"]] == [
        "ulasim", "istanbulkart", "iski-fatura", "sosyal-destek", "sorun-153",
    ]
    counts = {}
    for chip in data["sorular"]:
        counts[chip["kategori"]] = counts.get(chip["kategori"], 0) + 1
    assert all(count <= 5 for count in counts.values())
    text = json.dumps(data, ensure_ascii=False).lower()
    assert "tkinlik" not in text
    assert "—" not in text and "–" not in text and not re.search(r"\bETA\b", text)


def test_knowledge_questions_are_verbatim_eval_rows() -> None:
    rows = {
        row["id"]: row
        for row in (
            json.loads(line)
            for line in (REPO_ROOT / "eval/knowledge_questions.jsonl").read_text(encoding="utf-8").splitlines()
        )
    }
    chips = [chip for chip in _catalog()["sorular"] if chip["kind"] == "knowledge"]
    for chip in chips:
        row = rows[chip["eval_id"]]
        assert chip["soru_tr"] == row["question"]
        assert row["answerable"] is True and row["sensitive"] is False
        assert chip["source_url"] in row["gold_urls"]
        assert chip["soru_en"] is None


def test_knowledge_source_urls_are_in_sources_txt() -> None:
    sources = {
        line.split("\t", 1)[0]
        for line in (REPO_ROOT / "data/knowledge/sources.txt").read_text(encoding="utf-8").splitlines()
        if line.startswith("http")
    }
    for chip in _catalog()["sorular"]:
        if chip["kind"] == "knowledge":
            assert chip["source_url"] in sources


def test_live_questions_route_to_their_tool() -> None:
    agent = NabizAgent(Nabiz(), config=LlmConfig(), system_prompt="test prompt")
    for chip in _catalog()["sorular"]:
        if chip["kind"] == "live":
            assert agent.route(chip["soru_tr"])[0] == chip["arac"]
            assert agent.route(chip["soru_en"])[0] == chip["arac"]


def test_agency_chips_reach_the_institution_router() -> None:
    """The E02 İSKİ chip lives on as an agency chip: /api/agency names the institution, index or not."""
    chips = [chip for chip in _catalog()["sorular"] if chip["kind"] == "agency"]
    assert [chip["soru_tr"] for chip in chips] == ["İSKİ ve fatura işlemleri için nereye başvurabilirim?"]
    for chip in chips:
        for question in (chip["soru_tr"], chip["soru_en"]):
            assert agency_route(question).agency == "iski", question


def test_knowledge_questions_reach_the_knowledge_path() -> None:
    agent = NabizAgent(Nabiz(), config=LlmConfig(), system_prompt="test prompt")
    for chip in _catalog()["sorular"]:
        if chip["kind"] == "knowledge":
            assert agent.route(chip["soru_tr"]) == ("", {"reason": "scope"})


def test_no_chip_is_refused_or_an_emergency() -> None:
    for chip in _catalog()["sorular"]:
        for question in (chip["soru_tr"], chip["soru_en"]):
            if question:
                assert refuses_in_context(question, []) is False
                assert emergency_intent(question) is False


def test_official_chips_reach_the_reviewed_routes() -> None:
    for chip in (item for item in _catalog()["sorular"] if item["kind"] == "official"):
        for question in (chip["soru_tr"], chip["soru_en"]):
            kind = intent(question)
            assert kind in {"account", "help"}, question
            assert select_path(question, kind) is not None, question
            assert refuses_in_context(question, []) is False, question
            assert emergency_intent(question) is False, question


def test_missing_index_returns_only_live_chips(tmp_path, monkeypatch) -> None:
    _offline(monkeypatch, tmp_path / "missing.db")
    monkeypatch.setenv("NABIZ_QUICK_KNOWLEDGE", "1")
    response = _client().get("/api/quick")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["categories"]] == ["ulasim", "iski-fatura", "sosyal-destek"]
    chips = _chips(response)
    assert sorted(chip["kind"] for chip in chips.values()) == ["agency", "live", "live", "live", "live", "official", "official"]
    assert response.json()["counts"]["official"] == 2
    assert response.json()["index"]["state"] == "missing"


def test_empty_index_returns_only_live_chips(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "empty.db"
    KnowledgeStore(db_path)
    _offline(monkeypatch, db_path)
    monkeypatch.setenv("NABIZ_QUICK_KNOWLEDGE", "1")
    response = _client().get("/api/quick")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["categories"]] == ["ulasim", "iski-fatura", "sosyal-destek"]
    chips = _chips(response)
    assert sorted(chip["kind"] for chip in chips.values()) == ["agency", "live", "live", "live", "live", "official", "official"]
    assert response.json()["counts"]["official"] == 2
    assert response.json()["index"]["state"] == "empty"


def test_evidence_on_the_source_page_shows_the_chip(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "knowledge.db"
    _seed_askida_fatura(db_path, "https://istanbulsenin.istanbul/")
    _offline(monkeypatch, db_path)
    _one_page_floor(monkeypatch)
    closed = _client().get("/api/quick").json()
    assert "k-genel-08" not in _chips(closed)
    assert closed["index"]["knowledge_enabled"] is False
    assert closed["index"]["state"] == "ready"
    assert closed["counts"]["knowledge_shown"] == 0

    monkeypatch.setenv("NABIZ_QUICK_KNOWLEDGE", "1")
    opened = _client().get("/api/quick")
    chips = _chips(opened)
    assert opened.status_code == 200
    assert "k-genel-08" in chips
    assert "k-genel-01" not in chips


def test_evidence_on_another_page_does_not_count(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "knowledge.db"
    _seed_askida_fatura(db_path, "https://ibb.istanbul/")
    _offline(monkeypatch, db_path)
    _one_page_floor(monkeypatch)
    monkeypatch.setenv("NABIZ_QUICK_KNOWLEDGE", "1")
    response = _client().get("/api/quick")
    assert response.status_code == 200
    assert "k-genel-08" not in _chips(response)


def test_quick_never_calls_a_model(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "knowledge.db"
    _seed_askida_fatura(db_path, "https://istanbulsenin.istanbul/")
    _offline(monkeypatch, db_path)
    _one_page_floor(monkeypatch)
    monkeypatch.setenv("NABIZ_QUICK_KNOWLEDGE", "1")
    reference = _client().get("/api/quick")
    assert reference.status_code == 200

    monkeypatch.setenv("NABIZ_LLM_BASE_URL", "http://fake-llm/v1")
    monkeypatch.setenv("NABIZ_LLM_API_KEY", "k")
    original = quick_api.answer
    calls = []

    async def tracking_answer(*args, **kwargs):
        calls.append(kwargs.copy())
        return await original(*args, **kwargs)

    monkeypatch.setattr(quick_api, "answer", tracking_answer)
    response = _client().get("/api/quick")
    assert response.status_code == 200
    assert response.json() == reference.json()
    assert calls and all(call["embedder"] is None and "generate" not in call for call in calls)
    assert "k-genel-08" in _chips(response)


def test_the_calibrated_floor_still_applies_by_default(tmp_path, monkeypatch) -> None:
    """Without the test-only knob the one-page page is thin evidence: the chip stays hidden."""
    db_path = tmp_path / "knowledge.db"
    _seed_askida_fatura(db_path, "https://istanbulsenin.istanbul/")
    _offline(monkeypatch, db_path)
    monkeypatch.setenv("NABIZ_QUICK_KNOWLEDGE", "1")
    response = _client().get("/api/quick")
    assert response.status_code == 200
    assert "k-genel-08" not in _chips(response)
    assert response.json()["index"]["knowledge_enabled"] is True


def test_quick_chips_static_contract() -> None:
    js = (STATIC / "js/quick_chips.js").read_text(encoding="utf-8")
    css = (STATIC / "css/quick_chips.css").read_text(encoding="utf-8")
    required = ("#quick-cards", "#chat-input", "#chat-form", "requestSubmit()", "aria-label", "data-quick", "answerLanguage")
    for value in required:
        assert value in js
    for forbidden in ("data-seed", "data-ask", "localStorage"):
        assert forbidden not in js
    assert "white-space: normal" in css and "min(100%" in css
    color = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(")
    assert not color.search(css)
