from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SpeechSynthesisResult:
    audio_bytes: bytes
    media_type: str
    sample_rate: int
    duration_ms: int
    provider: str
    model: str


@dataclass(frozen=True)
class SpeechSynthesisSegment:
    audio_bytes: bytes
    media_type: str
    sample_rate: int
    duration_ms: int
    provider: str
    model: str
    index: int


class TTSProvider(Protocol):
    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        speed: float = 1.0,
    ) -> SpeechSynthesisResult:
        ...


class StreamingTTSProvider(TTSProvider, Protocol):
    async def synthesize_stream(
        self,
        text: str,
        voice_id: str | None = None,
        speed: float = 1.0,
    ) -> AsyncIterator[SpeechSynthesisSegment]:
        ...
