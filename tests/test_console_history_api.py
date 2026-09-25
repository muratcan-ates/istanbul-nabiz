from __future__ import annotations

import datetime as dt
import pathlib
from typing import Any

import httpx
from conftest import offline_settings, refuse_network
from fastapi.testclient import TestClient

from ibb_mcp.cache import TTLCache
from ibb_mcp.http import PoliteClient
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.collector import lake
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard

PROVENANCE_KEYS = {"source", "url", "observed_at", "age_s", "mode"}
CARD_KEYS = {"id", "kind", "title", "body", "status", "provenance", "author"}
SOURCE = "metro_equipment_snapshot"


def _row(stamp: dt.datetime, **overrides: Any) -> dict[str, Any]:
    return {
        "snapshot_ts_utc": stamp.isoformat(),
        "ts_utc": stamp.isoformat(),
        "has_record": True,
        "station_name": "Kartal",
        "equipment_code": "TEST-ASN-01",
        "outage_id": "fault-1",
        "status_class": "fault",
        **overrides,
    }


def _client() -> TestClient:
    nabiz = Nabiz(
        SourceContext.create(
            client=PoliteClient(transport=httpx.MockTransport(refuse_network)),
            cache=TTLCache(),
            settings=offline_settings(),
        )
    )
    app = build_console_app(
        settings=offline_settings(),
        nabiz=nabiz,
        llm_config=llm.LlmConfig(),
        guard=SpendGuard(BudgetConfig(state_path=None)),
    )
    return TestClient(app)


def test_equipment_history_endpoint_returns_card_contract_keys(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setenv(lake.ENV_LAKE_DIR, str(tmp_path))
    first = dt.datetime.now(dt.UTC) - dt.timedelta(hours=2)
    second = first + dt.timedelta(hours=1)
    lake.write_rows(SOURCE, [_row(first)], snapshot_ts=first, backend="local-json")
    lake.write_rows(SOURCE, [_row(second)], snapshot_ts=second, backend="local-json")

    with _client() as client:
        response = client.get("/api/equipment/history", params={"station": "Kartal"})

    assert response.status_code == 200
    body = response.json()
    assert set(body) >= CARD_KEYS
    assert set(body["provenance"]) == PROVENANCE_KEYS
    assert body["station"] == "Kartal"
    assert body["equipment_code"] == "TEST-ASN-01"
    assert body["fault_count_7d"] == 2
    assert body["avg_duration_hours"] == 1.0
    assert body["current_status"] == "fault"
    assert body["provenance"]["source"] == SOURCE
    assert body["provenance"]["mode"] == "recorded"
    assert "ortalama 1 saat" in body["text"]


def test_equipment_history_endpoint_without_station_or_equipment_id_is_400(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setenv(lake.ENV_LAKE_DIR, str(tmp_path))

    with _client() as client:
        response = client.get("/api/equipment/history")

    assert response.status_code == 400
    assert response.json()["error"] == "bad_request"


def test_equipment_history_endpoint_with_empty_lake_says_history_not_yet_available(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    monkeypatch.setenv(lake.ENV_LAKE_DIR, str(tmp_path))

    with _client() as client:
        response = client.get("/api/equipment/history", params={"station": "Kartal"})

    assert response.status_code == 200
    body = response.json()
    assert set(body) >= CARD_KEYS
    assert body["fault_count_7d"] is None
    assert body["avg_duration_hours"] is None
    assert body["current_status"] == "unknown"
    assert body["provenance"]["mode"] == "unknown"
    assert body["text"].startswith("Tarihçe henüz yok (toplama başladı: ")
