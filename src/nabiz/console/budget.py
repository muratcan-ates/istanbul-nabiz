"""The daily spend ceiling for the paid model: past it, the chat answers by rule, and says so.

The owner set the ceiling (``NABIZ_LLM_DAILY_USD``, default 1.0 USD per İstanbul day). What
a turn costs is priced from the token usage the endpoint reports and the prices the owner
configures (``NABIZ_LLM_PRICE_IN_PER_MTOK`` and ``NABIZ_LLM_PRICE_OUT_PER_MTOK``, USD per
million input and output tokens). No price is written into this code: a price quoted from
memory would make the ceiling a guess. Until both prices are set the ceiling is applied as a
count of model calls instead (``NABIZ_LLM_DAILY_CALLS``, default 100), which is a proxy and
not a dollar figure.

A turn reserves room for the most calls it can make (:meth:`SpendGuard.reserve`) before it
starts and releases it when it has recorded what it spent, all under one lock: twenty turns
arriving at once cannot each see the ceiling unreached. Priced by dollars, a turn's cost is
only known afterwards, so one turn in flight can pass the ceiling by its own cost; the chat
also caps how many model turns run at once. A local model (Foundry Local on this laptop)
bills nobody and is not counted.

The Arena's seats keep their own guard over their own file and ceiling
(:meth:`BudgetConfig.for_arena`): a burst of signals must never leave the citizens' chat
without its model for the rest of the day. The day's total is kept in a small JSON file (``NABIZ_LLM_SPEND_FILE``, default
``data/console/llm_spend.json``, gitignored) so a restart does not reset it. It holds counts
and dollars only: no question, no answer, nothing about who asked.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import pathlib
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ibb_mcp.config import REPO_ROOT
from ibb_mcp.models import ISTANBUL_TZ, utcnow

log = logging.getLogger("nabiz.console.budget")

DEFAULT_DAILY_USD = 1.0
DEFAULT_DAILY_CALLS = 100
DEFAULT_SPEND_FILE = REPO_ROOT / "data" / "console" / "llm_spend.json"
#: The Arena's own ceiling, apart from the chat's. Placeholders until the owner sets them:
#: 30 calls is ten signals with three seats each. ``NABIZ_ARENA_DAILY_USD`` and
#: ``NABIZ_ARENA_DAILY_CALLS`` override them.
ARENA_DAILY_USD = 0.25
ARENA_DAILY_CALLS = 30
#: Providers that cost nothing per call.
FREE_PROVIDERS = frozenset({"foundry_local"})


def _float(env: Mapping[str, str], name: str) -> float | None:
    raw = (env.get(name) or "").strip().replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


@dataclass(frozen=True)
class BudgetConfig:
    daily_usd: float = DEFAULT_DAILY_USD
    price_in_per_mtok: float | None = None
    price_out_per_mtok: float | None = None
    daily_calls: int = DEFAULT_DAILY_CALLS
    state_path: pathlib.Path | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> BudgetConfig:
        env = os.environ if env is None else env
        daily_usd = _float(env, "NABIZ_LLM_DAILY_USD")
        calls = _float(env, "NABIZ_LLM_DAILY_CALLS")
        spend_file = (env.get("NABIZ_LLM_SPEND_FILE") or "").strip()
        return cls(
            daily_usd=DEFAULT_DAILY_USD if daily_usd is None else daily_usd,
            price_in_per_mtok=_float(env, "NABIZ_LLM_PRICE_IN_PER_MTOK"),
            price_out_per_mtok=_float(env, "NABIZ_LLM_PRICE_OUT_PER_MTOK"),
            daily_calls=DEFAULT_DAILY_CALLS if calls is None else int(calls),
            state_path=pathlib.Path(spend_file) if spend_file else DEFAULT_SPEND_FILE,
        )

    @classmethod
    def for_arena(cls, env: Mapping[str, str] | None = None) -> BudgetConfig:
        """The Arena's guard: the same prices, its own ceiling and its own file."""
        env = os.environ if env is None else env
        base = cls.from_env(env)
        daily_usd = _float(env, "NABIZ_ARENA_DAILY_USD")
        calls = _float(env, "NABIZ_ARENA_DAILY_CALLS")
        return cls(
            daily_usd=ARENA_DAILY_USD if daily_usd is None else daily_usd,
            price_in_per_mtok=base.price_in_per_mtok,
            price_out_per_mtok=base.price_out_per_mtok,
            daily_calls=ARENA_DAILY_CALLS if calls is None else int(calls),
            state_path=base.state_path.with_name(f"arena_{base.state_path.name}") if base.state_path else None,
        )

    @property
    def priced(self) -> bool:
        return self.price_in_per_mtok is not None and self.price_out_per_mtok is not None


def _today(clock: Callable[[], dt.datetime]) -> str:
    return clock().astimezone(ISTANBUL_TZ).date().isoformat()


class SpendGuard:
    """Today's model spend, and whether the next turn may use the model."""

    def __init__(self, config: BudgetConfig | None = None, *, clock: Callable[[], dt.datetime] = utcnow) -> None:
        self.config = config or BudgetConfig()
        self._clock = clock
        # record() also runs on worker threads (the Arena's seats), so every read and write of
        # the day's count holds this lock.
        self._lock = threading.Lock()
        self._held = 0
        self._state = self._load()

    def _blank(self) -> dict[str, Any]:
        return {"day": _today(self._clock), "usd": 0.0, "calls": 0, "prompt_tokens": 0, "completion_tokens": 0}

    def _load(self) -> dict[str, Any]:
        path = self.config.state_path
        if path is None or not path.is_file():
            return self._blank()
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("spend file unreadable; starting today's count at zero")
            return self._blank()
        return state if isinstance(state, dict) and state.get("day") == _today(self._clock) else self._blank()

    def _current(self) -> dict[str, Any]:
        if self._state.get("day") != _today(self._clock):
            self._state = self._blank()
        return self._state

    def _room(self, calls: int) -> bool:
        """Whether ``calls`` more model calls fit today, counting the room turns in flight hold."""
        state = self._current()
        if self.config.priced:
            return state["usd"] < self.config.daily_usd
        return state["calls"] + self._held + calls <= self.config.daily_calls

    def allows(self, provider: str) -> bool:
        """May the next call use this provider's model?"""
        if provider in FREE_PROVIDERS:
            return True
        with self._lock:
            return self._room(1)

    def reserve(self, provider: str, calls: int) -> bool:
        """Hold room for up to ``calls`` model calls; ``False`` when that would pass today's ceiling."""
        if provider in FREE_PROVIDERS:
            return True
        with self._lock:
            if not self._room(calls):
                return False
            self._held += calls
            return True

    def release(self, provider: str, calls: int) -> None:
        """Give back what :meth:`reserve` held, once the calls made are recorded."""
        if provider in FREE_PROVIDERS:
            return
        with self._lock:
            self._held = max(0, self._held - calls)

    def cost_usd(self, usage: Mapping[str, Any]) -> float:
        if not self.config.priced:
            return 0.0
        prompt = float(usage.get("prompt_tokens") or 0)
        completion = float(usage.get("completion_tokens") or 0)
        return (prompt * self.config.price_in_per_mtok + completion * self.config.price_out_per_mtok) / 1_000_000

    def record(self, provider: str, usage: Mapping[str, Any], calls: int) -> None:
        """Add one turn's model calls and tokens to today's total."""
        if provider in FREE_PROVIDERS:
            return
        with self._lock:
            state = self._current()
            state["calls"] += max(0, int(calls))
            state["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
            state["completion_tokens"] += int(usage.get("completion_tokens") or 0)
            state["usd"] = round(state["usd"] + self.cost_usd(usage), 6)
            self._save()

    def today(self) -> dict[str, Any]:
        """Today's totals and the ceiling in force: dollars when priced, calls otherwise."""
        with self._lock:
            state = dict(self._current())
        state["ceiling"] = (
            {"kind": "usd", "value": self.config.daily_usd}
            if self.config.priced
            else {"kind": "calls", "value": self.config.daily_calls}
        )
        return state

    def _save(self) -> None:
        path = self.config.state_path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # A name of its own: two guards (or two processes) never write one scratch file.
            scratch = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
            scratch.write_text(json.dumps(self._state), encoding="utf-8")
            scratch.replace(path)
        except OSError:
            # The in-memory count still holds the ceiling for this process.
            log.warning("spend file not written; the ceiling holds in memory until restart")
