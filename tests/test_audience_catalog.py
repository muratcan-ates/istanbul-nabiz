from __future__ import annotations

import json
import re
import sqlite3
from copy import deepcopy

import pytest
from conftest import REPO_ROOT

from ibb_mcp.tools import Nabiz
from nabiz.agent import LlmConfig, NabizAgent
from nabiz.console import audience_api
from nabiz.console.agency_router import route as agency_route
from nabiz.console.policy import emergency_intent, refuses_in_context

CATALOG_PATH = REPO_ROOT / "data/knowledge/audience_suggestions.json"
STATIC = REPO_ROOT / "src/nabiz/console/static"
EXPECTED_GROUPS = ["ogrenci", "calisan", "yas65", "tekerlekli", "gorme", "isitme", "bilissel", "turist"]
FORBIDDEN_COPY = re.compile(r"hak kazan|yararlanabilirsiniz|uygunsunuz|ücretsiz binersiniz|eligible|you qualify|entitled", re.I)


def catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def test_catalog_shape_and_validator_rejects_bad_rows() -> None:
    data = catalog()
    audience_api.validate_catalog(data)
    assert [group["id"] for group in data["gruplar"]] == EXPECTED_GROUPS
    assert [group["tur"] for group in data["gruplar"][:3]] == ["yas", "yas", "yas"]
    assert all("cocuk" not in json.dumps(row, ensure_ascii=False).lower() for row in data["gruplar"])
    assert not any(
        key in json.dumps(data, ensure_ascii=False).lower()
        for key in ("birth_date", "dogum_tarihi", "yas_sayisi", "engel_orani", "tani")
    )

    duplicate = deepcopy(data)
    duplicate["oneriler"].append(deepcopy(duplicate["oneriler"][0]))
    invalid_kind = deepcopy(data)
    invalid_kind["oneriler"][0]["tur"] = "x"
    unknown_ref = deepcopy(data)
    unknown_ref["gruplar"][0]["oneriler"].append("bilinmeyen")
    missing_text = deepcopy(data)
    del missing_text["oneriler"][0]["metin_tr"]
    for invalid in (duplicate, invalid_kind, unknown_ref, missing_text):
        with pytest.raises(ValueError):
            audience_api.validate_catalog(invalid)


def test_every_group_has_three_non_knowledge_and_english_suggestions() -> None:
    data = catalog()
    suggestions = {item["id"]: item for item in data["oneriler"]}
    assert len(data["oneriler"]) == 29
    assert len(data["kisayollar"]) == 7
    for group in data["gruplar"]:
        items = [suggestions[item_id] for item_id in group["oneriler"]]
        assert sum(item["tur"] != "bilgi" for item in items) >= 3, group["id"]
        assert sum(bool(item["metin_en"]) for item in items) >= 3, group["id"]
    assert all(any(item_id in group["oneriler"] for group in data["gruplar"]) for item_id in suggestions)
    assert all(any(item["id"] in group["kisayollar"] for group in data["gruplar"]) for item in data["kisayollar"])


def test_questions_route_to_the_recorded_tool_or_agency() -> None:
    data = catalog()
    agent = NabizAgent(Nabiz(), config=LlmConfig(), system_prompt="test prompt")
    for item in data["oneriler"]:
        if item["tur"] == "arac":
            assert agent.route(item["metin_tr"])[0] == item["arac"], item["id"]
            assert agent.route(item["metin_en"])[0] == item["arac"], item["id"]
        elif item["tur"] == "kurum":
            assert agency_route(item["metin_tr"]).agency == item["kurum"], item["id"]
            assert agency_route(item["metin_en"]).agency == item["kurum"], item["id"]


def test_knowledge_questions_match_the_eval_and_source_catalogs() -> None:
    rows = {
        row["id"]: row
        for row in (
            json.loads(line) for line in (REPO_ROOT / "eval/knowledge_questions.jsonl").read_text(encoding="utf-8").splitlines()
        )
    }
    sources = {
        line.split("\t", 1)[0]
        for line in (REPO_ROOT / "data/knowledge/sources.txt").read_text(encoding="utf-8").splitlines()
        if line.startswith("http")
    }
    for item in (entry for entry in catalog()["oneriler"] if entry["tur"] == "bilgi"):
        row = rows[item["eval_id"]]
        assert item["metin_tr"] == row["question"]
        assert row["answerable"] is True
        assert item["source_url"] in row["gold_urls"] and item["source_url"] in sources
        assert item["metin_en"] is None


def test_page_urls_and_existing_index_pages_are_verified_read_only() -> None:
    sources = {
        line.split("\t", 1)[0]
        for line in (REPO_ROOT / "data/knowledge/sources.txt").read_text(encoding="utf-8").splitlines()
        if line.startswith("http")
    }
    pages = [item for item in catalog()["oneriler"] if item["tur"] == "sayfa"]
    assert len(pages) == 13
    for item in pages:
        assert item["url"].startswith("https://") and item["url"] in sources

    database = REPO_ROOT / "data/knowledge/knowledge.db"
    if database.exists():
        connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        try:
            for item in pages:
                assert connection.execute(
                    "SELECT 1 FROM documents WHERE url=? AND active=1 LIMIT 1", (item["url"],)
                ).fetchone(), item["url"]
        finally:
            connection.close()


def test_shortcuts_and_profile_needs_point_at_real_controls() -> None:
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    needs_source = (STATIC / "js/profile.js").read_text(encoding="utf-8")
    profile_needs = set(re.findall(r"\{ key: '([a-z_]+)'", needs_source))
    for item in catalog()["kisayollar"]:
        if item["dosya"] == "index.html":
            source = index
            assert f'id="{item["hedef"]}"' in source
        else:
            source = (STATIC / item["dosya"]).read_text(encoding="utf-8")
            assert f".id = '{item['hedef']}'" in source or f'id="{item["hedef"]}"' in source
    assert {need for group in catalog()["gruplar"] for need in group["profil"]} <= profile_needs


def test_all_catalog_copy_is_short_honest_and_non_emergency() -> None:
    data = catalog()
    copy = [
        value for row in data["oneriler"] + data["kisayollar"] for key, value in row.items() if key.startswith("metin_") and value
    ]
    for value in copy:
        assert len(value) <= 90
        assert "—" not in value and "–" not in value
        assert not re.search(r"\bETA\b|\blive\b", value, re.I)
        assert "canlı" not in value.casefold()
        assert FORBIDDEN_COPY.search(value) is None
        assert "ibb onaylı" not in value.casefold()
    for item in data["oneriler"]:
        if item["tur"] not in {"arac", "kurum", "bilgi"}:
            continue
        for question in (item["metin_tr"], item["metin_en"]):
            if question:
                assert refuses_in_context(question, []) is False, item["id"]
                assert emergency_intent(question) is False, item["id"]


def test_refused_or_ambiguous_candidates_are_not_reintroduced() -> None:
    excluded_for_refusal = {
        "k-ulasim-09",
        "k-hassas-05",
        "k-hassas-06",
        "k-hassas-07",
        "k-ispark-06",
        "k-ulasim-05",
        "k-ulasim-14",
    }
    excluded_for_policy = {"k-hassas-03", "k-genel-04"}
    data = catalog()
    assert excluded_for_refusal.isdisjoint({item.get("eval_id") for item in data["oneriler"]})
    assert excluded_for_policy.isdisjoint({item.get("eval_id") for item in data["oneriler"]})
    rows = {
        row["id"]: row
        for row in (
            json.loads(line) for line in (REPO_ROOT / "eval/knowledge_questions.jsonl").read_text(encoding="utf-8").splitlines()
        )
    }
    assert all(refuses_in_context(rows[key]["question"], []) for key in excluded_for_refusal)
    assert "canlı" in rows["k-genel-04"]["question"].casefold()
    assert "başvurabilir" in rows["k-hassas-03"]["question"].casefold()
