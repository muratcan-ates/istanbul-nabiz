"""Contracts for the one-card, large-button citizen page."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any

import httpx
import pytest
from conftest import REPO_ROOT, offline_settings, refuse_network
from fastapi.testclient import TestClient

from ibb_mcp.cache import TTLCache
from ibb_mcp.http import PoliteClient
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
HTML = STATIC / "kolay.html"
JS = STATIC / "js" / "kolay.js"
CSS = STATIC / "css" / "kolay.css"


@pytest.fixture(scope="module")
def nabiz() -> Nabiz:
    return Nabiz(
        SourceContext.create(
            client=PoliteClient(transport=httpx.MockTransport(refuse_network)),
            cache=TTLCache(),
            settings=offline_settings(),
        )
    )


@pytest.fixture
def app_client(nabiz: Nabiz):
    app = build_console_app(
        nabiz=nabiz,
        llm_config=llm.LlmConfig(),
        guard=SpendGuard(BudgetConfig(state_path=None)),
    )
    with TestClient(app) as client:
        yield client


def node_json(source: str) -> Any:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    url = json.dumps(JS.as_uri())
    script = f"import * as easy from {url};\n{source}"
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def css_block(source: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^{}]*)\}", source, flags=re.S)
    assert match, f"missing CSS block: {selector}"
    return match.group(1)


def declarations(block: str) -> dict[str, str]:
    return {name: value.strip() for name, value in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", block)}


def resolve_color(value: str, values: dict[str, str]) -> str:
    seen: set[str] = set()
    while value.startswith("var("):
        name = value[4:-1].strip()
        assert name in values and name not in seen, f"unresolved or cyclic color variable: {name}"
        seen.add(name)
        value = values[name]
    assert re.fullmatch(r"#[0-9a-fA-F]{6}", value), value
    return value


def luminance(color: str) -> float:
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(first: str, second: str) -> float:
    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def test_kolay_page_is_served_with_csp(app_client: TestClient) -> None:
    response = app_client.get("/kolay.html")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert "Resmî İBB hizmeti değildir" in response.text


def test_kolay_page_has_one_h1_two_bands_and_three_actions() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert html.count("<h1") == 1
    assert 'lang="tr"' in html
    assert 'id="kolay-ai-band"' in html
    assert 'id="kolay-sor"' in html and 'id="kolay-durak"' in html
    assert 'id="kolay-call-153" class="kolay-call" href="tel:153"' in html
    assert 'id="kolay-call-112" class="kolay-call-112" href="tel:112"' in html
    assert 'class="skip-link" href="#main"' in html and 'id="main"' in html
    assert 'role="status"' in html and 'aria-live="polite"' in html
    assert 'aria-labelledby="kolay-sor-title"' in html and 'id="kolay-sor-title"' in html
    assert 'aria-labelledby="kolay-durak-title"' in html and 'id="kolay-durak-title"' in html
    assert 'id="kolay-panel-sor"' in html and 'id="kolay-panel-durak"' in html
    assert 'id="chat-form"' in html and 'id="chat-input"' in html and 'id="chat-submit"' in html
    assert 'id="kolay-stop-form"' in html and 'id="kolay-remember"' in html
    assert 'id="kolay-stop-saved"' in html and 'id="chat-log"' in html
    assert 'id="asistan"' not in html


def test_kolay_page_has_no_inline_script_or_handler() -> None:
    html = HTML.read_text(encoding="utf-8")
    scripts = re.findall(r"<script\b[^>]*>", html)
    assert scripts and all(re.search(r"\bsrc=", script) for script in scripts)
    modules = re.findall(r'<script type="module" src="([^"]+)">', html)
    assert modules[:2] == ["/js/kolay.js", "/js/voice.js"]
    assert 'href="/js/kolay.js"' in html
    assert not re.search(r"\son[a-z]+\s*=", html, flags=re.I)
    assert not re.search(r"\sstyle\s*=", html, flags=re.I)
    refs = re.findall(r'(?:href|src)="(/(?:css|js|fonts)/[^"#?]+)"', html)
    assert refs
    assert all((STATIC / ref.lstrip("/")).is_file() for ref in refs)


def test_kolay_files_say_no_eta_no_working_no_dash() -> None:
    dash_glyphs = (chr(0x2014), chr(0x2013))
    for path in (HTML, JS, CSS):
        content = path.read_text(encoding="utf-8")
        assert not re.search(r"\bETA\b", content)
        assert "çalışıyor" not in content.lower()
        assert "logo" not in content.lower()
        assert "İBB onaylı" not in content
        assert all(glyph not in content for glyph in dash_glyphs)


def test_kolay_uses_the_same_chat_and_arrival_lines() -> None:
    source = JS.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")
    assert "'/api/chat?lang=tr'" in source and "'/api/arrival'" in source
    assert "/mock/" not in source
    assert "import('./api.js')" in source and "import('./chat.js')" in source
    assert "{ MOCK, get, stream }" in source and "Örnek veri modu bu sayfada kapalı" in source
    assert "AI_NOTICE" in source and "privacyBandMarkup" in source
    assert "Ben İstanbul şehir bilgi asistanıyım" not in source
    assert "Ben İstanbul şehir bilgi asistanıyım" not in html


def test_answer_markup_quote_is_verbatim() -> None:
    values = node_json(
        "const html=easy.answerMarkup({mode:'quote_only',answer_text:'X',citations:[{quote:'Abonelik için  kimlik gerekir.',"
        "url:'https://www.iski.istanbul/abonelik',title:'Su',fetched_at:'2026-09-25T08:00:00+00:00'}]});"
        "console.log(JSON.stringify(html));"
    )
    assert "Abonelik için  kimlik gerekir." in values
    assert "quote-box" in values


def test_answer_markup_unknown_and_refused_show_fixed_text_and_153() -> None:
    values = node_json(
        "const rows=['unknown','refused'].map(mode=>{const data={mode,citations:[{quote:'Kaynak cümlesi'}]};"
        "return [easy.finalText(data,'U'),easy.answerMarkup(data)];});console.log(JSON.stringify(rows));"
    )
    for text, markup in values:
        assert text == "U"
        assert "tel:153" in markup
        assert "U" not in markup and "cites" not in markup and "Resmî kaynağı aç" not in markup


def test_answer_markup_emergency_leads_with_112() -> None:
    values = node_json(
        "const data={mode:'redirect',emergency:true};const markup=easy.answerMarkup(data);"
        "console.log(JSON.stringify([markup,easy.finalText(data,'U')]));"
    )
    markup, sentence = values
    assert markup.index("tel:112") < markup.index("tel:153")
    assert 'role="alert"' in markup
    assert sentence == "Bu acil bir durum olabilir. Hemen arayın."


def test_arrival_markup_keeps_the_single_minute_rule() -> None:
    values = node_json(
        "const rows=[{display:'7 dk',line:'500T',stop:'ŞİFA SONDURAK',provenance:{age_s:60,mode:'live'}},"
        "{display:'tarifeye göre',line:'500T',stop:'ŞİFA SONDURAK'},"
        "{display:'doğrulanamadı',line:'500T',stop:'<img src=x>'}].map(easy.arrivalMarkup);"
        "console.log(JSON.stringify(rows));"
    )
    assert "7 dk" in values[0]
    assert "Tahmini varış." in values[0]
    for markup, word in zip(values[1:], ("tarifeye göre", "doğrulanamadı"), strict=True):
        minute = re.search(r'<p class="kolay-minute">(.*?)</p>', markup)
        assert minute and minute.group(1) == word
        assert not re.search(r"\d", minute.group(1))
    assert "&lt;img" in values[2]
    assert all("ETA" not in value for value in values)


def test_saved_stop_roundtrip_and_rejects_bad_data() -> None:
    values = node_json(
        "const values=new Map();const storage={getItem:key=>values.get(key)||null,"
        "setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};"
        "easy.saveStop(storage,{line:'500T',stop:'Şifa Sondurak'},'2026-09-25T08:00:00Z');"
        "const saved=easy.readSavedStop(storage);storage.setItem(easy.KOLAY_KEY,'{');const broken=easy.readSavedStop(storage);"
        "storage.setItem(easy.KOLAY_KEY,JSON.stringify({line:'',stop:'Durak'}));const empty=easy.readSavedStop(storage);"
        "storage.setItem(easy.KOLAY_KEY,JSON.stringify({line:'1234567890123',stop:'Durak'}));"
        "const long=easy.readSavedStop(storage);"
        "easy.forgetStop(storage);console.log(JSON.stringify([saved,broken,empty,long,easy.readSavedStop(storage)]));"
    )
    assert values == [{"line": "500T", "stop": "Şifa Sondurak"}, None, None, None, None]


def test_kolay_css_tap_targets_and_answer_size() -> None:
    source = CSS.read_text(encoding="utf-8")
    assert "--kolay-tap: 64px" in source
    assert "min-height: var(--kolay-tap)" in source
    size = re.search(r"--kolay-answer-size:\s*([\d.]+)rem", source)
    assert size and float(size.group(1)) * 16 >= 22
    assert "@media (prefers-color-scheme: dark)" in source
    assert ':root:not([data-theme="light"])' in source
    assert ':root[data-theme="dark"]' in source
    assert "@media (max-width: 359px)" in source
    assert "position: fixed" in source and "bottom: 0" in source


def test_kolay_colour_pairs_meet_seven_to_one() -> None:
    tokens = (STATIC / "css" / "tokens.css").read_text(encoding="utf-8")
    source = CSS.read_text(encoding="utf-8")
    token_values = declarations(css_block(tokens, ":root"))
    dark_tokens = declarations(css_block(tokens, ':root[data-theme="dark"]'))
    easy_light = declarations(css_block(source, ":root"))
    easy_dark = declarations(css_block(source, ':root[data-theme="dark"]'))
    pairs = (("--kolay-bg", "--kolay-ink"), ("--kolay-btn", "--kolay-btn-ink"),
             ("--kolay-call", "--kolay-call-ink"), ("--kolay-danger", "--kolay-danger-ink"))
    for easy_values, token_overrides in ((easy_light, {}), (easy_dark, dark_tokens)):
        values = {**token_values, **token_overrides, **easy_values}
        for foreground, background in pairs:
            first = resolve_color(values[foreground], values)
            second = resolve_color(values[background], values)
            assert contrast(first, second) >= 7.0, (foreground, background, contrast(first, second))
    skip = css_block(source, "body a.skip-link")
    assert "background: var(--kolay-btn)" in skip
    assert "color: var(--kolay-btn-ink)" in skip


def test_render_final_shows_one_sentence_per_card() -> None:
    chat = (STATIC / "js" / "chat.js").read_text(encoding="utf-8")
    unknown_match = re.search(r"const UNKNOWN_TEXT = (.+);", chat)
    assert unknown_match
    unknown = json.loads(unknown_match.group(1))
    chat_url = json.dumps((STATIC / "js" / "chat.js").as_uri())
    source = (
        f"globalThis.window={{location:{{search:''}}}};const chat=await import({chat_url});"
        "const make=()=>{const parts={'.chat-text':{textContent:'Bu konularda cevap üretmiyorum.'},"
        "'.chat-final':{innerHTML:''},'.kolay-progress':{hidden:false}};const attrs={};const classes=[];"
        "return {parts,attrs,classes,li:{querySelector:key=>parts[key],classList:{add:value=>classes.push(value)},"
        "setAttribute:(key,value)=>attrs[key]=value}}};"
        "const refused=make();easy.renderFinal(refused.li,{mode:'refused',refused:true},chat.UNKNOWN_TEXT);"
        "const answer=make();answer.parts['.chat-text'].textContent='A';"
        "easy.renderFinal(answer.li,{mode:'answer',answer_text:'A'},chat.UNKNOWN_TEXT);"
        "const emergency=make();easy.renderFinal(emergency.li,{mode:'redirect',emergency:true},chat.UNKNOWN_TEXT);"
        "console.log(JSON.stringify({refused:refused.parts['.chat-text'].textContent+refused.parts['.chat-final'].innerHTML,"
        "busy:refused.attrs['aria-busy'],answer:answer.parts['.chat-text'].textContent+answer.parts['.chat-final'].innerHTML,"
        "emergency:emergency.parts['.chat-text'].textContent}));"
    )
    values = node_json(source)
    assert values["refused"].count(unknown) == 1
    assert "Bu konularda cevap üretmiyorum." not in values["refused"]
    assert values["busy"] == "false"
    assert values["answer"].count("A") == 1
    assert values["emergency"]
