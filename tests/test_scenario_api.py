"""Offline HTTP, persistence and consent-boundary checks for E77."""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sqlite3
from types import SimpleNamespace
from typing import Any

import httpx
from conftest import offline_settings, refuse_network
from fastapi.testclient import TestClient

from ibb_mcp.cache import TTLCache
from ibb_mcp.http import PoliteClient
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.console.access import OperatorAccess
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.scenario_api import scenario_routes
from nabiz.console.scenario_store import SavedJourneys, ScenarioStore


def _client(tmp_path: pathlib.Path, monkeypatch, *, reader: SavedJourneys | None = None, clock=None):
    path = tmp_path / "scenarios.db"
    monkeypatch.setenv("NABIZ_SCENARIOS_DB_PATH", str(path))
    monkeypatch.setenv("NABIZ_JOURNEY_WATCH_DB_PATH", str(tmp_path / "journey_watch.sqlite"))  # E65 joined in P00 G3
    settings = offline_settings()
    nabiz = Nabiz(
        SourceContext.create(
            client=PoliteClient(transport=httpx.MockTransport(refuse_network)),
            cache=TTLCache(),
            settings=settings,
        )
    )
    app = build_console_app(
        settings=settings,
        nabiz=nabiz,
        llm_config=llm.LlmConfig(),
        guard=SpendGuard(BudgetConfig(state_path=None)),
        access=OperatorAccess(token="scenario-test"),
    )
    app.include_router(scenario_routes)
    # The production integration includes this router before the final static-file mount.
    included = app.router.routes.pop()
    mount = next(index for index, route in enumerate(app.router.routes) if getattr(route, "path", None) == "")
    app.router.routes.insert(mount, included)
    if clock is not None:
        app.state.scenario_clock = clock
    if reader is not None:
        app.state.scenario_saved_journeys = reader
    return app, nabiz, path


def _headers() -> dict[str, str]:
    return {"X-Nabiz-Operator": "scenario-test"}


def test_operator_gate_and_station_catalog_are_offline(tmp_path, monkeypatch) -> None:
    app, _, _ = _client(tmp_path, monkeypatch)
    with TestClient(app) as client:
        assert client.get("/api/console/scenario/stations").status_code == 401
        response = client.get("/api/console/scenario/stations", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["provenance"]["mode"] == "recorded"
    assert {"name", "lines", "lifts", "lift_status_now"} <= set(
        next(item for item in body["stations"] if item["name"] == "Zeytinburnu")
    )


def test_run_matches_measured_demo_and_persists_with_private_errors(tmp_path, monkeypatch) -> None:
    app, nabiz, path = _client(tmp_path, monkeypatch)

    class Engine:
        def __init__(self):
            self._state = {"existing": "unchanged"}

        def states(self):
            return dict(self._state)

    engine = Engine()
    app.state.ports.console = SimpleNamespace(engine=engine)
    states_before = engine.states()
    counts = {"stations": 0, "snapshot": 0}
    source_snapshots = []
    original = nabiz._source

    class Counted:
        def __init__(self, source, kind):
            self.source, self.kind = source, kind

        async def stations(self):
            counts["stations"] += 1
            return await self.source.stations()

        async def snapshot(self, groups=("Asansör",)):
            counts["snapshot"] += 1
            result = await self.source.snapshot(groups)
            source_snapshots.append(result[0])
            return result

    nabiz._source = lambda name: Counted(original(name), name) if name in {"metro", "metro_equipment"} else original(name)
    payload = {
        "station": "Zeytinburnu",
        "line": "M1A",
        "routes": ["Zeytinburnu > Bağcılar", "Bostancı > Kartal", "Maltepe > Pendik"],
        "sample": True,
    }
    with TestClient(app) as client:
        response = client.post("/api/console/scenario/run", headers=_headers(), json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        assert [row["effect"] for row in body["routes"]] == ["blocked", "not_affected", "not_affected"]
        assert body["routes"][0]["sample"] is True
        assert body["closure"]["hypothetical"] is True
        assert body["counts"]["affected"] == 1
        assert body["saved"]["status"] == "no_table"  # E65 present (P00 G3), its store not created yet
        assert counts == {"stations": 1, "snapshot": 1}
        assert source_snapshots and all(record.code != "nabiz-scenario" for record in source_snapshots[0].records)
        assert engine.states() == states_before
        row_id = body["id"]
        assert row_id.startswith("scn-") and len(row_id) == 16
        saved = client.get(f"/api/console/scenario/{row_id}", headers=_headers())
        assert saved.status_code == 200 and saved.json()["recomputed"] is False
        listing = client.get("/api/console/scenario", headers=_headers()).json()
        assert listing["items"][0]["id"] == row_id
        assert client.get("/api/console/scenario", headers={"X-Nabiz-Operator": "wrong"}).status_code == 401
        invalid = client.post(
            "/api/console/scenario/run",
            headers=_headers(),
            json={"station": "Zeytinburnu", "routes": ["not a route", "Bostancı > Kartal"]},
        )
        assert invalid.status_code == 200
        assert [row["effect"] for row in invalid.json()["routes"]] == ["invalid", "not_affected"]
        invalid_id = invalid.json()["id"]
        too_many = client.post(
            "/api/console/scenario/run",
            headers=_headers(),
            json={
                "station": "Zeytinburnu",
                "routes": ["Bostancı > Kartal"] * 13,
            },
        )
        assert too_many.status_code == 422
        assert client.delete(f"/api/console/scenario/{row_id}", headers=_headers()).status_code == 204
        assert client.get(f"/api/console/scenario/{row_id}", headers=_headers()).status_code == 404
    assert path.is_file()
    second, _, _ = _client(tmp_path, monkeypatch)
    with TestClient(second) as client:
        items = client.get("/api/console/scenario", headers=_headers()).json()["items"]
        assert [item["id"] for item in items] == [invalid_id]


def test_scenario_store_ttl_and_limit_use_the_injected_clock(tmp_path) -> None:
    now = [dt.datetime(2026, 9, 26, 12, tzinfo=dt.UTC)]
    store = ScenarioStore(tmp_path / "ttl.db", clock=lambda: now[0])
    result: dict[str, Any] = {"counts": {"affected": 1}, "routes": [], "saved": {"status": "missing"}}
    row = store.add("Zeytinburnu", None, [], result)
    assert len(store.items()) == 1 and store.get(row["id"])
    now[0] += dt.timedelta(days=31)
    assert store.items() == [] and store.get(row["id"]) is None


def test_saved_journey_reader_is_read_only_and_requires_explicit_consent(tmp_path) -> None:
    absent = tmp_path / "not-created.db"
    assert SavedJourneys(absent, module_available=True).read().status == "no_table"
    assert not absent.exists()
    path = tmp_path / "journey_watch.db"
    now = dt.datetime(2026, 9, 26, tzinfo=dt.UTC)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE journey_watch (id TEXT, account_id TEXT, "
            "created_at TEXT, last_seen_at TEXT, expires_at TEXT, consent_version TEXT, data TEXT)"
        )
        for index in range(4):
            connection.execute(
                "INSERT INTO journey_watch VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    f"private-{index}",
                    "private-account",
                    now.isoformat(),
                    now.isoformat(),
                    (now + dt.timedelta(days=2)).isoformat(),
                    "v2",
                    json.dumps({"from": "Kadıköy", "to": "Levent", "time": now.isoformat(), "needs": ["step_free"]}),
                ),
            )
    denied = SavedJourneys(path, clock=lambda: now, module_available=True, consent_versions=frozenset()).read()
    assert denied.status == "consent_scope" and denied.pairs == ()
    reader = SavedJourneys(path, clock=lambda: now, module_available=True, consent_versions=frozenset({"v2"}))
    allowed = reader.read()
    assert allowed.status == "ok" and allowed.considered == 4 and allowed.pairs[0][1] == 4
    assert "private-account" not in repr(allowed) and "private-0" not in repr(allowed)
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(journey_watch)")}
        assert {"id", "account_id", "created_at", "last_seen_at", "expires_at", "consent_version", "data"} == columns


def test_saved_journey_http_result_contains_only_suppressed_totals(tmp_path, monkeypatch) -> None:
    now = dt.datetime(2026, 9, 26, tzinfo=dt.UTC)
    watch = tmp_path / "journey_watch.db"
    with sqlite3.connect(watch) as connection:
        connection.execute(
            "CREATE TABLE journey_watch (id TEXT, account_id TEXT, "
            "created_at TEXT, last_seen_at TEXT, expires_at TEXT, consent_version TEXT, data TEXT)"
        )
        for index in range(2):
            connection.execute(
                "INSERT INTO journey_watch VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    f"private-{index}",
                    "private-account",
                    now.isoformat(),
                    now.isoformat(),
                    (now + dt.timedelta(days=2)).isoformat(),
                    "v2",
                    json.dumps({"from": "Bostancı", "to": "Kartal", "time": now.isoformat(), "needs": ["step_free"]}),
                ),
            )
    reader = SavedJourneys(watch, clock=lambda: now, module_available=True, consent_versions=frozenset({"v2"}))
    app, _, _ = _client(tmp_path, monkeypatch, reader=reader)
    with TestClient(app) as client:
        response = client.post(
            "/api/console/scenario/run",
            headers=_headers(),
            json={
                "station": "Zeytinburnu",
                "line": "M1A",
                "routes": ["Zeytinburnu > Bağcılar"],
                "include_saved": True,
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["saved"]["status"] == "ok" and body["saved"]["considered"] == "lt3"
    assert set(body["saved"]["effects"].values()) == {"lt3"}
    assert "private-account" not in response.text and "private-0" not in response.text
    assert body["assumptions"][-2:] == ["saved_scope", "small_hidden"]
