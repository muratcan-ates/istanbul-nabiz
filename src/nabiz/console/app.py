"""The product app's factory, its process entry point and the citizen routes.

``build_console_app`` wires one process: one :class:`~ibb_mcp.tools.Nabiz` facade (one polite
HTTP client and one cache for every visitor, DECISIONS #3), one model configuration, one spend
guard and the ports. :func:`main` is the only place that reads the repository's ``.env``, so
tests and imports never pick up a real key.

The request log writes method, path, status and duration: never a query string (it can hold
saved stations and needs) and never a body (it holds the question).

The operator's side sits behind :class:`~nabiz.console.access.OperatorAccess` (a token, or this
machine only), the chat behind a per-address turn limit, and the page's sample data
(``/mock/*``) is served only offline or with ``NABIZ_UI_MOCK=1``: on a public address a
"?mock=1" link must not dress made-up cards in the product's name.
"""

from __future__ import annotations

import logging
import os
import pathlib
import posixpath
import time
import urllib.parse
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ibb_mcp.config import ATTRIBUTION_EN, Settings
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.console.access import (
    CHAT_TURNS_PER_MIN,
    COOKIE,
    COOKIE_MAX_AGE_S,
    OperatorAccess,
    TurnLimiter,
    is_operator_path,
    login_page,
)
from nabiz.console.accounts_api import account_routes
from nabiz.console.agency_api import agency_routes
from nabiz.console.approval_health_api import approval_health_routes
from nabiz.console.arrival import arrival_stale_after_s, arrival_view
from nabiz.console.brief import Freshness, build_brief, split_csv
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.cards import CARD_STALE_DEFAULT_S, env_seconds
from nabiz.console.chat import ChatRequest, ChatService
from nabiz.console.compare_api import compare_routes
from nabiz.console.day_api import day_routes
from nabiz.console.drill_api import drill_routes
from nabiz.console.envfile import load_env_file
from nabiz.console.feedback_api import feedback_routes
from nabiz.console.history_api import history_routes
from nabiz.console.how_api import how_routes
from nabiz.console.journey_api import accessible_journey_route
from nabiz.console.kill_switch_api import chat_gate, kill_switch_routes
from nabiz.console.knowledge_api import knowledge_routes
from nabiz.console.map_layers_api import map_layers_routes
from nabiz.console.nearby_api import nearby_router
from nabiz.console.operator import operator_routes, port_problem
from nabiz.console.organs_api import organs_routes
from nabiz.console.policy import functional_needs
from nabiz.console.ports import Ports, UnwiredStepFree
from nabiz.console.quota import MeteredGuard, QuotaBook
from nabiz.console.quota_api import plan_turn, quota_routes
from nabiz.console.requests_api import request_routes
from nabiz.console.rules_api import rules_routes
from nabiz.console.stop_card import stop_card_router

log = logging.getLogger("nabiz.console")

CONSOLE_STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"
DEFAULT_CONSOLE_PORT = 8090

#: Same-origin only: the page is vanilla JS served from ``static/``. A page that needs another
#: origin (a map's tiles) widens this here, with the reason, not in the page. The one widening:
#: ``img-src`` admits OpenStreetMap's tile hosts, because the citizen map (``js/map.js``, G18) draws
#: its base layer from ``tile.openstreetmap.org`` as plain images once the visitor asks for their
#: location. Leaflet itself is vendored (``static/vendor/leaflet``), so scripts and styles stay 'self'.
OSM_TILE_SOURCES = ("https://tile.openstreetmap.org", "https://*.tile.openstreetmap.org")
CONSOLE_HEADERS = {
    "Content-Security-Policy": "; ".join(
        [
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: " + " ".join(OSM_TILE_SOURCES),
            "connect-src 'self'",
            "font-src 'self'",
            "worker-src 'self'",
            "manifest-src 'self'",
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
citizen_routes.include_router(nearby_router)


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
            # The turn's own rule (B01): a capped first rung may still answer from a later one.
            "within_budget": llm.pick_rung(config, state.guard.allows) is not None or not llm.available(config),
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
        published=state.ports.published,
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


citizen_routes.add_api_route("/api/journey/accessible", accessible_journey_route, methods=["GET"])


@citizen_routes.get("/console")
async def operator_page() -> FileResponse:
    """The simulated operator's page; the static mount serves everything it loads."""
    return FileResponse(CONSOLE_STATIC_DIR / "console.html", media_type="text/html")


@citizen_routes.post("/console/login")
async def operator_login(request: Request) -> Response:
    """The sign-in form's target: a right token sets the session cookie, anything else is refused."""
    access: OperatorAccess = request.app.state.access
    body = (await request.body())[:1024].decode("utf-8", errors="replace")
    offered = (urllib.parse.parse_qs(body).get("token") or [""])[0]
    if not access.token_matches(offered.strip()):
        return HTMLResponse(login_page(failed=True), status_code=401)
    response = RedirectResponse("/console", status_code=303)
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(
        COOKIE, access.cookie_value(), max_age=COOKIE_MAX_AGE_S, httponly=True, samesite="strict", secure=secure, path="/"
    )
    return response


@citizen_routes.post("/api/chat")
async def citizen_chat(request: Request, body: ChatRequest) -> Response:
    if (paused := chat_gate(request)) is not None:
        return paused
    service: ChatService = request.app.state.chat
    limiter: TurnLimiter = request.app.state.chat_limiter
    # DECISIONS #36: an emergency is never limited or counted; the daily quota closes only the model.
    turn = plan_turn(request, body.message)
    if not turn.emergency and not limiter.allow(request.client.host if request.client else "unknown"):
        return port_problem(429, "too_many_turns", "Çok sık soru geldi. Bir dakika sonra yeniden dene.")
    return StreamingResponse(
        turn.events(service, body),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _gate(request: Request) -> Response | None:
    """The operator's door and the sample-data switch, on the path the static files would serve."""
    state = request.app.state
    path = posixpath.normpath(request.url.path)
    if path.startswith("/mock/") and not (state.settings.offline or os.getenv("NABIZ_UI_MOCK") == "1"):
        return port_problem(404, "not_found", "Örnek veri bu sunucuda kapalı.")
    refusal = state.access.refusal(request) if is_operator_path(path) else None
    if refusal is not None and refusal.status_code == 401 and path.startswith("/console"):
        return HTMLResponse(login_page(failed=False), status_code=401)
    return refusal


async def _request_log(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    started = time.perf_counter()
    response = _gate(request) or await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    log.info("%s %s -> %s in %.1f ms", request.method, request.url.path, response.status_code, elapsed_ms)
    for name, value in CONSOLE_HEADERS.items():
        response.headers.setdefault(name, value)
    if not request.url.path.startswith("/api/"):
        # The page is ES modules with no build step: a cached old module beside a new one
        # breaks the page (the web app's DECISIONS entry on the same trap).
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


async def _invalid_request(request: Request, exc: Exception) -> Response:
    # FastAPI's own 422 body is English and names fields; the pages show {error, message}.
    return port_problem(422, "invalid_request", "İstek geçersiz: bir alan eksik, çok uzun ya da tanınmıyor.")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    from ibb_mcp.telemetry import setup_telemetry

    setup_telemetry("nabiz-console")
    state = app.state
    owned = state.nabiz is None
    if owned:
        state.nabiz = Nabiz(SourceContext.create(settings=state.settings))
    # The chat's guard also meters each person's daily model calls (DECISIONS #36); /healthz reads the plain one.
    state.chat = ChatService(state.nabiz, state.chat_config, MeteredGuard(state.guard), offline=state.settings.offline)
    release = None
    if state.wire_nexus:
        from nabiz.console.wiring import wire_ports

        # The Arena gets its own spend guard (wire_ports' default), never the chat's.
        state.ports, release = wire_ports(state.nabiz, state.settings, llm_config=state.chat_config)
    log.info("nabiz console up: offline=%s model=%s", state.settings.offline, state.chat_config.describe())
    try:
        yield
    finally:
        if release is not None:
            await release()
        if owned:
            await state.nabiz.aclose()
            state.nabiz = None


def build_console_app(
    settings: Settings | None = None,
    nabiz: Nabiz | None = None,
    *,
    llm_config: llm.LlmConfig | None = None,
    ports: Ports | None = None,
    guard: SpendGuard | None = None,
    wire_nexus: bool = False,
    access: OperatorAccess | None = None,
) -> FastAPI:
    """Build the app. Anything passed in (a facade, a model config, ports) is used as given.

    ``wire_nexus`` binds the ports to the decision core and the lift records once the facade
    exists (:mod:`nabiz.console.wiring`); without it, and without ``ports``, every console call
    answers 503 "not wired". An injected facade is left open on shutdown: whoever built it owns it.
    """
    app = FastAPI(title="Nabız", description="Resmî İBB hizmeti değildir. " + ATTRIBUTION_EN, lifespan=_lifespan)
    state = app.state
    state.chat_config = llm_config if llm_config is not None else llm.LlmConfig.from_env()
    state.wire_nexus = wire_nexus and ports is None
    state.settings = settings or (nabiz.settings if nabiz else Settings.from_env())
    state.nabiz = nabiz
    state.ports = ports or Ports()
    state.guard = guard or SpendGuard(BudgetConfig.from_env())
    state.access = access or OperatorAccess.from_env()
    state.chat_limiter = TurnLimiter(env_seconds("NABIZ_CHAT_TURNS_PER_MIN", CHAT_TURNS_PER_MIN))
    state.quota = QuotaBook.from_env()
    state.fresh = Freshness(
        offline=state.settings.offline,
        card_stale_after_s=env_seconds("NABIZ_CARD_STALE_S", CARD_STALE_DEFAULT_S),
        arrival_stale_after_s=arrival_stale_after_s(),
    )
    app.middleware("http")(_request_log)
    app.add_exception_handler(RequestValidationError, _invalid_request)
    app.include_router(citizen_routes)
    app.include_router(compare_routes)
    app.include_router(feedback_routes)
    app.include_router(history_routes)
    app.include_router(knowledge_routes)
    app.include_router(how_routes)
    app.include_router(map_layers_routes)
    app.include_router(agency_routes)
    app.include_router(operator_routes)
    app.include_router(rules_routes)
    app.include_router(day_routes)
    app.include_router(approval_health_routes)
    app.include_router(organs_routes)
    app.include_router(drill_routes)
    app.include_router(kill_switch_routes)
    app.include_router(stop_card_router)
    app.include_router(quota_routes)
    app.include_router(account_routes)
    # Operatöre aktar + çeviri: /api/requests for visitors, /api/console/requests behind the console's door.
    app.include_router(request_routes)
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
        build_console_app(wire_nexus=True),
        host=os.getenv("NABIZ_HOST", "127.0.0.1"),
        port=int(os.getenv("NABIZ_CONSOLE_PORT", str(DEFAULT_CONSOLE_PORT))),
        access_log=False,
    )
