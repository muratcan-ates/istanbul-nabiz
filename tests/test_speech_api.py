"""An unwired router can still be checked without changing the application."""

from __future__ import annotations

import io
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nabiz.console.speech_api import MAX_AUDIO_BYTES, speech_router
from nabiz.console.speech_provider import OffSpeech, speech_provider


class FakeSpeech:
    available = True

    def __init__(self, *, text: str = "500T ne zaman gelir?", audio: bytes = b"fake-mp3") -> None:
        self.calls: list[str] = []
        self.text = text
        self.audio = audio

    async def transcribe(self, audio: bytes, language: str) -> str:
        self.calls.append("transcribe")
        return self.text

    async def synthesize(self, text: str, language: str) -> bytes:
        self.calls.append("synthesize")
        return self.audio


def client_with(provider: FakeSpeech | OffSpeech) -> TestClient:
    app = FastAPI()
    app.include_router(speech_router)
    app.dependency_overrides[speech_provider] = lambda: provider
    return TestClient(app)


def wav_seconds(seconds: int) -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x01\x02" * (seconds * 16000))
    return stream.getvalue()


def test_off_routes_offer_typing() -> None:
    client = client_with(OffSpeech())
    for path, payload in (
        ("/api/speech/transcribe", {"content": wav_seconds(1), "headers": {"content-type": "audio/wav"}}),
        ("/api/speech/synthesize", {"json": {"text": "Merhaba"}}),
    ):
        reply = client.post(path, **payload)
        assert reply.status_code == 503
        assert reply.json()["detail"]["status"] == "kapalı"
        assert "Yazarak devam" in reply.json()["detail"]["message"]


def test_transcription_is_only_an_editable_draft() -> None:
    provider = FakeSpeech()
    client = client_with(provider)
    reply = client.post("/api/speech/transcribe?language=tr", content=wav_seconds(1), headers={"content-type": "audio/wav"})
    assert reply.status_code == 200
    assert reply.json() == {
        "status": "taslak", "text": "500T ne zaman gelir?", "editable": True, "auto_send": False, "language": "tr",
    }
    assert provider.calls == ["transcribe"]
    assert reply.headers["cache-control"] == "no-store"


def test_synthetic_response_is_marked_and_not_cached() -> None:
    provider = FakeSpeech()
    reply = client_with(provider).post("/api/speech/synthesize", json={"text": "Merhaba", "language": "tr"})
    assert reply.status_code == 200
    assert reply.content == b"fake-mp3"
    assert reply.headers["x-nabiz-synthetic-voice"] == "true"
    assert reply.headers["cache-control"] == "no-store"
    assert provider.calls == ["synthesize"]


def test_duration_size_and_format_are_rejected_without_logging_audio(caplog: pytest.LogCaptureFixture) -> None:
    provider = FakeSpeech()
    client = client_with(provider)
    too_long = client.post("/api/speech/transcribe", content=wav_seconds(31), headers={"content-type": "audio/wav"})
    assert too_long.status_code == 413
    assert "30 saniye" in too_long.json()["detail"]
    too_large = client.post("/api/speech/transcribe", content=b"private-audio" + b"x" * MAX_AUDIO_BYTES,
                            headers={"content-type": "audio/wav"})
    assert too_large.status_code == 413
    invalid = client.post("/api/speech/transcribe", content=b"private-audio", headers={"content-type": "audio/wav"})
    assert invalid.status_code == 415
    truncated = client.post("/api/speech/transcribe", content=wav_seconds(1)[:-20],
                            headers={"content-type": "audio/wav"})
    assert truncated.status_code == 415
    assert provider.calls == []
    assert "private-audio" not in caplog.text


def test_only_tr_and_en_and_bounded_text() -> None:
    client = client_with(FakeSpeech())
    assert client.post("/api/speech/transcribe?language=de", content=wav_seconds(1),
                       headers={"content-type": "audio/wav"}).status_code == 422
    assert client.post("/api/speech/synthesize", json={"text": "x" * 601}).status_code == 422


def test_unusable_provider_outputs_fail_closed() -> None:
    oversized = client_with(FakeSpeech(text="x" * 601)).post(
        "/api/speech/transcribe", content=wav_seconds(1), headers={"content-type": "audio/wav"}
    )
    assert oversized.status_code == 422
    silent = client_with(FakeSpeech(audio=b"")).post("/api/speech/synthesize", json={"text": "Merhaba"})
    assert silent.status_code == 503
