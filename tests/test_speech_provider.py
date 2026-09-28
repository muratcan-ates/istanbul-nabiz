"""Speech adapters use injected HTTP transports and never contact a real service."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from nabiz.console.speech_provider import AzureSpeech, OffSpeech, OpenAISpeech, SpeechSettings, SpeechUnavailable, speech_provider


def test_provider_is_off_by_default_and_offline_even_with_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NABIZ_SPEECH_PROVIDER", "off")
    assert isinstance(speech_provider(), OffSpeech)
    monkeypatch.setenv("NABIZ_SPEECH_PROVIDER", "azure")
    monkeypatch.setenv("NABIZ_AZURE_SPEECH_KEY", "test-only")
    monkeypatch.setenv("NABIZ_AZURE_SPEECH_REGION", "test-region")
    monkeypatch.setenv("NABIZ_SPEECH_DAILY_CALLS", "5")
    monkeypatch.setenv("NABIZ_OFFLINE", "1")
    assert isinstance(speech_provider(), OffSpeech)
    monkeypatch.delenv("NABIZ_OFFLINE")
    monkeypatch.setenv("NABIZ_SPEECH_DAILY_CALLS", "0")
    assert isinstance(speech_provider(), OffSpeech)


def test_azure_adapter_uses_wav_and_escaped_ssml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NABIZ_OFFLINE", raising=False)
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if ".stt." in str(request.url):
            return httpx.Response(200, json={"RecognitionStatus": "Success", "DisplayText": "Merhaba"})
        return httpx.Response(200, content=b"mp3")

    async def check() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
            provider = AzureSpeech(SpeechSettings("azure", "test-only", "test-region", 20), client)
            assert await provider.transcribe(b"RIFF-test", "tr") == "Merhaba"
            assert await provider.synthesize("A&B", "en") == b"mp3"

    asyncio.run(check())
    assert seen[0].url.params["language"] == "tr-TR"
    assert seen[0].content == b"RIFF-test"
    assert b"A&amp;B" in seen[1].content
    assert seen[1].headers["x-microsoft-outputformat"] == "audio-16khz-32kbitrate-mono-mp3"


def test_openai_adapter_uses_transcription_and_speech_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NABIZ_OFFLINE", raising=False)
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/transcriptions"):
            return httpx.Response(200, json={"text": "Hello"})
        return httpx.Response(200, content=b"mp3")

    async def check() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
            provider = OpenAISpeech(SpeechSettings("openai", "test-only", daily_calls=20), client)
            assert await provider.transcribe(b"RIFF-test", "en") == "Hello"
            assert await provider.synthesize("Hello", "en") == b"mp3"

    asyncio.run(check())
    assert seen[0].url.path == "/v1/audio/transcriptions"
    assert b"whisper-1" in seen[0].content
    assert b"RIFF-test" in seen[0].content
    assert seen[1].url.path == "/v1/audio/speech"
    assert b'"model":"tts-1"' in seen[1].content


def test_provider_failures_do_not_return_upstream_body(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.delenv("NABIZ_OFFLINE", raising=False)
    secret_audio = b"private-speech-bytes"

    async def check() -> None:
        transport = httpx.MockTransport(lambda _r: httpx.Response(500, text="private reply"))
        async with httpx.AsyncClient(transport=transport) as client:
            provider = OpenAISpeech(SpeechSettings("openai", "test-only", daily_calls=20), client)
            with pytest.raises(SpeechUnavailable):
                await provider.transcribe(secret_audio, "tr")

    asyncio.run(check())
    assert "private-speech-bytes" not in caplog.text
    assert "private reply" not in caplog.text
