"""P07: one citizen-facing report code from photo (E51) to timeline (E66), incident file (E67) and outcomes (E75)."""

from __future__ import annotations

import base64
import datetime as dt
import logging
import pathlib
from typing import Any

import pytest
from fastapi.testclient import TestClient
from nexus_helpers import Clock, build_engine
from test_photo_image import jpeg
from test_report_timeline_api import create_report
from test_report_triage import report_app

from nabiz.console import incident
from nabiz.console.access import OperatorAccess
from nabiz.console.outcomes import SnapshotStore
from nabiz.console.photo_reports import STATUS_TRANSITIONS, NewPhotoReport, PhotoReportStore
from nabiz.console.report_link import (
    CARD_STATE_BY_PHOTO_STATUS,
    CARD_STATE_BY_STAGE,
    LinkRefused,
    card_from_report,
    card_state,
    link_photo,
    photo_ref,
    photos_for_report,
    report_for_photo,
    unlink_photo,
)
from nabiz.console.report_timeline import STAGES, WAITING_ON, TimelineStore

# Copied from SOZLESME v0 (docs/contracts/chat-card.md on the P01 branch); D2 swaps this for
# chat_cards.validate_card(from_v0(card)).
CARD_V0_TYPES = ("route", "map", "event", "calendar_draft", "photo_report", "status", "info", "memory")
CARD_V0_STATUSES = ("preparing", "needs_input", "ready", "awaiting_confirmation", "done", "unavailable", "error")
CARD_V0_ACTIONS = {
    "use_location": ("device", True), "type_place": ("view", False), "expand_map": ("view", False),
    "listen": ("view", False), "remember_here": ("device", True), "remember_always": ("device", True),
    "change": ("view", False), "forget": ("device", False), "save_calendar": ("nabiz", True),
    "export_ics": ("device", False), "review_report": ("view", False), "send": ("nabiz", True),
    "open_official": ("external", False), "add_outlook": ("external", True), "confirm_resolved": ("nabiz", True),
    "reopen": ("nabiz", True), "cancel": ("nabiz", True), "appeal": ("nabiz", True), "share": ("external", True),
}
PHOTO_REPORT_STATES = ("received", "reviewed", "forwarded", "answered", "citizen_confirmed", "reopened", "closed")
PHOTO_REPORT_FIELDS = {"report_code", "photo_code", "category", "place", "state", "waiting_on", "timeline", "has_photo",
                       "simulated"}
HEADERS = {"X-Nabiz-Operator": "t"}
T0 = dt.datetime(2026, 9, 25, 9, 0, tzinfo=dt.UTC)


def _photo(store: PhotoReportStore, place: dict[str, str] | None = None) -> dict[str, Any]:
    return store.create(NewPhotoReport(
        category="lift", place=place or {"kind": "district", "name": "Kartal"}, description="", masked_count=0,
        masked_kinds=(), lang="tr", photo_meta={"type": "jpeg"}, photo=b"x", photo_type="jpeg",
    ))


def _timeline(tmp_path: pathlib.Path, code: str = "ABCDEFGH", signal_id: str = "sig-1") -> TimelineStore:
    store = TimelineStore(tmp_path / "timeline.db", clock=Clock())
    store.ensure(code, signal_id, "Kartal", "not_working", T0)
    return store


def assert_card_v0(card: dict[str, Any]) -> None:
    assert card["v"] == 0 and card["type"] in CARD_V0_TYPES and card["type"] == "photo_report"
    assert card["status"] in CARD_V0_STATUSES
    assert set(card["data"]) == PHOTO_REPORT_FIELDS
    body = card["data"]
    assert body["state"] in PHOTO_REPORT_STATES and body["simulated"] is True
    assert body["waiting_on"] in {"citizen", "operator", None}
    assert body["place"]["kind"] in {"station", "district"} and isinstance(body["place"]["name"], str)
    assert all(set(step) == {"at", "step", "by"} and step["by"] in {"citizen", "operator", "system"}
               for step in body["timeline"])
    assert card["linked"] == {"event_id": None, "report_code": body["report_code"], "operation_id": None}
    assert card["sensitive"] is False and len(card["title"]) <= 120
    for action in card["actions"]:
        kind, consent = CARD_V0_ACTIONS[action["id"]]
        assert action["kind"] == kind and action["requires_consent"] is (consent or action["requires_consent"])
        assert len(action["label"]) <= 40
        if kind in {"view", "device"}:
            assert action["operation_id"] is None
        else:
            assert action["operation_id"] and action["operation_id"].startswith("op-")
    text = str(card)
    assert "/photo" not in text and "photo_url" not in text and "base64" not in text


def test_one_photo_ref_definition_is_shared_with_the_incident_file() -> None:
    assert incident.photo_ref is photo_ref
    assert photo_ref("ABCDEFGH") == photo_ref("ABCDEFGH") and len(photo_ref("ABCDEFGH")) == len("photo:") + 12
    [member] = incident.photo_members([{"code": "ABCDEFGH", "place": {"kind": "station", "name": "Kartal"}}])
    assert member["ref"] == photo_ref("ABCDEFGH")


def test_state_mapping_is_one_total_table() -> None:
    assert set(CARD_STATE_BY_STAGE) == {*STAGES, "reopened"} == set(WAITING_ON) - {"none"} | {"confirmed"}
    assert set(CARD_STATE_BY_PHOTO_STATUS) == set(STATUS_TRANSITIONS)
    assert set(CARD_STATE_BY_STAGE.values()) | set(CARD_STATE_BY_PHOTO_STATUS.values()) == set(PHOTO_REPORT_STATES)
    # "Çözüldü" only through the citizen's confirmation, never an operator step.
    assert [stage for stage, state in CARD_STATE_BY_STAGE.items() if state == "citizen_confirmed"] == ["confirmed"]
    assert card_state("confirmed") == "citizen_confirmed" and card_state(photo_status="closed") == "closed"
    assert card_state("resolution_reported", "closed") == "answered"
    with pytest.raises(ValueError):
        card_state()


@pytest.mark.parametrize("stage", [*STAGES, "reopened"])
def test_card_matches_the_v0_contract_at_every_stage(stage: str) -> None:
    row = {"code": "ABCDEFGH", "station": "Kartal", "stage": stage, "updated_at": T0.isoformat(),
           "data": {"history": [{"stage": "recorded", "at": T0.isoformat(), "by": "system"},
                                {"by": "citizen", "step": "photo_added", "photo_ref": photo_ref("P"), "at": T0.isoformat()}],
                    "photo_refs": [photo_ref("P")]}}
    for lang in ("tr", "en"):
        card = card_from_report("ABCDEFGH", lang=lang, timeline=row)
        assert_card_v0(card)
        body = card["data"]
        assert body["photo_code"] is None and body["has_photo"] is True
        assert body["state"] == CARD_STATE_BY_STAGE[stage]
        assert [step["step"] for step in body["timeline"]] == ["recorded", "photo_added"]
        ids = [action["id"] for action in card["actions"]]
        assert ids[0] == "review_report"
        assert ("confirm_resolved" in ids) is (stage == "resolution_reported")
    with pytest.raises(ValueError):
        card_from_report("ABCDEFGH", lang="de", timeline=row)


def test_link_is_atomic_idempotent_and_refuses_other_reports(tmp_path: pathlib.Path) -> None:
    photos = PhotoReportStore(tmp_path / "photos.db")
    timeline = _timeline(tmp_path)
    timeline.ensure("BCDEFGHJ", "sig-2", "Pendik", "not_working", T0)
    photo = _photo(photos)
    assert photo["linked_report_code"] is None and photo["linked_signal_id"] is None
    assert link_photo(photo["code"], None, None, photos_db=photos.path, timeline_db=timeline.path)["linked"] is False
    assert report_for_photo(photo["code"], photos_db=photos.path) is None
    kwargs = {"photos_db": photos.path, "timeline_db": timeline.path}
    with pytest.raises(LinkRefused) as refused:
        link_photo(photo["code"], "ABCDEFGH", "sig-other", **kwargs)
    assert refused.value.status == 403 and refused.value.reason == "report_mismatch"
    assert link_photo(photo["code"], "ABCDEFGH", "sig-1", **kwargs)["linked"] is True
    assert link_photo(photo["code"], "ABCDEFGH", "sig-1", **kwargs)["linked"] is True
    with pytest.raises(LinkRefused) as refused:
        link_photo(photo["code"], "BCDEFGHJ", "sig-2", **kwargs)
    assert (refused.value.status, refused.value.reason) == (403, "already_linked")
    assert report_for_photo(photo["code"], photos_db=photos.path) == {"report_code": "ABCDEFGH", "signal_id": "sig-1"}
    assert photos_for_report("ABCDEFGH", photos_db=photos.path) == [photo["code"]]
    row = timeline.get("ABCDEFGH")
    assert row["data"]["photo_refs"] == [photo_ref(photo["code"])]
    assert [event.get("step") for event in row["data"]["history"]].count("photo_added") == 1
    assert photo["code"] not in timeline.path.read_bytes().decode("latin-1")
    assert timeline.get("BCDEFGHJ")["data"].get("photo_refs") is None
    assert unlink_photo(photo["code"], "ABCDEFGH", timeline_db=timeline.path) is True
    assert timeline.get("ABCDEFGH")["data"]["photo_refs"] == []
    with pytest.raises(LinkRefused) as refused:
        link_photo("ZZZZZZZZ", "ABCDEFGH", "sig-1", **kwargs)
    assert refused.value.status == 404


def test_confirmed_report_takes_no_photo_and_a_failed_write_rolls_back_both(tmp_path: pathlib.Path) -> None:
    photos = PhotoReportStore(tmp_path / "photos.db")
    timeline = _timeline(tmp_path)
    for actor, step in (("operator", "reviewing"), ("operator", "resolution_reported")):
        timeline.apply("ABCDEFGH", actor, step, to=step, text="Bakım tamamlandı.")
    timeline.apply("ABCDEFGH", "citizen", "fixed")
    photo = _photo(photos)
    with pytest.raises(LinkRefused) as refused:
        link_photo(photo["code"], "ABCDEFGH", "sig-1", photos_db=photos.path, timeline_db=timeline.path)
    assert (refused.value.status, refused.value.reason) == (422, "report_closed")
    assert photos.get(photo["code"])["linked_report_code"] is None

    other = TimelineStore(tmp_path / "other.db", clock=Clock())
    other.ensure("CDEFGHJK", "sig-3", "Kartal", "not_working", T0)
    with other._connect() as conn:  # a trigger that fails the timeline half of the one transaction
        conn.execute("CREATE TRIGGER refuse BEFORE UPDATE ON report_timeline BEGIN SELECT RAISE(ABORT, 'x'); END")
    with pytest.raises(Exception, match="x"):
        link_photo(photo["code"], "CDEFGHJK", "sig-3", photos_db=photos.path, timeline_db=other.path)
    assert photos.get(photo["code"])["linked_report_code"] is None


@pytest.fixture
def chain(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    clock = Clock()
    for name, file in (("NEXUS_DB_PATH", "nexus.db"), ("NABIZ_PHOTO_REPORTS_DB_PATH", "photos.db"),
                       ("NABIZ_REPORT_TIMELINE_DB_PATH", "timeline.db"), ("NABIZ_INCIDENTS_DB_PATH", "incidents.db"),
                       ("NABIZ_OUTCOMES_DB_PATH", "outcomes.db")):
        monkeypatch.setenv(name, str(tmp_path / file))
    monkeypatch.setenv("NABIZ_PHOTO_REPORTS_PER_HOUR", "20")
    engine = build_engine(tmp_path, clock)
    app, _published = report_app(engine, clock, access=OperatorAccess(token="t"))
    app.state.report_timeline = TimelineStore(tmp_path / "timeline.db", clock=clock)
    app.state.outcome_snapshots = SnapshotStore(tmp_path / "outcomes.db", clock=clock)
    with TestClient(app, base_url="http://127.0.0.1:8090") as client:
        yield client, engine, clock


def _send_photo(client: TestClient, report_code: str | None = None) -> Any:
    body = {"photo": base64.b64encode(jpeg()).decode("ascii"), "category": "lift", "description": "",
            "place": {"kind": "district", "name": "Kartal"}, "lang": "tr", "consent": True}
    if report_code is not None:
        body["report_code"] = report_code
    return client.post("/api/photo-reports", json=body)


def server_log(caplog: pytest.LogCaptureFixture) -> str:
    """The app's own log lines; the test client's httpx logger prints the URL it was given."""
    return "\n".join(record.getMessage() for record in caplog.records if record.name.startswith("nabiz"))


def _board_o3(client: TestClient) -> tuple[dict[str, Any], dict[str, Any]]:
    board = client.get("/api/console/outcomes?days=30", headers=HEADERS).json()["board"]
    group = next(item for item in board["groups"] if item["key"] == "O3")
    return group["metrics"][0], group["counts"]


def test_one_code_from_photo_to_incident_to_citizen_confirmation(chain, caplog) -> None:
    client, engine, clock = chain
    caplog.set_level(logging.INFO)
    code = create_report(client, engine, clock)
    sent = _send_photo(client, code)
    assert sent.status_code == 201, sent.text
    photo = sent.json()
    assert photo["linked_report_code"] == code and photo["photo_ref"] == photo_ref(photo["code"])
    assert_card_v0(photo["card"])
    assert photo["card"]["data"]["photo_code"] == photo["code"] and photo["card"]["data"]["has_photo"] is True

    citizen = client.get(f"/api/report/timeline/{code}").json()
    assert citizen["has_photo"] is True and citizen["photo_refs"] == [photo["photo_ref"]]
    assert photo["code"] not in str(citizen) and citizen["card"]["data"]["photo_code"] is None
    assert any(event.get("step") == "photo_added" for event in citizen["history"])

    listing = client.get("/api/console/incidents", headers=HEADERS).json()
    assert len(listing["items"]) == 1 and listing["items"][0]["members"] == {
        "reports": 1, "people": 1, "photos": 1, "equipment": 0}
    detail = client.get(f"/api/console/incidents/{listing['items'][0]['id']}", headers=HEADERS).json()
    assert detail["report_codes"] == [code]
    assert detail["members"]["photos"][0]["report_code"] == code
    assert detail["members"]["photos"][0]["linked_ref"] == detail["members"]["reports"][0]["ref"]

    url = f"/api/console/report-timeline/{code}/advance"
    assert client.post(url, headers=HEADERS, json={"to": "reviewing"}).status_code == 200
    answered = client.post(url, headers=HEADERS, json={"to": "resolution_reported", "note": "Bakım tamamlandı."})
    assert answered.status_code == 200 and answered.json()["ledger_entry_id"]
    assert client.post(url, headers=HEADERS, json={"to": "confirmed"}).status_code == 409
    card = client.get(f"/api/report/timeline/{code}").json()["card"]
    assert card["data"]["state"] == "answered" and card["status"] == "awaiting_confirmation"
    assert {action["id"] for action in card["actions"]} == {"review_report", "confirm_resolved", "reopen"}
    metric, counts = _board_o3(client)
    assert (metric["numerator"], metric["denominator"]) == (0, 1)

    confirmed = client.post(f"/api/report/timeline/{code}/respond", json={"action": "fixed"})
    assert confirmed.status_code == 200 and confirmed.json()["stage"] == "confirmed"
    assert confirmed.json()["card"]["data"]["state"] == "citizen_confirmed"
    metric, counts = _board_o3(client)
    assert (metric["numerator"], metric["denominator"]) == (1, 1)
    assert counts["reports"] == 1 and counts["with_photo"] == 1
    closed = _send_photo(client, code)
    assert closed.status_code == 422 and closed.json()["error"] == "report_closed"

    messages = server_log(caplog)
    assert code not in messages and photo["code"] not in messages
    for template in ("/api/photo-reports ", "/api/report/timeline/{code}", "/api/console/report-timeline/{code}/advance",
                     "/api/report/timeline/{code}/respond", "/api/console/incidents/{incident_id}"):
        assert template in messages


def test_other_codes_are_refused_and_the_console_stays_behind_its_door(chain, caplog) -> None:
    client, engine, clock = chain
    caplog.set_level(logging.INFO)
    first = create_report(client, engine, clock)
    clock.advance(minutes=31)
    second = create_report(client, engine, clock, kind="data_wrong")
    assert first != second
    linked = _send_photo(client, first).json()
    standalone = _send_photo(client).json()
    assert standalone["linked_report_code"] is None and "card" not in standalone

    moved = client.post(f"/api/photo-reports/{linked['code']}/link", json={"report_code": second})
    assert moved.status_code == 403 and moved.json()["error"] == "already_linked"
    assert moved.headers["cache-control"] == "no-store"
    for raw, status, error in (("23456789", 403, "report_mismatch"), ("x!", 422, "invalid_report_code")):
        refused = client.post(f"/api/photo-reports/{standalone['code']}/link", json={"report_code": raw})
        assert (refused.status_code, refused.json()["error"]) == (status, error)
        refused = _send_photo(client, raw)
        assert (refused.status_code, refused.json()["error"]) == (status, error)
    assert client.get(f"/api/report/timeline/{second}").json()["photo_refs"] == []
    ok = client.post(f"/api/photo-reports/{standalone['code']}/link", json={"report_code": second})
    assert ok.status_code == 200 and ok.json()["linked_report_code"] == second
    assert client.post(f"/api/photo-reports/{standalone['code']}/link", json={"report_code": second}).status_code == 200
    assert client.get(f"/api/report/timeline/{first}").json()["photo_refs"] == [linked["photo_ref"]]

    assert client.delete(f"/api/photo-reports/{standalone['code']}").status_code == 200
    assert client.get(f"/api/report/timeline/{second}").json()["has_photo"] is False

    for path in ("/api/console/photo-reports", "/api/console/report-timeline", "/api/console/incidents",
                 "/api/console/outcomes", f"/api/console/photo-reports/{linked['code']}/photo"):
        refused = client.get(path)
        assert refused.status_code == 401 and refused.headers["cache-control"] == "no-store", path
    refused = client.post(f"/api/console/report-timeline/{first}/advance", json={"to": "reviewing"})
    assert refused.status_code == 401 and refused.headers["cache-control"] == "no-store"

    messages = server_log(caplog)
    for secret in (first, second, linked["code"], standalone["code"]):
        assert secret not in messages
    assert "/api/photo-reports/{code}/link" in messages and "/api/console/photo-reports/{code}/photo" in messages
