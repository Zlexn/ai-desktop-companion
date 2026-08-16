from collections.abc import Iterator
import sqlite3

from fastapi import Depends, Request

from app.asr.base import ASRProvider
from app.asr.factory import create_asr_provider
from app.core.config import Settings, get_settings
from app.providers.base import LLMProvider
from app.repositories.chat_turns import ChatTurnRepository
from app.repositories.context_sources import ContextSourceRepository
from app.repositories.emotion_analysis import EmotionAnalysisRepository
from app.repositories.memory_automation import MemoryAutomationRepository
from app.repositories.personas import PersonaRepository
from app.repositories.memory_audit import MemoryAuditRepository
from app.repositories.emotions import EmotionRepository
from app.repositories.expression_plans import ExpressionPlanRepository
from app.repositories.memories import MemoryRepository
from app.repositories.memory_embeddings import MemoryEmbeddingRepository
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection, resolve_sqlite_path
from app.repositories.summary_automation import SummaryAutomationRepository
from app.repositories.summary_public import SummaryPublicRepository
from app.repositories.summary_selection import SummarySelectionRepository
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.services.chat_service import ChatService
from app.services.context_composer import ContextComposer
from app.services.context_data_encoder import ContextDataEncoder
from app.services.emotion_analysis_dispatch import EmotionAnalysisDispatchFence
from app.services.emotion_analysis_scheduler import EmotionAnalysisScheduler
from app.services.emotion_policy import EmotionPolicy
from app.services.emotion_context import EmotionContextFormatter
from app.services.emotion_service import CompletedTurnEmotionUpdater, EmotionService
from app.services.expression_plan_policy import ExpressionPlanPolicy
from app.services.expression_plan_service import ExpressionPlanService
from app.services.memory_extraction_dispatch import MemoryExtractionDispatchFence
from app.services.memory_job_scheduler import MemoryJobScheduler
from app.services.memory_source_reference import MemorySourceReferenceService
from app.services.memory_write_dispatch import MemoryWriteDispatchFence
from app.services.memory_candidate_service import MemoryCandidateService
from app.services.message_bound_tts_service import MessageBoundTTSService
from app.services.memory_embedding_service import (
    FakeMemoryEmbeddingProvider,
    MemoryEmbeddingProvider,
    MemoryEmbeddingService,
    SentenceTransformersMemoryEmbeddingProvider,
)
from app.services.memory_forget_service import MemoryForgetService
from app.services.memory_conflict_resolution import MemoryConflictResolutionService
from app.services.relationship_hooks import (
    NoOpRelationshipChangeNotifier,
    RelationshipChangeNotifier,
)
from app.services.session_deletion_coordinator import (
    SessionDeletionCoordinator,
    SessionDeletionFence,
)
from app.services.prompt_renderer import PromptRenderer, default_prompt_renderer
from app.services.persona_service import PersonaService
from app.services.session_summary_provider import (
    FakeSessionSummaryProvider,
    SessionSummaryProvider,
)
from app.services.session_summary_scheduler import SessionSummaryScheduler
from app.services.asr_service import ASRService
from app.services.session_summary_service import (
    build_summary_injection_policy,
    build_summary_processing_policy,
)
from app.services.summary_invalidation import SummaryInvalidationService
from app.services.summary_rebuild import SummaryRebuildService
from app.services.summary_dispatch import (
    SummaryDisclosureFence,
    SummaryProcessingFence,
)
from app.services.tts_service import TTSService
from app.services.versioned_memory_mutation import VersionedMemoryMutationService
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


def get_chat_turn_repository(
    connection: sqlite3.Connection = Depends(get_connection),
) -> ChatTurnRepository:
    return ChatTurnRepository(connection)


def get_memory_source_reference_service(
    request: Request,
) -> MemorySourceReferenceService:
    return request.app.state.memory_source_reference_service


def get_memory_repository(
    connection: sqlite3.Connection = Depends(get_connection),
    source_references: MemorySourceReferenceService = Depends(
        get_memory_source_reference_service
    ),
) -> MemoryRepository:
    return MemoryRepository(
        connection,
        source_references=source_references,
    )


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


def get_llm_provider(request: Request) -> LLMProvider:
    return request.app.state.llm_provider


def build_session_summary_provider(settings: Settings) -> SessionSummaryProvider:
    if settings.session_summary_provider == "fake":
        return FakeSessionSummaryProvider()
    raise ValueError(
        "remote summary Providers are constructed only by the fenced Task 7 worker"
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


def get_versioned_memory_repository(
    connection: sqlite3.Connection = Depends(get_connection),
) -> VersionedMemoryRepository:
    return VersionedMemoryRepository(connection)


def get_memory_automation_repository(
    connection: sqlite3.Connection = Depends(get_connection),
) -> MemoryAutomationRepository:
    return MemoryAutomationRepository(connection)


def get_memory_extraction_dispatch_fence(
    request: Request,
) -> MemoryExtractionDispatchFence:
    return request.app.state.memory_extraction_dispatch_fence


def get_memory_write_dispatch_fence(
    request: Request,
) -> MemoryWriteDispatchFence:
    return request.app.state.memory_write_dispatch_fence


def get_memory_job_scheduler(request: Request) -> MemoryJobScheduler:
    return request.app.state.memory_job_scheduler


def get_relationship_change_notifier(
    request: Request,
) -> RelationshipChangeNotifier:
    return getattr(
        request.app.state,
        "relationship_change_notifier",
        NoOpRelationshipChangeNotifier(),
    )


def get_versioned_memory_mutation_service(
    connection: sqlite3.Connection = Depends(get_connection),
    source_references: MemorySourceReferenceService = Depends(
        get_memory_source_reference_service
    ),
    relationship_notifier: RelationshipChangeNotifier = Depends(
        get_relationship_change_notifier
    ),
) -> VersionedMemoryMutationService:
    return VersionedMemoryMutationService(
        connection,
        memories=MemoryRepository(
            connection,
            source_references=source_references,
        ),
        versioned=VersionedMemoryRepository(connection),
        source_references=source_references,
        relationship_notifier=relationship_notifier,
    )


def get_session_deletion_fence(request: Request) -> SessionDeletionFence:
    return request.app.state.session_deletion_fence


def get_session_deletion_coordinator(
    connection: sqlite3.Connection = Depends(get_connection),
    source_references: MemorySourceReferenceService = Depends(
        get_memory_source_reference_service
    ),
    deletion_fence: SessionDeletionFence = Depends(get_session_deletion_fence),
) -> SessionDeletionCoordinator:
    return SessionDeletionCoordinator(
        connection,
        versioned=VersionedMemoryRepository(connection),
        source_references=source_references,
        deletion_fence=deletion_fence,
    )


def get_summary_processing_fence(request: Request) -> SummaryProcessingFence:
    return request.app.state.summary_processing_fence


def get_summary_disclosure_fence(request: Request) -> SummaryDisclosureFence:
    return request.app.state.summary_disclosure_fence


def get_summary_automation_repository(
    connection: sqlite3.Connection = Depends(get_connection),
) -> SummaryAutomationRepository:
    return SummaryAutomationRepository(connection)


def get_summary_public_repository(
    connection: sqlite3.Connection = Depends(get_connection),
) -> SummaryPublicRepository:
    return SummaryPublicRepository(connection)


def get_summary_invalidation_service(
    settings: Settings = Depends(get_settings),
) -> SummaryInvalidationService:
    return SummaryInvalidationService(settings.database_url)


def get_summary_rebuild_service(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> SummaryRebuildService:
    return SummaryRebuildService(
        settings.database_url,
        settings=settings,
        session_deletion_generation=(
            request.app.state.summary_session_deletion_generation
        ),
    )


def get_summary_processing_policy(
    settings: Settings = Depends(get_settings),
):
    return build_summary_processing_policy(settings)


def get_summary_injection_policy(
    settings: Settings = Depends(get_settings),
):
    return build_summary_injection_policy(settings)


def get_memory_conflict_resolution_service(
    connection: sqlite3.Connection = Depends(get_connection),
    source_references: MemorySourceReferenceService = Depends(
        get_memory_source_reference_service
    ),
    relationship_notifier: RelationshipChangeNotifier = Depends(
        get_relationship_change_notifier
    ),
) -> MemoryConflictResolutionService:
    versioned = VersionedMemoryRepository(connection)
    memories = MemoryRepository(
        connection,
        source_references=source_references,
    )
    forget = MemoryForgetService(
        connection,
        versioned=versioned,
        source_references=source_references,
    )
    return MemoryConflictResolutionService(
        connection,
        versioned=versioned,
        memories=memories,
        forget=forget,
        source_references=source_references,
        relationship_notifier=relationship_notifier,
    )


def get_memory_forget_service(
    connection: sqlite3.Connection = Depends(get_connection),
    source_references: MemorySourceReferenceService = Depends(
        get_memory_source_reference_service
    ),
) -> MemoryForgetService:
    versioned = VersionedMemoryRepository(connection)
    return MemoryForgetService(
        connection,
        versioned=versioned,
        source_references=source_references,
    )


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


def get_persona_service(
    request: Request,
    connection: sqlite3.Connection = Depends(get_connection),
) -> PersonaService:
    return PersonaService(
        PersonaRepository(connection),
        compiler=request.app.state.persona_compiler,
        bootstrap_config={},
    )


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
    request: Request,
    settings: Settings = Depends(get_settings),
    connection: sqlite3.Connection = Depends(get_connection),
    sessions: SessionRepository = Depends(get_session_repository),
    messages: MessageRepository = Depends(get_message_repository),
    chat_turns: ChatTurnRepository = Depends(get_chat_turn_repository),
    memories: MemoryRepository = Depends(get_memory_repository),
    persona_service: PersonaService = Depends(get_persona_service),
    provider: LLMProvider = Depends(get_llm_provider),
    memory_candidates: MemoryCandidateService = Depends(get_memory_candidate_service),
    memory_job_scheduler: MemoryJobScheduler = Depends(get_memory_job_scheduler),
    memory_embeddings: MemoryEmbeddingService | None = Depends(get_memory_embedding_service),
    summary_scheduler: SessionSummaryScheduler = Depends(get_session_summary_scheduler),
    summary_disclosure_fence: SummaryDisclosureFence = Depends(
        get_summary_disclosure_fence
    ),
    emotion_service: EmotionService = Depends(get_emotion_service),
    emotion_updater: CompletedTurnEmotionUpdater = Depends(get_completed_turn_emotion_updater),
    emotion_analysis_scheduler: EmotionAnalysisScheduler = Depends(get_emotion_analysis_scheduler),
    expression_plans: ExpressionPlanService = Depends(get_expression_plan_service),
) -> ChatService:
    summary_policy = build_summary_injection_policy(settings)
    summary_available = bool(
        getattr(request.app.state, "summary_injection_available", False)
    )
    summary_authority = (
        SummaryAutomationRepository(connection).valid_injection_snapshot(
            summary_policy
        )
        if summary_available
        else None
    )
    summary_selection = (
        SummarySelectionRepository(
            connection,
            min_lexical_relevance=(
                settings.summary_injection_min_lexical_relevance
            ),
            session_deletion_generation=(
                request.app.state.summary_session_deletion_generation
            ),
        )
        if summary_authority is not None
        else None
    )
    return ChatService(
        sessions,
        messages,
        chat_turns,
        persona_service,
        ContextSourceRepository(
            messages,
            memories if settings.memory_context_enabled else None,
            memory_retrieval_mode=settings.memory_retrieval_mode,
            memory_embedding_service=memory_embeddings,
            memory_embedding_min_score=settings.memory_embedding_min_score,
            sessions=sessions,
            summary_selection=summary_selection,
            summary_authority=summary_authority,
        ),
        ContextComposer(settings, ContextDataEncoder()),
        provider,
        settings,
        memory_candidates=memory_candidates,
        memory_job_scheduler=memory_job_scheduler,
        summary_scheduler=summary_scheduler,
        emotion_updater=emotion_updater,
        emotion_analysis_scheduler=emotion_analysis_scheduler,
        emotion_snapshot_reader=emotion_service,
        emotion_context_formatter=EmotionContextFormatter(),
        expression_plans=expression_plans,
        summary_disclosure_fence=summary_disclosure_fence,
    )
