from __future__ import annotations

import argparse
import base64
import json
import math
import os
from collections.abc import Callable, Mapping, Sequence

import httpx

BLOCKED_EXIT_CODE = 2


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an opt-in Stage 4D CosyVoice protocol smoke.")
    parser.add_argument("--backend-url", default="http://127.0.0.1:18003")
    parser.add_argument("--voice-id", default="default-zh-female")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser.parse_args(argv)


def _require_success(response: httpx.Response, step: str) -> None:
    if not response.is_success:
        raise RuntimeError(f"{step} failed")


def _is_wav(value: bytes) -> bool:
    return len(value) >= 12 and value[:4] == b"RIFF" and value[8:12] == b"WAVE"


def _validate_nonstream_wav(response: httpx.Response) -> None:
    content_type = response.headers.get("content-type", "").lower()
    if not content_type.startswith("audio/wav") or not _is_wav(response.content):
        raise RuntimeError("message speech did not return valid WAV")


def _positive_finite_integer(value: object) -> bool:
    return type(value) is int and value > 0 and math.isfinite(value)


def _validate_stream(response: httpx.Response) -> int:
    try:
        events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("message speech stream has invalid NDJSON") from exc
    if len(events) < 3 or events[0].get("type") != "start":
        raise RuntimeError("message speech stream must start once")
    if sum(event.get("type") == "start" for event in events) != 1:
        raise RuntimeError("message speech stream must start once")
    if events[-1].get("type") != "done":
        raise RuntimeError("message speech stream must end with done")

    segments = events[1:-1]
    if not segments or any(event.get("type") != "segment" for event in segments):
        raise RuntimeError("message speech stream has invalid event ordering")
    for expected_index, segment in enumerate(segments):
        index = segment.get("index")
        if type(index) is not int or index != expected_index:
            raise RuntimeError("message speech stream indexes are not contiguous")
        if segment.get("media_type") != "audio/wav":
            raise RuntimeError("message speech stream segment is not WAV")
        if not _positive_finite_integer(segment.get("duration_ms")):
            raise RuntimeError("message speech stream duration is invalid")
        if not _positive_finite_integer(segment.get("sample_rate")):
            raise RuntimeError("message speech stream sample rate is invalid")
        raw = segment.get("audio_base64")
        try:
            decoded = base64.b64decode(raw, validate=True) if isinstance(raw, str) else b""
        except (ValueError, base64.binascii.Error) as exc:
            raise RuntimeError("message speech stream base64 is invalid") from exc
        if not _is_wav(decoded):
            raise RuntimeError("message speech stream segment bytes are not WAV")

    count = events[-1].get("segment_count")
    if type(count) is not int or count != len(segments):
        raise RuntimeError("message speech stream segment count is invalid")
    return len(segments)


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    client_factory: Callable[..., httpx.Client] = httpx.Client,
) -> int:
    args = _parse_args(argv)
    source_environment = os.environ if environ is None else environ
    if source_environment.get("STAGE4D_REAL_COSYVOICE") != "1":
        print("BLOCKED: set STAGE4D_REAL_COSYVOICE=1 to run the real CosyVoice smoke")
        return BLOCKED_EXIT_CODE

    session_id: str | None = None
    primary_error: Exception | None = None
    cleanup_error: Exception | None = None
    wav_size = 0
    segment_count = 0
    try:
        with client_factory(base_url=args.backend_url.rstrip("/"), timeout=args.timeout) as client:
            _require_success(client.get("/health"), "health")
            session = client.post("/api/sessions", json={"title": "Stage 4D CosyVoice protocol smoke"})
            _require_success(session, "session creation")
            session_id = str(session.json()["id"])
            chat = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"content": "请简短回复这条无敏感信息的协议测试消息。"},
            )
            _require_success(chat, "chat")
            assistant_message_id = chat.json().get("assistant_message_id")
            if not isinstance(assistant_message_id, str) or not assistant_message_id:
                raise RuntimeError("chat response has no assistant message id")
            speech_body = {"voice_id": args.voice_id, "speed": args.speed}
            speech = client.post(f"/api/messages/{assistant_message_id}/speech", json=speech_body)
            _require_success(speech, "message speech")
            _validate_nonstream_wav(speech)
            wav_size = len(speech.content)
            stream = client.post(
                f"/api/messages/{assistant_message_id}/speech/stream",
                json=speech_body,
            )
            _require_success(stream, "message speech stream")
            segment_count = _validate_stream(stream)
    except Exception as exc:
        primary_error = exc

    if session_id is not None:
        try:
            with client_factory(base_url=args.backend_url.rstrip("/"), timeout=args.timeout) as cleanup_client:
                cleanup = cleanup_client.delete(f"/api/sessions/{session_id}")
                _require_success(cleanup, "session cleanup")
        except Exception as exc:
            cleanup_error = exc

    if primary_error is not None:
        print(
            "BLOCKED: Stage 4D CosyVoice protocol smoke failed "
            f"({type(primary_error).__name__}) cleanup_failed={str(cleanup_error is not None).lower()}"
        )
        return 1
    if cleanup_error is not None:
        print("BLOCKED: Stage 4D CosyVoice protocol smoke failed (cleanup) cleanup_failed=true")
        return 1

    print(
        "PASS: Stage 4D CosyVoice message protocol "
        f"assistant_id_present=true wav_bytes={wav_size} stream_segments={segment_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
