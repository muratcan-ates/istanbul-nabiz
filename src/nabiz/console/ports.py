"""The seams where the decision core and the step-free alternative plug in.

Two other lanes write what sits behind these: ``nexus_core`` (signals, the reflex and arena
paths, human approval, the hash-chained ledger, rule drafts) and the Metro equipment source
with its alternative-station computation. This module fixes only the shapes the routes need,
so the app, its tests and the page can run before either lands, and the integrator binds the
real implementations in one place (:func:`nabiz.console.app.build_console_app`'s ``ports``).

Until then every console call answers 503 "not wired" and the alternative answers
"unknown": an unbound seam says so, it never invents a queue or a lift status.

Error contract for implementations: raise ``LookupError`` (``KeyError`` included) for an
unknown id (the route answers 404), ``ValueError`` for a refused request (400),
:class:`PortConflict` when the state does not allow it (409), and :class:`PortNotWired` when the
backing store is not available (503).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

#: The operator's role label everywhere this prototype records or shows one.
OPERATOR = "Simüle operatör"


class PortNotWired(RuntimeError):
    """The implementation behind a port is not bound in this process."""


class PortConflict(RuntimeError):
    """The request is valid but the state does not allow it (a settled card, no recording): 409."""


class StepFreePort(Protocol):
    """Lift status at a station, and the nearest station whose lift works."""

    async def alternative(self, station: str, needs: Sequence[str]) -> dict[str, Any]:
        """``{station, lift_status, alternative, operator_approved, provenance}`` (the API contract)."""
        ...


class ConsolePort(Protocol):
    """The simulated operator's side of the decision core (``nexus_core``)."""

    async def queue(self) -> dict[str, Any]: ...

    async def decision(self, signal_id: str) -> dict[str, Any]: ...

    async def decide(
        self, signal_id: str, *, action: str, reason: str, edited_text: str | None, actor: str
    ) -> dict[str, Any]: ...

    async def trace(self, signal_id: str) -> dict[str, Any]: ...

    async def verify(self) -> dict[str, Any]: ...

    async def stats(self) -> dict[str, Any]: ...

    async def rule_drafts(self) -> dict[str, Any]: ...

    async def adopt_rule(self, draft_id: str, *, reason: str, actor: str) -> dict[str, Any]: ...

    async def simulate(self, fixture: str) -> dict[str, Any]: ...


class UnwiredStepFree:
    """No equipment data bound: the lift status is unknown, and no alternative is offered."""

    async def alternative(self, station: str, needs: Sequence[str]) -> dict[str, Any]:
        return {
            "station": station,
            "lift_status": "unknown",
            "alternative": None,
            "operator_approved": False,
            "provenance": {"source": "metro_equipment", "url": None, "observed_at": None, "age_s": None, "mode": "unknown"},
        }


class UnwiredConsole:
    """No decision core bound: every call is refused with 503."""

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        async def not_wired(*args: Any, **kwargs: Any) -> dict[str, Any]:
            raise PortNotWired("Karar çekirdeği bu süreçte bağlı değil.")

        return not_wired


@dataclass
class Ports:
    step_free: StepFreePort = field(default_factory=UnwiredStepFree)
    console: ConsolePort = field(default_factory=UnwiredConsole)
