from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nabiz.console import culture_events_api
from nabiz.console.culture_events import culture_event_id
from nexus_core.stats import ISTANBUL


def _payload(events: list[dict[str, Any]], listings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "source": "Kültür AŞ · kultur.istanbul", "source_url": "https://kultur.istanbul/",
        "captured_at": "2026-09-26T12:00:00+00:00", "license_note": "Kaynak notu.",
        "not_captured": [{"url": "https://kultur.istanbul/etkinlikler/", "reason": "JavaScript ile yükleniyor."}],
        "home_events": events, "listings": listings or [],
    }


def _event(title: str = "Örnek Etkinlik", date_text: str = "03-10-2026 15:00", slugs: list[str] | None = None) -> dict[str, Any]:
    return {
        "title": title, "link": f"https://kultur.istanbul/etkinlik/{title.lower().replace(' ', '-')}/",
        "date_text": date_text, "venue": "Örnek Sahne", "types": ["Ücretsiz"] if slugs else [],
        "type_slugs": slugs or [],
    }


def _client(path: Path, monkeypatch: Any) -> TestClient:
    monkeypatch.setenv("NABIZ_EVENTS_PATH", str(path))
    app = FastAPI()
    app.include_router(culture_events_api.culture_events_routes)
    return TestClient(app)


def _clock(monkeypatch: Any) -> None:
    monkeypatch.setattr(culture_events_api, "_now", lambda: dt.datetime(2026, 9, 27, 10, 0, tzinfo=ISTANBUL))


def test_missing_capture_returns_no_data_and_no_store(tmp_path: Path, monkeypatch: Any) -> None:
    _clock(monkeypatch)
    client = _client(tmp_path / "absent.json", monkeypatch)
    response = client.get("/api/events")
    assert response.status_code == 200
    assert response.json() == {"status": "no_data", "message": "Etkinlik verisi henüz yok."}
    assert response.headers["cache-control"] == "no-store"


def test_bad_dates_audience_and_unknown_district_are_rejected(tmp_path: Path, monkeypatch: Any) -> None:
    _clock(monkeypatch)
    path = tmp_path / "events.json"
    path.write_text(json.dumps(_payload([_event()])), encoding="utf-8")
    client = _client(path, monkeypatch)
    for value in ("2026-09-26", "2026-10-28", "not-a-date"):
        assert client.get("/api/events", params={"date": value}).status_code == 422
    assert client.get("/api/events", params={"with": "senior"}).json()["error"] == "bad_audience"
    assert client.get("/api/events", params={"district": "Kadıköy"}).json()["error"] == "unknown_district"


def test_event_list_and_day_contract_are_source_bounded(tmp_path: Path, monkeypatch: Any) -> None:
    _clock(monkeypatch)
    event = _event(slugs=["ucretsiz"])
    path = tmp_path / "events.json"
    path.write_text(json.dumps(_payload([event], [{"link": "https://kultur.istanbul/uncaptured/"}])), encoding="utf-8")
    client = _client(path, monkeypatch)
    response = client.get("/api/events", params={"date": "2026-10-03", "free": "1"})
    body = response.json()
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert body["status"] == "ok" and body["today"] == "2026-09-27"
    assert len(body["events"]) == 1
    assert body["events"][0]["title"] == "Örnek Etkinlik"
    assert body["events"][0]["date_text"] == "03-10-2026 15:00"
    assert body["hidden"]["undated"] == 1
    assert "from" not in json.dumps(body)

    event_id = culture_event_id(event["link"])
    details = client.get("/api/events/day", params={"id": event_id, "date": "2026-10-03"})
    assert details.status_code == 200 and details.headers["cache-control"] == "no-store"
    assert details.json()["event"]["id"] == event_id
    assert details.json()["venue_hours"] is None
    assert details.json()["nearby"] == []
    assert "Mekân erişim bilgisi kaynakta yok." in details.json()["notes"]


def test_event_gone_is_a_404_with_no_store(tmp_path: Path, monkeypatch: Any) -> None:
    _clock(monkeypatch)
    path = tmp_path / "events.json"
    path.write_text(json.dumps(_payload([_event(date_text="11-10-2026")])), encoding="utf-8")
    response = _client(path, monkeypatch).get("/api/events/day", params={"id": "ev_000000000000", "date": "2026-10-03"})
    assert response.status_code == 404
    assert response.json()["error"] == "event_gone"
    assert response.headers["cache-control"] == "no-store"


def test_calendar_endpoint_returns_ics_attachment(tmp_path: Path, monkeypatch: Any) -> None:
    _clock(monkeypatch)
    event = _event()
    path = tmp_path / "events.json"
    path.write_text(json.dumps(_payload([event])), encoding="utf-8")
    response = _client(path, monkeypatch).post("/api/events/calendar", json={
        "id": culture_event_id(event["link"]), "date": "2026-10-03", "lang": "tr",
    })
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/calendar; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="nabiz-gun-plani.ics"'
    assert response.headers["cache-control"] == "no-store"
    assert "DTSTART:20261003T120000Z" in response.text
