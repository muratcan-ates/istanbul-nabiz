"""Approved alternatives (OA): one human approval binds one text to one outage, for a while.

When a person approves (or edits and approves) a card whose action is
``publish_alternative``, and the signal names its outage (``payload.outage_id``, the
equipment code plus when the fault was first seen), the approved text is bound to that outage
as ``OA-<outage_id>``. The next snapshot of the same outage does not wait for a person again,
but it is not published blindly either: the run-time check (R-05) must pass first:

* the bound alternative station is still the one the new snapshot proposes
  (``alternative_changed`` otherwise);
* the new snapshot says the alternative's elevator is not out of service, explicitly
  (``payload.alternative_faulty is False``); unknown is not good enough
  (``alternative_unverified``);
* the snapshot is fresher than the staleness threshold (``stale_data``).

A failed check sends the signal back to a person (``binding_check_failed``). A binding covers
one outage only: a new fault on the same equipment has a new ``outage_id`` and needs a new
decision. It ends when the approved proposal expires (at most 30 days by default). This is
not a rule and does not generalise; learned rules are ``rule_drafts.py``.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

from nexus_core.signals import Signal, as_utc
from nexus_core.state import SignalState

BINDING_PREFIX = "OA-"
BOUND_ACTION = "publish_alternative"
APPROVED_BINDING = "approved_binding"
BINDING_CHECK_FAILED = "binding_check_failed"


class Binding(BaseModel):
    model_config = ConfigDict(frozen=True)

    binding_id: str
    outage_id: str
    entity_id: str
    text: str
    alternative_station: str | None
    approved_signal_id: str
    approved_at: dt.datetime
    expires_at: dt.datetime | None

    def is_active(self, now: dt.datetime) -> bool:
        return self.expires_at is None or as_utc(now) < self.expires_at


def outage_of(signal: Signal) -> str | None:
    outage = signal.payload.get("outage_id")
    return outage if isinstance(outage, str) and outage else None


def binding_of(state: SignalState) -> Binding | None:
    """The binding an approved ``publish_alternative`` card created, if it created one."""
    decision, outage = state.decision, outage_of(state.signal)
    ruling = next((r for r in state.rulings if r.status == "approved"), None)
    if decision is None or outage is None or ruling is None or decision.proposed_action.kind != BOUND_ACTION:
        return None
    alternative = state.signal.payload.get("alternative_station")
    return Binding(
        binding_id=f"{BINDING_PREFIX}{outage}",
        outage_id=outage,
        entity_id=state.signal.entity_id,
        text=ruling.published_text or decision.proposed_action.text,
        alternative_station=alternative if isinstance(alternative, str) else None,
        approved_signal_id=state.signal.signal_id,
        approved_at=ruling.at,
        expires_at=decision.proposed_action.expires_at,
    )


def find_binding(states: Iterable[SignalState], signal: Signal, now: dt.datetime) -> Binding | None:
    """The newest active binding for this signal's entity and outage, if any."""
    outage = outage_of(signal)
    if outage is None:
        return None
    found = [
        binding
        for state in states
        if (binding := binding_of(state)) is not None
        and binding.outage_id == outage
        and binding.entity_id == signal.entity_id
        and binding.is_active(now)
    ]
    return max(found, key=lambda b: b.approved_at) if found else None


def revalidate(binding: Binding, signal: Signal, now: dt.datetime, stale_after_s: int) -> tuple[str, ...]:
    """R-05: the reasons the bound text may not be published for this snapshot; empty means publish."""
    failures: list[str] = []
    if signal.payload.get("alternative_station") != binding.alternative_station:
        failures.append("alternative_changed")
    if signal.payload.get("alternative_faulty") is not False:
        failures.append("alternative_unverified")
    age = signal.provenance.age_s(now)
    if age is None or age > stale_after_s:
        failures.append("stale_data")
    return tuple(failures)
