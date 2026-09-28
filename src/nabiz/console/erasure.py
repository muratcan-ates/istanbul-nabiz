"""Account deletion manifest and fail-closed hook coordinator for P00 integration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

# Browser-only guest data is intentionally absent. The page must describe it separately.
# P00 D2a (H): the owner's order; the account row goes last, so a failure leaves it to retry.
REQUIRED_HOOKS = (
    "calendar_plans", "outlook_tokens", "appeals", "bookings", "journeys", "photo_reports", "account_memory",
    "citizen_requests", "email_outbox", "family_links", "quota", "sessions", "account",
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
    results: dict[str, object] = field(default_factory=dict)  # what each hook returned (counts), in order


class ErasureChain:
    """The integrator registers each module's account-scoped deletion function."""

    def __init__(self, hooks: Mapping[str, Callable[[str], object]]) -> None:
        unknown = sorted(set(hooks) - set(REQUIRED_HOOKS))
        if unknown:
            raise ValueError(f"Unknown erasure hook: {', '.join(unknown)}")
        self.hooks = dict(hooks)

    def erase(self, account_id: str) -> ErasureResult:
        if not account_id:
            raise ValueError("Account id required")
        missing = tuple(name for name in REQUIRED_HOOKS if name not in self.hooks)
        if missing:
            raise ErasureIncomplete((), ", ".join(missing))
        completed: list[str] = []
        results: dict[str, object] = {}
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
            results[name] = result
        return ErasureResult(account_id, tuple(completed), results)
