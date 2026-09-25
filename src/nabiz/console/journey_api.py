"""Citizen route for an accessible rail journey."""

from __future__ import annotations

from typing import Any

from fastapi import Query, Request

from nabiz.console.brief import split_csv
from nabiz.console.cards import provenance_view, unknown_provenance
from nabiz.console.operator import port_problem
from nabiz.console.ports import PortNotWired


async def accessible_journey_route(
    request: Request,
    from_place: str = Query(..., alias="from", min_length=1, max_length=120),
    to: str = Query(..., min_length=1, max_length=120),
    needs: str = "step_free",
) -> Any:
    """GET /api/journey/accessible: source-backed steps and an honest unavailable answer."""
    try:
        result = await request.app.state.nabiz.accessible_journey(from_place, to, split_csv(needs, limit=16))
    except PortNotWired as exc:
        return port_problem(503, "not_wired", str(exc))
    except LookupError:
        return port_problem(404, "not_found", "Bu yer bulunamadı.")
    except ValueError as exc:
        return port_problem(400, "bad_request", str(exc))
    body = dict(result.data)
    offline = request.app.state.fresh.offline
    body["provenance"] = (
        provenance_view(result.provenance, offline=offline)
        if result.provenance is not None
        else unknown_provenance("metro_equipment")
    )
    return body
