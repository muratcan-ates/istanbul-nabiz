"""Tests for the token scripts in ``scripts/design/``: the page's colours are measured, not typed.

``static/css/tokens.css`` is generated, so these hold the committed file to what the scripts write
and every contrast pair to its WCAG minimum, and show each check going red on the breakage it
guards (docs/ENGINEERING.md CI-6). The scripts are standard library only; nothing reads the network.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from types import ModuleType

import pytest
from conftest import REPO_ROOT

DESIGN = REPO_ROOT / "scripts" / "design"


def load(name: str) -> ModuleType:
    """Import one design script; registered by name because the scripts import each other by name."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, DESIGN / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


colorlib = load("colorlib")
build_palette = load("build_palette")
build_final_tokens = load("build_final_tokens")
verify_tokens = load("verify_tokens")


@pytest.fixture
def token_copies(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """The served file and its annotated copy, generated into tmp_path for one test to break."""
    assert build_final_tokens.main(["--out", str(tmp_path)]) == 0
    return tmp_path / "tokens.css", tmp_path / "tokens.annotated.css"


def test_the_colour_maths_match_published_reference_values() -> None:
    # Ottosson's OKLab red, the textbook 4.48:1 grey, Sharma's CIEDE2000 pairs, Machado's grey.
    colorlib.self_check()


def test_every_palette_pair_passes_and_no_pure_black_or_white_is_used(capsys: pytest.CaptureFixture[str]) -> None:
    assert build_palette.main([]) == 0, capsys.readouterr().out


def test_the_committed_token_files_are_what_the_scripts_generate() -> None:
    assert build_final_tokens.main(["--check"]) == 0


def test_a_hand_edit_of_the_served_tokens_is_caught(token_copies: tuple[pathlib.Path, pathlib.Path]) -> None:
    served, _ = token_copies
    text = served.read_text(encoding="utf-8")
    served.write_text(text.replace("--primary-700: ", "--primary-700: #123456; --was: ", 1), encoding="utf-8")
    assert build_final_tokens.main(["--out", str(served.parent), "--check"]) == 1


def test_every_contrast_pair_passes_in_both_themes() -> None:
    served, annotated = (path.read_text(encoding="utf-8") for path in (build_final_tokens.SERVED, build_final_tokens.ANNOTATED))
    report, _ = verify_tokens.verify(served, annotated)
    assert report["problems"] == []
    # The counts docs/design/DESIGN.md §3 quotes.
    assert report["counts"] == {"palette_required": 178, "palette_pass": 178, "added_required": 80, "added_pass": 80}
    assert report["served_equals_annotated"] and report["dark_blocks_identical"]


def test_a_failing_pair_turns_the_verifier_red(token_copies: tuple[pathlib.Path, pathlib.Path]) -> None:
    # Axis labels and stamps in a pale grey: under 4.5:1 on the page in the light theme.
    pale = ("--text-subtle: var(--neutral-600);", "--text-subtle: var(--neutral-300);")
    texts = [path.read_text(encoding="utf-8").replace(*pale, 1) for path in token_copies]
    report, _ = verify_tokens.verify(*texts)
    assert any("text-subtle" in problem for problem in report["problems"]), report["problems"]


def test_dark_blocks_that_drift_apart_turn_the_verifier_red(token_copies: tuple[pathlib.Path, pathlib.Path]) -> None:
    served, annotated = (path.read_text(encoding="utf-8") for path in token_copies)
    # Only the data-theme="dark" block (the last one) changes; the OS-dark block keeps its value.
    head, sep, tail = served.rpartition("--text-muted: ")
    report, _ = verify_tokens.verify(head + sep + tail.replace("var(--neutral-300)", "var(--neutral-200)", 1), annotated)
    assert any("drift" in problem for problem in report["problems"]), report["problems"]
