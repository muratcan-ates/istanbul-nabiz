"""The step-free port bound to İBB's lift records and to the operator's approvals.

``GET /api/alternative`` and the home page's lift cards ask one question: is this station's
lift listed as unusable, and if so where else can a person get on or off without steps. The
answer comes from ``Nabiz.accessible_alternative`` (İBB's list and the metro graph). What this
module adds is the contract's ``operator_approved``: true only while an approval the simulated
operator gave for this station's current outage is still active in the ledger
(``nexus_core`` calls it an approved alternative, OA), and then the citizen card shows the
text the operator approved instead of the machine's suggestion.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ibb_mcp.text import fold_tr
from ibb_mcp.tools import Nabiz
from nabiz.console.cards import provenance_view
from nexus_core import NexusEngine
from nexus_core.approved import Binding

LIFT_STATUSES = frozenset({"working", "out_of_service", "unknown"})


def _same_station(a: Any, b: Any) -> bool:
    return isinstance(a, str) and isinstance(b, str) and fold_tr(a) == fold_tr(b)


class StepFreeService:
    """:class:`~nabiz.console.ports.StepFreePort` over the facade and, when bound, the decision core."""

    def __init__(self, nabiz: Nabiz, engine: NexusEngine | None = None, *, offline: bool) -> None:
        self.nabiz = nabiz
        self.engine = engine
        self.offline = offline

    def approved_for(self, station: str, alternative: dict[str, Any] | None, outage_ids: Sequence[str]) -> Binding | None:
        """The active approval for this station's current outage, when it names the alternative shown now.

        One approval covers one outage (``nexus_core.approved``): a new fault at the same
        station is a new outage the operator has not seen, so it gets no badge.
        """
        if self.engine is None or alternative is None or not outage_ids:
            return None
        states = self.engine.states()
        for binding in self.engine.bindings():
            state = states.get(binding.approved_signal_id)
            if state is None or not _same_station(state.signal.payload.get("station"), station):
                continue
            if binding.outage_id in outage_ids and _same_station(binding.alternative_station, alternative.get("station")):
                return binding
        return None

    async def alternative(self, station: str, needs: Sequence[str]) -> dict[str, Any]:
        result = await self.nabiz.accessible_alternative(station, list(needs) or None)
        data = result.data
        raw = data.get("alternative")
        alternative = None
        if raw:
            alternative = {k: raw.get(k) for k in ("station", "line", "extra_minutes", "reason")}
        lift = data.get("lift_status")
        view: dict[str, Any] = {
            "station": data.get("station", station),
            "lift_status": lift if lift in LIFT_STATUSES else "unknown",
            "alternative": alternative,
            "operator_approved": False,
            "provenance": provenance_view(result.provenance, offline=self.offline, mode=data.get("mode")),
            "text": data.get("text"),
            "uncertainty": data.get("uncertainty", []),
            "stale": bool(data.get("stale")),
        }
        outages = [o for o in data.get("outage_ids") or [] if isinstance(o, str)]
        binding = self.approved_for(view["station"], alternative, outages)
        if binding is not None and alternative is not None:
            # The machine's reason ends "operatör onayı taşımaz"; once a person approved, the page
            # shows the approved text instead, so the card never says both.
            alternative["reason"] = f"{binding.text} (Simüle operatör onayladı.)"
            view.update(operator_approved=True, approved_text=binding.text)
        return view
