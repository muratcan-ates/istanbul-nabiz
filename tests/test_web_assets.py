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
CONSOLE_STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"


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


def test_provenance_exports_shared_translations_and_how_panel(tmp_path) -> None:
    source = (CONSOLE_STATIC / "js" / "provenance.js").read_text(encoding="utf-8")
    chat = (CONSOLE_STATIC / "js" / "chat.js").read_text(encoding="utf-8")
    assert "AUTHOR_TR" in source and "TOOL_TR" in source
    assert "metro_equipment_signals" in source and "check_alerts" in source
    assert not re.search(r"const\s+(?:TOOL_TR|AUTHOR_TR)\s*=", chat)
    assert "import { AUTHOR_TR, TOOL_TR" in chat

    node = shutil.which("node")
    if node is None:  # pragma: no cover - CI without node still checks the source contract above
        pytest.skip("node is not installed")
    module = json.dumps((CONSOLE_STATIC / "js" / "provenance.js").as_uri())
    harness = tmp_path / "provenance_harness.mjs"
    harness.write_text(
        f"import {{ howPanel }} from {module};\n"
        "console.log(howPanel({tool:'metro_equipment_signals',source_url:'https://example.test/source',"
        "observed_at:'2026-09-25T09:00:00Z',rule_id:'R-03',signal_id:'sig-1',"
        "uncertainty:['recorded_data'],latency_ms:12.8},'card-1'));\n",
        encoding="utf-8",
    )
    proc = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    for expected in (
        '<details id="card-1-how">', 'Bu nasıl bulundu?',
        'Metro ekipman sinyalleri (metro_equipment_signals)', 'https://example.test/source',
        'Kayıt zamanı:', 'R-03', 'recorded_data', 'Sistem gecikmesi: 12 ms',
    ):
        assert expected in proc.stdout

    empty = tmp_path / "empty_how_harness.mjs"
    empty.write_text(
        f"import {{ howPanel }} from {module};\n"
        "console.log(howPanel({tools:[],tool_calls:0,elapsed_s:0,latency_ms:1,"
        "rule_id:null,uncertainty:[]},'quote-1'));\n",
        encoding="utf-8",
    )
    proc = subprocess.run([node, str(empty)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "Araç: bilinmiyor" in proc.stdout


def test_answer_cards_keep_quotes_exact_and_hide_unknown_sources(tmp_path) -> None:
    node = shutil.which("node")
    if node is None:  # pragma: no cover - CI without node still checks the static tests
        pytest.skip("node is not installed")
    module = json.dumps((CONSOLE_STATIC / "js" / "chat.js").as_uri())
    harness = tmp_path / "answer_card_harness.mjs"
    harness.write_text(
        "globalThis.window = { location: { search: '', origin: 'http://localhost' } };\n"
        f"const {{ answerCard }} = await import({module});\n"
        "const how = {tools:[],tool_calls:0,elapsed_s:0.2,latency_ms:2,rule_id:null,uncertainty:[]};\n"
        "const quote = 'Kaynak cümlesi aynen korunur.';\n"
        "const citations = [{institution:'İBB',title:'Örnek',url:'https://example.ibb.gov.tr/ornek',"
        "quote,fetched_at:'2026-09-25T10:00:00Z',source_updated_at:null}];\n"
        "const quoteHtml = answerCard({mode:'quote_only',answer_text:'Kısa yanıt.',author:'kural',"
        "citations,steps:null,how},'quote-check');\n"
        "const unknown = answerCard({mode:'unknown',answer_text:'ignored',author:'kural',"
        "citations,steps:['ignored'],how},'unknown-check');\n"
        "const emergency = answerCard({mode:'redirect',emergency:true,how},'emergency-check');\n"
        "const guard = answerCard({mode:'guard',refused:true,answer_text:'Bu isteği yerine getiremem.',author:'kural',"
        "citations:[],how},'guard-check');\n"
        "console.log(JSON.stringify({quoteHtml,unknown,emergency,guard}));\n",
        encoding="utf-8",
    )
    proc = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert '<blockquote class="quote-exact">Kaynak cümlesi aynen korunur.</blockquote>' in result["quoteHtml"]
    assert "Bu nasıl bulundu?" in result["quoteHtml"]  # the empty-tool provenance panel must render
    assert 'href="tel:153"' in result["unknown"]
    assert all(part not in result["unknown"] for part in ("KAYNAK", "NASIL YAPILIR", "Bu nasıl bulundu?", "chat-foot"))
    assert 'href="tel:112"' in result["emergency"] and 'href="tel:153"' in result["emergency"]
    # The emergency card carries the "how was this found" panel outside its alert box (E38, decision 6);
    # the legacy unknown path above still does not.
    assert "Bu nasıl bulundu?" in result["emergency"]
    assert result["emergency"].index("Bu nasıl bulundu?") > result["emergency"].index("</div></div></div>")
    # E16's input guard: its plain sentence and 153, nothing that suggests a sourced answer.
    assert "Bu isteği yerine getiremem." in result["guard"] and 'href="tel:153"' in result["guard"]
    hidden = ("KAYNAK", "Kaynak yok", "cevabı yazan", "feedback-slot", "Bu nasıl bulundu?")
    assert all(part not in result["guard"] for part in hidden)


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
