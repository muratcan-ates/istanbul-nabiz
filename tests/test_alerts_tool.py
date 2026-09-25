"""``check_alerts`` as a tool: the façade, the MCP server with its typed schema, and the web route.

``tests/test_alerts.py`` proves the engine forgets what it is given. These prove the two
doors in front of it keep that promise too: the MCP tool advertises a real schema (so a
model is not left guessing an opaque object), evaluates the subscription in memory, writes
nothing to disk and logs no coordinate on the way through ``call_tool``, and the web route
takes the subscription in a POST body, never a query string. (The SDK's request-level
logging sits outside ``call_tool``; ``docs/privacy.md`` §2 says what it logs and that no test
pins it.)

Everything runs sealed (see ``tests/test_tools_extra.py``): no ``data/lake``, no GTFS, and
no committed reliability table.
"""

from __future__ import annotations

import builtins
import json
import logging
import pathlib
from collections.abc import Iterator
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from test_tools_extra import sealed, sealed_nabiz  # noqa: F401 - ``sealed`` is a fixture used by name

from ibb_mcp.alerts.schema import AlertSubscription
from ibb_mcp.server import build_server
from ibb_mcp.tools import Nabiz

#: A coordinate distinctive enough to find in any log line or file it might leak into.
HOME_LAT, HOME_LON = 41.0431287, 29.0094213
HOME_LAT_TEXT, HOME_LON_TEXT = "41.0431287", "29.0094213"


def subscription(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "places": [{"key": "ev", "label": "Ev", "lat": HOME_LAT, "lon": HOME_LON}],
        "rules": [
            {"kind": "traffic", "threshold_index": 1},
            {"kind": "air_quality", "place": "ev", "aqi_threshold": 1},
            {"kind": "metro_disruption", "lines": ["M4"]},
        ],
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def nabiz(sealed: list[str], tmp_path: pathlib.Path) -> Nabiz:  # noqa: F811 - the imported fixture, requested by name
    return sealed_nabiz(tmp_path)


# --------------------------------------------------------------------------------------
# the façade
# --------------------------------------------------------------------------------------
async def test_the_tool_returns_the_engines_whole_answer(nabiz: Nabiz) -> None:
    result = await nabiz.check_alerts(subscription())
    data = result.data

    kinds = {alert["kind"] for alert in data["alerts"]}
    assert {"traffic", "air_quality"} <= kinds  # thresholds of 1 fire on any recorded reading
    assert data["alert_count"] == len(data["alerts"])
    assert data["stateless"] is True
    assert data["privacy"]["stored_server_side"] == "none"
    assert data["cooldown_policy"]["enforced_by"] == "client"
    assert data["disclaimer"]
    for alert in data["alerts"]:
        assert alert["dedupe_key"] and alert["cooldown_seconds"] >= 300
        assert all(citation["provenance"]["source"] for citation in alert["citations"])
    assert result.provenance.source == "nabiz_alerts"
    json.dumps(data)


async def test_a_typed_subscription_and_a_plain_dict_are_the_same_request(nabiz: Nabiz) -> None:
    typed = await nabiz.check_alerts(AlertSubscription.model_validate(subscription()))
    plain = await nabiz.check_alerts(subscription())
    assert [a["dedupe_key"] for a in typed.data["alerts"]] == [a["dedupe_key"] for a in plain.data["alerts"]]


async def test_an_unreadable_source_is_said_out_loud_not_reported_as_all_clear(
    nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ibb_mcp.http import UpstreamUnavailable

    async def down(self: Any) -> Any:
        raise UpstreamUnavailable("metro down")

    monkeypatch.setattr("ibb_mcp.sources.metro.MetroSource.service_status", down)
    result = await nabiz.check_alerts({"rules": [{"kind": "metro_disruption", "lines": ["M4"]}]})

    assert result.data["alerts"] == []
    assert "metro_status" in result.data["unavailable"]
    assert "Kontrol edilemeyenler" in result.note


async def test_bunching_without_a_reliability_table_reports_why(nabiz: Nabiz) -> None:
    result = await nabiz.check_alerts({"rules": [{"kind": "bus_bunching", "line": "500T"}]})
    assert result.data["alerts"] == []
    assert "üretilmedi" in result.data["unavailable"]["reliability"]


async def test_a_coordinate_outside_istanbul_is_refused_without_being_echoed(nabiz: Nabiz) -> None:
    foreign = subscription(places=[{"key": "ev", "lat": 52.5200066, "lon": 13.404954}])
    with pytest.raises(ValueError) as caught:
        await nabiz.check_alerts(foreign)
    assert "52.52" not in str(caught.value) and "13.40" not in str(caught.value)
    assert "'ev'" in str(caught.value)


# --------------------------------------------------------------------------------------
# the MCP layer
# --------------------------------------------------------------------------------------
def resolve(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    ref = node.get("$ref")
    return schema["$defs"][ref.rsplit("/", 1)[-1]] if ref else node


async def test_the_subscription_schema_is_typed_not_an_opaque_object(nabiz: Nabiz) -> None:
    tool = next(t for t in await build_server(app=nabiz).list_tools() if t.name == "check_alerts")
    schema = tool.input_schema
    sub = resolve(schema, schema["properties"]["subscription"])

    assert set(sub["properties"]) == {"places", "rules", "muted_keys"}
    assert sub["required"] == ["rules"]
    place = resolve(schema, sub["properties"]["places"]["items"])
    assert set(place["required"]) == {"key", "lat", "lon"}
    variants = sub["properties"]["rules"]["items"]["oneOf"]
    kinds = {resolve(schema, variant)["properties"]["kind"]["const"] for variant in variants}
    assert kinds == {"metro_disruption", "parking_filling", "air_quality", "traffic", "bus_bunching", "lift_outage"}
    # The KVKK promise is part of what the model reads, not only of docs/privacy.md.
    assert "SAKLANMAZ" in tool.description and "docs/privacy.md" in tool.description


async def test_check_alerts_renders_through_the_server_and_logs_no_coordinate(
    nabiz: Nabiz, caplog: pytest.LogCaptureFixture
) -> None:
    server = build_server(app=nabiz)
    with caplog.at_level(logging.DEBUG):
        result = await server.call_tool("check_alerts", {"subscription": subscription()})
    payload = json.loads(result.content[0].text)

    assert payload["data"]["alert_count"] >= 2
    assert payload["provenance"]["source"] == "nabiz_alerts"
    logged = "\n".join(record.getMessage() for record in caplog.records)
    for secret in (HOME_LAT_TEXT, HOME_LON_TEXT, "Ev"):
        assert secret not in logged, f"{secret!r} reached a log record"


async def test_check_alerts_through_the_server_writes_nothing_to_disk(nabiz: Nabiz, monkeypatch: pytest.MonkeyPatch) -> None:
    server = build_server(app=nabiz)
    real_open = builtins.open

    def read_only_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if any(flag in mode for flag in "wax+"):
            raise AssertionError(f"check_alerts tried to write {file!r}")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", read_only_open)
    monkeypatch.setattr(pathlib.Path, "write_text", lambda *a, **k: pytest.fail("write_text during check_alerts"))
    result = await server.call_tool("check_alerts", {"subscription": subscription()})
    assert json.loads(result.content[0].text)["data"]["stateless"] is True


async def test_an_unknown_rule_kind_is_rejected_by_the_schema(nabiz: Nabiz) -> None:
    with pytest.raises(ToolError, match="tsunami"):
        await build_server(app=nabiz).call_tool("check_alerts", {"subscription": {"rules": [{"kind": "tsunami"}]}})


async def test_a_bad_subscription_is_a_readable_refusal_over_mcp(nabiz: Nabiz) -> None:
    rules = [{"kind": "air_quality", "place": "is"}]  # refers to a place that was never declared
    result = await build_server(app=nabiz).call_tool("check_alerts", {"subscription": subscription(rules=rules)})
    payload = json.loads(result.content[0].text)
    assert payload["error"] == "bad_request"
    assert HOME_LAT_TEXT not in payload["message"]


# --------------------------------------------------------------------------------------
# the web route
# --------------------------------------------------------------------------------------
@pytest.fixture
def client(nabiz: Nabiz) -> Iterator[Any]:
    from fastapi.testclient import TestClient

    from nabiz.web.main import create_app

    with TestClient(create_app(nabiz=nabiz)) as test_client:
        yield test_client


def test_the_web_route_takes_the_subscription_in_a_post_body(client: Any, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        response = client.post("/api/alerts/check", json=subscription())
    assert response.status_code == 200, response.text
    assert response.json()["data"]["alert_count"] >= 2
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert HOME_LAT_TEXT not in logged and HOME_LON_TEXT not in logged

    # There is no GET form that could carry a coordinate in a URL.
    assert client.get("/api/alerts/check", params={"lat": HOME_LAT, "lon": HOME_LON}).status_code in {404, 405}


def test_the_web_route_refuses_a_foreign_coordinate_with_a_400(client: Any) -> None:
    response = client.post("/api/alerts/check", json=subscription(places=[{"key": "ev", "lat": 52.52, "lon": 13.4}]))
    assert response.status_code == 400
    assert "52.52" not in response.json()["message"]
