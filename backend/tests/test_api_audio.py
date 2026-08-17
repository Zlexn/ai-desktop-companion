from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


def test_speech_api_returns_binary_wav_and_headers(client: TestClient) -> None:
    response = client.post("/api/audio/speech", json={"text": "雪乃测试音", "voice_id": "fake-default", "speed": 1.0})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content.startswith(b"RIFF")
    assert response.content[8:12] == b"WAVE"
    assert response.headers["x-tts-provider"] == "fake"
    assert response.headers["x-tts-model"] == "fake-tone-v1"
    assert int(response.headers["x-audio-duration-ms"]) > 0
    assert response.headers["x-audio-sample-rate"] == "16000"


def test_speech_api_does_not_create_sessions_or_messages(client: TestClient) -> None:
    before = client.get("/api/sessions")
    assert before.status_code == 200
    assert before.json() == []

    response = client.post("/api/audio/speech", json={"text": "只合成测试音"})

    assert response.status_code == 200
    after = client.get("/api/sessions")
    assert after.status_code == 200
    assert after.json() == []


def test_speech_api_rejects_blank_text(client: TestClient) -> None:
    response = client.post("/api/audio/speech", json={"text": "   "})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "tts_invalid_request"
    assert "堆栈" not in response.text
    assert "Traceback" not in response.text


def test_speech_api_rejects_unknown_voice_id(client: TestClient) -> None:
    response = client.post("/api/audio/speech", json={"text": "测试", "voice_id": "unknown"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "tts_invalid_request"


def test_speech_api_rejects_invalid_speed(client: TestClient) -> None:
    response = client.post("/api/audio/speech", json={"text": "测试", "speed": 9.0})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "tts_invalid_request"


def test_speech_api_rejects_overlong_text(client: TestClient) -> None:
    response = client.post("/api/audio/speech", json={"text": "太" * 1001})

    assert response.status_code == 422


def make_client_with_tts_mode(tmp_path: Path, monkeypatch, mode: str) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / f'{mode}.db'}")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("TTS_PROVIDER", "fake")
    monkeypatch.setenv("TTS_FAKE_MODE", mode)
    get_settings.cache_clear()
    return TestClient(create_app())


def test_speech_api_maps_empty_provider_response(tmp_path: Path, monkeypatch) -> None:
    with make_client_with_tts_mode(tmp_path, monkeypatch, "empty") as client:
        response = client.post("/api/audio/speech", json={"text": "测试"})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "tts_invalid_response"
    assert "Traceback" not in response.text
    get_settings.cache_clear()


def test_speech_api_maps_provider_error(tmp_path: Path, monkeypatch) -> None:
    with make_client_with_tts_mode(tmp_path, monkeypatch, "error") as client:
        response = client.post("/api/audio/speech", json={"text": "测试"})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "tts_unavailable"
    assert "Traceback" not in response.text
    get_settings.cache_clear()


def test_speech_api_maps_provider_timeout(tmp_path: Path, monkeypatch) -> None:
    with make_client_with_tts_mode(tmp_path, monkeypatch, "timeout") as client:
        response = client.post("/api/audio/speech", json={"text": "测试"})

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "tts_timeout"
    assert "Traceback" not in response.text
    get_settings.cache_clear()
