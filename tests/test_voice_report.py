"""Offline contracts for on-device voice intent and the E24 report bridge."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from conftest import REPO_ROOT

from ibb_mcp.text import normalize_tr
from nabiz.console import agency_router, policy

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
VOICE_JS = STATIC / "js" / "voice.js"
INTENT_JS = STATIC / "js" / "voice_intent.js"
REPORT_JS = STATIC / "js" / "voice_report.js"
VOICE_REPORT_JS = REPORT_JS
REPORT_CARD_JS = STATIC / "js" / "report.js"


def run_node(source: str) -> str:
    """Run a pure-module assertion with Node when it is available."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    result = subprocess.run(
        [node, "--input-type=module", "-e", source],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_the_prompt_uses_siz() -> None:
    """The confirmation prompt uses the page's formal form of address."""
    module_url = json.dumps(VOICE_JS.as_uri())
    run_node(
        f"const {{ confirmPrompt }} = await import({module_url});"
        "if (confirmPrompt('x') !== 'Sizi şöyle anladım: \"x\"') throw new Error('wrong prompt');"
    )
    assert "Seni" not in VOICE_JS.read_text(encoding="utf-8")


def test_voice_js_hands_the_transcript_to_a_listener() -> None:
    """The voice module dispatches an interceptable event without adding imports or prefix parsing."""
    source = VOICE_JS.read_text(encoding="utf-8")
    for required in (
        "nabiz:voice-transcript",
        "cancelable: true",
        "dataset.transcript",
        "voice-confirm-yes",
        "voice-confirm-edit",
    ):
        assert required in source
    assert "prefix.length" not in source
    assert re.findall(r"^import .*;$", source, re.M) == ["import { esc } from './format.js';"]


def test_fold_matches_normalize_tr() -> None:
    """The JavaScript fold produces the server's Turkish matching keys."""
    cases = [
        "KADIKÖY İSKELE",
        "Şişli-Mecidiyeköy",
        "Kartal'da",
        "İstanbul’da ASANSÖR çalışmıyor!",
        "IĞDIR, ÇAĞLAYAN",
        "Ayrılık Çeşmesi'nde",
        "Kâğıthane İstasyonu",
        "GÖZTEPE / SÖĞÜTLÜÇEŞME",
        "Beykoz'dan Üsküdar'a",
        "I\u0307STANBUL ve I\u0307SKELE",
        "  çok...boşluk  ",
        "M4: Kadıköy - Kartal",
    ]
    module_url = json.dumps(INTENT_JS.as_uri())
    values = json.dumps(cases, ensure_ascii=False)
    output = run_node(
        f"const {{ foldTr }} = await import({module_url});"
        f"console.log(JSON.stringify({values}.map(foldTr)));"
    )
    assert json.loads(output) == [normalize_tr(value) for value in cases]


def test_the_device_guard_agrees_with_the_server() -> None:
    """A 24-phrase Turkish corpus produces the same emergency and gas-card decisions on device."""
    cases = [
        "Kartal'da yangın var asansör çalışmıyor",
        "istasyonda gaz kokusu var",
        "doğalgaz kaçağı",
        "annem düştü kalkamıyor",
        "acil yardım lazım",
        "biri yaralandı",
        "kalp krizi",
        "acil çıkış asansörü çalışmıyor",
        "fiyat düştü",
        "gaz faturası yüksek",
        "Kartal'da asansör çalışmıyor",
        "kazan dairesi",
        "Acil durumda toplanma alanı nerede",
        "Telefonum bozuldu",
        "Metro çalışmıyor",
        "Babam düştü ama iyi",
        "Bina çatladı",
        "Gaz sayacı nerede",
        "Acil çıkış nerede",
        "otobüs kaza yaptı",
        "yaralandık",
        "kanama var",
        "nefes alamıyorum",
        "Doğalgaz aboneliği",
    ]
    module_url = json.dumps(INTENT_JS.as_uri())
    values = json.dumps(cases, ensure_ascii=False)
    output = run_node(
        f"const {{ looksLikeEmergency, gasHazard }} = await import({module_url});"
        f"console.log(JSON.stringify({values}.map((text) => [looksLikeEmergency(text), gasHazard(text)])));"
    )
    actual = json.loads(output)
    expected = [[policy.emergency_intent(text), policy.emergency_hazard(text)] for text in cases]
    assert actual == expected


def _js_strings(source: str, name: str) -> set[str]:
    match = re.search(rf"export const {name} = Object\.freeze\(\[(.*?)\]\);", source, re.S)
    assert match is not None, f"missing frozen {name} list"
    return set(re.findall(r"'([^']*)'", match.group(1)))


def test_the_device_lists_cover_the_server_lists() -> None:
    """The emergency lists on device contain the active Turkish server vocabulary."""
    source = INTENT_JS.read_text(encoding="utf-8")
    assert _js_strings(source, "ACIL_PREFIXES") >= set(policy.EMERGENCY_TERMS["acil"])
    assert _js_strings(source, "EMERGENCY_WORDS") >= set(policy._EMERGENCY_WORDS)
    assert _js_strings(source, "EMERGENCY_STEMS") >= set(policy._EMERGENCY_STEMS)


def test_a_lift_complaint_with_a_station_becomes_a_report() -> None:
    """Only a non-question lift fault with one known station enters the report flow."""
    stations = ["Kartal", "Kadıköy", "Ayrılık Çeşmesi", "Şişli-Mecidiyeköy"]
    cases = [
        ("Kartal'da asansör çalışmıyor", "Kartal"),
        ("kartalda asansör bozuk", "Kartal"),
        ("Ayrılık Çeşmesi'nde asansör kapalı", "Ayrılık Çeşmesi"),
        ("Kadıköy asansörü arızalı", "Kadıköy"),
        ("Kartal'da asansör çalışıyor mu", None),
        ("Kartal'da asansör çalışmıyor mu?", None),
        ("asansör çalışmıyor", None),
        ("Kartal'da asansör çalışıyor", None),
        ("otobüs kaçta gelir", None),
        ("Kartal'da yangın var asansör çalışmıyor", "emergency"),
    ]
    module_url = json.dumps(INTENT_JS.as_uri())
    payload = json.dumps({"stations": stations, "cases": [case[0] for case in cases]}, ensure_ascii=False)
    output = run_node(
        f"const {{ readIntent }} = await import({module_url});"
        f"const data = {payload};"
        "console.log(JSON.stringify(data.cases.map((text) => readIntent(text, data.stations))));"
    )
    intents = json.loads(output)
    for (text, expected), intent in zip(cases, intents, strict=True):
        if expected == "emergency":
            assert intent["type"] == "emergency", text
        elif expected is None:
            assert intent["type"] == "none", text
        else:
            assert intent == {"type": "lift_report", "station": expected, "kind": "not_working"}, text


def test_unsupported_work_names_a_fixed_keyword_only() -> None:
    """Unsupported services route from fixed vocabulary; questions remain ordinary chat."""
    cases = [
        ("evde suyum akmıyor", "su", "iski"),
        ("doğal gaz kesildi", "dogalgaz", "igdas"),
        ("Kartal'da yürüyen merdiven çalışmıyor", "metro", "metro"),
        ("su nerede satılıyor?", None, None),
    ]
    module_url = json.dumps(INTENT_JS.as_uri())
    payload = json.dumps({"stations": ["Kartal"], "cases": [case[0] for case in cases]}, ensure_ascii=False)
    output = run_node(
        f"const {{ readIntent }} = await import({module_url});"
        f"const data = {payload};"
        "console.log(JSON.stringify(data.cases.map((text) => readIntent(text, data.stations))));"
    )
    for (text, keyword, agency), intent in zip(cases, json.loads(output), strict=True):
        if keyword is None:
            assert intent["type"] == "none", text
        else:
            assert intent == {"type": "agency", "keyword": keyword, "agency": agency}, text
    for item in _agency_keywords():
        route = agency_router.route(item["keyword"])
        assert route.agency == item["agency"]
        assert route.emergency is False


def _agency_keywords() -> list[dict[str, str]]:
    source = INTENT_JS.read_text(encoding="utf-8")
    block = re.search(r"export const AGENCY_KEYWORDS = Object\.freeze\(\[(.*?)\]\);", source, re.S)
    assert block is not None
    entries = re.findall(
        r"Object\.freeze\(\{ agency: '([^']+)', keyword: '([^']+)'",
        block.group(1),
    )
    return [{"agency": agency, "keyword": keyword} for agency, keyword in entries]


def test_only_three_fields_leave_the_device() -> None:
    """The bridge uses only station data, a fixed agency keyword, and E24's three-field body."""
    source = VOICE_REPORT_JS.read_text(encoding="utf-8")
    assert source.count("post(") == 1
    assert "post('/api/report', { station, kind: 'not_working', bucket })" in source
    calls = re.findall(r"\bget\([^;]+?\)", source, re.S)
    assert len(calls) == 2
    assert "get('/api/map/stations')" in calls[0]
    assert "get('/api/agency', { q: intent.keyword })" in calls[1]
    assert all("transcript" not in call for call in calls)
    assert "transcript" not in source.split("post('/api/report'", 1)[1].split("})", 1)[0]
    for forbidden in ("fetch(", "sendBeacon", "XMLHttpRequest", "WebSocket", "navigator.geolocation"):
        assert forbidden not in source


def test_voice_report_follows_the_page_rules() -> None:
    """The report block uses the approved words, status semantics, and separate identifiers."""
    source = VOICE_REPORT_JS.read_text(encoding="utf-8")
    for required in (
        "Şimdi", "Bugün, daha önce", "Vazgeç", "Soru olarak yaz", "söylediğiniz cümle gönderilmez",
        "tel:153", 'role="status"', "nabiz:report-sent", "MOCK", "EMERGENCY_EVENT",
    ):
        assert required in source
    for forbidden in ("oluşturuldu", "iletildi", "başvurunuz", "Seni", "—", "–"):
        assert forbidden not in source
    assert not re.search(r"\bETA\b", source)
    for old_id in ("report-box", "report-confirm", "report-status"):
        assert f'id="{old_id}"' not in source


def test_voice_report_writes_the_e24_device_mark() -> None:
    """The voice flow shares E24's local key format and Turkish station casing."""
    report = REPORT_CARD_JS.read_text(encoding="utf-8")
    voice = VOICE_REPORT_JS.read_text(encoding="utf-8")
    assert "nabiz.report.v1" in report and "nabiz.report.v1" in voice
    assert "toLocaleLowerCase('tr')" in report
    assert "toLocaleLowerCase('tr')" in voice
