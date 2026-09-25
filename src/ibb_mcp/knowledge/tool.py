"""MCP tool contract for local IBB service-page search."""

from __future__ import annotations

import datetime as dt
import json
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from ibb_mcp.models import Provenance, ToolResult, utcnow

from .answer import assess_evidence
from .embed import Embedder
from .retrieve import search
from .store import KnowledgeStore

TOOL_NAME = "ibb_services_search"
DESCRIPTION = "İstanbul'daki resmî hizmet sayfalarında arama yapar ve kaynak cümlelerini bağlantılarıyla döndürür."
SCHEMA = {
    "name": TOOL_NAME,
    "description": DESCRIPTION,
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "maxLength": 200, "description": "Aranacak hizmet sorusu"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}


async def ibb_services_search(
    query: Annotated[str, Field(max_length=200)],
    limit: Annotated[int, Field(ge=1, le=10)] = 5,
    *,
    store: KnowledgeStore,
    embedder: Embedder | None,
) -> ToolResult:
    """İstanbul'daki hizmet kaynaklarında ara; her sonuçta alıntı, bağlantı ve alınma tarihi vardır."""
    hits = await search(store, query, embedder=embedder, limit=limit)
    latest = max((dt.datetime.fromisoformat(hit.fetched_at.replace("Z", "+00:00")) for hit in hits), default=None)
    source_url = hits[0].url if hits else "data/knowledge/sources.txt"
    evidence = assess_evidence(hits, query=query)
    return ToolResult(
        data={
            "query": query,
            "hits": [hit.to_dict() for hit in hits],
            "evidence": {
                "level": evidence.level,
                "best_cosine": evidence.best_cosine,
                "best_bm25": evidence.best_bm25,
                "coverage": evidence.coverage,
            },
        },
        provenance=Provenance(
            source="local:knowledge",
            source_url=source_url,
            reported_at=latest or utcnow(),
            license="Kurum web sayfası; alıntı, kaynak bağlantısıyla",
        ),
        note=None if evidence.level == "sufficient" else "Yerel bilgi dizininde doğrulanabilir eşleşme bulunamadı.",
    )


_search_impl = ibb_services_search


def register_mcp_tool(mcp: MCPServer, *, store: KnowledgeStore, embedder: Embedder | None) -> None:
    """Advertise the search tool without importing the transport composition root."""
    run_search = _search_impl

    @mcp.tool()
    async def ibb_services_search(
        query: Annotated[str, Field(max_length=200)],
        limit: Annotated[int, Field(ge=1, le=10)] = 5,
    ) -> str:
        """İstanbul'daki hizmet kaynaklarında ara; her sonuçta alıntı, bağlantı ve alınma tarihi vardır."""
        result = await run_search(query, limit, store=store, embedder=embedder)
        return json.dumps(
            {"data": result.data, "provenance": result.provenance.model_dump(mode="json"), "note": result.note},
            ensure_ascii=False,
        )
