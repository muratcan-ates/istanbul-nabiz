"""Operator-only HTTP endpoints for hypothetical lift-closure scenarios."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from ibb_mcp.http import RateLimitExceeded, UpstreamUnavailable
from ibb_mcp.text import fold_tr
from nabiz.console.cards import provenance_view, unknown_provenance
from nabiz.console.operator import port_problem
from nabiz.console.ports import PortNotWired
from nabiz.console.scenario import MAX_PLACE_CHARS, MAX_ROUTES, lift_status_now, route_from
from nabiz.console.scenario_run import run_scenario
from nabiz.console.scenario_store import MAX_SAVED, TTL_DAYS, SavedJourneys, ScenarioStore

log = logging.getLogger("nabiz.console.scenario")
scenario_routes = APIRouter(prefix="/api/console")


class RouteBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    origin: str = Field(alias="from", min_length=1, max_length=120)
    destination: str = Field(alias="to", min_length=1, max_length=120)
    needs: list[str] | None = None


class RunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    station: str = Field(min_length=1, max_length=MAX_PLACE_CHARS)
    line: str | None = Field(default=None, max_length=80)
    routes: list[str | RouteBody] = Field(min_length=1, max_length=MAX_ROUTES)
    include_saved: bool = False
    sample: bool = False


def _store(request: Request) -> ScenarioStore:
    if hasattr(request.app.state, "scenario_clock"):
        return ScenarioStore(clock=request.app.state.scenario_clock)
    return ScenarioStore()


def _saved_reader(request: Request) -> SavedJourneys:
    reader = getattr(request.app.state, "scenario_saved_journeys", None)
    return reader if isinstance(reader, SavedJourneys) else SavedJourneys()


def _source_unavailable() -> JSONResponse:
    return port_problem(503, "source_unavailable", "İstasyon ya da asansör kaydı okunamadı.")


@scenario_routes.get("/scenario/stations")
async def scenario_stations(request: Request) -> Any:
    nabiz = getattr(request.app.state, "nabiz", None)
    if nabiz is None:
        return port_problem(503, "not_wired", "İstasyon ve asansör kaynağı bağlı değil.")
    try:
        stations, _ = await nabiz._source("metro").stations()
        snapshot, provenance = await nabiz._source("metro_equipment").snapshot(("Asansör",))
    except (PortNotWired, RateLimitExceeded, UpstreamUnavailable, AttributeError):
        return _source_unavailable()
    if not snapshot.groups_read:
        return _source_unavailable()
    grouped: dict[str, list[Any]] = defaultdict(list)
    for platform in stations:
        if platform.name:
            grouped[fold_tr(platform.name)].append(platform)
    items = []
    for platforms in grouped.values():
        name = platforms[0].name or ""
        state = lift_status_now(platforms, snapshot.records)
        count = None if any(p.lifts is None for p in platforms) else sum(p.lifts or 0 for p in platforms)
        items.append(
            {
                "name": name,
                "lines": sorted({p.line_name for p in platforms if p.line_name}),
                "lifts": count,
                "lift_status_now": state,
            }
        )
    stamp = provenance_view(provenance, offline=nabiz.settings.offline) if provenance else unknown_provenance("metro_equipment")
    return {"stations": sorted(items, key=lambda item: fold_tr(item["name"])), "provenance": stamp}


@scenario_routes.post("/scenario/run")
async def scenario_run_endpoint(request: Request, body: RunBody) -> Any:
    started = time.perf_counter()
    nabiz = getattr(request.app.state, "nabiz", None)
    if nabiz is None:
        return port_problem(503, "not_wired", "İstasyon ve asansör kaynağı bağlı değil.")
    normalized: list[dict[str, Any]] = []
    errors: dict[int, str] = {}
    for index, raw in enumerate(body.routes):
        try:
            payload = raw.model_dump(by_alias=True) if isinstance(raw, RouteBody) else raw
            normalized.append(route_from(payload))
        except ValueError as exc:
            errors[index] = str(exc)
            normalized.append({"from": "", "to": "", "needs": ["step_free"]})
    # Invalid rows are kept in place so valid rows still receive a result.
    valid = [(index, route) for index, route in enumerate(normalized) if index not in errors]
    include_saved = body.include_saved and _saved_reader(request).status() == "ok"
    try:
        output = await run_scenario(
            nabiz,
            " ".join(body.station.split()),
            body.line or None,
            [route for _index, route in valid],
            include_saved=include_saved,
            sample=body.sample,
            saved_source=_saved_reader(request),
        )
    except LookupError:
        return port_problem(404, "unknown_station", "Seçilen istasyon ya da hat İBB istasyon listesinde yok.")
    except PortNotWired as exc:
        return port_problem(503, "not_wired", str(exc))
    rows_by_index = {index: row for (index, _route), row in zip(valid, output["routes"], strict=True)}
    all_rows = []
    for index, _route in enumerate(normalized):
        if index in errors:
            all_rows.append(
                {
                    "label": "Güzergâh " + str(index + 1),
                    "from": "",
                    "to": "",
                    "needs": ["step_free"],
                    "sample": body.sample,
                    "effect": "invalid",
                    "before": None,
                    "after": None,
                    "added_minutes": None,
                    "uncertainty": [],
                    "error": errors[index],
                }
            )
        else:
            all_rows.append(rows_by_index[index])
    output["routes"] = all_rows
    output["counts"] = {
        **{
            name: output["counts"].get(name, 0)
            for name in ("blocked", "detour", "not_affected", "already_unavailable", "unverified", "affected")
        },
        "invalid": len(errors),
        "total": len(all_rows),
    }
    store = _store(request)
    stored = store.add(body.station.strip(), body.line, normalized_routes(normalized, errors, body.sample), output)
    elapsed = round((time.perf_counter() - started) * 1000)
    log.info("scenario action=run outcome=stored elapsed_ms=%d", elapsed)
    return {"id": stored["id"], "computed_at": stored["computed_at"], "stored": True, **output}


def normalized_routes(routes: list[dict[str, Any]], errors: dict[int, str], sample: bool) -> list[dict[str, Any]]:
    return [
        {"from": route["from"], "to": route["to"], "needs": route["needs"], "sample": bool(sample)}
        if index not in errors
        else {"from": "", "to": "", "needs": ["step_free"], "sample": bool(sample)}
        for index, route in enumerate(routes)
    ]


@scenario_routes.get("/scenario")
async def scenario_list(request: Request) -> dict[str, Any]:
    items = _store(request).items()
    return {"items": items, "limit": MAX_SAVED, "ttl_days": TTL_DAYS, "saved_status": _saved_reader(request).status()}


@scenario_routes.get("/scenario/{row_id}")
async def scenario_get(row_id: str, request: Request) -> Any:
    row = _store(request).get(row_id)
    if row is None:
        return port_problem(404, "not_found", "Kaydedilen senaryo bulunamadı.")
    return row


@scenario_routes.delete("/scenario/{row_id}")
async def scenario_delete(row_id: str, request: Request) -> Any:
    try:
        _store(request).delete(row_id)
    except LookupError:
        return port_problem(404, "not_found", "Kaydedilen senaryo bulunamadı.")
    elapsed = 0
    log.info("scenario action=delete outcome=deleted elapsed_ms=%d", elapsed)
    return Response(status_code=204)
