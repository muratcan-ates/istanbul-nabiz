"""The page's drawings: the pen line (js/charts/pulse-*.js) and the "Veri tazeliği" ruler
(js/charts/age-ruler.js), run in node on answers the app itself gives offline.

The chart modules are pure (scripts/check_web_budget.py keeps them so): the clock, the width and
the payload are arguments, so node imports the very files the browser runs and no DOM is needed.
The inputs come from the app through ``TestClient``, never from hand-written numbers; where a test
needs another data age it changes the timing (the clock and ``age_seconds``), never a reading.
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

from ibb_mcp.cache import TTLCache
from ibb_mcp.http import PoliteClient
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.web.main import STATIC_DIR, create_app

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed; the chart harness needs it")

CHARTS = STATIC_DIR / "js" / "charts"
HOUR_MS = 3_600_000
DASHES = ("—", "–")
INJECTION = '<img src=x onerror="alert(1)">'
# The sentence DESIGN.md section 7 gives for the recorded offline payload (state archive).
ARCHIVE_SENTENCE = (
    "Son ölçüm 8 Eylül 09:00; çizgi o güne ait, canlı değil. O güne kadarki 24 saatte trafik indeksi en düşük 1 "
    "(01:00), en yüksek 74 (18:00). Son ölçüm 60, yoğun. Önceki gün aynı saatte 50."
)


@pytest.fixture(scope="module")
def answers() -> Iterator[dict[str, Any]]:
    """/api/traffic?window=24h and /api/freshness, as the offline app answers them."""
    nabiz = Nabiz(
        SourceContext.create(
            client=PoliteClient(transport=httpx.MockTransport(refuse_network)),
            cache=TTLCache(),
            settings=offline_settings(),
        )
    )
    with TestClient(create_app(nabiz=nabiz)) as client:
        traffic = client.get("/api/traffic", params={"window": "24h"})
        client.get("/api/parking", params={"place": "Taksim", "radius_km": 1.5, "min_free": 1})
        freshness = client.get("/api/freshness")
    assert traffic.status_code == 200 and freshness.status_code == 200
    yield {"traffic": traffic.json(), "freshness": freshness.json()}


def node(tmp_path, body: str, **inputs: Any) -> Any:
    """Run ``body`` as an ES module with the chart modules imported and ``inputs`` as constants."""
    imports = "\n".join(
        f"import * as {name} from {json.dumps((CHARTS / f'{file}.js').as_uri())};"
        for name, file in (("geo", "pulse-geometry"), ("view", "pulse-view"), ("ruler", "age-ruler"))
    )
    consts = "\n".join(f"const {key} = {json.dumps(value, ensure_ascii=False)};" for key, value in inputs.items())
    harness = tmp_path / "charts_harness.mjs"
    harness.write_text(f"{imports}\n{consts}\n{body}\n", encoding="utf-8")
    proc = subprocess.run([NODE, str(harness)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def last_reading_ms(traffic: dict[str, Any]) -> int:
    """The newest reading's time, the anchor of a simulated clock."""
    return int(dt.datetime.fromisoformat(traffic["data"]["now"]["at_utc"]).timestamp() * 1000)


def with_age(traffic: dict[str, Any], seconds: float | None) -> dict[str, Any]:
    """The same readings, read ``seconds`` after the last one (None: an age nobody knows)."""
    changed = copy.deepcopy(traffic)
    if seconds is None:
        changed["provenance"].pop("age_seconds")
        changed["provenance"].pop("age")
    else:
        changed["provenance"]["age_seconds"] = seconds
        changed["provenance"]["age"] = f"{int(seconds // 60)} dk önce"
    return changed


VIEW = "view.pulseView(res, { width: W, height: H, uid: UID, clock: CLOCK, failed: false })"


def render(tmp_path, res: dict[str, Any] | None, clock: float, width: int = 900, height: int = 180, uid: str = "np-a") -> Any:
    box = "{ left: 1, top: 18, width: W - 105, height: H - 42 }"  # the plot box pulse-view uses from 640 px
    body = f"const v = {VIEW};\nconst m = geo.pulse(res && res.data, res && res.provenance, {box}, CLOCK);\n"
    body += "console.log(JSON.stringify({ v, m }));"
    return node(tmp_path, body, res=res, W=width, H=height, UID=uid, CLOCK=clock)


# --------------------------------------------------------------------------------------
# the pen line
# --------------------------------------------------------------------------------------
def test_the_recorded_day_draws_the_same_line_every_time(tmp_path, answers) -> None:
    traffic = answers["traffic"]
    clock = last_reading_ms(traffic) + 15 * 86_400_000
    out = node(
        tmp_path,
        f"const a = {VIEW};\nconst b = {VIEW};\nconsole.log(JSON.stringify([a, b]));",
        res=traffic,
        W=900,
        H=180,
        UID="np-a",
        CLOCK=clock,
    )
    assert out[0] == out[1]
    view = out[0]
    assert view["state"] == "archive"  # the fixture is days old: grey, dated, never breathing
    assert f'<desc id="np-a-d">{ARCHIVE_SENTENCE}</desc>' in view["svg"]
    assert '<title id="np-a-t">Trafik indeksi, 24 saatlik kayıt</title>' in view["svg"]
    assert "pulse-ring" not in view["svg"] and "is-old" in view["svg"]
    assert "Son ölçüm 8 Eylül 09:00. Çizgi o güne ait, canlı değil." in view["readout"]
    assert "Önceki gün bu saatte 50. 10 puan daha yoğun." in view["readout"]
    assert "ölçüm <b>" in view["readout"] and "#i-history" in view["readout"]  # a days-old İBB reading
    assert view["table"].count("<tr>") == 1 + 25  # header row and 24 hours plus now
    assert "7 Eylül 09:00" in view["table"] and "8 Eylül 00:00" in view["table"]


def test_the_svg_stays_small_and_every_number_in_it_is_real(tmp_path, answers) -> None:
    out = render(tmp_path, answers["traffic"], last_reading_ms(answers["traffic"]) + 86_400_000)
    svg = out["v"]["svg"]
    assert len(re.findall(r"<[a-zA-Z]", svg)) <= 150
    assert "NaN" not in svg and "undefined" not in svg and "Infinity" not in svg
    numbers = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", out["m"]["path"])]
    xs = numbers[0::2]
    assert xs and min(xs) >= 0 and max(xs) <= 900
    assert "#" not in re.sub(r'url\(#np-a-ink\)|href="#[\w-]+"', "", svg), "colour comes from classes, never a literal"


def test_two_figures_on_one_page_never_share_an_id(tmp_path, answers) -> None:
    clock = last_reading_ms(answers["traffic"]) + 86_400_000
    body = 'const ids = (s) => [...s.matchAll(/ id="([^"]+)"/g)].map((m) => m[1]);\n'
    body += "const a = view.pulseView(res, { width: 900, height: 180, uid: 'np-hero', clock: CLOCK });\n"
    body += "const b = view.pulseView(res, { width: 600, height: 180, uid: 'np-kart-3', clock: CLOCK });\n"
    body += "console.log(JSON.stringify([ids(a.svg), ids(b.svg)]));"
    first, second = node(tmp_path, body, res=answers["traffic"], CLOCK=clock)
    assert len(first) == 3 and not set(first) & set(second)  # title, desc, gradient


@pytest.mark.parametrize(
    ("age", "state"),
    [(0, "live"), (2400, "live"), (7199, "live"), (7200, "delayed"), (43_200, "delayed"), (86_400, "archive"), (None, "archive")],
)
def test_the_state_follows_the_data_age(tmp_path, answers, age, state) -> None:
    res = with_age(answers["traffic"], age)
    clock = last_reading_ms(res) + (age or 0) * 1000
    out = render(tmp_path, res, clock)
    view, model = out["v"], out["m"]
    assert view["state"] == state == model["state"]
    description = model["description"]
    if state == "live":
        assert description.startswith("Son 24 saatte trafik indeksi")
        assert "pulse-ring" in view["svg"] and "is-old" not in view["svg"]
        assert model["title"] == "Trafik indeksi, son 24 saat"
    else:
        assert "Son 24 saatte" not in description and "pulse-ring" not in view["svg"]
        assert model["title"] == "Trafik indeksi, 24 saatlik kayıt"
    if state == "delayed":
        assert description.endswith(f"Veri {int(age // 60)} dk önce ölçüldü.")
    if state == "archive":
        assert description.startswith("Son ölçüm 8 Eylül 09:00;")


def test_a_live_line_ends_at_the_clock_so_the_gap_is_the_data_age(tmp_path, answers) -> None:
    res = with_age(answers["traffic"], 2400)
    out = render(tmp_path, res, last_reading_ms(res) + 2_400_000)
    gap, width = out["m"]["gap"], 900 - 105
    assert gap["x2"] - gap["x1"] == pytest.approx(width * 40 / (24 * 60), abs=0.01)  # 40 minutes of 24 hours


def test_a_reading_almost_a_day_old_leaves_the_window_nearly_empty(tmp_path, answers) -> None:
    """A delayed window still ends at the clock: 23 h 59 min of gap leaves one reading in it."""
    res = with_age(answers["traffic"], 86_399)
    out = render(tmp_path, res, last_reading_ms(res) + 86_399_000)
    assert out["v"]["state"] == "insufficient"
    assert out["m"]["description"] == "Çizgi için yeterli ölçüm yok. Veri 1439 dk önce ölçüldü."


def test_fewer_than_two_readings_draw_guides_and_say_so(tmp_path, answers) -> None:
    res = copy.deepcopy(answers["traffic"])
    res["data"]["history"] = []
    out = render(tmp_path, res, last_reading_ms(res) + 86_400_000)
    assert out["v"]["state"] == "insufficient" and "pulse-line" not in out["v"]["svg"]
    assert out["v"]["svg"].count("pulse-guide") == 4
    assert "Çizgi için yeterli ölçüm yok." in out["v"]["readout"]
    assert out["m"]["description"].startswith("Çizgi için yeterli ölçüm yok. Veri ")


def test_loading_and_failure_draw_the_frame_and_offer_a_retry(tmp_path) -> None:
    body = "const opts = { width: 900, height: 180, uid: 'np-a', clock: 1758600000000 };\n"
    body += "console.log(JSON.stringify([view.pulseView(null, opts), view.pulseView(null, { ...opts, failed: true })]));"
    loading, failed = node(tmp_path, body)
    assert loading["state"] == "loading" and failed["state"] == "error"
    assert loading["svg"].count("pulse-guide") == 4 and "pulse-line" not in loading["svg"]
    assert "Tekrar dene" not in loading["readout"]
    assert "Trafik verisi şu an alınamadı." in failed["readout"] and "data-retry" in failed["readout"]


def test_nothing_is_drawn_at_width_zero(tmp_path, answers) -> None:
    """The design sketch drew the whole line at x near 0 after measuring a plot before layout."""
    out = render(tmp_path, answers["traffic"], last_reading_ms(answers["traffic"]), width=0)
    assert out["v"]["svg"] == ""
    assert "Trafik indeksi, tüm şehir" in out["v"]["readout"]


def cubic_overshoot(path: str) -> float:
    """How far any drawn point leaves the band between a segment's two readings, in px."""
    worst = 0.0
    for sub in re.findall(r"M[^M]+", path):
        numbers = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", sub)]
        y0 = numbers[1]
        for i in range(2, len(numbers) - 5, 6):
            _, c1, _, c2, _, y1 = numbers[i : i + 6]
            lo, hi = min(y0, y1), max(y0, y1)
            for k in range(41):
                t = k / 40
                y = (1 - t) ** 3 * y0 + 3 * (1 - t) ** 2 * t * c1 + 3 * (1 - t) * t * t * c2 + t**3 * y1
                worst = max(worst, lo - y, y - hi)
            y0 = y1
    return worst


def test_the_curve_never_overshoots_a_reading(tmp_path, answers) -> None:
    out = render(tmp_path, answers["traffic"], last_reading_ms(answers["traffic"]) + 86_400_000)
    assert out["m"]["subpaths"] == 1
    assert cubic_overshoot(out["m"]["path"]) <= 0.001


def test_a_missing_hour_is_a_break_in_the_line_never_a_bridge(tmp_path, answers) -> None:
    res = copy.deepcopy(answers["traffic"])
    del res["data"]["history"][10:13]  # a three-hour hole in the recorded day
    out = render(tmp_path, res, last_reading_ms(res) + 86_400_000)
    assert out["m"]["subpaths"] == 2 and out["m"]["path"].count("M") == 2
    assert cubic_overshoot(out["m"]["path"]) <= 0.001


def test_the_readout_escapes_what_the_server_sends(tmp_path, answers) -> None:
    res = with_age(answers["traffic"], 7200)  # delayed: the age is in the <desc> and in the stamp
    res["provenance"]["age"] = INJECTION
    out = render(tmp_path, res, last_reading_ms(res) + 7_200_000)
    for part in (out["v"]["svg"], out["v"]["readout"]):
        assert "<img" not in part and "&lt;img" in part


# --------------------------------------------------------------------------------------
# the age ruler
# --------------------------------------------------------------------------------------
def test_the_ruler_ticks_sit_where_the_log_axis_puts_them(tmp_path) -> None:
    out = node(tmp_path, "console.log(JSON.stringify(ruler.TICKS.map(([s]) => ruler.ageFraction(s))));")
    assert [round(f, 3) for f in out] == [0, 0.136, 0.311, 0.447, 0.689, 0.837, 0.947, 1]


def marks(tmp_path, sources: dict[str, Any], width: int = 1200, wide: bool = True) -> str:
    return node(tmp_path, "console.log(JSON.stringify(ruler.rulerMarks(S, W, WIDE)));", S=sources, W=width, WIDE=wide)


def test_the_recorded_sources_are_plotted_by_their_data_age(tmp_path, answers) -> None:
    sources = answers["freshness"]["data"]["sources"]
    assert {"traffic", "ispark"} <= set(sources)
    width = 1200
    html = marks(tmp_path, sources, width)
    placed = [float(x) for x in re.findall(r"--x:([\d.]+)", html)]
    ages = {name: s["data_age_seconds"] for name, s in sources.items() if s.get("data_age_seconds") is not None}
    fractions = node(
        tmp_path,
        "console.log(JSON.stringify(Object.fromEntries(Object.entries(A).map(([k, s]) => [k, ruler.ageFraction(s)]))));",
        A=ages,
    )
    for name, fraction in fractions.items():
        # Plotted by the data's own age, the one the answers' stamps show, never the fetch's: each
        # source sits on its mark, or within the 14 px that merged it into one.
        assert min(abs((1 - fraction) - x) * width for x in placed) < 14, name
    table = node(tmp_path, "console.log(JSON.stringify(ruler.rulerTable(S)));", S=sources)
    assert table.count("<tr>") == 1 + len(sources)


def test_marks_closer_than_14_px_merge_into_one(tmp_path) -> None:
    near = {
        "iett_line": {"data_age_seconds": 30, "age_seconds": 30, "healthy": True, "errors": 0},
        "iett_fleet": {"data_age_seconds": 32, "age_seconds": 32, "healthy": True, "errors": 0},
        "traffic": {"data_age_seconds": 86_400 * 14, "age_seconds": 60, "healthy": True, "errors": 0},
    }
    html = marks(tmp_path, near)
    assert html.count("<li") == 2
    assert "İETT (2): 30 sn önce" in html and "is-now" in html
    assert "İETT hat konumları: 30 sn önce" in html and "İETT filo: 32 sn önce" in html  # both stay readable
    assert marks(tmp_path, near, width=100_000).count("<li") == 3  # far apart on a wide enough axis
    assert marks(tmp_path, near, width=358, wide=False).count("<li") == 3  # a phone lists every source


def test_an_unhealthy_source_is_dashed_and_one_never_read_says_so(tmp_path) -> None:
    sources = {
        "metro_status": {"data_age_seconds": 600, "age_seconds": 600, "healthy": False, "errors": 2},
        "aq_readings": {"data_age_seconds": None, "age_seconds": None, "healthy": False, "errors": 3},
        "gtfs": {"data_age_seconds": None, "age_seconds": None, "healthy": False, "errors": 0},
    }
    html = marks(tmp_path, sources)
    assert html.count("<li") == 2  # a source with no read and no error is not drawn
    assert html.count("is-unhealthy") == 2 and "#i-alert-triangle" in html
    assert "Hava kalitesi ölçümleri: hiç alınamadı" in html and "--x:0.0000" in html and "is-start" in html
    assert "is-now" not in html  # ten-minute-old data from a failing source is not "current"
    assert marks(tmp_path, {}) == ""


def test_the_ruler_escapes_source_names_and_errors(tmp_path) -> None:
    sources = {INJECTION: {"data_age_seconds": 60, "age_seconds": 60, "healthy": False, "errors": 1, "last_error": INJECTION}}
    html = marks(tmp_path, sources) + node(tmp_path, "console.log(JSON.stringify(ruler.rulerTable(S)));", S=sources)
    assert "<img" not in html and "&lt;img" in html


def test_no_drawing_prints_an_em_or_en_dash(tmp_path, answers) -> None:
    traffic = answers["traffic"]
    out = render(tmp_path, traffic, last_reading_ms(traffic) + 86_400_000)
    ruler_html = marks(tmp_path, answers["freshness"]["data"]["sources"])
    axis = node(tmp_path, "console.log(JSON.stringify([ruler.axisSvg(true), ruler.axisSvg(false)]));")
    for text in (out["v"]["svg"], out["v"]["readout"], out["v"]["table"], ruler_html, *axis):
        assert not any(d in text for d in DASHES), text[:200]
