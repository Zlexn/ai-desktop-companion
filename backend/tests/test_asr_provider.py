from __future__ import annotations

import time

import pytest

from app.asr.fake_provider import FakeASRProvider
from app.core.errors import ASRInvalidResponseError, ASRTimeoutError, ASRUnavailableError


@pytest.mark.asyncio
async def test_fake_asr_returns_deterministic_text_and_metadata() -> None:
    provider = FakeASRProvider(text="固定测试转写", detected_language="zh")
    audio = b"\x1a\x45\xdf\xa3minimal-webm-signature-fixture"

    first = await provider.transcribe(audio, "audio/webm", "zh")
    second = await provider.transcribe(audio, "audio/webm", "zh")

    assert first == second
    assert first.text == "固定测试转写"
    assert first.detected_language == "zh"
    assert first.provider == "fake"
    assert first.model == "fake-asr-v1"
    assert first.inference_ms == 0
    assert first.duration_ms is None
    assert first.segments is None


@pytest.mark.asyncio
async def test_fake_asr_uses_valid_language_hint_when_present() -> None:
    provider = FakeASRProvider(text="测试", detected_language="zh")

    result = await provider.transcribe(b"RIFFxxxxWAVE", "audio/wav", "en-US")

    assert result.detected_language == "en-US"


@pytest.mark.asyncio
async def test_fake_asr_invalid_language_hint_falls_back_to_configured_language() -> None:
    provider = FakeASRProvider(text="测试", detected_language="zh")

    result = await provider.transcribe(b"RIFFxxxxWAVE", "audio/wav", "bad language!")

    assert result.detected_language == "zh"


@pytest.mark.asyncio
async def test_fake_asr_empty_mode_returns_empty_text_for_service_validation() -> None:
    result = await FakeASRProvider(mode="empty").transcribe(b"RIFFxxxxWAVE", "audio/wav", "zh")

    assert result.text == ""
    assert result.provider == "fake"
    assert result.model == "fake-asr-v1"
    assert result.duration_ms is None


@pytest.mark.asyncio
async def test_fake_asr_invalid_mode_returns_invalid_metadata_for_service_validation() -> None:
    result = await FakeASRProvider(mode="invalid").transcribe(b"RIFFxxxxWAVE", "audio/wav", "zh")

    assert result.text == "这是 Fake ASR 测试转写。"
    assert result.provider == ""
    assert result.model == ""
    assert result.inference_ms == -1
    assert result.duration_ms is None


@pytest.mark.asyncio
async def test_fake_asr_error_modes_raise_deterministic_errors() -> None:
    with pytest.raises(ASRUnavailableError):
        await FakeASRProvider(mode="error").transcribe(b"RIFFxxxxWAVE", "audio/wav", "zh")

    start = time.perf_counter()
    with pytest.raises(ASRTimeoutError):
        await FakeASRProvider(mode="timeout").transcribe(b"RIFFxxxxWAVE", "audio/wav", "zh")
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert elapsed_ms < 100


@pytest.mark.asyncio
async def test_fake_asr_does_not_use_audio_content_or_summary_in_result() -> None:
    secret_audio = b"RIFFxxxxWAVE-private-audio-content-should-not-appear"

    result = await FakeASRProvider(text="固定文本").transcribe(secret_audio, "audio/wav", "zh")

    rendered = repr(result)
    assert "private-audio-content" not in rendered
    assert "should-not-appear" not in rendered
