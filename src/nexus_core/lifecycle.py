# Adapted from CloudSentinel app/actions.py (github.com/muratcan-ates/cloudsentinel @ 80938ae), MIT License,
# Copyright (c) 2026 CloudSentinel Team (YZTA Bootcamp 2026, Group 60). See NOTICE.md.
"""TTL expiry for unanswered NEXUS decision cards."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

from nexus_core.ledger import EntryKind, Ledger
from nexus_core.signals import as_utc
from nexus_core.state import SignalState


def expire_cards(ledger: Ledger, states: Iterable[SignalState], ttl_hours: int, now: dt.datetime) -> list[str]:
    """Seal expired awaiting-approval cards and leave deferred cards to the operator."""
    if ttl_hours == 0:
        return []
    current = as_utc(now)
    cutoff = current - dt.timedelta(hours=ttl_hours)
    expired = []
    for state in states:
        if state.status != "awaiting_approval" or state.drafted_at is None or state.drafted_at > cutoff:
            continue
        detail = {"expires_at": state.decision.expires_at.isoformat() if state.decision and state.decision.expires_at else None}
        ledger.append(
            EntryKind.EXPIRED,
            actor="system:timeout",
            detail=detail,
            signal_id=state.signal.signal_id,
            entity_id=state.signal.entity_id,
        )
        expired.append(state.signal.signal_id)
    return expired
