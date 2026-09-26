"""Tests for ``scripts/guardrails.py``: each fence must fail on the incident it guards.

A guardrail that has never been seen failing is a guardrail nobody knows works. So every
check is run here against a small synthetic repository in ``tmp_path`` holding one
violation, and against the same repository without it. Nothing reads the network.

Secrets, addresses and home paths are assembled at run time instead of being written out:
this file is itself scanned by the checks it tests, and a literal would trip them.
"""

from __future__ import annotations

import base64
import datetime as dt
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import uuid

import pytest
from conftest import REPO_ROOT

_spec = importlib.util.spec_from_file_location("guardrails", REPO_ROOT / "scripts" / "guardrails.py")
guardrails = importlib.util.module_from_spec(_spec)
# Registered before it runs: @dataclass resolves the module's annotations through sys.modules.
sys.modules[_spec.name] = guardrails
_spec.loader.exec_module(guardrails)

AT = "@"
HOME_MAC = "/Us" + "ers/"


def write(root: pathlib.Path, name: str, text: str) -> pathlib.Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def dense_value(n: int = 30) -> str:
    """A value that looks like a real key: random, base64, never the same twice.

    The leading digit keeps a random draw from starting like a placeholder ("my...",
    "test...") or an identifier, which would make the test flaky, not the check wrong.
    """
    return "9" + base64.b64encode(os.urandom(n)).decode().rstrip("=")


def url_safe(n: int) -> str:
    """Random base64url with no padding, the alphabet a JSON web token uses."""
    return base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")


# --------------------------------------------------------------------------------------
# which files are checked
# --------------------------------------------------------------------------------------
@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_tracked_files_include_new_files_and_skip_ignored_and_deleted(tmp_path: pathlib.Path) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(HOME=str(tmp_path), GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
    write(repo, ".gitignore", "secret.env\n")
    write(repo, "tracked.md", "x")
    write(repo, "gone.md", "x")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, env=env)
    (repo / "gone.md").unlink()
    write(repo, "new.md", "x")
    write(repo, "secret.env", "x")
    # Untracked build output: CI writes this before the guardrails step, and its test ids
    # quote the trailers the authorship tests feed the gate.
    write(repo, "reports/junit.xml", "Co-Authored-By: x")

    names = {guardrails.rel(repo, p) for p in guardrails.tracked_files(repo)}
    assert names == {".gitignore", "tracked.md", "new.md"}


def test_without_git_the_walk_skips_what_is_never_published(tmp_path: pathlib.Path) -> None:
    for name in ("src/a.py", ".venv/lib/x.py", "data/lake/x.json", "logs/c.log", ".env", "data/reference/gtfs/stops.csv"):
        write(tmp_path, name, "x")
    names = {guardrails.rel(tmp_path, p) for p in guardrails.tracked_files(tmp_path)}
    assert names == {"src/a.py"}


# --------------------------------------------------------------------------------------
# no-plate and fixture-plates-synthetic
# --------------------------------------------------------------------------------------
def test_plate_key_pattern_does_not_read_template_as_plate() -> None:
    # Regression: "template:" in docs/deploy.md failed the check as a plate-shaped key.
    assert guardrails._PLATE_KEY_IN_TEXT.search("template:") is None
    assert guardrails._PLATE_KEY_IN_TEXT.search('  "plate": "x"') is not None
    assert guardrails._PLATE_KEY_IN_TEXT.search("row['Plaka']") is not None


def test_no_plate_flags_a_read_and_ignores_a_docstring(tmp_path: pathlib.Path) -> None:
    write(tmp_path, "src/nabiz/doc.py", '"""We never keep the plaka field."""\n')
    assert guardrails.check_no_plate(tmp_path).status == guardrails.PASS

    write(tmp_path, "src/nabiz/leak.py", 'def f(raw):\n    return raw["Plaka"]\n')
    result = guardrails.check_no_plate(tmp_path)
    assert result.status == guardrails.FAIL
    assert [f.location for f in result.findings] == ["src/nabiz/leak.py:2"]


@pytest.mark.parametrize(
    "text",
    [
        '[{"Plaka": "00 XX 001", "KapiNo": "A-1"}]',
        '<r>[{\\"Plaka\\":\\"00 XX 002\\"}]</r>',
        "<r>[{&quot;Plaka&quot;:&quot;00 XX 003&quot;}]</r>",
        "<Arac><Plaka>00 XX 004</Plaka></Arac>",
        '[{"Plaka": null}, {"Plaka": ""}]',
    ],
)
def test_synthetic_fixture_plates_pass(tmp_path: pathlib.Path, text: str) -> None:
    write(tmp_path, "tests/fixtures/fleet.json", text)
    assert guardrails.check_fixture_plates_synthetic(tmp_path).status == guardrails.PASS


@pytest.mark.parametrize(
    "text",
    [
        '[{"Plaka": "99 ABC 123"}]',
        '<r>[{\\"Plaka\\":\\"99 ABC 123\\"}]</r>',
        "<Arac><Plaka>34ABC123</Plaka></Arac>",
        '[{"plaka": "06 XY 99"}]',
    ],
)
def test_a_real_looking_fixture_plate_fails_without_being_echoed(tmp_path: pathlib.Path, text: str) -> None:
    write(tmp_path, "tests/fixtures/fleet.soap.xml", text)
    result = guardrails.check_fixture_plates_synthetic(tmp_path)
    assert result.status == guardrails.FAIL
    assert len(result.findings) == 1
    rendered = " ".join(f.message for f in result.findings) + result.summary
    assert "ABC" not in rendered and "XY" not in rendered, "the report must not republish the plate"


def test_the_committed_fixtures_carry_only_synthetic_plates() -> None:
    result = guardrails.check_fixture_plates_synthetic(REPO_ROOT)
    assert result.status == guardrails.PASS, result.findings


@pytest.mark.parametrize("where", ["eval/run_eval.py", "docs/notes.md", "tests/test_privacy.py"])
def test_a_real_looking_plate_outside_the_fixtures_fails_without_being_echoed(tmp_path: pathlib.Path, where: str) -> None:
    # Assembled at run time: a literal would trip this very check on this file.
    plate = "3" + "4 ABC 123"
    write(tmp_path, "tests/fixtures/fleet.json", '[{"Plaka": "00 XX 001"}]')
    write(tmp_path, where, f'example = "{plate}"\n')
    result = guardrails.check_fixture_plates_synthetic(tmp_path)
    assert result.status == guardrails.FAIL
    assert [f.location for f in result.findings] == [f"{where}:1"]
    rendered = " ".join(f.message for f in result.findings) + result.summary
    assert "ABC" not in rendered, "the report must not republish the plate"


@pytest.mark.parametrize(
    "example",
    ["00 XX 000", "99 AB 1234", "06 XY 99", "34 QA 12", "15 TR + 15 EN", "at 08 30 or 17 45"],
)
def test_synthetic_or_impossible_plates_outside_the_fixtures_pass(tmp_path: pathlib.Path, example: str) -> None:
    write(tmp_path, "tests/fixtures/fleet.json", '[{"Plaka": "00 XX 001"}]')
    write(tmp_path, "eval/README.md", f"the plate shape (`{example}`)\n")
    assert guardrails.check_fixture_plates_synthetic(tmp_path).status == guardrails.PASS


# --------------------------------------------------------------------------------------
# mcp-schemas
# --------------------------------------------------------------------------------------
def good_tools(n: int) -> list[tuple[str, str, dict]]:
    tools = [(f"tool_{i}", "Does a thing.", {"properties": {"query": {"type": "string"}}}) for i in range(n - 1)]
    return [*tools, ("city_freshness", "Data ages.", {"properties": {}})]


def test_tool_count_is_a_floor_not_an_exact_number() -> None:
    assert guardrails.evaluate_tool_schemas(good_tools(12)).status == guardrails.PASS
    assert guardrails.evaluate_tool_schemas(good_tools(15)).status == guardrails.PASS
    result = guardrails.evaluate_tool_schemas(good_tools(11))
    assert result.status == guardrails.FAIL
    assert "at least 12" in result.findings[0].message


def test_a_tool_that_lost_functools_wraps_fails() -> None:
    tools = good_tools(12)
    tools[0] = ("broken", "Does a thing.", {"properties": {"args": {}, "kwargs": {}}})
    result = guardrails.evaluate_tool_schemas(tools)
    assert result.status == guardrails.FAIL
    assert "functools.wraps" in result.findings[0].message


def test_the_real_server_advertises_real_schemas() -> None:
    result = guardrails.check_mcp_schemas(REPO_ROOT)
    assert result.status == guardrails.PASS, result.findings


# --------------------------------------------------------------------------------------
# no-raw-ibb-calls
# --------------------------------------------------------------------------------------
def test_a_raw_client_inside_ibb_mcp_fails(tmp_path: pathlib.Path) -> None:
    write(tmp_path, "src/ibb_mcp/sources/new.py", "import httpx\n\ndef fetch():\n    return httpx.get('x')\n")
    result = guardrails.check_no_raw_ibb_calls(tmp_path)
    assert result.status == guardrails.FAIL
    assert result.findings[0].location == "src/ibb_mcp/sources/new.py:4"


def test_the_gtfs_allowlist_covers_one_function_not_the_file(tmp_path: pathlib.Path) -> None:
    write(tmp_path, "src/ibb_mcp/gtfs.py", "import httpx\n\ndef download_gtfs():\n    with httpx.Client() as c:\n        pass\n")
    assert guardrails.check_no_raw_ibb_calls(tmp_path).status == guardrails.PASS

    source = "import httpx\n\ndef download_gtfs():\n    httpx.Client()\n\ndef other():\n    httpx.get('x')\n"
    write(tmp_path, "src/ibb_mcp/gtfs.py", source)
    result = guardrails.check_no_raw_ibb_calls(tmp_path)
    assert result.status == guardrails.FAIL
    assert [f.location for f in result.findings] == ["src/ibb_mcp/gtfs.py:7"]


def test_the_embedding_call_is_a_model_endpoint_only_in_its_own_function(tmp_path: pathlib.Path) -> None:
    """G14: the knowledge layer's embedding POST goes to the model provider, not to İBB."""
    embed = "import httpx\n\nasync def embed_documents():\n    async with httpx.AsyncClient() as c:\n        pass\n"
    write(tmp_path, "src/ibb_mcp/knowledge/embed.py", embed)
    assert guardrails.check_no_raw_ibb_calls(tmp_path).status == guardrails.PASS

    write(tmp_path, "src/ibb_mcp/knowledge/embed.py", embed + "\ndef other():\n    httpx.get('x')\n")
    result = guardrails.check_no_raw_ibb_calls(tmp_path)
    assert [f.location for f in result.findings] == ["src/ibb_mcp/knowledge/embed.py:8"]

    write(tmp_path, "src/ibb_mcp/knowledge/embed.py", embed + "\nURL = 'https://api.ibb.gov.tr/x'\n")
    assert guardrails.check_no_raw_ibb_calls(tmp_path).status == guardrails.FAIL, "a file naming an İBB host loses the exemption"


def test_a_raw_call_elsewhere_that_names_an_ibb_host_fails(tmp_path: pathlib.Path) -> None:
    write(tmp_path, "scripts/peek.py", "import requests\nrequests.get('https://api.ibb.gov.tr/x')\n")
    assert guardrails.check_no_raw_ibb_calls(tmp_path).status == guardrails.FAIL


# --------------------------------------------------------------------------------------
# csv-truncation
# --------------------------------------------------------------------------------------
def rows(path: pathlib.Path, data_rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"h\n" + b"1\n" * data_rows)


def test_an_export_at_the_excel_ceiling_fails_unless_a_complete_file_shadows_it(tmp_path: pathlib.Path) -> None:
    gtfs = tmp_path / "data" / "reference" / "gtfs"
    rows(gtfs / "stop_times.csv", guardrails.EXCEL_MAX_DATA_ROWS)
    assert guardrails.check_csv_truncation(tmp_path).status == guardrails.FAIL

    rows(gtfs / "stop_times.txt", guardrails.EXCEL_MAX_DATA_ROWS + 10)
    result = guardrails.check_csv_truncation(tmp_path)
    assert result.status == guardrails.WARN
    assert "prefers stop_times.txt" in result.findings[0].message


def test_a_large_but_complete_export_passes(tmp_path: pathlib.Path) -> None:
    rows(tmp_path / "data" / "reference" / "big.csv", guardrails.EXCEL_MAX_DATA_ROWS - 1)
    assert guardrails.check_csv_truncation(tmp_path).status == guardrails.PASS


# --------------------------------------------------------------------------------------
# coordinate-sanity
# --------------------------------------------------------------------------------------
def test_a_longitude_in_the_latitude_slot_is_one_of_the_rejected_values() -> None:
    # Regression: the case was listed as ("lon", 28.9784), which is a valid longitude, so
    # the check failed on every run while testing the wrong thing.
    assert ("lat", 28.9784, "İstanbul longitude offered as a latitude") in guardrails.OUT_OF_BOUNDS


def test_coordinate_sanity_passes_on_the_real_gazetteer() -> None:
    result = guardrails.check_coordinate_sanity(REPO_ROOT)
    assert result.status == guardrails.PASS, result.findings


# --------------------------------------------------------------------------------------
# no-secrets
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "line",
    [
        "# APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=<guid>;IngestionEndpoint=https://<region>.example/",
        'ENV_CONNECTION_STRING = "AZURE_STORAGE_CONNECTION_STRING"',
        "    applicationInsightsConnectionString: monitoring.outputs.applicationInsightsConnectionString",
        "var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))",
        "    tokens = frozenset(needle.split())",
        "NABIZ_LLM_API_KEY=${{ vars.NOT_A_SECRET_AT_ALL }}",
        'api_key = os.environ["NABIZ_LLM_API_KEY"]',
    ],
)
def test_templates_names_and_references_are_not_secrets(tmp_path: pathlib.Path, line: str) -> None:
    write(tmp_path, "infra/x.bicep", line + "\n")
    result = guardrails.check_no_secrets(tmp_path)
    assert result.status == guardrails.PASS, result.findings


@pytest.mark.parametrize(
    "line",
    [
        lambda: f"NABIZ_LLM_API_KEY={dense_value()}",
        lambda: f'  "apiKey": "{dense_value()}"',
        # No secret-sounding key on this line: only the JWT shape itself can catch it.
        lambda: "Authorization: Bearer " + ".".join(["eyJ" + url_safe(12), "eyJ" + url_safe(24), url_safe(24)]),
        lambda: "AccountKey=" + dense_value(66),
    ],
)
def test_a_real_looking_secret_fails(tmp_path: pathlib.Path, line) -> None:
    write(tmp_path, "config.env.example", line() + "\n")
    assert guardrails.check_no_secrets(tmp_path).status == guardrails.FAIL


# --------------------------------------------------------------------------------------
# no-personal-data
# --------------------------------------------------------------------------------------
def test_only_the_noreply_addresses_are_allowed(tmp_path: pathlib.Path) -> None:
    write(tmp_path, "docs/a.md", "Commit as 135648847+muratcan-ates" + AT + "users.noreply.github.com.\n")
    write(tmp_path, "docs/b.md", "Merged by GitHub <noreply" + AT + "github.com>.\n")
    assert guardrails.check_no_personal_data(tmp_path).status == guardrails.PASS

    write(tmp_path, "docs/c.md", "Contact: someone" + AT + "example.invalid\n")
    result = guardrails.check_no_personal_data(tmp_path)
    assert result.status == guardrails.FAIL
    assert result.findings[0].location == "docs/c.md:1"


@pytest.mark.parametrize(
    ("address", "status"),
    [
        ("ornek" + AT + "example.com", "PASS"),
        ("ornek" + AT + "example.org", "PASS"),
        ("ornek" + AT + "example.net", "PASS"),
        ("ornek" + AT + "example.invalid", "FAIL"),
        ("ornek" + AT + "examples.com", "FAIL"),
        ("ornek" + AT + "mail.example.com", "FAIL"),
        ("ornek" + AT + "example.com.tr", "FAIL"),
    ],
)
def test_only_the_rfc_2606_example_domains_pass_as_placeholders(tmp_path: pathlib.Path, address: str, status: str) -> None:
    """DECISIONS #38: the example account's placeholder address is not personal data; nothing else widens."""
    write(tmp_path, "docs/x.md", f"E-posta: {address}\n")
    assert guardrails.check_no_personal_data(tmp_path).status == status


@pytest.mark.parametrize(
    ("text", "status"),
    [
        (HOME_MAC + "alice/code/istanbul-nabiz/logs/collector.log", "FAIL"),
        ("/home/" + "bob/.cache/uv", "FAIL"),
        ("C:\\" + "Users\\" + "carol\\repo", "FAIL"),
        ("``" + HOME_MAC + "<name>/t.json`` would be a leak", "PASS"),
        ("/home/runner/work/istanbul-nabiz/istanbul-nabiz/data", "PASS"),
        ("icon" + AT + "2x.png", "PASS"),
    ],
)
def test_home_paths_are_flagged_and_placeholders_are_not(tmp_path: pathlib.Path, text: str, status: str) -> None:
    write(tmp_path, "docs/x.md", text + "\n")
    assert guardrails.check_no_personal_data(tmp_path).status == status


def test_a_documented_exception_is_exact(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    address = "press" + AT + "example.invalid"
    write(tmp_path, "docs/x.md", address + "\n")
    monkeypatch.setitem(guardrails.PERSONAL_DATA_EXCEPTIONS, ("docs/x.md", address), "a published press contact")
    assert guardrails.check_no_personal_data(tmp_path).status == guardrails.PASS

    write(tmp_path, "docs/x.md", address + "\nother" + AT + "example.invalid\n")
    assert guardrails.check_no_personal_data(tmp_path).status == guardrails.FAIL


# --------------------------------------------------------------------------------------
# no-ai-attribution
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "status"),
    [
        ("Co-Authored-By: Someone <x>", "FAIL"),
        ("\U0001f916 Generated with a tool", "FAIL"),
        ("Generated with [Claude Code](https://claude.invalid)", "FAIL"),
        ("generated by ChatGPT", "FAIL"),
        ("``places.csv`` is regenerated by ``scripts/build_places.py``.", "PASS"),
        ("The fixture was generated with extract.py.", "PASS"),
        ("Claude Desktop and VS Code both launch the server over stdio.", "PASS"),
    ],
)
def test_ai_attribution_lines(tmp_path: pathlib.Path, text: str, status: str) -> None:
    write(tmp_path, "docs/x.md", text + "\n")
    assert guardrails.check_no_ai_attribution(tmp_path).status == status


def test_files_that_state_the_rule_may_quote_it(tmp_path: pathlib.Path) -> None:
    write(tmp_path, "AGENTS.md", "No `Co-Authored-By`, no 'Generated with'.\n")
    assert guardrails.check_no_ai_attribution(tmp_path).status == guardrails.PASS


# --------------------------------------------------------------------------------------
# no-fabricated-metrics
# --------------------------------------------------------------------------------------
RESULTS_HEAD = "# Demo\n\n## Results\n\n| Metric | Result | Source |\n|---|---|---|\n"


def results_repo(root: pathlib.Path, rows: str) -> None:
    write(root, "README.md", RESULTS_HEAD + rows + "\n## Next\n\n| a | 99.9 min | nowhere |\n")
    write(root, "eval/results/run.md", "| Task success | 24/24 |\n| p95 | 17819 ms |\n| MAE | 12.94 min (n = 1351) |\n")
    write(root, "data/reference/profile.json", json.dumps({"overall": {"mae_minutes": 12.37}, "cells": {"a": 1, "b": 2, "c": 3}}))


def test_results_numbers_found_in_the_named_file_pass(tmp_path: pathlib.Path) -> None:
    results_repo(
        tmp_path,
        "| Task success | **24/24** | `eval/results/run.md` |\n"
        "| p95 latency | 17,819 ms | same |\n"
        "| MAE | **12.94 min** (n = 1,351) | same, `make eta` |\n"
        "| In-sample fit | 12.37 min over 3 cells | `data/reference/profile.json` (`overall.mae_minutes`) |\n"
        "| With a model | n/a — never evaluated | needs an endpoint (DECISIONS #5) |\n"
        "| Later | [T] | `eval/results/run.md` |\n",
    )
    result = guardrails.check_no_fabricated_metrics(tmp_path)
    assert result.status == guardrails.PASS, result.findings


def test_a_results_number_the_named_file_does_not_hold_fails(tmp_path: pathlib.Path) -> None:
    # The incident: the old check only asked whether eval/results/latest.md existed.
    write(tmp_path, "eval/results/latest.md", "| Task success | 24/24 |\n")
    results_repo(
        tmp_path,
        "| Task success | **24/24** | `eval/results/run.md` |\n"
        "| p95 latency | 17.8 s | same |\n"
        "| Held out | 35.82 min | `eval/results/run.md` |\n",
    )
    result = guardrails.check_no_fabricated_metrics(tmp_path)
    assert result.status == guardrails.FAIL
    assert [f.location for f in result.findings] == ["README.md:8", "README.md:9"]
    assert "17.8" in result.findings[0].message and "35.82" in result.findings[1].message


def test_a_results_row_with_numbers_and_no_evidence_file_fails(tmp_path: pathlib.Path) -> None:
    results_repo(tmp_path, "| Coverage | 91% | `scripts/coverage.py`, the CI log |\n")
    result = guardrails.check_no_fabricated_metrics(tmp_path)
    assert result.status == guardrails.FAIL
    assert "names no file" in result.findings[0].message


def test_the_committed_readme_results_are_backed_by_their_files() -> None:
    result = guardrails.check_no_fabricated_metrics(REPO_ROOT)
    assert result.status == guardrails.PASS, result.findings


SAYILAR_HEAD = "\n## Sayılar\n\nGiriş.\n\n| Ne | Değer | Kaynak |\n|---|---|---|\n"


def sayilar_repo(root: pathlib.Path, rows: str) -> None:
    """A README with a backed Results table and a Turkish Sayılar table; the evidence is written in English."""
    results = "| Task success | 24/24 | `eval/results/run.md` |\n"
    write(root, "README.md", RESULTS_HEAD + results + SAYILAR_HEAD + rows + "\n## Next\n")
    write(root, "eval/results/run.md", "| Task success | 24/24 |\n")
    eta = "| Mean absolute error | 12.94 min |\n| Within 5 minutes | 27.3% |\n| Sample size | 1351 |\n"
    write(root, "eval/results/eta.md", eta)
    write(root, "eval/results/agent.md", "| Numeric faithfulness | 100.0% (126/126 numbers) |\n")


def test_sayilar_turkish_numbers_found_in_the_named_file_pass(tmp_path: pathlib.Path) -> None:
    sayilar_repo(
        tmp_path,
        "| Ortalama mutlak hata | **12,94 dk** (n = 1.351) | `eval/results/eta.md` · `make eta` · 8–22 Eyl |\n"
        "| 5 dakika içinde | %27,3 | same |\n"
        "| Kaynağıyla eşleşen sayı | **126/126** | `eval/results/agent.md` · 8 Eyl |\n",
    )
    result = guardrails.check_no_fabricated_metrics(tmp_path)
    assert result.status == guardrails.PASS, result.findings
    assert "1 Results row(s) and 3 Sayılar row(s)" in result.summary


def test_a_sayilar_number_the_named_file_does_not_hold_fails(tmp_path: pathlib.Path) -> None:
    sayilar_repo(
        tmp_path,
        "| Ortalama mutlak hata | **12,94 dk** | `eval/results/eta.md` |\n| Kalibre edilmiş hata | **11,2 dk** | same |\n",
    )
    result = guardrails.check_no_fabricated_metrics(tmp_path)
    assert result.status == guardrails.FAIL
    assert [f.location for f in result.findings] == ["README.md:16"]  # the second Sayılar row
    assert "11.2 not found" in result.findings[0].message


def test_readme_without_sayilar_still_checks_results(tmp_path: pathlib.Path) -> None:
    results_repo(tmp_path, "| Task success | **24/24** | `eval/results/run.md` |\n")
    result = guardrails.check_no_fabricated_metrics(tmp_path)
    assert result.status == guardrails.PASS and "0 Sayılar row(s)" in result.summary
    results_repo(tmp_path, "| Task success | **25/25** | `eval/results/run.md` |\n")
    assert guardrails.check_no_fabricated_metrics(tmp_path).status == guardrails.FAIL


@pytest.mark.parametrize(
    ("line", "name"),
    [
        ("Portal 555 veri seti sunuyor.", "555 datasets"),
        ("Calibration took the error from 16.8 → 11.2 min.", "16.8 to 11.2"),
        ("| Tests | **1250 passed** |", "1250 tests"),
        ("İBB verisi 15 araç ile sunulur.", "15, 16 or 17 tools"),
        ("One MCP server with 17 tools.", "15, 16 or 17 tools"),
        ("A server \u2014 and a page.", "em dash"),
        ("## Sayılar\n\n| ETA hatası | 12,94 dk |", "ETA in Sayılar"),
    ],
)
def test_stale_claims_fail(tmp_path: pathlib.Path, line: str, name: str) -> None:
    write(tmp_path, "README.md", "# Demo\n\n" + line + "\n")
    result = guardrails.check_stale_claims(tmp_path)
    assert result.status == guardrails.FAIL
    assert [f.message.split(":", 1)[0] for f in result.findings] == [name]
    assert result.findings[0].location == f"README.md:{3 + line.count(chr(10))}"


def test_correct_claims_pass(tmp_path: pathlib.Path) -> None:
    write(
        tmp_path,
        "README.md",
        "# Demo\n\n## Results\n\n| Bus ETA error | 12.94 min |\n\n## Sayılar\n\n"
        "| Araç | 18 araç |\n| Dönem | 8–22 Eyl |\n| Varış tahmini hatası | medyan 11,24 dk |\n",
    )
    result = guardrails.check_stale_claims(tmp_path)
    assert result.status == guardrails.PASS, result.findings


def test_the_committed_readme_has_no_stale_claims() -> None:
    result = guardrails.check_stale_claims(REPO_ROOT)
    assert result.status == guardrails.PASS, result.findings


def test_the_committed_readme_sayilar_are_backed_by_their_files() -> None:
    result = guardrails.check_no_fabricated_metrics(REPO_ROOT)
    assert result.status == guardrails.PASS, result.findings
    assert " 0 Sayılar row(s)" not in result.summary


def test_files_from_checks_exactly_the_listed_files_even_under_a_skipped_directory(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """ci-local's copy has no git index, and the walk skips logs/: a still-tracked log there was
    checked by CI and not by ci-local. With the published list handed over, both see it."""
    monkeypatch.setattr(guardrails, "FILES_FROM", None)  # restored after the test, whatever main() sets
    write(tmp_path, "src/app.py", "x = 1\n")
    write(tmp_path, "logs/mcp-http.log", f"started by someone{AT}example.invalid\n")  # example.com is a placeholder (#38)
    write(tmp_path, "notes.md", "not published\n")
    assert guardrails.check_no_personal_data(tmp_path).status == guardrails.PASS, "the walk skips logs/"

    listed = tmp_path / "published.lst"
    listed.write_text("src/app.py\0logs/mcp-http.log\0gone.py\0", encoding="utf-8")
    code = guardrails.main(["--repo", str(tmp_path), "--files-from", str(listed), "--only", "no-personal-data"])
    assert code == 1
    assert "logs/mcp-http.log:1" in capsys.readouterr().out
    assert guardrails.tracked_files(tmp_path) == [tmp_path / "logs/mcp-http.log", tmp_path / "src/app.py"]


# --------------------------------------------------------------------------------------
# runner
# --------------------------------------------------------------------------------------
def test_list_names_every_check(capsys: pytest.CaptureFixture[str]) -> None:
    assert guardrails.main(["--list"]) == 0
    out = capsys.readouterr().out
    for name, _ in guardrails.CHECKS:
        assert name in out


def test_an_unknown_check_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as excinfo:
        guardrails.main(["--only", "no-such-check"])
    assert excinfo.value.code == 2


def test_json_output_names_the_repository_not_its_absolute_path(tmp_path: pathlib.Path, capsys) -> None:
    repo = tmp_path / "some-checkout"
    write(repo, "docs/x.md", "Co-Authored-By: Someone <x>\n")
    assert guardrails.main(["--repo", str(repo), "--only", "no-ai-attribution", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["repo"] == "some-checkout"
    assert payload["failed"] == 1
    assert str(tmp_path) not in json.dumps(payload)


def test_a_check_that_raises_is_reported_as_a_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    def boom(repo: pathlib.Path) -> guardrails.CheckResult:
        raise RuntimeError("broken check")

    monkeypatch.setattr(guardrails, "CHECKS", (("boom", boom),))
    (result,) = guardrails.run_checks(tmp_path)
    assert result.status == guardrails.FAIL
    assert "RuntimeError" in result.summary


# --------------------------------------------------------------------------------------
# agent-rules-links
# --------------------------------------------------------------------------------------
def test_agent_rules_links_passes_when_every_named_path_and_target_exists(tmp_path: pathlib.Path) -> None:
    write(tmp_path, "Makefile", "test:  ## run\n\tpytest\nci-local:\n\tbash x\n")
    write(tmp_path, "src/pkg/mod.py", "")
    write(tmp_path, "docs/guide.md", "")
    rules = "Read [`docs/guide.md`](docs/guide.md), edit `src/pkg/mod.py`.\nRun `make test` and `make ci-local`.\n"
    write(tmp_path, "AGENTS.md", rules)
    result = guardrails.check_agent_rules_links(tmp_path)
    assert result.status == guardrails.PASS, result.findings


def test_agent_rules_links_fails_on_a_path_that_moved_and_a_target_that_is_gone(tmp_path: pathlib.Path) -> None:
    write(tmp_path, "Makefile", "test:\n\tpytest\n")
    write(tmp_path, "AGENTS.md", "Edit `src/pkg/renamed.py`; see [the doc](docs/gone.md); then `make smoke`.\n")
    result = guardrails.check_agent_rules_links(tmp_path)
    assert result.status == guardrails.FAIL
    messages = " ".join(f.message for f in result.findings)
    assert "src/pkg/renamed.py" in messages and "docs/gone.md" in messages and "make smoke" in messages


def test_agent_rules_links_ignores_commands_placeholders_urls_and_gitignored_trees(tmp_path: pathlib.Path) -> None:
    write(tmp_path, "Makefile", "test:\n\tpytest\n")
    write(
        tmp_path,
        "AGENTS.md",
        "Run `git worktree add ../nabiz-<lane> -b feat/<lane>`, propose `eval/journeys.<lane>.jsonl`, never commit\n"
        "`data/lake/` or `.venv/bin/python`, import `mcp.server.mcpserver`, read [MCP](https://modelcontextprotocol.io).\n",
    )
    result = guardrails.check_agent_rules_links(tmp_path)
    assert result.status == guardrails.SKIP, result.findings


def test_agent_rules_links_fails_on_a_broken_link_in_any_markdown_file(tmp_path: pathlib.Path) -> None:
    """A doc outside the rule files that links a moved file is caught; its link is read from its own folder."""
    write(tmp_path, "Makefile", "test:\n\tpytest\n")
    write(tmp_path, "AGENTS.md", "Run `make test`.\n")
    write(tmp_path, "docs/SPRINT.md", "")
    write(tmp_path, "docs/guide.md", "See [the plan](SPRINT.md) and [the old plan](plan-v1.md).\n")
    result = guardrails.check_agent_rules_links(tmp_path)
    assert result.status == guardrails.FAIL
    assert [(f.location, f.message) for f in result.findings] == [("docs/guide.md", "names `plan-v1.md`, which does not exist")]


def test_agent_rules_links_reads_only_links_outside_the_rule_files(tmp_path: pathlib.Path) -> None:
    """Other docs name deleted paths and targets on purpose; only their links are checked."""
    write(tmp_path, "Makefile", "test:\n\tpytest\n")
    write(tmp_path, "AGENTS.md", "Run `make test`.\n")
    write(tmp_path, "docs/history.md", "`scripts/removed.py` is gone and `make old-target` with it.\n")
    result = guardrails.check_agent_rules_links(tmp_path)
    assert result.status == guardrails.PASS, result.findings


# --------------------------------------------------------------------------------------
# fixture-freshness
# --------------------------------------------------------------------------------------
def capture_report(root: pathlib.Path, calls: list[dict]) -> pathlib.Path:
    return write(root, "tests/fixtures/_capture_report.json", json.dumps(calls))


def test_fixture_age_is_the_recorded_capture_time_not_the_checkout_time(tmp_path: pathlib.Path) -> None:
    """A fresh clone stamps the report with the checkout time; the recorded time does not move."""
    old = (dt.datetime.now(dt.UTC) - dt.timedelta(days=45)).isoformat()
    capture_report(tmp_path, [{"name": "ispark_park", "captured_at_utc": old}, {"name": "gtfs_package"}])
    result = guardrails.check_fixture_freshness(tmp_path)
    assert result.status == guardrails.WARN
    assert "45 days" in result.summary


def test_recently_captured_fixtures_pass_and_an_undated_report_falls_back_to_its_file_time(tmp_path: pathlib.Path) -> None:
    capture_report(tmp_path, [{"name": "ispark_park", "captured_at_utc": dt.datetime.now(dt.UTC).isoformat()}])
    assert guardrails.check_fixture_freshness(tmp_path).status == guardrails.PASS
    report = capture_report(tmp_path, [{"name": "ispark_park", "status": 200}])
    a_year_ago = (dt.datetime.now(dt.UTC) - dt.timedelta(days=365)).timestamp()
    os.utime(report, (a_year_ago, a_year_ago))
    assert guardrails.check_fixture_freshness(tmp_path).status == guardrails.WARN


# --------------------------------------------------------------------------------------
# no-azure-ids
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "template",
    [
        "subscriptionId: {guid}",
        'AZURE_TENANT_ID="{guid}"',
        "| principalId | {guid} |",
        "az role assignment create --assignee-object-id {guid}",
        ".add database nabiz ingestors ('aadapp={guid};contoso.onmicrosoft.com')",
    ],
)
def test_an_account_id_beside_an_azure_word_fails_without_being_echoed(tmp_path: pathlib.Path, template: str) -> None:
    guid = str(uuid.uuid4())  # made at run time: this file is scanned by the check it tests
    write(tmp_path, "docs/deploy.md", "Provisioned.\n" + template.format(guid=guid) + "\n")
    result = guardrails.check_no_azure_ids(tmp_path)
    assert result.status == guardrails.FAIL
    assert [f.location for f in result.findings] == ["docs/deploy.md:2"]
    assert guid not in json.dumps([f.message for f in result.findings]) + result.summary


def test_public_role_ids_placeholders_and_ids_without_an_azure_word_pass(tmp_path: pathlib.Path) -> None:
    role = next(iter(guardrails.PUBLIC_ROLE_DEFINITIONS))
    write(tmp_path, "infra/modules/x.bicep", f"roleDefinitionId: subscriptionResourceId('x', '{role}') // for principalId\n")
    write(tmp_path, "tests/test_x.py", "principal_command('11111111-2222-3333-4444-555555555555', 'tenant-id')\n")
    write(tmp_path, "docs/x.md", f"subscription: {'0' * 8}-{'0' * 4}-{'0' * 4}-{'0' * 4}-{'0' * 12}\n")
    write(tmp_path, "tests/fixtures/aq_stations.json", f'{{"Id": "{uuid.uuid4()}", "Name": "Kadıköy"}}\n')
    result = guardrails.check_no_azure_ids(tmp_path)
    assert result.status == guardrails.PASS, result.findings


def test_every_allowed_role_id_is_one_the_infra_assigns() -> None:
    """The allow-list cannot quietly grow: each value must still be in infra/modules/*.bicep."""
    bicep = " ".join(path.read_text(encoding="utf-8") for path in (REPO_ROOT / "infra" / "modules").glob("*.bicep"))
    assert [guid for guid in guardrails.PUBLIC_ROLE_DEFINITIONS if guid not in bicep] == []


def test_the_committed_tree_carries_no_azure_account_id() -> None:
    result = guardrails.check_no_azure_ids(REPO_ROOT)
    assert result.status == guardrails.PASS, result.findings
