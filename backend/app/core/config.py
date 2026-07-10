import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


DEFAULT_DATABASE_URL = "sqlite:///./data/app.db"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_ASR_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ABSOLUTE_ASR_MAX_UPLOAD_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True)
class Settings:
    app_name: str = "AI Desktop Companion"
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = DEFAULT_DATABASE_URL
    llm_provider: str = "fake"
    llm_model: str = DEFAULT_MODEL
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2
    recent_context_messages: int = 12
    fake_provider_mode: str = "ok"
    anthropic_api_key: str | None = None
    deepseek_api_key: str | None = None
    deepseek_base_url: str = DEFAULT_DEEPSEEK_BASE_URL
    deepseek_thinking_enabled: bool = False
    deepseek_max_tokens: int = 256
    deepseek_timeout_seconds: float = 120.0
    deepseek_max_retries: int = 0
    tts_provider: str = "fake"
    tts_fake_mode: str = "ok"
    tts_max_text_chars: int = 1000
    tts_default_voice: str = "fake-default"
    tts_default_speed: float = 1.0
    tts_cosyvoice_base_url: str = "http://127.0.0.1:8001"
    tts_cosyvoice_model: str = "Fun-CosyVoice3-0.5B-2512"
    tts_cosyvoice_timeout_seconds: float = 30.0
    asr_provider: str = "fake"
    asr_max_upload_bytes: int = DEFAULT_ASR_MAX_UPLOAD_BYTES
    asr_max_duration_ms: int = 30_000
    asr_min_duration_ms: int = 300
    asr_default_language: str = "zh"
    fake_asr_mode: str = "ok"
    fake_asr_text: str = "这是 Fake ASR 测试转写。"
    fake_asr_detected_language: str | None = "zh"
    asr_faster_whisper_model_path: str = ""
    asr_faster_whisper_model_name: str = "medium"
    asr_faster_whisper_model_revision: str = "08e178d48790749d25932bbc082711ddcfdfbc4f"
    asr_faster_whisper_device: str = "cuda"
    asr_faster_whisper_compute_type: str = "float16"
    asr_faster_whisper_beam_size: int = 1
    asr_faster_whisper_timeout_seconds: float = 30.0
    asr_faster_whisper_streaming_enabled: bool = False
    asr_faster_whisper_streaming_window_ms: int = 3000
    asr_faster_whisper_streaming_step_ms: int = 1000
    asr_faster_whisper_streaming_min_partial_chars: int = 1
    asr_faster_whisper_streaming_max_partials: int = 8
    memory_context_enabled: bool = True
    memory_context_limit: int = 8
    memory_retrieval_mode: str = "relevance"
    memory_retrieval_fallback_limit: int = 3
    memory_candidates_enabled: bool = True
    memory_candidate_provider: str = "heuristic"
    memory_candidate_llm_max_tokens: int = 512
    memory_candidate_llm_timeout_seconds: float = 15.0
    memory_candidate_llm_confidence_threshold: float = 0.75
    memory_candidate_llm_max_candidates: int = 3
    memory_embedding_enabled: bool = False
    memory_embedding_provider: str = "fake"
    memory_embedding_model: str = "fake-memory-embedding-v1"
    memory_embedding_min_score: float = 0.35

    @property
    def sqlite_path(self) -> Path:
        if not self.database_url.startswith("sqlite:///"):
            raise ValueError("Only sqlite:/// database URLs are supported in stage 1")
        raw_path = self.database_url.removeprefix("sqlite:///")
        return Path(raw_path)

    def redacted(self) -> dict[str, object]:
        return {
            "app_name": self.app_name,
            "app_env": self.app_env,
            "log_level": self.log_level,
            "database_url": self.database_url,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "llm_timeout_seconds": self.llm_timeout_seconds,
            "llm_max_retries": self.llm_max_retries,
            "recent_context_messages": self.recent_context_messages,
            "fake_provider_mode": self.fake_provider_mode,
            "anthropic_api_key": "***" if self.anthropic_api_key else None,
            "deepseek_api_key": "***" if self.deepseek_api_key else None,
            "deepseek_base_url": self.deepseek_base_url,
            "deepseek_thinking_enabled": self.deepseek_thinking_enabled,
            "deepseek_max_tokens": self.deepseek_max_tokens,
            "deepseek_timeout_seconds": self.deepseek_timeout_seconds,
            "deepseek_max_retries": self.deepseek_max_retries,
            "tts_provider": self.tts_provider,
            "tts_fake_mode": self.tts_fake_mode,
            "tts_max_text_chars": self.tts_max_text_chars,
            "tts_default_voice": self.tts_default_voice,
            "tts_default_speed": self.tts_default_speed,
            "tts_cosyvoice_base_url": self.tts_cosyvoice_base_url,
            "tts_cosyvoice_model": self.tts_cosyvoice_model,
            "tts_cosyvoice_timeout_seconds": self.tts_cosyvoice_timeout_seconds,
            "asr_provider": self.asr_provider,
            "asr_max_upload_bytes": self.asr_max_upload_bytes,
            "asr_max_duration_ms": self.asr_max_duration_ms,
            "asr_min_duration_ms": self.asr_min_duration_ms,
            "asr_default_language": self.asr_default_language,
            "fake_asr_mode": self.fake_asr_mode,
            "fake_asr_text": "***" if self.fake_asr_text else "",
            "fake_asr_detected_language": self.fake_asr_detected_language,
            "asr_faster_whisper_model_path": self.asr_faster_whisper_model_path,
            "asr_faster_whisper_model_name": self.asr_faster_whisper_model_name,
            "asr_faster_whisper_model_revision": self.asr_faster_whisper_model_revision,
            "asr_faster_whisper_device": self.asr_faster_whisper_device,
            "asr_faster_whisper_compute_type": self.asr_faster_whisper_compute_type,
            "asr_faster_whisper_beam_size": self.asr_faster_whisper_beam_size,
            "asr_faster_whisper_timeout_seconds": self.asr_faster_whisper_timeout_seconds,
            "asr_faster_whisper_streaming_enabled": self.asr_faster_whisper_streaming_enabled,
            "asr_faster_whisper_streaming_window_ms": self.asr_faster_whisper_streaming_window_ms,
            "asr_faster_whisper_streaming_step_ms": self.asr_faster_whisper_streaming_step_ms,
            "asr_faster_whisper_streaming_min_partial_chars": self.asr_faster_whisper_streaming_min_partial_chars,
            "asr_faster_whisper_streaming_max_partials": self.asr_faster_whisper_streaming_max_partials,
            "memory_context_enabled": self.memory_context_enabled,
            "memory_context_limit": self.memory_context_limit,
            "memory_retrieval_mode": self.memory_retrieval_mode,
            "memory_retrieval_fallback_limit": self.memory_retrieval_fallback_limit,
            "memory_candidates_enabled": self.memory_candidates_enabled,
            "memory_candidate_provider": self.memory_candidate_provider,
            "memory_candidate_llm_max_tokens": self.memory_candidate_llm_max_tokens,
            "memory_candidate_llm_timeout_seconds": self.memory_candidate_llm_timeout_seconds,
            "memory_candidate_llm_confidence_threshold": self.memory_candidate_llm_confidence_threshold,
            "memory_candidate_llm_max_candidates": self.memory_candidate_llm_max_candidates,
            "memory_embedding_enabled": self.memory_embedding_enabled,
            "memory_embedding_provider": self.memory_embedding_provider,
            "memory_embedding_model": self.memory_embedding_model,
            "memory_embedding_min_score": self.memory_embedding_min_score,
        }


def _get_env(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None or value == "" else value


def _get_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    lowered = value.lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _get_float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be greater than 0")
    return parsed


def _get_score_env(name: str, default: float) -> float:
    parsed = _get_float_env(name, default)
    if parsed < 0.0 or parsed > 1.0:
        raise ValueError(f"{name} must be between 0.0 and 1.0")
    return parsed


def _get_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"{name} must be greater than or equal to 0")
    return parsed


def _get_positive_int_env(name: str, default: int) -> int:
    parsed = _get_int_env(name, default)
    if parsed <= 0:
        raise ValueError(f"{name} must be greater than 0")
    return parsed


def _get_int_env_with_max(name: str, default: int, maximum: int) -> int:
    parsed = _get_positive_int_env(name, default)
    if parsed > maximum:
        raise ValueError(f"{name} must be less than or equal to {maximum}")
    return parsed


def _get_stripped_env(name: str, default: str) -> str:
    value = _get_env(name, default).strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value


def _validate_duration_window(minimum_ms: int, maximum_ms: int) -> None:
    if minimum_ms > maximum_ms:
        raise ValueError("ASR_MIN_DURATION_MS must be less than or equal to ASR_MAX_DURATION_MS")


def load_settings() -> Settings:
    provider = _get_env("LLM_PROVIDER", "fake").lower()
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY") or None
    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY") or None
    deepseek_thinking_enabled = _get_bool_env("DEEPSEEK_THINKING_ENABLED", False)

    if provider not in {"fake", "anthropic", "deepseek"}:
        raise ValueError("LLM_PROVIDER must be one of: fake, anthropic, deepseek")
    if provider == "anthropic" and not anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
    if provider == "deepseek" and not deepseek_api_key:
        raise ValueError("DEEPSEEK_API_KEY is required when LLM_PROVIDER=deepseek")
    if provider == "deepseek" and deepseek_thinking_enabled:
        raise ValueError("DEEPSEEK_THINKING_ENABLED must be false in stage 1")

    tts_provider = _get_env("TTS_PROVIDER", "fake").lower()
    if tts_provider not in {"fake", "cosyvoice-http"}:
        raise ValueError("TTS_PROVIDER must be one of: fake, cosyvoice-http")

    asr_provider = _get_env("ASR_PROVIDER", "fake").lower()
    if asr_provider not in {"fake", "faster-whisper"}:
        raise ValueError("ASR_PROVIDER must be one of: fake, faster-whisper")
    asr_max_upload_bytes = _get_int_env_with_max(
        "ASR_MAX_UPLOAD_BYTES",
        DEFAULT_ASR_MAX_UPLOAD_BYTES,
        ABSOLUTE_ASR_MAX_UPLOAD_BYTES,
    )
    asr_max_duration_ms = _get_positive_int_env("ASR_MAX_DURATION_MS", 30_000)
    asr_min_duration_ms = _get_positive_int_env("ASR_MIN_DURATION_MS", 300)
    _validate_duration_window(asr_min_duration_ms, asr_max_duration_ms)
    fake_asr_text = _get_stripped_env("FAKE_ASR_TEXT", "这是 Fake ASR 测试转写。")
    asr_faster_whisper_model_path = _get_env("ASR_FASTER_WHISPER_MODEL_PATH", "").strip()
    asr_faster_whisper_model_name = _get_stripped_env("ASR_FASTER_WHISPER_MODEL_NAME", "medium")
    asr_faster_whisper_model_revision = _get_stripped_env(
        "ASR_FASTER_WHISPER_MODEL_REVISION",
        "08e178d48790749d25932bbc082711ddcfdfbc4f",
    )
    asr_faster_whisper_device = _get_env("ASR_FASTER_WHISPER_DEVICE", "cuda").lower()
    asr_faster_whisper_compute_type = _get_stripped_env("ASR_FASTER_WHISPER_COMPUTE_TYPE", "float16")
    asr_faster_whisper_beam_size = _get_positive_int_env("ASR_FASTER_WHISPER_BEAM_SIZE", 1)
    asr_faster_whisper_timeout_seconds = _get_float_env("ASR_FASTER_WHISPER_TIMEOUT_SECONDS", 30.0)
    asr_faster_whisper_streaming_enabled = _get_bool_env("ASR_FASTER_WHISPER_STREAMING_ENABLED", False)
    asr_faster_whisper_streaming_window_ms = _get_positive_int_env("ASR_FASTER_WHISPER_STREAMING_WINDOW_MS", 3000)
    asr_faster_whisper_streaming_step_ms = _get_positive_int_env("ASR_FASTER_WHISPER_STREAMING_STEP_MS", 1000)
    asr_faster_whisper_streaming_min_partial_chars = _get_positive_int_env("ASR_FASTER_WHISPER_STREAMING_MIN_PARTIAL_CHARS", 1)
    asr_faster_whisper_streaming_max_partials = _get_positive_int_env("ASR_FASTER_WHISPER_STREAMING_MAX_PARTIALS", 8)
    if asr_faster_whisper_streaming_window_ms < asr_faster_whisper_streaming_step_ms:
        raise ValueError("ASR_FASTER_WHISPER_STREAMING_WINDOW_MS must be greater than or equal to ASR_FASTER_WHISPER_STREAMING_STEP_MS")
    if asr_provider == "faster-whisper" and not asr_faster_whisper_model_path:
        raise ValueError("ASR_FASTER_WHISPER_MODEL_PATH is required when ASR_PROVIDER=faster-whisper")
    if asr_faster_whisper_device not in {"cuda", "cpu"}:
        raise ValueError("ASR_FASTER_WHISPER_DEVICE must be one of: cuda, cpu")

    memory_candidate_provider = _get_env("MEMORY_CANDIDATE_PROVIDER", "heuristic").lower()
    if memory_candidate_provider not in {"heuristic", "llm"}:
        raise ValueError("MEMORY_CANDIDATE_PROVIDER must be one of: heuristic, llm")
    memory_embedding_provider = _get_env("MEMORY_EMBEDDING_PROVIDER", "fake").lower()
    if memory_embedding_provider not in {"fake", "sentence-transformers"}:
        raise ValueError("MEMORY_EMBEDDING_PROVIDER must be one of: fake, sentence-transformers")
    memory_context_limit = _get_positive_int_env("MEMORY_CONTEXT_LIMIT", 8)
    memory_retrieval_mode = _get_env("MEMORY_RETRIEVAL_MODE", "relevance").lower()
    if memory_retrieval_mode not in {"embedding", "relevance", "recent"}:
        raise ValueError("MEMORY_RETRIEVAL_MODE must be one of: embedding, relevance, recent")
    memory_retrieval_fallback_limit = _get_positive_int_env("MEMORY_RETRIEVAL_FALLBACK_LIMIT", 3)
    if memory_retrieval_fallback_limit > memory_context_limit:
        raise ValueError("MEMORY_RETRIEVAL_FALLBACK_LIMIT must be less than or equal to MEMORY_CONTEXT_LIMIT")

    return Settings(
        app_name=_get_env("APP_NAME", "AI Desktop Companion"),
        app_env=_get_env("APP_ENV", "development"),
        log_level=_get_env("LOG_LEVEL", "INFO"),
        database_url=_get_env("DATABASE_URL", DEFAULT_DATABASE_URL),
        llm_provider=provider,
        llm_model=_get_env("LLM_MODEL", DEFAULT_MODEL),
        llm_timeout_seconds=_get_float_env("LLM_TIMEOUT_SECONDS", 30.0),
        llm_max_retries=_get_int_env("LLM_MAX_RETRIES", 2),
        recent_context_messages=_get_positive_int_env("RECENT_CONTEXT_MESSAGES", 12),
        fake_provider_mode=_get_env("FAKE_PROVIDER_MODE", "ok"),
        anthropic_api_key=anthropic_api_key,
        deepseek_api_key=deepseek_api_key,
        deepseek_base_url=_get_env("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL),
        deepseek_thinking_enabled=deepseek_thinking_enabled,
        deepseek_max_tokens=_get_int_env_with_max("DEEPSEEK_MAX_TOKENS", 256, 256),
        deepseek_timeout_seconds=_get_float_env("DEEPSEEK_TIMEOUT_SECONDS", 120.0),
        deepseek_max_retries=_get_int_env("DEEPSEEK_MAX_RETRIES", 0),
        tts_provider=tts_provider,
        tts_fake_mode=_get_env("TTS_FAKE_MODE", "ok"),
        tts_max_text_chars=_get_positive_int_env("TTS_MAX_TEXT_CHARS", 1000),
        tts_default_voice=_get_env("TTS_DEFAULT_VOICE", "fake-default"),
        tts_default_speed=_get_float_env("TTS_DEFAULT_SPEED", 1.0),
        tts_cosyvoice_base_url=_get_stripped_env("TTS_COSYVOICE_BASE_URL", "http://127.0.0.1:8001"),
        tts_cosyvoice_model=_get_stripped_env("TTS_COSYVOICE_MODEL", "Fun-CosyVoice3-0.5B-2512"),
        tts_cosyvoice_timeout_seconds=_get_float_env("TTS_COSYVOICE_TIMEOUT_SECONDS", 30.0),
        asr_provider=asr_provider,
        asr_max_upload_bytes=asr_max_upload_bytes,
        asr_max_duration_ms=asr_max_duration_ms,
        asr_min_duration_ms=asr_min_duration_ms,
        asr_default_language=_get_stripped_env("ASR_DEFAULT_LANGUAGE", "zh"),
        fake_asr_mode=_get_env("FAKE_ASR_MODE", "ok"),
        fake_asr_text=fake_asr_text,
        fake_asr_detected_language=_get_env("FAKE_ASR_DETECTED_LANGUAGE", "zh") or None,
        asr_faster_whisper_model_path=asr_faster_whisper_model_path,
        asr_faster_whisper_model_name=asr_faster_whisper_model_name,
        asr_faster_whisper_model_revision=asr_faster_whisper_model_revision,
        asr_faster_whisper_device=asr_faster_whisper_device,
        asr_faster_whisper_compute_type=asr_faster_whisper_compute_type,
        asr_faster_whisper_beam_size=asr_faster_whisper_beam_size,
        asr_faster_whisper_timeout_seconds=asr_faster_whisper_timeout_seconds,
        asr_faster_whisper_streaming_enabled=asr_faster_whisper_streaming_enabled,
        asr_faster_whisper_streaming_window_ms=asr_faster_whisper_streaming_window_ms,
        asr_faster_whisper_streaming_step_ms=asr_faster_whisper_streaming_step_ms,
        asr_faster_whisper_streaming_min_partial_chars=asr_faster_whisper_streaming_min_partial_chars,
        asr_faster_whisper_streaming_max_partials=asr_faster_whisper_streaming_max_partials,
        memory_context_enabled=_get_bool_env("MEMORY_CONTEXT_ENABLED", True),
        memory_context_limit=memory_context_limit,
        memory_retrieval_mode=memory_retrieval_mode,
        memory_retrieval_fallback_limit=memory_retrieval_fallback_limit,
        memory_candidates_enabled=_get_bool_env("MEMORY_CANDIDATES_ENABLED", True),
        memory_candidate_provider=memory_candidate_provider,
        memory_candidate_llm_max_tokens=_get_positive_int_env("MEMORY_CANDIDATE_LLM_MAX_TOKENS", 512),
        memory_candidate_llm_timeout_seconds=_get_float_env("MEMORY_CANDIDATE_LLM_TIMEOUT_SECONDS", 15.0),
        memory_candidate_llm_confidence_threshold=_get_score_env("MEMORY_CANDIDATE_LLM_CONFIDENCE_THRESHOLD", 0.75),
        memory_candidate_llm_max_candidates=_get_positive_int_env("MEMORY_CANDIDATE_LLM_MAX_CANDIDATES", 3),
        memory_embedding_enabled=_get_bool_env("MEMORY_EMBEDDING_ENABLED", False),
        memory_embedding_provider=memory_embedding_provider,
        memory_embedding_model=_get_stripped_env("MEMORY_EMBEDDING_MODEL", "fake-memory-embedding-v1"),
        memory_embedding_min_score=_get_score_env("MEMORY_EMBEDDING_MIN_SCORE", 0.35),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
