from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import get_settings

MINIMAL_WEBM_SIGNATURE_FIXTURE = b"\x1a\x45\xdf\xa3" + b"x" * 200
MINIMAL_MP4_SIGNATURE_FIXTURE = b"\x00\x00\x00\x18ftypmp42" + b"x" * 200
MINIMAL_WAV_SIGNATURE_FIXTURE = b"RIFF" + b"\x24\x00\x00\x00WAVEfmt " + b"x" * 200


# ── success ──────────────────────────────────────────────────────────────────

def test_transcriptions_webm_signature_succeeds(client: TestClient) -> None:
    response = client.post(
        "/api/audio/transcriptions",
        files={"file": ("test.webm", MINIMAL_WEBM_SIGNATURE_FIXTURE, "audio/webm")},
        data={"language": "zh"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "这是 Fake ASR 测试转写。"
    assert body["detected_language"] == "zh"
    assert body["duration_ms"] is None
    assert body["provider"] == "fake"
    assert body["model"] == "fake-asr-v1"
    assert body["inference_ms"] == 0


def test_transcriptions_mp4_signature_succeeds(client: TestClient) -> None:
    response = client.post(
        "/api/audio/transcriptions",
        files={"file": ("test.mp4", MINIMAL_MP4_SIGNATURE_FIXTURE, "audio/mp4")},
        data={"language": "zh"},
    )

    assert response.status_code == 200
    assert response.json()["text"] == "这是 Fake ASR 测试转写。"


def test_transcriptions_wav_signature_succeeds(client: TestClient) -> None:
    response = client.post(
        "/api/audio/transcriptions",
        files={"file": ("test.wav", MINIMAL_WAV_SIGNATURE_FIXTURE, "audio/wav")},
        data={"language": "zh"},
    )

    assert response.status_code == 200
    assert response.json()["text"] == "这是 Fake ASR 测试转写。"


def test_transcriptions_duration_ms_is_null(client: TestClient) -> None:
    response = client.post(
        "/api/audio/transcriptions",
        files={"file": ("test.webm", MINIMAL_WEBM_SIGNATURE_FIXTURE, "audio/webm")},
        data={"language": "zh"},
    )

    assert response.status_code == 200
    assert response.json()["duration_ms"] is None


def test_transcriptions_language_form_field_is_respected(client: TestClient) -> None:
    response = client.post(
        "/api/audio/transcriptions",
        files={"file": ("test.webm", MINIMAL_WEBM_SIGNATURE_FIXTURE, "audio/webm")},
        data={"language": "en-US"},
    )

    assert response.status_code == 200
    assert response.json()["detected_language"] == "en-US"


def test_transcriptions_media_type_codecs_parameter_is_normalized(client: TestClient) -> None:
    response = client.post(
        "/api/audio/transcriptions",
        files={"file": ("test.webm", MINIMAL_WEBM_SIGNATURE_FIXTURE, "audio/webm;codecs=opus")},
        data={"language": "zh"},
    )

    assert response.status_code == 200
    assert response.json()["text"] == "这是 Fake ASR 测试转写。"


# ── missing file ─────────────────────────────────────────────────────────────

def test_transcriptions_missing_file_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/audio/transcriptions",
        data={"language": "zh"},
    )

    assert response.status_code == 422
    assert "Traceback" not in response.text


# ── empty / zero-byte ────────────────────────────────────────────────────────

def test_transcriptions_empty_file_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/audio/transcriptions",
        files={"file": ("empty.webm", b"", "audio/webm")},
        data={"language": "zh"},
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "asr_file_missing"
    assert "Traceback" not in response.text


# ── oversized ────────────────────────────────────────────────────────────────

def test_transcriptions_oversized_file_rejected_via_size_field(client: TestClient) -> None:
    big = b"\x1a\x45\xdf\xa3" + b"x" * (10 * 1024 * 1024)

    response = client.post(
        "/api/audio/transcriptions",
        files={"file": ("big.webm", big, "audio/webm")},
        data={"language": "zh"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "asr_file_too_large"


def test_transcriptions_max_plus_one_guard(client: TestClient) -> None:
    over_max = b"\x00\x00\x00\x18ftypmp42" + b"x" * (10 * 1024 * 1024)

    response = client.post(
        "/api/audio/transcriptions",
        files={"file": ("over.mp4", over_max, "audio/mp4")},
        data={"language": "zh"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "asr_file_too_large"


# ── unsupported media type ───────────────────────────────────────────────────

def test_transcriptions_unsupported_media_type_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/audio/transcriptions",
        files={"file": ("test.ogg", b"OggSxxxx", "audio/ogg")},
        data={"language": "zh"},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "asr_unsupported_media_type"


# ── missing content_type ─────────────────────────────────────────────────────

def test_transcriptions_missing_content_type_rejected(client: TestClient) -> None:
    class NoContentTypeFile:
        content_type = ""
        size = len(MINIMAL_WEBM_SIGNATURE_FIXTURE)

        async def read(self, _n: int = -1) -> bytes:
            return MINIMAL_WEBM_SIGNATURE_FIXTURE

        async def close(self) -> None:
            pass

    response = client.post(
        "/api/audio/transcriptions",
        files=[("file", ("test.bin", MINIMAL_WEBM_SIGNATURE_FIXTURE, ""))],
        data={"language": "zh"},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "asr_unsupported_media_type"


# ── MIME / signature mismatch ────────────────────────────────────────────────

def test_transcriptions_webm_mime_with_non_webm_content_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/audio/transcriptions",
        files={"file": ("test.webm", b"not-a-webm-file", "audio/webm")},
        data={"language": "zh"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "asr_invalid_audio"


# ── invalid language ─────────────────────────────────────────────────────────

def test_transcriptions_invalid_language_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/audio/transcriptions",
        files={"file": ("test.webm", MINIMAL_WEBM_SIGNATURE_FIXTURE, "audio/webm")},
        data={"language": "中文"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "asr_invalid_request"


# ── fake provider error modes ───────────────────────────────────────────────

def _make_asr_mode_client(tmp_path: Path, monkeypatch, mode: str) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / f'asr_{mode}.db'}")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("ASR_PROVIDER", "fake")
    monkeypatch.setenv("FAKE_ASR_MODE", mode)
    monkeypatch.setenv("APP_ENV", "test")
    get_settings.cache_clear()
    return TestClient(__import__("app.main", fromlist=["create_app"]).create_app())


def test_transcriptions_maps_timeout_mode(tmp_path: Path, monkeypatch) -> None:
    client = _make_asr_mode_client(tmp_path, monkeypatch, "timeout")

    try:
        response = client.post(
            "/api/audio/transcriptions",
            files={"file": ("test.wav", MINIMAL_WAV_SIGNATURE_FIXTURE, "audio/wav")},
            data={"language": "zh"},
        )

        assert response.status_code == 504
        assert response.json()["error"]["code"] == "asr_timeout"
        assert "Traceback" not in response.text
    finally:
        get_settings.cache_clear()


def test_transcriptions_maps_error_mode(tmp_path: Path, monkeypatch) -> None:
    client = _make_asr_mode_client(tmp_path, monkeypatch, "error")

    try:
        response = client.post(
            "/api/audio/transcriptions",
            files={"file": ("test.wav", MINIMAL_WAV_SIGNATURE_FIXTURE, "audio/wav")},
            data={"language": "zh"},
        )

        assert response.status_code == 502
        assert response.json()["error"]["code"] == "asr_unavailable"
        assert "Traceback" not in response.text
    finally:
        get_settings.cache_clear()


def test_transcriptions_maps_empty_mode(tmp_path: Path, monkeypatch) -> None:
    client = _make_asr_mode_client(tmp_path, monkeypatch, "empty")

    try:
        response = client.post(
            "/api/audio/transcriptions",
            files={"file": ("test.wav", MINIMAL_WAV_SIGNATURE_FIXTURE, "audio/wav")},
            data={"language": "zh"},
        )

        assert response.status_code == 502
        assert response.json()["error"]["code"] == "asr_invalid_response"
        assert "Traceback" not in response.text
    finally:
        get_settings.cache_clear()


# ── no chat side effects ─────────────────────────────────────────────────────

def test_transcriptions_does_not_create_sessions_or_messages(client: TestClient) -> None:
    before = client.get("/api/sessions")
    assert before.status_code == 200
    assert before.json() == []

    response = client.post(
        "/api/audio/transcriptions",
        files={"file": ("test.webm", MINIMAL_WEBM_SIGNATURE_FIXTURE, "audio/webm")},
        data={"language": "zh"},
    )

    assert response.status_code == 200
    after = client.get("/api/sessions")
    assert after.status_code == 200
    assert after.json() == []


# ── /api/audio/speech regression ─────────────────────────────────────────────

def test_speech_api_still_works_alongside_transcriptions(client: TestClient) -> None:
    speech_resp = client.post("/api/audio/speech", json={"text": "共存测试", "voice_id": "fake-default", "speed": 1.0})
    assert speech_resp.status_code == 200
    assert speech_resp.headers["content-type"].startswith("audio/wav")
    assert speech_resp.headers["x-tts-provider"] == "fake"
    assert speech_resp.content.startswith(b"RIFF")

    asr_resp = client.post(
        "/api/audio/transcriptions",
        files={"file": ("test.webm", MINIMAL_WEBM_SIGNATURE_FIXTURE, "audio/webm")},
        data={"language": "zh"},
    )
    assert asr_resp.status_code == 200
    assert asr_resp.json()["text"] == "这是 Fake ASR 测试转写。"


# ── network isolation ────────────────────────────────────────────────────────

def test_transcriptions_does_not_access_network(tmp_path: Path, monkeypatch) -> None:
    import httpx

    def forbidden_client(*args, **kwargs):
        raise AssertionError("2B-2 transcriptions route must not access network")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden_client)

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'netcheck.db'}")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("ASR_PROVIDER", "fake")

    from app.main import create_app
    from app.core.config import get_settings
    from fastapi.testclient import TestClient as TC

    get_settings.cache_clear()
    try:
        app = create_app()
        with TC(app) as c:
            response = c.post(
                "/api/audio/transcriptions",
                files={"file": ("test.webm", MINIMAL_WEBM_SIGNATURE_FIXTURE, "audio/webm")},
                data={"language": "zh"},
            )
            assert response.status_code == 200
            assert response.json()["text"] == "这是 Fake ASR 测试转写。"
    finally:
        get_settings.cache_clear()


# ── no persistent audio files ────────────────────────────────────────────────

def test_transcriptions_does_not_create_persistent_audio_files(tmp_path: Path, client: TestClient) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)

    before_files = set(str(p) for p in data_dir.rglob("*") if p.is_file())

    response = client.post(
        "/api/audio/transcriptions",
        files={"file": ("test.wav", MINIMAL_WAV_SIGNATURE_FIXTURE, "audio/wav")},
        data={"language": "zh"},
    )

    assert response.status_code == 200
    after_files = set(str(p) for p in data_dir.rglob("*") if p.is_file())
    assert after_files == before_files
