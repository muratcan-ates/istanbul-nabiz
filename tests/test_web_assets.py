"""The page's vendored assets: the Tabler sprite, the favicon, the web font and their licences.

The scripts that build them (``scripts/design/build_icon_sprite.py``, ``build_font_subset.py``) need
a downloaded tarball or font and, for the font, fontTools; these tests need neither. They hold the
committed outputs to the scripts' own lists and to ``tokens.css``, so a hand edit, or a list changed
without a re-run, shows up. The font's cmap and figures are ``check_font.py``'s job (it needs brotli).
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import urllib.parse

import pytest
from conftest import REPO_ROOT

from nabiz.web.main import STATIC_DIR

_spec = importlib.util.spec_from_file_location("build_icon_sprite", REPO_ROOT / "scripts" / "design" / "build_icon_sprite.py")
sprite = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = sprite
_spec.loader.exec_module(sprite)

PAGE = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
HEAD, _, BODY = PAGE.partition("</head>")


def generated(part: str) -> str:
    blocks = re.findall(r"<!-- icons:start -->(.*?)<!-- icons:end -->", part, flags=re.S)
    assert len(blocks) == 1, "one generated icon block in <head> (favicon) and one in <body> (sprite)"
    return blocks[0]


def symbol_ids(svg: str) -> list[str]:
    return re.findall(r'<symbol id="i-([\w-]+)"', svg)


def test_the_inline_sprite_and_icons_svg_hold_exactly_the_scripts_lists() -> None:
    assert symbol_ids(generated(BODY)) == list(sprite.INLINE)
    assert symbol_ids((STATIC_DIR / "icons.svg").read_text(encoding="utf-8")) == list(sprite.EXTERNAL)
    # Tabler's invisible bounding path and per-file stroke attributes were stripped: one CSS rule
    # (.icon in css/base.css) draws every glyph.
    for svg in (generated(BODY), (STATIC_DIR / "icons.svg").read_text(encoding="utf-8")):
        assert 'd="M0 0h24v24H0z"' not in svg and "stroke-width" not in svg


def test_icons_js_sends_the_same_glyphs_inline_and_the_rest_to_icons_svg(tmp_path) -> None:
    source = (STATIC_DIR / "js" / "icons.js").read_text(encoding="utf-8")
    listed = re.search(r"const INLINE = new Set\(\((.*?)\)\.split", source, flags=re.S)
    assert listed, "js/icons.js keeps its INLINE list"
    assert "".join(re.findall(r"'([^']*)'", listed.group(1))).split(" ") == list(sprite.INLINE)

    node = shutil.which("node")
    if node is None:  # pragma: no cover - CI without node still checks the list above
        pytest.skip("node is not installed")
    harness = tmp_path / "icons_harness.mjs"
    url = json.dumps((STATIC_DIR / "js" / "icons.js").as_uri())
    harness.write_text(f"import {{ icon }} from {url};\nconsole.log(JSON.stringify([icon('bus'), icon('car')]));\n")
    proc = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    inline, external = json.loads(proc.stdout)
    assert 'href="#i-bus"' in inline and 'aria-hidden="true"' in inline
    assert 'href="/icons.svg#i-car"' in external


def test_the_favicon_wears_the_primary_button_colours_of_both_themes() -> None:
    link = re.search(r'<link rel="icon" href="data:image/svg\+xml,([^"]*)">', generated(HEAD))
    assert link, "the favicon link is inside the generated head block"
    image = urllib.parse.unquote(link.group(1))
    tokens = sprite.token_values((STATIC_DIR / "css" / "tokens.css").read_text(encoding="utf-8"))
    (fill, ink), (dark_fill, dark_ink) = ([tokens[t] for t in sprite.FAVICON_TOKENS[theme]] for theme in ("light", "dark"))
    assert f"rect{{fill:{fill}}}path{{stroke:{ink}}}" in image
    assert f"@media (prefers-color-scheme:dark){{rect{{fill:{dark_fill}}}path{{stroke:{dark_ink}}}}}" in image
    # The activity glyph, verbatim from the package.
    assert "M3 12h4l3 8l4 -16l3 8h4" in image


def test_the_web_font_is_one_preloaded_woff2_inside_its_budget() -> None:
    font = STATIC_DIR / "fonts" / "nabiz-sans-tr-v1.woff2"
    assert font.read_bytes()[:4] == b"wOF2"
    assert font.stat().st_size <= 60_000
    assert '<link rel="preload" href="/fonts/nabiz-sans-tr-v1.woff2" as="font" type="font/woff2" crossorigin>' in HEAD
    base = (STATIC_DIR / "css" / "base.css").read_text(encoding="utf-8")
    assert 'src: url(/fonts/nabiz-sans-tr-v1.woff2) format("woff2")' in base


def test_the_fallback_face_carries_the_computed_metric_overrides() -> None:
    base = (STATIC_DIR / "css" / "base.css").read_text(encoding="utf-8")
    block = re.findall(r"/\* fallback-metrics:start \*/(.*?)/\* fallback-metrics:end \*/", base, flags=re.S)
    assert len(block) == 1, "build_font_subset.py writes between exactly one pair of markers"
    faces = re.findall(r"@font-face \{[^}]*\}", block[0])
    assert len(faces) == 2  # 400 and 700
    for face in faces:
        assert '"Nabız Sans Fallback"' in face and "font-display: swap" in face
        for descriptor in ("size-adjust", "ascent-override", "descent-override", "line-gap-override"):
            assert re.search(rf"{descriptor}: \d+\.\d\d%;", face), descriptor


def test_each_vendored_asset_ships_with_its_licence() -> None:
    ofl = (STATIC_DIR / "fonts" / "OFL.txt").read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE Version 1.1" in ofl
    assert "with Reserved Font Name 'Source'" in ofl  # why the subset is renamed
    mit = (STATIC_DIR / "icons.LICENSE.txt").read_text(encoding="utf-8")
    assert mit.startswith("MIT License") and "Copyright (c) 2020-2026 Paweł Kuna" in mit
    notice = (REPO_ROOT / "NOTICE.md").read_text(encoding="utf-8")
    for name in ("Source Sans 3", "Tabler Icons", "MapLibre GL JS", "OpenStreetMap"):
        assert name in notice, name
