import math
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.domain.models import MemoryType
from app.services.persona_contract import ContextTypeBudget


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
    chat_context_max_characters: int = 24_000
    chat_current_user_max_characters: int = 8_000
    persona_max_characters: int = 8_000
    chat_dynamic_context_max_characters: int = 8_000
    chat_emotion_context_max_characters: int = 500
    memory_context_user_fact_max_items: int = 2
    memory_context_user_fact_max_characters: int = 1_200
    memory_context_preference_max_items: int = 2
    memory_context_preference_max_characters: int = 1_200
    memory_context_long_term_goal_max_items: int = 2
    memory_context_long_term_goal_max_characters: int = 1_200
    memory_context_important_event_max_items: int = 1
    memory_context_important_event_max_characters: int = 800
    memory_context_relationship_event_max_items: int = 1
    memory_context_relationship_event_max_characters: int = 800
    memory_context_other_max_items: int = 1
    memory_context_other_max_characters: int = 600
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
    memory_automation_mode: str = "candidate_confirmation"
    memory_extractor_route: str = "none"
    memory_extractor_provider: str = "anthropic"
    memory_extractor_model: str = ""
    memory_extractor_max_tokens: int = 512
    memory_extractor_timeout_seconds: float = 15.0
    memory_extractor_max_retries: int = 0
    memory_extractor_max_proposals: int = 3
    memory_extractor_max_proposal_characters: int = 200
    memory_extractor_max_total_characters: int = 600
    memory_commit_semantic_retries: int = 2
    memory_source_reference_key_path: Path = Path(
        "backend/data/memory-source-reference-v1.key"
    )
    session_summary_enabled: bool = True
    session_summary_provider: str = "fake"
    session_summary_trigger_message_count: int = 12
    session_summary_trigger_turn_count: int = 6
    session_summary_max_input_turns: int = 12
    session_summary_max_input_messages: int = 24
    session_summary_max_input_characters: int = 12_000
    session_summary_llm_provider: str = "deepseek"
    session_summary_llm_model: str = DEFAULT_MODEL
    session_summary_llm_max_tokens: int = 512
    session_summary_llm_timeout_seconds: float = 15.0
    session_summary_llm_max_retries: int = 0
    session_summary_max_output_characters: int = 2_000
    summary_injection_max_fragments: int = 2
    summary_injection_max_fragment_characters: int = 1_000
    summary_injection_max_total_characters: int = 1_600
    summary_injection_min_lexical_relevance: float = 0.15
    summary_rebuild_min_safe_turns: int = 1
    summary_job_max_attempts: int = 3
    summary_job_recovery_stale_seconds: int = 300
    relationship_context_max_characters: int = 600
    relationship_reconcile_max_attempts: int = 3
    relationship_recovery_stale_seconds: int = 300
    emotion_analysis_enabled: bool = False
    emotion_analysis_provider: str = "deepseek"
    emotion_analysis_model: str = DEFAULT_MODEL
    emotion_analysis_max_tokens: int = 384
    emotion_analysis_timeout_seconds: float = 15.0
    emotion_analysis_max_retries: int = 0
    emotion_analysis_recent_messages: int = 6
    emotion_analysis_memory_limit: int = 3
    emotion_analysis_max_item_characters: int = 2_000
    emotion_analysis_max_total_characters: int = 8_000

    def context_memory_type_budgets(self) -> dict[MemoryType, ContextTypeBudget]:
        return {
            MemoryType.USER_FACT: ContextTypeBudget(
                self.memory_context_user_fact_max_items,
                self.memory_context_user_fact_max_characters,
                1,
            ),
            MemoryType.PREFERENCE: ContextTypeBudget(
                self.memory_context_preference_max_items,
                self.memory_context_preference_max_characters,
                1,
            ),
            MemoryType.LONG_TERM_GOAL: ContextTypeBudget(
                self.memory_context_long_term_goal_max_items,
                self.memory_context_long_term_goal_max_characters,
                1,
            ),
            MemoryType.IMPORTANT_EVENT: ContextTypeBudget(
                self.memory_context_important_event_max_items,
                self.memory_context_important_event_max_characters,
                1,
            ),
            MemoryType.RELATIONSHIP_EVENT: ContextTypeBudget(
                self.memory_context_relationship_event_max_items,
                self.memory_context_relationship_event_max_characters,
                1,
            ),
            MemoryType.OTHER: ContextTypeBudget(
                self.memory_context_other_max_items,
                self.memory_context_other_max_characters,
                0,
            ),
        }

    def emotion_analysis_policy_fingerprint(self) -> str:
        endpoint = self.deepseek_base_url.rstrip('/') if self.emotion_analysis_provider == "deepseek" else "anthropic-default"
        return "|".join(
            (
                "emotion-analysis-disclosure-v1",
                self.emotion_analysis_provider,
                endpoint,
                str(self.emotion_analysis_recent_messages),
                str(self.emotion_analysis_memory_limit),
                str(self.emotion_analysis_max_item_characters),
                str(self.emotion_analysis_max_total_characters),
            )
        )

    @property
    def sqlite_path(self) -> Path:
        if not self.database_url.startswith("sqlite:///"):
            raise ValueError("Only sqlite:/// database URLs are supported")
        raw_path = self.database_url.removeprefix("sqlite:///")
        if raw_path == ":memory:":
            raise ValueError("DATABASE_URL=sqlite:///:memory: is not supported; use an isolated temporary SQLite file")
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
            "chat_context_max_characters": self.chat_context_max_characters,
            "chat_current_user_max_characters": self.chat_current_user_max_characters,
            "persona_max_characters": self.persona_max_characters,
            "chat_dynamic_context_max_characters": self.chat_dynamic_context_max_characters,
            "chat_emotion_context_max_characters": self.chat_emotion_context_max_characters,
            "memory_context_user_fact_max_items": self.memory_context_user_fact_max_items,
            "memory_context_user_fact_max_characters": self.memory_context_user_fact_max_characters,
            "memory_context_preference_max_items": self.memory_context_preference_max_items,
            "memory_context_preference_max_characters": self.memory_context_preference_max_characters,
            "memory_context_long_term_goal_max_items": self.memory_context_long_term_goal_max_items,
            "memory_context_long_term_goal_max_characters": self.memory_context_long_term_goal_max_characters,
            "memory_context_important_event_max_items": self.memory_context_important_event_max_items,
            "memory_context_important_event_max_characters": self.memory_context_important_event_max_characters,
            "memory_context_relationship_event_max_items": self.memory_context_relationship_event_max_items,
            "memory_context_relationship_event_max_characters": self.memory_context_relationship_event_max_characters,
            "memory_context_other_max_items": self.memory_context_other_max_items,
            "memory_context_other_max_characters": self.memory_context_other_max_characters,
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
            "memory_automation_mode": self.memory_automation_mode,
            "memory_extractor_route": self.memory_extractor_route,
            "memory_extractor_provider": self.memory_extractor_provider,
            "memory_extractor_model": self.memory_extractor_model,
            "memory_extractor_max_tokens": self.memory_extractor_max_tokens,
            "memory_extractor_timeout_seconds": self.memory_extractor_timeout_seconds,
            "memory_extractor_max_retries": self.memory_extractor_max_retries,
            "memory_extractor_max_proposals": self.memory_extractor_max_proposals,
            "memory_extractor_max_proposal_characters": self.memory_extractor_max_proposal_characters,
            "memory_extractor_max_total_characters": self.memory_extractor_max_total_characters,
            "memory_commit_semantic_retries": self.memory_commit_semantic_retries,
            "memory_source_reference_key_path": str(
                self.memory_source_reference_key_path
            ),
            "session_summary_enabled": self.session_summary_enabled,
            "session_summary_provider": self.session_summary_provider,
            "session_summary_trigger_message_count": self.session_summary_trigger_message_count,
            "session_summary_trigger_turn_count": self.session_summary_trigger_turn_count,
            "session_summary_max_input_turns": self.session_summary_max_input_turns,
            "session_summary_max_input_messages": self.session_summary_max_input_messages,
            "session_summary_max_input_characters": self.session_summary_max_input_characters,
            "session_summary_llm_provider": self.session_summary_llm_provider,
            "session_summary_llm_model": self.session_summary_llm_model,
            "session_summary_llm_max_tokens": self.session_summary_llm_max_tokens,
            "session_summary_llm_timeout_seconds": self.session_summary_llm_timeout_seconds,
            "session_summary_llm_max_retries": self.session_summary_llm_max_retries,
            "session_summary_max_output_characters": self.session_summary_max_output_characters,
            "summary_injection_max_fragments": self.summary_injection_max_fragments,
            "summary_injection_max_fragment_characters": self.summary_injection_max_fragment_characters,
            "summary_injection_max_total_characters": self.summary_injection_max_total_characters,
            "summary_injection_min_lexical_relevance": self.summary_injection_min_lexical_relevance,
            "summary_rebuild_min_safe_turns": self.summary_rebuild_min_safe_turns,
            "summary_job_max_attempts": self.summary_job_max_attempts,
            "summary_job_recovery_stale_seconds": self.summary_job_recovery_stale_seconds,
            "relationship_context_max_characters": self.relationship_context_max_characters,
            "relationship_reconcile_max_attempts": self.relationship_reconcile_max_attempts,
            "relationship_recovery_stale_seconds": self.relationship_recovery_stale_seconds,
            "emotion_analysis_enabled": self.emotion_analysis_enabled,
            "emotion_analysis_provider": self.emotion_analysis_provider,
            "emotion_analysis_model": self.emotion_analysis_model,
            "emotion_analysis_max_tokens": self.emotion_analysis_max_tokens,
            "emotion_analysis_timeout_seconds": self.emotion_analysis_timeout_seconds,
            "emotion_analysis_max_retries": self.emotion_analysis_max_retries,
            "emotion_analysis_recent_messages": self.emotion_analysis_recent_messages,
            "emotion_analysis_memory_limit": self.emotion_analysis_memory_limit,
            "emotion_analysis_max_item_characters": self.emotion_analysis_max_item_characters,
            "emotion_analysis_max_total_characters": self.emotion_analysis_max_total_characters,
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


def _get_positive_score_env(name: str, default: float) -> float:
    parsed = _get_float_env(name, default)
    if not math.isfinite(parsed) or parsed > 1.0:
        raise ValueError(f"{name} must be greater than 0.0 and less than or equal to 1.0")
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


def _get_bounded_int_env(
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    parsed = _get_int_env(name, default)
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
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

    chat_context_max_characters = _get_bounded_int_env(
        "CHAT_CONTEXT_MAX_CHARACTERS", 24_000, 2_048, 100_000
    )
    chat_current_user_max_characters = _get_bounded_int_env(
        "CHAT_CURRENT_USER_MAX_CHARACTERS", 8_000, 1, 8_000
    )
    persona_max_characters = _get_bounded_int_env(
        "PERSONA_MAX_CHARACTERS", 8_000, 1_024, 16_000
    )
    chat_dynamic_context_max_characters = _get_bounded_int_env(
        "CHAT_DYNAMIC_CONTEXT_MAX_CHARACTERS", 8_000, 512, 32_000
    )
    recent_context_messages = _get_bounded_int_env(
        "RECENT_CONTEXT_MESSAGES", 12, 1, 50
    )
    chat_emotion_context_max_characters = _get_bounded_int_env(
        "CHAT_EMOTION_CONTEXT_MAX_CHARACTERS", 500, 100, 1_000
    )
    if persona_max_characters + chat_current_user_max_characters > chat_context_max_characters:
        raise ValueError(
            "protected context maxima must not exceed CHAT_CONTEXT_MAX_CHARACTERS"
        )
    if chat_dynamic_context_max_characters > chat_context_max_characters:
        raise ValueError(
            "CHAT_DYNAMIC_CONTEXT_MAX_CHARACTERS must not exceed "
            "CHAT_CONTEXT_MAX_CHARACTERS"
        )
    if chat_emotion_context_max_characters > chat_dynamic_context_max_characters:
        raise ValueError(
            "CHAT_EMOTION_CONTEXT_MAX_CHARACTERS must not exceed "
            "CHAT_DYNAMIC_CONTEXT_MAX_CHARACTERS"
        )

    context_memory_budget_values = {
        "memory_context_user_fact_max_items": _get_bounded_int_env(
            "MEMORY_CONTEXT_USER_FACT_MAX_ITEMS", 2, 1, 8
        ),
        "memory_context_user_fact_max_characters": _get_bounded_int_env(
            "MEMORY_CONTEXT_USER_FACT_MAX_CHARACTERS", 1_200, 200, 8_000
        ),
        "memory_context_preference_max_items": _get_bounded_int_env(
            "MEMORY_CONTEXT_PREFERENCE_MAX_ITEMS", 2, 1, 8
        ),
        "memory_context_preference_max_characters": _get_bounded_int_env(
            "MEMORY_CONTEXT_PREFERENCE_MAX_CHARACTERS", 1_200, 200, 8_000
        ),
        "memory_context_long_term_goal_max_items": _get_bounded_int_env(
            "MEMORY_CONTEXT_LONG_TERM_GOAL_MAX_ITEMS", 2, 1, 8
        ),
        "memory_context_long_term_goal_max_characters": _get_bounded_int_env(
            "MEMORY_CONTEXT_LONG_TERM_GOAL_MAX_CHARACTERS", 1_200, 200, 8_000
        ),
        "memory_context_important_event_max_items": _get_bounded_int_env(
            "MEMORY_CONTEXT_IMPORTANT_EVENT_MAX_ITEMS", 1, 1, 8
        ),
        "memory_context_important_event_max_characters": _get_bounded_int_env(
            "MEMORY_CONTEXT_IMPORTANT_EVENT_MAX_CHARACTERS", 800, 200, 8_000
        ),
        "memory_context_relationship_event_max_items": _get_bounded_int_env(
            "MEMORY_CONTEXT_RELATIONSHIP_EVENT_MAX_ITEMS", 1, 1, 8
        ),
        "memory_context_relationship_event_max_characters": _get_bounded_int_env(
            "MEMORY_CONTEXT_RELATIONSHIP_EVENT_MAX_CHARACTERS", 800, 200, 8_000
        ),
        "memory_context_other_max_items": _get_bounded_int_env(
            "MEMORY_CONTEXT_OTHER_MAX_ITEMS", 1, 1, 8
        ),
        "memory_context_other_max_characters": _get_bounded_int_env(
            "MEMORY_CONTEXT_OTHER_MAX_CHARACTERS", 600, 200, 8_000
        ),
    }

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
    memory_context_limit = _get_bounded_int_env("MEMORY_CONTEXT_LIMIT", 8, 1, 32)
    memory_retrieval_mode = _get_env("MEMORY_RETRIEVAL_MODE", "relevance").lower()
    if memory_retrieval_mode not in {"embedding", "relevance", "recent"}:
        raise ValueError("MEMORY_RETRIEVAL_MODE must be one of: embedding, relevance, recent")
    memory_retrieval_fallback_limit = _get_positive_int_env("MEMORY_RETRIEVAL_FALLBACK_LIMIT", 3)
    if memory_retrieval_fallback_limit > memory_context_limit:
        raise ValueError("MEMORY_RETRIEVAL_FALLBACK_LIMIT must be less than or equal to MEMORY_CONTEXT_LIMIT")

    memory_automation_mode = _get_env(
        "MEMORY_AUTOMATION_MODE", "candidate_confirmation"
    ).lower()
    if memory_automation_mode not in {
        "off", "candidate_confirmation", "shadow_auto", "auto_active"
    }:
        raise ValueError(
            "MEMORY_AUTOMATION_MODE must be one of: off, candidate_confirmation, shadow_auto, auto_active"
        )

    memory_extractor_route = _get_env("MEMORY_EXTRACTOR_ROUTE", "none").lower()
    if memory_extractor_route not in {"none", "local", "fake", "remote"}:
        raise ValueError(
            "MEMORY_EXTRACTOR_ROUTE must be one of: none, local, fake, remote"
        )

    memory_extractor_provider = _get_env("MEMORY_EXTRACTOR_PROVIDER", "anthropic").lower()
    if memory_extractor_provider not in {"anthropic", "deepseek"}:
        raise ValueError(
            "MEMORY_EXTRACTOR_PROVIDER must be one of: anthropic, deepseek"
        )

    model = _get_env("LLM_MODEL", DEFAULT_MODEL)
    memory_extractor_model = _get_env("MEMORY_EXTRACTOR_MODEL", model).strip()
    if not memory_extractor_model:
        memory_extractor_model = model.strip()
    if not memory_extractor_model:
        raise ValueError("MEMORY_EXTRACTOR_MODEL must not be empty")
    memory_extractor_max_tokens = _get_int_env_with_max(
        "MEMORY_EXTRACTOR_MAX_TOKENS", 512, 2_048
    )
    if memory_extractor_max_tokens < 64:
        raise ValueError("MEMORY_EXTRACTOR_MAX_TOKENS must be greater than or equal to 64")
    memory_extractor_timeout_seconds = _get_float_env(
        "MEMORY_EXTRACTOR_TIMEOUT_SECONDS", 15.0
    )
    if not math.isfinite(memory_extractor_timeout_seconds):
        raise ValueError("MEMORY_EXTRACTOR_TIMEOUT_SECONDS must be finite")
    if memory_extractor_timeout_seconds > 60.0:
        raise ValueError("MEMORY_EXTRACTOR_TIMEOUT_SECONDS must be less than or equal to 60.0")
    if memory_extractor_timeout_seconds < 1.0:
        raise ValueError("MEMORY_EXTRACTOR_TIMEOUT_SECONDS must be greater than or equal to 1.0")
    memory_extractor_max_retries = _get_int_env("MEMORY_EXTRACTOR_MAX_RETRIES", 0)
    if memory_extractor_max_retries != 0:
        raise ValueError("MEMORY_EXTRACTOR_MAX_RETRIES must be 0 in Gate A")
    memory_extractor_max_proposals = _get_int_env_with_max(
        "MEMORY_EXTRACTOR_MAX_PROPOSALS", 3, 10
    )
    memory_extractor_max_proposal_characters = _get_int_env_with_max(
        "MEMORY_EXTRACTOR_MAX_PROPOSAL_CHARACTERS", 200, 500
    )
    if memory_extractor_max_proposal_characters < 20:
        raise ValueError(
            "MEMORY_EXTRACTOR_MAX_PROPOSAL_CHARACTERS must be greater than or equal to 20"
        )
    memory_extractor_max_total_characters = _get_int_env_with_max(
        "MEMORY_EXTRACTOR_MAX_TOTAL_CHARACTERS", 600, 2_000
    )
    if memory_extractor_max_total_characters < 20:
        raise ValueError(
            "MEMORY_EXTRACTOR_MAX_TOTAL_CHARACTERS must be greater than or equal to 20"
        )
    if memory_extractor_max_total_characters < memory_extractor_max_proposal_characters:
        raise ValueError(
            "MEMORY_EXTRACTOR_MAX_TOTAL_CHARACTERS must be greater than or equal to "
            "MEMORY_EXTRACTOR_MAX_PROPOSAL_CHARACTERS"
        )
    memory_commit_semantic_retries = _get_int_env(
        "MEMORY_COMMIT_SEMANTIC_RETRIES", 2
    )
    if memory_commit_semantic_retries > 3:
        raise ValueError(
            "MEMORY_COMMIT_SEMANTIC_RETRIES must be less than or equal to 3"
        )
    memory_source_reference_key_path = Path(
        _get_stripped_env(
            "MEMORY_SOURCE_REFERENCE_KEY_PATH",
            "backend/data/memory-source-reference-v1.key",
        )
    )

    session_summary_provider = _get_env("SESSION_SUMMARY_PROVIDER", "fake").lower()
    if session_summary_provider not in {"fake", "llm"}:
        raise ValueError("SESSION_SUMMARY_PROVIDER must be one of: fake, llm")
    session_summary_llm_provider = _get_env("SESSION_SUMMARY_LLM_PROVIDER", "deepseek").lower()
    session_summary_llm_model = _get_env("SESSION_SUMMARY_LLM_MODEL", DEFAULT_MODEL).strip()
    if session_summary_provider == "llm":
        if session_summary_llm_provider not in {"anthropic", "deepseek"}:
            raise ValueError("SESSION_SUMMARY_LLM_PROVIDER must be one of: anthropic, deepseek")
        if not session_summary_llm_model:
            raise ValueError("SESSION_SUMMARY_LLM_MODEL must not be empty")
    session_summary_trigger_turn_count = _get_bounded_int_env(
        "SESSION_SUMMARY_TRIGGER_TURN_COUNT", 6, 1, 50
    )
    session_summary_max_input_turns = _get_bounded_int_env(
        "SESSION_SUMMARY_MAX_INPUT_TURNS", 12, 1, 50
    )
    session_summary_max_input_messages = _get_bounded_int_env(
        "SESSION_SUMMARY_MAX_INPUT_MESSAGES", 24, 2, 100
    )
    session_summary_max_input_characters = _get_bounded_int_env(
        "SESSION_SUMMARY_MAX_INPUT_CHARACTERS", 12_000, 512, 50_000
    )
    session_summary_llm_max_tokens = _get_bounded_int_env(
        "SESSION_SUMMARY_LLM_MAX_TOKENS", 512, 64, 2_048
    )
    session_summary_llm_timeout_seconds = _get_float_env(
        "SESSION_SUMMARY_LLM_TIMEOUT_SECONDS", 15.0
    )
    if (
        not math.isfinite(session_summary_llm_timeout_seconds)
        or not 1 <= session_summary_llm_timeout_seconds <= 120
    ):
        raise ValueError(
            "SESSION_SUMMARY_LLM_TIMEOUT_SECONDS must be between 1 and 120"
        )
    session_summary_llm_max_retries = _get_bounded_int_env(
        "SESSION_SUMMARY_LLM_MAX_RETRIES", 0, 0, 3
    )
    session_summary_max_output_characters = _get_bounded_int_env(
        "SESSION_SUMMARY_MAX_OUTPUT_CHARACTERS", 2_000, 128, 8_000
    )
    summary_injection_max_fragments = _get_bounded_int_env(
        "SUMMARY_INJECTION_MAX_FRAGMENTS", 2, 1, 8
    )
    summary_injection_max_fragment_characters = _get_bounded_int_env(
        "SUMMARY_INJECTION_MAX_FRAGMENT_CHARACTERS", 1_000, 64, 4_000
    )
    summary_injection_max_total_characters = _get_bounded_int_env(
        "SUMMARY_INJECTION_MAX_TOTAL_CHARACTERS", 1_600, 64, 8_000
    )
    summary_injection_min_lexical_relevance = _get_positive_score_env(
        "SUMMARY_INJECTION_MIN_LEXICAL_RELEVANCE", 0.15
    )
    summary_rebuild_min_safe_turns = _get_bounded_int_env(
        "SUMMARY_REBUILD_MIN_SAFE_TURNS", 1, 1, 50
    )
    summary_job_max_attempts = _get_bounded_int_env(
        "SUMMARY_JOB_MAX_ATTEMPTS", 3, 1, 10
    )
    summary_job_recovery_stale_seconds = _get_bounded_int_env(
        "SUMMARY_JOB_RECOVERY_STALE_SECONDS", 300, 30, 3_600
    )
    if session_summary_trigger_turn_count > session_summary_max_input_turns:
        raise ValueError(
            "SESSION_SUMMARY_TRIGGER_TURN_COUNT must not exceed "
            "SESSION_SUMMARY_MAX_INPUT_TURNS"
        )
    if session_summary_max_input_messages % 2:
        raise ValueError("SESSION_SUMMARY_MAX_INPUT_MESSAGES must be even")
    if (
        summary_injection_max_fragment_characters
        > summary_injection_max_total_characters
    ):
        raise ValueError(
            "SUMMARY_INJECTION_MAX_FRAGMENT_CHARACTERS must not exceed "
            "SUMMARY_INJECTION_MAX_TOTAL_CHARACTERS"
        )
    if summary_injection_max_total_characters > chat_dynamic_context_max_characters:
        raise ValueError(
            "SUMMARY_INJECTION_MAX_TOTAL_CHARACTERS must not exceed dynamic context"
        )

    relationship_context_max_characters = _get_bounded_int_env(
        "RELATIONSHIP_CONTEXT_MAX_CHARACTERS", 600, 128, 2_000
    )
    relationship_reconcile_max_attempts = _get_bounded_int_env(
        "RELATIONSHIP_RECONCILE_MAX_ATTEMPTS", 3, 1, 10
    )
    relationship_recovery_stale_seconds = _get_bounded_int_env(
        "RELATIONSHIP_RECOVERY_STALE_SECONDS", 300, 30, 3_600
    )
    if relationship_context_max_characters > chat_dynamic_context_max_characters:
        raise ValueError(
            "RELATIONSHIP_CONTEXT_MAX_CHARACTERS must not exceed dynamic context"
        )

    emotion_analysis_enabled = _get_bool_env("EMOTION_ANALYSIS_ENABLED", False)
    emotion_analysis_provider = _get_env("EMOTION_ANALYSIS_PROVIDER", "deepseek").lower()
    emotion_analysis_model = _get_env("EMOTION_ANALYSIS_MODEL", DEFAULT_MODEL).strip()
    emotion_analysis_max_tokens = _get_positive_int_env("EMOTION_ANALYSIS_MAX_TOKENS", 384)
    emotion_analysis_timeout_seconds = _get_float_env("EMOTION_ANALYSIS_TIMEOUT_SECONDS", 15.0)
    emotion_analysis_max_retries = _get_int_env("EMOTION_ANALYSIS_MAX_RETRIES", 0)
    if emotion_analysis_max_retries != 0:
        raise ValueError("EMOTION_ANALYSIS_MAX_RETRIES must be 0 without provider idempotency support")
    emotion_analysis_recent_messages = _get_positive_int_env("EMOTION_ANALYSIS_RECENT_MESSAGES", 6)
    emotion_analysis_memory_limit = _get_positive_int_env("EMOTION_ANALYSIS_MEMORY_LIMIT", 3)
    emotion_analysis_max_item_characters = _get_positive_int_env("EMOTION_ANALYSIS_MAX_ITEM_CHARACTERS", 2_000)
    emotion_analysis_max_total_characters = _get_positive_int_env("EMOTION_ANALYSIS_MAX_TOTAL_CHARACTERS", 8_000)
    if emotion_analysis_max_total_characters < 2:
        raise ValueError("EMOTION_ANALYSIS_MAX_TOTAL_CHARACTERS must be at least 2")
    if emotion_analysis_recent_messages > 6:
        raise ValueError("EMOTION_ANALYSIS_RECENT_MESSAGES must be less than or equal to 6")
    if emotion_analysis_memory_limit > 3:
        raise ValueError("EMOTION_ANALYSIS_MEMORY_LIMIT must be less than or equal to 3")
    if emotion_analysis_enabled:
        if emotion_analysis_provider not in {"anthropic", "deepseek"}:
            raise ValueError("EMOTION_ANALYSIS_PROVIDER must be one of: anthropic, deepseek")
        if not emotion_analysis_model:
            raise ValueError("EMOTION_ANALYSIS_MODEL must not be empty")
        if emotion_analysis_provider == "anthropic" and not anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when EMOTION_ANALYSIS_PROVIDER=anthropic")
        if emotion_analysis_provider == "deepseek" and not deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY is required when EMOTION_ANALYSIS_PROVIDER=deepseek")
        if emotion_analysis_max_total_characters < emotion_analysis_max_item_characters:
            raise ValueError(
                "EMOTION_ANALYSIS_MAX_TOTAL_CHARACTERS must be greater than or equal to "
                "EMOTION_ANALYSIS_MAX_ITEM_CHARACTERS"
            )

    return Settings(
        app_name=_get_env("APP_NAME", "AI Desktop Companion"),
        app_env=_get_env("APP_ENV", "development"),
        log_level=_get_env("LOG_LEVEL", "INFO"),
        database_url=_get_env("DATABASE_URL", DEFAULT_DATABASE_URL),
        llm_provider=provider,
        llm_model=model,
        llm_timeout_seconds=_get_float_env("LLM_TIMEOUT_SECONDS", 30.0),
        llm_max_retries=_get_int_env("LLM_MAX_RETRIES", 2),
        recent_context_messages=recent_context_messages,
        chat_context_max_characters=chat_context_max_characters,
        chat_current_user_max_characters=chat_current_user_max_characters,
        persona_max_characters=persona_max_characters,
        chat_dynamic_context_max_characters=chat_dynamic_context_max_characters,
        chat_emotion_context_max_characters=chat_emotion_context_max_characters,
        **context_memory_budget_values,
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
        memory_automation_mode=memory_automation_mode,
        memory_extractor_route=memory_extractor_route,
        memory_extractor_provider=memory_extractor_provider,
        memory_extractor_model=memory_extractor_model,
        memory_extractor_max_tokens=memory_extractor_max_tokens,
        memory_extractor_timeout_seconds=memory_extractor_timeout_seconds,
        memory_extractor_max_retries=memory_extractor_max_retries,
        memory_extractor_max_proposals=memory_extractor_max_proposals,
        memory_extractor_max_proposal_characters=memory_extractor_max_proposal_characters,
        memory_extractor_max_total_characters=memory_extractor_max_total_characters,
        memory_commit_semantic_retries=memory_commit_semantic_retries,
        memory_source_reference_key_path=memory_source_reference_key_path,
        session_summary_enabled=_get_bool_env("SESSION_SUMMARY_ENABLED", True),
        session_summary_provider=session_summary_provider,
        session_summary_trigger_message_count=_get_positive_int_env("SESSION_SUMMARY_TRIGGER_MESSAGE_COUNT", 12),
        session_summary_trigger_turn_count=session_summary_trigger_turn_count,
        session_summary_max_input_turns=session_summary_max_input_turns,
        session_summary_max_input_messages=session_summary_max_input_messages,
        session_summary_max_input_characters=session_summary_max_input_characters,
        session_summary_llm_provider=session_summary_llm_provider,
        session_summary_llm_model=session_summary_llm_model,
        session_summary_llm_max_tokens=session_summary_llm_max_tokens,
        session_summary_llm_timeout_seconds=session_summary_llm_timeout_seconds,
        session_summary_llm_max_retries=session_summary_llm_max_retries,
        session_summary_max_output_characters=session_summary_max_output_characters,
        summary_injection_max_fragments=summary_injection_max_fragments,
        summary_injection_max_fragment_characters=(
            summary_injection_max_fragment_characters
        ),
        summary_injection_max_total_characters=(
            summary_injection_max_total_characters
        ),
        summary_injection_min_lexical_relevance=(
            summary_injection_min_lexical_relevance
        ),
        summary_rebuild_min_safe_turns=summary_rebuild_min_safe_turns,
        summary_job_max_attempts=summary_job_max_attempts,
        summary_job_recovery_stale_seconds=summary_job_recovery_stale_seconds,
        relationship_context_max_characters=relationship_context_max_characters,
        relationship_reconcile_max_attempts=relationship_reconcile_max_attempts,
        relationship_recovery_stale_seconds=relationship_recovery_stale_seconds,
        emotion_analysis_enabled=emotion_analysis_enabled,
        emotion_analysis_provider=emotion_analysis_provider,
        emotion_analysis_model=emotion_analysis_model,
        emotion_analysis_max_tokens=emotion_analysis_max_tokens,
        emotion_analysis_timeout_seconds=emotion_analysis_timeout_seconds,
        emotion_analysis_max_retries=emotion_analysis_max_retries,
        emotion_analysis_recent_messages=emotion_analysis_recent_messages,
        emotion_analysis_memory_limit=emotion_analysis_memory_limit,
        emotion_analysis_max_item_characters=emotion_analysis_max_item_characters,
        emotion_analysis_max_total_characters=emotion_analysis_max_total_characters,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
