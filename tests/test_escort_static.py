"""Static and pure-JavaScript checks for the self-mounting E71 modules."""

from __future__ import annotations

import datetime as dt
import json
import re

from conftest import REPO_ROOT
from test_static_a11y import node_json

from nabiz.console.escort_api import summary_lines
from nabiz.console.escort_request import EscortDraft, validate

STATIC = REPO_ROOT / "src/nabiz/console/static"
JS = STATIC / "js/escort.js"
CONSOLE_JS = STATIC / "js/console_escort.js"
CSS = STATIC / "css/escort.css"
CONSOLE_CSS = STATIC / "css/console_escort.css"
TODAY = dt.date(2026, 9, 25)
STATIONS = ["Kadıköy", "Levent", "Kartal"]
SAMPLE = {
    "need": "wheelchair",
    "assistance": ["meet_at_entrance", "transfer"],
    "date": "2026-10-03",
    "time": "09:30",
    "window_min": 60,
    "meet_station": "Kadıköy",
    "to_station": "Levent",
    "return_kind": "same_day",
    "return_time": "17:00",
    "companion": False,
    "note": "Kısa not",
}


def escort_module(tmp_path, script: str):
    module = json.dumps(JS.as_uri())
    prelude = "globalThis.window = { location: { search: '?mock=1', origin: 'http://localhost' } };\n"
    return node_json(tmp_path, {}, f"{prelude}const escort = await import({module});\n{script}")


def test_javascript_summary_matches_python_in_turkish_and_english(tmp_path):
    draft = validate(SAMPLE, STATIONS, TODAY)
    assert isinstance(draft, EscortDraft)
    values = escort_module(
        tmp_path,
        f"const d = {json.dumps(SAMPLE, ensure_ascii=False)}; "
        "console.log(JSON.stringify([escort.summaryLines(d,'tr'), escort.summaryLines(d,'en')]));",
    )
    assert values == [summary_lines(draft, "tr"), summary_lines(draft, "en")]


def test_javascript_validation_matches_python_for_six_error_classes(tmp_path):
    invalid = [
        {**SAMPLE, "need": "unknown"},
        {**SAMPLE, "assistance": []},
        {**SAMPLE, "date": "2026-09-24"},
        {**SAMPLE, "time": "04:59"},
        {**SAMPLE, "meet_station": "Haydarpaşa"},
        {**SAMPLE, "return_time": "09:30"},
        {**SAMPLE, "note": "x" * 201},
    ]
    encoded = json.dumps(invalid, ensure_ascii=False)
    stations = json.dumps(STATIONS, ensure_ascii=False)
    values = escort_module(
        tmp_path,
        f"const drafts = {encoded}; "
        f"console.log(JSON.stringify(drafts.map(d => escort.validateDraft(d, {stations}, '2026-09-25'))));",
    )
    expected = [validate(item, STATIONS, TODAY) for item in invalid]
    assert values == expected
    assert (
        escort_module(tmp_path, "console.log(JSON.stringify(escort.matchStation('kadıköy', ['Kadıköy','Levent'])));") == "Kadıköy"
    )


def test_card_markup_escapes_dynamic_text_and_has_153_disclaimer_not_112(tmp_path):
    view = {
        "code": "K7M2QX9P",
        "status": "received",
        "status_text": "Alındı",
        "summary": ["<script>alert(1)</script>"],
        "history": [],
    }
    html = escort_module(tmp_path, f"console.log(JSON.stringify(escort.cardMarkup({json.dumps(view)}, 'tr')));")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "Resmî İBB hizmeti değildir." in html and 'href="tel:153"' in html
    assert 'href="tel:112"' not in html
    assert '<dl class="escort-summary">' in html


def test_status_copy_follows_current_language_and_never_claims_arrangement(tmp_path):
    view = {"code": "K7M2QX9P", "status": "received", "status_text": "Alındı", "summary": [], "history": []}
    english = escort_module(tmp_path, f"console.log(JSON.stringify(escort.cardMarkup({json.dumps(view)}, 'en')));")
    assert "This record does not mean an escort has been arranged." in english
    assert "Alındı" not in english


def test_validation_field_maps_from_the_server_error_to_the_localized_label(tmp_path):
    values = escort_module(
        tmp_path,
        "console.log(JSON.stringify([escort.validationTarget(escort.TEXT.tr.badDate), escort.TEXT.en.badDate]));",
    )
    assert values == [["badDate", "date"], "Choose a valid date."]


def test_device_storage_caps_at_five_drops_expired_and_handles_throwing_storage(tmp_path):
    now = 1_790_000_000_000
    records = [{"code": f"K7M2QX{2 + i}P", "draft": {"date": "2026-10-20"}, "summary": [str(i)], "at": now + i} for i in range(7)]
    records += [{"code": None, "draft": {"date": "2026-09-01"}, "summary": ["old"], "at": now}]
    script = f"""
const store = {{ value: '', getItem() {{ return this.value; }}, setItem(_key, value) {{ this.value = value; }} }};
const records = {json.dumps(records)};
const written = escort.writeStore(store, records, {now});
const read = escort.readStore(store, {now});
const broken = {{ getItem() {{ throw Error('blocked'); }}, setItem() {{ throw Error('blocked'); }} }};
console.log(JSON.stringify([
  written, read.length, read.map(item => item.code), escort.readStore(broken), escort.writeStore(broken, records, {now}),
]));
"""
    written, count, codes, broken, saved = escort_module(tmp_path, script)
    assert written is True and count == 5 and codes == [item["code"] for item in records[:7][-5:]]
    assert broken == [] and saved is False


def test_console_moves_match_the_python_transition_table(tmp_path):
    module = json.dumps(CONSOLE_JS.as_uri())
    values = node_json(
        tmp_path,
        {},
        f"globalThis.window = {{ location: {{ search: '?mock=1', origin: 'http://localhost' }} }}; "
        f"const c = await import({module}); "
        "const states = ['received','seen','referred_official','closed','cancelled']; "
        "console.log(JSON.stringify(Object.fromEntries(states.map(s => [s,c.movesFor(s)]))));",
    )
    from nabiz.console.escort_request import OPERATOR_MOVES

    expected = {
        status: list(OPERATOR_MOVES.get(status, ()))
        for status in ("received", "seen", "referred_official", "closed", "cancelled")
    }
    assert values == expected


def test_four_assets_have_no_forbidden_motion_or_colour_patterns_and_guard_dom_setup():
    assets = (JS, CONSOLE_JS, CSS, CONSOLE_CSS)
    for path in assets:
        source = path.read_text(encoding="utf-8")
        lowered = source.lower()
        for phrase in ("setinterval", "yardım geliyor", "canlı"):
            assert phrase not in lowered, (path.name, phrase)
        assert "\u2014" not in source and "\u2013" not in source
        assert not re.search(r"addEventListener\s*\(\s*['\"]scroll", source)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", source)
        for match in re.finditer(r"\b(?:animation|transition)\s*:", source):
            before = source[: match.start()]
            assert before.rfind("@media (prefers-reduced-motion: no-preference)") >= before.rfind("@media"), path.name
    for path in (JS, CONSOLE_JS):
        source = path.read_text(encoding="utf-8")
        assert re.search(r"if\s*\(typeof document !== ['\"]undefined['\"]\)\s*mount", source)
    assert "t(key, 'tr') === message" in JS.read_text(encoding="utf-8")
    assert "aria-invalid" in JS.read_text(encoding="utf-8")
    assert "if (!doc.querySelector('#journey-section') && !doc.querySelector('#alternative')) return;" in JS.read_text(
        encoding="utf-8"
    )
    assert "STORAGE_KEY" not in "\n".join(line for line in JS.read_text(encoding="utf-8").splitlines() if "post(" in line)
    local_flow = JS.read_text(encoding="utf-8").split("function saveLocal()", 1)[1].split("function removeRecord", 1)[0]
    assert "get(" not in local_flow and "post(" not in local_flow


def test_modules_do_not_enter_service_worker_shell():
    shell = (STATIC / "sw.js").read_text(encoding="utf-8")
    assert "escort" not in shell.lower()


def test_form_has_no_identity_or_free_location_fields_and_g5_is_not_present(tmp_path):
    html = escort_module(tmp_path, "console.log(JSON.stringify(escort.TEXT.tr));")
    source = JS.read_text(encoding="utf-8")
    assert "navigator.clipboard" not in source and "@media print" not in (CSS.read_text(encoding="utf-8"))
    assert 'name="phone"' not in source and 'name="address"' not in source and 'name="email"' not in source
    assert "Resmî İBB hizmeti değildir." in html["disclaimer"]
