from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.dependencies import build_session_summary_provider
from app.providers.base import LLMProvider
from app.providers.factory import create_emotion_analysis_provider
from app.repositories.emotion_analysis import EmotionAnalysisRepository
from app.repositories.emotions import EmotionRepository
from app.repositories.memories import MemoryRepository
from app.api.routes import (
    audio,
    chat,
    emotion,
    health,
    memories,
    message_expression,
    message_speech,
    sessions,
)
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.core.resources import close_async_resource
from app.repositories.messages import MessageRepository
from app.repositories.session_summaries import SessionSummaryRepository
from app.repositories.sqlite import managed_connection
from app.services.emotion_analysis_analyzer import LLMEmotionAnalyzer
from app.services.emotion_analysis_dispatch import EmotionAnalysisDispatchFence
from app.services.emotion_analysis_input import EmotionAnalysisInputBuilder
from app.services.emotion_analysis_scheduler import InProcessEmotionAnalysisScheduler
from app.services.emotion_analysis_service import EmotionAnalysisService
from app.services.emotion_policy import EmotionPolicy
from app.services.session_summary_provider import (
    SessionSummaryProvider,
    close_session_summary_provider,
)
from app.services.session_summary_scheduler import InProcessSessionSummaryScheduler
from app.services.session_summary_service import SessionSummaryService


def create_app(
    summary_provider_factory: Callable[[], SessionSummaryProvider] | None = None,
    emotion_analysis_provider_factory: Callable[[], LLMProvider | None] | None = None,
) -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        summary_provider = (
            summary_provider_factory()
            if summary_provider_factory is not None
            else build_session_summary_provider(settings)
        )
        with managed_connection(settings.database_url):
            pass

        async def run_summary_job(session_id: str) -> None:
            with managed_connection(settings.database_url) as connection:
                service = SessionSummaryService(
                    messages=MessageRepository(connection),
                    summaries=SessionSummaryRepository(connection),
                    provider=summary_provider,
                    settings=settings,
                )
                await service.maybe_generate_for_session(session_id)

        summary_scheduler = InProcessSessionSummaryScheduler(run_summary_job)
        app.state.session_summary_scheduler = summary_scheduler

        analysis_provider = (
            emotion_analysis_provider_factory()
            if emotion_analysis_provider_factory is not None
            else create_emotion_analysis_provider(settings)
        )
        emotion_analysis_dispatch_fence = EmotionAnalysisDispatchFence()
        app.state.emotion_analysis_dispatch_fence = emotion_analysis_dispatch_fence
        with managed_connection(settings.database_url) as connection:
            EmotionAnalysisRepository(connection).recover_incomplete_jobs()

        async def run_emotion_analysis_job(
            user_message_id: str,
            assistant_message_id: str,
            base_emotion_version: int,
        ) -> None:
            if analysis_provider is None:
                return
            with managed_connection(settings.database_url) as connection:
                messages = MessageRepository(connection)
                assistant_message = messages.get(assistant_message_id)
                user_message = messages.get(user_message_id)
                if (
                    assistant_message is None
                    or user_message is None
                    or user_message.session_id != assistant_message.session_id
                    or user_message.role.value != "user"
                    or assistant_message.role.value != "assistant"
                ):
                    return
                memories = MemoryRepository(connection).list_relevant_for_context(
                    user_message.content,
                    settings.emotion_analysis_memory_limit,
                    0,
                )
                service = EmotionAnalysisService(
                    enabled=settings.emotion_analysis_enabled,
                    provider_name=settings.emotion_analysis_provider,
                    model=settings.emotion_analysis_model,
                    policy_fingerprint=settings.emotion_analysis_policy_fingerprint(),
                    analysis_repository=EmotionAnalysisRepository(connection),
                    emotion_repository=EmotionRepository(connection),
                    policy=EmotionPolicy(),
                    input_builder=EmotionAnalysisInputBuilder(
                        recent_message_limit=settings.emotion_analysis_recent_messages,
                        memory_limit=settings.emotion_analysis_memory_limit,
                        max_item_characters=settings.emotion_analysis_max_item_characters,
                        max_total_characters=settings.emotion_analysis_max_total_characters,
                    ),
                    analyzer=LLMEmotionAnalyzer(
                        provider=analysis_provider,
                        model=settings.emotion_analysis_model,
                        max_tokens=settings.emotion_analysis_max_tokens,
                        timeout_seconds=settings.emotion_analysis_timeout_seconds,
                        max_retries=settings.emotion_analysis_max_retries,
                    ),
                    dispatch_fence=emotion_analysis_dispatch_fence,
                )
                await service.process_turn(
                    session_id=assistant_message.session_id,
                    user_message=user_message,
                    assistant_message=assistant_message,
                    recent_messages=messages.list_recent(
                        assistant_message.session_id,
                        settings.emotion_analysis_recent_messages,
                    ),
                    relevant_memories=memories,
                    base_emotion_version=base_emotion_version,
                )

        emotion_analysis_scheduler = InProcessEmotionAnalysisScheduler(
            run_emotion_analysis_job
        )
        app.state.emotion_analysis_scheduler = emotion_analysis_scheduler
        try:
            yield
        finally:
            await emotion_analysis_scheduler.shutdown()
            await summary_scheduler.shutdown()
            if analysis_provider is not None:
                await close_async_resource(analysis_provider)
            await close_session_summary_provider(summary_provider)

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(sessions.router)
    app.include_router(chat.router)
    app.include_router(audio.router)
    app.include_router(message_speech.router)
    app.include_router(message_expression.router)
    app.include_router(memories.router)
    app.include_router(emotion.router)

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        error = exc.to_response()
        return JSONResponse(
            status_code=error.status_code,
            content={"error": {"code": error.code, "message": error.message}},
        )

    return app


app = create_app()
