"""The product app's factory, its process entry point and the citizen routes.

``build_console_app`` wires one process: one :class:`~ibb_mcp.tools.Nabiz` facade (one polite
HTTP client and one cache for every visitor, DECISIONS #3), one model configuration, one spend
guard and the ports. :func:`main` is the only place that reads the repository's ``.env``, so
tests and imports never pick up a real key.

The request log writes method, path, status and duration: never a query string (it can hold
saved stations and needs) and never a body (it holds the question).
"""

from __future__ import annotations

import logging
import os
import pathlib
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ibb_mcp.config import ATTRIBUTION_EN, Settings
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.console.arrival import arrival_stale_after_s, arrival_view
from nabiz.console.brief import Freshness, build_brief, split_csv
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.cards import CARD_STALE_DEFAULT_S, env_seconds
from nabiz.console.chat import ChatRequest, ChatService
from nabiz.console.envfile import load_env_file
from nabiz.console.operator import operator_routes, port_problem
from nabiz.console.policy import functional_needs
from nabiz.console.ports import Ports, UnwiredStepFree

log = logging.getLogger("nabiz.console")

CONSOLE_STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"
DEFAULT_CONSOLE_PORT = 8090

#: Same-origin only: the page is vanilla JS served from ``static/``. A page that needs another
#: origin (a map's tiles) widens this here, with the reason, not in the page.
CONSOLE_HEADERS = {
    "Content-Security-Policy": "; ".join(
        [
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data:",
            "connect-src 'self'",
            "font-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ]
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

citizen_routes = APIRouter()


@citizen_routes.get("/healthz")
async def console_health(request: Request) -> dict[str, Any]:
    """Liveness, and which author the chat will use next: the model, the local model or the rules."""
    state = request.app.state
    config: llm.LlmConfig = state.chat.config
    return {
        "status": "ok",
        "offline": state.settings.offline,
        "model": {
            "provider": config.provider,
            "configured": llm.available(config),
            "within_budget": state.guard.allows(config.provider),
        },
    }


@citizen_routes.get("/api/brief")
async def citizen_brief(request: Request, stations: str = "", lines: str = "", needs: str = "") -> dict[str, Any]:
    state = request.app.state
    return await build_brief(
        state.nabiz,
        state.ports.step_free,
        stations=split_csv(stations),
        lines=split_csv(lines),
        needs=functional_needs(split_csv(needs, limit=16)),
        fresh=state.fresh,
    )


@citizen_routes.get("/api/arrival")
async def citizen_arrival(
    request: Request,
    line: str = Query(..., min_length=1, max_length=12),
    stop: str = Query(..., min_length=1, max_length=80),
) -> Any:
    fresh: Freshness = request.app.state.fresh
    try:
        return await arrival_view(
            request.app.state.nabiz, line, stop, stale_after_s=fresh.arrival_stale_after_s, offline=fresh.offline
        )
    except ValueError as exc:
        return port_problem(400, "bad_request", str(exc))


@citizen_routes.get("/api/alternative")
async def citizen_alternative(
    request: Request,
    station: str = Query(..., min_length=1, max_length=80),
    needs: str = "step_free",
) -> Any:
    wanted = functional_needs(split_csv(needs, limit=16))
    try:
        view = await request.app.state.ports.step_free.alternative(station, wanted)
    except Exception as exc:  # noqa: BLE001 - an unreadable record is "unknown", never a 500
        log.warning("step-free port failed: %s", type(exc).__name__)
        view = await UnwiredStepFree().alternative(station, wanted)
    if view.get("lift_status") not in {"working", "out_of_service", "unknown"}:
        view = {**view, "lift_status": "unknown"}
    return view


@citizen_routes.post("/api/chat")
async def citizen_chat(request: Request, body: ChatRequest) -> StreamingResponse:
    service: ChatService = request.app.state.chat
    return StreamingResponse(
        service.events(body),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def build_console_app(
    settings: Settings | None = None,
    nabiz: Nabiz | None = None,
    *,
    llm_config: llm.LlmConfig | None = None,
    ports: Ports | None = None,
    guard: SpendGuard | None = None,
) -> FastAPI:
    """Build the app. Anything passed in (a facade, a model config, ports) is used as given.

    An injected facade is left open on shutdown: whoever built it owns it.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        from ibb_mcp.telemetry import setup_telemetry

        setup_telemetry("nabiz-console")
        owned = app.state.nabiz is None
        if owned:
            app.state.nabiz = Nabiz(SourceContext.create(settings=app.state.settings))
        app.state.chat = ChatService(app.state.nabiz, chat_config, app.state.guard, offline=app.state.settings.offline)
        log.info("nabiz console up: offline=%s model=%s", app.state.settings.offline, chat_config.describe())
        try:
            yield
        finally:
            if owned:
                await app.state.nabiz.aclose()
                app.state.nabiz = None

    chat_config = llm_config if llm_config is not None else llm.LlmConfig.from_env()
    app = FastAPI(title="Nabız", description="Resmî İBB hizmeti değildir. " + ATTRIBUTION_EN, lifespan=lifespan)
    app.state.settings = settings or (nabiz.settings if nabiz else Settings.from_env())
    app.state.nabiz = nabiz
    app.state.ports = ports or Ports()
    app.state.guard = guard or SpendGuard(BudgetConfig.from_env())
    app.state.fresh = Freshness(
        offline=app.state.settings.offline,
        card_stale_after_s=env_seconds("NABIZ_CARD_STALE_S", CARD_STALE_DEFAULT_S),
        arrival_stale_after_s=arrival_stale_after_s(),
    )

    @app.middleware("http")
    async def request_log(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        log.info("%s %s -> %s in %.1f ms", request.method, request.url.path, response.status_code, elapsed_ms)
        for name, value in CONSOLE_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    app.include_router(citizen_routes)
    app.include_router(operator_routes)
    # Last, so every /api route wins the match ahead of the page's files.
    if CONSOLE_STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=CONSOLE_STATIC_DIR, html=True), name="static")
    return app


def main() -> None:  # pragma: no cover - process entry point
    """``python -m nabiz.console``: load ``.env``, then serve on ``NABIZ_CONSOLE_PORT`` (default 8090)."""
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    load_env_file()
    uvicorn.run(
        build_console_app(),
        host=os.getenv("NABIZ_HOST", "127.0.0.1"),
        port=int(os.getenv("NABIZ_CONSOLE_PORT", str(DEFAULT_CONSOLE_PORT))),
        access_log=False,
    )
