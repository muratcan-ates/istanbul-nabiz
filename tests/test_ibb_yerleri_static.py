"""Static, language and pure-function contracts for the İBB places panel."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from conftest import REPO_ROOT

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
VIEW = STATIC / "js" / "ibb_yerleri_view.js"
MODULE = STATIC / "js" / "ibb_yerleri.js"
CSS = STATIC / "css" / "ibb_yerleri.css"

CATALOG = {
    "tr": {
        "ui.ibbplaces.address_missing": "Adres kayıtta yok.",
        "ui.ibbplaces.captured_date": "Nabız'a alındı",
        "ui.ibbplaces.category.halk_ekmek": "Halk Ekmek büfeleri",
        "ui.ibbplaces.category.kent_lokantasi": "Kent Lokantaları",
        "ui.ibbplaces.category.sosyal_tesis": "İBB sosyal tesisleri",
        "ui.ibbplaces.category.wifi": "ibbWiFi noktaları",
        "ui.ibbplaces.category_count": "{count} kayıt · veri tarihi {date}",
        "ui.ibbplaces.category_legend": "Ne görmek istersiniz?",
        "ui.ibbplaces.closed": "Kapalı",
        "ui.ibbplaces.data_date": "veri tarihi",
        "ui.ibbplaces.date_unknown": "kayıtta yok",
        "ui.ibbplaces.disclaimer": "Resmî İBB hizmeti değildir.",
        "ui.ibbplaces.district_result": "{district}'de {count} {category} kaydı; haritada {shown} nokta.",
        "ui.ibbplaces.empty": "Bu bölgede kayıt yok. Başka bir ilçe seçebilirsiniz.",
        "ui.ibbplaces.error": "İBB yerleri şu an okunamadı.",
        "ui.ibbplaces.intro": (
            "Halk Ekmek büfeleri, Kent Lokantaları, İBB sosyal tesisleri ve ibbWiFi noktaları; İBB Açık Veri'den kayıtlı liste."
        ),
        "ui.ibbplaces.license": "Lisans",
        "ui.ibbplaces.list_unavailable": "Bu liste alınamadı.",
        "ui.ibbplaces.loading_short": "veri okunuyor",
        "ui.ibbplaces.location_error": "Konumunuz alınamadı. İlçe seçerek bakabilirsiniz.",
        "ui.ibbplaces.mock": "Örnek: sunucu bağlı değil.",
        "ui.ibbplaces.nearby": "Konumuma yakın",
        "ui.ibbplaces.nearby_result": "Konumunuza yakın {count} {category} kaydı; haritada {shown} nokta.",
        "ui.ibbplaces.no_live_info": "Anlık doluluk ve açılış saati bu veride yok.",
        "ui.ibbplaces.open_dataset": "Veri setini aç",
        "ui.ibbplaces.open_license": "Lisansı aç",
        "ui.ibbplaces.other_layer": "Harita şu an başka bir katmanı gösteriyor.",
        "ui.ibbplaces.outside_istanbul": "Bu konum İstanbul aralığında değil. İlçe seçerek bakabilirsiniz.",
        "ui.ibbplaces.results_title": "Haritadaki kayıtlar",
        "ui.ibbplaces.retry": "Yeniden dene",
        "ui.ibbplaces.show": "Haritada göster",
        "ui.ibbplaces.source_brand": "İBB Açık Veri",
        "ui.ibbplaces.source_title_unknown": "Veri seti adı kayıtta yok",
        "ui.ibbplaces.sources_summary": "Bu veri nereden?",
        "ui.ibbplaces.stale_note": "Bu kayıt eski; nokta değişmiş olabilir.",
        "ui.ibbplaces.title": "İBB yerleri",
        "ui.ibbplaces.truncated_district": "Bu ilçede 60'tan fazla kayıt var; ilk 60 kayıt haritada gösteriliyor.",
        "ui.ibbplaces.truncated_nearby": "Yakınınızda 60 kayıttan fazlası var; en yakın 60 kayıt haritada.",
        "ui.ibbplaces.unavailable_short": "alınamadı",
        "ui.ibbplaces.where_label": "Nerede?",
    },
    "en": {
        "ui.ibbplaces.address_missing": "No address is in this record.",
        "ui.ibbplaces.captured_date": "added to Nabız",
        "ui.ibbplaces.category.halk_ekmek": "Halk Ekmek kiosks",
        "ui.ibbplaces.category.kent_lokantasi": "Kent Lokantaları",
        "ui.ibbplaces.category.sosyal_tesis": "İBB social facilities",
        "ui.ibbplaces.category.wifi": "ibbWiFi locations",
        "ui.ibbplaces.category_count": "{count} records · data date {date}",
        "ui.ibbplaces.category_legend": "What would you like to see?",
        "ui.ibbplaces.closed": "Off",
        "ui.ibbplaces.data_date": "data date",
        "ui.ibbplaces.date_unknown": "not in the record",
        "ui.ibbplaces.disclaimer": "This is not an official İBB service.",
        "ui.ibbplaces.district_result": "{count} {category} records in {district}; {shown} points on the map.",
        "ui.ibbplaces.empty": "There are no records in this area. You can choose another district.",
        "ui.ibbplaces.error": "İBB places could not be read.",
        "ui.ibbplaces.intro": (
            "Recorded lists from İBB Open Data: Halk Ekmek kiosks, Kent Lokantaları, İBB social facilities and ibbWiFi locations."
        ),
        "ui.ibbplaces.license": "Licence",
        "ui.ibbplaces.list_unavailable": "This list could not be obtained.",
        "ui.ibbplaces.loading_short": "reading records",
        "ui.ibbplaces.location_error": "Your location could not be read. You can choose a district instead.",
        "ui.ibbplaces.mock": "Example: server is not connected.",
        "ui.ibbplaces.nearby": "Near my location",
        "ui.ibbplaces.nearby_result": "{count} {category} records near you; {shown} points on the map.",
        "ui.ibbplaces.no_live_info": "These records do not include occupancy or opening hours.",
        "ui.ibbplaces.open_dataset": "Open dataset",
        "ui.ibbplaces.open_license": "Open licence",
        "ui.ibbplaces.other_layer": "The map is showing another layer now.",
        "ui.ibbplaces.outside_istanbul": "This location is outside the İstanbul search area. You can choose a district.",
        "ui.ibbplaces.results_title": "Recorded places on the map",
        "ui.ibbplaces.retry": "Try again",
        "ui.ibbplaces.show": "Show on map",
        "ui.ibbplaces.source_brand": "İBB Open Data",
        "ui.ibbplaces.source_title_unknown": "Dataset name is not in the record",
        "ui.ibbplaces.sources_summary": "Where is this data from?",
        "ui.ibbplaces.stale_note": "This record is old; the location may have changed.",
        "ui.ibbplaces.title": "İBB places",
        "ui.ibbplaces.truncated_district": "There are more than 60 records in this district; the first 60 are on the map.",
        "ui.ibbplaces.truncated_nearby": "There are more than 60 nearby records; the closest 60 are on the map.",
        "ui.ibbplaces.unavailable_short": "unavailable",
        "ui.ibbplaces.where_label": "Where?",
    },
}


def node_json(expression: str, payload: object | None = None) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = (
        "import fs from 'node:fs';\n"
        "const input = JSON.parse(fs.readFileSync(0, 'utf8'));\n"
        f"const output = await (async () => {{ {expression} }})();\n"
        "console.log(JSON.stringify(output));\n"
    )
    result = subprocess.run(
        [node, "--experimental-default-type=module", "--input-type=module", "-e", script],
        input=json.dumps(payload or {}, ensure_ascii=False),
        capture_output=True,
        text=True,
        cwd=STATIC,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_pure_helpers_keep_search_rounded_and_source_date_honest() -> None:
    view_url = VIEW.as_uri()
    values = node_json(
        f"const view=await import({json.dumps(view_url)}); return ({'{'}box:view.searchBox(41.001,29.001,0.004),"
        "date:view.dateLabel('2023-03-15T21:11:55+00:00'),"
        "stale:view.isStale('2023-03-15T21:11:55+00:00','2026-09-27T00:00:00Z'),"
        "distances:[view.distanceText(350),view.distanceText(1200)]})"
    )
    assert values == {
        "box": {"minLon": 28.99, "minLat": 40.99, "maxLon": 29.01, "maxLat": 41.01},
        "date": "15.03.2023",
        "stale": True,
        "distances": ["350 m", "1,2 km"],
    }


def test_rows_are_escaped_source_dated_and_linked_to_the_same_map_card() -> None:
    view_url = VIEW.as_uri()
    point = {
        "id": "halk_ekmek-7",
        "name": "Ada <b>Yeri</b>",
        "district": "Kadıköy",
        "address": "Mahalle & sokak",
        "lat": 41.0,
        "lon": 29.0,
    }
    source = {
        "title": "İstanbul Halk Ekmek",
        "dataset_url": "https://data.ibb.gov.tr/dataset/test",
        "license": "İBB Açık Veri Lisansı",
        "resource_last_modified": "2026-02-10T11:19:59+00:00",
        "captured_at": "2026-09-27T00:46:24+00:00",
        "stale": False,
    }
    values = node_json(
        f"const view=await import({json.dumps(view_url)}); return ({'{'}"
        "rows:view.rowsMarkup({points:[input.point],source:input.source},null),"
        "map:view.mapPoints([input.point],null)})",
        {"point": point, "source": source},
    )
    row = values["rows"]
    assert '<details id="iy-halk_ekmek-7">' in row
    assert '<span lang="tr">Ada &lt;b&gt;Yeri&lt;/b&gt;</span>' in row
    assert "Mahalle &amp; sokak" in row
    assert "2026" in row and "İBB Açık Veri Lisansı" in row
    assert values["map"] == [
        {"lat": 41, "lon": 29, "label": "Ada <b>Yeri</b> · Kadıköy", "kind": "place", "card": "iy-halk_ekmek-7"}
    ]


def test_markup_has_closed_by_default_controls_and_a_visible_disclaimer() -> None:
    info = {"categories": [], "districts": ["Kadıköy"]}
    view_url = VIEW.as_uri()
    markup = node_json(
        f"const view=await import({json.dumps(view_url)}); return view.sectionMarkup(input.info,'tr')", {"info": info}
    )
    assert '<section id="ibb-yerleri"' in markup
    assert 'value="closed" checked' in markup
    assert 'id="ibb-yerleri-where"' in markup and 'id="ibb-yerleri-show"' in markup
    assert 'role="status" aria-live="polite"' in markup
    assert markup.count('role="status"') == 1
    assert "Resmî İBB hizmeti değildir." in markup
    assert '<option value="Kadıköy" lang="tr">Kadıköy</option>' in markup


def test_map_conversion_caps_to_the_same_points_and_sorts_nearby_rows() -> None:
    view_url = VIEW.as_uri()
    points = [
        {"id": "halk_ekmek-1", "name": "Uzak", "district": "Kadıköy", "address": "", "lat": 41.01, "lon": 29.01},
        {"id": "halk_ekmek-2", "name": "Yakın", "district": "Kadıköy", "address": "", "lat": 41.001, "lon": 29.001},
    ]
    values = node_json(
        f"const view=await import({json.dumps(view_url)}); return ({'{'}map:view.mapPoints(input.points,input.user),"
        "rows:view.rowsMarkup({points:input.points,source:{}},input.user)})",
        {"points": points, "user": {"lat": 41.0, "lon": 29.0}},
    )
    assert values["map"][0]["card"] == "iy-halk_ekmek-2"
    assert values["map"][0]["kind"] == "place"
    assert values["rows"].index("halk_ekmek-2") < values["rows"].index("halk_ekmek-1")


def test_catalogs_are_bilingual_and_cover_exactly_the_module_keys() -> None:
    assert set(CATALOG["tr"]) == set(CATALOG["en"])
    keys = set(
        re.findall(r"ui\.ibbplaces\.[A-Za-z0-9_.]+", VIEW.read_text(encoding="utf-8") + MODULE.read_text(encoding="utf-8"))
    )
    assert keys == set(CATALOG["tr"])
    assert all(CATALOG[language][key].strip() for language in ("tr", "en") for key in keys)


def test_module_exports_and_does_not_fetch_without_a_dom_anchor() -> None:
    module_url = MODULE.as_uri()
    values = node_json(
        f"globalThis.window={{location:{{search:''}}}}; let calls=0; globalThis.fetch=()=>{{calls+=1;}}; "
        f"const mod=await import({json.dumps(module_url)}); "
        "return {anchors:mod.ANCHORS,style:mod.STYLESHEET,id:mod.SECTION_ID,calls}"
    )
    assert values == {
        "anchors": ["harita-katmanlari", "harita", "map-space"],
        "style": "/css/ibb_yerleri.css",
        "id": "ibb-yerleri",
        "calls": 0,
    }


def test_modules_and_css_follow_the_no_storage_no_motion_no_colour_literal_rules() -> None:
    view, module, css = (path.read_text(encoding="utf-8") for path in (VIEW, MODULE, CSS))
    combined = view + module
    for forbidden in ("btn-primary", "setInterval", "localStorage"):
        assert forbidden not in combined
    assert not re.search(r"addEventListener\(\s*['\"]scroll", combined)
    assert "fetch(" not in combined
    assert "get('/api/ibb-places')" in module
    assert "`/api/ibb-places/${category}`" in module
    assert re.search(r"#[\da-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", css) is None
    assert "var(--bad)" not in css and "infinite" not in css
    assert "min-height: 44px" in css and "overflow-wrap: anywhere" in css
    visible = re.sub(r"/\*[\s\S]*?\*/|//[^\n]*", "", combined)
    visible = re.sub(r"ui\.ibbplaces\.[A-Za-z0-9_.]+|aria-live", "", visible)
    visible += " ".join(CATALOG[language][key] for language in CATALOG for key in CATALOG[language])
    assert "\u2014" not in visible and "\u2013" not in visible
    assert not re.search(r"\b(canlı|live|kafe|açık şu an)\b", visible, re.I)
    assert "Resmî İBB hizmeti değildir." in visible


def test_javascript_parses_and_icon_references_exist_in_the_sprite() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    for path in (VIEW, MODULE):
        result = subprocess.run(
            [node, "--check", "--experimental-default-type=module", str(path)], capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, result.stderr
    sprite = (STATIC / "icons.svg").read_text(encoding="utf-8")
    used = set(re.findall(r"icon\('([\w-]+)'\)", VIEW.read_text() + MODULE.read_text()))
    available = set(re.findall(r'<symbol id="i-([\w-]+)"', sprite))
    assert used <= available


def test_owned_module_keys_are_absent_from_files_owned_by_other_lanes() -> None:
    for relative in (
        "src/nabiz/console/static/js/map.js",
        "src/nabiz/console/static/js/map_layers.js",
        "src/nabiz/console/static/index.html",
        "src/nabiz/console/static/sw.js",
        "src/nabiz/console/static/js/home.js",
    ):
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "ibb_yerleri" not in source and "ibb-places" not in source
    # P00 G3 wired the back end: app.py now names the router, and nothing else of E79.
    app = (REPO_ROOT / "src/nabiz/console/app.py").read_text(encoding="utf-8")
    assert "from nabiz.console.ibb_yerleri_api import ibb_yerleri_routes" in app and "ibb-places" not in app
