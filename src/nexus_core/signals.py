"""Signals: what NEXUS reacts to, and where each one came from.

A :class:`Signal` is one observation about one thing in the city (an elevator, a car park, a
data source), already parsed by whoever produced it. NEXUS never fetches anything itself: the
console, as the composition root, turns İBB data into signals and hands them over. That keeps
this package a library with no network, no İBB client and no model SDK in its import graph.

Every signal carries an :class:`Origin`: the source, its address, when the source observed the
thing and whether the value is live, recorded or a timetable. The console renders it as the
public ``Provenance`` object (:meth:`Origin.as_provenance`), so every card and every decision
can say where its facts came from and how old they are.

Times are timezone-aware UTC throughout. A naive datetime is refused at the boundary rather
than guessed at: an hour's error in "how old is this" is exactly the error the product exists
to avoid.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Severity = Literal["info", "warning", "critical"]
SourceMode = Literal["live", "recorded", "schedule", "unknown"]
#: Returns "now". Injected everywhere so a test, or a replay, can fix the time.
Clock = Callable[[], dt.datetime]

#: Queue titles (Turkish, user-facing) for the signal kinds the missions know. An unknown kind
#: is shown by its code rather than dropped.
SIGNAL_TITLES: dict[str, str] = {
    "equipment_fault": "Asansör ya da yürüyen merdiven kullanılamıyor",
    "long_outage": "Uzun süren arıza",
    "hub_faults": "Aynı aktarma merkezinde birden çok arıza",
    "source_stale": "Kaynak bayat ya da yanıt vermiyor",
    "parking_full": "Otopark doluyor",
    "air_quality": "Hava kalitesi",
    "bus_bunching": "Otobüs yığılması",
}


def system_clock() -> dt.datetime:
    """The wall clock, in UTC."""
    return dt.datetime.now(dt.UTC)


def as_utc(value: dt.datetime) -> dt.datetime:
    """``value`` in UTC; a naive datetime is an error, never assumed to be local or UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("naive datetime: NEXUS needs a timezone-aware time")
    return value.astimezone(dt.UTC)


class Origin(BaseModel):
    """Where a fact came from: the source, its address, when it was observed, and how."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(min_length=1, max_length=200)
    url: str | None = None
    observed_at: dt.datetime | None = None
    mode: SourceMode = "unknown"

    @field_validator("observed_at")
    @classmethod
    def _utc(cls, value: dt.datetime | None) -> dt.datetime | None:
        return None if value is None else as_utc(value)

    def age_s(self, now: dt.datetime) -> int | None:
        """Whole seconds since the source observed the fact; ``None`` when it did not say."""
        if self.observed_at is None:
            return None
        return max(0, int((as_utc(now) - self.observed_at).total_seconds()))

    def as_provenance(self, now: dt.datetime) -> dict[str, Any]:
        """The console API's ``Provenance`` object, with the age measured at ``now``."""
        return {
            "source": self.source,
            "url": self.url,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "age_s": self.age_s(now),
            "mode": self.mode,
        }


class Signal(BaseModel):
    """One observation NEXUS routes: to a reflex rule, or to the Arena and a human."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signal_id: str = Field(min_length=1, max_length=128)
    kind: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)
    entity_id: str = Field(min_length=1, max_length=200)
    severity: Severity
    observed_at: dt.datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    provenance: Origin

    @field_validator("observed_at")
    @classmethod
    def _utc(cls, value: dt.datetime) -> dt.datetime:
        return as_utc(value)

    @classmethod
    def create(
        cls,
        *,
        kind: str,
        entity_id: str,
        severity: Severity,
        observed_at: dt.datetime,
        provenance: Origin,
        payload: dict[str, Any] | None = None,
    ) -> Signal:
        """A signal whose id is derived from what it observed, so replaying a snapshot is idempotent."""
        seed = f"{kind}|{entity_id}|{as_utc(observed_at).isoformat()}"
        signal_id = "sig-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
        return cls(
            signal_id=signal_id,
            kind=kind,
            entity_id=entity_id,
            severity=severity,
            observed_at=observed_at,
            provenance=provenance,
            payload=dict(payload or {}),
        )

    @property
    def title(self) -> str:
        """The queue title for this kind of signal, in Turkish."""
        return SIGNAL_TITLES.get(self.kind, self.kind)
