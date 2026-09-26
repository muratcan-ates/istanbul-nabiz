"""Offline contract tests for the standalone QR stop card."""

from __future__ import annotations

import ast
import asyncio
import re
import time
from collections.abc import Iterator, Sequence
from typing import Any

import httpx
import pytest
from conftest import FIXTURES_DIR, offline_settings, refuse_network
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ibb_mcp.cache import TTLCache
from ibb_mcp.config import ATTRIBUTION, Settings
from ibb_mcp.http import PoliteClient
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.console import stop_card
from nabiz.console.brief import Freshness
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.ports import Ports, UnwiredStepFree
from nabiz.console.stop_card import stop_card_router

CONTRACT_KEYS = {
    "code",
    "name",
    "direction",
    "lat",
    "lon",
    "lines_known",
    "lines",
    "metro",
    "offline",
    "url",
    "links",
    "stop_provenance",
}
METRO_KEYS = {
    "station",
    "lines",
    "distance_m",
    "lift_status",
    "lift_line",
    "alternative",
    "ask_href",
    "operator_approved",
    "stale",
    "provenance",
}
FRESH = Freshness(offline=True, card_stale_after_s=600, arrival_stale_after_s=180)


@pytest.fixture(scope="module")
def nabiz() -> Iterator[Nabiz]:
    yield Nabiz(
        SourceContext.create(
            client=PoliteClient(transport=httpx.MockTransport(refuse_network)),
            cache=TTLCache(),
            settings=offline_settings(),
        )
    )


def card_client(nabiz: Nabiz, *, step_free: Any = None) -> TestClient:
    app = FastAPI()
    app.state.nabiz = nabiz
    app.state.fresh = FRESH
    app.state.ports = Ports(step_free=step_free or UnwiredStepFree())
    app.include_router(stop_card_router)
    return TestClient(app)


class FakeStepFree:
    def __init__(
        self,
        lift_status: str,
        *,
        fail: bool = False,
        age_s: int = 120,
        mode: str = "live",
        alternative: bool = True,
        extra_minutes: int | None = 4,
    ) -> None:
        self.lift_status = lift_status
        self.fail = fail
        self.age_s = age_s
        self.mode = mode
        self.has_alternative = alternative
        self.extra_minutes = extra_minutes
        self.asked: list[tuple[str, Sequence[str]]] = []

    async def alternative(self, station: str, needs: Sequence[str]) -> dict[str, Any]:
        self.asked.append((station, needs))
        if self.fail:
            raise RuntimeError("port unavailable")
        alt = {"station": "Gayrettepe", "line": "M2", "extra_minutes": self.extra_minutes, "reason": "İBB kaydında alternatif."}
        return {
            "station": station,
            "lift_status": self.lift_status,
            "alternative": alt if self.has_alternative else None,
            "operator_approved": False,
            "provenance": {
                "source": "metro_equipment",
                "url": None,
                "observed_at": "2026-09-26T00:00:00+00:00",
                "age_s": self.age_s,
                "mode": self.mode,
            },
            "stale": False,
        }


def test_known_stop_page_is_html_without_script(nabiz: Nabiz) -> None:
    with card_client(nabiz) as client:
        response = client.get("/d/401351")
    body = response.text
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'lang="tr"' in body and body.count("<h1") == 1
    assert "ŞİFA SONDURAK" in body and "500T" in body and "tarifeye göre" in body
    assert "Resmî İBB hizmeti değildir" in body
    assert "<script" not in body and 'style="' not in body
    assert len(response.content) <= 16_384


@pytest.mark.parametrize("code", ["999999", "abc", "1234567890"])
def test_unknown_code_is_404_in_plain_turkish(nabiz: Nabiz, code: str) -> None:
    with card_client(nabiz) as client:
        page = client.get(f"/d/{code}")
        api = client.get(f"/api/stop-card/{code}")
    assert page.status_code == 404 and "Durak bulunamadı" in page.text and "<form" in page.text
    assert api.status_code == 404
    assert api.json() == {"error": "not_found", "message": "Durak bulunamadı."}


def test_missing_gtfs_says_stop_not_found(tmp_path: Any) -> None:
    settings = Settings(offline=True, fixtures_dir=FIXTURES_DIR, gtfs_dir=tmp_path / "yok")
    missing = Nabiz(
        SourceContext.create(
            client=PoliteClient(transport=httpx.MockTransport(refuse_network)), cache=TTLCache(), settings=settings
        )
    )
    with card_client(missing) as client:
        page = client.get("/d/401351")
        api = client.get("/api/stop-card/401351")
    assert page.status_code == 404 and stop_card.NO_GTFS in page.text
    assert api.json()["message"] == stop_card.NO_GTFS


def test_no_eta_no_dash_on_every_surface(nabiz: Nabiz) -> None:
    paths = ("/d/401351", "/d/406031", "/d/113326", "/d/401351/yazdir", "/d", "/d/999999", "/api/stop-card/401351")
    with card_client(nabiz) as client:
        bodies = [client.get(path).text for path in paths]
    for body in bodies:
        assert not re.search(r"\bETA\b", body)
        without_attribution = body.replace(ATTRIBUTION, "")
        assert "—" not in without_attribution and "–" not in without_attribution


def test_single_minute_rule_holds(nabiz: Nabiz) -> None:
    with card_client(nabiz) as client:
        body = client.get("/api/stop-card/406031").json()
    for item in body["lines"]:
        assert item["display"] in {"tarifeye göre", "doğrulanamadı", None} or re.fullmatch(r"\d+ dk", item["display"])
        assert item["minutes"] is None or isinstance(item["minutes"], int)


def test_json_contract_keys(nabiz: Nabiz) -> None:
    with card_client(nabiz) as client:
        body = client.get("/api/stop-card/113326").json()
    assert set(body) == CONTRACT_KEYS
    assert all(set(line) == {"line", "minutes", "display", "provenance"} for line in body["lines"])
    assert body["metro"] is None or set(body["metro"]) == METRO_KEYS
    assert body["links"] == {"page": "/d/113326", "print": "/d/113326/yazdir", "qr": "/d/113326/qr.svg"}


def test_lines_come_from_the_stop_index(nabiz: Nabiz) -> None:
    with card_client(nabiz) as client:
        kadikoy = client.get("/api/stop-card/406031").json()
        sifa = client.get("/api/stop-card/116301").json()
        empty = client.get("/api/stop-card/205561").json()
        page = client.get("/d/205561")
    assert [row["line"] for row in kadikoy["lines"]] == ["8A", "14ŞB"]
    assert [row["line"] for row in sifa["lines"]] == ["25S1", "153"]
    assert empty["lines"] == [] and "Bu durak için hat kaydı bulunamadı." in page.text


def test_hat_query_reorders_and_unknown_hat_is_ignored(nabiz: Nabiz) -> None:
    with card_client(nabiz) as client:
        reordered = client.get("/api/stop-card/406031?hat=14ŞB").json()
        ignored = client.get("/api/stop-card/406031?hat=500T").json()
    assert reordered["lines"][0]["line"] == "14ŞB"
    assert [row["line"] for row in ignored["lines"]] == ["8A", "14ŞB"]


def test_more_lines_than_the_cap_get_a_show_link(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stop_card, "MAX_ARRIVAL_LINES", 1)
    with card_client(nabiz) as client:
        body = client.get("/api/stop-card/406031").json()
        page = client.get("/d/406031")
    assert body["lines"][1]["display"] is None
    assert 'href="/d/406031?hat=14%C5%9EB"' in page.text


def test_metro_nearby_shows_lift_record_with_age(nabiz: Nabiz) -> None:
    step_free = FakeStepFree("working")
    with card_client(nabiz, step_free=step_free) as client:
        response = client.get("/d/113326")
    assert "Yakındaki raylı istasyon: 4.Levent (M2)" in response.text
    assert "Duraktan 195 m." in response.text
    assert "İBB kaydında arıza yok · 2 dk önce" in response.text
    assert step_free.asked == [("4.Levent", ["step_free"])]


def test_lift_fault_offers_step_free_alternative(nabiz: Nabiz) -> None:
    with card_client(nabiz, step_free=FakeStepFree("out_of_service")) as client:
        response = client.get("/d/113326")
        unknown_time = client.get("/api/stop-card/113326", headers={"host": "testserver"}).json()
    assert "Asansör arızalı (İBB kaydı)" in response.text
    assert "Adımsız alternatif: Gayrettepe (M2)" in response.text
    assert "istasyonlar arası tahminen 4 dk (dönüş dahil değil)" in response.text
    assert "needs=step_free" in response.text and "Operatör onayı yok" in response.text
    assert unknown_time["metro"]["lift_status"] == "out_of_service"
    no_time = FakeStepFree("out_of_service", extra_minutes=None)
    no_alt = FakeStepFree("out_of_service", alternative=False)
    with card_client(nabiz, step_free=no_time) as client:
        assert "süre bilinmiyor" in client.get("/d/113326").text
    with card_client(nabiz, step_free=no_alt) as client:
        assert "tel:153" in client.get("/d/113326").text


def test_lift_unknown_and_port_failure_are_unverified(nabiz: Nabiz) -> None:
    with card_client(nabiz) as client:
        unwired = client.get("/d/113326")
    with card_client(nabiz, step_free=FakeStepFree("working", fail=True)) as client:
        failed = client.get("/d/113326")
    assert "Asansör durumu doğrulanamadı" in unwired.text
    assert failed.status_code == 200 and "Asansör durumu doğrulanamadı" in failed.text


def test_lift_text_never_says_working(nabiz: Nabiz) -> None:
    with card_client(nabiz, step_free=FakeStepFree("working")) as client:
        bodies = [client.get(path).text for path in ("/d/113326", "/d/406031", "/d/401351")]
    assert all(not re.search(r"asansör[^.\n]{0,40}\bçalışıyor\b", body, re.I) for body in bodies)


def test_stop_far_from_metro_has_no_lift_block(nabiz: Nabiz) -> None:
    with card_client(nabiz) as client:
        page = client.get("/d/401351")
        body = client.get("/api/stop-card/401351").json()
    assert "Yakındaki raylı istasyon" not in page.text and body["metro"] is None


def test_age_text_thresholds() -> None:
    age = stop_card.age_text
    assert age(None) == "yaşı bilinmiyor"
    assert age({"mode": "recorded", "age_s": 5}) == "kayıtlı veri"
    assert age({"mode": "live", "age_s": 45}) == "45 sn önce"
    assert age({"mode": "live", "age_s": 120}) == "2 dk önce"
    assert age({"mode": "live", "age_s": 7200}) == "2 sa önce"
    assert age({"mode": "live", "age_s": 259200}) == "3 gün önce"


def test_code_form_redirects_and_validates(nabiz: Nabiz) -> None:
    with card_client(nabiz) as client:
        redirect = client.get("/d?kod=401351", follow_redirects=False)
        invalid = client.get("/d?kod=12a")
        form = client.get("/d")
    assert redirect.status_code == 303 and redirect.headers["location"] == "/d/401351"
    assert invalid.status_code == 200 and "1 ile 9 arası rakam" in invalid.text
    assert form.status_code == 200 and "<form" in form.text


def test_qr_without_segno_is_text_fallback_not_503(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stop_card, "load_segno", lambda: None)
    with card_client(nabiz) as client:
        qr = client.get("/d/401351/qr.svg")
        missing = client.get("/d/999999/qr.svg")
        printed = client.get("/d/401351/yazdir")
    assert qr.status_code == 200 and qr.headers["content-type"].startswith("text/plain")
    assert "QR üretici kurulu değil" in qr.text and "http://testserver/d/401351" in qr.text
    assert qr.headers["X-Nabiz-QR"] == "unavailable"
    assert missing.status_code == 404 and printed.status_code == 200
    assert "QR üretici kurulu değil" in printed.text


def test_qr_with_segno_is_svg(nabiz: Nabiz) -> None:
    pytest.importorskip("segno")
    with card_client(nabiz) as client:
        response = client.get("/d/401351/qr.svg")
    assert response.status_code == 200 and response.headers["content-type"].startswith("image/svg+xml")
    assert response.text.startswith("<svg") and "<script" not in response.text


def test_public_base_url_goes_into_the_qr(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NABIZ_PUBLIC_BASE_URL", "https://nabiz.example.org/")
    with card_client(nabiz) as client:
        public = client.get("/d/401351/yazdir")
    monkeypatch.setenv("NABIZ_PUBLIC_BASE_URL", "http://nabiz.example.org/")
    with card_client(nabiz) as client:
        ignored = client.get("/d/401351/yazdir")
    assert "https://nabiz.example.org/d/401351" in public.text
    assert "http://testserver/d/401351" in ignored.text


def test_print_card_has_no_arrival_minutes(nabiz: Nabiz) -> None:
    with card_client(nabiz) as client:
        response = client.get("/d/401351/yazdir")
    assert "Durak kodu 401351" in response.text and "Hatlar: 500T" in response.text
    assert "Resmî İBB hizmeti değildir" in response.text
    assert not re.search(r"\b\d+ dk\b|tarifeye göre|doğrulanamadı", response.text)


def test_offline_band_is_shown(nabiz: Nabiz) -> None:
    with card_client(nabiz) as client:
        page = client.get("/d/401351")
    assert "Kayıtlı veri: bu sunucu çevrimdışı çalışıyor" in page.text


def test_stop_card_css_is_print_ready_and_token_only() -> None:
    css_path = FIXTURES_DIR.parent.parent / "src" / "nabiz" / "console" / "static" / "css" / "stop_card.css"
    css = css_path.resolve().read_text(encoding="utf-8")
    assert "@media print" in css and "@page" in css and "A6" in css
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(|oklch\(", css)
    assert not re.search(r"animation|transition|@keyframes|\bETA\b|—|–", css, re.I)
    assert not any(int(px) > 320 for px in re.findall(r"(?:min-)?width:\s*(\d+)px", css))
    assert len(css.splitlines()) <= 250


def test_module_imports_stay_in_the_facade() -> None:
    root = FIXTURES_DIR.parent.parent.resolve()
    source = root / "src" / "nabiz" / "console"
    for filename in ("stop_card.py", "stop_card_html.py"):
        tree = ast.parse((source / filename).read_text(encoding="utf-8"))
        imports = []
        private_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
                private_imports.extend(alias.name for alias in node.names if alias.name.startswith("_"))
        assert not any(
            name == "ibb_mcp.gtfs" or name.startswith(("ibb_mcp.sources", "ibb_mcp.lines", "httpx", "openai", "nabiz.agent.llm"))
            for name in imports
        )
        assert not private_imports
        if filename == "stop_card_html.py":
            assert "ibb_mcp.tools" not in imports and "nabiz.console.arrival" not in imports


def test_console_app_serves_the_stop_card(nabiz: Nabiz) -> None:
    from nabiz.console.app import build_console_app

    app = build_console_app(
        settings=offline_settings(),
        nabiz=nabiz,
        llm_config=llm.LlmConfig(),
        guard=SpendGuard(BudgetConfig(state_path=None)),
    )
    with TestClient(app) as client:
        response = client.get("/d/401351")
    assert response.status_code == 200
    assert "script-src 'self'" in response.headers["content-security-policy"]


def test_stuck_lines_share_one_timeout(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    async def stuck(*args: Any, **kwargs: Any) -> dict[str, Any]:
        await asyncio.sleep(30)
        return {}

    monkeypatch.setenv("NABIZ_STOP_CARD_WAIT_S", "1")
    monkeypatch.setattr(stop_card, "arrival_view", stuck)
    started = time.monotonic()
    with card_client(nabiz) as client:
        body = client.get("/api/stop-card/406031").json()
    elapsed = time.monotonic() - started
    assert elapsed < 2
    assert [row["display"] for row in body["lines"]] == ["doğrulanamadı", "doğrulanamadı"]


def test_tram_stop_is_labelled_rail_not_metro(nabiz: Nabiz) -> None:
    with card_client(nabiz) as client:
        response = client.get("/d/406031")
        body = client.get("/api/stop-card/406031").json()
    assert "Yakındaki raylı istasyon: Mühürdar (T3)" in response.text
    assert "Asansör durumu doğrulanamadı" in response.text
    assert body["metro"]["station"] == "Mühürdar"
    assert body["metro"]["lines"] == ["T3"]
    assert body["metro"]["lift_status"] == "unknown"
    assert "Yakındaki metro" not in response.text
