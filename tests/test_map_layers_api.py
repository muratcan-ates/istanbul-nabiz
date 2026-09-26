"""Map layer API and browser contract tests; generated equipment rows are test values, not İBB data."""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from conftest import FIXTURES_DIR, REPO_ROOT
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ibb_mcp.cache import TTLCache
from ibb_mcp.config import Settings
from ibb_mcp.http import PoliteClient, UpstreamUnavailable
from ibb_mcp.models import LAT_RANGE, LON_RANGE, Provenance, ToolResult, utcnow
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.sources.metro_equipment import details_fixture_name, summary_fixture_name
from ibb_mcp.tools import Nabiz
from nabiz.console.map_layers_api import (
    LIFT_RECORD_TEXT,
    NOTE_EMPTY,
    NOTE_UNREAD,
    lifts_collection,
    map_layers_routes,
    offline_flag,
    stations_collection,
)

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"


def refuse_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"offline map test reached the network: {request.url}")


def layers_app(nabiz: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(map_layers_routes)
    app.state.nabiz = nabiz
    return app


def offline_nabiz(directory: pathlib.Path) -> Nabiz:
    settings = Settings(offline=True, fixtures_dir=directory)
    client = PoliteClient(transport=httpx.MockTransport(refuse_network))
    return Nabiz(SourceContext.create(client=client, cache=TTLCache(), settings=settings))


def record(
    station: str = "Kartal",
    line: str = "M4",
    *,
    station_id: int | None = 16,
    line_id: int | None = 3,
    code: str = "TEST-ASN-01",
    date: str | None = "2026-09-20T08:00:00",
    kind: str = "Arıza",
) -> dict[str, Any]:
    """Create one synthetic detail row in the source's verified field shape."""
    return {
        "Code": code,
        "Group": "Asansör",
        "LineId": line_id,
        "LineName": line,
        "StationId": station_id,
        "StationName": station,
        "Location": None,
        "Type": kind,
        "Date": date,
        "Description": None,
    }


def envelope(rows: list[Any]) -> dict[str, Any]:
    return {"Success": True, "Error": None, "Data": rows}


def write_recordings(
    directory: pathlib.Path,
    details: dict[str, list[Any]],
    summary: list[Any] | None,
    stamp: str = "20260101",
) -> None:
    """Use a private fixtures folder with generated test rows and a copied station list."""
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES_DIR / "metro_stations.json", directory / "metro_stations.json")
    for group, rows in details.items():
        target = directory / f"{details_fixture_name(group, stamp)}.json"
        target.write_text(json.dumps(envelope(rows)), encoding="utf-8")
    if summary is not None:
        target = directory / f"{summary_fixture_name(stamp)}.json"
        target.write_text(json.dumps(envelope(summary)), encoding="utf-8")


def get_layers(nabiz: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    with TestClient(layers_app(nabiz)) as client:
        stations = client.get("/api/map/stations")
        lifts = client.get("/api/map/lifts")
    assert stations.status_code == 200
    assert lifts.status_code == 200
    return stations.json(), lifts.json()


def assert_safe_answer(body: dict[str, Any]) -> None:
    encoded = json.dumps(body, ensure_ascii=False)
    assert not re.search(r"working|çalışıyor|calisiyor", encoded, re.I)
    assert "\u2014" not in encoded and "\u2013" not in encoded
    assert not re.search(r"\bETA\b", encoded, re.I)


def test_stations_is_a_geojson_feature_collection(tmp_path: pathlib.Path) -> None:
    write_recordings(tmp_path, {}, None)
    nabiz = offline_nabiz(tmp_path)
    stations, _ = get_layers(nabiz)
    expected = sum(place.kind == "metro_station" for place in nabiz.places.places)
    assert stations["type"] == "FeatureCollection"
    assert stations["count"] == len(stations["features"]) == expected
    for feature in stations["features"]:
        assert feature["type"] == "Feature"
        assert feature["geometry"]["type"] == "Point"
        lon, lat = feature["geometry"]["coordinates"]
        assert isinstance(lon, float) and isinstance(lat, float)
        assert LON_RANGE[0] <= lon <= LON_RANGE[1]
        assert LAT_RANGE[0] <= lat <= LAT_RANGE[1]
        assert set(feature["properties"]) == {"kind", "name", "lift_record", "text"}
        assert feature["properties"]["kind"] == "station"
        assert_safe_answer(feature)


def test_station_ids_are_unique_and_stable(tmp_path: pathlib.Path) -> None:
    write_recordings(tmp_path, {}, None)
    first, _ = get_layers(offline_nabiz(tmp_path))
    second, _ = get_layers(offline_nabiz(tmp_path))
    ids = [feature["id"] for feature in first["features"]]
    assert len(ids) == len(set(ids))
    assert "station-bogazici-u-hisarustu" in ids
    assert "station-bogazici-u-hisarustu-2" in ids
    assert ids == [feature["id"] for feature in second["features"]]


def test_lifts_without_a_recording_is_an_empty_list_that_says_so(tmp_path: pathlib.Path) -> None:
    shutil.copy(FIXTURES_DIR / "metro_stations.json", tmp_path / "metro_stations.json")
    stations, lifts = get_layers(offline_nabiz(tmp_path))
    assert lifts["features"] == []
    assert lifts["lift_record"] == "unread"
    assert lifts["note"] == NOTE_UNREAD
    assert set(lifts["provenance"]) == {"source", "url", "observed_at", "age_s", "mode"}
    assert lifts["provenance"]["mode"] == "unknown"
    assert lifts["provenance"]["age_s"] is None
    assert all(feature["properties"]["lift_record"] == "unread" for feature in stations["features"])
    assert all(feature["properties"]["text"] == LIFT_RECORD_TEXT["unread"] for feature in stations["features"])
    assert_safe_answer(stations)
    assert_safe_answer(lifts)


def test_no_request_leaves_the_machine(tmp_path: pathlib.Path) -> None:
    shutil.copy(FIXTURES_DIR / "metro_stations.json", tmp_path / "metro_stations.json")
    stations, lifts = get_layers(offline_nabiz(tmp_path))
    assert stations["features"]
    assert lifts["features"] == []


def test_a_recorded_lift_fault_is_placed_on_its_station(tmp_path: pathlib.Path) -> None:
    write_recordings(tmp_path, {"Asansör": [record()]}, None)
    stations, lifts = get_layers(offline_nabiz(tmp_path))
    assert len(lifts["features"]) == 1
    item = lifts["features"][0]
    assert item["geometry"]["coordinates"] == [29.211026, 40.906818]
    assert item["properties"]["placed"] is True
    assert item["properties"]["status"] == "Arıza"
    by_id = {feature["id"]: feature["properties"] for feature in stations["features"]}
    assert by_id["station-kartal"]["lift_record"] == "recorded_fault"
    assert by_id["station-yenikapi"]["lift_record"] == "no_fault_record"
    assert by_id["station-yenikapi"]["text"] == "İBB kaydında arıza yok"
    assert_safe_answer(stations)
    assert_safe_answer(lifts)


async def test_a_record_the_facade_does_not_bind_stays_unplaced(tmp_path: pathlib.Path) -> None:
    write_recordings(tmp_path, {"Asansör": [record("VEZNECILER", "M2", station_id=21)]}, None)
    nabiz = offline_nabiz(tmp_path)
    lifts = await lifts_collection(nabiz, offline=True)
    stations = await stations_collection(nabiz, offline=True)
    assert lifts["features"][0]["geometry"] is None
    assert lifts["features"][0]["properties"]["placed"] is False
    facade = await nabiz.metro_equipment_status(station="VEZNECILER", group="Asansör")
    assert facade.data["count"] == 0
    assert all(feature["properties"]["lift_record"] != "recorded_fault" for feature in stations["features"])
    assert next(
        feature["properties"]
        for feature in stations["features"]
        if feature["properties"]["name"].startswith("Vezneciler")
    )["lift_record"] == "no_fault_record"
    assert_safe_answer(stations)
    assert_safe_answer(lifts)


def test_an_unknown_station_is_listed_without_a_point(tmp_path: pathlib.Path) -> None:
    write_recordings(tmp_path, {"Asansör": [record("Hiçyok İstasyonu")]}, None)
    _, lifts = get_layers(offline_nabiz(tmp_path))
    assert lifts["features"][0]["geometry"] is None
    assert lifts["features"][0]["properties"]["placed"] is False
    assert lifts["features"][0]["properties"]["text"]


def test_read_with_zero_records_says_no_fault_record_not_working(tmp_path: pathlib.Path) -> None:
    write_recordings(tmp_path, {"Asansör": []}, None)
    stations, lifts = get_layers(offline_nabiz(tmp_path))
    assert lifts["lift_record"] == "read"
    assert lifts["features"] == []
    assert lifts["note"] == NOTE_EMPTY
    assert all(feature["properties"]["lift_record"] == "no_fault_record" for feature in stations["features"])
    assert_safe_answer(stations)
    assert_safe_answer(lifts)


class FakePlace:
    def __init__(self, name: str, lat: float = 41.0, lon: float = 29.0) -> None:
        self.kind = "metro_station"
        self.name = name
        self.lat = lat
        self.lon = lon


class FakeNabiz:
    def __init__(
        self,
        *,
        places: list[FakePlace] | None = None,
        records: list[dict[str, Any]] | None = None,
        unread: bool = False,
        fail: bool = False,
    ) -> None:
        self.settings = Settings(offline=False)
        self.places = SimpleNamespace(places=places or [])
        self.records = records or []
        self.unread = unread
        self.fail = fail
        self.station_calls: list[str] = []
        self.provenance = Provenance(
            source="metro_equipment",
            source_url="local:test-equipment",
            observed_at=utcnow(),
        )

    async def metro_equipment_status(self, station: str | None = None, group: str | None = None) -> ToolResult:
        if self.fail:
            raise UpstreamUnavailable("synthetic failure", source="metro_equipment")
        if station is not None:
            self.station_calls.append(station)
            return ToolResult(
                data={"count": 0, "records": [], "station": {"name": station}},
                provenance=self.provenance,
            )
        return ToolResult(
            data={
                "available": not self.unread,
                "groups_read": [] if self.unread else ["Asansör"],
                "records": self.records,
                "stale": False,
                "uncertainty": [],
                "date_label": "İBB kaydındaki tarih",
                "disclaimer": "Resmî İBB hizmeti değildir.",
            },
            provenance=self.provenance,
        )


def fake_record(station: str, code: str = "fake") -> dict[str, Any]:
    return {
        "code": code,
        "equipment_type": "elevator",
        "station": station,
        "line": "M1",
        "status_type": "Arıza",
        "ibb_date": None,
        "location": None,
        "text": station + ": asansör kullanılamıyor, İBB kaydındaki durum: Arıza.",
    }


@pytest.mark.parametrize("mode", ["unread", "fault", "empty", "failure"])
def test_no_answer_says_working(mode: str) -> None:
    if mode == "unread":
        nabiz = FakeNabiz(unread=True)
    elif mode == "fault":
        nabiz = FakeNabiz(places=[FakePlace("Kartal")], records=[fake_record("Kartal")])
    elif mode == "empty":
        nabiz = FakeNabiz()
    else:
        nabiz = FakeNabiz(fail=True)
    stations, lifts = get_layers(nabiz)
    assert_safe_answer(stations)
    assert_safe_answer(lifts)


def test_an_equipment_failure_is_unread_not_500() -> None:
    nabiz = FakeNabiz(places=[FakePlace("Kartal"), FakePlace("Yenikapı")], fail=True)
    with TestClient(layers_app(nabiz)) as client:
        stations = client.get("/api/map/stations")
        lifts = client.get("/api/map/lifts")
    assert stations.status_code == lifts.status_code == 200
    assert stations.json()["lift_record"] == lifts.json()["lift_record"] == "unread"
    assert lifts.json()["provenance"]["mode"] == "unknown"


async def test_lift_lookup_is_capped() -> None:
    rows = [fake_record(f"Bilinmeyen {index}", str(index)) for index in range(50)]
    nabiz = FakeNabiz(records=rows)
    result = await lifts_collection(nabiz, offline=False)
    assert result["count"] == 50
    assert len(nabiz.station_calls) <= 40


def test_offline_flag_prefers_app_state_fresh() -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                fresh=SimpleNamespace(offline=True),
                nabiz=SimpleNamespace(settings=SimpleNamespace(offline=False)),
            )
        )
    )
    assert offline_flag(request) is True
    fallback = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(nabiz=SimpleNamespace(settings=SimpleNamespace(offline=True))))
    )
    assert offline_flag(fallback) is True
    both_false = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                fresh=SimpleNamespace(offline=False),
                nabiz=SimpleNamespace(settings=SimpleNamespace(offline=False)),
            )
        )
    )
    assert offline_flag(both_false) is False


async def test_empty_gazetteer_returns_a_clear_station_note() -> None:
    result = await stations_collection(FakeNabiz(), offline=False)
    assert result["type"] == "FeatureCollection"
    assert result["features"] == []
    assert result["note"] == "İstasyon listesi bu sunucuda yok."


def test_map_layers_js_contract() -> None:
    sources = [
        (STATIC / "js" / "map_layers.js").read_text(encoding="utf-8"),
        (STATIC / "js" / "map_equipment.js").read_text(encoding="utf-8"),
    ]
    source = "\n".join(sources)
    required = [
        "nabiz:show-on-map",
        "import('./map.js')",
        "showOnMap",
        "highlightMarker",
        "withCard",
        "initMap",
        "'/api/map/stations'",
        "'/api/map/lifts'",
        "'/api/map/equipment'",
        'id="harita-katmanlari"',
        "ArrowDown",
    ]
    for phrase in required:
        assert phrase in source, phrase
    forbidden = [
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "navigator.geolocation",
        "sendBeacon",
        "WebSocket",
        "animate(",
        "behavior: 'smooth'",
        "working",
        "çalışıyor",
        "\u2014",
        "\u2013",
    ]
    assert not [phrase for phrase in forbidden if any(phrase.casefold() in item.casefold() for item in sources)]
    assert all(not re.search(r"\bETA\b", item, re.I) for item in sources)
    assert all("from './" not in item for item in sources)
    assert all(len(item.splitlines()) <= 300 for item in sources)
    icon_names = set(re.findall(r"icon\('([^']+)'\)", source))
    icon_source = (STATIC / "icons.svg").read_text(encoding="utf-8")
    assert icon_names
    assert all('id="i-' + name + '"' in icon_source for name in icon_names)


def test_map_layers_css_tokens_and_label() -> None:
    source = (STATIC / "css" / "map_layers.css").read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(|oklch\(", source, re.I)
    assert not re.search(r"animation|transition|@keyframes", source, re.I)
    assert 'content: "Asansör"' in source
    assert ".is-broken::after" in source
    assert len(source.splitlines()) <= 350
    assert "\u2014" not in source and "\u2013" not in source


def node_json(tmp_path: pathlib.Path, body: str) -> Any:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    module = (STATIC / "js" / "map_layers.js").as_uri()
    harness = tmp_path / "map_layers_harness.mjs"
    harness.write_text(
        "import * as L from " + json.dumps(module) + ";\n" + body + "\n",
        encoding="utf-8",
    )
    result = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_row_text_and_points_in_node(tmp_path: pathlib.Path) -> None:
    data = node_json(
        tmp_path,
        """
const makeStation = (id, name, lon, lift_record, text) => ({
  type: 'Feature', id, geometry: {type: 'Point', coordinates: [lon, 40.9]},
  properties: {kind: 'station', name, lift_record, text},
});
const stations = Array.from({length: 10}, (_, i) => makeStation(
  'station-' + i, i === 0 ? 'Kartal' : 'İstasyon ' + i, 29 + i / 100,
  i === 0 ? 'recorded_fault' : 'no_fault_record',
  i === 0 ? 'İBB kaydında asansör arızası var' : 'İBB kaydında arıza yok',
));
const lifts = [{
  type: 'Feature', id: 'lift-1', geometry: {type: 'Point', coordinates: [29, 40.9]},
  properties: {kind: 'lift', station: 'Kartal', status: 'Arıza', placed: true, text: 'Kartal (M4): asansör kullanılamıyor.'},
}];
const unread = {...stations[1], properties: {...stations[1].properties, lift_record: 'unread'}};
const detail = L.validDetail({points: [{lat: 91, lon: 0, label: 'x'}], layers: []});
const clean = L.validDetail({points: [{lat: 41, lon: 29, label: 'x'.repeat(200), broken: true}]});
const faultPoints = L.featuresToPoints(stations, lifts, {layers: ['lifts']});
const nearest = L.featuresToPoints(stations, lifts, {layers: ['stations', 'lifts'], focus: {lat: 40.9, lon: 29}});
const ninth = 'ml-' + stations[8].id;
const extended = L.withCard(nearest, ninth, stations, lifts, {layers: ['stations', 'lifts']});
const already = L.withCard(nearest, nearest[0].card, stations, lifts, {layers: ['stations', 'lifts']});
const unplaced = [{...lifts[0], id: 'lift-2', geometry: null, properties: {...lifts[0].properties, placed: false}}];
const same = L.withCard(nearest, 'ml-lift-2', stations, unplaced, {layers: ['stations', 'lifts']});
console.log(JSON.stringify({
  faultText: L.rowText(stations[0], {ageLabel: '12 dk önce'}),
  noFaultText: L.rowText(stations[1], {ageLabel: '12 dk önce'}),
  unreadText: L.rowText(unread, {ageLabel: '12 dk önce'}),
  unreadDistanceText: L.rowText(unread, {distance: 450, ageLabel: '12 dk önce'}),
  liftUnplacedText: L.rowText(unplaced[0]),
  faultPoints, nearestCount: nearest.length,
  liftOnlyCount: faultPoints.length, faultBroken: faultPoints[0].broken,
  extendedCount: extended.length, extendedCard: extended[extended.length - 1].card,
  alreadySame: already === nearest, unplacedSame: same === nearest,
  invalidCount: detail.points.length, defaults: Array.from(detail.layers),
  labelLength: clean.points[0].label.length,
  badKind: clean.points[0].kind, eventBroken: clean.points[0].broken || false,
  distance: L.distanceM({lat: 40.906818, lon: 29.211026}, {lat: 41.005, lon: 28.95}),
}));
""",
    )
    assert data["faultText"] == "Kartal · İBB kaydında asansör arızası var · 12 dk önce"
    assert data["noFaultText"] == "İstasyon 1 · İBB kaydında arıza yok · 12 dk önce"
    assert data["unreadText"] == "İstasyon 1"
    assert data["unreadDistanceText"] == "İstasyon 1 · 450 m"
    assert data["liftUnplacedText"].endswith(" · Haritada yeri bulunamadı")
    assert data["liftOnlyCount"] == 1 and data["faultBroken"] is True
    assert data["nearestCount"] == 8
    assert data["extendedCount"] == 9 and data["extendedCard"] == "ml-station-8"
    assert data["alreadySame"] is True and data["unplacedSame"] is True
    assert data["invalidCount"] == 0 and data["defaults"] == ["stations", "lifts"]
    assert data["labelLength"] == 80 and data["badKind"] == "place"
    assert data["eventBroken"] is False
    assert 20000 < data["distance"] < 30000
