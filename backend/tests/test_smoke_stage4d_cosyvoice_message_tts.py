from __future__ import annotations

import base64
import io
import json
import wave
from pathlib import Path

import httpx
import pytest

from scripts.smoke_stage4d_cosyvoice_message_tts import BLOCKED_EXIT_CODE, main


def wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(b"\x00\x00")
    return buffer.getvalue()


def valid_events() -> list[dict[str, object]]:
    audio = base64.b64encode(wav_bytes()).decode("ascii")
    return [
        {"type": "start", "provider": "cosyvoice-http", "model": "model"},
        {
            "type": "segment",
            "index": 0,
            "audio_base64": audio,
            "media_type": "audio/wav",
            "duration_ms": 10,
            "sample_rate": 16_000,
        },
        {"type": "done", "segment_count": 1},
    ]


def response_for_events(events: list[dict[str, object]]) -> httpx.Response:
    body = "\n".join([*(json.dumps(event) for event in events), ""])
    return httpx.Response(200, text=body, headers={"content-type": "application/x-ndjson"})


def run_with_handler(monkeypatch: pytest.MonkeyPatch, handler, *, args: list[str] | None = None) -> int:
    monkeypatch.setenv("STAGE4D_REAL_COSYVOICE", "1")
    return main(
        args or ["--backend-url", "http://test"],
        client_factory=lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handler), **kwargs),
    )


def protocol_handler(
    *,
    speech_content: bytes | None = None,
    speech_content_type: str = "audio/wav",
    stream_events: list[dict[str, object]] | None = None,
    delete_status: int = 204,
):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/api/sessions" and request.method == "POST":
            return httpx.Response(201, json={"id": "session-1"})
        if request.url.path == "/api/sessions/session-1/messages":
            return httpx.Response(200, json={
                "reply": "private reply must not be printed",
                "metadata": {"provider": "private-provider-body", "model": "private-model"},
                "assistant_message_id": "assistant-1",
            })
        if request.url.path == "/api/messages/assistant-1/speech":
            return httpx.Response(
                200,
                content=wav_bytes() if speech_content is None else speech_content,
                headers={"content-type": speech_content_type},
            )
        if request.url.path == "/api/messages/assistant-1/speech/stream":
            return response_for_events(valid_events() if stream_events is None else stream_events)
        if request.url.path == "/api/sessions/session-1" and request.method == "DELETE":
            return httpx.Response(delete_status)
        return httpx.Response(404)

    return handler


def test_smoke_refuses_real_provider_without_explicit_opt_in(monkeypatch, capsys) -> None:
    monkeypatch.delenv("STAGE4D_REAL_COSYVOICE", raising=False)
    assert main(["--backend-url", "http://127.0.0.1:18003"]) == BLOCKED_EXIT_CODE
    assert "BLOCKED: set STAGE4D_REAL_COSYVOICE=1" in capsys.readouterr().out


def test_smoke_exercises_message_bound_protocol_without_writing_audio(monkeypatch, capsys) -> None:
    requests: list[tuple[str, str, object | None]] = []
    base_handler = protocol_handler()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
        return base_handler(request)

    monkeypatch.setattr(Path, "write_bytes", lambda *_args, **_kwargs: pytest.fail("audio must not be written"))
    result = run_with_handler(
        monkeypatch,
        handler,
        args=["--backend-url", "http://test", "--voice-id", "voice-1", "--speed", "1.04"],
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "PASS" in output
    assert "private reply" not in output
    assert "private-provider-body" not in output
    assert requests == [
        ("GET", "/health", None),
        ("POST", "/api/sessions", {"title": "Stage 4D CosyVoice protocol smoke"}),
        ("POST", "/api/sessions/session-1/messages", {"content": "请简短回复这条无敏感信息的协议测试消息。"}),
        ("POST", "/api/messages/assistant-1/speech", {"voice_id": "voice-1", "speed": 1.04}),
        ("POST", "/api/messages/assistant-1/speech/stream", {"voice_id": "voice-1", "speed": 1.04}),
        ("DELETE", "/api/sessions/session-1", None),
    ]


@pytest.mark.parametrize(
    ("content", "content_type"),
    [(wav_bytes(), "text/plain"), (b"RIFF1234NOPE", "audio/wav"), (b"RIFFWAVE", "audio/wav")],
)
def test_smoke_rejects_invalid_nonstream_wav(monkeypatch, content, content_type) -> None:
    assert run_with_handler(
        monkeypatch,
        protocol_handler(speech_content=content, speech_content_type=content_type),
    ) == 1


@pytest.mark.parametrize(
    "events",
    [
        [valid_events()[0], valid_events()[2]],
        [*valid_events(), valid_events()[1]],
        [valid_events()[0], *valid_events()],
        [valid_events()[0], valid_events()[1], {"type": "done", "segment_count": 2}],
        [valid_events()[0], {"type": "unknown"}, valid_events()[2]],
        [valid_events()[0], {**valid_events()[1], "index": 1}, valid_events()[2]],
        [valid_events()[0], {**valid_events()[1], "index": False}, valid_events()[2]],
        [valid_events()[0], {**valid_events()[1], "index": True}, valid_events()[2]],
        [valid_events()[0], {**valid_events()[1], "media_type": "text/plain"}, valid_events()[2]],
        [valid_events()[0], {**valid_events()[1], "duration_ms": 0}, valid_events()[2]],
        [valid_events()[0], {**valid_events()[1], "sample_rate": -1}, valid_events()[2]],
        [valid_events()[0], {**valid_events()[1], "duration_ms": 1.5}, valid_events()[2]],
        [valid_events()[0], {**valid_events()[1], "audio_base64": "%%%"}, valid_events()[2]],
        [valid_events()[0], {**valid_events()[1], "audio_base64": base64.b64encode(b"RIFF1234NOPE").decode()}, valid_events()[2]],
        [valid_events()[1], valid_events()[0], valid_events()[2]],
        [valid_events()[0], valid_events()[1]],
    ],
)
def test_smoke_rejects_invalid_stream_protocol(monkeypatch, events) -> None:
    assert run_with_handler(monkeypatch, protocol_handler(stream_events=events)) == 1


def test_smoke_success_with_cleanup_failure_is_not_pass(monkeypatch, capsys) -> None:
    result = run_with_handler(monkeypatch, protocol_handler(delete_status=500))
    output = capsys.readouterr().out
    assert result == 1
    assert "PASS" not in output
    assert "cleanup_failed=true" in output


def test_smoke_primary_failure_wins_over_cleanup_failure(monkeypatch, capsys) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200)
        if request.url.path == "/api/sessions" and request.method == "POST":
            return httpx.Response(201, json={"id": "session-1"})
        if request.url.path == "/api/sessions/session-1/messages":
            return httpx.Response(500, text="upstream secret response")
        if request.method == "DELETE":
            return httpx.Response(500, text="cleanup secret response")
        return httpx.Response(404)

    result = run_with_handler(monkeypatch, handler)
    output = capsys.readouterr().out
    assert result == 1
    assert "cleanup_failed=true" in output
    assert "RuntimeError" in output
    assert "upstream secret" not in output
    assert "cleanup secret" not in output
