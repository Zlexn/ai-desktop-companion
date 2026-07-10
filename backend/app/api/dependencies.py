from collections.abc import Iterator
import sqlite3

from fastapi import Depends

from app.asr.base import ASRProvider
from app.asr.factory import create_asr_provider
from app.core.config import Settings, get_settings
from app.providers.base import LLMProvider
from app.providers.factory import create_provider
from app.repositories.memory_audit import MemoryAuditRepository
from app.repositories.memories import MemoryRepository
from app.repositories.memory_embeddings import MemoryEmbeddingRepository
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.services.chat_service import ChatService
from app.services.context_builder import ContextBuilder
from app.services.memory_candidate_service import MemoryCandidateService
from app.services.memory_embedding_service import (
    FakeMemoryEmbeddingProvider,
    MemoryEmbeddingProvider,
    MemoryEmbeddingService,
    SentenceTransformersMemoryEmbeddingProvider,
)
from app.services.prompt_renderer import PromptRenderer, default_prompt_renderer
from app.services.asr_service import ASRService
from app.services.tts_service import TTSService
from app.tts.base import TTSProvider
from app.tts.factory import create_tts_provider


def get_connection(settings: Settings = Depends(get_settings)) -> Iterator[sqlite3.Connection]:
    with managed_connection(settings.database_url) as connection:
        yield connection


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


def get_llm_provider(settings: Settings = Depends(get_settings)) -> LLMProvider:
    return create_provider(settings)


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
    )
    return ChatService(sessions, messages, context_builder, prompt_renderer, provider, settings, memory_candidates)
