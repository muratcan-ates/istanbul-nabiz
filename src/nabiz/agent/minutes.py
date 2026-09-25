"""The single-minute arrival rule, shared by the arrival card and the chat.

The owner's rule (product principles §4.4): an arrival is one whole minute, "7 dk", never a
range and never a decimal. Under a minute is "1 dk" (never "şimdi"). A timetable estimate
has no number at all, because ``ibb_mcp.eta`` counts it to the planned departure from the
terminus, not to the rider's stop; stale data says "tarifeye göre" the same way. Rounding
is down on purpose: missing the bus costs more than waiting a minute for it.

:func:`shown_minutes` is the rule; ``nabiz.console.arrival`` builds the card from it, and the
agent writes its answer from it (the text also rides in the tool payload, so the model reads
the same "7 dk" the card shows and the faithfulness check finds its number there).
"""

from __future__ import annotations

import math
from typing import Any

UNVERIFIED = "doğrulanamadı"
BY_TIMETABLE = "tarifeye göre"
#: How each estimate was made, in the words a rider reads.
METHOD_TR = {"stop_sequence": "durak sırasına göre", "distance": "mesafeye göre", "schedule": "tarifeye göre"}


def shown_minutes(eta_minutes: float | None, method: str | None, *, stale: bool) -> tuple[int | None, str]:
    """The whole minute to show and its text: ``(7, "7 dk")``, or ``(None, "tarifeye göre")``."""
    if eta_minutes is None or not method:
        return None, UNVERIFIED
    if method == "schedule" or stale:
        return None, BY_TIMETABLE
    minutes = max(1, math.floor(eta_minutes))
    return minutes, f"{minutes} dk"


def with_shown_minutes(data: Any, *, stale: bool) -> Any:
    """A tool payload's ``arrivals`` with the text each one may be shown as (``shown``)."""
    if not isinstance(data, dict) or not isinstance(data.get("arrivals"), list):
        return data
    arrivals = [
        {**a, "shown": shown_minutes(a.get("eta_minutes"), a.get("method"), stale=stale)[1]} if isinstance(a, dict) else a
        for a in data["arrivals"]
    ]
    return {**data, "arrivals": arrivals}
