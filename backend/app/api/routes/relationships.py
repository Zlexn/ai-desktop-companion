from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import (
    get_relationship_api_service,
    get_relationship_disclosure_fence,
)
from app.core.errors import NotFoundError, ValidationAppError
from app.domain.relationship import RelationshipEventType
from app.domain.schemas import (
    RelationshipAuditPageResponse,
    RelationshipCapabilitiesResponse,
    RelationshipEventPageResponse,
    RelationshipJobPageResponse,
    RelationshipMutationResponse,
    RelationshipProjectionResponse,
    RelationshipReconcileRequest,
    RelationshipRedactRequest,
    RelationshipReenableRequest,
    RelationshipSuppressRequest,
)
from app.services.relationship_api import (
    RelationshipApiService,
    relationship_api_now,
)
from app.services.relationship_authority import (
    StaleRelationshipAuthorityError,
)
from app.services.relationship_dispatch import RelationshipDisclosureFence

router = APIRouter(prefix="/api/relationship", tags=["relationship"])


def _projection_response(
    service: RelationshipApiService,
) -> RelationshipProjectionResponse:
    view = service.projection()
    if view is None:
        return RelationshipProjectionResponse(available=False)
    return RelationshipProjectionResponse(
        available=True,
        projection_id=view.projection_id,
        projection_version=view.projection_version,
        familiarity_bucket=(
            view.familiarity_bucket.value
            if hasattr(view.familiarity_bucket, "value")
            else str(view.familiarity_bucket)
        ),
        preferred_address=view.preferred_address,
        relationship_summary_code=(
            view.relationship_summary_code.value
            if hasattr(view.relationship_summary_code, "value")
            else str(view.relationship_summary_code)
        ),
        persona_artifact_id=view.persona_artifact_id,
        projection_rule_version=view.projection_rule_version,
        contributing_event_count=view.contributing_event_count,
    )


def _authority_response(authority) -> dict[str, object]:
    return {
        "source_memory_id": authority.source_memory_id,
        "event_type": authority.event_type.value,
        "subject_code": authority.subject_code,
        "decision_id": authority.decision_id,
        "generation": authority.generation,
        "action": authority.action.value if authority.action is not None else None,
        "authority_epoch": authority.authority_epoch,
        "suppressed": authority.suppressed,
    }


def _mutation_error(exc: Exception) -> ValidationAppError:
    if isinstance(exc, StaleRelationshipAuthorityError):
        error = ValidationAppError("关系授权状态已变化。")
        error.status_code = 409
        return error
    if isinstance(exc, NotFoundError):
        return ValidationAppError("关系事件不存在。")
    return ValidationAppError("关系操作状态无效。")


def _reconcile_error(exc: Exception) -> ValidationAppError:
    if isinstance(exc, StaleRelationshipAuthorityError) or (
        isinstance(exc, ValueError) and "projection version is stale" in str(exc)
    ):
        error = ValidationAppError("关系投影版本已变化。")
        error.status_code = 409
        return error
    return ValidationAppError("关系收敛操作失败。")


@router.get("/capabilities", response_model=RelationshipCapabilitiesResponse)
def capabilities() -> RelationshipCapabilitiesResponse:
    return RelationshipCapabilitiesResponse()


@router.get("/projection", response_model=RelationshipProjectionResponse)
def projection(
    service: RelationshipApiService = Depends(get_relationship_api_service),
) -> RelationshipProjectionResponse:
    return _projection_response(service)


@router.get("/events", response_model=RelationshipEventPageResponse)
def list_events(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
    service: RelationshipApiService = Depends(get_relationship_api_service),
) -> RelationshipEventPageResponse:
    try:
        items, next_cursor = service.page(
            service.event_items(),
            limit=limit,
            cursor=cursor,
            kind="relationship_events",
        )
    except ValueError as exc:
        raise ValidationAppError("分页游标无效。") from exc
    return RelationshipEventPageResponse(items=items, next_cursor=next_cursor)


@router.get("/jobs", response_model=RelationshipJobPageResponse)
def list_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
    service: RelationshipApiService = Depends(get_relationship_api_service),
) -> RelationshipJobPageResponse:
    try:
        items, next_cursor = service.page(
            service.job_items(),
            limit=limit,
            cursor=cursor,
            kind="relationship_jobs",
        )
    except ValueError as exc:
        raise ValidationAppError("分页游标无效。") from exc
    return RelationshipJobPageResponse(items=items, next_cursor=next_cursor)


@router.get("/audits", response_model=RelationshipAuditPageResponse)
def list_audits(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
    service: RelationshipApiService = Depends(get_relationship_api_service),
) -> RelationshipAuditPageResponse:
    try:
        items, next_cursor = service.page(
            service.audit_items(),
            limit=limit,
            cursor=cursor,
            kind="relationship_audits",
        )
    except ValueError as exc:
        raise ValidationAppError("分页游标无效。") from exc
    return RelationshipAuditPageResponse(items=items, next_cursor=next_cursor)


@router.post("/reconcile", response_model=RelationshipJobPageResponse)
async def reconcile(
    payload: RelationshipReconcileRequest,
    service: RelationshipApiService = Depends(get_relationship_api_service),
    fence: RelationshipDisclosureFence = Depends(
        get_relationship_disclosure_fence
    ),
) -> RelationshipJobPageResponse:
    try:
        async with fence.begin_mutation():
            await run_in_threadpool(
                service.reconcile,
                now=relationship_api_now(),
                expected_projection_version=payload.expected_projection_version,
            )
    except (ValueError, StaleRelationshipAuthorityError) as exc:
        raise _reconcile_error(exc) from exc
    items, _next = service.page(
        service.job_items(),
        limit=100,
        cursor=None,
        kind="relationship_jobs",
    )
    return RelationshipJobPageResponse(items=items, next_cursor=None)


@router.post("/rebuild", response_model=RelationshipJobPageResponse)
async def rebuild(
    payload: RelationshipReconcileRequest,
    service: RelationshipApiService = Depends(get_relationship_api_service),
    fence: RelationshipDisclosureFence = Depends(
        get_relationship_disclosure_fence
    ),
) -> RelationshipJobPageResponse:
    try:
        async with fence.begin_mutation():
            await run_in_threadpool(
                service.rebuild,
                now=relationship_api_now(),
                expected_projection_version=payload.expected_projection_version,
            )
    except (ValueError, StaleRelationshipAuthorityError) as exc:
        raise _reconcile_error(exc) from exc
    items, _next = service.page(
        service.job_items(),
        limit=100,
        cursor=None,
        kind="relationship_jobs",
    )
    return RelationshipJobPageResponse(items=items, next_cursor=None)


@router.post(
    "/events/{apply_event_id}/suppress",
    response_model=RelationshipMutationResponse,
)
async def suppress_apply(
    apply_event_id: str,
    payload: RelationshipSuppressRequest,
    service: RelationshipApiService = Depends(get_relationship_api_service),
    fence: RelationshipDisclosureFence = Depends(
        get_relationship_disclosure_fence
    ),
) -> RelationshipMutationResponse:
    try:
        async with fence.begin_mutation():
            authority = await run_in_threadpool(
                service.suppress,
                apply_event_id=apply_event_id,
                expected_decision_id=payload.expected_decision_id,
                expected_decision_generation=(
                    payload.expected_decision_generation
                ),
                expected_authority_epoch=payload.expected_authority_epoch,
                now=relationship_api_now(),
            )
    except (ValueError, StaleRelationshipAuthorityError) as exc:
        raise _mutation_error(exc) from exc
    return RelationshipMutationResponse(
        outcome="suppressed",
        authority=_authority_response(authority),
        projection=_projection_response(service),
    )


@router.post(
    "/events/{apply_event_id}/redact",
    response_model=RelationshipMutationResponse,
)
async def redact_apply(
    apply_event_id: str,
    payload: RelationshipRedactRequest,
    service: RelationshipApiService = Depends(get_relationship_api_service),
    fence: RelationshipDisclosureFence = Depends(
        get_relationship_disclosure_fence
    ),
) -> RelationshipMutationResponse:
    try:
        async with fence.begin_mutation():
            authority = await run_in_threadpool(
                service.redact,
                apply_event_id=apply_event_id,
                confirm_irreversible=payload.confirm_irreversible,
                expected_decision_id=payload.expected_decision_id,
                expected_decision_generation=(
                    payload.expected_decision_generation
                ),
                expected_authority_epoch=payload.expected_authority_epoch,
                now=relationship_api_now(),
            )
    except (ValueError, StaleRelationshipAuthorityError) as exc:
        raise _mutation_error(exc) from exc
    return RelationshipMutationResponse(
        outcome="redacted",
        authority=_authority_response(authority),
        projection=_projection_response(service),
    )


@router.post(
    "/authorities/{source_memory_id}/{event_type}/{subject_code}/reenable",
    response_model=RelationshipMutationResponse,
)
async def reenable_authority(
    source_memory_id: str,
    event_type: str,
    subject_code: str,
    payload: RelationshipReenableRequest,
    service: RelationshipApiService = Depends(get_relationship_api_service),
    fence: RelationshipDisclosureFence = Depends(
        get_relationship_disclosure_fence
    ),
) -> RelationshipMutationResponse:
    try:
        parsed_type = RelationshipEventType(event_type)
    except (TypeError, ValueError) as exc:
        raise ValidationAppError("关系事件类型无效。") from exc
    try:
        async with fence.begin_mutation():
            authority = await run_in_threadpool(
                service.reenable,
                source_memory_id=source_memory_id,
                event_type=parsed_type,
                subject_code=subject_code,
                expected_decision_id=payload.expected_decision_id,
                expected_decision_generation=(
                    payload.expected_decision_generation
                ),
                expected_authority_epoch=payload.expected_authority_epoch,
                now=relationship_api_now(),
            )
    except (ValueError, StaleRelationshipAuthorityError) as exc:
        raise _mutation_error(exc) from exc
    return RelationshipMutationResponse(
        outcome="reenabled",
        authority=_authority_response(authority),
        projection=_projection_response(service),
    )
