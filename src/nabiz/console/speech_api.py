"""Speech routes: transcription is a draft, never a chat submission.

Each call is bonded (P00 D2a, P04): one model call claimed on the person's quota and one on the day's shared
speech ceiling (``global:speech``, ``NABIZ_SPEECH_DAILY_CALLS``), both in the app's quota book, so the limit
holds across restarts and replicas; a call the provider does not complete gives both back.
"""

from __future__ import annotations

import io
import wave
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from nabiz.console.accounts_api import holder_for
from nabiz.console.quota import Holder, Tier
from nabiz.console.speech_provider import Language, SpeechProvider, SpeechSettings, SpeechUnavailable, speech_provider

speech_router = APIRouter()
MAX_AUDIO_BYTES = 2 * 1024 * 1024
MAX_SECONDS = 30
CLOSED = {"status": "kapalı", "message": "Ses hizmeti kapalı. Yazarak devam edebilirsiniz."}


class SpeechText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=600)
    language: Literal["tr", "en"] = "tr"


def _closed() -> HTTPException:
    return HTTPException(status_code=503, detail=CLOSED)


SPEECH_HOLDER = "global:speech"


class _Bond:
    """One speech call held on the person's quota and the shared speech ceiling; ``refund`` gives both back."""

    def __init__(self, request: Request) -> None:
        self.book = getattr(request.app.state, "quota", None)
        self.claims: list[Holder] = []
        if self.book is None:  # the bare router in its own tests; the product app always has a book
            return
        everyone = Holder(Tier("speech", "Ses", 0, SpeechSettings.from_env().daily_calls), SPEECH_HOLDER)
        for holder in (holder_for(request), everyone):
            if not self.book.reserve_calls(holder, 1):
                self.refund()
                raise _closed()
            self.claims.append(holder)

    def refund(self) -> None:
        for holder in self.claims:
            self.book.refund_calls(holder, 1)
        self.claims = []


def _validate_wav(audio: bytes) -> None:
    try:
        with wave.open(io.BytesIO(audio), "rb") as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getcomptype() != "NONE":
                raise ValueError
            if wav.getframerate() != 16000:
                raise ValueError
            frames = wav.getnframes()
            seconds = frames / wav.getframerate()
            if len(wav.readframes(frames)) != frames * 2:
                raise ValueError
    except (wave.Error, EOFError, ValueError) as exc:
        raise HTTPException(status_code=415, detail="16 kHz, tek kanallı PCM WAV ses kullanın.") from exc
    if seconds > MAX_SECONDS:
        raise HTTPException(status_code=413, detail="Ses en çok 30 saniye olabilir.")


async def _read_audio(request: Request) -> bytes:
    if request.headers.get("content-type", "").split(";", 1)[0].lower() not in {"audio/wav", "audio/x-wav"}:
        raise HTTPException(status_code=415, detail="16 kHz, tek kanallı PCM WAV ses kullanın.")
    audio = bytearray()
    async for chunk in request.stream():
        audio.extend(chunk)
        if len(audio) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="Ses dosyası en çok 2 MiB olabilir.")
    _validate_wav(audio)
    return bytes(audio)


@speech_router.post("/api/speech/transcribe")
async def transcribe(
    request: Request,
    response: Response,
    provider: Annotated[SpeechProvider, Depends(speech_provider)],
    language: Language = "tr",
) -> dict[str, object]:
    """Return text for an editable field; no call to the assistant is made here."""
    if not provider.available:
        raise _closed()
    audio = await _read_audio(request)
    bond = _Bond(request)
    try:
        text = await provider.transcribe(audio, language)
    except SpeechUnavailable as exc:
        bond.refund()
        raise _closed() from exc
    if not text or len(text) > 600:
        raise HTTPException(status_code=422, detail="Ses anlaşılamadı. Yazarak devam edebilirsiniz.")
    response.headers["Cache-Control"] = "no-store"
    return {"status": "taslak", "text": text, "editable": True, "auto_send": False, "language": language}


@speech_router.post("/api/speech/synthesize")
async def synthesize(
    request: Request,
    body: SpeechText,
    provider: Annotated[SpeechProvider, Depends(speech_provider)],
) -> Response:
    """Speak supplied answer text without creating another assistant response."""
    if not provider.available:
        raise _closed()
    bond = _Bond(request)
    try:
        audio = await provider.synthesize(body.text, body.language)
    except SpeechUnavailable as exc:
        bond.refund()
        raise _closed() from exc
    if not audio:
        bond.refund()
        raise _closed()
    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store", "X-Nabiz-Synthetic-Voice": "true"},
    )
