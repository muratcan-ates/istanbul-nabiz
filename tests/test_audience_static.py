# The JavaScript harnesses below keep executable snippets on single lines.
# ruff: noqa: E501

from __future__ import annotations

import json
import re
import shutil
import subprocess

from conftest import REPO_ROOT
from test_i18n_surfaces import TURKISH_CHARS, UI_CALL, js_fallback, template_literals
from test_static_a11y import node_json

STATIC = REPO_ROOT / "src/nabiz/console/static"
JS_DIR = STATIC / "js"
CATALOG = {
    "tr": {
        "ui.aud.title": "Size göre öneriler",
        "ui.aud.note": (
            "İsteğe bağlı. Seçiminiz yalnız bu cihazda durur, sunucuya gönderilmez; "
            "bir soruya dokunursanız yalnız o soru gönderilir."
        ),
        "ui.aud.edit_start": "Yaş grubunuzu ve ihtiyacınızı seçin",
        "ui.aud.edit_change": "Seçimi değiştir",
        "ui.aud.age_legend": "Yaş grubu",
        "ui.aud.age_none": "Belirtmek istemiyorum",
        "ui.aud.needs_legend": "İhtiyaç (birden çok seçebilirsiniz)",
        "ui.aud.g_ogrenci": "Öğrenci",
        "ui.aud.h_ogrenci": "Kart, kütüphane ve kurslar",
        "ui.aud.g_calisan": "Çalışan",
        "ui.aud.h_calisan": "Günlük yol, durak ve otopark",
        "ui.aud.g_yas65": "65 yaş ve üstü",
        "ui.aud.h_yas65": "Sağlık ve sosyal hizmetler, adımsız yol",
        "ui.aud.g_tekerlekli": "Tekerlekli sandalye",
        "ui.aud.h_tekerlekli": "Asansör ve adımsız yol",
        "ui.aud.g_gorme": "Görme",
        "ui.aud.h_gorme": "Az görme ya da ekran okuyucu",
        "ui.aud.g_isitme": "İşitme",
        "ui.aud.h_isitme": "Yazılı bilgi ve yazılı iletişim",
        "ui.aud.g_bilissel": "Bilişsel kolaylık",
        "ui.aud.h_bilissel": "Kısa ve sade anlatım",
        "ui.aud.g_turist": "Turist",
        "ui.aud.h_turist": "Şehre yeni gelenler için",
        "ui.aud.chosen": "Seçiminiz: {list}",
        "ui.aud.chips_label": "Size göre sorular ve sayfalar",
        "ui.aud.ask_suffix": "(dokununca sorulur)",
        "ui.aud.page_suffix": "(resmî sayfa, yeni sekmede açılır)",
        "ui.aud.more": "Daha fazla öneri",
        "ui.aud.shortcuts": "Kısayollar",
        "ui.aud.profile_line": (
            "Cevaplarınızda bu ihtiyaçları dikkate almak için Profilim'de ilgili "
            "kutuları işaretleyebilirsiniz: {needs}."
        ),
        "ui.aud.profile_go": "Profilim'e git",
        "ui.aud.need_step_free": "Adımsız erişim",
        "ui.aud.need_low_vision": "Az görüyorum",
        "ui.aud.need_hearing": "Az duyuyorum",
        "ui.aud.need_plain_language": "Sade dil",
        "ui.aud.kolay_text": "Daha büyük düğmeler ve tek adımlı bir ekran için Kolay ekranı deneyin.",
        "ui.aud.kolay_open": "Kolay ekranı aç",
        "ui.aud.kolay_hide": "Gizle",
        "ui.aud.clear": "Seçimi temizle",
        "ui.aud.count": "{n} öneri gösteriliyor.",
        "ui.aud.empty": "Bu seçim için şu an gösterilecek öneri yok. Sorunuzu yukarıya yazabilirsiniz.",
        "ui.aud.cleared": "Seçiminiz bu cihazdan silindi.",
        "ui.aud.failed": "Öneriler şu an yüklenemedi.",
        "ui.aud.retry": "Yeniden dene",
        "ui.aud.persona_text": "Yazı boyutu ve kontrast için görünümü de ayarlayabilirsiniz.",
        "ui.aud.persona_open": "Görünümü ayarla",
    },
    "en": {
        "ui.aud.title": "Suggestions for you",
        "ui.aud.note": (
            "Optional. Your choice stays on this device and is not sent to the server; "
            "if you tap a question, only that question is sent."
        ),
        "ui.aud.edit_start": "Choose your age group and needs",
        "ui.aud.edit_change": "Change your choice",
        "ui.aud.age_legend": "Age group",
        "ui.aud.age_none": "Prefer not to say",
        "ui.aud.needs_legend": "Needs (you can choose more than one)",
        "ui.aud.g_ogrenci": "Student",
        "ui.aud.h_ogrenci": "Cards, libraries and courses",
        "ui.aud.g_calisan": "Working",
        "ui.aud.h_calisan": "Daily commute, stops and parking",
        "ui.aud.g_yas65": "65 or older",
        "ui.aud.h_yas65": "Health and social services, step-free routes",
        "ui.aud.g_tekerlekli": "Wheelchair",
        "ui.aud.h_tekerlekli": "Lifts and step-free routes",
        "ui.aud.g_gorme": "Sight",
        "ui.aud.h_gorme": "Low vision or a screen reader",
        "ui.aud.g_isitme": "Hearing",
        "ui.aud.h_isitme": "Written information and contact",
        "ui.aud.g_bilissel": "Easier to follow",
        "ui.aud.h_bilissel": "Short, plain explanations",
        "ui.aud.g_turist": "Visitor",
        "ui.aud.h_turist": "For people new to the city",
        "ui.aud.chosen": "Your choice: {list}",
        "ui.aud.chips_label": "Questions and pages for you",
        "ui.aud.ask_suffix": "(asks now)",
        "ui.aud.page_suffix": "(official page, opens in a new tab)",
        "ui.aud.more": "More suggestions",
        "ui.aud.shortcuts": "Shortcuts",
        "ui.aud.profile_line": (
            "To have your answers take these needs into account, you can tick the "
            "matching boxes in My profile: {needs}."
        ),
        "ui.aud.profile_go": "Go to My profile",
        "ui.aud.need_step_free": "Step-free access",
        "ui.aud.need_low_vision": "Low vision",
        "ui.aud.need_hearing": "Hard of hearing",
        "ui.aud.need_plain_language": "Plain language",
        "ui.aud.kolay_text": "The easy screen has bigger buttons and one step at a time (Turkish only).",
        "ui.aud.kolay_open": "Open the easy screen",
        "ui.aud.kolay_hide": "Hide",
        "ui.aud.clear": "Clear my choice",
        "ui.aud.count": "{n} suggestions shown.",
        "ui.aud.empty": "There is nothing to suggest for this choice right now. You can type your question above.",
        "ui.aud.cleared": "Your choice was removed from this device.",
        "ui.aud.failed": "Suggestions could not be loaded right now.",
        "ui.aud.retry": "Try again",
        "ui.aud.persona_text": "You can also adjust text size and contrast in your appearance settings.",
        "ui.aud.persona_open": "Adjust appearance",
    },
}


def _data() -> dict:
    return json.loads((REPO_ROOT / "data/knowledge/audience_suggestions.json").read_text(encoding="utf-8"))


def _payload() -> dict:
    data = _data()
    kinds = {"arac": "tool", "kurum": "agency", "bilgi": "knowledge", "sayfa": "page"}
    return {
        "groups": [
            {
                "id": group["id"],
                "kind": "age" if group["tur"] == "yas" else "need",
                "suggestions": group["oneriler"],
                "shortcuts": group["kisayollar"],
                "profile": group["profil"],
                "kolay": group["kolay"],
            }
            for group in data["gruplar"]
        ],
        "suggestions": [
            {
                "id": item["id"],
                "kind": kinds[item["tur"]],
                "text_tr": item["metin_tr"],
                "text_en": item["metin_en"],
                "url": item.get("url"),
            }
            for item in data["oneriler"]
        ],
        "shortcuts": [
            {"id": item["id"], "target": item["hedef"], "text_tr": item["metin_tr"], "text_en": item["metin_en"]}
            for item in data["kisayollar"]
        ],
    }


def test_selection_parser_and_round_robin_rules(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"view": "js/audience_view.js", "i18n": "js/i18n_text.js"},
        f"""
        i18n.setCatalogs('tr', {json.dumps(CATALOG["tr"], ensure_ascii=False)}, {json.dumps(CATALOG["tr"], ensure_ascii=False)});
        const payload = {json.dumps(_payload(), ensure_ascii=False)};
        const bad = [null, '', '{{', '[]', '{{"version":2}}', '{{"version":1,"age":"cocuk"}}'];
        const duplicate = view.parseSelection('{{"version":1,"age":"yas65","needs":["tekerlekli","tekerlekli","cocuk"]}}');
        const selection = view.parseSelection('{{"version":1,"age":"yas65","needs":["tekerlekli"]}}');
        const picked = view.pickSuggestions(payload, selection, {{ lang: 'tr', present: new Set(['composer','journey-section','alternative','kultur','profilim']), profile: {{ consent: false, needs: ['step_free'] }} }});
        const accepted = view.pickSuggestions(payload, selection, {{ lang: 'tr', present: new Set(['composer','profilim']), profile: {{ consent: true, needs: ['step_free'] }} }});
        const persona = view.pickSuggestions(payload, selection, {{ lang: 'tr', present: new Set(['composer','persona']), profile: {{}}, personaUnset: true }});
        const activePersona = view.pickSuggestions(payload, selection, {{ lang: 'tr', present: new Set(['composer','persona']), profile: {{}}, personaUnset: false }});
        const noPersonaControl = view.pickSuggestions(payload, selection, {{ lang: 'tr', present: new Set(['composer']), profile: {{}}, personaUnset: true }});
        const visitor = view.pickSuggestions(payload, view.parseSelection('{{"version":1,"age":null,"needs":["turist"]}}'), {{ lang: 'tr', present: new Set(['composer','language-switch']), profile: {{}} }});
        const visitorEnglish = view.pickSuggestions(payload, view.parseSelection('{{"version":1,"age":null,"needs":["turist"]}}'), {{ lang: 'en', present: new Set(['composer','language-switch']), profile: {{}} }});
        const english = view.pickSuggestions(payload, selection, {{ lang: 'en', present: new Set(['composer','profilim']), profile: {{}} }});
        const noComposer = view.pickSuggestions(payload, selection, {{ lang: 'tr', present: new Set(['journey-section','alternative']), profile: {{}} }});
        const missingShortcut = view.pickSuggestions(payload, selection, {{ lang: 'tr', present: new Set(['composer','journey-section']), profile: {{}} }});
        const empty = view.pickSuggestions(payload, view.parseSelection(null), {{ lang: 'tr', present: new Set(['composer']), profile: {{}} }});
        console.log(JSON.stringify({{ bad: bad.map(view.parseSelection), duplicate, picked, accepted, persona, activePersona, noPersonaControl, visitor, visitorEnglish, english, noComposer, missingShortcut, empty }}));
        """,
    )
    assert all(value == {"version": 1, "age": None, "needs": [], "kolay_hidden": False} for value in values["bad"])
    assert values["duplicate"]["needs"] == ["tekerlekli"]
    assert [item["id"] for item in values["picked"]["chips"]] == [
        "a-yenikapi-adimsiz",
        "s-yasli-hizmetleri",
        "a-taksim-asansor",
    ]
    assert [item["id"] for item in values["picked"]["shortcuts"]] == ["journey-section", "alternative", "kultur"]
    assert values["picked"]["profileNeeds"] == ["step_free"] and values["picked"]["kolay"] is True
    assert values["accepted"]["profileNeeds"] == []
    assert values["persona"]["persona"] == "hareket"
    assert values["activePersona"]["persona"] is None and values["noPersonaControl"]["persona"] is None
    assert values["visitor"]["switchLanguage"] is True and values["visitorEnglish"]["switchLanguage"] is False
    assert values["english"]["kolay"] is False and all(
        item["kind"] != "knowledge" for item in values["english"]["chips"] + values["english"]["more"]
    )
    assert all(item["kind"] == "page" for item in values["noComposer"]["chips"] + values["noComposer"]["more"])
    assert [item["id"] for item in values["missingShortcut"]["shortcuts"]] == ["journey-section"]
    assert values["empty"] == {
        "chips": [],
        "more": [],
        "shortcuts": [],
        "profileNeeds": [],
        "kolay": False,
        "persona": None,
        "switchLanguage": False,
    }


def test_markup_is_escaped_accessible_and_has_no_extra_primary_action(tmp_path) -> None:
    page = {
        "id": "page-x",
        "kind": "page",
        "text_tr": "Resmî sayfa",
        "text_en": "Official page",
        "url": "https://example.org/page",
    }
    question = {"id": "question-x", "kind": "tool", "text_tr": "<img src=x>", "text_en": "Is it open?", "url": None}
    result = node_json(
        tmp_path,
        {"view": "js/audience_view.js", "i18n": "js/i18n_text.js"},
        f"""
        i18n.setCatalogs('tr', {json.dumps(CATALOG["tr"], ensure_ascii=False)}, {json.dumps(CATALOG["tr"], ensure_ascii=False)});
        const question = view.chipMarkup({json.dumps(question, ensure_ascii=False)}, 'tr');
        const page = view.chipMarkup({json.dumps(page, ensure_ascii=False)}, 'tr');
        const picked = {{ chips: [{json.dumps(question, ensure_ascii=False)}, {json.dumps(page, ensure_ascii=False)}], more: [], shortcuts: [], profileNeeds: [], kolay: false }};
        const html = view.sectionMarkup(view.parseSelection(null), 'tr') + view.resultMarkup(picked, view.parseSelection('{{"version":1,"age":"yas65","needs":[]}}'), 'tr');
        console.log(JSON.stringify({{ question, page, html }}));
        """,
    )
    assert (
        '<button type="button"' in result["question"]
        and 'aria-label="&lt;img src=x&gt; (dokununca sorulur)"' in result["question"]
    )
    assert "<img" not in result["question"] and "&lt;img src=x&gt;" in result["question"]
    assert 'target="_blank"' in result["page"] and 'rel="noopener noreferrer"' in result["page"]
    assert "(resmî sayfa, yeni sekmede açılır)" in result["page"]
    assert "btn-primary" not in result["html"] and "btn-danger" not in result["html"] and "is-bad" not in result["html"]
    assert "tel:" not in result["html"] and 'role="status"' in result["html"]


def test_catalog_keys_fallbacks_placeholders_and_english_are_aligned() -> None:
    sources = [(JS_DIR / name).read_text(encoding="utf-8") for name in ("audience.js", "audience_view.js")]
    calls = {match.group(2): js_fallback(match.group(4)) for source in sources for match in UI_CALL.finditer(source)}
    keys = {match.group(2) for source in sources for match in re.finditer(r"t\(\s*(['\"])(ui\.aud\.[^'\"]+)\1", source)}
    assert keys == set(CATALOG["tr"]) == set(CATALOG["en"])
    assert calls == CATALOG["tr"]
    for key, value in CATALOG["tr"].items():
        assert set(re.findall(r"\{(\w+)\}", value)) == set(re.findall(r"\{(\w+)\}", CATALOG["en"][key]))
    assert all(TURKISH_CHARS.search(value) is None for value in CATALOG["en"].values())
    existing_tr = json.loads((STATIC / "i18n/tr.json").read_text(encoding="utf-8"))
    existing_en = json.loads((STATIC / "i18n/en.json").read_text(encoding="utf-8"))
    # P00 G4: the keys moved into the page catalogues, unchanged
    assert all(existing_tr[k] == v for k, v in CATALOG["tr"].items())
    assert all(existing_en[k] == v for k, v in CATALOG["en"].items())


def test_new_modules_have_no_untranslated_copy_or_browser_state_in_the_pure_view() -> None:
    for name in ("audience.js", "audience_view.js"):
        source = (JS_DIR / name).read_text(encoding="utf-8")
        clean = re.sub(r"/\*.*?\*/|^\s*//.*$", "", source, flags=re.S | re.M)
        fallback_spans = [match.span(4) for match in UI_CALL.finditer(clean)]
        for _, _, chunks in template_literals(clean):
            assert all(TURKISH_CHARS.search(chunk) is None for chunk in chunks), name
        literals = re.compile(r"'((?:\\.|[^'\\])*)'|\"((?:\\.|[^\"\\])*)\"", re.S)
        for match in literals.finditer(clean):
            group = next(index for index, value in enumerate(match.groups(), start=1) if value is not None)
            value = match.group(group)
            if TURKISH_CHARS.search(value) is None:
                continue
            start, end = match.span(group)
            assert any(left <= start and end <= right for left, right in fallback_spans), (name, value)

    view = (JS_DIR / "audience_view.js").read_text(encoding="utf-8")
    for forbidden in ("document", "window", "fetch", "localStorage", "Date"):
        assert forbidden not in view


def test_mount_is_lazy_and_requests_only_the_fixed_get(tmp_path) -> None:
    if shutil.which("node") is None:
        import pytest

        pytest.skip("node is not installed")
    module_url = (JS_DIR / "audience.js").as_uri()
    api_payload = {
        "groups": [{"id": "yas65", "kind": "age", "suggestions": ["question-x"], "shortcuts": [], "profile": [], "kolay": True}],
        "suggestions": [
            {
                "id": "question-x",
                "kind": "tool",
                "text_tr": "M2'de arıza var mı?",
                "text_en": "Is there a disruption on the M2 line?",
                "url": None,
            }
        ],
        "shortcuts": [],
    }
    harness = tmp_path / "audience_mount.mjs"
    harness.write_text(
        f"""
        globalThis.window = {{ location: {{ search: '', origin: 'http://localhost', hash: '' }}, localStorage: null,
          Element: class FakeElement {{}} , addEventListener() {{}}, removeEventListener() {{}} }};
        let stored = null;
        const storageOps = [];
        window.localStorage = {{ getItem(key) {{ storageOps.push(['get', key]); return key === 'nabiz.audience.v1' ? stored : null; }},
          setItem(key, value) {{ storageOps.push(['set', key, value]); stored = value; }},
          removeItem(key) {{ storageOps.push(['remove', key]); stored = null; }} }};
        const requests = [];
        globalThis.fetch = async (url, options) => {{ requests.push({{ url: String(url), options }}); return {{ ok: true, json: async () => ({json.dumps(api_payload, ensure_ascii=False)}) }}; }};
        const {{ mountAudience }} = await import({json.dumps(module_url)});
        class Element extends window.Element {{
          constructor(id='') {{ super(); this.id=id; this.dataset={{}}; this.listeners={{}}; this.hidden=false; this.open=false; this.children={{}}; this.textContent=''; this.innerHTML=''; this.value=''; this.calls=0; }}
          addEventListener(name, fn) {{ this.listeners[name]=fn; }}
          closest(selector) {{ if (selector.startsWith('#')) return this.id === selector.slice(1) ? this : null; if (selector === 'button[data-aud]') return this.dataset.aud ? this : null; return null; }}
          setAttribute() {{}} removeAttribute() {{}} focus() {{ this.focused=true; }}
          querySelector(selector) {{ return this.children[selector] || null; }}
          querySelectorAll() {{ return []; }}
          contains(node) {{ return Object.values(this.children).includes(node); }}
          insertAdjacentHTML(where, html) {{ this.doc.insertions.push([where, html]); this.doc.makeSection(); }}
          replaceWith(node) {{ this.doc.section=node; }}
        }}
        class FakeDocument {{
          constructor(hasAnchor=true) {{ this.readyState='complete'; this.insertions=[]; this.links=[]; this.ids={{}}; this.section=null; this.head={{ appendChild: (node) => this.links.push(node) }};
            // P00 D2a: the section mounts in Hesabım, after "Size uygun görünüm" (was: before #city-cards).
            if (hasAnchor) this.ids['appearance-options']=Object.assign(new Element('appearance-options'),{{doc:this}});
            this.ids['chat-form']=new Element('chat-form'); this.ids['chat-form'].requestSubmit=()=>{{this.ids['chat-form'].calls+=1;}};
                this.ids['chat-input']=new Element('chat-input'); this.ids['profilim']=new Element('profilim');
                this.ids['persona-open']=new Element('persona-open'); this.ids['persona-open'].click=()=>{{this.ids['persona-open'].calls+=1;}};
                for (const id of ['journey-section','alternative','kultur','compare','my-stops','takip','harita']) this.ids[id]=new Element(id);
          }}
          createElement(name) {{ const node=new Element(); node.tagName=name.toUpperCase(); return node; }}
          querySelector() {{ return this.links.find((item)=>item.href==='/css/audience.css') || null; }}
          getElementById(id) {{ return id==='size-gore' ? this.section : this.ids[id] || null; }}
          addEventListener() {{}}
          makeSection() {{
            const section=new Element('size-gore'); section.doc=this;
            const result=new Element('aud-result'); const status=new Element('aud-status');
            const summary=new Element(); const edit=new Element('aud-edit'); edit.children['summary']=summary;
            const clear=new Element('aud-clear'); const title=new Element('aud-title');
            const age=new Element(); const form=new Element('aud-form'); form.querySelector=()=>age; form.querySelectorAll=()=>[];
            section.children={{'#aud-result':result,'#aud-status':status,'#aud-edit':edit,'#aud-form':form,'#aud-clear':clear,'#aud-title':title,'#aud-edit > summary':summary}};
            this.section=section;
          }}
        }}
        const noAnchor=new FakeDocument(false);
        await mountAudience(noAnchor, window);
        const noAnchorRequests=requests.length;
        const first=new FakeDocument(true);
        await mountAudience(first, window);
        const noChoiceRequests=requests.length;
        stored=JSON.stringify({{ version:1, age:'yas65', needs:[], kolay_hidden:false }});
        const second=new FakeDocument(true);
        const section=await mountAudience(second, window);
        const request=requests[0] || {{}};
        const click=section.listeners.click;
        const chip=new Element('question-button'); chip.dataset.aud='question-x';
        click({{ target: chip }});
        const beforeClear=second.section.children['#aud-status'].textContent;
        click({{ target: new Element('aud-persona-open') }});
        const clear=new Element('aud-clear');
        click({{ target: clear }});
        console.log(JSON.stringify({{ noAnchorRequests, noChoiceRequests, requestCount:requests.length, url:new URL(request.url).pathname,
          method:request.options.method || 'GET', body:request.options.body || null, insertion:second.insertions[0][0],
          styles:second.links.length, status:beforeClear, submitted:second.ids['chat-form'].calls,
          question:second.ids['chat-input'].value, personaClicks:second.ids['persona-open'].calls,
          personaWritten:storageOps.some((entry)=>entry[0]==='set' && entry[1]==='nabiz.persona.v1'),
          removed:storageOps.some((entry)=>entry[0]==='remove' && entry[1]==='nabiz.audience.v1') }}));
        """,
        encoding="utf-8",
    )
    result = subprocess.run([shutil.which("node"), str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["noAnchorRequests"] == value["noChoiceRequests"] == 0
    assert value["requestCount"] == value["styles"] == 1
    assert value["url"] == "/api/audience" and value["method"] == "GET" and value["body"] is None
    assert value["insertion"] == "afterend"
    assert value["status"] == "1 öneri gösteriliyor."
    assert value["submitted"] == 1 and value["question"] == "M2'de arıza var mı?"
    assert value["personaClicks"] == 1 and value["personaWritten"] is False
    assert value["removed"] is True


def test_module_css_and_owned_pages_respect_the_visual_contract() -> None:
    js = (JS_DIR / "audience.js").read_text(encoding="utf-8")
    css = (STATIC / "css/audience.css").read_text(encoding="utf-8")
    for forbidden in (
        "btn-primary",
        "btn-danger",
        "is-bad",
        "tel:",
        "sendBeacon",
        "XMLHttpRequest",
        "sessionStorage",
        "setInterval",
        "writeProfile",
        "savePrefs",
    ):
        assert forbidden not in (js + css)
    assert "if (typeof document !== 'undefined')" in js
    assert re.findall(r"['\"](/api/[^'\"]+)", js) == ["/api/audience"]
    assert "localStorage.setItem(AUDIENCE_KEY" in js
    assert "const PERSONA_STATE_KEY = 'nabiz.persona' + '.v1';" in js
    assert "getItem(PERSONA_STATE_KEY)" in js and "setItem(PERSONA_STATE_KEY" not in js
    assert re.search(r"location\.hash\s*=(?!=)", js) is None and "scroll" not in js
    assert all(value not in css for value in ("transition", "animation", "#", "rgba(", "rgb(", "hsl(", "oklch("))
    assert "white-space: normal" in css and "overflow-wrap: anywhere" in css and "min-height: var(--tap)" in css
    allowed = {
        "aud",
        "aud-note",
        "aud-result",
        "aud-results",
        "aud-chosen",
        "aud-empty",
        "aud-error",
        "aud-chips",
        "aud-chip",
        "aud-more",
        "aud-shortcuts",
        "aud-link",
        "aud-profile",
        "aud-kolay",
        "aud-persona",
        "aud-switch-language",
        "aud-form",
        "aud-status",
        "chips",
        "check",
        "check-label",
        "field-hint",
        "more",
        "btn-row",
        "btn",
    }
    classes = set(re.findall(r"\.([A-Za-z][A-Za-z0-9_-]*)", css))
    assert classes <= allowed
    for name in ("console.html", "kolay.html"):
        assert "audience" not in (STATIC / name).read_text(encoding="utf-8").lower()
