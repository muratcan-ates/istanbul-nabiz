from __future__ import annotations

import json
import re
import shutil
import subprocess
from urllib.parse import urlsplit

import pytest
from conftest import REPO_ROOT
from test_static_a11y import STATIC, node_json

from ibb_mcp.knowledge.guardrails import host_allowed

CATALOG = {
    "tr": {
        "ui.outage.again": "Hâlâ gelmedi, yeniden bildir",
        "ui.outage.announced_by_user": "Siz eklediniz: {time}",
        "ui.outage.announced_label": "Siz eklediniz: bitiş saati",
        "ui.outage.announced_summary": "Duyurulan bitiş saati",
        "ui.outage.area_heading": "Bölgeler",
        "ui.outage.area_summary": "{files} dosya · {reports} teyit · son {time}",
        "ui.outage.call_112": "112’yi arayın",
        "ui.outage.call_153": "153’ü arayın",
        "ui.outage.cancel": "Vazgeç",
        "ui.outage.choose_district": "İlçe seçin",
        "ui.outage.choose_district_error": "İlçeyi seçin.",
        "ui.outage.close_emergency": "Kartı kapat",
        "ui.outage.code_forgotten": "Talep kartı bu cihazdan kaldırıldı.",
        "ui.outage.confirm_title": "Suyum hâlâ gelmedi",
        "ui.outage.consent": (
            "Mahallemi, ilçemi ve isteğe bağlı notumu Nabız operatörüne (prototip, simüle) göndermeyi "
            "kabul ediyorum. İSKİ’ye iletilmez; 7 gün sonra silinir."
        ),
        "ui.outage.consent_error": "Göndermek için onay kutusunu işaretleyin.",
        "ui.outage.console_counts": "{waiting} bekliyor · {seen} görüldü",
        "ui.outage.console_error": "Teyit kuyruğu açılamadı. Bölüm görünürken yeniden deneyin.",
        "ui.outage.console_disclaimer": (
            "Vatandaşın “suyum hâlâ gelmedi” teyitleri. İSKİ’ye iletilmez; resmî kesinti bilgisi "
            "değildir. Kişisel veriler maskelenir; 7 gün sonra silinir."
        ),
        "ui.outage.console_title": "Hane kesinti teyitleri",
        "ui.outage.delete_home": "Evimi cihazdan sil",
        "ui.outage.delete_home_note": "Bu cihazdaki ev ve talep kodları silinir. Sunucudaki teyitler 7 gün saklanır.",
        "ui.outage.delete_home_summary": "Evimi cihazdan sil",
        "ui.outage.district_label": "İlçe",
        "ui.outage.edit_home": "Evimi değiştir",
        "ui.outage.edit_home_title": "Evimi değiştir",
        "ui.outage.emergency_note": "Bu acil bir durum olabilir. Operatör kuyruğunda beklemeyin.",
        "ui.outage.emergency_title": "Acil yardım",
        "ui.outage.expired": "Talebin saklama süresi doldu.",
        "ui.outage.forget_code": "Talebi cihazdan unut",
        "ui.outage.gas_187": "İGDAŞ 187 Doğal Gaz Acil Hattı",
        "ui.outage.gas_emergency_prefix": "Gaz kokusu alıyorsanız bu acildir:",
        "ui.outage.gas_no_source": "Doğal gaz kesintisi için Nabız’da kaynak yok.",
        "ui.outage.gas_recorded": "kayıtlı · {date} · ibb.istanbul",
        "ui.outage.gas_source": "İBB Faaliyet Raporu 2025",
        "ui.outage.gas_title": "Doğal gaz",
        "ui.outage.history_count": "Bu mahallede {count} kesinti kaydı.",
        "ui.outage.history_dataset": "2023-2024 veri seti",
        "ui.outage.history_source": "Kaynak: İBB Açık Veri, İSKİ",
        "ui.outage.history_title": "Geçmiş (kayıtlı, 2023-2024)",
        "ui.outage.home_deleted_note": "Evim ve talep kodlarım bu cihazdan silindi. Sunucudaki teyitler 7 gün saklanır.",
        "ui.outage.home_form_title": "Evimi kaydet",
        "ui.outage.home_label": "Kaydedilen ev",
        "ui.outage.home_saved": "Eviniz bu cihaza kaydedildi.",
        "ui.outage.how_summary": "Bu nasıl çalışır?",
        "ui.outage.how_text": (
            "Ev seçiminiz yalnız bu cihazda kalır. İsteğe bağlı teyit, açık rızanızdan sonra Nabız’ın "
            "simüle operatör kuyruğuna gider ve 7 gün sonra silinir."
        ),
        "ui.outage.list_unavailable": (
            "Planlı kesinti listesi henüz bağlı değil. İSKİ’nin Arıza Kesinti sayfasında mahalle/ilçe "
            "filtresiyle sorgulayabilirsiniz."
        ),
        "ui.outage.info_error": "Kesinti bilgisi açılamadı. Yeniden deneyin.",
        "ui.outage.loading": "Kesinti bilgisi yükleniyor.",
        "ui.outage.loading_report": "Talep yükleniyor.",
        "ui.outage.local_only": "Yalnız bu cihazda saklanır. Kaydetmek sunucuya istek göndermez.",
        "ui.outage.mock_not_sent": "Örnek: sunucu bağlı değil, teyit gönderilmedi.",
        "ui.outage.neighbourhood_error": "Yalnız mahalle adını yazın.",
        "ui.outage.neighbourhood_hint": "Yalnız mahalle adı; sokak ve kapı numarası yazmayın.",
        "ui.outage.neighbourhood_label": "Mahalle",
        "ui.outage.no_areas": "Bölge teyidi yok.",
        "ui.outage.no_reports": "Teyit dosyası yok.",
        "ui.outage.not_iski": "Resmî kesinti bilgisinden ayrıdır; İSKİ’ye iletilmez.",
        "ui.outage.not_official": "Resmî İBB hizmeti değildir.",
        "ui.outage.note_hint": "Sokak, kapı numarası, ad veya telefon yazmayın.",
        "ui.outage.note_label": "İsteğe bağlı not",
        "ui.outage.note_summary": "Not",
        "ui.outage.official_title": "İSKİ’nin resmî bilgisi",
        "ui.outage.open_confirm": "Suyum hâlâ gelmedi",
        "ui.outage.open_iski": "İSKİ Arıza Kesinti sayfasını aç",
        "ui.outage.open_quote_source": "Alıntının kaynağını aç",
        "ui.outage.or": "ve",
        "ui.outage.own_title": "Sizin bildiriminiz",
        "ui.outage.own_note": (
            "Duyurulan süre geçti ama suyunuz hâlâ gelmediyse bildirin. Bu bildirim İSKİ’ye gitmez; Nabız "
            "operatörüne (prototip, simüle) düşer. Acil durumda 112."
        ),
        "ui.outage.queue_heading": "Dosyalar",
        "ui.outage.quote_185": "Alo 185",
        "ui.outage.quote_page": "İSKİ sayfası",
        "ui.outage.quote_pressure": "İSKİ notu",
        "ui.outage.recorded_source": "kayıtlı · {date} · iski.istanbul",
        "ui.outage.report_count": "{count} teyit",
        "ui.outage.report_saved": "Teyidiniz kaydedildi.",
        "ui.outage.reported_by_user": "Siz bildirdiniz · {time}",
        "ui.outage.retry": "Yeniden dene",
        "ui.outage.save_home": "Evimi kaydet",
        "ui.outage.seen": "Gördüm",
        "ui.outage.seen_error": "Görüldü bilgisi kaydedilemedi. Yeniden deneyin.",
        "ui.outage.send": "Teyidi gönder",
        "ui.outage.send_error": "Teyit gönderilemedi. Yeniden deneyin.",
        "ui.outage.send_notice": "İlçe, mahalle ve isteğe bağlı not Nabız operatörüne gider; İSKİ’ye iletilmez.",
        "ui.outage.simulated": "Örnek: bu teyit İSKİ’ye iletilmez.",
        "ui.outage.status_seen": "Operatör gördü (prototip)",
        "ui.outage.status_waiting": "bekliyor",
        "ui.outage.storage_error": "Kaydedilemedi: tarayıcı depolamaya izin vermiyor.",
        "ui.outage.subtitle": "Yalnız bu cihazda; resmî bilgi İSKİ’den",
        "ui.outage.title": "Evimin suyu ve gazı",
        "ui.outage.unknown_time": "saat yok",
    },
    "en": {
        "ui.outage.again": "Still no water? Report again",
        "ui.outage.announced_by_user": "You added: {time}",
        "ui.outage.announced_label": "You added the announced end time",
        "ui.outage.announced_summary": "Announced end time",
        "ui.outage.area_heading": "Areas",
        "ui.outage.area_summary": "{files} files · {reports} confirmations · last {time}",
        "ui.outage.call_112": "Call 112",
        "ui.outage.call_153": "Call 153",
        "ui.outage.cancel": "Cancel",
        "ui.outage.choose_district": "Choose a district",
        "ui.outage.choose_district_error": "Choose a district.",
        "ui.outage.close_emergency": "Close this card",
        "ui.outage.code_forgotten": "The request card was removed from this device.",
        "ui.outage.confirm_title": "My water still has not returned",
        "ui.outage.consent": (
            "I agree to send my district, neighbourhood, and optional note to the Nabız operator "
            "(prototype, simulated). It is not sent to İSKİ and is deleted after 7 days."
        ),
        "ui.outage.consent_error": "Select the consent box to send.",
        "ui.outage.console_counts": "{waiting} waiting · {seen} seen",
        "ui.outage.console_error": "The confirmation queue could not be opened. Retry when this section is visible.",
        "ui.outage.console_disclaimer": (
            "Residents’ “my water still has not returned” confirmations. They are not sent to İSKİ and "
            "are not official outage information. Personal data is masked; records are deleted after 7 "
            "days."
        ),
        "ui.outage.console_title": "Household outage confirmations",
        "ui.outage.delete_home": "Delete my home from this device",
        "ui.outage.delete_home_note": (
            "The home and request codes on this device will be deleted. Server confirmations remain for 7 days."
        ),
        "ui.outage.delete_home_summary": "Delete my home from this device",
        "ui.outage.district_label": "District",
        "ui.outage.edit_home": "Change my home",
        "ui.outage.edit_home_title": "Change my home",
        "ui.outage.emergency_note": "This may be an emergency. Do not wait in the operator queue.",
        "ui.outage.emergency_title": "Emergency help",
        "ui.outage.expired": "The request retention period has ended.",
        "ui.outage.forget_code": "Forget this request on this device",
        "ui.outage.gas_187": "İGDAŞ 187 Natural Gas Emergency Line",
        "ui.outage.gas_emergency_prefix": "If you smell gas, treat it as an emergency:",
        "ui.outage.gas_no_source": "Nabız has no source for natural gas outages.",
        "ui.outage.gas_recorded": "recorded · {date} · ibb.istanbul",
        "ui.outage.gas_source": "İBB Activity Report 2025",
        "ui.outage.gas_title": "Natural gas",
        "ui.outage.history_count": "{count} outage records for this neighbourhood.",
        "ui.outage.history_dataset": "2023-2024 dataset",
        "ui.outage.history_source": "Source: İBB Open Data, İSKİ",
        "ui.outage.history_title": "History (recorded, 2023-2024)",
        "ui.outage.home_deleted_note": (
            "The home and request codes were removed from this device. Server confirmations remain for 7 days."
        ),
        "ui.outage.home_form_title": "Save my home",
        "ui.outage.home_label": "Saved home",
        "ui.outage.home_saved": "Your home was saved on this device.",
        "ui.outage.how_summary": "How does this work?",
        "ui.outage.how_text": (
            "Your home selection stays on this device. After your explicit consent, an optional "
            "confirmation goes to Nabız’s simulated operator queue and is deleted after 7 days."
        ),
        "ui.outage.list_unavailable": (
            "The planned outage list is not connected yet. Check the district and neighbourhood filters on İSKİ’s outage page."
        ),
        "ui.outage.info_error": "Outage information could not be opened. Retry.",
        "ui.outage.loading": "Loading outage information.",
        "ui.outage.loading_report": "Loading request.",
        "ui.outage.local_only": "Saved on this device only. Saving does not contact the server.",
        "ui.outage.mock_not_sent": "Example: server is not connected; confirmation was not sent.",
        "ui.outage.neighbourhood_error": "Enter only the neighbourhood name.",
        "ui.outage.neighbourhood_hint": "Enter only the neighbourhood name; do not enter a street or door number.",
        "ui.outage.neighbourhood_label": "Neighbourhood",
        "ui.outage.no_areas": "No area confirmations.",
        "ui.outage.no_reports": "No confirmation files.",
        "ui.outage.not_iski": "Separate from official outage information; not sent to İSKİ.",
        "ui.outage.not_official": "This is not an official İBB service.",
        "ui.outage.note_hint": "Do not enter a street, door number, name, or phone number.",
        "ui.outage.note_label": "Optional note",
        "ui.outage.note_summary": "Note",
        "ui.outage.official_title": "Official information from İSKİ",
        "ui.outage.open_confirm": "My water still has not returned",
        "ui.outage.open_iski": "Open İSKİ’s outage page",
        "ui.outage.open_quote_source": "Open the quote source",
        "ui.outage.or": "and",
        "ui.outage.own_title": "Your confirmation",
        "ui.outage.own_note": (
            "If the announced time has passed and your water has not returned, you can report it. This "
            "confirmation goes to Nabız’s simulated operator, not to İSKİ. Call 112 in an emergency."
        ),
        "ui.outage.queue_heading": "Files",
        "ui.outage.quote_185": "Alo 185",
        "ui.outage.quote_page": "İSKİ page",
        "ui.outage.quote_pressure": "İSKİ note",
        "ui.outage.recorded_source": "recorded · {date} · iski.istanbul",
        "ui.outage.report_count": "{count} confirmations",
        "ui.outage.report_saved": "Your confirmation was saved.",
        "ui.outage.reported_by_user": "You reported this · {time}",
        "ui.outage.retry": "Retry",
        "ui.outage.save_home": "Save my home",
        "ui.outage.seen": "Seen",
        "ui.outage.seen_error": "The seen status could not be saved. Retry.",
        "ui.outage.send": "Send confirmation",
        "ui.outage.send_error": "The confirmation could not be sent. Retry.",
        "ui.outage.send_notice": "Your district, neighbourhood, and optional note go to the Nabız operator, not to İSKİ.",
        "ui.outage.simulated": "Example: this confirmation is not sent to İSKİ.",
        "ui.outage.status_seen": "Operator saw it (prototype)",
        "ui.outage.status_waiting": "waiting",
        "ui.outage.storage_error": "Could not save: browser storage is unavailable.",
        "ui.outage.subtitle": "On this device only; official information from İSKİ",
        "ui.outage.title": "My water and gas",
        "ui.outage.unknown_time": "time unavailable",
    },
}


def test_catalog_matches_module_fallbacks_and_languages() -> None:
    modules = [STATIC / "js" / name for name in ("outage_watch.js", "console_outage_watch.js")]
    pattern = re.compile(r"t\(\s*(['\"])(ui\.outage\.[^'\"]+)\1\s*,\s*(['\"])((?:\\.|[^\\])*?)\3", re.S)
    calls = {}
    for path in modules:
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            calls[match.group(2)] = match.group(4).replace("\\'", "'").replace('\\"', '"')
    assert set(CATALOG["tr"]) == set(CATALOG["en"]) == set(calls)
    assert calls == CATALOG["tr"]
    assert all(
        set(re.findall(r"\{(\w+)\}", CATALOG["tr"][key])) == set(re.findall(r"\{(\w+)\}", CATALOG["en"][key])) for key in calls
    )


def test_sources_quotes_and_urls_are_pinned_and_allowlisted() -> None:
    data = json.loads((REPO_ROOT / "data/reference/outage_watch/outage_sources.json").read_text(encoding="utf-8"))
    source_by_id = {item["id"]: item for item in data["sources"]}
    for source in data["sources"]:
        url = source["url"]
        host = urlsplit(url).hostname or ""
        assert url.startswith("https://") and host_allowed(host)
        assert "igdas" not in host.lower()
        assert "iski.istanbul/web/tr-TR" not in url
    evidence = data["evidence"]
    for quote in data["official"]["quotes"]:
        source = source_by_id[quote["source_id"]]
        assert quote["source_id"] in evidence and quote["text"] in evidence[quote["source_id"]]["text"]
        assert source["url"].startswith("https://")
    for line in data["gas"]["lines"]:
        source = source_by_id[line["source_id"]]
        assert source["url"] and host_allowed(urlsplit(source["url"]).hostname or "")
        for evidence_id in line.get("quote_ids", []):
            assert evidence[evidence_id]["text"]
    assert "187 Doğal Gaz Acil Hattı" in evidence["gas_187_title"]["text"]
    assert data["iski_capture"]["list_status"] == "veri_alinamadi_js"
    history = data["history"]
    assert history["source_records"] == 6410 and len(history["areas"]) == 873
    serialized_history = json.dumps(history, ensure_ascii=False)
    assert "CALISMA YERİ" not in serialized_history and "GÖNÜLLÜ CAD" not in serialized_history


def test_static_modules_and_css_keep_the_feature_fences(tmp_path) -> None:
    citizen = (STATIC / "js/outage_watch.js").read_text(encoding="utf-8")
    console = (STATIC / "js/console_outage_watch.js").read_text(encoding="utf-8")
    citizen_css = (STATIC / "css/outage_watch.css").read_text(encoding="utf-8")
    console_css = (STATIC / "css/console_outage_watch.css").read_text(encoding="utf-8")
    assert "nabiz.outage.v1" in citizen
    assert set(re.findall(r"['\"](nabiz\.[^'\"]+)['\"]", citizen)) == {"nabiz.outage.v1"}
    assert all(path in citizen for path in ("/api/outage-watch/info", "/api/outage-watch/reports/"))
    assert all(path in console for path in ("/api/console/outage-watch", "/seen"))
    for source in (citizen, console):
        assert "setInterval" not in source
        assert not re.search(r"addEventListener\(\s*['\"]scroll", source, re.I)
        assert not re.search(r"MutationObserver\s*\([^)]*document\.body", source, re.S)
        assert "canlı" not in source.casefold() and "—" not in source and "–" not in source
    visible_copy = "\n".join(value for language in CATALOG.values() for value in language.values())
    visible_copy += "\n" + json.dumps(
        json.loads((REPO_ROOT / "data/reference/outage_watch/outage_sources.json").read_text(encoding="utf-8")),
        ensure_ascii=False,
    )
    assert "canlı" not in visible_copy.casefold() and "—" not in visible_copy and "–" not in visible_copy
    assert "--bad" in citizen_css and citizen_css.count("var(--bad)") == 2
    assert ".is-emergency" in citizen_css
    for css in (citizen_css, console_css):
        assert "infinite" not in css and "transition:" not in css and "animation:" not in css
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(", css)
    untouched_paths = (
        REPO_ROOT / "src/nabiz/console/static/index.html",
        REPO_ROOT / "src/nabiz/console/static/sw.js",
    )
    for path in untouched_paths:
        assert "outage_watch" not in path.read_text(encoding="utf-8")
    # P00 G5 wired the back end and the console panel; the citizen page and its cache wait for D2.
    app_source = (REPO_ROOT / "src/nabiz/console/app.py").read_text(encoding="utf-8")
    assert "from nabiz.console.outage_watch_api import outage_routes" in app_source
    console_html = (REPO_ROOT / "src/nabiz/console/static/console.html").read_text(encoding="utf-8")
    assert '<script type="module" src="/js/console_outage_watch.js"></script>' in console_html
    assert 'id="outage-watch-mount"' in console_html
    assert len(citizen.splitlines()) <= 350
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    for path in (STATIC / "js/outage_watch.js", STATIC / "js/console_outage_watch.js"):
        checked = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=30)
        assert checked.returncode == 0, checked.stderr
    boot = tmp_path / "window_boot.mjs"
    boot.write_text("globalThis.window={location:{search:''},addEventListener(){},removeEventListener(){}};\n", encoding="utf-8")
    values = node_json(
        tmp_path,
        {"boot": str(boot), "outage": "js/outage_watch.js"},
        "const storage={value:null,getItem(){return this.value},setItem(key,value){this.key=key;this.value=value;}};\n"
        "const home={district:'Kadıköy',neighbourhood:'Caferağa',saved_at:'today'};\n"
        "const saved=outage.writeStore({home,reports:[{code:'K7M2QX9P',created_at:'today'}]},storage);\n"
        "const read=outage.readStore(storage);\n"
        "const info={official:{},history:{areas:[{district:'Kadikoy',neighbourhood:'CAFERAĞA',count:28}]}};\n"
        "const boxes=outage.boxesFor(info,read);\n"
        "const primaries=[\n"
        "outage.primaryFor({home:null,homeFormOpen:true}),\n"
        "outage.primaryFor({home}),\n"
        "outage.primaryFor({home,formOpen:true}),\n"
        "outage.primaryFor({home,error:true}),\n"
        "outage.primaryFor({home,hasReports:true})\n"
        "];\n"
        "console.log(JSON.stringify({saved,key:storage.key,read,boxes,primaries}));",
    )
    assert values["saved"] is True and values["key"] == "nabiz.outage.v1"
    assert values["boxes"]["history"]["count"] == 28
    assert values["primaries"] == ["save_home", "confirm", "send", "retry", None]
