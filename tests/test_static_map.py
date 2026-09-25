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
    assert "https://tile.openstreetmap.org/{z}/{x}/{y}.png" in source
    assert "https://cdn." not in source
    assert "tileSource()" in source
    assert 'section.id = \'harita\'' in source
    assert 'id="map-fallback-list"' in source
    assert 'classList.add(\'is-broken\')' in source
    assert "keyboard: false" in source
    assert "html: button" in source


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
