from __future__ import annotations

import pytest

from app.asr.base import TranscriptionFinalEvent, TranscriptionPartialEvent
from app.asr.fake_provider import FakeASRProvider
from app.core.config import Settings
from app.core.errors import ASRUnavailableError
from app.services.asr_service import ASRService


@pytest.mark.asyncio
async def test_fake_asr_stream_yields_partial_and_final_events() -> None:
    provider = FakeASRProvider(text="语音转写文本", detected_language="zh")

    events = [event async for event in provider.transcribe_stream([b"chunk-1", b"chunk-2"], "audio/webm", "zh")]

    assert [event.type for event in events] == ["partial", "partial", "final"]
    assert isinstance(events[0], TranscriptionPartialEvent)
    assert events[0].index == 0
    assert events[0].text == "语音"
    assert events[0].is_final is False
    assert isinstance(events[1], TranscriptionPartialEvent)
    assert events[1].index == 1
    assert events[1].text == "语音转写文本"
    assert isinstance(events[2], TranscriptionFinalEvent)
    assert events[2].result.text == "语音转写文本"
    assert events[2].result.provider == "fake"
    assert events[2].result.model == "fake-asr-v1"


@pytest.mark.asyncio
async def test_asr_service_stream_validates_partial_and_final_events() -> None:
    service = ASRService(FakeASRProvider(text="语音转写文本", detected_language="zh"), Settings())

    events = [event async for event in service.transcribe_stream([b"chunk-1", b"chunk-2"], "audio/webm", "zh")]

    assert [event.type for event in events] == ["partial", "partial", "final"]
    assert events[-1].result.text == "语音转写文本"


@pytest.mark.asyncio
async def test_asr_service_stream_rejects_unsupported_provider() -> None:
    class BatchOnlyProvider:
        async def transcribe(self, audio_bytes: bytes, media_type: str, language: str | None = None):
            raise AssertionError("batch transcribe must not be called for streaming")

    service = ASRService(BatchOnlyProvider(), Settings())

    with pytest.raises(ASRUnavailableError, match="不支持流式转写"):
        _ = [event async for event in service.transcribe_stream([b"chunk-1"], "audio/webm", "zh")]
