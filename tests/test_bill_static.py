"""Static and pure-function checks for the E61 device-side explainer."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import REPO_ROOT
from test_i18n_surfaces import TURKISH_CHARS, UI_CALL, template_literals, ui_calls

from ibb_mcp.config import REPO_ROOT as CONFIG_ROOT

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
BILL_JS = STATIC / "js" / "bill.js"
BILL_CSS = STATIC / "css" / "bill.css"

CATALOG = {
    "tr": {
        "ui.bill.addLine": "Kalem ekle",
        "ui.bill.agencyLabel": "Kurum",
        "ui.bill.alo185": "İSKİ Alo 185",
        "ui.bill.amount": "Tutar (TL)",
        "ui.bill.billItem": "Fatura kalemi",
        "ui.bill.call153": "153’ü ara",
        "ui.bill.call185": "185’i ara",
        "ui.bill.cancel": "Vazgeç",
        "ui.bill.chooseAgency": "Kalemleri görmek için önce kurum seçin.",
        "ui.bill.chooseItem": "Kalem seçin",
        "ui.bill.clearBills": "Bu cihazdaki fatura kayıtlarını sil",
        "ui.bill.cleared": "Bu cihazdaki kayıtlar silindi.",
        "ui.bill.compareContext": "Kıyas, bu cihazdaki aynı kurumun önceki kaydıyla yapılır.",
        "ui.bill.compareTitle": "Önceki kayıtla kıyas",
        "ui.bill.confirmClear": "Onayla ve sil",
        "ui.bill.consentNeeded": "Saklamak için önce yalnız bu cihazda saklama kutusunu işaretleyin.",
        "ui.bill.consumption": "Tüketim",
        "ui.bill.copied": "Taslak panoya kopyalandı.",
        "ui.bill.copyDraft": "Taslağı kopyala",
        "ui.bill.copyFallback": "Kopyalamak için Ctrl+C / Cmd+C tuşlarına basın.",
        "ui.bill.currentBill": "Bu fatura",
        "ui.bill.dailyAverage": "Günlük ortalama",
        "ui.bill.days": "Dönem gün sayısı",
        "ui.bill.daysUnit": "gün",
        "ui.bill.decreased": "azaldı",
        "ui.bill.designThreshold": "1,5 oranı Nabız tasarım eşiğidir; İSKİ ölçütü değildir.",
        "ui.bill.difference": "Fark",
        "ui.bill.draftClose": "Bilgi rica ederim.",
        "ui.bill.draftHello": "Merhaba,",
        "ui.bill.draftIntro": "Faturamda, [abone numaranız] için {period} dönem tüketimi {amount} {unit} görünüyor.",
        "ui.bill.draftLabel": "Düzenlenebilir taslak",
        "ui.bill.draftPointDaily": "Sayaç okuma tarihini ve endeksini açıklayabilir misiniz?",
        "ui.bill.draftPointLeak": (
            "İç tesisattaki gizli su kaçağı düzenlemesinin koşullarını ve "
            "uygulanıp uygulanmayacağını açıklayabilir misiniz?"
        ),
        "ui.bill.draftPointOther": "Bu kalem hakkında bilgi rica ederim.",
        "ui.bill.draftPointPeriod": (
            "Dönemlerin farklı uzunlukta olduğunu dikkate alarak günlük ortalama tüketimi "
            "açıklayabilir misiniz?"
        ),
        "ui.bill.draftPointSum": (
            "Girdiğim kalemlerin toplamı faturadaki toplamla uyuşmuyor; atlanan bir satır olup "
            "olmadığını açıklar mısınız?"
        ),
        "ui.bill.draftPointUnknown": "Bu kalemin ne olduğunu kurumunuza sorabilir misiniz?",
        "ui.bill.draftTitle": "Soru taslağı",
        "ui.bill.draftTo": "ile",
        "ui.bill.draftUnsent": "Taslak: gönderilmedi",
        "ui.bill.editBill": "Bilgileri düzenle",
        "ui.bill.errorAmount": "Tutarı en çok iki ondalık basamakla girin.",
        "ui.bill.errorDate": "Tarih girin.",
        "ui.bill.errorDigits": "Bu alana numara yazmayın; abone ya da kimlik numarası gerekmez.",
        "ui.bill.errorNameLength": "Kalem adı en çok 60 karakter olabilir.",
        "ui.bill.errorOrder": "Bitiş tarihi başlangıç tarihinden sonra olmalı.",
        "ui.bill.errorPeriod": "Dönem 1 ile 100 gün arasında olmalı.",
        "ui.bill.errorRange": "Tüketim 0 ile 100000 arasında olmalı.",
        "ui.bill.errorRequired": "Bu alanı doldurun.",
        "ui.bill.explain": "Açıkla",
        "ui.bill.igdas": "İGDAŞ",
        "ui.bill.igdasNotice": "İGDAŞ faturası için Nabız kaynaklarında açıklama yok.",
        "ui.bill.increased": "arttı",
        "ui.bill.iski": "İSKİ",
        "ui.bill.itemName": "Kalem adı",
        "ui.bill.itemNumber": "Kalem {number}",
        "ui.bill.leakCheck": "Tesisatta kaçak ya da arıza fark ettim",
        "ui.bill.loadError": "Katalog alınamadı. Kurumunuzun resmî kanalına ya da 153’e başvurun.",
        "ui.bill.loading": "Kaynaklı açıklama yükleniyor.",
        "ui.bill.measure": "Ölçü",
        "ui.bill.mock": "Örnek veri kipinde fatura açıklaması kapalı.",
        "ui.bill.monthlyEquivalent": "Girdiğiniz tüketimin 30 güne karşılığı: {value} m³.",
        "ui.bill.newTab": "yeni sekmede açılır",
        "ui.bill.noSavedBills": "Kayıt yok.",
        "ui.bill.noSource": "Kaynak henüz yok.",
        "ui.bill.noSourceText": "Bu kalemin açıklaması Nabız kaynaklarında yok; kurumunuza sorun.",
        "ui.bill.notice": "Faturanızdaki bilgileri kendiniz girersiniz; bilgiler bu cihazdan çıkmaz. Resmî İBB hizmeti değildir.",
        "ui.bill.officialChannels": "Resmî kanallar",
        "ui.bill.openSource": "Kaynağı aç",
        "ui.bill.optionalTotal": "İsteğe bağlı fatura toplamı (TL)",
        "ui.bill.page": "s. {page}",
        "ui.bill.periodEnd": "Dönem bitişi",
        "ui.bill.periodStart": "Dönem başlangıcı",
        "ui.bill.periodSummary": "{days} gün; günlük ortalama {average} {unit}/gün.",
        "ui.bill.pointDaily": (
            "Günlük ortalama tüketim belirgin arttı; sayaç okuma tarihini ve endeksini sorabilirsiniz. "
            "Sayacın ölçüme gönderilmesini isteyebilirsiniz; yönetmeliğe göre sayaç doğru çıkarsa "
            "ölçüm bedelleri size tahakkuk ettirilir."
        ),
        "ui.bill.pointDailyGas": "Günlük ortalama tüketim belirgin arttı; sayaç okuma tarihini ve endeksini sorabilirsiniz.",
        "ui.bill.pointLeak": (
            "Yönetmelikte iç tesisattaki gizli su kaçağı için bir düzenleme var; koşullarını ve "
            "uygulanıp uygulanmayacağını İSKİ belirler."
        ),
        "ui.bill.pointPeriod": "Dönemler farklı uzunlukta; karşılaştırmada günlük ortalamaya bakın.",
        "ui.bill.pointSum": "Girdiğiniz kalemlerin toplamı faturadaki toplamla tutmuyor; atlanan bir satır olabilir.",
        "ui.bill.pointUnknown": "Bu kalemin ne olduğunu kurumunuza sorabilirsiniz.",
        "ui.bill.pointsTitle": "Sorulabilecek noktalar",
        "ui.bill.previousBill": "Önceki fatura",
        "ui.bill.rangeLast": "31 ve üzeri",
        "ui.bill.ready": "Açıklama hazır. Kararı kurumunuz verir.",
        "ui.bill.recorded": "kaydedildi: {date}",
        "ui.bill.removeLine": "Kalemi sil",
        "ui.bill.resultTitle": "Açıklama",
        "ui.bill.same": "aynı",
        "ui.bill.saveBill": "Sakla",
        "ui.bill.savedBill": "Bu faturayı yalnız bu cihazda sakla",
        "ui.bill.savedOk": "Fatura bu cihazda saklandı.",
        "ui.bill.savedTitle": "Kayıtlı faturalarım (bu cihazda)",
        "ui.bill.singleHome": "Konut aboneliği, tek konut",
        "ui.bill.sourceLine": "Kaynak",
        "ui.bill.sourceQuote": "Kaynaktaki metin",
        "ui.bill.storageUnavailable": "Bu tarayıcıda saklama kapalı; bilgiler sayfa yenilenince silinir.",
        "ui.bill.tariffCaveat": "Bu tablo bir hesap değildir; faturadaki tutar KDV, düşümler ve abone türüne göre değişir.",
        "ui.bill.tariffTitle": "2026 konut su tarifesi (KDV hariç, TL/m³)",
        "ui.bill.tier": "Kademe",
        "ui.bill.tierCurrent": "Girdiğiniz tüketim bu aralıkta",
        "ui.bill.tierNotice": "Bu bir hesap değildir; faturadaki kademe İSKİ’nin okuma dönemine göre belirlenir.",
        "ui.bill.tierRange": "Kademe {tier}: {range} m³/ay",
        "ui.bill.title": "Faturamı anla",
        "ui.bill.totalRate": "Toplam birim fiyat",
        "ui.bill.unitLabel": "Tüketim birimi",
        "ui.bill.versus": "önceki",
        "ui.bill.wastewaterRate": "Atık su birim fiyatı",
        "ui.bill.waterRate": "Su birim fiyatı",
    },
    "en": {
        "ui.bill.addLine": "Add item",
        "ui.bill.agencyLabel": "Agency",
        "ui.bill.alo185": "İSKİ Alo 185",
        "ui.bill.amount": "Amount (TL)",
        "ui.bill.billItem": "Bill item",
        "ui.bill.call153": "Call 153",
        "ui.bill.call185": "Call 185",
        "ui.bill.cancel": "Cancel",
        "ui.bill.chooseAgency": "Choose an agency to see its items.",
        "ui.bill.chooseItem": "Choose an item",
        "ui.bill.clearBills": "Delete bills saved on this device",
        "ui.bill.cleared": "Saved bills on this device were deleted.",
        "ui.bill.compareContext": "The comparison uses the previous bill from the same agency saved on this device.",
        "ui.bill.compareTitle": "Compare with the previous bill",
        "ui.bill.confirmClear": "Confirm and delete",
        "ui.bill.consentNeeded": "Select the device-only storage box before saving.",
        "ui.bill.consumption": "Consumption",
        "ui.bill.copied": "The draft was copied to the clipboard.",
        "ui.bill.copyDraft": "Copy draft",
        "ui.bill.copyFallback": "Press Ctrl+C / Cmd+C to copy.",
        "ui.bill.currentBill": "This bill",
        "ui.bill.dailyAverage": "Daily average",
        "ui.bill.days": "Days in period",
        "ui.bill.daysUnit": "days",
        "ui.bill.decreased": "decreased",
        "ui.bill.designThreshold": "The 1.5 ratio is a Nabız design threshold, not an İSKİ criterion.",
        "ui.bill.difference": "Difference",
        "ui.bill.draftClose": "Thank you for your information.",
        "ui.bill.draftHello": "Hello,",
        "ui.bill.draftIntro": "My bill shows consumption of {amount} {unit} for [your subscriber number] during {period}.",
        "ui.bill.draftLabel": "Editable draft",
        "ui.bill.draftPointDaily": "Could you explain the meter reading date and index?",
        "ui.bill.draftPointLeak": (
            "Could you explain the conditions for the internal plumbing leak provision "
            "and whether it applies?"
        ),
        "ui.bill.draftPointOther": "Please provide information about this item.",
        "ui.bill.draftPointPeriod": (
            "Could you explain the daily average consumption, considering the periods have "
            "different lengths?"
        ),
        "ui.bill.draftPointSum": (
            "The items I entered do not match the bill total; could you explain whether a line "
            "may be missing?"
        ),
        "ui.bill.draftPointUnknown": "Could you explain what this item is?",
        "ui.bill.draftTitle": "Question draft",
        "ui.bill.draftTo": "to",
        "ui.bill.draftUnsent": "Draft: not sent",
        "ui.bill.editBill": "Edit details",
        "ui.bill.errorAmount": "Enter an amount with no more than two decimal places.",
        "ui.bill.errorDate": "Enter a date.",
        "ui.bill.errorDigits": "Do not enter a number here; no account or identity number is needed.",
        "ui.bill.errorNameLength": "An item name can be at most 60 characters.",
        "ui.bill.errorOrder": "The end date must be after the start date.",
        "ui.bill.errorPeriod": "The period must be 1 to 100 days.",
        "ui.bill.errorRange": "Consumption must be from 0 to 100000.",
        "ui.bill.errorRequired": "Complete this field.",
        "ui.bill.explain": "Explain",
        "ui.bill.igdas": "İGDAŞ",
        "ui.bill.igdasNotice": "Nabız has no explanation sources for İGDAŞ bills.",
        "ui.bill.increased": "increased",
        "ui.bill.iski": "İSKİ",
        "ui.bill.itemName": "Item name",
        "ui.bill.itemNumber": "Item {number}",
        "ui.bill.leakCheck": "I noticed a leak or fault in the plumbing",
        "ui.bill.loadError": "The catalogue could not be loaded. Contact your agency through an official channel or call 153.",
        "ui.bill.loading": "Loading sourced explanations.",
        "ui.bill.measure": "Measure",
        "ui.bill.mock": "Bill explanations are disabled in sample data mode.",
        "ui.bill.monthlyEquivalent": "Your consumption equivalent for 30 days: {value} m³.",
        "ui.bill.newTab": "opens in a new tab",
        "ui.bill.noSavedBills": "No saved bills.",
        "ui.bill.noSource": "Source not available yet.",
        "ui.bill.noSourceText": "Nabız has no source explaining this item; ask your agency.",
        "ui.bill.notice": "You enter the bill details; they stay on this device. Not an official İBB service.",
        "ui.bill.officialChannels": "Official channels",
        "ui.bill.openSource": "Open source",
        "ui.bill.optionalTotal": "Optional bill total (TL)",
        "ui.bill.page": "p. {page}",
        "ui.bill.periodEnd": "Period end",
        "ui.bill.periodStart": "Period start",
        "ui.bill.periodSummary": "{days} days; daily average {average} {unit}/day.",
        "ui.bill.pointDaily": (
            "Daily average consumption increased notably; you can ask about the meter reading date and index. "
            "You can request a meter inspection; if the meter is found to work correctly, inspection fees are charged."
        ),
        "ui.bill.pointDailyGas": (
            "Daily average consumption increased notably; you can ask about the meter reading date and index."
        ),
        "ui.bill.pointLeak": (
            "The regulation has a provision for a hidden leak in internal plumbing; İSKİ decides its conditions "
            "and whether it applies."
        ),
        "ui.bill.pointPeriod": "The periods have different lengths; compare their daily averages.",
        "ui.bill.pointSum": "The items you entered do not match the bill total; a line may be missing.",
        "ui.bill.pointUnknown": "You can ask your agency what this item is.",
        "ui.bill.pointsTitle": "Points you can ask about",
        "ui.bill.previousBill": "Previous bill",
        "ui.bill.rangeLast": "31 and over",
        "ui.bill.ready": "Explanations are ready. Your agency decides.",
        "ui.bill.recorded": "recorded: {date}",
        "ui.bill.removeLine": "Remove item",
        "ui.bill.resultTitle": "Explanation",
        "ui.bill.same": "unchanged",
        "ui.bill.saveBill": "Save",
        "ui.bill.savedBill": "Save this bill on this device only",
        "ui.bill.savedOk": "The bill was saved on this device.",
        "ui.bill.savedTitle": "My saved bills on this device",
        "ui.bill.singleHome": "Residential account, one home",
        "ui.bill.sourceLine": "Source",
        "ui.bill.sourceQuote": "Text from the source",
        "ui.bill.storageUnavailable": "Storage is unavailable in this browser; details will be cleared when the page reloads.",
        "ui.bill.tariffCaveat": (
            "This table is not a calculation; the bill amount varies with VAT, deductions, and subscriber type."
        ),
        "ui.bill.tariffTitle": "2026 residential water tariff (excluding VAT, TL/m³)",
        "ui.bill.tier": "Tier",
        "ui.bill.tierCurrent": "Your entered consumption falls in this range",
        "ui.bill.tierNotice": "This is not a calculation; İSKİ determines the bill tier from its reading period.",
        "ui.bill.tierRange": "Tier {tier}: {range} m³/month",
        "ui.bill.title": "Understand my bill",
        "ui.bill.totalRate": "Total unit price",
        "ui.bill.unitLabel": "Consumption unit",
        "ui.bill.versus": "previous",
        "ui.bill.wastewaterRate": "Wastewater unit price",
        "ui.bill.waterRate": "Water unit price",
    },
}


def node_bill_json(tmp_path: Path, body: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    module_url = json.dumps((BILL_JS).as_uri())
    i18n_url = json.dumps((STATIC / "js" / "i18n_text.js").as_uri())
    script = f"""
      const values = new Map();
      globalThis.window = {{
        location: {{ search: '', hash: '', origin: 'http://localhost' }},
        addEventListener() {{}}, removeEventListener() {{}}, dispatchEvent() {{}},
        requestAnimationFrame(callback) {{ callback(); }},
        localStorage: {{
          getItem(key) {{ return values.get(key) || null; }},
          setItem(key, value) {{ values.set(key, value); }},
          removeItem(key) {{ values.delete(key); }}
        }}
      }};
      const bill = await import({module_url});
      const i18n = await import({i18n_url});
      {body}
    """
    harness = tmp_path / "bill_harness.mjs"
    harness.write_text(script, encoding="utf-8")
    result = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_ui_keys_and_fallbacks_match_the_local_catalogues() -> None:
    source = BILL_JS.read_text(encoding="utf-8")
    fallbacks = ui_calls(source)
    assert set(fallbacks) == set(CATALOG["tr"]) == set(CATALOG["en"])
    for key, fallback in fallbacks.items():
        assert CATALOG["tr"][key] == fallback, key
        assert set(re.findall(r"\{(\w+)\}", CATALOG["tr"][key])) == set(re.findall(r"\{(\w+)\}", CATALOG["en"][key])), key
    current_tr = json.loads((STATIC / "i18n" / "tr.json").read_text(encoding="utf-8"))
    current_en = json.loads((STATIC / "i18n" / "en.json").read_text(encoding="utf-8"))
    # P00 G5: the keys moved into the page catalogues, unchanged
    assert all(current_tr[k] == v for k, v in CATALOG["tr"].items())
    assert all(current_en[k] == v for k, v in CATALOG["en"].items())


def test_module_has_no_bare_turkish_or_forbidden_visible_text() -> None:
    source = BILL_JS.read_text(encoding="utf-8")
    clean = re.sub(r"/\*.*?\*/|^\s*//.*$", "", source, flags=re.S | re.M)
    fallback_spans = [match.span(4) for match in UI_CALL.finditer(clean)]
    literal_source = list(clean)
    for start, end, chunks in template_literals(clean):
        for chunk in chunks:
            assert TURKISH_CHARS.search(chunk) is None, chunk
        literal_source[start:end] = [" "] * (end - start)
    quoted = re.compile(r"'((?:\\.|[^'\\])*)'|\"((?:\\.|[^\"\\])*)\"", re.S)
    for match in quoted.finditer("".join(literal_source)):
        value = next(part for part in match.groups() if part is not None)
        if TURKISH_CHARS.search(value):
            start, end = match.span(next(i for i, part in enumerate(match.groups(), start=1) if part is not None))
            assert any(left <= start and end <= right for left, right in fallback_spans), value
    joined = source + BILL_CSS.read_text(encoding="utf-8") + json.dumps(CATALOG, ensure_ascii=False)
    assert chr(0x2014) not in joined and chr(0x2013) not in joined
    assert "canlı" not in joined.casefold()
    assert "find_forbidden" not in source


def test_style_uses_tokens_and_guards_its_single_appearance() -> None:
    css = BILL_CSS.read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}|\brgba?\s*\(", css)
    assert "@media (prefers-reduced-motion: no-preference)" in css
    assert "animation: bill-result-in var(--nd-dur-enter) var(--nd-ease-enter) both" in css
    assert "@media (prefers-reduced-motion: reduce)" not in css
    assert "infinite" not in css
    assert "transition:" not in css
    assert ".bill-compare-narrow" in css and ".bill-tariff-narrow" in css
    assert ".bill-tariff .bill-table-wrap" in css


def test_module_requests_only_the_catalogue_and_stores_one_device_key() -> None:
    source = BILL_JS.read_text(encoding="utf-8")
    assert "get(CATALOG_PATH, { lang: currentLang() })" in source
    assert "const CATALOG_PATH = '/api/bill/catalog'" in source
    assert "fetch(" not in source and "post(" not in source and "POST" not in source
    assert "const STORAGE_KEY = 'nabiz.bill.v1'" in source
    assert "setInterval" not in source and "scroll" not in source and "MutationObserver" not in source
    assert "document.body" not in source
    save_start = source.index("if (event.target.closest('[data-save]'))")
    save_end = source.index("if (event.target.closest('[data-edit]'))", save_start)
    save_code = source[save_start:save_end]
    assert save_code.index("if (!consent.checked)") < save_code.index("writeBills(updated)")
    assert "localStorage" in source and "nabiz.bill.v1" in source
    assert 'bill.js' not in (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'bill.css' not in (STATIC / "sw.js").read_text(encoding="utf-8")
    assert 'bill.js' not in (STATIC / "sw.js").read_text(encoding="utf-8")


def test_bill_module_is_valid_and_uses_existing_comparison_icons() -> None:
    source = BILL_JS.read_text(encoding="utf-8")
    result = subprocess.run(["node", "--check", str(BILL_JS)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    sprite = (STATIC / "icons.svg").read_text(encoding="utf-8")
    names = set(re.findall(r'<symbol id="i-([^"]+)"', sprite))
    assert {"external-link", "trending-up", "trending-down", "equal"} <= names
    assert "icon('external-link')" in source


def test_pure_input_comparison_questions_and_drafts(tmp_path: Path) -> None:
    catalog = json.loads((CONFIG_ROOT / "data" / "knowledge" / "bill_items.json").read_text(encoding="utf-8"))
    values = node_bill_json(
        tmp_path,
        """
        const catalog = JSON.parse(CATALOG_JSON);
        const base = {
          agency:'iski',start:'2026-09-01',end:'2026-10-01',unit:'m³',consumption:30,
          items:[{id:'su_bedeli',amount:80}],total:80
        };
        const invalidDate = bill.checkEntry({...base,end:base.start});
        const reverse = bill.checkEntry({...base,start:'2026-10-01',end:'2026-09-01'});
        const long = bill.checkEntry({...base,start:'2026-06-22',end:'2026-10-01'});
        const badAmount = bill.checkEntry({...base,items:[{id:'su_bedeli',amount:-1}]});
        const badName = bill.checkEntry({...base,items:[{id:'diger',label:'Kalem 123456',amount:1}]});
        const valid = bill.checkEntry(base);
        const previous = {
          ...base,id:'prev',start:'2026-08-01',end:'2026-08-21',consumption:20,
          items:[{id:'su_bedeli',amount:20}],total:20
        };
        const movement = [81,79,80].map((amount) => bill.compare(
          {...base,items:[{id:'su_bedeli',amount}]},
          {...base,id:'movement-prev',items:[{id:'su_bedeli',amount:80}]}
        ).items[0].direction);
        const allCurrent = {
          ...base,start:'2026-09-01',end:'2026-10-01',consumption:90,
          items:[{id:'diger',label:'İlave kalem',amount:50}],total:500,leak:true
        };
        const allPoints = bill.pointsToAsk(allCurrent, previous, catalog);
        const quiet = bill.pointsToAsk(
          {...base,consumption:10},
          {...base,id:'quiet-prev',start:'2026-08-01',end:'2026-08-31',consumption:20,
            items:[{id:'su_bedeli',amount:80}],total:80},
          catalog
        );
        const belowRatio = bill.pointsToAsk(
          {...base,items:[{id:'su_bedeli',amount:80}],total:80,consumption:44.7},
          {...base,id:'ratio-prev',items:[{id:'su_bedeli',amount:80}],total:80,consumption:30},catalog
        );
        const oneLiraDifference = bill.pointsToAsk(
          {...base,items:[{id:'su_bedeli',amount:80}],total:81,consumption:30},
          {...base,id:'sum-prev',items:[{id:'su_bedeli',amount:80}],total:80,consumption:30},catalog
        );
        const gas = bill.pointsToAsk(
          {...allCurrent,agency:'igdas',leak:true,unit:'kWh',items:[{id:'igdas_diger',label:'Service',amount:2}]},
          previous, catalog
        );
        i18n.setCatalogs('tr', {}, {});
        const draftTr = bill.draftText(allCurrent, allPoints, 'tr');
        const trVerdictWords = ['yanlış','iade','fazla ödeme','itiraz ediyorum','hak kazan']
          .some((word) => draftTr.toLocaleLowerCase('tr').includes(word));
        i18n.setCatalogs('en', {
          'ui.bill.draftHello':'Hello,','ui.bill.draftTo':'to',
          'ui.bill.draftIntro':'My bill shows consumption of {amount} {unit} for [your subscriber number] during {period}.',
          'ui.bill.draftClose':'Thank you for your information.',
          'ui.bill.draftPointUnknown':'Could you explain what this item is?',
          'ui.bill.draftPointSum':'Could you explain the total?',
          'ui.bill.draftPointPeriod':'Could you explain the daily average?',
          'ui.bill.draftPointDaily':'Could you explain the meter reading date and index?',
          'ui.bill.draftPointLeak':'Could you explain whether the provision applies?',
          'ui.bill.draftPointOther':'Please provide information.'
        }, {});
        const draftEn = bill.draftText(allCurrent, allPoints, 'en');
        const entry = {agency:'iski',start:'2026-09-01',end:'2026-10-01',consumption:14.9};
        const rows = [{tier:1},{tier:2},{tier:3}];
        const tiers = [14.9,15,15.1,30,30.1].map((value) => bill.tierFor(value, rows));
        const storageRoundtrip = bill.writeBills([{id:'b1',agency:'iski',start:'2026-09-01',end:'2026-10-01'}])
          && bill.readBills().length === 1 && bill.writeBills([]) && bill.readBills().length === 0;
        console.log(JSON.stringify({
          parsed:bill.parseAmount('1.234,56'),days:bill.periodDays(base),average:bill.dailyAverage(base),
          invalidDate:invalidDate.errors.map((x)=>x.code),reverse:reverse.ok,long:long.ok,badAmount:badAmount.ok,
          badName:badName.errors.map((x)=>x.code),valid:valid.ok,allPoints:allPoints.map((x)=>x.id),
          allSources:allPoints.map((x)=>x.source !== null),
          quiet:quiet.map((x)=>x.id),belowRatio:belowRatio.map((x)=>x.id),oneLiraDifference:oneLiraDifference.map((x)=>x.id),movement,
          gas:gas.map((x)=>[x.id,x.source,x.text_key]),draftTr,trVerdictWords,draftEn,tiers,monthly:bill.monthlyEquivalent(entry),storageRoundtrip
        }));
        """.replace("CATALOG_JSON", json.dumps(json.dumps(catalog, ensure_ascii=False), ensure_ascii=False)),
    )
    assert values["parsed"] == 1234.56
    assert values["days"] == 30 and values["average"] == 1
    assert values["invalidDate"] and not values["reverse"] and not values["long"] and not values["badAmount"]
    assert "digits" in values["badName"] and values["valid"]
    assert values["allPoints"] == ["unknown_item", "sum_mismatch", "period_length", "daily_up", "hidden_leak"]
    assert values["allSources"] == [False, False, True, True, True]
    assert values["quiet"] == []
    assert values["belowRatio"] == [] and values["oneLiraDifference"] == []
    assert values["movement"] == ["up", "down", "same"]
    assert all(source is None for _, source, _ in values["gas"])
    assert [point_id for point_id, _, _ in values["gas"]] == ["unknown_item", "sum_mismatch", "period_length", "daily_up"]
    assert all(key == "ui.bill.pointDailyGas" for point_id, _, key in values["gas"] if point_id == "daily_up")
    assert "[abone numaranız]" in values["draftTr"] and "90" in values["draftTr"] and not values["trVerdictWords"]
    assert "[your subscriber number]" in values["draftEn"] and "90" in values["draftEn"]
    assert values["tiers"] == [1, 1, 2, 2, 3] and values["monthly"] == 14.9
    assert values["storageRoundtrip"]
