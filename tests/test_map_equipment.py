"""Recorded escalator and moving walkway map API and pure UI helpers."""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
from typing import Any

from conftest import FIXTURES_DIR, REPO_ROOT
from fastapi.testclient import TestClient
from test_map_layers_api import assert_safe_answer, layers_app, offline_nabiz, write_recordings

from ibb_mcp.sources.metro_equipment import EQUIPMENT_GROUPS, EQUIPMENT_TYPES
from nabiz.console.map_layers_api import MOVING_GROUPS, MOVING_TYPES, TYPE_TR

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"


def equipment_response(nabiz: Any) -> dict[str, Any]:
    with TestClient(layers_app(nabiz)) as client:
        response = client.get("/api/map/equipment")
    assert response.status_code == 200
    return response.json()


def test_equipment_counts_match_the_recording() -> None:
    body = equipment_response(offline_nabiz(FIXTURES_DIR))
    assert body["counts"] == {"escalator": 38, "moving_walkway": 8}
    assert body["count"] == 46
    assert sum(feature["properties"]["not_operated"] for feature in body["features"]) == 14
    assert body["equipment_record"] == "read"


def test_equipment_features_carry_the_ibb_sentence_and_date() -> None:
    body = equipment_response(offline_nabiz(FIXTURES_DIR))
    for feature in body["features"]:
        properties = feature["properties"]
        assert "kullanılamıyor" in properties["text"]
        assert "İBB kaydındaki durum:" in properties["text"]
        if properties["ibb_date"]:
            assert "İBB kaydındaki tarih:" in properties["text"]


def test_equipment_never_says_working() -> None:
    body = equipment_response(offline_nabiz(FIXTURES_DIR))
    assert_safe_answer(body)
    assert all("çalışıyor" not in feature["properties"]["text"].casefold() for feature in body["features"])


def test_unread_equipment_is_200_and_says_so() -> None:
    nabiz = offline_nabiz(FIXTURES_DIR)

    async def unavailable(**kwargs: Any) -> None:
        raise RuntimeError("recording unavailable")

    nabiz.metro_equipment_status = unavailable
    body = equipment_response(nabiz)
    assert body["equipment_record"] == "unread"
    assert body["note"] == "Yürüyen merdiven ve bant kaydı okunamadı; durumları doğrulanamadı."
    assert body["features"] == []


def test_empty_moving_groups_say_not_proven_usable(tmp_path: pathlib.Path) -> None:
    write_recordings(
        tmp_path,
        {"Asansör": [], "Yürüyen Merdiven": [], "Yürüyen Bant": []},
        summary=[],
    )
    body = equipment_response(offline_nabiz(tmp_path))
    assert body["equipment_record"] == "read"
    assert body["count"] == 0
    expected = "İBB kaydında kullanılamayan yürüyen merdiven ya da bant yok. "
    assert body["note"] == expected + "Bu, kullanılabilir oldukları anlamına gelmez."


def test_feature_ids_are_unique_stable_and_not_from_code() -> None:
    first = equipment_response(offline_nabiz(FIXTURES_DIR))
    second = equipment_response(offline_nabiz(FIXTURES_DIR))
    ids = [feature["id"] for feature in first["features"]]
    assert ids == [feature["id"] for feature in second["features"]]
    assert len(ids) == len(set(ids)) == 46
    assert all(re.fullmatch(r"(?:esc|walk)-\d+", feature_id) for feature_id in ids)
    assert all("code" not in feature["properties"] for feature in first["features"])


def test_the_lift_layer_is_unchanged() -> None:
    with TestClient(layers_app(offline_nabiz(FIXTURES_DIR))) as client:
        response = client.get("/api/map/lifts")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 9
    assert body["lift_record"] == "read"
    assert all(
        set(feature["properties"]) == {"kind", "station", "line", "status", "ibb_date", "location", "text", "placed"}
        for feature in body["features"]
    )
    assert body["features"][0]["id"] == "lift-1"


def test_group_names_match_the_facade() -> None:
    assert tuple(group for group in EQUIPMENT_GROUPS if group != "Asansör") == MOVING_GROUPS
    moving_types = frozenset(value for key, value in EQUIPMENT_TYPES.items() if key != "asansor")
    assert moving_types == MOVING_TYPES
    assert TYPE_TR == {"escalator": "yürüyen merdiven", "moving_walkway": "yürüyen bant"}
    assert all(EQUIPMENT_TYPES[key] in MOVING_TYPES for key in ("yuruyen merdiven", "yuruyen bant"))


def run_node(tmp_path: pathlib.Path, body: str) -> Any:
    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node is not installed")
    helper = (STATIC / "js" / "map_equipment.js").as_uri()
    layers = (STATIC / "js" / "map_layers.js").as_uri()
    harness = tmp_path / "map_equipment_harness.mjs"
    harness.write_text(
        "import * as E from " + json.dumps(helper) + ";\n"
        + "import * as L from " + json.dumps(layers) + ";\n"
        + body + "\n",
        encoding="utf-8",
    )
    result = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_equipment_helpers_in_node(tmp_path: pathlib.Path) -> None:
    data = run_node(
        tmp_path,
        """
const feature = (id, type, station, not_operated, placed = true) => ({id, properties: {
  equipment_type: type, station, not_operated, placed, text: station + ' kayıt cümlesi',
}});
const collection = {features: [feature('esc-1', 'escalator', 'Kartal', false),
  feature('walk-1', 'moving_walkway', 'Kartal', true), feature('walk-2', 'moving_walkway', 'Pendik', false, false)]};
const selected = E.equipmentFeatures(collection, ['escalators', 'walkways']);
const parts = E.splitNotOperated(selected);
const stations = E.stationTypes(collection, ['escalators', 'walkways']);
const template = E.layersTemplate();
console.log(JSON.stringify({text: E.equipmentRowText(selected[2]), active: parts.active.length,
  notOperated: parts.notOperated.length, stationTypes: [...stations].map(([name, types]) => [name, [...types]]),
  ids: ['stations', 'lifts', 'escalators', 'walkways'].map((name) => template.includes('map-layers-' + name + '-toggle')),
  section: template.includes('id="harita-katmanlari"'), eventLayers: [...L.validDetail({layers: ['escalators']}).layers]}));
""",
    )
    assert data["text"].endswith(" · Haritada yeri bulunamadı")
    assert data["active"] == 2 and data["notOperated"] == 1
    assert data["stationTypes"] == [["Kartal", ["escalator", "moving_walkway"]]]
    assert data["ids"] == [True, True, True, True] and data["section"] is True
    assert data["eventLayers"] == ["escalators"]


def test_equipment_only_station_is_not_labelled_as_a_lift(tmp_path: pathlib.Path) -> None:
    data = run_node(
        tmp_path,
        """
const stations = {features: [{id: 'station-kartal', geometry: {type: 'Point', coordinates: [29.2, 40.9]},
  properties: {kind: 'station', name: 'Kartal', lift_record: 'no_fault_record'}}]};
const equipment = {features: [{id: 'esc-1', geometry: {type: 'Point', coordinates: [29.2, 40.9]},
  properties: {kind: 'equipment', equipment_type: 'escalator', station: 'Kartal', placed: true}}]};
const points = L.featuresToPoints(stations, {features: []}, {layers: ['escalators'], equipment});
const clicked = L.withCard([], 'ml-esc-1', stations, {features: []}, {layers: ['escalators'], equipment: equipment.features});
console.log(JSON.stringify({points, clicked}));
""",
    )
    assert len(data["points"]) == 1
    assert not data["points"][0].get("broken", False)
    assert data["points"][0]["label"].endswith("yürüyen merdiven kaydı")
    assert data["clicked"][0]["card"] == "ml-esc-1"
    assert not data["clicked"][0].get("broken", False)


def test_moving_layers_are_opt_in_for_events(tmp_path: pathlib.Path) -> None:
    data = run_node(
        tmp_path,
        "console.log(JSON.stringify({one:[...L.validDetail({layers:['escalators']}).layers],"
        + "default:[...L.validDetail({}).layers]}));",
    )
    assert data == {"one": ["escalators"], "default": ["stations", "lifts"]}


def test_map_equipment_module_is_pure() -> None:
    source = (STATIC / "js" / "map_equipment.js").read_text(encoding="utf-8")
    assert not any(token in source for token in ("document", "window", "localStorage", "fetch("))
    assert len(source.splitlines()) <= 300
