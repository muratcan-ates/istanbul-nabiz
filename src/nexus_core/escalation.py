"""Escalation: when a signal a rule could close goes to a human anyway.

Three deterministic triggers, each with a code the ledger and the console show:

* ``critical``: the signal's severity is ``critical``, or its kind is listed in the missions'
  ``critical_kinds`` (for example several faults at one interchange).
* ``repeat``: the same entity was seen at least ``repeat_threshold`` times within
  ``window_hours``, this signal included. Repeats are counted by outage, not by snapshot: a
  signal whose payload carries an ``outage_id`` counts once per outage, so one long fault
  re-reported every fifteen minutes is one event, not ninety-six.
* ``reflex_failed``: the matched rule could not run (a field its card needs is missing).

None of them asks a model how sure it is. The history comes from a port, so this module does
not know about SQLite; the engine wires it to the ledger.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence

from nexus_core.missions import EscalationSettings
from nexus_core.signals import Signal

CRITICAL = "critical"
REPEAT = "repeat"
REFLEX_FAILED = "reflex_failed"

#: ``(entity_id, since) -> earlier signals for that entity observed at or after ``since``.
HistoryPort = Callable[[str, dt.datetime], Sequence[Signal]]


def outage_key(signal: Signal) -> str:
    """What makes two signals the same event: the payload's ``outage_id``, else the signal itself."""
    outage = signal.payload.get("outage_id")
    return f"outage:{outage}" if isinstance(outage, str) and outage else f"signal:{signal.signal_id}"


class Escalation:
    """Decides, from the signal and its entity's recent history, whether a human must look."""

    def __init__(self, settings: EscalationSettings | None = None, history: HistoryPort | None = None) -> None:
        self.settings = settings or EscalationSettings()
        self._history = history

    @property
    def window(self) -> dt.timedelta:
        return dt.timedelta(hours=self.settings.window_hours)

    def repeats(self, signal: Signal) -> int:
        """Distinct events for this entity inside the window, this signal included."""
        earlier = self._history(signal.entity_id, signal.observed_at - self.window) if self._history else ()
        keys = {outage_key(s) for s in earlier if s.observed_at <= signal.observed_at}
        keys.add(outage_key(signal))
        return len(keys)

    def reasons(self, signal: Signal, repeats: int | None = None) -> tuple[str, ...]:
        """The triggers that fire for ``signal``; empty means the reflex path may run.

        ``repeats`` is :meth:`repeats` when the caller has already counted them.
        """
        found: list[str] = []
        if signal.severity == "critical" or signal.kind in self.settings.critical_kinds:
            found.append(CRITICAL)
        if (self.repeats(signal) if repeats is None else repeats) >= self.settings.repeat_threshold:
            found.append(REPEAT)
        return tuple(found)
