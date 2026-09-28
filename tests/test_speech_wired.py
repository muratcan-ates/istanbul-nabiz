"""P00 D2a (P04): speech is mounted, off by default, and every call is held on two quotas."""

from __future__ import annotations

import pathlib

import pytest
from conftest import offline_settings
from fastapi.testclient import TestClient

from nabiz.agent import llm
from nabiz.console.access import OperatorAccess
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard
from nabiz.console.quota import Holder, Tier
from nabiz.console.speech_api import SPEECH_HOLDER
from nabiz.console.speech_provider import SpeechUnavailable, speech_provider

DEVICE = {"X-Nabiz-Device": "d" * 24}


class FakeSpeech:
    def __init__(self, fail: bool = False) -> None:
        self.fail, self.calls = fail, 0

    @property
    def available(self) -> bool:
        return True

    async def transcribe(self, audio: bytes, language: str) -> str:
        raise SpeechUnavailable

    async def synthesize(self, text: str, language: str) -> bytes:
        self.calls += 1
        if self.fail:
            raise SpeechUnavailable
        return b"ID3-sample"


@pytest.fixture
def app(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "nexus.db"))
    monkeypatch.setenv("NABIZ_SPEECH_DAILY_CALLS", "2")
    return build_console_app(
        settings=offline_settings(), llm_config=llm.LlmConfig(), guard=SpendGuard(BudgetConfig(state_path=None)),
        access=OperatorAccess(token="test-operator-token", bound_host="0.0.0.0"),
    )


def left(app) -> int:
    return app.state.quota.calls_left(Holder(Tier("speech", "Ses", 0, 2), SPEECH_HOLDER))


def test_speech_is_mounted_and_closed_by_default(app) -> None:
    with TestClient(app, base_url="http://127.0.0.1:8090") as client:
        response = client.post("/api/speech/synthesize", json={"text": "Merhaba"}, headers=DEVICE)
    assert response.status_code == 503 and response.json()["detail"]["status"] == "kapalı"


def test_the_shared_ceiling_holds_and_a_failed_call_gives_its_claims_back(app) -> None:
    fake = FakeSpeech(fail=True)
    app.dependency_overrides[speech_provider] = lambda: fake
    with TestClient(app, base_url="http://127.0.0.1:8090") as client:
        assert client.post("/api/speech/synthesize", json={"text": "Merhaba"}, headers=DEVICE).status_code == 503
        assert left(app) == 2
        fake.fail = False
        statuses = [client.post("/api/speech/synthesize", json={"text": "Merhaba"}, headers=DEVICE).status_code
                    for _ in range(3)]
        status = client.get("/api/quota", headers=DEVICE).json()
    assert statuses == [200, 200, 503] and fake.calls == 3 and left(app) == 0
    assert status["model_calls_left"] == status["model_calls_limit"] - 2
