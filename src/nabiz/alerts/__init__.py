"""Proactive alerts: moved to :mod:`ibb_mcp.alerts`, re-exported here.

The engine, its rules and the MCP subscription schema moved into the server package on
2026-09-23: ``check_alerts`` is an MCP tool every client gets (DECISIONS #2), and the server
package imports nothing from ``nabiz`` (DECISIONS #8). ``from nabiz.alerts import
check_alerts`` and ``nabiz.alerts.engine`` keep working for code written before the move;
new code imports :mod:`ibb_mcp.alerts`.
"""

from __future__ import annotations

from ibb_mcp.alerts import (
    COOLDOWN_POLICY,
    DEFAULT_COOLDOWNS,
    MAX_PLACES,
    MAX_RULES,
    PRIVACY_SUMMARY,
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
    ParsedSubscription,
    Rule,
    Severity,
    TrafficObservation,
    TrafficRule,
    WatchedPlace,
    build_context,
    check_alerts,
    describe_subscription,
    evaluate_rules,
    evaluate_subscription,
    parse_subscription,
)

#: The engine's name for a user's place before 2026-09-23. It is now ``WatchedPlace``, so
#: that it cannot be confused with the gazetteer's ``ibb_mcp.sources.places.Place``.
Place = WatchedPlace

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
    "Place",
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
