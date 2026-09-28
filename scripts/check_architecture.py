#!/usr/bin/env python3
"""Architecture fences: import layers, cycles, dependency sets, and size/complexity ratchets.

``guardrails.py`` fences incidents that already happened. This file fences the *shape* of
the code, so that the next incident of that kind cannot happen quietly (docs/ENGINEERING.md
§13, MOD-1 to MOD-7). Every check is tied to a written decision or a measured fact, in the
order they run::

    layers           DECISIONS #8: ``ibb_mcp`` is the publishable server and imports nothing
                     from ``nabiz``. It held only "because nothing is reviewing it"; on
                     2026-09-23 the tree had four such imports (the alert engine in
                     server.py and tools.py, the tracing shim in http.py and server.py),
                     and ``import ibb_mcp.server`` loaded seven ``nabiz`` modules.
                     Inside ``ibb_mcp`` a module imports its own layer or a lower one.
                     The same pass enforces three narrower edges:
                     * sibling sources: each source module talks to one İBB service; one
                       source importing another (airquality -> metro, events -> places,
                       both for a text helper) couples two upstreams' failure modes.
                     * facade-only: DECISIONS #2, the agent is one MCP client among
                       several with no privileged path; it reaches İBB data through
                       ``ibb_mcp.tools``, and the web app through the same facade plus
                       what a composition root needs to build it.
                     * independent apps: nabiz.web, .agent, .collector, .alerts, .console
                       never import each other (the page has no LLM; the collector carries
                       the Azure SDKs), except the edges in APP_IMPORTS: the console runs
                       the agent in its chat (DECISIONS #23).
                     * libraries: nexus_core imports nothing from ibb_mcp or nabiz; the
                       console feeds it (DECISIONS #21).
    no-cycles        A cycle makes import order load-bearing and turns every split into an
                     untangling job. Zero on 2026-09-23; kept at zero, lazy imports included.
    dependency-sets  DECISIONS #8: installing ``ibb-mcp`` pulls three runtime packages. A
                     third-party import outside a package's declared set breaks that
                     promise without failing any test.
    one-meaning      Three public ``normalize_tr`` functions folded Turkish text three
                     different ways; which one a caller got depended on which module it
                     imported. Known repeats are ratcheted: they may only go.
    private-imports  ``_name`` is a module's internal. Zero cross-module imports in src/
                     and scripts/ on 2026-09-23 (tests may import privates).
    module-size      A module over the cap has more than one reason to change. Ratchet: a
                     module already over the cap may shrink, never grow, not by one line.
    class-size       Same, for classes: the ``Nabiz`` facade holds its tools in one body.
    complexity       ruff C901/PLR0912/PLR0913/PLR0915 with ``--isolated``, ``--ignore-noqa``,
                     the thresholds in COMPLEXITY_THRESHOLDS and only the policy ignores: a
                     function grandfathered with ``# noqa`` or a per-file ignore may get
                     simpler, never more complex, and a new one over the thresholds fails.
                     Isolated, because on 2026-09-23 raising a threshold or adding an
                     ``extend-exclude`` in pyproject.toml turned a real regression into
                     "improved" and passed both this gate and ``make lint``. A test holds
                     pyproject.toml's thresholds equal to these.

Usage::

    .venv/bin/python scripts/check_architecture.py              # table, exit 1 on any FAIL
    .venv/bin/python scripts/check_architecture.py --json
    .venv/bin/python scripts/check_architecture.py --only layers,no-cycles
    .venv/bin/python scripts/check_architecture.py --tighten    # lower entries that shrank
    .venv/bin/python scripts/check_architecture.py --write-baseline   # first landing only

Stdlib only; the complexity check shells out to the ruff next to this interpreter, the one
``make lint`` uses, and FAILS when it cannot find it: a gate that silently skips is not a
gate. Exit 0 when every check is PASS or WARN, 1 on any FAIL. WARN only ever means "a
baseline entry can be lowered" (``make architecture-tighten``); it never means "fine to
leave red". The one exception is sprint mode (DECISIONS #26, lane branches until 2026-10-01):
with ``NABIZ_SPRINT_MODE=1`` a failing ratchet (one-meaning, module-size, class-size, complexity)
is reported as WARN, findings included, and the run exits 0; the import fences FAIL as ever, and
the integration merge runs without the variable, where the same WARN is a FAIL again.
The baseline is ``scripts/architecture_baseline.json``; its entries are meant only to go
down. Nothing here compares it with the committed file, so raising an entry is a review matter and
needs its reason in the commit that does it.

"Code lines" exclude blank lines, comment-only lines and docstrings. Comments are free on
purpose: this repository's convention is that comments explain *why*, and a physical-line
cap would push people to delete exactly those.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tokenize
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINE_NAME = "scripts/architecture_baseline.json"
PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
#: DECISIONS #26: set to "1" on a lane branch (``make lane-gates``) until 2026-10-01, a failing ratchet
#: is reported as WARN. The import fences are contracts, not debt, and FAIL whatever the variable says.
SPRINT_MODE_ENV = "NABIZ_SPRINT_MODE"
RATCHETS = frozenset({"one-meaning", "module-size", "class-size", "complexity"})

# ---------------------------------------------------------------------------------------
# the contract
# ---------------------------------------------------------------------------------------
#: Bottom to top. A module may import modules of its own layer and of any layer below it,
#: lazily or not. Names are dotted prefixes: "ibb_mcp.sources" covers every source module.
#: The layers are what the import graph already was on 2026-09-23, not an invented target.
LAYERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "foundation",
        (
            "ibb_mcp.config",
            "ibb_mcp.models",
            "ibb_mcp.cache",
            "ibb_mcp.http",
            "ibb_mcp.reference",
            "ibb_mcp.telemetry",
            "ibb_mcp.text",
        ),
    ),
    ("sources", ("ibb_mcp.sources",)),
    (
        "domain",
        (
            "ibb_mcp.eta",
            # the ETA split (ENGINEERING §13): context <- live / schedule <- eta, all one layer
            "ibb_mcp.eta_context",
            "ibb_mcp.eta_live",
            "ibb_mcp.eta_schedule",
            "ibb_mcp.eta_profile",
            "ibb_mcp.gtfs",
            "ibb_mcp.lines",
            "ibb_mcp.metro_graph",
            "ibb_mcp.occupancy",
            "ibb_mcp.reliability",
            "ibb_mcp.timetables",
            "ibb_mcp.traffic_profile",
        ),
    ),
    (
        "services",
        (
            "ibb_mcp.routing",
            "ibb_mcp.analytics",
            "ibb_mcp.alerts",
            "ibb_mcp.accessibility",
            "ibb_mcp.equipment_signals",
            "ibb_mcp.knowledge",
            "ibb_mcp.catalog",
            # G20: the step-free rail journey; the facade delegates to it (Nabiz.accessible_journey)
            "ibb_mcp.journey_accessible",
        ),
    ),
    ("facade", ("ibb_mcp.tools",)),
    ("transport", ("ibb_mcp.server",)),
    # DECISIONS #21: the NEXUS decision library. Above the server, so ibb_mcp can never import
    # it; below the apps, so the console can. LIBRARY_IMPORTS narrows what it may import itself.
    ("nexus", ("nexus_core",)),
    ("apps", ("nabiz",)),
)

#: Libraries that import nothing from the project outside themselves, whatever their layer allows:
#: nexus_core is stdlib + pydantic, fed by the console (DECISIONS #21).
LIBRARY_IMPORTS: dict[str, tuple[str, ...]] = {"nexus_core": ()}
#: Top-level packages that are this project's own code, never third-party.
FIRST_PARTY = frozenset({"ibb_mcp", "nabiz", "nexus_core"})

#: nabiz apps are siblings: none imports another. ``nabiz.alerts`` is now only the old name
#: of ``ibb_mcp.alerts`` and stays in the list so nothing starts depending on it. A package
#: ``nabiz.<x>`` not listed here fails ``layers``: an undeclared app would otherwise pass every
#: fence below by being in none of their tables.
INDEPENDENT_APPS = ("nabiz.web", "nabiz.agent", "nabiz.collector", "nabiz.alerts", "nabiz.console")

#: The one exception to "siblings never import each other", and why (DECISIONS #23): the product
#: app ``nabiz.console`` is a composition root that runs the agent in its chat. The edge is one
#: way; nothing may import ``nabiz.console``.
APP_IMPORTS: dict[str, tuple[str, ...]] = {"nabiz.console": ("nabiz.agent",)}

#: Apps allowed any ``ibb_mcp`` module, and why. Every other app is in FACADE_ONLY; an app in
#: neither fails ``layers``.
UNRESTRICTED_APPS: dict[str, str] = {
    "nabiz.collector": "composition root: it builds a SourceContext and wires the sources directly",
    "nabiz.alerts": "the old import path of ibb_mcp.alerts: re-exports, nothing else",
}

#: The only ibb_mcp modules an app may reach, beyond its own package (DECISIONS #2). The
#: web app is a composition root: it builds the ``SourceContext`` the facade runs on and
#: configures tracing once per process, so it also sees ``config``, ``sources.base`` and
#: ``telemetry``. The collector is a composition root too and wires sources directly.
FACADE_ONLY: dict[str, tuple[str, ...]] = {
    "nabiz.agent": ("ibb_mcp.tools", "ibb_mcp.models", "ibb_mcp.http", "ibb_mcp.text", "ibb_mcp.telemetry"),
    "nabiz.web": (
        "ibb_mcp.tools",
        "ibb_mcp.models",
        "ibb_mcp.http",
        "ibb_mcp.config",
        "ibb_mcp.sources.base",
        "ibb_mcp.telemetry",
    ),
    # A composition root like the web app, which also folds Turkish text for the chat's rules.
    "nabiz.console": (
        "ibb_mcp.tools",
        "ibb_mcp.models",
        "ibb_mcp.http",
        "ibb_mcp.config",
        "ibb_mcp.sources.base",
        "ibb_mcp.telemetry",
        "ibb_mcp.text",
        # the knowledge index is a local SQLite file the console reads directly; IBB calls stay behind the facade
        "ibb_mcp.knowledge",
    ),
}

#: Import names allowed per package, beyond the standard library. CORE is pyproject
#: ``[project].dependencies``; the rest are its optional extras, by import name. The
#: longest matching prefix decides.
CORE = frozenset({"httpx", "pydantic", "mcp"})
#: Every module under src/ must fall under one key: a module that matches none fails
#: ``dependency-sets`` rather than importing whatever it likes. The bare ``nabiz`` package root
#: gets the core set only.
DEPENDENCY_SETS: dict[str, frozenset[str]] = {
    "ibb_mcp": CORE,
    "nabiz": CORE,
    # starlette and uvicorn are declared dependencies of the mcp package itself, and only
    # the HTTP transport uses them (ibb_mcp.server.build_http_app, main).
    "ibb_mcp.server": CORE | {"starlette", "uvicorn"},
    # Both imported under ImportError: opentelemetry-api arrives with mcp, the Azure
    # exporter with the `telemetry` extra. Without them tracing is a no-op, not a crash.
    "ibb_mcp.telemetry": CORE | {"opentelemetry", "azure"},
    "ibb_mcp.knowledge": CORE | {"numpy", "pypdf"},
    "nabiz.alerts": CORE,
    "nabiz.web": CORE | {"fastapi", "starlette", "uvicorn", "jinja2"},
    # nexus_core is first-party (FIRST_PARTY); the console is its composition root.
    "nabiz.console": CORE | {"fastapi", "starlette", "uvicorn"},
    # the `qr` extra, imported under ImportError: without it the stop card prints its address as text
    "nabiz.console.stop_card": CORE | {"fastapi", "starlette", "uvicorn", "segno"},
    # the `email` extra (azure-communication-email), imported only when the digest really sends (DECISIONS #38)
    "nabiz.console.email_sender": CORE | {"azure"},
    "nabiz.collector": CORE | {"azure", "deltalake", "pyarrow"},
    "nabiz.agent": CORE | {"openai", "agent_framework", "azure", "opentelemetry"},
    "nexus_core": frozenset({"pydantic"}),
}

#: Edges that break the contract today, each with the change that removes it. An entry
#: whose edge no longer exists FAILS ("delete the entry"), so this list can only shrink.
#: Empty since 2026-09-23, when the web app took setup_telemetry from ibb_mcp.telemetry.
LAYER_EXCEPTIONS: dict[tuple[str, str], str] = {}

#: Public names that may repeat across modules, and why.
ONE_MEANING_ALLOWED = {"main": "console entry point per composition root"}

MODULE_CODE_LINES_CAP = 400
CLASS_CODE_LINES_CAP = 250
CLASS_PUBLIC_METHODS_CAP = 15
COMPLEXITY_RULES = ("C901", "PLR0912", "PLR0913", "PLR0915")
#: The function-size thresholds (ENGINEERING §13, MOD-4), passed to ruff by this script, never
#: read from pyproject.toml; ``tests/test_check_architecture.py`` holds the two equal, so
#: ``make lint`` measures what this gate measures.
COMPLEXITY_THRESHOLDS: dict[str, int] = {
    "lint.mccabe.max-complexity": 10,
    "lint.pylint.max-branches": 12,
    "lint.pylint.max-args": 7,
    "lint.pylint.max-statements": 50,
}
RULE_THRESHOLD = {
    "C901": "lint.mccabe.max-complexity",
    "PLR0912": "lint.pylint.max-branches",
    "PLR0913": "lint.pylint.max-args",
    "PLR0915": "lint.pylint.max-statements",
}
#: pyproject.toml's target-version; --isolated would otherwise parse 3.12 syntax as an error.
TARGET_VERSION = "py312"
#: What ``make lint`` and CI lint, so a finding here is a finding there.
COMPLEXITY_PATHS = ("src", "scripts", "tests", ".github/scripts", "eval")
#: The only per-file ignores the complexity check honours: policy, not debt. Every other
#: per-file ignore in pyproject.toml is debt, and debt is measured through it.
POLICY_IGNORES: dict[str, tuple[str, ...]] = {
    # Test data builders take one keyword per model field on purpose.
    "tests/**": ("PLR0913",),
}


@dataclass(frozen=True)
class Finding:
    location: str
    message: str


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    findings: list[Finding] = field(default_factory=list)


# ---------------------------------------------------------------------------------------
# measuring
# ---------------------------------------------------------------------------------------
@dataclass
class Module:
    name: str
    path: pathlib.Path
    tree: ast.Module
    source: str
    #: (target, lineno) for every import, project and third-party, module-level and lazy.
    imports: list[tuple[str, int]] = field(default_factory=list)


def load_modules(repo: pathlib.Path) -> dict[str, Module]:
    """Every module under ``src/``, keyed by dotted name, with its imports resolved."""
    src = repo / "src"
    mods: dict[str, Module] = {}
    for path in sorted(src.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        parts = list(path.relative_to(src).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        source = path.read_text(encoding="utf-8")
        mods[".".join(parts)] = Module(".".join(parts), path, ast.parse(source), source)
    for mod in mods.values():
        is_pkg = mod.path.name == "__init__.py"
        for node in ast.walk(mod.tree):
            if isinstance(node, ast.Import):
                mod.imports += [(alias.name, node.lineno) for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    pkg = mod.name.split(".") if is_pkg else mod.name.split(".")[:-1]
                    pkg = pkg[: len(pkg) - node.level + 1]
                    base = ".".join(pkg + ([node.module] if node.module else []))
                else:
                    base = node.module or ""
                for alias in node.names:
                    full = f"{base}.{alias.name}"
                    # `from pkg import submodule` depends on the submodule, not on pkg/__init__.
                    mod.imports.append((full if full in mods else base, node.lineno))
    return mods


def resolve(name: str, mods: dict[str, Module]) -> str | None:
    parts = name.split(".")
    for i in range(len(parts), 0, -1):
        if ".".join(parts[:i]) in mods:
            return ".".join(parts[:i])
    return None


def project_edges(mods: dict[str, Module]) -> dict[str, dict[str, int]]:
    edges: dict[str, dict[str, int]] = defaultdict(dict)
    for mod in mods.values():
        for target, lineno in mod.imports:
            dst = resolve(target, mods)
            if dst and dst != mod.name:
                edges[mod.name].setdefault(dst, lineno)
    return edges


def under(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


def layer_of(name: str) -> int | None:
    for index, (_, prefixes) in enumerate(LAYERS):
        if any(under(name, prefix) for prefix in prefixes):
            return index
    return None


def code_lines(source: str, first: int = 1, last: int | None = None) -> int:
    """Lines holding code between ``first`` and ``last``: no blank, comment-only or docstring lines."""
    tree = ast.parse(source)
    doc: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) and body:
            head = body[0]
            if isinstance(head, ast.Expr) and isinstance(head.value, ast.Constant) and isinstance(head.value.value, str):
                doc.update(range(head.lineno, (head.end_lineno or head.lineno) + 1))
    skip = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}
    lines: set[int] = set()
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type not in skip:
            lines.update(n for n in range(tok.start[0], tok.end[0] + 1) if n not in doc)
    return len({n for n in lines if n >= first and (last is None or n <= last)})


def rel(repo: pathlib.Path, path: pathlib.Path) -> str:
    return path.resolve().relative_to(repo.resolve()).as_posix()


# ---------------------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------------------
def edge_violation(src: str, dst: str) -> str | None:
    """Why ``src`` may not import ``dst``, or None when the edge is allowed."""
    ls, ld = layer_of(src), layer_of(dst)
    if ls is not None and ld is not None and ld > ls:
        return f"{LAYERS[ls][0]} imports {LAYERS[ld][0]} ({dst})"
    if under(src, "ibb_mcp.sources") and under(dst, "ibb_mcp.sources") and dst != "ibb_mcp.sources.base":
        return f"source imports sibling source {dst}"
    library = next((lib for lib in LIBRARY_IMPORTS if under(src, lib)), None)
    if library and not under(dst, library) and not any(under(dst, a) for a in LIBRARY_IMPORTS[library]):
        return f"library {library} imports {dst}; it is fed by its caller, never the other way"
    app_s = next((app for app in INDEPENDENT_APPS if under(src, app)), None)
    app_d = next((app for app in INDEPENDENT_APPS if under(dst, app)), None)
    if app_s and app_d and app_s != app_d and app_d not in APP_IMPORTS.get(app_s, ()):
        return f"{app_s} imports sibling app {app_d}"
    allowed = next((v for k, v in FACADE_ONLY.items() if under(src, k)), None)
    if allowed is not None and under(dst, "ibb_mcp") and not any(under(dst, a) for a in allowed):
        return f"{src} bypasses the ibb_mcp.tools facade ({dst})"
    return None


def undeclared_apps(mods: dict[str, Module]) -> list[Finding]:
    """Apps the fences do not know: a nabiz.<x> package outside INDEPENDENT_APPS, or an app whose
    access to ibb_mcp is declared nowhere."""
    apps = {".".join(name.split(".")[:2]) for name in mods if under(name, "nabiz") and name != "nabiz"}
    findings = [
        Finding(app, "undeclared app: add it to INDEPENDENT_APPS, and to FACADE_ONLY or UNRESTRICTED_APPS")
        for app in sorted(apps - set(INDEPENDENT_APPS))
    ]
    findings += [
        Finding(app, "its ibb_mcp access is declared nowhere: add it to FACADE_ONLY or UNRESTRICTED_APPS")
        for app in INDEPENDENT_APPS
        if app not in FACADE_ONLY and app not in UNRESTRICTED_APPS
    ]
    return findings


def check_layers(repo: pathlib.Path, mods: dict[str, Module], baseline: dict) -> CheckResult:
    """Every project import points down the layer stack, and apps stay out of each other."""
    edges = project_edges(mods)
    broken = {(s, d): (ln, why) for s, ts in edges.items() for d, ln in ts.items() if (why := edge_violation(s, d))}
    findings = [
        Finding(f"{rel(repo, mods[s].path)}:{ln}", why)
        for (s, d), (ln, why) in sorted(broken.items())
        if (s, d) not in LAYER_EXCEPTIONS
    ]
    findings += [
        Finding("LAYER_EXCEPTIONS", f"stale exception {s} -> {d}: the edge is gone, delete the entry")
        for s, d in sorted(set(LAYER_EXCEPTIONS) - set(broken))
    ]
    findings += [Finding(m, "module is in no layer; add it to LAYERS") for m in sorted(mods) if "." in m and layer_of(m) is None]
    findings += undeclared_apps(mods)
    if findings:
        return CheckResult("layers", FAIL, f"{len(findings)} import(s) break the layer contract", findings)
    total = sum(map(len, edges.values()))
    return CheckResult("layers", PASS, f"{total} project imports obey the contract; {len(LAYER_EXCEPTIONS)} dated exception(s)")


def _pop_component(stack: list[str], on_stack: set[str], root: str) -> list[str]:
    """Pop Tarjan's stack down to ``root``: one strongly connected component."""
    component = stack[stack.index(root) :]
    del stack[stack.index(root) :]
    on_stack.difference_update(component)
    return sorted(component)


def strongly_connected(graph: dict[str, set[str]]) -> list[list[str]]:
    """Tarjan's algorithm; every component with more than one module."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    cycles: list[list[str]] = []

    def visit(v: str) -> None:
        index[v] = low[v] = len(index)
        stack.append(v)
        on_stack.add(v)
        for w in sorted(graph.get(v, ())):
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v] and len(component := _pop_component(stack, on_stack, v)) > 1:
            cycles.append(component)

    for v in sorted(graph):
        if v not in index:
            visit(v)
    return cycles


def check_no_cycles(repo: pathlib.Path, mods: dict[str, Module], baseline: dict) -> CheckResult:
    """No strongly connected component larger than one module, lazy imports included."""
    cycles = strongly_connected({m: set(t) for m, t in project_edges(mods).items()})
    if cycles:
        found = [Finding(" <-> ".join(c), "cycle") for c in cycles]
        return CheckResult("no-cycles", FAIL, f"{len(cycles)} import cycle(s)", found)
    return CheckResult("no-cycles", PASS, f"{len(mods)} modules, no import cycle")


def check_dependency_sets(repo: pathlib.Path, mods: dict[str, Module], baseline: dict) -> CheckResult:
    """Third-party imports stay inside the set the package's install extra declares."""
    std = set(sys.stdlib_module_names) | {"__future__"}
    findings = []
    for mod in mods.values():
        key = next((k for k in sorted(DEPENDENCY_SETS, key=len, reverse=True) if under(mod.name, k)), None)
        if key is None:
            findings.append(Finding(rel(repo, mod.path), f"{mod.name} is under no DEPENDENCY_SETS key; declare its set"))
            continue
        for target, lineno in mod.imports:
            top = target.split(".")[0]
            if top in std or top in FIRST_PARTY or top in DEPENDENCY_SETS[key]:
                continue
            findings.append(Finding(f"{rel(repo, mod.path)}:{lineno}", f"{key} imports undeclared third-party {top!r}"))
    if findings:
        return CheckResult("dependency-sets", FAIL, f"{len(findings)} undeclared third-party import(s)", findings)
    return CheckResult("dependency-sets", PASS, "every third-party import is in its package's declared set")


def public_definitions(repo: pathlib.Path, mods: dict[str, Module]) -> dict[str, list[str]]:
    """Public top-level function and class names, and where each is *defined*.

    A re-export (an import, or an assignment such as ``Place = WatchedPlace``) is not a
    definition: it names the same object, so it cannot mean something else.
    """
    where: dict[str, list[str]] = defaultdict(list)
    for mod in mods.values():
        if mod.path.name == "__init__.py":
            continue
        for node in mod.tree.body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and not node.name.startswith("_"):
                where[node.name].append(f"{rel(repo, mod.path)}:{node.lineno}")
    return where


def check_one_meaning(repo: pathlib.Path, mods: dict[str, Module], baseline: dict) -> CheckResult:
    """A public top-level name is defined in one module. Ratchet: known repeats may only go."""
    repeats = {n: locs for n, locs in public_definitions(repo, mods).items() if len(locs) > 1 and n not in ONE_MEANING_ALLOWED}
    known = baseline.get("one_meaning", {})
    findings = [
        Finding(", ".join(locs), f"public name {n!r} defined {len(locs)} times")
        for n, locs in sorted(repeats.items())
        if len(locs) > known.get(n, 1)
    ]
    if findings:
        return CheckResult("one-meaning", FAIL, f"{len(findings)} new repeated public name(s)", findings)
    shrunk = sorted(n for n, count in known.items() if len(repeats.get(n, [])) < count)
    if shrunk:
        return CheckResult("one-meaning", WARN, f"baseline can be lowered (run --tighten): {', '.join(shrunk)}")
    return CheckResult("one-meaning", PASS, f"{len(repeats)} known repeat(s), none new")


def absolute_module(node: ast.ImportFrom, name: str, is_pkg: bool) -> str:
    """The module an ``ImportFrom`` names, relative imports resolved the way ``load_modules`` does."""
    if not node.level:
        return node.module or ""
    pkg = name.split(".") if is_pkg else name.split(".")[:-1]
    pkg = pkg[: len(pkg) - node.level + 1]
    return ".".join(pkg + ([node.module] if node.module else []))


def private_names(tree: ast.Module, name: str, is_pkg: bool, is_project: Callable[[str], bool]) -> Iterable[tuple[int, str]]:
    """``(line, "module._name")`` for every ``_private`` name imported from another project module."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and is_project(module := absolute_module(node, name, is_pkg)):
            for alias in node.names:
                if alias.name.startswith("_") and not alias.name.startswith("__"):
                    yield node.lineno, f"{module}.{alias.name}"


def check_private_imports(repo: pathlib.Path, mods: dict[str, Module], baseline: dict) -> CheckResult:
    """No module in src/ or scripts/ imports another module's ``_private`` name, relative imports included."""
    scripts = sorted(p for p in (repo / "scripts").rglob("*.py") if "__pycache__" not in p.parts)
    sibling_scripts = {p.stem for p in scripts if p.parent == repo / "scripts"}

    def in_src(module: str) -> bool:
        return module.split(".")[0] in FIRST_PARTY

    def in_scripts(module: str) -> bool:  # scripts import each other as top-level modules
        return in_src(module) or module.split(".")[0] in sibling_scripts

    sources = [(m.path, m.tree, m.name, m.path.name == "__init__.py", in_src) for m in mods.values()]
    sources += [(p, ast.parse(p.read_text(encoding="utf-8")), p.stem, False, in_scripts) for p in scripts]
    findings = [
        Finding(f"{rel(repo, path)}:{line}", f"imports private {what}")
        for path, tree, name, is_pkg, is_project in sources
        for line, what in private_names(tree, name, is_pkg, is_project)
    ]
    if findings:
        return CheckResult("private-imports", FAIL, f"{len(findings)} private import(s)", findings)
    return CheckResult("private-imports", PASS, "no cross-module import of a _private name")


def _ratchet(name: str, measured: dict[str, int], cap: int, known: dict[str, int], unit: str) -> CheckResult:
    findings, lower = [], []
    for key, value in sorted(measured.items()):
        limit = max(cap, known.get(key, cap))
        if value > limit:
            grew = f"grew from {known[key]}" if key in known else f"is over the cap of {cap}"
            findings.append(Finding(key, f"{value} {unit}; {grew}. Split it (split plan, ENGINEERING §13) or shrink it"))
        elif key in known and value < known[key]:
            lower.append(f"{key} {known[key]}->{value}")
    stale = sorted(k for k in known if k not in measured)
    if findings:
        return CheckResult(name, FAIL, f"{len(findings)} over budget", findings)
    if lower or stale:
        return CheckResult(name, WARN, f"baseline can be lowered (run --tighten): {', '.join(lower + stale)}")
    over = sum(1 for value in measured.values() if value > cap)
    return CheckResult(name, PASS, f"cap {cap} {unit}; {over} grandfathered, none grew")


def measure_module_sizes(repo: pathlib.Path, mods: dict[str, Module]) -> dict[str, int]:
    return {rel(repo, m.path): code_lines(m.source) for m in mods.values()}


def check_module_size(repo: pathlib.Path, mods: dict[str, Module], baseline: dict) -> CheckResult:
    """A module holds at most MODULE_CODE_LINES_CAP code lines; grandfathered ones never grow."""
    known = baseline.get("module_code_lines", {})
    return _ratchet("module-size", measure_module_sizes(repo, mods), MODULE_CODE_LINES_CAP, known, "code lines")


def measure_classes(repo: pathlib.Path, mods: dict[str, Module]) -> tuple[dict[str, int], dict[str, int]]:
    sizes, methods = {}, {}
    for m in mods.values():
        for node in m.tree.body:
            if isinstance(node, ast.ClassDef):
                key = f"{rel(repo, m.path)}::{node.name}"
                sizes[key] = code_lines(m.source, node.lineno, node.end_lineno)
                methods[key] = sum(
                    isinstance(b, ast.FunctionDef | ast.AsyncFunctionDef) and not b.name.startswith("_") for b in node.body
                )
    return sizes, methods


def check_class_size(repo: pathlib.Path, mods: dict[str, Module], baseline: dict) -> CheckResult:
    """No god object: a class stays under both caps; grandfathered classes never grow."""
    sizes, methods = measure_classes(repo, mods)
    lines = _ratchet("class-size", sizes, CLASS_CODE_LINES_CAP, baseline.get("class_code_lines", {}), "code lines")
    count = _ratchet("class-size", methods, CLASS_PUBLIC_METHODS_CAP, baseline.get("class_public_methods", {}), "public methods")
    worst = min((lines, count), key=lambda r: {FAIL: 0, WARN: 1, PASS: 2}[r.status])
    return CheckResult("class-size", worst.status, f"{lines.summary} | {count.summary}", lines.findings + count.findings)


def _qualified_names(tree: ast.Module) -> dict[int, str]:
    """``{def line: "Class.method"}`` for every function, nested ones included."""
    names: dict[int, str] = {}

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                qualified = f"{prefix}{child.name}"
                if not isinstance(child, ast.ClassDef):
                    names[child.lineno] = qualified
                walk(child, qualified + ".")
            else:
                walk(child, prefix)

    walk(tree, "")
    return names


def find_ruff() -> str:
    ruff = shutil.which("ruff", path=str(pathlib.Path(sys.executable).parent)) or shutil.which("ruff")
    if ruff is None:
        raise RuntimeError("ruff not found next to this interpreter or on PATH; `make install` provides it")
    return ruff


def run_ruff(repo: pathlib.Path, paths: list[str], thresholds: dict[str, int]) -> list[dict]:
    """ruff's JSON findings for the complexity rules, configured by this script alone."""
    policy = ", ".join(f'"{glob}" = [{", ".join(repr(r) for r in rules)}]' for glob, rules in POLICY_IGNORES.items())
    overrides = [f"{key} = {value}" for key, value in thresholds.items()]
    overrides += [f'target-version = "{TARGET_VERSION}"', f"lint.per-file-ignores = {{{policy}}}"]
    command = [find_ruff(), "check", *paths, "--isolated", "--select", ",".join(COMPLEXITY_RULES), "--ignore-noqa"]
    command += [arg for override in overrides for arg in ("--config", override)]
    command += ["--output-format", "json", "--no-cache", "--exit-zero"]
    out = subprocess.run(command, cwd=repo, capture_output=True, text=True, check=True, timeout=120)
    items = json.loads(out.stdout or "[]")
    unreadable = [f"{item['filename']}: {item['message']}" for item in items if item.get("code") not in COMPLEXITY_RULES]
    if unreadable:
        raise RuntimeError(f"ruff could not measure: {'; '.join(unreadable)}")
    return items


def measure_all(repo: pathlib.Path, paths: list[str] | None = None) -> dict[str, int]:
    """``{"path::Qualified.name::RULE": value}`` for every function ruff sees, whatever its size.

    ruff runs ``--isolated`` with every threshold at 0, so it reports each function's exact
    values (a function with no argument or no branch is simply absent for that rule), and the
    per-file ignores are replaced by :data:`POLICY_IGNORES`. A ``# noqa`` or a per-file ignore
    hides nothing here, and nothing in pyproject.toml can exclude a file or move a threshold.
    """
    paths = paths if paths is not None else [p for p in COMPLEXITY_PATHS if (repo / p).exists()]
    result: dict[str, int] = {}
    trees: dict[pathlib.Path, dict[int, str]] = {}
    if not paths:  # ruff with no path would read the whole working directory
        return result
    for item in run_ruff(repo, paths, dict.fromkeys(COMPLEXITY_THRESHOLDS, 0)):
        path = pathlib.Path(item["filename"]).resolve()
        if path not in trees:
            trees[path] = _qualified_names(ast.parse(path.read_text(encoding="utf-8")))
        line = item["location"]["row"]
        name = trees[path].get(line, f"line{line}")
        value = int(item["message"].rsplit("(", 1)[1].split(" ", 1)[0])
        result[f"{rel(repo, path)}::{name}::{item['code']}"] = value
    return result


def over_threshold(values: dict[str, int], thresholds: dict[str, int] | None = None) -> dict[str, int]:
    """The findings ``make lint`` would report: values above :data:`COMPLEXITY_THRESHOLDS`."""
    thresholds = COMPLEXITY_THRESHOLDS if thresholds is None else thresholds
    return {k: v for k, v in values.items() if v > thresholds[RULE_THRESHOLD[k.rsplit("::", 1)[1]]]}


def measure_complexity(repo: pathlib.Path) -> dict[str, int]:
    """Every function over a threshold, with ``noqa`` and debt ignores switched off."""
    return over_threshold(measure_all(repo))


def function_exists(repo: pathlib.Path, key: str) -> bool:
    path_name, name, _ = key.rsplit("::", 2)
    path = repo / path_name
    return path.is_file() and name in _qualified_names(ast.parse(path.read_text(encoding="utf-8"))).values()


def check_complexity(repo: pathlib.Path, mods: dict[str, Module], baseline: dict) -> CheckResult:
    """No new function over the thresholds; grandfathered functions never get worse, and never vanish unmeasured."""
    known = baseline.get("complexity", {})
    everything = measure_all(repo)
    measured = over_threshold(everything)
    findings = [Finding(k, f"{v}: new violation of the threshold") for k, v in sorted(measured.items()) if k not in known]
    findings += [
        Finding(k, f"{v}: was {known[k]}; grandfathered code may get simpler, never more complex")
        for k, v in sorted(measured.items())
        if k in known and v > known[k]
    ]
    better = []
    for key in sorted(k for k in known if measured.get(k, 0) < known[k]):
        rule = key.rsplit("::", 1)[1]
        if key in everything or (rule in {"PLR0912", "PLR0913"} and function_exists(repo, key)):
            better.append(Finding(key, f"improved: {known[key]} -> {everything.get(key, 0)}"))
        elif function_exists(repo, key):
            # Every function has a complexity and a statement count; ruff not reporting one means
            # it no longer reads the file.
            findings.append(Finding(key, "the function exists but ruff no longer measures it: excluded?"))
        else:
            better.append(Finding(key, "the function is gone"))
    if findings:
        return CheckResult("complexity", FAIL, f"{len(findings)} complexity regression(s)", findings)
    if better:
        return CheckResult("complexity", WARN, f"{len(better)} baseline entr(ies) improved; run --tighten", better)
    return CheckResult("complexity", PASS, f"{len(measured)} grandfathered finding(s), none worse, none new")


CHECKS: tuple[tuple[str, Callable[[pathlib.Path, dict[str, Module], dict], CheckResult]], ...] = (
    ("layers", check_layers),
    ("no-cycles", check_no_cycles),
    ("dependency-sets", check_dependency_sets),
    ("one-meaning", check_one_meaning),
    ("private-imports", check_private_imports),
    ("module-size", check_module_size),
    ("class-size", check_class_size),
    ("complexity", check_complexity),
)

BASELINE_SECTIONS = ("module_code_lines", "class_code_lines", "class_public_methods", "one_meaning", "complexity")
BASELINE_COMMENT = (
    "Written by scripts/check_architecture.py. Entries may only go down (make architecture-tighten); "
    "raising one needs its reason in the commit that does it."
)


def current_baseline(repo: pathlib.Path, mods: dict[str, Module]) -> dict:
    sizes, methods = measure_classes(repo, mods)
    return {
        "_comment": BASELINE_COMMENT,
        "module_code_lines": {k: v for k, v in sorted(measure_module_sizes(repo, mods).items()) if v > MODULE_CODE_LINES_CAP},
        "class_code_lines": {k: v for k, v in sorted(sizes.items()) if v > CLASS_CODE_LINES_CAP},
        "class_public_methods": {k: v for k, v in sorted(methods.items()) if v > CLASS_PUBLIC_METHODS_CAP},
        "one_meaning": {
            k: len(v) for k, v in sorted(public_definitions(repo, mods).items()) if len(v) > 1 and k not in ONE_MEANING_ALLOWED
        },
        "complexity": dict(sorted(measure_complexity(repo).items())),
    }


def tighten(old: dict, new: dict) -> dict:
    """Keep only entries that still exist, each at min(old, new). Never raises or adds one."""
    out = {"_comment": old.get("_comment", BASELINE_COMMENT)}
    for section in BASELINE_SECTIONS:
        before, now = old.get(section, {}), new.get(section, {})
        out[section] = {k: min(v, before[k]) for k, v in sorted(now.items()) if k in before}
    return out


def sprint_mode() -> bool:
    return os.environ.get(SPRINT_MODE_ENV) == "1"


def suspend(result: CheckResult) -> CheckResult:
    """Sprint mode: a failing ratchet is a WARN the lane carries to the merge; its findings stay on screen."""
    if result.status == FAIL:
        result.status = WARN
        result.summary = f"{result.summary}; sprint mode ({SPRINT_MODE_ENV}=1), FAILS at the integration merge"
    return result


def run_checks(repo: pathlib.Path, baseline: dict, only: set[str] | None = None) -> list[CheckResult]:
    mods = load_modules(repo)
    sprint = sprint_mode()
    results = []
    for name, check in CHECKS:
        if only and name not in only:
            continue
        try:
            result = check(repo, mods, baseline)
        except Exception as exc:  # noqa: BLE001 - a broken check must be loud, never a silent pass
            results.append(CheckResult(name, FAIL, f"the check itself raised {type(exc).__name__}", [Finding(name, repr(exc))]))
            continue
        results.append(suspend(result) if sprint and name in RATCHETS else result)
    return results


def print_table(results: list[CheckResult]) -> None:
    width = max(len(r.name) for r in results)
    for r in results:
        print(f"{r.name.ljust(width)}  {r.status:4}  {r.summary}")
        for finding in r.findings:
            print(f"{' ' * width}        - {finding.location}: {finding.message}")
    failed = sum(r.status == FAIL for r in results)
    print(f"\n{len(results)} checks, {failed} failed")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_architecture", description=__doc__.split("\n", 1)[0])
    parser.add_argument("--repo", type=pathlib.Path, default=ROOT)
    parser.add_argument("--baseline", type=pathlib.Path, default=None, help=f"default: {BASELINE_NAME}")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--only", help="comma-separated check names")
    parser.add_argument("--write-baseline", action="store_true", help="record today's debt (first landing only)")
    parser.add_argument("--tighten", action="store_true", help="lower entries that improved; never raises one")
    args = parser.parse_args(list(argv) if argv is not None else None)
    repo = args.repo.resolve()
    path = args.baseline or repo / BASELINE_NAME
    baseline = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    if args.write_baseline or args.tighten:
        new = current_baseline(repo, load_modules(repo))
        data = tighten(baseline, new) if args.tighten else new
        path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(repo) if path.is_relative_to(repo) else path.name}")
        return 0

    results = run_checks(repo, baseline, set(args.only.split(",")) if args.only else None)
    if args.json:
        rows = [r.__dict__ | {"findings": [f.__dict__ for f in r.findings]} for r in results]
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        print_table(results)
    return 1 if any(r.status == FAIL for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
