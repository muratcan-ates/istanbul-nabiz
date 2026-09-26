# Adapted from DOU-Synapse apps/web/lib/accessibility.test.ts (MIT, Copyright (c) 2026 Muratcan Ates).
from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from conftest import REPO_ROOT

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"


def node_json(tmp_path, modules: dict[str, str], body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    imports = "\n".join(
        f"import * as {name} from {json.dumps((STATIC / path).as_uri())};" for name, path in modules.items()
    )
    harness = tmp_path / "a11y_harness.mjs"
    harness.write_text(f"{imports}\n{body}\n", encoding="utf-8")
    result = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_a11y_prefs_reject_bad_json_unknown_versions_and_wrong_types(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"a11y": "js/a11y.js"},
        "const bad = [null, '', '{', '[]', '{\"version\":2}', '{\"version\":1,\"text\":\"large\"}'];"
        "const valid = a11y.parsePrefs(JSON.stringify({version:1,text:125,contrast:'more',motion:'reduce',extra:true}));"
        "console.log(JSON.stringify([bad.map(a11y.parsePrefs), valid]));",
    )
    defaults = {"version": 1, "text": 100, "contrast": "standard", "motion": "system"}
    assert values[0] == [defaults] * 6
    assert values[1] == {"version": 1, "text": 125, "contrast": "more", "motion": "reduce"}


def test_a11y_apply_writes_the_three_root_attributes_and_system_motion_wins(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"a11y": "js/a11y.js"},
        "const attrs = {}; const root = {setAttribute: (key, value) => { attrs[key] = value; }};"
        "a11y.applyPrefs({version:1,text:150,contrast:'more',motion:'system'}, true, root);"
        "const system = {...attrs}; a11y.applyPrefs({version:1,text:125,contrast:'standard',motion:'reduce'}, false, root);"
        "console.log(JSON.stringify([system, attrs]));",
    )
    assert values == [
        {"data-text-scale": "150", "data-contrast": "more", "data-motion": "reduce"},
        {"data-text-scale": "125", "data-contrast": "standard", "data-motion": "reduce"},
    ]


def test_a11y_shortcuts_need_alt_shift_and_map_by_code(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"a11y": "js/a11y.js"},
        "const key = (code, extras={}) => a11y.shortcut({code,altKey:true,shiftKey:true,isComposing:false,...extras});"
        "console.log(JSON.stringify([key('KeyB'),key('KeyK'),key('KeyH'),key('KeyS'),key('KeyE'),"
        "a11y.shortcut({code:'KeyB',altKey:false,shiftKey:true}),"
        "a11y.shortcut({code:'KeyB',altKey:true,shiftKey:false}),key('KeyB',{isComposing:true}),key('KeyQ')]));",
    )
    assert values == ["text", "contrast", "motion", "simple", "panel", None, None, None, None]


def test_a11y_css_remaps_tokens_for_contrast_and_guards_motion_without_colour_literals() -> None:
    css = (STATIC / "css" / "a11y.css").read_text(encoding="utf-8")
    for selector in (
        ':root[data-contrast="more"]',
        ':root:not([data-theme="light"])[data-contrast="more"]',
        ':root[data-theme="dark"][data-contrast="more"]',
    ):
        assert selector in css
    assert "--text: var(--neutral-1000)" in css
    assert "--text: var(--neutral-0)" in css
    assert "--border: var(--neutral-600)" in css
    assert "--border: var(--neutral-400)" in css
    assert "--link: var(--primary-900)" in css
    assert "--link: var(--primary-200)" in css
    assert ':root[data-motion="reduce"]' in css and "animation-duration: .001ms !important" in css
    assert ':root[data-text-scale="125"] { font-size: 125%; }' in css
    assert ':root[data-text-scale="150"] { font-size: 150%; }' in css
    colour = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(")
    assert not colour.search(re.sub(r"/\*.*?\*/", "", css, flags=re.S))


def test_feedback_counts_on_device_and_payload_has_exactly_three_fields(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"feedback": "js/feedback.js"},
        "const base={version:1,up:0,down:0,reasons:{wrong:0,stale:0,misunderstood:0,other:0},share:false};"
        "const next=feedback.countFeedback(base,'down','stale');"
        "const payload=feedback.feedbackPayload('a-0123456789abcdef','down','stale');"
        "const up=feedback.feedbackPayload('a-0123456789abcdef','up',null);"
        "console.log(JSON.stringify({base,next,payload,up,ids:[feedback.newAnswerId(),feedback.newAnswerId()]}));",
    )
    assert values["base"]["down"] == 0
    assert values["next"]["down"] == 1 and values["next"]["reasons"]["stale"] == 1
    assert values["payload"] == {"answer_id": "a-0123456789abcdef", "vote": "down", "reason": "stale"}
    assert set(values["payload"]) == {"answer_id", "vote", "reason"}
    assert values["up"]["reason"] is None
    assert all(re.fullmatch(r"a-[0-9a-f]{16}", answer_id) for answer_id in values["ids"])
    assert values["ids"][0] != values["ids"][1]
    source = (STATIC / "js" / "feedback.js").read_text(encoding="utf-8")
    assert "Date.now" not in source and "randomUUID" not in source and "navigator.userAgent" not in source


def test_feedback_markup_has_thumbs_with_labels_four_reasons_and_no_free_text(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"feedback": "js/feedback.js"},
        "console.log(JSON.stringify({markup:feedback.feedbackMarkup('a-1'), "
        "reasons:feedback.PROBLEM_REASONS, labels:feedback.REASON_TR}));",
    )
    markup = values["markup"]
    assert "Bu cevap işine yaradı mı?" in markup
    assert 'data-vote="up" aria-pressed="false" aria-label="Evet, işime yaradı"' in markup
    assert 'data-vote="down" aria-pressed="false" aria-label="Hayır, işime yaramadı"' in markup
    assert '<span aria-hidden="true">👍</span>' in markup and '<span aria-hidden="true">👎</span>' in markup
    assert values["reasons"] == ["wrong", "stale", "misunderstood", "other"]
    radio_values = re.findall(r'<input type="radio" name="reason" value="([^"]+)">', markup)
    assert radio_values == values["reasons"]
    assert [values["labels"][key] for key in radio_values] == ["Yanlış", "Eski bilgi", "Sorumu anlamadı", "Başka"]
    assert "Anonim olarak gönder" in markup and "sorunuz, cevap ve kimliğiniz gitmez" in markup
    assert "<textarea" not in markup and 'type="text"' not in markup and "icon(" not in markup
    assert chr(0x1F916) not in (STATIC / "js" / "feedback.js").read_text(encoding="utf-8")


def test_disclosure_texts_have_one_source_and_kvkk_repeats_the_short_notice(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"disclosure": "js/disclosure.js"},
        "console.log(JSON.stringify({ai:disclosure.AI_NOTICE,privacy:disclosure.PRIVACY_NOTICE,warning:disclosure.PII_WARNING,"
        "band:disclosure.privacyBandMarkup(),notice:disclosure.aiNoticeMarkup()}));",
    )
    expected_ai = (
        "Ben İstanbul şehir bilgi asistanıyım ve yapay zekâ kullanıyorum. "
        "Resmî karar veren bir görevli değilim."
    )
    assert values["ai"] == expected_ai
    assert 'id="privacy-band"' in values["band"] and 'href="/kvkk.html"' in values["band"]
    for phrase in ("TC kimlik", "kart numarası", "sağlık belgesi", "Ses kaydı tutulmaz", "yurt dışı"):
        assert phrase.lower() in values["band"].lower()
    # The AI notice is one band per page session (chat.js), never repeated inside the first answer.
    assert values["notice"] == f'<div class="chat-band" role="note"><p>{expected_ai}</p></div>'
    assert "chat-ai-notice" not in (STATIC / "js" / "disclosure.js").read_text(encoding="utf-8")
    pages = [*STATIC.rglob("*.js"), *STATIC.rglob("*.html")]
    matches = [path for path in pages if values["ai"] in path.read_text(encoding="utf-8")]
    assert matches == [STATIC / "js" / "disclosure.js"]
    kvkk = (STATIC / "kvkk.html").read_text(encoding="utf-8")
    assert values["privacy"] in kvkk and values["warning"] in kvkk


def test_transcript_renders_each_part_and_soft_notice_is_not_an_alert(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"transcript": "js/transcript.js"},
        "const parts=[{kind:'question',text:'Merhaba <şehir>'},{kind:'text',text:'Yanıt'},"
        "{kind:'citations',items:[]},{kind:'quote',items:[]},{kind:'author',name:'model'},"
        "{kind:'notice',level:'soft',title:'Bilgi',text:'Kapsam dışı'},"
        "{kind:'notice',level:'bad',title:'Hata',text:'Taşıma hatası'}, {kind:'unknown'}];"
        "console.log(JSON.stringify({parts:parts.map(transcript.renderPart),all:transcript.renderParts(parts)}));",
    )
    assert 'class="chat-who">Siz</p>' in values["parts"][0]
    assert "Merhaba &lt;şehir&gt;" in values["parts"][0]
    assert 'class="chat-text"' in values["parts"][1]
    assert 'cevabı yazan: <b>model</b>' in values["parts"][4]
    assert 'class="callout"' in values["parts"][5] and 'role="alert"' not in values["parts"][5]
    assert 'class="callout callout-error" role="alert"' in values["parts"][6]
    assert values["parts"][7] == "" and len(values["all"]) > 0


def test_transcript_tool_labels_follow_the_g1_provenance_export(tmp_path) -> None:
    provenance = (STATIC / "js" / "provenance.js").read_text(encoding="utf-8")
    exported = re.search(r"\bexport\s+(?:const|let|var)\s+TOOL_TR\b|\bexport\s*\{[^}]*\bTOOL_TR\b", provenance)
    if not exported:
        pytest.skip("TOOL_TR/AUTHOR_TR export lands with G1")
    value = node_json(
        tmp_path,
        {"transcript": "js/transcript.js"},
        "console.log(JSON.stringify(transcript.renderPart({kind:'tool',name:'metro_status',status:'done'})));",
    )
    assert "Araç tamamlandı" in value and "TOOL_TR" not in value


def test_transcript_quote_box_uses_the_knowledge_hit_field_names_verbatim(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"transcript": "js/transcript.js"},
        "const hit={url:'https://www.iski.istanbul/abonelik',title:'Su aboneliği',"
        "quote:'Abonelik için  kimlik ve tapu/kira sözleşmesi gerekir.',fetched_at:'2026-09-25T08:00:00+00:00'};"
        "const prov={source:'metro_equipment',url:'https://www.metro.istanbul/',observed_at:'2026-09-25T07:30:00+00:00',age_s:720,mode:'live'};"
        "console.log(JSON.stringify({quote:transcript.renderPart({kind:'quote',items:[hit]}),"
        "mixed:transcript.renderPart({kind:'citations',items:[hit,prov]}),missing:transcript.renderPart({kind:'quote',items:[{...hit,fetched_at:''}]}),empty:transcript.quoteBox([])}));",
    )
    assert "Kaynakta geçen ifade" in values["quote"]
    assert 'href="https://www.iski.istanbul/abonelik"' in values["quote"]
    assert "Su aboneliği" in values["quote"]
    assert "Abonelik için  kimlik ve tapu/kira sözleşmesi gerekir." in values["quote"]
    assert "25.09.2026" in values["quote"]
    assert 'class="quote-box"' in values["mixed"] and 'class="cites"' in values["mixed"]
    assert "bilinmiyor" in values["missing"] and values["empty"] == ""
    source = (STATIC / "js" / "transcript.js").read_text(encoding="utf-8")
    quote_source = source.split("function quoteBox", 1)[1].split("function renderPart", 1)[0]
    assert "fetched_at" in source
    assert "fetchedAt" not in source and "source_url" not in source and "sourceUrl" not in source
    for forbidden in ("observed_at", ".replace(", ".trim(", ".slice(", "normalize("):
        assert forbidden not in quote_source
    assert not re.search(r"const\s+(?:TOOL_TR|AUTHOR_TR)\b", source)
    assert "from './provenance.js'" in source


def test_kvkk_page_carries_honesty_lines_and_names_every_storage_key() -> None:
    page = (STATIC / "kvkk.html").read_text(encoding="utf-8")
    assert '<html lang="tr">' in page and page.count("<h1") == 1
    assert 'class="skip-link"' in page and 'id="main"' in page
    assert "Resmî İBB hizmeti değildir" in page and "Simüle operatör" in page
    assert "Web Speech API" in page and "Ses kaydı tutulmaz" in page
    for key in (
        "nabiz.profile.v1", "nabiz.memory.v1", "nabiz-theme", "nabiz-simple", "nabiz.a11y.v1", "nabiz.feedback.v1",
        "nabiz.persona.v1", "nabiz.easyread.v1", "nabiz.kolay.v1", "nabiz.my-stops.v1", "nabiz.my-stops.asked.v1",
        "nabiz.conversations.v1", "nabiz-brief-v2",
    ):
        assert key in page
    assert 'id="kvkk-kisa"' in page
    for phrase in ("TC kimlik", "kart numarası", "sağlık belgesi", "yurt dışı", "cevap kimliği"):
        assert phrase.lower() in page.lower()
    for ref in re.findall(r'(?:href|src)="(/(?:css|js|fonts)/[^"#?]+)"', page):
        assert (STATIC / ref.lstrip("/")).is_file(), ref
    for target in re.findall(r'<nav[^>]*>(.*?)</nav>', page, flags=re.S):
        for anchor in re.findall(r'href="#([^"]+)"', target):
            assert f'id="{anchor}"' in page
    assert not re.search(r"\bETA\b|kanca|logo|/Users/|[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", page, re.I)
    assert chr(0x1F916) not in page and chr(0x2014) not in page and chr(0x2013) not in page
