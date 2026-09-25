"""Sprint mode (DECISIONS #26): ``NABIZ_SPRINT_MODE=1`` turns a failing ratchet into a WARN, and nothing else.

Same synthetic trees as ``tests/test_check_architecture.py`` and ``tests/test_check_web_budget.py``, with a
ratchet violation and a contract violation side by side, so the flag is seen to loosen the first and leave
the second red. Without the variable both scripts behave exactly as before; ``make ci-commit`` never sets it.
"""

from __future__ import annotations

import pathlib
import shutil

import pytest
from conftest import REPO_ROOT
from test_check_architecture import CLEAN, arch, tree
from test_check_web_budget import budget, random_text, write

FLAG = "NABIZ_SPRINT_MODE"
CONTRACTS = ("layers", "no-cycles", "dependency-sets", "private-imports")


@pytest.fixture
def off(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.delenv(FLAG, raising=False)
    return monkeypatch


def test_the_flag_is_off_unless_it_is_exactly_1(off: pytest.MonkeyPatch) -> None:
    assert not arch.sprint_mode() and not budget.sprint_mode()
    off.setenv(FLAG, "0")
    assert not arch.sprint_mode() and not budget.sprint_mode()
    off.setenv(FLAG, "1")
    assert arch.sprint_mode() and budget.sprint_mode()
    assert arch.SPRINT_MODE_ENV == budget.SPRINT_MODE_ENV == FLAG


# --------------------------------------------------------------------------------------
# architecture: every ratchet is a WARN, every contract stays a FAIL
# --------------------------------------------------------------------------------------
def all_red(root: pathlib.Path) -> None:
    """One tree that fails all eight checks: four contracts and four ratchets."""
    over_cap = "".join(f"x{i} = {i}\n" for i in range(arch.MODULE_CODE_LINES_CAP + 1))
    methods = "".join(f"    def tool_{i}(self):\n        return {i}\n" for i in range(arch.CLASS_PUBLIC_METHODS_CAP + 1))
    too_many = arch.COMPLEXITY_THRESHOLDS["lint.mccabe.max-complexity"]  # that many branches is one over
    branches = "".join(f"    if x == {i}:\n        return {i}\n" for i in range(too_many))
    tree(
        root,
        CLEAN
        | {
            "ibb_mcp/models.py": "from ibb_mcp.cache import Y\n" + over_cap,  # module-size, and a cycle with cache
            # layers (foundation imports facade), dependency-sets (fastapi), and the other half of the cycle
            "ibb_mcp/cache.py": "from ibb_mcp.models import X\nfrom ibb_mcp.tools import X\nimport fastapi\nY = 2\n",
            "ibb_mcp/tools.py": f"class Nabiz:\n{methods}",  # class-size
            "ibb_mcp/text.py": "def normalize_tr(t):\n    return t\n",  # one-meaning, with gtfs
            "ibb_mcp/gtfs.py": f"def normalize_tr(t):\n    return t\n\n\ndef route(x):\n{branches}    return -1\n",  # complexity
            "nabiz/web/main.py": "from ibb_mcp.tools import _dump\n",  # private-imports
        },
    )


def test_ratchets_warn_and_contracts_fail_under_the_flag(tmp_path: pathlib.Path, off: pytest.MonkeyPatch) -> None:
    all_red(tmp_path)
    before = {r.name: r for r in arch.run_checks(tmp_path, {})}
    assert {r.status for r in before.values()} == {arch.FAIL}, before
    off.setenv(FLAG, "1")
    after = {r.name: r for r in arch.run_checks(tmp_path, {})}
    assert {name: r.status for name, r in after.items()} == {
        name: arch.FAIL if name in CONTRACTS else arch.WARN for name, _ in arch.CHECKS
    }
    for name in arch.RATCHETS:  # the findings stay on screen, only the verdict changes
        assert after[name].findings == before[name].findings, name
        assert "sprint mode" in after[name].summary and before[name].summary in after[name].summary


def test_the_exit_code_follows_the_verdict(tmp_path: pathlib.Path, off: pytest.MonkeyPatch) -> None:
    all_red(tmp_path)
    ratchets = ["--repo", str(tmp_path), "--only", ",".join(sorted(arch.RATCHETS))]
    contracts = ["--repo", str(tmp_path), "--only", ",".join(CONTRACTS)]
    assert arch.main(ratchets) == 1 and arch.main(contracts) == 1
    off.setenv(FLAG, "1")
    assert arch.main(ratchets) == 0
    assert arch.main(contracts) == 1
    assert arch.main(["--repo", str(tmp_path)]) == 1  # the contracts still decide the whole run


def test_a_ratchet_check_that_raises_is_still_a_fail(tmp_path: pathlib.Path, off: pytest.MonkeyPatch) -> None:
    def boom(repo: pathlib.Path, mods: dict, baseline: dict) -> arch.CheckResult:
        raise RuntimeError("ruff missing")

    off.setattr(arch, "CHECKS", (("complexity", boom),))
    off.setenv(FLAG, "1")
    tree(tmp_path, CLEAN)
    (result,) = arch.run_checks(tmp_path, {})
    assert result.status == arch.FAIL and "raised RuntimeError" in result.summary


def test_the_real_tree_gets_no_new_finding_from_the_flag(off: pytest.MonkeyPatch) -> None:
    """The flag only ever lowers a verdict: on this checkout the two runs agree on every finding."""
    off.setattr(arch, "LAYER_EXCEPTIONS", dict(arch.LAYER_EXCEPTIONS))
    only = set(arch.RATCHETS) - {"complexity"}  # complexity runs ruff over the tree; the other three are enough
    before = [(r.name, r.status, r.findings) for r in arch.run_checks(REPO_ROOT, {}, only)]
    off.setenv(FLAG, "1")
    after = [(r.name, r.status, r.findings) for r in arch.run_checks(REPO_ROOT, {}, only)]
    assert [(n, f) for n, _, f in after] == [(n, f) for n, _, f in before]
    assert all(s == (arch.WARN if b == arch.FAIL else b) for (_, s, _), (_, b, _) in zip(after, before, strict=True))


# --------------------------------------------------------------------------------------
# web budget: the byte budget is a WARN, every other check stays a FAIL
# --------------------------------------------------------------------------------------
@pytest.fixture
def page(tmp_path: pathlib.Path) -> pathlib.Path:
    shutil.copytree(REPO_ROOT / budget.STATIC, tmp_path / budget.STATIC)
    # A vendored-library-sized blob past the JS target, and an em dash in visible text.
    write(tmp_path, "js/vendor-ish.js", f"// {random_text(90_000)}\n")
    write(tmp_path, "js/zz-dash.js", "export const s = 'a — b';\n")
    return tmp_path


def test_the_byte_budget_warns_and_a_fence_still_fails(page: pathlib.Path, off: pytest.MonkeyPatch) -> None:
    before = {r.name: r for r in budget.run_checks(page)}
    assert before["payload"].status == before["dashes"].status == budget.FAIL
    off.setenv(FLAG, "1")
    after = {r.name: r for r in budget.run_checks(page)}
    assert after["payload"].status == budget.WARN and after["dashes"].status == budget.FAIL
    assert [line for _, line in after["payload"].lines] == [line for _, line in before["payload"].lines]
    assert {status for status, _ in after["payload"].lines} == {budget.WARN}
    assert {r.name: r.status for r in budget.run_checks(page, strict=True)}["payload"] == budget.FAIL  # --strict wins


def test_a_met_target_is_a_warn_too_under_the_flag() -> None:
    """Deleting a met entry is the Integrator's edit, not a lane's; the lane hears about it and goes on."""
    result = budget.CheckResult("payload", "", [])
    assert budget.judge(result, budget.TARGETS, strict=False, sprint=True).status == budget.WARN
    assert any("target met" in line for _, line in result.lines)
    other = budget.CheckResult("dashes", "", [budget.Finding("dashes:x.js", "x.js: 1 em/en dash(es) in visible text")])
    assert budget.judge(other, budget.TARGETS, strict=False, sprint=True).status == budget.FAIL


def test_the_web_exit_code_follows_the_verdict(
    page: pathlib.Path, off: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = ["--repo", str(page), "--only", "payload"]
    assert budget.main(payload) == 1
    off.setenv(FLAG, "1")
    assert budget.main(payload) == 0
    out = capsys.readouterr().out
    assert "WARN" in out and "(mode: sprint)" in out
    assert budget.main([*payload, "--strict"]) == 1
    assert budget.main(["--repo", str(page)]) == 1  # the dash still fails the whole run


# --------------------------------------------------------------------------------------
# the make targets: lane-gates sets the flag, ci-commit and CI never do
# --------------------------------------------------------------------------------------
def recipe(makefile: str, target: str) -> str:
    return makefile.split(f"\n{target}:", 1)[1].split("\n\n", 1)[0]


def test_lane_gates_runs_the_sprint_list_and_the_full_gate_never_sees_the_flag() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    lane = recipe(makefile, "lane-gates")
    # NABIZ_LLM_NO_PROBE=1 keeps the Foundry Local probe out of the lane gate too (G8, DECISIONS #28).
    assert "NABIZ_OFFLINE=1 NABIZ_LLM_NO_PROBE=1 $(PY) -m pytest -q -x" in lane
    assert "$(RUFF) check $(SRC)" in lane
    assert f"{FLAG}=1 $(MAKE) --no-print-directory architecture" in lane
    assert "$(MAKE) --no-print-directory guardrails" in lane
    assert FLAG not in recipe(makefile, "ci-commit") and FLAG not in recipe(makefile, "architecture")
    for path in (".github/scripts/ci_local.sh", ".github/workflows/ci.yml"):
        assert FLAG not in (REPO_ROOT / path).read_text(encoding="utf-8"), path
    # ci_local.sh strips every NABIZ_* variable from the shell it inherits, so an exported flag dies there too.
    assert "NABIZ_[A-Za-z0-9_]*" in (REPO_ROOT / ".github/scripts/ci_local.sh").read_text(encoding="utf-8")
