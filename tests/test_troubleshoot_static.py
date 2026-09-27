from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from conftest import REPO_ROOT
from test_i18n_surfaces import TURKISH_CHARS, UI_CALL, UI_KEY, js_fallback, template_literals
from test_static_a11y import STATIC, node_json

VIEW = STATIC / "js/troubleshoot_view.js"
MODULE = STATIC / "js/troubleshoot.js"
CSS = STATIC / "css/troubleshoot.css"
FLOW_PATH = REPO_ROOT / "data/knowledge/istanbulkart_flows.json"
CATALOG = {
    "tr": {
        "ui.ikart.title": "İstanbulkart sorun giderme",
        "ui.ikart.note": (
            "Sorununuzu birkaç soruyla daraltır; adımlar İstanbulkart'ın resmî duyurularından. "
            "Kartınızın bakiyesini ve hareketlerini göremeyiz."
        ),
        "ui.ikart.no_secrets": "Nabız şifre, doğrulama kodu ya da kart numarası istemez.",
        "ui.ikart.remember": "Adımlarımı bu cihazda hatırla (sunucuya gitmez, 30 gün)",
        "ui.ikart.trail": "Yanıtlarınız",
        "ui.ikart.loading": "Adımlar yükleniyor.",
        "ui.ikart.load_failed": "Adımlar şu an yüklenemedi. İnsanla konuşmak için 153'ü arayabilirsiniz.",
        "ui.ikart.step_status": "Adım {n}: {question}",
        "ui.ikart.tried_failed": "Denedim, sorun sürüyor",
        "ui.ikart.not_tried": "Henüz denemedim",
        "ui.ikart.solved": "Sorun çözüldü",
        "ui.ikart.solved_note": "Tamam. Bu cihazdaki adımlar silindi.",
        "ui.ikart.when_hint": 'İsteğe bağlı. Özette "kullanıcı girdi" diye yazılır.',
        "ui.ikart.next": "Devam",
        "ui.ikart.skip": "Atla",
        "ui.ikart.back": "Geri",
        "ui.ikart.restart": "Baştan başla",
        "ui.ikart.forget": "Bu cihazdan sil",
        "ui.ikart.forgotten": "Bu cihazdaki adımlar silindi.",
        "ui.ikart.official_says": "Resmî duyuru ne diyor",
        "ui.ikart.source_line": "Kaynak: {source} · {host} · duyuru {page_date} · indirildi {date}",
        "ui.ikart.open_page": "Duyuruyu aç",
        "ui.ikart.date_unknown": "duyuru tarihi dizinde yok",
        "ui.ikart.gap_generic": "Bu adım için resmî kaynak henüz yok.",
        "ui.ikart.contact_title": "Kime başvurabilirsiniz",
        "ui.ikart.contact_call": "Arayın: {call}",
        "ui.ikart.contact_site": "{agency} resmî sitesi",
        "ui.ikart.summary_title": "Destek özeti",
        "ui.ikart.summary_note": (
            "Yalnız sizin yanıtlarınızdan oluşur; kurum doğrulaması değildir. "
            "Kopyalayıp destek hattına okuyabilir ya da yazabilirsiniz."
        ),
        "ui.ikart.summary_tr_note": "Özet Türkçedir; destek hattı için.",
        "ui.ikart.copy": "Özeti kopyala",
        "ui.ikart.copied": "Kopyalandı.",
        "ui.ikart.copy_failed": "Kopyalanamadı; metin seçildi, kendiniz kopyalayın.",
    },
    "en": {
        "ui.ikart.title": "İstanbulkart troubleshooting",
        "ui.ikart.note": (
            "Narrows your problem down with a few questions; the steps come from İstanbulkart's official announcements. "
            "We cannot see your card's balance or transactions."
        ),
        "ui.ikart.no_secrets": "Nabız never asks for a password, verification code or card number.",
        "ui.ikart.remember": "Remember my steps on this device (not sent to the server, 30 days)",
        "ui.ikart.trail": "Your answers",
        "ui.ikart.loading": "Loading the steps.",
        "ui.ikart.load_failed": "The steps could not be loaded right now. To talk to a person, you can call 153.",
        "ui.ikart.step_status": "Step {n}: {question}",
        "ui.ikart.tried_failed": "I tried, the problem remains",
        "ui.ikart.not_tried": "Not tried yet",
        "ui.ikart.solved": "The problem is solved",
        "ui.ikart.solved_note": "Done. The steps on this device were deleted.",
        "ui.ikart.when_hint": "Optional. The summary marks it as entered by you.",
        "ui.ikart.next": "Continue",
        "ui.ikart.skip": "Skip",
        "ui.ikart.back": "Back",
        "ui.ikart.restart": "Start over",
        "ui.ikart.forget": "Delete from this device",
        "ui.ikart.forgotten": "The steps on this device were deleted.",
        "ui.ikart.official_says": "What the official announcement says",
        "ui.ikart.source_line": "Source: {source} · {host} · announced {page_date} · downloaded {date}",
        "ui.ikart.open_page": "Open the announcement",
        "ui.ikart.date_unknown": "announcement date not in index",
        "ui.ikart.gap_generic": "There is no official source for this step yet.",
        "ui.ikart.contact_title": "Who you can contact",
        "ui.ikart.contact_call": "Call {call}",
        "ui.ikart.contact_site": "{agency} official website",
        "ui.ikart.summary_title": "Support summary",
        "ui.ikart.summary_note": (
            "It is made only from your answers; it is not a confirmation by the institution. "
            "Copy it and read it out or send it to the support line."
        ),
        "ui.ikart.summary_tr_note": "The summary is in Turkish, for the support line.",
        "ui.ikart.copy": "Copy the summary",
        "ui.ikart.copied": "Copied.",
        "ui.ikart.copy_failed": "Could not copy; the text is selected, please copy it yourself.",
    },
}


def _payload() -> dict:
    flows = json.loads(FLOW_PATH.read_text(encoding="utf-8"))
    sources = {}
    for source_id, source in flows["sources"].items():
        sources[source_id] = {
            "url": source["url"],
            "host": urlsplit(source["url"]).hostname,
            "name": "BELBİM (İstanbulkart)",
            "fetched_at": "2026-09-26T12:47:00+00:00",
            "page_date": {
                "d2762": "2026-06-29",
                "d2768": "2026-09-01",
                "d2780": "2026-04-04",
                "d2815": "2026-09-04",
            }[source_id],
        }
    return {
        "version": 1,
        "start": flows["start"],
        "nodes": flows["nodes"],
        "quotes": flows["quotes"],
        "sources": sources,
        "summary": flows["summary"],
        "contact": {
            "call": "153",
            "agency": {"name": "BELBİM (İstanbulkart)", "url": "https://www.istanbulkart.istanbul/"},
        },
        "disclaimer": "Resmî İBB hizmeti değildir.",
        "quotes_enabled": True,
    }


def _run_view(tmp_path, body: str, lang: str = "tr"):
    i18n_url = json.dumps((STATIC / "js/i18n_text.js").as_uri())
    tr_file = json.loads((STATIC / "i18n/tr.json").read_text(encoding="utf-8"))
    en_file = json.loads((STATIC / "i18n/en.json").read_text(encoding="utf-8"))
    tr = {**tr_file, **CATALOG["tr"]}
    en = {**en_file, **CATALOG["en"]}
    selected = en if lang == "en" else tr
    selected_json = json.dumps(selected, ensure_ascii=False)
    tr_json = json.dumps(tr, ensure_ascii=False)
    prelude = (
        f"const i18n = await import({i18n_url});\n"
        f"i18n.setCatalogs({json.dumps(lang)}, {selected_json}, {tr_json});"
    )
    return node_json(tmp_path, {"view": "js/troubleshoot_view.js"}, prelude + f"\n{body}")


def test_flow_choices_skip_back_and_stored_state(tmp_path) -> None:
    flows = json.dumps(_payload(), ensure_ascii=False)
    body = f"""
const flows = {flows};
const now = Date.parse('2026-09-26T12:00:00Z');
const begin = () => ({{...view.emptyState(), node: flows.start, at: now}});
let a = begin();
a = view.choose(flows, a, 'konu', 'yukleme', now);
a = view.choose(flows, a, 'yukleme_kanal', 'biletmatik', now);
a = view.choose(flows, a, 'yukleme_zaman', '2026-09-26T14:30', now);
const direct = a.node;
let b = begin();
b = view.choose(flows, b, 'konu', 'yukleme', now);
b = view.choose(flows, b, 'yukleme_kanal', 'diger', now);
b = view.choose(flows, b, 'yukleme_resmi', 'failed', now);
b = view.choose(flows, b, 'yukleme_zaman', null, now);
let c = begin();
c = view.choose(flows, c, 'konu', 'vize', now);
c = view.choose(flows, c, 'vize_kart', 'engelli', now);
c = view.choose(flows, c, 'vize_engelli_sms', 'almadim', now);
const solved = view.choose(flows, {{...c, node:'vize_engelli_nasil'}}, 'vize_engelli_nasil', 'solved', now);
const invalid = view.choose(flows, begin(), 'konu', 'unknown', now);
const previous = view.back(flows, a);
const skipped = {{...flows, nodes:{{...flows.nodes, yukleme_resmi:{{...flows.nodes.yukleme_resmi,kind:'skip'}}}}}};
let d = view.choose(skipped, view.choose(skipped, begin(), 'konu', 'yukleme', now), 'yukleme_kanal', 'diger', now);
const valid = {{version:1,node:'yukleme_kanal',path:[{{node:'konu',answer:'yukleme'}}],when:null,checks:{{}},at:now}};
const bads = [
  view.parseStored(JSON.stringify(valid), flows, now),
  view.parseStored(JSON.stringify({{...valid,at:now-31*86400000}}), flows, now),
  view.parseStored(JSON.stringify({{...valid,node:'unknown'}}), flows, now),
  view.parseStored(JSON.stringify({{...valid,path:[{{node:'konu',answer:'bad'}}]}}), flows, now),
  view.parseStored(JSON.stringify({{...valid,when:'bad'}}), flows, now),
  view.parseStored(JSON.stringify({{...valid,when:'2026-02-31T12:00'}}), flows, now),
  view.parseStored('{{', flows, now),
  view.parseStored(JSON.stringify({{...valid,version:2}}), flows, now),
];
console.log(JSON.stringify({{direct,b:b.node,c:c.node,solved:solved.node,invalidSame:invalid.node===flows.start,back:previous.node,skip:d.node,bads}}));
"""
    result = _run_view(tmp_path, body)
    assert result["direct"] == "yukleme_son"
    assert result["b"] == "yukleme_son"
    assert result["c"] == "vize_engelli_yok"
    assert result["solved"] == "__solved"
    assert result["invalidSame"] is True and result["back"] == "yukleme_zaman"
    assert result["skip"] == "yukleme_zaman"
    assert result["bads"][0]["node"] == "yukleme_kanal"
    assert result["bads"][1:] == [None] * 7


def test_summary_masks_identifiers_and_marks_entered_time_and_sources(tmp_path) -> None:
    flows = json.dumps(_payload(), ensure_ascii=False)
    body = f"""
const flows = {flows};
const now = Date.parse('2026-09-26T12:00:00Z');
let state = {{...view.emptyState(),node:flows.start,at:now}};
for (const [node,answer] of [
  ['konu','yukleme'], ['yukleme_kanal','diger'],
  ['yukleme_resmi','failed'], ['yukleme_zaman','2026-09-26T14:30'],
]) state=view.choose(flows,state,node,answer,now);
console.log(JSON.stringify({{
  text:view.summaryText(flows,state,flows.contact,now),
  masked:view.maskSummary('kart 5890 1234 5678 9012 name@example.org 26.09.2026 14:30'),
}}));
"""
    result = _run_view(tmp_path, body)
    text = result["text"]
    assert "İşlem zamanı (kullanıcı girdi): 26.09.2026 14:30" in text
    assert "duyuru 04.09.2026" in text and "https://www.istanbulkart.istanbul/duyurular/detay?id=2815" in text
    assert "Kart numarası, şifre ve doğrulama kodu bu özette yoktur." in text
    assert "kurum doğrulaması değildir" in text
    assert not any(word in text.lower() for word in ("iade", "başarı", "yüklendi"))
    assert "—" not in text and "–" not in text
    assert result["masked"] == "kart [gizlendi] [gizlendi] 26.09.2026 14:30"


def test_markup_is_escaped_bilingual_and_has_no_primary_action(tmp_path) -> None:
    flows = json.dumps(_payload(), ensure_ascii=False)
    body = f"""
const flows = {flows};
const state = {{...view.emptyState(),node:'konu',at:1}};
const shell = view.sectionMarkup(flows,state,false);
const english = view.stepMarkup(flows,{{...state,node:'basvuru_son',path:[{{node:'konu',answer:'basvuru'}}]}},'en');
const end = view.stepMarkup(flows,{{...state,node:'vize_engelli_yok',path:[{{node:'konu',answer:'vize'}}]}},'tr');
const quote = view.quoteMarkup({{parts:['<b>raw</b>']}},flows.sources.d2768,'en');
const missingFlows = {{...flows,nodes:{{...flows.nodes}}}};
missingFlows.nodes.vize_engelli_yok = {{...flows.nodes.vize_engelli_yok,quotes:[],unverified:true}};
const missing = view.stepMarkup(missingFlows,{{...state,node:'vize_engelli_yok'}},'en');
console.log(JSON.stringify({{shell,english,end,quote,missing}}));
"""
    result = _run_view(tmp_path, body, "en")
    assert result["shell"].count("<h2") == 1 and "btn-primary" not in result["shell"]
    assert 'id="kart-sorun"' in result["shell"] and 'id="ikart-remember"' in result["shell"]
    assert 'blockquote lang="tr"' in result["english"] and "Source text is Turkish." in result["english"]
    assert "tel:153" in result["end"] and "https://www.istanbulkart.istanbul/" in result["end"]
    assert "&lt;b&gt;raw&lt;/b&gt;" in result["quote"] and "<b>raw</b>" not in result["quote"]
    assert "official source" in result["missing"]
    assert result["missing"].count("<h3") == 1


def test_catalog_fallbacks_and_translations_are_complete() -> None:
    tr, en = CATALOG["tr"], CATALOG["en"]
    sources = {path.name: path.read_text(encoding="utf-8") for path in (VIEW, MODULE)}
    calls = {key: js_fallback(value) for source in sources.values() for _, key, _, value in UI_CALL.findall(source)}
    ikart_keys = {key for key in calls if key.startswith("ui.ikart.")}
    assert ikart_keys == set(tr) == set(en)
    for key in ikart_keys:
        assert calls[key] == tr[key], key
        assert bool(re.findall(r"\{(\w+)\}", tr[key])) == bool(re.findall(r"\{(\w+)\}", en[key]))
        assert set(re.findall(r"\{(\w+)\}", tr[key])) == set(re.findall(r"\{(\w+)\}", en[key]))
    existing_tr = json.loads((STATIC / "i18n/tr.json").read_text(encoding="utf-8"))
    existing_en = json.loads((STATIC / "i18n/en.json").read_text(encoding="utf-8"))
    # P00 G5: the keys moved into the page catalogues, unchanged
    assert all(existing_tr[k] == v for k, v in tr.items()) and all(existing_en[k] == v for k, v in en.items())
    for module in sources.values():
        all_keys = {key for _, key in UI_KEY.findall(module)}
        assert all_keys <= set(existing_tr) | set(tr)
        assert all_keys <= set(existing_en) | set(en)
    forbidden_words = (
        r"—|–|\bETA\b|canlı|\blive\b|logo|kanca|İBB onaylı|refund|eligible|you are entitled|"
        r"succeeded|went through successfully|iade edil|başarılı|yüklendi"
    )
    forbidden = re.compile(forbidden_words, re.I)
    assert not any(forbidden.search(value) for catalog in CATALOG.values() for value in catalog.values())
    assert sum(len(re.findall(r"(?<!\d)112(?!\d)", value)) for value in tr.values()) == sum(
        len(re.findall(r"(?<!\d)112(?!\d)", value)) for value in en.values()
    )
    assert sum(len(re.findall(r"(?<!\d)153(?!\d)", value)) for value in tr.values()) == sum(
        len(re.findall(r"(?<!\d)153(?!\d)", value)) for value in en.values()
    )


def test_modules_have_no_bare_turkish_or_forbidden_side_effects() -> None:
    for path in (VIEW, MODULE):
        source = path.read_text(encoding="utf-8")
        clean = re.sub(r"/\*.*?\*/|^\s*//.*$", "", source, flags=re.S | re.M)
        fallback_spans = [match.span(4) for match in UI_CALL.finditer(clean)]
        literal_source = list(clean)
        for start, end, chunks in template_literals(clean):
            for chunk in chunks:
                assert not TURKISH_CHARS.search(chunk)
            literal_source[start:end] = [" "] * (end - start)
        literals = re.compile(r"'((?:\\.|[^'\\])*)'|\"((?:\\.|[^\"\\])*)\"", re.S)
        for match in literals.finditer("".join(literal_source)):
            group = next(index for index, item in enumerate(match.groups(), start=1) if item is not None)
            value = match.group(group)
            if TURKISH_CHARS.search(value):
                start, end = match.span(group)
                assert any(left <= start and end <= right for left, right in fallback_spans), (path.name, value)
        for forbidden in ("setInterval", "dispatchEvent", "btn-primary", "/api/console", "innerHTML +="):
            assert forbidden not in source
    assert "localStorage" not in VIEW.read_text(encoding="utf-8")
    assert MODULE.read_text(encoding="utf-8").count("localStorage") == 1
    assert "troubleshoot_view.js" not in VIEW.read_text(encoding="utf-8")


def test_css_and_icon_sources_follow_local_tokens() -> None:
    css = CSS.read_text(encoding="utf-8")
    code = "\n".join(path.read_text(encoding="utf-8") for path in (VIEW, MODULE, CSS))
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(", re.sub(r"/\*.*?\*/", "", css, flags=re.S))
    for forbidden in ("transition", "animation", "infinite", "--danger", "--nd-red"):
        assert forbidden not in css
    assert "border-inline-start: 1px solid var(--nd-line)" in css
    assert "overflow-wrap: anywhere" in css and "CanvasText" in css
    icons = set(re.findall(r'id="i-([^"]+)"', (STATIC / "icons.svg").read_text(encoding="utf-8")))
    assert set(re.findall(r"icon\('([^']+)'", code)) <= icons
    agencies = json.loads((REPO_ROOT / "data/agencies.json").read_text(encoding="utf-8"))
    assert re.search(r"FALLBACK_CALL = '([^']+)'", VIEW.read_text(encoding="utf-8")).group(1) == agencies["call"]
    assert not re.search(r"[—–]", code)


def test_mount_does_not_fetch_without_anchor_and_uses_one_parameter_free_get(tmp_path) -> None:
    module_url = json.dumps(MODULE.as_uri())
    body = f"""
const events = {{}}; let calls = [];
globalThis.window = {{location:{{search:'',origin:'https://example.test',hash:''}},addEventListener:(name,fn)=>events[name]=fn}};
globalThis.document = {{head:{{append:()=>{{}}}},createElement:()=>({{}}),querySelector:()=>null}};
globalThis.fetch = async (url,options) => {{
  calls.push([String(url),options]);
  return {{ok:true,json:async()=>({json.dumps(_payload(), ensure_ascii=False)})}};
}};
const app = await import({module_url});
const missing = app.mountTroubleshoot(document,{{getItem:()=>null}});
const result = {{missing:missing===null,calls:calls.length,anchors:app.ANCHORS,stylesheet:app.STYLESHEET,section:app.SECTION_ID}};
console.log(JSON.stringify(result));
"""
    values = node_json(tmp_path, {}, body)
    assert values == {
        "missing": True,
        "calls": 0,
        "anchors": [["#city-tools", "beforeend"], ["#hesabim", "beforebegin"]],
        "stylesheet": "/css/troubleshoot.css",
        "section": "kart-sorun",
    }


def test_mount_remembers_only_with_consent_and_redraws_language_without_refetch(tmp_path) -> None:
    module_url = json.dumps(MODULE.as_uri())
    i18n_url = json.dumps((STATIC / "js/i18n_text.js").as_uri())
    payload = json.dumps(_payload(), ensure_ascii=False)
    body = f"""
const windowEvents={{}}, calls=[], stored=new Map();
const storage={{
  getItem:key=>stored.get(key)||null,
  setItem:(key,value)=>stored.set(key,value),
  removeItem:key=>stored.delete(key),
}};
globalThis.localStorage=storage;
globalThis.window={{location:{{search:'',origin:'https://example.test',hash:'#kart-sorun'}},
  addEventListener:(name,fn)=>windowEvents[name]=fn}};
globalThis.fetch=async(url,options)=>{{
  calls.push([String(url),options]);
  return {{ok:true,json:async()=>({payload})}};
}};
const i18n=await import({i18n_url});
const catalogs={json.dumps(CATALOG, ensure_ascii=False)};
const trFile={json.dumps(json.loads((STATIC / "i18n/tr.json").read_text(encoding="utf-8")), ensure_ascii=False)};
const enFile={json.dumps(json.loads((STATIC / "i18n/en.json").read_text(encoding="utf-8")), ensure_ascii=False)};
i18n.setCatalogs('tr',{{...trFile,...catalogs.tr}},{{...trFile,...catalogs.tr}});
const root={{open:false,innerHTML:'',handlers:{{}},
  addEventListener:(name,fn)=>root.handlers[name]=fn,
  contains:item=>item&&item.owner===root,
  querySelector(selector){{
    if(selector==='.status-line')return status;
    if(selector==='#ikart-q')return heading;
    if(selector==='#ikart-remember')return checkbox;
    return null;
  }}}};
const status={{textContent:''}};
const heading={{owner:root,id:'ikart-q',focus:()=>{{root.focused='ikart-q';document.activeElement=heading;}}}};
const checkbox={{owner:root,id:'ikart-remember',checked:false,
  focus:()=>{{root.focused='ikart-remember';document.activeElement=checkbox;}}}};
const anchor={{insertAdjacentHTML:(position,html)=>{{root.innerHTML=html;root.position=position;}}}};
globalThis.document={{head:{{append:()=>{{}}}},activeElement:null,defaultView:window,
  createElement:()=>({{}}),
  querySelector(selector){{
    if(selector==='#kart-sorun')return root.innerHTML?root:null;
    if(selector==='#city-tools')return anchor;
    return null;
  }}}};
const app=await import({module_url});
const mounted=app.mountTroubleshoot(document,storage);
await new Promise(resolve=>setTimeout(resolve,0));
checkbox.checked=true;root.handlers.change({{target:checkbox}});
const answer={{owner:root,dataset:{{ikartAnswer:'vize'}},closest:()=>answer}};
root.handlers.click({{target:answer}});await Promise.resolve();
const saved=JSON.parse(stored.get('nabiz.ikart.v1'));
i18n.setCatalogs('en',{{...enFile,...catalogs.en}},{{...trFile,...catalogs.tr}});
windowEvents['nabiz:lang']({{detail:{{lang:'en'}}}});
const focusAfterLanguage=root.focused;
window.location.hash='#kart-sorun';windowEvents.hashchange();
const countAfterLanguage=calls.length;
const focusAfterHash=root.focused;
const reloadStatus={{textContent:''}};
const reloadHeading={{owner:null,id:'ikart-q',focus:()=>{{}}}};
const reloadCheckbox={{id:'ikart-remember',checked:false,focus:()=>{{}}}};
const reloadRoot={{open:false,innerHTML:'',handlers:{{}},
  addEventListener:(name,fn)=>reloadRoot.handlers[name]=fn,
  contains:()=>false,
  querySelector(selector){{
    if(selector==='.status-line')return reloadStatus;
    if(selector==='#ikart-q')return reloadHeading;
    if(selector==='#ikart-remember')return reloadCheckbox;
    return null;
  }}}};
const reloadAnchor={{insertAdjacentHTML:(position,html)=>reloadRoot.innerHTML=html}};
const reloadDoc={{head:{{append:()=>{{}}}},activeElement:null,defaultView:window,
  createElement:()=>({{}}),
  querySelector(selector){{
    if(selector==='#kart-sorun')return reloadRoot.innerHTML?reloadRoot:null;
    if(selector==='#city-tools')return reloadAnchor;
    return null;
  }}}};
app.mountTroubleshoot(reloadDoc,storage);await new Promise(resolve=>setTimeout(resolve,0));
const restored=reloadRoot.innerHTML.includes('Which card?');
const restoredConsent=reloadRoot.innerHTML.includes('id="ikart-remember" checked');
checkbox.checked=false;root.handlers.change({{target:checkbox}});
const result={{mounted:!!mounted,requests:calls,storedKeys:Object.keys(saved).sort(),savedNode:saved.node,
  remembered:stored.has('nabiz.ikart.v1'),english:root.innerHTML.includes('Which card?'),
  restored,restoredConsent,open:root.open,focused:root.focused,focusAfterLanguage,focusAfterHash,
  countAfterLanguage,remaining:calls.length,position:root.position}};
console.log(JSON.stringify(result));
"""
    values = node_json(tmp_path, {}, body)
    assert values["mounted"] is True
    assert len(values["requests"]) == 2
    assert values["requests"][0][0] == "https://example.test/api/istanbulkart/flows"
    assert values["requests"][0][1].get("body") is None
    assert values["storedKeys"] == ["at", "checks", "node", "path", "version", "when"]
    assert values["savedNode"] == "vize_kart" and values["remembered"] is False
    assert values["english"] and values["open"] and values["focusAfterHash"] == "ikart-q"
    assert values["focusAfterLanguage"] == "ikart-q"
    assert values["restored"] and values["restoredConsent"]
    assert values["countAfterLanguage"] == 1 and values["remaining"] == 2
    assert values["position"] == "beforeend"


def test_error_mount_shows_only_a_retryless_contact_path(tmp_path) -> None:
    module_url = json.dumps(MODULE.as_uri())
    i18n_url = json.dumps((STATIC / "js/i18n_text.js").as_uri())
    body = f"""
const events={{}},calls=[];
globalThis.window={{location:{{search:'',origin:'https://example.test',hash:''}},
  addEventListener:(n,f)=>events[n]=f}};
globalThis.fetch=async(url,options)=>{{
  calls.push([String(url),options]);
  throw new Error('offline');
}};
const i18n=await import({i18n_url});
const status={{textContent:''}},heading={{focus:()=>{{}}}},checkbox={{checked:false}};
const root={{open:false,innerHTML:'',handlers:{{}},
  addEventListener:(n,f)=>root.handlers[n]=f,
  contains:()=>false,
  querySelector:s=>s==='.status-line'?status:s==='#ikart-q'?heading:s==='#ikart-remember'?checkbox:null}};
const anchor={{insertAdjacentHTML:(position,html)=>root.innerHTML=html}};
globalThis.document={{head:{{append:()=>{{}}}},defaultView:window,createElement:()=>({{}}),
  querySelector:s=>s==='#kart-sorun'?(root.innerHTML?root:null):s==='#city-tools'?anchor:null}};
const app=await import({module_url});
app.mountTroubleshoot(document,null);
await new Promise(resolve=>setTimeout(resolve,0));
const result={{requests:calls.length,failed:root.innerHTML.includes('load_failed')
  ||root.innerHTML.includes('Adımlar şu an yüklenemedi'),tel:root.innerHTML.includes('tel:153'),
  onlyNoFlow:!root.innerHTML.includes('Sorun ne?')}};
console.log(JSON.stringify(result));
"""
    values = node_json(tmp_path, {}, body)
    assert values == {"requests": 1, "failed": True, "tel": True, "onlyNoFlow": True}
