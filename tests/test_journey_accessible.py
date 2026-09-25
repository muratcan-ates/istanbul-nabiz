"""Accessible journey planning: route failures, lift checks and verified detours."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from typing import Any

import pytest

from ibb_mcp import journey_accessible
from ibb_mcp.accessibility import EQUIPMENT_DATA_UNAVAILABLE, NO_ALTERNATIVE
from ibb_mcp.http import UpstreamUnavailable
from ibb_mcp.metro_graph import MetroLeg, MetroPath, MetroPathResult
from ibb_mcp.models import MetroStation, Provenance
from ibb_mcp.routing import Waypoint
from ibb_mcp.sources.metro_equipment import EquipmentRecord, EquipmentSnapshot
from ibb_mcp.text import fold_tr


def provenance() -> Provenance:
    now = dt.datetime.now(dt.UTC)
    return Provenance(source="metro_equipment", source_url="https://example.test/lifts", observed_at=now)


def station(name: str, order: int, lon: float, *, lifts: int = 1, line: str = "M1") -> MetroStation:
    return MetroStation(name=name, line_name=line, order=order, lat=41.0, lon=lon, lifts=lifts)


class FakeGraph:
    def __init__(self, *, disconnected: bool = False) -> None:
        self.disconnected = disconnected

    def path_between_points(self, origin: tuple[float, float], destination: tuple[float, float]) -> MetroPathResult:
        if self.disconnected:
            return MetroPathResult(path=None, reason="disconnected")
        return MetroPathResult(path=MetroPath(
            legs=(
                MetroLeg("access", None, "Start", "A", 0, 60, 0.05),
                MetroLeg("ride", "M1", "A", "B", 1, 180, 1.0),
                MetroLeg("ride", "M1", "B", "C", 1, 180, 1.0),
                MetroLeg("egress", None, "C", "End", 0, 60, 0.05),
            ),
            total_seconds=660,
            ride_seconds=360,
            wait_seconds=180,
            transfer_count=0,
            lines=("M1",),
            stop_count=2,
        ), reason=None)

    def path_between_stations(self, origin: str, destination: str) -> MetroPathResult:
        if fold_tr(destination) == "d" and fold_tr(origin) == "a":
            legs = (MetroLeg("ride", "M1", "A", "D", 1, 240, 1.2),)
        elif fold_tr(origin) == "d" and fold_tr(destination) == "c":
            legs = (MetroLeg("ride", "M1", "D", "C", 1, 240, 1.2),)
        else:
            return MetroPathResult(path=None, reason="disconnected")
        return MetroPathResult(path=MetroPath(
            legs=legs, total_seconds=240, ride_seconds=240, wait_seconds=0, transfer_count=0, lines=("M1",), stop_count=1
        ), reason=None)


class FakeFacade:
    def __init__(self, stations: list[MetroStation], snapshot: EquipmentSnapshot, *, endpoint_error: bool = False,
                 snapshot_error: Exception | None = None, disconnected: bool = False) -> None:
        self.settings = SimpleNamespace(offline=True)
        self._metro = SimpleNamespace(stations=self._stations)
        self._equipment = SimpleNamespace(snapshot=self._snapshot)
        self._station_rows = stations
        self._snapshot_value = snapshot
        self._endpoint_error = endpoint_error
        self._snapshot_error = snapshot_error
        self._graph = FakeGraph(disconnected=disconnected)

    def _source(self, name: str) -> Any:
        return {"metro": self._metro, "metro_equipment": self._equipment}[name]

    async def _stations(self):
        return self._station_rows, provenance()

    async def _snapshot(self, groups):
        if self._snapshot_error:
            raise self._snapshot_error
        return self._snapshot_value, provenance()

    def _endpoint(self, name, lat, lon, *, role):
        if self._endpoint_error:
            raise ValueError("Yer çözümlenemedi.")
        coords = (lat, lon) if lat is not None else (41.0, 29.0 if role == "origin" else 29.03)
        return Waypoint(name=name or role, lat=coords[0], lon=coords[1])


def lift_fault(name: str, line: str = "M1") -> EquipmentRecord:
    return EquipmentRecord.from_raw({
        "Group": "Asansör", "StationName": name, "LineName": line, "Type": "Arıza", "Code": f"fault-{name}"
    })


def configure_graph(monkeypatch: pytest.MonkeyPatch, graph: FakeGraph) -> None:
    monkeypatch.setattr(journey_accessible.MetroGraph, "from_stations", classmethod(lambda cls, rows, added=(): graph))


@pytest.mark.asyncio
async def test_happy_path_includes_each_station_status_and_map_links(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [station("A", 1, 29.00), station("B", 2, 29.01), station("C", 3, 29.02)]
    facade = FakeFacade(rows, EquipmentSnapshot(groups_read=["Asansör"]))
    configure_graph(monkeypatch, facade._graph)
    result = await journey_accessible.plan_accessible_journey(facade, "Start", "End")

    assert result.data["available"] is True
    assert result.data["operator_approved"] is False
    assert result.data["steps"][0]["map_links"]["google"].startswith("https://www.google.com/maps/dir/?")
    assert result.data["steps"][1]["stations"][-1]["lift_status"] == "working"
    assert result.data["provenance"] is None
    assert result.provenance is not None


@pytest.mark.asyncio
async def test_unknown_place_is_unavailable_without_invented_route(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [station("A", 1, 29.00), station("B", 2, 29.01), station("C", 3, 29.02)]
    facade = FakeFacade(rows, EquipmentSnapshot(groups_read=["Asansör"]), endpoint_error=True)
    configure_graph(monkeypatch, facade._graph)
    result = await journey_accessible.plan_accessible_journey(facade, "Nowhere", "End")
    assert result.data["available"] is False
    assert result.data["steps"] == [] and "çözümlenemedi" in result.data["reason"]


@pytest.mark.asyncio
async def test_disconnected_route_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [station("A", 1, 29.00), station("B", 2, 29.01), station("C", 3, 29.02)]
    facade = FakeFacade(rows, EquipmentSnapshot(groups_read=["Asansör"]), disconnected=True)
    configure_graph(monkeypatch, facade._graph)
    result = await journey_accessible.plan_accessible_journey(facade, "Start", "End")
    assert result.data["available"] is False
    assert result.data["reason"] == "Bu iki nokta arasında doğrulanabilir bir raylı sistem bağlantısı bulunamadı."


@pytest.mark.asyncio
async def test_unreadable_lift_snapshot_says_unverified(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [station("A", 1, 29.00), station("B", 2, 29.01), station("C", 3, 29.02)]
    facade = FakeFacade(rows, EquipmentSnapshot())
    configure_graph(monkeypatch, facade._graph)
    result = await journey_accessible.plan_accessible_journey(facade, "Start", "End")
    assert result.data["available"] is False
    assert EQUIPMENT_DATA_UNAVAILABLE in result.data["uncertainty"]
    assert result.provenance is None


@pytest.mark.asyncio
async def test_outage_is_rerouted_around_affected_station(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [station("A", 1, 29.00), station("B", 2, 29.01), station("C", 3, 29.02), station("D", 4, 29.03)]
    snapshot = EquipmentSnapshot(records=[lift_fault("B")], groups_read=["Asansör"])
    facade = FakeFacade(rows, snapshot)
    configure_graph(monkeypatch, facade._graph)
    monkeypatch.setattr(journey_accessible.accessibility, "accessible_alternative", lambda *args, **kwargs: {
        "uncertainty": [],
        "alternative": {"station": "D", "line": "M1", "reason": "İBB kaydında D için asansör arızası yok."},
    })
    result = await journey_accessible.plan_accessible_journey(facade, "Start", "End")

    assert result.data["available"] is True
    assert result.data["alternative_used"]["avoided_station"] == "B"
    assert result.data["extra_minutes"] > 0
    assert all("B" not in (step.get("from_station"), step.get("to_station")) for step in result.data["steps"])


@pytest.mark.asyncio
async def test_no_safe_alternative_returns_named_uncertainty(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [station("A", 1, 29.00), station("B", 2, 29.01), station("C", 3, 29.02)]
    snapshot = EquipmentSnapshot(records=[lift_fault("B"), lift_fault("A"), lift_fault("C")], groups_read=["Asansör"])
    facade = FakeFacade(rows, snapshot)
    configure_graph(monkeypatch, facade._graph)
    monkeypatch.setattr(journey_accessible.accessibility, "accessible_alternative", lambda *args, **kwargs: {
        "uncertainty": [NO_ALTERNATIVE], "alternative": None
    })
    result = await journey_accessible.plan_accessible_journey(facade, "Start", "End")
    assert result.data["available"] is False
    assert NO_ALTERNATIVE in result.data["uncertainty"]
    assert result.data["steps"] == []


@pytest.mark.asyncio
async def test_equipment_read_error_returns_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [station("A", 1, 29.00), station("B", 2, 29.01), station("C", 3, 29.02)]
    facade = FakeFacade(rows, EquipmentSnapshot(), snapshot_error=UpstreamUnavailable("offline", source="metro_equipment"))
    configure_graph(monkeypatch, facade._graph)
    result = await journey_accessible.plan_accessible_journey(facade, "Start", "End")
    assert result.data["available"] is False
    assert EQUIPMENT_DATA_UNAVAILABLE in result.data["uncertainty"]
