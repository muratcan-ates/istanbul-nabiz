from __future__ import annotations

import datetime as dt
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nabiz.console.citizen_requests import HourlyLimit
from nabiz.console.outage_watch import OutageStore
from nabiz.console.outage_watch_api import OutageDesk, outage_routes
from nexus_core.ledger import Ledger

TEST_EMAIL = "someone" + "@example.test"


class MutableClock:
    def __init__(self) -> None:
        self.value = dt.datetime(2026, 9, 27, 12, 0, tzinfo=dt.UTC)

    def __call__(self) -> dt.datetime:
        return self.value

    def advance(self, **parts: int) -> None:
        self.value += dt.timedelta(**parts)


def client_for(tmp_path, *, limit: int = 3):
    clock = MutableClock()
    store = OutageStore(tmp_path / "outage.db", clock=clock)
    ledger = Ledger(tmp_path / "ledger.db", clock=clock)
    app = FastAPI()
    app.include_router(outage_routes)
    app.state.outage_desk = OutageDesk(store, ledger, HourlyLimit(limit))
    return TestClient(app), clock, store, ledger


def report_body(**changes):
    return {
        "district": "Kadıköy",
        "neighbourhood": "Caferağa",
        "consent": True,
        "announced_end": "14:00",
        "note": "",
        "lang": "tr",
        **changes,
    }


def test_info_is_sourced_and_history_matches_only_the_selected_area(tmp_path) -> None:
    client, _, _, _ = client_for(tmp_path)
    response = client.get("/api/outage-watch/info")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=300"
    body = response.json()
    assert body["official"]["status"] == "not_connected" and body["official"]["list"] is None
    assert body["official"]["captured_at"] == "2026-09-27T00:39:17+00:00"
    assert body["gas"]["status"] == "no_source"
    assert body["notes"]["not_official"] == "Resmî İBB hizmeti değildir."
    assert len(body["districts"]) == 39
    assert any(quote["id"] == "alo_185" and quote["text"] == "Su Kesintisi Öğrenme" for quote in body["official"]["quotes"])
    assert all("igdas" not in quote.get("source_url", "").lower() for quote in body["official"]["quotes"])
    # No emergency line is handed to the page (owner's decision, 30 Sep 2026): only the no-source line, with 153.
    assert [line["id"] for line in body["gas"]["lines"]] == ["no_gas_source"]
    served_gas = json.dumps(body["gas"], ensure_ascii=False)
    assert "112" not in served_gas and "187" not in served_gas and "153" in served_gas
    assert body["history"]["source_records"] == 6410
    history = client.get("/api/outage-watch/history", params={"district": "Kadıköy", "neighbourhood": "caferaga"}).json()
    assert history["area"]["count"] == 28
    assert history["period"] == "2023-2024"
    assert (
        client.get("/api/outage-watch/history", params={"district": "Kadıköy", "neighbourhood": "olmayan mahalle"}).json()["area"]
        is None
    )


def test_consent_validation_emergency_masking_repeat_seen_and_expiry(tmp_path) -> None:
    client, clock, store, ledger = client_for(tmp_path)
    missing_consent = client.post("/api/outage-watch/reports", json=report_body(consent=False))
    assert missing_consent.status_code == 400 and missing_consent.json()["error"] == "consent_required"
    assert client.post("/api/outage-watch/reports", json=report_body(district="İstanbul")).status_code == 400
    pii = client.post("/api/outage-watch/reports", json=report_body(neighbourhood="555 123 45 67"))
    assert pii.status_code == 400 and "yalnız mahalle" in pii.json()["message"]
    emergency = client.post("/api/outage-watch/reports", json=report_body(note="Gaz kokusu var"))
    assert emergency.status_code == 200 and emergency.json()["emergency"] is True
    assert emergency.json()["tel"] == "153" and store.items() == []

    created = client.post("/api/outage-watch/reports", json=report_body(note=TEST_EMAIL))
    assert created.status_code == 201
    view = created.json()
    assert view["status"] == "waiting" and view["confirmations"][0]["label"] == "Siz bildirdiniz"
    assert view["note_masked"] and TEST_EMAIL not in json.dumps(view)
    assert not {"signal_id", "client", "client_host", "operator", "device_id"} & set(view)
    code = view["code"]
    again = {"consent": True, "announced_end": "15:10", "note": ""}
    too_soon = client.post(f"/api/outage-watch/reports/{code}/again", json=again)
    assert too_soon.status_code == 409
    clock.advance(minutes=30)
    repeated = client.post(f"/api/outage-watch/reports/{code}/again", json=again)
    assert repeated.status_code == 201 and repeated.json()["code"] == code
    assert len(repeated.json()["confirmations"]) == 2
    assert client.get(f"/api/outage-watch/reports/{code}").json()["status"] == "waiting"
    console = client.get("/api/console/outage-watch").json()
    assert console["counts"] == {"waiting": 1, "seen": 0}
    assert console["items"][0]["note_masked"] and TEST_EMAIL not in json.dumps(console)

    marked = client.post(f"/api/console/outage-watch/{code}/seen")
    assert marked.status_code == 200 and marked.json()["status"] == "seen"
    assert client.post(f"/api/console/outage-watch/{code}/seen").status_code == 409
    citizen = client.get(f"/api/outage-watch/reports/{code}").json()
    assert citizen["status"] == "seen" and "operator" not in citizen
    entries = ledger.entries(kinds=("outage_confirmation", "outage_seen"))
    assert len(entries) == 3
    details = json.dumps([entry.detail for entry in entries], ensure_ascii=False)
    assert TEST_EMAIL not in details and "‹" not in details
    assert all("note" not in entry.detail for entry in entries)

    expired_client, expiry_clock, expired_store, _ = client_for(tmp_path / "expiry")
    first = expired_client.post("/api/outage-watch/reports", json=report_body()).json()
    expiry_clock.advance(days=7)
    expired = expired_client.get(f"/api/outage-watch/reports/{first['code']}")
    assert expired.status_code == 404 and expired_store.items() == []


def test_hourly_limit_has_no_persistent_client_key(tmp_path) -> None:
    client, _, store, _ = client_for(tmp_path, limit=1)
    assert client.post("/api/outage-watch/reports", json=report_body()).status_code == 201
    limited = client.post("/api/outage-watch/reports", json=report_body(neighbourhood="Osmanağa"))
    assert limited.status_code == 429
    data = json.dumps(store.items(), ensure_ascii=False)
    assert "testclient" not in data and "client" not in data
