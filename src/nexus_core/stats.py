"""Stats: the time NEXUS gives back, measured from the ledger, for the team and never per person.

* ``reflex_closed_today``: signals a rule closed since midnight, İstanbul time.
* ``awaiting_approval``: Arena cards no one has ruled on yet.
* ``deferred``: cards a person deferred; they stay in the queue and can still be decided.
* ``median_decision_s``: from the card being drafted to the first human ruling on it.
* ``citizen_update_latency_s``: from the source observing the fault to the citizen face showing
  it, counted only for what the citizen face really shows today: an approved step-free
  alternative (``publish_alternative``), and a later snapshot of that outage closed by its
  approval (OA). Other reflexes (an escalator card, the stale-data rule) are sealed but no
  citizen page shows them yet, so counting them would time a delivery that never happened.
  A recorded signal (a replay) is timed from when the core received it: its observation time
  is the recording's, days before the replay.
* ``approval_rate``: approvals (edited ones included) over approvals and rejections, over the
  last :data:`ROLLING_RULINGS` rulings; deferrals are not a verdict and are left out.

A rate above :data:`RUBBER_STAMP_RATE` raises ``rubber_stamp_warning`` ("göstermelik onay"):
a person who approves everything is not reviewing. The warning waits for
:data:`MIN_RULINGS_FOR_WARNING` rulings, because three approvals out of three is a small
sample, not a habit. The numbers carry no operator handle: the ledger has it for the audit
trail, the stats never group by it.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

from nexus_core.approved import BOUND_ACTION
from nexus_core.signals import as_utc
from nexus_core.state import SignalState

#: Türkiye has kept UTC+3 all year since 2016; a fixed offset needs no tz database in the image.
ISTANBUL = dt.timezone(dt.timedelta(hours=3), "TRT")
ROLLING_RULINGS = 50
RUBBER_STAMP_RATE = 0.98
MIN_RULINGS_FOR_WARNING = 10


class Stats(BaseModel):
    model_config = ConfigDict(frozen=True)

    reflex_closed_today: int
    awaiting_approval: int
    deferred: int
    median_decision_s: float | None
    citizen_update_latency_s: float | None
    approval_rate: float | None
    rulings_counted: int
    rubber_stamp_warning: bool


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


def _seconds(start: dt.datetime, end: dt.datetime) -> float:
    return max(0.0, (end - start).total_seconds())


def citizen_published_at(state: SignalState) -> dt.datetime | None:
    """When the citizen face started showing this signal's text, or ``None`` if it never does."""
    if state.action is not None:
        return state.closed_at if state.action.kind == BOUND_ACTION else None
    if state.decision is not None and state.decision.proposed_action.kind == BOUND_ACTION:
        return state.published_at
    return None


def _latency(state: SignalState, published: dt.datetime) -> float:
    start = state.signal.observed_at if state.signal.provenance.mode == "live" else state.received_at
    return _seconds(start, published)


def compute_stats(states: Iterable[SignalState], now: dt.datetime) -> Stats:
    states = list(states)
    today = as_utc(now).astimezone(ISTANBUL).date()
    closed_today = sum(1 for s in states if s.closed_at and s.closed_at.astimezone(ISTANBUL).date() == today)
    awaiting = sum(1 for s in states if s.status == "awaiting_approval")
    deferred = sum(1 for s in states if s.status == "deferred")
    decision_times = [
        _seconds(s.drafted_at, s.first_ruling.at) for s in states if s.drafted_at is not None and s.first_ruling is not None
    ]
    latencies = [_latency(s, published) for s in states if (published := citizen_published_at(s)) is not None]
    verdicts = sorted(
        (r for s in states for r in s.rulings if r.status in ("approved", "rejected")),
        key=lambda r: r.entry_id,
    )[-ROLLING_RULINGS:]
    rate = round(sum(r.status == "approved" for r in verdicts) / len(verdicts), 4) if verdicts else None
    warning = rate is not None and len(verdicts) >= MIN_RULINGS_FOR_WARNING and rate > RUBBER_STAMP_RATE
    return Stats(
        reflex_closed_today=closed_today,
        awaiting_approval=awaiting,
        deferred=deferred,
        median_decision_s=_median(decision_times),
        citizen_update_latency_s=_median(latencies),
        approval_rate=rate,
        rulings_counted=len(verdicts),
        rubber_stamp_warning=warning,
    )
