"""The two ETA measurement scripts, on synthetic data only.

``scripts/eta_report.py`` rewrites ``eval/results/eta.md`` and ``scripts/eta_holdout.py``
replays the calibrated profile; both read the gitignored lake. These tests point them at an
empty temporary lake and a temporary results file, so they never read the collector's data
and never touch the committed report.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
import sys

import pytest
from conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


eta_report = _load("eta_report")
eta_holdout = _load("eta_holdout")


def test_a_rerun_keeps_the_hand_written_part_of_the_report(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """eval/results/eta.md carries the held-out replay and the history below a rule. The
    script regenerates the part above it; losing the part below would lose the only record
    of what the in-sample figures mean."""
    results = tmp_path / "eval" / "results"
    results.mkdir(parents=True)
    hand_written = eta_report.HAND_WRITTEN_MARKER + " a command*\n\n## Held-out replay\n\nkept\n"
    (results / "eta.md").write_text("# ETA accuracy\n\nold numbers\n" + hand_written, encoding="utf-8")
    monkeypatch.setattr(eta_report, "ROOT", tmp_path)
    monkeypatch.setenv("NABIZ_LAKE_DIR", str(tmp_path / "lake"))
    monkeypatch.setenv("NABIZ_GTFS_DIR", str(tmp_path / "gtfs"))

    assert eta_report.main([]) == 0

    text = (results / "eta.md").read_text(encoding="utf-8")
    assert "old numbers" not in text
    assert text.endswith(hand_written)
    assert text.count(eta_report.HAND_WRITTEN_MARKER) == 1


def test_a_first_run_writes_only_the_generated_part(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(eta_report, "ROOT", tmp_path)
    monkeypatch.setenv("NABIZ_LAKE_DIR", str(tmp_path / "lake"))
    monkeypatch.setenv("NABIZ_GTFS_DIR", str(tmp_path / "gtfs"))

    assert eta_report.main([]) == 0

    assert eta_report.HAND_WRITTEN_MARKER not in (tmp_path / "eval" / "results" / "eta.md").read_text(encoding="utf-8")


def test_the_replay_scores_only_windows_the_collector_fully_watched() -> None:
    """A prediction near the end of a collection run has only its fast outcomes observed;
    scoring it would flatter whichever rate is lower."""
    start = dt.datetime(2026, 9, 13, 16, 0, tzinfo=dt.UTC)
    every_three_minutes = [start + dt.timedelta(minutes=3 * n) for n in range(40)]  # 117 minutes of ticks
    assert eta_holdout.window_is_covered(start, every_three_minutes)
    assert not eta_holdout.window_is_covered(start + dt.timedelta(minutes=60), every_three_minutes)

    with_a_gap = [t for t in every_three_minutes if not start + dt.timedelta(minutes=20) < t < start + dt.timedelta(minutes=40)]
    assert not eta_holdout.window_is_covered(start, with_a_gap)
