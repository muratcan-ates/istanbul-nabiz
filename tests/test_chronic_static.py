from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest
from test_i18n_surfaces import TURKISH_CHARS, UI_CALL, template_literals, ui_calls

from nabiz.console.report_triage import TRIAGE_NOTE

STATIC = pathlib.Path(__file__).parents[1] / "src" / "nabiz" / "console" / "static"
JS = STATIC / "js" / "console_chronic.js"
CSS = STATIC / "css" / "console_chronic.css"

CATALOG = {
    "tr": {
        "ui.chronic.title": "Kronik aksaklıklar",
        "ui.chronic.description": (
            "Metro İstanbul'un kullanılamayan ekipman listesi ve hat duyuruları, "
            "Nabız'ın kendi okumalarından; ayrı gün sayısına göre sıralı."
        ),
        "ui.chronic.period": "Dönem",
        "ui.chronic.period_7": "Son 7 gün",
        "ui.chronic.period_30": "Son 30 gün",
        "ui.chronic.loading": "Arşiv okunuyor.",
        "ui.chronic.loaded": "{period}: {count} satır.",
        "ui.chronic.failed": "Liste şu an alınamadı: {message}",
        "ui.chronic.retry": "Yeniden dene",
        "ui.chronic.mock": "Örnek veri modunda bu bölüm gösterilmez.",
        "ui.chronic.archive_missing": "Bu sunucuda Nabız arşivi yok; kronik aksaklık hesaplanamadı.",
        "ui.chronic.equipment_thin": (
            "Ekipman listesi bu dönemde yalnız {days} gün okundu. Kronik demek için en az {min} okunan gün gerekiyor; "
            "ekipman satırları şimdilik yalnız görülme sayısıdır."
        ),
        "ui.chronic.lines_thin": (
            "Hat duyuruları bu dönemde yalnız {days} gün okundu. "
            "Kronik demek için en az {min} okunan gün gerekiyor."
        ),
        "ui.chronic.no_rows": "Bu dönemde okunan günlerde listede ekipman ya da hat duyurusu görülmedi.",
        "ui.chronic.reports_unavailable": "Karar defteri okunamadı; vatandaş bildirimi sayılmadı.",
        "ui.chronic.reports_only": "Listede görülmeyen istasyonlarda vatandaş bildirimi: {stations}",
        "ui.chronic.list_title": "Görülenler",
        "ui.chronic.copy": "Listeyi kopyala",
        "ui.chronic.copied": "Liste kopyalandı.",
        "ui.chronic.copy_fallback": "Metin seçildi; kopyalamak için kopyalayın.",
        "ui.chronic.type_elevator": "asansör",
        "ui.chronic.type_escalator": "yürüyen merdiven",
        "ui.chronic.type_moving_walkway": "yürüyen bant",
        "ui.chronic.type_line": "hat duyurusu",
        "ui.chronic.tag": "kronik",
        "ui.chronic.seen_days": "{read} okunan günün {seen} gününde görüldü",
        "ui.chronic.seen_reads": "{total} okumadan {seen} tanesinde",
        "ui.chronic.first_last": "ilk {first} · son {last}",
        "ui.chronic.in_latest": "son okumada görüldü",
        "ui.chronic.not_in_latest": "son okumada görülmedi",
        "ui.chronic.at_once": "aynı anda en çok {count} adet",
        "ui.chronic.status_fault": "arıza",
        "ui.chronic.status_revision": "revizyon",
        "ui.chronic.status_not_operated": "çalıştırılmıyor",
        "ui.chronic.reports": "Vatandaş bildirimi: {count}",
        "ui.chronic.agency": "Önerilen kurum: {name}",
        "ui.chronic.agency_link": "resmî sayfa",
        "ui.chronic.agency_none": "Kurum çıkarılamadı; 153 doğru kuruma yönlendirir.",
        "ui.chronic.more": "Tümünü göster ({count})",
        "ui.chronic.foot": (
            "Arşiv süreksiz: bu dönemde ekipman listesi {equipment} gün, hat duyuruları {lines} gün okundu. "
            "Listede görülmemek, çalıştığı anlamına gelmez."
        ),
        "ui.chronic.last_read": "Son okuma: kayıtlı · {when}",
        "ui.chronic.triage_note": (
            "Öneri. Nabız hiçbir ekibe iş atamaz; "
            "karar ve iletme İBB çalışanınındır."
        ),
        "ui.chronic.how": "Nasıl hesaplandı?",
        "ui.chronic.how_units": (
            "Metro İstanbul aynı istasyondaki aynı türden ekipmanları ayıracak bir kimlik yayımlamıyor; "
            "bir satır, o istasyonda en az bir ekipmanın listede olduğunu söyler."
        ),
        "ui.chronic.how_threshold": (
            "Kronik: en az {min} ayrı günde görülen satır. "
            "Bu eşik bir tasarım kararıdır, ölçülmüş bir değer değildir."
        ),
        "ui.chronic.how_unreadable": "{count} okuma istasyon adı taşımadığı için sayılmadı.",
        "ui.chronic.how_reports": (
            "Vatandaş bildirimi doğrulanmamıştır; karar defterinden, "
            "istasyon bazında sayılır, hat ayrımı yoktur."
        ),
    },
    "en": {
        "ui.chronic.title": "Recurring disruptions",
        "ui.chronic.description": (
            "Metro Istanbul's list of unusable equipment and its line notices, "
            "from Nabız's own reads; sorted by number of separate days."
        ),
        "ui.chronic.period": "Period",
        "ui.chronic.period_7": "Last 7 days",
        "ui.chronic.period_30": "Last 30 days",
        "ui.chronic.loading": "Reading the archive.",
        "ui.chronic.loaded": "{period}: {count} rows.",
        "ui.chronic.failed": "The list could not be read right now: {message}",
        "ui.chronic.retry": "Try again",
        "ui.chronic.mock": "This section is not shown in sample data mode.",
        "ui.chronic.archive_missing": "There is no Nabız archive on this server; recurring disruptions could not be worked out.",
        "ui.chronic.equipment_thin": (
            "The equipment list was read on only {days} days in this period. At least {min} read days are needed to "
            "call anything recurring; equipment rows are only sighting counts for now."
        ),
        "ui.chronic.lines_thin": (
            "Line notices were read on only {days} days in this period. "
            "At least {min} read days are needed to call anything recurring."
        ),
        "ui.chronic.no_rows": "No equipment or line notice was seen on the list on the days read in this period.",
        "ui.chronic.reports_unavailable": "The decision ledger could not be read; citizen reports were not counted.",
        "ui.chronic.reports_only": "Citizen reports at stations not seen on the list: {stations}",
        "ui.chronic.list_title": "Sightings",
        "ui.chronic.copy": "Copy the list",
        "ui.chronic.copied": "List copied.",
        "ui.chronic.copy_fallback": "Text selected; copy it from here.",
        "ui.chronic.type_elevator": "lift",
        "ui.chronic.type_escalator": "escalator",
        "ui.chronic.type_moving_walkway": "moving walkway",
        "ui.chronic.type_line": "line notice",
        "ui.chronic.tag": "recurring",
        "ui.chronic.seen_days": "Seen on {seen} of {read} read days",
        "ui.chronic.seen_reads": "In {seen} of {total} reads",
        "ui.chronic.first_last": "first {first} · last {last}",
        "ui.chronic.in_latest": "seen in the latest read",
        "ui.chronic.not_in_latest": "not seen in the latest read",
        "ui.chronic.at_once": "at most {count} at once",
        "ui.chronic.status_fault": "fault",
        "ui.chronic.status_revision": "revision",
        "ui.chronic.status_not_operated": "not operated",
        "ui.chronic.reports": "Citizen reports: {count}",
        "ui.chronic.agency": "Suggested institution: {name}",
        "ui.chronic.agency_link": "official page",
        "ui.chronic.agency_none": "No institution could be found; 153 directs you to the right one.",
        "ui.chronic.more": "Show all ({count})",
        "ui.chronic.foot": (
            "The archive has gaps: in this period "
            "the equipment list was read on {equipment} days and line notices on {lines} days. "
            "Not being on the list does not mean it works."
        ),
        "ui.chronic.last_read": "Latest read: recorded · {when}",
        "ui.chronic.triage_note": (
            "A suggestion. Nabız assigns work to no team; "
            "deciding and forwarding belong to the İBB employee."
        ),
        "ui.chronic.how": "How is this worked out?",
        "ui.chronic.how_units": (
            "Metro Istanbul publishes no identifier that tells apart equipment of the same type at one station; "
            "a row says at least one of them was on the list."
        ),
        "ui.chronic.how_threshold": (
            "Recurring: a row seen on at least {min} separate days. "
            "This threshold is a design choice, not a measured value."
        ),
        "ui.chronic.how_unreadable": "{count} reads carried no station name and were not counted.",
        "ui.chronic.how_reports": (
            "Citizen reports are unverified; they are counted per station from the decision ledger, "
            "without telling lines apart."
        ),
    },
}


def node_json(expression: str, payload: object | None = None, *, search: str = "") -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    module_url = json.dumps((JS).as_uri())
    script = (
        f"globalThis.window = {{ location: {{ search: {json.dumps(search)} }} }};\n"
        "const chronic = await import(" + module_url + ");\n"
        "const input = JSON.parse(await new Promise((resolve) => { let data=''; "
        "process.stdin.on('data', (chunk) => data += chunk); "
        "process.stdin.on('end', () => resolve(data || '{}')); }));\n"
        f"const output = {expression};\n"
        "console.log(JSON.stringify(output));\n"
    )
    result = subprocess.run(
        [node, "--experimental-default-type=module", "--input-type=module", "-e", script],
        input=json.dumps(payload or {}, ensure_ascii=False), capture_output=True, text=True, cwd=STATIC, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def row(*, chronic: bool = False, kind: str = "equipment", reports: int | None = None) -> dict[str, object]:
    return {
        "kind": kind,
        "line": "M2",
        "station": "Hacıosman",
        "equipment_type": "escalator",
        "days_seen": 2,
        "read_days": 4,
        "reads_seen": 3,
        "reads_total": 8,
        "first_seen": "2026-09-25T20:00:00Z",
        "last_seen": "2026-09-26T20:00:00Z",
        "in_latest_read": True,
        "max_at_once": 2,
        "statuses": ["not_operated"],
        "notice": "Hat duyurusu kaynak metni",
        "chronic": chronic,
        "reports": reports,
        "agency": {"id": "metro", "name": "Metro İstanbul", "url": "https://www.metro.istanbul/"},
    }


def test_first_ten_rows_and_details_keep_their_order() -> None:
    payload = {
        "days": 7,
        "total_rows": 12,
        "rows": [row() for _ in range(12)],
        "coverage": {"equipment": {}, "lines": {}},
        "note_codes": [],
    }
    html = node_json("chronic.sectionMarkup(input)", payload, search="")

    lists = re.findall(r"<ol class=\"chronic-list\"[^>]*>(.*?)</ol>", html, flags=re.S)
    assert len(lists) == 2
    assert lists[0].count('<li class="chronic-row">') == 10
    assert 'class="chronic-more"><summary>Tümünü göster (12)</summary>' in html
    assert 'class="chronic-list" start="11"' in html


def test_recurring_label_only_marks_qualifying_rows_and_line_notice_is_not_equipment() -> None:
    values = node_json(
        "[chronic.rowMarkup(input.equipment), chronic.rowMarkup(input.line)]",
        {"equipment": row(), "line": row(chronic=True, kind="line")},
        search="",
    )
    unmarked, line = values

    assert "class=\"tag is-warn\"" not in unmarked
    assert "class=\"tag is-warn\"" in line
    assert "hat duyurusu" in line
    assert "kullanılamayan" not in line


def test_thin_data_and_missing_archive_have_distinct_markup() -> None:
    thin = {
        "days": 7,
        "total_rows": 0,
        "rows": [],
        "coverage": {"equipment": {"read_days": 1}, "lines": {"read_days": 2}},
        "chronic_min_days": 3,
        "note_codes": ["equipment_thin", "lines_thin", "no_rows"],
    }
    missing = {"days": 7, "note_codes": ["archive_missing"], "rows": [], "total_rows": 0}
    html, empty = node_json(
        "[chronic.sectionMarkup(input.thin), chronic.sectionMarkup(input.missing)]",
        {"thin": thin, "missing": missing}, search="",
    )

    assert "yalnız 1 gün okundu" in html and "yalnız 2 gün okundu" in html
    assert "<select" not in empty and "<ol" not in empty
    assert "Bu sunucuda Nabız arşivi yok" in empty


def test_report_count_and_untranslated_source_values_are_marked_safely() -> None:
    values = node_json(
        "[chronic.rowMarkup(input.zero), chronic.rowMarkup(input.none), "
        "chronic.rowMarkup(input.count), chronic.rowMarkup(input.line)]",
        {"zero": row(reports=0), "none": row(reports=None), "count": row(reports=2), "line": row(kind="line")},
        search="",
    )
    zero, none, counted, line = values

    assert "Vatandaş bildirimi" not in zero + none
    assert "Vatandaş bildirimi: 2" in counted
    assert 'lang="tr">Hacıosman</strong>' in counted
    assert 'lang="tr">Metro İstanbul</span>' in counted
    assert 'rel="noopener"' in counted
    assert 'lang="tr">Hat duyurusu kaynak metni</p>' in line
    missing_agency = node_json("chronic.rowMarkup({...input.zero, agency: null})", {"zero": row(reports=0)}, search="")
    assert "agency_none" not in missing_agency
    assert "Kurum çıkarılamadı" in missing_agency


def test_reports_without_a_list_match_are_only_shown_when_present() -> None:
    payload = {
        "days": 30,
        "total_rows": 0,
        "rows": [],
        "coverage": {"equipment": {"read_days": 4}, "lines": {"read_days": 4}},
        "chronic_min_days": 3,
        "note_codes": [],
        "reports_only": [{"station": "Yenikapı", "reports": 2}],
    }
    markup = node_json("chronic.sectionMarkup(input)", payload)
    empty = node_json("chronic.sectionMarkup({...input, reports_only: []})", payload)

    assert "Listede görülmeyen istasyonlarda vatandaş bildirimi:" in markup
    assert 'lang="tr">Yenikapı (2)</span>' in markup
    assert "Listede görülmeyen istasyonlarda vatandaş bildirimi:" not in empty


def test_copy_text_includes_visible_rows_and_duties_note() -> None:
    payload = {
        "rows": [row() for _ in range(12)],
        "coverage": {"equipment": {"read_days": 1}, "lines": {"read_days": 4}},
    }
    visible, expanded = node_json(
        "[chronic.copyText(input), chronic.copyText(input, true)]",
        payload,
    )

    assert visible.count("Hacıosman") == 10
    assert expanded.count("Hacıosman") == 12
    assert "Arşiv süreksiz" in visible
    assert "Nabız hiçbir ekibe iş atamaz" in visible
    assert "Önerilen kurum: Metro İstanbul" in visible


def test_copy_control_is_quiet_and_only_exists_with_rows() -> None:
    with_rows = {"days": 7, "rows": [row()], "coverage": {"equipment": {}, "lines": {}}, "note_codes": []}
    empty = {"days": 7, "rows": [], "coverage": {"equipment": {}, "lines": {}}, "note_codes": []}
    button_html, empty_html = node_json(
        "[chronic.sectionMarkup(input.with_rows), chronic.sectionMarkup(input.empty)]",
        {"with_rows": with_rows, "empty": empty},
    )

    assert 'id="chronic-copy" class="btn btn-quiet"' in button_html
    assert "btn-primary" not in button_html
    assert 'id="chronic-copy"' not in empty_html


def test_missing_anchor_returns_before_styles_or_fetch() -> None:
    result = node_json(
        "await (async () => { let calls=0; "
        "globalThis.fetch=() => { calls += 1; return Promise.reject(new Error('unexpected')); }; "
        "const doc={visibilityState:'visible', querySelector(){ return null; }}; "
        "const value=await chronic.mountChronic(doc); return {value, calls}; })()",
        search="",
    )

    assert result == {"value": None, "calls": 0}


def test_catalog_matches_every_key_fallback_and_placeholder_in_both_languages() -> None:
    source = JS.read_text(encoding="utf-8")
    fallbacks = ui_calls(source)

    assert set(fallbacks) == set(CATALOG["tr"]) == set(CATALOG["en"])
    assert fallbacks == CATALOG["tr"]
    assert CATALOG["tr"]["ui.chronic.triage_note"] == TRIAGE_NOTE
    for key, turkish in CATALOG["tr"].items():
        assert set(re.findall(r"\{(\w+)\}", turkish)) == set(re.findall(r"\{(\w+)\}", CATALOG["en"][key]))
        assert turkish.strip()
        assert "—" not in turkish and "–" not in turkish


def test_no_bare_turkish_interface_copy_or_forbidden_chronic_claims() -> None:
    source = JS.read_text(encoding="utf-8")
    clean = re.sub(r"/\*.*?\*/|^\s*//.*$", "", source, flags=re.S | re.M)
    fallbacks = [match.span(4) for match in UI_CALL.finditer(clean)]
    literal_source = list(clean)
    for start, end, _chunks in template_literals(clean):
        literal_source[start:end] = [" "] * (end - start)
    literals = "".join(literal_source)
    for match in re.finditer(r"(['\"])((?:\\.|[^\\])*?)\1", literals, flags=re.S):
        value = match.group(2)
        if TURKISH_CHARS.search(value):
            assert any(start <= match.start(2) and match.end(2) <= end for start, end in fallbacks), value
    forbidden = (
        "sürekli", "her gün", "çalışıyor", "düzeldi", "canlı", "ETA", "İBB onaylı",
        "btn-primary", "is-bad", "setInterval",
    )
    for phrase in forbidden:
        assert phrase not in source
    line_markup = node_json("chronic.rowMarkup(input.line)", {"line": row(kind="line")}, search="")
    assert "kullanılamıyor" not in line_markup


def test_css_uses_tokens_and_adds_no_motion_or_fixed_width() -> None:
    source = CSS.read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}|\b(?:rgb|hsl|oklch)\s*\(|\b(?:animation|transition)\s*:", source)
    assert "infinite" not in source
    assert "var(--nd-line)" in source and "var(--surface-raised)" in source
    assert "min-height: 44px" in source and "overflow-wrap: anywhere" in source
    assert "max-width: 100%" in source and "@media (max-width: 480px)" in source


def test_console_bundle_is_not_added_to_other_pages_or_service_worker() -> None:
    for name in ("index.html", "kolay.html", "sw.js"):
        assert "console_chronic" not in (STATIC / name).read_text(encoding="utf-8")


def test_node_syntax() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    result = subprocess.run([node, "--check", str(JS)], capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr
