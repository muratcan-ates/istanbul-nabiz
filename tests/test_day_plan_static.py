from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "nabiz" / "console" / "static"
JS_FILES = (STATIC / "js" / "day_plan.js", STATIC / "js" / "day_plan_view.js")
CSS_FILE = STATIC / "css" / "day_plan.css"

# New pairs stay beside this module until the integrator moves them to the shared catalogs.
CATALOG = {
    "ui.dayplan.title": ("Bir gün planı", "Plan a day"),
    "ui.dayplan.intro": (
        "Kaynakta tarihli etkinlikleri seçin ve gününüzü planlayın.",
        "Choose dated events from the source and plan your day.",
    ),
    "ui.dayplan.date": ("Tarih", "Date"),
    "ui.dayplan.district": ("İlçe", "District"),
    "ui.dayplan.audience": ("Kimle", "Who is going"),
    "ui.dayplan.all": ("Herkes", "Everyone"),
    "ui.dayplan.child": ("Çocukla", "With a child"),
    "ui.dayplan.adult": ("Yetişkin", "Adult"),
    "ui.dayplan.free": ("Yalnız ücretsiz", "Free events only"),
    "ui.dayplan.step_free": ("Basamaksız ulaşım", "Step free travel"),
    "ui.dayplan.age_note": (
        "Yaş aralığı kaynakta yok; kurumun “Çocuklar için” etiketi kullanılır.",
        "The source has no age range; this uses the institution’s “For children” tag.",
    ),
    "ui.dayplan.access_note": ("Mekân erişim bilgisi kaynakta yok.", "The source has no venue access information."),
    "ui.dayplan.show": ("Etkinlikleri göster", "Show events"),
    "ui.dayplan.hidden_title": ("Neden bazı etkinlikler yok?", "Why are some events missing?"),
    "ui.dayplan.all_districts": ("Tümü", "All districts"),
    "ui.dayplan.stale": (
        "Etkinlik listesi {date} tarihinde alındı; güncel olmayabilir. Gitmeden önce etkinlik sayfasını kontrol edin.",
        "The event list was captured on {date} and may be out of date. Check the event page before going.",
    ),
    "ui.dayplan.not_captured": (
        "Kültür AŞ’nin tam etkinlik listesi JavaScript ile yükleniyor; "
        "Nabız yalnız ana sayfadaki tarihli etkinlikleri okuyabildi.",
        "Kultur AŞ loads its full event list with JavaScript; "
        "Nabız could read only dated events on the home page.",
    ),
    "ui.dayplan.source": ("Kaynak: kultur.istanbul · alındı {stamp}", "Source: kultur.istanbul · captured {stamp}"),
    "ui.dayplan.hidden_counts": (
        "Geçmiş: {past}; iptal veya ertelendi: {cancelled}; başlamış: {started}; "
        "tarihsiz: {undated}; tarih çözülemedi: {unparsed}.",
        "Past: {past}; cancelled or postponed: {cancelled}; already started: {started}; "
        "no date: {undated}; date unreadable: {unparsed}.",
    ),
    "ui.dayplan.to": ("Nereye", "To"),
    "ui.dayplan.from": ("Nereden", "From"),
    "ui.dayplan.from_hint": (
        "Semt ya da durak adı yazın; ev adresi yazmayın. Bu cihazda kalır.",
        "Enter a neighborhood or stop; do not enter your home address. This stays on this device.",
    ),
    "ui.dayplan.add_trip": ("Ulaşımı ekle", "Add travel options"),
    "ui.dayplan.gone": (
        "Bu etkinlik artık kaynakta yok ya da bu tarihte sürmüyor; planı kaldırabilirsiniz.",
        "This event is no longer in the source or does not run on this date; you can remove the plan.",
    ),
    "ui.dayplan.refresh_failed": (
        "Etkinlik bilgisi yenilenemedi; bu cihazdaki planınız duruyor.",
        "Event details could not be refreshed; your plan remains on this device.",
    ),
    "ui.dayplan.route_required": ("Çıkış semtinizi veya durağınızı yazın.", "Enter your starting neighborhood or stop."),
    "ui.dayplan.comparing": ("Ulaşım seçenekleri karşılaştırılıyor.", "Comparing travel options."),
    "ui.dayplan.compare_failed": ("Ulaşım karşılaştırması alınamadı.", "Travel options could not be compared."),
    "ui.dayplan.compare_unavailable": (
        "Bu mekân için ulaşım karşılaştırılamadı. Mekânın yakınındaki durağın adını yazarak deneyin.",
        "Travel options could not be compared for this venue. Try the name of a nearby stop.",
    ),
    "ui.dayplan.compare_done": ("Gidiş ve dönüş karşılaştırması eklendi.", "Outbound and return options were added."),
    "ui.dayplan.calendar_error": ("Takvim dosyası indirilemedi.", "The calendar file could not be downloaded."),
    "ui.dayplan.count": ("{count} etkinlik bulundu.", "{count} events found."),
    "ui.dayplan.empty_free": ("Bu tarihte kaynakta ücretsiz etkinlik yok.", "The source has no free events on this date."),
    "ui.dayplan.empty": ("Seçtiğiniz ölçütlerde bu tarihte etkinlik yok.", "No events match your choices on this date."),
    "ui.dayplan.error": (
        "Etkinlikler alınamadı. Bağlantınızı denetleyip yeniden deneyin.",
        "Events could not be loaded. Check your connection and try again.",
    ),
    "ui.dayplan.loading": ("Etkinlikler yükleniyor.", "Loading events."),
    "ui.dayplan.mock": ("Örnek veri kipinde gün planı kapalı.", "The day planner is unavailable in demo mode."),
    "ui.dayplan.no_data": ("Etkinlik verisi henüz yok.", "Event data is not available yet."),
    "ui.dayplan.plan_removed": ("Plan bu cihazdan kaldırıldı.", "The plan was removed from this device."),
    "ui.dayplan.plan_saved": ("Plan bu cihazda kaydedildi.", "The plan was saved on this device."),
    "ui.dayplan.calendar_done": ("Takvim dosyası indirildi.", "The calendar file was downloaded."),
    "ui.dayplan.bus": ("Otobüs", "Bus"),
    "ui.dayplan.calendar": ("Takvime ekle", "Add to calendar"),
    "ui.dayplan.closed_day": ("E30 kaydına göre o gün kapalı.", "The E30 record says it is closed that day."),
    "ui.dayplan.district_missing": ("İlçe kaynakta yok.", "District not in source."),
    "ui.dayplan.district_value": ("İlçe: {district}", "District: {district}"),
    "ui.dayplan.estimate_note": (
        "Süreler bugünkü veriyle tahmindir; plan gününde değişebilir.",
        "Times are estimates from today's data and may change on the plan date.",
    ),
    "ui.dayplan.event_page": ("Etkinlik sayfası (kultur.istanbul)", "Event page (kultur.istanbul)"),
    "ui.dayplan.event_time": ("Saat: {time}", "Time: {time}"),
    "ui.dayplan.from_missing": ("Semt ya da durak yazın.", "Enter a neighborhood or stop."),
    "ui.dayplan.lift_working": ("İBB kaydında arıza yok.", "The İBB record reports no fault."),
    "ui.dayplan.lift_out": ("Asansör arızalı (İBB kaydı).", "The İBB record says the lift is out of service."),
    "ui.dayplan.lift_unknown": ("Asansör durumu doğrulanamadı.", "Lift status could not be verified."),
    "ui.dayplan.make_plan": ("Bununla plan kur", "Plan with this event"),
    "ui.dayplan.metro": ("Metro", "Metro"),
    "ui.dayplan.minutes": ("dk", "min"),
    "ui.dayplan.nearby_empty": (
        "Aynı ilçede o gün açık kayıt bulunamadı.",
        "No same district venues are recorded open that day.",
    ),
    "ui.dayplan.nearby_unknown": (
        "İlçe kaynakta yok; yakındaki kütüphane ve müze önerilemedi.",
        "The source has no district, so nearby libraries and museums could not be suggested.",
    ),
    "ui.dayplan.new_tab": ("Yeni sekmede açılır.", "Opens in a new tab."),
    "ui.dayplan.no_comparison": ("Karşılaştırma yok.", "No comparison available."),
    "ui.dayplan.no_hours": ("Çalışma saati kayıtta yok.", "Opening hours are not in the record."),
    "ui.dayplan.open_all_day": ("Kayda göre o gün 7/24 açık.", "The record says it is open all day."),
    "ui.dayplan.open_hours": (
        "Kayda göre {opens} ile {closes} arası açık.",
        "The record says it is open from {opens} to {closes}.",
    ),
    "ui.dayplan.past_plan": ("Bu planın tarihi geçti.", "This plan date has passed."),
    "ui.dayplan.plan_title": ("Gün planınız", "Your day plan"),
    "ui.dayplan.remove": ("Planı kaldır", "Remove plan"),
    "ui.dayplan.saved": ("Plan tarihi: {date} · Kaydedildi: {saved}", "Plan date: {date} · Saved: {saved}"),
    "ui.dayplan.sold_out": ("Tükendi", "Sold out"),
    "ui.dayplan.step_back": ("Dönüş", "Return"),
    "ui.dayplan.step_event": ("Etkinlik", "Event"),
    "ui.dayplan.step_exit": ("Çıkış", "Start"),
    "ui.dayplan.step_nearby": ("Yakında", "Nearby"),
    "ui.dayplan.step_out": ("Gidiş", "Outbound"),
    "ui.dayplan.ticket_note": (
        "Kayıt ve bilet etkinlik sayfasındadır; Nabız kayıt yapmaz.",
        "Registration and tickets are on the event page; Nabız does not register you.",
    ),
    "ui.dayplan.time_unknown": ("Saat kaynakta yok; etkinlik sayfasına bakın.", "The source has no time; check the event page."),
    "ui.dayplan.venue_missing": ("Mekân kaynakta yok.", "Venue not in source."),
    "ui.dayplan.venue_source": ("İBB Açık Veri · kayıt tarihi {recorded}", "Istanbul Open Data · record date {recorded}"),
    "ui.dayplan.holiday_note": (
        "Resmî tatil ve özel kapanışlar kayıtta yok; gitmeden önce arayın.",
        "Public holidays and special closures are not in the record; call before going.",
    ),
}


def test_day_plan_catalog_pairs_cover_every_new_key() -> None:
    sources = "\n".join(path.read_text(encoding="utf-8") for path in JS_FILES)
    found = set(re.findall(r"['\"](ui\.dayplan\.[^'\"]+)['\"]", sources))
    assert found == set(CATALOG)
    tr = json.loads((STATIC / "i18n" / "tr.json").read_text(encoding="utf-8"))
    en = json.loads((STATIC / "i18n" / "en.json").read_text(encoding="utf-8"))
    fallbacks = {}
    for key, value in re.findall(r"['\"](ui\.dayplan\.[^'\"]+)['\"]\s*,\s*'([^']*)'", sources):
        fallbacks[key] = value
    assert set(fallbacks) == set(CATALOG)
    for key, (turkish, english) in CATALOG.items():
        assert tr.get(key) in (None, turkish)
        assert en.get(key) in (None, english)
        assert fallbacks[key] == turkish


def test_view_is_pure_and_modules_obey_page_rules() -> None:
    view = JS_FILES[1].read_text(encoding="utf-8")
    module = JS_FILES[0].read_text(encoding="utf-8")
    css = CSS_FILE.read_text(encoding="utf-8")
    for forbidden in ("document", "window", "fetch", "localStorage", "Date.now"):
        assert forbidden not in view
    assert "btn-primary" not in module + view
    assert "setInterval" not in module + view
    assert "window.localStorage.getItem" in re.search(r"function readPlan\(\) \{([\s\S]*?)\n\}", module).group(1)
    assert "try" in re.search(r"function readPlan\(\) \{([\s\S]*?)\n\}", module).group(1)
    assert "try" in re.search(r"function savePlan\(plan\) \{([\s\S]*?)\n\}", module).group(1)
    assert "try" in re.search(r"function removePlan\(\) \{([\s\S]*?)\n\}", module).group(1)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css)
    assert not re.search(r"—|–", module + view + css)
    assert not re.search(r"\b(?:ETA|canlı|İBB onaylı)\b", module + view + css, re.IGNORECASE)
    assert not re.search(r"(?:transition|animation)\s*:", css) or "prefers-reduced-motion: no-preference" in css
    assert len(module.splitlines()) <= 260
    assert len(view.splitlines()) <= 280
    assert len(css.splitlines()) <= 160
    assert "external-link" in (STATIC / "icons.svg").read_text(encoding="utf-8")


def test_pure_plan_steps_hide_past_events_and_render_current_plan(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    source = JS_FILES[1].read_text(encoding="utf-8")
    harness = """
const t = (_key, fallback, vars = {}) => fallback.replace(/\\{(\\w+)\\}/g, (_, key) => vars[key] ?? `{${key}}`);
const plan = {date:'2026-10-03', event:{date_text:'03-10-2026',time:'15:00',venue:'Örnek Sahne',district:null},
  trip:{out:[],back:[]}, nearby:[], venue_hours:null};
console.log(JSON.stringify({past:planSteps(plan,'tr',t,'2026-10-04'), steps:planSteps(plan,'tr',t,'2026-09-27')}));
"""
    script = tmp_path / "day_plan_view_check.mjs"
    script.write_text(source + "\n" + harness, encoding="utf-8")
    result = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=30, check=True)
    output = json.loads(result.stdout)
    assert output["past"] == []
    assert [step["label"] for step in output["steps"]] == ["Çıkış", "Gidiş", "Etkinlik", "Yakında", "Dönüş"]
