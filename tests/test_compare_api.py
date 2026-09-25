"""The metro and bus citizen route over a fake facade; no network or live model is used."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from conftest import offline_settings
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ibb_mcp.http import RateLimitExceeded, UpstreamUnavailable
from ibb_mcp.models import Provenance, ToolResult, utcnow
from nabiz.console.compare_api import compare_routes

ROOT = Path(__file__).resolve().parents[1]
UNAVAILABLE_NOTE = "14M saat 08 için yeterli gözlem yok."


class FakeNabiz:
    def __init__(
        self,
        *,
        unavailable: bool = False,
        accessibility_error: Exception | None = None,
        reliability_error: Exception | None = None,
        reliability_available: bool = True,
    ) -> None:
        self.unavailable = unavailable
        self.accessibility_error = accessibility_error
        self.reliability_error = reliability_error
        self.reliability_available = reliability_available
        self.journey_args: dict[str, Any] | None = None
        self.accessibility_calls: list[dict[str, Any]] = []
        self.reliability_calls: list[dict[str, Any]] = []

    async def plan_journey(self, **kwargs: Any) -> ToolResult:
        self.journey_args = kwargs
        options = [] if self.unavailable else [
            {
                "mode": "metro", "label": "Metro", "available": True, "total_minutes": 34.0,
                "detail": {"origin_station": "Kadıköy", "transfers": 1},
            },
            {
                "mode": "bus", "label": "Otobüs 14M", "available": True, "total_minutes": 41.5,
                "detail": {"line_code": "14M", "stops_between": 16},
            },
        ]
        unavailable_options = [
            {"mode": "metro", "label": "Metro", "reason": "Metro istasyonu bulunamadı."},
            {"mode": "bus", "label": "Otobüs", "reason": "Bu yolculuk için tek hat yok."},
        ] if self.unavailable else []
        return ToolResult(
            data={
                "options": options,
                "unavailable_options": unavailable_options,
                "disclaimer": "Bu bir tahmindir.",
                "generated_at": utcnow().isoformat(),
            },
            provenance=Provenance(source="nabiz_routing", source_url="", observed_at=utcnow()),
        )

    async def accessible_alternative(self, *, station: str, needs: list[str]) -> ToolResult:
        self.accessibility_calls.append({"station": station, "needs": needs})
        if self.accessibility_error:
            raise self.accessibility_error
        return ToolResult(
            data={"lift_status": "out_of_service"},
            provenance=Provenance(source="metro_equipment", source_url="", observed_at=utcnow()),
        )

    async def line_reliability(self, *, line_code: str) -> ToolResult:
        self.reliability_calls.append({"line_code": line_code})
        if self.reliability_error:
            raise self.reliability_error
        data: Mapping[str, Any] = {
            "available": self.reliability_available,
            "median_headway_min": 14.0 if self.reliability_available else None,
            "bunching_label": "düzenli" if self.reliability_available else None,
        }
        note = "14 dk ortanca sefer aralığı." if self.reliability_available else UNAVAILABLE_NOTE
        return ToolResult(
            data=dict(data),
            provenance=Provenance(source="nabiz_reliability", source_url="", observed_at=utcnow()),
            note=note,
        )


def client_for(nabiz: FakeNabiz) -> TestClient:
    app = FastAPI()
    app.state.nabiz = nabiz
    app.state.settings = offline_settings()
    app.include_router(compare_routes)
    return TestClient(app)


def test_compare_returns_metro_bus_and_enrichment_with_provenance() -> None:
    nabiz = FakeNabiz()
    with client_for(nabiz) as client:
        response = client.get("/api/compare", params={"from": "Kadıköy", "to": "Taksim"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert [option["mode"] for option in body["options"]] == ["metro", "bus"]
    metro, bus = body["options"]
    assert (metro["minutes"], metro["transfers"]) == (34.0, 1)
    assert metro["accessibility"]["lift_status"] == "out_of_service"
    assert metro["accessibility"]["note"] == "asansör arızalı (İBB kaydı)"
    assert (bus["minutes"], bus["transfers"], bus["line_code"]) == (41.5, 0, "14M")
    assert bus["reliability"]["available"] is True
    assert all(option["provenance"]["source"] == "nabiz_routing" for option in body["options"])
    assert all(option["provenance"]["mode"] == "recorded" for option in body["options"])
    assert nabiz.journey_args == {"origin": "Kadıköy", "destination": "Taksim"}
    assert nabiz.accessibility_calls == [{"station": "Kadıköy", "needs": ["step_free"]}]
    assert nabiz.reliability_calls == [{"line_code": "14M"}]


def test_compare_missing_endpoints_returns_turkish_400() -> None:
    with client_for(FakeNabiz()) as client:
        response = client.get("/api/compare", params={"from": "Kadıköy"})
    assert response.status_code == 400
    assert response.json() == {"error": "bad_request", "message": "Başlangıç ve varış noktalarını yazın."}


def test_compare_rejects_unsupported_needs() -> None:
    nabiz = FakeNabiz()
    with client_for(nabiz) as client:
        response = client.get("/api/compare", params={"from": "Kadıköy", "to": "Taksim", "needs": "wheelchair"})
    assert response.status_code == 400 and "wheelchair" in response.json()["message"]
    assert nabiz.journey_args is None


def test_unavailable_modes_keep_reasons_without_blank_numbers() -> None:
    with client_for(FakeNabiz(unavailable=True)) as client:
        body = client.get("/api/compare", params={"from": "Kadıköy", "to": "Taksim"}).json()
    assert body["unavailable"] == [
        {"mode": "metro", "label": "Metro / raylı sistem", "reason": "Metro istasyonu bulunamadı."},
        {"mode": "bus", "label": "Otobüs", "reason": "Bu yolculuk için tek hat yok."},
    ]
    assert all(option["minutes"] is None and option["transfers"] is None for option in body["options"])


def test_enrichment_failures_leave_route_estimates_available() -> None:
    nabiz = FakeNabiz(accessibility_error=RateLimitExceeded("budget", source="metro_equipment"))
    with client_for(nabiz) as client:
        response = client.get("/api/compare", params={"from": "Kadıköy", "to": "Taksim"})
    assert response.status_code == 200
    metro, bus = response.json()["options"]
    assert metro["minutes"] == 34.0 and metro["accessibility"] is None
    assert metro["accessibility_note"] == "Asansör durumu okunamadı."
    assert bus["minutes"] == 41.5


def test_unavailable_reliability_note_is_preserved_exactly() -> None:
    with client_for(FakeNabiz(reliability_available=False)) as client:
        body = client.get("/api/compare", params={"from": "Kadıköy", "to": "Taksim"}).json()
    assert body["options"][1]["reliability"] == {
        "available": False,
        "note": UNAVAILABLE_NOTE,
        "median_headway_min": None,
        "bunching_label": None,
    }


def test_reliability_failure_leaves_route_estimate_available() -> None:
    nabiz = FakeNabiz(reliability_error=UpstreamUnavailable("offline", source="reliability"))
    with client_for(nabiz) as client:
        response = client.get("/api/compare", params={"from": "Kadıköy", "to": "Taksim"})
    assert response.status_code == 200
    bus = response.json()["options"][1]
    assert bus["minutes"] == 41.5 and bus["reliability"] is None
    assert bus["reliability_note"] == "Hat düzenliliği okunamadı."


def test_coordinate_endpoints_are_passed_to_the_checked_tool_inputs() -> None:
    nabiz = FakeNabiz(unavailable=True)
    with client_for(nabiz) as client:
        response = client.get("/api/compare", params={"from": "40.90,29.20", "to": "41.05,28.98"})
    assert response.status_code == 200
    assert nabiz.journey_args == {
        "origin": "40.90,29.20", "origin_lat": 40.90, "origin_lon": 29.20,
        "destination": "41.05,28.98", "destination_lat": 41.05, "destination_lon": 28.98,
    }


def test_official_service_disclaimer_remains_on_the_page() -> None:
    page = (ROOT / "src/nabiz/console/static/index.html").read_text(encoding="utf-8")
    assert "Resmî İBB hizmeti değildir" in page
