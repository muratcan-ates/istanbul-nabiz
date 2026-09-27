from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from test_i18n_surfaces import ARABIC_CHARS, TURKISH_CHARS, UI_CALL, template_literals
from test_static_a11y import STATIC

JS_DIR = STATIC / "js"
CSS_FILE = STATIC / "css" / "visitor.css"
VIEW_FILE = JS_DIR / "visitor_view.js"
MODULE_FILE = JS_DIR / "visitor.js"
CATALOG = {
    "tr": {
        "ui.visitor.title": "İstanbul'u ziyaret mi ediyorsunuz?",
        "ui.visitor.note": "İBB kayıtlarından ve resmî sayfalardan kısa cevaplar. Adlar ve adresler Türkçe kalır.",
        "ui.visitor.q_museums": "Hangi müzeler şu an açık?",
        "ui.visitor.q_airport": "Havalimanlarına hangi şehir otobüsleri gider?",
        "ui.visitor.q_emergency": "Acil numaralar",
        "ui.visitor.q_istanbulkart": "İstanbulkart'ı nereden alırım?",
        "ui.visitor.q_step_free": "Metro, tramvay ve vapurda basamaksız erişim",
        "ui.visitor.district_hint": "Parantez içinde: kayıttaki müze ve galeri sayısı.",
        "ui.visitor.museums_scope": "Yalnız İBB açık veri kaydındaki müze ve galeriler listelenir; başka müzeler bu kayıtta yok.",
        "ui.visitor.museums_access": "Kayıtta erişilebilirlik bilgisi yok; gitmeden önce müzeyi arayın.",
        "ui.visitor.museums_failed": "Müze kayıtları şu an alınamadı. Biraz sonra yeniden deneyin.",
        "ui.visitor.translation": "Çeviri Nabız'ındır; {source} yapmadı.",
        "ui.visitor.original": "Özgün metin (Türkçe)",
        "ui.visitor.source_line": "Kaynak: {source} · {host} · indirildi {date}",
        "ui.visitor.open_page": "Sayfayı aç",
        "ui.visitor.airport_lines": "İETT'nin sayfasında yazdığı gibi havalimanı hatları:",
        "ui.visitor.airport_note": (
            "Başka işletmeler bu kaynakta yok. "
            "Yola çıkmadan önce saatleri İETT'nin sayfasında kontrol edin."
        ),
        "ui.visitor.card_lang": "112 kartı başka bir dilde",
        "ui.visitor.card_pick": "Dil seçin",
        "ui.visitor.card_note": "Sohbete bu dillerden birinde acil bir durum yazarsanız asistan 112 kartını o dilde açar.",
    },
    "en": {
        "ui.visitor.title": "Visiting İstanbul?",
        "ui.visitor.note": "Short answers from İBB records and official pages. Names and addresses stay in Turkish.",
        "ui.visitor.q_museums": "Which museums are open now?",
        "ui.visitor.q_airport": "Which city buses go to the airports?",
        "ui.visitor.q_emergency": "Emergency numbers",
        "ui.visitor.q_istanbulkart": "Where do I get an İstanbulkart?",
        "ui.visitor.q_step_free": "Step-free access on metro, tram and ferry",
        "ui.visitor.district_hint": "In brackets: how many museums and galleries the record lists.",
        "ui.visitor.museums_scope": (
            "Only the museums and galleries in İBB's open data record are listed; "
            "other museums are not in this record."
        ),
        "ui.visitor.museums_access": "The record has no accessibility details; please call the museum before you go.",
        "ui.visitor.museums_failed": "The museum records could not be loaded right now. Please try again later.",
        "ui.visitor.translation": "Translation by Nabız, not by {source}.",
        "ui.visitor.original": "Original text (Turkish)",
        "ui.visitor.source_line": "Source: {source} · {host} · downloaded {date}",
        "ui.visitor.open_page": "Open the page",
        "ui.visitor.airport_lines": "Airport lines as written on İETT's page:",
        "ui.visitor.airport_note": "Other operators are not in this source. Check the times on İETT's page before you travel.",
        "ui.visitor.card_lang": "The 112 card in another language",
        "ui.visitor.card_pick": "Choose a language",
        "ui.visitor.card_note": (
            "If you describe an emergency in the chat in one of these languages, "
            "the assistant opens the 112 card in that language."
        ),
    },
}


def _catalog(language: str) -> dict[str, object]:
    return json.loads((STATIC / "i18n" / f"{language}.json").read_text(encoding="utf-8"))


def _node_run(tmp_path, body: str, *, language: str = "en", with_culture: bool = False):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    tr = {**_catalog("tr"), **CATALOG["tr"]}
    en = {**_catalog("en"), **CATALOG["en"]}
    i18n_url = json.dumps((JS_DIR / "i18n_text.js").as_uri())
    view_url = json.dumps(VIEW_FILE.as_uri())
    culture_url = json.dumps((JS_DIR / "culture.js").as_uri())
    selected = json.dumps(en if language == "en" else tr)
    setup = (
        f"const i18n = await import({i18n_url}); "
        f"i18n.setCatalogs({json.dumps(language)}, {selected}, {json.dumps(tr)});"
    )
    prelude = (
        "globalThis.window = {location:{search:'',origin:'http://localhost'},addEventListener(){},"
        "localStorage:{getItem(){return null},setItem(){}}};"
        "globalThis.document = {getElementById(){return null},querySelector(){return null},head:{append(){}}};"
    )
    imports = f"const view = await import({view_url});"
    if with_culture:
        imports += f"const culture = await import({culture_url});"
    harness = tmp_path / "visitor_harness.mjs"
    harness.write_text(f"{prelude}\n{setup}\n{imports}\n{body}\n", encoding="utf-8")
    result = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _example_payload() -> dict:
    return {
        "questions": [
            {"id": "museums", "kind": "museums", "districts": [{"name": "Fatih", "count": 15}]},
            {
                "id": "airport",
                "kind": "knowledge",
                "sources": [
                    {
                        "url": "https://iett.istanbul/icerik/havalimanlarina-ulasim",
                        "host": "iett.istanbul",
                        "name": "İETT",
                        "fetched_at": "2026-09-27T00:00:00+00:00",
                        "page_date": {"tr": "Güncelleme Tarihi : 23 Haziran 2022", "en": "Page updated: 23 June 2022"},
                        "quotes": [{"tr": "H-1 Mahmutbey Metro - İstanbul Havalimanı", "en": None}],
                    }
                ],
            },
            {"id": "emergency", "kind": "emergency"},
            {
                "id": "istanbulkart",
                "kind": "knowledge",
                "sources": [
                    {
                        "url": "https://www.metro.istanbul/Home/SikcaSorulanSorular",
                        "host": "www.metro.istanbul",
                        "name": "Metro İstanbul",
                        "fetched_at": "2026-09-27T00:00:00+00:00",
                        "page_date": None,
                        "quotes": [{"tr": "<b>Türkçe asıl cümle</b>", "en": "English translated sentence."}],
                    }
                ],
            },
            {
                "id": "step_free",
                "kind": "knowledge",
                "sources": [
                    {
                        "url": "https://www.metro.istanbul/icerik/eri%C5%9Filebilirlik-hizmetleri",
                        "host": "www.metro.istanbul",
                        "name": "Metro İstanbul",
                        "fetched_at": "2026-09-27T00:00:00+00:00",
                        "page_date": None,
                        "quotes": [{"tr": "<b>Türkçe erişim cümlesi</b>", "en": "English access sentence."}],
                    }
                ],
            },
            {"id": "unknown", "kind": "knowledge", "sources": []},
        ]
    }


def test_catalog_matches_all_module_fallbacks_and_lives_in_the_catalogues() -> None:
    modules = [VIEW_FILE.read_text(encoding="utf-8"), MODULE_FILE.read_text(encoding="utf-8")]
    keys = {
        match.group(2) for source in modules for match in UI_CALL.finditer(source) if match.group(2).startswith("ui.visitor.")
    }
    assert keys == set(CATALOG["tr"]) == set(CATALOG["en"])
    tr, en = _catalog("tr"), _catalog("en")
    assert all(tr[k] == CATALOG["tr"][k] and en[k] == CATALOG["en"][k] for k in keys)  # P00 G4: moved, unchanged
    calls = {
        match.group(2): match.group(4).replace("\\'", "'").replace('\\"', '"')
        for source in modules
        for match in UI_CALL.finditer(source)
    }
    for key in keys:
        assert calls[key] == CATALOG["tr"][key]
        assert set(re.findall(r"\{(\w+)\}", CATALOG["tr"][key])) == set(re.findall(r"\{(\w+)\}", CATALOG["en"][key]))
    culture_calls = {
        match.group(2): match.group(4).replace("\\'", "'").replace('\\"', '"')
        for source in modules
        for match in UI_CALL.finditer(source)
        if match.group(2).startswith("ui.culture.")
    }
    assert all(tr[key] == fallback for key, fallback in culture_calls.items())
    words = " ".join(value for entries in CATALOG.values() for value in entries.values())
    assert re.search(r"—|–|\bETA\b|\blive\b|canlı|logo|kanca|İBB onaylı", words, re.IGNORECASE) is None
    assert not re.search(r"[\u0600-\u06ff]", words)
    tr_copy = " ".join(CATALOG["tr"].values())
    en_copy = " ".join(CATALOG["en"].values())
    for number in ("112", "153"):
        assert tr_copy.count(number) == en_copy.count(number)
    multilingual = STATIC.parents[3] / "tests" / "test_emergency_multilingual.py"
    assert "test_each_language_opens_the_card_in_its_own_language" in multilingual.read_text(encoding="utf-8")


def test_new_modules_keep_copy_inside_translations_and_sources_inside_the_icon_set() -> None:
    sources = {VIEW_FILE.name: VIEW_FILE.read_text(encoding="utf-8"), MODULE_FILE.name: MODULE_FILE.read_text(encoding="utf-8")}
    for name, source in sources.items():
        clean = re.sub(r"/\*.*?\*/|^\s*//.*$", "", source, flags=re.S | re.M)
        fallback_spans = [match.span(4) for match in UI_CALL.finditer(clean)]
        for start, end, chunks in template_literals(clean):
            assert all(not TURKISH_CHARS.search(chunk) for chunk in chunks), (name, chunks)
            clean = clean[:start] + (" " * (end - start)) + clean[end:]
        for match in re.finditer(r"'((?:\\.|[^'\\])*)'|\"((?:\\.|[^\"\\])*)\"", clean, re.S):
            text = next(value for value in match.groups() if value is not None)
            if TURKISH_CHARS.search(text):
                start, end = match.span(1 if match.group(1) is not None else 2)
                assert any(left <= start and end <= right for left, right in fallback_spans), (name, text)
        assert not ARABIC_CHARS.search(source), name
        assert "—" not in source and "–" not in source
    for key in re.findall(r"icon\('([^']+)'\)", sources[VIEW_FILE.name]):
        assert f'id="i-{key}"' in (STATIC / "icons.svg").read_text(encoding="utf-8")
    view = sources[VIEW_FILE.name]
    assert not re.search(r"\b(document|window|fetch|localStorage)\b", view)
    script = sources[MODULE_FILE.name]
    assert not re.search(r"setInterval|dispatchEvent|nabiz:emergency|localStorage|btn-primary|/api/console", script + view)
    css = re.sub(r"/\*.*?\*/", "", CSS_FILE.read_text(encoding="utf-8"), flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(|transition|animation|infinite", css)
    assert "CanvasText" in css and "overflow-wrap: anywhere" in css and "width: 100%" in css
    assert len(view.splitlines()) <= 260 and len(script.splitlines()) <= 200 and len(css.splitlines()) <= 150


def test_section_knowledge_markup_and_emergency_card_are_bounded(tmp_path) -> None:
    values = _node_run(
        tmp_path,
        f"const html = view.sectionMarkup({json.dumps(_example_payload(), ensure_ascii=False)});"
        "const emergency = view.emergencyMarkup('en');"
        "console.log(JSON.stringify({html, emergency, unknown:view.cardPreview('xx'), german:view.cardPreview('de'),"
        "arabic:view.cardPreview('ar'), language:view.languageName('de')}));",
    )
    html = values["html"]
    assert html.count("<h2 ") == 1 and html.count('class="visitor-q"') == 5
    assert html.count('name="ziyaretci-soru"') == 5 and "btn-primary" not in html
    assert "Not an official İBB service." in html
    assert '<ul class="visitor-names" lang="tr">' in html and "H-1 Mahmutbey" in html
    assert "Translation by Nabız, not by Metro İstanbul." in html
    assert '<blockquote lang="tr"' in html and "&lt;b&gt;Türkçe asıl cümle&lt;/b&gt;" in html
    assert "quote-exact" not in html and 'rel="noopener"' in html
    assert "Güncelleme Tarihi : 23 Haziran 2022" in html and "Page updated: 23 June 2022" in html
    assert '<ul class="visitor-names" lang="tr">' in html
    assert values["unknown"] == "" and 'lang="de" dir="ltr"' in values["german"]
    assert 'lang="ar" dir="rtl"' in values["arabic"] and values["language"] == "Deutsch"
    emergency = values["emergency"]
    assert re.findall(r'href="(tel:[^"]+)"', emergency) == ["tel:112", "tel:187", "tel:153"]
    assert '<a class="btn" href="tel:112">Call 112</a>' in emergency
    assert '<p class="visitor-plea" id="visitor-plea" lang="tr">LÜTFEN YARDIM EDİN · 112&#39;Yİ ARAYIN</p>' in emergency
    assert emergency.count("<option") == 11 and 'data-visitor="grow"' in emergency


def test_museum_status_matches_culture_for_each_recorded_state(tmp_path) -> None:
    states = [
        {"state": "open", "closes_at": "19.00"},
        {"state": "open"},
        {"state": "closed", "opens_on": {"weekday": 1, "today": True, "time": "09.00"}},
        {"state": "closed", "opens_on": {"weekday": 2, "today": False, "time": "09.00"}},
        {"state": "unknown"},
    ]
    values = _node_run(
        tmp_path,
        f"const rows = {json.dumps(states)};"
        "const tr = rows.map((row) => [view.museumLine(row), culture.stateLine(row)]);"
        "i18n.setCatalogs('en', "
        + json.dumps({**_catalog("en"), **CATALOG["en"]}, ensure_ascii=False)
        + ", "
        + json.dumps({**_catalog("tr"), **CATALOG["tr"]}, ensure_ascii=False)
        + ");"
        "const en = rows.map((row) => [view.museumLine(row), culture.stateLine(row)]);"
        "console.log(JSON.stringify({tr,en}));",
        with_culture=True,
    )
    assert all(left == right for left, right in values["tr"] + values["en"])


def test_self_mounting_obeys_language_anchor_and_reuses_the_fetch(tmp_path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    tr = {**_catalog("tr"), **CATALOG["tr"]}
    en = {**_catalog("en"), **CATALOG["en"]}
    setup = (
        "const i18n = await import(" + json.dumps((JS_DIR / "i18n_text.js").as_uri()) + ");"
        "i18n.setCatalogs('en', " + json.dumps(en, ensure_ascii=False) + ", " + json.dumps(tr, ensure_ascii=False) + ");"
    )
    visitor_url = json.dumps(MODULE_FILE.as_uri())
    body = f"""
const requests = [];
globalThis.fetch = async (input) => {{
  const path = new URL(input).pathname;
  requests.push(path);
  return {{ok:true, json:async() => ({{questions:[{{id:'emergency',kind:'emergency'}}]}})}};
}};
const visitor = await import({visitor_url});
let hasAnchor = false;
let focusInside = false;
let focusCount = 0;
let currentSection = null;
let sectionHTML = '';
const target = {{insertAdjacentHTML(_where, html) {{
  sectionHTML = html;
  const handlers = {{}};
  const plea = {{large:false}};
  plea.classList={{toggle(_name,value){{plea.large=value;}}}};
  const button = {{pressed:'false',getAttribute(){{return this.pressed;}},setAttribute(_name,value){{this.pressed=value;}}}};
  currentSection = {{isConnected:true,handlers,addEventListener(name,fn){{handlers[name]=fn;}},
    contains(){{return focusInside;}},remove(){{this.isConnected=false;currentSection=null;}},
    querySelector(selector){{
      if(selector==='#visitor-plea') return plea;
      return {{innerHTML:'',hidden:false,textContent:'',setAttribute(){{}}}};
    }}}};
  currentSection.plea=plea;currentSection.button=button;
}}}};
const main={{focus(){{focusCount+=1;}}}};
const doc={{activeElement:{{}},head:{{append(){{}}}},
  querySelector(selector){{if(selector==='#chat-log' && hasAnchor)return target;return null;}},
  getElementById(id){{if(id==='ziyaretci')return currentSection;if(id==='main')return main;return null;}},
  createElement(){{return {{}};}}}};
const absent=visitor.mountVisitor(doc);
const callsAbsent=requests.length;
hasAnchor=true;
i18n.setCatalogs('tr', {json.dumps(tr, ensure_ascii=False)}, {json.dumps(tr, ensure_ascii=False)});
const turkish=visitor.mountVisitor(doc);
const callsTurkish=requests.length;
i18n.setCatalogs('en', {json.dumps(en, ensure_ascii=False)}, {json.dumps(tr, ensure_ascii=False)});
await visitor.mountVisitor(doc);
const callsEnglish=requests.length;
const firstHTML=sectionHTML;
const handler=currentSection.handlers.click;
handler({{target:{{closest(){{return currentSection.button;}}}}}});
const grew=[currentSection.plea.large,currentSection.button.pressed];
handler({{target:{{closest(){{return currentSection.button;}}}}}});
const shrank=[currentSection.plea.large,currentSection.button.pressed];
focusInside=true;
for(const listener of (globalThis.languageListeners||[])) listener({{detail:{{lang:'tr'}}}});
const removed=currentSection===null;
focusInside=false;
for(const listener of (globalThis.languageListeners||[])) listener({{detail:{{lang:'en'}}}});
await new Promise((resolve)=>setTimeout(resolve,0));
console.log(JSON.stringify({{absent:absent===null,callsAbsent,callsTurkish,callsEnglish,firstHTML,grew,shrank,removed,focusCount,reloaded:!!currentSection,requests}}));
"""
    # The i18n helper registers the real language listener on this window stub.
    prelude = (
        "globalThis.languageListeners=[];globalThis.window={location:{search:'',origin:'http://localhost'},"
        "addEventListener(_name,fn){languageListeners.push(fn)},removeEventListener(){},"
        "localStorage:{getItem(){return null},setItem(){}}};globalThis.document=undefined;"
    )
    harness = tmp_path / "visitor_mount.mjs"
    harness.write_text(f"{prelude}\n{setup}\n{body}\n", encoding="utf-8")
    result = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    values = json.loads(result.stdout)
    assert values["absent"] and values["callsAbsent"] == values["callsTurkish"] == 0
    assert values["callsEnglish"] == 1 and values["requests"] == ["/api/visitor"]
    assert values["firstHTML"].count('class="visitor-q"') == 1 and 'data-visitor="emergency"' in values["firstHTML"]
    assert values["grew"] == [True, "true"] and values["shrank"] == [False, "false"]
    assert values["removed"] and values["focusCount"] == 1 and values["reloaded"]
