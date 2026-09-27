"""Static, bilingual, and small-DOM checks for the fare surface."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from conftest import REPO_ROOT
from test_i18n_surfaces import TURKISH_CHARS, UI_CALL, js_fallback, template_literals

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
JS = STATIC / "js" / "fare.js"
CSS = STATIC / "css" / "fare.css"
FARES = REPO_ROOT / "data" / "reference" / "tarife" / "fares.json"
I18N = STATIC / "i18n"

CATALOG = {
    "tr": {
        "ui.fare.no_date": "sayfada tarih yok",
        "ui.fare.unknown": "bilinmiyor",
        "ui.fare.metro_transfer_rule_missing": "Metroya aktarmada ücretin nasıl hesaplandığı Nabız'ın kaynaklarında yok.",
        "ui.fare.bus_tariff_unavailable": "İETT tarifesi alınamadı: sayfa ücreti tarayıcıda yüklüyor (kontrol: {date}).",
        "ui.fare.marmaray_source_missing": "Marmaray ücreti için Nabız'ın kaynağı yok.",
        "ui.fare.eticket_scope_metro_only": (
            "Elektronik bilet sayfası yalnız Metro İstanbul'undur; "
            "bu araçta geçerliliği kaynakta yok."
        ),
        "ui.fare.subscription_scope_unknown": "Mavi kartın bu araçta geçerliliği Nabız'ın kaynaklarında yok.",
        "ui.fare.passes_missing": "Kaynakta bu tarife için geçiş sayısı yazmıyor; geçiş başı pay hesaplanamadı.",
        "ui.fare.unknown_mode": "Bu araç için Nabız'ın kaynağı yok.",
        "ui.fare.mode_metro": "Metro İstanbul raylı hat",
        "ui.fare.mode_ferry": "Vapur (Şehir Hatları)",
        "ui.fare.mode_bus": "Otobüs",
        "ui.fare.mode_metrobus": "Metrobüs",
        "ui.fare.mode_marmaray": "Marmaray",
        "ui.fare.mode_other": "Diğer",
        "ui.fare.tariff_full": "Tam",
        "ui.fare.tariff_student": "Öğrenci",
        "ui.fare.tariff_student30": "30 yaşından gün almış öğrenci",
        "ui.fare.tariff_other": "Başka bir kart",
        "ui.fare.other_mode_note": "Başka bir kart: sosyal, indirimli, 65 yaş ve üstü, engelli",
        "ui.fare.saved_date": "kaydedildi: {date}",
        "ui.fare.note_night": "Gece tarifesindeki iki kat hesaba katılmadı.",
        "ui.fare.note_distance": "Mesafe bazlı hatlarda iade farkı hesaba katılmadı.",
        "ui.fare.note_validity": "Mavi kartın geçerlilik süresi kaynakta yok.",
        "ui.fare.note_boarding": "Her biniş bir geçiş sayıldı; aktarmanın geçiş sayılıp sayılmadığı kaynakta yok.",
        "ui.fare.note_parking": "Park et devam et ücreti için Nabız'ın kaynağı yok.",
        "ui.fare.note_senior": "65 yaş ve üstü için tarife kaynağı yok.",
        "ui.fare.notes_title": "Hesaba katılmayanlar",
        "ui.fare.quote_summary": "Kaynaktaki metin",
        "ui.fare.source_open": "Resmî kaynağı aç (yeni sekme)",
        "ui.fare.extra_passes": "{count} kullanılmayan geçiş",
        "ui.fare.supporting_quote": "Geçerlilik bilgisi",
        "ui.fare.option_eticket": "Elektronik bilet",
        "ui.fare.option_subscription": "Mavi kart",
        "ui.fare.option_single": "İstanbulkart ile tek tek biniş",
        "ui.fare.known_part": "Haftalık bilinen kısım: {amount}",
        "ui.fare.unknown_count": "{count} bacağın ücreti bilinmiyor",
        "ui.fare.weekly": "Haftalık: {amount}",
        "ui.fare.sample": "Örnek hesaplama; güncel tarife için resmî kaynağa bakın.",
        "ui.fare.lowest": "Bu desende bilinen bedeli en düşük",
        "ui.fare.weeks_covered": "Kaynakta belirtilen geçiş sayısı bu desende {weeks} hafta sürer.",
        "ui.fare.other_title": "Tarife satırları",
        "ui.fare.other_card_note": "Kartınıza hangisinin uygulandığını Nabız bilmez; İstanbulkart'a ya da 153'e sorun.",
        "ui.fare.istanbulkart_link": "İstanbulkart resmî sayfası",
        "ui.fare.comparison_missing": "Bazı bedeller bilinmediği için karşılaştırma sıralaması yapılmadı.",
        "ui.fare.error_days": "Haftada 1 ile 7 gün arasında seçim yapın.",
        "ui.fare.error_tariff": "Bir tarife türü seçin.",
        "ui.fare.error_route": "Vapur hattını seçin.",
        "ui.fare.error_legs": "Bir ile dört bacak arasında seçim yapın.",
        "ui.fare.days_label": "Haftada kaç gün?",
        "ui.fare.days_word": "gün",
        "ui.fare.round_trip": "Gidiş ve dönüş",
        "ui.fare.tariff_legend": "Kartınızda uygulanan tarife türü",
        "ui.fare.legs_legend": "Bir yöndeki yolculuğun bacakları",
        "ui.fare.add_leg": "Bacak ekle",
        "ui.fare.within_window": "Aktarmalar 120 dakika içinde",
        "ui.fare.personalized": "Adıma kayıtlı (kişiselleştirilmiş) İstanbulkart kullanıyorum",
        "ui.fare.calculate": "Hesapla",
        "ui.fare.remove_leg": "Kaldır",
        "ui.fare.mode_label": "Bacak türü",
        "ui.fare.route_label": "Vapur hattı",
        "ui.fare.route_pick": "Hat seçin",
        "ui.fare.title": "Haftalık ulaşım maliyetim",
        "ui.fare.notice": (
            "Ücretler resmî sayfalardan kaydedildi; hesap bir tahmindir, resmî ücret değildir. "
            "Hangi tarifenin kartınıza uygulandığını İstanbulkart belirler."
        ),
        "ui.fare.disclaimer": "Resmî İBB hizmeti değildir.",
        "ui.fare.open_to_load": "Kataloğu görmek için bölümü açın.",
        "ui.fare.consent": "Bu deseni yalnız bu cihazda sakla",
        "ui.fare.save": "Sakla",
        "ui.fare.clear": "Bu cihazdaki desenimi sil",
        "ui.fare.consent_required": "Saklamak için önce bu cihazda saklama kutusunu işaretleyin.",
        "ui.fare.save_invalid": "Deseni gözden geçirin.",
        "ui.fare.saved": "Desen bu cihazda saklandı.",
        "ui.fare.storage_unavailable": "Bu tarayıcıda saklama kapalı; desen sayfa yenilenince silinir.",
        "ui.fare.clear_confirm": "Deseni sil",
        "ui.fare.clear_confirm_status": "Silmek için aynı düğmeye bir kez daha basın.",
        "ui.fare.deleted": "Bu cihazdaki desen silindi.",
        "ui.fare.mock": "Örnek veri kipinde ücret hesabı kapalı.",
        "ui.fare.estimating": "Hesaplanıyor.",
        "ui.fare.calculated": "Hesaplandı.",
        "ui.fare.estimate_failed": "Hesaplama yapılamadı. Kurumun resmî sayfasına ya da 153’e bakın.",
        "ui.fare.loading": "Tarife kaynakları yükleniyor.",
        "ui.fare.route_missing": "Saklı desendeki vapur hattı katalogda yok; bu bacak Diğer olarak gösteriliyor.",
        "ui.fare.ready": "Deseni girip Hesapla düğmesine basın.",
        "ui.fare.catalog_failed": "Tarife kataloğu alınamadı.",
    },
    "en": {
        "ui.fare.no_date": "no date on the page",
        "ui.fare.unknown": "unknown",
        "ui.fare.metro_transfer_rule_missing": "Nabiz's sources do not state how a transfer to metro is charged.",
        "ui.fare.bus_tariff_unavailable": (
            "The IETT fare was not captured: the page loads fares in the browser "
            "(checked: {date})."
        ),
        "ui.fare.marmaray_source_missing": "Nabiz has no source for the Marmaray fare.",
        "ui.fare.eticket_scope_metro_only": (
            "The electronic ticket page is for Metro Istanbul only; "
            "its use on this vehicle is not stated in the source."
        ),
        "ui.fare.subscription_scope_unknown": "Nabiz's sources do not state whether the Mavi Kart applies to this vehicle.",
        "ui.fare.passes_missing": (
            "The source does not list the pass count for this tariff, "
            "so a per-trip share could not be calculated."
        ),
        "ui.fare.unknown_mode": "Nabiz has no source for this vehicle.",
        "ui.fare.mode_metro": "Metro Istanbul rail line",
        "ui.fare.mode_ferry": "Ferry (Sehir Hatlari)",
        "ui.fare.mode_bus": "Bus",
        "ui.fare.mode_metrobus": "Metrobus",
        "ui.fare.mode_marmaray": "Marmaray",
        "ui.fare.mode_other": "Other",
        "ui.fare.tariff_full": "Full fare",
        "ui.fare.tariff_student": "Student",
        "ui.fare.tariff_student30": "Student aged 30 or older",
        "ui.fare.tariff_other": "Another card",
        "ui.fare.other_mode_note": "Another card: social, discounted, age 65 and over, disability",
        "ui.fare.saved_date": "saved: {date}",
        "ui.fare.note_night": "The double night fare was not included.",
        "ui.fare.note_distance": "Refund differences on distance-based lines were not included.",
        "ui.fare.note_validity": "The Mavi Kart validity period is not stated in the source.",
        "ui.fare.note_boarding": (
            "Each boarding was counted as one pass; the source does not say "
            "whether a transfer counts as a pass."
        ),
        "ui.fare.note_parking": "Nabiz has no source for a Park and Ride fee.",
        "ui.fare.note_senior": "No fare source is available for people aged 65 and over.",
        "ui.fare.notes_title": "Not included in the estimate",
        "ui.fare.quote_summary": "Source text",
        "ui.fare.source_open": "Open official source (opens in a new tab)",
        "ui.fare.extra_passes": "{count} unused passes",
        "ui.fare.supporting_quote": "Validity information",
        "ui.fare.option_eticket": "Electronic ticket",
        "ui.fare.option_subscription": "Mavi Kart subscription",
        "ui.fare.option_single": "Pay per ride with Istanbulkart",
        "ui.fare.known_part": "Known weekly part: {amount}",
        "ui.fare.unknown_count": "Fare unknown for {count} legs",
        "ui.fare.weekly": "Weekly: {amount}",
        "ui.fare.sample": "Sample calculation; check the official source for the current fare.",
        "ui.fare.lowest": "Lowest known cost for this pattern",
        "ui.fare.weeks_covered": "This pattern would use the listed pass count over {weeks} weeks.",
        "ui.fare.other_title": "Tariff rows",
        "ui.fare.other_card_note": "Nabiz does not know which tariff applies to your card; ask Istanbulkart or call 153.",
        "ui.fare.istanbulkart_link": "Official Istanbulkart page",
        "ui.fare.comparison_missing": "Some fares are unknown, so the options were not ranked.",
        "ui.fare.error_days": "Choose between 1 and 7 days per week.",
        "ui.fare.error_tariff": "Choose a tariff type.",
        "ui.fare.error_route": "Choose a ferry line.",
        "ui.fare.error_legs": "Choose between one and four legs.",
        "ui.fare.days_label": "Days per week",
        "ui.fare.days_word": "days",
        "ui.fare.round_trip": "Outbound and return",
        "ui.fare.tariff_legend": "Tariff type applied to your card",
        "ui.fare.legs_legend": "Legs for one direction",
        "ui.fare.add_leg": "Add a leg",
        "ui.fare.within_window": "Transfers are within 120 minutes",
        "ui.fare.personalized": "I use a personalized Istanbulkart registered to me",
        "ui.fare.calculate": "Calculate",
        "ui.fare.remove_leg": "Remove",
        "ui.fare.mode_label": "Leg type",
        "ui.fare.route_label": "Ferry line",
        "ui.fare.route_pick": "Choose a line",
        "ui.fare.title": "Weekly travel cost",
        "ui.fare.notice": (
            "Fees were captured from official pages; this is an estimate, not an official fare. "
            "Istanbulkart determines which tariff applies to your card."
        ),
        "ui.fare.disclaimer": "Not an official İBB service.",
        "ui.fare.open_to_load": "Open this section to load the catalogue.",
        "ui.fare.consent": "Save this pattern on this device only",
        "ui.fare.save": "Save",
        "ui.fare.clear": "Delete this device's saved pattern",
        "ui.fare.consent_required": "Check the on-device storage box before saving.",
        "ui.fare.save_invalid": "Review the pattern.",
        "ui.fare.saved": "The pattern was saved on this device.",
        "ui.fare.storage_unavailable": (
            "Storage is unavailable in this browser; the pattern will be cleared "
            "when the page reloads."
        ),
        "ui.fare.clear_confirm": "Delete the pattern",
        "ui.fare.clear_confirm_status": "Press the same button once more to delete it.",
        "ui.fare.deleted": "The pattern on this device was deleted.",
        "ui.fare.mock": "Fare calculation is disabled in example data mode.",
        "ui.fare.estimating": "Calculating.",
        "ui.fare.calculated": "Calculated.",
        "ui.fare.estimate_failed": "The estimate could not be calculated. Check the official page or call 153.",
        "ui.fare.loading": "Loading tariff sources.",
        "ui.fare.route_missing": "A saved ferry line is not in the catalogue; this leg is shown as Other.",
        "ui.fare.ready": "Enter your pattern and press Calculate.",
        "ui.fare.catalog_failed": "The fare catalogue could not be loaded.",
    },
}


def _fallbacks(source: str) -> dict[str, str]:
    return {match.group(2): js_fallback(match.group(4)) for match in UI_CALL.finditer(source)}


def test_fare_catalogs_match_module_fallbacks_and_have_equal_placeholders() -> None:
    source = JS.read_text(encoding="utf-8")
    fallbacks = _fallbacks(source)
    assert set(fallbacks) == set(CATALOG["tr"]) == set(CATALOG["en"])
    assert CATALOG["tr"] == fallbacks
    for key, turkish in CATALOG["tr"].items():
        assert set(re.findall(r"\{(\w+)\}", turkish)) == set(re.findall(r"\{(\w+)\}", CATALOG["en"][key]))
    for language in ("tr", "en"):
        page_catalog = json.loads((I18N / f"{language}.json").read_text(encoding="utf-8"))
        assert all(page_catalog[k] == v for k, v in CATALOG[language].items())  # P00 G3: moved into the page catalogues


def test_new_module_has_no_bare_turkish_or_untranslated_surface_copy() -> None:
    source = re.sub(r"/\*.*?\*/|^\s*//.*$", "", JS.read_text(encoding="utf-8"), flags=re.S | re.M)
    fallback_spans = [match.span(4) for match in UI_CALL.finditer(source)]
    chars = list(source)
    for start, end, chunks in template_literals(source):
        for chunk in chunks:
            assert not TURKISH_CHARS.search(chunk), chunk
        chars[start:end] = [" "] * (end - start)
    clean = "".join(chars)
    quoted = re.compile(r"'((?:\\.|[^'\\])*)'|\"((?:\\.|[^\"\\])*)\"", re.S)
    for match in quoted.finditer(clean):
        value = next(part for part in match.groups() if part is not None)
        start, end = match.span(1 if match.group(1) is not None else 2)
        if TURKISH_CHARS.search(value):
            assert any(left <= start and end <= right for left, right in fallback_spans), value


def test_static_contracts_hold_for_network_privacy_motion_and_layout() -> None:
    js = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    catalog = FARES.read_text(encoding="utf-8")
    assert re.findall(r"\b(?:get|post)\('(/api/fare/[^']+)'", js) == [
        "/api/fare/estimate", "/api/fare/estimate", "/api/fare/catalog",
    ]
    assert "post('/api/fare/estimate', pattern)" in js
    assert "const displayLabel = labelFromReason ? modeLabel(line.mode)" in js
    assert "sourceRow(source, sourceDateValue" in js
    assert re.findall(r"localStorage\.(?:getItem|setItem|removeItem)\(([^,)]+)", js) == [
        "STORAGE_KEY", "STORAGE_KEY", "STORAGE_KEY",
    ]
    assert "const STORAGE_KEY = 'nabiz.fare.v1'" in js
    for forbidden in ("setInterval", "scroll", "MutationObserver", "aria-live", "localStorage.setItem('fare"):
        assert forbidden not in js
    assert js.count('role="status"') == 1
    assert "autocomplete=\"off\" novalidate" in js
    assert "#tarife-sonuc" in js and "aria-describedby" in js
    assert '<section class="fare-panel" aria-labelledby="tarife-title">' in js
    assert "transition:" not in css
    assert re.search(r"@media\s*\(prefers-reduced-motion:\s*no-preference\)[\s\S]*?animation:\s*fare-enter", css)
    assert "infinite" not in css
    assert "@media (max-width: 480px)" in css and "grid-template-columns: minmax(0, 1fr)" in css
    assert "--tap" in css and "var(--nd-accent)" in css and "var(--surface" in css
    assert "@media (forced-colors: active)" in css
    colour = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(")
    assert not colour.search(css)
    for text in (js, css, catalog):
        assert "\u2014" not in text and "\u2013" not in text
        assert "canlı" not in text.casefold()
    banned = ("hakkınız var", "yararlanırsınız", "ücretsiz binersiniz", "size en uygun")
    for phrase in banned:
        assert phrase not in js.casefold()
    assert "fare.js" not in (STATIC / "index.html").read_text(encoding="utf-8")
    assert "fare.js" not in (STATIC / "sw.js").read_text(encoding="utf-8")
    symbols = set(re.findall(r'<symbol id="i-([\w-]+)"', (STATIC / "icons.svg").read_text(encoding="utf-8")))
    assert set(re.findall(r"icon\('([\w-]+)'", js)) <= symbols


def test_fare_module_passes_node_syntax_check() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    result = subprocess.run([node, "--check", str(JS)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


def test_pure_helpers_and_mount_are_safe_in_a_minimal_dom() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    source_url = json.dumps(JS.as_uri())
    i18n_url = json.dumps((STATIC / "js" / "i18n_text.js").as_uri())
    payload = json.dumps(CATALOG, ensure_ascii=False)
    script = f"""
globalThis.document = undefined;
const stored = new Map();
globalThis.window = {{location:{{search:''}}, addEventListener(){{}}, removeEventListener(){{}},
  localStorage:{{getItem:(key)=>stored.get(key)||null,setItem:(key,value)=>stored.set(key,value),removeItem:(key)=>stored.delete(key)}}}};
const fare = await import({source_url});
const i18n = await import({i18n_url});
const pattern = {{days_per_week:5,round_trip:true,tariff:'tam',legs:[{{mode:'metro'}}],within_window:false,personalized:false}};
const noConsent = fare.writePattern(pattern,false);
const emptyAfterNoConsent = stored.size;
const saved = fare.writePattern(pattern,true);
const readBack = fare.readPattern();
const bad = {{...pattern, extra:'do not retain'}};
const injected = fare.writePattern(bad,true);
const badRoute = {{...pattern,legs:[{{mode:'ferry',route:''}}]}};
const invalidRoute = fare.writePattern(badRoute,true);
i18n.setCatalogs('en',{payload}.en,{payload}.tr);
const enReason = fare.reasonText('bus_tariff_unavailable',{{date:'27.09.2026'}});
const enMoney = fare.formatKurus(4620,'en');
i18n.setCatalogs('tr',{payload}.tr,{payload}.tr);
const trReason = fare.reasonText('passes_missing');
const noHost = {{head:{{appendChild(){{throw Error('unexpected style')}}}},
  getElementById(){{return null}},querySelector(){{return null}}}};
fare.mountFare(noHost);
const node = () => ({{id:'',className:'',dataset:{{}},children:[],setAttribute(){{}},addEventListener(){{}},
  appendChild(child){{this.children.push(child)}},querySelector(){{return node()}},querySelectorAll(){{return []}},focus(){{}}}});
const host = node(), head = node();
const doc = {{head,createElement:()=>node(),querySelector:()=>null,
  getElementById(id){{
    if(id==='city-tools') return host;
    if(id==='tarife') return host.children.find((item)=>item.id==='tarife')||null;
    return null;
  }} }};
fare.mountFare(doc);fare.mountFare(doc);
console.log(JSON.stringify({{noConsent,emptyAfterNoConsent,saved,readBack,injected,invalidRoute,enReason,enMoney,trReason,
  mounted:host.children.length,styles:head.children.length,section:host.children[0].id}}));
"""
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    values = json.loads(result.stdout)
    assert values["noConsent"] is False and values["emptyAfterNoConsent"] == 0
    assert values["saved"] is True and values["readBack"]["tariff"] == "tam"
    assert values["injected"] is False and values["invalidRoute"] is False
    assert "The IETT fare was not captured" in values["enReason"]
    assert "46.20" in values["enMoney"]
    assert "geçiş sayısı yazmıyor" in values["trReason"]
    assert (values["mounted"], values["styles"], values["section"]) == (1, 1, "tarife")


def test_every_fare_card_carries_the_sample_calculation_label() -> None:
    """Owner decision (27 Sep): each fare card says it is a sample, next to its official source and date."""
    source = JS.read_text(encoding="utf-8")
    option = source[source.index("function optionMarkup"):source.index("function otherMarkup")]
    other = source[source.index("function otherMarkup"):source.index("function resultMarkup")]
    for block in (option, other):
        assert "t('ui.fare.sample'" in block
    assert "${sample}" in option
    assert "sourceRow(" in source[source.index("function lineMarkup"):source.index("function optionMarkup")]
