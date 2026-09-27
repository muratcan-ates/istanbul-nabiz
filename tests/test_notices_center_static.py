"""The self-mounting Updates module stays quiet without its anchor and keeps text safe."""

from __future__ import annotations

import json
import re

from test_i18n_surfaces import TURKISH_CHARS, UI_CALL, template_literals, ui_calls
from test_static_a11y import STATIC, node_json

JS = STATIC / "js" / "notices_center.js"
CSS = STATIC / "css" / "notices_center.css"
CATALOG = {
    "tr": {
        "ui.notices.title": "Güncellemeler",
        "ui.notices.note": "takip ettiğiniz konular ve bu cihazdaki kodlar; yalnız kayıtlı veri",
        "ui.notices.empty": "Henüz güncelleme yok; bir konuyu takip ettiğinizde ya da bildirim gönderdiğinizde burada görünür.",
        "ui.notices.count": "{count} yeni",
        "ui.notices.new": "Yeni",
        "ui.notices.example": "Örnek",
        "ui.notices.example_note": "Örnek: operatör rolü simüledir.",
        "ui.notices.severity_critical": "Kritik",
        "ui.notices.read_all": "Tümünü okundu say",
        "ui.notices.calendar": "Takvime ekle",
        "ui.notices.calendar_hint": (
            "Takvim dosyası kişisel veri içermeyen bir hatırlatıcıdır; "
            "aksaklığın ne zaman biteceğini söylemez."
        ),
        "ui.notices.calendar_done": "Takvim dosyası indirildi.",
        "ui.notices.calendar_loading": "Takvim dosyası hazırlanıyor.",
        "ui.notices.calendar_failed": "Takvim dosyası hazırlanamadı: {message}",
        "ui.notices.loading": "Güncellemeler alınıyor.",
        "ui.notices.failed": "Güncellemeler şu an alınamadı: {message}",
        "ui.notices.retry": "Yeniden dene",
        "ui.notices.unavailable": "Kontrol edilemedi:",
        "ui.notices.more": "Daha eski {count} güncelleme",
        "ui.notices.announce": "Güncellemelerde {count} yeni kayıt var.",
        "ui.notices.kind_notice": "duyuru",
        "ui.notices.kind_fault": "arıza kaydı",
        "ui.notices.kind_measured": "ölçülen düzensizlik",
        "ui.notices.kind_page": "yeni kaynak",
        "ui.notices.kind_request": "Operatör talebiniz",
        "ui.notices.kind_report": "Asansör bildiriminiz",
        "ui.notices.request_waiting": "Yanıt bekleniyor; yanıt, talebi gönderdiğiniz cihazdaki kartta görünür.",
        "ui.notices.request_answered": "Yanıtlandı; yanıtı sohbetteki talep kartında okuyabilirsiniz.",
        "ui.notices.date_source": "İBB kaydı · {when}",
        "ui.notices.date_read": "Nabız okuması · {when}",
        "ui.notices.date_measured": "ölçüldü · {when}",
        "ui.notices.date_page": "kaynak tarihi · {when}",
        "ui.notices.date_sent": "gönderildi · {when}",
        "ui.notices.date_answered": "yanıtlandı · {when}",
        "ui.notices.date_device": "bu cihazdan gönderildi · {when}",
        "ui.notices.date_none": "tarih yok",
    },
    "en": {
        "ui.notices.title": "Updates",
        "ui.notices.note": "topics you follow and codes on this device; recorded data only",
        "ui.notices.empty": "No updates yet; they appear here when you follow a topic or send a report.",
        "ui.notices.count": "{count} new",
        "ui.notices.new": "New",
        "ui.notices.example": "Example",
        "ui.notices.example_note": "Example: the operator role is simulated.",
        "ui.notices.severity_critical": "Critical",
        "ui.notices.read_all": "Mark all as read",
        "ui.notices.calendar": "Add to calendar",
        "ui.notices.calendar_hint": (
            "The calendar file is a reminder with no personal data; "
            "it does not say when a disruption ends."
        ),
        "ui.notices.calendar_done": "Calendar file downloaded.",
        "ui.notices.calendar_loading": "Preparing the calendar file.",
        "ui.notices.calendar_failed": "The calendar file could not be made: {message}",
        "ui.notices.loading": "Getting updates.",
        "ui.notices.failed": "Updates could not be read right now: {message}",
        "ui.notices.retry": "Try again",
        "ui.notices.unavailable": "Could not check:",
        "ui.notices.more": "{count} older updates",
        "ui.notices.announce": "There are {count} new items in Updates.",
        "ui.notices.kind_notice": "notice",
        "ui.notices.kind_fault": "fault record",
        "ui.notices.kind_measured": "measured irregularity",
        "ui.notices.kind_page": "new source",
        "ui.notices.kind_request": "Your operator request",
        "ui.notices.kind_report": "Your lift report",
        "ui.notices.request_waiting": "Waiting for a reply; it appears on the card on the device you sent it from.",
        "ui.notices.request_answered": "Answered; you can read the reply on the request card in the conversation.",
        "ui.notices.date_source": "İBB record · {when}",
        "ui.notices.date_read": "Read by Nabız · {when}",
        "ui.notices.date_measured": "measured · {when}",
        "ui.notices.date_page": "source date · {when}",
        "ui.notices.date_sent": "sent · {when}",
        "ui.notices.date_answered": "answered · {when}",
        "ui.notices.date_device": "sent from this device · {when}",
        "ui.notices.date_none": "no date",
    },
}


def run(tmp_path, body: str, lang: str = "tr"):
    url = json.dumps(JS.as_uri())
    i18n_url = json.dumps((STATIC / "js" / "i18n_text.js").as_uri())
    selected = json.dumps(CATALOG[lang], ensure_ascii=False)
    tr = json.dumps(CATALOG["tr"], ensure_ascii=False)
    setup = "globalThis.window = {location:{search:'',origin:'http://localhost'}};"
    setup += "globalThis.localStorage = {getItem(){return null},setItem(){}};let fetches=0;"
    setup += f"const i18n = await import({i18n_url});i18n.setCatalogs({json.dumps(lang)},{selected},{tr});"
    setup += f"const nc = await import({url});"
    return node_json(tmp_path, {}, setup + body)


def test_catalog_keys_match_fallbacks_and_share_placeholders() -> None:
    source = JS.read_text(encoding="utf-8")
    assert ui_calls(source) == CATALOG["tr"]
    for key in CATALOG["tr"]:
        assert set(re.findall(r"\{(\w+)\}", CATALOG["tr"][key])) == set(re.findall(r"\{(\w+)\}", CATALOG["en"][key]))


def test_visible_turkish_is_only_in_translation_fallbacks() -> None:
    source = re.sub(r"/\*.*?\*/|^\s*//.*$", "", JS.read_text(encoding="utf-8"), flags=re.S | re.M)
    spans = [match.span(4) for match in UI_CALL.finditer(source)]
    literal_source = list(source)
    for start, end, chunks in template_literals(source):
        for chunk in chunks:
            assert not TURKISH_CHARS.search(chunk)
        literal_source[start:end] = [" "] * (end - start)
    for match in re.finditer(r"'((?:\\.|[^'\\])*)'|\"((?:\\.|[^\"\\])*)\"", "".join(literal_source), re.S):
        value = next(part for part in match.groups() if part is not None)
        if TURKISH_CHARS.search(value):
            assert any(start - 1 <= match.start(0) and match.end(0) <= end + 1 for start, end in spans), value
    assert "—" not in source and "–" not in source and "canlı" not in source


def test_seen_storage_unread_markup_and_calendar_copy_are_bounded(tmp_path) -> None:
    body = r"""
const now=2000000000000, day=86400000;
const old=nc.parseSeen(JSON.stringify({version:1,items:{'n_0000000000000001':now-31*day}}),now);
const bad=nc.parseSeen('{',now), wrong=nc.parseSeen(JSON.stringify({version:2,items:{}}),now);
const ids=Array.from({length:205},(_,i)=>'n_'+String(i).padStart(16,'0'));
const saved=nc.rememberSeen({version:1,items:{}},ids,now);
const item={id:'n_abcdef0123456789',source:'report',ref_index:0,kind:'report',label:'<b>Station</b>',
 text_tr:'Örnek cümle',text_en:'Example sentence',status:'waiting',severity:'critical',recorded_at:null,
 date_kind:null,calendar:null,simulated:true};
const fresh=nc.itemMarkup(item,{unread:true,deviceAt:now});
const read=nc.itemMarkup(item,{unread:false,deviceAt:now});
const topic={...item,source:'topic',kind:'notice',calendar:'reminder',simulated:false};
const english=nc.itemMarkup(topic,{unread:true});
console.log(JSON.stringify({old,bad,wrong,saved,unread:nc.unreadIds([item],old),fresh,read,english,keys:nc.STORAGE_KEYS,device:nc.dateLine(item,now)}));
"""
    old, bad, wrong, saved, unread, fresh, read, english, keys, device = run(tmp_path, body, lang="en").values()
    assert old == bad == wrong == {"version": 1, "items": {}}
    assert len(saved["items"]) == 200 and len(unread) == 1
    assert "&lt;b&gt;Station&lt;/b&gt;" in fresh and "Example" in fresh and "New" in fresh
    assert "data-nc=\"calendar\"" not in fresh and "New" not in read
    assert '<p class="nc-text" lang="en">Example sentence</p>' in english
    assert "Add to calendar" in english and "lang=\"tr\"" in fresh
    assert keys == {"follows": "nabiz.follows.v1", "requests": "nabiz.requests.v1", "reports": "nabiz.report-codes.v1"}
    assert device.startswith("sent from this device · ")


def test_mount_without_anchor_does_not_insert_or_fetch(tmp_path) -> None:
    result = run(
        tmp_path,
        "const doc={querySelector(){return null}};const mounted=nc.mountNotices(doc,{getItem(){return null}});"
        "console.log(JSON.stringify([mounted,fetches]));",
    )
    assert result == [None, 0]


def test_styles_and_script_follow_the_notice_constraints() -> None:
    source = JS.read_text(encoding="utf-8")
    styles = CSS.read_text(encoding="utf-8")
    for forbidden in ("Notification", "PushManager", "showNotification", "requestPermission", "setInterval", "btn-primary"):
        assert forbidden not in source
    for forbidden in ("transition", "animation", "infinite", "--bad", "--danger"):
        assert forbidden not in styles
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(", styles)
    assert "overflow-wrap: anywhere" in styles and "forced-colors: active" in styles
    assert ".nc-item.is-unread" in styles and "border-inline-start: 3px solid var(--nd-accent)" in styles
    assert "—" not in source + styles and "–" not in source + styles


def test_the_page_catalogues_carry_the_notices_keys_unchanged() -> None:
    """P00 G4: the ui.notices.* keys moved into the page catalogues, unchanged, in both languages."""
    for lang in ("tr", "en"):
        surface = json.loads((STATIC / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
        assert all(surface[k] == v for k, v in CATALOG[lang].items())
