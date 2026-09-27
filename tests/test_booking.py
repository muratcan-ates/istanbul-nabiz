from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

import pytest
from conftest import REPO_ROOT

from nabiz.console import culture_api
from nabiz.console.accounts import ConsentRequired
from nabiz.console.booking import (
    ActiveLimit,
    BadSeat,
    BookingStore,
    Library,
    NotOffered,
    SeatTaken,
    Slot,
    SlotHeld,
    bookable_libraries,
    check_choice,
    day_plan,
    library_key,
    seat_ids,
    slots_for,
)
from nabiz.console.cards import display_text
from nexus_core.stats import ISTANBUL

DATA = REPO_ROOT / "data" / "reference" / "ibb_kultur"
NOW = dt.datetime(2026, 9, 29, 8, 0, tzinfo=ISTANBUL)


def example_library(
    *, days: frozenset[int] = frozenset(range(7)), hours: tuple[dt.time, dt.time] | str = (dt.time(9), dt.time(17))
) -> Library:
    return Library("deneme-kutuphanesi", "Deneme Kütüphanesi", "Kadıköy", days, hours, "09:00-17:00", "Hergün")  # type: ignore[arg-type]


def test_slots_are_two_hours_with_a_final_hour_or_more() -> None:
    assert slots_for((dt.time(9), dt.time(17))) == (Slot(540, 660), Slot(660, 780), Slot(780, 900), Slot(900, 1020))
    assert slots_for((dt.time(10), dt.time(19))) == (
        Slot(600, 720), Slot(720, 840), Slot(840, 960), Slot(960, 1080), Slot(1080, 1140)
    )
    assert slots_for((dt.time(9), dt.time(11, 30))) == (Slot(540, 660),)
    all_day = slots_for("always")
    assert len(all_day) == 12 and all_day[-1].end == 1440


def test_day_plan_uses_istanbul_date_and_hides_elapsed_times() -> None:
    plan = day_plan(example_library(hours=(dt.time(9), dt.time(21))), dt.datetime(2026, 9, 29, 21, 30, tzinfo=ISTANBUL))
    assert plan[0].reason == "no_slots_left" and not any(slot["bookable"] for slot in plan[0].slots)
    assert len([slot for slot in plan[1].slots if slot["bookable"]]) == 6
    weekday = day_plan(example_library(days=frozenset(range(5))), NOW)
    assert [day.reason for day in weekday[4:6]] == ["closed", "closed"]
    sunday_closed = day_plan(example_library(days=frozenset(range(1, 7))), dt.datetime(2026, 9, 28, 8, tzinfo=ISTANBUL))
    assert sunday_closed[0].reason == "closed"
    naive = day_plan(example_library(), dt.datetime(2026, 9, 29, 8))
    assert naive[0].date == "2026-09-29"


def test_real_recorded_libraries_are_unique_and_only_scheduled_libraries_are_bookable() -> None:
    culture_api.load_venues.cache_clear()
    venues, _ = culture_api.load_venues(DATA)
    keys = []
    eligible = 0
    for venue in venues:
        if venue.kind != "library" or not venue.district:
            continue
        days = culture_api.parse_days(venue.days_text)
        hours = culture_api.parse_hours(venue.hours_text) or culture_api.parse_hours(venue.days_text)
        if hours == "always":
            days = frozenset(range(7))
        if days is not None and hours is not None and venue.hours_text and venue.days_text:
            eligible += 1
            district = culture_api.district_name(venue.district)
            keys.append(library_key(display_text(district), display_text(venue.name)))
    libraries = bookable_libraries(DATA)
    museum_keys = {
        library_key(display_text(culture_api.district_name(item.district)), display_text(item.name))
        for item in venues if item.kind == "museum" and item.district
    }
    assert len(libraries) == eligible == len(keys)
    assert len(keys) == len(set(keys))
    assert len(libraries) < sum(item.kind == "library" for item in venues)
    assert set(libraries).isdisjoint(museum_keys)
    assert all(
        item.name == display_text(item.name) and item.district == display_text(item.district)
        for item in libraries.values()
    )


def test_bookable_catalog_reads_current_directory_and_excludes_museums(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def capture(stem: str, name_field: str, rows: list[dict[str, str | None]]) -> None:
        required = ["Ilce Adi", "Acilis Yili", "Adres", "Telefon", "Calisma Saatleri", "Calisma Gunleri"]
        data = {
            "fields": [{"id": name_field}, *[{"id": field} for field in required]],
            "records": rows,
        }
        (tmp_path / f"{stem}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    capture(
        "kutuphaneler",
        "Kutuphane Adi",
        [
            {
                "Kutuphane Adi": "Açık Kütüphane", "Ilce Adi": "Kadıköy", "Calisma Saatleri": "09:00-17:00",
                "Calisma Gunleri": "Hergün",
            },
            {
                "Kutuphane Adi": "Saati Yok", "Ilce Adi": "Kadıköy", "Calisma Saatleri": None,
                "Calisma Gunleri": "Hergün",
            },
        ],
    )
    capture(
        "muzeler", "Muze Adi",
        [{"Muze Adi": "Müze", "Ilce Adi": "Kadıköy", "Calisma Saatleri": "09:00-17:00", "Calisma Gunleri": "Hergün"}],
    )
    culture_api.load_venues.cache_clear()
    monkeypatch.setattr(culture_api, "CULTURE_DIR", tmp_path)
    try:
        values = bookable_libraries()
        assert len(values) == 1
        assert next(iter(values.values())).name == "Açık Kütüphane"
    finally:
        culture_api.load_venues.cache_clear()


def test_choice_and_seat_validation() -> None:
    library = example_library()
    slot = check_choice(library, "2026-09-29", 540, NOW)
    assert slot == Slot(540, 660)
    for day, start in (("2026-09-28", 540), ("2026-10-06", 540), ("2026-09-29", 480), ("2026-09-29", 540)):
        clock = NOW if day != "2026-09-29" or start != 540 else dt.datetime(2026, 9, 29, 9, 0, tzinfo=ISTANBUL)
        with pytest.raises(NotOffered):
            check_choice(library, day, start, clock)
    assert seat_ids()[0] == "A1" and seat_ids()[-1] == "F6" and len(seat_ids()) == 36


def test_store_enforces_consent_seat_slot_and_active_limits(tmp_path: Path) -> None:
    now = [NOW]
    store = BookingStore(tmp_path / "booking.db", clock=lambda: now[0])
    library = example_library()
    with pytest.raises(ConsentRequired):
        store.create(library, "2026-09-29", 540, "A1", "owner-1", False)
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM library_bookings").fetchone()[0] == 0
    with pytest.raises(BadSeat):
        store.create(library, "2026-09-29", 540, "Z9", "owner-1", True)
    first = store.create(library, "2026-09-29", 540, "A1", "owner-1", True)
    with pytest.raises(SeatTaken):
        store.create(library, "2026-09-29", 540, "A1", "owner-2", True)
    with pytest.raises(SlotHeld):
        store.create(library, "2026-09-29", 540, "A2", "owner-1", True)
    store.create(library, "2026-09-29", 660, "A2", "owner-1", True)
    with pytest.raises(ActiveLimit):
        store.create(library, "2026-09-29", 780, "A3", "owner-1", True)
    assert first["code"] and first["expires_at"].startswith("2026-10-29")


def test_cancel_checks_owner_deletes_row_and_frees_seat(tmp_path: Path) -> None:
    store = BookingStore(tmp_path / "booking.db", clock=lambda: NOW)
    library = example_library()
    saved = store.create(library, "2026-09-29", 540, "A1", "owner", True)
    assert store.cancel(saved["code"], "other") == "not_yours"
    assert "A1" in store.taken(library.key, "2026-09-29", 540)
    assert store.cancel(saved["code"], "owner") == "ok"
    assert store.cancel(saved["code"], "owner") == "not_found"
    assert "A1" not in store.taken(library.key, "2026-09-29", 540)
    assert store.create(library, "2026-09-29", 540, "A1", "other", True)


def test_expiry_and_owner_hash_are_private_and_salted_per_database(tmp_path: Path) -> None:
    now = [NOW]
    first = BookingStore(tmp_path / "first.db", clock=lambda: now[0])
    library = example_library()
    raw_device = "device-raw-0123456789"
    raw_account = "account-raw-abc123"
    token = "test-token"
    owner = first.holder_of("device", raw_device)
    assert owner == first.holder_of("device", raw_device)
    first.create(library, "2026-09-29", 540, "A1", owner, True)
    raw = first.path.read_bytes()
    assert all(value.encode() not in raw for value in (raw_device, raw_account, token))
    other = BookingStore(tmp_path / "second.db", clock=lambda: now[0])
    assert owner != other.holder_of("device", raw_device)
    now[0] += dt.timedelta(days=29)
    assert first.purge() == 0
    now[0] += dt.timedelta(days=2)
    assert first.purge() == 1


def test_key_folds_turkish_and_caps_length() -> None:
    assert library_key("Kadıköy", "İBB Şubesi") == "kadikoy-ibb-subesi"
    assert len(library_key("İlçe" * 30, "Kütüphane" * 20)) <= 80
