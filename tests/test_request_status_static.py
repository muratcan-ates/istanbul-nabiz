"""Operatöre aktar + çeviri on the pages: the visitor's consent form and request card (js/request_status.js),
the operator's queue (js/requests_console.js), the handoff card's bridge, and where the pages load them."""

from __future__ import annotations

import json
import re

from test_static_a11y import STATIC, node_json

REQUEST_JS = STATIC / "js" / "request_status.js"
CONSOLE_JS = STATIC / "js" / "requests_console.js"
CSS = STATIC / "css" / "operator_requests.css"
CONSENT = "Sorunuz ve seçtiğiniz dil İBB operatörüne iletilecek. Kişisel veriler maskelenir."


def run(tmp_path, body: str, module: str = "js/request_status.js", name: str = "rs", lang: str = "tr"):
    """Import a module that reads ``window`` at load time, after stubbing it."""
    url = json.dumps((STATIC / module).as_uri())
    i18n_url = json.dumps((STATIC / "js" / "i18n_text.js").as_uri())
    tr = json.dumps(json.loads((STATIC / "i18n" / "tr.json").read_text(encoding="utf-8")), ensure_ascii=False)
    en = json.dumps(json.loads((STATIC / "i18n" / "en.json").read_text(encoding="utf-8")), ensure_ascii=False)
    stub = "globalThis.window = { location: { search: '', origin: 'http://localhost' } };\n"
    selected = en if lang == "en" else tr
    setup = f"i18n.setCatalogs({json.dumps(lang)}, {selected}, {tr});\n"
    prelude = f"{stub}const i18n = await import({i18n_url});\n" + setup
    prelude += f"const {name} = await import({url});\n"
    return node_json(tmp_path, {}, prelude + body)


def doc(lang: str = "tr") -> str:
    return f"({{documentElement: {{lang: '{lang}'}}}})"


WAITING = {
    "code": "K7M2QX9P", "status": "waiting", "question": "Kartım [TC KİMLİK] <b>kayıp</b>", "translation_note": None,
    "note": "Cevap geldiğinde bu kartta görünür.", "simulated": "Prototip: operatör rolü simüledir.", "reply": None,
}  # fmt: skip
ANSWERED = {
    **WAITING,
    "status": "answered",
    "reply": {
        "text": "Sie können sie aufladen.", "lang": "de", "text_tr": "Doldurabilirsiniz.", "translation": "model",
        "label": "Bu yanıt bir İBB çalışanı tarafından yazıldı ve otomatik çevrildi.", "answered_at": "2026-09-26T10:00:00+00:00",
    },
}  # fmt: skip


def test_the_consent_form_says_the_sentence_and_caps_the_text(tmp_path) -> None:
    html = run(tmp_path, f"console.log(JSON.stringify(rs.formMarkup('<i>soru</i>', {doc()})));")
    assert CONSENT in html
    assert 'type="checkbox" id="op-consent"' in html and 'maxlength="1000"' in html
    assert "&lt;i&gt;soru&lt;/i&gt;" in html and 'href="tel:112"' in html
    for value in ("auto", "tr", "en"):
        assert f'<option value="{value}">' in html
    english = run(tmp_path, f"console.log(JSON.stringify(rs.formMarkup('', {doc('en')})));", lang="en")
    assert "Personal data is masked." in english


def test_the_waiting_card_shows_the_code_and_the_answered_card_the_reply_with_its_turkish(tmp_path) -> None:
    values = run(
        tmp_path,
        f"console.log(JSON.stringify([rs.cardMarkup({json.dumps(WAITING)}, {doc()}),"
        f" rs.cardMarkup({json.dumps(ANSWERED)}, {doc()})]));",
    )
    waiting, answered = values
    assert "Operatöre iletildi · #K7M2QX9P · bekleniyor" in waiting
    assert "&lt;b&gt;kayıp&lt;/b&gt;" in waiting and 'href="tel:112"' in waiting and 'data-op="remove"' in waiting
    assert "İBB operatörü yanıtladı" in answered
    assert '<p lang="de">Sie können sie aufladen.</p>' in answered
    assert "<details><summary>Türkçesi</summary>" in answered and "Doldurabilirsiniz." in answered
    assert "otomatik çevrildi" in answered and "simüle" in answered


def test_a_turkish_reply_has_no_folded_turkish_copy(tmp_path) -> None:
    turkish = {**ANSWERED, "reply": {**ANSWERED["reply"], "lang": "tr", "text": "Doldurabilirsiniz.", "text_tr": None}}
    html = run(tmp_path, f"console.log(JSON.stringify(rs.cardMarkup({json.dumps(turkish)}, {doc()})));")
    assert "<details>" not in html


def test_stored_codes_drop_bad_old_and_extra_entries(tmp_path) -> None:
    now = 1_790_000_000_000
    day = 86_400_000
    items = [{"code": "K7M2QX9P", "at": now - 31 * day}, {"code": "bad", "at": now}, {"code": "AAAAAAA1", "at": now}]
    items += [{"code": f"ABCDEFG{d}", "at": now - d} for d in range(2, 10)] + [{"code": "ZZZZZZZZ", "at": now}]
    body = (
        f"const raw = {json.dumps(json.dumps({'version': 1, 'items': items}))};"
        f"console.log(JSON.stringify([rs.parseStored(raw, {now}).map((i) => i.code), rs.parseStored('{{', {now}),"
        f"rs.parseStored(JSON.stringify({{version: 2, items: []}}), {now}), rs.POLL_MS, rs.STORAGE_KEY]));"
    )
    kept, broken, version, poll, key = run(tmp_path, body)
    assert "K7M2QX9P" not in kept and "bad" not in kept and "AAAAAAA1" not in kept, "1 is not in the alphabet"
    assert len(kept) == 9 and kept[-1] == "ZZZZZZZZ"
    assert broken == [] and version == []
    assert poll == 20_000 and key == "nabiz.requests.v1"


def test_the_offer_follows_unanswered_cards_and_never_an_emergency(tmp_path) -> None:
    body = """
const shell = (classes, ruleId = '') => ({ classList: { contains: (c) => classes.includes(c) }, dataset: { ruleId } });
console.log(JSON.stringify([
  rs.wantsOffer(shell(['is-refused'])), rs.wantsOffer(shell([], 'guard_input')), rs.wantsOffer(shell([], 'guard_output')),
  rs.wantsOffer(shell([])), rs.wantsOffer(shell(['is-refused', 'is-emergency'])), rs.wantsOffer(null),
]));
"""
    assert run(tmp_path, body) == [True, True, True, False, False, False]


def test_the_operator_queue_needs_a_preview_before_send_and_shows_the_turkish(tmp_path) -> None:
    item = {
        "code": "K7M2QX9P", "status": "waiting", "created_at": "2026-09-26T10:00:00+00:00", "lang": "de",
        "lang_source": "model algıladı", "original": "Wo <script>", "masked_count": 1, "masked_kinds": ["TELEFON"],
        "turkish": "Nerede?", "translation": {"status": "model", "label": "Model çevirisi", "author": "model"},
        "category": "İstanbulkart", "guard": "injection", "reply": None,
    }  # fmt: skip
    answered = {**item, "status": "answered", "reply": {
        "text_tr": "Doldurun.", "text": "Aufladen.", "lang": "de", "translation": "edited",
        "answered_at": "2026-09-26T10:05:00+00:00",
        "ledger_entry_id": 7,
    }}  # fmt: skip
    body = f"console.log(JSON.stringify([rq.detailMarkup({json.dumps(item)}), rq.detailMarkup({json.dumps(answered)})]));"
    waiting, done = run(tmp_path, body, "js/requests_console.js", "rq")
    assert "&lt;script&gt;" in waiting and "Nerede?" in waiting and "Model çevirisi" in waiting
    assert 'data-op="preview"' in waiting and '<div id="op-preview" hidden>' in waiting
    assert waiting.index('data-op="preview"') < waiting.index('data-op="send"')
    assert "girdi korumasına" in waiting and "1 kişisel veri maskelendi" in waiting
    assert "operatör düzeltti" in done and "defter kaydı 7" in done and 'data-op="send"' not in done


def test_the_handoff_card_offers_the_operator_without_sending_anything(tmp_path) -> None:
    values = node_json(
        tmp_path,
        {"handoff": "js/handoff.js"},
        "console.log(JSON.stringify([handoff.cardMarkup('Konu', {tid: null}), handoff.operatorQuestion(["
        "{role: 'user', text: 'M2 gece çalışıyor mu?'}, {role: 'assistant'}, "
        "{role: 'user', text: 'insanla görüşmek istiyorum'}])]));",
    )
    card, question = values
    order = [card.index(s) for s in ('"call"', '"operator"', '"emergency"', '"close"')]
    assert order == sorted(order) and "Operatöre ilet" in card
    assert question == "M2 gece çalışıyor mu?"


def test_the_pages_load_the_modules_and_the_console_has_its_section() -> None:
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    assert index.index('src="/js/handoff.js"') < index.index('src="/js/request_status.js"')
    console = (STATIC / "console.html").read_text(encoding="utf-8")
    assert console.count('<section id="citizen-requests" aria-labelledby="citizen-requests-title">') == 1
    assert '<script type="module" src="/js/requests_console.js"></script>' in console
    assert '<link rel="modulepreload" href="/js/requests_console.js">' in console
    sw = (STATIC / "sw.js").read_text(encoding="utf-8")
    assert "'/js/request_status.js'" in sw and "'/css/operator_requests.css'" in sw


def test_modules_stay_small_use_tokens_and_keep_the_device_key_documented() -> None:
    for path in (REQUEST_JS, CONSOLE_JS):
        assert len(path.read_text(encoding="utf-8").splitlines()) <= 300, path.name
    css = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", css)
    assert "animation" not in css and "transition" not in css and "calc(var(--tap) * 1.25)" in css
    source = REQUEST_JS.read_text(encoding="utf-8")
    assert "localStorage" in source and "setInterval" in source and "EventSource" not in source and "WebSocket" not in source
    assert "nabiz.requests.v1" in (STATIC / "kvkk.html").read_text(encoding="utf-8")
    assert "handoff.js" not in CONSOLE_JS.read_text(encoding="utf-8")
