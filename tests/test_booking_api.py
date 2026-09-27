from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nabiz.console.accounts import AccountStore
from nabiz.console.booking import BookingStore, bookable_libraries, day_plan
from nabiz.console.booking_api import booking_routes
from nabiz.console.citizen_requests import HourlyLimit
from nabiz.console.forbidden_terms import find_forbidden
from nexus_core.stats import ISTANBUL

NOW = dt.datetime(2026, 9, 29, 8, 0, tzinfo=ISTANBUL)
DEVICE_A = "device-alpha-0123456789"
DEVICE_B = "device-bravo-9876543210"


def setup_client(tmp_path, *, limit: HourlyLimit | None = None) -> tuple[TestClient, FastAPI, Any]:
    app = FastAPI()
    app.include_router(booking_routes)
    app.state.booking_store = BookingStore(tmp_path / "bookings.sqlite", clock=lambda: NOW)
    if limit is not None:
        app.state.booking_limit = limit
    client = TestClient(app, base_url="http://example.com")
    library = next(iter(bookable_libraries().values()))
    plan = day_plan(library, NOW)
    day = next(item for item in plan if item.open and any(slot["bookable"] for slot in item.slots))
    slot = next(slot for slot in day.slots if slot["bookable"])
    return client, app, {"library": library.key, "day": day.date, "start": slot["start"]}


def headers(device: str = DEVICE_A) -> dict[str, str]:
    return {"X-Nabiz-Device": device}


def booking_body(choice: dict[str, Any], *, seat: str = "A1", consent: bool = True) -> dict[str, Any]:
    return {**choice, "seat": seat, "consent": consent}


def test_list_detail_and_seat_endpoints_are_recorded_private_responses(tmp_path) -> None:
    client, _, choice = setup_client(tmp_path)
    listed = client.get("/api/booking/libraries")
    assert listed.status_code == 200 and listed.headers["cache-control"] == "no-store"
    assert listed.json()["example"] is True and "örnek" in listed.json()["notice"].lower()
    assert choice["library"] in {item["key"] for item in listed.json()["libraries"]}

    detail = client.get(f"/api/booking/libraries/{choice['library']}")
    assert detail.status_code == 200 and detail.headers["cache-control"] == "no-store"
    body = detail.json()
    assert body["provenance"]["mode"] == "recorded"
    assert body["room"]["capacity"] == 36 and body["limits"]["ttl_days"] == 30
    assert body["notice"] == "Örnek: İBB kütüphane randevu sistemine bağlı değildir."
    assert body["notes"][0].startswith("Salon planı ve kapasite örnektir")

    seats = client.get("/api/booking/seats", params=choice, headers=headers())
    assert seats.status_code == 200 and seats.headers["cache-control"] == "no-store"
    assert seats.json()["taken"] == [] and seats.json()["mine"] is None
    assert seats.json()["end"] > seats.json()["start"]


def test_consent_is_required_before_booking_rows_and_missing_holder_mine_is_empty(tmp_path) -> None:
    client, app, choice = setup_client(tmp_path)
    response = client.post("/api/booking", json=booking_body(choice, consent=False), headers=headers())
    assert response.status_code == 400 and response.json()["error"] == "consent_required"
    assert response.headers["cache-control"] == "no-store"
    assert app.state.booking_store.mine("absent") == []
    with client:
        absent = client.post("/api/booking", json=booking_body(choice))
        assert absent.status_code == 400 and absent.json()["error"] == "no_holder"
        mine = client.get("/api/booking/mine")
        assert mine.status_code == 200 and mine.json() == {"bookings": [], "held_by": None}


def test_conflict_owner_scope_and_cancel_api(tmp_path) -> None:
    client, app, choice = setup_client(tmp_path)
    created = client.post("/api/booking", json=booking_body(choice), headers=headers())
    assert created.status_code == 201, created.text
    assert created.headers["cache-control"] == "no-store"
    assert created.json()["held_by"] == "device" and created.json()["example"] is True
    code = created.json()["code"]

    conflict = client.post("/api/booking", json=booking_body(choice), headers=headers(DEVICE_B))
    assert conflict.status_code == 409 and conflict.json()["error"] == "seat_taken"
    same_slot = client.post("/api/booking", json=booking_body(choice, seat="A2"), headers=headers())
    assert same_slot.status_code == 409 and same_slot.json()["error"] == "slot_held"
    assert client.get("/api/booking/seats", params=choice, headers=headers(DEVICE_B)).json()["taken"] == ["A1"]

    mine = client.get("/api/booking/mine", headers=headers())
    assert mine.status_code == 200 and mine.json()["bookings"][0]["code"] == code
    forbidden = client.delete(f"/api/booking/{code}", headers=headers(DEVICE_B))
    assert forbidden.status_code == 403 and forbidden.json()["error"] == "not_yours"
    still_there = client.get("/api/booking/seats", params=choice, headers=headers())
    assert still_there.json()["taken"] == ["A1"]
    deleted = client.delete(f"/api/booking/{code}", headers=headers())
    assert deleted.status_code == 200 and deleted.json()["cancelled"] is True
    assert client.get("/api/booking/seats", params=choice, headers=headers()).json()["taken"] == []
    assert app.state.booking_store.mine(app.state.booking_store.holder_of("device", DEVICE_A)) == []


def test_same_example_account_is_shared_across_devices(tmp_path) -> None:
    client, app, choice = setup_client(tmp_path)
    accounts = AccountStore(tmp_path / "accounts.sqlite")
    account, token = accounts.create(email="kisi@example.com", provider="ibb", consent=True)
    app.state.accounts = accounts
    created = client.post(
        "/api/booking", json=booking_body(choice), headers={**headers(DEVICE_A), "X-Nabiz-Account": token}
    )
    assert created.status_code == 201 and created.json()["held_by"] == "account"
    second_device = {**headers(DEVICE_B), "X-Nabiz-Account": token}
    assert client.get("/api/booking/mine", headers=second_device).json()["bookings"][0]["code"] == created.json()["code"]
    removed = client.delete(f"/api/booking/{created.json()['code']}", headers=second_device)
    assert removed.status_code == 200
    accounts.close()


def test_unknown_library_bad_seat_not_offered_and_code_statuses(tmp_path) -> None:
    client, _, choice = setup_client(tmp_path)
    unknown = {**booking_body(choice), "library": "does-not-exist"}
    assert client.post("/api/booking", json=unknown, headers=headers()).status_code == 404
    bad_seat = client.post("/api/booking", json=booking_body(choice, seat="Z9"), headers=headers())
    assert bad_seat.status_code == 422 and bad_seat.json()["error"] == "bad_seat"
    wrong_day = {**booking_body(choice), "day": "2026-10-20"}
    assert client.post("/api/booking", json=wrong_day, headers=headers()).json()["error"] == "not_offered"
    assert client.delete("/api/booking/bad", headers=headers()).status_code == 404


def test_hourly_limit_uses_configured_value(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NABIZ_BOOKING_PER_HOUR", "2")
    client, _, choice = setup_client(tmp_path)
    for _ in range(2):
        result = client.post("/api/booking", json=booking_body(choice), headers=headers())
        assert result.status_code == 201
        assert client.delete(f"/api/booking/{result.json()['code']}", headers=headers()).status_code == 200
    limited = client.post("/api/booking", json=booking_body(choice), headers=headers())
    assert limited.status_code == 429 and limited.json()["error"] == "too_many"


def test_active_limit_is_returned_with_limit_value(tmp_path) -> None:
    client, _, _ = setup_client(tmp_path)
    library = next(
        item for item in bookable_libraries().values()
        if sum(slot["bookable"] for day in day_plan(item, NOW) for slot in day.slots) >= 3
    )
    open_choices = [
        {"library": library.key, "day": day.date, "start": slot["start"]}
        for day in day_plan(library, NOW) for slot in day.slots if slot["bookable"]
    ][:3]
    for index, choice in enumerate(open_choices):
        result = client.post("/api/booking", json=booking_body(choice, seat=f"A{index + 1}"), headers=headers())
        if index < 2:
            assert result.status_code == 201
        else:
            assert result.status_code == 409
            assert result.json()["error"] == "active_limit" and result.json()["limit"] == 2


def test_public_api_copy_has_no_forbidden_terms_or_long_dash(tmp_path) -> None:
    client, _, choice = setup_client(tmp_path)
    responses = [
        client.get("/api/booking/libraries"),
        client.get(f"/api/booking/libraries/{choice['library']}"),
        client.get("/api/booking/libraries/unknown-library"),
        client.get("/api/booking/seats", params=choice, headers=headers()),
        client.get("/api/booking/seats", params={**choice, "day": "2026-10-20"}),
        client.post("/api/booking", json=booking_body(choice, consent=False), headers=headers()),
        client.post("/api/booking", json=booking_body(choice), headers=headers()),
        client.post("/api/booking", json=booking_body({**choice, "library": "unknown-library"}), headers=headers()),
        client.post("/api/booking", json=booking_body({**choice, "day": "2026-10-20"}), headers=headers()),
        client.post("/api/booking", json=booking_body(choice, seat="Z9"), headers=headers()),
        client.get("/api/booking/mine"),
        client.delete("/api/booking/not-a-code", headers=headers()),
    ]
    for response in responses:
        body = response.text
        assert "—" not in body and "–" not in body and "canlı" not in body.lower()
        assert find_forbidden(body) == ()
