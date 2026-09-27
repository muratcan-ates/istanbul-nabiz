"""Browser-module contracts, bilingual key coverage and styling limits for E77."""

from __future__ import annotations

import json
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "nabiz" / "console" / "static"
JS = STATIC / "js" / "console_scenario.js"
CSS = STATIC / "css" / "console_scenario.css"

CATALOG = {
    "tr": {
        "ui.scn.assume.hypothetical": "Kapanış bir varsayımdır; İBB kaydına eklenmez ve kimseye bildirilmez.",
        "ui.scn.assume.endpoints": (
            "Asansör yalnız binilen, inilen ve aktarma yapılan istasyonlarda sayılır; trenle geçilen istasyon etkilenmez."
        ),
        "ui.scn.assume.record": "Önce ve senaryo hesabı aynı İBB kaydıyla yapılır.",
        "ui.scn.assume.traffic": "Sayılar güzergâh ve kayıt sayısıdır; yolcu, kalabalık ya da talep tahmini değildir.",
        "ui.scn.assume.times": "Ek süreler istasyon mesafesi modelinden gelir; tarife içermez.",
        "ui.scn.assume.saved": (
            "Yalnız hesabıyla ve rızasıyla sunucuda kaydedilmiş yolculuklar sayılır; cihazdaki kayıtlar görünmez."
        ),
        "ui.scn.assume.small": "3’ten az kayıt içeren sayılar gizlenir.",
        "ui.scn.routes.limit": "En çok 12 güzergâh yazın.",
        "ui.scn.routes.format": "Güzergâhı Başlangıç > Varış biçiminde yazın.",
        "ui.scn.summary": (
            "Senaryo: {station} istasyonunda asansör kapalı (varsayım). {total} güzergâhın "
            "{affected} tanesi etkilenir; {blocked} güzergâhta adımsız yol kalmaz, {detour} alternatifle sürer."
        ),
        "ui.scn.effect.blocked": "Adımsız yol kalmaz",
        "ui.scn.effect.detour": "Alternatifle sürer",
        "ui.scn.effect.none": "Etkilenmiyor",
        "ui.scn.effect.before": "Senaryodan önce de yok",
        "ui.scn.effect.unknown": "Doğrulanamadı",
        "ui.scn.effect.invalid": "Geçersiz güzergâh",
        "ui.scn.after.detour": "{station} üzerinden",
        "ui.scn.after.minutes": "yaklaşık {minutes} dk ek",
        "ui.scn.before.available": "adımsız yol var",
        "ui.scn.before.unavailable": "adımsız yol yok",
        "ui.scn.before.unknown": "doğrulanamadı",
        "ui.scn.saved.missing": "Kayıtlı yolculuk modülü bu sunucuda yok.",
        "ui.scn.saved.no_table": "Bu sunucuda kayıtlı yolculuk tablosu yok.",
        "ui.scn.saved.consent": "Kayıtlı yolculuk rızası bu kullanımı henüz kapsamıyor.",
        "ui.scn.saved.not_counted": "Kayıtlı yolculuklar bu senaryoda sayılmadı.",
        "ui.scn.saved.lt3": "3’ten az kayıt etkileniyor.",
        "ui.scn.saved.count": "{count} kayıt etkileniyor.",
        "ui.scn.sample": "Örnek",
        "ui.scn.col.before": "Önce",
        "ui.scn.col.after": "Senaryoda",
        "ui.scn.col.effect": "Durum",
        "ui.scn.source.stamp": "Kayıtlı · {time}",
        "ui.scn.source.unknown": "Kayıt zamanı doğrulanamadı.",
        "ui.scn.source.open": "İBB kaydını aç",
        "ui.scn.saved.note": (
            "Yalnız bu sunucuda hesabıyla ve rızasıyla kaydedilmiş yolculuklar sayılır; "
            "cihazda tutulan kayıtlar görünmez. Bu sayı kişi sayısı değildir."
        ),
        "ui.scn.special.title": "Doğrulanamayan veya senaryodan önce de olmayan güzergâhlar ({count})",
        "ui.scn.special.caption": "Güzergâh durumu",
        "ui.scn.col.route": "Güzergâh",
        "ui.scn.unaffected.count": "{count} güzergâh etkilenmiyor.",
        "ui.scn.unaffected.more": "Etkilenmeyen güzergâhlar ({count})",
        "ui.scn.closure.faulty": "Bu istasyon İBB kaydında zaten arızalı; senaryo bugünkü durumu gösterir.",
        "ui.scn.closure.no_lift": "İBB kaydında bu istasyon için asansör bilgisi yok; senaryo anlamlı değil.",
        "ui.scn.assumptions": "Varsayımlar",
        "ui.scn.affected.caption": "Etkilenen güzergâhlar",
        "ui.scn.none.affected": "Etkilenen güzergâh yok.",
        "ui.scn.source.label": "İBB metro arızalı ekipman kaydı",
        "ui.scn.model.label": "İstasyon ve süre modeli: Nabız planlayıcısı (tahmin, tarife değil).",
        "ui.scn.how.title": "Nasıl hesaplandı?",
        "ui.scn.how.max": "Operatör en çok 12 güzergâh girebilir.",
        "ui.scn.how.minimum": "3’ten az kayıt içeren toplamlar gizlenir.",
        "ui.scn.how.endpoints": "Asansörler yalnız binilen, inilen ve aktarma istasyonlarında denetlenir.",
        "ui.scn.all_lines": "Tüm hatlar",
        "ui.scn.saved.at": "hesaplandı · {time}",
        "ui.scn.saved.affected": "{count} etkilenen",
        "ui.scn.open": "Aç",
        "ui.scn.delete": "Sil",
        "ui.scn.saved.title": "Kaydedilen senaryolar",
        "ui.scn.saved.empty": "Henüz kaydedilen senaryo yok.",
        "ui.scn.mock": "Örnek veri modunda senaryo hesaplanmaz.",
        "ui.scn.title": "Müdahale senaryosu",
        "ui.scn.description": (
            "Bir istasyonun asansörü kapanırsa hangi güzergâhların adımsız yolu değişir? "
            "Varsayımsal hesaptır; yolcu ya da trafik tahmini değildir."
        ),
        "ui.scn.disclaimer": "Nabız simüle operatör aracı; resmî İBB planlama aracı değildir.",
        "ui.scn.station": "İstasyon",
        "ui.scn.line": "Hat",
        "ui.scn.routes": "Güzergâhlar",
        "ui.scn.routes.hint": "Her satıra bir güzergâh: Başlangıç > Varış (en çok 12)",
        "ui.scn.saved.toggle": "Kayıtlı yolculukları da say (yalnız toplam sayı)",
        "ui.scn.calculate": "Senaryoyu hesapla",
        "ui.scn.sample.fill": "Örnek listeyi doldur",
        "ui.scn.saved.opened": "Kayıtlı sonuç: {time}. İBB kaydı o andaki haliyle.",
        "ui.scn.routes.required": "En az bir güzergâh yazın.",
        "ui.scn.loading": "Senaryo hesaplanıyor.",
        "ui.scn.stations.loading": "İstasyonlar yükleniyor.",
        "ui.scn.done": "Senaryo kaydedildi.",
    },
    "en": {
        "ui.scn.assume.hypothetical": "The closure is hypothetical; it is not added to the İBB record or sent to anyone.",
        "ui.scn.assume.endpoints": (
            "Lifts are checked only at boarding, exit, transfer and walking endpoints; stations passed by train are not checked."
        ),
        "ui.scn.assume.record": "The before and scenario runs use the same İBB record.",
        "ui.scn.assume.traffic": "Counts are routes and records; they are not estimates of passengers, crowding or demand.",
        "ui.scn.assume.times": "Extra time comes from the station distance model and is not a timetable.",
        "ui.scn.assume.saved": (
            "Only journeys saved on this server with an account and consent are counted; device-only records are not visible."
        ),
        "ui.scn.assume.small": "Counts below 3 records are hidden.",
        "ui.scn.routes.limit": "Enter no more than 12 routes.",
        "ui.scn.routes.format": "Enter a route as Origin > Destination.",
        "ui.scn.summary": (
            "Scenario: the lift at {station} station is closed (hypothetical). "
            "{affected} of {total} routes are affected; {blocked} lose their step-free route and "
            "{detour} continue by an alternative."
        ),
        "ui.scn.effect.blocked": "No step-free route remains",
        "ui.scn.effect.detour": "Continues by an alternative",
        "ui.scn.effect.none": "Unaffected",
        "ui.scn.effect.before": "Unavailable before the scenario",
        "ui.scn.effect.unknown": "Unverified",
        "ui.scn.effect.invalid": "Invalid route",
        "ui.scn.after.detour": "via {station}",
        "ui.scn.after.minutes": "about {minutes} min extra",
        "ui.scn.before.available": "step-free route available",
        "ui.scn.before.unavailable": "no step-free route",
        "ui.scn.before.unknown": "unverified",
        "ui.scn.saved.missing": "The saved journey module is not on this server.",
        "ui.scn.saved.no_table": "There is no saved journey table on this server.",
        "ui.scn.saved.consent": "Saved journey consent does not yet cover this use.",
        "ui.scn.saved.not_counted": "Saved journeys were not counted in this scenario.",
        "ui.scn.saved.lt3": "Fewer than 3 records are affected.",
        "ui.scn.saved.count": "{count} records are affected.",
        "ui.scn.sample": "Example",
        "ui.scn.col.before": "Before",
        "ui.scn.col.after": "In the scenario",
        "ui.scn.col.effect": "Status",
        "ui.scn.source.stamp": "Recorded · {time}",
        "ui.scn.source.unknown": "Record time could not be verified.",
        "ui.scn.source.open": "Open the İBB record",
        "ui.scn.saved.note": (
            "Only journeys saved on this server with an account and consent are counted; "
            "device-only records are not visible. This is not a count of people."
        ),
        "ui.scn.special.title": "Unverified or already unavailable routes ({count})",
        "ui.scn.special.caption": "Route status",
        "ui.scn.col.route": "Route",
        "ui.scn.unaffected.count": "{count} routes are unaffected.",
        "ui.scn.unaffected.more": "Unaffected routes ({count})",
        "ui.scn.closure.faulty": "The İBB record already lists a fault at this station; the scenario shows the current record.",
        "ui.scn.closure.no_lift": "The İBB record has no lift information for this station; this scenario is not meaningful.",
        "ui.scn.assumptions": "Assumptions",
        "ui.scn.affected.caption": "Affected routes",
        "ui.scn.none.affected": "No affected routes.",
        "ui.scn.source.label": "İBB metro faulty equipment record",
        "ui.scn.model.label": "Station and time model: Nabız planner (estimate, not a timetable).",
        "ui.scn.how.title": "How was this calculated?",
        "ui.scn.how.max": "Operators can enter up to 12 routes.",
        "ui.scn.how.minimum": "Totals below 3 records are hidden.",
        "ui.scn.how.endpoints": "Lifts are checked only at boarding, exit and transfer stations.",
        "ui.scn.all_lines": "All lines",
        "ui.scn.saved.at": "computed · {time}",
        "ui.scn.saved.affected": "{count} affected",
        "ui.scn.open": "Open",
        "ui.scn.delete": "Delete",
        "ui.scn.saved.title": "Saved scenarios",
        "ui.scn.saved.empty": "No scenarios have been saved yet.",
        "ui.scn.mock": "Scenarios cannot be calculated in sample data mode.",
        "ui.scn.title": "Intervention scenario",
        "ui.scn.description": (
            "If a station lift closes, which routes lose their step-free path? "
            "This is hypothetical, not a passenger or traffic estimate."
        ),
        "ui.scn.disclaimer": "Nabız simulated operator tool; not an official İBB planning tool.",
        "ui.scn.station": "Station",
        "ui.scn.line": "Line",
        "ui.scn.routes": "Routes",
        "ui.scn.routes.hint": "One route per line: Origin > Destination (up to 12)",
        "ui.scn.saved.toggle": "Count saved journeys too (totals only)",
        "ui.scn.calculate": "Calculate scenario",
        "ui.scn.sample.fill": "Fill example routes",
        "ui.scn.saved.opened": "Saved result: {time}. The İBB record as it was then.",
        "ui.scn.routes.required": "Enter at least one route.",
        "ui.scn.loading": "Calculating scenario.",
        "ui.scn.stations.loading": "Loading stations.",
        "ui.scn.done": "Scenario saved.",
    },
}


def test_domless_module_import_and_pure_helpers(tmp_path: pathlib.Path) -> None:
    source = json.dumps(JS.as_uri())
    format_url = json.dumps((STATIC / "js" / "format.js").as_uri())
    script = f"""
globalThis.window = {{ location: {{ search: '', origin: 'http://localhost' }} }};
const mod = await import({source});
const format = await import({format_url});
console.log(JSON.stringify({{
  hasDocument: typeof document,
  parsed: mod.parseRoutes('A > B\\n\\nC > D'),
  tooMany: mod.parseRoutes(Array(13).fill('A > B').join('\\n')).errors.length,
  malformed: mod.parseRoutes('A to B').errors.length,
  tones: ['blocked','detour','not_affected','already_unavailable','unverified'].map((effect) => mod.rowModel({{effect}}).tone),
  small: mod.savedLine('lt3'),
  assumptions: mod.assumptionLines(['hypothetical','not_traffic']).length,
  escaped: format.esc('<b>')
}}));
"""
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, text=True, capture_output=True, check=True)
    body = json.loads(result.stdout)
    assert body["hasDocument"] == "undefined"
    assert body["parsed"]["routes"] == ["A > B", "C > D"] and not body["parsed"]["errors"]
    assert body["tooMany"] == 1 and body["malformed"] == 1
    assert body["tones"] == ["warn", "accent", "quiet", "quiet", "quiet"]
    assert body["small"] == "3’ten az kayıt etkileniyor."
    assert body["assumptions"] == 2 and body["escaped"] == "&lt;b&gt;"


def test_catalog_keys_match_module_and_fallbacks_without_bare_turkish() -> None:
    js = JS.read_text(encoding="utf-8")
    keys = set(re.findall(r"['\"](ui\.scn\.[^'\"]+)['\"]", js))
    assert keys == set(CATALOG["tr"]) == set(CATALOG["en"])
    fallbacks = {
        match.group(1): match.group(2) for match in re.finditer(r"['\"](ui\.scn\.[^'\"]+)['\"]\s*,\s*['\"]([^'\"]*)['\"]", js)
    }
    for key, value in fallbacks.items():
        assert CATALOG["tr"][key] == value
        assert set(re.findall(r"\{(\w+)\}", CATALOG["tr"][key])) == set(re.findall(r"\{(\w+)\}", CATALOG["en"][key]))
    turkish_values = set(CATALOG["tr"].values())
    route_data = {"Zeytinburnu > Bağcılar", "Bostancı > Kartal", "Maltepe > Pendik"}
    literals = re.findall(r"['\"]([^'\"\n]*)['\"]", js)
    assert all(not re.search(r"[çğıöşüİıÇĞÖŞÜ]", value) or value in turkish_values or value in route_data for value in literals)


def test_styles_and_mounting_stay_inside_console_boundaries() -> None:
    js = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    assert len(js.splitlines()) <= 300 and len(css.splitlines()) <= 350
    assert "setInterval" not in js and "scroll" not in js and "canlı" not in js
    assert "yolcu sayısı" not in js and "tahmin ediyoruz" not in js
    assert "infinite" not in css and "is-bad" not in css
    assert not re.search(r"#[0-9a-fA-F]{3,8}|\b(?:rgb|rgba|hsl|hsla)\s*\(", css)
    for match in re.finditer(r"(?m)^\s*(?:transition|animation)\s*:", css):
        assert "@media (prefers-reduced-motion: no-preference)" in css[: match.start()]
    for path in (STATIC / "sw.js", STATIC / "index.html", STATIC / "kolay.html", ROOT / "src/nabiz/web/static/index.html"):
        assert "console_scenario" not in path.read_text(encoding="utf-8")
    console = (STATIC / "console.html").read_text(encoding="utf-8")
    assert 'id="citizen-requests"' in console
    assert 'id="scenario-mount"' in console and js.index("'scenario-mount'") < js.index("'citizen-requests'")  # P00 G3
    checked = subprocess.run(["node", "--check", str(JS)], cwd=ROOT, text=True, capture_output=True)
    assert checked.returncode == 0, checked.stderr
