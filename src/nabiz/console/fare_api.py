"""Two no-store endpoints for the source-backed fare catalogue and pattern estimate."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from nabiz.console.fare_calc import estimate, parse_pattern
from nabiz.console.fare_sources import DISCLAIMER, NOTICE, FareCatalogError, load_fare_catalog, public_fare_catalog
from nabiz.console.operator import port_problem

fare_routes = APIRouter()
_MAX_BODY = 2048
_UNAVAILABLE = "Ücret kataloğu bu sunucuda hazır değil; kurumun resmî sayfasına ya da 153'e başvurun."


def _problem(status: int, code: str, message: str, **extra: Any) -> JSONResponse:
    response = port_problem(status, code, message)
    response.headers["Cache-Control"] = "no-store"
    if extra:
        body = {"error": code, "message": message, **extra}
        response = JSONResponse(status_code=status, content=body, headers={"Cache-Control": "no-store"})
    return response


@fare_routes.get("/api/fare/catalog")
async def fare_catalog(lang: str = "tr") -> JSONResponse:
    if lang not in {"tr", "en"}:
        return _problem(400, "invalid_lang", "Dil seçimi geçersiz.")
    try:
        catalog = load_fare_catalog()
        payload = public_fare_catalog(catalog, lang)
    except FareCatalogError:
        return _problem(503, "fare_catalog_unavailable", _UNAVAILABLE)
    return JSONResponse(
        status_code=200,
        content={**payload, "notice": NOTICE, "disclaimer": DISCLAIMER},
        headers={"Cache-Control": "no-store"},
    )


@fare_routes.post("/api/fare/estimate")
async def fare_estimate(request: Request) -> JSONResponse:
    length = request.headers.get("content-length", "")
    try:
        if length and int(length) > _MAX_BODY:
            return _problem(413, "pattern_too_large", "Desen isteği çok büyük.")
    except ValueError:
        return _problem(400, "invalid_pattern", "Desen isteği geçersiz.", fields=[])
    chunks = []
    body_size = 0
    async for chunk in request.stream():
        body_size += len(chunk)
        if body_size > _MAX_BODY:
            return _problem(413, "pattern_too_large", "Desen isteği çok büyük.")
        chunks.append(chunk)
    raw = b"".join(chunks)
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _problem(400, "invalid_pattern", "Deseni gözden geçirin.", fields=[])
    try:
        catalog = load_fare_catalog()
    except FareCatalogError:
        return _problem(503, "fare_catalog_unavailable", _UNAVAILABLE)
    pattern, errors = parse_pattern(data, catalog)
    if pattern is None:
        return _problem(400, "invalid_pattern", "Deseni gözden geçirin.", fields=errors)
    result = estimate(pattern, catalog)
    return JSONResponse(
        status_code=200,
        content={"estimate": result, "notice": NOTICE, "disclaimer": DISCLAIMER},
        headers={"Cache-Control": "no-store"},
    )
