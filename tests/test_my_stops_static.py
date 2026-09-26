from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import offline_settings, refuse_network
from fastapi.testclient import TestClient
from httpx import MockTransport

from ibb_mcp.cache import TTLCache
from ibb_mcp.http import PoliteClient
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC = REPO_ROOT / "src/nabiz/console/static"
SCRIPT = STATIC / "js/my_stops.js"
STYLE = STATIC / "css/my_stops.css"


def node_json(tmp_path: Path, body: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    harness = tmp_path / "my_stops_harness.mjs"
    harness.write_text(f"import * as stops from {json.dumps(SCRIPT.as_uri())};\n{body}\n", encoding="utf-8")
    result = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_my_stops_assets_exist_and_parse() -> None:
    assert SCRIPT.is_file()
    assert STYLE.is_file()
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    for asset in (SCRIPT,):
        result = subprocess.run([node, "--check", str(asset)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
    imports = re.findall(r"from\s+['\"](\./[^'\"]+\.js)['\"]", SCRIPT.read_text(encoding="utf-8"))
    assert imports
    assert all((SCRIPT.parent / imported.removeprefix("./")).is_file() for imported in imports)


def test_my_stops_never_says_working_or_eta() -> None:
    source = SCRIPT.read_text(encoding="utf-8") + STYLE.read_text(encoding="utf-8")
    assert not re.search(r"\bETA\b", source, re.I)
    assert not re.search(r"asansör[^.\n]{0,40}\bçalışıyor\b", source, re.I)
    assert "şimdi" not in source.lower()
    assert not re.search(r"[\u2012-\u2015\u2212]", source)
    assert "yapay zekâ tarafından üretildi" not in source.lower()


def test_items_pair_profile_places_and_the_device_store(tmp_path: Path) -> None:
    values = node_json(tmp_path, """
const items = stops.buildItems({stations:['Kartal'], lines:['M4','500T']}, [], [{line:'500T', stop:'Şifa Sondurak'}]);
console.log(JSON.stringify([items, stops.buildItems({}, [], [])]));
""")
    assert values == [
        [
            {"kind": "stop", "line": "500T", "stop": "Şifa Sondurak", "key": "500T|şifa sondurak"},
            {"kind": "station", "station": "Kartal", "key": "station:Kartal"},
        ],
        [],
    ]
    capped = node_json(tmp_path, """
const pairs = Array.from({length:8}, (_, i) => ({line:`${i}T`, stop:`Durak ${i}`}));
console.log(JSON.stringify([stops.buildItems({}, [], pairs).length, stops.MAX_ITEMS]));
""")
    assert capped == [6, 6]


def test_requests_carry_no_profile_fields(tmp_path: Path) -> None:
    values = node_json(tmp_path, """
console.log(JSON.stringify([
  stops.requestsFor({kind:'stop',line:'500T',stop:'Şifa Sondurak'}),
  stops.requestsFor({kind:'station',station:'Kartal'}),
  stops.requestsFor({kind:'line',line:'500T'})
]));
""")
    assert values == [
        [{"path": "/api/arrival", "params": {"line": "500T", "stop": "Şifa Sondurak"}}],
        [{"path": "/api/alternative", "params": {"station": "Kartal", "needs": "step_free"}}],
        [],
    ]
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("post(", "fetch(", "nabiz.profile.v1", "effectiveNeeds", "consent", "writeProfile", "addMemory"):
        assert forbidden not in source


def test_arrival_row_shows_the_server_minute_verbatim(tmp_path: Path) -> None:
    arrival = json.loads((STATIC / "mock/arrival.json").read_text(encoding="utf-8"))
    values = node_json(tmp_path, f"""
const data = {json.dumps(arrival, ensure_ascii=False)};
const scheduled = stops.arrivalRow({{...data, display:'tarifeye göre', minutes:null}});
const missing = stops.arrivalRow({{minutes:null}});
console.log(JSON.stringify([stops.arrivalRow(data), scheduled, missing]));
""")
    assert "7 dk" in values[0]
    assert "40 sn önce" in values[0]
    assert "tarifeye göre" in values[1] and not re.search(r"\d+ dk", values[1])
    assert "doğrulanamadı" in values[2]


def test_lift_row_never_says_working_and_offers_the_step_free_path(tmp_path: Path) -> None:
    alternative = json.loads((STATIC / "mock/alternative.json").read_text(encoding="utf-8"))
    values = node_json(tmp_path, f"""
const data = {json.dumps(alternative, ensure_ascii=False)};
const fault = stops.liftRow(data, 'mystop-0');
const empty = stops.liftRow({{lift_status:'out_of_service', alternative:null}}, 'mystop-1');
const rows = ['working','out_of_service','unknown'].map(lift_status => stops.liftRow({{lift_status}}, 'mystop-x'));
console.log(JSON.stringify([fault, empty, rows]));
""")
    assert "Adımsız yol" in values[0] and 'aria-controls="mystop-0-alt"' in values[0]
    assert "Pendik" in values[0] and "6 dk" in values[0] and "Operatör onaylı (simüle)" in values[0]
    assert "tel:153" in values[1]
    assert "İBB kaydında arıza yok" in values[2][0]
    assert "doğrulanamadı" in values[2][2]
    assert all("asansör çalışıyor" not in row.lower() for row in values[2])


def test_suggestion_after_three_asks_and_never_without_yes(tmp_path: Path) -> None:
    values = node_json(tmp_path, """
let state = {v:1, asked:{}};
const first = stops.bumpAsk(state, '500t', 'Şifa  Sondurak', []); state = first.state;
const second = stops.bumpAsk(state, '500T', 'ŞİFA SONDURAK', []); state = second.state;
const third = stops.bumpAsk(state, '500T', 'Şifa Sondurak', []); state = third.state;
const declined = stops.dismissAsk(state, '500T|şifa sondurak');
const fifth = stops.bumpAsk(declined, '500t', 'Şifa Sondurak', []);
const saved = stops.bumpAsk(state, '500T', 'Şifa Sondurak', ['500T|şifa sondurak']);
console.log(JSON.stringify([first.suggest, second.suggest, third.suggest, fifth.suggest, saved.suggest, state]));
""")
    assert values[:5] == [False, False, True, False, False]
    assert values[5]["asked"]["500T|şifa sondurak"]["n"] == 3


def test_storage_is_wrapped_and_keys_are_named(tmp_path: Path) -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "'nabiz.my-stops.v1'" in source
    assert "'nabiz.my-stops.asked.v1'" in source
    assert re.search(r"try\s*\{[^}]*localStorage\.getItem\(STORE_KEY\)", source, re.S)
    assert re.search(r"try\s*\{[^}]*localStorage\.setItem\(STORE_KEY", source, re.S)
    assert re.search(r"try\s*\{[^}]*localStorage\.getItem\(ASKED_KEY\)", source, re.S)
    assert re.search(r"try\s*\{[^}]*localStorage\.setItem\(ASKED_KEY", source, re.S)
    values = node_json(tmp_path, "console.log(JSON.stringify(stops.readStore()));")
    assert values == []


def test_strip_markup_is_keyboard_ready_and_fits_320(tmp_path: Path) -> None:
    markup = node_json(tmp_path, "console.log(JSON.stringify(stops.stripMarkup([])));" )
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'ul class="mystops-strip" id="my-stops-list"' in source
    assert "Durak ekle" in markup and 'href="#profilim"' in markup
    assert 'aria-label="Kayıtlı duraklar ve istasyonlar"' in markup
    values = node_json(tmp_path, """
console.log(JSON.stringify(stops.stripMarkup([
 {kind:'stop',line:'500T',stop:'Şifa Sondurak',key:'a'},
 {kind:'station',station:'Kartal',key:'b'}
])));
""")
    assert 'aria-label="Kayıtlı duraklar ve istasyonlar"' in values
    assert 'tabindex="0"' in values and 'tabindex="-1"' in values
    assert 'aria-labelledby="mystop-0-t"' in values
    style = STYLE.read_text(encoding="utf-8")
    assert "overflow-x: auto" in style and "scroll-snap-type: x proximity" in style
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgb|hsl)a?\s*\(", style)
    assert "transition" not in style and "animation" not in style


def test_the_endpoints_the_strip_reads_keep_their_shape() -> None:
    nabiz = Nabiz(SourceContext.create(client=PoliteClient(transport=MockTransport(refuse_network)),
                                       cache=TTLCache(), settings=offline_settings()))
    app = build_console_app(settings=offline_settings(), nabiz=nabiz, llm_config=llm.LlmConfig(),
                            guard=SpendGuard(BudgetConfig(state_path=None)))
    with TestClient(app) as client:
        arrival = client.get("/api/arrival", params={"line": "500T", "stop": "Şifa Sondurak"})
        alternative = client.get("/api/alternative", params={"station": "Kartal", "needs": "step_free"})
    assert arrival.status_code == 200
    assert re.fullmatch(r"\d+ dk|tarifeye göre|doğrulanamadı", arrival.json()["display"])
    assert alternative.status_code == 200
    assert alternative.json()["lift_status"] in {"working", "out_of_service", "unknown"}
    assert "alternative" in alternative.json()
