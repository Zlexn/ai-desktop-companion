from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app

OriginalAsyncClient = httpx.AsyncClient


def parse_ndjson(body: bytes) -> list[dict[str, object]]:
    return [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]


def wav_bytes() -> bytes:
    return b"RIFFcosyWAVE"


def make_stream_line(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


def test_speech_stream_api_uses_cosyvoice_http_streaming_provider(tmp_path: Path, monkeypatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/audio/speech"
        body = json.loads(request.content.decode("utf-8"))
        assert body["stream"] is True
        stream_body = b"".join([
            make_stream_line({"type": "start", "provider": "cosyvoice-http", "model": "test-model"}),
            make_stream_line({
                "type": "segment",
                "index": 0,
                "audio_base64": base64.b64encode(wav_bytes()).decode("ascii"),
                "media_type": "audio/wav",
                "duration_ms": 100,
                "sample_rate": 24000,
            }),
            make_stream_line({"type": "done", "segment_count": 1}),
        ])
        return httpx.Response(200, content=stream_body, headers={"Content-Type": "application/x-ndjson"})

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'cosyvoice-stream.db'}")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("TTS_PROVIDER", "cosyvoice-http")
    monkeypatch.setenv("TTS_COSYVOICE_BASE_URL", "http://cosyvoice.local")
    monkeypatch.setenv("TTS_COSYVOICE_MODEL", "test-model")
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: OriginalAsyncClient(transport=httpx.MockTransport(handler), **kwargs),
    )
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        response = client.post("/api/audio/speech/stream", json={"text": "测试真实流式语音。"})

    get_settings.cache_clear()
    assert response.status_code == 200
    events = parse_ndjson(response.content)
    assert events[0] == {"type": "start", "provider": "cosyvoice-http", "model": "test-model"}
    assert events[1]["type"] == "segment"
    assert events[1]["index"] == 0
    assert base64.b64decode(events[1]["audio_base64"]) == wav_bytes()
    assert events[1]["sample_rate"] == 24000
    assert events[-1] == {"type": "done", "segment_count": 1}
