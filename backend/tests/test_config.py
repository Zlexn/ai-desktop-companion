import json
from pathlib import Path

import pytest

from app.core.config import DEFAULT_DATABASE_URL, DEFAULT_MODEL, Settings, load_settings
from app.core.errors import sanitize_error_text
from app.domain.models import (
    MemoryEvidenceExtractorKind,
    MemoryType,
    MemoryVersionSourceKind,
)
from app.domain.schemas import UpdateMemoryWriteConsentRequest
from app.services.memory_gate_b_contract import (
    MEMORY_ALLOWED_AUTO_TYPES,
    MEMORY_ALLOWED_AUTO_TYPES_VERSION,
    MEMORY_AUTO_ACTIVE_SCHEMA_VERSION,
    MEMORY_WRITE_POLICY_VERSION,
)
from app.services.persona_contract import (
    CONTEXT_COMPOSER_VERSION,
    CONTEXT_DATA_ENCODER_VERSION,
    CONTEXT_MANIFEST_VERSION,
    PERSONA_CANONICALIZATION_VERSION,
    PERSONA_COMPILER_VERSION,
    PERSONA_RULESET_VERSION,
    PERSONA_SCHEMA_VERSION,
    PERSONA_TEMPLATE_VERSION,
    ContextTypeBudget,
)


SESSION_SUMMARY_ENV_NAMES = (
    "SESSION_SUMMARY_ENABLED",
    "SESSION_SUMMARY_PROVIDER",
    "SESSION_SUMMARY_TRIGGER_MESSAGE_COUNT",
    "SESSION_SUMMARY_TRIGGER_TURN_COUNT",
    "SESSION_SUMMARY_MAX_INPUT_TURNS",
    "SESSION_SUMMARY_MAX_INPUT_MESSAGES",
    "SESSION_SUMMARY_MAX_INPUT_CHARACTERS",
    "SESSION_SUMMARY_LLM_PROVIDER",
    "SESSION_SUMMARY_LLM_MODEL",
    "SESSION_SUMMARY_LLM_MAX_TOKENS",
    "SESSION_SUMMARY_LLM_TIMEOUT_SECONDS",
    "SESSION_SUMMARY_LLM_MAX_RETRIES",
    "SESSION_SUMMARY_MAX_OUTPUT_CHARACTERS",
    "SUMMARY_INJECTION_MAX_FRAGMENTS",
    "SUMMARY_INJECTION_MAX_FRAGMENT_CHARACTERS",
    "SUMMARY_INJECTION_MAX_TOTAL_CHARACTERS",
    "SUMMARY_INJECTION_MIN_LEXICAL_RELEVANCE",
    "SUMMARY_REBUILD_MIN_SAFE_TURNS",
    "SUMMARY_JOB_MAX_ATTEMPTS",
    "SUMMARY_JOB_RECOVERY_STALE_SECONDS",
)

EMOTION_ANALYSIS_ENV_NAMES = (
    "EMOTION_ANALYSIS_ENABLED",
    "EMOTION_ANALYSIS_PROVIDER",
    "EMOTION_ANALYSIS_MODEL",
    "EMOTION_ANALYSIS_MAX_TOKENS",
    "EMOTION_ANALYSIS_TIMEOUT_SECONDS",
    "EMOTION_ANALYSIS_MAX_RETRIES",
    "EMOTION_ANALYSIS_RECENT_MESSAGES",
    "EMOTION_ANALYSIS_MEMORY_LIMIT",
    "EMOTION_ANALYSIS_MAX_ITEM_CHARACTERS",
    "EMOTION_ANALYSIS_MAX_TOTAL_CHARACTERS",
)

RELATIONSHIP_ENV_NAMES = (
    "RELATIONSHIP_CONTEXT_MAX_CHARACTERS",
    "RELATIONSHIP_RECONCILE_MAX_ATTEMPTS",
    "RELATIONSHIP_RECOVERY_STALE_SECONDS",
)


MEMORY_AUTOMATION_ENV_NAMES = (
    "MEMORY_AUTOMATION_MODE",
    "MEMORY_EXTRACTOR_ROUTE",
    "MEMORY_EXTRACTOR_PROVIDER",
    "MEMORY_EXTRACTOR_MODEL",
    "MEMORY_EXTRACTOR_MAX_TOKENS",
    "MEMORY_EXTRACTOR_TIMEOUT_SECONDS",
    "MEMORY_EXTRACTOR_MAX_RETRIES",
    "MEMORY_EXTRACTOR_MAX_PROPOSALS",
    "MEMORY_EXTRACTOR_MAX_PROPOSAL_CHARACTERS",
    "MEMORY_EXTRACTOR_MAX_TOTAL_CHARACTERS",
    "MEMORY_COMMIT_SEMANTIC_RETRIES",
    "MEMORY_SOURCE_REFERENCE_KEY_PATH",
)


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
        "CHAT_CONTEXT_MAX_CHARACTERS",
        "CHAT_CURRENT_USER_MAX_CHARACTERS",
        "PERSONA_MAX_CHARACTERS",
        "CHAT_DYNAMIC_CONTEXT_MAX_CHARACTERS",
        "CHAT_EMOTION_CONTEXT_MAX_CHARACTERS",
        "MEMORY_CONTEXT_USER_FACT_MAX_ITEMS",
        "MEMORY_CONTEXT_USER_FACT_MAX_CHARACTERS",
        "MEMORY_CONTEXT_PREFERENCE_MAX_ITEMS",
        "MEMORY_CONTEXT_PREFERENCE_MAX_CHARACTERS",
        "MEMORY_CONTEXT_LONG_TERM_GOAL_MAX_ITEMS",
        "MEMORY_CONTEXT_LONG_TERM_GOAL_MAX_CHARACTERS",
        "MEMORY_CONTEXT_IMPORTANT_EVENT_MAX_ITEMS",
        "MEMORY_CONTEXT_IMPORTANT_EVENT_MAX_CHARACTERS",
        "MEMORY_CONTEXT_RELATIONSHIP_EVENT_MAX_ITEMS",
        "MEMORY_CONTEXT_RELATIONSHIP_EVENT_MAX_CHARACTERS",
        "MEMORY_CONTEXT_OTHER_MAX_ITEMS",
        "MEMORY_CONTEXT_OTHER_MAX_CHARACTERS",
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
        *SESSION_SUMMARY_ENV_NAMES,
        *RELATIONSHIP_ENV_NAMES,
        *EMOTION_ANALYSIS_ENV_NAMES,
        *MEMORY_AUTOMATION_ENV_NAMES,
    ):
        monkeypatch.delenv(name, raising=False)



def test_chat_context_max_characters_defaults_to_24000(monkeypatch):
    monkeypatch.delenv("CHAT_CONTEXT_MAX_CHARACTERS", raising=False)

    settings = load_settings()

    assert settings.chat_context_max_characters == 24_000
    assert settings.redacted()["chat_context_max_characters"] == 24_000


def test_chat_context_max_characters_accepts_safe_override(monkeypatch):
    monkeypatch.setenv("CHAT_CONTEXT_MAX_CHARACTERS", "18000")

    assert load_settings().chat_context_max_characters == 18_000


@pytest.mark.parametrize("value", ["0", "-1", "not-an-integer"])
def test_chat_context_max_characters_rejects_invalid_values(monkeypatch, value):
    monkeypatch.setenv("CHAT_CONTEXT_MAX_CHARACTERS", value)

    with pytest.raises(ValueError, match="CHAT_CONTEXT_MAX_CHARACTERS"):
        load_settings()


def test_gate_c1_version_constants_are_frozen() -> None:
    assert PERSONA_SCHEMA_VERSION == "persona-schema-v1"
    assert PERSONA_RULESET_VERSION == "persona-ruleset-v1"
    assert PERSONA_TEMPLATE_VERSION == "persona-template-v1"
    assert PERSONA_COMPILER_VERSION == "persona-compiler-v1"
    assert PERSONA_CANONICALIZATION_VERSION == "persona-canonical-json-v1"
    assert CONTEXT_COMPOSER_VERSION == "context-composer-v2"
    assert CONTEXT_DATA_ENCODER_VERSION == "context-data-json-v2"
    assert CONTEXT_MANIFEST_VERSION == "context-manifest-v2"


def test_gate_c1_context_budget_defaults() -> None:
    settings = load_settings()

    assert settings.chat_context_max_characters == 24_000
    assert settings.chat_current_user_max_characters == 8_000
    assert settings.persona_max_characters == 8_000
    assert settings.chat_dynamic_context_max_characters == 8_000
    assert settings.recent_context_messages == 12
    assert settings.chat_emotion_context_max_characters == 500
    assert settings.memory_context_limit == 8
    assert settings.context_memory_type_budgets() == {
        MemoryType.USER_FACT: ContextTypeBudget(2, 1_200, 1),
        MemoryType.PREFERENCE: ContextTypeBudget(2, 1_200, 1),
        MemoryType.LONG_TERM_GOAL: ContextTypeBudget(2, 1_200, 1),
        MemoryType.IMPORTANT_EVENT: ContextTypeBudget(1, 800, 1),
        MemoryType.RELATIONSHIP_EVENT: ContextTypeBudget(1, 800, 1),
        MemoryType.OTHER: ContextTypeBudget(1, 600, 0),
    }
    redacted = settings.redacted()
    assert redacted["chat_current_user_max_characters"] == 8_000
    assert redacted["persona_max_characters"] == 8_000
    assert redacted["memory_context_user_fact_max_characters"] == 1_200


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({"CHAT_CONTEXT_MAX_CHARACTERS": "2047"}, "CHAT_CONTEXT_MAX_CHARACTERS"),
        ({"CHAT_CONTEXT_MAX_CHARACTERS": "100001"}, "CHAT_CONTEXT_MAX_CHARACTERS"),
        ({"CHAT_CURRENT_USER_MAX_CHARACTERS": "0"}, "CHAT_CURRENT_USER_MAX_CHARACTERS"),
        ({"CHAT_CURRENT_USER_MAX_CHARACTERS": "8001"}, "CHAT_CURRENT_USER_MAX_CHARACTERS"),
        ({"PERSONA_MAX_CHARACTERS": "1023"}, "PERSONA_MAX_CHARACTERS"),
        ({"PERSONA_MAX_CHARACTERS": "16001"}, "PERSONA_MAX_CHARACTERS"),
        (
            {
                "CHAT_CONTEXT_MAX_CHARACTERS": "12000",
                "PERSONA_MAX_CHARACTERS": "8000",
                "CHAT_CURRENT_USER_MAX_CHARACTERS": "8000",
            },
            "protected context maxima",
        ),
        ({"CHAT_DYNAMIC_CONTEXT_MAX_CHARACTERS": "511"}, "CHAT_DYNAMIC_CONTEXT_MAX_CHARACTERS"),
        ({"CHAT_DYNAMIC_CONTEXT_MAX_CHARACTERS": "32001"}, "CHAT_DYNAMIC_CONTEXT_MAX_CHARACTERS"),
        (
            {"CHAT_DYNAMIC_CONTEXT_MAX_CHARACTERS": "25000"},
            "CHAT_DYNAMIC_CONTEXT_MAX_CHARACTERS",
        ),
        ({"CHAT_EMOTION_CONTEXT_MAX_CHARACTERS": "99"}, "CHAT_EMOTION_CONTEXT_MAX_CHARACTERS"),
        ({"CHAT_EMOTION_CONTEXT_MAX_CHARACTERS": "1001"}, "CHAT_EMOTION_CONTEXT_MAX_CHARACTERS"),
        (
            {
                "CHAT_DYNAMIC_CONTEXT_MAX_CHARACTERS": "512",
                "CHAT_EMOTION_CONTEXT_MAX_CHARACTERS": "600",
            },
            "CHAT_EMOTION_CONTEXT_MAX_CHARACTERS",
        ),
        ({"RECENT_CONTEXT_MESSAGES": "0"}, "RECENT_CONTEXT_MESSAGES"),
        ({"RECENT_CONTEXT_MESSAGES": "51"}, "RECENT_CONTEXT_MESSAGES"),
        ({"MEMORY_CONTEXT_LIMIT": "0"}, "MEMORY_CONTEXT_LIMIT"),
        ({"MEMORY_CONTEXT_LIMIT": "33"}, "MEMORY_CONTEXT_LIMIT"),
        ({"MEMORY_CONTEXT_USER_FACT_MAX_ITEMS": "0"}, "MEMORY_CONTEXT_USER_FACT_MAX_ITEMS"),
        ({"MEMORY_CONTEXT_USER_FACT_MAX_ITEMS": "9"}, "MEMORY_CONTEXT_USER_FACT_MAX_ITEMS"),
        ({"MEMORY_CONTEXT_USER_FACT_MAX_CHARACTERS": "199"}, "MEMORY_CONTEXT_USER_FACT_MAX_CHARACTERS"),
        ({"MEMORY_CONTEXT_USER_FACT_MAX_CHARACTERS": "8001"}, "MEMORY_CONTEXT_USER_FACT_MAX_CHARACTERS"),
        ({"MEMORY_CONTEXT_PREFERENCE_MAX_ITEMS": "0"}, "MEMORY_CONTEXT_PREFERENCE_MAX_ITEMS"),
        ({"MEMORY_CONTEXT_PREFERENCE_MAX_ITEMS": "9"}, "MEMORY_CONTEXT_PREFERENCE_MAX_ITEMS"),
        ({"MEMORY_CONTEXT_PREFERENCE_MAX_CHARACTERS": "199"}, "MEMORY_CONTEXT_PREFERENCE_MAX_CHARACTERS"),
        ({"MEMORY_CONTEXT_PREFERENCE_MAX_CHARACTERS": "8001"}, "MEMORY_CONTEXT_PREFERENCE_MAX_CHARACTERS"),
        ({"MEMORY_CONTEXT_LONG_TERM_GOAL_MAX_ITEMS": "0"}, "MEMORY_CONTEXT_LONG_TERM_GOAL_MAX_ITEMS"),
        ({"MEMORY_CONTEXT_LONG_TERM_GOAL_MAX_ITEMS": "9"}, "MEMORY_CONTEXT_LONG_TERM_GOAL_MAX_ITEMS"),
        ({"MEMORY_CONTEXT_LONG_TERM_GOAL_MAX_CHARACTERS": "199"}, "MEMORY_CONTEXT_LONG_TERM_GOAL_MAX_CHARACTERS"),
        ({"MEMORY_CONTEXT_LONG_TERM_GOAL_MAX_CHARACTERS": "8001"}, "MEMORY_CONTEXT_LONG_TERM_GOAL_MAX_CHARACTERS"),
        ({"MEMORY_CONTEXT_IMPORTANT_EVENT_MAX_ITEMS": "0"}, "MEMORY_CONTEXT_IMPORTANT_EVENT_MAX_ITEMS"),
        ({"MEMORY_CONTEXT_IMPORTANT_EVENT_MAX_ITEMS": "9"}, "MEMORY_CONTEXT_IMPORTANT_EVENT_MAX_ITEMS"),
        ({"MEMORY_CONTEXT_IMPORTANT_EVENT_MAX_CHARACTERS": "199"}, "MEMORY_CONTEXT_IMPORTANT_EVENT_MAX_CHARACTERS"),
        ({"MEMORY_CONTEXT_IMPORTANT_EVENT_MAX_CHARACTERS": "8001"}, "MEMORY_CONTEXT_IMPORTANT_EVENT_MAX_CHARACTERS"),
        ({"MEMORY_CONTEXT_RELATIONSHIP_EVENT_MAX_ITEMS": "0"}, "MEMORY_CONTEXT_RELATIONSHIP_EVENT_MAX_ITEMS"),
        ({"MEMORY_CONTEXT_RELATIONSHIP_EVENT_MAX_ITEMS": "9"}, "MEMORY_CONTEXT_RELATIONSHIP_EVENT_MAX_ITEMS"),
        ({"MEMORY_CONTEXT_RELATIONSHIP_EVENT_MAX_CHARACTERS": "199"}, "MEMORY_CONTEXT_RELATIONSHIP_EVENT_MAX_CHARACTERS"),
        ({"MEMORY_CONTEXT_RELATIONSHIP_EVENT_MAX_CHARACTERS": "8001"}, "MEMORY_CONTEXT_RELATIONSHIP_EVENT_MAX_CHARACTERS"),
        ({"MEMORY_CONTEXT_OTHER_MAX_ITEMS": "0"}, "MEMORY_CONTEXT_OTHER_MAX_ITEMS"),
        ({"MEMORY_CONTEXT_OTHER_MAX_ITEMS": "9"}, "MEMORY_CONTEXT_OTHER_MAX_ITEMS"),
        ({"MEMORY_CONTEXT_OTHER_MAX_CHARACTERS": "199"}, "MEMORY_CONTEXT_OTHER_MAX_CHARACTERS"),
        ({"MEMORY_CONTEXT_OTHER_MAX_CHARACTERS": "8001"}, "MEMORY_CONTEXT_OTHER_MAX_CHARACTERS"),
    ],
)
def test_gate_c1_context_budget_validation(
    monkeypatch: pytest.MonkeyPatch,
    environment: dict[str, str],
    message: str,
) -> None:
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=message):
        load_settings()


def test_gate_c1_context_budget_accepts_legal_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CHAT_CONTEXT_MAX_CHARACTERS", "18000")
    monkeypatch.setenv("CHAT_CURRENT_USER_MAX_CHARACTERS", "2000")
    monkeypatch.setenv("PERSONA_MAX_CHARACTERS", "16000")
    monkeypatch.setenv("CHAT_DYNAMIC_CONTEXT_MAX_CHARACTERS", "18000")
    monkeypatch.setenv("CHAT_EMOTION_CONTEXT_MAX_CHARACTERS", "1000")
    monkeypatch.setenv("RECENT_CONTEXT_MESSAGES", "50")
    monkeypatch.setenv("MEMORY_CONTEXT_LIMIT", "32")
    monkeypatch.setenv("MEMORY_RETRIEVAL_FALLBACK_LIMIT", "3")
    monkeypatch.setenv("MEMORY_CONTEXT_USER_FACT_MAX_ITEMS", "8")
    monkeypatch.setenv("MEMORY_CONTEXT_USER_FACT_MAX_CHARACTERS", "8000")

    settings = load_settings()

    assert settings.chat_context_max_characters == 18_000
    assert settings.persona_max_characters == 16_000
    assert settings.context_memory_type_budgets()[MemoryType.USER_FACT] == (
        ContextTypeBudget(8, 8_000, 1)
    )


def test_emotion_analysis_settings_default_to_disabled_deepseek() -> None:
    settings = load_settings()

    assert settings.emotion_analysis_enabled is False
    assert settings.emotion_analysis_provider == "deepseek"
    assert settings.emotion_analysis_model == DEFAULT_MODEL
    assert settings.emotion_analysis_max_tokens == 384
    assert settings.emotion_analysis_timeout_seconds == 15.0
    assert settings.emotion_analysis_max_retries == 0
    assert settings.emotion_analysis_recent_messages == 6
    assert settings.emotion_analysis_memory_limit == 3
    assert settings.emotion_analysis_max_item_characters == 2_000
    assert settings.emotion_analysis_max_total_characters == 8_000

    redacted = settings.redacted()
    assert redacted["emotion_analysis_enabled"] is False
    assert redacted["emotion_analysis_provider"] == "deepseek"
    assert redacted["emotion_analysis_model"] == DEFAULT_MODEL
    assert "emotion_analysis_api_key" not in redacted


def test_emotion_analysis_accepts_safe_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMOTION_ANALYSIS_ENABLED", "true")
    monkeypatch.setenv("EMOTION_ANALYSIS_PROVIDER", "anthropic")
    monkeypatch.setenv("EMOTION_ANALYSIS_MODEL", "claude-test")
    monkeypatch.setenv("EMOTION_ANALYSIS_MAX_TOKENS", "256")
    monkeypatch.setenv("EMOTION_ANALYSIS_TIMEOUT_SECONDS", "8")
    monkeypatch.setenv("EMOTION_ANALYSIS_MAX_RETRIES", "0")
    monkeypatch.setenv("EMOTION_ANALYSIS_RECENT_MESSAGES", "4")
    monkeypatch.setenv("EMOTION_ANALYSIS_MEMORY_LIMIT", "2")
    monkeypatch.setenv("EMOTION_ANALYSIS_MAX_ITEM_CHARACTERS", "900")
    monkeypatch.setenv("EMOTION_ANALYSIS_MAX_TOTAL_CHARACTERS", "3500")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "emotion-secret")

    settings = load_settings()

    assert settings.emotion_analysis_enabled is True
    assert settings.emotion_analysis_provider == "anthropic"
    assert settings.emotion_analysis_model == "claude-test"
    assert settings.emotion_analysis_max_tokens == 256
    assert settings.emotion_analysis_timeout_seconds == 8.0
    assert settings.emotion_analysis_max_retries == 0
    assert settings.emotion_analysis_recent_messages == 4
    assert settings.emotion_analysis_memory_limit == 2
    assert settings.emotion_analysis_max_item_characters == 900
    assert settings.emotion_analysis_max_total_characters == 3_500
    assert "emotion-secret" not in str(settings.redacted())


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("EMOTION_ANALYSIS_PROVIDER", "other", "EMOTION_ANALYSIS_PROVIDER"),
        ("EMOTION_ANALYSIS_MODEL", "   ", "EMOTION_ANALYSIS_MODEL"),
        ("EMOTION_ANALYSIS_MAX_TOKENS", "0", "must be greater than 0"),
        ("EMOTION_ANALYSIS_TIMEOUT_SECONDS", "0", "must be greater than 0"),
        ("EMOTION_ANALYSIS_MAX_RETRIES", "1", "must be 0"),
        ("EMOTION_ANALYSIS_RECENT_MESSAGES", "0", "must be greater than 0"),
        ("EMOTION_ANALYSIS_MEMORY_LIMIT", "0", "must be greater than 0"),
        ("EMOTION_ANALYSIS_MAX_ITEM_CHARACTERS", "0", "must be greater than 0"),
        ("EMOTION_ANALYSIS_MAX_TOTAL_CHARACTERS", "0", "must be greater than 0"),
        ("EMOTION_ANALYSIS_MAX_TOTAL_CHARACTERS", "1", "must be at least 2"),
    ],
)
def test_invalid_enabled_emotion_analysis_setting_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    message: str,
) -> None:
    monkeypatch.setenv("EMOTION_ANALYSIS_ENABLED", "true")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=message):
        load_settings()


def test_disabled_emotion_analysis_does_not_require_provider_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMOTION_ANALYSIS_ENABLED", "false")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    assert load_settings().emotion_analysis_enabled is False


def test_enabled_emotion_analysis_requires_selected_provider_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMOTION_ANALYSIS_ENABLED", "true")
    monkeypatch.setenv("EMOTION_ANALYSIS_PROVIDER", "deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        load_settings()


def test_emotion_analysis_total_budget_must_cover_current_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMOTION_ANALYSIS_ENABLED", "true")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("EMOTION_ANALYSIS_MAX_ITEM_CHARACTERS", "2000")
    monkeypatch.setenv("EMOTION_ANALYSIS_MAX_TOTAL_CHARACTERS", "1000")

    with pytest.raises(ValueError, match="EMOTION_ANALYSIS_MAX_TOTAL_CHARACTERS"):
        load_settings()


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


def test_gate_b_contract_and_conservative_defaults() -> None:
    settings = load_settings()

    assert Settings(memory_automation_mode="auto_active").memory_automation_mode == "auto_active"
    assert MEMORY_AUTO_ACTIVE_SCHEMA_VERSION == "memory-auto-active-schema-v1"
    assert MEMORY_WRITE_POLICY_VERSION == "memory-auto-write-policy-v1"
    assert MEMORY_ALLOWED_AUTO_TYPES_VERSION == "memory-auto-write-types-v1"
    assert MEMORY_ALLOWED_AUTO_TYPES == (
        MemoryType.USER_FACT,
        MemoryType.PREFERENCE,
        MemoryType.LONG_TERM_GOAL,
        MemoryType.IMPORTANT_EVENT,
        MemoryType.RELATIONSHIP_EVENT,
        MemoryType.OTHER,
    )
    assert settings.memory_automation_mode == "candidate_confirmation"
    assert settings.memory_commit_semantic_retries == 2
    assert str(settings.memory_source_reference_key_path).replace("\\", "/").endswith(
        "backend/data/memory-source-reference-v1.key"
    )


def test_memory_automation_accepts_auto_active_deployment_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEMORY_AUTOMATION_MODE", "auto_active")

    assert load_settings().memory_automation_mode == "auto_active"


@pytest.mark.parametrize("value", ["-1", "4", "not-an-integer"])
def test_memory_commit_semantic_retries_reject_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("MEMORY_COMMIT_SEMANTIC_RETRIES", value)

    with pytest.raises(ValueError, match="MEMORY_COMMIT_SEMANTIC_RETRIES"):
        load_settings()


def test_memory_write_grant_requires_exact_ordered_allowed_types() -> None:
    expected = [memory_type.value for memory_type in MEMORY_ALLOWED_AUTO_TYPES]
    request = UpdateMemoryWriteConsentRequest(
        action="grant",
        policy_version="memory-auto-write-policy-v1",
        retention_disclosure_version="memory-auto-write-retention-v1",
        allowed_memory_types_version="memory-auto-write-types-v1",
        allowed_memory_types=expected,
    )

    assert request.allowed_memory_types == expected

    invalid_lists = [[], expected[:-1], [*expected, expected[-1]], list(reversed(expected))]
    for invalid in invalid_lists:
        with pytest.raises(ValueError, match="allowed_memory_types"):
            UpdateMemoryWriteConsentRequest(
                action="grant",
                policy_version="memory-auto-write-policy-v1",
                retention_disclosure_version="memory-auto-write-retention-v1",
                allowed_memory_types_version="memory-auto-write-types-v1",
                allowed_memory_types=invalid,
            )


def test_gate_b_source_and_extractor_kinds_are_strict_enums() -> None:
    assert {value.value for value in MemoryVersionSourceKind} == {
        "legacy",
        "manual",
        "candidate",
        "automatic",
        "user_edit",
        "user_revert",
    }
    assert {value.value for value in MemoryEvidenceExtractorKind} == {
        "local",
        "fake",
        "remote",
        "manual",
        "candidate",
    }
    with pytest.raises(ValueError):
        MemoryVersionSourceKind("unknown")
    with pytest.raises(ValueError):
        MemoryEvidenceExtractorKind("unknown")


def test_gate_b_fixture_corpus_is_versioned_and_complete() -> None:
    fixture_path = (
        Path(__file__).parent / "fixtures" / "memory_gate_b" / "commit_cases.json"
    )
    document = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert document["fixture_schema_version"] == "memory-gate-b-fixtures-v1"
    assert {case["name"] for case in document["cases"]} == {
        "safe_create",
        "exact_support",
        "explicit_correction",
        "unique_conflict",
        "ambiguous_exact",
        "ambiguous_conflict",
        "sensitive_reject",
        "explicit_no_memory",
        "deletion_intent",
        "assistant_invented_fact",
        "exact_tombstone",
        "subject_tombstone",
        "stale_user_edit",
        "deleted_job",
        "dual_consent",
    }


def test_memory_automation_defaults_preserve_candidate_confirmation(monkeypatch):
    settings = load_settings()

    assert settings.memory_automation_mode == "candidate_confirmation"
    assert settings.memory_extractor_route == "none"
    assert settings.memory_extractor_provider == "anthropic"
    assert settings.memory_extractor_model == DEFAULT_MODEL
    assert settings.memory_extractor_max_tokens == 512
    assert settings.memory_extractor_timeout_seconds == 15.0
    assert settings.memory_extractor_max_retries == 0
    assert settings.memory_extractor_max_proposals == 3
    assert settings.memory_extractor_max_proposal_characters == 200
    assert settings.memory_extractor_max_total_characters == 600


def test_memory_automation_accepts_shadow_fake_overrides(monkeypatch):
    monkeypatch.setenv("MEMORY_AUTOMATION_MODE", "shadow_auto")
    monkeypatch.setenv("MEMORY_EXTRACTOR_ROUTE", "fake")
    monkeypatch.setenv("MEMORY_EXTRACTOR_PROVIDER", "anthropic")
    monkeypatch.setenv("MEMORY_EXTRACTOR_MODEL", "memory-fixture-v1")
    monkeypatch.setenv("MEMORY_EXTRACTOR_MAX_TOKENS", "256")
    monkeypatch.setenv("MEMORY_EXTRACTOR_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("MEMORY_EXTRACTOR_MAX_RETRIES", "0")
    monkeypatch.setenv("MEMORY_EXTRACTOR_MAX_PROPOSALS", "2")
    monkeypatch.setenv("MEMORY_EXTRACTOR_MAX_PROPOSAL_CHARACTERS", "120")
    monkeypatch.setenv("MEMORY_EXTRACTOR_MAX_TOTAL_CHARACTERS", "240")

    settings = load_settings()

    assert settings.memory_automation_mode == "shadow_auto"
    assert settings.memory_extractor_route == "fake"
    assert settings.memory_extractor_provider == "anthropic"
    assert settings.memory_extractor_model == "memory-fixture-v1"
    assert settings.memory_extractor_max_tokens == 256
    assert settings.memory_extractor_timeout_seconds == 5.0
    assert settings.memory_extractor_max_retries == 0
    assert settings.memory_extractor_max_proposals == 2
    assert settings.memory_extractor_max_proposal_characters == 120
    assert settings.memory_extractor_max_total_characters == 240


@pytest.mark.parametrize("provider", ["anthropic", "deepseek"])
def test_fake_memory_extractor_preserves_dormant_remote_provider(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    monkeypatch.setenv("MEMORY_EXTRACTOR_ROUTE", "fake")
    monkeypatch.setenv("MEMORY_EXTRACTOR_PROVIDER", provider)

    settings = load_settings()

    assert settings.memory_extractor_route == "fake"
    assert settings.memory_extractor_provider == provider


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MEMORY_AUTOMATION_MODE", "automatic"),
        ("MEMORY_EXTRACTOR_ROUTE", "cloud"),
        ("MEMORY_EXTRACTOR_PROVIDER", "fake"),
        ("MEMORY_EXTRACTOR_MAX_TOKENS", "63"),
        ("MEMORY_EXTRACTOR_MAX_TOKENS", "2049"),
        ("MEMORY_EXTRACTOR_TIMEOUT_SECONDS", "0.9"),
        ("MEMORY_EXTRACTOR_TIMEOUT_SECONDS", "60.1"),
        ("MEMORY_EXTRACTOR_MAX_PROPOSALS", "0"),
        ("MEMORY_EXTRACTOR_MAX_PROPOSALS", "11"),
        ("MEMORY_EXTRACTOR_MAX_PROPOSAL_CHARACTERS", "19"),
        ("MEMORY_EXTRACTOR_MAX_PROPOSAL_CHARACTERS", "501"),
        ("MEMORY_EXTRACTOR_MAX_TOTAL_CHARACTERS", "19"),
        ("MEMORY_EXTRACTOR_MAX_TOTAL_CHARACTERS", "2001"),
    ],
)
def test_memory_automation_rejects_invalid_setting(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        load_settings()


def test_memory_extractor_timeout_seconds_rejects_non_finite_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEMORY_EXTRACTOR_TIMEOUT_SECONDS", "nan")

    with pytest.raises(ValueError, match="MEMORY_EXTRACTOR_TIMEOUT_SECONDS"):
        load_settings()


def test_memory_extractor_total_characters_must_cover_one_proposal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEMORY_EXTRACTOR_MAX_PROPOSAL_CHARACTERS", "200")
    monkeypatch.setenv("MEMORY_EXTRACTOR_MAX_TOTAL_CHARACTERS", "199")

    with pytest.raises(
        ValueError,
        match="MEMORY_EXTRACTOR_MAX_TOTAL_CHARACTERS",
    ):
        load_settings()


def test_memory_extractor_retries_are_disabled_in_gate_a(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEMORY_EXTRACTOR_MAX_RETRIES", "1")

    with pytest.raises(
        ValueError,
        match="MEMORY_EXTRACTOR_MAX_RETRIES must be 0 in Gate A",
    ):
        load_settings()


def test_memory_automation_accepts_auto_active(monkeypatch):
    monkeypatch.setenv("MEMORY_AUTOMATION_MODE", "auto_active")

    assert load_settings().memory_automation_mode == "auto_active"


def test_memory_automation_redacted_settings_include_metadata_not_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEMORY_AUTOMATION_MODE", "shadow_auto")
    monkeypatch.setenv("MEMORY_EXTRACTOR_ROUTE", "remote")
    monkeypatch.setenv("MEMORY_EXTRACTOR_PROVIDER", "anthropic")
    monkeypatch.setenv("MEMORY_EXTRACTOR_MODEL", "memory-model-v1")
    monkeypatch.setenv("MEMORY_EXTRACTOR_MAX_TOKENS", "256")
    monkeypatch.setenv("MEMORY_EXTRACTOR_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("MEMORY_EXTRACTOR_MAX_RETRIES", "0")
    monkeypatch.setenv("MEMORY_EXTRACTOR_MAX_PROPOSALS", "2")
    monkeypatch.setenv("MEMORY_EXTRACTOR_MAX_PROPOSAL_CHARACTERS", "120")
    monkeypatch.setenv("MEMORY_EXTRACTOR_MAX_TOTAL_CHARACTERS", "240")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "memory-secret")

    redacted = load_settings().redacted()

    assert redacted["memory_automation_mode"] == "shadow_auto"
    assert redacted["memory_extractor_route"] == "remote"
    assert redacted["memory_extractor_provider"] == "anthropic"
    assert redacted["memory_extractor_model"] == "memory-model-v1"
    assert redacted["memory_extractor_max_tokens"] == 256
    assert redacted["memory_extractor_timeout_seconds"] == 5.0
    assert redacted["memory_extractor_max_retries"] == 0
    assert redacted["memory_extractor_max_proposals"] == 2
    assert redacted["memory_extractor_max_proposal_characters"] == 120
    assert redacted["memory_extractor_max_total_characters"] == 240
    assert "memory-secret" not in str(redacted)


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




def test_gate_c3_relationship_configuration_defaults_are_frozen() -> None:
    settings = load_settings()

    assert settings.relationship_context_max_characters == 600
    assert settings.relationship_reconcile_max_attempts == 3
    assert settings.relationship_recovery_stale_seconds == 300
    assert settings.redacted()["relationship_context_max_characters"] == 600
    assert settings.redacted()["relationship_reconcile_max_attempts"] == 3
    assert settings.redacted()["relationship_recovery_stale_seconds"] == 300


@pytest.mark.parametrize(
    ("name", "minimum", "maximum"),
    [
        ("RELATIONSHIP_CONTEXT_MAX_CHARACTERS", "128", "2000"),
        ("RELATIONSHIP_RECONCILE_MAX_ATTEMPTS", "1", "10"),
        ("RELATIONSHIP_RECOVERY_STALE_SECONDS", "30", "3600"),
    ],
)
def test_gate_c3_relationship_configuration_accepts_legal_edges(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    minimum: str,
    maximum: str,
) -> None:
    monkeypatch.setenv(name, minimum)
    minimum_settings = load_settings()
    monkeypatch.setenv(name, maximum)
    maximum_settings = load_settings()

    field = name.lower()
    assert getattr(minimum_settings, field) == int(minimum)
    assert getattr(maximum_settings, field) == int(maximum)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("RELATIONSHIP_CONTEXT_MAX_CHARACTERS", "127"),
        ("RELATIONSHIP_CONTEXT_MAX_CHARACTERS", "2001"),
        ("RELATIONSHIP_RECONCILE_MAX_ATTEMPTS", "0"),
        ("RELATIONSHIP_RECONCILE_MAX_ATTEMPTS", "11"),
        ("RELATIONSHIP_RECOVERY_STALE_SECONDS", "29"),
        ("RELATIONSHIP_RECOVERY_STALE_SECONDS", "3601"),
        ("RELATIONSHIP_RECOVERY_STALE_SECONDS", "not-an-integer"),
    ],
)
def test_gate_c3_relationship_configuration_rejects_out_of_range_values(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        load_settings()


def test_gate_c3_relationship_context_cap_cannot_widen_dynamic_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CHAT_DYNAMIC_CONTEXT_MAX_CHARACTERS", "512")
    monkeypatch.setenv("SUMMARY_INJECTION_MAX_FRAGMENT_CHARACTERS", "512")
    monkeypatch.setenv("SUMMARY_INJECTION_MAX_TOTAL_CHARACTERS", "512")
    monkeypatch.setenv("RELATIONSHIP_CONTEXT_MAX_CHARACTERS", "513")

    with pytest.raises(ValueError, match="RELATIONSHIP_CONTEXT_MAX_CHARACTERS"):
        load_settings()


def test_gate_c3_relationship_environment_contains_no_authority_or_remote_route() -> None:
    assert set(RELATIONSHIP_ENV_NAMES) == {
        "RELATIONSHIP_CONTEXT_MAX_CHARACTERS",
        "RELATIONSHIP_RECONCILE_MAX_ATTEMPTS",
        "RELATIONSHIP_RECOVERY_STALE_SECONDS",
    }
    assert not any(
        token in name
        for name in RELATIONSHIP_ENV_NAMES
        for token in ("CONSENT", "AUTHORITY", "PROVIDER", "MODEL", "API_KEY", "ASSET")
    )


def test_gate_c2_summary_configuration_defaults_are_frozen() -> None:
    settings = load_settings()

    assert settings.session_summary_enabled is True
    assert settings.session_summary_provider == "fake"
    assert settings.session_summary_trigger_turn_count == 6
    assert settings.session_summary_max_input_turns == 12
    assert settings.session_summary_max_input_messages == 24
    assert settings.session_summary_max_input_characters == 12_000
    assert settings.session_summary_llm_provider == "deepseek"
    assert settings.session_summary_llm_model == "deepseek-v4-flash"
    assert settings.session_summary_llm_max_tokens == 512
    assert settings.session_summary_llm_timeout_seconds == 15.0
    assert settings.session_summary_llm_max_retries == 0
    assert settings.session_summary_max_output_characters == 2_000
    assert settings.summary_injection_max_fragments == 2
    assert settings.summary_injection_max_fragment_characters == 1_000
    assert settings.summary_injection_max_total_characters == 1_600
    assert settings.summary_injection_min_lexical_relevance == 0.15
    assert settings.summary_rebuild_min_safe_turns == 1
    assert settings.summary_job_max_attempts == 3
    assert settings.summary_job_recovery_stale_seconds == 300

    redacted = settings.redacted()
    for field in (
        "session_summary_trigger_turn_count",
        "session_summary_max_input_turns",
        "session_summary_max_input_messages",
        "session_summary_max_input_characters",
        "session_summary_max_output_characters",
        "summary_injection_max_fragments",
        "summary_injection_max_fragment_characters",
        "summary_injection_max_total_characters",
        "summary_injection_min_lexical_relevance",
        "summary_rebuild_min_safe_turns",
        "summary_job_max_attempts",
        "summary_job_recovery_stale_seconds",
    ):
        assert redacted[field] == getattr(settings, field)


def test_gate_c2_summary_configuration_accepts_legal_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overrides = {
        "SESSION_SUMMARY_TRIGGER_TURN_COUNT": "50",
        "SESSION_SUMMARY_MAX_INPUT_TURNS": "50",
        "SESSION_SUMMARY_MAX_INPUT_MESSAGES": "100",
        "SESSION_SUMMARY_MAX_INPUT_CHARACTERS": "50000",
        "SESSION_SUMMARY_LLM_MAX_TOKENS": "2048",
        "SESSION_SUMMARY_LLM_TIMEOUT_SECONDS": "120",
        "SESSION_SUMMARY_LLM_MAX_RETRIES": "3",
        "SESSION_SUMMARY_MAX_OUTPUT_CHARACTERS": "8000",
        "SUMMARY_INJECTION_MAX_FRAGMENTS": "8",
        "SUMMARY_INJECTION_MAX_FRAGMENT_CHARACTERS": "4000",
        "SUMMARY_INJECTION_MAX_TOTAL_CHARACTERS": "8000",
        "SUMMARY_INJECTION_MIN_LEXICAL_RELEVANCE": "1.0",
        "SUMMARY_REBUILD_MIN_SAFE_TURNS": "50",
        "SUMMARY_JOB_MAX_ATTEMPTS": "10",
        "SUMMARY_JOB_RECOVERY_STALE_SECONDS": "3600",
    }
    for name, value in overrides.items():
        monkeypatch.setenv(name, value)

    settings = load_settings()

    assert settings.session_summary_trigger_turn_count == 50
    assert settings.session_summary_max_input_turns == 50
    assert settings.session_summary_max_input_messages == 100
    assert settings.summary_injection_max_total_characters == 8_000
    assert settings.summary_injection_min_lexical_relevance == 1.0


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SESSION_SUMMARY_TRIGGER_TURN_COUNT", "0"),
        ("SESSION_SUMMARY_TRIGGER_TURN_COUNT", "51"),
        ("SESSION_SUMMARY_MAX_INPUT_TURNS", "0"),
        ("SESSION_SUMMARY_MAX_INPUT_TURNS", "51"),
        ("SESSION_SUMMARY_MAX_INPUT_MESSAGES", "1"),
        ("SESSION_SUMMARY_MAX_INPUT_MESSAGES", "101"),
        ("SESSION_SUMMARY_MAX_INPUT_MESSAGES", "3"),
        ("SESSION_SUMMARY_MAX_INPUT_CHARACTERS", "511"),
        ("SESSION_SUMMARY_MAX_INPUT_CHARACTERS", "50001"),
        ("SESSION_SUMMARY_LLM_MAX_TOKENS", "63"),
        ("SESSION_SUMMARY_LLM_MAX_TOKENS", "2049"),
        ("SESSION_SUMMARY_LLM_TIMEOUT_SECONDS", "0.9"),
        ("SESSION_SUMMARY_LLM_TIMEOUT_SECONDS", "121"),
        ("SESSION_SUMMARY_LLM_TIMEOUT_SECONDS", "nan"),
        ("SESSION_SUMMARY_LLM_TIMEOUT_SECONDS", "inf"),
        ("SESSION_SUMMARY_LLM_MAX_RETRIES", "4"),
        ("SESSION_SUMMARY_MAX_OUTPUT_CHARACTERS", "127"),
        ("SESSION_SUMMARY_MAX_OUTPUT_CHARACTERS", "8001"),
        ("SUMMARY_INJECTION_MAX_FRAGMENTS", "0"),
        ("SUMMARY_INJECTION_MAX_FRAGMENTS", "9"),
        ("SUMMARY_INJECTION_MAX_FRAGMENT_CHARACTERS", "63"),
        ("SUMMARY_INJECTION_MAX_FRAGMENT_CHARACTERS", "4001"),
        ("SUMMARY_INJECTION_MAX_TOTAL_CHARACTERS", "63"),
        ("SUMMARY_INJECTION_MAX_TOTAL_CHARACTERS", "8001"),
        ("SUMMARY_INJECTION_MIN_LEXICAL_RELEVANCE", "0"),
        ("SUMMARY_INJECTION_MIN_LEXICAL_RELEVANCE", "1.01"),
        ("SUMMARY_INJECTION_MIN_LEXICAL_RELEVANCE", "nan"),
        ("SUMMARY_INJECTION_MIN_LEXICAL_RELEVANCE", "inf"),
        ("SUMMARY_REBUILD_MIN_SAFE_TURNS", "0"),
        ("SUMMARY_REBUILD_MIN_SAFE_TURNS", "51"),
        ("SUMMARY_JOB_MAX_ATTEMPTS", "0"),
        ("SUMMARY_JOB_MAX_ATTEMPTS", "11"),
        ("SUMMARY_JOB_RECOVERY_STALE_SECONDS", "29"),
        ("SUMMARY_JOB_RECOVERY_STALE_SECONDS", "3601"),
    ],
)
def test_gate_c2_summary_configuration_rejects_out_of_range_values(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        load_settings()


def test_gate_c2_summary_configuration_rejects_cross_field_widening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = (
        (
            {
                "SESSION_SUMMARY_TRIGGER_TURN_COUNT": "7",
                "SESSION_SUMMARY_MAX_INPUT_TURNS": "6",
            },
            "SESSION_SUMMARY_TRIGGER_TURN_COUNT",
        ),
        ({"SESSION_SUMMARY_MAX_INPUT_MESSAGES": "3"}, "must be even"),
        (
            {
                "SUMMARY_INJECTION_MAX_FRAGMENT_CHARACTERS": "1001",
                "SUMMARY_INJECTION_MAX_TOTAL_CHARACTERS": "1000",
            },
            "SUMMARY_INJECTION_MAX_FRAGMENT_CHARACTERS",
        ),
        (
            {
                "CHAT_DYNAMIC_CONTEXT_MAX_CHARACTERS": "512",
                "SUMMARY_INJECTION_MAX_TOTAL_CHARACTERS": "513",
            },
            "SUMMARY_INJECTION_MAX_TOTAL_CHARACTERS",
        ),
    )
    for environment, expected in cases:
        for name in SESSION_SUMMARY_ENV_NAMES:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv("CHAT_DYNAMIC_CONTEXT_MAX_CHARACTERS", raising=False)
        for name, value in environment.items():
            monkeypatch.setenv(name, value)
        with pytest.raises(ValueError, match=expected):
            load_settings()


def test_gate_c2_summary_environment_never_grants_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SESSION_SUMMARY_PROVIDER", "llm")
    monkeypatch.setenv("SESSION_SUMMARY_ENABLED", "true")

    settings = load_settings()

    assert settings.session_summary_provider == "llm"
    assert not hasattr(settings, "summary_processing_consent")
    assert not hasattr(settings, "summary_injection_consent")


def test_session_summary_settings_default_to_offline_fake() -> None:
    settings = load_settings()

    assert settings.session_summary_enabled is True
    assert settings.session_summary_provider == "fake"
    assert settings.session_summary_trigger_message_count == 12
    assert settings.session_summary_max_input_messages == 24
    assert settings.session_summary_llm_provider == "deepseek"
    assert settings.session_summary_llm_model == "deepseek-v4-flash"
    assert settings.session_summary_llm_max_tokens == 512
    assert settings.session_summary_llm_timeout_seconds == 15.0
    assert settings.session_summary_llm_max_retries == 0

    redacted = settings.redacted()
    assert redacted["session_summary_enabled"] is True
    assert redacted["session_summary_provider"] == "fake"
    assert redacted["session_summary_trigger_message_count"] == 12
    assert redacted["session_summary_max_input_messages"] == 24
    assert redacted["session_summary_llm_provider"] == "deepseek"
    assert redacted["session_summary_llm_model"] == "deepseek-v4-flash"
    assert redacted["session_summary_llm_max_tokens"] == 512
    assert redacted["session_summary_llm_timeout_seconds"] == 15.0
    assert redacted["session_summary_llm_max_retries"] == 0


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("SESSION_SUMMARY_PROVIDER", "other", "SESSION_SUMMARY_PROVIDER"),
        ("SESSION_SUMMARY_TRIGGER_MESSAGE_COUNT", "0", "must be greater than 0"),
        ("SESSION_SUMMARY_MAX_INPUT_MESSAGES", "0", "SESSION_SUMMARY_MAX_INPUT_MESSAGES"),
        ("SESSION_SUMMARY_LLM_MAX_TOKENS", "0", "SESSION_SUMMARY_LLM_MAX_TOKENS"),
        ("SESSION_SUMMARY_LLM_TIMEOUT_SECONDS", "0", "must be greater than 0"),
        ("SESSION_SUMMARY_LLM_MAX_RETRIES", "-1", "greater than or equal to 0"),
    ],
)
def test_invalid_session_summary_setting_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    message: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=message):
        load_settings()


def test_fake_summary_does_not_require_real_provider_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SESSION_SUMMARY_PROVIDER", "fake")
    monkeypatch.setenv("SESSION_SUMMARY_LLM_PROVIDER", "deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    assert load_settings().session_summary_provider == "fake"


def test_llm_summary_fence_does_not_require_provider_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SESSION_SUMMARY_PROVIDER", "llm")
    monkeypatch.setenv("SESSION_SUMMARY_LLM_PROVIDER", "deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    assert load_settings().session_summary_provider == "llm"


def test_llm_summary_rejects_unknown_selected_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SESSION_SUMMARY_PROVIDER", "llm")
    monkeypatch.setenv("SESSION_SUMMARY_LLM_PROVIDER", "other")

    with pytest.raises(
        ValueError,
        match="SESSION_SUMMARY_LLM_PROVIDER must be one of: anthropic, deepseek",
    ):
        load_settings()


def test_fake_summary_ignores_empty_llm_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SESSION_SUMMARY_PROVIDER", "fake")
    monkeypatch.setenv("SESSION_SUMMARY_LLM_MODEL", "   ")

    settings = load_settings()

    assert settings.session_summary_provider == "fake"


def test_llm_summary_model_must_not_be_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SESSION_SUMMARY_PROVIDER", "llm")
    monkeypatch.setenv("SESSION_SUMMARY_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("SESSION_SUMMARY_LLM_MODEL", "   ")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    with pytest.raises(ValueError, match="SESSION_SUMMARY_LLM_MODEL must not be empty"):
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
