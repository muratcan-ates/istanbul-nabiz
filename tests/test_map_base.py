"""The offline sample base map: no map server is asked for anything, and no station falls into the sea.

On 30 Sep the owner's browser showed OpenStreetMap's "Access blocked" tiles on every map, so the three
Leaflet maps (the citizen map, the chat map card and the operator's report map) draw a sample base in the
browser instead (``js/map_base.js``). Its shapes are approximate; these tests keep the places the demo can
show on land and keep every map drawing its markers.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess

import pytest
from conftest import REPO_ROOT

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
BASE_JS = STATIC / "js" / "map_base.js"
BASE_CSS = STATIC / "css" / "map_base.css"
MAPS = ("map.js", "chat_card_map.js", "console_report_map.js")
PLACES = REPO_ROOT / "data" / "reference" / "places.csv"
IBB_PLACES = REPO_ROOT / "data" / "reference" / "ibb_places"


def node() -> str:
    path = shutil.which("node")
    if path is None:
        pytest.skip("node is not installed")
    return path


def run_module(tmp_path, body: str) -> dict:
    script = tmp_path / "map_base_harness.mjs"
    script.write_text(f"const base = await import({json.dumps(BASE_JS.as_uri())});\n{body}\n", encoding="utf-8")
    result = subprocess.run([node(), str(script)], capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def inside(lat: float, lon: float, ring: list[list[float]]) -> bool:
    hit = False
    for (lat1, lon1), (lat2, lon2) in zip(ring, ring[-1:] + ring[:-1], strict=True):
        if (lat1 > lat) != (lat2 > lat) and lon < lon1 + (lat - lat1) * (lon2 - lon1) / (lat2 - lat1):
            hit = not hit
    return hit


def in_sea(sea: list, lat: float, lon: float) -> bool:
    return any(inside(lat, lon, rings[0]) and not any(inside(lat, lon, hole) for hole in rings[1:]) for rings in sea)


@pytest.fixture(scope="module")
def shapes(tmp_path_factory) -> dict:
    return run_module(tmp_path_factory.mktemp("base"), "console.log(JSON.stringify({sea: base.SEA, districts: base.DISTRICTS}));")


def test_no_map_tile_server_is_named_in_the_console_source() -> None:
    sources = [path for path in (STATIC / "js").glob("*.js")] + [STATIC / "sw.js", REPO_ROOT / "src/nabiz/console/app.py"]
    sources += list(STATIC.glob("*.html")) + list((STATIC / "i18n").glob("*.json"))
    for path in sources:
        text = path.read_text(encoding="utf-8")
        assert "tile.openstreetmap.org" not in text, path.name
        assert "OpenStreetMap" not in text, path.name
    for name in MAPS:
        source = (STATIC / "js" / name).read_text(encoding="utf-8")
        assert "tileLayer" not in source and "import('./map_base.js')" in source and "mockBase" in source, name


def test_every_station_and_place_stays_on_land(shapes) -> None:
    sea = shapes["sea"]
    for lat, lon, name in (
        (40.9, 28.9, "Marmara"),
        (41.07, 29.053, "Bosphorus"),
        (41.03, 28.957, "Golden Horn"),
        (41.4, 29.0, "Black Sea"),
        (41.021, 29.004, "Maiden's Tower"),
    ):
        assert in_sea(sea, lat, lon), name
    with PLACES.open(encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle) if row["lat"] and row["lon"]]
    assert len(rows) > 250
    wet = [row["name"] for row in rows if in_sea(sea, float(row["lat"]), float(row["lon"]))]
    assert not wet, wet
    wet_labels = [name for name, lat, lon in shapes["districts"] if in_sea(sea, lat, lon)]
    assert not wet_labels, wet_labels


def test_ibb_places_stay_on_land(shapes) -> None:
    files = sorted(IBB_PLACES.glob("*.json"))
    if not files:
        pytest.skip("İBB place layers are not in this checkout")
    checked, wet = 0, []
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        lat_at, lon_at = data["columns"].index("lat"), data["columns"].index("lon")
        for row in data["rows"]:
            lat, lon = row[lat_at], row[lon_at]
            if isinstance(lat, int | float) and isinstance(lon, int | float):
                checked += 1
                if in_sea(shapes["sea"], lat, lon):
                    wet.append((path.stem, row[0]))
    assert checked > 1000
    assert not wet, wet


def test_mock_base_builds_quiet_layers_and_names_itself(tmp_path) -> None:
    values = run_module(
        tmp_path,
        r"""
const panes = {}, calls = {polygons: [], labels: []};
globalThis.document = {querySelector() { return null; }, head: {append(node) { calls.style = node.href; }},
  createElement(tag) { return {tag, textContent: '', rel: '', href: ''}; }};
const classes = [];
const map = {getContainer() { return {classList: {add(name) { classes.push(name); }}}; },
  getPane(name) { return panes[name]; },
  createPane(name) { panes[name] = {style: {}, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }}; return panes[name]; },
  on(event) { calls.on = event; }, getZoom() { return 8; }};
const L = {
  polygon(rings, options) { calls.polygons.push(options); return {kind: 'sea'}; },
  divIcon(options) { return options; },
  marker(at, options) { calls.labels.push({text: options.icon.html.textContent, interactive: options.interactive,
    keyboard: options.keyboard, pane: options.pane}); return {kind: 'label'}; },
  layerGroup(layers, options) { return {count: layers.length, attribution: options.attribution}; },
};
const group = base.mockBase(L, map, {attribution: '<b>Örnek</b>'});
console.log(JSON.stringify({group, classes, style: calls.style, on: calls.on, polygons: calls.polygons,
  labels: calls.labels, panes: Object.fromEntries(Object.entries(panes).map(([k, v]) => [k, {hidden: !!v.hidden,
  aria: v.attrs['aria-hidden'], pointer: v.style.pointerEvents}])), note: base.BASE_NOTE}));
""",
    )
    assert values["group"] == {"count": 3 + 12, "attribution": "&lt;b&gt;Örnek&lt;/b&gt;"}
    assert values["classes"] == ["map-base"] and values["style"] == "/css/map_base.css" and values["on"] == "zoomend"
    for shape in values["polygons"]:
        assert shape["interactive"] is False and shape["className"] == "map-base-sea" and shape["stroke"] is False
    assert all(label["interactive"] is False and label["keyboard"] is False for label in values["labels"])
    assert {label["text"] for label in values["labels"]} >= {"Fatih", "Kadıköy", "Üsküdar", "Beşiktaş", "Pendik"}
    assert values["panes"]["nabizBaseSea"] == {"hidden": False, "aria": "true", "pointer": "none"}
    # Below zoom 11 the district names would pile up, so their pane hides.
    assert values["panes"]["nabizBaseLabels"] == {"hidden": True, "aria": "true", "pointer": "none"}
    assert values["note"] == "Örnek harita altlığı; kıyılar yaklaşık"


def test_every_map_still_draws_its_markers() -> None:
    citizen = (STATIC / "js" / "map.js").read_text(encoding="utf-8")
    assert "window.L.marker([first.lat, first.lon]" in citizen and "baseSource().addTo(map)" in citizen
    assert "drawMarkers();" in citizen and 'id="map-fallback-list"' in citizen
    card = (STATIC / "js" / "chat_card_map.js").read_text(encoding="utf-8")
    assert "window.L.marker([point.lat, point.lon])" in card and "baseModule.mockBase(window.L, map" in card
    report = (STATIC / "js" / "console_report_map.js").read_text(encoding="utf-8")
    assert "window.L.circleMarker(point" in report and "baseSource().addTo(map)" in report


def test_base_files_follow_the_static_rules() -> None:
    script = BASE_JS.read_text(encoding="utf-8")
    css = BASE_CSS.read_text(encoding="utf-8")
    colour = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(")
    assert not colour.search(script) and not colour.search(re.sub(r"/\*.*?\*/", "", css, flags=re.S))
    assert "\u2014" not in script + css and "\u2013" not in script + css
    assert "fetch(" not in script and "https://" not in script
    assert ':root[data-theme="dark"]' in css and "prefers-color-scheme: dark" in css and "forced-colors" in css
    shell = (STATIC / "sw.js").read_text(encoding="utf-8")
    assert "'/js/map_base.js', '/css/map_base.css'" in shell
    # Dynamic imports only: the base stays out of the citizen page's first-visit closure.
    for name in MAPS:
        source = (STATIC / "js" / name).read_text(encoding="utf-8")
        assert not re.search(r"^import .*map_base", source, flags=re.M), name
