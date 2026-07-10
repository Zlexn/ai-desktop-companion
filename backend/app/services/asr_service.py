from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterable

from app.asr.base import ASRProvider, TranscriptionFinalEvent, TranscriptionPartialEvent, TranscriptionResult, TranscriptionStreamEvent
from app.core.config import Settings
from app.core.errors import (
    ASRError,
    ASRFileTooLargeError,
    ASRInvalidAudioError,
    ASRInvalidRequestError,
    ASRInvalidResponseError,
    ASRTimeoutError,
    ASRUnavailableError,
    ASRUnsupportedMediaTypeError,
)

_ALLOWED_MEDIA_TYPES = {"audio/webm", "audio/mp4", "audio/wav", "audio/x-wav"}
_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{2,8})*$")


class ASRService:
    def __init__(self, provider: ASRProvider, settings: Settings) -> None:
        self._provider = provider
        self._settings = settings

    @property
    def max_upload_bytes(self) -> int:
        return self._settings.asr_max_upload_bytes

    async def transcribe(
        self,
        audio_bytes: bytes,
        media_type: str,
        language: str | None = None,
    ) -> TranscriptionResult:
        self._validate_audio_bytes(audio_bytes)
        normalized_media_type = self._normalize_media_type(media_type)
        self._validate_media_type(normalized_media_type)
        self._validate_container_signature(audio_bytes, normalized_media_type)
        clean_language = self._normalize_language(language)

        try:
            result = await self._provider.transcribe(audio_bytes, normalized_media_type, clean_language)
        except ASRTimeoutError:
            raise
        except TimeoutError as exc:
            raise ASRTimeoutError() from exc
        except ASRUnavailableError:
            raise
        except ASRError:
            raise
        except Exception as exc:
            raise ASRUnavailableError() from exc

        return self._validate_result(result)

    async def transcribe_stream(
        self,
        audio_chunks: Iterable[bytes],
        media_type: str,
        language: str | None = None,
    ) -> AsyncIterator[TranscriptionStreamEvent]:
        chunks = list(audio_chunks)
        self._validate_audio_bytes(b"".join(chunks))
        normalized_media_type = self._normalize_media_type(media_type)
        self._validate_media_type(normalized_media_type)
        clean_language = self._normalize_language(language)

        transcribe_stream = getattr(self._provider, "transcribe_stream", None)
        if transcribe_stream is None:
            raise ASRUnavailableError("当前 ASR Provider 不支持流式转写。")

        try:
            async for event in transcribe_stream(chunks, normalized_media_type, clean_language):
                if isinstance(event, TranscriptionPartialEvent):
                    text = event.text.strip()
                    if event.index < 0 or not text:
                        raise ASRInvalidResponseError()
                    yield TranscriptionPartialEvent(
                        type="partial",
                        index=event.index,
                        text=text,
                        is_final=False,
                        audio_ms=event.audio_ms,
                        provider=event.provider,
                        model=event.model,
                    )
                elif isinstance(event, TranscriptionFinalEvent):
                    yield TranscriptionFinalEvent(type="final", result=self._validate_result(event.result))
                else:
                    raise ASRInvalidResponseError()
        except ASRTimeoutError:
            raise
        except TimeoutError as exc:
            raise ASRTimeoutError() from exc
        except ASRUnavailableError:
            raise
        except ASRError:
            raise
        except Exception as exc:
            raise ASRUnavailableError() from exc

    def _validate_audio_bytes(self, audio_bytes: bytes) -> None:
        if not audio_bytes or not audio_bytes.strip():
            raise ASRInvalidRequestError()
        if len(audio_bytes) > self._settings.asr_max_upload_bytes:
            raise ASRFileTooLargeError()

    def _normalize_media_type(self, media_type: str) -> str:
        normalized = media_type.split(";", 1)[0].strip().lower()
        if not normalized:
            raise ASRUnsupportedMediaTypeError()
        return normalized

    def _validate_media_type(self, media_type: str) -> None:
        if media_type not in _ALLOWED_MEDIA_TYPES:
            raise ASRUnsupportedMediaTypeError()

    def _validate_container_signature(self, audio_bytes: bytes, media_type: str) -> None:
        if media_type == "audio/webm" and not audio_bytes.startswith(b"\x1a\x45\xdf\xa3"):
            raise ASRInvalidAudioError()
        if media_type == "audio/mp4" and not self._has_mp4_ftyp_box(audio_bytes):
            raise ASRInvalidAudioError()
        if media_type in {"audio/wav", "audio/x-wav"} and not self._has_wav_header(audio_bytes):
            raise ASRInvalidAudioError()

    def _has_mp4_ftyp_box(self, audio_bytes: bytes) -> bool:
        if len(audio_bytes) < 12:
            return False
        box_size = int.from_bytes(audio_bytes[0:4], byteorder="big", signed=False)
        return box_size >= 8 and box_size <= len(audio_bytes) and audio_bytes[4:8] == b"ftyp"

    def _has_wav_header(self, audio_bytes: bytes) -> bool:
        return len(audio_bytes) >= 12 and audio_bytes.startswith(b"RIFF") and audio_bytes[8:12] == b"WAVE"

    def _normalize_language(self, language: str | None) -> str:
        candidate = self._settings.asr_default_language if language is None else language.strip()
        if not candidate or len(candidate) > 32 or not _LANGUAGE_RE.fullmatch(candidate):
            raise ASRInvalidRequestError()
        return candidate

    def _validate_result(self, result: TranscriptionResult) -> TranscriptionResult:
        text = result.text.strip()
        if not text:
            raise ASRInvalidResponseError()
        if not result.provider.strip() or not result.model.strip():
            raise ASRInvalidResponseError()
        if not isinstance(result.inference_ms, int) or result.inference_ms < 0:
            raise ASRInvalidResponseError()
        if result.duration_ms is not None:
            if not isinstance(result.duration_ms, int) or result.duration_ms < 0:
                raise ASRInvalidResponseError()
            if result.duration_ms < self._settings.asr_min_duration_ms:
                raise ASRInvalidResponseError()
            if result.duration_ms > self._settings.asr_max_duration_ms:
                raise ASRInvalidResponseError()

        if text == result.text:
            return result
        return TranscriptionResult(
            text=text,
            detected_language=result.detected_language,
            duration_ms=result.duration_ms,
            provider=result.provider,
            model=result.model,
            inference_ms=result.inference_ms,
            segments=result.segments,
        )
