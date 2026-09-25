"""Builders shared by the ``test_nexus_core_*`` files: a settable clock, signals, an engine.

Every NEXUS test runs on a fixed clock and a ledger in ``tmp_path``; none touches
``data/nexus/nexus.db`` or the network.
"""

from __future__ import annotations

import datetime as dt
import pathlib
from typing import Any

from conftest import REPO_ROOT

from nexus_core.arena import ArenaPort
from nexus_core.decisions import Approval, Operator
from nexus_core.engine import NexusEngine
from nexus_core.ledger import Ledger
from nexus_core.missions import Mission, load_missions
from nexus_core.signals import Origin, Signal

T0 = dt.datetime(2026, 9, 25, 9, 0, tzinfo=dt.UTC)
MISSIONS_DIR = REPO_ROOT / "missions"
METRO_URL = "https://api.ibb.gov.tr/MetroIstanbul/api/MetroMobile/V2/GetFaultyEquipmentDetails"


class Clock:
    """A clock the test moves by hand."""

    def __init__(self, now: dt.datetime = T0) -> None:
        self.now = now

    def __call__(self) -> dt.datetime:
        return self.now

    def advance(self, **delta: float) -> dt.datetime:
        self.now += dt.timedelta(**delta)
        return self.now


def origin(observed_at: dt.datetime | None = T0, *, source: str = "Metro İstanbul", mode: str = "live") -> Origin:
    return Origin(source=source, url=METRO_URL, observed_at=observed_at, mode=mode)


def make_signal(
    kind: str = "equipment_fault",
    *,
    entity: str = "M2-TAKSIM-ASN-01",
    observed_at: dt.datetime = T0,
    severity: str = "warning",
    provenance: Origin | None = None,
    **payload: Any,
) -> Signal:
    return Signal.create(
        kind=kind,
        entity_id=entity,
        severity=severity,
        observed_at=observed_at,
        provenance=provenance or origin(observed_at),
        payload=payload,
    )


def elevator(outage: str = "ASN-01@2026-09-25T08:00", *, observed_at: dt.datetime = T0, **extra: Any) -> Signal:
    """An elevator out of service at Taksim, with a step-free alternative in the same snapshot."""
    payload: dict[str, Any] = {
        "station": "Taksim",
        "line": "M2",
        "equipment_type": "elevator",
        "outage_id": outage,
        "alternative_station": "Şişhane",
        "alternative_line": "M2",
        "alternative_faulty": False,
        "extra_minutes": 4,
    }
    payload.update(extra)
    return make_signal(observed_at=observed_at, **{k: v for k, v in payload.items() if v is not None})


def escalator(**extra: Any) -> Signal:
    payload = {"station": "Kadıköy", "equipment_type": "escalator", "outage_id": "YM-07@2026-09-25"} | extra
    return make_signal(entity="M4-KADIKOY-YM-07", **{k: v for k, v in payload.items() if v is not None})


def missions() -> list[Mission]:
    return load_missions(MISSIONS_DIR)


def build_engine(tmp_path: pathlib.Path, clock: Clock, *, arena: ArenaPort | None = None, **kwargs: Any) -> NexusEngine:
    ledger = Ledger(tmp_path / "nexus.db", clock=clock)
    return NexusEngine(ledger, kwargs.pop("mission_list", None) or missions(), arena=arena, clock=clock, **kwargs)


OPERATOR = Operator(handle="op-1")


def approve(signal_id: str, action: str = "approve", reason: str = "", edited_text: str | None = None) -> Approval:
    return Approval(signal_id=signal_id, action=action, reason=reason, edited_text=edited_text, actor=OPERATOR)
