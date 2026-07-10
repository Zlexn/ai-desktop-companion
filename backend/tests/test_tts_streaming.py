from __future__ import annotations

import wave
from io import BytesIO

import pytest

from app.core.config import Settings
from app.core.errors import TTSInvalidRequestError, TTSInvalidResponseError
from app.services.tts_service import TTSService
from app.tts.base import SpeechSynthesisSegment
from app.tts.fake_provider import FakeTTSProvider


def wav_duration_ms(audio_bytes: bytes) -> int:
    with wave.open(BytesIO(audio_bytes), "rb") as wav_file:
        return round(wav_file.getnframes() / wav_file.getframerate() * 1000)


@pytest.mark.asyncio
async def test_fake_tts_stream_yields_ordered_wav_segments() -> None:
    provider = FakeTTSProvider()

    segments = [segment async for segment in provider.synthesize_stream("第一句。第二句。第三句。", "fake-default", 1.0)]

    assert [segment.index for segment in segments] == [0, 1, 2]
    assert all(segment.media_type == "audio/wav" for segment in segments)
    assert all(segment.audio_bytes.startswith(b"RIFF") for segment in segments)
    assert all(segment.audio_bytes[8:12] == b"WAVE" for segment in segments)
    assert all(segment.sample_rate == 16000 for segment in segments)
    assert all(segment.duration_ms == wav_duration_ms(segment.audio_bytes) for segment in segments)
    assert all(segment.provider == "fake" for segment in segments)
    assert all(segment.model == "fake-tone-v1" for segment in segments)


@pytest.mark.asyncio
async def test_tts_service_stream_reuses_request_validation() -> None:
    service = TTSService(FakeTTSProvider(), Settings(tts_provider="fake", llm_provider="fake"))

    with pytest.raises(TTSInvalidRequestError):
        _ = [segment async for segment in service.synthesize_stream("   ")]


class InvalidStreamingProvider(FakeTTSProvider):
    async def synthesize_stream(self, text: str, voice_id: str | None = None, speed: float = 1.0):
        yield SpeechSynthesisSegment(
            audio_bytes=b"not a wav",
            media_type="audio/mpeg",
            sample_rate=0,
            duration_ms=0,
            provider="fake",
            model="fake-tone-v1",
            index=0,
        )


@pytest.mark.asyncio
async def test_tts_service_stream_validates_segments() -> None:
    service = TTSService(InvalidStreamingProvider(), Settings(tts_provider="fake", llm_provider="fake"))

    with pytest.raises(TTSInvalidResponseError):
        _ = [segment async for segment in service.synthesize_stream("测试")]
