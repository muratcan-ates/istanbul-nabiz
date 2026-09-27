from __future__ import annotations

import ast
import json
import re

from test_i18n_surfaces import TURKISH_CHARS, UI_CALL, js_fallback, template_literals
from test_static_a11y import STATIC, node_json

from nabiz.console.poll import DISTRICTS

CATALOG = {
    "tr": {
        "ui.poll.already": "Bu cihazdan bu ankete zaten oy verildi.",
        "ui.poll.choose": "Bir seçenek işaretleyin.",
        "ui.poll.disclosure": (
            "Simüle operatörün anketi; resmî İBB anketi değildir. Cihaz başına bir oy; "
            "seçiminiz bu cihazla ilişkilendirilmeden sayılır. Bitiş: {date}."
        ),
        "ui.poll.dismiss": "Şimdi değil",
        "ui.poll.dismiss_district": "Bu ilçede değilim",
        "ui.poll.district": "Bu anket {district} için.",
        "ui.poll.example": "Örnek",
        "ui.poll.offline": "Sunucuya ulaşılamadı. Bağlantınızı kontrol edip tekrar deneyin.",
        "ui.poll.option": "Seçenek",
        "ui.poll.preview_note": "Önizleme; henüz yayımlanmadı.",
        "ui.poll.results": "Sonuçlar",
        "ui.poll.sending": "Gönderiliyor",
        "ui.poll.share": "Pay",
        "ui.poll.thanks": "Oyunuz alındı. Teşekkürler.",
        "ui.poll.title": "İstanbul'a Sor",
        "ui.poll.vote": "Oy ver",
        "ui.poll.votes": "Cevap",
        "ui.poll.wait_for_five": "5 cevaptan sonra",
        "ui.pollc.active_line": "Yayında · Kime: {target} · Bitiş: {date}",
        "ui.pollc.add_option": "Seçenek ekle",
        "ui.pollc.all": "Tüm vatandaşlar",
        "ui.pollc.cancel": "Vazgeç",
        "ui.pollc.choose_district": "İlçe seçin",
        "ui.pollc.close": "Anketi bitir",
        "ui.pollc.close_title": "Anketi bitir",
        "ui.pollc.closed": "Anket bitti; son sonuçlar deftere yazıldı.",
        "ui.pollc.closes_on": "Bitiş günü",
        "ui.pollc.closing": "Bitiriliyor",
        "ui.pollc.closed_operator": "Operatör kararıyla bitti.",
        "ui.pollc.closed_time": "Süre doldu.",
        "ui.pollc.confirm": "Soruyu ve seçenekleri okudum; kişisel veri yok.",
        "ui.pollc.confirm_required": "Önce onay kutusunu işaretleyin.",
        "ui.pollc.description": (
            "Vatandaşa tek soruluk kısa anket. Yayımlamadan önce onayınız gerekir; yayın ve bitiş karar defterine yazılır."
        ),
        "ui.pollc.district": "İlçe",
        "ui.pollc.draft_saved": "Önizleme hazır. Soru ve seçenekleri kontrol edin.",
        "ui.pollc.edit": "Taslağı düzenle",
        "ui.pollc.load_error": "Anket bilgisi alınamadı. Yeniden deneyin.",
        "ui.pollc.last_closed": "Son biten anket",
        "ui.pollc.new": "Yeni anket",
        "ui.pollc.option_number": "Seçenek {number}",
        "ui.pollc.options": "Seçenekler",
        "ui.pollc.preview": "Önizle",
        "ui.pollc.preview_heading": "Vatandaş böyle görecek",
        "ui.pollc.publish": "Yayımla",
        "ui.pollc.publish_text": (
            "Bu soru vatandaş sayfasında {date} saatine kadar görünecek. Yayın karar defterine adınızla yazılır."
        ),
        "ui.pollc.publish_title": "Anketi yayımla",
        "ui.pollc.published": "Yayımlandı: karar deftere yazıldı.",
        "ui.pollc.publishing": "Yayımlanıyor",
        "ui.pollc.question": "Soru",
        "ui.pollc.question_hint": "Kişi adı, telefon ya da adres yazmayın.",
        "ui.pollc.reason": "Gerekçe",
        "ui.pollc.reason_hint": "Deftere yazılır, vatandaşa gösterilmez. Kişi adı yazmayın.",
        "ui.pollc.reason_required": "Anketi bitirmek için gerekçe yazın.",
        "ui.pollc.remaining": "Kalan {count} karakter",
        "ui.pollc.remove_option": "Kaldır",
        "ui.pollc.results_disclaimer": "Bu sonuçlar temsili değildir; yalnız Nabız'da oy verenleri gösterir.",
        "ui.pollc.target": "Kime",
        "ui.pollc.target_district": "{district} ilçesi",
        "ui.pollc.title": "İstanbul'a Sor",
        "ui.pollc.total_line": "Toplam {count} cevap · son okuma {time}",
    },
    "en": {
        "ui.poll.already": "This device has already voted in this poll.",
        "ui.poll.choose": "Select an option.",
        "ui.poll.disclosure": (
            "A simulated operator's poll. This is not an official İBB poll. One vote per device; "
            "your choice is counted without being linked to this device. Closes: {date}."
        ),
        "ui.poll.dismiss": "Not now",
        "ui.poll.dismiss_district": "I am not in this district",
        "ui.poll.district": "This poll is for {district}.",
        "ui.poll.example": "Example",
        "ui.poll.offline": "We could not reach the server. Check your connection and try again.",
        "ui.poll.option": "Option",
        "ui.poll.preview_note": "Preview; not published yet.",
        "ui.poll.results": "Results",
        "ui.poll.sending": "Submitting",
        "ui.poll.share": "Share",
        "ui.poll.thanks": "Your vote was counted. Thank you.",
        "ui.poll.title": "Ask Istanbul",
        "ui.poll.vote": "Vote",
        "ui.poll.votes": "Votes",
        "ui.poll.wait_for_five": "After 5 votes",
        "ui.pollc.active_line": "Published · Audience: {target} · Closes: {date}",
        "ui.pollc.add_option": "Add an option",
        "ui.pollc.all": "All residents",
        "ui.pollc.cancel": "Cancel",
        "ui.pollc.choose_district": "Choose a district",
        "ui.pollc.close": "Close poll",
        "ui.pollc.close_title": "Close poll",
        "ui.pollc.closed": "Poll closed. Final results were recorded in the ledger.",
        "ui.pollc.closes_on": "Closing day",
        "ui.pollc.closing": "Closing",
        "ui.pollc.closed_operator": "Closed by an operator.",
        "ui.pollc.closed_time": "The poll period ended.",
        "ui.pollc.confirm": "I reviewed the question and options. There is no personal data.",
        "ui.pollc.confirm_required": "Check the confirmation box first.",
        "ui.pollc.description": (
            "A short, one-question poll for residents. Your approval is required before publication. "
            "Publication and closure are recorded in the decision ledger."
        ),
        "ui.pollc.district": "District",
        "ui.pollc.draft_saved": "Preview ready. Review the question and options.",
        "ui.pollc.edit": "Edit draft",
        "ui.pollc.load_error": "Poll details could not be loaded. Try again.",
        "ui.pollc.last_closed": "Last closed poll",
        "ui.pollc.new": "New poll",
        "ui.pollc.option_number": "Option {number}",
        "ui.pollc.options": "Options",
        "ui.pollc.preview": "Preview",
        "ui.pollc.preview_heading": "What residents will see",
        "ui.pollc.publish": "Publish",
        "ui.pollc.publish_text": (
            "This question will appear on the citizen page until {date}. "
            "Publication is recorded in the decision ledger under your name."
        ),
        "ui.pollc.publish_title": "Publish poll",
        "ui.pollc.published": "Published. The decision was recorded in the ledger.",
        "ui.pollc.publishing": "Publishing",
        "ui.pollc.question": "Question",
        "ui.pollc.question_hint": "Do not enter a person's name, phone number or address.",
        "ui.pollc.reason": "Reason",
        "ui.pollc.reason_hint": "This is recorded in the ledger and not shown to residents. Do not enter a person's name.",
        "ui.pollc.reason_required": "Enter a reason to close the poll.",
        "ui.pollc.remaining": "{count} characters remaining",
        "ui.pollc.remove_option": "Remove",
        "ui.pollc.results_disclaimer": "These results are not representative; they show only people who voted on Nabız.",
        "ui.pollc.target": "Audience",
        "ui.pollc.target_district": "{district} district",
        "ui.pollc.title": "Ask Istanbul",
        "ui.pollc.total_line": "{count} votes total · last read {time}",
    },
}

POLL_VIEW = STATIC / "js" / "poll_view.js"
POLL = STATIC / "js" / "poll.js"
POLL_CONSOLE = STATIC / "js" / "console_poll.js"
POLL_CSS = STATIC / "css" / "poll.css"
POLL_CONSOLE_CSS = STATIC / "css" / "console_poll.css"


def test_card_markup_is_safe_bilingual_and_has_no_primary_action(tmp_path) -> None:
    question = "Beşiktaş'ta ulaşım nasıl? <b>Bugün</b>"
    poll = {
        "id": "sample",
        "question": question,
        "options": [{"key": "o1", "label": "Daha iyi"}, {"key": "o2", "label": "Aynı"}],
        "target": {"kind": "district", "district": "Beşiktaş"},
        "closes_at": "2026-09-28T20:59:59+00:00",
    }
    encoded = json.dumps(poll, ensure_ascii=False)
    card, preview = node_json(
        tmp_path,
        {"view": "js/poll_view.js", "i18n": "js/i18n_text.js"},
        f"const poll={encoded};console.log(JSON.stringify([view.cardMarkup(poll),view.cardMarkup(poll,{{preview:true}})]));",
    )
    assert card.count('type="radio"') == 2 and '<legend lang="tr">' in card
    assert "btn-primary" not in card and "Örnek" in card and "resmî İBB anketi değildir" in card
    assert "Bu anket Beşiktaş için." in card and "Bu ilçede değilim" in card
    assert "&lt;b&gt;Bugün&lt;/b&gt;" in card and "Beşiktaş'ta ulaşım nasıl? <b>" not in card
    assert "inert" in preview and 'id="istanbula-sor-preview"' in preview and "poll-title-preview" in preview
    assert "Önizleme; henüz yayımlanmadı." in preview
    english = node_json(
        tmp_path,
        {"view": "js/poll_view.js", "i18n": "js/i18n_text.js"},
        f"i18n.setCatalogs('en',{json.dumps(CATALOG['en'], ensure_ascii=False)},{json.dumps(CATALOG['tr'], ensure_ascii=False)});"
        f"console.log(JSON.stringify(view.cardMarkup({encoded})));",
    )
    assert "Ask Istanbul" in english and "Vote" in english and "I am not in this district" in english
    assert "not an official İBB poll" in english and '<legend lang="tr">' in english


def test_results_hide_shares_before_five_and_localize_percent_position(tmp_path) -> None:
    options = [{"key": "o1", "label": "Sabah"}, {"key": "o2", "label": "Akşam"}]
    values = node_json(
        tmp_path,
        {"view": "js/poll_view.js", "i18n": "js/i18n_text.js"},
        "const small=view.resultsMarkup({total:4,rows:[{key:'o1',label:'Sabah',count:3,percent:null},"
        "{key:'o2',label:'Akşam',count:1,percent:null}]});"
        "i18n.setCatalogs('en',{},{});const big=view.resultsMarkup({total:7,rows:[{key:'o1',label:'Sabah',count:3,percent:42},"
        "{key:'o2',label:'Akşam',count:4,percent:58}]});"
        "console.log(JSON.stringify([small,big,view.percentText(42,'tr'),view.percentText(42,'en')]));",
    )
    small, big, tr_percent, en_percent = values
    assert "5 cevaptan sonra" in small and "poll-bar" not in small
    assert "42%" in big and "58%" in big and "poll-bar" in big
    assert tr_percent == "%42" and en_percent == "42%"
    assert len(options) == 2


def test_missing_citizen_anchor_does_not_leave_dom_or_make_a_request(tmp_path) -> None:
    url = json.dumps(POLL.as_uri())
    body = (
        "let calls=0;globalThis.fetch=()=>{calls+=1;return Promise.resolve({ok:true,json:async()=>({poll:null})});};"
        "globalThis.window={location:{search:''},addEventListener(){},removeEventListener(){}};"
        "globalThis.document={querySelector(){return null;}};"
        f"const poll=await import({url});const result=await poll.mountPoll(document);console.log(JSON.stringify([result,calls]));"
    )
    assert node_json(tmp_path, {}, body) == [None, 0]


def test_catalogues_cover_every_key_and_match_fallbacks() -> None:
    sources = {path.name: path.read_text(encoding="utf-8") for path in (POLL_VIEW, POLL, POLL_CONSOLE)}
    calls = {match.group(2): js_fallback(match.group(4)) for source in sources.values() for match in UI_CALL.finditer(source)}
    assert set(calls) == set(CATALOG["tr"]) == set(CATALOG["en"])
    for key, fallback in calls.items():
        assert CATALOG["tr"][key] == fallback, key
        assert set(re.findall(r"\{(\w+)\}", CATALOG["tr"][key])) == set(re.findall(r"\{(\w+)\}", CATALOG["en"][key])), key
    for lang in ("tr", "en"):  # P00 G2: the keys moved into the page catalogues, unchanged
        surface = json.loads((STATIC / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
        assert all(surface[k] == v for k, v in CATALOG[lang].items())
    all_copy = "\n".join([*CATALOG["tr"].values(), *CATALOG["en"].values()])
    assert "\u2013" not in all_copy and "\u2014" not in all_copy
    assert "ETA" not in all_copy and "canlı" not in all_copy and "İBB onaylı" not in all_copy
    assert re.search(r"[\u0600-\u06ff]", all_copy) is None
    for name, source in sources.items():
        clean = re.sub(r"/\*.*?\*/|^\s*//.*$", "", source, flags=re.S | re.M)
        fallback_spans = [match.span(4) for match in UI_CALL.finditer(clean)]
        literal_source = list(clean)
        for start, end, chunks in template_literals(clean):
            assert all(not TURKISH_CHARS.search(chunk) for chunk in chunks), name
            literal_source[start:end] = [" "] * (end - start)
        for match in re.finditer(r"'((?:\\.|[^'\\])*)'|\"((?:\\.|[^\"\\])*)\"", "".join(literal_source), re.S):
            value = next(item for item in match.groups() if item is not None)
            if TURKISH_CHARS.search(value):
                start, end = match.span(1 if match.group(1) is not None else 2)
                assert any(left <= start and end <= right for left, right in fallback_spans), (name, value)


def test_anchors_timing_styles_districts_and_cache_scope() -> None:
    assert "#city-cards" in POLL.read_text(encoding="utf-8") and "#asistan" in POLL.read_text(encoding="utf-8")
    assert "setInterval" not in POLL.read_text(encoding="utf-8")
    assert "#citizen-requests" in POLL_CONSOLE.read_text(encoding="utf-8") and "#day" in POLL_CONSOLE.read_text(encoding="utf-8")
    assert "['#polls-mount', 'afterend'], ['#citizen-requests'" in POLL_CONSOLE.read_text(encoding="utf-8")  # P00 G2 mount first
    assert "POLL_MS = 20_000" in POLL_CONSOLE.read_text(encoding="utf-8")
    for stylesheet in (POLL_CSS, POLL_CONSOLE_CSS):
        source = re.sub(r"/\*.*?\*/", "", stylesheet.read_text(encoding="utf-8"), flags=re.S)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", source), stylesheet.name
        assert "infinite" not in source
    citizen_css = POLL_CSS.read_text(encoding="utf-8")
    assert "@media (prefers-reduced-motion: no-preference)" in citizen_css
    assert "animation:" in citizen_css and "transition:" not in citizen_css
    assert "animation:" not in POLL_CONSOLE_CSS.read_text(encoding="utf-8")
    handoff = (STATIC / "js" / "handoff.js").read_text(encoding="utf-8")
    values = re.search(r"const ILCELER = Object\.freeze\(\[(.*?)\]\);", handoff, re.S)
    assert values
    assert ast.literal_eval("[" + values.group(1) + "]") == list(DISTRICTS)
    assert "console_poll" not in (STATIC / "sw.js").read_text(encoding="utf-8")


def test_only_confirmation_dialogs_contain_a_primary_action() -> None:
    source = POLL_CONSOLE.read_text(encoding="utf-8")
    assert source.count("btn-primary") == 2
    assert source.count("<dialog") == 2
    for match in re.finditer("btn-primary", source):
        opening = source.rfind("<dialog", 0, match.start())
        closing = source.rfind("</dialog>", 0, match.start())
        assert opening > closing


def test_self_review_preserves_modal_context_focus_and_result_disclosure() -> None:
    citizen = POLL.read_text(encoding="utf-8")
    console = POLL_CONSOLE.read_text(encoding="utf-8")
    exact_disclosure = "Bu sonuçlar temsili değildir; yalnız Nabız'da oy verenleri gösterir."
    fallbacks = {match.group(2): js_fallback(match.group(4)) for match in UI_CALL.finditer(console)}
    assert fallbacks["ui.pollc.results_disclaimer"] == exact_disclosure and "resultsMarkup(active.results)" in console
    assert "anchor.position === 'afterend' ? anchor.element.nextElementSibling : anchor.element" in citizen
    render = console[
        console.index("function render(data, force = false)") : console.index("async function refresh(force = false)")
    ]
    assert "if (section.querySelector('dialog[open]')) return;" in render
    assert render.index("if (section.querySelector('dialog[open]')) return;") < render.index("lastSnapshot = snapshot;")


def test_last_closed_poll_has_a_collapsed_results_section() -> None:
    console = POLL_CONSOLE.read_text(encoding="utf-8")
    assert 'class="poll-last-closed"' in console and "resultsMarkup(poll.results)" in console
    assert "ui.pollc.closed_time" in console and "ui.pollc.closed_operator" in console


def test_keyboard_motion_theme_and_small_screen_contracts() -> None:
    citizen = POLL.read_text(encoding="utf-8")
    console = POLL_CONSOLE.read_text(encoding="utf-8")
    citizen_css = POLL_CSS.read_text(encoding="utf-8")
    console_css = POLL_CONSOLE_CSS.read_text(encoding="utf-8")
    assert '<fieldset><legend lang="tr">' in (STATIC / "js" / "poll_view.js").read_text(encoding="utf-8")
    assert 'type="submit" class="btn" data-poll-vote' in (STATIC / "js" / "poll_view.js").read_text(encoding="utf-8")
    assert "showModal()" in console and 'data-op="cancel-dialog"' in console
    assert "dialogTrigger?.focus()" in console and "if (!check.checked)" in console
    assert "{ confirm: true, digest: current.draft.digest }" in console
    assert "@media (prefers-reduced-motion: no-preference)" in citizen_css
    assert ':root:not([data-motion="reduce"]):not([data-simple="on"])' in citizen_css
    assert "@media (max-width: 24rem)" in console_css and "grid-template-columns: minmax(0, 1fr) auto" in console_css
    assert "inline-size: calc(100vw - 1rem)" in console_css
    assert ":focus-visible" in citizen_css and ":focus-visible" in console_css
    tokens = (STATIC / "css" / "tokens.css").read_text(encoding="utf-8")
    assert "@media (prefers-color-scheme: dark)" in tokens
    assert "nabiz:emergency" in citizen and "onLang" in citizen and "visibilitychange" in citizen
