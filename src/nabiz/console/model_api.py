"""Read-only status for the model that the citizen chat would use.

This lane found ``llm.pick_rung`` on its base, so it is the sole source for
the active rung. The route does not probe a provider or read the chat service,
which is created only during the app lifespan.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter, Request

from nabiz.agent import llm
from nabiz.console.budget import FREE_PROVIDERS, SpendGuard

model_routes = APIRouter(prefix="/api/model")

PROVIDER_LABEL = {
    "azure_openai": "bulut modeli",
    "openai_compatible": "bulut modeli",
    "foundry_local": "yerel model",
}

NOTE_NO_MODEL = "Şu an cevaplar yapay zekâ modeli olmadan, hazır kurallarla yazılıyor."
NOTE_CAP_RULES = "Bugünkü model sınırı doldu; cevaplar hazır kurallarla yazılıyor."
NOTE_CAP_LOCAL = "Bulut modelinin bugünkü sınırı doldu; cevapları yerel model yazıyor."


def provider_label(provider: str | None) -> str:
    """Return the short label safe to show on either product surface."""
    return PROVIDER_LABEL.get(provider or "", "kural")


def rung_view(rung: llm.LlmConfig) -> dict[str, Any]:
    """Expose provider metadata without leaking a model name, URL, or key."""
    return {
        "provider": rung.provider,
        "label": provider_label(rung.provider),
        "free": rung.provider in FREE_PROVIDERS,
    }


def active_rung(
    config: llm.LlmConfig,
    allows: Callable[[str], bool],
    *,
    env: Mapping[str, str] | None = None,
) -> llm.LlmConfig | None:
    """Use the same ladder decision as chat, including its live environment switch."""
    return llm.pick_rung(config, allows, env=env)


def citizen_note(config: llm.LlmConfig, active: llm.LlmConfig | None, within_budget: bool) -> str | None:
    """Give citizens one plain sentence only when the chat needs an explanation."""
    configured = llm.rungs(config)
    if active is None:
        return NOTE_CAP_RULES if configured else NOTE_NO_MODEL
    first = configured[0] if configured else None
    if active.provider == "foundry_local" and not within_budget and first and first.provider != "foundry_local":
        return NOTE_CAP_LOCAL
    return None


def model_status(
    config: llm.LlmConfig,
    guard: SpendGuard,
    *,
    offline: bool,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the public status contract using only configured state and spend counters."""
    allows = guard.allows
    within_budget = allows(config.provider)
    first = llm.first_rung(config, allows)
    active = active_rung(config, allows, env=env)
    active_provider = active.provider if active else None
    return {
        "offline": offline,
        "configured": bool(llm.rungs(config)),
        "rungs": [rung_view(rung) for rung in llm.rungs(config)],
        "first_rung": {"provider": first.provider, "label": provider_label(first.provider)} if first else None,
        "within_budget": within_budget,
        "ladder": llm.local_on_cap(env),
        "active_author": llm.author_of(active_provider),
        "active_label": provider_label(active_provider),
        "note": citizen_note(config, active, within_budget),
    }


@model_routes.get("/status")
async def model_status_route(request: Request) -> dict[str, Any]:
    """Return the citizen-safe model status without starting discovery or inference."""
    state = request.app.state
    return model_status(state.chat_config, state.guard, offline=state.settings.offline)
