"""The E40 citizen surfaces use the shared Turkish and English catalogue without translating server data."""

from __future__ import annotations

import json
import re

from test_static_a11y import STATIC, node_json

MODULES = (
    "account.js", "account_view.js", "follow.js", "quota_strip.js", "request_status.js", "requests_console.js", "open_data.js",
    "culture.js", "console_knowledge_editor.js",
)
JS_DIR = STATIC / "js"
I18N = STATIC / "i18n"
UI_CALL = re.compile(r"t\(\s*(['\"])(ui\.[^'\"]+)\1\s*,\s*(['\"])((?:\\.|[^\\])*?)\3", re.S)
UI_KEY = re.compile(r"t\(\s*(['\"])(ui\.[^'\"]+)\1")
TURKISH_CHARS = re.compile(r"[çğıöşüÇĞİÖŞÜ]")
ARABIC_CHARS = re.compile(r"[\u0600-\u06ff]")
# A regex literal after an operator or an opening bracket (``replace(/[&<>"']/g, ...)``): its quotes are
# not string delimiters and its body is never shown, so the scan blanks it (length kept, offsets hold).
REGEX_LITERAL = re.compile(r"([(,=:!&|?\[]\s*)/(?![/*])((?:\\.|\[(?:\\.|[^\]\\\n])*\]|[^/\\\n\[])+)/([dgimsuvy]*)")
HANDOFF_KEYS = {
    "dyn.handoff_title", "dyn.handoff_description", "dyn.handoff_summary_label", "dyn.handoff_copy",
    "dyn.handoff_call", "dyn.handoff_tid", "dyn.handoff_operator", "dyn.handoff_emergency", "dyn.handoff_close",
}


def catalog(language: str) -> dict[str, object]:
    return json.loads((I18N / f"{language}.json").read_text(encoding="utf-8"))


def js_fallback(value: str) -> str:
    return value.replace("\\\\", "\\").replace("\\'", "'").replace('\\"', '"').replace("\\n", "\n")


def ui_calls(source: str) -> dict[str, str]:
    return {match.group(2): js_fallback(match.group(4)) for match in UI_CALL.finditer(source)}


def blank_regex_literals(source: str) -> str:
    return REGEX_LITERAL.sub(lambda m: m.group(1) + "/" + " " * len(m.group(2)) + "/" + m.group(3), source)


def surface_sources() -> dict[str, str]:
    return {name: (JS_DIR / name).read_text(encoding="utf-8") for name in MODULES}


def skip_quoted(value: str, index: int) -> int:
    quote = value[index]
    index += 1
    while index < len(value):
        if value[index] == "\\":
            index += 2
        elif value[index] == quote:
            return index + 1
        else:
            index += 1
    return index


def comment_end(value: str, index: int) -> int | None:
    if value.startswith("//", index):
        end = value.find("\n", index + 2)
        return len(value) if end < 0 else end + 1
    if value.startswith("/*", index):
        end = value.find("*/", index + 2)
        return len(value) if end < 0 else end + 2
    return None


def scan_expression(value: str, index: int) -> tuple[int, list[str]]:
    depth = 1
    nested: list[str] = []
    while index < len(value) and depth:
        char = value[index]
        end = comment_end(value, index)
        if end is not None:
            index = end
            continue
        if char in "'\"":
            index = skip_quoted(value, index)
            continue
        elif char == "`":
            index, chunks = scan_template(value, index)
            nested.extend(chunks)
            continue
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        index += 1
    return index, nested


def scan_template(value: str, start: int) -> tuple[int, list[str]]:
    chunks: list[str] = []
    index = start + 1
    chunk_start = index
    while index < len(value):
        if value[index] == "\\":
            index += 2
            continue
        if value[index] == "`":
            chunks.append(value[chunk_start:index])
            return index + 1, chunks
        if value.startswith("${", index):
            chunks.append(value[chunk_start:index])
            index, nested = scan_expression(value, index + 2)
            chunks.extend(nested)
            chunk_start = index
            continue
        index += 1
    chunks.append(value[chunk_start:])
    return index, chunks


def template_literals(value: str) -> list[tuple[int, int, list[str]]]:
    found: list[tuple[int, int, list[str]]] = []
    index = 0
    while index < len(value):
        if value.startswith("//", index):
            end = value.find("\n", index + 2)
            index = len(value) if end < 0 else end + 1
        elif value.startswith("/*", index):
            end = value.find("*/", index + 2)
            index = len(value) if end < 0 else end + 2
        elif value[index] in "'\"":
            quote = value[index]
            index += 1
            while index < len(value):
                if value[index] == "\\":
                    index += 2
                elif value[index] == quote:
                    index += 1
                    break
                else:
                    index += 1
        elif value[index] == "`":
            end, chunks = scan_template(value, index)
            found.append((index, end, chunks))
            index = end
        else:
            index += 1
    return found


def test_every_ui_key_carries_its_modules_turkish() -> None:
    tr = catalog("tr")
    sources = surface_sources()
    calls = {key: value for source in sources.values() for key, value in ui_calls(source).items()}
    keys = {key for key in tr if key.startswith("ui.")}
    assert keys == set(calls)
    for key in keys:
        assert tr[key] == calls[key], key


def test_every_t_call_has_both_catalog_entries() -> None:
    tr, en = catalog("tr"), catalog("en")
    keys = {key for source in surface_sources().values() for _, key in UI_KEY.findall(source)}
    assert keys <= set(tr)
    assert keys <= set(en)


def test_placeholders_match_across_languages() -> None:
    tr, en = catalog("tr"), catalog("en")
    for key in (key for key in tr if key.startswith("ui.")):
        assert set(re.findall(r"\{(\w+)\}", tr[key])) == set(re.findall(r"\{(\w+)\}", en[key])), key


def test_new_surfaces_have_no_bare_turkish() -> None:
    categories = {
        "Bilgi ve İletişim Teknolojileri", "Enerji", "Ekonomi", "Güvenlik", "Mobilite", "Çevre", "İnsan", "Yönetişim", "Yaşam",
    }
    allowlist = categories | {"Türkçe"}
    for name, source in surface_sources().items():
        clean = blank_regex_literals(re.sub(r"/\*.*?\*/|^\s*//.*$", "", source, flags=re.S | re.M))
        fallback_spans = [match.span(4) for match in UI_CALL.finditer(clean)]
        literal_source = list(clean)
        for start_template, end_template, chunks in template_literals(clean):
            for chunk in chunks:
                assert not TURKISH_CHARS.search(chunk), (name, chunk)
            literal_source[start_template:end_template] = [" "] * (end_template - start_template)
        clean_literals = "".join(literal_source)
        literals = re.compile(r"'((?:\\.|[^'\\])*)'|\"((?:\\.|[^\"\\])*)\"", re.S)
        for match in literals.finditer(clean_literals):
            group = next(index for index, part in enumerate(match.groups(), start=1) if part is not None)
            value = match.group(group)
            start, end = match.span(group)
            if not TURKISH_CHARS.search(value) or value in allowlist:
                continue
            assert any(left <= start and end <= right for left, right in fallback_spans), (name, value)


def test_i18n_text_is_side_effect_free_and_holds_no_copy(tmp_path) -> None:
    helper = JS_DIR / "i18n_text.js"
    source = helper.read_text(encoding="utf-8")
    assert "innerHTML" not in source
    assert TURKISH_CHARS.search(source) is None
    assert re.search(r"(['\"])ar\1", source) is None
    module = node_json(
        tmp_path,
        {"i18n": "js/i18n_text.js"},
        "const tr = i18n.t('ui.x', 'Türkçe {n}', {n: 3});"
        "i18n.setCatalogs('en', {'ui.x':'English {n}'}, {});"
        "const en = i18n.t('ui.x', 'Türkçe {n}', {n: 3});"
        "const missing = i18n.t('ui.missing', 'Backup {n}', {n: 4});"
        "i18n.setCatalogs('ar', {'ui.x':'wrong'}, {});"
        "console.log(JSON.stringify([tr, en, missing, i18n.currentLang()]));",
    )
    assert module == ["Türkçe 3", "English 3", "Backup 4", "tr"]


def test_server_text_is_marked_turkish(tmp_path) -> None:
    account_url = json.dumps((JS_DIR / "account_view.js").as_uri())
    follow_url = json.dumps((JS_DIR / "follow.js").as_uri())
    data_url = json.dumps((JS_DIR / "open_data.js").as_uri())
    setup = (
        "globalThis.window = {location:{search:''},"
        "localStorage:{getItem(){return null},setItem(){},removeItem(){},key(){return null},get length(){return 0}}};"
    )
    body = "".join([
        setup,
        f"const account = await import({account_url});",
        f"const follow = await import({follow_url});",
        f"const data = await import({data_url});",
        "const consent = account.consentBlock({text:'Hukuki rıza metni.',version:'1'});",
        "const topic = follow.topicItem({kind:'line',value:'M2',label:'M2 hattı'},",
        "{active:['Kayıtlı aksaklık'],note:'Sunucu notu.'});",
        "const card = data.datasetCard({title:'Veri seti',url:'https://example.test',organization:'İBB',",
        "categories:['Mobilite'],summary:'Açıklama',formats:['CSV'],datastore:true,last_updated:null});",
        "console.log(JSON.stringify([consent,topic,card]));",
    ])
    values = node_json(tmp_path, {"i18n": "js/i18n_text.js"}, body)
    assert '<span lang="tr">Hukuki rıza metni.</span>' in values[0]
    assert '<b lang="tr">M2 hattı</b>' in values[1] and 'lang="tr">Kayıtlı aksaklık' in values[1]
    assert '<li class="od-card" lang="tr">' in values[2] and 'lang="tr">Açıklama' in values[2]


def test_english_surface_markup_uses_catalog_copy_and_keeps_turkish_data(tmp_path) -> None:
    catalog_setup = (
        f"i18n.setCatalogs('en', {json.dumps(catalog('en'), ensure_ascii=False)}, "
        f"{json.dumps(catalog('tr'), ensure_ascii=False)});"
    )
    imports = {
        "account": (JS_DIR / "account_view.js").as_uri(),
        "follow": (JS_DIR / "follow.js").as_uri(),
        "data": (JS_DIR / "open_data.js").as_uri(),
        "request": (JS_DIR / "request_status.js").as_uri(),
        "queue": (JS_DIR / "requests_console.js").as_uri(),
    }
    dynamic_imports = "".join(f"const {name} = await import({json.dumps(url)});" for name, url in imports.items())
    setup = (
        "globalThis.window = {location:{search:''},"
        "localStorage:{getItem(){return null},setItem(){},removeItem(){},key(){return null},get length(){return 0}}};"
    )
    body = "".join([
        setup, catalog_setup, dynamic_imports,
        "const band='Örnek hesap · gerçek İBB/İstanbulkart bağlantısı yok · entegrasyon İBB izni gerektirir';",
        "const accountCard = account.providerCard({key:'belbim',label:'İstanbulkart (örnek)',flow:'sms',band},'1234');",
        "const quota = account.quotaText({questions_left:14,questions_limit:20,model_open:true,has_account:false});",
        "const topic = follow.topicItem({kind:'line',value:'M2',label:'M2 hattı'},",
        "{active:['Kayıtlı aksaklık'],note:'Sunucu notu.'});",
        "const dataCard = data.datasetCard({title:'Veri seti',url:'https://example.test',organization:'İBB',",
        "categories:['Mobilite'],summary:'Açıklama',formats:['CSV'],datastore:true,last_updated:null});",
        "const operatorForm = request.formMarkup('', {});",
        "const queueDetail = queue.detailMarkup({code:'K7M2QX9P',category:'İstanbulkart',lang:'en',",
        "lang_source:'model algıladı',original:'Where is my card?',masked_count:0,masked_kinds:[],",
        "turkish:'Kartım nerede?',translation:{label:'Model çevirisi'},reply:null});",
        "console.log(JSON.stringify([accountCard,quota,topic,dataCard,operatorForm,queueDetail]));",
    ])
    values = node_json(tmp_path, {"i18n": "js/i18n_text.js"}, body)
    assert "Example account" in values[0] and "No SMS is sent" in values[0]
    assert 'lang="tr">İstanbulkart (örnek)' in values[0]
    assert values[1].startswith('Left today: 14 of 20 questions')
    assert 'Stop following' in values[2] and 'lang="tr">Kayıtlı aksaklık' in values[2]
    assert 'lang="tr">Açıklama' in values[3] and 'Data API available' in values[3]
    assert 'Send to an operator' in values[4] and 'Personal data is masked.' in values[4]
    assert 'Original (masked)' in values[5] and 'Preview translation' in values[5]
    assert 'lang="tr">Kartım nerede?' in values[5]


def test_no_arabic_anywhere_new() -> None:
    tr, en = catalog("tr"), catalog("en")
    new_keys = {key for key in tr if key.startswith("ui.") or key.startswith("dyn.handoff_")}
    new_keys |= {
        "page.nav_follow", "page.account_title", "page.account_note", "page.account_prompt", "page.follow_title",
        "page.follow_note", "page.follow_hint", "page.follow_empty", "page.open_data_title", "page.open_data_note",
        "page.open_data_label", "page.open_data_placeholder", "page.open_data_search", "page.open_data_categories",
    }
    assert new_keys <= set(en)
    assert all(not ARABIC_CHARS.search(tr[key]) and not ARABIC_CHARS.search(en[key]) for key in new_keys)
    assert not (I18N / "ar.json").exists()
    assert not re.search(r"(['\"])ar\1", (JS_DIR / "i18n_text.js").read_text(encoding="utf-8"))


def test_the_handoff_card_buttons_translate() -> None:
    tr, en = catalog("tr"), catalog("en")
    source = (JS_DIR / "handoff.js").read_text(encoding="utf-8")
    assert set(tr) & set(en) >= HANDOFF_KEYS
    for key in HANDOFF_KEYS:
        value = tr[key]
        assert value in source or value.replace("'", "\\'") in source, key
    assert en["dyn.handoff_call"] == "Call 153"
    for number in ("112", "153"):
        assert sum(tr[key].count(number) for key in HANDOFF_KEYS) == sum(en[key].count(number) for key in HANDOFF_KEYS)


def test_the_language_redraw_leaves_the_follow_and_quota_behaviour_alone() -> None:
    follow = (JS_DIR / "follow.js").read_text(encoding="utf-8")
    # chat.js sends {suggestion, host}; the box goes under the answer that offered it.
    assert "const { suggestion, host } = evt.detail || {};" in follow and "host.appendChild(suggestionBox(suggestion))" in follow
    mount = follow[follow.index("async function mountFollow()"):]
    order = [mount.index(step) for step in ("await moveDeviceFollows();", "await loadAccountFollows();", "await render(true);")]
    assert order == sorted(order)
    assert "document.visibilityState === 'visible'" in mount and "CHECK_MS" in mount
    strip = (JS_DIR / "quota_strip.js").read_text(encoding="utf-8")
    # "text · tier" with an account: the separator sits between the sentence and the tier label.
    assert strip.index("data-quota-text") < strip.index("data-quota-separator") < strip.index("data-quota-tier lang")
    console = (JS_DIR / "requests_console.js").read_text(encoding="utf-8")
    # Without ?lang=en the console asks for no catalogue.
    assert "get('lang') === 'en') await loadCatalogs('en');" in console
