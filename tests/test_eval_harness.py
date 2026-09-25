"""The journey eval harness's own consistency checks, run with the suite.

``eval/run_eval.py --selftest`` reads the scenario file and the metric helpers and touches
neither data nor network. It used to run only by hand, which is how three tools reached the
MCP server with no scenario and the check that should have said so went unnoticed. Here it
runs on every push.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest
from conftest import REPO_ROOT

_spec = importlib.util.spec_from_file_location("run_eval", REPO_ROOT / "eval" / "run_eval.py")
run_eval = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(run_eval)


def test_the_scenario_file_passes_the_harness_selftest(capsys: pytest.CaptureFixture[str]) -> None:
    scenarios = run_eval.load_scenarios(run_eval.JOURNEYS)
    assert run_eval.selftest(scenarios) == 0, capsys.readouterr().out


def test_every_tool_the_server_registers_has_a_scenario() -> None:
    scenarios = run_eval.load_scenarios(run_eval.JOURNEYS)
    covered = {call["tool"] for scenario in scenarios for call in scenario["calls"]}
    assert run_eval.mcp_tool_names() <= covered


def test_a_scenario_can_only_name_modes_the_runner_has(tmp_path: pathlib.Path) -> None:
    row = json.loads(run_eval.JOURNEYS.read_text(encoding="utf-8").splitlines()[0])
    bad = tmp_path / "journeys.jsonl"
    bad.write_text(json.dumps({**row, "modes": ["telepathy"]}, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="modes"):
        run_eval.load_scenarios(bad)


def test_the_alert_scenario_is_never_put_to_the_agent() -> None:
    """The web agent holds no subscription and does not offer check_alerts."""
    scenarios = run_eval.load_scenarios(run_eval.JOURNEYS)
    alerting = [s for s in scenarios if "check_alerts" in s["expected_tools"]]
    assert alerting and all(s.get("modes") == ["deterministic"] for s in alerting)


def test_an_offline_run_leaves_latest_md_alone(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``latest.md`` is the most recent live run, which README Results quotes.

    Before 2026-09-23 every offline run replaced it, so ``make eval`` as a verification step
    rewrote a tracked file with recorded-data numbers.
    """
    latest = tmp_path / "latest.md"
    latest.write_text("the live run\n", encoding="utf-8")

    assert run_eval.main(["--offline", "--only", "j3-tr-1", "--results-dir", str(tmp_path)]) == 0

    assert latest.read_text(encoding="utf-8") == "the live run\n"
    kept = sorted(path.suffix for path in tmp_path.iterdir() if path != latest)
    assert kept == [".json", ".md"], "the run's own record is still written"
    assert "latest.md" not in capsys.readouterr().out.splitlines()[-1]


def test_update_latest_points_latest_md_at_an_offline_run(tmp_path: pathlib.Path) -> None:
    latest = tmp_path / "latest.md"
    latest.write_text("the live run\n", encoding="utf-8")

    assert run_eval.main(["--offline", "--only", "j3-tr-1", "--results-dir", str(tmp_path), "--update-latest"]) == 0

    (record,) = tmp_path.glob("*-offline.md")
    assert latest.read_text(encoding="utf-8") == record.read_text(encoding="utf-8")
