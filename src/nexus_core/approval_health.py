"""Duration and coded-reason summaries for the operator's approval ledger."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from nexus_core.state import SignalState
from nexus_core.stats import MIN_RULINGS_FOR_WARNING, ROLLING_RULINGS, Stats

ActionGroup = Literal["approve", "reject"]
DurationKey = Literal["lt_10s", "s10_60", "m1_5", "gt_5m"]

# The ranges include the lower bound and exclude the upper bound. These labels mirror the console.
DURATION_BUCKETS = (
    ("lt_10s", "10 sn altı", 0.0, 10.0),
    ("s10_60", "10 sn ile 1 dk", 10.0, 60.0),
    ("m1_5", "1 ile 5 dk", 60.0, 300.0),
    ("gt_5m", "5 dk ve üstü", 300.0, None),
)

# This display map mirrors the operator's coded-reason table; free text is never returned.
REASON_LABELS: dict[str, tuple[str, str]] = {
    "evidence_current": ("approve", "Kanıt güncel ve yeterli"),
    "seats_agree": ("approve", "Üç koltuk uyumlu"),
    "text_correct": ("approve", "Metin doğru ve yayıma uygun"),
    "evidence_stale": ("reject", "Kanıt eşikten eski"),
    "evidence_insufficient": ("reject", "Kanıt yetersiz"),
    "wrong_place": ("reject", "Yanlış yer ya da hat"),
    "duplicate": ("reject", "Yinelenen sinyal"),
    "text_unfit": ("reject", "Metin yayıma uygun değil"),
    "needs_verification": ("defer", "Ek doğrulama gerekiyor"),
    "await_fresh_data": ("defer", "Taze veri bekleniyor"),
}


class DurationBucket(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: DurationKey
    label: str
    count: int


class ReasonCount(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    label: str
    group: ActionGroup
    count: int


class ApprovalHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    rulings_counted: int
    sufficient: bool
    approval_rate: float | None
    median_decision_s: float | None
    decisions_timed: int
    durations: tuple[DurationBucket, ...]
    by_action: dict[str, int]
    reasons: tuple[ReasonCount, ...]
    without_code: int


def reason_code(reason: str) -> str | None:
    """Return the known reason code, dropping any free-text suffix."""
    for code, (_, label) in REASON_LABELS.items():
        if reason == label or reason.startswith(label + ": "):
            return code
    return None


def _verdict_window(states: Iterable[SignalState]):
    rulings = (ruling for state in states for ruling in state.rulings if ruling.status in ("approved", "rejected"))
    return sorted(rulings, key=lambda ruling: ruling.entry_id)[-ROLLING_RULINGS:]


def _duration_values(states: Iterable[SignalState]) -> list[float]:
    return [
        max(0.0, (state.first_ruling.at - state.drafted_at).total_seconds())
        for state in states
        if state.drafted_at is not None and state.first_ruling is not None
    ]


def _duration_buckets(values: list[float]) -> tuple[DurationBucket, ...]:
    counts = Counter()
    for value in values:
        for key, _, lower, upper in DURATION_BUCKETS:
            if value >= lower and (upper is None or value < upper):
                counts[key] += 1
                break
    return tuple(DurationBucket(key=key, label=label, count=counts[key]) for key, label, _, _ in DURATION_BUCKETS)


def _reason_counts(rulings) -> tuple[tuple[ReasonCount, ...], dict[str, int], int]:
    actions = {"approve": 0, "edit": 0, "reject": 0}
    codes = Counter()
    without_code = 0
    for ruling in rulings:
        actions[ruling.action] += 1
        code = reason_code(ruling.reason)
        if code is None:
            without_code += 1
        elif REASON_LABELS[code][0] in ("approve", "reject"):
            codes[code] += 1
        else:
            without_code += 1
    reasons = tuple(
        ReasonCount(code=code, label=label, group=group, count=codes[code])
        for code, (group, label) in REASON_LABELS.items()
        if group in ("approve", "reject")
    )
    return reasons, actions, without_code


def compute_approval_health(states: Iterable[SignalState], stats: Stats) -> ApprovalHealth:
    """Summarize first-decision durations and the latest coded approval or rejection reasons."""
    states = list(states)
    rulings = _verdict_window(states)
    durations = _duration_values(states)
    reasons, actions, without_code = _reason_counts(rulings)
    return ApprovalHealth(
        rulings_counted=stats.rulings_counted,
        sufficient=stats.rulings_counted >= MIN_RULINGS_FOR_WARNING,
        approval_rate=stats.approval_rate,
        median_decision_s=stats.median_decision_s,
        decisions_timed=len(durations),
        durations=_duration_buckets(durations),
        by_action=actions,
        reasons=reasons,
        without_code=without_code,
    )
