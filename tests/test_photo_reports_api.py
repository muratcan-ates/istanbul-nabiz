"""API, retention, operator-door, and ledger checks for E51."""

from __future__ import annotations

import base64
import json
import pathlib
import sqlite3
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import offline_settings
from fastapi.testclient import TestClient
from nexus_helpers import Clock
from test_photo_image import jpeg

from nabiz.agent import llm
from nabiz.console.access import OperatorAccess
from nabiz.console.app import build_console_app
from nabiz.console.photo_image import MAX_PHOTO_BYTES
from nabiz.console.photo_reports import PHOTO_DISTRICTS, NewPhotoReport, PhotoReportStore
from nabiz.console.photo_reports_api import MAX_BODY_BYTES, photo_report_routes
from nexus_core.ledger import Ledger

OPERATOR_HEADERS = {"X-Nabiz-Operator": "operator-test"}
PHOTO = jpeg()


def put_static_last(app: Any) -> None:
    mount = next(route for route in app.router.routes if getattr(route, "name", None) == "static")
    app.router.routes.remove(mount)
    app.router.routes.append(mount)


def make_client() -> TestClient:
    app = build_console_app(
        settings=offline_settings(),
        llm_config=llm.LlmConfig(),
        access=OperatorAccess(token="operator-test"),
    )
    app.state.nabiz = SimpleNamespace(places=SimpleNamespace(places=[SimpleNamespace(kind="metro_station", name="Kartal")]))
    app.include_router(photo_report_routes)
    put_static_last(app)
    return TestClient(app, base_url="http://127.0.0.1:8090")


@pytest.fixture
def api(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "nexus.db"))
    monkeypatch.setenv("NABIZ_PHOTO_REPORTS_DB_PATH", str(tmp_path / "photo-reports.db"))
    monkeypatch.setenv("NABIZ_PHOTO_REPORTS_PER_HOUR", "3")
    return make_client()


def payload(*, description: str = "Kaldırım taşı yerinden çıktı.", place: dict[str, str] | None = None,
            photo: bytes = PHOTO, consent: bool = True) -> dict[str, Any]:
    return {
        "photo": base64.b64encode(photo).decode("ascii"),
        "category": "pavement",
        "description": description,
        "place": place or {"kind": "station", "name": "Kartal"},
        "lang": "tr",
        "consent": consent,
    }


def test_photo_report_flow_is_private_and_only_the_operator_can_read_photo(api: TestClient, tmp_path: pathlib.Path) -> None:
    description = "Kaldırım bozuk, telefon 05321234567."
    response = api.post("/api/photo-reports", json=payload(description=description))
    assert response.status_code == 201, response.text
    citizen = response.json()
    code = citizen["code"]
    assert len(code) == 8 and citizen["status"] == "new"
    assert "05321234567" not in response.text and "photo" not in citizen
    assert response.headers["cache-control"] == "no-store"
    assert api.get(f"/api/photo-reports/{code}").json()["description"].endswith("[TELEFON].")

    refused = api.get("/api/console/photo-reports")
    assert refused.status_code == 401
    queue = api.get("/api/console/photo-reports", headers=OPERATOR_HEADERS)
    assert queue.status_code == 200 and queue.json()["counts"]["new"] == 1
    item = queue.json()["items"][0]
    assert item["place"] == {"kind": "station", "name": "Kartal"}
    assert item["has_photo"] and "photo" not in item
    fetched = api.get(f"/api/console/photo-reports/{code}/photo", headers=OPERATOR_HEADERS)
    assert fetched.status_code == 200 and fetched.headers["content-type"] == "image/jpeg"
    assert b"Exif" not in fetched.content and b"GPS" not in fetched.content

    for target in ("reviewed", "forwarded", "closed"):
        reason = "Vatandaşla 05321234567 üzerinden görüşüldü." if target == "reviewed" else "İşlem yapıldı."
        changed = api.post(
            f"/api/console/photo-reports/{code}/status", headers=OPERATOR_HEADERS,
            json={"status": target, "reason": reason},
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["ledger_entry_id"] > 0
    assert api.get(f"/api/console/photo-reports/{code}/photo", headers=OPERATOR_HEADERS).status_code == 404
    assert api.get(f"/api/photo-reports/{code}").json()["status"] == "closed"

    ledger = Ledger(tmp_path / "nexus.db")
    entries = ledger.entries(entity_id=f"photo_report:{code}")
    assert [entry.kind for entry in entries] == [
        "photo_report", "photo_report_status", "photo_report_status", "photo_report_status",
    ]
    detail = json.dumps([entry.detail for entry in entries], ensure_ascii=False)
    assert description not in detail and "Kartal" not in detail and "Exif" not in detail and "sha" not in detail
    assert "05321234567" not in detail and ledger.verify().ok
    assert entries[1].detail["masked_count"] == 1


def test_invalid_photo_report_filters_and_status_bodies_are_no_store(api: TestClient) -> None:
    invalid_filter = api.get("/api/console/photo-reports?status=closed", headers=OPERATOR_HEADERS)
    assert invalid_filter.status_code == 422 and invalid_filter.headers["cache-control"] == "no-store"

    invalid_status = api.post(
        "/api/console/photo-reports/23456789/status", headers=OPERATOR_HEADERS, json={"status": "unknown"},
    )
    assert invalid_status.status_code == 422 and invalid_status.headers["cache-control"] == "no-store"

    oversized_status = api.post(
        "/api/console/photo-reports/23456789/status", headers=OPERATOR_HEADERS, content=b"x" * (64 * 1024 + 1),
    )
    assert oversized_status.status_code == 413 and oversized_status.headers["cache-control"] == "no-store"


def test_consent_emergency_limits_places_and_image_types(api: TestClient) -> None:
    no_consent = api.post("/api/photo-reports", json=payload(consent=False))
    assert no_consent.status_code == 400 and no_consent.json()["error"] == "consent_required"

    emergency = api.post("/api/photo-reports", json=payload(description="Yangın var, 112'yi arayın."))
    assert emergency.status_code == 200 and emergency.json()["emergency"] is True
    assert emergency.json()["tel"] == "112"
    assert api.get("/api/console/photo-reports", headers=OPERATOR_HEADERS).json()["items"] == []

    bad_station = api.post("/api/photo-reports", json=payload(place={"kind": "station", "name": "Bilinmeyen"}))
    assert bad_station.status_code == 400 and bad_station.json()["error"] == "unknown_place"
    bad_district = api.post("/api/photo-reports", json=payload(place={"kind": "district", "name": "İstanbul"}))
    assert bad_district.status_code == 400 and bad_district.json()["error"] == "unknown_place"

    svg = api.post("/api/photo-reports", json=payload(photo=b"<svg></svg>"))
    assert svg.status_code == 415 and svg.json()["error"] == "bad_type"


def test_hourly_limit_and_streamed_request_size_are_enforced(api: TestClient) -> None:
    for _ in range(3):
        assert api.post("/api/photo-reports", json=payload()).status_code == 201
    assert api.post("/api/photo-reports", json=payload()).status_code == 429
    assert api.post("/api/photo-reports", content=b"x" * (MAX_BODY_BYTES + 1)).status_code == 413


def test_status_requires_reason_and_rejects_unavailable_transition(api: TestClient) -> None:
    code = api.post("/api/photo-reports", json=payload()).json()["code"]
    missing = api.post(
        f"/api/console/photo-reports/{code}/status", headers=OPERATOR_HEADERS,
        json={"status": "reviewed", "reason": ""},
    )
    assert missing.status_code == 400 and missing.json()["error"] == "reason_required"
    closed = api.post(
        f"/api/console/photo-reports/{code}/status", headers=OPERATOR_HEADERS,
        json={"status": "closed", "reason": "Tamamlandı."},
    )
    assert closed.status_code == 200
    invalid = api.post(
        f"/api/console/photo-reports/{code}/status", headers=OPERATOR_HEADERS,
        json={"status": "reviewed", "reason": "Yeniden aç."},
    )
    assert invalid.status_code == 409 and invalid.json()["error"] == "transition_not_allowed"


@pytest.mark.parametrize("target", ["reviewed", "closed"])
def test_status_and_ledger_change_together_or_not_at_all(
    api: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, target: str,
) -> None:
    code = api.post("/api/photo-reports", json=payload()).json()["code"]
    desk = api.app.state.photo_desk

    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(desk.ledger, "append", broken)
    caplog.set_level("INFO")
    failed = api.post(f"/api/console/photo-reports/{code}/status", headers=OPERATOR_HEADERS,
                      json={"status": target, "reason": "Saha ekibine iletildi."})
    assert failed.status_code == 503 and failed.json()["error"] == "ledger_failed"
    assert failed.headers["cache-control"] == "no-store"
    row = desk.store.get(code)
    assert row["status"] == "new" and len(row["history"]) == 1 and desk.store.photo(code) is not None
    assert code not in "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("nabiz"))
    monkeypatch.undo()
    sealed = api.post(f"/api/console/photo-reports/{code}/status", headers=OPERATOR_HEADERS,
                      json={"status": target, "reason": "Saha ekibine iletildi."})
    assert sealed.status_code == 200 and desk.store.get(code)["status"] == target
    assert desk.ledger.entries()[-1].kind == "photo_report_status"


def test_citizen_withdrawal_removes_row_and_seals_only_the_code(api: TestClient, tmp_path: pathlib.Path) -> None:
    code = api.post("/api/photo-reports", json=payload()).json()["code"]
    deleted = api.delete(f"/api/photo-reports/{code}")
    assert deleted.status_code == 200 and deleted.json() == {"deleted": True}
    assert api.get(f"/api/photo-reports/{code}").status_code == 404
    last = Ledger(tmp_path / "nexus.db").entries()[-1]
    assert last.kind == "photo_report_withdrawn" and last.detail == {"code": code}


def test_options_match_the_citizen_contract(api: TestClient) -> None:
    response = api.get("/api/photo-reports/options")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    body = response.json()
    assert [item["key"] for item in body["categories"]] == ["pavement", "lift", "litter", "lighting", "other"]
    assert body["districts"] == list(PHOTO_DISTRICTS) and len(body["districts"]) == 39
    assert body["limits"] == {"max_bytes": MAX_PHOTO_BYTES, "max_edge": 1600, "text_chars": 280, "ttl_days": 30, "per_hour": 3}


def test_store_purges_expired_reports_and_photo_bytes(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    store = PhotoReportStore(tmp_path / "store.db", clock=clock)
    report = NewPhotoReport(
        category="pavement", place={"kind": "district", "name": "Kartal"}, description="", masked_count=0,
        masked_kinds=(), lang="tr", photo_meta={"type": "jpeg", "bytes": len(PHOTO), "width": 4, "height": 3},
        photo=PHOTO, photo_type="jpeg",
    )
    row = store.create(report)
    assert store.photo(row["code"]) == (PHOTO, "jpeg")
    clock.advance(days=30, seconds=1)
    assert store.get(row["code"]) is None and store.photo(row["code"]) is None
