from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    for name in (
        "CHAT_CONTEXT_MAX_CHARACTERS",
        "SESSION_SUMMARY_ENABLED",
        "SESSION_SUMMARY_PROVIDER",
        "SESSION_SUMMARY_TRIGGER_MESSAGE_COUNT",
        "SESSION_SUMMARY_MAX_INPUT_MESSAGES",
        "SESSION_SUMMARY_LLM_PROVIDER",
        "SESSION_SUMMARY_LLM_MODEL",
        "SESSION_SUMMARY_LLM_MAX_TOKENS",
        "SESSION_SUMMARY_LLM_TIMEOUT_SECONDS",
        "SESSION_SUMMARY_LLM_MAX_RETRIES",
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
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()
