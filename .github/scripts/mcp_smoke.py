#!/usr/bin/env python3
"""MCP server smoke test: build the server that ships, offline, and read its tool contract.

The test suite calls the tool functions directly; this goes through the server a client
would launch. A tool that fails to *register* — a signature the SDK cannot turn into a
JSON schema, an import error, a decorator applied in the wrong order — fails here rather
than inside someone's editor. The worst version has already happened once: the rendering
decorator lost ``functools.wraps`` and every tool advertised ``(*args, **kwargs)``, which
the SDK then rejected on every call while every in-process test stayed green.

So each tool must advertise a JSON-schema object for its input, with its real parameter
names and never ``args``/``kwargs``, plus a description. The count is a floor, not an exact
number: a new tool is a feature, a missing one is the incident. ``tests/test_mcp_integration.py``
pins the exact names. Run by CI and by ``make smoke``; reads fixtures only, never İBB.
"""

from __future__ import annotations

import asyncio
import os
import sys

MIN_TOOLS = 12
FORBIDDEN_PARAMS = {"args", "kwargs"}


def main() -> int:
    # Forced, not defaulted: a smoke test that could reach api.ibb.gov.tr would spend a
    # rate budget shared with every other consumer of the gateway.
    os.environ["NABIZ_OFFLINE"] = "1"
    from ibb_mcp.server import build_server

    tools = asyncio.run(build_server().list_tools())
    problems: list[str] = []
    lines: list[str] = []
    for tool in sorted(tools, key=lambda t: t.name):
        # MCP 2.x names it input_schema; the wire format and older SDKs say inputSchema.
        schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None)
        properties = schema.get("properties") if isinstance(schema, dict) else None
        if not isinstance(schema, dict) or schema.get("type") != "object" or not isinstance(properties, dict):
            problems.append(f"{tool.name}: advertises no JSON-schema object for its input: {schema!r}")
            continue
        leaked = sorted(FORBIDDEN_PARAMS & set(properties))
        if leaked:
            problems.append(f"{tool.name}: advertises {leaked}; the @tool wrapper lost functools.wraps")
        if not (tool.description or "").strip():
            problems.append(f"{tool.name}: has no description for the model to read")
        lines.append(f"  {tool.name}({', '.join(properties)})")

    if len(tools) < MIN_TOOLS:
        problems.append(f"expected at least {MIN_TOOLS} tools, the server lists {len(tools)}")

    print(f"MCP server built offline and lists {len(tools)} tools:")
    print("\n".join(lines))
    for problem in problems:
        print(f"FAIL {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
