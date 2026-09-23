"""``scripts/probe_day0.py`` writes ``docs/day0_report.json``, a tracked file in a public repository.

What a CLI prints after its version number is a machine fingerprint (a build triple naming
the CPU and OS, a vendor suffix, an install prefix naming the package manager), so the
report keeps the version and nothing else. Nothing here runs a check or reaches the network.
"""

from __future__ import annotations

import importlib.util
import sys

import pytest
from conftest import REPO_ROOT

_spec = importlib.util.spec_from_file_location("probe_day0", REPO_ROOT / "scripts" / "probe_day0.py")
probe_day0 = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = probe_day0
_spec.loader.exec_module(probe_day0)


@pytest.mark.parametrize(
    ("exe", "raw", "expected"),
    [
        ("uv", "uv 0.11.14 (3fdfdc7d4 2026-05-12 aarch64-apple-darwin)", "uv 0.11.14"),
        ("git", "git version 2.50.1 (Apple Git-155)", "git 2.50.1"),
        ("gh", "gh version 2.97.0 (2026-07-31)", "gh 2.97.0"),
        ("az", "azure-cli 2.77.0", "az 2.77.0"),
        ("foundry", "no version here", "foundry"),
    ],
)
def test_a_tool_version_keeps_the_number_and_drops_the_fingerprint(exe: str, raw: str, expected: str) -> None:
    assert probe_day0._bare_version(exe, raw) == expected


def test_the_committed_report_carries_no_machine_fingerprint() -> None:
    text = (REPO_ROOT / "docs" / "day0_report.json").read_text(encoding="utf-8")
    home_mac, home_linux = "/Us" + "ers/", "/ho" + "me/"
    for fingerprint in ("darwin", "linux-gnu", "homebrew", "Apple Git", "/usr/", "~/", home_mac, home_linux):
        assert fingerprint not in text, fingerprint
