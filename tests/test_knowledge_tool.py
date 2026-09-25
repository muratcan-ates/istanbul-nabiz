from __future__ import annotations

import asyncio

from mcp.server.mcpserver import MCPServer
from test_knowledge_store import seed_page

from ibb_mcp.knowledge import open_from_env
from ibb_mcp.knowledge.embed import HashingEmbedder
from ibb_mcp.knowledge.store import KnowledgeStore
from ibb_mcp.knowledge.tool import SCHEMA, TOOL_NAME, ibb_services_search, register_mcp_tool


def test_tool_result_has_provenance(tmp_path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    seed_page(store, "Su aboneliği başvurusu resmî kaynakta açıklanır.")
    result = asyncio.run(ibb_services_search("su aboneliği", store=store, embedder=HashingEmbedder()))
    assert result.provenance.source == "local:knowledge"
    assert result.provenance.source_url.startswith("https://")
    assert result.data["hits"] and result.data["evidence"]["level"] == "sufficient"


def test_mcp_registration_advertises_schema(tmp_path) -> None:
    server = MCPServer("knowledge-test", "0.1")
    register_mcp_tool(server, store=KnowledgeStore(tmp_path / "knowledge.db"), embedder=None)
    tools = asyncio.run(server.list_tools())
    tool = next(item for item in tools if item.name == TOOL_NAME)
    assert tool.input_schema["properties"]["query"]["maxLength"] == SCHEMA["parameters"]["properties"]["query"]["maxLength"]


def test_open_from_env_returns_none_without_a_db(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NABIZ_KNOWLEDGE_DB", str(tmp_path / "missing.db"))
    assert open_from_env() == (None, None)
