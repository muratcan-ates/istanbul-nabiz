"""Rules and storage for E71's short-lived support request files."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3

import pytest

from ibb_mcp.config import REPO_ROOT
from nabiz.console.escort_api import (
    STATUS_TEXT,
    escort_citizen_view,
    escort_operator_view,
    load_sources,
    load_stations,
    summary_lines,
)
from nabiz.console.escort_request import (
    CITIZEN_MOVES,
    OPERATOR_MOVES,
    EscortDraft,
    EscortStore,
    TransitionError,
    escort_path,
    validate,
)

TODAY = dt.date(2026, 9, 25)
STATIONS = ("Kadıköy", "Levent", "Kartal")


def body(**updates):
    return {
        "need": "wheelchair",
        "assistance": ["meet_at_entrance", "transfer"],
        "date": "2026-10-03",
        "time": "09:30",
        "window_min": 60,
        "meet_station": "kadikoy",
        "to_station": "LEVENT",
        "return_kind": "same_day",
        "return_time": "17:00",
        "companion": False,
        "note": "Kısa not",
        **updates,
    }


def create(store: EscortStore, **updates):
    draft = validate(body(**updates), STATIONS, TODAY)
    assert isinstance(draft, EscortDraft)
    return store.create(draft)


def test_load_stations_reads_unique_real_metro_names_and_environment_csv(tmp_path, monkeypatch):
    actual = load_stations()
    assert len(actual) > 200
    assert len({name.casefold() for name in actual}) == len(actual)
    csv_path = tmp_path / "places.csv"
    csv_path.write_text(
        "name,lat,lon,kind,district\nKadıköy,0,0,metro_station,x\nKADIKOY,0,0,metro_station,x\nOtobüs,0,0,bus_stop,x\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NABIZ_PLACES_CSV", str(csv_path))
    assert load_stations() == ("Kadıköy",)


def test_validate_accepts_a_canonical_draft():
    result = validate(body(), STATIONS, TODAY)
    assert isinstance(result, EscortDraft)
    assert result.meet_station == "Kadıköy" and result.to_station == "Levent"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"date": "2026-09-24"}, "Tarih bugün ile 30 gün sonrası arasında olmalı."),
        ({"date": "2026-10-26"}, "Tarih bugün ile 30 gün sonrası arasında olmalı."),
        ({"date": "03/10/2026"}, "Geçerli bir tarih seçin."),
        ({"time": "04:59"}, "Saat 05:00 ile 23:59 arasında olmalı."),
        ({"meet_station": "Haydarpaşa"}, "Listeden bir buluşma istasyonu seçin."),
        ({"meet_station": "Kadıköy", "to_station": "kadikoy"}, "Buluşma ve varış istasyonları farklı olmalı."),
        ({"return_time": "09:30"}, "Dönüş saati yolculuk saatinden sonra olmalı."),
        ({"assistance": []}, "En az bir destek seçin."),
        ({"need": "unknown"}, "Bir ihtiyaç türü seçin."),
        ({"note": "x" * 201}, "Not en fazla 200 karakter olabilir."),
        ({"assistance": ["invalid"]}, "En az bir destek seçin."),
        ({"window_min": 45}, "Bir zaman aralığı seçin."),
        ({"companion": "no"}, "Refakatçiniz olup olmadığını belirtin."),
    ],
)
def test_validate_reports_each_invalid_field(changes, message):
    assert validate(body(**changes), STATIONS, TODAY) == message


def test_summary_lines_are_bilingual_and_have_no_long_dash():
    draft = validate(body(), STATIONS, TODAY)
    assert isinstance(draft, EscortDraft)
    tr, en = summary_lines(draft, "tr"), summary_lines(draft, "en")
    assert tr[0] == "İhtiyaç: Tekerlekli sandalye"
    assert tr[2] == "Tarih: 3 Ekim 2026, 09:30 ile 10:30 arası"
    assert en[0] == "Need: Wheelchair"
    assert en[2] == "Date: 3 October 2026, between 09:30 and 10:30"
    assert all("\u2014" not in line and "\u2013" not in line for line in tr + en)


def test_summary_marks_an_interval_that_ends_the_next_day():
    draft = validate(body(time="23:30", window_min=60, return_kind="none", return_time=""), STATIONS, TODAY)
    assert isinstance(draft, EscortDraft)
    assert "00:30 (ertesi gün)" in summary_lines(draft, "tr")[2]
    assert "00:30 (next day)" in summary_lines(draft, "en")[2]


@pytest.mark.parametrize(
    ("actor", "status", "target", "allowed"),
    [("operator", status, target, True) for status, targets in OPERATOR_MOVES.items() for target in targets]
    + [("citizen", status, target, True) for status, targets in CITIZEN_MOVES.items() for target in targets]
    + [
        ("operator", status, target, False)
        for status in ("received", "seen", "referred_official", "closed", "cancelled")
        for target in ("received", "seen", "referred_official", "closed", "cancelled")
        if target not in OPERATOR_MOVES.get(status, ())
    ]
    + [
        ("citizen", status, target, False)
        for status in ("received", "seen", "referred_official", "closed", "cancelled")
        for target in ("received", "seen", "referred_official", "closed", "cancelled")
        if target not in CITIZEN_MOVES.get(status, ())
    ],
)
def test_transition_matrix_is_closed_and_role_scoped(tmp_path, actor, status, target, allowed):
    store = EscortStore(tmp_path / f"{actor}-{status}-{target}.db", clock=lambda: dt.datetime(2026, 9, 25, 9, tzinfo=dt.UTC))
    row = create(store)
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE escort_requests SET status = ? WHERE code = ?", (status, row["code"]))
    kwargs = (
        {"agency_id": "cozum_153"}
        if target == "referred_official"
        else {"note": "İşlem tamamlandı"}
        if target == "closed"
        else {}
    )
    if allowed:
        result = store.move(row["code"], actor, target, **kwargs)
        assert result and result["status"] == target
    else:
        with pytest.raises(TransitionError):
            store.move(row["code"], actor, target, **kwargs)


def test_operators_cannot_cancel_and_final_states_have_no_moves():
    assert "cancelled" not in {move for values in OPERATOR_MOVES.values() for move in values}
    assert OPERATOR_MOVES.get("closed") is None and OPERATOR_MOVES.get("cancelled") is None
    assert CITIZEN_MOVES.get("closed") is None and CITIZEN_MOVES.get("cancelled") is None


def test_note_pii_is_masked_before_sqlite_and_operator_sees_only_masked_text(tmp_path):
    store = EscortStore(tmp_path / "notes.db", clock=lambda: dt.datetime(2026, 9, 25, 9, tzinfo=dt.UTC))
    private_note = "Ara 0505 123 45 67, 11111111110 veya murat@example.com"
    row = create(store, note=private_note)
    with sqlite3.connect(store.path) as db:
        raw = " ".join(str(value) for line in db.iterdump() for value in line)
    assert "0505 123 45 67" not in raw and "11111111110" not in raw and "murat@example.com" not in raw
    shown = escort_operator_view(row)
    assert "[TELEFON]" in shown["note_masked"] and "[TC KİMLİK]" in shown["note_masked"] and "[E-POSTA]" in shown["note_masked"]
    assert shown["masked_count"] == 3


def test_ttl_uses_the_earlier_of_thirty_days_and_requested_date_plus_one_day(tmp_path):
    now = dt.datetime(2026, 9, 25, 9, tzinfo=dt.UTC)
    clock_now = [now]
    store = EscortStore(tmp_path / "ttl.db", clock=lambda: clock_now[0])
    far = create(store, date="2026-10-24")
    clock_now[0] += dt.timedelta(days=30, seconds=1)
    assert store.get(far["code"]) is None

    clock_now[0] = now
    soon = create(store, date="2026-09-25")
    clock_now[0] = dt.datetime(2026, 9, 25, 21, 0, 1, tzinfo=dt.UTC)
    assert store.get(soon["code"]) is None


def test_path_env_override_and_ledger_sibling(tmp_path):
    explicit = tmp_path / "explicit.db"
    assert escort_path({"NABIZ_ESCORT_DB_PATH": str(explicit)}) == explicit
    ledger = tmp_path / "ledger" / "nexus.db"
    assert escort_path({"NEXUS_DB_PATH": str(ledger)}) == ledger.with_name("escort_requests.db")


def test_sources_are_allowlisted_https_and_agencies_exist(tmp_path):
    sources = load_sources()
    allowlist = {
        line.split("\t", 1)[0]
        for line in (REPO_ROOT / "data/knowledge/sources.txt").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }
    agencies = json.loads((REPO_ROOT / "data/agencies.json").read_text(encoding="utf-8"))["agencies"]
    agency_ids = {agency["id"] for agency in agencies}
    assert len(sources) == 5
    assert all(source["url"] in allowlist and source["url"].startswith("https:") for source in sources)
    assert all(source["agency_id"] in agency_ids for source in sources)
    changed = json.loads(json.dumps(sources))
    changed[0]["url"] = changed[0]["url"].replace("https:", "http:")
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="güvenli"):
        load_sources(path)


def test_knowledge_database_source_check_when_available():
    if not (REPO_ROOT / "data/knowledge/knowledge.db").is_file():
        pytest.skip("ignored knowledge.db is absent in this checkout")
    assert len(load_sources()) == 5


def test_citizen_view_has_no_internal_or_raw_fields_and_neutral_status_copy(tmp_path):
    store = EscortStore(tmp_path / "view.db", clock=lambda: dt.datetime(2026, 9, 25, 9, tzinfo=dt.UTC))
    row = create(store, note="Murat@example.com")
    agencies = {
        item["id"]: item for item in json.loads((REPO_ROOT / "data/agencies.json").read_text(encoding="utf-8"))["agencies"]
    }
    view = escort_citizen_view(row, load_sources(), agencies)
    assert not {"signal_id", "operator", "ip", "note", "data"}.intersection(view)
    assert "Murat@example.com" not in json.dumps(view, ensure_ascii=False)
    assert view["official"]["call"] == "153"
    banned = ("yardım geliyor", "yolda", "ekip", "garanti", "ayarlandı", "hakkınız", "canlı")
    for status in ("received", "seen", "referred_official", "closed", "cancelled"):
        text = STATUS_TEXT["tr"][status].lower()
        assert all(term not in text for term in banned)


def test_operator_view_has_only_masked_request_note(tmp_path):
    store = EscortStore(tmp_path / "operator.db", clock=lambda: dt.datetime(2026, 9, 25, 9, tzinfo=dt.UTC))
    row = create(store, note="0505 123 45 67")
    shown = escort_operator_view(row)
    assert shown["note_masked"] == "[TELEFON]"
    assert all(key not in shown for key in ("signal_id", "ip", "operator_label"))
