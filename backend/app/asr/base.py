from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class TranscriptionSegment:
    start_ms: int
    end_ms: int
    text: str
    confidence: float | None = None


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    detected_language: str | None
    duration_ms: int | None
    provider: str
    model: str
    inference_ms: int
    segments: tuple[TranscriptionSegment, ...] | None = None


@dataclass(frozen=True)
class TranscriptionPartialEvent:
    type: Literal["partial"]
    index: int
    text: str
    is_final: bool
    audio_ms: int | None = None
    provider: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class TranscriptionFinalEvent:
    type: Literal["final"]
    result: TranscriptionResult


TranscriptionStreamEvent = TranscriptionPartialEvent | TranscriptionFinalEvent


class ASRProvider(Protocol):
    async def transcribe(
        self,
        audio_bytes: bytes,
        media_type: str,
        language: str | None = None,
    ) -> TranscriptionResult:
        ...


class StreamingASRProvider(ASRProvider, Protocol):
    async def transcribe_stream(
        self,
        audio_chunks: Iterable[bytes],
        media_type: str,
        language: str | None = None,
    ) -> AsyncIterator[TranscriptionStreamEvent]:
        ...
