from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


def parse_ndjson(body: bytes) -> list[dict[str, object]]:
    return [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]


def test_transcriptions_stream_returns_start_partial_final_and_done(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'stream-asr.db'}")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("ASR_PROVIDER", "fake")
    monkeypatch.setenv("FAKE_ASR_TEXT", "语音转写文本")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/audio/transcriptions/stream",
            files=[("chunks", ("chunk.webm", b"\x1a\x45\xdf\xa3chunk", "audio/webm"))],
            data={"language": "zh"},
        )

    get_settings.cache_clear()
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = parse_ndjson(response.content)
    assert events[0] == {"type": "start", "provider": "fake", "model": "fake-asr-v1"}
    assert events[1] == {"type": "partial", "index": 0, "text": "语音", "is_final": False, "audio_ms": 1000}
    assert events[2] == {"type": "partial", "index": 1, "text": "语音转写文本", "is_final": False, "audio_ms": 2000}
    assert events[3] == {
        "type": "final",
        "text": "语音转写文本",
        "detected_language": "zh",
        "duration_ms": None,
        "provider": "fake",
        "model": "fake-asr-v1",
        "inference_ms": 0,
    }
    assert events[-1] == {"type": "done"}
