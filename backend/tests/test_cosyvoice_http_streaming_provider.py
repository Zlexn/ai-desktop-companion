from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.core.errors import TTSInvalidResponseError, TTSTimeoutError, TTSUnavailableError
from app.tts.cosyvoice_http_provider import CosyVoiceHTTPProvider


OriginalAsyncClient = httpx.AsyncClient


def patch_async_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: OriginalAsyncClient(transport=httpx.MockTransport(handler), **kwargs),
    )


def wav_bytes(label: str = "first") -> bytes:
    return b"RIFF" + label.encode("utf-8") + b"WAVE"


def ndjson_line(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


@pytest.mark.asyncio
async def test_cosyvoice_http_provider_streams_ordered_wav_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/audio/speech"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["stream"] is True
        assert payload["response_format"] == "wav"
        assert payload["input"] == "第一句。第二句。"
        body = b"".join([
            ndjson_line({"type": "start", "provider": "cosyvoice-http", "model": "test-model"}),
            ndjson_line({
                "type": "segment",
                "index": 0,
                "audio_base64": base64.b64encode(wav_bytes("one")).decode("ascii"),
                "media_type": "audio/wav",
                "duration_ms": 120,
                "sample_rate": 24000,
            }),
            ndjson_line({
                "type": "segment",
                "index": 1,
                "audio_base64": base64.b64encode(wav_bytes("two")).decode("ascii"),
                "media_type": "audio/wav",
                "duration_ms": 140,
                "sample_rate": 24000,
            }),
            ndjson_line({"type": "done", "segment_count": 2}),
        ])
        return httpx.Response(200, content=body, headers={"Content-Type": "application/x-ndjson"})

    patch_async_client(monkeypatch, handler)
    provider = CosyVoiceHTTPProvider(
        base_url="http://cosyvoice.local",
        model="test-model",
        default_voice="default-zh-female",
        timeout_seconds=5,
    )

    segments = [segment async for segment in provider.synthesize_stream("第一句。第二句。")]

    assert [segment.index for segment in segments] == [0, 1]
    assert [segment.audio_bytes for segment in segments] == [wav_bytes("one"), wav_bytes("two")]
    assert all(segment.media_type == "audio/wav" for segment in segments)
    assert all(segment.sample_rate == 24000 for segment in segments)
    assert [segment.duration_ms for segment in segments] == [120, 140]
    assert all(segment.provider == "cosyvoice-http" for segment in segments)
    assert all(segment.model == "test-model" for segment in segments)


@pytest.mark.asyncio
async def test_cosyvoice_http_provider_stream_rejects_malformed_segment(monkeypatch: pytest.MonkeyPatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = ndjson_line({"type": "segment", "index": 0, "audio_base64": "", "media_type": "audio/wav", "duration_ms": 0, "sample_rate": 0})
        return httpx.Response(200, content=body, headers={"Content-Type": "application/x-ndjson"})

    patch_async_client(monkeypatch, handler)
    provider = CosyVoiceHTTPProvider(base_url="http://cosyvoice.local", model="test-model", default_voice="default", timeout_seconds=5)

    with pytest.raises(TTSInvalidResponseError):
        _ = [segment async for segment in provider.synthesize_stream("测试")]


@pytest.mark.asyncio
async def test_cosyvoice_http_provider_stream_maps_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"error": "bad gateway"})

    patch_async_client(monkeypatch, handler)
    provider = CosyVoiceHTTPProvider(base_url="http://cosyvoice.local", model="test-model", default_voice="default", timeout_seconds=5)

    with pytest.raises(TTSUnavailableError):
        _ = [segment async for segment in provider.synthesize_stream("测试")]


@pytest.mark.asyncio
async def test_cosyvoice_http_provider_stream_maps_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    patch_async_client(monkeypatch, handler)
    provider = CosyVoiceHTTPProvider(base_url="http://cosyvoice.local", model="test-model", default_voice="default", timeout_seconds=5)

    with pytest.raises(TTSTimeoutError):
        _ = [segment async for segment in provider.synthesize_stream("测试")]
