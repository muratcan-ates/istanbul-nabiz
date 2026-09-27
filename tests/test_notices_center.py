"""E55's stateless notice contracts and RFC 5545 reminders."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterator
from types import SimpleNamespace

import httpx
import pytest
from conftest import offline_settings, refuse_network
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nexus_helpers import Clock, approve, build_engine
from test_report_outcome import code_for, outcome_app, post_report, put_static_last

from ibb_mcp.cache import TTLCache
from ibb_mcp.http import PoliteClient
from ibb_mcp.models import ISTANBUL_TZ
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.console.follow import topic_from
from nabiz.console.ics import CalendarEvent, calendar_text, escape_text, fold_line
from nabiz.console.notices_center import calendar_event, notice_id, report_notice, request_notice, topic_notices
from nabiz.console.notices_center_api import notices_center_routes

NOW = dt.datetime(2026, 9, 26, 12, 0, tzinfo=dt.UTC)


@pytest.fixture(scope="module")
def nabiz() -> Iterator[Nabiz]:
    yield Nabiz(
        SourceContext.create(
            client=PoliteClient(transport=httpx.MockTransport(refuse_network)),
            cache=TTLCache(),
            settings=offline_settings(),
        )
    )


class MemoryStore:
    def __init__(self, rows: dict[str, dict[str, object]] | None = None) -> None:
        self.rows = rows or {}

    def get(self, code: str) -> dict[str, object] | None:
        return self.rows.get(code)


def request_row(code: str, *, answered: bool = False) -> dict[str, object]:
    reply = None
    status = "waiting"
    if answered:
        status = "answered"
        reply = {
            "text": "A PRIVATE REPLY",
            "lang": "en",
            "text_tr": "ÖZEL YANIT",
            "translation": "operator",
            "answered_at": "2026-09-26T09:12:00+00:00",
        }
    return {
        "code": code,
        "status": status,
        "created_at": "2026-09-26T09:00:00+00:00",
        "expires_at": "2026-10-26T08:50:00+00:00",
        "lang": "tr",
        "original_masked": "PRIVATE QUESTION",
        "masked_count": 0,
        "translation_status": "model",
        "reply": reply,
    }


def api_app(nabiz: Nabiz, rows: dict[str, dict[str, object]] | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(notices_center_routes)
    app.state.nabiz = nabiz
    app.state.notices_clock = lambda: NOW
    app.state.report_clock = lambda: NOW
    app.state.request_desk = SimpleNamespace(store=MemoryStore(rows))
    app.state.ports = SimpleNamespace(console=SimpleNamespace(engine=None))
    return app


def unescape_ical(value: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        if value[index] == "\\" and index + 1 < len(value):
            index += 1
            result.append("\n" if value[index] in "nN" else value[index])
        else:
            result.append(value[index])
        index += 1
    return "".join(result)


def test_ics_escapes_text_folds_utf8_and_uses_crlf() -> None:
    original = "İşğüö\\;,\r\nson" + chr(1)
    assert escape_text("a\\b,c;d\n") == "a\\\\b\\,c\\;d\\n"
    event = CalendarEvent(
        "fixed@istanbul-nabiz",
        dt.datetime(2026, 9, 27, 6, 0, tzinfo=dt.UTC),
        15,
        "İşğüö; alarm",
        original,
        "https://example.test/#guncellemeler",
    )
    content = calendar_text([event], now=NOW)
    assert content.endswith("\r\n") and "\n" not in content.replace("\r\n", "")
    assert all(len(line.encode("utf-8")) <= 75 for line in content.split("\r\n") if line)
    assert "BEGIN:VCALENDAR\r\nVERSION:2.0" in content
    assert "DTSTART:20260927T060000Z" in content
    assert "METHOD:PUBLISH" in content and "DURATION:PT15M" in content
    assert "ORGANIZER:" not in content and "ATTENDEE:" not in content and "LOCATION:" not in content
    assert "mailto:" not in content and chr(1) not in content
    assert "SUMMARY:İşğüö\\; alarm" in content
    unfolded = content.replace("\r\n ", "")
    description = next(line.removeprefix("DESCRIPTION:") for line in unfolded.split("\r\n") if line.startswith("DESCRIPTION:"))
    expected = original.replace("\r\n", "\n").replace("\r", "\n").replace(chr(1), "")
    assert unescape_ical(description) == expected
    folded = fold_line("X:" + "İşğüö" * 30)
    assert all(len(line.encode("utf-8")) <= 75 for line in folded.split("\r\n"))
    assert folded.split("\r\n")[1].startswith(" ")


def test_ics_rejects_naive_times_and_omits_non_http_urls() -> None:
    with pytest.raises(ValueError):
        CalendarEvent("uid", dt.datetime(2026, 9, 27, 9), 15, "summary", "description")
    event = CalendarEvent("uid", NOW, 1, "summary", "description", "javascript:alert(1)")
    assert "URL:" not in calendar_text([event], now=NOW)
    with pytest.raises(ValueError):
        CalendarEvent("uid", NOW, 241, "summary", "description")


@pytest.mark.asyncio
async def test_topics_use_recorded_alert_dates_and_report_unavailable_sources(nabiz: Nabiz, monkeypatch) -> None:
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", "data/knowledge/not-built-e55.db")
    m7, missing_m7 = await topic_notices(nabiz, topic_from("metro_line", "M7"), 0)
    etiler, missing_etiler = await topic_notices(nabiz, topic_from("station", "Etiler"), 1)
    nowhere, unknown = await topic_notices(nabiz, topic_from("station", "Hiçyokköy"), 2)
    knowledge, no_index = await topic_notices(nabiz, topic_from("knowledge", "kreş"), 3)
    assert missing_m7 is missing_etiler is None
    assert any(item.kind == "notice" and item.date_kind in {"source", "read"} for item in m7)
    assert any(item.kind == "fault" and item.date_kind in {"source", "read"} for item in etiler)
    assert all(item.calendar == "reminder" and item.open for item in m7 + etiler)
    assert nowhere == knowledge == []
    assert unknown and "Bu adla bir metro istasyonu bulunamadı" in unknown["text_tr"]
    assert no_index and "Bilgi arşivi bu sunucuda kurulu değil" in no_index["text_tr"]


@pytest.mark.asyncio
async def test_notice_ids_and_calendar_dates_do_not_depend_on_read_time(nabiz: Nabiz) -> None:
    topic = topic_from("metro_line", "M7")
    first, _ = await topic_notices(nabiz, topic, 0)
    again, _ = await topic_notices(nabiz, topic, 0)
    assert [item.id for item in first] == [item.id for item in again]
    assert notice_id("request", "a", "a", "waiting") != notice_id("request", "a", "a", "answered")
    item = next(item for item in first if item.calendar == "reminder")
    event = calendar_event(item, now=NOW, lang="tr")
    assert event is not None and event.start == dt.datetime(2026, 9, 27, 6, 0, tzinfo=dt.UTC)


def test_request_and_report_notices_exclude_private_text_and_report_time() -> None:
    waiting = request_notice(request_row("K7M2QX9P"), 0, NOW)
    answered = request_notice(request_row("K7M2QX9P", answered=True), 0, NOW)
    assert waiting.status == "waiting" and waiting.date_kind == "sent" and waiting.calendar == "reminder"
    assert answered.status == "answered" and answered.date_kind == "answered" and answered.calendar == "expiry"
    assert answered.recorded_at == dt.datetime(2026, 9, 26, 9, 12, tzinfo=dt.UTC)
    assert "PRIVATE" not in str(waiting.public()) and "PRIVATE" not in str(answered.public())
    assert "K7M2QX9P" not in str(waiting.public()) and "K7M2QX9P" not in str(answered.public())
    expiry = calendar_event(answered, now=NOW, lang="en")
    assert expiry is not None and expiry.start == dt.datetime(2026, 10, 25, 8, 50, tzinfo=dt.UTC)
    assert "26.10.2026 11:50" in expiry.description
    expired = request_notice(
        {**request_row("K7M2QX9P", answered=True), "expires_at": "2026-09-27T10:00:00+00:00"}, 0, NOW
    )
    assert expired.calendar is None and calendar_event(expired, now=NOW, lang="tr") is None

    report = report_notice({
        "code": "23456789", "station": "Kartal", "status": "waiting", "text": "Onay bekliyor: simüle operatör.",
    }, 0)
    public = report.public()
    assert public["recorded_at"] is None and public["date_kind"] is None
    assert not re.search(r"\d{4}-\d{2}-\d{2}T", str(public))
    assert "23456789" not in str(public) and "signal_id" not in str(public) and "reason" not in str(public)
    report_event = calendar_event(report, now=NOW, lang="tr")
    assert report_event is not None
    calendar_copy = f"{report_event.summary} {report_event.description}"
    assert "Kartal" not in calendar_copy and "23456789" not in calendar_copy and "PRIVATE" not in calendar_copy
    assert ISTANBUL_TZ.utcoffset(NOW) == dt.timedelta(hours=3)


def test_notice_endpoint_is_stateless_and_calendar_is_rebuilt(nabiz: Nabiz, tmp_path, monkeypatch, caplog) -> None:
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(tmp_path / "not-installed.db"))
    app = api_app(nabiz, {"K7M2QX9P": request_row("K7M2QX9P")})
    before = set(tmp_path.rglob("*"))
    with TestClient(app) as client:
        payload = {
            "topics": [{"kind": "metro_line", "value": "M7"}],
            "requests": ["K7M2QX9P"],
            "reports": ["23456789"],
        }
        response = client.post("/api/notices", json=payload)
        again = client.post("/api/notices", json=payload)
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        body = response.json()
        assert [item["id"] for item in body["items"]] == [item["id"] for item in again.json()["items"]]
        request_item = next(item for item in body["items"] if item["source"] == "request")
        assert request_item["status"] == "waiting" and request_item["date_kind"] == "sent"
        assert request_item["calendar"] == "reminder" and "K7M2QX9P" not in str(body)
        assert "PRIVATE QUESTION" not in str(body) and "A PRIVATE REPLY" not in str(body)
        assert body["unavailable"] and body["unavailable"][0]["source"] == "report"

        calendar = client.post("/api/notices/calendar", json={
            "source": "request", "code": "K7M2QX9P", "topic": None,
            "item_id": request_item["id"], "lang": "en",
        })
        assert calendar.status_code == 200
        assert calendar.headers["content-type"].startswith("text/calendar; charset=utf-8")
        assert 'attachment; filename="nabiz-hatirlatici.ics"' in calendar.headers["content-disposition"]
        assert calendar.headers["cache-control"] == "no-store"
        assert "SUMMARY:Nabız reminder: your operator request" in calendar.text
        assert "K7M2QX9P" not in calendar.text and "PRIVATE" not in calendar.text

        gone = client.post("/api/notices/calendar", json={
            "source": "request", "code": "K7M2QX9P", "item_id": "n_0000000000000000",
        })
        invalid_topic = client.post("/api/notices", json={"topics": [{"kind": "knowledge", "value": "41.0082, 28.9784"}]})
        too_many = client.post("/api/notices", json={"topics": [{"kind": "metro_line", "value": "M2"}] * 11})
        invalid_code = client.post("/api/notices", json={"requests": ["not-a-code"]})
    assert gone.status_code == 404 and gone.json()["error"] == "notice_gone"
    assert invalid_topic.status_code == 400 and invalid_topic.json()["error"] == "follow_topic"
    assert too_many.status_code == 422
    assert invalid_code.status_code == 200 and invalid_code.json()["skipped"] == 1
    assert set(tmp_path.rglob("*")) == before
    assert "K7M2QX9P" not in caplog.text and "23456789" not in caplog.text


def test_report_endpoint_returns_waiting_then_approved_without_server_time(tmp_path) -> None:
    clock = Clock()
    engine = build_engine(tmp_path, clock)
    app, _ = outcome_app(engine, clock)
    app.include_router(notices_center_routes)
    put_static_last(app)
    app.state.notices_clock = lambda: NOW
    with TestClient(app) as client:
        assert post_report(client).status_code == 200
        code = code_for(client)
        waiting = client.post("/api/notices", json={"reports": [code]}).json()["items"][0]
        before = len(engine.ledger.entries())
        waiting_calendar = client.post("/api/notices/calendar", json={
            "source": "report", "code": code, "item_id": waiting["id"], "lang": "tr",
        })
        after = len(engine.ledger.entries())
        state = next(value for value in engine.states().values() if value.signal.kind == "citizen_report")
        engine.decide(approve(state.signal.signal_id, reason="reviewed"))
        approved = client.post("/api/notices", json={"reports": [code]}).json()["items"][0]
        no_calendar = client.post("/api/notices/calendar", json={
            "source": "report", "code": code, "item_id": approved["id"], "lang": "en",
        })
    assert waiting["status"] == "waiting" and waiting["calendar"] == "reminder"
    assert waiting["recorded_at"] is None and waiting["date_kind"] is None
    assert waiting_calendar.status_code == 200
    assert "Kartal" not in waiting_calendar.text and code not in waiting_calendar.text
    assert after == before
    assert approved["status"] == "approved" and approved["calendar"] is None
    assert not re.search(r"\d{4}-\d{2}-\d{2}T", str(approved))
    assert code not in str(approved) and "signal_id" not in str(approved) and "reason" not in str(approved)
    assert no_calendar.status_code == 422 and no_calendar.json()["error"] == "no_calendar"
