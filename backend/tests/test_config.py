import pytest

from app.core.config import DEFAULT_DATABASE_URL, DEFAULT_MODEL, load_settings
from app.core.errors import sanitize_error_text


@pytest.fixture(autouse=True)
def clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "APP_NAME",
        "APP_ENV",
        "LOG_LEVEL",
        "DATABASE_URL",
        "LLM_PROVIDER",
        "LLM_MODEL",
        "LLM_TIMEOUT_SECONDS",
        "LLM_MAX_RETRIES",
        "RECENT_CONTEXT_MESSAGES",
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_THINKING_ENABLED",
        "DEEPSEEK_MAX_TOKENS",
        "DEEPSEEK_TIMEOUT_SECONDS",
        "DEEPSEEK_MAX_RETRIES",
        "TTS_PROVIDER",
        "TTS_FAKE_MODE",
        "TTS_MAX_TEXT_CHARS",
        "TTS_DEFAULT_VOICE",
        "TTS_DEFAULT_SPEED",
        "TTS_COSYVOICE_BASE_URL",
        "TTS_COSYVOICE_MODEL",
        "TTS_COSYVOICE_TIMEOUT_SECONDS",
        "ASR_PROVIDER",
        "ASR_MAX_UPLOAD_BYTES",
        "ASR_MAX_DURATION_MS",
        "ASR_MIN_DURATION_MS",
        "ASR_DEFAULT_LANGUAGE",
        "FAKE_ASR_MODE",
        "FAKE_ASR_TEXT",
        "FAKE_ASR_DETECTED_LANGUAGE",
        "ASR_FASTER_WHISPER_MODEL_PATH",
        "ASR_FASTER_WHISPER_MODEL_NAME",
        "ASR_FASTER_WHISPER_MODEL_REVISION",
        "ASR_FASTER_WHISPER_DEVICE",
        "ASR_FASTER_WHISPER_COMPUTE_TYPE",
        "ASR_FASTER_WHISPER_BEAM_SIZE",
        "ASR_FASTER_WHISPER_TIMEOUT_SECONDS",
        "ASR_FASTER_WHISPER_STREAMING_ENABLED",
        "ASR_FASTER_WHISPER_STREAMING_WINDOW_MS",
        "ASR_FASTER_WHISPER_STREAMING_STEP_MS",
        "ASR_FASTER_WHISPER_STREAMING_MIN_PARTIAL_CHARS",
        "ASR_FASTER_WHISPER_STREAMING_MAX_PARTIALS",
        "MEMORY_CONTEXT_ENABLED",
        "MEMORY_CONTEXT_LIMIT",
        "MEMORY_RETRIEVAL_MODE",
        "MEMORY_RETRIEVAL_FALLBACK_LIMIT",
        "MEMORY_CANDIDATES_ENABLED",
        "MEMORY_CANDIDATE_PROVIDER",
        "MEMORY_CANDIDATE_LLM_MAX_TOKENS",
        "MEMORY_CANDIDATE_LLM_TIMEOUT_SECONDS",
        "MEMORY_CANDIDATE_LLM_CONFIDENCE_THRESHOLD",
        "MEMORY_CANDIDATE_LLM_MAX_CANDIDATES",
        "MEMORY_EMBEDDING_ENABLED",
        "MEMORY_EMBEDDING_PROVIDER",
        "MEMORY_EMBEDDING_MODEL",
        "MEMORY_EMBEDDING_MIN_SCORE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_load_settings_defaults_to_fake_provider() -> None:
    settings = load_settings()

    assert settings.database_url == DEFAULT_DATABASE_URL
    assert settings.llm_provider == "fake"
    assert settings.llm_model == DEFAULT_MODEL
    assert settings.llm_timeout_seconds == 30.0
    assert settings.recent_context_messages == 12
    assert settings.anthropic_api_key is None


def test_memory_context_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_CONTEXT_ENABLED", "false")
    monkeypatch.setenv("MEMORY_CONTEXT_LIMIT", "5")

    settings = load_settings()

    assert settings.memory_context_enabled is False
    assert settings.memory_context_limit == 5


def test_memory_retrieval_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_RETRIEVAL_MODE", "recent")
    monkeypatch.setenv("MEMORY_RETRIEVAL_FALLBACK_LIMIT", "2")

    settings = load_settings()

    assert settings.memory_retrieval_mode == "recent"
    assert settings.memory_retrieval_fallback_limit == 2
    assert settings.redacted()["memory_retrieval_mode"] == "recent"
    assert settings.redacted()["memory_retrieval_fallback_limit"] == 2


def test_rejects_unknown_memory_retrieval_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_RETRIEVAL_MODE", "vector")

    with pytest.raises(ValueError, match="MEMORY_RETRIEVAL_MODE must be one of: embedding, relevance, recent"):
        load_settings()


def test_memory_retrieval_fallback_limit_must_not_exceed_context_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_CONTEXT_LIMIT", "2")
    monkeypatch.setenv("MEMORY_RETRIEVAL_FALLBACK_LIMIT", "3")

    with pytest.raises(ValueError, match="MEMORY_RETRIEVAL_FALLBACK_LIMIT must be less than or equal to MEMORY_CONTEXT_LIMIT"):
        load_settings()


def test_memory_embedding_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_RETRIEVAL_MODE", "embedding")
    monkeypatch.setenv("MEMORY_EMBEDDING_ENABLED", "true")
    monkeypatch.setenv("MEMORY_EMBEDDING_PROVIDER", "fake")
    monkeypatch.setenv("MEMORY_EMBEDDING_MODEL", "fake-memory-embedding-v1")
    monkeypatch.setenv("MEMORY_EMBEDDING_MIN_SCORE", "0.42")

    settings = load_settings()

    assert settings.memory_retrieval_mode == "embedding"
    assert settings.memory_embedding_enabled is True
    assert settings.memory_embedding_provider == "fake"
    assert settings.memory_embedding_model == "fake-memory-embedding-v1"
    assert settings.memory_embedding_min_score == 0.42
    assert settings.redacted()["memory_embedding_enabled"] is True
    assert settings.redacted()["memory_embedding_provider"] == "fake"
    assert settings.redacted()["memory_embedding_model"] == "fake-memory-embedding-v1"
    assert settings.redacted()["memory_embedding_min_score"] == 0.42


def test_rejects_unknown_memory_embedding_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_EMBEDDING_PROVIDER", "remote")

    with pytest.raises(ValueError, match="MEMORY_EMBEDDING_PROVIDER must be one of: fake, sentence-transformers"):
        load_settings()


def test_memory_embedding_min_score_must_be_between_zero_and_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_EMBEDDING_MIN_SCORE", "1.5")

    with pytest.raises(ValueError, match="MEMORY_EMBEDDING_MIN_SCORE must be between 0.0 and 1.0"):
        load_settings()


def test_memory_candidate_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_CANDIDATES_ENABLED", "false")
    monkeypatch.setenv("MEMORY_CANDIDATE_PROVIDER", "heuristic")

    settings = load_settings()

    assert settings.memory_candidates_enabled is False
    assert settings.memory_candidate_provider == "heuristic"


def test_memory_candidate_settings_accept_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_CANDIDATE_PROVIDER", "llm")
    monkeypatch.setenv("MEMORY_CANDIDATE_LLM_MAX_TOKENS", "384")
    monkeypatch.setenv("MEMORY_CANDIDATE_LLM_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("MEMORY_CANDIDATE_LLM_CONFIDENCE_THRESHOLD", "0.8")
    monkeypatch.setenv("MEMORY_CANDIDATE_LLM_MAX_CANDIDATES", "2")

    settings = load_settings()

    assert settings.memory_candidate_provider == "llm"
    assert settings.memory_candidate_llm_max_tokens == 384
    assert settings.memory_candidate_llm_timeout_seconds == 7.0
    assert settings.memory_candidate_llm_confidence_threshold == 0.8
    assert settings.memory_candidate_llm_max_candidates == 2
    assert settings.redacted()["memory_candidate_llm_max_tokens"] == 384
    assert settings.redacted()["memory_candidate_llm_timeout_seconds"] == 7.0
    assert settings.redacted()["memory_candidate_llm_confidence_threshold"] == 0.8
    assert settings.redacted()["memory_candidate_llm_max_candidates"] == 2


def test_rejects_unknown_memory_candidate_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_CANDIDATE_PROVIDER", "remote")

    with pytest.raises(ValueError, match="MEMORY_CANDIDATE_PROVIDER must be one of: heuristic, llm"):
        load_settings()


def test_anthropic_provider_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")

    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY is required"):
        load_settings()


def test_anthropic_provider_accepts_api_key_and_redacts_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-secret")

    settings = load_settings()

    assert settings.anthropic_api_key == "sk-test-secret"
    assert settings.redacted()["anthropic_api_key"] == "***"
    assert "sk-test-secret" not in str(settings.redacted())


def test_deepseek_provider_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")

    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY is required"):
        load_settings()


def test_deepseek_provider_accepts_defaults_and_redacts_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-secret")

    settings = load_settings()

    assert settings.llm_provider == "deepseek"
    assert settings.deepseek_api_key == "deepseek-test-secret"
    assert settings.deepseek_base_url == "https://api.deepseek.com"
    assert settings.llm_model == "deepseek-v4-flash"
    assert settings.deepseek_thinking_enabled is False
    assert settings.deepseek_max_tokens == 256
    assert settings.deepseek_timeout_seconds == 120.0
    assert settings.deepseek_max_retries == 0
    assert settings.redacted()["deepseek_api_key"] == "***"
    assert "deepseek-test-secret" not in str(settings.redacted())


def test_deepseek_settings_allow_safe_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-secret")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("LLM_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("DEEPSEEK_THINKING_ENABLED", "false")
    monkeypatch.setenv("DEEPSEEK_MAX_TOKENS", "128")
    monkeypatch.setenv("DEEPSEEK_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("DEEPSEEK_MAX_RETRIES", "0")

    settings = load_settings()

    assert settings.deepseek_base_url == "https://api.deepseek.com"
    assert settings.llm_model == "deepseek-v4-flash"
    assert settings.deepseek_thinking_enabled is False
    assert settings.deepseek_max_tokens == 128
    assert settings.deepseek_timeout_seconds == 60.0
    assert settings.deepseek_max_retries == 0


def test_deepseek_thinking_must_remain_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-secret")
    monkeypatch.setenv("DEEPSEEK_THINKING_ENABLED", "true")

    with pytest.raises(ValueError, match="DEEPSEEK_THINKING_ENABLED must be false"):
        load_settings()


def test_deepseek_max_tokens_cannot_exceed_stage_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-secret")
    monkeypatch.setenv("DEEPSEEK_MAX_TOKENS", "257")

    with pytest.raises(ValueError, match="DEEPSEEK_MAX_TOKENS must be less than or equal to 256"):
        load_settings()


def test_invalid_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "unknown")

    with pytest.raises(ValueError, match="LLM_PROVIDER must be one of"):
        load_settings()


def test_tts_defaults_to_fake_provider() -> None:
    settings = load_settings()

    assert settings.tts_provider == "fake"
    assert settings.tts_fake_mode == "ok"
    assert settings.tts_max_text_chars == 1000
    assert settings.tts_default_voice == "fake-default"
    assert settings.tts_default_speed == 1.0
    assert settings.tts_cosyvoice_base_url == "http://127.0.0.1:8001"
    assert settings.tts_cosyvoice_model == "Fun-CosyVoice3-0.5B-2512"
    assert settings.tts_cosyvoice_timeout_seconds == 30.0


def test_tts_settings_allow_safe_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TTS_PROVIDER", "fake")
    monkeypatch.setenv("TTS_FAKE_MODE", "empty")
    monkeypatch.setenv("TTS_MAX_TEXT_CHARS", "200")
    monkeypatch.setenv("TTS_DEFAULT_VOICE", "fake-default")
    monkeypatch.setenv("TTS_DEFAULT_SPEED", "1.25")
    monkeypatch.setenv("TTS_COSYVOICE_BASE_URL", "http://127.0.0.1:9001")
    monkeypatch.setenv("TTS_COSYVOICE_MODEL", "test-cosyvoice")
    monkeypatch.setenv("TTS_COSYVOICE_TIMEOUT_SECONDS", "12.5")

    settings = load_settings()

    assert settings.tts_provider == "fake"
    assert settings.tts_fake_mode == "empty"
    assert settings.tts_max_text_chars == 200
    assert settings.tts_default_voice == "fake-default"
    assert settings.tts_default_speed == 1.25
    assert settings.tts_cosyvoice_base_url == "http://127.0.0.1:9001"
    assert settings.tts_cosyvoice_model == "test-cosyvoice"
    assert settings.tts_cosyvoice_timeout_seconds == 12.5


def test_unknown_tts_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TTS_PROVIDER", "real")

    with pytest.raises(ValueError, match="TTS_PROVIDER must be one of"):
        load_settings()


def test_asr_defaults_to_fake_provider() -> None:
    settings = load_settings()

    assert settings.asr_provider == "fake"
    assert settings.asr_max_upload_bytes == 10 * 1024 * 1024
    assert settings.asr_max_duration_ms == 30_000
    assert settings.asr_min_duration_ms == 300
    assert settings.asr_default_language == "zh"
    assert settings.fake_asr_mode == "ok"
    assert settings.fake_asr_text == "这是 Fake ASR 测试转写。"
    assert settings.fake_asr_detected_language == "zh"


def test_asr_settings_allow_safe_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASR_PROVIDER", "fake")
    monkeypatch.setenv("ASR_MAX_UPLOAD_BYTES", "4096")
    monkeypatch.setenv("ASR_MAX_DURATION_MS", "5000")
    monkeypatch.setenv("ASR_MIN_DURATION_MS", "250")
    monkeypatch.setenv("ASR_DEFAULT_LANGUAGE", "en-US")
    monkeypatch.setenv("FAKE_ASR_MODE", "empty")
    monkeypatch.setenv("FAKE_ASR_TEXT", "测试覆盖文本")
    monkeypatch.setenv("FAKE_ASR_DETECTED_LANGUAGE", "en-US")

    settings = load_settings()

    assert settings.asr_provider == "fake"
    assert settings.asr_max_upload_bytes == 4096
    assert settings.asr_max_duration_ms == 5000
    assert settings.asr_min_duration_ms == 250
    assert settings.asr_default_language == "en-US"
    assert settings.fake_asr_mode == "empty"
    assert settings.fake_asr_text == "测试覆盖文本"
    assert settings.fake_asr_detected_language == "en-US"


def test_unknown_asr_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASR_PROVIDER", "real")

    with pytest.raises(ValueError, match="ASR_PROVIDER must be one of"):
        load_settings()


def test_asr_max_upload_bytes_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASR_MAX_UPLOAD_BYTES", "0")

    with pytest.raises(ValueError, match="ASR_MAX_UPLOAD_BYTES must be greater than 0"):
        load_settings()


def test_asr_max_upload_bytes_has_absolute_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASR_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024 + 1))

    with pytest.raises(ValueError, match="ASR_MAX_UPLOAD_BYTES must be less than or equal to"):
        load_settings()


def test_asr_duration_window_must_be_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASR_MAX_DURATION_MS", "100")
    monkeypatch.setenv("ASR_MIN_DURATION_MS", "300")

    with pytest.raises(ValueError, match="ASR_MIN_DURATION_MS must be less than or equal to ASR_MAX_DURATION_MS"):
        load_settings()


def test_fake_asr_text_must_not_be_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_ASR_TEXT", "   ")

    with pytest.raises(ValueError, match="FAKE_ASR_TEXT must not be empty"):
        load_settings()


def test_asr_redacted_settings_do_not_include_fake_transcript_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_ASR_TEXT", "本地测试转写文本")

    settings = load_settings()

    assert settings.redacted()["fake_asr_text"] == "***"
    assert "本地测试转写文本" not in str(settings.redacted())

def test_numeric_settings_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "0")

    with pytest.raises(ValueError, match="LLM_TIMEOUT_SECONDS must be greater than 0"):
        load_settings()


def test_sanitize_error_text_removes_secret_values() -> None:
    text = "request failed with token sk-test-secret in provider output"

    sanitized = sanitize_error_text(text, ["sk-test-secret"])

    assert sanitized == "request failed with token *** in provider output"


def test_faster_whisper_asr_provider_requires_model_path(monkeypatch):
    monkeypatch.setenv("ASR_PROVIDER", "faster-whisper")
    monkeypatch.delenv("ASR_FASTER_WHISPER_MODEL_PATH", raising=False)

    with pytest.raises(ValueError, match="ASR_FASTER_WHISPER_MODEL_PATH is required"):
        load_settings()


def test_faster_whisper_asr_settings_allow_safe_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("ASR_PROVIDER", "faster-whisper")
    monkeypatch.setenv("ASR_FASTER_WHISPER_MODEL_PATH", str(tmp_path))
    monkeypatch.setenv("ASR_FASTER_WHISPER_MODEL_NAME", "medium")
    monkeypatch.setenv("ASR_FASTER_WHISPER_MODEL_REVISION", "08e178d48790749d25932bbc082711ddcfdfbc4f")
    monkeypatch.setenv("ASR_FASTER_WHISPER_DEVICE", "cuda")
    monkeypatch.setenv("ASR_FASTER_WHISPER_COMPUTE_TYPE", "float16")
    monkeypatch.setenv("ASR_FASTER_WHISPER_BEAM_SIZE", "1")
    monkeypatch.setenv("ASR_FASTER_WHISPER_TIMEOUT_SECONDS", "45")

    settings = load_settings()

    assert settings.asr_provider == "faster-whisper"
    assert settings.asr_faster_whisper_model_path == str(tmp_path)
    assert settings.asr_faster_whisper_model_name == "medium"
    assert settings.asr_faster_whisper_model_revision == "08e178d48790749d25932bbc082711ddcfdfbc4f"
    assert settings.asr_faster_whisper_device == "cuda"
    assert settings.asr_faster_whisper_compute_type == "float16"
    assert settings.asr_faster_whisper_beam_size == 1
    assert settings.asr_faster_whisper_timeout_seconds == 45




def test_faster_whisper_streaming_settings_default_disabled() -> None:
    settings = load_settings()

    assert settings.asr_faster_whisper_streaming_enabled is False
    assert settings.asr_faster_whisper_streaming_window_ms == 3000
    assert settings.asr_faster_whisper_streaming_step_ms == 1000
    assert settings.asr_faster_whisper_streaming_min_partial_chars == 1
    assert settings.asr_faster_whisper_streaming_max_partials == 8


def test_faster_whisper_streaming_settings_parse_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASR_FASTER_WHISPER_STREAMING_ENABLED", "true")
    monkeypatch.setenv("ASR_FASTER_WHISPER_STREAMING_WINDOW_MS", "2500")
    monkeypatch.setenv("ASR_FASTER_WHISPER_STREAMING_STEP_MS", "500")
    monkeypatch.setenv("ASR_FASTER_WHISPER_STREAMING_MIN_PARTIAL_CHARS", "2")
    monkeypatch.setenv("ASR_FASTER_WHISPER_STREAMING_MAX_PARTIALS", "3")

    settings = load_settings()

    assert settings.asr_faster_whisper_streaming_enabled is True
    assert settings.asr_faster_whisper_streaming_window_ms == 2500
    assert settings.asr_faster_whisper_streaming_step_ms == 500
    assert settings.asr_faster_whisper_streaming_min_partial_chars == 2
    assert settings.asr_faster_whisper_streaming_max_partials == 3


def test_faster_whisper_streaming_window_must_be_at_least_step(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASR_FASTER_WHISPER_STREAMING_WINDOW_MS", "500")
    monkeypatch.setenv("ASR_FASTER_WHISPER_STREAMING_STEP_MS", "1000")

    with pytest.raises(ValueError, match="ASR_FASTER_WHISPER_STREAMING_WINDOW_MS must be greater than or equal to ASR_FASTER_WHISPER_STREAMING_STEP_MS"):
        load_settings()


def test_faster_whisper_asr_settings_reject_invalid_device(monkeypatch, tmp_path):
    monkeypatch.setenv("ASR_PROVIDER", "faster-whisper")
    monkeypatch.setenv("ASR_FASTER_WHISPER_MODEL_PATH", str(tmp_path))
    monkeypatch.setenv("ASR_FASTER_WHISPER_DEVICE", "tpu")

    with pytest.raises(ValueError, match="ASR_FASTER_WHISPER_DEVICE"):
        load_settings()


def test_faster_whisper_asr_redacted_settings_include_no_audio_or_text(monkeypatch, tmp_path):
    monkeypatch.setenv("ASR_PROVIDER", "faster-whisper")
    monkeypatch.setenv("ASR_FASTER_WHISPER_MODEL_PATH", str(tmp_path))

    redacted = load_settings().redacted()

    assert redacted["asr_provider"] == "faster-whisper"
    assert redacted["asr_faster_whisper_model_path"] == str(tmp_path)
    assert redacted["fake_asr_text"] == "***"
