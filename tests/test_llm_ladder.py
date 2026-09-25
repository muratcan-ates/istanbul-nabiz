"""Offline acceptance tests for Foundry discovery and the model fallback ladder."""

from __future__ import annotations

import logging
import subprocess

import httpx
import pytest
import respx

from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.agent.agent import NabizAgent


def _completion(content: str = "Yerel yanıt") -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1,
        "model": "phi-4-mini",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
    }


def test_explicit_foundry_url_is_the_local_rung():
    config = llm.LlmConfig.from_env(
        {"NABIZ_FOUNDRY_LOCAL_URL": "http://127.0.0.1:52403/v1///", "NABIZ_LLM_MODEL": "cloud-model"},
        probe=False,
    )
    assert config.provider == "foundry_local"
    assert config.base_url == "http://127.0.0.1:52403/v1"
    assert config.model is None


def test_foundry_status_output_yields_the_port():
    args = ["/usr/bin/foundry", "service", "status"]
    completed = subprocess.CompletedProcess(
        args, 0, "Service running at http://127.0.0.1:52403/openai/status\n", ""
    )
    def which(name):
        return "/usr/bin/foundry" if name == "foundry" else None

    def run(*args, **kwargs):
        return completed

    assert llm.foundry_status_url(which=which, run=run) == "http://127.0.0.1:52403/v1"

    def no_url(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, "service is stopped", "")

    assert llm.foundry_status_url(which=which, run=no_url) is None

    def missing(_):
        return None

    assert llm.foundry_status_url(which=missing, run=run) is None

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    assert llm.foundry_status_url(which=which, run=timeout) is None


def test_models_probe_on_the_default_port(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llm, "foundry_status_url", lambda: None)
    monkeypatch.setattr(llm, "foundry_local_running", lambda: True)
    with respx.mock:
        respx.get("http://127.0.0.1:5273/v1/models").mock(
            return_value=httpx.Response(200, json={"data": [{"id": "phi-4-mini-cpu"}]})
        )
        config = llm.LlmConfig.from_env({}, probe=True)
    assert config.base_url == "http://127.0.0.1:5273/v1"
    assert config.model == "phi-4-mini-cpu"
    assert config.provider == "foundry_local"


def test_no_probe_skips_subprocess_and_sockets(monkeypatch: pytest.MonkeyPatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("probing is disabled")

    monkeypatch.setattr(llm, "foundry_status_url", unexpected)
    monkeypatch.setattr(llm, "foundry_local_running", unexpected)
    monkeypatch.setattr(llm, "models_reachable", unexpected)
    config = llm.LlmConfig.from_env({"NABIZ_LLM_NO_PROBE": "1"}, probe=True)
    assert config.provider == "none"


def test_cloud_config_carries_the_local_rung_and_not_its_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llm, "foundry_status_url", lambda: "http://127.0.0.1:52403/v1")
    config = llm.LlmConfig.from_env(
        {
            "NABIZ_LLM_BASE_URL": "https://tenant.openai.azure.com/openai/v1",
            "NABIZ_LLM_API_KEY": "secret-key-for-test",
            "NABIZ_LLM_MODEL": "gpt-4.1-mini",
        },
        probe=True,
    )
    assert config.model == "gpt-4.1-mini"
    assert config.fallback is not None
    assert config.fallback.provider == "foundry_local"
    assert config.fallback.model is None
    assert llm.rungs(config) == (config, config.fallback)


def test_first_rung_selects_the_first_allowed_provider():
    local = llm.LlmConfig(base_url="http://127.0.0.1:52403/v1", provider="foundry_local")
    cloud = llm.LlmConfig(
        base_url="https://tenant.openai.azure.com/openai/v1", provider="azure_openai", fallback=local
    )
    assert llm.first_rung(cloud, lambda provider: provider == "foundry_local") is local
    assert llm.first_rung(cloud, lambda _: False) is None


async def test_chat_drops_from_cloud_to_local_on_error(caplog: pytest.LogCaptureFixture):
    config = llm.LlmConfig(
        base_url="http://cloud.invalid/v1",
        api_key="secret-key-for-test",
        model="cloud-model",
        provider="openai_compatible",
        fallback=llm.LlmConfig(
            base_url="http://127.0.0.1:52403/v1", model="phi-4-mini", provider="foundry_local"
        ),
    )
    with respx.mock:
        respx.post("http://cloud.invalid/v1/chat/completions").mock(
            return_value=httpx.Response(500, text="private body that must not be logged")
        )
        respx.post("http://127.0.0.1:52403/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_completion())
        )
        with caplog.at_level(logging.WARNING, logger="nabiz.agent.llm"):
            response = await llm.chat(config, [{"role": "user", "content": "hello"}])
    assert response["provider"] == "foundry_local"
    assert response["content"] == "Yerel yanıt"
    assert "secret-key-for-test" not in caplog.text
    assert "private body" not in caplog.text
    assert "failed (LlmError)" in caplog.text


async def test_agent_answer_records_the_rung_that_wrote_it(ctx):
    config = llm.LlmConfig(
        base_url="http://127.0.0.1:52403/v1", model="phi-4-mini", provider="foundry_local"
    )
    agent = NabizAgent(Nabiz(ctx), config=config, system_prompt="test prompt")
    with respx.mock:
        respx.post("http://127.0.0.1:52403/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_completion())
        )
        answer = await agent.ask("Hello")
    assert answer.mode == "llm"
    assert answer.provider == "foundry_local"


async def test_all_rungs_failed_falls_to_rules(ctx):
    cloud = llm.LlmConfig(
        base_url="http://cloud.invalid/v1",
        api_key="secret-key-for-test",
        model="cloud-model",
        provider="openai_compatible",
        fallback=llm.LlmConfig(
            base_url="http://127.0.0.1:52403/v1", model="phi-4-mini", provider="foundry_local"
        ),
    )
    agent = NabizAgent(Nabiz(ctx), config=cloud, system_prompt="test prompt")
    with respx.mock:
        respx.post("http://cloud.invalid/v1/chat/completions").mock(
            side_effect=httpx.ConnectError("wifi offline")
        )
        respx.post("http://127.0.0.1:52403/v1/chat/completions").mock(
            side_effect=httpx.ConnectError("wifi offline")
        )
        answer = await agent.ask("Şu an trafik nasıl?")
    assert answer.mode == "deterministic"
    assert answer.provider == "none"


def test_author_of_labels():
    assert llm.author_of("azure_openai") == "model"
    assert llm.author_of("openai_compatible") == "model"
    assert llm.author_of("foundry_local") == "yerel model"
    assert llm.author_of("none") == "kural"
    assert llm.author_of(None) == "kural"


def test_describe_lists_rungs_without_the_key():
    config = llm.LlmConfig(
        base_url="https://tenant.openai.azure.com/openai/v1",
        api_key="secret-key-for-test",
        model="gpt-4.1-mini",
        provider="azure_openai",
        fallback=llm.LlmConfig(
            base_url="http://127.0.0.1:52403/v1", provider="foundry_local"
        ),
    )
    description = config.describe()
    assert "provider=azure_openai" in description
    assert "-> provider=foundry_local" in description
    assert "key=yes" in description and "key=no" in description
    assert "secret-key-for-test" not in description


def test_foundry_status_probe_runs_once_per_process(monkeypatch: pytest.MonkeyPatch):
    llm.foundry_status_url.cache_clear()
    calls = 0

    def which(name: str) -> str:
        assert name == "foundry"
        return "/usr/bin/foundry"

    def run(*args, **kwargs):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(args[0], 0, "http://localhost:52403/status", "")

    monkeypatch.setattr(llm.shutil, "which", which)
    monkeypatch.setattr(llm.subprocess, "run", run)
    assert llm.LlmConfig.from_env({}, probe=True).base_url == "http://127.0.0.1:52403/v1"
    assert llm.LlmConfig.from_env({}, probe=True).base_url == "http://127.0.0.1:52403/v1"
    assert calls == 1
    llm.foundry_status_url.cache_clear()
    llm.LlmConfig.from_env({}, probe=True)
    assert calls == 2
    llm.foundry_status_url.cache_clear()
