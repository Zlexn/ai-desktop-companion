from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.dependencies import get_tts_service
from app.core.config import get_settings
from app.core.errors import TTSUnavailableError
from app.main import create_app
from app.tts.base import SpeechSynthesisSegment


def parse_ndjson(body: bytes) -> list[dict[str, object]]:
    return [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]


def test_speech_stream_api_emits_start_segments_and_done(client: TestClient) -> None:
    response = client.post("/api/audio/speech/stream", json={"text": "第一句。第二句。", "voice_id": "fake-default", "speed": 1.0})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = parse_ndjson(response.content)
    assert events[0] == {"type": "start", "provider": "fake", "model": "fake-tone-v1"}
    segments = [event for event in events if event["type"] == "segment"]
    assert [segment["index"] for segment in segments] == [0, 1]
    for segment in segments:
        audio_bytes = base64.b64decode(segment["audio_base64"])
        assert audio_bytes.startswith(b"RIFF")
        assert audio_bytes[8:12] == b"WAVE"
        assert segment["media_type"] == "audio/wav"
        assert segment["sample_rate"] == 16000
        assert int(segment["duration_ms"]) > 0
    assert events[-1] == {"type": "done", "segment_count": 2}


def test_speech_stream_api_rejects_blank_text_before_streaming(client: TestClient) -> None:
    response = client.post("/api/audio/speech/stream", json={"text": "   "})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "tts_invalid_request"


class LeakingAfterFirstSegmentTTSService:
    async def synthesize_stream(
        self,
        text: str,
        voice_id: str | None = None,
        speed: float | None = None,
    ) -> AsyncIterator[SpeechSynthesisSegment]:
        yield SpeechSynthesisSegment(
            b"RIFF", "audio/wav", 16_000, 100, "recording", "v1", 0
        )
        raise TTSUnavailableError("upstream secret: http://internal.local?token=abc")


def test_legacy_speech_stream_hides_post_start_provider_error(client: TestClient) -> None:
    client.app.dependency_overrides[get_tts_service] = LeakingAfterFirstSegmentTTSService
    try:
        response = client.post("/api/audio/speech/stream", json={"text": "测试"})
    finally:
        client.app.dependency_overrides.pop(get_tts_service, None)

    assert response.status_code == 200
    events = parse_ndjson(response.content)
    assert events[-1] == {"type": "error", "message": "语音合成失败，请稍后重试。"}
    assert "secret" not in response.text
    assert "internal.local" not in response.text
    assert "token" not in response.text


def make_client_with_tts_provider(tmp_path: Path, monkeypatch, provider: str) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / f'{provider}.db'}")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("TTS_PROVIDER", provider)
    if provider == "cosyvoice-http":
        monkeypatch.setenv("TTS_COSYVOICE_BASE_URL", "http://127.0.0.1:1")
        monkeypatch.setenv("TTS_COSYVOICE_MODEL", "test-model")
    get_settings.cache_clear()
    return TestClient(create_app())


def test_speech_stream_api_reports_unsupported_provider_before_streaming(tmp_path: Path, monkeypatch) -> None:
    with make_client_with_tts_provider(tmp_path, monkeypatch, "cosyvoice-http") as client:
        response = client.post("/api/audio/speech/stream", json={"text": "测试"})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "tts_unavailable"
    get_settings.cache_clear()
