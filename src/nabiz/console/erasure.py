"""Account deletion manifest and fail-closed hook coordinator for P00 integration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

# Browser-only guest data is intentionally absent. The page must describe it separately.
REQUIRED_HOOKS = (
    "account_memory", "citizen_requests", "email_outbox", "family_links",
    "quota", "sessions", "account",
)


class ErasureIncomplete(RuntimeError):
    """Some account data may remain; never report full deletion to the user."""

    def __init__(self, completed: tuple[str, ...], failed: str) -> None:
        self.completed = completed
        self.failed = failed
        super().__init__("Hesap verilerinin silinmesi tamamlanamadı.")


@dataclass(frozen=True)
class ErasureResult:
    account_id: str
    completed: tuple[str, ...]


class ErasureChain:
    """The integrator registers each module's account-scoped deletion function."""

    def __init__(self, hooks: Mapping[str, Callable[[str], object]]) -> None:
        self.hooks = dict(hooks)

    def erase(self, account_id: str) -> ErasureResult:
        if not account_id:
            raise ValueError("Account id required")
        missing = tuple(name for name in REQUIRED_HOOKS if name not in self.hooks)
        if missing:
            raise ErasureIncomplete((), ", ".join(missing))
        completed: list[str] = []
        for name in REQUIRED_HOOKS:
            try:
                result = self.hooks[name](account_id)
                if result is False:
                    raise ErasureIncomplete(tuple(completed), name)
            except ErasureIncomplete:
                raise
            except Exception as exc:
                raise ErasureIncomplete(tuple(completed), name) from exc
            completed.append(name)
        return ErasureResult(account_id, tuple(completed))
