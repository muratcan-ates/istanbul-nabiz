"""The console's request log writes the route template, never a citizen's code from the URL.

A request code, photo code or journey id in the path opens a citizen's file, so the log line
carries ``/api/requests/{code}``, also when the operator's door refuses the request before any
route runs, and a fixed marker when nothing matches. Every row lives in this test's temporary
folder; no model, no İBB call. The token and the codes below are test values.
"""

from __future__ import annotations

import logging
import pathlib

import pytest
from conftest import offline_settings
from fastapi.testclient import TestClient

from nabiz.agent import llm
from nabiz.console.access import OperatorAccess
from nabiz.console.app import UNMATCHED_PATH, build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard

TOKEN = "test-operator-token"
CODE = "ABCD2345"


@pytest.fixture
def console(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "nexus.db"))
    monkeypatch.setenv("NABIZ_REQUESTS_DB_PATH", str(tmp_path / "requests.db"))
    app = build_console_app(
        settings=offline_settings(),
        llm_config=llm.LlmConfig(),
        guard=SpendGuard(BudgetConfig(state_path=None)),
        access=OperatorAccess(token=TOKEN, bound_host="0.0.0.0"),
    )
    return TestClient(app, base_url="http://127.0.0.1:8090")


def log_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "nabiz.console"]


def test_a_citizen_code_in_the_path_is_logged_as_its_template(console: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="nabiz.console"):
        console.get(f"/api/requests/{CODE}")
    lines = log_lines(caplog)
    assert any(line.startswith("GET /api/requests/{code} -> ") for line in lines), lines
    assert not any(CODE in line for line in lines)


def test_a_refused_operator_path_is_logged_as_its_template(console: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="nabiz.console"):
        response = console.post(f"/api/console/requests/{CODE}/reply", json={"text": "x"})
    assert response.status_code == 401
    lines = log_lines(caplog)
    assert any(line.startswith("POST /api/console/requests/{code}/reply -> 401") for line in lines), lines
    assert not any(CODE in line for line in lines)


def test_an_unmatched_path_is_a_fixed_marker(console: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="nabiz.console"):
        console.get(f"/api/nothing/{CODE}")
        console.get(f"/console/escort/{CODE}")
        console.get(f"/no-such-page/{CODE}")
    lines = log_lines(caplog)
    assert sum(line.startswith(f"GET {UNMATCHED_PATH} -> ") for line in lines) == 3, lines
    assert not any(CODE in line for line in lines)


def test_a_served_page_file_keeps_its_name(console: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="nabiz.console"):
        assert console.get("/index.html").status_code == 200
    assert any(line.startswith("GET /index.html -> 200") for line in log_lines(caplog))


def test_the_doors_json_refusal_is_never_cached(console: TestClient) -> None:
    """P00 G2 (E51 note): the 401 the door returns before any route runs carries no-store too."""
    response = console.get("/api/console/photo-reports")
    assert response.status_code == 401 and response.headers["cache-control"] == "no-store"


def test_the_wave_codes_are_logged_as_templates(console: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    """P00 G2 (E71 note): escort, photo, timeline and editor codes never reach the log; E66's own filter is gone."""
    ref = "abcdef123456"
    with caplog.at_level(logging.INFO, logger="nabiz.console"):
        console.get(f"/api/escort/requests/{CODE}")
        assert console.post(f"/api/console/escort/{CODE}/move", json={"to": "reviewing"}).status_code == 401
        assert console.get(f"/api/console/photo-reports/{CODE}/photo").status_code == 401
        console.get(f"/api/report/timeline/{CODE}")
        assert console.get(f"/api/console/knowledge-editor/gaps/{ref}").status_code == 401
    lines = log_lines(caplog)
    for template in (
        "GET /api/escort/requests/{code} -> ", "POST /api/console/escort/{code}/move -> 401",
        "GET /api/console/photo-reports/{code}/photo -> 401", "GET /api/report/timeline/{code} -> ",
        "GET /api/console/knowledge-editor/gaps/{ref} -> 401",
    ):
        assert any(line.startswith(template) for line in lines), (template, lines)
    assert not any(CODE in line or ref in line for line in lines)
    assert not any(type(item).__name__ == "_TimelineLogFilter" for item in logging.getLogger("nabiz.console").filters)
