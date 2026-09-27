from __future__ import annotations

import pathlib
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_notice_age import EQUIPMENT_SOURCE, METRO_SOURCE, NOW, set_lake, write_part

from nabiz.console import chronic_api
from nabiz.console.access import is_operator_path
from nabiz.console.chronic_api import chronic_routes


def small_client() -> TestClient:
    app = FastAPI()
    app.include_router(chronic_routes)
    app.state.report_clock = lambda: NOW
    return TestClient(app, base_url="http://127.0.0.1:8093")


def equipment_row(stamp: str, station: str = "Hacıosman") -> dict[str, Any]:
    # Sentetik arşiv satırı; gerçek İBB verisi değildir.
    return {
        "snapshot_ts_utc": stamp,
        "has_record": True,
        "equipment_type": "escalator",
        "equipment_code": "YURMERDVEN",
        "line_name": "M2",
        "station_name": station,
        "status_class": "not_operated",
        "status_type": "Çalıştırılmıyor",
        "uncertainty": [],
    }


def test_window_validation_payload_and_unavailable_report_ledger(tmp_path: pathlib.Path, monkeypatch) -> None:
    set_lake(monkeypatch, tmp_path)
    first = "2026-09-25T06:00:00Z"
    second = "2026-09-26T06:00:00Z"
    write_part(
        tmp_path,
        METRO_SOURCE,
        first,
        [{"snapshot_ts_utc": first, "has_notice": True, "line_name": "M7", "description": "Duyuru"}],
    )
    write_part(tmp_path, EQUIPMENT_SOURCE, second, [equipment_row(second)])

    with small_client() as client:
        default = client.get("/api/console/chronic")
        thirty = client.get("/api/console/chronic?days=30")
        invalid = client.get("/api/console/chronic?days=14")

    assert default.status_code == thirty.status_code == 200
    assert default.json()["days"] == 7
    assert thirty.json()["days"] == 30
    assert invalid.status_code == 422
    body = default.json()
    fields = {"window_start", "generated_at", "chronic_min_days", "coverage", "rows", "total_rows", "reports_total", "note_codes"}
    assert fields <= body.keys()
    assert body["reports_total"] is None
    assert "reports_unavailable" in body["note_codes"]
    assert body["rows"][0]["agency"]["id"] == "metro"


def test_missing_archive_returns_only_archive_missing_note(tmp_path: pathlib.Path, monkeypatch) -> None:
    set_lake(monkeypatch, tmp_path)

    with small_client() as client:
        response = client.get("/api/console/chronic")

    assert response.status_code == 200
    assert response.json()["note_codes"] == ["archive_missing"]
    assert response.json()["rows"] == []
    assert response.json()["total_rows"] == 0
    assert response.json()["coverage"]["equipment"]["reads"] == 0


def test_report_counts_join_by_normalized_station_without_returning_identity(tmp_path: pathlib.Path, monkeypatch) -> None:
    from test_report_map_api import build_report_map_client, post_report, put_static_last

    lake = tmp_path / "lake"
    set_lake(monkeypatch, lake)
    client, _, clock = build_report_map_client(tmp_path / "ledger")
    client.app.include_router(chronic_routes)
    put_static_last(client.app)
    stamp = clock.now.isoformat().replace("+00:00", "Z")
    write_part(lake, EQUIPMENT_SOURCE, stamp, [equipment_row(stamp, "Kartal") | {"equipment_type": "elevator"}])

    with client:
        assert post_report(client, "Kartal", "not_working").status_code == 200
        response = client.get("/api/console/chronic")

    assert response.status_code == 200
    body = response.json()
    elevator = next(row for row in body["rows"] if row["equipment_type"] == "elevator")
    assert elevator["reports"] == 1
    assert body["reports_total"] == 1
    assert not {"signal_id", "actor", "device"} & set(elevator)


def test_reports_at_stations_without_an_elevator_list_row_are_separate(tmp_path: pathlib.Path, monkeypatch) -> None:
    from test_report_map_api import build_report_map_client, post_report, put_static_last

    lake = tmp_path / "lake"
    set_lake(monkeypatch, lake)
    client, _, clock = build_report_map_client(tmp_path / "ledger")
    client.app.include_router(chronic_routes)
    put_static_last(client.app)
    stamp = clock.now.isoformat().replace("+00:00", "Z")
    listed = equipment_row(stamp, "Kartal") | {"equipment_type": "elevator"}
    write_part(lake, EQUIPMENT_SOURCE, stamp, [listed])

    with client:
        assert post_report(client, "Kartal", "not_working").status_code == 200
        assert post_report(client, "Yenikapı", "not_working").status_code == 200
        response = client.get("/api/console/chronic")

    assert response.status_code == 200
    body = response.json()
    assert body["reports_total"] == 2
    assert body["reports_only"] == [{"station": "Yenikapı", "reports": 1}]


def test_reports_only_rows_are_sorted_and_capped() -> None:
    counts = {
        f"station-{index}": {"station": f"İstasyon {index:02d}", "reports": index + 1}
        for index in range(12)
    }

    result = chronic_api._reports_only(counts, set())

    assert len(result) == 10
    assert result[0] == {"station": "İstasyon 11", "reports": 12}
    assert result[-1] == {"station": "İstasyon 02", "reports": 3}


def test_agency_table_failure_is_a_null_suggestion_not_an_api_failure(tmp_path: pathlib.Path, monkeypatch) -> None:
    set_lake(monkeypatch, tmp_path)
    stamp = "2026-09-26T06:00:00Z"
    write_part(tmp_path, EQUIPMENT_SOURCE, stamp, [equipment_row(stamp)])
    monkeypatch.setattr(chronic_api, "route", lambda _query: (_ for _ in ()).throw(FileNotFoundError()))

    with small_client() as client:
        response = client.get("/api/console/chronic")

    assert response.status_code == 200
    assert response.json()["rows"][0]["agency"] is None


def test_endpoint_path_is_covered_by_the_operator_access_rule() -> None:
    assert is_operator_path("/api/console/chronic")
