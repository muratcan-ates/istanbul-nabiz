"""The İBB Open Data catalogue on the citizen page: ``GET /api/datasets`` and the chat's dataset citations.

Both read ``Nabiz.ibb_datasets_search`` (the local catalogue file, ``ibb_mcp.catalog``): no request
reaches İBB when a visitor searches, and every answer says how old the catalogue copy is. Without a
copy the route answers 503 ``catalog_missing`` with a sentence the page shows as it is, never an
empty list that would read as "İBB publishes nothing about this".

The query and the category go to the facade and nowhere else: they are not logged.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import APIRouter, Query, Request

from nabiz.console.operator import port_problem

open_data_routes = APIRouter()

#: The 503 the page shows when this server holds no catalogue copy.
CATALOG_MISSING = (
    "İBB Açık Veri kataloğunun kaydı bu sunucuda yok. Veri setlerine https://data.ibb.gov.tr adresinden bakabilirsin."
)
#: The citation source of a dataset (the page's label: "İBB Açık Veri kataloğu").
CATALOG_SOURCE = "ibb_catalog"


@open_data_routes.get("/api/datasets")
async def datasets(
    request: Request,
    q: str = Query("", max_length=200),
    category: str = Query("", max_length=60),
    limit: int = Query(8, ge=1, le=20),
) -> Any:
    """Datasets matching ``q`` and/or ``category``; neither lists the most recently updated."""
    try:
        result = await request.app.state.nabiz.ibb_datasets_search(query=q, category=category or None, limit=limit)
    except ValueError as exc:
        return port_problem(400, "bad_request", str(exc))
    if not result.data["catalog"]["available"]:
        return port_problem(503, "catalog_missing", CATALOG_MISSING)
    provenance = result.provenance
    return {
        **result.data,
        "note": result.note,
        "provenance": {
            "source": CATALOG_SOURCE,
            "url": provenance.source_url,
            "observed_at": provenance.observed_at.isoformat() if provenance.observed_at else None,
            "age_s": None if provenance.unread else int(provenance.age_seconds),
            "mode": "recorded",
        },
    }


def dataset_citations(tool_calls: Iterable[Any]) -> list[dict[str, Any]]:
    """One citation per dataset a chat answer named, so each gets its link, publisher and last update."""
    cited: list[dict[str, Any]] = []
    for call in tool_calls:
        payload = getattr(call, "payload", None)
        if getattr(call, "name", None) != "ibb_datasets_search" or not payload:
            continue
        data = payload.get("data") or {}
        captured = (data.get("catalog") or {}).get("captured_at_utc")
        cited += [
            {
                "source": CATALOG_SOURCE,
                "title": hit.get("title"),
                "institution": hit.get("organization") or "İBB Açık Veri",
                "url": hit.get("url"),
                "source_updated_at": hit.get("last_updated"),
                "fetched_at": captured,
            }
            for hit in data.get("datasets") or []
        ]
    return cited
