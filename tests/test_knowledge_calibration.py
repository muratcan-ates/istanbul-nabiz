"""``scripts/knowledge_calibration.py`` and its question set, on a temporary index only.

The script measures the gitignored ``data/knowledge/knowledge.db``; these tests point it at a one-page
index in a temporary directory, so they never read the real index and never write a tracked file.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
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


def test_the_question_set_has_twenty_mitigating_rows_and_a_negative_set() -> None:
    rows = calibration.read_rows(calibration.SET_PATH, "calibration")
    groups = {row["group"] for row in rows}
    assert groups == {"hafifletiyor", "demo", "negatif"}
    assert sum(row["group"] == "hafifletiyor" for row in rows) == 20
    assert sum(row["group"] == "negatif" for row in rows) >= 20
    assert len({row["id"] for row in rows}) == len(rows)
    assert all(not row["gold_urls"] for row in rows if row["group"] == "negatif")


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
