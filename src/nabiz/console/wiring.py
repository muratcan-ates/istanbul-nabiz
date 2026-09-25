"""Bind the ports to the real implementations: the decision core, the lift records, the model.

:func:`wire_ports` is the one place the product app meets ``nexus_core``. It opens the
ledger (``NEXUS_DB_PATH``, default ``data/nexus/nexus.db``, gitignored), loads every
``missions/*.toml`` (``NEXUS_MISSIONS_DIR`` overrides the folder: an installed package has no
repository around it), chooses the Arena's seats (the model when ``NABIZ_LLM_*`` configures one,
the core's rule-based seats otherwise, on the Arena's own spend guard) and returns the two ports
the routes call. No rule loaded is a refusal to start, not an engine that sends everything to a
person and closes nothing. It runs
inside the app's lifespan, after the shared facade exists, and only when the app is built with
``wire_nexus=True`` (``python -m nabiz.console`` does; the tests pass their own ports).

Recorded replays (``POST /api/console/simulate``) read ``tests/fixtures`` through a second,
offline facade whatever the app's own mode, so a replay never reaches İBB.
"""

from __future__ import annotations

import dataclasses
import math
import os
import pathlib
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from ibb_mcp.config import REPO_ROOT, Settings
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.console.arena_seats import arena_port
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.cards import env_seconds
from nabiz.console.nexus_port import DEFAULT_INGEST_EVERY_S, NexusConsole
from nabiz.console.ports import Ports
from nabiz.console.published import PublishedCards
from nabiz.console.step_free import StepFreeService
from nexus_core import Ledger, Mission, NexusEngine, load_missions

MISSIONS_DIR = REPO_ROOT / "missions"
DEFAULT_LEDGER = REPO_ROOT / "data" / "nexus" / "nexus.db"


def ledger_path(env: Mapping[str, str] | None = None) -> pathlib.Path:
    raw = (os.environ if env is None else env).get("NEXUS_DB_PATH", "").strip()
    return pathlib.Path(raw) if raw else DEFAULT_LEDGER


def missions_dir(env: Mapping[str, str] | None = None) -> pathlib.Path:
    raw = (os.environ if env is None else env).get("NEXUS_MISSIONS_DIR", "").strip()
    return pathlib.Path(raw) if raw else MISSIONS_DIR


def required_missions(directory: pathlib.Path) -> list[Mission]:
    """The missions in ``directory``; none, or none with a rule, stops the app from starting."""
    missions = load_missions(directory)
    if not any(m.rules for m in missions):
        raise RuntimeError(f"no mission rules in {directory.name!r}: set NEXUS_MISSIONS_DIR to the missions folder")
    return missions


class RecordedFacade:
    """An offline facade over the recordings, opened on first use and closed with the app."""

    def __init__(self, nabiz: Nabiz, settings: Settings) -> None:
        self._shared = nabiz if settings.offline else None
        self._settings = dataclasses.replace(settings, offline=True)
        self._own: Nabiz | None = None

    def __call__(self) -> Nabiz:
        if self._shared is not None:
            return self._shared
        if self._own is None:
            self._own = Nabiz(SourceContext.create(settings=self._settings))
        return self._own

    async def aclose(self) -> None:
        if self._own is not None:
            await self._own.aclose()
            self._own = None


def arena_usd_per_call(seats: Any, env: Mapping[str, str] | None = None) -> float | None:
    """What one Arena seat call costs, for the card's cost receipt.

    Rule-based seats (``seats`` is ``None``) make no model call, so their cost is zero: a count,
    not a price. A model seat's price is the owner's, ``NABIZ_ARENA_USD_PER_CALL`` in USD; unset or
    invalid, the receipt shows no cost rather than one quoted from memory (the rule of
    :mod:`nabiz.console.budget`).
    """
    if seats is None:
        return 0.0
    raw = (os.environ if env is None else env).get("NABIZ_ARENA_USD_PER_CALL", "").strip()
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if math.isfinite(value) and value >= 0 else None


def build_engine(llm_config: llm.LlmConfig | None, guard: SpendGuard, *, path: pathlib.Path | None = None) -> NexusEngine:
    """The engine over the ledger and the missions; ``guard`` is the Arena's own, not the chat's."""
    seats = arena_port(llm_config, guard)
    return NexusEngine(
        Ledger(path or ledger_path()), required_missions(missions_dir()), arena=seats, usd_per_call=arena_usd_per_call(seats)
    )


def wire_ports(
    nabiz: Nabiz,
    settings: Settings,
    *,
    llm_config: llm.LlmConfig | None,
    guard: SpendGuard | None = None,
    engine: NexusEngine | None = None,
) -> tuple[Ports, Callable[[], Awaitable[None]]]:
    """The bound ports and the coroutine function that releases what they opened.

    ``guard`` is the Arena's spend guard; by default its own (``BudgetConfig.for_arena``), so the
    seats never spend the chat's ceiling.
    """
    engine = engine or build_engine(llm_config, guard or SpendGuard(BudgetConfig.for_arena()))
    recorded = RecordedFacade(nabiz, settings)
    console = NexusConsole(
        engine,
        nabiz,
        recorded=recorded,
        offline=settings.offline,
        ingest_every_s=env_seconds("NABIZ_CONSOLE_INGEST_S", DEFAULT_INGEST_EVERY_S),
    )
    step_free = StepFreeService(nabiz, engine, offline=settings.offline)
    published = PublishedCards(engine, offline=settings.offline, stale_after_s=engine.stale_after_s)
    return Ports(step_free=step_free, console=console, published=published), recorded.aclose
