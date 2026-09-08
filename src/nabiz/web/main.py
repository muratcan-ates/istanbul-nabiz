"""FastAPI service that puts the twelve Nabız tools on HTTP and serves the web UI.

Three rules shape this module.

*One process, one Nabiz.* İBB's gateway starts refusing everyone after roughly fifteen
rapid calls and İETT documents 100 requests an hour for the whole project, so the app
holds a single :class:`~ibb_mcp.tools.Nabiz` — one polite HTTP client, one shared cache —
for its whole lifetime. A per-request instance would multiply our upstream footprint by
the number of visitors and take the service down for every other consumer of this public
data, not just for us.

*The envelope is the contract.* Every endpoint returns the tool's ``ToolResult`` as
``{data, provenance, note}``, with the provenance enriched by the two fields a browser
cannot compute for itself: ``age`` (already phrased in Turkish, e.g. "17 sn önce") and
``age_seconds``. The UI shows that age on every card, which is the product promise.

*A failure is an answer, not a stack trace.* An unknown place is a 400 with the tool's own
Turkish explanation; an İBB outage is a 503 that says so. Nothing reaches the browser as a
bare 500, because "bir şeyler ters gitti" teaches the user nothing about whether the bus
is coming.
"""

from __future__ import annotations

import logging
import os
import pathlib
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as metadata_version
from typing import Any

from fastapi import Depends, FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from ibb_mcp.config import ATTRIBUTION, ATTRIBUTION_EN, Settings
from ibb_mcp.http import RateLimitExceeded, UpstreamUnavailable
from ibb_mcp.models import ToolResult
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz

log = logging.getLogger("nabiz.web")

STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"


def _version() -> str:
    """Report the installed version; a bare checkout is not installed, so fall back."""
    try:
        return metadata_version("istanbul-nabiz")
    except PackageNotFoundError:  # pragma: no cover - only in a bare checkout
        return "0.1.0"


VERSION = _version()


# --------------------------------------------------------------------------------------
# Response shaping
# --------------------------------------------------------------------------------------
def envelope(result: ToolResult) -> dict[str, Any]:
    """Render a tool result as the JSON the browser (and any HTTP client) receives.

    ``age`` is computed here rather than in the browser on purpose: the phrasing rules
    live in :meth:`ibb_mcp.models.Provenance.describe_age`, and one implementation of
    "how old is this" is one implementation to keep honest.
    """
    prov = result.provenance
    return {
        "data": jsonable_encoder(result.data),
        "provenance": {
            "source": prov.source,
            "source_url": prov.source_url,
            "observed_at": prov.observed_at.isoformat(),
            "reported_at": prov.reported_at.isoformat() if prov.reported_at else None,
            "age": prov.describe_age(),
            "age_seconds": round(prov.age_seconds, 1),
            "stale": prov.cached,
            "license": prov.license,
        },
        "note": result.note,
    }


def error_response(status: int, kind: str, message: str) -> JSONResponse:
    """A failure the UI can render as a card instead of an alert box."""
    return JSONResponse(status_code=status, content={"error": kind, "message": message})


async def call_tool(fn: Callable[..., Awaitable[ToolResult]], /, **kwargs: Any) -> Response:
    """Run one tool and translate its failures into HTTP the UI can explain.

    ``RateLimitExceeded`` is checked before ``UpstreamUnavailable`` because it is a
    subclass: it means *we* stopped, deliberately, below İETT's published ceiling, which
    is a different story from İBB being down and deserves its own status code.
    """
    try:
        result = await fn(**kwargs)
    except RateLimitExceeded as exc:
        log.warning("rate limit reached: %s", exc)
        return error_response(429, "rate_limited", f"Kendi istek bütçemiz doldu, İBB servisini yormamak için bekliyoruz: {exc}")
    except UpstreamUnavailable as exc:
        log.warning("upstream unavailable: %s", exc)
        return error_response(503, "upstream_unavailable", f"İBB servisi şu anda yanıt vermiyor: {exc}")
    except ValueError as exc:
        return error_response(400, "bad_request", str(exc))
    except Exception as exc:  # noqa: BLE001 - a broken tool must not become a bare 500
        log.exception("unhandled error in %s", getattr(fn, "__name__", fn))
        return error_response(
            500,
            "internal_error",
            f"Beklenmeyen bir hata oluştu ({type(exc).__name__}). Bu bilgi uydurulmadı, alınamadı.",
        )
    return JSONResponse(content=envelope(result))


# --------------------------------------------------------------------------------------
# App factory
# --------------------------------------------------------------------------------------
def ensure_log_handler() -> None:
    """Make the request log visible under ``uvicorn nabiz.web.main:app``.

    Uvicorn's default logging config attaches handlers to its own ``uvicorn.*`` loggers and
    leaves the root logger at WARNING, so a library logger like ``nabiz.web`` writes into
    the void — the duration line below would exist and never be seen in the shape we
    actually deploy. Adding one handler when nobody else has, and only then, keeps that
    line visible without hijacking an application that configured logging itself.
    """
    if log.handlers or logging.getLogger().handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    # Stop propagating once we own a handler. ``main()`` calls ``basicConfig`` *after* this
    # module has already been imported (``app`` is built at import time), so a propagating
    # logger would print every request line twice under ``python -m nabiz.web.main`` — once
    # from this handler and once from the root one basicConfig installs a moment later.
    log.propagate = False


def cors_origins() -> list[str]:
    """Cross-origin allow-list.

    Empty by default: the single page is served by this very app, so same-origin fetches
    need no CORS header at all. ``NABIZ_CORS_ORIGINS`` opens it up for a separately hosted
    front end (comma-separated, or ``*``).
    """
    raw = os.getenv("NABIZ_CORS_ORIGINS", "").strip()
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def get_nabiz(request: Request) -> Nabiz:
    return request.app.state.nabiz


NabizDep = Depends(get_nabiz)


def create_app(settings: Settings | None = None, nabiz: Nabiz | None = None) -> FastAPI:
    """Build the app. Pass ``nabiz`` to supply a pre-built (e.g. offline) instance.

    An injected instance is left open on shutdown: whoever built it owns its lifetime.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = app.state.nabiz is None
        if owned:
            app.state.nabiz = Nabiz(SourceContext.create(settings=app.state.settings))
        log.info("nabiz web up: version=%s offline=%s", VERSION, app.state.nabiz.settings.offline)
        try:
            yield
        finally:
            if owned:
                await app.state.nabiz.aclose()
                app.state.nabiz = None

    app = FastAPI(
        title="İstanbul Nabız",
        version=VERSION,
        description="Resmi değildir. " + ATTRIBUTION_EN,
        lifespan=lifespan,
    )
    app.state.settings = settings or (nabiz.settings if nabiz else Settings.from_env())
    app.state.nabiz = nabiz
    ensure_log_handler()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """One line per request with its duration — the cheapest useful observability."""
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        log.info("%s %s -> %s in %.1f ms", request.method, request.url.path, response.status_code, elapsed_ms)
        response.headers["X-Response-Time-ms"] = f"{elapsed_ms:.1f}"
        return response

    # -- health ----------------------------------------------------------------------
    @app.get("/healthz")
    async def healthz(app_nabiz: Nabiz = NabizDep) -> JSONResponse:
        """Liveness plus the freshness of every source, so a probe shows *why* it is sad."""
        try:
            freshness = await app_nabiz.city_freshness()
            sources = jsonable_encoder(freshness.data)
        except Exception as exc:  # noqa: BLE001 - health must answer even when broken
            log.exception("freshness unavailable")
            return JSONResponse(
                status_code=200,
                content={"status": "degraded", "version": VERSION, "sources": None, "detail": str(exc)},
            )
        return JSONResponse({"status": "ok", "version": VERSION, "sources": sources})

    # -- 1. places ---------------------------------------------------------------------
    @app.get("/api/places")
    async def api_places(q: str = Query(..., min_length=1), limit: int = Query(5, ge=1, le=20), n: Nabiz = NabizDep):
        return await call_tool(n.places_resolve, query=q, limit=limit)

    # -- 2. parking --------------------------------------------------------------------
    @app.get("/api/parking")
    async def api_parking(
        place: str = Query(..., min_length=1),
        radius_km: float = Query(1.5, gt=0, le=15),
        min_free: int = Query(1, ge=0, le=1000),
        n: Nabiz = NabizDep,
    ):
        return await call_tool(n.ispark_find_parking, place=place, radius_km=radius_km, min_free=min_free)

    @app.get("/api/parking/typical")
    async def api_parking_typical(
        park_id: int = Query(..., ge=1),
        weekday: int | None = Query(None, ge=0, le=6),
        hour: int | None = Query(None, ge=0, le=23),
        n: Nabiz = NabizDep,
    ):
        return await call_tool(n.ispark_typical_occupancy, park_id=park_id, weekday=weekday, hour=hour)

    # -- 3. buses ----------------------------------------------------------------------
    @app.get("/api/stops")
    async def api_stops(q: str = Query(..., min_length=1), limit: int = Query(8, ge=1, le=30), n: Nabiz = NabizDep):
        return await call_tool(n.iett_stops_search, query=q, limit=limit)

    @app.get("/api/buses")
    async def api_buses(line: str = Query(..., min_length=1), direction: str | None = None, n: Nabiz = NabizDep):
        return await call_tool(n.iett_line_buses, line_code=line, direction=direction)

    @app.get("/api/arrivals")
    async def api_arrivals(
        line: str = Query(..., min_length=1),
        stop: str = Query(..., min_length=1),
        limit: int = Query(3, ge=1, le=10),
        n: Nabiz = NabizDep,
    ):
        return await call_tool(n.iett_next_arrivals, line_code=line, stop=stop, limit=limit)

    # -- 4. metro ----------------------------------------------------------------------
    @app.get("/api/metro")
    async def api_metro(line: str | None = None, n: Nabiz = NabizDep):
        return await call_tool(n.metro_status, line=line)

    @app.get("/api/metro/station")
    async def api_metro_station(name: str = Query(..., min_length=1), n: Nabiz = NabizDep):
        return await call_tool(n.metro_station_info, name=name)

    # -- 5. traffic --------------------------------------------------------------------
    @app.get("/api/traffic")
    async def api_traffic(window: str = Query("now"), n: Nabiz = NabizDep):
        if window not in {"now", "24h"}:
            return error_response(400, "bad_request", "window yalnızca 'now' veya '24h' olabilir.")
        return await call_tool(n.traffic_index, window=window)

    # -- 6. air quality ----------------------------------------------------------------
    @app.get("/api/air")
    async def api_air(place: str = Query(..., min_length=1), n: Nabiz = NabizDep):
        return await call_tool(n.air_quality_now, place=place)

    @app.get("/api/air/forecast")
    async def api_air_forecast(
        place: str = Query(..., min_length=1),
        hours: int = Query(6, ge=1, le=24),
        n: Nabiz = NabizDep,
    ):
        return await call_tool(n.air_quality_forecast, place=place, horizon_hours=hours)

    # -- 7. freshness ------------------------------------------------------------------
    @app.get("/api/freshness")
    async def api_freshness(n: Nabiz = NabizDep):
        return await call_tool(n.city_freshness)

    # -- front-end configuration -------------------------------------------------------
    @app.get("/config.js")
    async def config_js() -> Response:
        """Hand the page its runtime configuration.

        ``NABIZ_MAPS_KEY`` reaches the browser by design, so treat it as public. Azure Maps
        *subscription* keys cannot be restricted by origin — only a SAS token carries an
        ``allowedOrigins`` list — so a subscription key put here is a key anyone can lift
        and spend against this subscription. Prefer a SAS token scoped to this app's
        origin, or leave the variable unset: the map then falls back to OpenStreetMap
        raster tiles, which need no credential at all.
        """
        key = os.getenv("NABIZ_MAPS_KEY", "")
        body = "\n".join(
            [
                f"window.NABIZ_MAPS_KEY = {_js_string(key)};",
                f"window.NABIZ_VERSION = {_js_string(VERSION)};",
                f"window.NABIZ_ATTRIBUTION = {_js_string(ATTRIBUTION)};",
                "",
            ]
        )
        return Response(content=body, media_type="application/javascript; charset=utf-8")

    # The static mount is last so every /api route wins the match ahead of it.
    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    else:  # pragma: no cover - only when the package is installed without its assets
        log.warning("static directory missing at %s; serving API only", STATIC_DIR)

    return app


def _js_string(value: str) -> str:
    """Escape a Python string into a JavaScript string literal for ``/config.js``."""
    import json

    return json.dumps(value, ensure_ascii=False)


app = create_app()


def main() -> None:  # pragma: no cover - process entry point
    """Run the app with uvicorn: ``python -m nabiz.web.main``."""
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(app, host=os.getenv("NABIZ_HOST", "127.0.0.1"), port=int(os.getenv("NABIZ_PORT", "8000")))


if __name__ == "__main__":  # pragma: no cover
    main()
