from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_tts_service
from app.core.config import get_settings
from app.core.errors import TTSUnavailableError
from app.repositories.sqlite import managed_connection
from app.tts.base import SpeechSynthesisResult, SpeechSynthesisSegment


def create_chat(client: TestClient) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    session = client.post("/api/sessions", json={"title": "bound speech"}).json()
    chat = client.post(
        f"/api/sessions/{session['id']}/messages",
        json={"content": "hello"},
    ).json()
    messages = client.get(f"/api/sessions/{session['id']}/messages").json()
    return session, chat, messages


def parse_ndjson(body: bytes) -> list[dict[str, object]]:
    return [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]


def test_message_speech_synthesizes_chat_response_by_assistant_id(client: TestClient) -> None:
    _, chat, _ = create_chat(client)

    response = client.post(f"/api/messages/{chat['assistant_message_id']}/speech", json={})

    assert response.status_code == 200
    assert response.content[:4] == b"RIFF"
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.headers["x-tts-provider"] == "fake"


@pytest.mark.parametrize(
    "body",
    [
        {"text": "forged"},
        {"delivery": "firm"},
        {"intensity": "medium"},
        {"style": "free-form"},
        {"ssml": "<speak>forged</speak>"},
        {"provider_options": {"pitch": 2}},
    ],
)
def test_message_speech_rejects_client_expression_injection(
    client: TestClient,
    body: dict[str, object],
) -> None:
    _, chat, _ = create_chat(client)

    response = client.post(f"/api/messages/{chat['assistant_message_id']}/speech", json=body)

    assert response.status_code == 422


def test_message_speech_rejects_missing_and_user_messages(client: TestClient) -> None:
    _, _, messages = create_chat(client)

    missing = client.post("/api/messages/missing/speech", json={})
    user = client.post(f"/api/messages/{messages[0]['id']}/speech", json={})

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert user.status_code == 422
    assert user.json()["error"]["code"] == "tts_invalid_request"


def test_message_speech_uses_default_when_plan_is_missing(client: TestClient) -> None:
    _, chat, _ = create_chat(client)
    with managed_connection(get_settings().database_url) as connection:
        connection.execute(
            "DELETE FROM expression_plans WHERE assistant_message_id = ?",
            (chat["assistant_message_id"],),
        )
        connection.commit()

    response = client.post(f"/api/messages/{chat['assistant_message_id']}/speech", json={})

    assert response.status_code == 200
    assert response.content.startswith(b"RIFF")


def test_message_speech_timeout_does_not_delete_persisted_text(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'timeout-message.db'}")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("TTS_PROVIDER", "fake")
    monkeypatch.setenv("TTS_FAKE_MODE", "timeout")
    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as client:
        session, chat, _ = create_chat(client)
        response = client.post(f"/api/messages/{chat['assistant_message_id']}/speech", json={})
        messages = client.get(f"/api/sessions/{session['id']}/messages").json()

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "tts_timeout"
    assert messages[-1]["id"] == chat["assistant_message_id"]
    assert messages[-1]["content"] == chat["reply"]
    get_settings.cache_clear()


def test_message_speech_maps_empty_audio_without_deleting_text(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'empty-message.db'}")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("TTS_PROVIDER", "fake")
    monkeypatch.setenv("TTS_FAKE_MODE", "empty")
    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as client:
        session, chat, _ = create_chat(client)
        response = client.post(f"/api/messages/{chat['assistant_message_id']}/speech", json={})
        messages = client.get(f"/api/sessions/{session['id']}/messages").json()

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "tts_invalid_response"
    assert messages[-1]["id"] == chat["assistant_message_id"]
    get_settings.cache_clear()


def test_message_speech_stream_emits_start_segment_and_done(client: TestClient) -> None:
    _, chat, _ = create_chat(client)

    response = client.post(
        f"/api/messages/{chat['assistant_message_id']}/speech/stream",
        json={},
    )

    assert response.status_code == 200
    events = parse_ndjson(response.content)
    assert events[0] == {"type": "start", "provider": "fake", "model": "fake-tone-v1"}
    assert any(event["type"] == "segment" for event in events)
    assert events[-1]["type"] == "done"


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


def test_message_speech_stream_hides_post_start_provider_error(client: TestClient) -> None:
    _, chat, _ = create_chat(client)
    client.app.dependency_overrides[get_tts_service] = LeakingAfterFirstSegmentTTSService
    try:
        response = client.post(
            f"/api/messages/{chat['assistant_message_id']}/speech/stream",
            json={},
        )
    finally:
        client.app.dependency_overrides.pop(get_tts_service, None)

    assert response.status_code == 200
    events = parse_ndjson(response.content)
    assert events[-1] == {"type": "error", "message": "语音合成失败，请稍后重试。"}
    assert "secret" not in response.text
    assert "internal.local" not in response.text
    assert "token" not in response.text


class RecordingTTSService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, float | None, str]] = []

    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        speed: float | None = None,
    ) -> SpeechSynthesisResult:
        self.calls.append((text, voice_id, speed, "nonstream"))
        return SpeechSynthesisResult(b"RIFF", "audio/wav", 16_000, 100, "recording", "v1")

    async def synthesize_stream(
        self,
        text: str,
        voice_id: str | None = None,
        speed: float | None = None,
    ) -> AsyncIterator[SpeechSynthesisSegment]:
        self.calls.append((text, voice_id, speed, "stream"))
        yield SpeechSynthesisSegment(b"RIFF", "audio/wav", 16_000, 100, "recording", "v1", 0)


def test_message_stream_and_nonstream_use_identical_final_speed(client: TestClient) -> None:
    _, chat, _ = create_chat(client)
    with managed_connection(get_settings().database_url) as connection:
        connection.execute(
            "UPDATE expression_plans SET rate = 0.94 WHERE assistant_message_id = ?",
            (chat["assistant_message_id"],),
        )
        connection.commit()
    recording = RecordingTTSService()
    client.app.dependency_overrides[get_tts_service] = lambda: recording
    try:
        nonstream = client.post(
            f"/api/messages/{chat['assistant_message_id']}/speech",
            json={"voice_id": "fake-default", "speed": 1.5},
        )
        stream = client.post(
            f"/api/messages/{chat['assistant_message_id']}/speech/stream",
            json={"voice_id": "fake-default", "speed": 1.5},
        )
    finally:
        client.app.dependency_overrides.pop(get_tts_service, None)

    assert nonstream.status_code == 200
    assert stream.status_code == 200
    assert recording.calls[0][:2] == recording.calls[1][:2]
    assert recording.calls[0][2] == pytest.approx(1.41)
    assert recording.calls[1][2] == pytest.approx(1.41)


def test_legacy_text_speech_route_remains_unchanged(client: TestClient) -> None:
    response = client.post("/api/audio/speech", json={"text": "legacy", "speed": 1.0})

    assert response.status_code == 200
    assert response.content.startswith(b"RIFF")
