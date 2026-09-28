"""Story 2: an event from memory, then a calendar entry (docs/acceptance/HIKAYE-2.md).

The base has the recorded opening hours of İBB libraries and museums and the chat's offer to
remember; the dated event list, the calendar file and the booking cleanup on account deletion come
with P00 G4, the chat's own memory with P02. The event file itself is reference data
(``data/reference/etkinlik``) that a cloud checkout does not have, so the G4 tests assert the honest
empty answer when it is missing and the dated, sourced list when it is there.
"""

from __future__ import annotations

import datetime as dt
import re

import pytest
from fastapi.testclient import TestClient
from test_console_chat import FakeModel, reply

from acceptance.support import CLOUD, after, build_app, chat, offline_nabiz, sign_in, tools_started
from ibb_mcp.models import ISTANBUL_TZ
from nabiz.agent import llm

HEALTH_WORDS = ("diyabet", "kalp", "astım", "epilepsi", "diyaliz")


def _today() -> dt.date:
    return dt.datetime.now(ISTANBUL_TZ).date()


def _next_saturday() -> dt.date:
    today = _today()
    return today + dt.timedelta(days=(5 - today.weekday()) % 7 or 7)


# ---- the base -------------------------------------------------------------------------------------------


def test_venue_hours_are_read_from_the_record_never_called_live(client: TestClient) -> None:
    """Step 2: what is open is "Kayda göre", with the institution's own hours text beside it."""
    response = client.get("/api/culture", params={"district": "Kadıköy"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["district"] == "Kadıköy" and body["venues"]
    for venue in body["venues"]:
        assert venue["district"] == "Kadıköy"
        assert venue["state"] in {"open", "closed", "unknown"}
        text = venue["state_text"].casefold()
        assert "kayda göre" in text or venue["state"] == "unknown", venue
        assert "canlı" not in text


def test_an_unknown_district_is_refused_not_guessed(client: TestClient) -> None:
    """Step 7 (no source): a district the record does not have gets no nearest match."""
    response = client.get("/api/culture", params={"district": "Atlantis"})
    assert response.status_code == 422 and response.json()["error"] == "unknown_district"


def test_memory_is_offered_after_two_asks_and_never_kept_by_the_server(client: TestClient) -> None:
    """Step 4 (criterion 3): the offer comes from the person's own words; the server stores nothing."""
    earlier = ["Bebek arabasıyla Kadıköy'e gideceğim"]
    _, first = chat(client, "Bebek arabasıyla metroya binebilir miyim?", history=[])
    assert first["memory_suggestion"] is None, "one mention is not a habit"
    _, second = chat(client, "Bebek arabasıyla metroya binebilir miyim?", history=earlier)
    assert second["memory_suggestion"] == {"key": "stroller", "label": "Bebek arabası"}
    _, fresh = chat(client, "Bebek arabasıyla metroya binebilir miyim?", history=[])
    assert fresh["memory_suggestion"] is None, "a new conversation starts with nothing remembered on the server"


def test_two_conversations_share_nothing_on_the_server(client: TestClient) -> None:
    """Criterion 2, server side: a turn knows only the history its own page sends; no other chat leaks in."""
    chat(client, "Kadıköy'de otopark var mı?")
    stream, final = chat(client, "Peki otopark?")
    assert tools_started(stream) == [], "no parking search for a place this conversation never named"
    assert final["answer"].startswith("Hangi semt ya da ilçe"), "a new conversation asks where, it does not remember"


def test_a_health_word_in_the_profile_never_reaches_the_model(stores: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """Criterion 3: only functional needs pass to the model; a diagnosis sent as a need is dropped."""
    fake = FakeModel(reply("Bu konuda doğrulanmış bir kaynak bulamadım."))
    monkeypatch.setattr(llm, "chat", fake)
    with TestClient(build_app(offline_nabiz(), config=CLOUD)) as client:
        chat(client, "Kadıköy'de bu akşam ne yapabilirim?", needs=["stroller", "diyabet", "diagnosis:kalp"])
    system = fake.calls[0]["messages"][0]["content"].casefold()
    assert "bebek arabası" in system, "the functional need reaches the model"
    assert not any(word in system for word in HEALTH_WORDS)


def test_a_fee_question_about_an_event_is_not_answered_with_a_number(client: TestClient) -> None:
    """Step 8 (no source for a price): the chat sends the person to 153 and the official page."""
    _, final = chat(client, "Cumartesi Kadıköy'deki konserin bilet fiyatı kaç lira?")
    assert final["refused"] is True and "153" in final["answer"]
    assert not re.search(r"\d+\s*(?:tl|lira|₺)", final["answer"], re.I)


# ---- P00 G4: dated events, the calendar file, bookings on account deletion -------------------------------


@after("G4", "/api/events")
def test_events_for_a_day_are_dated_sourced_and_never_past(client: TestClient) -> None:
    today = _today()
    response = client.get("/api/events", params={"date": today.isoformat()})
    assert response.status_code == 200, response.text
    assert response.headers.get("cache-control") == "no-store"
    body = response.json()
    if body["status"] == "no_data":
        assert body["message"], "no event file: an honest sentence, no made-up event"
        return
    assert body["date"] == today.isoformat() and body["source"]["captured_at"], "every list names its capture time"
    assert isinstance(body["source"]["stale"], bool) and body["source"]["url"].startswith("https://")
    assert isinstance(body["hidden"].get("past"), int), "past events are counted, never listed"
    for event in body["events"]:
        assert event["link"].startswith("https://") and event["date_text"], "each card carries its source link and date"


@after("G4", "/api/events")
def test_cumartesi_olsun_moves_the_list_to_that_day(client: TestClient) -> None:
    """Step 6 (date correction): the page re-asks for Saturday; the answer is Saturday's list."""
    saturday = _next_saturday()
    body = client.get("/api/events", params={"date": saturday.isoformat()}).json()
    if body["status"] != "no_data":
        assert body["date"] == saturday.isoformat()


@after("G4", "/api/events")
def test_a_past_day_never_lists_events_as_coming(client: TestClient) -> None:
    yesterday = (_today() - dt.timedelta(days=1)).isoformat()
    response = client.get("/api/events", params={"date": yesterday})
    if response.status_code == 422:
        assert response.json()["error"] == "bad_date"
    else:
        assert response.status_code == 200 and not response.json().get("events"), "a past day shows nothing as upcoming"


@after("G4", "/api/events/calendar", "POST")
def test_the_calendar_file_is_istanbul_time_personal_data_free_and_not_cached(client: TestClient) -> None:
    """Criterion 6: time zone, a repeated click, no personal data; a bad id is refused, not guessed."""
    bad = client.post("/api/events/calendar", json={"id": "x", "date": _today().isoformat(), "lang": "tr"})
    assert bad.status_code == 422, "an id that is not an event's is refused, never guessed"
    listing = client.get("/api/events", params={"date": _next_saturday().isoformat()}).json()
    if not listing.get("events"):
        pytest.skip("not run: veri yerelde (data/reference/etkinlik yok)")
    request = {"id": listing["events"][0]["id"], "date": listing["date"], "lang": "tr"}
    first, second = (client.post("/api/events/calendar", json=request) for _ in range(2))
    assert first.status_code == 200 and first.headers["content-type"].startswith("text/calendar")
    assert first.headers.get("cache-control") == "no-store"
    assert re.search(r"^DTSTART(?:;VALUE=DATE:\d{8}|:\d{8}T\d{6}Z)\r?$", first.text, re.M), "UTC or an all-day date"
    uid = re.findall(r"^UID:.*$", first.text, re.M)
    assert uid and uid == re.findall(r"^UID:.*$", second.text, re.M), "a double click makes the same event"
    assert "@" not in first.text.replace(uid[0], ""), "no e-mail in the file"


@after("G4", "/api/events/calendar", "POST")
def test_deleting_the_account_reports_its_bookings_deleted(client: TestClient) -> None:
    account = sign_in(client, "etkinlik@example.org")
    deleted = client.delete("/api/account", headers=account)
    assert deleted.status_code == 200
    assert isinstance(deleted.json().get("bookings_deleted"), int), "the deletion names what it removed"
