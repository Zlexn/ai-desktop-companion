from pathlib import Path

from app.domain.models import ChatRole, MemorySource, MemoryType
from app.providers.base import LLMMessage
from app.repositories.memories import MemoryRepository
from app.repositories.memory_embeddings import MemoryEmbeddingRepository
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.services.context_builder import ContextBuilder
from app.services.memory_embedding_service import FakeMemoryEmbeddingProvider, MemoryEmbeddingService, MemoryEmbeddingUnavailableError


def test_context_builder_returns_recent_messages_in_chronological_order(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'context-builder.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("上下文构建")
        messages.add(session.id, ChatRole.USER, "第一条")
        messages.add(session.id, ChatRole.ASSISTANT, "第二条")
        messages.add(session.id, ChatRole.USER, "第三条")

        context = ContextBuilder(messages, 2).build_recent_context(session.id)

        assert context == [
            LLMMessage(role=ChatRole.ASSISTANT, content="第二条"),
            LLMMessage(role=ChatRole.USER, content="第三条"),
        ]


def test_memory_context_is_caveated_and_separate(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'memory-context.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        session = sessions.create("记忆上下文")
        messages.add(session.id, ChatRole.USER, "你好")
        memories.create(
            content="用户偏好中文回复。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )
        builder = ContextBuilder(messages, 12, memories=memories, memory_context_enabled=True, memory_context_limit=8)

        context = builder.build_context(session.id)

        assert context[0].role == ChatRole.SYSTEM
        assert "长期记忆记录" in context[0].content
        assert "不得描述为绝对事实" in context[0].content
        assert "用户偏好中文回复。" in context[0].content
        assert context[1].role == ChatRole.USER
        assert context[1].content == "你好"


def test_memory_context_excludes_pending_and_dismissed_candidates(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'memory-context-candidates.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        session = sessions.create("候选上下文")
        active, _ = memories.create(
            content="用户偏好中文回复。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )
        pending, _ = memories.create_candidate(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=session.id,
            importance=3,
            confidence=0.7,
            metadata={},
        )
        assert pending is not None
        dismissed, _ = memories.create_candidate(
            content="用户不喜欢咖啡。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=session.id,
            importance=3,
            confidence=0.7,
            metadata={},
        )
        assert dismissed is not None
        memories.dismiss_candidate(dismissed.id)

        builder = ContextBuilder(messages, 12, memories=memories, memory_context_enabled=True, memory_context_limit=8)
        context = builder.build_memory_context()

        assert len(context) == 1
        assert active.content in context[0].content
        assert "用户喜欢红茶。" not in context[0].content
        assert "用户不喜欢咖啡。" not in context[0].content


def test_memory_context_uses_query_relevance(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'memory-context-relevance.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        session = sessions.create("相关记忆")
        messages.add(session.id, ChatRole.USER, "我喜欢什么饮料？")
        memories.create(
            content="用户正在构建本地 AI 桌宠。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=5,
            confidence=1.0,
            metadata={},
        )
        memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=2,
            confidence=0.8,
            metadata={},
        )
        builder = ContextBuilder(
            messages,
            12,
            memories=memories,
            memory_context_enabled=True,
            memory_context_limit=8,
            memory_retrieval_mode="relevance",
            memory_retrieval_fallback_limit=2,
        )

        context = builder.build_memory_context(query="我喜欢什么饮料？")

        assert len(context) == 1
        assert "长期记忆记录" in context[0].content
        assert "不得描述为绝对事实" in context[0].content
        assert "用户喜欢红茶。" in context[0].content
        assert "用户正在构建本地 AI 桌宠。" not in context[0].content


def test_memory_context_recent_mode_keeps_existing_ordering(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'memory-context-recent.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        sessions.create("最近记忆")
        high, _ = memories.create(
            content="用户正在构建本地 AI 桌宠。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=5,
            confidence=1.0,
            metadata={},
        )
        low, _ = memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=2,
            confidence=0.8,
            metadata={},
        )
        builder = ContextBuilder(
            messages,
            12,
            memories=memories,
            memory_context_enabled=True,
            memory_context_limit=8,
            memory_retrieval_mode="recent",
            memory_retrieval_fallback_limit=2,
        )

        context = builder.build_memory_context(query="我喜欢什么饮料？")

        assert high.content in context[0].content
        assert low.content in context[0].content


def test_memory_context_can_be_disabled(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'memory-context-disabled.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        session = sessions.create("禁用记忆")
        messages.add(session.id, ChatRole.USER, "你好")
        memories.create(
            content="用户偏好中文回复。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )
        builder = ContextBuilder(messages, 12, memories=memories, memory_context_enabled=False, memory_context_limit=8)

        context = builder.build_context(session.id)

        assert [message.content for message in context] == ["你好"]


def test_memory_context_embedding_mode_uses_embedding_service(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'memory-context-embedding.db'}"
    with managed_connection(database_url) as connection:
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        embeddings = MemoryEmbeddingRepository(connection)
        service = MemoryEmbeddingService(embeddings, FakeMemoryEmbeddingProvider())
        tea, _ = memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=2,
            confidence=0.8,
            metadata={},
        )
        project, _ = memories.create(
            content="用户正在构建本地 AI 桌宠。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=5,
            confidence=1.0,
            metadata={},
        )
        service.ensure_embedding(tea)
        service.ensure_embedding(project)
        builder = ContextBuilder(
            messages,
            12,
            memories=memories,
            memory_context_enabled=True,
            memory_context_limit=8,
            memory_retrieval_mode="embedding",
            memory_retrieval_fallback_limit=2,
            memory_embedding_service=service,
            memory_embedding_min_score=0.1,
        )

        context = builder.build_memory_context(query="我喜欢什么饮料？")

        assert len(context) == 1
        assert "用户喜欢红茶。" in context[0].content
        assert "用户正在构建本地 AI 桌宠。" not in context[0].content
        assert "不得描述为绝对事实" in context[0].content


class FailingMemoryEmbeddingService:
    def search_relevant(self, query: str, limit: int, min_score: float):
        raise MemoryEmbeddingUnavailableError("embedding unavailable")


def test_memory_context_embedding_mode_falls_back_to_relevance(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'memory-context-embedding-fallback.db'}"
    with managed_connection(database_url) as connection:
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        memories.create(
            content="用户正在构建本地 AI 桌宠。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=5,
            confidence=1.0,
            metadata={},
        )
        memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=2,
            confidence=0.8,
            metadata={},
        )
        builder = ContextBuilder(
            messages,
            12,
            memories=memories,
            memory_context_enabled=True,
            memory_context_limit=8,
            memory_retrieval_mode="embedding",
            memory_retrieval_fallback_limit=2,
            memory_embedding_service=FailingMemoryEmbeddingService(),
            memory_embedding_min_score=0.1,
        )

        context = builder.build_memory_context(query="我喜欢什么饮料？")

        assert "用户喜欢红茶。" in context[0].content
        assert "用户正在构建本地 AI 桌宠。" not in context[0].content
