from fastapi import APIRouter, Depends, Query, Response, status
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import (
    get_memory_audit_repository,
    get_memory_automation_repository,
    get_memory_conflict_resolution_service,
    get_memory_embedding_service,
    get_memory_extraction_dispatch_fence,
    get_memory_forget_service,
    get_relationship_disclosure_fence,
    get_summary_disclosure_fence,
    get_memory_repository,
    get_memory_source_reference_service,
    get_memory_write_dispatch_fence,
    get_session_repository,
    get_versioned_memory_mutation_service,
    get_versioned_memory_repository,
)
from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError, ValidationAppError
from app.domain.models import (
    Memory,
    MemoryAuditEvent,
    MemoryConflict,
    MemoryConflictResolutionKind,
    MemoryConflictStatus,
    MemoryDeletionScope,
    MemoryEvidence,
    MemoryExtractionConsent,
    MemoryExtractionConsentStatus,
    MemoryJob,
    MemoryJobAudit,
    MemoryStatus,
    MemoryType,
    MemoryVersion,
    MemoryWriteConsent,
    MemoryWriteConsentStatus,
)
from app.domain.schemas import (
    ConfirmMemoryCandidateRequest,
    CreateMemoryRequest,
    MemoryAuditEventResponse,
    MemoryConflictPageResponse,
    MemoryConflictResolutionRequest,
    MemoryConflictResolutionResponse,
    MemoryConflictResponse,
    MemoryEvidencePageResponse,
    MemoryEvidenceResponse,
    MemoryExtractionConsentResponse,
    MemoryForgetRequest,
    MemoryForgetResponse,
    MemoryJobAuditResponse,
    MemoryJobResponse,
    MemoryMutationResponse,
    MemoryResponse,
    MemoryUndoResponse,
    MemoryVersionPageResponse,
    MemoryVersionResponse,
    MemoryWriteConsentResponse,
    ReplaceConflictRequest,
    UpdateMemoryExtractionConsentRequest,
    UpdateMemoryRequest,
    UpdateMemoryWriteConsentRequest,
)
from app.providers.factory import memory_extractor_provider_is_configured
from app.repositories.memory_automation import MemoryAutomationRepository
from app.repositories.memory_audit import MemoryAuditRepository
from app.repositories.memories import MemoryRepository
from app.repositories.sessions import SessionRepository
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.services.memory_conflict_resolution import (
    ConflictResolutionPayload,
    MemoryConflictResolutionService,
)
from app.services.memory_embedding_service import MemoryEmbeddingService
from app.services.memory_extraction_dispatch import (
    MEMORY_EXTRACTION_DISCLOSED_FIELDS,
    MEMORY_EXTRACTION_DISCLOSURE_VERSION,
    MEMORY_EXTRACTION_PURPOSE,
    MemoryExtractionDispatchFence,
)
from app.services.memory_forget_service import MemoryForgetResult, MemoryForgetService
from app.services.relationship_dispatch import RelationshipDisclosureFence
from app.services.summary_dispatch import SummaryDisclosureFence
from app.services.memory_gate_b_contract import (
    MEMORY_ALLOWED_AUTO_TYPES,
    MEMORY_ALLOWED_AUTO_TYPES_VERSION,
    MEMORY_WRITE_POLICY_VERSION,
    MEMORY_WRITE_PURPOSE,
    MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION,
)
from app.services.memory_write_dispatch import MemoryWriteDispatchFence
from app.services.memory_source_reference import MemorySourceReferenceService
from app.services.versioned_memory_mutation import VersionedMemoryMutationService

router = APIRouter(prefix="/api/memories", tags=["memories"])


def _memory_response(memory: Memory) -> MemoryResponse:
    return MemoryResponse.model_validate(memory, from_attributes=True)


def _audit_response(event: MemoryAuditEvent) -> MemoryAuditEventResponse:
    return MemoryAuditEventResponse.model_validate(event, from_attributes=True)


def _consent_response(
    consent: MemoryExtractionConsent,
    settings: Settings,
) -> MemoryExtractionConsentResponse:
    deployment_configured = (
        settings.memory_extractor_route != "remote"
        or memory_extractor_provider_is_configured(settings)
    )
    return MemoryExtractionConsentResponse(
        scope_id=consent.scope_id,
        status=consent.status.value,
        purpose=consent.purpose,
        provider=consent.provider,
        disclosure_version=consent.disclosure_version,
        disclosed_fields=list(consent.disclosed_fields),
        generation=consent.generation,
        deployment_route=settings.memory_extractor_route,
        deployment_provider=settings.memory_extractor_provider,
        deployment_configured=deployment_configured,
        created_at=consent.created_at,
        updated_at=consent.updated_at,
    )


def _write_consent_response(consent: MemoryWriteConsent) -> MemoryWriteConsentResponse:
    return MemoryWriteConsentResponse(
        scope_id=consent.scope_id,
        status=consent.status.value,
        purpose=consent.purpose,
        policy_version=consent.policy_version,
        retention_disclosure_version=consent.retention_disclosure_version,
        allowed_memory_types_version=consent.allowed_memory_types_version,
        allowed_memory_types=[item.value for item in consent.allowed_memory_types],
        generation=consent.generation,
        granted_at=consent.granted_at,
        created_at=consent.created_at,
        updated_at=consent.updated_at,
    )


def _memory_job_response(job: MemoryJob) -> MemoryJobResponse:
    return MemoryJobResponse.model_validate(job, from_attributes=True)


def _memory_job_audit_response(audit: MemoryJobAudit) -> MemoryJobAuditResponse:
    return MemoryJobAuditResponse.model_validate(audit, from_attributes=True)


def _version_response(item: MemoryVersion) -> MemoryVersionResponse:
    return MemoryVersionResponse.model_validate(item, from_attributes=True)


def _evidence_response(item: MemoryEvidence) -> MemoryEvidenceResponse:
    return MemoryEvidenceResponse.model_validate(item, from_attributes=True)


def _conflict_response(item: MemoryConflict) -> MemoryConflictResponse:
    return MemoryConflictResponse.model_validate(item, from_attributes=True)


def _forget_response(result: MemoryForgetResult) -> MemoryForgetResponse:
    return MemoryForgetResponse(
        scope=result.scope.value,
        scope_id=result.scope_id,
        forgotten_memory_ids=list(result.forgotten_memory_ids),
        forgotten_candidate_ids=list(result.forgotten_candidate_ids),
        deletion_generation=result.deletion_generation,
        summary_barrier_generation=result.summary_barrier_generation,
    )


def _ensure_embedding(memory_embeddings: MemoryEmbeddingService | None, memory: Memory) -> None:
    if memory_embeddings is None or memory.status != MemoryStatus.ACTIVE:
        return
    try:
        memory_embeddings.ensure_embedding(memory)
    except Exception:
        pass


@router.get("/extraction/consent", response_model=MemoryExtractionConsentResponse)
def get_memory_extraction_consent(
    settings: Settings = Depends(get_settings),
    automation: MemoryAutomationRepository = Depends(get_memory_automation_repository),
) -> MemoryExtractionConsentResponse:
    return _consent_response(automation.get_consent(), settings)


@router.put("/extraction/consent", response_model=MemoryExtractionConsentResponse)
async def update_memory_extraction_consent(
    request: UpdateMemoryExtractionConsentRequest,
    settings: Settings = Depends(get_settings),
    automation: MemoryAutomationRepository = Depends(get_memory_automation_repository),
    fence: MemoryExtractionDispatchFence = Depends(get_memory_extraction_dispatch_fence),
) -> MemoryExtractionConsentResponse:
    statuses = {
        "grant": MemoryExtractionConsentStatus.GRANTED,
        "decline": MemoryExtractionConsentStatus.DECLINED,
        "revoke": MemoryExtractionConsentStatus.REVOKED,
    }
    mutation = fence.begin_consent_mutation()
    async with mutation:
        consent = automation.set_consent(
            status=statuses[request.action],
            purpose=MEMORY_EXTRACTION_PURPOSE,
            provider=settings.memory_extractor_provider,
            disclosure_version=MEMORY_EXTRACTION_DISCLOSURE_VERSION,
            disclosed_fields=MEMORY_EXTRACTION_DISCLOSED_FIELDS,
        )
    return _consent_response(consent, settings)


@router.get(
    "/automation/write-consent",
    response_model=MemoryWriteConsentResponse,
)
def get_memory_write_consent(
    automation: MemoryAutomationRepository = Depends(get_memory_automation_repository),
) -> MemoryWriteConsentResponse:
    return _write_consent_response(automation.get_write_consent())


@router.put(
    "/automation/write-consent",
    response_model=MemoryWriteConsentResponse,
)
async def update_memory_write_consent(
    request: UpdateMemoryWriteConsentRequest,
    automation: MemoryAutomationRepository = Depends(get_memory_automation_repository),
    fence: MemoryWriteDispatchFence = Depends(get_memory_write_dispatch_fence),
) -> MemoryWriteConsentResponse:
    statuses = {
        "grant": MemoryWriteConsentStatus.GRANTED,
        "decline": MemoryWriteConsentStatus.DECLINED,
        "revoke": MemoryWriteConsentStatus.REVOKED,
    }
    mutation = fence.begin_write_consent_mutation()
    async with mutation:
        consent = automation.set_write_consent(
            status=statuses[request.action],
            purpose=MEMORY_WRITE_PURPOSE,
            policy_version=MEMORY_WRITE_POLICY_VERSION,
            allowed_memory_types_version=MEMORY_ALLOWED_AUTO_TYPES_VERSION,
            allowed_memory_types=MEMORY_ALLOWED_AUTO_TYPES,
            retention_disclosure_version=MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION,
        )
    return _write_consent_response(consent)


@router.get("/jobs", response_model=list[MemoryJobResponse])
def list_memory_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    automation: MemoryAutomationRepository = Depends(get_memory_automation_repository),
) -> list[MemoryJobResponse]:
    return [_memory_job_response(job) for job in automation.list_jobs(limit=limit)]


@router.get("/jobs/audits", response_model=list[MemoryJobAuditResponse])
def list_memory_job_audits(
    limit: int = Query(default=20, ge=1, le=100),
    automation: MemoryAutomationRepository = Depends(get_memory_automation_repository),
) -> list[MemoryJobAuditResponse]:
    return [_memory_job_audit_response(audit) for audit in automation.list_audits(limit=limit)]


@router.get("/audit-events", response_model=list[MemoryAuditEventResponse])
def list_memory_audit_events(
    limit: int = Query(default=20, ge=1, le=100),
    audit: MemoryAuditRepository = Depends(get_memory_audit_repository),
) -> list[MemoryAuditEventResponse]:
    return [_audit_response(event) for event in audit.list_recent(limit=limit)]


@router.get("/conflicts", response_model=MemoryConflictPageResponse)
def list_memory_conflicts(
    status_filter: MemoryConflictStatus = Query(
        default=MemoryConflictStatus.OPEN,
        alias="status",
    ),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
    versioned: VersionedMemoryRepository = Depends(get_versioned_memory_repository),
) -> MemoryConflictPageResponse:
    try:
        page = versioned.list_conflicts(
            status=status_filter,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        raise ValidationAppError("分页游标无效。") from exc
    return MemoryConflictPageResponse(
        items=[_conflict_response(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.post(
    "/conflicts/{conflict_id}/resolve",
    response_model=MemoryConflictResolutionResponse,
)
async def resolve_memory_conflict(
    conflict_id: str,
    request: MemoryConflictResolutionRequest,
    service: MemoryConflictResolutionService = Depends(
        get_memory_conflict_resolution_service
    ),
    disclosure_fence: SummaryDisclosureFence = Depends(
        get_summary_disclosure_fence
    ),
) -> MemoryConflictResolutionResponse:
    replacement = request if isinstance(request, ReplaceConflictRequest) else None
    async with disclosure_fence.begin_mutation():
        result = await run_in_threadpool(
            service.resolve,
            conflict_id,
            ConflictResolutionPayload(
                kind=MemoryConflictResolutionKind(request.kind),
                content=replacement.content if replacement else None,
                memory_type=(
                    MemoryType(replacement.memory_type) if replacement else None
                ),
                subject=replacement.subject if replacement else None,
                importance=replacement.importance if replacement else 3,
                confidence=replacement.confidence if replacement else 1.0,
                canonical_subject_code=(
                    replacement.canonical_subject_code if replacement else None
                ),
            ),
        )
    return MemoryConflictResolutionResponse(
        conflict=_conflict_response(result.conflict),
        resolved_memory=(
            _memory_response(result.resolved_memory)
            if result.resolved_memory is not None
            else None
        ),
    )


@router.post("/forget", response_model=MemoryForgetResponse)
async def forget_memory_scope(
    request: MemoryForgetRequest,
    service: MemoryForgetService = Depends(get_memory_forget_service),
    disclosure_fence: SummaryDisclosureFence = Depends(
        get_summary_disclosure_fence
    ),
) -> MemoryForgetResponse:
    scope = MemoryDeletionScope(request.scope)
    async with disclosure_fence.begin_mutation():
        result = await run_in_threadpool(
            service.forget_scope,
            scope=scope,
            scope_id=request.scope_id,
        )
    return _forget_response(result)


@router.get("/{memory_id}/versions", response_model=MemoryVersionPageResponse)
def list_memory_versions(
    memory_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
    memories: MemoryRepository = Depends(get_memory_repository),
    versioned: VersionedMemoryRepository = Depends(get_versioned_memory_repository),
    source_references: MemorySourceReferenceService = Depends(
        get_memory_source_reference_service
    ),
) -> MemoryVersionPageResponse:
    memories.require(memory_id)
    versioned.bootstrap_legacy(
        memory_id,
        source_references=source_references,
    )
    try:
        page = versioned.list_versions(memory_id, limit=limit, cursor=cursor)
    except ValueError as exc:
        raise ValidationAppError("分页游标无效。") from exc
    return MemoryVersionPageResponse(
        items=[_version_response(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.get("/{memory_id}/evidence", response_model=MemoryEvidencePageResponse)
def list_memory_evidence(
    memory_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
    memories: MemoryRepository = Depends(get_memory_repository),
    versioned: VersionedMemoryRepository = Depends(get_versioned_memory_repository),
) -> MemoryEvidencePageResponse:
    memories.require(memory_id)
    try:
        page = versioned.list_evidence(memory_id, limit=limit, cursor=cursor)
    except ValueError as exc:
        raise ValidationAppError("分页游标无效。") from exc
    return MemoryEvidencePageResponse(
        items=[_evidence_response(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.post("/{memory_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
def archive_memory(
    memory_id: str,
    mutations: VersionedMemoryMutationService = Depends(
        get_versioned_memory_mutation_service
    ),
) -> Response:
    try:
        mutations.archive(memory_id)
    except ValueError as exc:
        raise ValidationAppError("只能归档正式记忆。") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{memory_id}/forget", response_model=MemoryForgetResponse)
async def forget_memory(
    memory_id: str,
    memories: MemoryRepository = Depends(get_memory_repository),
    service: MemoryForgetService = Depends(get_memory_forget_service),
    relationship_fence: RelationshipDisclosureFence = Depends(
        get_relationship_disclosure_fence
    ),
    disclosure_fence: SummaryDisclosureFence = Depends(
        get_summary_disclosure_fence
    ),
) -> MemoryForgetResponse:
    memories.require(memory_id)
    # Lock order: RelationshipDisclosureFence before SummaryDisclosureFence.
    async with relationship_fence.begin_mutation():
        async with disclosure_fence.begin_mutation():
            result = await run_in_threadpool(service.forget_memory, memory_id)
    return _forget_response(result)


@router.post("/{memory_id}/undo-latest-auto", response_model=MemoryUndoResponse)
async def undo_latest_auto_memory_change(
    memory_id: str,
    service: MemoryConflictResolutionService = Depends(
        get_memory_conflict_resolution_service
    ),
    disclosure_fence: SummaryDisclosureFence = Depends(
        get_summary_disclosure_fence
    ),
) -> MemoryUndoResponse:
    async with disclosure_fence.begin_mutation():
        result = await run_in_threadpool(service.undo_latest_auto, memory_id)
    return MemoryUndoResponse(
        memory_id=result.memory_id,
        action=result.action,
        memory=_memory_response(result.memory) if result.memory is not None else None,
    )


@router.post("/{memory_id}/confirm", response_model=MemoryMutationResponse)
def confirm_memory_candidate(
    memory_id: str,
    request: ConfirmMemoryCandidateRequest | None = None,
    mutations: VersionedMemoryMutationService = Depends(
        get_versioned_memory_mutation_service
    ),
    memory_embeddings: MemoryEmbeddingService | None = Depends(get_memory_embedding_service),
) -> MemoryMutationResponse:
    try:
        memory, conflicts = mutations.confirm_candidate(
            memory_id,
            canonical_subject_code=(
                request.canonical_subject_code if request is not None else None
            ),
        )
    except ValueError as exc:
        raise ValidationAppError("只能确认待确认记忆。") from exc
    _ensure_embedding(memory_embeddings, memory)
    return MemoryMutationResponse(
        memory=_memory_response(memory),
        conflicts=[_memory_response(conflict) for conflict in conflicts],
    )


@router.post("/{memory_id}/dismiss", response_model=MemoryResponse)
def dismiss_memory_candidate(
    memory_id: str,
    memories: MemoryRepository = Depends(get_memory_repository),
) -> MemoryResponse:
    try:
        memory = memories.dismiss_candidate(memory_id)
    except ValueError as exc:
        raise ValidationAppError("只能忽略待确认记忆。") from exc
    return _memory_response(memory)


@router.get("", response_model=list[MemoryResponse])
def list_memories(
    status_filter: str = "active",
    memories: MemoryRepository = Depends(get_memory_repository),
) -> list[MemoryResponse]:
    status_value = MemoryStatus(status_filter)
    return [_memory_response(memory) for memory in memories.list(status=status_value)]


@router.post("", response_model=MemoryMutationResponse, status_code=status.HTTP_201_CREATED)
def create_memory(
    request: CreateMemoryRequest,
    mutations: VersionedMemoryMutationService = Depends(
        get_versioned_memory_mutation_service
    ),
    sessions: SessionRepository = Depends(get_session_repository),
    memory_embeddings: MemoryEmbeddingService | None = Depends(get_memory_embedding_service),
) -> MemoryMutationResponse:
    if request.source_session_id is not None:
        sessions.require(request.source_session_id)
    memory, conflicts = mutations.create_manual(
        content=request.content,
        memory_type=MemoryType(request.memory_type),
        source_session_id=request.source_session_id,
        importance=request.importance,
        confidence=request.confidence,
        metadata=request.metadata,
        canonical_subject_code=request.canonical_subject_code,
    )
    _ensure_embedding(memory_embeddings, memory)
    return MemoryMutationResponse(
        memory=_memory_response(memory),
        conflicts=[_memory_response(conflict) for conflict in conflicts],
    )


@router.patch("/{memory_id}", response_model=MemoryMutationResponse)
def update_memory(
    memory_id: str,
    request: UpdateMemoryRequest,
    mutations: VersionedMemoryMutationService = Depends(
        get_versioned_memory_mutation_service
    ),
    memory_embeddings: MemoryEmbeddingService | None = Depends(get_memory_embedding_service),
) -> MemoryMutationResponse:
    try:
        memory, conflicts = mutations.update(
            memory_id,
            content=request.content,
            memory_type=(
                MemoryType(request.memory_type)
                if request.memory_type is not None
                else None
            ),
            importance=request.importance,
            confidence=request.confidence,
            metadata=request.metadata,
            canonical_subject_code=request.canonical_subject_code,
            canonical_subject_code_provided=(
                "canonical_subject_code" in request.model_fields_set
            ),
        )
    except ValueError as exc:
        raise ValidationAppError("只能修改正式记忆。") from exc
    _ensure_embedding(memory_embeddings, memory)
    return MemoryMutationResponse(
        memory=_memory_response(memory),
        conflicts=[_memory_response(conflict) for conflict in conflicts],
    )


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(
    memory_id: str,
    mutations: VersionedMemoryMutationService = Depends(
        get_versioned_memory_mutation_service
    ),
) -> Response:
    try:
        mutations.archive(memory_id)
    except ValueError as exc:
        raise ValidationAppError("只能归档正式记忆。") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
