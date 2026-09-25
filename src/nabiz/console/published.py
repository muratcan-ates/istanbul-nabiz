"""Read the citizen-facing cards already sealed in the NEXUS ledger.

The 24-hour reflex window is a design parameter: it limits how long a closed rule card stays
on the home page. This port only reads engine state. New signals still arrive when the operator
queue is read, never as a side effect of a citizen brief request.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any

from ibb_mcp.text import fold_tr
from nabiz.console.cards import card, how_view
from nabiz.console.nexus_port import board_key, titled
from nexus_core.approved import BOUND_ACTION
from nexus_core.arena import assess_confidence, uncertainty_codes
from nexus_core.engine import NexusEngine, default_evidence
from nexus_core.signals import system_clock
from nexus_core.state import SignalState

PUBLISHED_FOR_S = 86_400
CITYWIDE_KINDS = frozenset({"parking_full", "air_quality", "bus_bunching", "source_stale"})
EQUIPMENT_KINDS = frozenset({"equipment_fault", "hub_faults", "long_outage"})
KIND_BY_SIGNAL = {
    "long_outage": "metro_equipment", "hub_faults": "metro_equipment", "equipment_fault": "metro_equipment",
    "source_stale": "metro_equipment", "parking_full": "parking", "air_quality": "air", "bus_bunching": "metro_status",
}


class PublishedCards:
    """The read-only citizen port for rule-closed and operator-approved cards."""

    def __init__(
        self,
        engine: NexusEngine,
        *,
        offline: bool,
        stale_after_s: int,
        clock: Any = system_clock,
    ) -> None:
        self.engine = engine
        self.offline = offline
        self.stale_after_s = stale_after_s
        self.clock = clock

    async def published(self, *, stations: Sequence[str]) -> list[dict[str, Any]]:
        now = self.clock()
        requested = {fold_tr(station) for station in stations if fold_tr(station)}
        latest: dict[tuple[str, str, str | None], SignalState] = {}
        for state in self.engine.states().values():
            if not self._visible(state, now, requested):
                continue
            key = board_key(state)
            current = latest.get(key)
            if current is None or state.received_at > current.received_at:
                latest[key] = state
        return [self._card(state, now) for state in sorted(latest.values(), key=lambda item: item.received_at)]

    def _visible(self, state: SignalState, now: dt.datetime, requested: set[str]) -> bool:
        signal = state.signal
        payload = signal.payload
        location = payload.get("station") or payload.get("hub")
        if signal.kind in CITYWIDE_KINDS:
            pass
        elif isinstance(location, str) and location:
            if fold_tr(location) not in requested:
                return False
        else:
            return False

        if state.status == "closed_by_reflex":
            if state.action is None or state.action.kind == BOUND_ACTION or state.closed_at is None:
                return False
            age_s = (now - state.closed_at).total_seconds()
            return 0 <= age_s <= PUBLISHED_FOR_S

        if state.status not in {"approved", "executed"} or state.decision is None:
            return False
        if state.decision.proposed_action.kind != "publish_card" or not state.rulings:
            return False
        ruling = state.rulings[-1]
        if not ruling.published_text:
            return False
        expires_at = state.decision.proposed_action.expires_at
        return expires_at is None or expires_at > now

    def _card(self, state: SignalState, now: dt.datetime) -> dict[str, Any]:
        signal = state.signal
        provenance = signal.provenance.as_provenance(now)
        if self.offline and provenance["mode"] == "live":
            provenance["mode"] = "recorded"

        if state.status == "closed_by_reflex":
            action = state.action
            assert action is not None
            kind = action.card.kind or "metro_equipment"
            title, body = action.card.title, action.card.body
            rule_id = state.rule_id or action.rule_id
            uncertainty = assess_confidence(
                uncertainty_codes(default_evidence(signal), [], now, self.stale_after_s)
            ).codes
            latency_ms = state.reflex_ms
        else:
            decision = state.decision
            assert decision is not None and state.rulings
            text = state.rulings[-1].published_text or ""
            kind = KIND_BY_SIGNAL.get(signal.kind, "metro_equipment")
            title = titled(signal.title, state)
            body = f"{text} (Simüle operatör onayladı.)"
            rule_id = state.rule_id or decision.rule_id
            uncertainty = decision.confidence.codes
            published_at = state.published_at
            latency_ms = (published_at - state.received_at).total_seconds() * 1000 if published_at else None

        tool = "metro_equipment_signals" if signal.kind in EQUIPMENT_KINDS else "check_alerts"
        how = how_view(
            tool, provenance, rule_id=rule_id, signal_id=signal.signal_id,
            uncertainty=uncertainty, latency_ms=latency_ms,
        )
        status = "unverified" if signal.kind == "source_stale" else "warning"
        return card(kind, signal.signal_id, title=title, body=body, status=status, provenance=provenance, how=how)
