"""MCP tool contract for local IBB service-page search."""

from __future__ import annotations

import datetime as dt
import json
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from ibb_mcp.models import Provenance, ToolResult, utcnow

from .answer import assess_evidence, evidence_thresholds
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
    evidence = assess_evidence(hits, query=query, **evidence_thresholds())
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

#: What the facade answers when this server has no index: a named gap, never an empty "no match".
INDEX_MISSING_NOTE = (
    "Yerel hizmet sayfası dizini bu sunucuda kurulu değil; hizmet sayfası araması yapılamadı. "
    "Kaynak uydurma, kullanıcıya bu aramanın şu an yapılamadığını söyle."
)


async def search_local_index(query: str, limit: int = 5, *, offline: bool = False) -> ToolResult:
    """The ``Nabiz.ibb_services_search`` body: open the index the environment names and search it.

    Offline, the optional embedding endpoint is never called (lexical search only), so an
    offline run makes no network request at all. A missing index is reported, not hidden.
    """
    if not isinstance(query, str) or not query.strip() or len(query) > 200:
        raise ValueError("Arama metni 1 ile 200 karakter arasında olmalı.")
    if not 1 <= int(limit) <= 10:
        raise ValueError("limit 1 ile 10 arasında olmalı.")
    from . import open_from_env

    store, embedder = open_from_env()
    if store is None:
        return ToolResult(
            data={"query": query, "hits": [], "evidence": {"level": "index_missing"}},
            provenance=Provenance(
                source="local:knowledge",
                source_url="data/knowledge/sources.txt",
                license="Kurum web sayfası; alıntı, kaynak bağlantısıyla",
            ),
            note=INDEX_MISSING_NOTE,
        )
    return await _search_impl(query, int(limit), store=store, embedder=None if offline else embedder)


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
