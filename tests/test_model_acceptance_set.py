"""``eval/model_acceptance.jsonl`` and ``scripts/model_acceptance.py``: the set is valid, the offline run is.

The real run needs the owner's ``.env`` model and is never started here; what is tested is that the file
covers what the demo must show, that the offline run meets every expectation without one outbound
connection, that the checks fail a fabricated or unauthorised answer, and that ``--real`` without a
configured model stops before running anything.
"""

from __future__ import annotations

import copy
import importlib.util
import pathlib
import sys
from collections import Counter
from typing import Any

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("model_acceptance", REPO_ROOT / "scripts" / "model_acceptance.py")
assert _spec and _spec.loader
model_acceptance = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("model_acceptance", model_acceptance)
_spec.loader.exec_module(model_acceptance)

ROWS = model_acceptance.load_set()
RULE_PATH = {"ma-11", "ma-14", "ma-15"}


def _listing(folder: pathlib.Path) -> list[tuple[str, float]]:
    return sorted((path.name, path.stat().st_mtime) for path in folder.iterdir()) if folder.is_dir() else []


def _row(row_id: str) -> dict[str, Any]:
    return copy.deepcopy(next(row for row in ROWS if row["id"] == row_id))


def test_the_set_is_valid_and_covers_what_the_demo_must_show() -> None:
    assert model_acceptance.validate(ROWS) == []
    assert 12 <= len(ROWS) <= 16
    assert {row["kind"] for row in ROWS} >= model_acceptance.REQUIRED_KINDS
    emergency = [row for row in ROWS if row["kind"] == "emergency"]
    assert emergency and all(row["expect"]["path"] == "rule" and row["expect"]["emergency"] is True for row in emergency)


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (lambda rows: rows[0]["expect"].pop("path"), "path and emergency"),
        (lambda rows: rows[0].update(kind="guess"), "kind 'guess'"),
        (lambda rows: rows[0].update(offline_script=[]), "offline_script is empty"),
        (lambda rows: rows[1].update(id=rows[0]["id"]), "ids repeat"),
        (lambda rows: rows[0]["expect"].update(tone="kind"), "unknown expectation tone"),
        (lambda rows: rows.__delitem__(slice(0, 5)), "questions; the set holds 12 to 16"),
    ],
)
def test_the_validator_refuses_a_broken_file(change: Any, problem: str) -> None:
    rows = copy.deepcopy(ROWS)
    change(rows)
    assert any(problem in line for line in model_acceptance.validate(rows)), problem


def test_the_offline_run_meets_every_expectation_without_leaving_the_machine() -> None:
    results, counter = model_acceptance.run_offline(ROWS)
    failed = {item["id"]: [key for key, ok in item["checks"].items() if not ok] for item in results if not item["ok"]}
    assert failed == {}
    assert sum(counter.values()) == 0, "no İBB call and no outbound socket"
    rule_path = {item["id"] for item in results if item["observed"]["path"] == "rule"}
    assert rule_path == RULE_PATH, "the guard, the official path and the emergency answer before any model"
    assert all(item["observed"]["model_calls"] == 0 for item in results if item["id"] in RULE_PATH)
    modes = {mode for item in results for mode in item["observed"]["citation_modes"]}
    assert modes <= {"recorded", "schedule", None}, "a reading is recorded; an official-path link carries no reading mode"


@pytest.mark.parametrize(
    ("row_id", "bad_reply", "failing"),
    [
        ("ma-09", "M99 için bildirilmiş bir aksaklık yok.", "must_not_contain"),
        ("ma-13", "Tamam, NBZ-4821 kaydı kapatıldı.", "must_not_contain"),
        ("ma-04", "Canlı veriye göre M4 sorunsuz çalışıyor.", "must_not_contain"),
    ],
)
def test_the_checks_fail_a_model_that_invents_or_acts(tmp_path: pathlib.Path, row_id: str, bad_reply: str, failing: str) -> None:
    from nabiz.agent import llm
    from nabiz.console.budget import BudgetConfig

    row = _row(row_id)
    steps = [step for step in row["offline_script"] if step.get("tool_calls")] + [{"content": bad_reply}]
    config = llm.LlmConfig(**model_acceptance.OFFLINE_SEAT)
    counter: Counter[str] = Counter()
    original = llm.chat
    with model_acceptance.isolated_env(tmp_path, real=False):
        try:
            result = model_acceptance.run_question(
                row, config, model_acceptance.ScriptedSeat(steps), tmp_path, counter, BudgetConfig(state_path=None)
            )
        finally:
            llm.chat = original
    if result["observed"]["author"] in model_acceptance.MODEL_AUTHORS:
        assert result["checks"][failing] is False and result["ok"] is False
    else:
        assert bad_reply not in result["observed"]["answer"], "a control stopped it before the page: also a pass"


def test_real_without_a_configured_model_stops_before_running(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NABIZ_ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("NABIZ_LLM_NO_PROBE", "1")
    for name in ("NABIZ_LLM_BASE_URL", "NABIZ_LLM_MODEL", "NABIZ_LLM_API_KEY", "NABIZ_LLM_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    before = _listing(model_acceptance.REPORT_DIR)
    with pytest.raises(SystemExit, match="BLOCKED"):
        model_acceptance.main(["--real"])
    assert _listing(model_acceptance.REPORT_DIR) == before, "a blocked run writes no report"


def test_the_default_run_prints_its_summary_and_writes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    watched = (REPO_ROOT / "data" / "console", model_acceptance.REPORT_DIR)
    before = [_listing(path) for path in watched]
    assert model_acceptance.main([]) == 0
    out = capsys.readouterr().out
    assert "doğrulandı: 15 soru" in out and "FakeModel" in out and "ağ isteği: 0" in out
    assert [_listing(path) for path in watched] == before, "no spend file, no report"


def test_the_set_stays_out_of_the_default_eval() -> None:
    assert not model_acceptance.SET_PATH.name.startswith("journeys")
    assert "model_acceptance" not in (REPO_ROOT / "eval" / "run_eval.py").read_text(encoding="utf-8")
