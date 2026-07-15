from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.errors import TTSInvalidRequestError, TTSInvalidResponseError, TTSTimeoutError, TTSUnavailableError
from app.services.tts_service import TTSService
from app.tts.base import SpeechSynthesisResult
from app.tts.cosyvoice_http_provider import CosyVoiceHTTPProvider
from app.tts.factory import create_tts_provider
from app.tts.fake_provider import FakeTTSProvider


def test_tts_service_validate_speed_accepts_boundaries() -> None:
    assert TTSService.validate_speed(0.5) == 0.5
    assert TTSService.validate_speed(2.0) == 2.0


@pytest.mark.parametrize("speed", [0.49, 2.01, float("inf"), float("nan")])
def test_tts_service_validate_speed_rejects_invalid_values(speed: float) -> None:
    with pytest.raises(TTSInvalidRequestError):
        TTSService.validate_speed(speed)


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
async def test_tts_service_rejects_empty_or_blank_text(text: str) -> None:
    service = TTSService(FakeTTSProvider(), Settings())

    with pytest.raises(TTSInvalidRequestError):
        await service.synthesize(text)


@pytest.mark.asyncio
async def test_tts_service_rejects_text_over_configured_limit() -> None:
    service = TTSService(FakeTTSProvider(), Settings(tts_max_text_chars=5))

    with pytest.raises(TTSInvalidRequestError):
        await service.synthesize("超过五个字符")


@pytest.mark.asyncio
@pytest.mark.parametrize("speed", [0.0, 0.49, 2.01, float("inf"), float("nan")])
async def test_tts_service_rejects_invalid_speed(speed: float) -> None:
    service = TTSService(FakeTTSProvider(), Settings())

    with pytest.raises(TTSInvalidRequestError):
        await service.synthesize("测试", speed=speed)


@pytest.mark.asyncio
async def test_tts_service_rejects_unknown_voice_id() -> None:
    service = TTSService(FakeTTSProvider(), Settings(tts_default_voice="fake-default"))

    with pytest.raises(TTSInvalidRequestError):
        await service.synthesize("测试", voice_id="unknown")


@pytest.mark.asyncio
async def test_tts_service_maps_empty_provider_audio_to_invalid_response() -> None:
    service = TTSService(FakeTTSProvider(mode="empty"), Settings())

    with pytest.raises(TTSInvalidResponseError):
        await service.synthesize("测试")


@pytest.mark.asyncio
async def test_tts_service_preserves_provider_timeout_and_unavailable_errors() -> None:
    with pytest.raises(TTSTimeoutError):
        await TTSService(FakeTTSProvider(mode="timeout"), Settings()).synthesize("测试")

    with pytest.raises(TTSUnavailableError):
        await TTSService(FakeTTSProvider(mode="error"), Settings()).synthesize("测试")


@pytest.mark.asyncio
async def test_tts_service_wraps_unexpected_provider_exception() -> None:
    class BrokenProvider:
        async def synthesize(self, text: str, voice_id: str | None = None, speed: float = 1.0) -> SpeechSynthesisResult:
            raise RuntimeError("boom")

    with pytest.raises(TTSUnavailableError):
        await TTSService(BrokenProvider(), Settings()).synthesize("测试")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        SpeechSynthesisResult(b"abc", "text/plain", 16_000, 100, "fake", "fake-tone-v1"),
        SpeechSynthesisResult(b"abc", "audio/wav", 0, 100, "fake", "fake-tone-v1"),
        SpeechSynthesisResult(b"abc", "audio/wav", 16_000, 0, "fake", "fake-tone-v1"),
        SpeechSynthesisResult(b"abc", "audio/wav", 16_000, 100, "", "fake-tone-v1"),
        SpeechSynthesisResult(b"abc", "audio/wav", 16_000, 100, "fake", ""),
    ],
)
async def test_tts_service_rejects_invalid_provider_metadata(result: SpeechSynthesisResult) -> None:
    class InvalidProvider:
        async def synthesize(self, text: str, voice_id: str | None = None, speed: float = 1.0) -> SpeechSynthesisResult:
            return result

    with pytest.raises(TTSInvalidResponseError):
        await TTSService(InvalidProvider(), Settings()).synthesize("测试")


def test_tts_factory_creates_fake_provider() -> None:
    provider = create_tts_provider(Settings(tts_provider="fake"))

    assert isinstance(provider, FakeTTSProvider)


def test_tts_factory_creates_cosyvoice_http_provider() -> None:
    provider = create_tts_provider(
        Settings(
            tts_provider="cosyvoice-http",
            tts_cosyvoice_base_url="http://127.0.0.1:9001",
            tts_cosyvoice_model="test-model",
            tts_default_voice="test-voice",
        )
    )

    assert isinstance(provider, CosyVoiceHTTPProvider)


def test_tts_factory_rejects_unknown_provider_without_fallback() -> None:
    with pytest.raises(ValueError, match="Unsupported TTS_PROVIDER"):
        create_tts_provider(Settings(tts_provider="unknown"))
