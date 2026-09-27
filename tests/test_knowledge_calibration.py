"""``scripts/knowledge_calibration.py`` and its question set, on a temporary index only.

The script measures the gitignored ``data/knowledge/knowledge.db``; these tests point it at a one-page
index in a temporary directory, so they never read the real index and never write a tracked file.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from pathlib import Path

from conftest import REPO_ROOT
from test_knowledge_store import seed_page

from ibb_mcp.knowledge.store import KnowledgeStore


def _load():
    spec = importlib.util.spec_from_file_location("knowledge_calibration", REPO_ROOT / "scripts" / "knowledge_calibration.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


calibration = _load()


def test_the_question_set_has_the_expected_groups_and_negative_set() -> None:
    rows = calibration.read_rows(calibration.SET_PATH, "calibration")
    groups = {row["group"] for row in rows}
    assert groups == {"hafifletiyor", "demo", "negatif", "kurum-sayfasi", "yardim", "resmi-yol"}
    assert sum(row["group"] == "hafifletiyor" for row in rows) == 20
    assert sum(row["group"] == "demo" for row in rows) == 6
    assert sum(row["group"] == "negatif" for row in rows) == 28
    assert sum(row["group"] == "kurum-sayfasi" for row in rows) == 17
    assert sum(row["group"] == "yardim" for row in rows) >= 4
    assert sum(row["group"] == "resmi-yol" for row in rows) >= 4
    assert len({row["id"] for row in rows}) == len(rows)
    assert all(not row["gold_urls"] for row in rows if row["group"] == "negatif")
    assert all(row["gold_urls"] for row in rows if row["group"] == "kurum-sayfasi")
    assert all(row["gold_urls"] for row in rows if row["group"] in {"yardim", "resmi-yol"})


def test_the_moved_questions_keep_their_ids() -> None:
    rows = {row["id"]: row for row in calibration.read_rows(calibration.SET_PATH, "calibration")}
    source_rows = {row["id"]: row for row in map(json.loads, calibration.SET_PATH.read_text(encoding="utf-8").splitlines())}
    assert rows["n-15"]["group"] == rows["n-16"]["group"] == "kurum-sayfasi"
    assert all("igdas.istanbul" in url for question_id in ("n-15", "n-16") for url in rows[question_id]["gold_urls"])
    assert "expect" not in source_rows["n-15"] and "expect" not in source_rows["n-16"]


def test_urls_compare_loosely() -> None:
    assert calibration.canonical("https://www.metro.istanbul/icerik/eri%C5%9Filebilirlik-hizmetleri/") == (
        "metro.istanbul/icerik/erişilebilirlik-hizmetleri"
    )
    assert calibration.canonical("http://WWW.ISPARK.istanbul/") == calibration.canonical("https://ispark.istanbul")


def test_a_run_and_its_report_on_a_temporary_index(tmp_path: Path, monkeypatch) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    seed_page(store, "Su aboneliği başvurusu İSKİ şubelerinden ve internet sitesinden yapılır.")
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(tmp_path / "knowledge.db"))
    rows = [
        {"id": "a", "set": "t", "group": "seed", "question": "Su aboneliği başvurusu nasıl yapılır?",
         "gold_urls": ["https://www.iski.istanbul/abonelik"], "seed_sensitive": False, "expect": None, "row": None},
        {"id": "b", "set": "t", "group": "negatif", "question": "Kutup ayısı nerede yaşar?",
         "gold_urls": [], "seed_sensitive": None, "expect": "unknown", "row": None},
    ]  # fmt: skip
    measured = asyncio.run(calibration.measure(rows))
    assert measured[0]["top_is_gold"] and measured[0]["gold_rank"] == 1
    assert measured[1]["mode"] == "unknown" and measured[1]["cited_urls"] == []
    summary = calibration.summary(measured)
    assert summary["total"] == 2 and summary["negative_answered"] == 0
    run = {"label": "x", "thresholds": {}, "summary": summary, "rows": measured}
    before, after, md = tmp_path / "before.json", tmp_path / "after.json", tmp_path / "out.md"
    before.write_text(json.dumps(run), encoding="utf-8")
    after.write_text(json.dumps(run), encoding="utf-8")
    assert calibration.report(str(before), str(after), str(md)) == 0
    text = md.read_text(encoding="utf-8")
    assert "| negatif | 1 |" in text and "Kutup ayısı" in text


def test_a_grid_on_a_temporary_index(tmp_path: Path, monkeypatch) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    seed_page(store, "Su aboneliği başvurusu İSKİ şubelerinden ve internet sitesinden yapılır.")
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(tmp_path / "knowledge.db"))
    monkeypatch.setenv("NABIZ_KNOWLEDGE_FTS_MIN", "23")
    monkeypatch.setenv("NABIZ_KNOWLEDGE_MIN_COVERAGE", "0.25")
    rows = [
        {"id": "positive", "set": "t", "group": "kurum-sayfasi", "question": "Su aboneliği başvurusu nasıl yapılır?",
         "gold_urls": ["https://www.iski.istanbul/abonelik"], "seed_sensitive": False, "expect": None, "row": None},
    ]  # fmt: skip

    entries = calibration.grid(rows, [0.0], [0.0]) + calibration.grid(rows, [1000.0], [0.5])

    assert len(entries) == 2
    assert entries[0]["summary"]["modes"]["answer"] == 1
    assert entries[1]["summary"]["modes"]["unknown"] == 1
    assert os.environ["NABIZ_KNOWLEDGE_FTS_MIN"] == "23"
    assert os.environ["NABIZ_KNOWLEDGE_MIN_COVERAGE"] == "0.25"


def test_the_report_renders_the_grid_and_counts_its_own_rows(tmp_path: Path) -> None:
    question = {
        "id": "k-01",
        "set": "calibration",
        "group": "kurum-sayfasi",
        "question": "Su aboneliği nereden açılır?",
        "gold_urls": ["https://iski.istanbul/abonelik"],
        "sensitive": False,
        "top_url": "https://iski.istanbul/abonelik",
        "top_bm25": 8.0,
        "coverage": 0.5,
        "top_is_gold": True,
        "gold_rank": 1,
        "level": "sufficient",
        "mode": "answer",
        "cited_urls": ["https://iski.istanbul/abonelik"],
        "cited_is_gold": True,
        "chat": {"mode": "answer"},
    }
    negative = {
        "id": "n-23",
        "set": "calibration",
        "group": "negatif",
        "question": "Elektrik aboneliği nasıl yapılır?",
        "gold_urls": [],
        "sensitive": False,
        "top_url": None,
        "top_bm25": None,
        "coverage": 0.0,
        "top_is_gold": False,
        "gold_rank": None,
        "level": "out_of_scope",
        "mode": "unknown",
        "cited_urls": [],
        "cited_is_gold": False,
        "chat": {"mode": "unknown"},
    }
    measured = [question, negative]
    summary = {
        "total": 2,
        "modes": {"answer": 1, "quote_only": 0, "unknown": 1},
        "by_group": {
            "kurum-sayfasi": {"n": 1, "answer": 1, "quote_only": 0, "unknown": 0},
            "negatif": {"n": 1, "answer": 0, "quote_only": 0, "unknown": 1},
        },
        "top_is_gold": 1,
        "gold_in_top8": 1,
        "with_gold": 1,
        "answered_with_gold": 1,
        "answered_cites_gold": 1,
        "answered_cites_other": 0,
        "negative_answered": 0,
    }
    run = {"label": "offline", "thresholds": {"fts_min": 8.0, "min_coverage": 0.5}, "summary": summary, "rows": measured}
    before, after, grid, md = (tmp_path / name for name in ("before.json", "after.json", "grid.json", "out.md"))
    before.write_text(json.dumps(run), encoding="utf-8")
    after.write_text(json.dumps(run), encoding="utf-8")
    grid.write_text(
        json.dumps(
            {
                "label": "grid",
                "grid": [
                    {
                        "thresholds": {"fts_min": 8.0, "min_coverage": 0.5},
                        "summary": summary,
                        "max_negative_bm25_over_coverage": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert calibration.report(str(before), str(after), str(md), str(grid)) == 0
    text = md.read_text(encoding="utf-8")
    assert "## Eşik taraması" in text and text.count("**seçildi**") == 1
    assert "aynı 2 soru" in text and "aynı 198 soru" not in text


def test_the_grid_marks_the_applied_thresholds_when_the_rule_pick_was_rejected(tmp_path: Path) -> None:
    """The rule's pick can be overruled (DECISIONS #59); the table then shows both, from the runs' own JSON."""
    summary = {"modes": {"answer": 0, "quote_only": 0, "unknown": 0}, "answered_cites_gold": 0,
               "answered_cites_other": 0, "negative_answered": 0}  # fmt: skip
    applied = {"fts_min": 16.0, "min_coverage": 0.5}
    rule_pick = {"fts_min": 10.0, "min_coverage": 0.6}
    grid = tmp_path / "grid.json"
    grid.write_text(json.dumps({"label": "grid", "grid": [
        {"thresholds": applied, "summary": summary, "max_negative_bm25_over_coverage": 15.45},
        {"thresholds": rule_pick, "summary": {**summary, "answered_cites_gold": 1}, "max_negative_bm25_over_coverage": None},
    ]}), encoding="utf-8")  # fmt: skip

    text = "\n".join(calibration._grid_lines(str(grid), applied))

    assert text.count("**seçildi**") == 1 and "| **seçildi** 16.00 | 0.50 |" in text
    assert "| **kural** 10.00 | 0.60 |" in text and "DECISIONS.md" in text
