#!/usr/bin/env python3
"""The numbers sheet: tool, test and eval counts measured in one run, written in one place.

A number read out in a demo has to come from a file anyone can re-make (AGENTS.md §5). This
script measures each one with the command that owns it and writes the same values twice:
``eval/results/numbers.md`` for people and ``eval/results/numbers.json`` for code. The table
rows and their order are a contract: the site's "how it works" page reads them by row name.

Each step has its own pure parser, so a changed output format fails loudly instead of
turning into a wrong number. When any step's output cannot be parsed, neither file is
written and the exit status is 1. A value that was not measured is ``null``; there is no
fallback constant.

Offline only: every subprocess gets ``NABIZ_OFFLINE=1`` and ``NABIZ_LLM_NO_PROBE=1``, and the
tests run under ``NABIZ_SPRINT_MODE=1`` because CI and ``make lane-gates`` run them that way
until 2026-10-01 (DECISIONS #29). The flag is written into the sheet so the reader knows.

Usage::

    NABIZ_OFFLINE=1 .venv/bin/python scripts/demo_numbers.py            # markdown to stdout
    NABIZ_OFFLINE=1 .venv/bin/python scripts/demo_numbers.py --write    # both files
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import datetime as dt
import json
import os
import pathlib
import platform
import re
import subprocess
import sys
from collections.abc import Callable

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
RESULTS = REPO_ROOT / "eval" / "results"
EVAL_OUT = "reports/eval"  # gitignored; eval/results is the Integrator's (Makefile eval-record)
PY = sys.executable
SPRINT_FLAG = "NABIZ_SPRINT_MODE"
SPRINT_NOTE = f"{SPRINT_FLAG}=1 (DECISIONS #29)"
COMMAND = "`NABIZ_OFFLINE=1 .venv/bin/python scripts/demo_numbers.py --write`"
TEST_ENV_NOTE = f"NABIZ_OFFLINE=1 NABIZ_LLM_NO_PROBE=1 {SPRINT_FLAG}=1"

# (row name, JSON key, command). Row names and their order are read by the site: do not rename.
ROWS: tuple[tuple[str, str, str], ...] = (
    ("MCP tools", "tools", "build_server().list_tools(), offline"),
    ("Tests collected", "tests_collected", "pytest --collect-only -q"),
    ("Tests passed", "tests_passed", f"pytest -q ({TEST_ENV_NOTE})"),
    ("Tests failed", "tests_failed", "same"),
    ("Tests skipped", "tests_skipped", "same"),
    ("Tests xfailed", "tests_xfailed", "same"),
    ("Eval scenarios in eval/journeys.jsonl", "eval_total", "eval/run_eval.py --offline"),
    ("Eval scenarios run (deterministic, offline)", "eval_run", "same"),
    ("Eval scenarios skipped (agent-only)", "eval_skipped", "same"),
    ("Eval scenarios passed", "eval_passed", "same"),
    ("Knowledge questions validated", "knowledge_questions", "eval/run_knowledge_eval.py --offline"),
)
RETRIEVAL_ROW = "| Knowledge retrieval accuracy | n/a (offline: fixed unknown answers, retrieval not measured) | same |"
PYTEST_OUTCOMES = ("failed", "passed", "skipped", "xfailed")


class ParseError(ValueError):
    """A step printed something its parser does not recognise; nothing may be written."""


# --------------------------------------------------------------------------------------
# parsers: pure, one per step
# --------------------------------------------------------------------------------------
def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        raise ParseError("empty output")
    return lines[-1]


def parse_collected(text: str) -> int:
    """``2128 tests collected in 0.78s`` (the last line of ``pytest --collect-only -q``) -> 2128."""
    match = re.match(r"(\d+) tests? collected\b", _last_line(text))
    if not match:
        raise ParseError(f"no 'N tests collected' in: {_last_line(text)!r}")
    return int(match.group(1))


def parse_pytest_summary(text: str) -> dict[str, int]:
    """The last line of ``pytest -q``: each outcome counted, a missing one is 0, warnings not counted."""
    line = _last_line(text).strip("= ")
    if not re.search(r"\bin \d+(?:\.\d+)?s\b", line):
        raise ParseError(f"no pytest summary in: {line!r}")
    counts = dict.fromkeys(PYTEST_OUTCOMES, 0)
    for number, word in re.findall(r"(\d+) (\w+)", line):
        if word in counts:
            counts[word] = int(number)
    if not any(counts.values()):
        raise ParseError(f"no outcome counted in: {line!r}")
    return counts


def parse_eval_header(text: str) -> tuple[int, int, int]:
    """``... · 60/72 scenarios run, 12 skipped · ...`` -> (run, total, skipped)."""
    match = re.search(r"\b(\d+)/(\d+) scenarios run, (\d+) skipped\b", text)
    if not match:
        raise ParseError("no 'N/M scenarios run, K skipped' in the eval report")
    run, total, skipped = (int(g) for g in match.groups())
    return run, total, skipped


def parse_eval_success(text: str) -> tuple[int, int]:
    """``| Task success rate | 60/60 (100.0%) | ...`` -> (passed, run)."""
    match = re.search(r"^\| Task success rate \| (\d+)/(\d+)\b", text, re.MULTILINE)
    if not match:
        raise ParseError("no 'Task success rate' row in the eval report")
    return int(match.group(1)), int(match.group(2))


def parse_knowledge(text: str) -> int:
    """``PASS: 100 records; schema and forbidden-claim checks valid`` -> 100."""
    match = re.search(r"^PASS: (\d+) records\b", text, re.MULTILINE)
    if not match:
        raise ParseError("no 'PASS: N records' in the knowledge eval output")
    return int(match.group(1))


# --------------------------------------------------------------------------------------
# the sheet
# --------------------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class Sheet:
    values: dict[str, int | None]
    tool_names: list[str]
    commit: str
    measured_at: str
    python: str
    sprint_mode: bool = True


def render(sheet: Sheet) -> str:
    """The markdown sheet: plain integers, no thousands separator, no dash in the prose."""
    flag = SPRINT_NOTE if sheet.sprint_mode else f"{SPRINT_FLAG} unset"
    head = (
        f"Measured {sheet.measured_at} · working tree over commit `{sheet.commit}` · Python {sheet.python} · {flag} · {COMMAND}"
    )
    rows = [f"| {name} | {_cell(sheet.values.get(key))} | {command} |" for name, key, command in ROWS]
    return "\n".join(
        [
            "# Numbers sheet",
            "",
            head,
            "",
            "| Number | Value | Command |",
            "|---|---|---|",
            *rows,
            RETRIEVAL_ROW,
            "",
            f"Tools: {', '.join(sheet.tool_names)}",
            "",
        ]
    )


def _cell(value: int | None) -> str:
    return "n/a (not measured)" if value is None else str(value)


def render_json(sheet: Sheet) -> str:
    data: dict[str, object] = {key: sheet.values.get(key) for _, key, _ in ROWS}
    data |= {
        "tool_names": sheet.tool_names,
        "commit": sheet.commit,
        "measured_at": sheet.measured_at,
        "sprint_mode": sheet.sprint_mode,
    }
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# --------------------------------------------------------------------------------------
# measuring: every step goes through ``read(step) -> text``, so tests can hand in any output
# --------------------------------------------------------------------------------------
Reader = Callable[[str], str]


def measure(read: Reader, now: dt.datetime | None = None) -> Sheet:
    """Run every step through ``read``; a ParseError names the step whose output broke."""
    values: dict[str, int | None] = {}
    names = _step("tools", read, lambda text: sorted(line for line in text.splitlines() if line.strip()))
    values["tools"] = len(names)
    values["tests_collected"] = _step("collect", read, parse_collected)
    summary = _step("pytest", read, parse_pytest_summary)
    values |= {f"tests_{outcome}": summary[outcome] for outcome in PYTEST_OUTCOMES}
    report = _step("eval", read, lambda text: text)
    run, total, skipped = _step("eval", lambda _: report, parse_eval_header)
    passed, run_again = _step("eval", lambda _: report, parse_eval_success)
    if run_again != run:
        raise ParseError(f"eval: header says {run} run, the success row says {run_again}")
    values |= {"eval_total": total, "eval_run": run, "eval_skipped": skipped, "eval_passed": passed}
    values["knowledge_questions"] = _step("knowledge", read, parse_knowledge)
    commit = _step("commit", read, _parse_commit)
    stamp = (now or dt.datetime.now(dt.UTC)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return Sheet(values, names, commit, stamp, platform.python_version())


def _step[T](step: str, read: Reader, parse: Callable[[str], T]) -> T:
    try:
        return parse(read(step))
    except ParseError as exc:
        raise ParseError(f"{step}: {exc}") from exc


def _parse_commit(text: str) -> str:
    sha = text.strip()
    if not re.fullmatch(r"[0-9a-f]{7,40}", sha):
        raise ParseError(f"not a commit id: {sha!r}")
    return sha


def _env() -> dict[str, str]:
    return os.environ | {"NABIZ_OFFLINE": "1", "NABIZ_LLM_NO_PROBE": "1", SPRINT_FLAG: "1"}


def _run(*args: str) -> str:
    # The exit status is not the verdict: a red suite still prints a summary worth reading.
    done = subprocess.run(args, cwd=REPO_ROOT, env=_env(), capture_output=True, text=True, check=False)
    return done.stdout + done.stderr


def _tool_names() -> str:
    os.environ["NABIZ_OFFLINE"] = "1"  # forced, as in .github/scripts/mcp_smoke.py
    from ibb_mcp.server import build_server

    return "\n".join(tool.name for tool in asyncio.run(build_server().list_tools()))


def _eval_report() -> str:
    out = _run(PY, "eval/run_eval.py", "--offline", "--results-dir", EVAL_OUT)
    match = re.search(r"^written: .*?(\S+\.md)\s*$", out, re.MULTILINE)
    if not match:
        return out  # the header parser then names the step that broke
    return (REPO_ROOT / match.group(1)).read_text(encoding="utf-8")


def real_reader(step: str) -> str:
    pytest = (PY, "-m", "pytest", "-q", "-p", "no:cacheprovider")
    steps: dict[str, Callable[[], str]] = {
        "tools": _tool_names,
        "collect": lambda: _run(*pytest, "--collect-only"),
        "pytest": lambda: _run(*pytest),
        "eval": _eval_report,
        "knowledge": lambda: _run(PY, "eval/run_knowledge_eval.py", "--questions", "eval/knowledge_questions.jsonl", "--offline"),
        "commit": lambda: _run("git", "rev-parse", "--short", "HEAD"),
    }
    return steps[step]()


def write(sheet: Sheet, out_dir: pathlib.Path) -> list[pathlib.Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md, js = out_dir / "numbers.md", out_dir / "numbers.json"
    md.write_text(render(sheet), encoding="utf-8")
    js.write_text(render_json(sheet), encoding="utf-8")
    return [md, js]


def main(argv: list[str] | None = None, read: Reader = real_reader) -> int:
    parser = argparse.ArgumentParser(description="Measure the numbers sheet (no network).")
    parser.add_argument("--write", action="store_true", help="write eval/results/numbers.md and numbers.json")
    parser.add_argument("--out-dir", type=pathlib.Path, default=RESULTS, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        sheet = measure(read)
    except ParseError as exc:
        print(f"numbers sheet not written: {exc}", file=sys.stderr)
        return 1
    if args.write:
        for path in write(sheet, args.out_dir):
            print(f"written: {path}")
    else:
        print(render(sheet), end="")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO_ROOT / "src"))
    raise SystemExit(main())
