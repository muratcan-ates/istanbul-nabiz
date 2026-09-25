"""The swappable model client. One protocol, four possible providers, none required.

WHY this is the most constrained piece of the project: the model is the only component
whose availability cannot be guaranteed. Azure for Students subscriptions frequently ship
with **zero** Azure OpenAI quota (Microsoft staff said so in July 2026), GitHub Models was
retired on 2026-07-30, and a quota request may be approved halfway through the sprint. So
nothing above this module may name a provider. Everything speaks the OpenAI-compatible
``/chat/completions`` shape and its endpoint is configured with these variables:

    NABIZ_LLM_BASE_URL      https://<resource>.openai.azure.com/openai/v1
                            http://localhost:5273/v1          (Foundry Local)
                            https://<anything>/v1             (any compatible gateway)
    NABIZ_LLM_API_KEY    empty for Foundry Local
    NABIZ_LLM_MODEL      gpt-4.1-mini · phi-4-mini · qwen2.5-7b
    NABIZ_FOUNDRY_LOCAL_URL optional dynamic local endpoint

If no cloud endpoint is set, we discover Foundry Local or use its default port; if neither
is available, the provider is ``none`` and the agent falls back to deterministic mode. A
demo that still answers with zero model quota is worth more than a demo that needs one.

The ``openai`` package is used when installed and raw ``httpx`` otherwise. Both paths go
through the same normaliser, so the caller always receives
``{"content", "tool_calls", "usage", "model", "finish_reason", "provider", "raw"}`` and
never sees an SDK object. That is what lets the eval harness record a run without importing
the SDK.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import cache
from typing import Any, Literal

import httpx

from ibb_mcp.telemetry import span

log = logging.getLogger("nabiz.agent.llm")

Provider = Literal["azure_openai", "foundry_local", "openai_compatible", "none"]

#: Foundry Local's older default OpenAI-compatible port.
FOUNDRY_LOCAL_URL = "http://127.0.0.1:5273/v1"
FOUNDRY_LOCAL_HOST = ("127.0.0.1", 5273)
_LOCAL_URL_RE = re.compile(r"https?://(localhost|127\.0\.0\.1):(\d+)")

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
    "  NABIZ_FOUNDRY_LOCAL_URL (Foundry Local dinamik port seçerse)\n"
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
    fallback: LlmConfig | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, *, probe: bool = True) -> LlmConfig:
        """Read the environment and attach a local Foundry endpoint as a fallback.

        ``probe`` is switchable because discovery may start a CLI process or open a local
        socket. An explicit local URL remains usable with probing disabled.
        """
        env = os.environ if env is None else env
        values = {field: _first(env, names) for field, names in _ENV_KEYS.items()}
        base_url, api_key, model = values["base_url"], values["api_key"], values["model"]
        if base_url:
            config = cls(
                base_url=base_url.rstrip("/"),
                api_key=api_key or None,
                model=model or None,
                provider=detect_provider(base_url),
            )
            if config.provider == "foundry_local":
                return config
            return replace(config, fallback=_local_config(env, probe=probe))
        return _local_config(env, probe=probe) or cls(model=model or None, provider="none")

    @property
    def configured(self) -> bool:
        return self.provider != "none" and bool(self.base_url)

    def describe(self) -> str:
        """A key-free summary safe to write into an eval report."""
        configured = rungs(self)
        if not configured:
            return "provider=none (deterministic mode)"
        first = configured[0]
        lines = [
            f"provider={first.provider} model={first.model or '<auto>'} "
            f"base_url={first.base_url} key={'yes' if first.api_key else 'no'}"
        ]
        lines.extend(
            f"  -> provider={rung.provider} base_url={rung.base_url} key={'yes' if rung.api_key else 'no'}"
            for rung in configured[1:]
        )
        return "\n".join(lines)


def rungs(config: LlmConfig | None) -> tuple[LlmConfig, ...]:
    """Return at most three configured endpoints, stopping safely at a repeated object."""
    found: list[LlmConfig] = []
    seen: set[int] = set()
    current = config
    while current and len(found) < 3 and id(current) not in seen:
        seen.add(id(current))
        if current.configured:
            found.append(current)
        current = current.fallback
    return tuple(found)


def first_rung(config: LlmConfig | None, allows: Callable[[str], bool]) -> LlmConfig | None:
    """Return the first configured provider accepted by a caller's spend guard."""
    return next((rung for rung in rungs(config) if allows(rung.provider)), None)


def author_of(provider: str | None) -> str:
    """Citizen-facing label for the endpoint that wrote the answer."""
    if provider == "foundry_local":
        return "yerel model"
    if provider in {None, "none"}:
        return "kural"
    return "model"


def _first(env: Mapping[str, str], names: Sequence[str]) -> str | None:
    for name in names:
        value = (env.get(name) or "").strip()
        if value:
            return value
    return None


def _local_config(env: Mapping[str, str], *, probe: bool) -> LlmConfig | None:
    explicit = (env.get("NABIZ_FOUNDRY_LOCAL_URL") or "").strip()
    if explicit:
        return LlmConfig(base_url=explicit.rstrip("/"), provider="foundry_local")
    if not probe or env.get("NABIZ_LLM_NO_PROBE", "").lower() in {"1", "true", "yes"}:
        return None

    base_url = foundry_status_url()
    if base_url:
        return LlmConfig(base_url=base_url, provider="foundry_local")
    if foundry_local_running():
        model = models_reachable(FOUNDRY_LOCAL_URL)
        if model:
            log.info("found Foundry Local on %s:%s", *FOUNDRY_LOCAL_HOST)
            return LlmConfig(base_url=FOUNDRY_LOCAL_URL, model=model, provider="foundry_local")
    return None


@cache
def _cached_foundry_status_url(which: Callable[[str], str | None], run: Callable[..., Any]) -> str | None:
    """Cache the potentially slow CLI status call for this pair of discovery seams."""
    try:
        executable = which("foundry")
        if not executable:
            return None
        result = run([executable, "service", "status"], capture_output=True, text=True, timeout=3, check=False)
        match = _LOCAL_URL_RE.search(f"{result.stdout or ''}\n{result.stderr or ''}")
        if not match:
            log.info("Foundry Local status did not contain a localhost URL")
            return None
        return f"http://127.0.0.1:{match.group(2)}/v1"
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.info("Foundry Local status probe failed (%s)", type(exc).__name__)
        return None


def foundry_status_url(
    *, which: Callable[[str], str | None] | None = None, run: Callable[..., Any] | None = None
) -> str | None:
    """Find the dynamic local port reported by `foundry service status`, if installed."""
    return _cached_foundry_status_url(which or shutil.which, run or subprocess.run)


foundry_status_url.cache_clear = _cached_foundry_status_url.cache_clear  # type: ignore[attr-defined]


def models_reachable(base_url: str, timeout: float = 0.5) -> str | None:
    """Return the first model id only when an endpoint answers its models request."""
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(f"{base_url.rstrip('/')}/models")
        if response.status_code != 200:
            return None
        data = response.json().get("data") or []
        model = data[0].get("id") if data else None
        return model if isinstance(model, str) and model else None
    except (httpx.HTTPError, ValueError, AttributeError, IndexError) as exc:
        log.info("Foundry Local model probe failed (%s)", type(exc).__name__)
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
    """Flatten a chat completion; ``chat`` adds the selected provider to this shape."""
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
        log.info("model discovery failed (%s)", type(exc).__name__)
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
    """Try each configured model rung and return the response with its provider label.

    Extra keyword arguments (``temperature``, ``max_tokens``, ``tool_choice`` …) are passed
    through verbatim, so a provider-specific knob does not need a change here.
    """
    ladder = rungs(config)
    if not ladder:
        require(config)
    last_error: LlmError | None = None
    for rung in ladder:
        with span("nabiz.llm.rung", **{"nabiz.agent.provider": rung.provider}):
            try:
                response = await _chat_rung(rung, messages, tools, **kw)
            except LlmError as exc:
                last_error = exc
                log.warning("model rung %s failed (%s); dropping to next rung", rung.provider, type(exc).__name__)
                continue
            response["provider"] = rung.provider
            return response
    if last_error:
        raise last_error
    require(config)
    raise LlmError("No configured model rung")


async def _chat_rung(
    config: LlmConfig,
    messages: Sequence[Mapping[str, Any]],
    tools: Sequence[Mapping[str, Any]] | None,
    **kw: Any,
) -> dict[str, Any]:
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
        raise LlmError(f"{config.provider} çağrısı başarısız ({type(exc).__name__})") from exc
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
            raise LlmError(f"{config.provider} endpointine ulaşılamadı ({type(exc).__name__})") from exc
        if response.status_code >= 400:
            raise LlmError(f"{config.provider} endpointi HTTP {response.status_code} döndürdü")
        try:
            return _normalise(response.json())
        except ValueError as exc:
            raise LlmError(f"{config.provider} endpointi geçerli JSON döndürmedi") from exc
