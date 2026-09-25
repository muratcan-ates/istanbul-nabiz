# Adapted from CloudSentinel app/analytics.py (github.com/muratcan-ates/cloudsentinel @ 80938ae), MIT License,
# Copyright (c) 2026 CloudSentinel Team (YZTA Bootcamp 2026, Group 60). See NOTICE.md.
"""Measured, read-only receipts for one NEXUS signal run."""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RunReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    signal_id: str
    path: Literal["reflex", "arena"]
    reflex_ms: float | None
    arena_ms: float | None
    wall_ms: float = Field(ge=0)
    llm_calls: int = Field(ge=0)
    usd: float | None = Field(default=None, ge=0)


def receipt_of(state: Any, usd_per_call: float | None = None) -> RunReceipt | None:
    """Read a sealed receipt without making a model call or mutating the ledger."""
    receipt = state.receipt
    if receipt is None:
        return None
    if usd_per_call is None:
        return receipt
    return receipt.model_copy(update={"usd": round(receipt.llm_calls * usd_per_call, 6)})


def calls_made(port: object) -> int | None:
    """Read an optional model-port counter without assuming every port exposes one."""
    try:
        value = getattr(port, "calls_made", None)
    except Exception:  # noqa: BLE001 - a broken optional metric cannot break a decision
        return None
    return value if isinstance(value, int) and value >= 0 else None


def count_calls(before: int | None, after: int | None, author: str, seat_count: int) -> int:
    """Prefer a measured counter delta; use the documented port-author fallback otherwise."""
    if before is not None and after is not None and after >= before:
        return after - before
    return 0 if author == "kural" else seat_count


def make_receipt(
    *,
    signal_id: str,
    path: Literal["reflex", "arena"],
    reflex_ms: float | None,
    arena_ms: float | None,
    wall_ms: float,
    llm_calls: int,
    usd_per_call: float | None,
) -> RunReceipt:
    usd = round(llm_calls * usd_per_call, 6) if usd_per_call is not None else None
    return RunReceipt(
        signal_id=signal_id,
        path=path,
        reflex_ms=reflex_ms,
        arena_ms=arena_ms,
        wall_ms=max(0.0, wall_ms),
        llm_calls=llm_calls,
        usd=usd,
    )


def elapsed_ms(started: float) -> float:
    """Milliseconds elapsed on the monotonic process clock."""
    return round((time.perf_counter() - started) * 1000, 3)
