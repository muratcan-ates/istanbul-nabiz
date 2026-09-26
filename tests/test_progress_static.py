from __future__ import annotations

import html
import json
import re
import shutil
import subprocess

import pytest
from conftest import REPO_ROOT

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
CONFIDENCE = STATIC / "js" / "arrival_confidence.js"
LABELS = STATIC / "js" / "tool_labels.js"
CSS = STATIC / "css" / "progress.css"


def node_json(tmp_path, modules: dict[str, str], body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    imports = "\n".join(
        f"import * as {name} from {json.dumps((STATIC / path).as_uri())};" for name, path in modules.items()
    )
    harness = tmp_path / "progress_harness.mjs"
    harness.write_text(f"{imports}\n{body}\n", encoding="utf-8")
    result = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_measured_numbers_match_eval_eta_md() -> None:
    code = CONFIDENCE.read_text(encoding="utf-8")
    match = re.search(
        r"export const MEASURED = Object\.freeze\(\{ maeMinutes: ([\d.]+), samples: (\d+), "
        r"from: '([^']+)', to: '([^']+)', lines: \[(.*?)\], source: '([^']+)' \}\);",
        code,
    )
    assert match
    report = (REPO_ROOT / "eval" / "results" / "eta.md").read_text(encoding="utf-8")
    mae = re.search(r"\| Mean absolute error \| (\d+\.\d+) min \|", report)
    samples = re.search(r"\| Sample size \| (\d+) \|", report)
    dates = re.search(r"collected between (\d{4}-\d{2}-\d{2}) [\d:]+\s+and (\d{4}-\d{2}-\d{2})", report)
    assert mae and samples and dates
    diagnosis_lines = report.split("## Diagnosis", 1)[1].splitlines()
    separator = next(i for i, line in enumerate(diagnosis_lines) if re.fullmatch(r"---", line.strip()))
    diagnosis = diagnosis_lines[:separator]
    lines = [found.group(1) for line in diagnosis if (found := re.match(r"^\| (\w+) \| \d+ \| [\d.]+ min \|", line))]
    measured_lines = re.findall(r"'([^']+)'", match.group(5))
    assert float(match.group(1)) == float(mae.group(1))
    assert int(match.group(2)) == int(samples.group(1))
    assert match.group(3) == dates.group(1)
    assert match.group(4) == dates.group(2)
    assert measured_lines == lines
    assert match.group(6) == "eval/results/eta.md"


def test_forbidden_numbers_never_reach_the_page() -> None:
    forbidden = ("16,8", "16.8", "11,2", "11.2", "12,37", "12.37", "→")
    for path in (CONFIDENCE, LABELS, CSS):
        source = path.read_text(encoding="utf-8")
        assert not any(item in source for item in forbidden), path
        assert not re.search(r"\bETA\b", source), path
        assert "\u2013" not in source and "\u2014" not in source, path


def test_confidence_follows_the_single_minute_display(tmp_path) -> None:
    from nabiz.agent.minutes import BY_TIMETABLE, UNVERIFIED

    values = node_json(
        tmp_path,
        {"confidence": "js/arrival_confidence.js"},
        "const values = ['7 dk','1 dk',"
        + json.dumps(BY_TIMETABLE)
        + ","
        + json.dumps(UNVERIFIED)
        + ", '', null, 'yakında', '7,5 dk'];"
        "console.log(JSON.stringify(values.map(confidence.confidenceFor)));",
    )
    assert values == ["measured", "measured", "schedule", "unverified", None, None, None, None]


def test_measured_line_says_the_measurement(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"confidence": "js/arrival_confidence.js"},
        "console.log(JSON.stringify(confidence.whyMarkup('measured')));",
    )
    markup = html.unescape(values)
    assert "Neden emin değilim: 8-22 Eylül'de 1.351 tahmini ölçtük; tahmin ortalama 13 dakika kadar şaştı." in markup
    assert (
        "otobüsün durağa geldiği görülen 1.351 tahmini, geliş anıyla karşılaştırdı; "
        "durakta görülemeyen otobüsler sayılmadı."
    ) in markup
    for value in (
        "Tarihler UTC",
        "ölçüldü",
        'data-why="measured"',
        'data-mae="12.94"',
        'data-n="1351"',
        'data-from="2026-09-08"',
        'data-to="2026-09-22"',
        'data-source="eval/results/eta.md"',
        'id="arrival-why-more"',
        "Nasıl ölçüldü?",
        "15F",
        "500T",
    ):
        assert value in markup
    visible = re.sub(r"<[^>]+>", "", markup)
    assert "12,94" not in visible and "12.94" not in visible and "n=" not in visible
    assert "ETA" not in markup


def test_schedule_and_unverified_lines_carry_no_number(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"confidence": "js/arrival_confidence.js"},
        "console.log(JSON.stringify([confidence.whyMarkup('schedule'),confidence.whyMarkup('unverified'),confidence.whyMarkup(null)]));",
    )
    schedule, unverified, empty = (html.unescape(value) for value in values)
    assert "tarife saati, taze canlı konum yok" in schedule
    assert "bu durağa yaklaşan otobüsün konumu bulunamadı ya da İETT kaynağına ulaşılamadı" in unverified
    assert "tahmin vermedi" not in unverified
    for markup in (schedule, unverified):
        assert not re.search(r"\d", re.sub(r"<[^>]+>", "", markup))
    assert empty == ""


def test_turkish_number_and_date_format(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"confidence": "js/arrival_confidence.js"},
        "console.log(JSON.stringify([confidence.trDecimal(12.94),confidence.trInt(1351),confidence.trInt(999),"
        "confidence.trInt(12345),confidence.rangeTr('2026-09-08','2026-09-22'),"
        "confidence.rangeTr('2026-09-28','2026-10-03')]));",
    )
    assert values == ["12,94", "1.351", "999", "12.345", "8-22 Eylül", "28 Eylül-3 Ekim"]


async def test_every_mcp_tool_has_a_label(settings) -> None:
    from ibb_mcp.server import build_server
    from nabiz.agent.schemas import TOOL_DESCRIPTIONS

    mcp_tools = {tool.name for tool in await build_server(settings).list_tools()}
    source = LABELS.read_text(encoding="utf-8")
    labels = set(re.findall(r'^\s{2}([a-z_]+): \{ started: "([^"]+)", ended: "([^"]+)" \},$', source, re.M))
    names = {name for name, _started, _ended in labels}
    assert names == mcp_tools
    assert set(TOOL_DESCRIPTIONS) <= names


def test_labels_are_plain_turkish_and_claim_no_success() -> None:
    source = LABELS.read_text(encoding="utf-8")
    labels = re.findall(r'^\s{2}[a-z_]+: \{ started: "([^"]+)", ended: "([^"]+)" \},$', source, re.M)
    assert len(labels) == 18
    for started, ended in labels:
        assert started.endswith("…")
        assert not ended.endswith((".", "…"))
        for phrase in ("ETA", "Doğrula", "doğrulandı", "bulundu", "başarı", "geldi"):
            assert phrase not in started + ended
    required = (
        'iett_next_arrivals: { started: "İETT\'ye soruluyor…", ended: "İETT sorgusu bitti" },',
        'ibb_services_search: { started: "Resmî sayfalar taranıyor…", ended: "Resmî sayfa taraması bitti" },',
        'metro_equipment_status: { started: "Metro asansör kaydı okunuyor…", '
        'ended: "Metro asansör kaydı okuması bitti" },',
    )
    assert all(line in source for line in required)


def test_progress_line_phases_and_escaping(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"labels": "js/tool_labels.js"},
        "const start=labels.progressLine({name:'iett_next_arrivals',status:'start'});"
        "const end=labels.progressLine({name:'iett_next_arrivals',status:'end'});"
        "const unknown=labels.progressLine({name:'bilinmeyen_arac',status:'start'});"
        "const hostile=['<img src=x>','__proto__'].map(name=>labels.progressLine({name,status:'start'}));"
        "console.log(JSON.stringify({start,end,unknown,hostile,invalid:labels.progressLine({name:'iett_next_arrivals',status:'progress'}),missing:labels.progressLine(null)}));",
    )
    assert values["start"]["phase"] == "STARTED"
    assert "is-running" in values["start"]["className"]
    assert "İETT&#39;ye soruluyor…" in values["start"]["html"] and "#i-refresh" in values["start"]["html"]
    assert values["start"]["sentence"] == "İETT'ye soruluyor…"
    assert values["end"]["phase"] == "ENDED"
    assert values["end"]["sentence"] == "İETT sorgusu bitti."
    assert "#i-info-circle" in values["end"]["html"] and "Cevap yazılıyor" not in values["end"]["html"]
    assert values["unknown"]["sentence"] == "İBB kaynağına soruluyor…"
    assert all("İBB kaynağına soruluyor…" in item["sentence"] and "<img" not in item["html"] for item in values["hostile"])
    assert values["invalid"] is None and values["missing"] is None
    source = LABELS.read_text(encoding="utf-8")
    assert "WRITING" not in source and "Cevap yazılıyor" not in source


def test_progress_css_moves_only_when_allowed() -> None:
    source = CSS.read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    media = re.search(r"@media \(prefers-reduced-motion: no-preference\)\s*\{([\s\S]*?)\n\}", css)
    assert media
    animations = re.findall(r"\banimation\s*:", css)
    assert len(animations) == len(re.findall(r"\banimation\s*:", media.group(1))) == 1
    assert ':not([data-motion="reduce"])' in media.group(1)
    assert ':not([data-simple="on"])' in media.group(1)
    assert "transition" not in css and "@keyframes" not in css
    colour = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(")
    assert not colour.search(css)
    assert ".arrival-why" in css and "overflow-wrap" in css
    assert len(source.splitlines()) <= 80


def test_modules_are_pure_offline_and_small() -> None:
    confidence = CONFIDENCE.read_text(encoding="utf-8")
    labels = LABELS.read_text(encoding="utf-8")
    for source in (confidence, labels):
        for forbidden in (
            "fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "EventSource",
            "localStorage", "sessionStorage", "api.js",
        ):
            assert forbidden not in source
    assert "document" not in labels and "window" not in labels
    assert "if (typeof document !== 'undefined') mountArrivalConfidence();" in confidence
    assert len(confidence.splitlines()) <= 150
    assert len(labels.splitlines()) <= 120
    assert "behavior: 'smooth'" not in confidence + labels


def test_why_line_attaches_to_the_real_arrival_card(tmp_path) -> None:
    mock = json.loads((STATIC / "mock" / "arrival.json").read_text(encoding="utf-8"))
    values = node_json(
        tmp_path,
        {"cards": "js/cards.js", "confidence": "js/arrival_confidence.js"},
        "const mock = "
        + json.dumps(mock, ensure_ascii=False)
        + "; const render = data => { const markup=cards.arrivalCard(data);"
        "const value=markup.match(/class=\"card-value[^\"]*\">([^<]*)<\\/span>/)[1];"
        "return {markup,kind:confidence.confidenceFor(value)}; };"
        "console.log(JSON.stringify([render(mock),render({...mock,minutes:null,display:'tarifeye göre'})]));",
    )
    assert 'class="card-value' in values[0]["markup"] and 'class="card-metric"' in values[0]["markup"]
    assert values[0]["kind"] == "measured"
    assert values[1]["kind"] == "schedule"


def test_more_panel_keeps_open_and_focus_across_redraw(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"confidence": "js/arrival_confidence.js"},
        "const make=()=>{const summary={focused:null,focus(o){this.focused=o;}};"
        "return {summary,details:{open:false,querySelector:()=>summary}};};"
        "const first=make(); confidence.restoreMore(first.details,{moreOpen:true,moreFocused:true});"
        "const second=make(); confidence.restoreMore(second.details,{moreOpen:false,moreFocused:false});"
        "console.log(JSON.stringify({open:first.details.open,focused:first.summary.focused,closed:second.details.open,untouched:second.summary.focused}));",
    )
    assert values == {"open": True, "focused": {"preventScroll": True}, "closed": False, "untouched": None}
    source = CONFIDENCE.read_text(encoding="utf-8")
    assert "focusin" in source and "focusout" in source and "moreFocused" in source
