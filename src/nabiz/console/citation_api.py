"""Read-only endpoint that exposes sentence-to-source evidence details."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ibb_mcp.knowledge import answer, open_from_env
from ibb_mcp.knowledge.citation_map import citation_map, labels
from nabiz.console.knowledge_api import INDEX_MISSING
from nabiz.console.operator import port_problem

citation_routes = APIRouter()


def _index(request: Request):
    store = getattr(request.app.state, "knowledge_store", None)
    embedder = getattr(request.app.state, "knowledge_embedder", None)
    if store is None:
        store, embedder = open_from_env()
        request.app.state.knowledge_store = store
        request.app.state.knowledge_embedder = embedder
    return store, embedder


@citation_routes.post("/api/knowledge/citations")
async def knowledge_citations(request: Request):
    """Return the local answer with its evidence map; sensitivity is supplied as false here."""
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
    result = await answer(question, store=store, embedder=embedder, sensitive=False)
    return {**result.to_dict(), "citation_map": citation_map(result, store=store), "labels": labels(lang)}
