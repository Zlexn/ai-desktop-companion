from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain.models import ChatRole, EmotionState, EmotionVector, MemorySource, MemoryType
from app.domain.session_summary import (
    SummaryInjectionAuthoritySnapshot,
    SummarySourceFragment,
)
from app.providers.base import LLMMessage
from app.repositories.context_sources import ContextSourceRepository
from app.repositories.memories import MemoryRepository
from app.repositories.memory_embeddings import MemoryEmbeddingRepository
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.services.context_builder import ContextBuilder
from app.services.memory_embedding_service import FakeMemoryEmbeddingProvider, MemoryEmbeddingService, MemoryEmbeddingUnavailableError


class RecordingEmotionFormatter:
    def __init__(self) -> None:
        self.seen_state: EmotionState | None = None

    def format(self, state: EmotionState) -> str:
        self.seen_state = state
        return "emotion context"


def test_context_snapshot_excludes_current_before_limit(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'snapshot-exclusion.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("snapshot")
        first = messages.add(session.id, ChatRole.USER, "first")
        second = messages.add(session.id, ChatRole.ASSISTANT, "second")
        current = messages.add(session.id, ChatRole.USER, "current")

        snapshot = ContextSourceRepository(messages, None).snapshot(
            session_id=session.id,
            current_user_message_id=current.id,
            query="current",
            recent_limit=2,
            memory_limit=0,
        )

        assert [item.id for item in snapshot.recent_messages] == [first.id, second.id]
        assert current.id not in [item.id for item in snapshot.recent_messages]


def test_context_sources_include_exact_current_version_provenance(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'snapshot-version.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        session = sessions.create("snapshot")
        current = messages.add(session.id, ChatRole.USER, "红茶")
        memory, _ = memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=0.9,
            metadata={},
        )
        state = connection.execute(
            "SELECT current_version_id FROM memory_record_states WHERE memory_id=?",
            (memory.id,),
        ).fetchone()

        snapshot = ContextSourceRepository(messages, memories).snapshot(
            session_id=session.id,
            current_user_message_id=current.id,
            query="红茶",
            recent_limit=12,
            memory_limit=8,
        )

        assert len(snapshot.memories) == 1
        source = snapshot.memories[0]
        assert source.memory_id == memory.id
        assert source.current_version_id == state["current_version_id"]
        assert source.legacy_compat is False
        assert source.source_kind.value == "manual"


def test_context_sources_legacy_rows_have_no_fabricated_version_id(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'snapshot-legacy.db'}"
    with managed_connection(database_url) as connection:
        connection.execute(
            """
            INSERT INTO memories (
                id, content, memory_type, source, source_session_id,
                importance, confidence, status, metadata_json, created_at, updated_at
            ) VALUES ('legacy', 'legacy memory', 'other', 'manual', NULL,
                      3, 1.0, 'active', '{}', ?, ?)
            """,
            (datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat()),
        )
        connection.commit()

        sources = MemoryRepository(connection).list_context_sources(None, 8)

        assert sources[0].memory_id == "legacy"
        assert sources[0].current_version_id is None
        assert sources[0].legacy_compat is True


def test_context_sources_exclude_deleted_and_open_conflict_records(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'snapshot-ineligible.db'}"
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        left, _ = memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=0.9,
            metadata={},
        )
        right, _ = memories.create(
            content="用户不喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=0.9,
            metadata={},
        )
        conflict_left, conflict_right = sorted((left.id, right.id))
        connection.execute(
            """
            INSERT INTO memory_conflicts (
                conflict_id, left_memory_id, right_memory_id, status,
                resolution_kind, resolved_memory_id, created_at, resolved_at
            ) VALUES ('conflict', ?, ?, 'open', NULL, NULL, ?, NULL)
            """,
            (conflict_left, conflict_right, datetime.now(UTC).isoformat()),
        )
        connection.commit()

        assert memories.list_context_sources("红茶", 8) == []


def test_recent_message_failure_is_not_hidden_by_optional_summary_handling() -> None:
    class FailingMessages:
        def list_recent_excluding(self, *_args, **_kwargs):
            raise RuntimeError("recent messages unavailable")

    repository = ContextSourceRepository(
        FailingMessages(),  # type: ignore[arg-type]
        None,
    )

    with pytest.raises(RuntimeError, match="recent messages unavailable"):
        repository.snapshot(
            session_id="session",
            current_user_message_id="current",
            query="query",
            recent_limit=12,
            memory_limit=0,
        )


def test_summary_lookup_failure_is_isolated_after_recent_snapshot(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'summary-lookup-failure.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("summary")
        messages = MessageRepository(connection)
        previous = messages.add(session.id, ChatRole.USER, "previous")
        current = messages.add(session.id, ChatRole.USER, "current")

        class FailingSelection:
            def select(self, **kwargs):
                raise RuntimeError("summary lookup failed")

        snapshot = ContextSourceRepository(
            messages,
            None,
            summary_selection=FailingSelection(),  # type: ignore[arg-type]
            summary_authority=SummaryInjectionAuthoritySnapshot(
                generation=1,
                policy_fingerprint="policy",
                disclosure_version="summary-injection-disclosure-v1",
                disclosed_fields=("summary_text",),
                max_fragment_count=1,
                max_fragment_characters=100,
                max_total_characters=100,
            ),
        ).snapshot(
            session_id=session.id,
            current_user_message_id=current.id,
            query="current",
            recent_limit=12,
            memory_limit=0,
        )

        assert [item.id for item in snapshot.recent_messages] == [previous.id]
        assert snapshot.summaries == ()
        assert snapshot.summary_authority is None


def test_context_snapshot_exposes_selected_summary_and_authority(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'summary-source-snapshot.db'}"
    authority = SummaryInjectionAuthoritySnapshot(
        generation=2,
        policy_fingerprint="policy",
        disclosure_version="summary-injection-disclosure-v1",
        disclosed_fields=("summary_text",),
        max_fragment_count=1,
        max_fragment_characters=100,
        max_total_characters=100,
    )
    fragment = SummarySourceFragment(
        summary_id="summary",
        source_session_id="source-session",
        source_kind="generated",
        created_at=datetime.now(UTC),
        summary_text="低信任摘要",
        observed_barrier_generation=0,
        source_set_hash="source-set-hash",
        suppression_generation=0,
        suppression_state=None,
        summarizer_schema_version="session-summary-v2",
        injection_schema_version="summary-injection-v1",
        source_turn_ids=("turn",),
        source_message_ids=("user", "assistant"),
    )

    class RecordingSelection:
        def __init__(self) -> None:
            self.recent_ids: tuple[str, ...] = ()

        def select(self, **kwargs):
            self.recent_ids = kwargs["selected_recent_message_ids"]
            return SimpleNamespace(
                fragments=(fragment,),
                authority=authority,
            )

    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("summary")
        messages = MessageRepository(connection)
        previous = messages.add(session.id, ChatRole.USER, "previous")
        current = messages.add(session.id, ChatRole.USER, "current")
        selection = RecordingSelection()

        snapshot = ContextSourceRepository(
            messages,
            None,
            summary_selection=selection,  # type: ignore[arg-type]
            summary_authority=authority,
        ).snapshot(
            session_id=session.id,
            current_user_message_id=current.id,
            query="current",
            recent_limit=12,
            memory_limit=0,
        )

        assert selection.recent_ids == (previous.id,)
        assert snapshot.summaries == (fragment,)
        assert snapshot.summary_authority == authority


def test_context_builder_exposes_typed_snapshot_compatibility(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'builder-snapshot.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("snapshot")
        previous = messages.add(session.id, ChatRole.USER, "same")
        current = messages.add(session.id, ChatRole.USER, "same")
        builder = ContextBuilder(messages, 12)

        snapshot = builder.snapshot_sources(
            session_id=session.id,
            current_user_message_id=current.id,
            query="same",
        )

        assert [item.id for item in snapshot.recent_messages] == [previous.id]


def test_emotion_context_formats_only_caller_supplied_snapshot(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'caller-snapshot.db'}"
    with managed_connection(database_url) as connection:
        snapshot = EmotionState(
            "default-companion",
            True,
            EmotionVector(0.5, 0.4, 0.2, 0.55, 0.1, 0.6),
            7,
            datetime.now(UTC),
        )
        formatter = RecordingEmotionFormatter()
        builder = ContextBuilder(
            MessageRepository(connection),
            12,
            emotion_context_formatter=formatter,
        )

        context = builder.build_emotion_context(snapshot)

        assert formatter.seen_state is snapshot
        assert context == [LLMMessage(role=ChatRole.SYSTEM, content="emotion context")]


def test_build_context_preserves_emotion_memory_history_order(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'ordered-context.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        session = sessions.create("ordered")
        messages.add(session.id, ChatRole.USER, "history")
        memories.create(
            content="memory",
            memory_type=MemoryType.OTHER,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )
        snapshot = EmotionState(
            "default-companion",
            True,
            EmotionVector(0.5, 0.4, 0.2, 0.55, 0.1, 0.6),
            7,
            datetime.now(UTC),
        )
        builder = ContextBuilder(
            messages,
            12,
            memories=memories,
            emotion_context_formatter=RecordingEmotionFormatter(),
        )

        context = builder.build_context(
            session.id,
            emotion_context=builder.build_emotion_context(snapshot),
        )

        assert [message.role for message in context] == [
            ChatRole.SYSTEM,
            ChatRole.SYSTEM,
            ChatRole.USER,
        ]
        assert context[0].content == "emotion context"
        assert "memory" in context[1].content
        assert context[2].content == "history"



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
