"""Citizen-facing metro and bus comparison, with optional evidence beside the estimate."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ibb_mcp.http import RateLimitExceeded, UpstreamUnavailable
from ibb_mcp.tools import Nabiz
from nabiz.console.cards import display_text, iso_now, provenance_view, unknown_provenance

compare_routes = APIRouter()

_COORDINATES = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*,\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*$")
_LIFT_TR = {
    "working": "İBB kaydında arıza yok",
    "out_of_service": "asansör arızalı (İBB kaydı)",
    "unknown": "asansör durumu doğrulanamadı",
}


def _bad_request(message: str) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": "bad_request", "message": display_text(message)})


def _journey_args(value: str, endpoint: str) -> dict[str, Any]:
    """Keep place names as names and pass a coordinate pair through the tool's checked inputs."""
    match = _COORDINATES.fullmatch(value)
    if match is None:
        return {endpoint: value}
    return {
        endpoint: value,
        f"{endpoint}_lat": float(match.group(1)),
        f"{endpoint}_lon": float(match.group(2)),
    }


def _provenance(result: Any, *, offline: bool) -> dict[str, Any]:
    stamp = getattr(result, "provenance", None)
    return provenance_view(stamp, offline=offline) if stamp is not None else unknown_provenance("nabiz_routing")


def _mode_option(mode: str, payload: Mapping[str, Any], missing: Mapping[str, Any], prov: dict[str, Any]) -> dict[str, Any]:
    labels = {"metro": "Metro / raylı sistem", "bus": "Otobüs"}
    source = payload or missing
    available = bool(payload.get("available")) and payload.get("total_minutes") is not None
    detail = payload.get("detail") or {}
    line_code = detail.get("line_code") if mode == "bus" else None
    label = f"Otobüs {line_code}" if line_code else labels[mode] if mode == "metro" else (missing.get("label") or labels[mode])
    option: dict[str, Any] = {
        "mode": mode,
        "label": display_text(str(label)),
        "available": available,
        "minutes": payload.get("total_minutes") if available else None,
        "transfers": detail.get("transfers", 0 if mode == "bus" else None) if available else None,
        "accessibility": None,
        "accessibility_note": None,
        "reliability": None,
        "reliability_note": None,
        "provenance": prov,
        "reason": display_text(str(source.get("reason") or "Bu seçenek hesaplanamadı.")) if not available else None,
    }
    if mode == "bus" and available:
        option["line_code"] = line_code
    return option


async def _add_accessibility(nabiz: Nabiz, option: dict[str, Any], detail: Mapping[str, Any]) -> None:
    station = detail.get("origin_station")
    if not station:
        option["accessibility"] = {"lift_status": "unknown", "note": _LIFT_TR["unknown"]}
        return
    try:
        result = await nabiz.accessible_alternative(station=str(station), needs=["step_free"])
    except (RateLimitExceeded, UpstreamUnavailable):
        option["accessibility_note"] = "Asansör durumu okunamadı."
        return
    data = result.data if isinstance(result.data, Mapping) else {}
    status = data.get("lift_status")
    if status not in _LIFT_TR:
        status = "unknown"
    option["accessibility"] = {"lift_status": status, "note": _LIFT_TR[status]}


async def _add_reliability(nabiz: Nabiz, option: dict[str, Any], detail: Mapping[str, Any]) -> None:
    line_code = detail.get("line_code")
    if not line_code:
        option["reliability_note"] = "Hat kodu bulunamadığı için düzenlilik okunamadı."
        return
    try:
        result = await nabiz.line_reliability(line_code=str(line_code))
    except (RateLimitExceeded, UpstreamUnavailable):
        option["reliability_note"] = "Hat düzenliliği okunamadı."
        return
    data = result.data if isinstance(result.data, Mapping) else {}
    note = result.note or data.get("note")
    option["reliability"] = {
        "available": bool(data.get("available")),
        "note": str(note) if note else "Hat düzenliliği doğrulanamadı.",
        "median_headway_min": data.get("median_headway_min"),
        "bunching_label": data.get("bunching_label"),
    }


async def _enrich(nabiz: Nabiz, options: list[dict[str, Any]], raw_by_mode: Mapping[str, Mapping[str, Any]]) -> None:
    for option in options:
        if not option["available"]:
            continue
        detail = raw_by_mode[option["mode"]].get("detail") or {}
        if option["mode"] == "metro":
            await _add_accessibility(nabiz, option, detail)
        elif option["mode"] == "bus":
            await _add_reliability(nabiz, option, detail)


@compare_routes.get("/api/compare")
async def citizen_compare(
    request: Request,
    from_value: str = Query(default="", alias="from", max_length=120),
    to_value: str = Query(default="", alias="to", max_length=120),
    needs: str = Query(default="step_free", max_length=120),
) -> Any:
    """Compare only rail and bus; an enrichment outage leaves the route estimate intact."""
    if not from_value.strip() or not to_value.strip():
        return _bad_request("Başlangıç ve varış noktalarını yazın.")
    requested = list(dict.fromkeys(item.strip() for item in needs.split(",") if item.strip()))
    unsupported = [item for item in requested if item != "step_free"]
    if unsupported:
        return _bad_request(f"Desteklenmeyen ihtiyaç: {', '.join(unsupported)}. Desteklenen: step_free.")

    arguments = _journey_args(from_value.strip(), "origin") | _journey_args(to_value.strip(), "destination")
    nabiz: Nabiz = request.app.state.nabiz
    try:
        result = await nabiz.plan_journey(**arguments)
    except ValueError as exc:
        return _bad_request(str(exc))

    data = result.data if isinstance(result.data, Mapping) else {}
    raw_by_mode = {
        str(option.get("mode")): option
        for option in data.get("options", [])
        if option.get("mode") in {"metro", "bus"}
    }
    missing_by_mode = {
        str(option.get("mode")): option
        for option in data.get("unavailable_options", [])
        if option.get("mode") in {"metro", "bus"}
    }
    offline = bool(getattr(request.app.state.settings, "offline", False))
    prov = _provenance(result, offline=offline)
    options = [_mode_option(mode, raw_by_mode.get(mode, {}), missing_by_mode.get(mode, {}), prov) for mode in ("metro", "bus")]
    await _enrich(nabiz, options, raw_by_mode)
    unavailable = [
        {"mode": option["mode"], "label": option["label"], "reason": option["reason"]}
        for option in options
        if not option["available"]
    ]
    return {
        "from": display_text(from_value.strip()),
        "to": display_text(to_value.strip()),
        "options": options,
        "unavailable": unavailable,
        "disclaimer": display_text(str(data.get("disclaimer") or "")),
        "generated_at": data.get("generated_at") or iso_now(),
    }
