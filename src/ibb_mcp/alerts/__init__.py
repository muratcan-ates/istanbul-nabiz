"""Proactive alerts (epic E2), built so that privacy is a property of the code, not a promise.

The server is stateless: it holds no subscription, no coordinate and no history. The browser
keeps the subscription in ``localStorage`` and sends it with each check; the server evaluates
pure rules against data it already fetched for everybody and answers. See ``docs/privacy.md``
for the data-flow diagram, what is stored where, retention (none) and how a user deletes
everything (clear the site's browser storage).

Typical use from the tool layer::

    from ibb_mcp.alerts import check_alerts
    payload = await check_alerts(nabiz.ctx, subscription)

or, when the caller already has a snapshot (tests, the collector, a batch job)::

    ctx = await build_context(source_ctx, subscription)
    alerts = evaluate_subscription(subscription, ctx)

The engine lives in the server package because ``check_alerts`` is an MCP tool every client
gets (DECISIONS #2), and ``ibb_mcp`` imports nothing from ``nabiz`` (DECISIONS #8). Until
2026-09-23 it was ``nabiz.alerts``, which (with the tracing module) made ``import ibb_mcp.server``
load seven ``nabiz`` modules; that name still works, as a re-export (:mod:`nabiz.alerts`).
"""

from __future__ import annotations

from ibb_mcp.alerts.engine import (
    COOLDOWN_POLICY,
    DEFAULT_COOLDOWNS,
    MAX_PLACES,
    MAX_RULES,
    PRIVACY_SUMMARY,
    ParsedSubscription,
    WatchedPlace,
    build_context,
    check_alerts,
    describe_subscription,
    evaluate_subscription,
    parse_subscription,
)
from ibb_mcp.alerts.rules import (
    AirQualityObservation,
    AirQualityRule,
    Alert,
    AlertContext,
    BunchingObservation,
    BusBunchingRule,
    Citation,
    MetroDisruptionRule,
    MetroObservation,
    ParkingFillingRule,
    ParkingObservation,
    Rule,
    Severity,
    TrafficObservation,
    TrafficRule,
    evaluate_rules,
)

__all__ = [
    "COOLDOWN_POLICY",
    "DEFAULT_COOLDOWNS",
    "MAX_PLACES",
    "MAX_RULES",
    "PRIVACY_SUMMARY",
    "AirQualityObservation",
    "AirQualityRule",
    "Alert",
    "AlertContext",
    "BunchingObservation",
    "BusBunchingRule",
    "Citation",
    "MetroDisruptionRule",
    "MetroObservation",
    "ParkingFillingRule",
    "ParkingObservation",
    "ParsedSubscription",
    "Rule",
    "Severity",
    "TrafficObservation",
    "TrafficRule",
    "WatchedPlace",
    "build_context",
    "check_alerts",
    "describe_subscription",
    "evaluate_rules",
    "evaluate_subscription",
    "parse_subscription",
]
