"""E66 modules mount themselves, keep the PWA boundary and honour reduced motion."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from conftest import REPO_ROOT

from nabiz.console.report_timeline import OPERATOR_MOVES

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
JS_FILES = [STATIC / "js" / "report_timeline.js", STATIC / "js" / "console_report_timeline.js"]
CSS_FILES = [STATIC / "css" / "report_timeline.css", STATIC / "css" / "console_report_timeline.css"]


def run_node(script: str) -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    return subprocess.run([node, "--input-type=module", "-e", script], check=True, capture_output=True, text=True).stdout


def test_card_markup_escapes_dynamic_text_and_separates_the_three_concepts() -> None:
    source = JS_FILES[0].as_uri()
    output = run_node(f"""
globalThis.window = {{ location: {{ search: '' }} }};
const mod = await import({json.dumps(source)});
const data = {{
  code: 'K7M2QX9P', station: '<script>alert(1)</script>', kind: 'not_working', kind_text: 'asansör kapalıydı',
  stage: 'resolution_reported', waiting_on: 'citizen', reopen_count: 0,
  steps: [{{stage:'recorded',reached:true,at:'2026-09-25T09:00:00Z',current:false}},
    {{stage:'reviewing',reached:true,at:'2026-09-25T09:01:00Z',current:false}},
    {{stage:'info_needed',reached:false,at:null,current:false}},{{stage:'referred',reached:false,at:null,current:false}},
    {{stage:'resolution_reported',reached:true,at:'2026-09-25T09:02:00Z',current:true}},
    {{stage:'confirmed',reached:false,at:null,current:false}}],
  history: [], publication: 'approved', official: {{available:false,call:'153',agency:{{name:'153 Çözüm Merkezi',url:'https://cozummerkezi.ibb.istanbul/'}}}}
}};
const html = mod.cardMarkup(data);
console.log(JSON.stringify(html));
""")
    html = json.loads(output)
    assert "&lt;script&gt;" in html and "<script>" not in html
    assert 'aria-current="step"' in html and "Resmî kayıt" in html
    assert "Yayın kararı (E33):</b> Onaylandı" in html
    assert "Resmî İBB hizmeti değildir." in html
    assert html.count('class="btn btn-primary"') == 1


def test_moves_for_matches_the_server_transition_table() -> None:
    source = JS_FILES[1].as_uri()
    output = run_node(f"""
globalThis.window = {{ location: {{ search: '' }} }};
const mod = await import({json.dumps(source)});
console.log(JSON.stringify(Object.fromEntries(['recorded','reviewing','info_needed','referred','resolution_reported','confirmed','reopened']
  .map(stage => [stage, mod.movesFor(stage)]))));
""")
    actual = json.loads(output)
    assert actual == {stage: list(OPERATOR_MOVES.get(stage, ())) for stage in actual}
    assert "confirmed" not in actual["reopened"] and not actual["confirmed"]


def test_response_errors_are_not_misreported_as_network_failures() -> None:
    source = JS_FILES[0].as_uri()
    output = run_node(f"""
globalThis.window = {{ location: {{ search: '' }} }};
const mod = await import({json.dumps(source)});
console.log(JSON.stringify([0, 409, 429, 503].map(status => mod.responseError(status, 'en'))));
""")
    messages = json.loads(output)
    assert len(set(messages)) == 4
    assert "server" in messages[0].lower()
    assert "changed" in messages[1].lower()
    assert "limit" in messages[2].lower()


def test_asset_contract_and_reduced_motion_rules() -> None:
    javascript = [path.read_text(encoding="utf-8") for path in JS_FILES]
    styles = [path.read_text(encoding="utf-8") for path in CSS_FILES]
    for source in javascript + styles:
        assert "setInterval" not in source
        assert not re.search(r"addEventListener\s*\(\s*['\"]scroll", source)
        assert "canlı" not in source.lower() and "ETA" not in source
        assert "\u2014" not in source and "\u2013" not in source
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgb\s*\(", source)
    for source in styles:
        for match in re.finditer(r"\b(?:transition|animation)\s*:", source):
            start = source.rfind("@media (prefers-reduced-motion: no-preference)", 0, match.start())
            assert start >= 0
            opening = source.find("{", start)
            depth = 0
            end = opening
            for end in range(opening, len(source)):
                depth += source[end] == "{"
                depth -= source[end] == "}"
                if depth == 0:
                    break
            assert match.start() < end
        assert "infinite" not in source
    for source in javascript:
        assert re.search(r"if\s*\(typeof document !== ['\"]undefined['\"]\)", source)
        assert source.rfind("if (typeof document") > source.rfind("function mount")
    assert "console_report_timeline" not in (STATIC / "sw.js").read_text(encoding="utf-8")


def test_citizen_storage_reader_never_writes_e33_codes() -> None:
    source = JS_FILES[0].read_text(encoding="utf-8")
    reader = source[source.index("function readCodes"):source.index("function safeUrl")]
    assert "getItem" in reader and "setItem" not in reader
    assert "nabiz.report-codes.v1" in reader or "OUTCOME_KEY" in reader
    refresh = source[source.index("async function refresh(code)"):source.index("function syncCodes()")]
    assert "inFlight.has(code)" in refresh and "inFlight.add(code)" in refresh and "inFlight.delete(code)" in refresh
