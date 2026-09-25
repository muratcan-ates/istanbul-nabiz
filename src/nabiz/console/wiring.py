"""Bind the ports to the real implementations: the decision core, the lift records, the model.

:func:`wire_ports` is the one place the product app meets ``nexus_core``. It opens the
ledger (``NEXUS_DB_PATH``, default ``data/nexus/nexus.db``, gitignored), loads every
``missions/*.toml``, chooses the Arena's seats (the model when ``NABIZ_LLM_*`` configures one,
the core's rule-based seats otherwise) and returns the two ports the routes call. It runs
inside the app's lifespan, after the shared facade exists, and only when the app is built with
``wire_nexus=True`` (``python -m nabiz.console`` does; the tests pass their own ports).

Recorded replays (``POST /api/console/simulate``) read ``tests/fixtures`` through a second,
offline facade whatever the app's own mode, so a replay never reaches İBB.
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
from collections.abc import Awaitable, Callable, Mapping

from ibb_mcp.config import REPO_ROOT, Settings
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.console.arena_seats import arena_port
from nabiz.console.budget import SpendGuard
from nabiz.console.cards import env_seconds
from nabiz.console.nexus_port import DEFAULT_INGEST_EVERY_S, NexusConsole
from nabiz.console.ports import Ports
from nabiz.console.step_free import StepFreeService
from nexus_core import Ledger, NexusEngine, load_missions

MISSIONS_DIR = REPO_ROOT / "missions"
DEFAULT_LEDGER = REPO_ROOT / "data" / "nexus" / "nexus.db"


def ledger_path(env: Mapping[str, str] | None = None) -> pathlib.Path:
    raw = (os.environ if env is None else env).get("NEXUS_DB_PATH", "").strip()
    return pathlib.Path(raw) if raw else DEFAULT_LEDGER


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


def build_engine(llm_config: llm.LlmConfig | None, guard: SpendGuard, *, path: pathlib.Path | None = None) -> NexusEngine:
    return NexusEngine(Ledger(path or ledger_path()), load_missions(MISSIONS_DIR), arena=arena_port(llm_config, guard))


def wire_ports(
    nabiz: Nabiz,
    settings: Settings,
    *,
    llm_config: llm.LlmConfig | None,
    guard: SpendGuard,
    engine: NexusEngine | None = None,
) -> tuple[Ports, Callable[[], Awaitable[None]]]:
    """The bound ports and the coroutine function that releases what they opened."""
    engine = engine or build_engine(llm_config, guard)
    recorded = RecordedFacade(nabiz, settings)
    console = NexusConsole(
        engine,
        nabiz,
        recorded=recorded,
        offline=settings.offline,
        ingest_every_s=env_seconds("NABIZ_CONSOLE_INGEST_S", DEFAULT_INGEST_EVERY_S),
    )
    step_free = StepFreeService(nabiz, engine, offline=settings.offline)
    return Ports(step_free=step_free, console=console), recorded.aclose
