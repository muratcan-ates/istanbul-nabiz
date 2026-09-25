"""HTTP routes for local service-source search and evidence-backed answers."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ibb_mcp.knowledge import answer, open_from_env, search
from nabiz.console.operator import port_problem

knowledge_routes = APIRouter()
#: The 503 the page shows when this server has no service-page index built.
INDEX_MISSING = "Hizmet sayfası dizini bu sunucuda kurulu değil; şimdilik 153 Çözüm Merkezi'ne ya da ilgili resmî sayfaya bak."


def _index(request: Request):
    store = getattr(request.app.state, "knowledge_store", None)
    embedder = getattr(request.app.state, "knowledge_embedder", None)
    if store is None:
        store, embedder = open_from_env()
        request.app.state.knowledge_store = store
        request.app.state.knowledge_embedder = embedder
    return store, embedder


@knowledge_routes.get("/api/knowledge/search")
async def knowledge_search(request: Request, q: str = "", limit: int = 5):
    """Return local hybrid-search hits in the stable public schema."""
    if not q.strip() or len(q) > 200 or not 1 <= limit <= 10:
        return port_problem(400, "invalid_query", "Arama metni 1 ile 200 karakter, limit 1 ile 10 arasında olmalı.")
    store, embedder = _index(request)
    if store is None:
        return port_problem(503, "knowledge_index_missing", INDEX_MISSING)
    hits = await search(store, q, embedder=embedder, limit=limit)
    return {
        "hits": [hit.to_dict() for hit in hits],
        "mode": "hybrid" if embedder is not None and store.fts_available else "fts",
        "index_built_at": store.index_built_at(),
    }


@knowledge_routes.post("/api/knowledge/ask")
async def knowledge_ask(request: Request):
    """Answer a short question with source citations from the local index."""
    try:
        body = await request.json()
    except Exception:
        return port_problem(400, "invalid_body", "İstek gövdesi okunamadı.")
    question = body.get("question") if isinstance(body, dict) else None
    lang = body.get("lang", "tr") if isinstance(body, dict) else "tr"
    if (
        not isinstance(question, str)
        or not question.strip()
        or len(question) > 200
        or not isinstance(lang, str)
        or lang not in {"tr", "en"}
    ):
        return port_problem(400, "invalid_question", "Soru 1 ile 200 karakter arasında olmalı; dil tr ya da en.")
    store, embedder = _index(request)
    if store is None:
        return port_problem(503, "knowledge_index_missing", INDEX_MISSING)
    result = await answer(question, store=store, embedder=embedder)
    return result.to_dict()
