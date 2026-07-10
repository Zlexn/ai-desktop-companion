from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


def parse_ndjson(body: bytes) -> list[dict[str, object]]:
    return [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]


def test_faster_whisper_streaming_disabled_returns_clear_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'disabled.db'}")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("ASR_PROVIDER", "faster-whisper")
    monkeypatch.setenv("ASR_FASTER_WHISPER_MODEL_PATH", str(tmp_path))
    monkeypatch.setenv("ASR_FASTER_WHISPER_STREAMING_ENABLED", "false")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/audio/transcriptions/stream",
            files=[("chunks", ("chunk.webm", b"\x1a\x45\xdf\xa3chunk", "audio/webm"))],
            data={"language": "zh"},
        )

    get_settings.cache_clear()
    assert response.status_code in {502, 503, 504}
    assert "流式" in response.text or "stream" in response.text.lower()


def test_faster_whisper_streaming_enabled_returns_partial_final_done(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'enabled.db'}")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("ASR_PROVIDER", "faster-whisper")
    monkeypatch.setenv("ASR_FASTER_WHISPER_MODEL_PATH", str(tmp_path))
    monkeypatch.setenv("ASR_FASTER_WHISPER_MODEL_NAME", "medium")
    monkeypatch.setenv("ASR_FASTER_WHISPER_MODEL_REVISION", "test")
    monkeypatch.setenv("ASR_FASTER_WHISPER_STREAMING_ENABLED", "true")
    get_settings.cache_clear()

    from app.asr.base import TranscriptionFinalEvent, TranscriptionPartialEvent, TranscriptionResult
    from app.asr.faster_whisper_provider import FasterWhisperASRProvider

    async def fake_stream(self, audio_chunks, media_type, language=None):
        yield TranscriptionPartialEvent(type="partial", index=0, text="真实", is_final=False, audio_ms=1000, provider=self.provider_name, model=self.public_model_name)
        yield TranscriptionFinalEvent(
            type="final",
            result=TranscriptionResult(
                text="真实转写",
                detected_language="zh",
                duration_ms=1200,
                provider="faster-whisper",
                model="medium@test",
                inference_ms=123,
            ),
        )

    monkeypatch.setattr(FasterWhisperASRProvider, "transcribe_stream", fake_stream)

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/audio/transcriptions/stream",
            files=[("chunks", ("chunk.webm", b"\x1a\x45\xdf\xa3chunk", "audio/webm"))],
            data={"language": "zh"},
        )

    get_settings.cache_clear()
    assert response.status_code == 200
    events = parse_ndjson(response.content)
    assert events[0] == {"type": "start", "provider": "faster-whisper", "model": "medium@test"}
    assert events[1] == {"type": "partial", "index": 0, "text": "真实", "is_final": False, "audio_ms": 1000}
    assert events[2]["type"] == "final"
    assert events[2]["text"] == "真实转写"
    assert events[-1] == {"type": "done"}
