from __future__ import annotations

import pytest

from app.core.errors import TTSTimeoutError, TTSUnavailableError
from app.tts.cosyvoice_http_provider import CosyVoiceHTTPProvider


class _FakeResponse:
    def __init__(self, *, content: bytes = b"RIFF....WAVE", headers: dict[str, str] | None = None) -> None:
        self.content = content
        self.headers = headers or {
            "content-type": "audio/wav",
            "X-Audio-Sample-Rate": "24000",
            "X-Audio-Duration-Ms": "1200",
        }

    def raise_for_status(self) -> None:
        return None


@pytest.mark.asyncio
async def test_cosyvoice_http_provider_posts_openai_compatible_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeClient:
        def __init__(self, *, timeout: float, trust_env: bool) -> None:
            assert timeout == 12.0
            assert trust_env is False

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, url: str, json: dict[str, object]) -> _FakeResponse:
            calls.append((url, json))
            return _FakeResponse()

    monkeypatch.setattr("app.tts.cosyvoice_http_provider.httpx.AsyncClient", FakeClient)
    provider = CosyVoiceHTTPProvider(
        base_url="http://127.0.0.1:9001/",
        model="test-model",
        default_voice="test-voice",
        timeout_seconds=12.0,
    )

    result = await provider.synthesize("你好", speed=1.25)

    assert calls == [
        (
            "http://127.0.0.1:9001/v1/audio/speech",
            {
                "model": "test-model",
                "input": "你好",
                "voice": "test-voice",
                "response_format": "wav",
                "speed": 1.25,
            },
        )
    ]
    assert result.audio_bytes.startswith(b"RIFF")
    assert result.media_type == "audio/wav"
    assert result.sample_rate == 24000
    assert result.duration_ms == 1200
    assert result.provider == "cosyvoice-http"
    assert result.model == "test-model"


@pytest.mark.asyncio
async def test_cosyvoice_http_provider_maps_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        def __init__(self, *, timeout: float, trust_env: bool) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, url: str, json: dict[str, object]) -> _FakeResponse:
            import httpx

            raise httpx.TimeoutException("timeout")

    monkeypatch.setattr("app.tts.cosyvoice_http_provider.httpx.AsyncClient", FakeClient)
    provider = CosyVoiceHTTPProvider(
        base_url="http://127.0.0.1:9001",
        model="test-model",
        default_voice="test-voice",
        timeout_seconds=1.0,
    )

    with pytest.raises(TTSTimeoutError):
        await provider.synthesize("你好")


@pytest.mark.asyncio
async def test_cosyvoice_http_provider_maps_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        def __init__(self, *, timeout: float, trust_env: bool) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, url: str, json: dict[str, object]) -> _FakeResponse:
            import httpx

            raise httpx.ConnectError("connection failed")

    monkeypatch.setattr("app.tts.cosyvoice_http_provider.httpx.AsyncClient", FakeClient)
    provider = CosyVoiceHTTPProvider(
        base_url="http://127.0.0.1:9001",
        model="test-model",
        default_voice="test-voice",
        timeout_seconds=1.0,
    )

    with pytest.raises(TTSUnavailableError):
        await provider.synthesize("你好")
