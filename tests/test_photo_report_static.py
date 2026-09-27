"""Static and Node-level contracts for the two self-mounting E51 modules."""

from __future__ import annotations

import ast
import json
import pathlib
import re

from test_static_a11y import STATIC, node_json

PHOTO_JS = STATIC / "js" / "photo_report.js"
CONSOLE_JS = STATIC / "js" / "console_photo_reports.js"
PHOTO_CSS = STATIC / "css" / "photo_report.css"
CONSOLE_CSS = STATIC / "css" / "console_photo_reports.css"


def run(tmp_path: pathlib.Path, module: str, body: str, name: str = "photo"):
    url = json.dumps((STATIC / module).as_uri())
    setup = (
        "globalThis.window = {location: {search: '', origin: 'http://localhost'}, "
        "setInterval: () => 1, clearInterval: () => {}};\n"
        f"const {name} = await import({url});\n"
    )
    return node_json(tmp_path, {}, setup + body)


def test_sanitizer_signatures_scaling_and_device_code_storage(tmp_path: pathlib.Path) -> None:
    values = run(
        tmp_path,
        "js/photo_report.js",
        "const bytes = (values) => new Uint8Array(values);"
        "const now=1790000000000, day=86400000;"
        "const items=[{code:'K7M2QX9P',at:now-31*day},{code:'K7M2QX9P',at:now},"
        "...Array.from({length:22},(_,i)=>({code:'ABCDEFGH',at:now-i}))];"
        "console.log(JSON.stringify([photo.sniffPhoto(bytes([255,216,255])),"
        "photo.sniffPhoto(bytes([137,80,78,71,13,10,26,10])),"
        "photo.sniffPhoto(bytes([82,73,70,70,0,0,0,0,87,69,66,80])),"
        "photo.sniffPhoto(bytes([71,73,70,56,57,97])),photo.sniffPhoto(bytes([60,115,118,103])),"
        "photo.fitWithin(4000,3000,1600),photo.fitWithin(240,120,1600),"
        "photo.parseStored('{'),photo.parseStored(JSON.stringify({version:2,items:[]})),"
        "photo.parseStored(JSON.stringify({version:1,items}),now).length,"
        "photo.parseStored(JSON.stringify({version:1,items:[{code:'LLLLLLLL',at:now}]}),now).length,photo.STORAGE_KEY]));",
    )
    assert values == ["jpeg", "png", "webp", None, None, [1600, 1200], [240, 120], [], [], 20, 0,
                      "nabiz.photo-reports.v1"]


def test_citizen_form_is_labeled_single_primary_and_escaped(tmp_path: pathlib.Path) -> None:
    html, card, keys = run(
        tmp_path,
        "js/photo_report.js",
        "const html=photo.formMarkup({categories:[{key:'pavement',tr:'Kaldırım ve yol'}],"
        "districts:['Kartal'],stations:['Kartal']});"
        "const card=photo.cardMarkup({code:'K7M2QX9P',status:'forwarded',category:'<svg>',"
        "place:{name:'<img src=x>'},history:[{status:'forwarded',reason:'<script>alert(1)</script>'}]});"
        "console.log(JSON.stringify([html,card,[Object.keys(photo.COPY.tr).sort(),Object.keys(photo.COPY.en).sort()]]));",
    )
    assert html.count("btn-primary") == 1
    assert html.index("callout-warn") < html.index('id="photo-file"')
    consent = re.search(r'<input[^>]*id="photo-consent"[^>]*>', html)
    assert consent and "checked" not in consent.group()
    controls = re.findall(r'<(input|select|textarea)\b([^>]*)>', html)
    labels = set(re.findall(r'<label\s+for="([^"]+)"', html))
    for _, attributes in controls:
        identifier = re.search(r'\bid="([^"]+)"', attributes)
        assert identifier and identifier.group(1) in labels, attributes
    assert "<svg>" not in card and "<img src=x>" not in card and "<script>" not in card
    assert "&lt;svg&gt;" in card and "&lt;script&gt;" in card
    assert keys[0] == keys[1] and all(value for value in keys[0])


def test_console_detail_has_only_the_next_primary_and_closed_has_no_action(tmp_path: pathlib.Path) -> None:
    open_item = {
        "code": "K7M2QX9P", "status": "new", "category": "pavement", "place": {"kind": "station", "name": "Kartal"},
        "description": "<b>bozuk</b>", "lang": "tr", "masked_count": 1, "created_at": "2026-09-26T10:00:00+00:00",
        "has_photo": True, "photo_meta": {"type": "jpeg", "bytes": 540000, "width": 1600, "height": 1200},
        "history": [{"status": "new", "at": "2026-09-26T10:00:00+00:00", "reason": None}],
    }
    closed = {**open_item, "status": "closed", "has_photo": False}
    output = run(
        tmp_path,
        "js/console_photo_reports.js",
        f"const item={json.dumps(open_item)};const closed={json.dumps(closed)};"
        "console.log(JSON.stringify([consoleReports.detailMarkup(item),consoleReports.detailMarkup(closed),"
        "consoleReports.NEXT_STATUS,consoleReports.listItem(item,item.code)]));",
        "consoleReports",
    )
    detail, closed_detail, next_status, list_html = output
    assert next_status == {"new": "reviewed", "reviewed": "forwarded", "forwarded": "closed", "closed": None}
    assert detail.count("btn-primary") == 1 and "İncelendi olarak işaretle" in detail
    assert 'alt="Vatandaşın gönderdiği fotoğraf: Kaldırım ve yol, Kartal"' in detail
    assert "&lt;b&gt;bozuk&lt;/b&gt;" in detail
    assert "btn-primary" not in closed_detail and 'data-action="transition"' not in closed_detail
    assert 'aria-current="true"' in list_html and "Kaldırım ve yol" in list_html
    source = CONSOLE_JS.read_text(encoding="utf-8")
    assert ".console-nav" not in source and "console.html" not in source


def test_city_district_list_matches_the_shared_handoff_list() -> None:
    tree = ast.parse((STATIC.parent / "photo_reports.py").read_text(encoding="utf-8"))
    server = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                  and any(isinstance(target, ast.Name) and target.id == "PHOTO_DISTRICTS" for target in node.targets))
    handoff = (STATIC / "js" / "handoff.js").read_text(encoding="utf-8")
    match = re.search(r"const ILCELER = Object\.freeze\(\[(.*?)\]\);", handoff, re.S)
    assert match
    citizen = re.findall(r"'([^']*)'", match.group(1))
    assert len(server) == 39 and list(server) == citizen


def test_new_assets_follow_the_page_static_rules() -> None:
    sources = [PHOTO_JS.read_text(encoding="utf-8"), CONSOLE_JS.read_text(encoding="utf-8")]
    styles = [PHOTO_CSS.read_text(encoding="utf-8"), CONSOLE_CSS.read_text(encoding="utf-8")]
    for source in sources:
        for forbidden in ("createObjectURL", "blob:", "http://", "https://", "canlı", "ETA", "\u2014", "\u2013", "scroll"):
            assert forbidden not in source
        endings = (
            "if (typeof document !== 'undefined') mountPhotoReport(document);",
            "if (typeof document !== 'undefined') void mountPhotoReportsConsole(document);",
        )
        assert any(source.rstrip().endswith(ending) for ending in endings)
    colour = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(")
    for css in styles:
        assert not colour.search(re.sub(r"/\*.*?\*/", "", css, flags=re.S))
        assert not re.search(r"\b(?:transition|animation)\s*:", css)
    assert ".console-nav" not in sources[1] and "console.html" not in sources[1]


def test_warning_is_murats_single_sentence_and_claims_no_blurring() -> None:
    source = PHOTO_JS.read_text(encoding="utf-8")
    assert "Fotoğrafta kişi yüzü ya da araç plakası olmamasına dikkat edin." in source
    lowered = source.lower()
    for claim in ("bulanık", "blur", "maskelendi: yüz", "faces are hidden"):
        assert claim not in lowered
