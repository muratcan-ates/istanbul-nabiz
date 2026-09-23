"""Tests for ``scripts/check_architecture.py``: each fence goes red on the shape it guards.

Same pattern as ``tests/test_guardrails.py``: a tiny synthetic ``src/`` in ``tmp_path`` with
one violation, and the same tree without it. A gate that has never been seen failing is
not a gate yet (docs/ENGINEERING.md, principle 1), so every check has a red case here.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tomllib

import pytest
from conftest import REPO_ROOT

_spec = importlib.util.spec_from_file_location("check_architecture", REPO_ROOT / "scripts" / "check_architecture.py")
arch = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = arch
_spec.loader.exec_module(arch)

#: The repository's own dated exceptions, for the tests that check the real tree.
REAL_EXCEPTIONS = dict(arch.LAYER_EXCEPTIONS)


def tree(root: pathlib.Path, files: dict[str, str]) -> dict[str, arch.Module]:
    for name, text in files.items():
        path = root / "src" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return arch.load_modules(root)


CLEAN = {
    "ibb_mcp/models.py": "X = 1\n",
    "ibb_mcp/cache.py": "from ibb_mcp.models import X\n",
    "ibb_mcp/sources/base.py": "from ibb_mcp.cache import X\n",
    "ibb_mcp/sources/metro.py": "from ibb_mcp.sources.base import X\n",
    "ibb_mcp/tools.py": "from ibb_mcp.sources.base import X\n",
    "nabiz/agent/agent.py": "from ibb_mcp.tools import X\n",
    "nabiz/web/main.py": "from ibb_mcp.tools import X\nfrom ibb_mcp.config import Y\n",
    "ibb_mcp/config.py": "Y = 2\n",
}


@pytest.fixture(autouse=True)
def no_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    """The repository's dated exceptions name modules the synthetic trees do not have."""
    monkeypatch.setattr(arch, "LAYER_EXCEPTIONS", {})


def test_a_clean_tree_passes_every_import_check(tmp_path: pathlib.Path) -> None:
    mods = tree(tmp_path, CLEAN)
    for check in (arch.check_layers, arch.check_no_cycles, arch.check_dependency_sets, arch.check_private_imports):
        result = check(tmp_path, mods, {})
        assert result.status == arch.PASS, result


@pytest.mark.parametrize(
    ("name", "text", "why"),
    [
        # DECISIONS #8, the edge the rule exists for; a lazy import counts too.
        ("ibb_mcp/tools.py", "def f():\n    from nabiz.alerts.engine import check_alerts\n", "facade imports apps"),
        ("ibb_mcp/models.py", "def f():\n    import nabiz.web.main\n", "foundation imports apps"),
        ("ibb_mcp/cache.py", "from ibb_mcp.tools import X\n", "foundation imports facade"),
        ("ibb_mcp/sources/iett.py", "from ibb_mcp.sources.metro import X\n", "sibling source"),
        ("nabiz/web/main.py", "from nabiz.agent.agent import X\n", "sibling app"),
        ("nabiz/agent/agent.py", "from ibb_mcp.sources.metro import X\n", "bypasses the ibb_mcp.tools facade"),
    ],
)
def test_each_forbidden_edge_fails(tmp_path: pathlib.Path, name: str, text: str, why: str) -> None:
    files = CLEAN | {"nabiz/alerts/engine.py": "X = 1\n"} | {name: text}
    result = arch.check_layers(tmp_path, tree(tmp_path, files), {})
    assert result.status == arch.FAIL and any(why in f.message for f in result.findings), result


def test_a_dated_exception_lets_its_edge_through(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(arch, "LAYER_EXCEPTIONS", {("nabiz.web.main", "nabiz.agent.agent"): "being removed"})
    files = CLEAN | {"nabiz/web/main.py": "from nabiz.agent.agent import X\n"}
    assert arch.check_layers(tmp_path, tree(tmp_path, files), {}).status == arch.PASS


def test_a_stale_exception_fails_so_the_list_only_shrinks(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(arch, "LAYER_EXCEPTIONS", {("ibb_mcp.cache", "ibb_mcp.tools"): "gone already"})
    result = arch.check_layers(tmp_path, tree(tmp_path, CLEAN), {})
    assert result.status == arch.FAIL and "stale exception" in result.findings[0].message


def test_a_module_in_no_layer_fails(tmp_path: pathlib.Path) -> None:
    result = arch.check_layers(tmp_path, tree(tmp_path, CLEAN | {"ibb_mcp/newthing.py": "X = 1\n"}), {})
    assert result.status == arch.FAIL and "in no layer" in result.findings[0].message


def test_a_cycle_fails(tmp_path: pathlib.Path) -> None:
    mods = tree(tmp_path, CLEAN | {"ibb_mcp/models.py": "from ibb_mcp.cache import Y\nX = 1\n"})
    result = arch.check_no_cycles(tmp_path, mods, {})
    assert result.status == arch.FAIL and "ibb_mcp.cache <-> ibb_mcp.models" in result.findings[0].location


def test_a_lazy_cycle_fails_too(tmp_path: pathlib.Path) -> None:
    mods = tree(tmp_path, CLEAN | {"ibb_mcp/models.py": "def f():\n    from ibb_mcp.cache import Y\n"})
    assert arch.check_no_cycles(tmp_path, mods, {}).status == arch.FAIL


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("ibb_mcp/cache.py", "import fastapi\n"),  # the server package has three runtime dependencies
        ("ibb_mcp/sources/base.py", "def f():\n    import openai\n"),
        ("nabiz/web/main.py", "from azure.identity import DefaultAzureCredential\n"),  # web carries no Azure SDK
    ],
)
def test_an_undeclared_third_party_import_fails(tmp_path: pathlib.Path, name: str, text: str) -> None:
    mods = tree(tmp_path, CLEAN | {name: text})
    assert arch.check_dependency_sets(tmp_path, mods, {}).status == arch.FAIL


def test_the_mcp_transport_may_use_what_the_sdk_brings(tmp_path: pathlib.Path) -> None:
    mods = tree(tmp_path, CLEAN | {"ibb_mcp/server.py": "import uvicorn\nfrom starlette.requests import Request\n"})
    assert arch.check_dependency_sets(tmp_path, mods, {}).status == arch.PASS


def test_a_new_repeated_public_name_fails_and_a_known_one_may_only_go(tmp_path: pathlib.Path) -> None:
    twice = "def normalize_tr(t):\n    return t\n"
    files = CLEAN | {"ibb_mcp/text.py": twice, "ibb_mcp/gtfs.py": twice}
    mods = tree(tmp_path, files)
    assert arch.check_one_meaning(tmp_path, mods, {}).status == arch.FAIL
    assert arch.check_one_meaning(tmp_path, mods, {"one_meaning": {"normalize_tr": 2}}).status == arch.PASS
    assert arch.check_one_meaning(tmp_path, mods, {"one_meaning": {"normalize_tr": 3}}).status == arch.WARN


def test_a_re_export_is_not_a_second_meaning(tmp_path: pathlib.Path) -> None:
    files = CLEAN | {
        "ibb_mcp/text.py": "def normalize_tr(t):\n    return t\n",
        "ibb_mcp/gtfs.py": "from ibb_mcp.text import normalize_tr\nfold = normalize_tr\n",
    }
    assert arch.check_one_meaning(tmp_path, tree(tmp_path, files), {}).status == arch.PASS


def test_importing_a_private_name_fails(tmp_path: pathlib.Path) -> None:
    mods = tree(tmp_path, CLEAN | {"nabiz/web/main.py": "from ibb_mcp.tools import _dump\n"})
    assert arch.check_private_imports(tmp_path, mods, {}).status == arch.FAIL


def test_module_size_ratchet_blocks_growth_and_ignores_comments(tmp_path: pathlib.Path) -> None:
    code = "".join(f"x{i} = {i}\n" for i in range(arch.MODULE_CODE_LINES_CAP + 5))
    baseline = {"module_code_lines": {"src/ibb_mcp/models.py": arch.MODULE_CODE_LINES_CAP + 5}}
    assert arch.check_module_size(tmp_path, tree(tmp_path, CLEAN | {"ibb_mcp/models.py": code}), {}).status == arch.FAIL
    assert arch.check_module_size(tmp_path, tree(tmp_path, {"ibb_mcp/models.py": code}), baseline).status == arch.PASS
    commented = '"""A long module docstring.\n' + "text\n" * 50 + '"""\n' + code + "".join(f"# why {i}\n" for i in range(50))
    assert arch.check_module_size(tmp_path, tree(tmp_path, {"ibb_mcp/models.py": commented}), baseline).status == arch.PASS
    grown = tree(tmp_path, {"ibb_mcp/models.py": code + "one_more = 1\n"})
    result = arch.check_module_size(tmp_path, grown, baseline)
    assert result.status == arch.FAIL and "grew from" in result.findings[0].message
    shrunk = tree(tmp_path, {"ibb_mcp/models.py": code[: code.rindex("x")]})
    assert arch.check_module_size(tmp_path, shrunk, baseline).status == arch.WARN


def test_class_size_ratchet_counts_public_methods(tmp_path: pathlib.Path) -> None:
    methods = "".join(f"    def tool_{i}(self):\n        return {i}\n" for i in range(arch.CLASS_PUBLIC_METHODS_CAP + 1))
    mods = tree(tmp_path, CLEAN | {"ibb_mcp/tools.py": f"class Nabiz:\n{methods}"})
    result = arch.check_class_size(tmp_path, mods, {})
    assert result.status == arch.FAIL and "public methods" in result.findings[0].message
    known = {"class_public_methods": {"src/ibb_mcp/tools.py::Nabiz": arch.CLASS_PUBLIC_METHODS_CAP + 1}}
    assert arch.check_class_size(tmp_path, mods, known).status == arch.PASS


def test_tighten_never_raises_or_adds_an_entry() -> None:
    old = {"module_code_lines": {"a.py": 500, "b.py": 450}, "complexity": {"a.py::f::C901": 14}}
    new = {"module_code_lines": {"a.py": 480, "b.py": 470, "c.py": 999}, "complexity": {"a.py::f::C901": 12, "b.py::g::C901": 11}}
    tightened = arch.tighten(old, new)
    assert tightened["module_code_lines"] == {"a.py": 480, "b.py": 450}
    assert tightened["complexity"] == {"a.py::f::C901": 12}


# --------------------------------------------------------------------------------------
# complexity, through the real ruff
# --------------------------------------------------------------------------------------
#: Small thresholds, so the synthetic functions below stay small; the gate's own are in
#: COMPLEXITY_THRESHOLDS. The PYPROJECT below sets the same small ones, and a debt ignore.
SMALL = {
    "lint.mccabe.max-complexity": 3,
    "lint.pylint.max-branches": 12,
    "lint.pylint.max-args": 3,
    "lint.pylint.max-statements": 50,
}


@pytest.fixture
def small_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(arch, "COMPLEXITY_THRESHOLDS", SMALL)


PYPROJECT = """
[tool.ruff]
line-length = 130
[tool.ruff.lint]
select = ["C90", "PLR0912", "PLR0913", "PLR0915"]
[tool.ruff.lint.mccabe]
max-complexity = 3
[tool.ruff.lint.pylint]
max-args = 3
[tool.ruff.lint.per-file-ignores]
"src/ibb_mcp/models.py" = ["C901", "PLR0913"]
"""


def branches(count: int) -> str:
    body = "".join(f"    if x == {i}:\n        return {i}\n" for i in range(count))
    return f"def route(x):  # noqa: C901 - debt\n{body}    return -1\n"


def complexity_repo(root: pathlib.Path, source: str) -> pathlib.Path:
    (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    tree(root, {"ibb_mcp/models.py": source})
    return root


@pytest.mark.usefixtures("small_thresholds")
def test_complexity_sees_through_noqa_and_debt_ignores(tmp_path: pathlib.Path) -> None:
    measured = arch.measure_complexity(complexity_repo(tmp_path, branches(4) + "\ndef wide(a, b, c, d):\n    return a\n"))
    assert measured == {"src/ibb_mcp/models.py::route::C901": 5, "src/ibb_mcp/models.py::wide::PLR0913": 4}


@pytest.mark.usefixtures("small_thresholds")
def test_complexity_ratchet_fails_on_a_new_or_a_worse_function(tmp_path: pathlib.Path) -> None:
    repo = complexity_repo(tmp_path, branches(4))
    known = {"complexity": {"src/ibb_mcp/models.py::route::C901": 5}}
    assert arch.check_complexity(repo, {}, known).status == arch.PASS
    assert arch.check_complexity(repo, {}, {}).status == arch.FAIL  # new
    complexity_repo(tmp_path, branches(5))
    result = arch.check_complexity(repo, {}, known)
    assert result.status == arch.FAIL and "was 5" in result.findings[0].message  # worse
    complexity_repo(tmp_path, branches(3))
    assert arch.check_complexity(repo, {}, known).status == arch.WARN  # better: tighten


@pytest.mark.usefixtures("small_thresholds")
def test_the_policy_ignore_still_applies_in_tests(tmp_path: pathlib.Path) -> None:
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_builder.py").write_text("def make(a, b, c, d, e):\n    return a\n", encoding="utf-8")
    assert arch.measure_complexity(tmp_path) == {}


def test_pyproject_can_neither_raise_a_threshold_nor_exclude_a_file(tmp_path: pathlib.Path) -> None:
    """The two ways around the ratchet shown on 2026-09-23: both passed `make lint` and this gate."""
    loosened = PYPROJECT.replace("max-complexity = 3", "max-complexity = 30").replace("max-args = 3", "max-args = 12")
    (tmp_path / "pyproject.toml").write_text(
        loosened.replace("line-length = 130", 'line-length = 130\nextend-exclude = ["src/ibb_mcp/models.py"]'), encoding="utf-8"
    )
    wide = "def wide(a, b, c, d, e, f, g, h, i):\n    return a\n"
    tree(tmp_path, {"ibb_mcp/models.py": branches(11) + "\n" + wide})
    assert arch.measure_complexity(tmp_path) == {
        "src/ibb_mcp/models.py::route::C901": 12,
        "src/ibb_mcp/models.py::wide::PLR0913": 9,
    }


def test_the_gates_thresholds_are_the_ones_pyproject_sets() -> None:
    """``make lint`` reads pyproject.toml, this gate its own constants; they must be one policy."""
    lint = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["ruff"]["lint"]
    configured = {
        "lint.mccabe.max-complexity": lint["mccabe"]["max-complexity"],
        "lint.pylint.max-branches": lint["pylint"]["max-branches"],
        "lint.pylint.max-args": lint["pylint"]["max-args"],
        "lint.pylint.max-statements": lint["pylint"]["max-statements"],
    }
    assert configured == arch.COMPLEXITY_THRESHOLDS
    assert tuple(arch.COMPLEXITY_THRESHOLDS.values()) == (10, 12, 7, 50)  # ENGINEERING §13, MOD-4


@pytest.mark.usefixtures("small_thresholds")
def test_a_grandfathered_function_ruff_stops_reading_fails(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing from the measurement is "improved" only when the function measurably got smaller."""
    repo = complexity_repo(tmp_path, branches(4))
    known = {"complexity": {"src/ibb_mcp/models.py::route::C901": 5}}
    monkeypatch.setattr(arch, "COMPLEXITY_PATHS", ("scripts",))  # src/ no longer read
    result = arch.check_complexity(repo, {}, known)
    assert result.status == arch.FAIL and "no longer measures" in result.findings[0].message
    monkeypatch.setattr(arch, "COMPLEXITY_PATHS", ("src",))
    complexity_repo(tmp_path, branches(1))  # complexity 2, under the threshold of 3
    result = arch.check_complexity(repo, {}, known)
    assert result.status == arch.WARN and result.findings[0].message == "improved: 5 -> 2"
    complexity_repo(tmp_path, "X = 1\n")
    result = arch.check_complexity(repo, {}, known)
    assert result.status == arch.WARN and result.findings[0].message == "the function is gone"


# --------------------------------------------------------------------------------------
# undeclared apps, dependency sets and private imports fail closed
# --------------------------------------------------------------------------------------
def test_a_new_app_package_must_be_declared(tmp_path: pathlib.Path) -> None:
    """On 2026-09-23 a new nabiz.ops package passed layers, dependency-sets and facade-only unseen."""
    probe = "import requests\nfrom nabiz.agent.agent import X\nfrom ibb_mcp.sources.metro import Y\n"
    mods = tree(tmp_path, CLEAN | {"nabiz/ops/probe.py": probe})
    result = arch.check_layers(tmp_path, mods, {})
    assert result.status == arch.FAIL and any("undeclared app" in f.message for f in result.findings), result
    assert arch.check_dependency_sets(tmp_path, mods, {}).status == arch.FAIL  # requests is not in the nabiz set


def test_the_package_root_gets_the_core_set_only(tmp_path: pathlib.Path) -> None:
    mods = tree(tmp_path, CLEAN | {"nabiz/__init__.py": "import numpy\n"})
    assert arch.check_dependency_sets(tmp_path, mods, {}).status == arch.FAIL


def test_a_module_under_no_dependency_set_fails(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(arch, "DEPENDENCY_SETS", {k: v for k, v in arch.DEPENDENCY_SETS.items() if k != "nabiz"})
    mods = tree(tmp_path, CLEAN | {"nabiz/ops/probe.py": "X = 1\n"})
    result = arch.check_dependency_sets(tmp_path, mods, {})
    assert result.status == arch.FAIL and "under no DEPENDENCY_SETS key" in result.findings[0].message


def test_a_relative_import_of_a_private_name_fails(tmp_path: pathlib.Path) -> None:
    files = CLEAN | {
        "ibb_mcp/alerts/__init__.py": "",
        "ibb_mcp/alerts/engine.py": "def _parse_rule():\n    return 1\n",
        "ibb_mcp/alerts/rules.py": "from .engine import _parse_rule as parse_rule_again\n",
    }
    result = arch.check_private_imports(tmp_path, tree(tmp_path, files), {})
    assert result.status == arch.FAIL and "ibb_mcp.alerts.engine._parse_rule" in result.findings[0].message


def test_a_script_importing_another_scripts_private_name_fails(tmp_path: pathlib.Path) -> None:
    mods = tree(tmp_path, CLEAN)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "guardrails.py").write_text("def _python_plate_findings():\n    return []\n", encoding="utf-8")
    (tmp_path / "scripts" / "zz_probe.py").write_text("from guardrails import _python_plate_findings\n", encoding="utf-8")
    result = arch.check_private_imports(tmp_path, mods, {})
    assert result.status == arch.FAIL and result.findings[0].location == "scripts/zz_probe.py:1"


# --------------------------------------------------------------------------------------
# the real repository
# --------------------------------------------------------------------------------------
def test_the_repository_passes_its_own_fences(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(arch, "LAYER_EXCEPTIONS", REAL_EXCEPTIONS)
    baseline = json.loads((REPO_ROOT / arch.BASELINE_NAME).read_text(encoding="utf-8"))
    results = arch.run_checks(REPO_ROOT, baseline)
    assert [r.name for r in results] == [name for name, _ in arch.CHECKS]
    assert not [r for r in results if r.status == arch.FAIL], [r for r in results if r.status == arch.FAIL]


def test_every_debt_ignore_in_pyproject_is_in_the_baseline() -> None:
    """A per-file ignore is debt the gate knows by name, not a quiet way around ``make lint``."""
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ignores = config["tool"]["ruff"]["lint"]["per-file-ignores"]
    known = json.loads((REPO_ROOT / arch.BASELINE_NAME).read_text(encoding="utf-8"))["complexity"]
    for glob, rules in ignores.items():
        if glob in arch.POLICY_IGNORES:
            assert tuple(rules) == arch.POLICY_IGNORES[glob], glob
            continue
        for rule in rules:
            assert any(key.startswith(f"{glob}::") and key.endswith(f"::{rule}") for key in known), (glob, rule)


def test_the_server_package_imports_nothing_from_the_apps() -> None:
    """DECISIONS #8 in one line, independent of the layer table: it is the edge that matters most."""
    mods = arch.load_modules(REPO_ROOT)
    edges = arch.project_edges(mods)
    offending = sorted(
        (src, dst) for src, targets in edges.items() for dst in targets if arch.under(src, "ibb_mcp") and arch.under(dst, "nabiz")
    )
    assert offending == []
