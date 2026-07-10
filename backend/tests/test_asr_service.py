from __future__ import annotations

import asyncio
import builtins

import pytest

from app.asr.base import TranscriptionResult
from app.asr.fake_provider import FakeASRProvider
from app.core.config import Settings
from app.core.errors import (
    ASRFileTooLargeError,
    ASRInvalidAudioError,
    ASRInvalidRequestError,
    ASRInvalidResponseError,
    ASRTimeoutError,
    ASRUnavailableError,
    ASRUnsupportedMediaTypeError,
)
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.services.asr_service import ASRService


MINIMAL_WEBM_SIGNATURE_FIXTURE = b"\x1a\x45\xdf\xa3minimal-webm-signature-fixture"
MINIMAL_MP4_SIGNATURE_FIXTURE = b"\x00\x00\x00\x18ftypmp42minimal-mp4-signature-fixture"
MINIMAL_WAV_SIGNATURE_FIXTURE = b"RIFF\x24\x00\x00\x00WAVEfmt minimal-wav-signature-fixture"


@pytest.mark.asyncio
@pytest.mark.parametrize("audio", [b"", b"   "])
async def test_asr_service_rejects_empty_bytes(audio: bytes) -> None:
    service = ASRService(FakeASRProvider(), Settings())

    with pytest.raises(ASRInvalidRequestError) as exc_info:
        await service.transcribe(audio, "audio/wav", "zh")

    assert exc_info.value.to_response().code == "asr_invalid_request"


@pytest.mark.asyncio
async def test_asr_service_rejects_oversized_content() -> None:
    service = ASRService(FakeASRProvider(), Settings(asr_max_upload_bytes=10))

    with pytest.raises(ASRFileTooLargeError) as exc_info:
        await service.transcribe(MINIMAL_WEBM_SIGNATURE_FIXTURE, "audio/webm", "zh")

    assert exc_info.value.to_response().code == "asr_file_too_large"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("media_type", "audio"),
    [
        ("audio/webm", MINIMAL_WEBM_SIGNATURE_FIXTURE),
        ("audio/webm;codecs=opus", MINIMAL_WEBM_SIGNATURE_FIXTURE),
        ("Audio/WebM; codecs=opus", MINIMAL_WEBM_SIGNATURE_FIXTURE),
        ("audio/mp4", MINIMAL_MP4_SIGNATURE_FIXTURE),
        ("audio/wav", MINIMAL_WAV_SIGNATURE_FIXTURE),
        ("audio/x-wav", MINIMAL_WAV_SIGNATURE_FIXTURE),
    ],
)
async def test_asr_service_accepts_supported_media_types_and_signature_fixtures(media_type: str, audio: bytes) -> None:
    service = ASRService(FakeASRProvider(text="签名测试"), Settings())

    result = await service.transcribe(audio, media_type, "zh")

    assert result.text == "签名测试"
    assert result.provider == "fake"
    assert result.model == "fake-asr-v1"
    assert result.duration_ms is None


@pytest.mark.asyncio
async def test_asr_service_rejects_unsupported_media_type() -> None:
    service = ASRService(FakeASRProvider(), Settings())

    with pytest.raises(ASRUnsupportedMediaTypeError) as exc_info:
        await service.transcribe(b"not-a-container", "audio/ogg", "zh")

    assert exc_info.value.to_response().code == "asr_unsupported_media_type"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("media_type", "audio"),
    [
        ("audio/webm", b"not-webm"),
        ("audio/mp4", b"not-mp4"),
        ("audio/mp4", b"junkftypnot-an-mp4"),
        ("audio/mp4", b"\x00\x00\x00\x03ftypmp42"),
        ("audio/wav", b"not-wav"),
        ("audio/x-wav", b"not-wav"),
    ],
)
async def test_asr_service_rejects_media_type_signature_conflicts(media_type: str, audio: bytes) -> None:
    service = ASRService(FakeASRProvider(), Settings())

    with pytest.raises(ASRInvalidAudioError) as exc_info:
        await service.transcribe(audio, media_type, "zh")

    assert exc_info.value.to_response().code == "asr_invalid_audio"


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["", " ", "zh!", "中文", "a" * 33])
async def test_asr_service_rejects_invalid_language_hint(language: str) -> None:
    service = ASRService(FakeASRProvider(), Settings())

    with pytest.raises(ASRInvalidRequestError):
        await service.transcribe(MINIMAL_WAV_SIGNATURE_FIXTURE, "audio/wav", language)


@pytest.mark.asyncio
async def test_asr_service_uses_default_language_when_hint_is_none() -> None:
    service = ASRService(FakeASRProvider(), Settings(asr_default_language="zh"))

    result = await service.transcribe(MINIMAL_WAV_SIGNATURE_FIXTURE, "audio/wav", None)

    assert result.detected_language == "zh"


@pytest.mark.asyncio
async def test_asr_service_maps_empty_transcript_to_invalid_response() -> None:
    service = ASRService(FakeASRProvider(mode="empty"), Settings())

    with pytest.raises(ASRInvalidResponseError) as exc_info:
        await service.transcribe(MINIMAL_WAV_SIGNATURE_FIXTURE, "audio/wav", "zh")

    assert exc_info.value.to_response().code == "asr_invalid_response"


@pytest.mark.asyncio
async def test_asr_service_maps_provider_timeout_and_error() -> None:
    with pytest.raises(ASRTimeoutError) as timeout_info:
        await ASRService(FakeASRProvider(mode="timeout"), Settings()).transcribe(MINIMAL_WAV_SIGNATURE_FIXTURE, "audio/wav", "zh")
    assert timeout_info.value.to_response().code == "asr_timeout"

    with pytest.raises(ASRUnavailableError) as unavailable_info:
        await ASRService(FakeASRProvider(mode="error"), Settings()).transcribe(MINIMAL_WAV_SIGNATURE_FIXTURE, "audio/wav", "zh")
    assert unavailable_info.value.to_response().code == "asr_unavailable"


@pytest.mark.asyncio
async def test_asr_service_maps_generic_provider_timeout_to_asr_timeout() -> None:
    class TimeoutProvider:
        async def transcribe(self, audio_bytes: bytes, media_type: str, language: str | None = None) -> TranscriptionResult:
            raise TimeoutError("provider timed out")

    with pytest.raises(ASRTimeoutError):
        await ASRService(TimeoutProvider(), Settings()).transcribe(MINIMAL_WAV_SIGNATURE_FIXTURE, "audio/wav", "zh")


@pytest.mark.asyncio
async def test_asr_service_maps_asyncio_timeout_to_asr_timeout() -> None:
    class TimeoutProvider:
        async def transcribe(self, audio_bytes: bytes, media_type: str, language: str | None = None) -> TranscriptionResult:
            raise asyncio.TimeoutError("provider timed out")

    with pytest.raises(ASRTimeoutError):
        await ASRService(TimeoutProvider(), Settings()).transcribe(MINIMAL_WAV_SIGNATURE_FIXTURE, "audio/wav", "zh")


@pytest.mark.asyncio
async def test_asr_service_rejects_provider_duration_below_configured_minimum() -> None:
    class ShortDurationProvider:
        async def transcribe(self, audio_bytes: bytes, media_type: str, language: str | None = None) -> TranscriptionResult:
            return TranscriptionResult("测试", "zh", 100, "fake", "fake-asr-v1", 0)

    with pytest.raises(ASRInvalidResponseError):
        await ASRService(ShortDurationProvider(), Settings(asr_min_duration_ms=300)).transcribe(
            MINIMAL_WAV_SIGNATURE_FIXTURE,
            "audio/wav",
            "zh",
        )


@pytest.mark.asyncio
async def test_asr_service_wraps_unexpected_provider_exception() -> None:
    class BrokenProvider:
        async def transcribe(self, audio_bytes: bytes, media_type: str, language: str | None = None) -> TranscriptionResult:
            raise RuntimeError("boom")

    with pytest.raises(ASRUnavailableError):
        await ASRService(BrokenProvider(), Settings()).transcribe(MINIMAL_WAV_SIGNATURE_FIXTURE, "audio/wav", "zh")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        TranscriptionResult("", "zh", None, "fake", "fake-asr-v1", 0),
        TranscriptionResult("   ", "zh", None, "fake", "fake-asr-v1", 0),
        TranscriptionResult("测试", "zh", None, "", "fake-asr-v1", 0),
        TranscriptionResult("测试", "zh", None, "fake", "", 0),
        TranscriptionResult("测试", "zh", None, "fake", "fake-asr-v1", -1),
        TranscriptionResult("测试", "zh", -1, "fake", "fake-asr-v1", 0),
        TranscriptionResult("测试", "zh", 30_001, "fake", "fake-asr-v1", 0),
    ],
)
async def test_asr_service_rejects_invalid_provider_response_metadata(result: TranscriptionResult) -> None:
    class InvalidProvider:
        async def transcribe(self, audio_bytes: bytes, media_type: str, language: str | None = None) -> TranscriptionResult:
            return result

    with pytest.raises(ASRInvalidResponseError):
        await ASRService(InvalidProvider(), Settings(asr_max_duration_ms=30_000)).transcribe(
            MINIMAL_WAV_SIGNATURE_FIXTURE,
            "audio/wav",
            "zh",
        )


@pytest.mark.asyncio
async def test_asr_service_does_not_create_chat_sessions_or_messages(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        before_sessions = sessions.list()

        service = ASRService(FakeASRProvider(), Settings(database_url=database_url))
        await service.transcribe(MINIMAL_WAV_SIGNATURE_FIXTURE, "audio/wav", "zh")

        after_sessions = sessions.list()
        assert after_sessions == before_sessions
        assert messages.list("missing-session") == []


@pytest.mark.asyncio
async def test_asr_service_does_not_write_files(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden_open(*args, **kwargs):
        raise AssertionError("ASR foundation must not write or read audio files")

    monkeypatch.setattr(builtins, "open", forbidden_open)
    service = ASRService(FakeASRProvider(), Settings())

    result = await service.transcribe(MINIMAL_WAV_SIGNATURE_FIXTURE, "audio/wav", "zh")

    assert result.text == "这是 Fake ASR 测试转写。"


@pytest.mark.asyncio
async def test_asr_service_does_not_access_network(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        import httpx
    except ImportError:  # pragma: no cover - httpx is a project dependency
        httpx = None

    if httpx is not None:
        def forbidden_client(*args, **kwargs):
            raise AssertionError("ASR foundation must not access network")

        monkeypatch.setattr(httpx, "AsyncClient", forbidden_client)

    service = ASRService(FakeASRProvider(), Settings())
    result = await service.transcribe(MINIMAL_WEBM_SIGNATURE_FIXTURE, "audio/webm", "zh")

    assert result.text == "这是 Fake ASR 测试转写。"
