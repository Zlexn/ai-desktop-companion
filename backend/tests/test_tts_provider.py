from __future__ import annotations

import wave
from io import BytesIO

import pytest

from app.core.errors import TTSTimeoutError, TTSUnavailableError
from app.tts.fake_provider import FakeTTSProvider


@pytest.mark.asyncio
async def test_fake_tts_returns_valid_deterministic_wav() -> None:
    provider = FakeTTSProvider()

    first = await provider.synthesize("雪乃测试音", "fake-default", 1.0)
    second = await provider.synthesize("雪乃测试音", "fake-default", 1.0)

    assert first.audio_bytes == second.audio_bytes
    assert first.audio_bytes.startswith(b"RIFF")
    assert first.audio_bytes[8:12] == b"WAVE"
    assert first.media_type == "audio/wav"
    assert first.provider == "fake"
    assert first.model == "fake-tone-v1"
    assert first.sample_rate == 16_000
    assert 120 <= first.duration_ms <= 900

    with wave.open(BytesIO(first.audio_bytes), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 16_000
        assert wav_file.getnframes() > 0


@pytest.mark.asyncio
async def test_fake_tts_duration_is_bounded_for_long_text() -> None:
    result = await FakeTTSProvider().synthesize("长文本" * 1000, "fake-default", 1.0)

    assert 120 <= result.duration_ms <= FakeTTSProvider.max_duration_ms


@pytest.mark.asyncio
async def test_fake_tts_speed_changes_duration() -> None:
    provider = FakeTTSProvider()

    slow = await provider.synthesize("语速测试", "fake-default", 0.5)
    fast = await provider.synthesize("语速测试", "fake-default", 2.0)

    assert slow.duration_ms > fast.duration_ms
    assert slow.audio_bytes != fast.audio_bytes


@pytest.mark.asyncio
async def test_fake_tts_error_modes_raise_deterministic_errors() -> None:
    with pytest.raises(TTSUnavailableError):
        await FakeTTSProvider(mode="error").synthesize("测试", "fake-default", 1.0)

    with pytest.raises(TTSTimeoutError):
        await FakeTTSProvider(mode="timeout").synthesize("测试", "fake-default", 1.0)


@pytest.mark.asyncio
async def test_fake_tts_empty_mode_returns_empty_audio_for_service_validation() -> None:
    result = await FakeTTSProvider(mode="empty").synthesize("测试", "fake-default", 1.0)

    assert result.audio_bytes == b""
    assert result.media_type == "audio/wav"
    assert result.duration_ms == 0
