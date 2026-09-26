"""The operator endpoint for approval duration and coded-reason summaries."""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Request

from nabiz.console.operator import port_problem
from nabiz.console.ports import OPERATOR
from nexus_core.approval_health import ApprovalHealth, compute_approval_health
from nexus_core.engine import NexusEngine
from nexus_core.stats import MIN_RULINGS_FOR_WARNING, ROLLING_RULINGS

approval_health_routes = APIRouter(prefix="/api/console")


def approval_health_payload(health: ApprovalHealth, generated_at: dt.datetime) -> dict[str, Any]:
    """Build the reduced E18 response without person identifiers or free-text reasons."""
    return {
        "actor": OPERATOR,
        "window": {
            "size": ROLLING_RULINGS,
            "rulings_counted": health.rulings_counted,
            "min_rulings": MIN_RULINGS_FOR_WARNING,
        },
        "sufficient": health.sufficient,
        "approval_rate": health.approval_rate,
        "median_decision_s": health.median_decision_s,
        "decisions_timed": health.decisions_timed,
        "durations": [bucket.model_dump() for bucket in health.durations],
        "reasons": {
            "by_action": health.by_action,
            "codes": [reason.model_dump() for reason in health.reasons],
            "without_code": health.without_code,
        },
        "generated_at": generated_at.isoformat(),
    }


@approval_health_routes.get("/approval-health")
async def console_approval_health(request: Request) -> Any:
    port = request.app.state.ports.console
    engine = getattr(port, "engine", None)
    if not isinstance(engine, NexusEngine):
        return port_problem(503, "not_wired", "Karar çekirdeği bu süreçte bağlı değil.")
    states = list(engine.states().values())
    stats = engine.stats()
    health = compute_approval_health(states, stats)
    return approval_health_payload(health, dt.datetime.now(dt.UTC))
