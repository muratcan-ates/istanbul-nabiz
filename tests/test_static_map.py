"""Static checks for the citizen map module and its local Leaflet distribution."""

from __future__ import annotations

import re
import shutil
import subprocess

from conftest import REPO_ROOT

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
MAP_JS = STATIC / "js" / "map.js"
MAP_CSS = STATIC / "css" / "map.css"
VENDOR = STATIC / "vendor" / "leaflet"


def test_leaflet_distribution_is_vendored_with_license() -> None:
    assert (VENDOR / "leaflet.js").is_file()
    assert (VENDOR / "leaflet.css").is_file()
    assert "BSD 2-Clause License" in (VENDOR / "LICENSE.txt").read_text(encoding="utf-8")
    for name in ("layers-2x.png", "layers.png", "marker-icon-2x.png", "marker-icon.png", "marker-shadow.png"):
        assert (VENDOR / "images" / name).is_file()
    assert 't.version="1.9.4"' in (VENDOR / "leaflet.js").read_text(encoding="utf-8")


def test_map_has_the_local_leaflet_entry_and_point_contract() -> None:
    source = MAP_JS.read_text(encoding="utf-8")
    for exported in ("initMap", "showOnMap", "highlightMarker", "hideMap"):
        assert re.search(rf"\b{exported}\b", source)
    assert "navigator.geolocation.getCurrentPosition" in source
    # 30 Sep: the base is the offline sample map, imported once a map opens; no tile is fetched.
    assert "openstreetmap" not in source.lower() and "tileLayer" not in source
    assert "https://cdn." not in source
    assert "baseSource()" in source and "import('./map_base.js')" in source
    assert "loadStylesheet('/css/map_base.css')" in source
    assert "Harita örnek bir altlıktır ve cihazınızda çizilir; dış harita sunucusuna istek gitmez." in source
    assert 'section.id = \'harita\'' in source
    assert 'id="map-fallback-list"' in source
    assert 'classList.add(\'is-broken\')' in source
    assert "keyboard: false" in source
    assert "html: button" in source



def test_the_first_map_view_frames_every_point() -> None:
    # 30 Sep: with the sample base, opening close on the first station showed only bare land. The first
    # view and every later list now share one framing: one point close, several fitted together.
    source = MAP_JS.read_text(encoding="utf-8")
    create = source[source.index("function createMap()"):source.index("function validPoint(")]
    assert "fitPoints();" in create and "setView([first.lat" not in create
    fit = source[source.index("function fitPoints()"):source.index("function createMap()")]
    assert "points.length === 1" in fit and "map.fitBounds(points.map(" in fit
    show = source[source.index("function showOnMap("):source.index("function hideMap(")]
    assert "fitPoints();" in show and "drawPointList();" in show

def test_map_files_follow_static_text_and_token_rules() -> None:
    text = MAP_JS.read_text(encoding="utf-8") + MAP_CSS.read_text(encoding="utf-8")
    assert "\u2014" not in text and "\u2013" not in text
    assert not re.search(r"\bETA\b", text)
    assert "kanca" not in text.lower()
    colour = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(")
    assert not colour.search(MAP_CSS.read_text(encoding="utf-8"))


def test_map_icon_names_exist_in_the_sprite() -> None:
    source = MAP_JS.read_text(encoding="utf-8")
    sprite = (STATIC / "icons.svg").read_text(encoding="utf-8")
    available = set(re.findall(r'<symbol id="i-([\w-]+)"', sprite))
    used = set(re.findall(r"icon\('([\w-]+)'\)", source))
    assert used
    assert used <= available


def test_map_module_parses() -> None:
    node = shutil.which("node")
    if node is None:
        return
    proc = subprocess.run([node, "--check", str(MAP_JS)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
