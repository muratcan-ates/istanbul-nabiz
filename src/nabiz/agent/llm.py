"""The swappable model client. One protocol, four possible providers, none required.

WHY this is the most constrained piece of the project: the model is the only component
whose availability cannot be guaranteed. Azure for Students subscriptions frequently ship
with **zero** Azure OpenAI quota (Microsoft staff said so in July 2026), GitHub Models was
retired on 2026-07-30, and a quota request may be approved halfway through the sprint. So
nothing above this module may name a provider. Everything speaks the OpenAI-compatible
``/chat/completions`` shape and the endpoint is three environment variables:

    NABIZ_LLM_BASE_URL   https://<resource>.openai.azure.com/openai/v1
                         http://localhost:5273/v1          (Foundry Local)
                         https://<anything>/v1             (any compatible gateway)
    NABIZ_LLM_API_KEY    empty for Foundry Local
    NABIZ_LLM_MODEL      gpt-4.1-mini · phi-4-mini · qwen2.5-7b

If none of them is set we probe Foundry Local's default port on this machine, and if that
is closed too the provider is ``none``: :func:`available` returns False, and the agent
falls back to its deterministic mode instead of crashing. A demo that still answers with
zero model quota is worth more than a demo that needs one.

The ``openai`` package is used when installed and raw ``httpx`` otherwise. Both paths go
through the same normaliser, so the caller always receives
``{"content", "tool_calls", "usage", "model", "finish_reason", "raw"}`` and never sees an
SDK object. That is what lets the eval harness record a run without importing the SDK.
"""

from __future__ import annotations

import json
import logging
import os
import socket
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

import httpx

log = logging.getLogger("nabiz.agent.llm")

Provider = Literal["azure_openai", "foundry_local", "openai_compatible", "none"]

#: Foundry Local's default OpenAI-compatible port. Documented by the CLI (`foundry service
#: status`); probing it is what makes "just run the agent on the laptop" work with no config.
FOUNDRY_LOCAL_URL = "http://localhost:5273/v1"
FOUNDRY_LOCAL_HOST = ("127.0.0.1", 5273)

#: Both spellings are accepted: DECISIONS #5 writes ``LLM_BASE_URL``, ``.env.example``
#: writes ``NABIZ_LLM_BASE_URL``. The prefixed name wins so a shell-wide LLM_* export for
#: some other project cannot silently steer this agent.
_ENV_KEYS = {
    "base_url": ("NABIZ_LLM_BASE_URL", "LLM_BASE_URL"),
    "api_key": ("NABIZ_LLM_API_KEY", "LLM_API_KEY"),
    "model": ("NABIZ_LLM_MODEL", "LLM_MODEL"),
}

SETUP_HELP = (
    "LLM yapılandırılmadı. Şunlardan birini ayarlayın:\n"
    "  NABIZ_LLM_BASE_URL, NABIZ_LLM_MODEL (ve gerekiyorsa NABIZ_LLM_API_KEY)\n"
    "  · Azure OpenAI   https://<kaynak>.openai.azure.com/openai/v1\n"
    "  · Foundry Local  http://localhost:5273/v1  (anahtar gerekmez; 'foundry model run phi-4-mini')\n"
    "  · OpenAI uyumlu  https://<sunucu>/v1\n"
    "Model olmadan ajan yine çalışır: deterministic mod anahtar kelimeyle araca yönlendirir."
)


class LlmError(RuntimeError):
    """Any failure talking to the model endpoint."""


class LlmUnavailable(LlmError):
    """No endpoint is configured. Carries the setup instructions, not a stack trace."""


@dataclass(frozen=True)
class LlmConfig:
    """Where the model lives. Frozen so a run can record exactly what it used."""

    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    provider: Provider = "none"
    timeout: float = 60.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, *, probe: bool = True) -> LlmConfig:
        """Read the environment, then fall back to a local Foundry service if one is up.

        ``probe`` is switchable because the fallback opens a TCP socket: tests and CI must
        be able to ask for "the configuration as written" without touching the machine.
        """
        env = os.environ if env is None else env
        values = {field: _first(env, names) for field, names in _ENV_KEYS.items()}
        base_url, api_key, model = values["base_url"], values["api_key"], values["model"]

        if base_url:
            return cls(
                base_url=base_url.rstrip("/"),
                api_key=api_key or None,
                model=model or None,
                provider=detect_provider(base_url),
            )
        if probe and env.get("NABIZ_LLM_NO_PROBE", "").lower() not in {"1", "true", "yes"} and foundry_local_running():
            log.info("no LLM configured; found Foundry Local on %s:%s", *FOUNDRY_LOCAL_HOST)
            return cls(base_url=FOUNDRY_LOCAL_URL, api_key=None, model=model or None, provider="foundry_local")
        return cls(model=model or None, provider="none")

    @property
    def configured(self) -> bool:
        return self.provider != "none" and bool(self.base_url)

    def describe(self) -> str:
        """A one-line, key-free summary safe to write into an eval report."""
        if not self.configured:
            return "provider=none (deterministic mode)"
        return (
            f"provider={self.provider} model={self.model or '<auto>'} "
            f"base_url={self.base_url} key={'yes' if self.api_key else 'no'}"
        )


def _first(env: Mapping[str, str], names: Sequence[str]) -> str | None:
    for name in names:
        value = (env.get(name) or "").strip()
        if value:
            return value
    return None


def detect_provider(base_url: str) -> Provider:
    """Classify an endpoint by its URL. Only affects headers and reporting, never routing."""
    host = base_url.lower()
    if "openai.azure.com" in host or "cognitiveservices.azure.com" in host:
        return "azure_openai"
    if ":5273" in host or "foundry" in host:
        return "foundry_local"
    return "openai_compatible"


def foundry_local_running(host: tuple[str, int] = FOUNDRY_LOCAL_HOST, timeout: float = 0.25) -> bool:
    """Is something listening on Foundry Local's port? A TCP connect, not an HTTP call."""
    try:
        with socket.create_connection(host, timeout=timeout):
            return True
    except OSError:
        return False


def available(config: LlmConfig | None) -> bool:
    """True when :func:`chat` can be called at all."""
    return bool(config and config.configured)


def require(config: LlmConfig | None) -> LlmConfig:
    """Return the config or explain, in one message, exactly what to set."""
    if config is None or not config.configured:
        raise LlmUnavailable(SETUP_HELP)
    return config


def _headers(config: LlmConfig) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
        if config.provider == "azure_openai":
            # The Azure v1 surface accepts either; sending both survives a resource that
            # was created before the OpenAI-compatible route was enabled.
            headers["api-key"] = config.api_key
    return headers


def _normalise(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten a chat completion into the shape the agent uses. Never raises on shape."""
    choices = raw.get("choices") or [{}]
    choice = choices[0] if isinstance(choices, list) and choices else {}
    message = choice.get("message") or {}
    calls: list[dict[str, Any]] = []
    for position, call in enumerate(message.get("tool_calls") or []):
        function = call.get("function") or {}
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except ValueError:
                # A small local model that emits malformed JSON must not kill the turn;
                # the agent reports the bad call back to the model as a tool error.
                arguments = {"__unparsed__": function.get("arguments")}
        calls.append(
            {
                "id": call.get("id") or f"call_{position}",
                "name": function.get("name") or call.get("name") or "",
                "arguments": arguments if isinstance(arguments, dict) else {},
            }
        )
    return {
        "content": message.get("content"),
        "tool_calls": calls,
        "usage": dict(raw.get("usage") or {}),
        "model": raw.get("model"),
        "finish_reason": choice.get("finish_reason"),
        "raw": raw,
    }


async def discover_model(config: LlmConfig, *, client: httpx.AsyncClient | None = None) -> str | None:
    """Ask the endpoint which model it is serving.

    Foundry Local's loaded model gets a machine-specific id (``phi-4-mini-cuda-gpu`` and
    friends), so hard-coding one in the environment is exactly the wrong move on a laptop
    whose accelerator we do not control.
    """
    config = require(config)
    owns = client is None
    client = client or httpx.AsyncClient(timeout=config.timeout)
    try:
        response = await client.get(f"{config.base_url}/models", headers=_headers(config))
        response.raise_for_status()
        data = response.json().get("data") or []
        return data[0].get("id") if data else None
    except (httpx.HTTPError, ValueError, AttributeError, IndexError) as exc:
        log.info("model discovery failed on %s: %r", config.base_url, exc)
        return None
    finally:
        if owns:
            await client.aclose()


async def resolve_model(config: LlmConfig) -> LlmConfig:
    """Fill in ``model`` from the endpoint when the environment did not name one."""
    if config.model or not available(config):
        return config
    discovered = await discover_model(config)
    if not discovered:
        raise LlmError(
            f"{config.base_url} bir model adı vermedi. NABIZ_LLM_MODEL ayarlayın "
            "(ör. gpt-4.1-mini, phi-4-mini)."
        )
    return replace(config, model=discovered)


async def chat(
    config: LlmConfig,
    messages: Sequence[Mapping[str, Any]],
    tools: Sequence[Mapping[str, Any]] | None = None,
    **kw: Any,
) -> dict[str, Any]:
    """One chat completion. Returns ``{content, tool_calls, usage, model, ...}``.

    Extra keyword arguments (``temperature``, ``max_tokens``, ``tool_choice`` …) are passed
    through verbatim, so a provider-specific knob does not need a change here.
    """
    config = await resolve_model(require(config))
    payload: dict[str, Any] = {"model": config.model, "messages": list(messages)}
    if tools:
        payload["tools"] = list(tools)
        payload.setdefault("tool_choice", "auto")
    payload.update({key: value for key, value in kw.items() if value is not None})

    try:
        from openai import AsyncOpenAI  # noqa: PLC0415 - optional dependency, imported late
    except ImportError:
        return await _chat_httpx(config, payload)

    client = AsyncOpenAI(
        base_url=config.base_url,
        api_key=config.api_key or "not-needed",  # Foundry Local rejects an empty string
        default_headers={"api-key": config.api_key} if config.provider == "azure_openai" and config.api_key else None,
        timeout=config.timeout,
    )
    try:
        completion = await client.chat.completions.create(**payload)
    except Exception as exc:  # noqa: BLE001 - the SDK raises a family of its own errors
        raise LlmError(f"{config.provider} çağrısı başarısız: {exc}") from exc
    finally:
        await client.close()
    return _normalise(completion.model_dump())


async def _chat_httpx(config: LlmConfig, payload: Mapping[str, Any]) -> dict[str, Any]:
    """The no-dependency path: POST /chat/completions ourselves."""
    url = f"{config.base_url}/chat/completions"
    async with httpx.AsyncClient(timeout=config.timeout) as client:
        try:
            response = await client.post(url, json=dict(payload), headers=_headers(config))
        except httpx.HTTPError as exc:
            raise LlmError(f"{url} adresine ulaşılamadı: {exc}") from exc
        if response.status_code >= 400:
            raise LlmError(f"{url} {response.status_code}: {response.text[:400]}")
        try:
            return _normalise(response.json())
        except ValueError as exc:
            raise LlmError(f"{url} geçerli JSON döndürmedi: {response.text[:200]}") from exc
