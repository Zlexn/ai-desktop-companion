from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import (
    get_session_summary_scheduler,
    get_summary_automation_repository,
    get_summary_disclosure_fence,
    get_summary_injection_policy,
    get_summary_invalidation_service,
    get_summary_processing_fence,
    get_summary_processing_policy,
    get_summary_public_repository,
    get_summary_rebuild_service,
)
from app.core.config import Settings, get_settings
from app.core.errors import (
    NotFoundError,
    SummaryAuthorityVersionConflictError,
    ValidationAppError,
)
from app.domain.schemas import (
    SummaryAuditPageResponse,
    SummaryAuthorityMutationRequest,
    SummaryCapabilitiesResponse,
    SummaryInjectionConsentResponse,
    SummaryJobMutationRequest,
    SummaryJobPageResponse,
    SummaryMutationResponse,
    SummaryPageResponse,
    SummaryProcessingConsentResponse,
    SummaryRebuildRequest,
    SummaryRedactRequest,
    SummaryStatusResponse,
)
from app.domain.session_summary import (
    SummaryJobKind,
    SummaryJobStatus,
    SummarySuppressionState,
)
from app.repositories.summary_automation import (
    SummaryAutomationRepository,
    SummaryInjectionAuthority,
    SummaryInjectionPolicy,
    SummaryProcessingAuthority,
    SummaryProcessingPolicy,
)
from app.repositories.summary_public import SummaryPublicRepository
from app.services.session_summary_scheduler import SessionSummaryScheduler
from app.services.session_summary_service import summary_provider_policy_for_settings
from app.services.summary_dispatch import (
    SummaryDisclosureFence,
    SummaryProcessingFence,
)
from app.services.summary_invalidation import SummaryInvalidationService
from app.services.summary_rebuild import SummaryRebuildService


router = APIRouter(prefix="/api/summaries", tags=["summaries"])


def _page(
    items,
    has_more: bool,
    *,
    offset: int,
    kind: str,
    filter_value: str | None = None,
):
    return {
        "items": items,
        "next_cursor": (
            SummaryPublicRepository.encode_cursor(
                offset + len(items),
                kind=kind,
                filter_value=filter_value,
            )
            if has_more
            else None
        ),
    }


def _processing_response(
    authority: SummaryProcessingAuthority,
    policy: SummaryProcessingPolicy,
    *,
    valid: bool,
) -> SummaryProcessingConsentResponse:
    return SummaryProcessingConsentResponse(
        scope_id=authority.scope_id,
        status=authority.status.value,
        route=policy.route,
        disclosure_version=policy.disclosure_version,
        purpose=policy.purpose,
        provider=policy.provider,
        model=policy.model,
        disclosed_fields=list(policy.disclosed_fields),
        generation=authority.generation,
        valid_for_current_policy=valid,
        reason_code=None if valid else "not_granted_for_current_policy",
        updated_at=authority.updated_at,
    )


def _injection_response(
    authority: SummaryInjectionAuthority,
    policy: SummaryInjectionPolicy,
    *,
    valid: bool,
) -> SummaryInjectionConsentResponse:
    return SummaryInjectionConsentResponse(
        scope_id=authority.scope_id,
        status=authority.status.value,
        route=policy.route,
        disclosure_version=policy.disclosure_version,
        purpose=policy.purpose,
        provider=policy.chat_provider,
        model=policy.chat_model,
        disclosed_fields=list(policy.disclosed_fields),
        generation=authority.generation,
        max_fragment_count=policy.max_fragment_count,
        max_fragment_characters=policy.max_fragment_characters,
        max_total_characters=policy.max_total_characters,
        valid_for_current_policy=valid,
        reason_code=None if valid else "not_granted_for_current_policy",
        updated_at=authority.updated_at,
    )


def _mutation_error(exc: Exception) -> ValidationAppError:
    if isinstance(exc, SummaryAuthorityVersionConflictError):
        error = ValidationAppError("摘要授权版本已变化。")
        error.status_code = 409
        return error
    return ValidationAppError("摘要操作状态无效。")


def _capability_available(request: Request, kind: str) -> bool:
    return bool(
        getattr(request.app.state, f"summary_{kind}_available", False)
    )


def _require_enabled_action(
    request: Request,
    *,
    kind: str,
    action: str,
) -> None:
    if _capability_available(request, kind):
        return
    if action in {"grant", "enable_local"}:
        raise ValidationAppError("摘要能力当前未启用。")


def _summary_operation_error(message: str) -> ValidationAppError:
    error = ValidationAppError(message)
    error.status_code = 409
    return error


@router.get("/capabilities", response_model=SummaryCapabilitiesResponse)
def capabilities(
    request: Request,
    processing_policy: SummaryProcessingPolicy = Depends(
        get_summary_processing_policy
    ),
    injection_policy: SummaryInjectionPolicy = Depends(
        get_summary_injection_policy
    ),
) -> SummaryCapabilitiesResponse:
    return SummaryCapabilitiesResponse(
        summary_processing=bool(
            getattr(request.app.state, "summary_processing_available", False)
        ),
        summary_injection=bool(
            getattr(request.app.state, "summary_injection_available", False)
        ),
        processing_route=processing_policy.route,
        processing_provider=processing_policy.provider,
        processing_model=processing_policy.model,
        injection_route=injection_policy.route,
        injection_provider=injection_policy.chat_provider,
        injection_model=injection_policy.chat_model,
        remote_summary=getattr(
            request.app.state,
            "remote_summary_capability",
            "not_configured",
        ),
    )


@router.get(
    "/processing-consent",
    response_model=SummaryProcessingConsentResponse,
)
def get_processing_consent(
    request: Request,
    repository: SummaryAutomationRepository = Depends(
        get_summary_automation_repository
    ),
    policy: SummaryProcessingPolicy = Depends(get_summary_processing_policy),
) -> SummaryProcessingConsentResponse:
    authority = repository.get_processing_authority()
    snapshot = repository.valid_processing_snapshot(policy)
    return _processing_response(
        authority,
        policy,
        valid=(
            _capability_available(request, "processing")
            and snapshot is not None
            and snapshot.generation == authority.generation
        ),
    )


@router.put(
    "/processing-consent",
    response_model=SummaryProcessingConsentResponse,
)
async def mutate_processing_consent(
    payload: SummaryAuthorityMutationRequest,
    request: Request,
    repository: SummaryAutomationRepository = Depends(
        get_summary_automation_repository
    ),
    policy: SummaryProcessingPolicy = Depends(get_summary_processing_policy),
    processing_fence: SummaryProcessingFence = Depends(
        get_summary_processing_fence
    ),
) -> SummaryProcessingConsentResponse:
    try:
        _require_enabled_action(
            request,
            kind="processing",
            action=payload.action,
        )
        async with processing_fence.begin_mutation():
            authority = await run_in_threadpool(
                repository.mutate_processing,
                action=payload.action,
                expected_generation=payload.expected_generation,
                policy=policy,
            )
    except (ValueError, SummaryAuthorityVersionConflictError) as exc:
        raise _mutation_error(exc) from exc
    snapshot = repository.valid_processing_snapshot(policy)
    return _processing_response(
        authority,
        policy,
        valid=(
            _capability_available(request, "processing")
            and snapshot is not None
            and snapshot.generation == authority.generation
        ),
    )


@router.get(
    "/injection-consent",
    response_model=SummaryInjectionConsentResponse,
)
def get_injection_consent(
    request: Request,
    repository: SummaryAutomationRepository = Depends(
        get_summary_automation_repository
    ),
    policy: SummaryInjectionPolicy = Depends(get_summary_injection_policy),
) -> SummaryInjectionConsentResponse:
    authority = repository.get_injection_authority()
    snapshot = repository.valid_injection_snapshot(policy)
    return _injection_response(
        authority,
        policy,
        valid=(
            _capability_available(request, "injection")
            and snapshot is not None
            and snapshot.generation == authority.generation
        ),
    )


@router.put(
    "/injection-consent",
    response_model=SummaryInjectionConsentResponse,
)
async def mutate_injection_consent(
    payload: SummaryAuthorityMutationRequest,
    request: Request,
    repository: SummaryAutomationRepository = Depends(
        get_summary_automation_repository
    ),
    policy: SummaryInjectionPolicy = Depends(get_summary_injection_policy),
    disclosure_fence: SummaryDisclosureFence = Depends(
        get_summary_disclosure_fence
    ),
) -> SummaryInjectionConsentResponse:
    try:
        _require_enabled_action(
            request,
            kind="injection",
            action=payload.action,
        )
        async with disclosure_fence.begin_mutation():
            authority = await run_in_threadpool(
                repository.mutate_injection,
                action=payload.action,
                expected_generation=payload.expected_generation,
                policy=policy,
            )
    except (ValueError, SummaryAuthorityVersionConflictError) as exc:
        raise _mutation_error(exc) from exc
    snapshot = repository.valid_injection_snapshot(policy)
    return _injection_response(
        authority,
        policy,
        valid=(
            _capability_available(request, "injection")
            and snapshot is not None
            and snapshot.generation == authority.generation
        ),
    )


@router.get("/status", response_model=SummaryStatusResponse)
def status(
    repository: SummaryPublicRepository = Depends(get_summary_public_repository),
) -> SummaryStatusResponse:
    summary_counts, job_counts = repository.status_counts()
    return SummaryStatusResponse(
        summary_counts=summary_counts,
        job_counts=job_counts,
    )


@router.get("", response_model=SummaryPageResponse)
def list_summaries(
    session_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
    repository: SummaryPublicRepository = Depends(get_summary_public_repository),
) -> SummaryPageResponse:
    try:
        offset = repository.decode_cursor(
            cursor,
            kind="summaries",
            filter_value=session_id,
        )
    except ValueError as exc:
        raise ValidationAppError("分页游标无效。") from exc
    items, has_more = repository.list_summaries(
        session_id=session_id,
        limit=limit,
        offset=offset,
    )
    return SummaryPageResponse(
        **_page(
            items,
            has_more,
            offset=offset,
            kind="summaries",
            filter_value=session_id,
        )
    )


@router.get("/jobs", response_model=SummaryJobPageResponse)
def list_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
    repository: SummaryAutomationRepository = Depends(
        get_summary_automation_repository
    ),
    public: SummaryPublicRepository = Depends(get_summary_public_repository),
) -> SummaryJobPageResponse:
    try:
        offset = public.decode_cursor(cursor, kind="summary_jobs")
    except ValueError as exc:
        raise ValidationAppError("分页游标无效。") from exc
    items, has_more = public.list_jobs(
        repository.list_jobs(),
        limit=limit,
        offset=offset,
    )
    return SummaryJobPageResponse(
        **_page(items, has_more, offset=offset, kind="summary_jobs")
    )


@router.get("/audits", response_model=SummaryAuditPageResponse)
def list_audits(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
    repository: SummaryPublicRepository = Depends(get_summary_public_repository),
) -> SummaryAuditPageResponse:
    try:
        offset = repository.decode_cursor(cursor, kind="summary_audits")
    except ValueError as exc:
        raise ValidationAppError("分页游标无效。") from exc
    items, has_more = repository.list_audits(limit=limit, offset=offset)
    return SummaryAuditPageResponse(
        **_page(items, has_more, offset=offset, kind="summary_audits")
    )


@router.get("/{summary_id}")
def summary_detail(
    summary_id: str,
    repository: SummaryPublicRepository = Depends(get_summary_public_repository),
):
    try:
        return repository.summary_detail(summary_id)
    except KeyError as exc:
        raise NotFoundError("会话概述不存在。") from exc


@router.post("/{summary_id}/redact", response_model=SummaryMutationResponse)
async def redact_summary(
    summary_id: str,
    payload: SummaryRedactRequest,
    service: SummaryInvalidationService = Depends(
        get_summary_invalidation_service
    ),
    disclosure_fence: SummaryDisclosureFence = Depends(
        get_summary_disclosure_fence
    ),
) -> SummaryMutationResponse:
    try:
        async with disclosure_fence.begin_mutation():
            suppression = await run_in_threadpool(
                service.redact_summary,
                summary_id,
                expected_suppression_generation=(
                    payload.expected_suppression_generation
                ),
                confirmation=payload.confirmation,
            )
    except KeyError as exc:
        raise NotFoundError("会话概述不存在。") from exc
    except ValueError as exc:
        if str(exc) == "exact summary is required":
            raise NotFoundError("会话概述不存在。") from exc
        raise ValidationAppError("会话概述清除状态无效。") from exc
    return SummaryMutationResponse(
        outcome="redacted",
        summary_id=summary_id,
        suppression_generation=suppression.generation,
        suppression_state=suppression.state.value,
    )


@router.post("/{summary_id}/rebuild", response_model=SummaryMutationResponse)
async def rebuild_summary(
    summary_id: str,
    payload: SummaryRebuildRequest,
    request: Request,
    service: SummaryRebuildService = Depends(get_summary_rebuild_service),
    scheduler: SessionSummaryScheduler = Depends(get_session_summary_scheduler),
    processing_fence: SummaryProcessingFence = Depends(
        get_summary_processing_fence
    ),
    disclosure_fence: SummaryDisclosureFence = Depends(
        get_summary_disclosure_fence
    ),
) -> SummaryMutationResponse:
    try:
        if not _capability_available(request, "processing"):
            raise ValidationAppError("摘要生成能力当前未启用。")
        async with processing_fence.begin_mutation():
            async with disclosure_fence.begin_mutation():
                suppression = await run_in_threadpool(
                    service.authorize,
                    summary_id=summary_id,
                    expected_suppression_generation=(
                        payload.expected_suppression_generation
                    ),
                )
                job, _created = await run_in_threadpool(
                    service.reserve,
                    suppression.permit_id,
                )
    except KeyError as exc:
        raise NotFoundError("会话概述不存在。") from exc
    except ValueError as exc:
        if str(exc) == "exact summary is required":
            raise NotFoundError("会话概述不存在。") from exc
        raise ValidationAppError("会话概述重建状态无效。") from exc
    scheduler.start_job(job)
    return SummaryMutationResponse(
        outcome="rebuild_scheduled",
        summary_id=summary_id,
        job_id=job.id,
        status=job.status.value,
        suppression_generation=suppression.generation + 1,
        suppression_state="rebuild_in_progress",
    )


@router.post("/jobs/{job_id}/retry", response_model=SummaryMutationResponse)
async def retry_job(
    job_id: str,
    payload: SummaryJobMutationRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
    policy: SummaryProcessingPolicy = Depends(get_summary_processing_policy),
    repository: SummaryAutomationRepository = Depends(
        get_summary_automation_repository
    ),
    processing_fence: SummaryProcessingFence = Depends(
        get_summary_processing_fence
    ),
    rebuild_service: SummaryRebuildService = Depends(get_summary_rebuild_service),
    scheduler: SessionSummaryScheduler = Depends(get_session_summary_scheduler),
) -> SummaryMutationResponse:
    try:
        if not _capability_available(request, "processing"):
            raise _summary_operation_error("摘要生成能力当前未启用。")
        current = repository.require_job(job_id)
        expected_status = SummaryJobStatus(payload.expected_status)
        if current.status is not expected_status:
            raise ValueError("summary job state conflict")
        async with processing_fence.begin_mutation():
            if current.job_kind is SummaryJobKind.REBUILD:
                if (
                    payload.expected_suppression_generation is None
                    or payload.expected_suppression_state is None
                ):
                    raise ValueError("rebuild suppression snapshot is required")
                job, suppression = await run_in_threadpool(
                    rebuild_service.retry,
                    job_id=job_id,
                    expected_job_status=expected_status,
                    expected_suppression_generation=(
                        payload.expected_suppression_generation
                    ),
                    expected_suppression_state=SummarySuppressionState(
                        payload.expected_suppression_state
                    ),
                )
                scheduler.start_job(job)
                return SummaryMutationResponse(
                    outcome="retry_scheduled",
                    job_id=job.id,
                    status=job.status.value,
                    suppression_generation=suppression.generation,
                    suppression_state=suppression.state.value,
                )
            if (
                payload.expected_suppression_generation is not None
                or payload.expected_suppression_state is not None
            ):
                raise ValueError("incremental retry forbids suppression snapshot")
            job, created = await run_in_threadpool(
                repository.retry_job,
                job_id,
                processing_policy=policy,
                provider_policy_fingerprint=(
                    summary_provider_policy_for_settings(settings)
                ),
                session_deletion_generation=(
                    request.app.state.summary_session_deletion_generation(
                        current.session_id
                    )
                ),
            )
    except KeyError as exc:
        raise NotFoundError("会话概述任务不存在。") from exc
    except ValueError as exc:
        raise _summary_operation_error("会话概述任务重试状态已变化。") from exc
    if not created:
        return SummaryMutationResponse(
            outcome="retry_deduplicated",
            job_id=job.id,
            status=job.status.value,
        )
    scheduler.start_job(job)
    return SummaryMutationResponse(
        outcome="retry_scheduled",
        job_id=job.id,
        status=job.status.value,
    )


@router.post("/jobs/{job_id}/cancel", response_model=SummaryMutationResponse)
async def cancel_job(
    job_id: str,
    payload: SummaryJobMutationRequest,
    repository: SummaryAutomationRepository = Depends(
        get_summary_automation_repository
    ),
    processing_fence: SummaryProcessingFence = Depends(
        get_summary_processing_fence
    ),
    rebuild_service: SummaryRebuildService = Depends(get_summary_rebuild_service),
) -> SummaryMutationResponse:
    try:
        current = repository.require_job(job_id)
        if current.status.value != payload.expected_status:
            raise ValueError("summary job state conflict")
        if current.job_kind.value == "rebuild":
            if (
                current.rebuild_permit_id is None
                or payload.expected_suppression_generation is None
                or payload.expected_suppression_state != "rebuild_in_progress"
            ):
                raise ValueError("rebuild suppression snapshot is required")
            async with processing_fence.begin_mutation():
                suppression = await run_in_threadpool(
                    rebuild_service.cancel,
                    current.rebuild_permit_id,
                    expected_suppression_generation=(
                        payload.expected_suppression_generation
                    ),
                )
            return SummaryMutationResponse(
                outcome="cancelled",
                job_id=job_id,
                status="cancelled",
                suppression_generation=suppression.generation,
                suppression_state=suppression.state.value,
            )
        if (
            payload.expected_suppression_generation is not None
            or payload.expected_suppression_state is not None
        ):
            raise ValueError("incremental cancel forbids suppression snapshot")
        async with processing_fence.begin_mutation():
            job = await run_in_threadpool(repository.cancel_api_job, job_id)
    except KeyError as exc:
        raise NotFoundError("会话概述任务不存在。") from exc
    except ValueError as exc:
        raise _summary_operation_error("会话概述任务取消状态已变化。") from exc
    return SummaryMutationResponse(
        outcome="cancelled",
        job_id=job.id,
        status=job.status.value,
    )
