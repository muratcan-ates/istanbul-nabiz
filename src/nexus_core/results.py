"""Immutable result shapes returned by the NEXUS engine."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from nexus_core.decisions import Decision, Status
from nexus_core.receipts import RunReceipt
from nexus_core.reflex import Action


class ProcessResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    signal_id: str
    path: Literal["reflex", "arena"]
    status: Status
    rule_id: str | None = None
    reasons: tuple[str, ...] = ()
    action: Action | None = None
    decision: Decision | None = None
    reflex_ms: float | None = None
    receipt: RunReceipt | None = None
    duplicate: bool = False
