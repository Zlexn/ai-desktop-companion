import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.errors import ProviderError
from app.domain.models import MemoryStatus, MemoryType
from app.providers.base import LLMMessage, LLMOptions, LLMResponse
from app.repositories.memories import MemoryRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.services.memory_candidate_service import MemoryCandidateService


class StubLLMProvider:
    def __init__(self, text: str | None = None, error: Exception | None = None) -> None:
        self.text = text or "{}"
        self.error = error
        self.calls: list[tuple[list[LLMMessage], LLMOptions]] = []

    async def generate(self, messages: list[LLMMessage], options: LLMOptions) -> LLMResponse:
        self.calls.append((messages, options))
        if self.error is not None:
            raise self.error
        return LLMResponse(text=self.text, provider="stub", model=options.model)


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'memory-candidates.db'}"


@pytest.mark.asyncio
async def test_heuristic_extracts_explicit_like_statement(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        service = MemoryCandidateService(memories, Settings(memory_candidates_enabled=True))

        created = await service.create_candidates_from_user_text(
            session_id=None,
            user_text="我喜欢红茶。",
        )

        assert len(created) == 1
        assert created[0].content == "用户喜欢红茶。"
        assert created[0].memory_type == MemoryType.PREFERENCE
        assert created[0].status == MemoryStatus.PENDING
        assert created[0].importance == 3
        assert created[0].confidence == 0.7
        assert created[0].metadata["candidate_reason"] == "explicit_like_statement"
        assert created[0].metadata["extraction_provider"] == "heuristic"


@pytest.mark.asyncio
async def test_heuristic_extracts_goal_statement(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        service = MemoryCandidateService(memories, Settings(memory_candidates_enabled=True))

        created = await service.create_candidates_from_user_text(
            session_id=None,
            user_text="我的目标是本地部署一个能实时交流的桌宠。",
        )

        assert len(created) == 1
        assert created[0].content == "用户的目标是本地部署一个能实时交流的桌宠。"
        assert created[0].memory_type == MemoryType.LONG_TERM_GOAL


@pytest.mark.asyncio
async def test_heuristic_ignores_vague_or_disabled_candidates(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        disabled = MemoryCandidateService(memories, Settings(memory_candidates_enabled=False))
        enabled = MemoryCandidateService(memories, Settings(memory_candidates_enabled=True))

        assert await disabled.create_candidates_from_user_text(session_id=None, user_text="我喜欢红茶。") == []
        assert await enabled.create_candidates_from_user_text(session_id=None, user_text="你好") == []
        assert await enabled.create_candidates_from_user_text(session_id=None, user_text="我现在有点开心") == []


@pytest.mark.asyncio
async def test_heuristic_does_not_duplicate_existing_candidate(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        service = MemoryCandidateService(memories, Settings(memory_candidates_enabled=True))

        first = await service.create_candidates_from_user_text(session_id=None, user_text="我喜欢红茶。")
        second = await service.create_candidates_from_user_text(session_id=None, user_text="我喜欢红茶。")

        assert len(first) == 1
        assert second == []
        assert len(memories.list(status=MemoryStatus.PENDING)) == 1


@pytest.mark.asyncio
async def test_llm_provider_creates_pending_candidate_with_safe_metadata(database_url: str) -> None:
    payload = {
        "candidates": [
            {
                "content": "用户喜欢红茶。",
                "memory_type": "preference",
                "confidence": 0.92,
                "importance": 4,
                "source_quote": "我喜欢红茶",
                "reason": "explicit_preference_statement",
                "should_create_candidate": True,
            }
        ]
    }
    provider = StubLLMProvider(json.dumps(payload, ensure_ascii=False))
    settings = Settings(memory_candidates_enabled=True, memory_candidate_provider="llm")

    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        session = SessionRepository(connection).create("LLM 候选")
        service = MemoryCandidateService(memories, settings, llm_provider=provider)

        created = await service.create_candidates_from_user_text(
            session_id=session.id,
            user_text="我喜欢红茶，也喜欢安静的晚上。",
        )

        assert len(created) == 1
        memory = created[0]
        assert memory.content == "用户喜欢红茶。"
        assert memory.memory_type == MemoryType.PREFERENCE
        assert memory.status == MemoryStatus.PENDING
        assert memory.importance == 4
        assert memory.confidence == 0.92
        assert memory.source_session_id == session.id
        assert memory.metadata["candidate_reason"] == "explicit_preference_statement"
        assert memory.metadata["extraction_provider"] == "llm"
        assert memory.metadata["extraction_schema"] == "memory_extraction_schema_v1"
        assert memory.metadata["source_quote"] == "我喜欢红茶"
        assert memory.metadata["raw_confidence"] == 0.92
        assert "candidates" not in memory.metadata
        assert len(provider.calls) == 1
        messages, options = provider.calls[0]
        assert options.model == settings.llm_model
        assert options.max_tokens == settings.memory_candidate_llm_max_tokens
        assert options.timeout_seconds == settings.memory_candidate_llm_timeout_seconds
        assert messages[-1].content == "我喜欢红茶，也喜欢安静的晚上。"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "candidate",
    [
        {
            "content": "用户喜欢红茶。",
            "memory_type": "preference",
            "confidence": 0.95,
            "importance": 3,
            "source_quote": "我喜欢红茶",
            "reason": "explicit_preference_statement",
            "should_create_candidate": False,
        },
        {
            "content": "用户喜欢红茶。",
            "memory_type": "preference",
            "confidence": 0.2,
            "importance": 3,
            "source_quote": "我喜欢红茶",
            "reason": "low_confidence_statement",
            "should_create_candidate": True,
        },
        {
            "content": "用户喜欢红茶。",
            "memory_type": "emotion_state",
            "confidence": 0.95,
            "importance": 3,
            "source_quote": "我喜欢红茶",
            "reason": "invalid_memory_type",
            "should_create_candidate": True,
        },
        {
            "content": "用户喜欢红茶。",
            "memory_type": "preference",
            "confidence": 0.95,
            "importance": 6,
            "source_quote": "我喜欢红茶",
            "reason": "invalid_importance",
            "should_create_candidate": True,
        },
        {
            "content": "",
            "memory_type": "preference",
            "confidence": 0.95,
            "importance": 3,
            "source_quote": "我喜欢红茶",
            "reason": "empty_content",
            "should_create_candidate": True,
        },
        {
            "content": "用户喜欢咖啡。",
            "memory_type": "preference",
            "confidence": 0.95,
            "importance": 3,
            "source_quote": "我喜欢咖啡",
            "reason": "invented_quote",
            "should_create_candidate": True,
        },
        {
            "content": "用户的 API Key 是 sk-test-secret。",
            "memory_type": "user_fact",
            "confidence": 0.95,
            "importance": 5,
            "source_quote": "我的 API Key 是 sk-test-secret",
            "reason": "secret_statement",
            "should_create_candidate": True,
        },
        {
            "content": "助手喜欢红茶。",
            "memory_type": "preference",
            "confidence": 0.95,
            "importance": 3,
            "source_quote": "我喜欢红茶",
            "reason": "assistant_subject",
            "should_create_candidate": True,
        },
    ],
)
async def test_llm_provider_filters_invalid_candidates(database_url: str, candidate: dict[str, object]) -> None:
    provider = StubLLMProvider(json.dumps({"candidates": [candidate]}, ensure_ascii=False))
    settings = Settings(memory_candidates_enabled=True, memory_candidate_provider="llm")

    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        service = MemoryCandidateService(memories, settings, llm_provider=provider)

        created = await service.create_candidates_from_user_text(
            session_id=None,
            user_text="我喜欢红茶。我的 API Key 是 sk-test-secret。",
        )

        assert created == []
        assert memories.list(status=MemoryStatus.PENDING) == []


@pytest.mark.asyncio
async def test_llm_provider_returns_empty_on_invalid_json(database_url: str) -> None:
    provider = StubLLMProvider("not json")
    settings = Settings(memory_candidates_enabled=True, memory_candidate_provider="llm")

    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        service = MemoryCandidateService(memories, settings, llm_provider=provider)

        created = await service.create_candidates_from_user_text(session_id=None, user_text="我喜欢红茶。")

        assert created == []
        assert memories.list(status=MemoryStatus.PENDING) == []


@pytest.mark.asyncio
async def test_llm_provider_returns_empty_on_provider_error(database_url: str) -> None:
    provider = StubLLMProvider(error=ProviderError("provider unavailable"))
    settings = Settings(memory_candidates_enabled=True, memory_candidate_provider="llm")

    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        service = MemoryCandidateService(memories, settings, llm_provider=provider)

        created = await service.create_candidates_from_user_text(session_id=None, user_text="我喜欢红茶。")

        assert created == []
        assert memories.list(status=MemoryStatus.PENDING) == []
