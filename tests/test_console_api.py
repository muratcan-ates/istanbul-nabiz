"""The product app's citizen routes (arrival, brief, alternative) and the operator routes over fake ports.

The decision core and the step-free computation are other lanes' work, so the operator routes
are tested against :class:`FakeConsole` and :class:`FakeStepFree`: what is under test is the
route layer (validation, the error contract, the actor it records), not the store.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator, Sequence
from typing import Any

import httpx
import pytest
from conftest import offline_settings, refuse_network
from fastapi.testclient import TestClient

from ibb_mcp.cache import TTLCache
from ibb_mcp.config import Settings
from ibb_mcp.http import PoliteClient, UpstreamUnavailable
from ibb_mcp.models import Provenance, ToolResult, utcnow
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.console.app import build_console_app
from nabiz.console.arrival import single_minute
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.ports import OPERATOR, Ports

PROVENANCE_KEYS = {"source", "url", "observed_at", "age_s", "mode"}
CARD_KEYS = {"id", "kind", "title", "body", "status", "provenance", "author", "how"}
DISPLAYS = {"tarifeye göre", "doğrulanamadı"}


@pytest.fixture(scope="module")
def nabiz() -> Iterator[Nabiz]:
    yield Nabiz(
        SourceContext.create(
            client=PoliteClient(transport=httpx.MockTransport(refuse_network)),
            cache=TTLCache(),
            settings=offline_settings(),
        )
    )


def app_client(nabiz: Any, *, ports: Ports | None = None, settings: Settings | None = None) -> TestClient:
    app = build_console_app(
        settings=settings,
        nabiz=nabiz,
        llm_config=llm.LlmConfig(),
        ports=ports,
        guard=SpendGuard(BudgetConfig(state_path=None)),
    )
    return TestClient(app)


def strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


# --------------------------------------------------------------------------------------
# the single-minute rule
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("eta", "method", "age", "expected"),
    [
        (7.9, "stop_sequence", 30, (7, "7 dk")),  # rounded down: early beats late
        (0.4, "distance", 30, (1, "1 dk")),  # under a minute is still "1 dk", never "şimdi"
        (-0.3, "stop_sequence", 30, (1, "1 dk")),
        (12.0, "stop_sequence", 181, (None, "tarifeye göre")),  # position older than the threshold
        (12.0, "stop_sequence", None, (None, "tarifeye göre")),  # an age nobody can prove is not fresh
        (12.0, "schedule", 5, (None, "tarifeye göre")),  # counted to the terminus departure, not the stop
        (None, "stop_sequence", 5, (None, "doğrulanamadı")),
        (5.0, None, 5, (None, "doğrulanamadı")),
    ],
)
def test_single_minute(eta: float | None, method: str | None, age: float | None, expected: tuple[int | None, str]) -> None:
    shown = single_minute(eta, method=method, age_s=age, stale_after_s=180, offline=False)
    assert (shown.minutes, shown.display) == expected
    assert shown.mode == {"tarifeye göre": "schedule", "doğrulanamadı": "unknown"}.get(shown.display, "live")


def test_a_recorded_estimate_is_never_called_live() -> None:
    assert single_minute(7.0, method="stop_sequence", age_s=10, stale_after_s=180, offline=True).mode == "recorded"


class StubArrivals:
    """Just the one tool ``/api/arrival`` calls, returning a crafted result or raising."""

    def __init__(
        self,
        *,
        arrivals: Sequence[dict[str, Any]] = (),
        dropped_stale: int = 0,
        stale_live: Sequence[dict[str, Any]] = (),
        error: Exception | None = None,
    ):
        self.settings = Settings(offline=False)
        self.arrivals, self.dropped_stale, self.error = list(arrivals), dropped_stale, error
        self.stale_live = list(stale_live)
        self.stale_after_s: float | None = None

    async def iett_next_arrivals(
        self, line_code: str, stop: str, limit: int = 3, stale_after_s: float | None = None
    ) -> ToolResult:
        self.stale_after_s = stale_after_s
        if self.error is not None:
            raise self.error
        now = utcnow()
        return ToolResult(
            data={
                "line_code": line_code.upper(),
                "stop": {"stop_code": "401351", "name": "ŞİFA SONDURAK"},
                "arrivals": self.arrivals,
                "diagnostics": {"dropped_stale": self.dropped_stale, "stale_live": self.stale_live},
            },
            provenance=Provenance(source="iett_line", source_url="https://x.invalid", observed_at=now, reported_at=now),
        )


def bus(eta: float, *, age_s: float, method: str = "stop_sequence") -> dict[str, Any]:
    return {"eta_minutes": eta, "method": method, "reported_at": (utcnow() - dt.timedelta(seconds=age_s)).isoformat()}


def arrival(stub: StubArrivals) -> dict[str, Any]:
    with app_client(stub, settings=stub.settings) as client:
        response = client.get("/api/arrival", params={"line": "500t", "stop": "401351"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"line", "stop", "minutes", "display", "provenance"}
    assert set(body["provenance"]) == PROVENANCE_KEYS
    assert "ETA" not in json.dumps(body, ensure_ascii=False)
    return body


def test_arrival_fresh_position_shows_one_whole_minute() -> None:
    body = arrival(StubArrivals(arrivals=[bus(6.6, age_s=40)]))
    assert (body["minutes"], body["display"]) == (6, "6 dk")
    assert body["provenance"]["mode"] == "live" and 39 <= body["provenance"]["age_s"] <= 45
    assert (body["line"], body["stop"]) == ("500T", "ŞİFA SONDURAK")


def test_arrival_under_a_minute_is_one_minute() -> None:
    assert arrival(StubArrivals(arrivals=[bus(0.2, age_s=10)]))["display"] == "1 dk"


def test_arrival_stale_position_withdraws_the_number() -> None:
    body = arrival(StubArrivals(arrivals=[bus(6.6, age_s=400)]))
    assert (body["minutes"], body["display"], body["provenance"]["mode"]) == (None, "tarifeye göre", "schedule")
    assert body["provenance"]["age_s"] >= 400, "the card still says how old the position is"


def test_arrival_staleness_threshold_is_a_knob(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NABIZ_ARRIVAL_STALE_S", "600")
    assert arrival(StubArrivals(arrivals=[bus(6.6, age_s=400)]))["display"] == "6 dk"


def test_arrival_with_only_old_positions_is_by_timetable() -> None:
    body = arrival(StubArrivals(dropped_stale=12))
    assert (body["minutes"], body["display"]) == (None, "tarifeye göre")


def test_arrival_passes_its_stale_limit_to_the_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """G12: the tool falls back to the timetable past the same age the card withdraws a number at."""
    stub = StubArrivals(arrivals=[bus(6.6, age_s=40)])
    arrival(stub)
    assert stub.stale_after_s == 180
    monkeypatch.setenv("NABIZ_ARRIVAL_STALE_S", "600")
    arrival(stub)
    assert stub.stale_after_s == 600


def test_arrival_past_the_stale_limit_without_a_timetable_is_by_timetable() -> None:
    """The tool dropped every live estimate as older than the card's limit and found no timetable to
    fall back on: the stale case again, so the card says "tarifeye göre", never a number."""
    body = arrival(StubArrivals(stale_live=[{"door_no": "", "age_s": 240.0, "method": "stop_sequence", "eta_minutes": 6.6}]))
    assert (body["minutes"], body["display"], body["provenance"]["mode"]) == (None, "tarifeye göre", "schedule")


def test_arrival_from_the_gtfs_timetable_has_no_number() -> None:
    body = arrival(StubArrivals(arrivals=[bus(10.0, age_s=0, method="schedule")]))
    assert (body["minutes"], body["display"], body["provenance"]["mode"]) == (None, "tarifeye göre", "schedule")


def test_arrival_with_nothing_is_unverified() -> None:
    body = arrival(StubArrivals())
    assert (body["minutes"], body["display"], body["provenance"]["mode"]) == (None, "doğrulanamadı", "unknown")


def test_arrival_when_ibb_is_down_is_unverified_not_an_error() -> None:
    body = arrival(StubArrivals(error=UpstreamUnavailable("503", source="iett", status=503)))
    assert (body["minutes"], body["display"]) == (None, "doğrulanamadı")
    assert body["provenance"] == {"source": "iett", "url": None, "observed_at": None, "age_s": None, "mode": "unknown"}


def test_arrival_for_an_unknown_line_is_a_400_with_the_reason() -> None:
    stub = StubArrivals(error=ValueError("'999X' İETT'nin GTFS hat listesinde yok"))
    with app_client(stub, settings=stub.settings) as client:
        response = client.get("/api/arrival", params={"line": "999X", "stop": "x"})
    assert response.status_code == 400 and "999X" in response.json()["message"]


def test_arrival_on_the_recorded_fixture_never_claims_live(nabiz: Nabiz) -> None:
    with app_client(nabiz) as client:
        body = client.get("/api/arrival", params={"line": "500T", "stop": "401351"}).json()
    assert body["display"] in DISPLAYS or body["display"].endswith(" dk")
    assert body["provenance"]["mode"] != "live"


# --------------------------------------------------------------------------------------
# fake ports
# --------------------------------------------------------------------------------------
class FakeStepFree:
    def __init__(self, lift_status: str = "out_of_service", *, fail: bool = False) -> None:
        self.lift_status, self.fail = lift_status, fail
        self.asked: list[tuple[str, list[str]]] = []

    async def alternative(self, station: str, needs: Sequence[str]) -> dict[str, Any]:
        self.asked.append((station, list(needs)))
        if self.fail:
            raise RuntimeError("equipment source down")
        return {
            "station": station,
            "lift_status": self.lift_status,
            "alternative": {"station": "Şişhane", "line": "M2", "extra_minutes": 4, "reason": "asansör kaydı temiz"},
            "operator_approved": False,
            "provenance": {"source": "metro_equipment", "url": None, "observed_at": "2026-09-25T06:00:00+00:00", "age_s": 60,
                           "mode": "recorded"},
        }  # fmt: skip


class FakeConsole:
    """Records what the routes hand over; ``missing`` ids raise LookupError as the contract says."""

    def __init__(self) -> None:
        self.decided: list[dict[str, Any]] = []
        self.adopted: list[dict[str, Any]] = []
        self.missing = {"nope"}

    async def queue(self) -> dict[str, Any]:
        return {"items": [{"signal_id": "s1", "kind": "lift_fault", "title": "Taksim asansör", "severity": "warning",
                           "path": "arena", "status": "awaiting_approval", "created_at": "2026-09-25T06:00:00+00:00",
                           "summary": "Asansör arızası"}]}  # fmt: skip

    async def decision(self, signal_id: str) -> dict[str, Any]:
        if signal_id in self.missing:
            raise KeyError(signal_id)
        return {"signal_id": signal_id, "author": "kural"}

    async def decide(self, signal_id: str, *, action: str, reason: str, edited_text: str | None, actor: str) -> dict[str, Any]:
        if signal_id in self.missing:
            raise KeyError(signal_id)
        if signal_id == "closed":
            raise ValueError("Bu sinyal zaten kapandı.")
        self.decided.append(
            {"signal_id": signal_id, "action": action, "reason": reason, "edited_text": edited_text, "actor": actor}
        )
        return {"status": "approved" if action == "approve" else action, "ledger_entry_id": "L1"}

    async def trace(self, signal_id: str) -> dict[str, Any]:
        step = {"at": "2026-09-25T06:00:00+00:00", "actor": "reflex", "kind": "routed", "detail": "arena"}
        return {"steps": [step], "hash_ok": True}

    async def verify(self) -> dict[str, Any]:
        return {"ok": True, "entries": 3}

    async def stats(self) -> dict[str, Any]:
        return {"reflex_closed_today": 2, "awaiting_approval": 1, "median_decision_s": None,
                "citizen_update_latency_s": None, "approval_rate": None}  # fmt: skip

    async def rule_drafts(self) -> dict[str, Any]:
        return {"drafts": []}

    async def adopt_rule(self, draft_id: str, *, reason: str, actor: str) -> dict[str, Any]:
        self.adopted.append({"draft_id": draft_id, "reason": reason, "actor": actor})
        return {"rule_id": "R-100", "expires_at": "2026-10-25T00:00:00+00:00"}

    async def simulate(self, fixture: str) -> dict[str, Any]:
        if fixture == "unknown_fixture":
            raise KeyError(fixture)
        return {"signal_id": f"sim-{fixture}"}


@pytest.fixture
def console(nabiz: Nabiz) -> Iterator[tuple[TestClient, FakeConsole]]:
    fake = FakeConsole()
    with app_client(nabiz, ports=Ports(step_free=FakeStepFree(), console=fake)) as client:
        yield client, fake


@pytest.mark.parametrize(
    ("path", "key"),
    [
        ("/api/console/queue", "items"),
        ("/api/console/decisions/s1", "signal_id"),
        ("/api/console/ledger/s1/trace", "hash_ok"),
        ("/api/console/ledger/verify", "entries"),
        ("/api/console/stats", "reflex_closed_today"),
        ("/api/console/rule-drafts", "drafts"),
    ],
)
def test_console_reads_pass_through_the_port(console: tuple[TestClient, FakeConsole], path: str, key: str) -> None:
    client, _ = console
    response = client.get(path)
    assert response.status_code == 200, response.text
    assert key in response.json()


def test_an_approval_is_recorded_as_the_simulated_operator(console: tuple[TestClient, FakeConsole]) -> None:
    client, fake = console
    response = client.post("/api/console/decisions/s1", json={"action": "approve", "reason": "", "edited_text": None})
    assert response.status_code == 200 and response.json() == {"status": "approved", "ledger_entry_id": "L1"}
    assert fake.decided == [{"signal_id": "s1", "action": "approve", "reason": "", "edited_text": None, "actor": OPERATOR}]
    assert OPERATOR == "Simüle operatör"


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"action": "reject", "reason": ""}, "reason_required"),
        ({"action": "defer", "reason": "   "}, "reason_required"),
        ({"action": "edit", "reason": "metin", "edited_text": "  "}, "edited_text_required"),
    ],
)
def test_a_decision_without_its_reason_is_refused_before_the_core(
    console: tuple[TestClient, FakeConsole], body: dict[str, Any], error: str
) -> None:
    client, fake = console
    response = client.post("/api/console/decisions/s1", json=body)
    assert response.status_code == 400 and response.json()["error"] == error
    assert fake.decided == []


def test_a_reasoned_rejection_and_an_edit_reach_the_core(console: tuple[TestClient, FakeConsole]) -> None:
    client, fake = console
    assert client.post("/api/console/decisions/s1", json={"action": "reject", "reason": " kanıt eski "}).status_code == 200
    assert client.post("/api/console/decisions/s1", json={"action": "edit", "edited_text": "Yeni metin"}).status_code == 200
    recorded = [(d["action"], d["reason"], d["edited_text"]) for d in fake.decided]
    assert recorded == [("reject", "kanıt eski", None), ("edit", "", "Yeni metin")]


@pytest.mark.parametrize(
    ("method", "path", "body", "status"),
    [
        ("get", "/api/console/decisions/nope", None, 404),
        ("post", "/api/console/decisions/nope", {"action": "approve"}, 404),
        ("post", "/api/console/decisions/closed", {"action": "approve"}, 400),
        ("post", "/api/console/decisions/s1", {"action": "delete"}, 422),
        ("get", "/api/console/decisions/" + "x" * 81, None, 422),
        ("post", "/api/console/simulate", {"fixture": "../../etc/passwd"}, 422),
        ("post", "/api/console/simulate", {"fixture": "unknown_fixture"}, 404),
        ("post", "/api/console/rule-drafts/d1/adopt", {"reason": "   "}, 400),
        ("post", "/api/console/rule-drafts/d1/adopt", {}, 422),
    ],
)
def test_the_console_error_contract(
    console: tuple[TestClient, FakeConsole], method: str, path: str, body: dict[str, Any] | None, status: int
) -> None:
    client, _ = console
    response = client.request(method.upper(), path, json=body)
    assert response.status_code == status, response.text


def test_simulate_and_adopt_reach_the_core(console: tuple[TestClient, FakeConsole]) -> None:
    client, fake = console
    simulated = client.post("/api/console/simulate", json={"fixture": "taksim_lift_fault"})
    assert simulated.json() == {"signal_id": "sim-taksim_lift_fault"}
    adopted = client.post("/api/console/rule-drafts/d1/adopt", json={"reason": "üç onay, aynı desen"})
    assert adopted.status_code == 200 and adopted.json()["rule_id"] == "R-100"
    assert fake.adopted == [{"draft_id": "d1", "reason": "üç onay, aynı desen", "actor": OPERATOR}]


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/api/console/queue", None),
        ("get", "/api/console/decisions/s1", None),
        ("post", "/api/console/decisions/s1", {"action": "approve"}),
        ("get", "/api/console/ledger/s1/trace", None),
        ("get", "/api/console/ledger/verify", None),
        ("get", "/api/console/stats", None),
        ("get", "/api/console/rule-drafts", None),
        ("post", "/api/console/rule-drafts/d1/adopt", {"reason": "x"}),
        ("post", "/api/console/simulate", {"fixture": "taksim"}),
    ],
)
def test_an_unwired_console_says_so(nabiz: Nabiz, method: str, path: str, body: dict[str, Any] | None) -> None:
    with app_client(nabiz) as client:
        response = client.request(method.upper(), path, json=body)
    assert response.status_code == 503 and response.json()["error"] == "not_wired"


# --------------------------------------------------------------------------------------
# alternative and brief
# --------------------------------------------------------------------------------------
def test_alternative_passes_the_port_view_and_only_known_needs(nabiz: Nabiz) -> None:
    step_free = FakeStepFree()
    with app_client(nabiz, ports=Ports(step_free=step_free)) as client:
        body = client.get("/api/alternative", params={"station": "Taksim", "needs": "step_free,wheelchair_user"}).json()
    assert body["lift_status"] == "out_of_service" and body["alternative"]["station"] == "Şişhane"
    assert step_free.asked == [("Taksim", ["step_free"])]


@pytest.mark.parametrize("step_free", [None, FakeStepFree(fail=True), FakeStepFree(lift_status="probably fine")])
def test_alternative_without_a_readable_record_is_unknown(nabiz: Nabiz, step_free: FakeStepFree | None) -> None:
    with app_client(nabiz, ports=Ports(step_free=step_free) if step_free else None) as client:
        body = client.get("/api/alternative", params={"station": "Taksim"}).json()
    assert body["lift_status"] == "unknown"
    assert set(body) >= {"station", "lift_status", "alternative", "operator_approved", "provenance"}


def brief(nabiz: Nabiz, step_free: FakeStepFree | None, **params: str) -> list[dict[str, Any]]:
    with app_client(nabiz, ports=Ports(step_free=step_free) if step_free else None) as client:
        response = client.get("/api/brief", params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"cards", "generated_at"}
    for one in body["cards"]:
        assert set(one) == CARD_KEYS, one
        assert set(one["provenance"]) == PROVENANCE_KEYS, one
        assert one["author"] == "kural" and one["status"] in {"ok", "warning", "stale", "unverified"}
        assert one["provenance"]["mode"] != "live", "offline cards are recorded, never live"
    for text in strings(body):
        assert "—" not in text and "–" not in text and "ETA" not in text, text
        assert "çalışıyor" not in text, "a lift is never said to work"
    return body["cards"]


def test_brief_with_a_step_free_need_offers_the_alternative(nabiz: Nabiz) -> None:
    cards = brief(nabiz, FakeStepFree(), stations="Taksim", lines="M7,500T:401351", needs="step_free")
    kinds = [one["kind"] for one in cards]
    assert kinds[:3] == ["metro_status", "metro_equipment", "alternative"]
    assert {"arrival", "traffic", "air"} <= set(kinds)
    alternative = cards[2]
    assert "Şişhane (M2)" in alternative["body"] and "Operatör onayı yok" in alternative["body"]
    assert cards[1]["status"] == "warning"


def test_brief_without_the_need_shows_the_lift_record_only(nabiz: Nabiz) -> None:
    kinds = [one["kind"] for one in brief(nabiz, FakeStepFree(), stations="Taksim")]
    assert "metro_equipment" in kinds and "alternative" not in kinds


def test_brief_without_equipment_data_says_unverified(nabiz: Nabiz) -> None:
    cards = brief(nabiz, None, stations="Taksim", needs="step_free")
    lift = next(one for one in cards if one["kind"] == "metro_equipment")
    assert lift["status"] == "unverified" and lift["provenance"]["mode"] == "unknown"


def test_every_brief_card_says_how_it_was_found(nabiz: Nabiz) -> None:
    cards = brief(nabiz, FakeStepFree(), stations="Kartal", lines="500T:401351", needs="step_free")
    required = {"tool", "source_url", "observed_at", "rule_id", "signal_id", "uncertainty", "latency_ms"}
    for one in cards:
        assert isinstance(one["how"], dict)
        assert required <= one["how"].keys()
        assert isinstance(one["how"]["uncertainty"], list)


def test_brief_with_nothing_saved_still_shows_the_city(nabiz: Nabiz) -> None:
    assert [one["kind"] for one in brief(nabiz, None)] == ["metro_status", "traffic"]


# --------------------------------------------------------------------------------------
# the page and the process
# --------------------------------------------------------------------------------------
def test_the_page_is_served_with_its_notice_and_headers(nabiz: Nabiz) -> None:
    with app_client(nabiz) as client:
        page = client.get("/")
        health = client.get("/healthz").json()
    assert page.status_code == 200 and "Resmî İBB hizmeti değildir" in page.text
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert health == {"status": "ok", "offline": True, "model": {"provider": "none", "configured": False, "within_budget": True}}
