"""Tests for ``scripts/demo_numbers.py``: the parsers read the real output formats, and nothing broken is written.

No subprocess runs here: every step's output is handed in as text, the way ``measure`` reads it.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import pathlib
import re
import sys

import pytest
from conftest import REPO_ROOT

_spec = importlib.util.spec_from_file_location("demo_numbers", REPO_ROOT / "scripts" / "demo_numbers.py")
demo = importlib.util.module_from_spec(_spec)
# Registered before it runs: @dataclass resolves the module's annotations through sys.modules.
sys.modules[_spec.name] = demo
_spec.loader.exec_module(demo)

EVAL_REPORT = (
    "# Eval results\n\n"
    "`mode=deterministic` · `offline` · data source: recorded fixtures (tests/fixtures) · "
    "60/72 scenarios run, 12 skipped · upstream requests to İBB: 0\n\n"
    "| Metric | Result | How it is measured |\n|---|---|---|\n"
    "| Task success rate | 60/60 (100.0%) | journey scenarios |\n"
)
OUTPUTS = {
    "tools": "iett_next_arrivals\nair_quality\n",
    "collect": "tests/test_x.py::test_a\n\n2128 tests collected in 0.78s\n",
    "pytest": "....\n2 failed, 2118 passed, 5 skipped, 3 xfailed, 1 warning in 47.32s\n",
    "eval": EVAL_REPORT,
    "knowledge": "PASS: 1351 records; schema and forbidden-claim checks valid\nBuckets: k-genel=20\n",
    "commit": "93c16bf\n",
}
NOW = dt.datetime(2026, 9, 26, 3, 0, tzinfo=dt.UTC)


def sheet(**broken: str) -> demo.Sheet:
    outputs = OUTPUTS | broken
    return demo.measure(outputs.__getitem__, now=NOW)


def test_parse_collected_reads_the_last_line() -> None:
    assert demo.parse_collected("2128 tests collected in 0.78s") == 2128
    assert demo.parse_collected(OUTPUTS["collect"]) == 2128
    with pytest.raises(demo.ParseError):
        demo.parse_collected("no tests ran in 0.01s")


def test_parse_pytest_summary_counts_each_outcome() -> None:
    assert demo.parse_pytest_summary("2 failed, 2118 passed, 5 skipped, 3 xfailed, 1 warning in 47.32s") == {
        "failed": 2,
        "passed": 2118,
        "skipped": 5,
        "xfailed": 3,
    }
    assert demo.parse_pytest_summary("2120 passed in 40.00s") == {"failed": 0, "passed": 2120, "skipped": 0, "xfailed": 0}
    with pytest.raises(demo.ParseError):
        demo.parse_pytest_summary("ImportError: no module named ibb_mcp")


def test_parse_eval_header_reads_run_total_skipped() -> None:
    assert demo.parse_eval_header("... · 60/72 scenarios run, 12 skipped · ...") == (60, 72, 12)
    assert demo.parse_eval_success(EVAL_REPORT) == (60, 60)
    with pytest.raises(demo.ParseError):
        demo.parse_eval_header("72 scenarios")


def test_parse_knowledge_reads_the_record_count() -> None:
    assert demo.parse_knowledge("PASS: 100 records; schema and forbidden-claim checks valid") == 100
    with pytest.raises(demo.ParseError):
        demo.parse_knowledge("FAIL: 3 problems")


def test_render_writes_plain_integers_without_dashes() -> None:
    text = demo.render(sheet())
    assert "—" not in text and "–" not in text
    assert not re.search(r"\bETA\b", text)
    assert "| Knowledge questions validated | 1351 |" in text and "1,351" not in text
    assert "| MCP tools | 2 |" in text and "Tools: air_quality, iett_next_arrivals" in text
    assert "working tree over commit `93c16bf`" in text and "NABIZ_SPRINT_MODE=1 (DECISIONS #29)" in text


def test_render_json_matches_the_markdown_rows() -> None:
    measured = sheet()
    data = json.loads(demo.render_json(measured))
    cells = dict(re.findall(r"^\| ([^|]+?) \| (\d+) \|", demo.render(measured), re.MULTILINE))
    assert len(cells) == len(demo.ROWS)
    for name, key, _ in demo.ROWS:
        assert data[key] == int(cells[name]), key
    assert data["commit"] == "93c16bf" and data["sprint_mode"] is True
    assert data["measured_at"] == "2026-09-26T03:00:00Z"
    assert set(data) == {key for _, key, _ in demo.ROWS} | {"tool_names", "commit", "measured_at", "sprint_mode"}


@pytest.mark.parametrize("step", ["collect", "pytest", "eval", "knowledge", "commit"])
def test_an_unparseable_step_writes_nothing(step: str, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    outputs = OUTPUTS | {step: "Traceback (most recent call last):\n  boom\n"}
    assert demo.main(["--write", "--out-dir", str(tmp_path)], read=outputs.__getitem__) == 1
    assert not (tmp_path / "numbers.md").exists() and not (tmp_path / "numbers.json").exists()
    assert f"{step}:" in capsys.readouterr().err
    assert demo.main(["--write", "--out-dir", str(tmp_path)], read=OUTPUTS.__getitem__) == 0
    assert (tmp_path / "numbers.md").exists() and (tmp_path / "numbers.json").exists()
