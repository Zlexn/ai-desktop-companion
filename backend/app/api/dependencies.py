from collections.abc import Iterator
import sqlite3

from fastapi import Depends, Request

from app.asr.base import ASRProvider
from app.asr.factory import create_asr_provider
from app.core.config import Settings, get_settings
from app.providers.base import LLMProvider
from app.providers.factory import create_named_provider, create_provider
from app.repositories.emotion_analysis import EmotionAnalysisRepository
from app.repositories.memory_audit import MemoryAuditRepository
from app.repositories.emotions import EmotionRepository
from app.repositories.expression_plans import ExpressionPlanRepository
from app.repositories.memories import MemoryRepository
from app.repositories.memory_embeddings import MemoryEmbeddingRepository
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection, resolve_sqlite_path
from app.services.chat_service import ChatService
from app.services.context_builder import ContextBuilder
from app.services.emotion_analysis_dispatch import EmotionAnalysisDispatchFence
from app.services.emotion_analysis_scheduler import EmotionAnalysisScheduler
from app.services.emotion_policy import EmotionPolicy
from app.services.emotion_context import EmotionContextFormatter
from app.services.emotion_service import CompletedTurnEmotionUpdater, EmotionService
from app.services.expression_plan_policy import ExpressionPlanPolicy
from app.services.expression_plan_service import ExpressionPlanService
from app.services.memory_candidate_service import MemoryCandidateService
from app.services.message_bound_tts_service import MessageBoundTTSService
from app.services.memory_embedding_service import (
    FakeMemoryEmbeddingProvider,
    MemoryEmbeddingProvider,
    MemoryEmbeddingService,
    SentenceTransformersMemoryEmbeddingProvider,
)
from app.services.prompt_renderer import PromptRenderer, default_prompt_renderer
from app.services.session_summary_provider import (
    FakeSessionSummaryProvider,
    LLMSessionSummaryProvider,
    SessionSummaryProvider,
)
from app.services.session_summary_scheduler import SessionSummaryScheduler
from app.services.asr_service import ASRService
from app.services.tts_service import TTSService
from app.tts.base import TTSProvider
from app.tts.expression_mapper import TTSExpressionMapper
from app.tts.factory import create_tts_provider


def get_connection(settings: Settings = Depends(get_settings)) -> Iterator[sqlite3.Connection]:
    with managed_connection(settings.database_url) as connection:
        yield connection


def get_read_only_connection(
    settings: Settings = Depends(get_settings),
) -> Iterator[sqlite3.Connection]:
    path = resolve_sqlite_path(settings.database_url).resolve()
    connection = sqlite3.connect(
        f"file:{path.as_posix()}?mode=ro",
        uri=True,
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA query_only = ON")
    try:
        yield connection
    finally:
        connection.close()


def get_session_repository(connection: sqlite3.Connection = Depends(get_connection)) -> SessionRepository:
    return SessionRepository(connection)


def get_message_repository(connection: sqlite3.Connection = Depends(get_connection)) -> MessageRepository:
    return MessageRepository(connection)


def get_memory_repository(connection: sqlite3.Connection = Depends(get_connection)) -> MemoryRepository:
    return MemoryRepository(connection)


def get_memory_embedding_repository(connection: sqlite3.Connection = Depends(get_connection)) -> MemoryEmbeddingRepository:
    return MemoryEmbeddingRepository(connection)


def get_memory_audit_repository(connection: sqlite3.Connection = Depends(get_connection)) -> MemoryAuditRepository:
    return MemoryAuditRepository(connection)


def get_emotion_repository(connection: sqlite3.Connection = Depends(get_connection)) -> EmotionRepository:
    return EmotionRepository(connection)


def get_emotion_analysis_repository(
    connection: sqlite3.Connection = Depends(get_connection),
) -> EmotionAnalysisRepository:
    return EmotionAnalysisRepository(connection)


def get_emotion_service(repository: EmotionRepository = Depends(get_emotion_repository)) -> EmotionService:
    return EmotionService(repository, EmotionPolicy())


class LocalCompletedTurnEmotionUpdater:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def update(self, session_id, user_message, assistant_message):
        with managed_connection(self._database_url) as connection:
            return EmotionService(EmotionRepository(connection), EmotionPolicy()).apply_completed_turn(
                session_id, user_message, assistant_message
            )


def get_completed_turn_emotion_updater(
    settings: Settings = Depends(get_settings),
    emotion_service: EmotionService = Depends(get_emotion_service),
) -> CompletedTurnEmotionUpdater:
    del emotion_service
    return LocalCompletedTurnEmotionUpdater(settings.database_url)


def get_llm_provider(settings: Settings = Depends(get_settings)) -> LLMProvider:
    return create_provider(settings)


def build_session_summary_provider(settings: Settings) -> SessionSummaryProvider:
    if settings.session_summary_provider == "fake":
        return FakeSessionSummaryProvider()

    llm_provider = create_named_provider(
        settings,
        settings.session_summary_llm_provider,
        deepseek_max_tokens=settings.session_summary_llm_max_tokens,
        deepseek_timeout_seconds=settings.session_summary_llm_timeout_seconds,
        deepseek_max_retries=settings.session_summary_llm_max_retries,
    )
    return LLMSessionSummaryProvider(
        llm_provider=llm_provider,
        model=settings.session_summary_llm_model,
    )


def get_session_summary_provider(
    settings: Settings = Depends(get_settings),
) -> SessionSummaryProvider:
    return build_session_summary_provider(settings)


def get_session_summary_scheduler(request: Request) -> SessionSummaryScheduler:
    return request.app.state.session_summary_scheduler


def get_emotion_analysis_scheduler(request: Request) -> EmotionAnalysisScheduler:
    return request.app.state.emotion_analysis_scheduler


def get_emotion_analysis_dispatch_fence(request: Request) -> EmotionAnalysisDispatchFence:
    return request.app.state.emotion_analysis_dispatch_fence


def get_memory_candidate_service(
    settings: Settings = Depends(get_settings),
    memories: MemoryRepository = Depends(get_memory_repository),
    provider: LLMProvider = Depends(get_llm_provider),
) -> MemoryCandidateService:
    return MemoryCandidateService(memories, settings, llm_provider=provider)


def get_memory_embedding_provider(settings: Settings = Depends(get_settings)) -> MemoryEmbeddingProvider | None:
    if not settings.memory_embedding_enabled:
        return None
    if settings.memory_embedding_provider == "fake":
        return FakeMemoryEmbeddingProvider(settings.memory_embedding_model)
    if settings.memory_embedding_provider == "sentence-transformers":
        return SentenceTransformersMemoryEmbeddingProvider(settings.memory_embedding_model)
    return None


def get_memory_embedding_service(
    repository: MemoryEmbeddingRepository = Depends(get_memory_embedding_repository),
    provider: MemoryEmbeddingProvider | None = Depends(get_memory_embedding_provider),
) -> MemoryEmbeddingService | None:
    if provider is None:
        return None
    return MemoryEmbeddingService(repository, provider)


def get_prompt_renderer() -> PromptRenderer:
    return default_prompt_renderer()


def get_tts_provider(settings: Settings = Depends(get_settings)) -> TTSProvider:
    return create_tts_provider(settings)


def get_asr_provider(settings: Settings = Depends(get_settings)) -> ASRProvider:
    return create_asr_provider(settings)


def get_tts_service(
    settings: Settings = Depends(get_settings),
    provider: TTSProvider = Depends(get_tts_provider),
) -> TTSService:
    return TTSService(provider, settings)


def get_expression_plan_service(
    connection: sqlite3.Connection = Depends(get_connection),
    messages: MessageRepository = Depends(get_message_repository),
) -> ExpressionPlanService:
    return ExpressionPlanService(
        messages,
        ExpressionPlanRepository(connection),
        ExpressionPlanPolicy(),
    )


def get_expression_query_service(
    connection: sqlite3.Connection = Depends(get_read_only_connection),
) -> ExpressionPlanService:
    return ExpressionPlanService(
        MessageRepository(connection),
        ExpressionPlanRepository(connection),
        ExpressionPlanPolicy(),
    )


def get_message_bound_tts_service(
    messages: MessageRepository = Depends(get_message_repository),
    plans: ExpressionPlanService = Depends(get_expression_plan_service),
    tts: TTSService = Depends(get_tts_service),
) -> MessageBoundTTSService:
    return MessageBoundTTSService(messages, plans, TTSExpressionMapper(), tts)


def get_asr_service(
    settings: Settings = Depends(get_settings),
    provider: ASRProvider = Depends(get_asr_provider),
) -> ASRService:
    return ASRService(provider, settings)


def get_chat_service(
    settings: Settings = Depends(get_settings),
    sessions: SessionRepository = Depends(get_session_repository),
    messages: MessageRepository = Depends(get_message_repository),
    memories: MemoryRepository = Depends(get_memory_repository),
    prompt_renderer: PromptRenderer = Depends(get_prompt_renderer),
    provider: LLMProvider = Depends(get_llm_provider),
    memory_candidates: MemoryCandidateService = Depends(get_memory_candidate_service),
    memory_embeddings: MemoryEmbeddingService | None = Depends(get_memory_embedding_service),
    summary_scheduler: SessionSummaryScheduler = Depends(get_session_summary_scheduler),
    emotion_service: EmotionService = Depends(get_emotion_service),
    emotion_updater: CompletedTurnEmotionUpdater = Depends(get_completed_turn_emotion_updater),
    emotion_analysis_scheduler: EmotionAnalysisScheduler = Depends(get_emotion_analysis_scheduler),
    expression_plans: ExpressionPlanService = Depends(get_expression_plan_service),
) -> ChatService:
    context_builder = ContextBuilder(
        messages,
        settings.recent_context_messages,
        memories=memories,
        memory_context_enabled=settings.memory_context_enabled,
        memory_context_limit=settings.memory_context_limit,
        memory_retrieval_mode=settings.memory_retrieval_mode,
        memory_retrieval_fallback_limit=settings.memory_retrieval_fallback_limit,
        memory_embedding_service=memory_embeddings,
        memory_embedding_min_score=settings.memory_embedding_min_score,
        emotion_context_formatter=EmotionContextFormatter(),
    )
    return ChatService(
        sessions,
        messages,
        context_builder,
        prompt_renderer,
        provider,
        settings,
        memory_candidates=memory_candidates,
        summary_scheduler=summary_scheduler,
        emotion_updater=emotion_updater,
        emotion_analysis_scheduler=emotion_analysis_scheduler,
        emotion_snapshot_reader=emotion_service,
        expression_plans=expression_plans,
    )
