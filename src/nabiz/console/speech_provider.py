"""Optional speech adapters. They never persist audio, text or credentials."""

from __future__ import annotations

import datetime as dt
import os
import threading
from dataclasses import dataclass
from html import escape
from typing import Literal, Protocol

import httpx

Language = Literal["tr", "en"]
_LOCALES = {"tr": "tr-TR", "en": "en-US"}
_AZURE_VOICES = {"tr": "tr-TR-AhmetNeural", "en": "en-US-JennyNeural"}


class SpeechUnavailable(Exception):
    """A provider cannot answer; the caller must offer typing instead."""


class SpeechProvider(Protocol):
    @property
    def available(self) -> bool: ...

    async def transcribe(self, audio: bytes, language: Language) -> str: ...

    async def synthesize(self, text: str, language: Language) -> bytes: ...


@dataclass(frozen=True)
class SpeechSettings:
    provider: str = "off"
    key: str = ""
    azure_region: str = ""
    daily_calls: int = 0

    @classmethod
    def from_env(cls) -> SpeechSettings:
        name = os.getenv("NABIZ_SPEECH_PROVIDER", "off").strip().lower()
        raw_limit = os.getenv("NABIZ_SPEECH_DAILY_CALLS", "0").strip()
        try:
            limit = max(0, int(raw_limit))
        except ValueError:
            limit = 0
        key_name = {"azure": "NABIZ_AZURE_SPEECH_KEY", "openai": "NABIZ_OPENAI_SPEECH_KEY"}.get(name, "")
        return cls(
            provider=name,
            key=os.getenv(key_name, "") if key_name else "",
            azure_region=os.getenv("NABIZ_AZURE_SPEECH_REGION", "").strip().lower() if name == "azure" else "",
            daily_calls=limit,
        )

    @property
    def ready(self) -> bool:
        if os.getenv("NABIZ_OFFLINE") == "1" or self.daily_calls < 1 or not self.key:
            return False
        if self.provider == "azure":
            return bool(self.azure_region and self.azure_region.replace("-", "").isalnum())
        return self.provider == "openai"


class _DailyLimit:
    """A process-local safety ceiling; deployment still needs a shared spend guard."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._day: dt.date | None = None
        self._used = 0

    def reserve(self, maximum: int) -> None:
        with self._lock:
            today = dt.datetime.now(dt.UTC).date()
            if self._day != today:
                self._day, self._used = today, 0
            if self._used >= maximum:
                raise SpeechUnavailable
            self._used += 1


_LIMIT = _DailyLimit()


class OffSpeech:
    @property
    def available(self) -> bool:
        return False

    async def transcribe(self, audio: bytes, language: Language) -> str:
        raise SpeechUnavailable

    async def synthesize(self, text: str, language: Language) -> bytes:
        raise SpeechUnavailable


class RemoteSpeech:
    def __init__(self, settings: SpeechSettings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.client = client

    @property
    def available(self) -> bool:
        return self.settings.ready

    async def _post(self, url: str, **kwargs: object) -> httpx.Response:
        if not self.available:
            raise SpeechUnavailable
        _LIMIT.reserve(self.settings.daily_calls)
        try:
            if self.client is not None:
                response = await self.client.post(url, timeout=20, **kwargs)
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.post(url, timeout=20, **kwargs)
            response.raise_for_status()
            return response
        except (httpx.HTTPError, ValueError) as exc:
            raise SpeechUnavailable from exc


class AzureSpeech(RemoteSpeech):
    async def transcribe(self, audio: bytes, language: Language) -> str:
        region = self.settings.azure_region
        url = f"https://{region}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"
        response = await self._post(
            url,
            params={"language": _LOCALES[language]},
            headers={"Ocp-Apim-Subscription-Key": self.settings.key, "Content-Type": "audio/wav"},
            content=audio,
        )
        try:
            result = response.json()
            if result.get("RecognitionStatus") == "Success" and isinstance(result.get("DisplayText"), str):
                return result["DisplayText"].strip()
        except (ValueError, AttributeError):
            pass
        raise SpeechUnavailable

    async def synthesize(self, text: str, language: Language) -> bytes:
        locale = _LOCALES[language]
        voice = _AZURE_VOICES[language]
        ssml = f'<speak version="1.0" xml:lang="{locale}"><voice name="{voice}">{escape(text)}</voice></speak>'
        response = await self._post(
            f"https://{self.settings.azure_region}.tts.speech.microsoft.com/cognitiveservices/v1",
            headers={
                "Ocp-Apim-Subscription-Key": self.settings.key,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "audio-16khz-32kbitrate-mono-mp3",
            },
            content=ssml.encode("utf-8"),
        )
        return response.content or _unavailable()


class OpenAISpeech(RemoteSpeech):
    async def transcribe(self, audio: bytes, language: Language) -> str:
        response = await self._post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {self.settings.key}"},
            data={"model": "whisper-1", "language": language},
            files={"file": ("speech.wav", audio, "audio/wav")},
        )
        try:
            result = response.json()
            if isinstance(result.get("text"), str):
                return result["text"].strip()
        except (ValueError, AttributeError):
            pass
        raise SpeechUnavailable

    async def synthesize(self, text: str, language: Language) -> bytes:
        response = await self._post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {self.settings.key}"},
            json={"model": "tts-1", "voice": "alloy", "input": text, "response_format": "mp3"},
        )
        return response.content or _unavailable()


def _unavailable() -> bytes:
    raise SpeechUnavailable


def speech_provider() -> SpeechProvider:
    settings = SpeechSettings.from_env()
    if not settings.ready:
        return OffSpeech()
    return AzureSpeech(settings) if settings.provider == "azure" else OpenAISpeech(settings)
