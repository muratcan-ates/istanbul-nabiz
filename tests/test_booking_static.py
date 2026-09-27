from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import REPO_ROOT
from test_i18n_surfaces import TURKISH_CHARS, UI_CALL, UI_KEY, catalog, js_fallback, template_literals

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
BOOKING_JS = STATIC / "js" / "booking.js"
BOOKING_CSS = STATIC / "css" / "booking.css"

CATALOG = {
    "tr": {
        "ui.booking.open": "Randevu al (örnek)",
        "ui.booking.title": "Kütüphane randevusu (örnek)",
        "ui.booking.notice": "Örnek: İBB kütüphane randevu sistemine bağlı değildir.",
        "ui.booking.room_note": (
            "Salon planı ve kapasite örnektir; kütüphanenin gerçek doluluğunu göstermez. "
            "Dolu koltuklar yalnız Nabız'da alınan örnek randevulardır."
        ),
        "ui.booking.hours": "Kayıtlı çalışma saati",
        "ui.booking.day_legend": "Gün",
        "ui.booking.today": "Bugün",
        "ui.booking.tomorrow": "Yarın",
        "ui.booking.day0": "Pzt",
        "ui.booking.day1": "Sal",
        "ui.booking.day2": "Çar",
        "ui.booking.day3": "Per",
        "ui.booking.day4": "Cum",
        "ui.booking.day5": "Cmt",
        "ui.booking.day6": "Paz",
        "ui.booking.day_label": "{day} {date}",
        "ui.booking.closed": "{day} · kayda göre kapalı",
        "ui.booking.no_slots_left": "{day} · bugün için saat kalmadı",
        "ui.booking.slot_legend": "Saat aralığı",
        "ui.booking.none": "Önümüzdeki 7 günde seçilebilir saat yok.",
        "ui.booking.room": "Çalışma salonu (örnek)",
        "ui.booking.seat_legend": "Koltuk seçin: {room}, {capacity} koltuk",
        "ui.booking.entrance": "Giriş",
        "ui.booking.row": "{row} sırası",
        "ui.booking.seat_free": "{row} sırası, {number} numaralı koltuk, boş",
        "ui.booking.seat_taken": "{row} sırası, {number} numaralı koltuk, dolu",
        "ui.booking.seat_mine": "{row} sırası, {number} numaralı koltuk, sizin randevunuz",
        "ui.booking.seat_selected": "{row} sırası, {number} numaralı koltuk, seçtiğiniz",
        "ui.booking.seat_accessible": "erişilebilir masa",
        "ui.booking.legend_free": "Boş",
        "ui.booking.legend_taken": "Dolu (Nabız'da ayrılmış)",
        "ui.booking.legend_selected": "Seçtiğiniz",
        "ui.booking.legend_accessible": "Erişilebilir masa",
        "ui.booking.loading": "Koltuklar yükleniyor.",
        "ui.booking.loading_library": "Kayıtlar yükleniyor.",
        "ui.booking.pick_seat": "Bir koltuk seçin.",
        "ui.booking.consent": (
            "Kütüphane, gün, saat ve koltuk seçimimin, bu cihazın ya da örnek hesabımın kodunun özetiyle birlikte "
            "Nabız sunucusunda en çok 30 gün saklanmasını kabul ediyorum. Ad, telefon ve TC kimlik istenmez; "
            "iptal ettiğimde kayıt hemen silinir."
        ),
        "ui.booking.consent_more": "Ne saklanır?",
        "ui.booking.consent_detail": (
            "Saklanan: kütüphane, gün, saat aralığı, koltuk, randevu kodu, onay sürümü ve cihaz kodunuzun "
            "ya da örnek hesabınızın tuzlu özeti. İBB'ye ya da kütüphaneye gönderilmez."
        ),
        "ui.booking.consent_error": "Randevu için onay kutusunu işaretleyin.",
        "ui.booking.submit": "Randevuyu al",
        "ui.booking.close": "Vazgeç",
        "ui.booking.busy": "Randevu kaydediliyor.",
        "ui.booking.done_title": "Randevunuz alındı (örnek)",
        "ui.booking.done_line": "{library} · {day} {slot} · koltuk {seat}",
        "ui.booking.code": "Randevu kodu: {code}",
        "ui.booking.held_device": "Bu randevu bu cihaza bağlı.",
        "ui.booking.held_account": "Bu randevu örnek hesabınıza bağlı.",
        "ui.booking.ttl": "Kayıt 30 gün sonra kendiliğinden silinir; kütüphane bu randevuyu görmez.",
        "ui.booking.has_booking": "Bu saatte randevunuz var: koltuk {seat}.",
        "ui.booking.ok": "Tamam",
        "ui.booking.cancel": "Randevuyu iptal et",
        "ui.booking.cancel_confirm": "Randevu iptal edilsin mi? Koltuk yeniden boş olur.",
        "ui.booking.cancel_yes": "Evet, iptal et",
        "ui.booking.cancel_no": "Vazgeç",
        "ui.booking.cancelled": "Randevu iptal edildi; kayıt silindi.",
        "ui.booking.cancelled_title": "Randevunuz iptal edildi (örnek)",
        "ui.booking.err_seat_taken": "Bu koltuk az önce ayrıldı; başka bir koltuk seçin.",
        "ui.booking.err_slot_held": "Bu saat aralığında zaten bir randevunuz var.",
        "ui.booking.err_active_limit": "En çok {limit} yaklaşan randevunuz olabilir; önce birini iptal edin.",
        "ui.booking.err_bad_seat": "Seçtiğiniz koltuk örnek salon planında yok.",
        "ui.booking.err_too_many": "Bu saat içinde çok deneme oldu; biraz sonra tekrar deneyin.",
        "ui.booking.err_no_holder": "Bu tarayıcı cihaz kodunu saklayamıyor (gizli pencere olabilir); randevu alınamıyor.",
        "ui.booking.err_not_offered": "Bu gün ya da saat artık seçilemiyor; liste yenilendi.",
        "ui.booking.err_offline": "Sunucuya ulaşılamadı; bağlantınızı kontrol edip tekrar deneyin.",
        "ui.booking.err_failed": "Randevu kaydedilemedi: {message}",
        "ui.booking.retry": "Tekrar deneyin.",
    },
    "en": {
        "ui.booking.open": "Book a seat (example)",
        "ui.booking.title": "Library booking (example)",
        "ui.booking.notice": "Example: not connected to İBB's library booking system.",
        "ui.booking.room_note": (
            "The room plan and capacity are an example and do not show the library's real occupancy. "
            "Taken seats are only example bookings made in Nabız."
        ),
        "ui.booking.hours": "Recorded opening hours",
        "ui.booking.day_legend": "Day",
        "ui.booking.today": "Today",
        "ui.booking.tomorrow": "Tomorrow",
        "ui.booking.day0": "Mon",
        "ui.booking.day1": "Tue",
        "ui.booking.day2": "Wed",
        "ui.booking.day3": "Thu",
        "ui.booking.day4": "Fri",
        "ui.booking.day5": "Sat",
        "ui.booking.day6": "Sun",
        "ui.booking.day_label": "{day} {date}",
        "ui.booking.closed": "{day} · closed by the record",
        "ui.booking.no_slots_left": "{day} · no times left today",
        "ui.booking.slot_legend": "Time",
        "ui.booking.none": "No bookable time in the next 7 days.",
        "ui.booking.room": "Study room (example)",
        "ui.booking.seat_legend": "Choose a seat: {room}, {capacity} seats",
        "ui.booking.entrance": "Entrance",
        "ui.booking.row": "Row {row}",
        "ui.booking.seat_free": "Row {row}, seat {number}, free",
        "ui.booking.seat_taken": "Row {row}, seat {number}, taken",
        "ui.booking.seat_mine": "Row {row}, seat {number}, your booking",
        "ui.booking.seat_selected": "Row {row}, seat {number}, selected",
        "ui.booking.seat_accessible": "accessible desk",
        "ui.booking.legend_free": "Free",
        "ui.booking.legend_taken": "Taken (booked in Nabız)",
        "ui.booking.legend_selected": "Your choice",
        "ui.booking.legend_accessible": "Accessible desk",
        "ui.booking.loading": "Loading seats.",
        "ui.booking.loading_library": "Loading library details.",
        "ui.booking.pick_seat": "Choose a seat.",
        "ui.booking.consent": (
            "I agree that my library, day, time and seat choice is kept on the Nabız server for at most 30 days, "
            "with a digest of this device's or my example account's code. No name, phone or ID number is asked; "
            "when I cancel, the record is deleted at once."
        ),
        "ui.booking.consent_more": "What is kept?",
        "ui.booking.consent_detail": (
            "Kept: library, day, time, seat, booking code, consent version and a salted digest of your device code "
            "or example account. Nothing is sent to İBB or the library."
        ),
        "ui.booking.consent_error": "Tick the consent box to book.",
        "ui.booking.submit": "Book this seat",
        "ui.booking.close": "Close",
        "ui.booking.busy": "Saving the booking.",
        "ui.booking.done_title": "Your seat is booked (example)",
        "ui.booking.done_line": "{library} · {day} {slot} · seat {seat}",
        "ui.booking.code": "Booking code: {code}",
        "ui.booking.held_device": "This booking is tied to this device.",
        "ui.booking.held_account": "This booking is tied to your example account.",
        "ui.booking.ttl": "The record is deleted after 30 days; the library does not see this booking.",
        "ui.booking.has_booking": "You have a booking at this time: seat {seat}.",
        "ui.booking.ok": "Done",
        "ui.booking.cancel": "Cancel this booking",
        "ui.booking.cancel_confirm": "Cancel this booking? The seat becomes free again.",
        "ui.booking.cancel_yes": "Yes, cancel it",
        "ui.booking.cancel_no": "Keep it",
        "ui.booking.cancelled": "Booking cancelled; the record is deleted.",
        "ui.booking.cancelled_title": "Your booking was cancelled (example)",
        "ui.booking.err_seat_taken": "This seat was just booked; please choose another.",
        "ui.booking.err_slot_held": "You already have a booking at this time.",
        "ui.booking.err_active_limit": "You can hold at most {limit} upcoming bookings; cancel one first.",
        "ui.booking.err_bad_seat": "That seat is not in the example room plan.",
        "ui.booking.err_too_many": "Too many tries this hour; please try again later.",
        "ui.booking.err_no_holder": "This browser cannot keep a device code (a private window?); booking is not possible.",
        "ui.booking.err_not_offered": "That day or time can no longer be chosen; the list was refreshed.",
        "ui.booking.err_offline": "The server could not be reached; check your connection and try again.",
        "ui.booking.err_failed": "The booking could not be saved: {message}",
        "ui.booking.retry": "Try again.",
    },
}


def test_catalog_matches_every_booking_fallback_and_has_equal_placeholders() -> None:
    source = BOOKING_JS.read_text(encoding="utf-8")
    calls = {key: js_fallback(fallback) for _, key, _, fallback in UI_CALL.findall(source) if key.startswith("ui.booking.")}
    keys = {key for _, key in UI_KEY.findall(source) if key.startswith("ui.booking.")}
    assert keys == set(CATALOG["tr"]) == set(CATALOG["en"]) == set(calls)
    assert calls == CATALOG["tr"]
    for key, value in CATALOG["tr"].items():
        assert set(re.findall(r"\{(\w+)\}", value)) == set(re.findall(r"\{(\w+)\}", CATALOG["en"][key]))
        assert value.strip() and "—" not in value and "–" not in value and "canlı" not in value.lower()
    for lang in ("tr", "en"):  # P00 G4: the keys moved into the page catalogues, unchanged
        assert all(catalog(lang)[k] == v for k, v in CATALOG[lang].items())
    tr = catalog("tr")
    culture_calls = {
        key: js_fallback(fallback)
        for _, key, _, fallback in UI_CALL.findall(source)
        if key.startswith("ui.culture.")
    }
    assert {key: tr[key] for key in culture_calls} == culture_calls


def test_booking_surface_has_no_untranslated_turkish_or_template_copy() -> None:
    source = BOOKING_JS.read_text(encoding="utf-8")
    clean = re.sub(r"/\*.*?\*/|^\s*//.*$", "", source, flags=re.S | re.M)
    fallback_spans = [match.span(4) for match in UI_CALL.finditer(clean)]
    literal_source = list(clean)
    for start, end, chunks in template_literals(clean):
        for chunk in chunks:
            assert not TURKISH_CHARS.search(chunk), ("booking.js", chunk)
        literal_source[start:end] = [" "] * (end - start)
    quoted = re.compile(r"'((?:\\.|[^'\\])*)'|\"((?:\\.|[^\"\\])*)\"", re.S)
    for match in quoted.finditer("".join(literal_source)):
        group = 1 if match.group(1) is not None else 2
        value = match.group(group)
        start, end = match.span(group)
        if TURKISH_CHARS.search(value):
            assert any(left <= start and end <= right for left, right in fallback_spans), value


def test_booking_js_contracts_and_small_dom_import(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    checked = subprocess.run([node, "--check", str(BOOKING_JS)], capture_output=True, text=True, timeout=60)
    assert checked.returncode == 0, checked.stderr
    source = BOOKING_JS.read_text(encoding="utf-8")
    assert source.rstrip().splitlines()[-1] == "if (typeof document !== 'undefined') mountBooking(document);"
    assert "setInterval" not in source and "localStorage.setItem" not in source and "addEventListener('scroll'" not in source
    assert "document.body" not in source and "observer.observe(list, { childList: true, subtree: false })" in source
    assert "deviceId" in source and "readAccount" in source and source.count("/css/booking.css") == 1
    assert "fetch('/api/booking" in source or "api('/api/booking" in source
    harness = tmp_path / "booking_harness.mjs"
    harness.write_text(
        "globalThis.window={location:{search:'?mock=0'}}; let calls=0;"
        "globalThis.fetch=()=>{calls+=1;throw new Error('unexpected')};"
        f"const i18n=await import({json.dumps((STATIC / 'js' / 'i18n_text.js').as_uri())});"
        f"const booking=await import({json.dumps(BOOKING_JS.as_uri())});"
        "booking.mountBooking({querySelector(){return null}});"
        "const room={name:'Study room (example)',rows:'ABCDEF',seats_per_row:6,aisle_after:3,accessible:['A1','A2'],capacity:36};"
        f"i18n.setCatalogs('tr',{json.dumps(CATALOG['tr'], ensure_ascii=False)},{json.dumps(CATALOG['tr'], ensure_ascii=False)});"
        "const html=booking.seatMapMarkup(room,['B4'],null,'C3');"
        "const tr=[booking.hhmm(540,'tr'),booking.slotText({start:540,end:660},'tr')];"
        "const map=[(html.match(/type=\\\"radio\\\"/g)||[]).length,(html.match(/role=\\\"group\\\"/g)||[]).length,"
        "html.includes('B4')&&html.includes('disabled'),html.includes('erişilebilir masa')];"
        f"i18n.setCatalogs('en',{json.dumps(CATALOG['en'], ensure_ascii=False)},{json.dumps(CATALOG['tr'], ensure_ascii=False)});"
        "const en=[booking.hhmm(1440,'en'),booking.seatLabel('A1','free',true),booking.errorText('seat_taken')];"
        "console.log(JSON.stringify({calls,tr,map,en}));",
        encoding="utf-8",
    )
    result = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["calls"] == 0
    assert output["tr"] == ["09.00", "09.00-11.00"]
    assert output["map"] == [36, 6, True, True]
    assert output["en"][0] == "24:00" and "Row A" in output["en"][1] and "This seat" in output["en"][2]
    assert not TURKISH_CHARS.search(json.dumps(output["en"], ensure_ascii=False))


def test_booking_css_is_token_scoped_and_has_no_motion_or_private_colours() -> None:
    css = BOOKING_CSS.read_text(encoding="utf-8")
    assert "--tap" in css and "--bad" not in css and "backdrop-filter" not in css
    assert not re.search(r"\b(?:transition|animation)\s*:", css)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(", css)
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for selector in re.findall(r"([^{}]+)\{", stripped):
        if selector.strip().startswith("@"):
            continue
        for part in selector.split(","):
            assert part.strip().startswith((".booking", "#randevu")), part
    assert "var(--text-muted) 0 1px, transparent 1px 6px" in css
    assert ".booking-seat.is-taken .booking-seat-face > span" in css
    assert "background: var(--surface-raised); color: var(--text)" in css
    assert "@media (max-width: 480px)" in css and "@media (forced-colors: active)" in css
