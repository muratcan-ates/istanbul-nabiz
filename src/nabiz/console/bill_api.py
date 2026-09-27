"""Read-only source catalogue endpoint for the device-side bill explainer."""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from nabiz.console.bill_helper import (
    BILL_ITEMS_PATH,
    BillCatalogError,
    load_bill_catalog,
    public_bill_catalog,
    validate_bill_catalog,
)
from nabiz.console.operator import port_problem

bill_routes = APIRouter()
UNAVAILABLE = "Fatura açıklama kataloğu bu sunucuda hazır değil; kurumunuzun resmî sayfasına ya da 153'e başvurun."


@bill_routes.get("/api/bill/catalog")
def bill_catalog(lang: str = Query(default="tr")) -> JSONResponse:
    """Return the source catalogue; no bill entry is accepted or recorded here."""
    if lang not in {"tr", "en"}:
        return port_problem(400, "invalid_lang", "Dil seçimi tr ya da en olmalı.")
    try:
        catalog = load_bill_catalog(BILL_ITEMS_PATH)
        problems = validate_bill_catalog(catalog)
        if problems:
            raise BillCatalogError("Fatura açıklama kataloğu doğrulanamadı.")
        response = JSONResponse(content=public_bill_catalog(catalog, lang))
        response.headers["Cache-Control"] = "no-store"
        return response
    except (BillCatalogError, OSError, ValueError):
        response = port_problem(503, "bill_catalog_unavailable", UNAVAILABLE)
        response.headers["Cache-Control"] = "no-store"
        return response
