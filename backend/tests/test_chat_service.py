import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import ProviderInvalidResponseError
from app.domain.models import (
    EMOTION_BASELINE,
    ChatRole,
    EmotionState,
    MemorySource,
    MemoryStatus,
    MemoryType,
)
from app.providers.base import LLMMessage, LLMOptions, LLMResponse
from app.providers.fake_provider import FakeProvider
from app.repositories.memories import MemoryRepository
from app.repositories.memory_embeddings import MemoryEmbeddingRepository
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.services.chat_service import ChatService
from app.services.context_builder import ContextBuilder
from app.services.memory_candidate_service import MemoryCandidateService
from app.services.memory_embedding_service import FakeMemoryEmbeddingProvider, MemoryEmbeddingService, MemoryEmbeddingUnavailableError
from app.services.prompt_renderer import default_prompt_renderer
from app.services.session_summary_scheduler import InProcessSessionSummaryScheduler


class RecordingSnapshotReader:
    def __init__(self, snapshot: EmotionState) -> None:
        self.snapshot = snapshot
        self.calls = 0

    def get_state(self, *, apply_decay: bool = True) -> EmotionState:
        assert apply_decay is True
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("snapshot read more than once")
        return self.snapshot


class RecordingSnapshotFormatter:
    def __init__(self) -> None:
        self.seen_state: EmotionState | None = None

    def format(self, state: EmotionState) -> str:
        self.seen_state = state
        return "以下内容只是角色表达策略。"


class RecordingExpressionPlans:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, EmotionState]] = []

    def create_for_assistant_message(
        self,
        assistant_message_id: str,
        snapshot: EmotionState,
    ) -> None:
        self.calls.append((assistant_message_id, snapshot))
        if self.fail:
            raise RuntimeError("expression plan failed")


class FailingSnapshotReader:
    def get_state(self, *, apply_decay: bool = True) -> EmotionState:
        raise RuntimeError("snapshot failed")


@pytest.mark.asyncio
async def test_chat_service_reads_one_snapshot_for_context_and_plan(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'single-snapshot.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("single snapshot")
        snapshot = EmotionState(
            "default-companion", True, EMOTION_BASELINE, 9, datetime.now(UTC)
        )
        reader = RecordingSnapshotReader(snapshot)
        formatter = RecordingSnapshotFormatter()
        plans = RecordingExpressionPlans()
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 12, emotion_context_formatter=formatter),
            default_prompt_renderer(),
            FakeProvider(),
            Settings(llm_model="test-model"),
            emotion_snapshot_reader=reader,
            expression_plans=plans,
        )

        reply = await service.send_message(session.id, "hello")

        stored = messages.list(session.id)
        assert reader.calls == 1
        assert formatter.seen_state is snapshot
        assert plans.calls == [(stored[-1].id, snapshot)]
        assert reply.assistant_message_id == stored[-1].id


@pytest.mark.asyncio
async def test_snapshot_failure_keeps_text_reply_and_skips_plan(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'snapshot-failure.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("snapshot failure")
        plans = RecordingExpressionPlans()
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 12, emotion_context_formatter=RecordingSnapshotFormatter()),
            default_prompt_renderer(),
            FakeProvider(),
            Settings(llm_model="test-model"),
            emotion_snapshot_reader=FailingSnapshotReader(),
            expression_plans=plans,
        )

        reply = await service.send_message(session.id, "hello")

        assert reply.reply
        assert [message.role for message in messages.list(session.id)] == [
            ChatRole.USER,
            ChatRole.ASSISTANT,
        ]
        assert plans.calls == []


@pytest.mark.asyncio
async def test_plan_failure_does_not_block_reply_local_update_or_remote_schedule(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'plan-failure.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("plan failure")
        snapshot = EmotionState(
            "default-companion", True, EMOTION_BASELINE, 9, datetime.now(UTC)
        )
        updater = RecordingEmotionUpdater()
        scheduler = RecordingEmotionAnalysisScheduler(messages)
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 12, emotion_context_formatter=RecordingSnapshotFormatter()),
            default_prompt_renderer(),
            FakeProvider(),
            Settings(llm_model="test-model"),
            emotion_snapshot_reader=RecordingSnapshotReader(snapshot),
            expression_plans=RecordingExpressionPlans(fail=True),
            emotion_updater=updater,
            emotion_analysis_scheduler=scheduler,
        )

        reply = await service.send_message(session.id, "hello")

        assert reply.assistant_message_id == updater.assistant_ids[0]
        assert scheduler.assistant_ids == updater.assistant_ids


class FailingAssistantMessageRepository:
    def __init__(self, wrapped: MessageRepository) -> None:
        self._wrapped = wrapped

    def add(self, session_id, role, content, metadata=None):
        if role is ChatRole.ASSISTANT:
            raise RuntimeError("assistant persistence failed")
        return self._wrapped.add(session_id, role, content, metadata)

    def list_recent(self, session_id: str, limit: int):
        return self._wrapped.list_recent(session_id, limit)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", [FakeProvider(mode="empty"), FakeProvider()])
async def test_plan_is_not_created_before_valid_response_and_assistant_persistence(
    tmp_path: Path,
    provider: FakeProvider,
) -> None:
    database_url = f"sqlite:///{tmp_path / f'no-plan-{provider.mode}.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("no early plan")
        repository = messages if provider.mode == "empty" else FailingAssistantMessageRepository(messages)
        snapshot = EmotionState(
            "default-companion", True, EMOTION_BASELINE, 9, datetime.now(UTC)
        )
        plans = RecordingExpressionPlans()
        service = ChatService(
            sessions,
            repository,  # type: ignore[arg-type]
            ContextBuilder(repository, 12, emotion_context_formatter=RecordingSnapshotFormatter()),  # type: ignore[arg-type]
            default_prompt_renderer(),
            provider,
            Settings(llm_model="test-model"),
            emotion_snapshot_reader=RecordingSnapshotReader(snapshot),
            expression_plans=plans,
        )

        with pytest.raises((ProviderInvalidResponseError, RuntimeError)):
            await service.send_message(session.id, "hello")

        assert plans.calls == []



class RecordingEmotionAnalysisScheduler:
    def __init__(self, messages: MessageRepository) -> None:
        self._messages = messages
        self.turn_ids: list[tuple[str, str, int]] = []
        self.roles_seen_at_schedule: list[list[ChatRole]] = []

    @property
    def assistant_ids(self) -> list[str]:
        return [assistant_id for _user_id, assistant_id, _version in self.turn_ids]

    def schedule(
        self,
        user_message_id: str,
        assistant_message_id: str,
        base_emotion_version: int,
    ) -> None:
        self.turn_ids.append(
            (user_message_id, assistant_message_id, base_emotion_version)
        )
        rows = self._messages._connection.execute(
            "SELECT session_id FROM messages WHERE id = ?",
            (assistant_message_id,),
        ).fetchone()
        assert rows is not None
        self.roles_seen_at_schedule.append(
            [message.role for message in self._messages.list(str(rows["session_id"]))]
        )


class RecordingEmotionUpdater:
    def __init__(self) -> None:
        self.assistant_ids: list[str] = []

    def update(self, session_id, user_message, assistant_message):
        self.assistant_ids.append(assistant_message.id)
        from app.domain.models import EMOTION_BASELINE, EmotionState
        from datetime import UTC, datetime
        return EmotionState(
            scope_id="default-companion",
            enabled=True,
            vector=EMOTION_BASELINE,
            version=7,
            updated_at=datetime.now(UTC),
        )


@pytest.mark.asyncio
async def test_chat_service_schedules_emotion_analysis_after_local_update_and_persistence(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'analysis-after-local.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("分析调度")
        updater = RecordingEmotionUpdater()
        scheduler = RecordingEmotionAnalysisScheduler(messages)
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            FakeProvider(),
            Settings(llm_model="test-model"),
            emotion_updater=updater,
            emotion_analysis_scheduler=scheduler,
        )

        await service.send_message(session.id, "请在本地情感更新后安排分析。")

        assert len(updater.assistant_ids) == 1
        assert scheduler.assistant_ids == updater.assistant_ids
        assert scheduler.turn_ids[0][0] != scheduler.turn_ids[0][1]
        assert scheduler.turn_ids[0][2] == 7
        assert scheduler.roles_seen_at_schedule == [[ChatRole.USER, ChatRole.ASSISTANT]]


class FailingEmotionUpdater:
    def update(self, session_id, user_message, assistant_message) -> None:
        raise RuntimeError("local emotion update failed")


@pytest.mark.asyncio
async def test_chat_service_does_not_schedule_remote_analysis_when_local_update_fails(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'local-update-failure.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("本地更新失败")
        scheduler = RecordingEmotionAnalysisScheduler(messages)
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            FakeProvider(),
            Settings(llm_model="test-model"),
            emotion_updater=FailingEmotionUpdater(),
            emotion_analysis_scheduler=scheduler,
        )

        reply = await service.send_message(session.id, "聊天仍应成功。")

        assert reply.provider == "fake"
        assert scheduler.assistant_ids == []


class FailingEmotionAnalysisScheduler:
    def schedule(
        self,
        user_message_id: str,
        assistant_message_id: str,
        base_emotion_version: int,
    ) -> None:
        raise RuntimeError("analysis scheduler failed")


@pytest.mark.asyncio
async def test_chat_service_ignores_emotion_analysis_scheduling_failure(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'analysis-schedule-failure.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("分析调度失败")
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            FakeProvider(),
            Settings(llm_model="test-model"),
            emotion_analysis_scheduler=FailingEmotionAnalysisScheduler(),
        )

        reply = await service.send_message(session.id, "即使分析调度失败也要回复。")

        assert reply.provider == "fake"
        assert [message.role for message in messages.list(session.id)] == [
            ChatRole.USER,
            ChatRole.ASSISTANT,
        ]


class RecordingSummaryScheduler:
    def __init__(self, messages: MessageRepository) -> None:
        self._messages = messages
        self.session_ids: list[str] = []
        self.roles_seen_at_schedule: list[list[ChatRole]] = []

    def schedule(self, session_id: str) -> None:
        self.session_ids.append(session_id)
        self.roles_seen_at_schedule.append(
            [message.role for message in self._messages.list(session_id)]
        )


@pytest.mark.asyncio
async def test_chat_service_schedules_summary_after_assistant_persistence(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'summary-after-persist.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("摘要调度")
        scheduler = RecordingSummaryScheduler(messages)
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            FakeProvider(),
            Settings(llm_model="test-model"),
            summary_scheduler=scheduler,
        )

        reply = await service.send_message(session.id, "请在回复后安排摘要。")

        assert reply.provider == "fake"
        assert scheduler.session_ids == [session.id]
        assert scheduler.roles_seen_at_schedule == [
            [ChatRole.USER, ChatRole.ASSISTANT]
        ]


class FailingSummaryScheduler:
    def schedule(self, session_id: str) -> None:
        raise RuntimeError("summary scheduler failed")


@pytest.mark.asyncio
async def test_chat_service_ignores_summary_scheduling_failure(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'summary-schedule-failure.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("摘要调度失败")
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            FakeProvider(),
            Settings(llm_model="test-model"),
            summary_scheduler=FailingSummaryScheduler(),
        )

        reply = await service.send_message(session.id, "即使摘要调度失败也要回复。")

        assert reply.provider == "fake"
        assert [message.role for message in messages.list(session.id)] == [
            ChatRole.USER,
            ChatRole.ASSISTANT,
        ]


@pytest.mark.asyncio
async def test_in_process_summary_scheduler_returns_before_job_finishes() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    async def job(session_id: str) -> None:
        assert session_id == "session-1"
        started.set()
        await release.wait()
        finished.set()

    scheduler = InProcessSessionSummaryScheduler(job)

    scheduler.schedule("session-1")
    assert not finished.is_set()
    await started.wait()
    assert not finished.is_set()
    release.set()
    await finished.wait()


@pytest.mark.asyncio
async def test_in_process_summary_scheduler_coalesces_same_session_while_running() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    calls: list[str] = []

    async def job(session_id: str) -> None:
        calls.append(session_id)
        started.set()
        await release.wait()

    scheduler = InProcessSessionSummaryScheduler(job)

    scheduler.schedule("session-1")
    scheduler.schedule("session-1")
    await started.wait()
    assert calls == ["session-1"]
    release.set()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_in_process_summary_scheduler_reruns_once_when_rescheduled_while_running() -> None:
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    second_finished = asyncio.Event()
    calls: list[str] = []

    async def job(session_id: str) -> None:
        calls.append(session_id)
        if len(calls) == 1:
            first_started.set()
            await release_first.wait()
        else:
            second_finished.set()

    scheduler = InProcessSessionSummaryScheduler(job)

    scheduler.schedule("session-1")
    await first_started.wait()
    scheduler.schedule("session-1")
    release_first.set()
    await second_finished.wait()

    assert calls == ["session-1", "session-1"]


@pytest.mark.asyncio
async def test_in_process_summary_scheduler_shutdown_cancels_stuck_job() -> None:
    cancelled = asyncio.Event()

    async def job(session_id: str) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    scheduler = InProcessSessionSummaryScheduler(job)
    scheduler.schedule("session-1")
    await asyncio.sleep(0)

    await scheduler.shutdown(timeout_seconds=0.01)

    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_in_process_summary_scheduler_shutdown_does_not_restart_dirty_job() -> None:
    first_started = asyncio.Event()
    cancelled = asyncio.Event()
    calls: list[str] = []

    async def job(session_id: str) -> None:
        calls.append(session_id)
        first_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    scheduler = InProcessSessionSummaryScheduler(job)
    scheduler.schedule("session-1")
    await first_started.wait()
    scheduler.schedule("session-1")

    await scheduler.shutdown(timeout_seconds=0.01)
    await asyncio.sleep(0)
    scheduler.schedule("session-1")
    await asyncio.sleep(0)

    assert cancelled.is_set()
    assert calls == ["session-1"]


def test_context_budget_removes_oldest_history_before_newer_history() -> None:
    messages = [
        LLMMessage(role=ChatRole.SYSTEM, content="role"),
        LLMMessage(role=ChatRole.USER, content="oldest-history"),
        LLMMessage(role=ChatRole.ASSISTANT, content="newest-history"),
        LLMMessage(role=ChatRole.USER, content="current"),
    ]

    fitted = ChatService._fit_provider_messages(messages, 31)

    assert [message.content for message in fitted] == ["role", "newest-history", "current"]


def test_context_budget_counts_system_join_separators() -> None:
    messages = [
        LLMMessage(role=ChatRole.SYSTEM, content="role"),
        LLMMessage(role=ChatRole.SYSTEM, content="memory"),
        LLMMessage(role=ChatRole.USER, content="x" * 20),
    ]

    fitted = ChatService._fit_provider_messages(messages, 30)

    assert fitted == [messages[0], messages[-1]]


def test_context_budget_keeps_memory_until_history_is_removed() -> None:
    messages = [
        LLMMessage(role=ChatRole.SYSTEM, content="role"),
        LLMMessage(role=ChatRole.SYSTEM, content="memory-context"),
        LLMMessage(role=ChatRole.USER, content="old-history"),
        LLMMessage(role=ChatRole.USER, content="current"),
    ]

    fitted = ChatService._fit_provider_messages(messages, 30)

    assert [message.content for message in fitted] == ["role", "memory-context", "current"]


def test_context_budget_removes_memory_after_history() -> None:
    messages = [
        LLMMessage(role=ChatRole.SYSTEM, content="role"),
        LLMMessage(role=ChatRole.SYSTEM, content="large-memory-context"),
        LLMMessage(role=ChatRole.USER, content="current"),
    ]

    fitted = ChatService._fit_provider_messages(messages, 11)

    assert [message.content for message in fitted] == ["role", "current"]


def test_context_budget_allows_hard_preserved_overflow_without_truncation() -> None:
    messages = [
        LLMMessage(role=ChatRole.SYSTEM, content="role-system"),
        LLMMessage(role=ChatRole.USER, content="current-user-message"),
    ]

    fitted = ChatService._fit_provider_messages(messages, 5)

    assert fitted == messages
    assert sum(len(message.content) for message in fitted) > 5


@pytest.mark.asyncio
async def test_chat_service_persists_pruned_history_unchanged(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'pruned-persistence.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("裁剪不删历史")
        seeded = [
            messages.add(session.id, ChatRole.USER, "old-user" * 10),
            messages.add(session.id, ChatRole.ASSISTANT, "old-assistant" * 10),
        ]
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            FakeProvider(),
            Settings(llm_model="test-model", chat_context_max_characters=200),
        )

        await service.send_message(session.id, "current")

        stored = messages.list(session.id)
        assert [message.id for message in stored[:2]] == [message.id for message in seeded]
        assert [message.content for message in stored[:2]] == [
            "old-user" * 10,
            "old-assistant" * 10,
        ]
        assert [message.role for message in stored[-2:]] == [ChatRole.USER, ChatRole.ASSISTANT]


@pytest.mark.asyncio
async def test_chat_service_persists_user_and_assistant_messages(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'chat.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("聊天")
        provider = FakeProvider()
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            provider,
            Settings(llm_model="test-model"),
        )

        reply = await service.send_message(session.id, "今天有点累")

        stored = messages.list(session.id)
        assert reply.provider == "fake"
        assert reply.model == "test-model"
        assert [message.role for message in stored] == [ChatRole.USER, ChatRole.ASSISTANT]
        assert stored[0].content == "今天有点累"
        assert stored[1].content == reply.reply
        assert provider.calls[0][0].role == ChatRole.SYSTEM
        assert provider.calls[0][-1].content == "今天有点累"


@pytest.mark.asyncio
async def test_chat_service_sends_system_prompt_and_full_recent_context_on_second_turn(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'multi_turn_context.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("上下文")
        provider = FakeProvider()
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            provider,
            Settings(llm_model="test-model"),
        )

        first_reply = await service.send_message(session.id, "第一轮用户消息")
        await service.send_message(session.id, "第二轮用户消息")

        second_call = provider.calls[1]
        assert second_call[0].role == ChatRole.SYSTEM
        assert "林夕" in second_call[0].content
        assert [(message.role, message.content) for message in second_call[1:]] == [
            (ChatRole.USER, "第一轮用户消息"),
            (ChatRole.ASSISTANT, first_reply.reply),
            (ChatRole.USER, "第二轮用户消息"),
        ]


@pytest.mark.asyncio
async def test_chat_service_passes_current_user_text_for_memory_relevance(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'chat_relevant_memory.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        session = sessions.create("相关记忆聊天")
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
        provider = FakeProvider()
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(
                messages,
                12,
                memories=memories,
                memory_context_enabled=True,
                memory_context_limit=8,
                memory_retrieval_mode="relevance",
                memory_retrieval_fallback_limit=2,
            ),
            default_prompt_renderer(),
            provider,
            Settings(llm_model="test-model"),
        )

        await service.send_message(session.id, "我喜欢什么饮料？")

        sent_contents = [message.content for message in provider.calls[0]]
        memory_context = sent_contents[1]
        assert "用户喜欢红茶。" in memory_context
        assert "用户正在构建本地 AI 桌宠。" not in memory_context


@pytest.mark.asyncio
async def test_chat_service_uses_embedding_selected_memory_context(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'chat_embedding_memory.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        embeddings = MemoryEmbeddingRepository(connection)
        embedding_service = MemoryEmbeddingService(embeddings, FakeMemoryEmbeddingProvider())
        session = sessions.create("语义记忆聊天")
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
        embedding_service.ensure_embedding(tea)
        embedding_service.ensure_embedding(project)
        provider = FakeProvider()
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(
                messages,
                12,
                memories=memories,
                memory_context_enabled=True,
                memory_context_limit=8,
                memory_retrieval_mode="embedding",
                memory_retrieval_fallback_limit=2,
                memory_embedding_service=embedding_service,
                memory_embedding_min_score=0.1,
            ),
            default_prompt_renderer(),
            provider,
            Settings(llm_model="test-model", memory_retrieval_mode="embedding"),
        )

        await service.send_message(session.id, "我喜欢什么饮料？")

        memory_context = provider.calls[0][1].content
        assert "用户喜欢红茶。" in memory_context
        assert "用户正在构建本地 AI 桌宠。" not in memory_context

    database_url = f"sqlite:///{tmp_path / 'context.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("上下文")
        for index in range(5):
            messages.add(session.id, ChatRole.USER, f"旧消息 {index}")
        provider = FakeProvider()
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 3),
            default_prompt_renderer(),
            provider,
            Settings(llm_model="test-model", recent_context_messages=3),
        )

        await service.send_message(session.id, "新消息")

        sent_contents = [message.content for message in provider.calls[0]]
        assert "旧消息 0" not in sent_contents
        assert "旧消息 1" not in sent_contents
        assert sent_contents[-3:] == ["旧消息 3", "旧消息 4", "新消息"]


@pytest.mark.asyncio
async def test_chat_service_maps_invalid_provider_response(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'invalid.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("错误")
        scheduler = RecordingSummaryScheduler(messages)
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            FakeProvider(mode="invalid"),
            Settings(llm_model="test-model"),
            summary_scheduler=scheduler,
        )

        with pytest.raises(ProviderInvalidResponseError):
            await service.send_message(session.id, "触发错误")

        assert scheduler.session_ids == []


class FailingMemoryCandidateService:
    async def create_candidates_from_user_text(self, *, session_id: str | None, user_text: str):
        raise RuntimeError("candidate extraction failed")


@pytest.mark.asyncio
async def test_chat_service_ignores_memory_candidate_extraction_failure(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'candidate_failure.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("候选失败")
        provider = FakeProvider()
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            provider,
            Settings(llm_model="test-model"),
            FailingMemoryCandidateService(),
        )

        reply = await service.send_message(session.id, "我喜欢红茶。")

        stored = messages.list(session.id)
        assert reply.provider == "fake"
        assert [message.role for message in stored] == [ChatRole.USER, ChatRole.ASSISTANT]
        assert stored[-1].content == reply.reply


@pytest.mark.asyncio
async def test_chat_service_excludes_pending_candidates_from_next_turn_context(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'pending_candidate_context.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        session = sessions.create("pending 不进上下文")
        provider = FakeProvider()
        memory_candidates = MemoryCandidateService(memories, Settings(memory_candidates_enabled=True))
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(
                messages,
                12,
                memories=memories,
                memory_context_enabled=True,
                memory_context_limit=8,
                memory_retrieval_mode="relevance",
                memory_retrieval_fallback_limit=3,
            ),
            default_prompt_renderer(),
            provider,
            Settings(llm_model="test-model", memory_context_enabled=True),
            memory_candidates,
        )

        await service.send_message(session.id, "我喜欢红茶。")
        await service.send_message(session.id, "你记得我的饮料偏好吗？")

        assert len(memories.list(status=MemoryStatus.PENDING)) == 1
        second_call_contents = [message.content for message in provider.calls[1]]
        assert all("用户喜欢红茶。" not in content for content in second_call_contents)


@pytest.mark.asyncio
async def test_chat_service_prunes_old_history_before_provider_when_context_is_large(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'context_budget.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("上下文预算")
        for index in range(4):
            messages.add(session.id, ChatRole.USER, f"旧消息 {index} " + "甲" * 7000)
            messages.add(session.id, ChatRole.ASSISTANT, f"旧回复 {index} " + "乙" * 7000)
        current_text = "当前问题 " + "丙" * 1000
        provider = FakeProvider()
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            provider,
            Settings(llm_model="test-model"),
        )

        await service.send_message(session.id, current_text)

        sent = provider.calls[0]
        sent_text = "\n".join(message.content for message in sent)
        assert sent[0].role == ChatRole.SYSTEM
        assert "林夕" in sent[0].content
        assert sent[-1] == LLMMessage(role=ChatRole.USER, content=current_text)
        assert "旧消息 0" not in sent_text
        assert sum(len(message.content) for message in sent) <= 24_000


class MetadataProvider:
    async def generate(self, messages: list[LLMMessage], options: LLMOptions) -> LLMResponse:
        return LLMResponse(
            text="带指标的回复",
            provider="deepseek",
            model=options.model,
            metadata={
                "finish_reason": "stop",
                "completion_id": "chatcmpl-test",
                "total_tokens": 9,
            },
        )


@pytest.mark.asyncio
async def test_chat_service_persists_provider_metadata_without_public_shape_change(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'metadata.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("指标")
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            MetadataProvider(),
            Settings(llm_model="deepseek-v4-flash"),
        )

        reply = await service.send_message(session.id, "记录指标")

        stored = messages.list(session.id)
        assert reply.provider == "deepseek"
        assert reply.model == "deepseek-v4-flash"
        assert stored[-1].metadata == {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "finish_reason": "stop",
            "completion_id": "chatcmpl-test",
            "total_tokens": 9,
        }


class FailingMemoryEmbeddingService:
    def search_relevant(self, query: str, limit: int, min_score: float):
        raise MemoryEmbeddingUnavailableError("embedding unavailable")


@pytest.mark.asyncio
async def test_chat_service_embedding_failure_falls_back_to_relevance(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'chat_embedding_fallback.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        session = sessions.create("嵌入失败回退")
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
        provider = FakeProvider()
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(
                messages,
                12,
                memories=memories,
                memory_context_enabled=True,
                memory_context_limit=8,
                memory_retrieval_mode="embedding",
                memory_retrieval_fallback_limit=2,
                memory_embedding_service=FailingMemoryEmbeddingService(),
                memory_embedding_min_score=0.1,
            ),
            default_prompt_renderer(),
            provider,
            Settings(llm_model="test-model", memory_retrieval_mode="embedding"),
        )

        await service.send_message(session.id, "我喜欢什么饮料？")

        memory_context = provider.calls[0][1].content
        assert "用户喜欢红茶。" in memory_context
        assert "用户正在构建本地 AI 桌宠。" not in memory_context


def test_context_builder_returns_recent_llm_messages(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'builder.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("上下文构建")
        messages.add(session.id, ChatRole.USER, "一")
        messages.add(session.id, ChatRole.ASSISTANT, "二")
        messages.add(session.id, ChatRole.USER, "三")

        context = ContextBuilder(messages, 2).build_recent_context(session.id)

        assert context == [
            LLMMessage(role=ChatRole.ASSISTANT, content="二"),
            LLMMessage(role=ChatRole.USER, content="三"),
        ]


def test_send_message_api_returns_reply_and_stores_messages(client: TestClient) -> None:
    session = client.post("/api/sessions", json={"title": "聊天"}).json()

    response = client.post(f"/api/sessions/{session['id']}/messages", json={"content": "你好"})

    assert response.status_code == 200
    body = response.json()
    assert body["reply"].startswith("我听见了：你好")
    assert body["metadata"] == {"provider": "fake", "model": "test-model"}

    messages = client.get(f"/api/sessions/{session['id']}/messages").json()
    assert [message["role"] for message in messages] == ["user", "assistant"]


def test_send_message_to_missing_session_returns_404(client: TestClient) -> None:
    response = client.post("/api/sessions/missing/messages", json={"content": "你好"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_empty_message_returns_validation_error(client: TestClient) -> None:
    session = client.post("/api/sessions", json={"title": "聊天"}).json()

    response = client.post(f"/api/sessions/{session['id']}/messages", json={"content": ""})

    assert response.status_code == 422
