from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterable

from app.asr.base import TranscriptionFinalEvent, TranscriptionPartialEvent, TranscriptionResult, TranscriptionStreamEvent
from app.core.errors import ASRInvalidRequestError, ASRTimeoutError, ASRUnavailableError

_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{2,8})*$")


class FakeASRProvider:
    provider_name = "fake"
    model_name = "fake-asr-v1"

    def __init__(
        self,
        mode: str = "ok",
        text: str = "这是 Fake ASR 测试转写。",
        detected_language: str | None = "zh",
    ) -> None:
        self.mode = mode
        self.text = text
        self.detected_language = detected_language

    async def transcribe(
        self,
        audio_bytes: bytes,
        media_type: str,
        language: str | None = None,
    ) -> TranscriptionResult:
        if self.mode == "error":
            raise ASRUnavailableError()
        if self.mode == "timeout":
            raise ASRTimeoutError()
        if self.mode == "empty":
            return TranscriptionResult(
                text="",
                detected_language=self._detected_language(language),
                duration_ms=None,
                provider=self.provider_name,
                model=self.model_name,
                inference_ms=0,
            )
        if self.mode == "invalid":
            return TranscriptionResult(
                text=self.text,
                detected_language=self._detected_language(language),
                duration_ms=None,
                provider="",
                model="",
                inference_ms=-1,
            )

        return TranscriptionResult(
            text=self.text,
            detected_language=self._detected_language(language),
            duration_ms=None,
            provider=self.provider_name,
            model=self.model_name,
            inference_ms=0,
        )

    async def transcribe_stream(
        self,
        audio_chunks: Iterable[bytes],
        media_type: str,
        language: str | None = None,
    ) -> AsyncIterator[TranscriptionStreamEvent]:
        chunks = list(audio_chunks)
        if not chunks:
            raise ASRInvalidRequestError()
        if self.mode == "error":
            raise ASRUnavailableError()
        if self.mode == "timeout":
            raise ASRTimeoutError()

        text = "" if self.mode == "empty" else self.text.strip()
        if text:
            partial_length = min(len(text), 2)
            yield TranscriptionPartialEvent(type="partial", index=0, text=text[:partial_length], is_final=False, audio_ms=1000, provider=self.provider_name, model=self.model_name)
            yield TranscriptionPartialEvent(type="partial", index=1, text=text, is_final=False, audio_ms=2000, provider=self.provider_name, model=self.model_name)

        yield TranscriptionFinalEvent(
            type="final",
            result=await self.transcribe(b"".join(chunks), media_type, language),
        )

    def _detected_language(self, language: str | None) -> str | None:
        if language and _LANGUAGE_RE.fullmatch(language):
            return language
        return self.detected_language
