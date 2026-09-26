"""Offline API and rendering contracts for the single trip card."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import httpx
import pytest
from conftest import REPO_ROOT, offline_settings, refuse_network
from fastapi.testclient import TestClient

from ibb_mcp.cache import TTLCache
from ibb_mcp.http import PoliteClient
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"


def node_json(tmp_path, modules: dict[str, str], body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    imports = "\n".join(
        f"import * as {name} from {json.dumps((STATIC / path).as_uri())};" for name, path in modules.items()
    )
    harness = tmp_path / "trip_harness.mjs"
    harness.write_text(f"{imports}\n{body}\n", encoding="utf-8")
    result = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def offline_client():
    settings = offline_settings()
    nabiz = Nabiz(SourceContext.create(
        client=PoliteClient(transport=httpx.MockTransport(refuse_network)),
        cache=TTLCache(), settings=settings,
    ))
    app = build_console_app(
        settings=settings, nabiz=nabiz, llm_config=llm.LlmConfig(),
        guard=SpendGuard(BudgetConfig(state_path=None)),
    )
    return TestClient(app)


def read_list(source: str, name: str) -> set[str]:
    match = re.search(rf"const {name} = \[([^\]]*)\]", source)
    assert match, f"missing {name}"
    return set(re.findall(r"'(\w+)'", match.group(1)))


def test_offline_compare_carries_every_field_the_card_reads() -> None:
    with offline_client() as client:
        responses = [
            client.get("/api/compare", params={"from": "Kadıköy", "to": "Levent"}),
            client.get("/api/compare", params={"from": "Kartal", "to": "4. Levent"}),
        ]
    assert any(response.status_code == 200 for response in responses)
    source = (STATIC / "js" / "trip_view.js").read_text(encoding="utf-8")
    compare_reads = read_list(source, "COMPARE_READS")
    option_reads = read_list(source, "OPTION_READS")
    for response in responses:
        if response.status_code != 200:
            continue
        body = response.json()
        assert compare_reads <= set(body)
        for option in body["options"]:
            assert option_reads - {"line_code"} <= set(option)
            if option.get("mode") == "bus" and option.get("available"):
                assert "line_code" in option


def test_offline_journey_carries_every_field_the_card_reads() -> None:
    with offline_client() as client:
        response = client.get("/api/journey/accessible", params={"from": "Kadıköy", "to": "Levent"})
        alternative_response = client.get("/api/alternative", params={"station": "Kadıköy"})
    assert response.status_code == 200, response.text
    assert alternative_response.status_code == 200, alternative_response.text
    alternative_source = (STATIC / "js" / "trip_view.js").read_text(encoding="utf-8")
    alternative_reads = read_list(alternative_source, "ALTERNATIVE_READS")
    assert alternative_reads - {"text"} <= set(alternative_response.json())
    body = response.json()
    source = (STATIC / "js" / "trip_view.js").read_text(encoding="utf-8")
    journey_reads = read_list(source, "JOURNEY_READS")
    step_reads = read_list(source, "STEP_READS")
    if body["available"]:
        assert journey_reads - {"reason"} <= set(body)
    else:
        assert journey_reads - {"alternatives_used"} <= set(body)
    for step in body.get("steps", []):
        assert set(step) <= step_reads


@pytest.mark.asyncio
async def test_detour_fixture_carries_the_avoided_station_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    from test_journey_accessible import FakeFacade, configure_graph, lift_fault, station

    from ibb_mcp import journey_accessible
    from ibb_mcp.accessibility import EquipmentSnapshot
    from nabiz.console.cards import provenance_view

    rows = [station("A", 1, 29.00), station("B", 2, 29.01), station("C", 3, 29.02), station("D", 4, 29.03)]
    facade = FakeFacade(rows, EquipmentSnapshot(records=[lift_fault("B")], groups_read=["Asansör"]))
    configure_graph(monkeypatch, facade._graph)
    monkeypatch.setattr(journey_accessible.accessibility, "accessible_alternative", lambda *args, **kwargs: {
        "uncertainty": [],
        "alternative": {"station": "D", "line": "M1", "reason": "İBB kaydında D için asansör arızası yok."},
    })
    result = await journey_accessible.plan_accessible_journey(facade, "Start", "End")
    body = dict(result.data)
    body["provenance"] = provenance_view(result.provenance, offline=True)
    source = (STATIC / "js" / "trip_view.js").read_text(encoding="utf-8")
    detour_reads = read_list(source, "DETOUR_READS")
    step_reads = read_list(source, "STEP_READS")
    journey_reads = read_list(source, "JOURNEY_READS")
    assert body["available"] is True
    assert detour_reads <= set(body["alternatives_used"][0])
    assert body["alternatives_used"][0]["avoided_station"] == "B"
    assert journey_reads - {"reason"} <= set(body)
    assert all(set(step) <= step_reads for step in body["steps"])


def test_card_reads_only_declared_fields() -> None:
    view = (STATIC / "js" / "trip_view.js").read_text(encoding="utf-8")
    entry = (STATIC / "js" / "trip.js").read_text(encoding="utf-8")
    source = view + "\n" + entry
    exclusions = {"length", "map", "filter", "forEach", "find", "some", "every", "slice", "join",
                  "includes", "indexOf", "trim", "toFixed", "toString", "js"}
    contracts = {
        "option": read_list(view, "OPTION_READS"),
        "compare": read_list(view, "COMPARE_READS"),
        "journey": read_list(view, "JOURNEY_READS"),
        "step": read_list(view, "STEP_READS"),
        "alt": read_list(view, "DETOUR_READS"),
        "entry": read_list(view, "ALTERNATIVE_READS"),
    }
    for variable, allowed in contracts.items():
        used = set(re.findall(rf"\b{variable}\??\.(\w+)", source)) - exclusions
        assert used <= allowed, f"{variable}: undeclared fields {used - allowed}"
    assert not re.search(r"\b(?:compare|journey)\.error\b", source)


def test_detour_card_shows_record_age_and_never_says_working(tmp_path) -> None:
    entry = {
        "station": "B", "lift_status": "out_of_service",
        "provenance": {
            "source": "metro_equipment", "url": None,
            "observed_at": "2026-09-25T10:30:00+03:00", "age_s": 120, "mode": "recorded",
        },
    }
    detour = {
        "available": True, "from": "Start", "to": "End", "steps": [], "extra_minutes": 4,
        "alternative_used": {"station": "D", "line": "M1", "avoided_station": "B", "reason": "recorded"},
        "alternatives_used": [{"station": "D", "line": "M1", "avoided_station": "B", "reason": "recorded"}],
        "provenance": entry["provenance"], "uncertainty": [], "disclaimer": "",
    }
    compare = {"from": "Start", "to": "End", "options": [
        {"mode": "metro", "label": "Metro", "available": True, "minutes": 12, "transfers": 0,
         "accessibility": {"lift_status": "working"}, "provenance": entry["provenance"]},
        {"mode": "bus", "label": "Otobüs", "available": False, "minutes": None, "transfers": None,
         "reason": "Hat doğrulanamadı.", "provenance": entry["provenance"]},
    ], "disclaimer": ""}
    payload = json.dumps({"compare": compare, "detour": detour, "entry": entry}, ensure_ascii=False)
    values = node_json(
        tmp_path, {"view": "js/trip_view.js", "cards": "js/cards.js", "provenance": "js/provenance.js"},
        f"const data = {payload}; const args={{needs:[],liftByStation:{{B:data.entry}},compareError:null,journeyError:null}};"
        "const html=view.tripCardHtml(data.compare,data.detour,args);"
        "const pending=view.tripCardHtml(data.compare,data.detour,{...args,liftByStation:{}});"
        "const unknown=view.tripCardHtml(data.compare,data.detour,{...args,liftByStation:{B:{lift_status:'unknown'}}});"
        "const sentence=view.tripCardHtml(data.compare,data.detour,{...args,"
        "liftByStation:{B:{lift_status:'unknown',text:'B istasyonunda asansör yok.'}}});"
        "const partial=view.tripCardHtml(null,data.detour,{...args,compareError:'zaman aşımı'});"
        "console.log(JSON.stringify({html,pending,unknown,sentence,partial,age:provenance.ageText(data.entry.provenance),working:cards.LIFT_TR.working,unknownText:cards.LIFT_TR.unknown}));",
    )
    assert "Rotadan çıkarıldı: B" in values["html"]
    assert f"asansör kaydında arıza · {values['age']}" in values["html"]
    assert "Yerine D (M1) kullanıldı" in values["html"]
    assert values["working"] in values["html"]
    assert "asansör kaydı okunuyor" in values["pending"]
    assert values["unknownText"] in values["unknown"]
    assert "B istasyonunda asansör yok." in values["sentence"]
    assert values["unknownText"] not in values["sentence"]
    assert "Karşılaştırma alınamadı: zaman aşımı" in values["partial"]
    assert "trip-stepfree" in values["partial"]
    for html in values.values():
        assert "çalışıyor" not in html
        assert not re.search(r"\bETA\b", html)
    for path in ("js/trip.js", "js/trip_view.js"):
        assert "çalışıyor" not in (STATIC / path).read_text(encoding="utf-8")


def test_step_free_profile_puts_the_step_free_route_first(tmp_path) -> None:
    values = node_json(
        tmp_path, {"view": "js/trip_view.js"},
        "const compare={from:'A',to:'B',options:[],disclaimer:''};"
        "const journey={available:true,from:'A',to:'B',steps:[],extra_minutes:0,uncertainty:[],disclaimer:''};"
        "const top=view.tripCardHtml(compare,journey,{needs:['step_free'],liftByStation:{}});"
        "const stroller=view.tripCardHtml(compare,journey,{needs:['stroller'],liftByStation:{}});"
        "const normal=view.tripCardHtml(compare,journey,{needs:[],liftByStation:{}});"
        "console.log(JSON.stringify({orders:[view.sectionOrder(['step_free']),view.sectionOrder(['stroller']),view.sectionOrder([])],top,stroller,normal}));",
    )
    assert values["orders"] == [["stepfree", "compare"], ["stepfree", "compare"], ["compare", "stepfree"]]
    for html in (values["top"], values["stroller"]):
        assert html.index('id="trip-stepfree"') < html.index('class="trip-compare"')
        assert '<details id="trip-stepfree" class="trip-stepfree" open>' in html
    assert values["normal"].index('class="trip-compare"') < values["normal"].index('id="trip-stepfree"')
    assert '<details id="trip-stepfree" class="trip-stepfree">' in values["normal"]


def test_compare_row_uses_one_minute_figure(tmp_path) -> None:
    compare = json.loads((STATIC / "mock" / "compare.json").read_text(encoding="utf-8"))
    compare["from"] = "Kadıköy"
    compare["to"] = "Levent"
    values = node_json(
        tmp_path, {"view": "js/trip_view.js"},
        f"const compare={json.dumps(compare, ensure_ascii=False)};"
        "const html=view.comparisonRow(compare);"
        "const empty=view.comparisonRow({from:'A',to:'B',options:[{mode:'metro',label:'Metro',available:true,"
        "minutes:null,transfers:0,reason:'Süre kaydı yok.'}],disclaimer:''});"
        "console.log(JSON.stringify({html,empty}));",
    )
    assert "42 dk" in values["html"]
    assert "41,5" not in values["html"]
    assert "aktarmasız" in values["html"]
    assert "daha kısa" in values["html"]
    assert "Süre kaydı yok." in values["empty"]
    assert not re.search(r"\b\d+ dk\b", values["empty"])


def test_map_points_come_from_server_links_and_geo_uri_is_numeric(tmp_path) -> None:
    journey = json.loads((STATIC / "mock" / "journey.json").read_text(encoding="utf-8"))
    payload = json.dumps(journey, ensure_ascii=False)
    values = node_json(
        tmp_path, {"view": "js/trip_view.js"},
        f"const journey={payload};"
        "console.log(JSON.stringify({points:view.mapPoints(journey),evil:view.coordsFromLinks({apple:'https://evil.test/?daddr=1,2'}),"
        "script:view.coordsFromLinks({google:'javascript:alert(1)'}),range:view.coordsFromLinks({apple:'https://maps.apple.com/?daddr=100,29'}),"
        "geo:view.geoUri({lat:41.078,lon:29.01,label:'Levent'})}));",
    )
    source = (STATIC / "js" / "trip.js").read_text(encoding="utf-8")
    assert "'nabiz:show-on-map'" in source and "source: 'trip'" in source and "'harita-katmanlari'" in source
    assert source.index("dispatchEvent(") < source.index("showOnMap(")
    for path in ("js/trip.js", "js/trip_view.js"):
        assert "broken" not in (STATIC / path).read_text(encoding="utf-8")
    assert values["points"][0] == {"lat": 40.99, "lon": 29.025, "label": "Kadıköy", "card": "trip-step-1", "kind": "station"}
    assert values["points"][-1]["label"] == "Levent" and values["points"][-1]["kind"] == "place"
    assert len(values["points"]) <= 20 and all("broken" not in point for point in values["points"])
    assert values["evil"] is None and values["script"] is None and values["range"] is None
    assert values["geo"] == "geo:41.078000,29.010000?q=41.078000,29.010000(Levent)"
    from ibb_mcp.journey_accessible import _maps_links
    assert journey["steps"][0]["map_links"]["apple"] == _maps_links(40.99, 29.025, "Kadıköy")["apple"]


def test_needs_and_profile_never_leave_in_requests_or_links(tmp_path) -> None:
    entry = (STATIC / "js" / "trip.js").read_text(encoding="utf-8")
    view = (STATIC / "js" / "trip_view.js").read_text(encoding="utf-8")
    source = entry + "\n" + view
    calls = re.findall(r"get\([^;]*\)", source)
    assert calls and all("needs" not in call for call in calls)
    assert re.search(r"buildShareUrl\(\s*tripQuestion\([^)]*\)\s*,\s*\[\]\s*\)", entry)
    for forbidden in ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "EventSource",
                      "localStorage.setItem", "sessionStorage", "navigator.geolocation"):
        assert forbidden not in source
    values = node_json(
        tmp_path, {"view": "js/trip_view.js"},
        "const compare={from:'Kadıköy',to:'Levent',options:[]};"
        "const journey={available:false,from:'Kadıköy',to:'Levent',steps:[],extra_minutes:0,uncertainty:[],disclaimer:''};"
        "const question=view.tripQuestion('Kadıköy','Levent');"
        "const parsed=view.parseTripQuery('?'+new URLSearchParams({q:question}));"
        "const other=view.parseTripQuery('?q=merhaba');"
        "console.log(JSON.stringify({share:view.shareText(compare,journey),question,parsed,other}));",
    )
    assert "profil" not in values["share"].lower()
    assert "step_free" not in values["share"] and "stroller" not in values["share"]
    assert values["question"] == "Yolculuk: Kadıköy → Levent"
    assert values["parsed"] == {"from": "Kadıköy", "to": "Levent"}
    assert values["other"] is None


def test_trip_module_wiring_is_parallel_and_node_importable(tmp_path) -> None:
    entry = (STATIC / "js" / "trip.js").read_text(encoding="utf-8")
    view = (STATIC / "js" / "trip_view.js").read_text(encoding="utf-8")
    assert "const [compareRes, journeyRes] = await Promise.allSettled(" in entry
    for path in ("'/api/compare'", "'/api/journey/accessible'", "MOCK ? '/api/journey'", "'/api/alternative'"):
        assert path in entry
    for path in ("import('./api.js')", "import('./map.js')", "import('./share.js')"):
        assert path in entry
    assert "from './trip_view.js'" in entry
    for source in (entry, view):
        assert "from './api.js'" not in source and "from './map.js'" not in source and "from './share.js'" not in source
    for forbidden in ("document", "window", "navigator", "import("):
        assert forbidden not in view
    assert "typeof document !== 'undefined'" in entry
    assert "behavior: 'smooth'" not in entry
    assert entry.count("\n") + 1 <= 300 and view.count("\n") + 1 <= 300
    icons = (STATIC / "icons.svg").read_text(encoding="utf-8")
    used = re.findall(r"icon\('([^']+)'\)", entry + view)
    for name in used:
        assert f'id="i-{name}"' in icons
    values = node_json(
        tmp_path, {"entry": "js/trip.js", "view": "js/trip_view.js"},
        "console.log(JSON.stringify({entry:['EXAMPLE','runTrip','openTrip','mountTrip'].every((name)=>name in entry),"
        "view:['COMPARE_READS','OPTION_READS','JOURNEY_READS','STEP_READS','DETOUR_READS','ALTERNATIVE_READS',"
        "'wantsStepFree','sectionOrder','comparisonRow','stepFreeBlock','avoidedText','coordsFromLinks','mapPoints',"
        "'geoUri','tripQuestion','parseTripQuery','shareText','tripCardHtml'].every((name)=>name in view)}));",
    )
    assert values == {"entry": True, "view": True}


def test_trip_css_is_one_column_at_375px_without_colour_literals() -> None:
    css = (STATIC / "css" / "trip.css").read_text(encoding="utf-8")
    assert "grid-template-columns: minmax(0, 1fr)" in css
    assert "@media (min-width: 40rem)" in css
    assert "white-space: normal" in css
    assert "min-height: var(--tap)" in css
    assert "overflow-wrap: anywhere" in css
    colour = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(")
    assert not colour.search(re.sub(r"/\*.*?\*/", "", css, flags=re.S))
    if re.search(r"\b(?:transition|animation)\b", css):
        assert "@media (prefers-reduced-motion: no-preference)" in css
    assert "\u2014" not in css and "\u2013" not in css
    assert not re.search(r"\bETA\b", css)
    assert css.count("\n") + 1 <= 350
