from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ibb_mcp.config import REPO_ROOT
from nabiz.console import culture_api
from nabiz.console.culture_api import Venue, load_venues, parse_days, parse_hours, venue_state
from nexus_core.stats import ISTANBUL

DATA_DIR = REPO_ROOT / "data" / "reference" / "ibb_kultur"
STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
CAPTURE_FIELDS = (
    "_id",
    "Ilce Adi",
    "Acilis Yili",
    "Adres",
    "Telefon",
    "Calisma Saatleri",
    "Calisma Gunleri",
)


def client() -> TestClient:
    app = FastAPI()
    app.include_router(culture_api.culture_routes)
    return TestClient(app)


def write_capture(directory: Path, libraries: list[dict[str, Any]], museums: list[dict[str, Any]] | None = None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    shared_fields = ["Ilce Adi", "Acilis Yili", "Adres", "Telefon", "Calisma Saatleri", "Calisma Gunleri"]
    for kind, stem, name_field, records in (
        ("library", "kutuphaneler", "Kutuphane Adi", libraries),
        ("museum", "muzeler", "Muze Adi", museums or []),
    ):
        rows = []
        for number, values in enumerate(records, start=1):
            rows.append({"_id": number, name_field: values.get("name"), **{key: values.get(key) for key in shared_fields}})
        payload = {
            "captured_at": "2026-09-26T12:29:08+00:00",
            "package_id": f"ibb-{stem}-lokasyon-calisma-gun-ve-saatleri",
            "resource_id": f"resource-{kind}",
            "resource_last_modified": "2026-02-12T12:11:17.167819",
            "license_id": "ibb-license",
            "license_title": "Istanbul Metropolitan Municipality Open Data License",
            "fields": [{"id": "_id"}, {"id": name_field}, *[{"id": key} for key in shared_fields]],
            "total": len(rows),
            "records": rows,
        }
        (directory / f"{stem}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def venue(
    name: str = "Deneme Kütüphanesi",
    *,
    hours: str | None = "09:00-22:00",
    days: str | None = "Hergün",
    kind: str = "library",
    district: str = "Kadıköy",
) -> Venue:
    return Venue(kind, name, district, "Kayıttaki adres", ("0212 000 00 00",), hours, days, None)  # type: ignore[arg-type]


def schedule_row(name: str, hours: str | None, days: str | None, district: str = "Kadıköy") -> dict[str, Any]:
    return {
        "name": name,
        "Ilce Adi": district,
        "Acilis Yili": "2020",
        "Adres": "Kayıttaki adres",
        "Telefon": "0212 000 00 00",
        "Calisma Saatleri": hours,
        "Calisma Gunleri": days,
    }


def response_texts(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in response_texts(item)]
    if isinstance(value, list):
        return [text for item in value for text in response_texts(item)]
    return []


def test_the_capture_is_read_as_it_is() -> None:
    load_venues.cache_clear()
    venues, metadata = load_venues(DATA_DIR)
    for kind, stem, name_field in (
        ("library", "kutuphaneler", "Kutuphane Adi"),
        ("museum", "muzeler", "Muze Adi"),
    ):
        payload = json.loads((DATA_DIR / f"{stem}.json").read_text(encoding="utf-8"))
        typed = [item for item in venues if item.kind == kind]
        assert len(typed) == payload["total"] == len(payload["records"])
        assert {field["id"] for field in payload["fields"]} >= {"_id", name_field, *CAPTURE_FIELDS[1:]}
        assert all(item.name.strip() for item in typed)
        assert metadata[kind]["captured_at"] == payload["captured_at"]
    load_venues.cache_clear()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hergün", frozenset(range(7))),
        ("Her gün", frozenset(range(7))),
        ("Pazartesi-Cuma", frozenset(range(5))),
        ("Salı-Pazar", frozenset(range(1, 7))),
        ("Pazartesi-Cumartesi", frozenset(range(6))),
        ("Hafta içi: 09:00 - 17:00 / Hafta sonu: Kapalı", frozenset(range(5))),
        ("Bazı günler", None),
        (None, None),
    ],
)
def test_days_are_parsed_or_left_unknown(text: str | None, expected: frozenset[int] | None) -> None:
    assert parse_days(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("09:00-22:00", (dt.time(9), dt.time(22))),
        ("10:00 - 18:00", (dt.time(10), dt.time(18))),
        ("09.00- 19.00", (dt.time(9), dt.time(19))),
        ("7/24", "always"),
        ("Hafta içi: 09:00 - 17:00 / Hafta sonu: Kapalı", (dt.time(9), dt.time(17))),
        ("24:00-25:00", None),
        ("09:00-09:00", None),
        ("", None),
        (None, None),
    ],
)
def test_hours_are_parsed_or_left_unknown(text: str | None, expected: Any) -> None:
    assert parse_hours(text) == expected


def test_open_now_is_computed_in_istanbul_time() -> None:
    now_utc = dt.datetime(2026, 9, 29, 18, 30, tzinfo=dt.UTC)
    state = venue_state(venue(), now_utc)
    assert now_utc.astimezone(ISTANBUL).weekday() == 1
    assert now_utc.astimezone(ISTANBUL).strftime("%H:%M") == "21:30"
    assert state == {
        "state": "open",
        "text": "Kayda göre şu an açık · kapanış 22.00",
        "closes_at": "22.00",
        "opens_next": None,
    }


def test_closed_says_when_it_opens_next() -> None:
    now = dt.datetime(2026, 9, 29, 22, 0, tzinfo=ISTANBUL)
    state = venue_state(venue(), now)
    assert state["state"] == "closed"
    assert state["text"] == "Kayda göre şu an kapalı · açılış Çarşamba 09.00"
    assert state["opens_next"] == "Çarşamba 09.00"
    weekday_closed = venue(hours="10:00 - 18:00", days="Salı-Pazar")
    monday = dt.datetime(2026, 9, 28, 12, 0, tzinfo=ISTANBUL)
    assert venue_state(weekday_closed, monday)["opens_next"] == "Salı 10.00"
    weekend = venue(hours=None, days="Hafta içi: 09:00 - 17:00 / Hafta sonu: Kapalı")
    saturday = dt.datetime(2026, 10, 3, 12, 0, tzinfo=ISTANBUL)
    assert venue_state(weekend, saturday)["opens_next"] == "Pazartesi 09.00"


def test_seven_twenty_four_is_always_open() -> None:
    state = venue_state(venue(hours="7/24", days=None), dt.datetime(2026, 9, 27, 3, tzinfo=ISTANBUL))
    assert state == {"state": "open", "text": "Kayda göre 7/24 açık", "closes_at": None, "opens_next": None}


def test_a_district_lists_only_its_venues_sorted_open_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_capture(
        tmp_path,
        [
            schedule_row("Geç kapanan", "09:00-23:00", "Hergün"),
            schedule_row("Erken kapanan", "09:00-22:00", "Hergün"),
            schedule_row("Kapalı", "09:00-17:00", "Hergün"),
            schedule_row("Başka ilçe", "09:00-22:00", "Hergün", "Üsküdar"),
        ],
        [schedule_row("Saat yok", None, None)],
    )
    load_venues.cache_clear()
    monkeypatch.setattr(culture_api, "CULTURE_DIR", tmp_path)
    monkeypatch.setattr(culture_api, "_now_local", lambda: dt.datetime(2026, 9, 29, 21, 30, tzinfo=ISTANBUL))
    body = client().get("/api/culture", params={"district": "Kadıköy"}).json()
    assert [item["name"] for item in body["venues"]] == ["Erken kapanan", "Geç kapanan", "Kapalı", "Saat yok"]
    assert {item["district"] for item in body["venues"]} == {"Kadıköy"}
    assert [item["state"] for item in body["venues"]] == ["open", "open", "closed", "unknown"]
    libraries_only = client().get("/api/culture", params={"district": "Kadıköy", "kinds": "library"}).json()
    assert all(item["kind"] == "library" for item in libraries_only["venues"])
    load_venues.cache_clear()


def test_district_matching_folds_turkish_letters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        schedule_row("Kadıköy", "09:00-22:00", "Hergün"),
        schedule_row("Kağıthane", "09:00-22:00", "Hergün", "Kağıthane"),
    ]
    write_capture(tmp_path, rows)
    load_venues.cache_clear()
    monkeypatch.setattr(culture_api, "CULTURE_DIR", tmp_path)
    for requested, expected in (("kadikoy", "Kadıköy"), ("KAĞITHANE", "Kağıthane"), ("Kâğıthane", "Kağıthane")):
        body = client().get("/api/culture", params={"district": requested}).json()
        assert {item["district"] for item in body["venues"]} == {expected}
    load_venues.cache_clear()


def test_unknown_district_and_bad_kinds_are_422(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_capture(tmp_path, [schedule_row("Kadıköy", "09:00-22:00", "Hergün")])
    load_venues.cache_clear()
    monkeypatch.setattr(culture_api, "CULTURE_DIR", tmp_path)
    api = client()
    unknown = api.get("/api/culture", params={"district": "Narnia"})
    bad_kinds = api.get("/api/culture", params={"district": "Kadıköy", "kinds": "libraries"})
    assert unknown.status_code == 422 and unknown.json()["error"] == "unknown_district"
    assert bad_kinds.status_code == 422 and bad_kinds.json()["error"] == "bad_kinds"
    load_venues.cache_clear()


def test_without_the_capture_the_section_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    load_venues.cache_clear()
    monkeypatch.setattr(culture_api, "CULTURE_DIR", tmp_path)
    response = client().get("/api/culture")
    assert response.status_code == 200
    assert response.json()["venues"] == []
    assert response.json()["note"] == "Kütüphane ve müze kaydı bu sunucuda yok."
    load_venues.cache_clear()


def test_no_occupancy_is_promised(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_capture(tmp_path, [schedule_row("Kadıköy", "09:00-22:00", "Hergün")])
    load_venues.cache_clear()
    monkeypatch.setattr(culture_api, "CULTURE_DIR", tmp_path)
    payload = client().get("/api/culture", params={"district": "Kadıköy"}).json()
    for text in response_texts(payload):
        folded = text.casefold()
        if "doluluk" in folded:
            assert "doluluk bilgisi yok" in folded
        assert "boş yer" not in folded and "kalabalık" not in folded and "%" not in text
    load_venues.cache_clear()


def test_answers_carry_the_source_and_the_disclaimers() -> None:
    load_venues.cache_clear()
    venues, _ = load_venues(DATA_DIR)
    district = next(item.district for item in venues if item.kind == "library" and item.district)
    payload = client().get("/api/culture", params={"district": district}).json()
    assert payload["provenance_by_kind"]["library"]["source"] == "ibb_open_data"
    assert payload["provenance_by_kind"]["library"]["url"].startswith("https://data.ibb.gov.tr/dataset/")
    assert payload["provenance_by_kind"]["library"]["observed_at"] == "2026-02-12T12:11:17.167819"
    assert payload["provenance_by_kind"]["library"]["age_s"] >= 0
    assert payload["license"] == "İBB Açık Veri Lisansı"
    assert "Resmî tatil ve özel kapanışlar kayıtta yok; gitmeden önce arayın." in payload["notes"]
    assert payload["disclaimer"] == "Resmî İBB hizmeti değildir."
    load_venues.cache_clear()


def test_culture_files_follow_the_page_rules() -> None:
    js = (STATIC / "js" / "culture.js").read_text(encoding="utf-8")
    css = (STATIC / "css" / "culture.css").read_text(encoding="utf-8")
    assert all(token in js for token in ("/api/culture", 'role="status"', "tel:", "esc(", "nabiz.culture.v1"))
    assert re.search(r"try\s*\{\s*const value = JSON\.parse\(window\.localStorage", js)
    for text in (js, css):
        assert "—" not in text and "–" not in text
        assert re.search(r"\bETA\b", text) is None
    assert "--tap" in css and "transition:" not in css and "animation:" not in css
    color = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(")
    assert color.search(re.sub(r"/\*.*?\*/", "", css, flags=re.S)) is None
    node = shutil.which("node")
    if node:
        result = subprocess.run([node, "--check", str(STATIC / "js" / "culture.js")], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr


def test_no_request_leaves_the_machine(_no_outbound_network: list[str]) -> None:
    load_venues.cache_clear()
    response = client().get("/api/culture")
    assert response.status_code == 200
    assert _no_outbound_network == []
    load_venues.cache_clear()
