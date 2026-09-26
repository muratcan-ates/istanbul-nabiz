#!/usr/bin/env python3
"""Automated fences around the failure modes this repository has *already* hit.

Every check below is a regression test for a real incident, not a hypothetical. The
project keeps a written record of each one (``docs/NABIZ.md`` §1–§2, ``DECISIONS.md``),
and a written rule that nobody re-reads is a rule that comes back. So each rule that cost
us time once is encoded here and run by CI on every push.

The incidents, in the order the checks appear::

    no-plate              İETT's fleet feed ships a number plate (``Plaka``). Decision 7
                          drops it at the parsing boundary. A single ``raw["Plaka"]``
                          anywhere downstream would put a personal identifier into a
                          public lake — a KVKK problem, not a style problem.
    fixture-plates-synthetic
                          The recorded fleet fixtures are published with the code, so a
                          real plate in them is the same leak by another route. Every
                          ``Plaka`` under ``tests/fixtures`` must be synthetic: ``00 ...``,
                          a province code that does not exist. A recorded plate outlived
                          that scrub as the eval harness's example, so every other file
                          is read for a plate-shaped value with a real province code.
    mcp-schemas           The result-rendering decorator in ``server.py`` once lost
                          ``functools.wraps``. The MCP SDK derives each tool's JSON
                          schema from the wrapped signature, so all twelve tools
                          advertised ``(*args, **kwargs)`` and the SDK rejected every
                          call. Nothing in-process noticed; only a real client did.
    no-raw-ibb-calls      ``api.ibb.gov.tr`` 503s *every* İBB service after ~15 rapid
                          requests, and İETT documents 100 requests/hour for the whole
                          project. One module reaching for ``httpx`` directly spends a
                          budget shared with every other consumer of this public data.
    csv-truncation        İBB's GTFS ``stop_times.csv`` was exported through Excel and
                          stops dead at 1,048,575 data rows — only 14% of trips present, 86% missing,
                          500T absent entirely. It parses perfectly. The ZIP's
                          ``stop_times.txt`` (6.16M rows) is the complete file.
    coordinate-sanity     GTFS coordinates arrive with thousands separators
                          (``410.191.700.005.564`` = ``41.0191700005564``).
                          ``repair_coordinate`` fixes them and rejects what it cannot
                          fix; four stops still land outside İstanbul and are dropped.
    no-secrets            The repository is public (MIT, data CC BY 4.0). A key pushed
                          once is a key leaked forever.
    no-personal-data      A tracked collector log once carried local paths, and 19
                          early commits carry a personal e-mail address. The history is
                          public and permanent; the tree at least must stay clean.
    no-ai-attribution     The owner is the author (AGENTS.md §2). A ``Co-Authored-By``
                          trailer or a "Generated with" footer pasted into a file puts
                          an assistant's name on work it did not answer for.
    fixture-freshness     The offline suite and the demo both run on recorded İBB
                          responses. Stale fixtures make a green suite meaningless, but
                          re-capturing spends the shared gateway budget — so this warns
                          and never fails.
    no-fabricated-metrics README §Results promises numbers copied from the file each row
                          names. §1.5 forbids inventing a metric. Every number in a
                          Result cell must be written in that row's evidence file.
    agent-rules-links     The previous project's agent instructions pointed at a long-stale
                          branch, and agents followed them (docs/ENGINEERING.md AI-1).
                          Every repository path and ``make`` target that AGENTS.md,
                          CLAUDE.md and CONTRIBUTING.md name must exist, and every
                          relative link in any tracked Markdown file must resolve.
    no-azure-ids          A subscription, tenant or client id pasted from `az` or `azd` output
                          into a tracked file is permanent public history. Fails on a GUID on the
                          same line as subscription, tenant, clientId, principalId, objectId or
                          aadapp; the public built-in role definitions in infra/ are listed with
                          their reason.

None of them needs the network or git history. The file list comes from the git index
when there is one (``git ls-files``: what is tracked plus what ``git add`` would pick up)
and from a filtered directory walk otherwise, so the script also runs on a source copy;
``--files-from`` hands it an exact list instead (``make ci-local`` does).

Usage::

    .venv/bin/python scripts/guardrails.py            # table, exit 1 on any FAIL
    .venv/bin/python scripts/guardrails.py --json     # machine-readable
    .venv/bin/python scripts/guardrails.py --only no-plate,mcp-schemas
    .venv/bin/python scripts/guardrails.py --list

Exit status is 0 when every check is PASS, WARN or SKIP, and 1 when any check FAILs.
A WARN never fails the build; it is a thing to look at, not a thing to block on.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import csv
import datetime as dt
import json
import math
import pathlib
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"

#: Excel refuses to open more than 1,048,576 rows, header included. A CSV that stops on
#: exactly that boundary went through a spreadsheet, whatever its extension claims.
EXCEL_MAX_DATA_ROWS = 1_048_575

#: İstanbul's bounding box, same values ``ibb_mcp.models`` uses. Duplicated on purpose:
#: a guardrail that imports the constant it is checking cannot catch someone widening it.
LAT_RANGE = (40.7, 41.7)
LON_RANGE = (27.9, 29.95)

IBB_HOSTS = ("api.ibb.gov.tr", "data.ibb.gov.tr")

TEXT_SUFFIXES = {
    ".py", ".js", ".ts", ".json", ".jsonl", ".md", ".yml", ".yaml", ".toml", ".cfg", ".ini",
    ".sh", ".sql", ".kql", ".bicep", ".css", ".html", ".xml", ".txt", ".csv", ".example", ".log",
}

#: What a directory walk skips when there is no git index to ask. These are the gitignored
#: trees that exist in a working checkout; none of them is published, so none can leak.
WALK_SKIP_DIRS = {
    ".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", ".azure",
    "lake", "gtfs", "logs", "reports", "dist", "build",
}
WALK_SKIP_FILES = {".env", ".DS_Store"}

#: Set by ``--files-from``: the exact list of repository-relative paths to check, instead of
#: asking git or walking. ``make ci-local`` passes the list it copied, because its copy has no
#: git index, and the walk skips a ``logs/`` directory that a tracked log once lived in: CI
#: checked one file more than ci-local did.
FILES_FROM: list[str] | None = None


@dataclass(frozen=True)
class Finding:
    """One concrete violation: where it is, and what is wrong with it."""

    location: str
    message: str


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.status == FAIL


# ---------------------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------------------
def tracked_files(repo: pathlib.Path) -> list[pathlib.Path]:
    """The files a push would publish: tracked, plus new files ``git add`` would pick up.

    ``-co --exclude-standard`` rather than plain ``ls-files`` so a file a lane has just
    written is checked before it is committed, not after it is public. ``data/lake/``,
    ``data/reference/gtfs/`` and ``.venv/`` are gitignored and hold hundreds of megabytes,
    so walking the tree instead would be both slow and wrong: an ignored file cannot leak.

    Git is only asked when ``repo`` is itself a checkout (``.git`` is a directory, or a
    file in a linked worktree); otherwise a temporary copy inside some unrelated repository
    would be answered from that repository's index. The fallback walk covers a source
    tarball, the clean copy ``make ci-local`` builds, and the tests.

    Untracked files pass the same directory filter as the walk. CI runs pytest before this
    script, and ``reports/junit.xml`` is untracked output whose test ids quote the very
    trailers and addresses the test files feed these checks.
    """

    def publishable(name: str) -> bool:
        path = pathlib.PurePosixPath(name)
        return path.name not in WALK_SKIP_FILES and not WALK_SKIP_DIRS.intersection(path.parts)

    if FILES_FROM is not None:
        return sorted(repo / name for name in set(FILES_FROM) if (repo / name).is_file())
    if (repo / ".git").exists():
        try:
            listed: set[str] = set()
            for flags, keep in ((["-c"], None), (["-o", "--exclude-standard"], publishable)):
                out = subprocess.run(
                    ["git", "-C", str(repo), "ls-files", *flags, "-z"],
                    capture_output=True, check=True, text=True, timeout=60,
                )
                listed.update(n for n in out.stdout.split("\0") if n and (keep is None or keep(n)))
            # -c lists index entries whose file has been deleted from the working tree.
            found = [repo / n for n in sorted(listed) if (repo / n).is_file()]
            if found:
                return found
        except (OSError, subprocess.SubprocessError):
            pass
    return sorted(p for p in repo.rglob("*") if p.is_file() and publishable(p.relative_to(repo).as_posix()))


def read_text(path: pathlib.Path) -> str | None:
    """Decode a file as UTF-8, or return None when it is binary or unreadable."""
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def rel(repo: pathlib.Path, path: pathlib.Path) -> str:
    try:
        return path.relative_to(repo).as_posix()
    except ValueError:
        return str(path)


def is_text_candidate(path: pathlib.Path) -> bool:
    """Known text suffixes, plus suffix-less files such as ``Makefile`` and ``LICENSE``."""
    return path.suffix in TEXT_SUFFIXES or path.suffix == ""


def count_lines(path: pathlib.Path) -> int:
    """Count newline-terminated lines without holding the file in memory (26 MB CSVs)."""
    total = 0
    trailing_newline = True
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            total += chunk.count(b"\n")
            trailing_newline = chunk.endswith(b"\n")
    return total if trailing_newline else total + 1


# ---------------------------------------------------------------------------------------
# 1. no-plate
# ---------------------------------------------------------------------------------------
#: ``plate`` bounded by non-identifier characters, so ``template``, ``boilerplate`` and
#: ``plateau`` do not match, and neither does the Turkish inflection ``plakası`` — which
#: only ever appears inside a sentence explaining that we do not keep plates.
PLATE_TOKEN = re.compile(r"(?<![A-Za-z0-9_])(plaka|plate|plate_no|plateno|numberplate|license_plate)(?![A-Za-z0-9_])", re.I)

#: Files allowed to say the word. ``models.py`` documents the drop and is where it happens;
#: the tests assert the absence, and ``tests/fixtures`` has its own, stricter check below.
PLATE_EXEMPT = ("src/ibb_mcp/models.py", "tests/")

#: A plate-shaped *key* in a data or config file. The word boundary matters: without it
#: ``template:`` in a Markdown code block read as a ``plate:`` key and failed the check.
_PLATE_KEY_IN_TEXT = re.compile(
    r"""(?<![A-Za-z0-9_])(["']?)(?P<tok>plaka|plate|plate_no|plateNo|numberplate)\1\s*[:=]"""
    r"""|\[\s*["'](?P<idx>plaka|plate|plateNo)["']\s*\]""",
    re.I,
)


def _plate_like(name: str) -> bool:
    return bool(PLATE_TOKEN.search(name))


def _python_plate_findings(source: str, label: str) -> list[Finding]:
    """Flag plate usage that could *persist*, and ignore prose that merely mentions it.

    The distinction matters: ``server.py`` and ``snapshots.py`` both explain in a docstring
    that plates are never stored, and a grep-only check would flag those forever until
    somebody deleted the explanation. So this walks the AST, where comments and docstrings
    do not exist, and looks only at the places a value can be read or written: dict keys,
    subscripts, ``.get()``/``.pop()`` lookups, identifiers, attributes and model fields.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [Finding(f"{label}:{exc.lineno or 0}", f"could not parse: {exc.msg}")]

    findings: list[Finding] = []

    def flag(node: ast.AST, what: str) -> None:
        findings.append(Finding(f"{label}:{getattr(node, 'lineno', 0)}", what))

    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str) and _plate_like(key.value):
                    flag(key, f"dict key {key.value!r} could persist a number plate")
        elif isinstance(node, ast.Subscript):
            sl = node.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str) and _plate_like(sl.value):
                flag(node, f"subscript [{sl.value!r}] reads a number plate out of a payload")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in {"get", "pop", "setdefault", "getattr"}:
                first = node.args[0] if node.args else None
                if isinstance(first, ast.Constant) and isinstance(first.value, str) and _plate_like(first.value):
                    flag(node, f".{func.attr}({first.value!r}) reads a number plate out of a payload")
            for kw in node.keywords:
                if kw.arg and _plate_like(kw.arg):
                    flag(node, f"keyword argument {kw.arg!r} carries a number plate")
        elif isinstance(node, ast.Attribute) and _plate_like(node.attr):
            flag(node, f"attribute .{node.attr} carries a number plate")
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and _plate_like(node.target.id):
            flag(node, f"field {node.target.id!r} would store a number plate")
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and _plate_like(node.id):
            flag(node, f"variable {node.id!r} holds a number plate")
        elif isinstance(node, ast.arg) and _plate_like(node.arg):
            flag(node, f"parameter {node.arg!r} accepts a number plate")

    return findings


def check_no_plate(repo: pathlib.Path) -> CheckResult:
    """Decision 7: the plate is dropped at the parsing boundary and never travels further.

    İETT's ``GetFiloAracKonum_json`` returns ``Plaka`` for 6,911 vehicles. Door number
    identifies a bus well enough for every feature here, and the ADX free cluster's terms
    forbid personal data outright, so the plate has nowhere legitimate to go. This check
    proves the absence two ways: statically, over every tracked source file, and
    dynamically, by asking the live ``BusPosition`` model for its fields.
    """
    findings: list[Finding] = []
    for path in tracked_files(repo):
        name = rel(repo, path)
        if name.startswith(PLATE_EXEMPT) or "fixtures/" in name or path.suffix not in TEXT_SUFFIXES:
            continue
        source = read_text(path)
        if source is None or not PLATE_TOKEN.search(source):
            continue
        if path.suffix == ".py":
            findings.extend(_python_plate_findings(source, name))
            continue
        for lineno, line in enumerate(source.splitlines(), start=1):
            if _PLATE_KEY_IN_TEXT.search(line):
                findings.append(Finding(f"{name}:{lineno}", "a plate-shaped key appears in a data or config file"))

    model_note = ""
    try:
        from ibb_mcp.models import BusPosition

        leaked = sorted(f for f in BusPosition.model_fields if _plate_like(f))
        if leaked:
            findings.append(Finding("ibb_mcp.models.BusPosition", f"model fields would store a plate: {leaked}"))
        model_note = f", BusPosition has {len(BusPosition.model_fields)} fields and none is plate-shaped"
    except ImportError as exc:  # pragma: no cover - only when the package is not installed
        return CheckResult("no-plate", SKIP, f"ibb_mcp not importable ({exc})", findings)

    if findings:
        return CheckResult("no-plate", FAIL, f"{len(findings)} plate reference(s) that could persist", findings)
    return CheckResult("no-plate", PASS, f"no persistable plate reference outside the documented drop{model_note}")


# ---------------------------------------------------------------------------------------
# 2. fixture-plates-synthetic
# ---------------------------------------------------------------------------------------
#: A ``Plaka`` value in any of the shapes the fixtures carry: a JSON key, the same JSON
#: escaped inside a SOAP envelope (``\"Plaka\":\"...\"`` or ``&quot;``), or an XML element.
FIXTURE_PLATE = re.compile(
    r"""(?:"|\\"|&quot;)plaka(?:"|\\"|&quot;)\s*:\s*(?:(?:"|\\"|&quot;)(?P<quoted>[^"\\&<]*)|(?P<bare>[^\s,}\]]+))"""
    r"""|<plaka>(?P<element>[^<]*)</plaka>""",
    re.I,
)
#: Turkish plates open with a province code, 01 to 81. ``00`` belongs to no province, so a
#: value that starts with it cannot be anyone's car.
SYNTHETIC_PLATE_PREFIX = "00 "

#: A plate written the way İETT's feed writes it, in any file: province code, one to three
#: letters, two to five digits, single spaces. The first plate of the original recording
#: survived the fixture scrub as the "example plate" of the eval harness, because the check
#: above only read tests/fixtures/. Outside a ``Plaka`` field there is no key to anchor on,
#: so the value is judged by itself: provinces run 01 to 81 and Turkish plates never use Q,
#: W or X, and a value outside either rule (``00 XX 001``, ``99 AB 1234``) is nobody's car.
PLATE_SHAPED_VALUE = re.compile(r"(?<![0-9A-Za-z])(?P<province>\d{2}) (?P<letters>[A-Z]{1,3}) \d{2,5}(?![0-9A-Za-z])")
REAL_PROVINCES = range(1, 82)
NON_PLATE_LETTERS = frozenset("QWX")


def _could_be_a_real_plate(match: re.Match[str]) -> bool:
    return int(match["province"]) in REAL_PROVINCES and not NON_PLATE_LETTERS.intersection(match["letters"])


def check_fixture_plates_synthetic(repo: pathlib.Path) -> CheckResult:
    """Every number plate in a recorded fixture must be synthetic, and so must every example.

    ``no-plate`` exempts the fixtures because they are verbatim İBB payloads and really do
    carry the key. But fixtures are published with the code, so the *values* must not be
    real: the capture script rewrites each one to ``00 XX 001``-style placeholders. This
    reads every text fixture, including the SOAP envelopes where the JSON sits escaped
    inside XML, and fails on any ``Plaka`` value that does not start with ``00 ``.

    A plate copied out of a recording into a comment, a test or a document is the same leak,
    so every other publishable text file is read for a plate-shaped value that could be real
    (see ``PLATE_SHAPED_VALUE``).
    """
    fixtures = repo / "tests" / "fixtures"
    if not fixtures.is_dir():
        return CheckResult("fixture-plates-synthetic", SKIP, "tests/fixtures/ does not exist")

    findings: list[Finding] = []
    seen = files = scanned = 0
    for path in tracked_files(repo):
        name = rel(repo, path)
        if not is_text_candidate(path):
            continue
        if not name.startswith("tests/fixtures/"):
            source = read_text(path)
            if source is None:
                continue
            scanned += 1
            for lineno, line in enumerate(source.splitlines(), start=1):
                for match in PLATE_SHAPED_VALUE.finditer(line):
                    if _could_be_a_real_plate(match):
                        # As below: never echo the value.
                        message = "a plate-shaped value with a real province code; write examples as 00 XX 001"
                        findings.append(Finding(f"{name}:{lineno}", message))
            continue
        source = read_text(path)
        if source is None or "plaka" not in source.casefold():
            continue
        files += 1
        for lineno, line in enumerate(source.splitlines(), start=1):
            for match in FIXTURE_PLATE.finditer(line):
                value = next(v for v in match.group("quoted", "bare", "element") if v is not None).strip()
                if value.casefold() in {"", "null", "none"}:
                    continue  # an empty or null plate identifies nobody
                seen += 1
                if not value.startswith(SYNTHETIC_PLATE_PREFIX):
                    # Never echo the value: if it is real, the report would republish it.
                    message = f"Plaka value does not start with {SYNTHETIC_PLATE_PREFIX!r} ({len(value)} chars)"
                    findings.append(Finding(f"{name}:{lineno}", message))

    if findings:
        return CheckResult("fixture-plates-synthetic", FAIL, f"{len(findings)} plate value(s) look real", findings)
    return CheckResult(
        "fixture-plates-synthetic",
        PASS,
        f"{seen} Plaka value(s) in {files} fixture file(s), all start with '00 '; "
        f"no real-looking plate in {scanned} other text file(s)",
    )


# ---------------------------------------------------------------------------------------
# 3. mcp-schemas
# ---------------------------------------------------------------------------------------
#: A floor, not an exact count: adding a tool is a feature, losing one is the incident.
#: ``tests/test_mcp_integration.py`` pins the exact set of names.
MIN_TOOL_COUNT = 12
FORBIDDEN_PARAMS = {"args", "kwargs", "varargs", "varkw"}


def evaluate_tool_schemas(tools: Iterable[tuple[str, str | None, dict | None]]) -> CheckResult:
    """Judge a tool list. Split out from the import so a test can feed it a broken one.

    ``tools`` is ``(name, description, input_schema)`` per tool. The signature is
    deliberately plain data rather than SDK objects, because the point of this check is
    the *contract on the wire*, not the SDK's class layout.
    """
    findings: list[Finding] = []
    tools = list(tools)

    if len(tools) < MIN_TOOL_COUNT:
        message = f"expected at least {MIN_TOOL_COUNT} tools, the server advertises {len(tools)}"
        findings.append(Finding("ibb_mcp.server.build_server", message))

    empty = 0
    for name, description, schema in tools:
        props = sorted((schema or {}).get("properties", {}))
        leaked = FORBIDDEN_PARAMS.intersection(props)
        if leaked:
            findings.append(
                Finding(
                    f"tool {name}",
                    f"advertises {sorted(leaked)} — the decorator lost functools.wraps and every call will be rejected",
                )
            )
        if not (description or "").strip():
            findings.append(Finding(f"tool {name}", "has no description; a client cannot tell the model when to call it"))
        if not props:
            empty += 1

    # ``city_freshness`` genuinely takes no arguments. Two or more parameterless tools means
    # the schemas stopped being derived from the signatures, which is the same incident
    # wearing a different mask.
    if empty > 1:
        findings.append(Finding("ibb_mcp.server", f"{empty} tools advertise no parameters at all; only city_freshness should"))

    if findings:
        return CheckResult("mcp-schemas", FAIL, f"{len(findings)} problem(s) in the advertised tool contract", findings)
    return CheckResult("mcp-schemas", PASS, f"{len(tools)} tools, real parameter names, all described")


def check_mcp_schemas(repo: pathlib.Path) -> CheckResult:
    """Build the real server and read the schemas a client would actually receive.

    In-process tests call the tool functions directly and never go near schema validation,
    which is precisely why the ``functools.wraps`` regression shipped unnoticed. This
    builds the server offline — no İBB call, fixtures only — and inspects what it publishes.
    """
    try:
        from ibb_mcp.config import Settings
        from ibb_mcp.server import build_server
    except ImportError as exc:
        return CheckResult("mcp-schemas", SKIP, f"ibb_mcp/mcp SDK not importable ({exc})")

    settings = Settings(
        gtfs_dir=repo / "data" / "reference" / "gtfs",
        places_csv=repo / "data" / "reference" / "places.csv",
        fixtures_dir=repo / "tests" / "fixtures",
        offline=True,
    )
    try:
        tools = asyncio.run(build_server(settings).list_tools())
    except Exception as exc:  # noqa: BLE001 - any failure to build the server is the finding
        return CheckResult("mcp-schemas", FAIL, "the server could not be built", [Finding("build_server", repr(exc))])

    # MCP 2.x exposes ``input_schema``; the wire format and older SDKs use ``inputSchema``.
    described = [
        (t.name, t.description, getattr(t, "input_schema", None) or getattr(t, "inputSchema", None))
        for t in tools
    ]
    return evaluate_tool_schemas(described)


# ---------------------------------------------------------------------------------------
# 4. no-raw-ibb-calls
# ---------------------------------------------------------------------------------------
#: Call sites that may hold an HTTP client of their own, and why. Keyed by file, or by
#: ``file::function`` when only one function in the file has a reason: a new raw call
#: elsewhere in ``gtfs.py`` must still fail.
RAW_HTTP_ALLOWLIST = {
    "src/ibb_mcp/http.py": "PoliteClient itself — this is the one place the sockets live",
    "src/ibb_mcp/gtfs.py::download_gtfs": (
        "a hand-run bulk download of static CSVs from the data.ibb.gov.tr portal, not the "
        "rate-limited api.ibb.gov.tr gateway; no request path calls it"
    ),
    "scripts/capture_fixtures.py": "one-off fixture capture, run by hand; spaces gateway calls >=7 s, caps İETT at 3 SOAP calls",
    "scripts/probe_day0.py": "one-off Day-0 reachability probe, run by hand once per environment, not on any request path",
}

#: Direct calls inside ``src/ibb_mcp/`` that go to the configured *model* endpoint, never to İBB,
#: keyed ``file::function``. The package-wide rule below assumes every client in ``src/ibb_mcp/``
#: is an İBB client; the knowledge layer's query embedding is the one that is not (G14: the rule
#: read it as an İBB call). The exemption holds only while the file names no İBB host, and
#: ``OpenAIEmbedder`` itself refuses an İBB host as its base URL, so it cannot become a side door.
MODEL_ENDPOINT_CALLS = {
    "src/ibb_mcp/knowledge/embed.py::embed_documents": (
        "OpenAI-compatible embeddings at NABIZ_LLM_BASE_URL (the model provider), not an İBB service"
    ),
}

#: ``httpx.AsyncClient``/``requests.get``/``urllib.request.urlopen`` and friends.
_HTTP_MODULES = {"httpx", "requests", "aiohttp", "urllib", "urllib3"}
_HTTP_CALLABLES = {
    "get", "post", "put", "patch", "delete", "head", "options", "request", "stream", "send",
    "Client", "AsyncClient", "Session", "ClientSession", "urlopen",
}


def _raw_http_call_sites(source: str, label: str) -> list[tuple[str | None, Finding]]:
    """Every direct ``<http module>.<call>(...)``, with the function it sits in."""
    tree = ast.parse(source)
    sites: list[tuple[str | None, Finding]] = []

    def visit(node: ast.AST, function: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else function
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr in _HTTP_CALLABLES:
                root = child.func.value
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name) and root.id in _HTTP_MODULES:
                    sites.append((function, Finding(f"{label}:{child.lineno}", f"direct {root.id}.{child.func.attr}(...)")))
            visit(child, inner)

    visit(tree, None)
    return sites


def check_no_raw_ibb_calls(repo: pathlib.Path) -> CheckResult:
    """§1.4: nothing reaches İBB except through ``PoliteClient``.

    The gateway is a single front door for every İBB service and starts 503-ing all of
    them after roughly fifteen rapid requests; İETT documents 100 requests/hour for the
    whole project and ``PoliteClient`` stops at 80 so we run out before İBB does. A module
    that builds its own ``httpx.Client`` spends that budget without spacing, without
    backoff and without the hourly counter noticing — and the budget is shared with every
    other consumer of this public data, not just with us.

    Two things are flagged: a direct HTTP call in a file that also names an İBB host, and
    *any* direct HTTP call inside ``src/ibb_mcp/`` — that package exists solely to talk to
    İBB, so a client there is an İBB client no matter where the URL is assembled. Calls in
    ``src/nabiz/agent/`` are not flagged: those go to the LLM endpoint, not to İBB.
    ``tests/`` is excluded because its httpx use is ``MockTransport``, whose entire purpose
    is to make a real call impossible.
    """
    findings: list[Finding] = []
    for path in sorted(repo.glob("src/**/*.py")) + sorted(repo.glob("scripts/**/*.py")) + sorted(repo.glob("eval/**/*.py")):
        name = rel(repo, path)
        if name in RAW_HTTP_ALLOWLIST:
            continue
        source = read_text(path)
        if source is None:
            continue
        try:
            calls = [(fn, s) for fn, s in _raw_http_call_sites(source, name) if f"{name}::{fn}" not in RAW_HTTP_ALLOWLIST]
        except SyntaxError as exc:
            findings.append(Finding(f"{name}:{exc.lineno or 0}", f"could not parse: {exc.msg}"))
            continue
        names_host = next((h for h in IBB_HOSTS if h in source), None)
        if not names_host:
            calls = [(fn, s) for fn, s in calls if f"{name}::{fn}" not in MODEL_ENDPOINT_CALLS]
        sites = [s for _, s in calls]
        if not sites:
            continue
        in_ibb_package = name.startswith("src/ibb_mcp/")
        if not (names_host or in_ibb_package):
            continue
        why = f"file names {names_host}" if names_host else "inside src/ibb_mcp/, which only ever talks to İBB"
        findings.extend(Finding(s.location, f"{s.message} bypasses PoliteClient ({why})") for s in sites)

    if findings:
        return CheckResult("no-raw-ibb-calls", FAIL, f"{len(findings)} call site(s) bypassing PoliteClient", findings)
    allowed = ", ".join(sorted(RAW_HTTP_ALLOWLIST))
    model = ", ".join(sorted(MODEL_ENDPOINT_CALLS))
    return CheckResult(
        "no-raw-ibb-calls", PASS, f"every İBB call goes through PoliteClient; allowlisted: {allowed}; model endpoint: {model}"
    )


# ---------------------------------------------------------------------------------------
# 5. csv-truncation
# ---------------------------------------------------------------------------------------
def check_csv_truncation(repo: pathlib.Path) -> CheckResult:
    """Catch the Excel row ceiling before it silently drops 86% of the timetable's trips.

    İBB publishes GTFS both as CSVs and as a ZIP. ``stop_times.csv`` was exported through a
    spreadsheet and ends at exactly 1,048,575 data rows — Excel's limit minus the header.
    It is valid CSV, it parses without a warning, and it holds only 14% of trips and misses
    every 500T trip, so the arrival tool answered "no buses" for a line running past the
    user's window. Only the ZIP's ``stop_times.txt`` (6.16M rows) is complete.

    A file landing on that boundary is never a coincidence, so exactly-equal is the test:
    it cannot be triggered by a genuinely large export.

    A truncated ``.csv`` sitting next to a longer ``.txt`` of the same name is only a WARN:
    ``ibb_mcp.gtfs._stop_times_path`` prefers the ``.txt``, so the short file is dead
    weight, not a wrong answer. Without that sibling the loader would read it, and it fails.
    """
    reference = repo / "data" / "reference"
    if not reference.is_dir():
        return CheckResult("csv-truncation", SKIP, "data/reference/ is absent (it is gitignored; nothing to check)")

    failures: list[Finding] = []
    shadowed: list[Finding] = []
    inspected = 0
    for path in sorted(reference.rglob("*.csv")) + sorted(reference.rglob("*.txt")):
        inspected += 1
        data_rows = max(count_lines(path) - 1, 0)  # minus the header line
        if data_rows != EXCEL_MAX_DATA_ROWS:
            continue
        complete = path.with_suffix(".txt")
        if path.suffix == ".csv" and complete.is_file() and count_lines(complete) - 1 > EXCEL_MAX_DATA_ROWS:
            shadowed.append(
                Finding(rel(repo, path), f"truncated at Excel's ceiling but unused: the loader prefers {complete.name}")
            )
            continue
        failures.append(
            Finding(
                rel(repo, path),
                f"exactly {EXCEL_MAX_DATA_ROWS:,} data rows — Excel's ceiling. This export is truncated; "
                "use the ZIP's stop_times.txt instead",
            )
        )

    if failures:
        return CheckResult("csv-truncation", FAIL, f"{len(failures)} truncated export(s)", failures + shadowed)
    if shadowed:
        return CheckResult("csv-truncation", WARN, f"{len(shadowed)} truncated file(s) present but shadowed", shadowed)
    return CheckResult("csv-truncation", PASS, f"{inspected} reference file(s) checked, none at the Excel ceiling")


# ---------------------------------------------------------------------------------------
# 6. coordinate-sanity
# ---------------------------------------------------------------------------------------
#: Values that must never survive ``repair_coordinate``. Ankara and London are real places
#: outside İstanbul; (0, 0) is the null-island default a missing field decays into; 91 is
#: not a latitude at all; and a longitude in the latitude slot is the swapped-column bug.
OUT_OF_BOUNDS = [
    ("lat", 39.9334, "Ankara"),
    ("lon", 32.8597, "Ankara"),
    ("lat", 0.0, "null island"),
    ("lon", 0.0, "null island"),
    ("lat", 91.0, "not a latitude"),
    ("lat", 51.5072, "London"),
    ("lat", 28.9784, "İstanbul longitude offered as a latitude"),
]


def check_coordinate_sanity(repo: pathlib.Path) -> CheckResult:
    """``repair_coordinate`` must repair İBB's mangling and reject everything else.

    The GTFS export writes ``41.0191700005564`` as ``410.191.700.005.564``. Stripping the
    separators recovers it — but the same transformation applied to a number that was never
    an İstanbul coordinate produces a plausible-looking one, so the bounding-box rejection
    is the half that actually protects us: four stops in the real feed still land outside
    İstanbul after repair and are dropped rather than displayed.

    ``places.csv`` is checked too. It is the gazetteer every "near me" answer starts from;
    one bad row there silently relocates a user and every distance computed for them.
    """
    try:
        from ibb_mcp.models import repair_coordinate
    except ImportError as exc:
        return CheckResult("coordinate-sanity", SKIP, f"ibb_mcp not importable ({exc})")

    findings: list[Finding] = []
    for kind, value, why in OUT_OF_BOUNDS:
        got = repair_coordinate(value, kind)
        if got is not None:
            findings.append(Finding("models.repair_coordinate", f"accepted {value} as {kind} ({why}) -> {got}"))

    repaired = repair_coordinate("410.191.700.005.564", "lat")
    if repaired is None or not math.isclose(repaired, 41.0191700005564, rel_tol=1e-12):
        findings.append(
            Finding("models.repair_coordinate", f"stopped repairing İBB's thousands separators: got {repaired!r}")
        )

    places = repo / "data" / "reference" / "places.csv"
    if not places.is_file():
        findings.append(Finding(rel(repo, places), "the gazetteer is missing; every 'near me' answer depends on it"))
        return CheckResult("coordinate-sanity", FAIL, "gazetteer missing", findings)

    rows = 0
    with places.open(encoding="utf-8-sig", newline="") as fh:
        for lineno, row in enumerate(csv.DictReader(fh), start=2):
            rows += 1
            try:
                lat, lon = float(row["lat"]), float(row["lon"])
            except (KeyError, TypeError, ValueError):
                findings.append(Finding(f"places.csv:{lineno}", f"unparseable coordinate for {row.get('name')!r}"))
                continue
            if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
                findings.append(Finding(f"places.csv:{lineno}", f"{row.get('name')!r} at ({lat}, {lon}) is outside İstanbul"))

    if findings:
        return CheckResult("coordinate-sanity", FAIL, f"{len(findings)} coordinate problem(s)", findings)
    summary = f"repair_coordinate rejects {len(OUT_OF_BOUNDS)} bad values; {rows} gazetteer rows inside the box"
    return CheckResult("coordinate-sanity", PASS, summary)


# ---------------------------------------------------------------------------------------
# 7. no-secrets
# ---------------------------------------------------------------------------------------
#: Shapes that are a secret whatever the surrounding variable is called.
STRONG_SECRETS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Azure storage account key", re.compile(r"AccountKey\s*=\s*[A-Za-z0-9+/]{60,}={0,2}")),
    (
        "App Insights instrumentation key",
        re.compile(r"InstrumentationKey\s*=\s*[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.I),
    ),
    ("Azure SAS token", re.compile(r"[?&]sig=[A-Za-z0-9%+/]{30,}")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("OpenAI-style API key", re.compile(r"\bsk-[A-Za-z0-9_-]{32,}\b")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("JSON web token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")),
)

#: ``NABIZ_LLM_API_KEY=<something>``: only a secret if ``<something>`` looks like one. The
#: optional quote after the key admits JSON (``"apiKey": "..."``). ``rest`` is whatever
#: follows the value up to whitespace, so ``Key=<guid>;Endpoint=...`` is judged as the
#: template it is, not as the harmless-looking fragment before its first ``<``.
ASSIGNED_SECRET = re.compile(
    r"""(?P<key>[A-Za-z0-9_.\-]*(?:api[_-]?key|secret|password|passwd|token|client[_-]?secret|connection[_-]?string|sas)[A-Za-z0-9_.\-]*)"""
    r"""["']?\s*[:=]\s*["']?(?P<value>[A-Za-z0-9+/=_.\-]{16,})(?P<rest>[^\s"']*)""",
    re.I,
)

#: Anything that reads like documentation, a template or an indirection is not a leak.
PLACEHOLDER = re.compile(
    r"^(?:<.*>|\$\{.*\}|\{\{.*\}\}|x{3,}|\*{3,}|\.{3,}|-+|none|null|true|false|empty|unset|"
    r"change[_-]?me|your[_-]?\w*|my[_-]?\w*|example\w*|sample\w*|dummy\w*|placeholder\w*|redacted\w*|"
    r"test\w*|fake\w*|os\.environ.*|os\.getenv.*|getenv.*|secrets\..*|process\.env.*)$",
    re.I,
)
#: ``AZURE_STORAGE_CONNECTION_STRING``: the *name* of an environment variable, not its value.
ENV_VAR_NAME = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")
#: ``monitoring.outputs.applicationInsightsConnectionString``: a reference in Bicep, Python or
#: YAML. A JWT has the same dotted shape, which is why it is a strong pattern above.
REFERENCE_PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:(?:\.|\(\)\.)[A-Za-z_][A-Za-z0-9_]*)+(?:\(\))?$")

#: Secret-ish spelling is normal in these: they explain the variables rather than set them.
SECRET_SCAN_SKIP_SUFFIXES = {".csv", ".jsonl", ".log", ".svg", ".xml"}


def _shannon_entropy(text: str) -> float:
    counts: dict[str, int] = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(text)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _is_placeholder(value: str, rest: str = "") -> bool:
    if PLACEHOLDER.fullmatch(value) or ENV_VAR_NAME.fullmatch(value) or REFERENCE_PATH.fullmatch(value):
        return True
    if any(marker in value + rest for marker in ("<", ">", "${", "{{", "$(")):
        return True
    if len(set(value)) <= 3:  # "aaaaaaaaaaaaaaaa", "0000-0000-0000"
        return True
    # A real key is dense; an English or Turkish phrase, a path and a dotted module name are not.
    return _shannon_entropy(value) < 3.2


def check_no_secrets(repo: pathlib.Path) -> CheckResult:
    """The repository is public. A key committed once is a key leaked forever.

    ``.env.example`` deliberately names every secret the project can consume and sets none
    of them, and the docs quote connection-string *shapes* — so a scan that only greps for
    the word "key" would drown in its own false positives and be switched off within a day.
    Two layers instead: provider-specific shapes that are a secret regardless of context,
    and assignments whose value is dense enough to be real rather than ``<guid>``,
    ``os.environ[...]``, the name of an environment variable or a reference to another
    resource's output.
    """
    findings: list[Finding] = []
    scanned = 0
    for path in tracked_files(repo):
        name = rel(repo, path)
        if path.suffix in SECRET_SCAN_SKIP_SUFFIXES or not is_text_candidate(path):
            continue
        source = read_text(path)
        if source is None:
            continue
        scanned += 1
        for lineno, line in enumerate(source.splitlines(), start=1):
            for label, pattern in STRONG_SECRETS:
                if pattern.search(line):
                    findings.append(Finding(f"{name}:{lineno}", f"{label} committed to a public repository"))
            match = ASSIGNED_SECRET.search(line)
            if match and not _is_placeholder(match.group("value"), match.group("rest")):
                size = len(match.group("value"))
                findings.append(
                    Finding(f"{name}:{lineno}", f"{match.group('key')} is assigned a real-looking value ({size} chars)")
                )

    if findings:
        return CheckResult("no-secrets", FAIL, f"{len(findings)} possible secret(s) in tracked files", findings)
    return CheckResult("no-secrets", PASS, f"{scanned} tracked text file(s) scanned, no credential-shaped value")


# ---------------------------------------------------------------------------------------
# 8. no-personal-data
# ---------------------------------------------------------------------------------------
#: The only e-mail addresses a tracked file may contain, and why each one is not personal.
ALLOWED_EMAILS = {
    "135648847+muratcan-ates@users.noreply.github.com": "the owner's GitHub noreply address, the identity commits carry",
    "noreply@github.com": "GitHub's own committer for merges made in the web UI",
}
#: Domains reserved for documentation by RFC 2606 §3: no person can hold an address there, so an
#: example account's placeholder (DECISIONS #36) is not personal data. Exact second-level names only:
#: ``example.invalid`` (the tests' stand-in for a real address) and look-alikes stay findings.
EXAMPLE_DOMAINS = frozenset({"example.com", "example.org", "example.net"})
#: Home directories that belong to a machine role, not to a person.
ALLOWED_HOMES = {
    "/home/runner": "the GitHub-hosted runner's fixed home; appears when a CI log is quoted",
}
#: Documented one-off exceptions: ``(path, matched text) -> why it is not personal``.
#: Deliberately exact. A new address or path in the same file is still a finding, so an
#: exception can never quietly widen. Empty today: nothing in the tree needs one.
PERSONAL_DATA_EXCEPTIONS: dict[tuple[str, str], str] = {}

EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![A-Za-z0-9-])")
#: ``name@2x.png`` and ``pkg@1.2.js`` are asset names, not addresses.
_NOT_A_DOMAIN = re.compile(r"\.(?:png|jpe?g|gif|svg|webp|ico|js|mjs|css|py|json|md|txt|lock)$", re.I)
#: A home directory followed by a real name. ``/Users/<name>`` in prose is a placeholder:
#: ``<`` is not a name character, so it does not match.
HOME_PATH = re.compile(r"(?:/Users/|/home/)[A-Za-z0-9._-]+|[A-Za-z]:\\+Users\\+[A-Za-z0-9._ -]+")


def _not_personal(address: str) -> bool:
    """A noreply identity, an asset name that looks like an address, or an RFC 2606 example domain."""
    lowered = address.lower()
    return lowered in ALLOWED_EMAILS or bool(_NOT_A_DOMAIN.search(address)) or lowered.rsplit("@", 1)[1] in EXAMPLE_DOMAINS


def check_no_personal_data(repo: pathlib.Path) -> CheckResult:
    """No e-mail address and no home-directory path in anything a push publishes.

    Both have happened here: a tracked ``logs/collector.log`` carried absolute paths from
    the machine that wrote it, and 19 early commits carry a personal address in their
    metadata. Git history is public and permanent, so the tree is the part that can still
    be kept clean. Everything allowed is listed above with its reason; there is no
    heuristic that lets an address through silently.
    """
    findings: list[Finding] = []
    scanned = 0
    for path in tracked_files(repo):
        name = rel(repo, path)
        if not is_text_candidate(path):
            continue
        source = read_text(path)
        if source is None:
            continue
        scanned += 1
        if "@" not in source and "Users" not in source and "/home/" not in source:
            continue
        for lineno, line in enumerate(source.splitlines(), start=1):
            for match in EMAIL.finditer(line):
                address = match.group(0)
                if _not_personal(address):
                    continue
                if (name, address) not in PERSONAL_DATA_EXCEPTIONS:
                    findings.append(Finding(f"{name}:{lineno}", f"e-mail address {address!r} in a public file"))
            for match in HOME_PATH.finditer(line):
                home = match.group(0).rstrip(" ")
                if home in ALLOWED_HOMES or (name, home) in PERSONAL_DATA_EXCEPTIONS:
                    continue
                findings.append(Finding(f"{name}:{lineno}", f"home-directory path {home!r}; write a repo-relative path"))

    if findings:
        return CheckResult("no-personal-data", FAIL, f"{len(findings)} personal trace(s) in tracked files", findings)
    return CheckResult(
        "no-personal-data", PASS, f"{scanned} text file(s): no e-mail but the {len(ALLOWED_EMAILS)} noreply ones, no home path"
    )


# ---------------------------------------------------------------------------------------
# 9. no-ai-attribution
# ---------------------------------------------------------------------------------------
#: Files that must quote the forbidden phrases because they state or enforce the rule.
ATTRIBUTION_RULE_FILES = {
    "AGENTS.md": "states the no-attribution rule for every agent",
    "CONTRIBUTING.md": "states the rule for human contributors",
    "docs/NABIZ.md": "the charter; states the rule",
    ".github/workflows/README.md": "documents the authorship gate",
    "scripts/guardrails.py": "defines these patterns",
    "scripts/check_authorship.py": "defines the commit-message patterns",
    "tests/test_guardrails.py": "feeds this check the text it must reject",
    "tests/test_check_authorship.py": "feeds the authorship gate the trailers it must reject",
}
_AI_NAMES = r"(?:claude|anthropic|chatgpt|openai|gpt-?\d*|copilot|codex|\bgemini\b|\bcursor\b|\baider\b|\ban? ai\b|\bai\b)"
AI_ATTRIBUTION: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Co-Authored-By trailer", re.compile(r"co-authored-by", re.I)),
    # Only with an assistant's name after it: "regenerated by scripts/build_places.py" and
    # "generated with extract.py" are ordinary English, and this repository says both.
    ("'Generated with/by <assistant>' line", re.compile(rf"\bgenerated (?:with|by)\W{{0,3}}{_AI_NAMES}", re.I)),
    ("robot emoji", re.compile("\U0001f916")),
)


def check_no_ai_attribution(repo: pathlib.Path) -> CheckResult:
    """AGENTS.md §2: the owner is the author, so no file carries an assistant's credit.

    Commit metadata is ``scripts/check_authorship.py``'s job. This is the other half: a
    trailer or footer pasted into a README, a docstring or a PR template ships with the
    code. The files that have to *quote* the phrases to state the rule are listed above,
    each with its reason, and are the only ones skipped.
    """
    findings: list[Finding] = []
    for path in tracked_files(repo):
        name = rel(repo, path)
        if name in ATTRIBUTION_RULE_FILES or not is_text_candidate(path):
            continue
        source = read_text(path)
        if source is None:
            continue
        for lineno, line in enumerate(source.splitlines(), start=1):
            for label, pattern in AI_ATTRIBUTION:
                if pattern.search(line):
                    findings.append(Finding(f"{name}:{lineno}", f"{label}; the owner is the author (AGENTS.md §2)"))

    if findings:
        return CheckResult("no-ai-attribution", FAIL, f"{len(findings)} AI attribution line(s)", findings)
    return CheckResult(
        "no-ai-attribution", PASS, f"no AI credit outside the {len(ATTRIBUTION_RULE_FILES)} files that state the rule"
    )


# ---------------------------------------------------------------------------------------
# 10. fixture-freshness
# ---------------------------------------------------------------------------------------
FIXTURE_MAX_AGE_DAYS = 30


def check_fixture_freshness(repo: pathlib.Path) -> CheckResult:
    """Warn when the recorded İBB responses are old enough to be lying.

    The whole offline suite, CI and the no-quota demo run on ``tests/fixtures``. When İBB
    changes a field name the fixtures keep the old one and every test stays green while
    the live product breaks — which is the failure this warns about.

    It warns and never fails: re-capturing spends the shared gateway budget, so this must not
    be able to nag someone into running it on a deadline. The age is the newest
    ``captured_at_utc`` in ``_capture_report.json``, the same time offline answers are dated
    by. A report without one (written before 2026-09-23) falls back to the file's mtime,
    which a fresh ``git clone`` sets to the checkout time: directional, not exact.
    """
    report = repo / "tests" / "fixtures" / "_capture_report.json"
    if not report.is_file():
        return CheckResult("fixture-freshness", WARN, "tests/fixtures/_capture_report.json is missing; fixture age is unknown")

    captured = _newest_capture(report) or dt.datetime.fromtimestamp(report.stat().st_mtime, dt.UTC)
    age_days = (dt.datetime.now(dt.UTC) - captured).days
    if age_days > FIXTURE_MAX_AGE_DAYS:
        return CheckResult(
            "fixture-freshness",
            WARN,
            f"fixtures are {age_days} days old (>{FIXTURE_MAX_AGE_DAYS}); consider `python scripts/capture_fixtures.py`",
            [Finding(rel(repo, report), f"last modified {age_days} days ago")],
        )
    return CheckResult("fixture-freshness", PASS, f"fixtures last captured {age_days} day(s) ago")


def _newest_capture(report: pathlib.Path) -> dt.datetime | None:
    """The newest ``captured_at_utc`` in the capture report, or ``None`` when it records none."""
    try:
        calls = json.loads(report.read_text(encoding="utf-8"))
        stamps = [dt.datetime.fromisoformat(call["captured_at_utc"]) for call in calls if "captured_at_utc" in call]
    except (OSError, ValueError, TypeError):
        return None
    return max((s if s.tzinfo else s.replace(tzinfo=dt.UTC) for s in stamps), default=None)


# ---------------------------------------------------------------------------------------
# 11. no-fabricated-metrics
# ---------------------------------------------------------------------------------------
#: ``[T]``, ``[S]``, ``[E]`` are the README's own "measured later" markers (§1.5). A cell
#: holding one is an honest gap, not a claim.
PLACEHOLDER_CELL = re.compile(r"\[[TSE]\]")
#: A number as the README and the result files write it: ``1,351``, ``12.94``, ``24`` in
#: ``24/24``. A comma between digits is a thousands separator here; both files are English.
_NUMBER = re.compile(r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\w])")
#: Where a Results row may take its numbers from. Anything else in backticks (a make
#: target, a JSON key, a script) is how the number was produced, not where it is written.
EVIDENCE_PREFIXES = ("eval/results/", "data/reference/")


def _normalise_number(token: str) -> str:
    """``1,351`` and ``1351``, ``08`` and ``8``, ``12.30`` and ``12.3`` are the same number."""
    whole, _, fraction = token.replace(",", "").partition(".")
    whole = whole.lstrip("0") or "0"
    fraction = fraction.rstrip("0")
    return f"{whole}.{fraction}" if fraction else whole


def _numbers_in(text: str) -> set[str]:
    return {_normalise_number(m.group(0)) for m in _NUMBER.finditer(text)}


#: A number as the README's Turkish ``## Sayılar`` table writes it: ``1.351``, ``12,94``,
#: ``%27,3``. There a dot between digits groups thousands and a comma marks the decimals.
_NUMBER_TR = re.compile(r"(?<![\w.,])(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?(?![\w])")


def _numbers_in_tr(text: str) -> set[str]:
    """``12,94`` is ``12.94`` and ``1.351`` is ``1351``, so both compare with the English evidence files."""
    return {_normalise_number(m.group(0).replace(".", "").replace(",", ".")) for m in _NUMBER_TR.finditer(text)}


def _evidence_numbers(path: pathlib.Path) -> set[str]:
    """Every number written in an evidence file, plus, for JSON, the size of every collection.

    A count such as "3,216 cells" is the length of an object in the profile, not a literal
    anywhere in it; accepting collection sizes lets such a row be checked instead of exempted.
    """
    text = read_text(path) or ""
    numbers = _numbers_in(text)
    if path.suffix == ".json":
        try:
            stack = [json.loads(text)]
        except ValueError:
            return numbers
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                numbers.add(str(len(node)))
                stack.extend(node.values())
            elif isinstance(node, list):
                numbers.add(str(len(node)))
                stack.extend(node)
    return numbers


def _table_rows(text: str, heading: str) -> list[tuple[int, list[str]]]:
    """The body rows of the first table under the ``## <heading>`` section, as (line number, cells)."""
    rows: list[tuple[int, list[str]]] = []
    inside = False
    for lineno, line in enumerate(text.splitlines(), start=1):
        if re.match(rf"^##\s+{heading}", line, re.I):
            inside = True
            continue
        if inside and line.startswith("## "):
            break
        stripped = line.strip()
        if inside and stripped.startswith("|") and not re.fullmatch(r"\|[\s:|-]+\|?", stripped):
            rows.append((lineno, [cell.strip() for cell in stripped.strip("|").split("|")]))
    return rows[1:]  # the first row is the header


def _results_rows(text: str) -> list[tuple[int, list[str]]]:
    """The body rows of the first table under ``## Results``, as (line number, cells)."""
    return _table_rows(text, r"Results\b")


def _sayilar_rows(text: str) -> list[tuple[int, list[str]]]:
    """The body rows of the Turkish ``## Sayılar`` table: the numbers read out in the demo."""
    return _table_rows(text, r"Sayılar\b")


def _unbacked_numbers(
    repo: pathlib.Path, rows: list[tuple[int, list[str]]], numbers_in: Callable[[str], set[str]], section: str
) -> tuple[list[Finding], int]:
    """Each row's value cell against the evidence files its source cell names: the findings and the numbers checked."""
    findings: list[Finding] = []
    checked = 0
    previous: list[pathlib.Path] = []
    for lineno, cells in rows:
        if len(cells) < 3:
            continue
        metric, result, source = cells[0], cells[1], cells[2]
        named = [
            repo / name
            for name in re.findall(r"`([^`\s]+)`", source)
            if name.startswith(EVIDENCE_PREFIXES) and (repo / name).is_file()
        ]
        if source.casefold().startswith("same"):
            named = [*previous, *named]
        previous = named or previous
        claimed = numbers_in(result)
        if not claimed or PLACEHOLDER_CELL.search(result):
            continue
        checked += len(claimed)
        label = metric.strip("*\"")[:40]
        if not named:
            message = f"'{label}' states numbers but names no file under eval/results/ or data/reference/"
            findings.append(Finding(f"README.md:{lineno}", f"{section}: {message}" if section != "Results" else message))
            continue
        evidence: set[str] = set()
        for path in named:
            evidence |= _evidence_numbers(path)
        missing = sorted(claimed - evidence, key=lambda n: float(n))
        if missing:
            where = ", ".join(rel(repo, p) for p in named)
            findings.append(Finding(f"README.md:{lineno}", f"'{label}': {', '.join(missing)} not found in {where}"))
    return findings, checked


def check_no_fabricated_metrics(repo: pathlib.Path) -> CheckResult:
    """§1.5: every number in the README's Results and Sayılar tables must be written in the file its row names.

    The README says its numbers are "copied from a file in ``eval/results/`` or
    ``data/reference/``, and the file is named in the row". That promise is only worth
    something if something checks it, because the pressure to fill a table the night before a
    demo is exactly when nobody does. An earlier version of this check only asked whether
    ``eval/results/latest.md`` existed, and passed while four of the table's rows quoted files
    it never opened. So each row's Result cell is compared, number by number, with the
    evidence files its Source cell names; a Source cell that starts with "same" reuses the
    row above's files. A number that cannot be found, or a row with numbers and no evidence
    file, fails. A ``[T]``/``[S]``/``[E]`` placeholder row is an honest gap and is skipped.
    The Turkish ``## Sayılar`` table, the numbers read out in the demo, is held to the same
    rule with Turkish number reading (``12,94``, ``1.351``); a README without it is not a FAIL.
    """
    readme = repo / "README.md"
    if not readme.is_file():
        return CheckResult("no-fabricated-metrics", SKIP, "no README.md")

    text = read_text(readme) or ""
    rows = _results_rows(text)
    if not rows:
        return CheckResult("no-fabricated-metrics", SKIP, "README has no '## Results' table")
    sayilar = _sayilar_rows(text)

    findings, checked = _unbacked_numbers(repo, rows, _numbers_in, "Results")
    tr_findings, tr_checked = _unbacked_numbers(repo, sayilar, _numbers_in_tr, "Sayılar")
    findings += tr_findings
    checked += tr_checked

    if findings:
        summary = f"{len(findings)} Results or Sayılar row(s) quote a number their source does not hold"
        return CheckResult("no-fabricated-metrics", FAIL, summary, findings)
    return CheckResult(
        "no-fabricated-metrics",
        PASS,
        f"{checked} number(s) in {len(rows)} Results row(s) and {len(sayilar)} Sayılar row(s),"
        " each found in the file its row names",
    )


# ---------------------------------------------------------------------------------------
# 11b. stale-claims
# ---------------------------------------------------------------------------------------
#: Claims the README once made and must not make again, each with the reason it is wrong.
STALE_CLAIMS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # The portal lists 547 to 552 datasets depending on the day, 41 of them API-shaped; 555 was never measured.
    ("555 datasets", re.compile(r"\b555\s+(?:veri\s+seti|data\s*sets?)", re.I)),
    # An old in-sample calibration claim; the held-out error is 35.82 min (eval/results/eta.md).
    ("16.8 to 11.2", re.compile(r"16[.,]8\s*(?:→|->|to)\s*11[.,]2")),
    # The test count of 23 Sep; the current count is in eval/results/numbers.md.
    ("1250 tests", re.compile(r"\b1[.,]?250\s+(?:passed|tests?)\b")),
    # The server lists 18 tools (make smoke, eval/results/numbers.md); 15, 16 and 17 are older counts.
    ("15, 16 or 17 tools", re.compile(r"\b1[5-7]\s+(?:araç|MCP\s+tools?|tools)\b")),
    # The page and its text carry no em dash (DECISIONS, web budget 'dashes'); the README follows it.
    ("em dash", re.compile("\u2014")),
)
#: "ETA" is an abbreviation a Turkish listener does not read; the demo's numbers say "varış tahmini".
_ETA_IN_SAYILAR = ("ETA in Sayılar", re.compile(r"\bETA\b"))


def check_stale_claims(repo: pathlib.Path) -> CheckResult:
    """README.md must not bring back a claim that was measured false or has gone stale.

    Each pattern is a sentence the README carried and lost for a reason written next to it.
    Lifted from the evidence files once is not enough: the same sentence gets pasted back from
    an old draft, a slide or a chat, so the fence stays. ``## Sayılar`` also carries no "ETA".
    """
    readme = repo / "README.md"
    if not readme.is_file():
        return CheckResult("stale-claims", SKIP, "no README.md")
    findings: list[Finding] = []
    in_sayilar = False
    lines = (read_text(readme) or "").splitlines()
    for lineno, line in enumerate(lines, start=1):
        if line.startswith("## "):
            in_sayilar = bool(re.match(r"^##\s+Sayılar\b", line))
        patterns = [*STALE_CLAIMS, _ETA_IN_SAYILAR] if in_sayilar else STALE_CLAIMS
        for name, pattern in patterns:
            if pattern.search(line):
                findings.append(Finding(f"README.md:{lineno}", f"{name}: {line.strip()[:60]}"))
    if findings:
        return CheckResult("stale-claims", FAIL, f"{len(findings)} stale claim(s) in README.md", findings)
    return CheckResult("stale-claims", PASS, f"README.md: {len(lines)} line(s), none of {len(STALE_CLAIMS) + 1} stale claims")


# ---------------------------------------------------------------------------------------
# 12. agent-rules-links
# ---------------------------------------------------------------------------------------
#: The files an agent is told to obey. A path or a target they name that does not exist
#: sends every agent that reads them the wrong way, silently.
AGENT_RULE_FILES = ("AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md")
#: The first segment a repository path in those files starts with. Anything else in
#: backticks (a module name, a command, a setting) is not a path and is not checked.
REPO_TOP_LEVEL = (
    ".claude/", ".github/", ".githooks/", ".vscode/", "data/", "docs/", "eval/", "infra/", "kql/", "scripts/", "src/", "tests/",
)
#: Gitignored trees: named on purpose ("never commit ``data/lake/``") and absent on a clean
#: clone, so their absence is not a broken reference.
IGNORED_PREFIXES = (".venv/", "data/lake/", "data/reference/gtfs/", "logs/", "reports/", ".claude/settings.local.json")
_BACKTICKED = re.compile(r"`([^`\n]+)`")
_MARKDOWN_LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
_MAKE_TARGET = re.compile(r"(?<![\w-])make ([a-z][a-z0-9-]*)")
_MAKE_RULE = re.compile(r"^([a-z][a-z0-9-]*)\s*:", re.MULTILINE)


def _named_paths(text: str) -> set[str]:
    """Repository paths a rule file names in backticks.

    Only the rule files are read this way. Other documents name paths on purpose that must
    not exist (a file that was deleted, a module that was renamed), so a repo-wide scan of
    backticks would flag deliberate negatives.
    """
    found: set[str] = set()
    for token in _BACKTICKED.findall(text):
        token = token.strip().split("::", 1)[0]
        if " " in token or any(ch in token for ch in "<>*{}$"):
            continue  # a command, a glob or a placeholder, not a path
        if token.startswith(REPO_TOP_LEVEL) or token in {"Makefile", "pyproject.toml", "README.md", "DECISIONS.md", "PLAN.md"}:
            found.add(token)
    return found


def _relative_links(text: str) -> set[str]:
    """Relative Markdown link targets: a moved or deleted file breaks them in any document."""
    return {t for t in _MARKDOWN_LINK.findall(text) if "://" not in t and not t.startswith("mailto:")}


def _broken_references(
    repo: pathlib.Path, source: pathlib.Path, text: str, targets: set[str] | None
) -> tuple[int, list[Finding]]:
    """Check one Markdown file: its links always, its backticked paths and make targets if it is a rule file.

    ``targets`` is the Makefile's target set for a rule file and None for any other document.
    Returns how many references were checked and the broken ones.
    """
    where = rel(repo, source)
    named = _relative_links(text) | (_named_paths(text) if targets is not None else set())
    findings: list[Finding] = []
    checked = 0
    for ref in sorted(named):
        normalised = ref.removeprefix("./")
        if normalised.startswith(IGNORED_PREFIXES):
            continue
        checked += 1
        if not (source.parent / normalised).exists() and not (repo / normalised).exists():
            findings.append(Finding(where, f"names `{ref}`, which does not exist"))
    if targets is not None:
        for target in sorted(set(_MAKE_TARGET.findall(text))):
            checked += 1
            if target not in targets:
                findings.append(Finding(where, f"names `make {target}`, which the Makefile does not define"))
    return checked, findings


def check_agent_rules_links(repo: pathlib.Path) -> CheckResult:
    """The agent rule files name only paths and make targets that exist, and no Markdown link is broken.

    ENGINEERING.md AI-1. Links are read in every tracked ``*.md``: a doc that links a moved file
    sends its reader to a 404 as surely as a rule file sends an agent the wrong way.
    """
    makefile = read_text(repo / "Makefile") or ""
    targets = set(_MAKE_RULE.findall(makefile))
    rule_files = {repo / name for name in AGENT_RULE_FILES}
    documents = {p for p in tracked_files(repo) if p.suffix == ".md"} | {p for p in rule_files if p.is_file()}
    findings: list[Finding] = []
    checked = 0
    for source in sorted(documents):
        text = read_text(source)
        if text is None:
            continue
        count, found = _broken_references(repo, source, text, targets if source in rule_files else None)
        checked += count
        findings.extend(found)
    if findings:
        summary = f"{len(findings)} broken reference(s) in the rule files or Markdown links"
        return CheckResult("agent-rules-links", FAIL, summary, findings)
    if not checked:
        return CheckResult("agent-rules-links", SKIP, "no rule file names a path or a make target, no Markdown file links one")
    return CheckResult(
        "agent-rules-links", PASS, f"{checked} path(s), link(s) and make target(s) checked in {len(documents)} Markdown file(s)"
    )


# ---------------------------------------------------------------------------------------
# 13. no-azure-ids
# ---------------------------------------------------------------------------------------
_GUID = re.compile(r"(?<![0-9A-Fa-f-])[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}(?![0-9A-Fa-f-])")
#: The words `az` and `azd` print an account's ids under. A GUID alone is often public here
#: (CKAN dataset ids, air-quality station ids, the lake's UUID namespace), so a blanket GUID
#: ban would be wrong; a GUID beside one of these words is an identity or a scope.
_AZURE_ID_WORDS = re.compile(r"subscription|tenant|client[_-]?id|principal[_-]?id|object[_-]?id|aadapp", re.I)
#: Azure's built-in role definitions have the same id in every tenant and are published by
#: Microsoft, so naming one identifies nobody. The values are the ones infra/modules/*.bicep
#: assigns; ``tests/test_guardrails.py`` fails if one of them is no longer used there.
PUBLIC_ROLE_DEFINITIONS = {
    "7f951dda-4ed3-4680-a7ca-43fe172d538d": "AcrPull",
    "423170ca-a8f6-4b0f-8487-9e4eb8f49bfa": "Azure Maps Data Reader",
    "3913510d-42f4-4e42-8a64-420c390055eb": "Monitoring Metrics Publisher",
    "ba92f5b4-2d11-453d-a403-e96b0029c9fe": "Storage Blob Data Contributor",
    "b7e6dc6d-f1e8-4753-8033-0f276bb0955b": "Storage Blob Data Owner",
    "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1": "Storage Blob Data Reader",
    "974c5e8b-45b9-4653-ba55-5f855dd0fb88": "Storage Queue Data Contributor",
    "0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3": "Storage Table Data Contributor",
}


def _is_placeholder_guid(guid: str) -> bool:
    """``00000000-0000-...`` or ``11111111-2222-3333-4444-555555555555``: one character per group.

    No generated id looks like this, and the tests use such values to feed the code the
    shape of a client id without committing one.
    """
    return all(len(set(group)) == 1 for group in guid.split("-"))


def check_no_azure_ids(repo: pathlib.Path) -> CheckResult:
    """No subscription, tenant or client id in anything a push publishes.

    The first ``azd provision`` prints them, and a line pasted from that output into a doc or
    a config is public forever. None of them is a secret on its own, but together they map
    the owner's account for anyone. A finding never echoes the value: CI logs are public too.
    """
    findings: list[Finding] = []
    scanned = 0
    for path in tracked_files(repo):
        source = read_text(path) if is_text_candidate(path) else None
        if source is None:
            continue
        scanned += 1
        if not _GUID.search(source):
            continue
        for lineno, line in enumerate(source.splitlines(), start=1):
            if not _AZURE_ID_WORDS.search(line):
                continue
            for match in _GUID.finditer(line):
                guid = match.group(0).lower()
                if guid not in PUBLIC_ROLE_DEFINITIONS and not _is_placeholder_guid(guid):
                    findings.append(Finding(f"{rel(repo, path)}:{lineno}", "a GUID beside an Azure account word; remove the id"))

    if findings:
        return CheckResult("no-azure-ids", FAIL, f"{len(findings)} Azure account id(s) in tracked files", findings)
    return CheckResult(
        "no-azure-ids", PASS, f"{scanned} text file(s): no account id; {len(PUBLIC_ROLE_DEFINITIONS)} public role ids allowed"
    )


# ---------------------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------------------
CHECKS: tuple[tuple[str, Callable[[pathlib.Path], CheckResult]], ...] = (
    ("no-plate", check_no_plate),
    ("fixture-plates-synthetic", check_fixture_plates_synthetic),
    ("mcp-schemas", check_mcp_schemas),
    ("no-raw-ibb-calls", check_no_raw_ibb_calls),
    ("csv-truncation", check_csv_truncation),
    ("coordinate-sanity", check_coordinate_sanity),
    ("no-secrets", check_no_secrets),
    ("no-personal-data", check_no_personal_data),
    ("no-ai-attribution", check_no_ai_attribution),
    ("fixture-freshness", check_fixture_freshness),
    ("no-fabricated-metrics", check_no_fabricated_metrics),
    ("stale-claims", check_stale_claims),
    ("agent-rules-links", check_agent_rules_links),
    ("no-azure-ids", check_no_azure_ids),
)


def run_checks(repo: pathlib.Path, only: Iterable[str] | None = None) -> list[CheckResult]:
    wanted = set(only) if only else None
    results: list[CheckResult] = []
    for name, fn in CHECKS:
        if wanted is not None and name not in wanted:
            continue
        try:
            results.append(fn(repo))
        except Exception as exc:  # noqa: BLE001 - a broken check must be loud, not silent
            results.append(CheckResult(name, FAIL, f"the check itself raised {type(exc).__name__}", [Finding(name, repr(exc))]))
    return results


def render_table(results: list[CheckResult]) -> Iterator[str]:
    name_w = max([len(r.name) for r in results] + [5])
    yield f"{'CHECK'.ljust(name_w)}  {'STATUS':6}  DETAIL"
    yield f"{'-' * name_w}  {'-' * 6}  {'-' * 64}"
    for r in results:
        yield f"{r.name.ljust(name_w)}  {r.status:6}  {r.summary}"
        for finding in r.findings:
            yield f"{' ' * name_w}  {'':6}  - {finding.location}: {finding.message}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="guardrails",
        description="Regression fences around failure modes İstanbul Nabız has already hit.",
    )
    parser.add_argument("--repo", type=pathlib.Path, default=ROOT, help="repository root (default: this checkout)")
    parser.add_argument("--only", help="comma-separated subset of checks to run")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of the table")
    parser.add_argument("--list", action="store_true", help="list the check names and exit")
    parser.add_argument(
        "--files-from",
        type=pathlib.Path,
        help="NUL-separated list of repository-relative paths to check, instead of git or a directory walk",
    )
    args = parser.parse_args(argv)

    global FILES_FROM
    FILES_FROM = (
        [name for name in args.files_from.read_text(encoding="utf-8").split("\0") if name] if args.files_from else None
    )

    if args.list:
        for name, fn in CHECKS:
            print(f"{name:25} {(fn.__doc__ or '').strip().splitlines()[0]}")
        return 0

    only = [s.strip() for s in args.only.split(",")] if args.only else None
    if only:
        unknown = sorted(set(only) - {name for name, _ in CHECKS})
        if unknown:
            parser.error(f"unknown check(s): {', '.join(unknown)}")

    repo = args.repo.resolve()
    results = run_checks(repo, only)
    failed = [r for r in results if r.failed]

    if args.json:
        print(json.dumps(
            {
                # The repository's name, never its absolute path: this output is pasted
                # into issues and handoffs, and the path names the machine's user.
                "repo": repo.name,
                "failed": len(failed),
                "checks": [
                    {
                        "name": r.name,
                        "status": r.status,
                        "summary": r.summary,
                        "findings": [{"location": f.location, "message": f.message} for f in r.findings],
                    }
                    for r in results
                ],
            },
            ensure_ascii=False,
            indent=1,
        ))
    else:
        for line in render_table(results):
            print(line)
        warned = [r for r in results if r.status == WARN]
        print()
        print(f"{len(results)} checks · {len(failed)} failed · {len(warned)} warning(s)")
        if failed:
            print("Failing checks guard incidents this project has already had. Fix the cause, not the check.")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
