from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import (
    audio,
    chat,
    emotion,
    health,
    memories,
    message_expression,
    message_speech,
    persona,
    sessions,
    summaries,
)
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.core.resources import close_async_resource
from app.domain.models import (
    MemoryAutomationMode,
    MemoryAutoActiveJobSnapshot,
    MemoryExtractorRoute,
    MemoryJobAuditOutcome,
    MemoryJobStatus,
)
from app.domain.session_summary import SummaryJob
from app.providers.base import LLMProvider
from app.providers.factory import (
    create_emotion_analysis_provider,
    create_memory_extractor_provider,
    create_provider,
    create_session_summary_llm_provider,
    memory_extractor_provider_is_configured,
)
from app.repositories.emotion_analysis import EmotionAnalysisRepository
from app.repositories.emotions import EmotionRepository
from app.repositories.memories import MemoryRepository
from app.repositories.memory_automation import MemoryAutomationRepository
from app.repositories.summary_automation import SummaryAutomationRepository
from app.repositories.personas import PersonaRepository
from app.repositories.messages import MessageRepository
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.repositories.sqlite import (
    managed_connection,
    memory_source_references_exist,
)
from app.services.emotion_analysis_analyzer import LLMEmotionAnalyzer
from app.services.emotion_analysis_dispatch import EmotionAnalysisDispatchFence
from app.services.emotion_analysis_input import EmotionAnalysisInputBuilder
from app.services.emotion_analysis_scheduler import InProcessEmotionAnalysisScheduler
from app.services.emotion_analysis_service import EmotionAnalysisService
from app.services.emotion_policy import EmotionPolicy
from app.services.memory_extraction_dispatch import MemoryExtractionDispatchFence
from app.services.memory_extraction_contract import memory_remote_authority_fingerprint
from app.services.memory_extractor import (
    LocalMemoryExtractor,
    MemoryExtractionFakeProvider,
    ProviderMemoryExtractor,
)
from app.services.memory_governor import MEMORY_GOVERNOR_VERSION, MemoryGovernor
from app.services.memory_gate_b_contract import (
    MEMORY_ALLOWED_AUTO_TYPES_VERSION,
    MEMORY_AUTO_ACTIVE_SCHEMA_VERSION,
    MEMORY_CANONICALIZATION_VERSION,
    MEMORY_COMMIT_POLICY_VERSION,
)
from app.services.memory_commit_policy import MemoryCommitPolicy
from app.services.memory_job_scheduler import (
    InProcessMemoryJobScheduler,
    NoOpMemoryJobScheduler,
)
from app.services.memory_job_service import (
    AutoActiveMemoryJobService,
    MemoryJobService,
    memory_job_is_compatible,
)
from app.services.memory_source_reference import MemorySourceReferenceService
from app.services.memory_write_dispatch import (
    MemoryWriteDispatchFence,
    MemoryWriteDispatcher,
)
from app.services.persona_compiler import PersonaCompiler
from app.services.persona_service import PersonaService
from app.services.prompt_renderer import default_prompt_renderer
from app.services.versioned_memory_commit import VersionedMemoryCommitService
from app.services.session_deletion_coordinator import SessionDeletionFence
from app.services.session_summary_provider import (
    LLMSessionSummaryProvider,
    SessionSummaryProvider,
)
from app.services.session_summary_scheduler import (
    DurableSessionSummaryScheduler,
    NoOpSessionSummaryScheduler,
)
from app.services.session_summary_service import SummaryJobReservationService
from app.services.session_summary_contract import (
    SUMMARY_JOB_SCHEMA_VERSION,
    SUMMARY_SCHEMA_VERSION,
)
from app.services.summary_dispatch import (
    SummaryDisclosureFence,
    SummaryProcessingFence,
)
from app.services.summary_job_service import SummaryJobService


def validate_memory_automation_capability(settings: Settings) -> None:
    del settings


def create_app(
    summary_provider_factory: Callable[[], SessionSummaryProvider] | None = None,
    emotion_analysis_provider_factory: Callable[[], LLMProvider | None] | None = None,
    chat_provider_factory: Callable[[], LLMProvider] | None = None,
    memory_extractor_provider_factory: Callable[[], LLMProvider | None] | None = None,
    settings_override: Settings | None = None,
    persona_bootstrap_source: Callable[[], dict[str, object]] | None = None,
) -> FastAPI:
    settings = settings_override or get_settings()
    validate_memory_automation_capability(settings)
    configure_logging(settings)
    prompt_renderer = default_prompt_renderer()
    persona_compiler = PersonaCompiler(
        template_text=prompt_renderer.load_template_text(),
        persona_max_characters=settings.persona_max_characters,
    )
    load_persona_bootstrap = (
        persona_bootstrap_source or prompt_renderer.load_persona_v1_config
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        chat_provider: LLMProvider | None = None
        memory_provider: LLMProvider | None = None
        memory_scheduler: InProcessMemoryJobScheduler | None = None
        analysis_provider: LLMProvider | None = None
        summary_scheduler = None
        emotion_analysis_scheduler = None
        try:
            chat_provider = (
                chat_provider_factory()
                if chat_provider_factory is not None
                else create_provider(settings)
            )
            app.state.llm_provider = chat_provider

            with managed_connection(settings.database_url) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    source_reference_service = (
                        MemorySourceReferenceService.load_or_create(
                            settings.memory_source_reference_key_path,
                            references_exist=lambda: memory_source_references_exist(
                                connection
                            ),
                        )
                    )
                except Exception:
                    connection.rollback()
                    raise
                else:
                    connection.commit()
            app.state.memory_source_reference_service = source_reference_service

            with managed_connection(settings.database_url) as connection:
                personas = PersonaRepository(connection)
                startup_state = personas.inspect_startup_state()
                persona_service = PersonaService(
                    personas,
                    compiler=persona_compiler,
                    bootstrap_config=load_persona_bootstrap,
                )
                if (
                    startup_state.artifact_count == 0
                    and startup_state.active_state is None
                ):
                    persona_service.bootstrap()
                else:
                    persona_service.verify_existing_startup_state(startup_state)
            app.state.persona_compiler = persona_compiler

            if settings.session_summary_enabled:
                def read_summary_session_deletion_generation(session_id: str) -> int:
                    with managed_connection(settings.database_url) as connection:
                        return VersionedMemoryRepository(
                            connection
                        ).read_deletion_generations(
                            session_reference_hash=(
                                source_reference_service.session_hash(session_id)
                            )
                        ).session_generation

                app.state.summary_session_deletion_generation = (
                    read_summary_session_deletion_generation
                )

                def reserve_summary_job(session_id: str, chat_turn_id: str):
                    with managed_connection(settings.database_url) as connection:
                        return SummaryJobReservationService(
                            connection,
                            settings=settings,
                            session_deletion_generation=(
                                lambda source_session_id: VersionedMemoryRepository(
                                    connection
                                ).read_deletion_generations(
                                    session_reference_hash=(
                                        source_reference_service.session_hash(
                                            source_session_id
                                        )
                                    )
                                ).session_generation
                            ),
                        ).reserve_for_turn(session_id, chat_turn_id)

                def recover_summary_jobs() -> tuple[list[SummaryJob], list[str]]:
                    with managed_connection(settings.database_url) as connection:
                        return SummaryAutomationRepository(
                            connection
                        ).prepare_recovery_jobs(
                            stale_before=(
                                datetime.now(UTC)
                                - timedelta(
                                    seconds=(
                                        settings.summary_job_recovery_stale_seconds
                                    )
                                )
                            ),
                            job_schema_version=SUMMARY_JOB_SCHEMA_VERSION,
                            summarizer_schema_version=SUMMARY_SCHEMA_VERSION,
                            max_attempts=settings.summary_job_max_attempts,
                        )

                summary_processing_fence = SummaryProcessingFence()
                summary_disclosure_fence = SummaryDisclosureFence()
                app.state.summary_processing_fence = summary_processing_fence
                app.state.summary_disclosure_fence = summary_disclosure_fence

                def build_remote_summary_provider() -> SessionSummaryProvider:
                    if summary_provider_factory is not None:
                        return summary_provider_factory()
                    llm_provider = create_session_summary_llm_provider(settings)
                    return LLMSessionSummaryProvider(
                        llm_provider=llm_provider,
                        model=settings.session_summary_llm_model,
                    )

                async def run_summary_job(
                    job_id: str,
                    expected_session_id: str,
                ) -> None:
                    await SummaryJobService(
                        database_url=settings.database_url,
                        settings=settings,
                        processing_fence=summary_processing_fence,
                        session_deletion_generation=(
                            read_summary_session_deletion_generation
                        ),
                        remote_provider_factory=(
                            build_remote_summary_provider
                            if settings.session_summary_provider == "llm"
                            else None
                        ),
                    ).process(
                        job_id,
                        expected_session_id=expected_session_id,
                    )

                def mutate_summary_job(method: str, job_id: str) -> None:
                    with managed_connection(settings.database_url) as connection:
                        getattr(SummaryAutomationRepository(connection), method)(job_id)

                summary_scheduler = DurableSessionSummaryScheduler(
                    reserve_for_turn=reserve_summary_job,
                    run_job=run_summary_job,
                    recover_job_ids=recover_summary_jobs,
                    fail_incompatible=lambda job_id: mutate_summary_job(
                        "fail_incompatible_job", job_id
                    ),
                    cancel_job=lambda job_id: mutate_summary_job(
                        "cancel_job", job_id
                    ),
                    fail_job=lambda job_id: mutate_summary_job("fail_job", job_id),
                )
                await summary_scheduler.recover()
            else:
                summary_scheduler = NoOpSessionSummaryScheduler()
                app.state.summary_session_deletion_generation = (
                    lambda _session_id: 0
                )
                app.state.summary_processing_fence = SummaryProcessingFence()
                app.state.summary_disclosure_fence = SummaryDisclosureFence()
            app.state.summary_processing_available = bool(
                settings.session_summary_enabled
            )
            app.state.summary_injection_available = bool(
                settings.session_summary_enabled
            )
            if not settings.session_summary_enabled:
                app.state.remote_summary_capability = "summary_disabled"
            elif settings.session_summary_provider == "llm":
                app.state.remote_summary_capability = (
                    "remote_summary_available_requires_consent"
                )
            else:
                app.state.remote_summary_capability = "local_summary_available"
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
                    relevant_memories = MemoryRepository(
                        connection
                    ).list_relevant_for_context(
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
                        relevant_memories=relevant_memories,
                        base_emotion_version=base_emotion_version,
                    )

            emotion_analysis_scheduler = InProcessEmotionAnalysisScheduler(
                run_emotion_analysis_job
            )
            app.state.emotion_analysis_scheduler = emotion_analysis_scheduler

            memory_dispatch_fence = MemoryExtractionDispatchFence()
            write_dispatch_fence = MemoryWriteDispatchFence()
            session_deletion_fence = SessionDeletionFence()
            app.state.memory_extraction_dispatch_fence = memory_dispatch_fence
            app.state.memory_write_dispatch_fence = write_dispatch_fence
            app.state.session_deletion_fence = session_deletion_fence
            app.state.memory_job_scheduler = NoOpMemoryJobScheduler()

            configured_mode = MemoryAutomationMode(settings.memory_automation_mode)
            configured_route = MemoryExtractorRoute(settings.memory_extractor_route)
            if configured_mode not in {
                MemoryAutomationMode.SHADOW_AUTO,
                MemoryAutomationMode.AUTO_ACTIVE,
            }:
                with managed_connection(settings.database_url) as connection:
                    MemoryAutomationRepository(
                        connection
                    ).reconcile_incomplete_jobs(compatible_job=lambda _job: False)

            if settings.memory_automation_mode in {
                MemoryAutomationMode.SHADOW_AUTO.value,
                MemoryAutomationMode.AUTO_ACTIVE.value,
            }:
                route = MemoryExtractorRoute(settings.memory_extractor_route)
                extractor = None
                if route is MemoryExtractorRoute.LOCAL:
                    extractor = LocalMemoryExtractor(settings)
                elif route is MemoryExtractorRoute.FAKE:
                    extractor = ProviderMemoryExtractor(
                        MemoryExtractionFakeProvider(settings), settings
                    )
                elif (
                    route is MemoryExtractorRoute.REMOTE
                    and memory_extractor_provider_is_configured(settings)
                ):
                    memory_provider = (
                        memory_extractor_provider_factory()
                        if memory_extractor_provider_factory is not None
                        else create_memory_extractor_provider(settings)
                    )
                    if memory_provider is not None:
                        extractor = ProviderMemoryExtractor(memory_provider, settings)

                governor = MemoryGovernor(
                    max_proposals=settings.memory_extractor_max_proposals,
                    max_proposal_characters=(
                        settings.memory_extractor_max_proposal_characters
                    ),
                    max_total_characters=settings.memory_extractor_max_total_characters,
                )

                mode = MemoryAutomationMode(settings.memory_automation_mode)

                async def run_memory_job(job_id: str) -> None:
                    with managed_connection(settings.database_url) as connection:
                        automation = MemoryAutomationRepository(connection)
                        if mode is MemoryAutomationMode.SHADOW_AUTO:
                            service = MemoryJobService(
                                automation=automation,
                                messages=MessageRepository(connection),
                                extractor=extractor,
                                governor=governor,
                                route=route,
                                provider_name=settings.memory_extractor_provider,
                                dispatch_fence=memory_dispatch_fence,
                            )
                        else:
                            dispatcher = MemoryWriteDispatcher(
                                write_fence=write_dispatch_fence,
                                read_write_consent=automation.get_write_consent,
                                remote_fence=(
                                    memory_dispatch_fence
                                    if route is MemoryExtractorRoute.REMOTE
                                    else None
                                ),
                                read_remote_consent=(
                                    automation.get_consent
                                    if route is MemoryExtractorRoute.REMOTE
                                    else None
                                ),
                                remote_provider=(
                                    settings.memory_extractor_provider
                                    if route is MemoryExtractorRoute.REMOTE
                                    else None
                                ),
                            )
                            versioned = VersionedMemoryRepository(connection)
                            commit_service = VersionedMemoryCommitService(
                                connection,
                                versioned=versioned,
                                policy=MemoryCommitPolicy(),
                                source_references=source_reference_service,
                                semantic_retries=settings.memory_commit_semantic_retries,
                            )
                            def snapshot_commit_targets():
                                versioned.bootstrap_all_active_legacy(
                                    source_references=source_reference_service,
                                )
                                return versioned.list_commit_targets()

                            service = AutoActiveMemoryJobService(
                                automation=automation,
                                messages=MessageRepository(connection),
                                extractor=extractor,
                                governor=governor,
                                route=route,
                                dispatcher=dispatcher,
                                source_references=source_reference_service,
                                commit_one=commit_service.commit_one,
                                commit_targets=snapshot_commit_targets,
                                deletion_fence=session_deletion_fence,
                            )
                        await service.process(job_id)

                def reserve_memory_job(**kwargs):
                    with managed_connection(settings.database_url) as connection:
                        return MemoryAutomationRepository(connection).reserve_job(
                            **kwargs
                        )

                def recover_memory_job_ids() -> list[str]:
                    with managed_connection(settings.database_url) as connection:
                        return MemoryAutomationRepository(
                            connection
                        ).recover_incomplete_jobs(
                            compatible_job=(
                                lambda job: memory_job_is_compatible(
                                    job,
                                    mode=mode,
                                    route=route,
                                )
                            ),
                        )

                def build_active_reservation(
                    *,
                    session_id: str,
                    user_message_id: str,
                    assistant_message_id: str,
                    persona_artifact_id: str,
                    chat_turn_id: str | None = None,
                    turn_completed_at=None,
                ) -> dict[str, object]:
                    with managed_connection(settings.database_url) as connection:
                        automation = MemoryAutomationRepository(connection)
                        write_consent = automation.get_write_consent()
                        remote_generation = None
                        remote_fingerprint = None
                        if route is MemoryExtractorRoute.REMOTE:
                            remote_consent = automation.get_consent()
                            remote_generation = remote_consent.generation
                            remote_fingerprint = memory_remote_authority_fingerprint(
                                generation=remote_consent.generation,
                                purpose=remote_consent.purpose or "",
                                provider=remote_consent.provider or "",
                                disclosure_version=(
                                    remote_consent.disclosure_version or ""
                                ),
                                disclosed_fields=remote_consent.disclosed_fields,
                            )
                        session_hash = source_reference_service.session_hash(session_id)
                        deletion_snapshot = VersionedMemoryRepository(
                            connection
                        ).read_deletion_generations(
                            session_reference_hash=session_hash
                        )
                    snapshot = MemoryAutoActiveJobSnapshot(
                        reserved_mode=MemoryAutomationMode.AUTO_ACTIVE,
                        workflow_version=MEMORY_AUTO_ACTIVE_SCHEMA_VERSION,
                        extractor_route=route,
                        governor_version=MEMORY_GOVERNOR_VERSION,
                        commit_policy_version=MEMORY_COMMIT_POLICY_VERSION,
                        canonicalization_version=MEMORY_CANONICALIZATION_VERSION,
                        allowed_memory_types_version=MEMORY_ALLOWED_AUTO_TYPES_VERSION,
                        write_consent_generation=write_consent.generation,
                        remote_consent_generation=remote_generation,
                        remote_authority_fingerprint=remote_fingerprint,
                        global_deletion_generation=deletion_snapshot.global_generation,
                        session_deletion_generation=deletion_snapshot.session_generation,
                        type_deletion_generations={
                            memory_type.value: generation
                            for memory_type, generation
                            in deletion_snapshot.type_generations.items()
                        },
                        source_session_reference_hash=session_hash,
                        source_user_message_reference_hash=(
                            source_reference_service.message_hash(user_message_id)
                        ),
                        source_assistant_message_reference_hash=(
                            source_reference_service.message_hash(assistant_message_id)
                        ),
                        turn_completed_at=turn_completed_at,
                    )
                    reservation = {
                        "turn_id": assistant_message_id,
                        "schema_version": MEMORY_AUTO_ACTIVE_SCHEMA_VERSION,
                        "session_id": session_id,
                        "user_message_id": user_message_id,
                        "assistant_message_id": assistant_message_id,
                        "persona_artifact_id": persona_artifact_id,
                        "mode": MemoryAutomationMode.AUTO_ACTIVE,
                        "extractor_route": route,
                        "governor_version": MEMORY_GOVERNOR_VERSION,
                        "auto_active_snapshot": snapshot,
                        "source_session_reference_hash": (
                            snapshot.source_session_reference_hash
                        ),
                        "source_user_message_reference_hash": (
                            snapshot.source_user_message_reference_hash
                        ),
                        "source_assistant_message_reference_hash": (
                            snapshot.source_assistant_message_reference_hash
                        ),
                    }
                    if chat_turn_id is not None:
                        reservation["chat_turn_id"] = chat_turn_id
                    return reservation

                def cancel_memory_job(job_id: str) -> None:
                    with managed_connection(settings.database_url) as connection:
                        MemoryAutomationRepository(connection).cancel_job(job_id)

                def fail_memory_job(job_id: str) -> None:
                    with managed_connection(settings.database_url) as connection:
                        MemoryAutomationRepository(connection).complete_job_with_audit(
                            job_id,
                            status=MemoryJobStatus.FAILED,
                            outcome=MemoryJobAuditOutcome.FAILED,
                            decision_counts={},
                            reason_counts={},
                            proposal_count=0,
                            accepted_count=0,
                            rejected_count=0,
                            redaction_count=0,
                            provider=None,
                            model=None,
                            elapsed_ms=None,
                            consent_generation=None,
                            error_category="database_error",
                        )

                memory_scheduler = InProcessMemoryJobScheduler(
                    reserve_job=reserve_memory_job,
                    run_job=run_memory_job,
                    recover_job_ids=recover_memory_job_ids,
                    cancel_job=cancel_memory_job,
                    fail_job=fail_memory_job,
                    mode=mode,
                    route=route,
                    reservation_factory=(
                        build_active_reservation
                        if mode is MemoryAutomationMode.AUTO_ACTIVE
                        else None
                    ),
                )
                app.state.memory_job_scheduler = memory_scheduler
                await memory_scheduler.recover()

            yield
        finally:
            closed_resource_ids: set[int] = set()

            async def close_owned_resource(resource: object | None) -> None:
                if resource is None or id(resource) in closed_resource_ids:
                    return
                closed_resource_ids.add(id(resource))
                await close_async_resource(resource)

            if memory_scheduler is not None:
                await memory_scheduler.shutdown()
            if emotion_analysis_scheduler is not None:
                await emotion_analysis_scheduler.shutdown()
            if summary_scheduler is not None:
                await summary_scheduler.shutdown()
            await close_owned_resource(memory_provider)
            await close_owned_resource(analysis_provider)
            await close_owned_resource(chat_provider)

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    if settings_override is not None:
        app.dependency_overrides[get_settings] = lambda: settings
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
    app.include_router(persona.router)
    app.include_router(summaries.router)

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        error = exc.to_response()
        return JSONResponse(
            status_code=error.status_code,
            content={"error": {"code": error.code, "message": error.message}},
        )

    return app


app = create_app()
