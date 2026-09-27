"""Static and pure-function checks for the self-mounting disaster-kit module."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import REPO_ROOT
from test_i18n_surfaces import TURKISH_CHARS, UI_CALL, js_fallback, template_literals
from test_static_a11y import STATIC

JS = STATIC / "js/disaster_kit.js"
CSS = STATIC / "css/disaster_kit.css"
JS_DIR = STATIC / "js"
_COPY = (
    ("ui.disaster.bag_place", "Çantamız nerede duruyor", "Where the bag is kept"),
    ("ui.disaster.meet_near", "Evin yakınında buluşma yeri", "Meeting place near home"),
    ("ui.disaster.meet_far", "Mahalle dışında buluşma yeri", "Meeting place outside the neighbourhood"),
    ("ui.disaster.assembly_note", "Bildiğim toplanma alanı", "Assembly area I know"),
    ("ui.disaster.no_date", "bilinmiyor", "unknown"),
    ("ui.disaster.updated", "sayfa güncellemesi {date}", "page updated {date}"),
    ("ui.disaster.no_update", "sayfada tarih yok", "no date on page"),
    ("ui.disaster.saved_date", "kaydedildi {date}", "saved {date}"),
    ("ui.disaster.open_source", "Kaynağı aç", "Open source"),
    ("ui.disaster.new_tab", "yeni sekmede açılır", "opens in a new tab"),
    ("ui.disaster.quote_toggle", "Kaynaktaki metin", "Source text"),
    ("ui.disaster.person", "Kişi {number}", "Person {number}"),
    ("ui.disaster.person_name", "Ad ya da yakınlık", "Name or relationship"),
    ("ui.disaster.phone", "Telefon", "Phone"),
    ("ui.disaster.remove_person", "Kişiyi kaldır", "Remove person"),
    ("ui.disaster.error_too_long", "Bu alanın sınırını kısaltın.", "Shorten this field."),
    (
        "ui.disaster.error_digits",
        "Bu alana numara yazmayın; kimlik ya da adres numarası gerekmez.",
        "Do not enter a number here; an identity or address number is not needed.",
    ),
    (
        "ui.disaster.error_phone_format",
        "Telefonu ülke koduyla ya da başında 0 ile yazın.",
        "Use a phone number with a country code or a leading 0.",
    ),
    (
        "ui.disaster.save_off",
        "Kaydetme kapalı; sayfa yenilenince işaretler silinir.",
        "Saving is off; checks are cleared when you reload the page.",
    ),
    ("ui.disaster.saved", "Bu cihazda kaydedildi, {time}", "Saved on this device, {time}"),
    ("ui.disaster.storage_closed", "Bu tarayıcıda saklama kapalı.", "Storage is unavailable in this browser."),
    ("ui.disaster.no_people", "Henüz kişi eklenmedi.", "No people added yet."),
    ("ui.disaster.review_six_months", "Su ya da gıda maddesini gözden geçirme zamanı.", "Time to review water or food."),
    (
        "ui.disaster.review_yearly",
        "Çanta içeriğini ve ailenizin gereksinimlerini gözden geçirme zamanı.",
        "Time to review the kit contents and your family's needs.",
    ),
    ("ui.disaster.review_done", "Gözden geçirdim", "I reviewed it"),
    ("ui.disaster.title", "Afet hazırlık dosyam", "My disaster preparation file"),
    (
        "ui.disaster.notice",
        "Bu dosya yalnız bu cihazda durur. Nabız binanızın ya da evinizin "
        "güvenliği hakkında değerlendirme yapmaz. Resmî İBB hizmeti değildir.",
        "This file stays on this device. Nabız does not assess your building or household. Not an official İBB service.",
    ),
    (
        "ui.disaster.offline_note",
        "Kaynak listesi çevrimdışı kullanım için bu cihazda saklanır.",
        "The source list is stored on this device for offline use.",
    ),
    ("ui.disaster.loading", "Kaynaklı liste yükleniyor.", "Loading source-backed list."),
    ("ui.disaster.failed", "Kaynaklı liste alınamadı.", "Could not load the source-backed list."),
    ("ui.disaster.mock", "Örnek veri kipinde afet dosyası kapalı.", "The disaster file is unavailable in sample data mode."),
    ("ui.disaster.count", "{total} maddeden {done} işaretli", "{done} of {total} items checked"),
    ("ui.disaster.empty", "Kaynaklı liste henüz alınmadı.", "The source-backed list has not loaded yet."),
    ("ui.disaster.care_title", "Çantanın bakımı", "Kit care"),
    ("ui.disaster.assembly_found", "Katalogda bir veri seti bulundu: {name}", "Dataset found in the catalogue: {name}"),
    (
        "ui.disaster.assembly_missing",
        "İBB açık veri kataloğunda toplanma alanı veri seti bulunamadı "
        "({count} veri seti tarandı, kaydedildi {date}). Nabız toplanma alanı göstermez.",
        "No assembly-area dataset was found in the İBB open data catalogue "
        "({count} datasets checked, saved {date}). Nabız does not show assembly areas.",
    ),
    ("ui.disaster.cached", "Kaydedilen kopya ({date})", "Saved copy ({date})"),
    (
        "ui.disaster.error_next",
        "Kaynaklar alınamadı. Bağlantıyı yeniden deneyin ya da 153’ü arayın.",
        "Sources could not be loaded. Retry the connection or call 153.",
    ),
    ("ui.disaster.call_number", "153", "153"),
    ("ui.disaster.bag_title", "Afet çantası", "Disaster kit"),
    ("ui.disaster.institution_badge", "Kurum kaynağı: AKOM", "Institution source: AKOM"),
    ("ui.disaster.plan_title", "Aile planı", "Family plan"),
    ("ui.disaster.personal_badge", "Sizin notunuz, Nabız doğrulamaz", "Your note, not verified by Nabız"),
    ("ui.disaster.contacts_title", "İletişime geçilecek kişiler", "People to contact"),
    ("ui.disaster.add_person", "Kişi ekle", "Add a person"),
    ("ui.disaster.consent", "Bu dosyayı yalnız bu cihazda sakla", "Store this file only on this device"),
    ("ui.disaster.assembly_title", "Toplanma alanı", "Assembly area"),
    ("ui.disaster.building_title", "Binam", "My building"),
    (
        "ui.disaster.building_notice",
        "Nabız binanızın durumu hakkında değerlendirme yapmaz ve fotoğraf almaz.",
        "Nabız does not assess your building and does not collect photos.",
    ),
    ("ui.disaster.print", "Yazdır ya da PDF olarak kaydet", "Print or save as PDF"),
    ("ui.disaster.print_contacts", "Yazdırırken kişileri de ekle", "Include people when printing"),
    ("ui.disaster.delete_again", "Silmek için yeniden basın", "Press again to delete"),
    ("ui.disaster.delete", "Bu cihazdaki afet dosyasını sil", "Delete the disaster file on this device"),
    ("ui.disaster.disclaimer", "Resmî İBB hizmeti değildir.", "Not an official İBB service."),
    ("ui.disaster.printed_on", "Yazdırma tarihi: {date}", "Print date: {date}"),
    ("ui.disaster.deleted", "Bu cihazdaki afet dosyası silindi.", "Disaster file deleted from this device."),
)
CATALOG = {
    "tr": {key: tr for key, tr, _en in _COPY},
    "en": {key: en for key, _tr, en in _COPY},
}


def test_module_fallbacks_equal_the_two_language_catalogue() -> None:
    source = JS.read_text(encoding="utf-8")
    fallback = {match.group(2): js_fallback(match.group(4)) for match in UI_CALL.finditer(source)}
    assert set(fallback) == set(CATALOG["tr"]) == set(CATALOG["en"])
    assert fallback == CATALOG["tr"]
    for key, tr in CATALOG["tr"].items():
        en = CATALOG["en"][key]
        assert set(re.findall(r"\{(\w+)\}", tr)) == set(re.findall(r"\{(\w+)\}", en)), key
    for language in ("tr", "en"):
        existing = json.loads((STATIC / f"i18n/{language}.json").read_text(encoding="utf-8"))
        assert not (set(CATALOG[language]) & set(existing))


def test_module_has_no_bare_turkish_or_forbidden_display_text() -> None:
    source = JS.read_text(encoding="utf-8")
    clean = re.sub(r"/\*.*?\*/|^\s*//.*$", "", source, flags=re.S | re.M)
    fallbacks = [match.span(4) for match in UI_CALL.finditer(clean)]
    literal_source = list(clean)
    for start, end, chunks in template_literals(clean):
        assert all(TURKISH_CHARS.search(chunk) is None for chunk in chunks)
        literal_source[start:end] = [" "] * (end - start)
    cleaned = "".join(literal_source)
    strings = re.compile(r"'((?:\\.|[^'\\])*)'|\"((?:\\.|[^\"\\])*)\"", re.S)
    for match in strings.finditer(cleaned):
        group = 1 if match.group(1) is not None else 2
        value, span = match.group(group), match.span(group)
        if TURKISH_CHARS.search(value):
            assert any(left <= span[0] and span[1] <= right for left, right in fallbacks), value
    for path in (JS, CSS, REPO_ROOT / "data/knowledge/disaster_kit.json"):
        text = path.read_text(encoding="utf-8").lower()
        assert "—" not in text and "–" not in text
        assert "canlı" not in text


def test_client_has_one_read_request_and_only_two_storage_keys() -> None:
    source = JS.read_text(encoding="utf-8")
    assert source.count("get('/api/disaster-kit', { lang })") == 1
    assert "addEventListener('submit', (event) => event.preventDefault())" in source
    assert re.findall(r"(?:https?://|['\"]/(?!api/)[^'\"]+)", source) == []
    assert not re.search(r"\b(?:POST|PUT)\b|method\s*:\s*['\"]DELETE|\.(?:post|delete)\s*\(", source, re.I)
    assert set(re.findall(r"'nabiz\.disaster\.[^']+'", source)) == {"'nabiz.disaster.v1'", "'nabiz.disaster.catalog.v1'"}
    for absent in ('type="file"', "getUserMedia", "geolocation", "setInterval", "MutationObserver", "addEventListener('scroll'"):
        assert absent not in source
    assert "disaster_kit" not in (STATIC / "index.html").read_text(encoding="utf-8")
    assert "disaster_kit" not in (STATIC / "sw.js").read_text(encoding="utf-8")


def test_styles_keep_print_scope_motion_and_tokens_local() -> None:
    css = CSS.read_text(encoding="utf-8")
    assert "@media print" in css and "nd-print-afet" in css
    assert "@media (prefers-reduced-motion: no-preference)" in css or not re.search(r"\b(?:transition|animation)\s*:", css)
    assert "infinite" not in css
    assert not re.search(r"#[0-9a-f]{3,8}\b|\brgba?\s*\(", css, re.I)
    sprite = (STATIC / "icons.svg").read_text(encoding="utf-8")
    icons = set(re.findall(r"icon\('([a-z-]+)'\)", JS.read_text(encoding="utf-8")))
    available = set(re.findall(r'<symbol id="i-([a-z-]+)"', sprite))
    assert icons <= available
    assert "375" not in css or "42rem" in css


def test_node_pure_rules_storage_review_and_print(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    source = JS.read_text(encoding="utf-8")
    subprocess.run([node, "--check", str(JS)], check=True, capture_output=True, text=True)
    replacements = {
        "import { MOCK, get } from './api.js';": "const { MOCK, get } = globalThis.disasterApi;",
        "import { currentLang, onLang, t } from './i18n_text.js';": "const { currentLang, onLang, t } = globalThis.disasterI18n;",
        "import { esc } from './format.js';": "const { esc } = globalThis.disasterFormat;",
        "import { icon } from './icons.js';": "const { icon } = globalThis.disasterIcons;",
    }
    for old, new in replacements.items():
        assert old in source
        source = source.replace(old, new)
    module_path = tmp_path / "disaster_kit_module.mjs"
    module_path.write_text(source, encoding="utf-8")
    harness = tmp_path / "disaster_kit_check.mjs"
    harness.write_text(
        """globalThis.disasterApi = {
  MOCK: false,
  get: async (...args) => args,
};
globalThis.disasterI18n = {
  currentLang: () => 'tr',
  onLang: () => () => {},
  t: (key, fallback, vars = {}) => fallback.replace(
    /\\{(\\w+)\\}/g,
    (_match, name) => vars[name] ?? `{${name}}`,
  ),
};
globalThis.disasterFormat = {
  esc: (value) => String(value ?? '').replace(/[&<>\\\"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '\\\"': '&quot;',
    \"'\": '&#39;',
  }[char])),
};
globalThis.disasterIcons = { icon: (name) => name };
const kit=await import('./disaster_kit_module.mjs');
const memory = {
  values: new Map(),
  getItem(key) { return this.values.get(key) ?? null; },
  setItem(key, value) { this.values.set(key, value); },
  removeItem(key) { this.values.delete(key); },
};
const failingStorage = { ...memory, setItem() { throw new Error('storage blocked'); } };
const noConsent = { consent: false };
const consent = { consent: true, version: 1, items: {}, plan: { contacts: [] } };
const base=Date.parse('2026-09-27T00:00:00Z');
const due = (days, field = 'su', reviewed = base) => kit.reviewDue({
  items: {
    [field]: {
      checked: true,
      checked_at: new Date(base - days * 86400000).toISOString(),
    },
  },
  reviewed_at: new Date(reviewed).toISOString(),
}, new Date(base));
const child = { open: false };
const root = { open: true, dataset: {}, querySelectorAll: () => [child] };
let after = () => {};
let printed = 0;
const classes = new Set();
const doc = {
  getElementById: (id) => id === 'afet-detail'
    ? root
    : id === 'afet-print-contacts' ? { checked: true } : null,
  documentElement: {
    classList: {
      add: (value) => classes.add(value),
      remove: (value) => classes.delete(value),
    },
  },
  defaultView: {
    addEventListener: (_name, fn) => { after = fn; },
    print: () => { printed++; },
  },
};
const printResult = kit.printKit(doc);
const during = [root.open, child.open, root.dataset.printContacts, classes.has('nd-print-afet')];
after();
const refused = kit.writeKit(memory, noConsent);
const writes = memory.values.size;
const accepted = kit.writeKit(memory, consent);
const roundTrip = kit.readKit(memory).consent;
const failedWrite = kit.writeKit(failingStorage, consent);
memory.values.set('nabiz.disaster.catalog.v1', 'cache');
const cleared = kit.clearKit(memory);
const catalogRetained = memory.values.has('nabiz.disaster.catalog.v1');
const result = {
  validLocal: kit.checkPlan({ contacts: [{ phone: '0532 123 45 67' }] }).ok,
  validIntl: kit.checkPlan({ contacts: [{ phone: '+90 212 123 45 67' }] }).ok,
  badPhone: kit.checkPlan({ contacts: [{ phone: '12345678901' }] }).ok,
  longPhone: kit.checkPlan({ contacts: [{ phone: '1234567890123456' }] }).ok,
  digits: kit.checkPlan({ bag_place: '123456' }).errors[0]?.code,
  long: kit.checkPlan({ bag_place: 'a'.repeat(81) }).errors[0]?.code,
  progress: kit.kitProgress({ items: { a: { checked: true } } }, [{ id: 'a' }, { id: 'b' }]),
  refused,
  writes,
  badJson: kit.readKit({ getItem: () => '{' }).consent,
  accepted,
  roundTrip,
  failedWrite,
  cleared,
  catalogRetained,
  six181: due(181).some((item) => item.id === 'six_months'),
  six182: due(182).some((item) => item.id === 'six_months'),
  year364: due(0, 'other', base - 364 * 86400000).some((item) => item.id === 'yearly'),
  year365: due(0, 'other', base - 365 * 86400000).some((item) => item.id === 'yearly'),
  unmarked: kit.reviewDue({ items: {} }, new Date(base)).length,
  printResult,
  during,
  afterPrint: [root.open, child.open, classes.has('nd-print-afet')],
  printed,
};
console.log(JSON.stringify(result));
""",
        encoding="utf-8",
    )
    result = subprocess.run([node, str(harness)], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    values = json.loads(result.stdout)
    assert values["validLocal"] and values["validIntl"]
    assert not values["badPhone"] and not values["longPhone"]
    assert values["digits"] == "digits" and values["long"] == "too_long"
    assert values["progress"] == {"done": 1, "total": 2}
    assert not values["refused"] and values["writes"] == 0 and not values["badJson"]
    assert values["accepted"] and values["roundTrip"] and not values["failedWrite"]
    assert values["cleared"] and values["catalogRetained"]
    assert not values["six181"] and values["six182"] and not values["year364"] and values["year365"] and values["unmarked"] == 0
    assert values["printResult"] and values["during"] == [True, True, "true", True]
    assert values["afterPrint"] == [True, False, False] and values["printed"] == 1
