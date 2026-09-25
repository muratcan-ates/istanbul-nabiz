"""The answers (js/cards/*.js and the scales and ribbons they draw), run in node on what the app
itself answers offline.

The card renderers are pure (scripts/check_web_budget.py keeps them so): a payload goes in, the
answer's HTML, its map points and its sentence come out, so node imports the very files the
browser runs and no DOM is needed. The payloads come from the app through ``TestClient``, never
from hand-written numbers; a test that needs a missing value or a hostile string changes a copy.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import re
import shutil
import subprocess
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from conftest import offline_settings, refuse_network
from fastapi.testclient import TestClient

import ibb_mcp.eta
from ibb_mcp.cache import TTLCache
from ibb_mcp.http import PoliteClient
from ibb_mcp.models import AQI_BANDS
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.web.main import STATIC_DIR, create_app

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed; the answer harness needs it")

JS = STATIC_DIR / "js"
DASHES = ("—", "–")
INJECTION = '<img src=x onerror="alert(1)">'
# The recorded 500T positions are stamped 09:08:48-09:08:59 İstanbul time on 2026-09-08
# (tests/fixtures/iett_hat_500T.json): a clock a minute later lets the ETA engine use them.
FIXTURE_CAPTURED_AT = dt.datetime(2026, 9, 8, 6, 10, tzinfo=dt.UTC)
CALLS = {
    "parking": ("/api/parking", {"place": "Taksim", "radius_km": 1.5, "min_free": 1}),
    "buses": ("/api/buses", {"line": "500T"}),
    "no_arrivals": ("/api/arrivals", {"line": "500T", "stop": "Şifa Sondurak", "limit": 3}),
    "metro": ("/api/metro", {}),
    "metro_m4": ("/api/metro", {"line": "M4"}),
    "station": ("/api/metro/station", {"name": "Kartal"}),
    "air": ("/api/air", {"place": "Beşiktaş"}),
    "forecast": ("/api/air/forecast", {"place": "Beşiktaş", "hours": 6}),
    "traffic_now": ("/api/traffic", {"window": "now"}),
    "traffic_24h": ("/api/traffic", {"window": "24h"}),
    "route": ("/api/route", {"from": "Kadıköy", "to": "Taksim"}),
    "stops": ("/api/stops", {"q": "Kadıköy"}),
    "places": ("/api/places", {"q": "Taksim"}),
    "freshness": ("/api/freshness", {}),
}
#: Every renderer with the payloads it takes, as the journeys in js/journeys.js call them.
RENDERERS = {
    "parking": "P.parkingAnswer(A.parking)",
    "buses": "T.busAnswer(A.buses)",
    "arrivals": "T.arrivalsAnswer(A.arrivals, 'Şifa Sondurak')",
    "no_arrivals": "T.arrivalsAnswer(A.no_arrivals, 'Şifa Sondurak')",
    "metro": "M.metroAnswer(A.metro)",
    "metro_m4": "M.metroAnswer(A.metro_m4, 'M4')",
    "station": "M.stationAnswer(A.station)",
    "air": "E.airAnswer(A.air, A.forecast, null)",
    "air_without_forecast": "E.airAnswer(A.air, null, new Error('zaman aşımı'))",
    "traffic": "E.trafficAnswer(A.traffic_now, A.traffic_24h, CLOCK)",
    "traffic_without_history": "E.trafficAnswer(A.traffic_now, null, CLOCK)",
    "route": "R.routeAnswer(A.route)",
    "stops": "L.stopsAnswer(A.stops)",
    "places": "L.placesAnswer(A.places)",
    "freshness": "L.freshnessAnswer(A.freshness)",
}
MODULES = {
    "P": "cards/parking",
    "T": "cards/transit",
    "M": "cards/metro",
    "E": "cards/environment",
    "R": "cards/route",
    "L": "cards/places",
    "S": "cards/sheet",
    "SC": "charts/scale",
    "RB": "charts/ribbon",
}


@pytest.fixture(scope="module")
def answers() -> Iterator[dict[str, Any]]:
    """The offline app's answers, plus arrivals under a clock just after the recorded positions."""
    nabiz = Nabiz(
        SourceContext.create(
            client=PoliteClient(transport=httpx.MockTransport(refuse_network)), cache=TTLCache(), settings=offline_settings()
        )
    )
    with TestClient(create_app(nabiz=nabiz)) as client:
        got = {}
        for name, (path, params) in CALLS.items():
            response = client.get(path, params=params)
            assert response.status_code == 200, (name, response.text)
            got[name] = response.json()
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(ibb_mcp.eta, "utcnow", lambda: FIXTURE_CAPTURED_AT)
            got["arrivals"] = client.get("/api/arrivals", params={"line": "500T", "stop": "401351", "limit": 3}).json()
    assert got["arrivals"]["data"]["arrivals"], "the frozen clock must give the fixture's buses an estimate"
    yield got


def node(tmp_path, body: str, **inputs: Any) -> Any:
    """Run ``body`` as an ES module with the renderers imported and ``inputs`` as constants."""
    imports = "\n".join(
        f"import * as {alias} from {json.dumps((JS / f'{file}.js').as_uri())};" for alias, file in MODULES.items()
    )
    consts = "\n".join(f"const {key} = {json.dumps(value, ensure_ascii=False)};" for key, value in inputs.items())
    harness = tmp_path / "answers_harness.mjs"
    harness.write_text(f"{imports}\n{consts}\n{body}\n", encoding="utf-8")
    proc = subprocess.run([NODE, str(harness)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


CLOCK = int(dt.datetime(2026, 9, 23, 12, tzinfo=dt.UTC).timestamp() * 1000)
#: Each answer as the page would show it: its HTML and every drawing at 600 x 180.
RENDER_ALL = (
    "const out = {};\n"
    "for (const [name, call] of Object.entries(CALLS)) {\n"
    "  const a = eval(call);\n"
    "  const drawn = Object.values(a.draw || {}).map((draw) => draw(600, 180, CLOCK));\n"
    "  out[name] = { ...a, draw: drawn };\n"
    "}\n"
    "console.log(JSON.stringify(out));"
)


def render_all(tmp_path, payloads: dict[str, Any]) -> dict[str, Any]:
    return node(tmp_path, RENDER_ALL, A=payloads, CALLS=RENDERERS, CLOCK=CLOCK)


@pytest.fixture(scope="module")
def rendered(answers, tmp_path_factory) -> dict[str, Any]:
    return render_all(tmp_path_factory.mktemp("answers"), answers)


def visible(answer: dict[str, Any]) -> str:
    return answer["html"] + "".join(answer["draw"]) + answer["say"]


# --------------------------------------------------------------------------------------
# every answer
# --------------------------------------------------------------------------------------
def test_every_answer_renders_with_a_stamp_a_sentence_and_no_dash(rendered) -> None:
    assert set(rendered) == set(RENDERERS)
    for name, answer in rendered.items():
        text = visible(answer)
        assert not any(d in text for d in DASHES), name
        assert not re.search(r"\b(?:undefined|NaN|null|Infinity)\b", text), name
        assert 'class="stamp' in answer["html"] or "callout-error" in answer["html"], f"{name} has no data age"
        assert answer["say"].endswith("."), name


def test_every_map_point_leads_to_something_on_the_page(rendered) -> None:
    for name, answer in rendered.items():
        ids = set(re.findall(r' id="(kart-\d+)"', answer["html"]))
        for point in answer.get("points", []):
            assert point["card"] in ids, (name, point)
            assert isinstance(point["lat"], float) and isinstance(point["lon"], float), (name, point)
        assert len(ids) == len(re.findall(r' id="kart-\d+"', answer["html"])), f"{name} repeats an id"


def test_every_string_from_the_server_is_escaped(tmp_path, answers) -> None:
    """Every string in every payload becomes an <img onerror> tag; none may reach the page as markup."""

    def poison(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: poison(v) for k, v in value.items()}
        if isinstance(value, list):
            return [poison(v) for v in value]
        return INJECTION if isinstance(value, str) else value

    out = render_all(tmp_path, {name: poison(copy.deepcopy(payload)) for name, payload in answers.items()})
    for name, answer in out.items():
        assert "<img" not in visible(answer).replace(answer["say"], ""), name
        assert "&lt;img src=x" in answer["html"], f"{name} dropped the server's text instead of escaping it"


def test_a_missing_value_reads_bilinmiyor(tmp_path, answers) -> None:
    """Numbers the source left out are the word, never a dash or an empty slot (spec 14.1)."""
    gone = copy.deepcopy(answers)
    for lot in gone["parking"]["data"]["parks"]:
        lot["empty"] = None
    for arrival in gone["arrivals"]["data"]["arrivals"]:
        arrival["eta_minutes"] = None
    gone["air"]["data"]["reading"].update(pm10=None, aqi_index=None)
    gone["station"]["data"]["stations"][0].update(lifts=None, wc=None)
    out = render_all(tmp_path, gone)
    assert "boş yer bilinmiyor" in out["parking"]["html"] and "scale-occ" not in out["parking"]["html"]
    assert "süre bilinmiyor" in out["arrivals"]["html"]
    assert "AQI bilinmiyor" in out["air"]["html"] and "<dd>bilinmiyor</dd>" in out["air"]["html"]
    assert out["station"]["html"].count('<dd class="row-muted">bilinmiyor</dd>') == 2
    for name, answer in out.items():
        assert not re.search(r"\b(?:undefined|NaN|null)\b", visible(answer)), name


# --------------------------------------------------------------------------------------
# per kind
# --------------------------------------------------------------------------------------
def test_parking_draws_occupancy_as_a_share_and_plots_the_searched_place(tmp_path, rendered, answers) -> None:
    html = rendered["parking"]["html"]
    for lot in answers["parking"]["data"]["parks"]:
        share = (lot["capacity"] - lot["empty"]) / lot["capacity"]
        assert f'style="--share:{share:.4f}"' in html
    assert html.count("Neredeyse dolu") == sum(
        1 for lot in answers["parking"]["data"]["parks"] if (lot["capacity"] - lot["empty"]) / lot["capacity"] >= 0.9
    )
    kinds = [p["kind"] for p in rendered["parking"]["points"]]
    assert kinds.count("place") == 1 and kinds.count("park") == len(answers["parking"]["data"]["parks"])
    closed = copy.deepcopy(answers["parking"])
    closed["data"]["parks"][0]["is_open"] = False
    html = node(tmp_path, "console.log(JSON.stringify(P.parkingAnswer(X).html));", X=closed)
    assert "Şu anda kapalı" in html and html.count("scale-occ") == len(closed["data"]["parks"]) - 1


def test_arrivals_say_how_each_estimate_was_made_and_how_old_the_position_is(rendered, answers) -> None:
    html = rendered["arrivals"]["html"]
    arrivals = answers["arrivals"]["data"]["arrivals"]
    assert html.count('class="card row') == len(arrivals)
    assert html.count("Yöntem: ") == len(arrivals) and "Bu tahmin nasıl yapıldı?" in html
    assert html.count(", konum ") == len(arrivals)  # the stamp names the position's own age
    assert answers["arrivals"]["data"]["disclaimer"] in html  # verbatim


def test_no_estimate_shows_the_reasons_and_keeps_unknown_codes_out_of_the_text(tmp_path, rendered, answers) -> None:
    html = rendered["no_arrivals"]["html"]
    assert "Neden varış tahmini yok?" in html and "Boş ekran da, uydurma dakika da yanıt değildir." in html
    assert "31 aracın konumu 600 sn’den eskiydi" in html and "Sayımlar" in html
    odd = copy.deepcopy(answers["no_arrivals"])
    odd["data"]["diagnostics"]["notes"] = ["some_new_code"]
    html = node(tmp_path, "console.log(JSON.stringify(T.arrivalsAnswer(X, 'Şifa Sondurak').html));", X=odd)
    assert '<li data-code="some_new_code">Açıklaması olmayan bir not var.</li>' in html


def test_bus_positions_are_a_table_by_direction_with_the_rest_behind_one_disclosure(rendered, answers) -> None:
    html = rendered["buses"]["html"]
    buses = answers["buses"]["data"]["buses"]
    assert "(KVKK)" in html and "#i-shield-lock" in html
    assert html.count('<tr class="card"') == len(buses) and f"Tümünü göster ({len(buses)})" in html
    first = html.split("<details>")[0]
    assert first.count('<tr class="card"') == 12
    assert set(re.findall(r'<th scope="rowgroup" colspan="4">([^<(]+) \(', html)) == {"4.Levent Metro yönü", "Şifa Sondurak yönü"}
    assert len(rendered["buses"]["points"]) == len(buses)


def test_metro_badges_take_the_operators_line_colour_and_always_the_code(tmp_path, rendered) -> None:
    assert 'style="--line:var(--line-M7);--line-ink:var(--line-M7-ink)">M7</span>' in rendered["metro"]["html"]
    assert "M4 hattında bildirilmiş aksaklık yok." in rendered["metro_m4"]["html"]
    badges = node(tmp_path, "console.log(JSON.stringify([M.badge('M11'), M.badge('X9'), M.badge('')]));")
    assert "var(--line-M11)" in badges[0] and badges[1] == '<span class="badge">X9</span>' and badges[2] == ""


def test_station_facilities_are_words_and_no_is_muted_not_red(rendered) -> None:
    html = rendered["station"]["html"]
    assert re.search(r"Asansör</dt><dd>5</dd>", html) and re.search(r"Bebek odası</dt><dd class=\"row-muted\">yok</dd>", html)
    assert "Hat sırası 16" in html and "row-warn" not in html


@pytest.mark.parametrize("aqi", [0, 49, 50, 150, 499, 500])
def test_the_aqi_tick_sits_inside_the_band_the_server_names(tmp_path, aqi) -> None:
    x = node(tmp_path, "console.log(JSON.stringify(SC.aqiPosition(V)));", V=aqi)
    band = next(i for i, (upper, _, _) in enumerate(AQI_BANDS) if aqi <= upper)
    assert band / 6 <= x <= (band + 1) / 6


def test_air_reads_the_band_and_draws_the_forecast_from_its_measured_input(rendered, answers) -> None:
    html = rendered["air"]["html"]
    assert 'aria-label="AQI 25, İyi bandı, 0 ile 500 arası ölçekte"' in html and "badge-aqi" in html
    assert "hesaplama <b>az önce</b>, girdi ölçümü 15 gün önce" in html
    (svg,) = rendered["air"]["draw"]
    assert 'class="pulse-dot is-old"' in svg  # a 15-day-old input is never the accent
    assert svg.count('class="pulse-best"') == 1 and "pulse-forecast" in svg
    assert "Tahmin alınamadı: zaman aşımı" in rendered["air_without_forecast"]["html"]
    assert rendered["air_without_forecast"]["draw"] == []


def test_the_forecast_draws_nothing_at_width_zero(tmp_path, answers) -> None:
    body = "console.log(JSON.stringify(SC.forecastSvg(F.data, { width: 0, height: 120, uid: 'np-x' })));"
    out = node(tmp_path, body, F=answers["forecast"])
    assert out == ""


def test_traffic_uses_the_pen_line_at_card_size(rendered) -> None:
    traffic = rendered["traffic"]
    (svg,) = traffic["draw"]
    assert "pulse-card is-archive" in traffic["html"] and "Saatlik değerler" in traffic["html"]
    assert 'aria-labelledby="np-kart-' in svg and "pulse-line" in svg
    assert "1 akıcı, 99 kilitli" in traffic["html"]
    assert "Çizgi için yeterli ölçüm yok." in rendered["traffic_without_history"]["html"]


RIBBON_ENDS = 'const s = RB.ribbon(LEGS, MAX);\nconsole.log(JSON.stringify([...s.matchAll(/x2="([\\d.]+)"/g)].map((m) => +m[1])));'


def test_route_ribbons_share_one_minute_axis_and_keep_the_unavailable_options(tmp_path, rendered, answers) -> None:
    html = rendered["route"]["html"]
    data = answers["route"]["data"]
    longest = max(o["total_minutes"] for o in data["options"] if o["available"])
    for option in (o for o in data["options"] if o["available"]):
        ends = node(tmp_path, RIBBON_ENDS, LEGS=option["legs"], MAX=longest)
        assert ends[-1] == pytest.approx(1000 * option["total_minutes"] / longest, abs=0.2)
    for unavailable in data["unavailable_options"]:
        assert f'<p class="row-muted">{unavailable["reason"].replace(chr(39), "&#39;")}</p>' in html
    assert "ribbon-transit" in html and "ribbon-drive" in html and "ribbon-foot" in html
    assert "hesaplama <b>az önce</b>, en eski girdi 15 gün önce" in html
    assert data["disclaimer"] in html


def test_stops_translate_the_direction_and_keep_raw_codes_in_a_disclosure(rendered, answers) -> None:
    html = rendered["stops"]["html"]
    assert "yön: Hacıköy" in html and "direction:" not in html
    visible_part, codes = html.split("<summary>", 1)[0], html.split("Kodlar", 1)[1]
    assert answers["stops"]["data"]["stops"][0]["stop_id"] not in visible_part
    assert answers["stops"]["data"]["stops"][0]["stop_id"] in codes


def test_the_freshness_answer_is_a_table_with_the_budget_sentence(rendered, answers) -> None:
    html = rendered["freshness"]["html"]
    sources = answers["freshness"]["data"]["sources"]
    assert html.count("<tr><td>") == len(sources)
    assert "İETT’nin saatlik 100 sınırının altında, 80’de duruyoruz." in html


def test_an_error_says_how_old_the_last_known_data_is_and_offers_a_retry(tmp_path, answers) -> None:
    body = (
        "const cards = [503, 400].map((status) => S.errorCard("
        "{ status, message: 'İBB servisi şu anda yanıt vermiyor: zaman aşımı' }, status === 503 ? X : null));\n"
        "console.log(JSON.stringify(cards));"
    )
    unavailable, refused = node(tmp_path, body, X=answers["freshness"]["data"]["sources"])
    assert "<p>zaman aşımı</p>" in unavailable  # the heading is not said twice
    assert "Bu bir Nabız hatası değil" in unavailable and "En son ne zaman veri alabildik" in unavailable
    assert "data-retry" in unavailable and "#i-cloud-off" in unavailable
    assert "data-retry" not in refused  # the same question would be refused again
