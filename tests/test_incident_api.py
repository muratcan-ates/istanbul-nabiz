"""E67 persistence, operator access and API acceptance cases."""

from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient
from nexus_helpers import Clock, build_engine, make_signal
from test_report_triage import put_static_last, report_app

from nabiz.console.access import OperatorAccess
from nabiz.console.incident_api import incident_routes
from nabiz.console.incident_store import AlreadyUndone, IncidentStore
from nabiz.console.report_api import REPORT_KIND
from nexus_core.ledger import Ledger


def _add_report(engine, clock: Clock, signal_id: str, station: str) -> None:
    signal = make_signal(
        kind=REPORT_KIND,
        entity=f"synthetic-report-{signal_id}",
        observed_at=clock.now,
        station=station,
        report_kind="not_working",
        bucket="now",
        lift_status=None,
        lift_text=None,
    )
    engine.process(signal)


def _add_equipment(engine, clock: Clock, signal_id: str, station: str) -> None:
    signal = make_signal(
        kind="equipment_fault",
        entity=f"synthetic-equipment-{signal_id}",
        observed_at=clock.now,
        station=station,
        line="M2",
        equipment_type="elevator",
        status_class="fault",
        status_type="Arıza",
    )
    engine.process(signal)


def _client(engine, clock, token: str = "t"):
    app, _published = report_app(engine, clock, access=OperatorAccess(token=token))
    app.include_router(incident_routes)
    put_static_last(app)
    return app


def _seed_api(tmp_path: pathlib.Path, monkeypatch):
    clock = Clock()
    ledger_path = tmp_path / "nexus.db"
    db_path = tmp_path / "incidents.db"
    monkeypatch.setenv("NEXUS_DB_PATH", str(ledger_path))
    monkeypatch.setenv("NABIZ_INCIDENTS_DB_PATH", str(db_path))
    engine = build_engine(tmp_path, clock)
    _add_report(engine, clock, "r-1", "Sanayi Mahallesi")
    clock.advance(seconds=1)
    _add_report(engine, clock, "r-2", "Sanayi Mahallesi")
    clock.advance(seconds=1)
    _add_equipment(engine, clock, "e-1", "Sanayi Mahallesi")
    clock.advance(seconds=1)
    _add_report(engine, clock, "r-3", "Üsküdar")
    before_states = engine.states()
    app = _client(engine, clock)
    headers = {"X-Nabiz-Operator": "t"}
    return clock, engine, app, headers, before_states


def test_incident_routes_require_operator_access_and_replay_split_merge(tmp_path: pathlib.Path, monkeypatch, caplog) -> None:
    clock, engine, app, headers, before_states = _seed_api(tmp_path, monkeypatch)

    with TestClient(app, base_url="http://127.0.0.1:8090") as client:
        assert client.get("/api/console/incidents").status_code == 401
        assert client.post("/api/console/incidents/missing/split").status_code == 401
        response = client.get("/api/console/incidents", headers=headers)
        assert response.status_code == 200
        listing = response.json()
        assert len(listing["items"]) == 2
        sanayi = next(item for item in listing["items"] if item["title_station"] == "Sanayi Mahallesi")
        assert sanayi["members"]["reports"] == 2 and sanayi["members"]["equipment"] == 1
        assert listing["photos_available"] is False
        detail = client.get(f"/api/console/incidents/{sanayi['id']}", headers=headers).json()
        assert {member["source"] for member in detail["members"]["equipment"]} == {"Metro İstanbul"}
        assert detail["record_note"] is None
        assert {factor["key"] for factor in detail["suggestion"]["factors"]} >= {"repeat", "waiting", "access"}

        state = detail["members"]["reports"][0]
        split = client.post(
            f"/api/console/incidents/{sanayi['id']}/split",
            headers=headers,
            json={"ref": state["ref"], "reason": "Kartlar farklı gözlem içeriyor"},
        )
        assert split.status_code == 200 and split.json()["ledger_changed"] is True
        action_id = split.json()["action_id"]
        assert len(client.get("/api/console/incidents", headers=headers).json()["items"]) == 3
        undo = client.post(
            f"/api/console/incidents/actions/{action_id}/undo", headers=headers, json={"reason": "İlk ayırma uygun görülmedi"}
        )
        assert undo.status_code == 200
        assert len(client.get("/api/console/incidents", headers=headers).json()["items"]) == 2

        other = next(item for item in listing["items"] if item["id"] != sanayi["id"])
        merge = client.post(
            f"/api/console/incidents/{sanayi['id']}/merge",
            headers=headers,
            json={"target": other["id"], "reason": "Kayıtlar aynı saha incelemesine ait"},
        )
        assert merge.status_code == 200
        merged = client.get(f"/api/console/incidents/{other['id']}", headers=headers).json()
        assert merged["multi_station"] is True and len(merged["stations"]) == 2
        assert (
            client.post(
                f"/api/console/incidents/actions/{merge.json()['action_id']}/undo",
                headers=headers,
                json={"reason": "İstasyonlar ayrı tutulmalı"},
            ).status_code
            == 200
        )

    with TestClient(_client(engine, clock), base_url="http://127.0.0.1:8090") as client:
        refreshed = client.get(f"/api/console/incidents/{sanayi['id']}", headers=headers).json()
        assert any(item["undone_at"] for item in refreshed["actions"])

    assert engine.states() == before_states  # signal-less incident ledger rows cannot alter card replay
    entries = engine.ledger.entries(kinds=("incident_changed",))
    assert entries and all(entry.signal_id is None for entry in entries)
    assert all(entry.entity_id.startswith("incident:") for entry in entries)
    assert all("SYNTHETIC" not in str(entry.detail) for entry in entries)
    assert engine.verify().ok
    assert "Sanayi Mahallesi" not in caplog.text
    assert "Kartlar farklı gözlem içeriyor" not in caplog.text


def test_priority_override_is_persistent_and_private(tmp_path: pathlib.Path, monkeypatch, caplog) -> None:
    clock, engine, app, headers, before_states = _seed_api(tmp_path, monkeypatch)
    with TestClient(app, base_url="http://127.0.0.1:8090") as client:
        listing = client.get("/api/console/incidents", headers=headers).json()
        sanayi = next(item for item in listing["items"] if item["title_station"] == "Sanayi Mahallesi")
        detail = client.get(f"/api/console/incidents/{sanayi['id']}", headers=headers).json()
        priority = client.post(
            f"/api/console/incidents/{sanayi['id']}/priority",
            headers=headers,
            json={"level": "high", "reason": "İnsan önceliği yeniden değerlendirdi"},
        )
        assert priority.status_code == 200 and priority.json()["priority"]["by"] == "operator"
        assert client.get("/api/console/incidents", headers=headers).json()["items"][0]["priority"] == {
            "level": "high",
            "by": "operator",
            "suggested_level": detail["suggestion"]["level"],
        }
        pii = client.post(
            f"/api/console/incidents/{sanayi['id']}/priority",
            headers=headers,
            json={"level": "medium", "reason": "Yetkili " + "operator" + "@example.invalid"},
        )
        assert pii.status_code == 400 and pii.json()["error"] == "reason_has_pii"
        assert (
            client.post(
                f"/api/console/incidents/{sanayi['id']}/priority",
                headers=headers,
                json={"level": "suggested", "reason": "Öneriye dönüş uygun"},
            ).status_code
            == 200
        )

    with TestClient(_client(engine, clock), base_url="http://127.0.0.1:8090") as client:
        refreshed = client.get(f"/api/console/incidents/{sanayi['id']}", headers=headers).json()
        assert refreshed["priority"]["by"] == "suggestion"
        assert len(refreshed["priority_history"]) == 2

    assert engine.states() == before_states
    entries = engine.ledger.entries(kinds=("incident_priority_set",))
    assert entries and all(entry.signal_id is None for entry in entries)
    assert all(entry.entity_id.startswith("incident:") for entry in entries)
    assert engine.verify().ok
    assert "Sanayi Mahallesi" not in caplog.text
    assert "İnsan önceliği yeniden değerlendirdi" not in caplog.text


def test_store_rejects_personal_data_and_expires_rows(tmp_path: pathlib.Path) -> None:
    clock = Clock()
    ledger = Ledger(tmp_path / "ledger.db", clock=clock)
    store = IncidentStore(tmp_path / "incidents.db", clock=clock)
    phone = "0" + "532" + "000" + "00" + "00"
    email = "operator" + "@example.invalid"
    tckn = "".join(str(value) for value in [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0])
    for pii in (phone, email, tckn):
        with pytest.raises(ValueError, match="kişisel bilgi"):
            store.set_priority("inc-123", "high", "Gerekçe " + pii, "normal", "simüle operatör", ledger)
    row = store.add_action(
        "split", "inc-123", {"ref": "report:sig-1", "station_key": "sanayi"}, "Kayıtları ayrı incele", "simüle operatör", ledger
    )
    assert row["ledger_entry"] == 1
    assert store.actions()[0]["data"] == {"ref": "report:sig-1", "station_key": "sanayi"}
    store.undo(row["id"], "İlk ayırma uygun görülmedi", "simüle operatör", ledger)
    with pytest.raises(AlreadyUndone):
        store.undo(row["id"], "Bir kez daha denendi", "simüle operatör", ledger)
    clock.advance(days=31)
    assert store.actions() == []
    assert ledger.verify().ok
