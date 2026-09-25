"""The lift-outage rule's public MCP schema, response, and log boundary."""

from __future__ import annotations

import json
import logging

from test_metro_equipment import offline_ctx, record, write_recordings

from ibb_mcp.server import build_server
from ibb_mcp.tools import Nabiz


def _resolve(schema: dict, node: dict) -> dict:
    ref = node.get("$ref")
    return schema["$defs"][ref.rsplit("/", 1)[-1]] if ref else node


async def test_lift_outage_is_in_the_advertised_schema(tmp_path) -> None:
    write_recordings(tmp_path, {"Asansör": [record()]}, summary=[])
    server = build_server(app=Nabiz(offline_ctx(tmp_path)))
    tool = next(item for item in await server.list_tools() if item.name == "check_alerts")
    schema = tool.input_schema
    subscription = _resolve(schema, schema["properties"]["subscription"])
    variants = subscription["properties"]["rules"]["items"]["oneOf"]
    kinds = {_resolve(schema, variant)["properties"]["kind"]["const"] for variant in variants}
    assert "lift_outage" in kinds


async def test_check_alerts_carries_a_lift_alert_end_to_end(tmp_path) -> None:
    write_recordings(tmp_path, {"Asansör": [record()]}, summary=[])
    server = build_server(app=Nabiz(offline_ctx(tmp_path)))
    result = await server.call_tool(
        "check_alerts",
        {"subscription": {"rules": [{"kind": "lift_outage", "stations": ["Kartal"]}]}},
    )
    payload = json.loads(result.content[0].text)
    alert = payload["data"]["alerts"][0]
    assert alert["kind"] == "lift_outage"
    assert alert["citations"]
    assert alert["uncertainty"]


async def test_lift_alert_logs_no_station_name(tmp_path, caplog) -> None:
    write_recordings(tmp_path, {"Asansör": [record()]}, summary=[])
    server = build_server(app=Nabiz(offline_ctx(tmp_path)))
    with caplog.at_level(logging.DEBUG):
        await server.call_tool(
            "check_alerts",
            {"subscription": {"rules": [{"kind": "lift_outage", "stations": ["Kartal"]}]}},
        )
    logged = "\n".join(item.getMessage() for item in caplog.records)
    assert "Kartal" not in logged

