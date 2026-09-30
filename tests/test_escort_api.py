"""HTTP contracts for accessible-support requests."""

from __future__ import annotations

import datetime as dt
import json
import logging
import pathlib
from zoneinfo import ZoneInfo

from conftest import offline_settings
from fastapi.testclient import TestClient
from test_report_map_api import put_static_last

from nabiz.console.access import OperatorAccess
from nabiz.console.app import build_console_app
from nabiz.console.citizen_requests import HourlyLimit
from nabiz.console.escort_api import escort_routes
from nabiz.console.escort_request import EscortStore, escort_path


def valid_body(**changes):
    tomorrow = dt.datetime.now(ZoneInfo("Europe/Istanbul")).date() + dt.timedelta(days=5)
    return {
        "need": "wheelchair",
        "assistance": ["meet_at_entrance", "transfer"],
        "date": tomorrow.isoformat(),
        "time": "09:30",
        "window_min": 60,
        "meet_station": "Kadıköy",
        "to_station": "Levent",
        "return_kind": "same_day",
        "return_time": "17:00",
        "companion": False,
        "note": "",
        "consent": True,
        **changes,
    }


def build_client(tmp_path: pathlib.Path, *, token: str | None = None):
    app = build_console_app(settings=offline_settings(), access=OperatorAccess(token=token))
    app.include_router(escort_routes)
    put_static_last(app)
    app.state.escort_store = EscortStore(tmp_path / "escort.db")
    app.state.escort_limit = HourlyLimit(3)
    return TestClient(app, base_url="http://127.0.0.1:8090")


def test_options_serve_station_source_and_153_contract(tmp_path):
    with build_client(tmp_path) as client:
        response = client.get("/api/escort/options")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    body = response.json()
    assert len(body["stations"]) > 200 and len(set(body["stations"])) == len(body["stations"])
    assert len(body["sources"]) == 5 and body["official"]["call"] == "153"


def test_options_return_stations_missing_when_csv_is_empty(tmp_path, monkeypatch):
    empty = tmp_path / "empty.csv"
    empty.write_text("name,lat,lon,kind,district\n", encoding="utf-8")
    monkeypatch.setenv("NABIZ_PLACES_CSV", str(empty))
    with build_client(tmp_path) as client:
        response = client.get("/api/escort/options")
    assert response.status_code == 503 and response.json()["error"] == "stations_missing"
    assert response.headers["cache-control"] == "no-store"


def test_create_requires_consent_validates_rate_limits_and_returns_normal_code(tmp_path):
    with build_client(tmp_path) as client:
        denied = client.post("/api/escort/requests", json=valid_body(consent=False))
        invalid = client.post("/api/escort/requests", json=valid_body(date="yesterday"))
        accepted = [client.post("/api/escort/requests", json=valid_body()) for _ in range(3)]
        limited = client.post("/api/escort/requests", json=valid_body())
    assert denied.status_code == 400 and denied.json()["error"] == "consent_required"
    assert invalid.status_code == 400 and "tarih" in invalid.json()["message"].lower()
    assert all(response.status_code == 201 for response in accepted)
    assert all(len(response.json()["code"]) == 8 for response in accepted)
    assert limited.status_code == 429 and limited.json()["error"] == "too_many"
    assert all(response.headers["cache-control"] == "no-store" for response in [denied, invalid, *accepted, limited])


def test_emergency_note_returns_the_153_card_without_storing(tmp_path):
    with build_client(tmp_path) as client:
        response = client.post("/api/escort/requests", json=valid_body(note="yangın var, nefes alamıyor"))
        queue = client.get("/api/console/escort")
    assert response.status_code == 200 and response.json()["emergency"] is True
    assert response.json()["tel"] == "153"
    assert queue.json()["items"] == []


def test_read_not_found_bad_code_and_valid_request(tmp_path):
    with build_client(tmp_path) as client:
        unknown = client.get("/api/escort/requests/K7M2QX9P")
        malformed = client.get("/api/escort/requests/bad")
        created = client.post("/api/escort/requests", json=valid_body())
        fetched = client.get(f"/api/escort/requests/{created.json()['code']}")
    assert unknown.status_code == malformed.status_code == 404
    assert fetched.status_code == 200 and fetched.json()["status"] == "received"
    assert "signal_id" not in fetched.json() and "operator" not in fetched.json()


def test_citizen_cancel_is_one_way_and_operator_cannot_move_cancelled(tmp_path):
    with build_client(tmp_path) as client:
        created = client.post("/api/escort/requests", json=valid_body()).json()
        code = created["code"]
        cancelled = client.post(f"/api/escort/requests/{code}/cancel")
        repeated = client.post(f"/api/escort/requests/{code}/cancel")
        operator = client.post(f"/api/console/escort/{code}/move", json={"to": "seen"})
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert repeated.status_code == operator.status_code == 409


def test_operator_moves_require_agency_and_close_note_and_stay_honest(tmp_path):
    with build_client(tmp_path) as client:
        created = client.post("/api/escort/requests", json=valid_body()).json()
        code = created["code"]
        seen = client.post(f"/api/console/escort/{code}/move", json={"to": "seen"})
        no_agency = client.post(f"/api/console/escort/{code}/move", json={"to": "referred_official"})
        unknown_agency = client.post(
            f"/api/console/escort/{code}/move", json={"to": "referred_official", "agency_id": "invented"}
        )
        referred = client.post(f"/api/console/escort/{code}/move", json={"to": "referred_official", "agency_id": "cozum_153"})
        citizen = client.get(f"/api/escort/requests/{code}")
        no_note = client.post(f"/api/console/escort/{code}/move", json={"to": "closed"})
    assert seen.status_code == 200 and seen.json()["status"] == "seen"
    assert no_agency.status_code == unknown_agency.status_code == no_note.status_code == 400
    assert referred.status_code == 200 and referred.json()["status"] == "referred_official"
    assert citizen.json()["agency"]["name"] == "153 Çözüm Merkezi"
    assert "teyit almadı" in citizen.json()["status_text"]
    assert referred.headers["cache-control"] == "no-store"


def test_console_endpoints_remain_behind_operator_access(tmp_path):
    with build_client(tmp_path, token="t") as client:
        denied = client.get("/api/console/escort")
        allowed = client.get("/api/console/escort", headers={"X-Nabiz-Operator": "t"})
    assert denied.status_code == 401
    assert allowed.status_code == 200 and allowed.json()["items"] == []


def test_all_api_responses_are_no_store_and_citizen_never_sees_raw_note(tmp_path):
    with build_client(tmp_path) as client:
        created = client.post("/api/escort/requests", json=valid_body(note="murat@example.com"))
        read = client.get(f"/api/escort/requests/{created.json()['code']}")
        unknown = client.get("/api/escort/requests/XXXXXXXX")
    for response in (created, read, unknown):
        assert response.headers["cache-control"] == "no-store"
    assert "murat@example.com" not in json.dumps(created.json(), ensure_ascii=False)


def test_feature_logger_does_not_emit_code_note_station_or_need(tmp_path, caplog):
    with build_client(tmp_path) as client:
        created = client.post("/api/escort/requests", json=valid_body(note="0505 123 45 67"))
        code = created.json()["code"]
        with caplog.at_level(logging.INFO, logger="nabiz.console.escort"):
            client.get(f"/api/escort/requests/{code}")
            client.post(f"/api/console/escort/{code}/move", json={"to": "seen"})
    route_logs = " ".join(record.getMessage() for record in caplog.records if record.name == "nabiz.console.escort")
    assert all(value not in route_logs for value in (code, "0505", "Kadıköy", "wheelchair"))


def test_database_path_uses_only_the_given_application_store(tmp_path):
    custom = tmp_path / "custom.db"
    assert escort_path({"NABIZ_ESCORT_DB_PATH": str(custom)}) == custom
