from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from ibb_mcp.config import REPO_ROOT
from nabiz.console.culture_api import load_venues
from nabiz.console.culture_events import (
    CultureEvent,
    culture_event_id,
    events_on,
    load_culture_events,
    parse_event_dates,
    plan_calendar_text,
    venue_district,
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("03-10-2026 15:00", (dt.date(2026, 10, 3), dt.date(2026, 10, 3), dt.time(15))),
        ("26-09-2026 13:00", (dt.date(2026, 9, 26), dt.date(2026, 9, 26), dt.time(13))),
        ("25-09-2026 20:00 - 25-09-2026", (dt.date(2026, 9, 25), dt.date(2026, 9, 25), dt.time(20))),
        ("02-05-2026 - 11-10-2026", (dt.date(2026, 5, 2), dt.date(2026, 10, 11), None)),
        ("23-09-2026", (dt.date(2026, 9, 23), dt.date(2026, 9, 23), None)),
        ("not a date", None),
        ("31-02-2026", None),
        ("11-10-2026 - 02-05-2026", None),
    ],
)
def test_event_date_formats(source: str, expected: Any) -> None:
    assert parse_event_dates(source) == expected


def _event(
    title: str,
    date_text: str,
    *,
    slugs: tuple[str, ...] = (),
    district: str | None = None,
    link: str | None = None,
) -> CultureEvent:
    link = link or f"https://kultur.istanbul/etkinlik/{title.lower().replace(' ', '-')}/"
    parsed = parse_event_dates(date_text)
    return CultureEvent(
        culture_event_id(link),
        title,
        link,
        date_text,
        "Örnek Sahne",
        (),
        slugs,
        parsed[0] if parsed else None,
        parsed[1] if parsed else None,
        parsed[2] if parsed else None,
        district,
    )


def test_events_on_counts_reasons_and_applies_source_filters() -> None:
    today = dt.date(2026, 9, 27)
    events = [
        _event("B", "03-10-2026 15:00", slugs=("ucretsiz",), district="Kadıköy"),
        _event("A", "03-10-2026", slugs=("cocuklar-icin-2", "yetiskinler-icin", "ucretsiz"), district="Kadıköy"),
        _event("Geçmiş", "23-09-2026", slugs=("ucretsiz",)),
        _event("İptal", "03-10-2026", slugs=("iptal",)),
        _event("Ertelendi", "03-10-2026", slugs=("ertelendi",)),
        _event("Okunamadı", "31-02-2026"),
        _event("Başladı", "27-09-2026 09:00"),
    ]
    selected, hidden = events_on(
        events,
        dt.date(2026, 10, 3),
        today,
        dt.time(10),
        audience="child",
        free_only=True,
        district="Kadıköy",
    )
    assert [event.title for event in selected] == ["A"]
    assert hidden == {"past": 2, "cancelled": 2, "started": 0, "undated": 0, "unparsed": 1}

    today_events, today_hidden = events_on(events, today, today, dt.time(10))
    assert all(event.title != "Başladı" for event in today_events)
    assert today_hidden["started"] == 1
    assert events_on(events, today - dt.timedelta(days=1), today, dt.time(10))[0] == []


def test_event_order_puts_known_times_first() -> None:
    day = dt.date(2026, 10, 3)
    events = [_event("İsimsiz saat", "03-10-2026"), _event("Akşam", "03-10-2026 20:00"), _event("Öğlen", "03-10-2026 12:00")]
    selected, _ = events_on(events, day, day - dt.timedelta(days=1), dt.time(9))
    assert [event.title for event in selected] == ["Öğlen", "Akşam", "İsimsiz saat"]


def test_venue_district_requires_an_exact_source_name() -> None:
    venues, _ = load_venues()
    known = next(venue for venue in venues if venue.district and venue_district(venue.name))
    assert venue_district(known.name) == known.district or venue_district(known.name) == "Küçükçekmece"
    assert venue_district(known.name + " benzer") is None


def test_capture_loader_reports_fields_and_does_not_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = {
        "title": "Örnek",
        "link": "https://kultur.istanbul/ornek/",
        "date_text": "03-10-2026",
        "venue": "Örnek",
        "types": [],
        "type_slugs": [],
    }
    payload = {
        "captured_at": "2026-09-26T12:00:00+00:00",
        "source": "Kültür AŞ",
        "source_url": "https://kultur.istanbul/",
        "license_note": "Not",
        "not_captured": [],
        "home_events": [first],
        "listings": [{"link": "https://kultur.istanbul/elsewhere/"}],
    }
    path = tmp_path / "events.json"
    monkeypatch.setenv("NABIZ_EVENTS_PATH", str(path))
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    events, meta = load_culture_events()
    assert events[0].title == "Örnek"
    assert (meta["undated"], meta["unparsed"]) == (1, 0)
    payload["home_events"][0]["title"] = "Örnek güncellendi"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert load_culture_events()[0][0].title == "Örnek güncellendi"


def test_actual_capture_has_schema_and_parseable_card_dates() -> None:
    path = REPO_ROOT / "data" / "reference" / "etkinlik" / "etkinlikler.json"
    if not path.exists():
        pytest.skip("owner capture is not present")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload.get("home_events"), list) and payload["home_events"]
    assert all(parse_event_dates(event["date_text"]) for event in payload["home_events"])


def _unfold(content: str) -> list[str]:
    rows = content.split("\r\n")
    result: list[str] = []
    for row in rows:
        if row.startswith(" ") and result:
            result[-1] += row[1:]
        elif row:
            result.append(row)
    return result


def test_calendar_is_utf8_folded_and_contains_no_personal_fields() -> None:
    event = _event("Türkçe, uzun; başlık \\ çizgisi", "03-10-2026 15:00", link="https://kultur.istanbul/etkinlik/ornek/")
    content = plan_calendar_text(event, dt.date(2026, 10, 3), "tr", dt.datetime(2026, 9, 27, tzinfo=dt.UTC), "2026-09-26")
    assert content.endswith("\r\n") and "\n" not in content.replace("\r\n", "")
    assert all(len(row.encode("utf-8")) <= 75 for row in content.split("\r\n") if row)
    unfolded = _unfold(content)
    summary = next(line for line in unfolded if line.startswith("SUMMARY:"))
    assert summary.endswith("Türkçe\\, uzun\\; başlık \\\\ çizgisi")
    assert "DTSTART:20261003T120000Z" in unfolded
    assert not any(key in content for key in ("LOCATION:", "ORGANIZER", "ATTENDEE", "mailto:"))
    assert "Nereden" not in content and "Kadıköy" not in content


def test_calendar_uses_date_when_source_has_no_time() -> None:
    event = _event("Gündüz", "03-10-2026")
    content = plan_calendar_text(event, dt.date(2026, 10, 3), "en", dt.datetime(2026, 9, 27, tzinfo=dt.UTC), "2026-09-26")
    assert "DTSTART;VALUE=DATE:20261003\r\n" in content
    assert "LOCATION:" not in content
