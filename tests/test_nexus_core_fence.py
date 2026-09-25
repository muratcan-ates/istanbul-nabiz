"""The architecture fence around nexus_core (DECISIONS #21), each edge shown red and green.

nexus_core is a library: stdlib and pydantic, nothing from ``ibb_mcp`` or ``nabiz``. The
server never imports it; an app (the console) may.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import tomllib

import pytest
from conftest import REPO_ROOT

_spec = importlib.util.spec_from_file_location("check_architecture_nexus", REPO_ROOT / "scripts" / "check_architecture.py")
arch = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = arch
_spec.loader.exec_module(arch)

BASE = {
    "ibb_mcp/models.py": "X = 1\n",
    "ibb_mcp/tools.py": "from ibb_mcp.models import X\n",
    "nexus_core/__init__.py": "from nexus_core.signals import Signal\n",
    "nexus_core/signals.py": "import datetime\nfrom pydantic import BaseModel\nclass Signal(BaseModel):\n    pass\n",
    "nexus_core/engine.py": "from .signals import Signal\n",
    "nabiz/web/main.py": "from ibb_mcp.tools import X\nfrom nexus_core.engine import Signal\n",
}


def tree(root: pathlib.Path, files: dict[str, str]) -> dict[str, arch.Module]:
    for name, text in files.items():
        path = root / "src" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return arch.load_modules(root)


@pytest.fixture(autouse=True)
def no_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(arch, "LAYER_EXCEPTIONS", {})


def test_the_library_and_an_app_using_it_pass(tmp_path: pathlib.Path) -> None:
    mods = tree(tmp_path, BASE)
    for check in (arch.check_layers, arch.check_no_cycles, arch.check_dependency_sets, arch.check_private_imports):
        assert check(tmp_path, mods, {}).status == arch.PASS, check.__name__


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("from ibb_mcp.models import X\n", "library nexus_core imports ibb_mcp.models"),
        ("def f():\n    from ibb_mcp.tools import X\n", "library nexus_core imports ibb_mcp.tools"),
        ("from nabiz.web.main import X\n", "imports apps"),
    ],
)
def test_the_library_imports_nothing_from_the_project(tmp_path: pathlib.Path, text: str, why: str) -> None:
    result = arch.check_layers(tmp_path, tree(tmp_path, BASE | {"nexus_core/engine.py": text}), {})
    assert result.status == arch.FAIL and any(why in f.message for f in result.findings), result


def test_the_server_never_imports_the_library(tmp_path: pathlib.Path) -> None:
    files = BASE | {"ibb_mcp/tools.py": "from nexus_core.engine import Signal\n"}
    result = arch.check_layers(tmp_path, tree(tmp_path, files), {})
    assert result.status == arch.FAIL and any("imports nexus" in f.message for f in result.findings), result


@pytest.mark.parametrize("package", ["httpx", "fastapi", "openai", "mcp"])
def test_the_library_depends_on_pydantic_alone(tmp_path: pathlib.Path, package: str) -> None:
    mods = tree(tmp_path, BASE | {"nexus_core/engine.py": f"import {package}\n"})
    assert arch.check_dependency_sets(tmp_path, mods, {}).status == arch.FAIL


def test_a_private_name_inside_the_library_is_still_private(tmp_path: pathlib.Path) -> None:
    mods = tree(tmp_path, BASE | {"nexus_core/engine.py": "from nexus_core.signals import _hidden\n"})
    assert arch.check_private_imports(tmp_path, mods, {}).status == arch.FAIL


def test_the_wheel_ships_the_library() -> None:
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "src/nexus_core" in config["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
