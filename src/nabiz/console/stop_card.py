"""Data and routes for a script-free public stop card.

Integrator handoff: include ``stop_card_router`` after ``operator_routes`` and before the
static mount in ``app.py``; the integration edits are listed in ``RAPOR-E12.md``.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import re
from contextlib import suppress
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from nabiz.agent.minutes import UNVERIFIED
from nabiz.console.arrival import arrival_view
from nabiz.console.brief import Freshness
from nabiz.console.cards import env_seconds, provenance_view, unknown_provenance
from nabiz.console.operator import port_problem
from nabiz.console.ports import UnwiredStepFree
from nabiz.console.stop_card_html import render_code_form, render_print_card, render_stop_missing, render_stop_page

log = logging.getLogger("nabiz.console.stop_card")

STOP_CODE = re.compile(r"^\d{1,9}$")
MAX_ARRIVAL_LINES = 3
METRO_NEAR_KM = 0.3
STOP_CARD_WAIT_DEFAULT_S = 4
NOT_FOUND = "Durak bulunamadı."
NO_GTFS = "Durak bulunamadı. Bu sunucuda durak listesi yüklü değil."

stop_card_router = APIRouter()
_background_arrivals: set[asyncio.Task[Any]] = set()


class StopCardMissing(LookupError):
    """A stop code is invalid, absent, or cannot be resolved without a GTFS index."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def public_base(request: Request) -> str:
    """Use a configured public HTTPS origin for printed QR codes when one is available."""
    configured = os.getenv("NABIZ_PUBLIC_BASE_URL", "").strip()
    if configured.startswith("https://"):
        return configured.rstrip("/")
    return str(request.base_url).rstrip("/")


def age_text(provenance: dict[str, Any] | None) -> str:
    """Format source age with the same thresholds as the other citizen cards."""
    if not provenance:
        return "yaşı bilinmiyor"
    if provenance.get("mode") == "recorded":
        return "kayıtlı veri"
    age = provenance.get("age_s")
    if not isinstance(age, (int, float)) or isinstance(age, bool):
        return "yaşı bilinmiyor"
    seconds = max(0, int(age))
    if seconds < 90:
        return f"{seconds} sn önce"
    if seconds < 5400:
        return f"{seconds // 60} dk önce"
    if seconds < 172800:
        return f"{seconds // 3600} sa önce"
    return f"{seconds // 86400} gün önce"


def _finish_background_task(task: asyncio.Task[Any]) -> None:
    """Retrieve a detached task's exception and release its reference when it finishes."""
    with suppress(asyncio.CancelledError):
        task.exception()
    _background_arrivals.discard(task)


def _ordered_lines(lines: list[str], hat: str | None) -> list[str]:
    if hat not in lines:
        return lines
    return [hat, *(line for line in lines if line != hat)]


def _unverified_line(line: str) -> dict[str, Any]:
    return {"line": line, "minutes": None, "display": UNVERIFIED, "provenance": unknown_provenance("iett")}


async def _arrival_rows(nabiz: Any, lines: list[str], code: str, *, fresh: Freshness) -> list[dict[str, Any]]:
    if not lines:
        return []
    queried = lines[:MAX_ARRIVAL_LINES]
    tasks = {
        asyncio.create_task(
            arrival_view(nabiz, line, code, stale_after_s=fresh.arrival_stale_after_s, offline=fresh.offline)
        ): line
        for line in queried
    }
    done, pending = await asyncio.wait(tasks, timeout=env_seconds("NABIZ_STOP_CARD_WAIT_S", STOP_CARD_WAIT_DEFAULT_S))
    rows: list[dict[str, Any]] = []
    for line in queried:
        task = next(task for task, task_line in tasks.items() if task_line == line)
        if task in pending:
            _background_arrivals.add(task)
            task.add_done_callback(_finish_background_task)
            rows.append(_unverified_line(line))
            continue
        if task not in done:
            rows.append(_unverified_line(line))
            continue
        try:
            arrival = task.result()
        except Exception:
            rows.append(_unverified_line(line))
            continue
        rows.append(
            {
                "line": line,
                "minutes": arrival.get("minutes"),
                "display": arrival.get("display"),
                "provenance": arrival.get("provenance"),
            }
        )
    rows.extend({"line": line, "minutes": None, "display": None, "provenance": None} for line in lines[MAX_ARRIVAL_LINES:])
    return rows


async def _nearby_rail(nabiz: Any, step_free: Any, stop: dict[str, Any]) -> dict[str, Any] | None:
    lat, lon = stop.get("lat"), stop.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    try:
        places = nabiz.places.nearest(lat, lon, kind="metro_station", limit=1)
    except Exception as exc:
        log.info("nearby rail lookup unavailable (%s)", type(exc).__name__)
        return None
    if not places or places[0].distance_km is None or places[0].distance_km > METRO_NEAR_KM:
        return None
    place = places[0]
    distance_m = round(place.distance_km * 1000)
    rail_lines: list[str] = []
    try:
        rail = await nabiz.accessible_alternative(place.name, ["step_free"])
        rail_lines = [str(line) for line in (rail.data or {}).get("lines") or []]
    except Exception as exc:
        log.info("rail line labels unavailable (%s)", type(exc).__name__)
    try:
        view = await step_free.alternative(place.name, ["step_free"])
    except Exception as exc:
        log.info("step-free port unavailable (%s)", type(exc).__name__)
        view = await UnwiredStepFree().alternative(place.name, ["step_free"])
    status = view.get("lift_status")
    if status not in {"working", "out_of_service", "unknown"}:
        status = "unknown"
    provenance = view.get("provenance")
    lift_line = {
        "working": f"İBB kaydında arıza yok · {age_text(provenance)}",
        "out_of_service": f"Asansör arızalı (İBB kaydı) · {age_text(provenance)}",
        "unknown": "Asansör durumu doğrulanamadı",
    }[status]
    alternative = view.get("alternative") if status == "out_of_service" else None
    ask_href = None
    if alternative:
        question = f"{place.name} istasyonunda asansör arızalı. Adımsız nasıl giderim?"
        ask_href = f"/?q={quote(question, safe='')}&needs=step_free"
    return {
        "station": place.name,
        "lines": rail_lines,
        "distance_m": distance_m,
        "lift_status": status,
        "lift_line": lift_line,
        "alternative": alternative,
        "ask_href": ask_href,
        "operator_approved": bool(view.get("operator_approved")),
        "stale": bool(view.get("stale")),
        "provenance": provenance or unknown_provenance("metro_equipment"),
    }


async def stop_card_data(
    nabiz: Any,
    step_free: Any,
    code: str,
    *,
    fresh: Freshness,
    base_url: str,
    hat: str | None = None,
) -> dict[str, Any]:
    """Build the shared page and JSON representation from the Nabız facade."""
    if not STOP_CODE.fullmatch(code):
        raise StopCardMissing(NOT_FOUND)
    try:
        result = await nabiz.iett_stops_search(code, limit=1)
    except Exception as exc:
        log.info("GTFS stop lookup unavailable (%s)", type(exc).__name__)
        raise StopCardMissing(NO_GTFS) from exc
    stops = (result.data or {}).get("stops") or []
    if not stops:
        raise StopCardMissing(NOT_FOUND)
    stop = stops[0]
    if not isinstance(stop, dict) or stop.get("stop_code") != code:
        raise StopCardMissing(NOT_FOUND)
    lines_known = True
    try:
        index = await nabiz.stop_routes()
        lines = list(index.lines_serving(code))
        lines_known = index.stop_count > 0
    except Exception as exc:
        log.info("GTFS stop routes unavailable (%s)", type(exc).__name__)
        lines, lines_known = [], False
    ordered = _ordered_lines(lines, hat)
    arrivals = await _arrival_rows(nabiz, ordered, code, fresh=fresh)
    return {
        "code": code,
        "name": stop.get("name") or code,
        "direction": (stop.get("description") or "").removeprefix("direction: ").strip() or None,
        "lat": stop.get("lat"),
        "lon": stop.get("lon"),
        "lines_known": lines_known,
        "lines": arrivals,
        "metro": await _nearby_rail(nabiz, step_free, stop),
        "offline": fresh.offline,
        "url": f"{base_url}/d/{code}",
        "links": {"page": f"/d/{code}", "print": f"/d/{code}/yazdir", "qr": f"/d/{code}/qr.svg"},
        "stop_provenance": provenance_view(result.provenance, offline=fresh.offline),
    }


def load_segno() -> Any | None:
    """Load the optional QR encoder selected by the owner's K10 decision."""
    try:
        import segno
    except ImportError:
        return None
    return segno


def qr_svg(url: str) -> str | None:
    """Create a high-contrast SVG QR code, or return ``None`` when segno is unavailable."""
    segno = load_segno()
    if segno is None:
        return None
    code = url.rstrip("/").rsplit("/", 1)[-1]
    qr = segno.make_qr(url, error="m")
    buffer = io.BytesIO()
    qr.save(
        buffer,
        kind="svg",
        scale=4,
        border=4,
        xmldecl=False,
        dark="#000000",
        light="#ffffff",
        title=f"Durak {code} bağlantısı",
    )
    return buffer.getvalue().decode("utf-8")


def _route_data(request: Request, code: str, hat: str | None = None) -> dict[str, Any]:
    state = request.app.state
    return stop_card_data(
        state.nabiz,
        state.ports.step_free,
        code,
        fresh=state.fresh,
        base_url=public_base(request),
        hat=hat,
    )


@stop_card_router.get("/api/stop-card/{code}")
async def stop_card_json(request: Request, code: str, hat: str | None = None) -> JSONResponse:
    try:
        data = await _route_data(request, code, hat)
    except StopCardMissing as exc:
        return port_problem(404, "not_found", exc.message)
    return JSONResponse(data)


@stop_card_router.get("/d", response_class=HTMLResponse)
async def stop_card_form(kod: str | None = None) -> Response:
    if kod and STOP_CODE.fullmatch(kod):
        return RedirectResponse(f"/d/{kod}", status_code=303)
    return HTMLResponse(render_code_form("Durak kodu 1 ile 9 arası rakamdan oluşur." if kod else None))


@stop_card_router.get("/d/{code}/qr.svg")
async def stop_card_qr(request: Request, code: str) -> Response:
    try:
        await _route_data(request, code)
    except StopCardMissing as exc:
        return Response(exc.message, status_code=404, media_type="text/plain")
    url = f"{public_base(request)}/d/{code}"
    svg = qr_svg(url)
    if svg is None:
        return Response(
            f"QR üretici kurulu değil.\n{url}\n",
            media_type="text/plain",
            headers={"X-Nabiz-QR": "unavailable"},
        )
    return Response(svg, media_type="image/svg+xml")


@stop_card_router.get("/d/{code}/yazdir", response_class=HTMLResponse)
async def stop_card_print(request: Request, code: str) -> HTMLResponse:
    try:
        data = await _route_data(request, code)
    except StopCardMissing as exc:
        return HTMLResponse(render_stop_missing(exc.message), status_code=404)
    return HTMLResponse(render_print_card(data, qr_svg(data["url"])))


@stop_card_router.get("/d/{code}", response_class=HTMLResponse)
async def stop_card_page(request: Request, code: str, hat: str | None = None) -> HTMLResponse:
    try:
        data = await _route_data(request, code, hat)
    except StopCardMissing as exc:
        return HTMLResponse(render_stop_missing(exc.message), status_code=404)
    return HTMLResponse(render_stop_page(data))
