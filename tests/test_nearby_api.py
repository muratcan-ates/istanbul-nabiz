"""Nearby source composition and the console's privacy-safe API boundary."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ibb_mcp.config import Settings
from ibb_mcp.http import UpstreamUnavailable
from ibb_mcp.models import Provenance, Stop, ToolResult, utcnow
from nabiz.agent import llm
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.nearby_api import nearby_view
from nabiz.console.ports import Ports

LAT, LON = 41.0, 29.0


def provenance(source: str) -> Provenance:
    return Provenance(source=source, source_url="local:test-data", observed_at=utcnow())


class FakeGtfs:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.asked: list[tuple[float, float, int]] = []

    def source_vintage(self) -> str:
        return "2026-09-25T08:00:00+00:00"

    def nearest_stops(self, lat: float, lon: float, *, limit: int) -> list[Stop]:
        self.asked.append((lat, lon, limit))
        if self.fail:
            raise RuntimeError("GTFS unavailable")
        return [
            Stop(stop_code=f"{index}", name=f"Durak {index}", lat=LAT + index / 10000, lon=LON, distance_km=index / 10)
            for index in range(1, 4)
        ]


class FakePlace:
    def __init__(self, name: str, lat: float) -> None:
        self.name, self.lat, self.lon, self.kind = name, lat, LON, "metro_station"


class FakeNabiz:
    def __init__(self, *, gtfs_fail: bool = False, parking_fail: bool = False,
                 metro_fail: bool = False, lift_status: dict[str, str] | None = None) -> None:
        self.settings = Settings(offline=False)
        self.ctx = object()
        self.places = type("PlaceIndex", (), {"places": [FakePlace("Yakın", LAT + 0.001), FakePlace("Sonraki", LAT + 0.002)]})()
        self.index = FakeGtfs(fail=gtfs_fail)
        self.parking_fail = parking_fail
        self.metro_fail = metro_fail
        self.lift_status = lift_status or {"Yakın": "out_of_service", "Sonraki": "working"}
        self.metro_calls: list[tuple[str, str]] = []
        self.journey_args: dict[str, Any] | None = None

    async def gtfs(self) -> FakeGtfs:
        if self.index.fail:
            raise UpstreamUnavailable("GTFS unavailable", source="gtfs")
        return self.index

    async def metro_equipment_status(self, *, station: str, group: str) -> ToolResult:
        self.metro_calls.append((station, group))
        if self.metro_fail:
            raise UpstreamUnavailable("Metro unavailable", source="metro_equipment")
        return ToolResult(
            data={"available": True, "groups_read": [group],
                  "station": {"name": station, "lift_status": self.lift_status.get(station, "unknown")}},
            provenance=provenance("metro_equipment"),
        )

    async def ispark_find_parking(self, *, lat: float, lon: float, min_free: int, with_tariff: bool) -> ToolResult:
        assert min_free == 1 and with_tariff is False
        if self.parking_fail:
            raise RuntimeError("parking unavailable")
        return ToolResult(
            data={"parks": [{"name": "Otopark", "empty": 12, "lat": LAT + 0.003, "lon": LON,
                              "distance_km": 0.3}]},
            provenance=provenance("ispark"),
        )

    async def plan_journey(self, **kwargs: Any) -> ToolResult:
        self.journey_args = kwargs
        return ToolResult(
            data={"options": [], "unavailable_options": [], "disclaimer": "Tahmindir."},
            provenance=provenance("nabiz_routing"),
        )


def make_client(nabiz: FakeNabiz) -> TestClient:
    app = build_console_app(
        settings=nabiz.settings,
        nabiz=nabiz,
        llm_config=llm.LlmConfig(),
        ports=Ports(),
        guard=SpendGuard(BudgetConfig(state_path=None)),
    )
    return TestClient(app)


@pytest.mark.asyncio
async def test_nearby_view_returns_three_stops_nearest_metro_parking_and_source_age() -> None:
    nabiz = FakeNabiz(lift_status={"Yakın": "working"})
    view = await nearby_view(nabiz, LAT, LON, needs=[], offline=False)
    assert [stop["name"] for stop in view["stops"]] == ["Durak 1", "Durak 2", "Durak 3"]
    assert view["stops"][0]["distance_m"] == 100
    assert view["metro"]["station"] == "Yakın" and view["metro"]["lift_status"] == "working"
    assert view["parking"]["name"] == "Otopark" and view["parking"]["empty"] == 12
    assert view["charging"] == {"status": "planlanan"}
    assert view["stops_provenance"]["source"] == "gtfs"
    assert view["metro_provenance"]["source"] == "metro_equipment"
    assert view["parking_provenance"]["source"] == "ispark"


@pytest.mark.asyncio
async def test_step_free_prefers_the_nearest_station_with_no_recorded_lift_fault() -> None:
    nabiz = FakeNabiz()
    view = await nearby_view(nabiz, LAT, LON, needs=["step_free"], offline=False)
    assert view["metro"]["station"] == "Sonraki"
    assert view["metro"]["lift_status"] == "working"
    assert nabiz.metro_calls == [("Yakın", "Asansör"), ("Sonraki", "Asansör")]


@pytest.mark.asyncio
async def test_each_source_failure_returns_unknown_provenance_instead_of_500() -> None:
    nabiz = FakeNabiz(gtfs_fail=True, parking_fail=True, metro_fail=True)
    view = await nearby_view(nabiz, LAT, LON, needs=[], offline=False)
    assert view["stops"] == [] and view["stops_provenance"]["mode"] == "unknown"
    assert view["metro"]["lift_status"] == "unknown" and view["metro_provenance"]["mode"] == "unknown"
    assert view["parking"] is None and view["parking_provenance"]["mode"] == "unknown"
    assert view["charging"] == {"status": "planlanan"}


def test_nearby_api_does_not_log_or_return_the_visitors_coordinates(caplog: pytest.LogCaptureFixture) -> None:
    nabiz = FakeNabiz(lift_status={"Yakın": "working"})
    with (
        make_client(nabiz) as client,
        caplog.at_level(logging.INFO, logger="nabiz.console"),
    ):
        response = client.get("/api/nearby", params={"lat": 41.2345, "lon": 29.8765, "needs": ""})
    assert response.status_code == 200
    assert "41.2345" not in response.text and "29.8765" not in response.text
    assert "41.2345" not in caplog.text and "29.8765" not in caplog.text
    assert "GET /api/nearby -> 200" in caplog.text


def test_nearby_api_source_failure_is_a_successful_unknown_response() -> None:
    nabiz = FakeNabiz(gtfs_fail=True, parking_fail=True, metro_fail=True)
    with make_client(nabiz) as client:
        response = client.get("/api/nearby", params={"lat": LAT, "lon": LON})
    assert response.status_code == 200
    body = response.json()
    assert body["stops_provenance"]["mode"] == "unknown"
    assert body["metro_provenance"]["mode"] == "unknown"
    assert body["parking_provenance"]["mode"] == "unknown"


def test_journey_button_bridge_passes_origin_and_target_coordinates() -> None:
    nabiz = FakeNabiz()
    with make_client(nabiz) as client:
        response = client.post(
            "/api/nearby/journey",
            json={
                "origin_lat": 41.0001,
                "origin_lon": 29.0002,
                "destination_lat": 41.004,
                "destination_lon": 29.005,
                "destination_name": "Durak 1",
            },
        )
    assert response.status_code == 200
    assert nabiz.journey_args == {
        "origin": "Konumum",
        "destination": "Durak 1",
        "origin_lat": 41.0001,
        "origin_lon": 29.0002,
        "destination_lat": 41.004,
        "destination_lon": 29.005,
    }
