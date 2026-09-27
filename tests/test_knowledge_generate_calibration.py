from __future__ import annotations

import asyncio
import importlib.util

import pytest
from conftest import REPO_ROOT
from test_knowledge_store import seed_page

from ibb_mcp.knowledge.answer import generation_messages
from ibb_mcp.knowledge.retrieve import Hit
from ibb_mcp.knowledge.store import KnowledgeStore
from nabiz.agent import llm
from nabiz.console.knowledge_generate import check_claims

spec = importlib.util.spec_from_file_location(
    "knowledge_calibration_generate", REPO_ROOT / "scripts" / "knowledge_calibration.py"
)
calibration = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(calibration)


def test_fake_calibration_preserves_answers_and_counts_expected_drops(tmp_path, monkeypatch) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    seed_page(store, "Su aboneliği başvurusu İSKİ şubelerinden ve internet sitesinden yapılır. Başvuru çevrimiçi alınır.")
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(tmp_path / "knowledge.db"))
    rows = [
        {
            "id": "positive",
            "set": "test",
            "group": "kurum-sayfasi",
            "question": "Su aboneliği başvurusu nasıl yapılır?",
            "gold_urls": ["https://www.iski.istanbul/abonelik"],
            "seed_sensitive": False,
            "expect": None,
            "row": None,
        },
        {
            "id": "negative",
            "set": "test",
            "group": "negatif",
            "question": "Kutup ayısı nerede yaşar?",
            "gold_urls": [],
            "seed_sensitive": False,
            "expect": "unknown",
            "row": None,
        },
    ]

    measured = asyncio.run(calibration.measure(rows, "fake"))
    summary = calibration.generation_summary(measured)

    assert summary["answered_off"] == summary["answered_with_model"]
    assert summary["negative_answered"] == 0
    assert summary["called"] == summary["accepted"] == 0
    assert measured[1]["generation"]["status"] == "skipped"


def test_model_generation_without_configuration_exits_two(monkeypatch, capsys) -> None:
    monkeypatch.setattr(llm.LlmConfig, "from_env", lambda **_kwargs: llm.LlmConfig())

    assert calibration.main(["--generate", "model"]) == 2
    assert "model yapılandırılmadı" in capsys.readouterr().err


def test_calibration_help_lists_generate_modes(capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        calibration.main(["--help"])

    assert exit_info.value.code == 0
    assert "--generate {off,fake,model}" in capsys.readouterr().out


def test_off_measure_has_no_generation_field(tmp_path, monkeypatch) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    seed_page(store, "Su aboneliği başvurusu İSKİ şubelerinden ve internet sitesinden yapılır. Başvuru çevrimiçi alınır.")
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(tmp_path / "knowledge.db"))
    rows = [
        {
            "id": "positive",
            "set": "test",
            "group": "kurum-sayfasi",
            "question": "Su aboneliği başvurusu nasıl yapılır?",
            "gold_urls": ["https://www.iski.istanbul/abonelik"],
            "seed_sensitive": False,
            "expect": None,
            "row": None,
        }
    ]

    measured = asyncio.run(calibration.measure(rows))

    assert "generation" not in measured[0]
    assert set(calibration.summary(measured)) == {
        "total",
        "modes",
        "by_group",
        "top_is_gold",
        "gold_in_top8",
        "with_gold",
        "answered_with_gold",
        "answered_cites_gold",
        "answered_cites_other",
        "negative_answered",
    }


def test_generation_summary_keeps_drop_keys_even_when_zero() -> None:
    row = {
        "group": "demo",
        "mode": "unknown",
        "generation": {
            "status": "skipped",
            "reason": "no_evidence",
            "dropped": dict.fromkeys(("shape", "unknown_id", "url_or_quote", "unfaithful", "unsupported", "over_limit"), 0),
            "claims": 0,
            "called": False,
            "answered_off": False,
            "author": "kural",
        },
    }

    summary = calibration.generation_summary([row])

    assert summary["dropped"] == {
        key: 0 for key in ("shape", "unknown_id", "url_or_quote", "unfaithful", "unsupported", "over_limit")
    }


def test_fake_model_exercises_quote_number_and_id_drop_reasons() -> None:
    question = "Su aboneliği başvurusu nasıl yapılır?"
    evidence = Hit(
        chunk_id="c1",
        quote_id="q1",
        url="https://www.iski.istanbul/abonelik",
        title="",
        quote="Su aboneliği başvurusu yapılır.",
        score=1.0,
        fetched_at="2026-09-27T10:00:00+00:00",
        source_updated_at=None,
        institution="ISKI",
        page_number=None,
        section_title=None,
    )
    messages = generation_messages(question, [evidence])
    config = llm.LlmConfig(base_url="http://model.invalid/v1", model="fake", provider="openai_compatible")
    response = asyncio.run(calibration.FakeKnowledgeModel()(config, messages))
    checked = check_claims(response["content"], question, [evidence])

    assert checked.dropped["url_or_quote"] == 1
    assert checked.dropped["unfaithful"] == 1
    assert checked.dropped["unknown_id"] == 1
