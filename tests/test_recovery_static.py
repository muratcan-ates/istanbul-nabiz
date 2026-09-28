from __future__ import annotations

import json
import re
import shutil
import subprocess

from conftest import REPO_ROOT
from test_i18n_surfaces import TURKISH_CHARS, UI_CALL, UI_KEY, js_fallback, template_literals
from test_static_a11y import STATIC, node_json

JS = STATIC / "js"
VIEW = JS / "recovery_view.js"
MOUNT = JS / "recovery.js"
CSS = STATIC / "css" / "recovery.css"
FLOW = json.loads((REPO_ROOT / "data/knowledge/recovery_flows.json").read_text(encoding="utf-8"))
AGENCIES = json.loads((REPO_ROOT / "data/agencies.json").read_text(encoding="utf-8"))
CATALOG = {
    "tr": {
        "ui.erisim.title": "Uygulamaya ya da hesaba giremiyorum",
        "ui.erisim.note": (
            "Denediğiniz adımları sırayla yazar; her adım kurumun resmî sayfasından. "
            "Hesabınıza erişemeyiz ve erişiminizi geri getiremeyiz."
        ),
        "ui.erisim.no_secrets": (
            "Nabız şifre, doğrulama kodu, kart numarası ya da T.C. kimlik numarası istemez. "
            "Bu bölümde bunları yazacağınız bir alan yok."
        ),
        "ui.erisim.remember": "Adımlarımı bu cihazda hatırla (sunucuya gitmez, 30 gün)",
        "ui.erisim.trail": "Yanıtlarınız",
        "ui.erisim.loading": "Adımlar yükleniyor.",
        "ui.erisim.load_failed": "Adımlar şu an yüklenemedi. İnsanla konuşmak için 153'ü arayabilirsiniz.",
        "ui.erisim.step_status": "Adım {n}: {question}",
        "ui.erisim.tried_failed": "Denedim, sorun sürüyor",
        "ui.erisim.not_tried": "Henüz denemedim",
        "ui.erisim.solved": "Sorun çözüldü",
        "ui.erisim.solved_note": "Tamam. Bu cihazdaki adımlar silindi.",
        "ui.erisim.back": "Geri",
        "ui.erisim.restart": "Baştan başla",
        "ui.erisim.forget": "Bu cihazdan sil",
        "ui.erisim.forgotten": "Bu cihazdaki adımlar silindi.",
        "ui.erisim.official_says": "Resmî sayfa ne diyor",
        "ui.erisim.source_line": "Kaynak: {source} · {host} · indirildi {date}",
        "ui.erisim.open_page": "Sayfayı aç",
        "ui.erisim.gap_generic": "Bu adım için resmî kaynak henüz yok.",
        "ui.erisim.alt_title": "Uygulama olmadan",
        "ui.erisim.handoff_ikart": "İstanbulkart sorun giderme bölümüne gidin",
        "ui.erisim.contact_title": "Kime başvurabilirsiniz",
        "ui.erisim.contact_call": "Arayın: {call}",
        "ui.erisim.contact_site": "{agency} resmî sitesi",
        "ui.erisim.summary_title": "Destek özeti",
        "ui.erisim.summary_note": (
            "Yalnız sizin yanıtlarınızdan oluşur; kurum doğrulaması değildir. "
            "Kopyalayıp destek hattına okuyabilir ya da yazabilirsiniz."
        ),
        "ui.erisim.summary_tr_note": "Özet Türkçedir; destek hattı için.",
        "ui.erisim.copy": "Özeti kopyala",
        "ui.erisim.copied": "Kopyalandı.",
        "ui.erisim.copy_failed": "Kopyalanamadı; metin seçildi, kendiniz kopyalayın.",
    },
    "en": {
        "ui.erisim.title": "I cannot get into an app or account",
        "ui.erisim.note": (
            "Lists the steps you have tried, in order; every step comes from the institution's official page. "
            "We cannot see your account or bring your access back."
        ),
        "ui.erisim.no_secrets": (
            "Nabız never asks for a password, verification code, card number or Turkish ID number. "
            "There is no field for them in this section."
        ),
        "ui.erisim.remember": "Remember my steps on this device (not sent to the server, 30 days)",
        "ui.erisim.trail": "Your answers",
        "ui.erisim.loading": "Loading the steps.",
        "ui.erisim.load_failed": "The steps could not be loaded right now. To talk to a person, you can call 153.",
        "ui.erisim.step_status": "Step {n}: {question}",
        "ui.erisim.tried_failed": "I tried, the problem remains",
        "ui.erisim.not_tried": "Not tried yet",
        "ui.erisim.solved": "The problem is solved",
        "ui.erisim.solved_note": "Done. The steps on this device were deleted.",
        "ui.erisim.back": "Back",
        "ui.erisim.restart": "Start over",
        "ui.erisim.forget": "Delete from this device",
        "ui.erisim.forgotten": "The steps on this device were deleted.",
        "ui.erisim.official_says": "What the official page says",
        "ui.erisim.source_line": "Source: {source} · {host} · downloaded {date}",
        "ui.erisim.open_page": "Open the page",
        "ui.erisim.gap_generic": "There is no official source for this step yet.",
        "ui.erisim.alt_title": "Without the app",
        "ui.erisim.handoff_ikart": "Go to the İstanbulkart troubleshooting section",
        "ui.erisim.contact_title": "Who you can contact",
        "ui.erisim.contact_call": "Call {call}",
        "ui.erisim.contact_site": "{agency} official website",
        "ui.erisim.summary_title": "Support summary",
        "ui.erisim.summary_note": (
            "It is made only from your answers; it is not a confirmation by the institution. "
            "Copy it and read it out or send it to the support line."
        ),
        "ui.erisim.summary_tr_note": "The summary is in Turkish, for the support line.",
        "ui.erisim.copy": "Copy the summary",
        "ui.erisim.copied": "Copied.",
        "ui.erisim.copy_failed": "Could not copy; the text is selected, please copy it yourself.",
    },
}


def view_payload() -> dict:
    sources = {}
    for source_id, source in FLOW["sources"].items():
        host = "www.istanbulkart.istanbul" if source["from"] == "capture" else source["url"].split("/")[2]
        sources[source_id] = {**source, "host": host, "fetched_at": "2026-09-27T00:00:00+00:00"}
    agencies = {item["id"]: {"name": item["name"], "url": item["url"]} for item in AGENCIES["agencies"]}
    return {**FLOW, "sources": sources, "contact": {"call": AGENCIES["call"], "agencies": agencies}}


def run_view(tmp_path, body: str, language: str = "tr"):
    imports = {
        "view": VIEW.as_uri(),
        "i18n": (JS / "i18n_text.js").as_uri(),
    }
    base_tr = json.loads((STATIC / "i18n" / "tr.json").read_text(encoding="utf-8"))
    base_en = json.loads((STATIC / "i18n" / "en.json").read_text(encoding="utf-8"))
    catalogs = {"tr": {**base_tr, **CATALOG["tr"]}, "en": {**base_en, **CATALOG["en"]}}
    setup = (
        f"i18n.setCatalogs({json.dumps(language)}, "
        f"{json.dumps(catalogs[language], ensure_ascii=False)}, "
        f"{json.dumps(catalogs['tr'], ensure_ascii=False)});"
    )
    dynamic = (
        f"const i18n = await import({json.dumps(imports['i18n'])});"
        f"{setup}const view = await import({json.dumps(imports['view'])});"
    )
    harness = tmp_path / "recovery_view.mjs"
    harness.write_text(dynamic + body, encoding="utf-8")
    result = subprocess.run([shutil.which("node") or "node", str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_flow_navigation_validation_and_skip_paths(tmp_path) -> None:
    data = FLOW
    body = f"""
let s = {{...view.emptyState(), node: {json.dumps(data['start'])}}};
const choose = (node, answer) => {{
  const next = view.choose({json.dumps(data)}, s, node, answer, 1000);
  const valid = next !== s;
  s = next;
  return valid;
}};
const senin = choose('konu','senin') && choose('senin_ne','kod_eski') && s.node === 'senin_numara_son';
s = {{...view.emptyState(),node:'konu'}};
const site = choose('konu','site') && choose('giris_soru','hayir') && s.node === 'senin_ne';
s = {{...view.emptyState(),node:'konu'}};
const ikart = choose('konu','ikart') && choose('ikart_ne','uygulama') && choose('ikart_vpn_c','failed')
  && choose('ikart_market_c','not_tried') && s.node === 'ikart_son';
s = {{...view.emptyState(),node:'ikart_sms_c'}};
const solved = view.choose({json.dumps(data)}, s, 'ikart_sms_c', 'solved', 1000).node === '__solved';
s = {{...view.emptyState(),node:'konu'}};
const invalid = view.choose({json.dumps(data)}, s, 'konu', 'not-an-option', 1000) === s;
s = view.choose({json.dumps(data)}, s, 'konu', 'senin', 1000);
s = view.choose({json.dumps(data)}, s, 'senin_ne', 'kod_eski', 1000);
const reversed = view.back({json.dumps(data)}, s).node;
const pruned = structuredClone({json.dumps(data)});
pruned.nodes.ikart_sms_c = {{kind:'skip',text:{{tr:'',en:''}},next:'ikart_son'}};
const skip = view.choose(pruned, {{...view.emptyState(),node:'konu'}}, 'konu', 'ikart', 1000);
console.log(JSON.stringify([senin,site,ikart,solved,invalid,reversed,skip.node]));
"""
    assert run_view(tmp_path, body) == [True, True, True, True, True, "senin_ne", "ikart_ne"]


def test_stored_state_expires_and_rejects_unknown_flow_data(tmp_path) -> None:
    data = FLOW
    now = 2_000_000_000_000
    body = f"""
const flows = {json.dumps(data)};
const now = {now};
let state = {{...view.emptyState(),node:flows.start}};
state = view.choose(flows,state,'konu','senin',now);
state = view.choose(flows,state,'senin_ne','kod_eski',now);
const valid = view.parseStored(JSON.stringify(state),flows,now);
const old = view.parseStored(JSON.stringify({{...state,at:now-31*view.KEEP_DAYS*86400000}}),flows,now);
const unknownNode = view.parseStored(JSON.stringify({{...state,node:'elsewhere'}}),flows,now);
const unknownAnswer = view.parseStored(JSON.stringify({{...state,path:[{{node:'konu',answer:'secret'}}]}}),flows,now);
const v2 = view.parseStored(JSON.stringify({{...state,version:2}}),flows,now);
console.log(JSON.stringify([valid.node,old,unknownNode,unknownAnswer,v2,view.STORAGE_KEY,view.KEEP_DAYS]));
"""
    assert run_view(tmp_path, body) == ["senin_numara_son", None, None, None, None, "nabiz.erisim.v1", 30]


def test_support_summary_masks_secrets_and_preserves_date_time(tmp_path) -> None:
    data = view_payload()
    body = f"""
const flows = {json.dumps(data, ensure_ascii=False)};
let state = {{...view.emptyState(),node:flows.start}};
state = view.choose(flows,state,'konu','ikart',1000);
state = view.choose(flows,state,'ikart_ne','sms_yok',1001);
state = view.choose(flows,state,'ikart_sms_c','failed',1002);
state = {{...state,node:'ikart_son'}};
const summary = view.summaryText(flows,state,flows.contact,Date.parse('2026-09-26T11:30:00Z'));
const email = 'x' + String.fromCharCode(64) + 'y.example';
const masked = view.maskSummary('kod 482913; kart 5890 1234 5678 9012; ' + email + '; 26.09.2026 14:30');
console.log(JSON.stringify([summary,masked,email]));
"""
    summary, masked, email = run_view(tmp_path, body)
    assert "Konu: İstanbulkart Mobil ya da bireysel hesabım" in summary
    assert "Denenen adımlar:" in summary and "Adımların kaynağı: www.istanbulkart.istanbul" in summary
    assert "kurum doğrulaması değildir" in summary and "T.C. kimlik numarası" in summary
    assert "erişiminiz geri" not in summary.lower() and "başarılı" not in summary.lower()
    assert "482913" not in masked and "5890" not in masked and email not in masked
    assert "26.09.2026 14:30" in masked


def test_markup_escapes_quotes_keeps_sources_turkish_and_limits_links(tmp_path) -> None:
    data = view_payload()
    data["quotes"]["g_online_islemler"]["parts"] = [FLOW["quotes"]["g_online_islemler"]["parts"][0] + " <b>alıntı</b>"]
    markup_data = json.dumps(data, ensure_ascii=False)
    body = f"""
const flows = {markup_data};
const quote = view.stepMarkup(flows,{{...view.emptyState(),node:'ikart_adres_c'}},'en',true);
const section = view.sectionMarkup(flows,{{...view.emptyState(),node:'konu'}},false);
const summary = view.summaryMarkup('kod 482913','en');
console.log(JSON.stringify([quote,section,summary]));
"""
    quote, section, summary = run_view(tmp_path, body, "en")
    assert quote.count("<h3") == 1 and 'blockquote lang="tr"' in quote
    assert "&lt;b&gt;alıntı&lt;/b&gt;" in quote and "Source text is Turkish." in quote
    assert "https://www.belbim.istanbul" in quote
    assert 'href="https://www.istanbulkart.istanbul/guvenlik"' in quote
    assert 'href="https://www.belbim.istanbul"' not in quote
    assert "quote-exact" not in quote and 'type="checkbox"' in section
    assert 'class="btn" data-erisim="copy"' in summary
    assert "btn-primary" not in section and "btn-primary" not in quote
    assert '<textarea id="erisim-summary" readonly' in summary and "summary_tr_note" not in summary


def test_catalog_fallbacks_and_placeholders_match_both_languages() -> None:
    sources = [VIEW.read_text(encoding="utf-8"), MOUNT.read_text(encoding="utf-8")]
    calls = {key: value for source in sources for key, value in (
        (match.group(2), js_fallback(match.group(4))) for match in UI_CALL.finditer(source)
    ) if key.startswith("ui.erisim.")}
    assert set(calls) == set(CATALOG["tr"])
    assert calls == CATALOG["tr"]
    keys = {key for source in sources for _, key in UI_KEY.findall(source) if key.startswith("ui.erisim.")}
    assert keys == set(CATALOG["tr"]) == set(CATALOG["en"])
    for key in CATALOG["tr"]:
        assert set(re.findall(r"\{(\w+)\}", CATALOG["tr"][key])) == set(re.findall(r"\{(\w+)\}", CATALOG["en"][key]))
        assert "—" not in CATALOG["tr"][key] + CATALOG["en"][key]
        assert "–" not in CATALOG["tr"][key] + CATALOG["en"][key]


MOUNT_DOM_STUB = r"""
class Element {
  constructor(doc, tag = 'div', id = '') {
    Object.assign(this, {
      doc, tagName: tag, id, dataset: {}, children: [], listeners: {}, hidden: false,
      checked: false, value: '', attrs: {}, parent: null, className: '',
    });
  }
  set innerHTML(value) {
    this._html = value;
    this.children = [];
    if (this.tagName === 'div' && value.includes('<details')) {
      const section = new Element(this.doc, 'details', 'erisim-kurtar');
      section.seed();
      this.firstElementChild = section;
      this.children = [section];
      section.parent = this;
      this.doc.ids.set(section.id, section);
      return;
    }
    this.seedDynamic(value);
  }
  get innerHTML() { return this._html || ''; }
  seed() {
    this.refs = new Map();
    const entries = [
      ['#erisim-title', 'h2', 'erisim-title'], ['.section-note', 'p', ''],
      ['.erisim-safe', 'p', ''], ['#erisim-remember', 'input', 'erisim-remember'],
      ['.erisim-remember-copy', 'span', ''], ['.erisim-trail', 'ol', ''],
      ['.erisim-step', 'div', ''], ['[data-erisim="back"]', 'button', ''],
      ['[data-erisim="restart"]', 'button', ''], ['[data-erisim="forget"]', 'button', ''],
      ['.erisim-foot', 'p', ''],
    ];
    for (const [key, tag, id] of entries) {
      const child = new Element(this.doc, tag, id);
      child.parent = this;
      this.refs.set(key, child);
    }
    const safe = this.refs.get('.erisim-safe');
    safe.children = [new Element(this.doc, 'svg')];
    safe.children[0].parent = safe;
  }
  seedDynamic(value) {
    this.refs = new Map();
    const question = value.match(/<h3[^>]*id="erisim-q"[^>]*>(.*?)<\/h3>/s);
    if (question) {
      const node = new Element(this.doc, 'h3', 'erisim-q');
      node.textContent = question[1];
      node.parent = this;
      this.refs.set('#erisim-q', node);
      this.doc.ids.set(node.id, node);
    }
    if (value.includes('class="status-line"')) {
      const node = new Element(this.doc, 'p');
      node.parent = this;
      this.refs.set('.status-line', node);
    }
    for (const match of value.matchAll(/<button[^>]*data-erisim-answer="([a-z_]+)"[^>]*>/g)) {
      const node = new Element(this.doc, 'button');
      node.dataset.erisimAnswer = match[1];
      node.parent = this;
      this.refs.set(`[data-erisim-answer="${match[1]}"]`, node);
    }
  }
  querySelector(selector) { return this.refs?.get(selector) || null; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(key, value) { this.attrs[key] = value; }
  append(...items) {
    this.children.push(...items);
    for (const item of items) item.parent = this;
  }
  replaceChildren(...items) {
    this.children = items;
    for (const item of items) item.parent = this;
  }
  insertAdjacentElement(position, item) {
    this.position = position;
    item.parent = this;
    this.doc.ids.set(item.id, item);
  }
  contains(item) {
    let node = item;
    while (node) {
      if (node === this) return true;
      node = node.parent;
    }
    return false;
  }
  focus() { this.doc.activeElement = this; }
  select() {}
}
Element.prototype.querySelector = function (selector) {
  if (this.refs?.has(selector)) return this.refs.get(selector);
  if (this.id !== 'erisim-kurtar') return null;
  if (['#erisim-q', '.status-line'].includes(selector)) {
    return this.refs.get('.erisim-step').refs?.get(selector) || null;
  }
  const answer = selector.match(/^\[data-erisim-answer="(.+)"\]$/);
  if (answer) return this.refs.get('.erisim-step').refs?.get(selector) || null;
  const action = selector.match(/^\[data-erisim="(.+)"\]$/);
  if (action) return this.refs.get(`[data-erisim="${action[1]}"]`) || null;
  return null;
};
Element.prototype.closest = function (selector) {
  return selector.includes('data-erisim') ? this : null;
};
"""


def test_mount_has_no_request_without_anchor_and_keeps_answers_on_device(tmp_path) -> None:
    payload = view_payload()
    expected_title = json.dumps(payload["nodes"]["senin_numara_son"]["text"]["en"], ensure_ascii=False)
    mount_url = json.dumps(MOUNT.as_uri())
    i18n_url = json.dumps((JS / "i18n_text.js").as_uri())
    setup = "\n".join([
        "globalThis.window = {location: {search: '', origin: 'http://localhost', hash: ''}, listeners: {},",
        "  addEventListener(name, callback) { this.listeners[name] = callback; }, removeEventListener() {}};",
        "let network = [];",
        "globalThis.fetch = async (url, init = {}) => { network.push({url: String(url), "
        "method: init.method, body: init.body || null}); "
        f"return {{ok: true, status: 200, json: async () => ({json.dumps(payload, ensure_ascii=False)})}}; }};",
        f"const i18n = await import({i18n_url});",
        f"i18n.setCatalogs('tr', {json.dumps(CATALOG['tr'], ensure_ascii=False)}, "
        f"{json.dumps(CATALOG['tr'], ensure_ascii=False)});",
        f"const recovery = await import({mount_url});",
    ])
    actions = "\n".join([
        "const anchor = new Element(null, 'section');",
        "const head = new Element(null, 'head');",
        "const doc = {head, documentElement: {lang: 'tr'}, activeElement: null, ids: new Map(), defaultView: window,",
        "  querySelector: () => null, getElementById: () => null, createElement: (tag) => new Element(doc, tag)};",
        "anchor.doc = doc; head.doc = doc;",
        "const storage = {value: null, getItem() {return this.value;},",
        "  setItem(key, value) {this.key = key; this.value = value;}, removeItem() {this.value = null;}};",
        "const absent = recovery.mountRecovery(doc, storage);",
        "const noRequest = network.length;",
        "doc.querySelector = (selector) => selector === '#hesabim' ? anchor : null;",
        "doc.getElementById = (id) => doc.ids.get(id) || null;",
        "const mounted = recovery.mountRecovery(doc, storage);",
        "await new Promise((resolve) => setTimeout(resolve, 0));",
        "window.location.hash = '#erisim-kurtar'; window.listeners.hashchange();",
        "const hashOpened = mounted.open && doc.activeElement.id === 'erisim-q';",
        f"i18n.setCatalogs('en', {json.dumps(CATALOG['en'], ensure_ascii=False)}, "
        f"{json.dumps(CATALOG['tr'], ensure_ascii=False)});",
        "window.listeners['nabiz:lang']({detail: {lang: 'en'}});",
        "const languageKeptFocus = doc.activeElement.id === 'erisim-q' && network.length === 1;",
        "const step = mounted.querySelector('.erisim-step');",
        "mounted.listeners.click({target: step.refs.get('[data-erisim-answer=\"senin\"]')});",
        "mounted.listeners.click({target: step.refs.get('[data-erisim-answer=\"kod_eski\"]')});",
        "const remember = mounted.querySelector('#erisim-remember');",
        "const unconsented = storage.value === null; remember.checked = true;",
        "mounted.listeners.change({target: remember});",
        "const saved = JSON.parse(storage.value);",
        "const anchor2 = new Element(null, 'section'), head2 = new Element(null, 'head');",
        "const doc2 = {head: head2, documentElement: {lang: 'en'}, activeElement: null, ids: new Map(), defaultView: window,",
        "  querySelector: () => null, getElementById: () => null, createElement: (tag) => new Element(doc2, tag)};",
        "anchor2.doc = doc2; head2.doc = doc2;",
        "doc2.querySelector = (selector) => selector === '#hesabim' ? anchor2 : null;",
        "doc2.getElementById = (id) => doc2.ids.get(id) || null;",
        "const reloaded = recovery.mountRecovery(doc2, storage); await new Promise((resolve) => setTimeout(resolve, 0));",
        "const restored = reloaded.querySelector('.erisim-step').refs.get('#erisim-q');",
        f"const restoredWithConsent = restored.textContent === {expected_title}",
        "  && reloaded.querySelector('#erisim-remember').checked;",
        "remember.checked = false; mounted.listeners.change({target: remember});",
        "const removedAfterConsent = storage.value === null;",
        "console.log(JSON.stringify([absent, noRequest, anchor.position, network, saved, storage.key, "
        "hashOpened, languageKeptFocus, unconsented, restoredWithConsent, removedAfterConsent]));",
    ])
    harness = tmp_path / "recovery_mount.mjs"
    harness.write_text(setup + MOUNT_DOM_STUB + actions, encoding="utf-8")
    result = subprocess.run([shutil.which("node") or "node", str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    (absent, no_request, position, network, saved, key, hash_opened, language_focus, unconsented,
     restored_with_consent, removed_after_consent) = json.loads(result.stdout)
    assert absent is None and no_request == 0 and position == "beforeend"
    assert len(network) == 1 and network[0]["url"].endswith("/api/erisim/flows") and network[0]["body"] is None
    assert saved["node"] == "senin_numara_son" and saved["path"] == [
        {"node": "konu", "answer": "senin"}, {"node": "senin_ne", "answer": "kod_eski"},
    ]
    assert set(saved) == {"version", "node", "path", "checks", "at"}
    assert key == "nabiz.erisim.v1"
    assert hash_opened and language_focus
    assert unconsented and restored_with_consent and removed_after_consent


def test_mount_failure_offers_only_153_and_keeps_error_local(tmp_path) -> None:
    mount_url = json.dumps(MOUNT.as_uri())
    i18n_url = json.dumps((JS / "i18n_text.js").as_uri())
    setup = "\n".join([
        "globalThis.window = {location: {search: '', origin: 'http://localhost', hash: ''}, listeners: {},",
        "  addEventListener(name, callback) { this.listeners[name] = callback; }, removeEventListener() {}};",
        "let network = []; globalThis.fetch = async (url, init = {}) => { network.push({url: String(url), "
        "body: init.body || null}); throw new Error('offline'); };",
        f"const i18n = await import({i18n_url});",
        f"const recovery = await import({mount_url});",
        "const anchor = new Element(null, 'section'), head = new Element(null, 'head');",
        "const doc = {head, documentElement: {lang: 'tr'}, activeElement: null, ids: new Map(), defaultView: window,",
        "  querySelector: (selector) => selector === '#hesabim' ? anchor : null, getElementById: () => null,",
        "  createElement: (tag) => new Element(doc, tag)}; anchor.doc = doc; head.doc = doc;",
        "const section = recovery.mountRecovery(doc, null); await new Promise((resolve) => setTimeout(resolve, 0));",
        "const step = section.querySelector('.erisim-step'), [message, call] = step.children;",
        "console.log(JSON.stringify([message.textContent, call.href, network]));",
    ])
    harness = tmp_path / "recovery_failure.mjs"
    harness.write_text(MOUNT_DOM_STUB + setup, encoding="utf-8")
    result = subprocess.run([shutil.which("node") or "node", str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    message, href, network = json.loads(result.stdout)
    assert "153" in message and href == "tel:153"
    assert len(network) == 1 and network[0]["url"].endswith("/api/erisim/flows") and network[0]["body"] is None


def test_mount_preserves_consent_selected_while_flow_loads(tmp_path) -> None:
    payload = json.dumps(view_payload(), ensure_ascii=False)
    mount_url = json.dumps(MOUNT.as_uri())
    setup = "\n".join([
        "globalThis.window = {location: {search: '', origin: 'http://localhost', hash: ''}, listeners: {},",
        "  addEventListener(name, callback) { this.listeners[name] = callback; }, removeEventListener() {}};",
        "let finishFetch; globalThis.fetch = async () => new Promise((resolve) => {",
        f"  finishFetch = () => resolve({{ok: true, status: 200, json: async () => ({payload})}}); }});",
        f"const recovery = await import({mount_url});",
        "const anchor = new Element(null, 'section'), head = new Element(null, 'head');",
        "const doc = {head, documentElement: {lang: 'tr'}, activeElement: null, ids: new Map(), defaultView: window,",
        "  querySelector: (selector) => selector === '#hesabim' ? anchor : null, getElementById: () => null,",
        "  createElement: (tag) => new Element(doc, tag)}; anchor.doc = doc; head.doc = doc;",
        "const storage = {value: null, getItem() {return this.value;},",
        "  setItem(key, value) {this.key = key; this.value = value;}, removeItem() {this.value = null;}};",
        "const section = recovery.mountRecovery(doc, storage);",
        "const remember = section.querySelector('#erisim-remember'); remember.checked = true;",
        "section.listeners.change({target: remember}); finishFetch();",
        "await new Promise((resolve) => setTimeout(resolve, 0));",
        "console.log(JSON.stringify([JSON.parse(storage.value), storage.key]));",
    ])
    harness = tmp_path / "recovery_consent.mjs"
    harness.write_text(MOUNT_DOM_STUB + setup, encoding="utf-8")
    result = subprocess.run([shutil.which("node") or "node", str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    saved, key = json.loads(result.stdout)
    assert key == "nabiz.erisim.v1" and saved["node"] == FLOW["start"]
    assert set(saved) == {"version", "node", "path", "checks", "at"}


def test_source_rules_no_extra_inputs_motion_or_unreviewed_links() -> None:
    view, mount, css = (path.read_text(encoding="utf-8") for path in (VIEW, MOUNT, CSS))
    for source in (view, mount):
        for forbidden in (
            "setInterval", "dispatchEvent", "btn-primary", "/api/console", "innerHTML +=",
            'type="password"', 'type="tel"', 'type="text"',
        ):
            assert forbidden not in source
        assert "—" not in source and "–" not in source
    assert mount.count("localStorage") == 1 and "function safeStorage()" in mount
    clean_css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(", clean_css)
    for forbidden in ("transition", "animation", "infinite", "--bad"):
        assert forbidden not in clean_css
    icons = set(re.findall(r"icon\('([^']+)'\)", view))
    sprite = (STATIC / "icons.svg").read_text(encoding="utf-8")
    assert all(f'id="i-{name}"' in sprite for name in icons)
    assert CATALOG["tr"]["ui.erisim.contact_call"].format(call="153")
    assert AGENCIES["call"] == "153"


def test_modules_have_no_bare_turkish_outside_fallbacks() -> None:
    for path in (VIEW, MOUNT):
        source = path.read_text(encoding="utf-8")
        clean = re.sub(r"/\*.*?\*/|^\s*//.*$", "", source, flags=re.S | re.M)
        spans = [match.span(4) for match in UI_CALL.finditer(clean)]
        literals = list(clean)
        for start, end, chunks in template_literals(clean):
            assert all(not TURKISH_CHARS.search(chunk) for chunk in chunks), path.name
            literals[start:end] = [" "] * (end - start)
        remaining = "".join(literals)
        for match in re.finditer(r"'((?:\\.|[^'\\])*)'|\"((?:\\.|[^\"\\])*)\"", remaining, re.S):
            value = match.group(1) if match.group(1) is not None else match.group(2)
            if TURKISH_CHARS.search(value):
                if value == "Kaynak metin Türkçedir.":
                    continue
                assert any(left <= match.start(1) <= right for left, right in spans), (path.name, value)


def test_copy_helpers_smoke(tmp_path) -> None:
    assert node_json(tmp_path, {"view": "js/recovery_view.js"}, "console.log(JSON.stringify(view.emptyState()));") == {
        "version": 1, "node": None, "path": [], "checks": {}, "at": 0,
    }


def test_the_page_catalogues_carry_the_recovery_keys_unchanged() -> None:
    """P00 G5: the ui.erisim.* keys moved into the page catalogues, unchanged, in both languages."""
    for lang in ("tr", "en"):
        surface = json.loads((STATIC / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
        assert all(surface[k] == v for k, v in CATALOG[lang].items())
