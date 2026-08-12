import asyncio
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import ProviderInvalidResponseError, ValidationAppError
from app.domain.models import (
    EMOTION_BASELINE,
    ChatRole,
    EmotionState,
    MemorySource,
    MemoryStatus,
    MemoryType,
)
from app.providers.base import ChatDispatchBudget, LLMMessage, LLMOptions, LLMResponse
from app.providers.fake_provider import FakeProvider
from app.repositories.chat_turns import ChatTurnRepository
from app.repositories.context_sources import ContextSourceRepository
from app.repositories.memories import MemoryRepository
from app.repositories.memory_embeddings import MemoryEmbeddingRepository
from app.repositories.messages import MessageRepository
from app.repositories.personas import PersonaRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.services.chat_service import ChatService
from app.services.context_builder import ContextBuilder
from app.services.context_composer import ContextComposer, ContextProtectedOverflowError
from app.services.context_data_encoder import ContextDataEncoder
from app.services.emotion_context import EmotionContextFormatter
from app.services.memory_candidate_service import MemoryCandidateService
from app.services.memory_embedding_service import FakeMemoryEmbeddingProvider, MemoryEmbeddingService, MemoryEmbeddingUnavailableError
from app.services.persona_compiler import PersonaCompiler
from app.services.persona_service import PersonaService
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


class RecordingSnapshotFormatter(EmotionContextFormatter):
    def __init__(self) -> None:
        self.seen_state: EmotionState | None = None

    def to_expression_view(self, state: EmotionState):
        self.seen_state = state
        return super().to_expression_view(state)

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


class RecordingMemoryJobScheduler:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str, str, str]] = []

    def schedule(
        self,
        *,
        session_id: str,
        user_message_id: str,
        assistant_message_id: str,
        persona_artifact_id: str,
        chat_turn_id: str | None = None,
        turn_completed_at=None,
    ) -> bool:
        del turn_completed_at
        if self.fail:
            raise RuntimeError("scheduler failure")
        self.calls.append(
            (
                session_id,
                user_message_id,
                assistant_message_id,
                persona_artifact_id,
            )
        )
        return True


class FailingSnapshotReader:
    def get_state(self, *, apply_decay: bool = True) -> EmotionState:
        raise RuntimeError("snapshot failed")


def _chat_service(
    connection: sqlite3.Connection,
    sessions: SessionRepository,
    messages: MessageRepository,
    context_builder: ContextBuilder,
    _prompt_renderer,
    provider,
    settings: Settings,
    *args,
    **kwargs,
) -> ChatService:
    renderer = default_prompt_renderer()
    repository = PersonaRepository(connection)
    personas = PersonaService(
        repository,
        compiler=PersonaCompiler(
            template_text=renderer.load_template_text(),
            persona_max_characters=settings.persona_max_characters,
        ),
        bootstrap_config=renderer.load_persona_v1_config(),
    )
    if repository.inspect_startup_state().artifact_count == 0:
        personas.bootstrap()
    formatter = context_builder._emotion_context_formatter or EmotionContextFormatter()
    chat_turns = kwargs.pop("chat_turns", ChatTurnRepository(connection))
    return ChatService(
        sessions,
        messages,
        chat_turns,
        personas,
        ContextSourceRepository(
            messages,
            context_builder._memories if context_builder._memory_context_enabled else None,
            memory_retrieval_mode=context_builder._memory_retrieval_mode,
            memory_embedding_service=context_builder._memory_embedding_service,
            memory_embedding_min_score=context_builder._memory_embedding_min_score,
        ),
        ContextComposer(settings, ContextDataEncoder()),
        provider,
        settings,
        *args,
        emotion_context_formatter=formatter,
        **kwargs,
    )


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
        service = _chat_service(connection,
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
        service = _chat_service(connection,
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
        service = _chat_service(connection,
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


class FailingChatTurnRepository:
    def append_assistant_turn(self, **_kwargs):
        raise RuntimeError("assistant persistence failed")


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
        repository = messages
        snapshot = EmotionState(
            "default-companion", True, EMOTION_BASELINE, 9, datetime.now(UTC)
        )
        plans = RecordingExpressionPlans()
        service = _chat_service(connection,
            sessions,
            repository,  # type: ignore[arg-type]
            ContextBuilder(repository, 12, emotion_context_formatter=RecordingSnapshotFormatter()),  # type: ignore[arg-type]
            default_prompt_renderer(),
            provider,
            Settings(llm_model="test-model"),
            emotion_snapshot_reader=RecordingSnapshotReader(snapshot),
            expression_plans=plans,
            chat_turns=(
                FailingChatTurnRepository()
                if provider.mode != "empty"
                else ChatTurnRepository(connection)
            ),
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
        service = _chat_service(connection,
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
        service = _chat_service(connection,
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
        service = _chat_service(connection,
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
        self.chat_turn_ids: list[str | None] = []
        self.roles_seen_at_schedule: list[list[ChatRole]] = []

    def schedule(self, session_id: str, *, chat_turn_id: str | None = None) -> None:
        self.session_ids.append(session_id)
        self.chat_turn_ids.append(chat_turn_id)
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
        service = _chat_service(connection,
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
        turn = connection.execute(
            "SELECT id, user_message_id, assistant_message_id FROM chat_turns"
        ).fetchone()
        assert turn is not None
        assert scheduler.chat_turn_ids == [str(turn["id"])]
        stored = messages.list(session.id)
        assert tuple(turn)[1:] == (stored[0].id, stored[1].id)


class FailingSummaryScheduler:
    def schedule(self, session_id: str, *, chat_turn_id: str | None = None) -> None:
        del session_id, chat_turn_id
        raise RuntimeError("summary scheduler failed")


@pytest.mark.asyncio
async def test_chat_service_ignores_summary_scheduling_failure(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'summary-schedule-failure.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("摘要调度失败")
        service = _chat_service(connection,
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


class BlockingChatProvider:
    provider_name = "fake"

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(
        self,
        messages: list[LLMMessage],
        options: LLMOptions,
    ) -> LLMResponse:
        self.started.set()
        await self.release.wait()
        return LLMResponse(
            text="reply after switch",
            provider="fake",
            model=options.model,
        )


@pytest.mark.asyncio
async def test_inflight_persona_switch_keeps_reply_and_job_on_frozen_artifact(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'inflight-persona.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("inflight persona")
        provider = BlockingChatProvider()
        scheduler = RecordingMemoryJobScheduler()
        settings = replace(
            Settings(llm_model="test-model"),
            memory_automation_mode="shadow_auto",
        )
        service = _chat_service(
            connection,
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            provider,
            settings,
            memory_job_scheduler=scheduler,
        )
        before = service._persona_service.current()

        turn = asyncio.create_task(service.send_message(session.id, "hello"))
        await provider.started.wait()
        replacement = default_prompt_renderer().load_persona_v1_config()
        replacement["identity"] = {
            **replacement["identity"],
            "name": "切换后的角色",
        }
        after = service._persona_service.create_and_activate(
            replacement,
            expected_artifact_id=before.artifact.id,
            expected_generation=before.active.activation_generation,
        )
        provider.release.set()
        reply = await turn

        assistant = messages.get(reply.assistant_message_id)
        assert assistant is not None
        manifest_persona_id = assistant.metadata["context_manifest"][
            "persona_artifact_id"
        ]
        assert manifest_persona_id == before.artifact.id
        assert after.artifact.id != before.artifact.id
        stored_messages = messages.list(session.id)
        assert scheduler.calls == [
            (
                session.id,
                stored_messages[0].id,
                reply.assistant_message_id,
                before.artifact.id,
            )
        ]


class CollidingMetadataProvider:
    provider_name = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[list[LLMMessage], LLMOptions]] = []

    async def generate(
        self,
        messages: list[LLMMessage],
        options: LLMOptions,
    ) -> LLMResponse:
        self.calls.append((messages, options))
        return LLMResponse(
            text="safe reply",
            provider="fake",
            model=options.model,
            metadata={
                "context_manifest": {
                    "persona_artifact_id": "attacker",
                    "prompt": "leak",
                },
                "provider_metric": 7,
                "finish_reason": "stop",
            },
        )


class FailingMemorySources:
    def list_context_sources(self, *args, **kwargs):
        raise RuntimeError("memory retrieval failed")


@pytest.mark.asyncio
async def test_gate_c1_rejects_current_user_limit_before_persistence(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'current-limit.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("current limit")
        provider = FakeProvider()
        settings = Settings(llm_model="test-model")
        service = _chat_service(
            connection,
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            provider,
            settings,
        )

        with pytest.raises(ValidationAppError, match="消息内容过长"):
            await service.send_message(session.id, "x" * 8001)

        assert messages.list(session.id) == []
        assert provider.calls == []


@pytest.mark.asyncio
async def test_gate_c1_current_message_exact_once_last_and_dispatch_budget(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'exact-current.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("exact current")
        messages.add(session.id, ChatRole.USER, "prior")
        messages.add(session.id, ChatRole.ASSISTANT, "prior reply")
        provider = CollidingMetadataProvider()
        settings = Settings(llm_model="test-model")
        service = _chat_service(
            connection,
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            provider,
            settings,
        )

        reply = await service.send_message(session.id, "current")

        sent, options = provider.calls[0]
        assert [(message.role, message.content) for message in sent[-3:]] == [
            (ChatRole.USER, "prior"),
            (ChatRole.ASSISTANT, "prior reply"),
            (ChatRole.USER, "current"),
        ]
        assert sum(message.content == "current" for message in sent) == 1
        assert isinstance(options.chat_dispatch_budget, ChatDispatchBudget)
        stored = messages.get(reply.assistant_message_id)
        assert stored is not None
        manifest = stored.metadata["context_manifest"]
        assert manifest["schema_version"] == "context-manifest-v2"
        assert manifest["persona_artifact_id"] != "attacker"
        assert manifest["selected_recent_message_ids"] == [
            message.id for message in messages.list(session.id)[:2]
        ]
        assert stored.metadata["finish_reason"] == "stop"
        assert "provider_metric" not in stored.metadata
        assert "prompt" not in str(manifest).lower()
        assert options.chat_dispatch_budget.expected_normalized_characters == (
            manifest["provider_character_count"]
        )
        assert options.chat_dispatch_budget.max_normalized_characters == (
            manifest["max_characters"]
        )
        assert options.chat_dispatch_budget.expected_normalized_characters <= (
            options.chat_dispatch_budget.max_normalized_characters
        )


@pytest.mark.asyncio
async def test_gate_c1_optional_source_and_emotion_failures_degrade(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'optional-failure.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("optional failures")
        provider = FakeProvider()
        settings = Settings(llm_model="test-model")
        service = _chat_service(
            connection,
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            provider,
            settings,
            emotion_snapshot_reader=FailingSnapshotReader(),
        )
        service._context_sources = ContextSourceRepository(
            messages,
            FailingMemorySources(),  # type: ignore[arg-type]
        )

        reply = await service.send_message(session.id, "hello")

        assert reply.reply
        assert [message.role for message in provider.calls[0]] == [
            ChatRole.SYSTEM,
            ChatRole.USER,
        ]
        stored = messages.get(reply.assistant_message_id)
        assert stored is not None
        assert stored.metadata["context_manifest"]["selected_memory_version_ids"] == []
        assert stored.metadata["context_manifest"]["source_emotion_version"] is None


@pytest.mark.asyncio
async def test_gate_c1_recent_source_failure_is_not_silently_discarded(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'recent-failure.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("recent failure")
        provider = FakeProvider()
        settings = Settings(llm_model="test-model")
        service = _chat_service(
            connection,
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            provider,
            settings,
        )

        class FailingRecentMessages:
            def list_recent_excluding(self, *args, **kwargs):
                raise RuntimeError("recent snapshot failed")

        service._context_sources = ContextSourceRepository(
            FailingRecentMessages(),  # type: ignore[arg-type]
            None,
        )

        with pytest.raises(RuntimeError, match="recent snapshot failed"):
            await service.send_message(session.id, "hello")
        assert provider.calls == []


@pytest.mark.asyncio
async def test_gate_c1_protected_overflow_calls_no_provider(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'protected-overflow.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("protected overflow")
        provider = FakeProvider()
        settings = Settings(
            llm_model="test-model",
            chat_context_max_characters=2001,
            persona_max_characters=1024,
            chat_current_user_max_characters=1002,
        )
        service = _chat_service(
            connection,
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            provider,
            settings,
        )

        with pytest.raises(ContextProtectedOverflowError):
            await service.send_message(session.id, "x" * 1002)

        assert provider.calls == []


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
        service = _chat_service(connection,
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            FakeProvider(),
            Settings(llm_model="test-model", chat_context_max_characters=2048),
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
        service = _chat_service(connection,
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
        service = _chat_service(connection,
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
        service = _chat_service(connection,
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
        service = _chat_service(connection,
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
        service = _chat_service(connection,
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
        service = _chat_service(connection,
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
        assert connection.execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0] == 0
        assert [message.role for message in messages.list(session.id)] == [ChatRole.USER]


class FailingMemoryCandidateService:
    async def create_candidates_from_user_text(self, *, session_id: str | None, user_text: str):
        raise RuntimeError("candidate extraction failed")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "expected_pending", "expected_scheduler_calls"),
    [
        ("off", 0, 0),
        ("candidate_confirmation", 1, 0),
        ("shadow_auto", 0, 1),
    ],
)
async def test_completed_turn_uses_exactly_one_memory_mode_branch(
    tmp_path: Path,
    mode: str,
    expected_pending: int,
    expected_scheduler_calls: int,
) -> None:
    database_url = f"sqlite:///{tmp_path / f'{mode}.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        session = sessions.create(mode)
        settings = replace(
            Settings(llm_model="test-model", memory_candidates_enabled=True),
            memory_automation_mode=mode,
        )
        scheduler = RecordingMemoryJobScheduler()
        service = _chat_service(connection,
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            FakeProvider(),
            settings,
            memory_candidates=MemoryCandidateService(memories, settings),
            memory_job_scheduler=scheduler,
        )

        reply = await service.send_message(session.id, "我喜欢红茶。")

        assert len(memories.list(status=MemoryStatus.PENDING)) == expected_pending
        assert len(scheduler.calls) == expected_scheduler_calls
        if scheduler.calls:
            scheduled_session, user_id, assistant_id, persona_id = scheduler.calls[0]
            stored = messages.list(session.id)
            assert scheduled_session == session.id
            assert user_id == stored[0].id
            assert assistant_id == reply.assistant_message_id == stored[1].id
            assert persona_id == stored[1].metadata["context_manifest"][
                "persona_artifact_id"
            ]


@pytest.mark.asyncio
async def test_shadow_scheduler_failure_does_not_rollback_persisted_reply(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'shadow-scheduler-failure.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("shadow scheduler failure")
        service = _chat_service(connection,
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            FakeProvider(),
            replace(Settings(llm_model="test-model"), memory_automation_mode="shadow_auto"),
            memory_job_scheduler=RecordingMemoryJobScheduler(fail=True),
        )

        reply = await service.send_message(session.id, "我喜欢红茶。")

        stored = messages.list(session.id)
        assert reply.assistant_message_id == stored[-1].id
        assert [message.role for message in stored] == [
            ChatRole.USER,
            ChatRole.ASSISTANT,
        ]


@pytest.mark.asyncio
async def test_provider_failure_does_not_schedule_shadow_work(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'provider-failure-no-shadow.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("provider failure")
        scheduler = RecordingMemoryJobScheduler()
        service = _chat_service(connection,
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            FakeProvider(mode="invalid"),
            replace(Settings(llm_model="test-model"), memory_automation_mode="shadow_auto"),
            memory_job_scheduler=scheduler,
        )

        with pytest.raises(ProviderInvalidResponseError):
            await service.send_message(session.id, "聊天失败不应调度。")

        assert scheduler.calls == []


@pytest.mark.asyncio
async def test_candidate_confirmation_respects_legacy_enabled_flag(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'candidate-disabled.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        session = sessions.create("候选关闭")
        settings = replace(
            Settings(llm_model="test-model", memory_candidates_enabled=False),
            memory_automation_mode="candidate_confirmation",
        )
        scheduler = RecordingMemoryJobScheduler()
        service = _chat_service(connection,
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            FakeProvider(),
            settings,
            memory_candidates=MemoryCandidateService(memories, settings),
            memory_job_scheduler=scheduler,
        )

        await service.send_message(session.id, "我喜欢红茶。")

        assert memories.list(status=MemoryStatus.PENDING) == []
        assert scheduler.calls == []


@pytest.mark.asyncio
async def test_chat_service_ignores_memory_candidate_extraction_failure(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'candidate_failure.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("候选失败")
        provider = FakeProvider()
        service = _chat_service(connection,
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
        service = _chat_service(connection,
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
        service = _chat_service(connection,
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
    provider_name = "deepseek"

    async def generate(self, messages: list[LLMMessage], options: LLMOptions) -> LLMResponse:
        return LLMResponse(
            text="带指标的回复",
            provider="deepseek",
            model=options.model,
            metadata={
                "finish_reason": "stop",
                "completion_id": "chatcmpl-test",
                "total_tokens": 9,
                "raw_response": "PROVIDER_RAW_OUTPUT_SENTINEL",
            },
        )


@pytest.mark.asyncio
async def test_chat_service_persists_provider_metadata_without_public_shape_change(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'metadata.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("指标")
        service = _chat_service(connection,
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
        assert {
            key: value
            for key, value in stored[-1].metadata.items()
            if key != "context_manifest"
        } == {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "finish_reason": "stop",
            "completion_id": "chatcmpl-test",
            "total_tokens": 9,
        }
        assert "raw_response" not in stored[-1].metadata
        assert stored[-1].metadata["context_manifest"]["schema_version"] == (
            "context-manifest-v2"
        )


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
        service = _chat_service(connection,
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
