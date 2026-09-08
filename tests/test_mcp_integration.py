"""End-to-end MCP protocol tests: spawn the real server and talk to it as a client.

The unit tests exercise :func:`ibb_mcp.server.build_server` in-process, which proves the
tools work but not that the *server* works. Those are different claims, and the gap
between them has already bitten this project once: the result-rendering decorator dropped
the wrapped function's signature, so every tool advertised ``(*args, **kwargs)`` and the
SDK rejected every call. Nothing in-process noticed, because nothing in-process went
through schema validation.

So these tests do what VS Code Copilot or Claude Desktop does: launch
``python -m ibb_mcp.server`` as a subprocess, complete the initialize handshake, list the
tools and call them over stdio. If the entry point, the JSON schemas or the transport
break, this fails.

Everything runs with ``NABIZ_OFFLINE=1`` against recorded fixtures, so the suite stays
hermetic and never touches the İBB gateway.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

import pytest

mcp_client = pytest.importorskip("mcp.client.stdio", reason="mcp client SDK not installed")
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Every tool the server promises. Locked down deliberately: silently losing a tool would
#: break clients that already reference it by name.
EXPECTED_TOOLS = {
    "places_resolve",
    "ispark_find_parking",
    "ispark_typical_occupancy",
    "iett_stops_search",
    "iett_line_buses",
    "iett_next_arrivals",
    "metro_status",
    "metro_station_info",
    "traffic_index",
    "air_quality_now",
    "air_quality_forecast",
    "city_freshness",
}


def _server_params() -> StdioServerParameters:
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "NABIZ_OFFLINE": "1",
        "NABIZ_FIXTURES_DIR": str(ROOT / "tests" / "fixtures"),
        "NABIZ_PLACES_CSV": str(ROOT / "data" / "reference" / "places.csv"),
    }
    return StdioServerParameters(command=sys.executable, args=["-m", "ibb_mcp.server"], env=env)


async def _call(session: ClientSession, name: str, arguments: dict) -> dict:
    result = await session.call_tool(name, arguments)
    assert result.content, f"{name} returned no content"
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_client_completes_handshake_and_sees_every_tool():
    async with stdio_client(_server_params()) as (read, write), ClientSession(read, write) as session:
        init = await session.initialize()
        assert init.server_info.name == "istanbul-nabiz"
        assert init.server_info.version

        names = {tool.name for tool in (await session.list_tools()).tools}
        assert names == EXPECTED_TOOLS


@pytest.mark.asyncio
async def test_every_tool_advertises_a_usable_schema():
    """A tool whose schema is ``(*args, **kwargs)`` looks fine until a client calls it."""
    async with stdio_client(_server_params()) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        for tool in (await session.list_tools()).tools:
            schema = tool.input_schema or {}
            properties = set(schema.get("properties", {}))
            assert "args" not in properties and "kwargs" not in properties, (
                f"{tool.name} lost its signature: the decorator must use functools.wraps"
            )
            assert tool.description, f"{tool.name} has no description for the model to read"


@pytest.mark.asyncio
async def test_tools_return_data_with_provenance_over_the_wire():
    async with stdio_client(_server_params()) as (read, write), ClientSession(read, write) as session:
        await session.initialize()

        places = await _call(session, "places_resolve", {"query": "Kadıköy", "limit": 2})
        assert places["data"]["matches"], "the gazetteer resolved nothing for a well-known place"
        assert places["provenance"]["license"].startswith("İBB")

        station = await _call(session, "metro_station_info", {"name": "Kartal"})
        first = station["data"]["stations"][0]
        assert first["line_name"] == "M4"
        assert first["lifts"] is not None, "accessibility data is the point of this tool"

        freshness = await _call(session, "city_freshness", {})
        assert "iett" in freshness["data"]["request_budget_remaining"]


@pytest.mark.asyncio
async def test_a_bad_argument_becomes_a_readable_refusal_not_a_crash():
    """The server must never hand a model a stack trace, and never invent a fallback."""
    async with stdio_client(_server_params()) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        payload = await _call(session, "air_quality_now", {"place": "zzz-boyle-bir-yer-yok"})
        assert payload["error"] == "bad_request"
        assert payload["advice"], "the model needs to be told not to make the answer up"
