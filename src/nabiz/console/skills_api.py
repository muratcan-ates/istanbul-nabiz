"""Read-only HTTP routes for the course discovery module."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ibb_mcp.config import REPO_ROOT
from nabiz.console.cards import display_text
from nabiz.console.skills_match import MODES, bio_card, checklist, load_reference, match, validate_choices

MAX_BODY_BYTES = 2048
skills_routes = APIRouter()


def _bad_request(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": "bad_request", "message": display_text(message)})


def _clean(value: Any) -> str:
    return display_text(value.strip()) if isinstance(value, str) else ""


def _official_url(value: Any) -> str | None:
    return value if isinstance(value, str) and value.startswith("https://enstitu.ibb.istanbul/") else None


def _call_number() -> str:
    try:
        value = json.loads((REPO_ROOT / "data" / "agencies.json").read_text(encoding="utf-8"))
        return str(value.get("call") or "")
    except (OSError, json.JSONDecodeError, AttributeError):
        return ""


def _options(ref: Any) -> dict[str, Any]:
    data = ref.data
    areas = [
        {
            "name": _clean(row.get("name")), "branch": _clean(row.get("branch")),
            "programs": row.get("programs"), "url": _official_url(row.get("url")),
        }
        for row in data.get("areas", [])
        if isinstance(row, dict) and _clean(row.get("name")) and _official_url(row.get("url"))
    ]
    source = {
        "name": _clean(data.get("source")) or "Enstitü İstanbul İSMEK",
        "retrieved_at": _clean(data.get("retrieved_at")) or None,
        "license": _clean(data.get("license")),
        "programs_url": _official_url(data.get("programs_url")) or "https://enstitu.ibb.istanbul/",
        "centers_url": _official_url(data.get("centers_url")) or "https://enstitu.ibb.istanbul/",
    }
    bio = bio_card()
    return {
        "available": ref.available, "reason": ref.reason,
        "branches": [_clean(item) for item in data.get("branches", []) if isinstance(item, str)],
        "areas": areas, "districts": [_clean(item) for item in data.get("districts", []) if isinstance(item, str)],
        "modes": list(MODES), "times": [_clean(item) for item in data.get("times", []) if isinstance(item, str)],
        "source": source, "jobs_status": bio, "disclaimer": "Resmî İBB hizmeti değildir.", "call": _call_number(),
    }


@skills_routes.get("/api/skills/options")
async def skills_options() -> dict[str, Any]:
    return _options(load_reference())


@skills_routes.post("/api/skills/match")
async def skills_match(request: Request) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    content_length = request.headers.get("content-length", "")
    if content_length.isdigit() and int(content_length) > MAX_BODY_BYTES:
        return JSONResponse(
            status_code=413,
            content={"error": "too_large", "message": "İstek gövdesi 2 KB sınırını aşıyor."},
            headers=headers,
        )
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            return JSONResponse(
                status_code=413,
                content={"error": "too_large", "message": "İstek gövdesi 2 KB sınırını aşıyor."},
                headers=headers,
            )
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse(
            status_code=400, content={"error": "bad_request", "message": "Geçerli bir JSON isteği gönderin."}, headers=headers
        )
    if not isinstance(payload, dict):
        return JSONResponse(
            status_code=400,
            content={"error": "bad_request", "message": "Seçim alanlarını içeren bir JSON nesnesi gönderin."},
            headers=headers,
        )
    ref = load_reference()
    if not ref.available:
        content = {**match(ref, validate_choices({}, ref)), "disclaimer": "Resmî İBB hizmeti değildir."}
        return JSONResponse(content=content, headers=headers)
    try:
        choices = validate_choices(payload, ref)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": "bad_request", "message": display_text(str(exc))}, headers=headers)
    return JSONResponse(content={**match(ref, choices), "disclaimer": "Resmî İBB hizmeti değildir."}, headers=headers)


@skills_routes.get("/api/skills/checklist")
async def skills_checklist(code: str = "") -> Any:
    result = checklist(load_reference(), code)
    if result is None:
        return JSONResponse(status_code=404, content={"error": "not_found", "message": "Program katalogda bulunamadı."})
    return result
