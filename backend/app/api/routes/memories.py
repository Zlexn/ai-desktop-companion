from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import get_memory_audit_repository, get_memory_embedding_service, get_memory_repository, get_session_repository
from app.core.errors import ValidationAppError
from app.domain.models import Memory, MemoryAuditEvent, MemoryAuditOperation, MemorySource, MemoryStatus, MemoryType
from app.domain.schemas import CreateMemoryRequest, MemoryAuditEventResponse, MemoryMutationResponse, MemoryResponse, UpdateMemoryRequest
from app.repositories.memory_audit import MemoryAuditRepository
from app.repositories.memories import MemoryRepository
from app.repositories.sessions import SessionRepository
from app.services.memory_embedding_service import MemoryEmbeddingService

router = APIRouter(prefix="/api/memories", tags=["memories"])


def _memory_response(memory: Memory) -> MemoryResponse:
    return MemoryResponse.model_validate(memory, from_attributes=True)


def _audit_response(event: MemoryAuditEvent) -> MemoryAuditEventResponse:
    return MemoryAuditEventResponse.model_validate(event, from_attributes=True)


def _record_conflicts(
    audit: MemoryAuditRepository,
    *,
    memory: Memory,
    conflicts: list[Memory],
    operation: MemoryAuditOperation,
) -> None:
    if not conflicts:
        return
    audit.record_conflict(
        memory_id=memory.id,
        related_memory_ids=[conflict.id for conflict in conflicts],
        operation=operation,
        metadata={"conflict_count": len(conflicts)},
    )


def _ensure_embedding(memory_embeddings: MemoryEmbeddingService | None, memory: Memory) -> None:
    if memory_embeddings is None or memory.status != MemoryStatus.ACTIVE:
        return
    try:
        memory_embeddings.ensure_embedding(memory)
    except Exception:
        pass


def _delete_embedding(memory_embeddings: MemoryEmbeddingService | None, memory_id: str) -> None:
    if memory_embeddings is None:
        return
    try:
        memory_embeddings.delete_embedding(memory_id)
    except Exception:
        pass


@router.get("/audit-events", response_model=list[MemoryAuditEventResponse])
def list_memory_audit_events(
    limit: int = Query(default=20, ge=1, le=100),
    audit: MemoryAuditRepository = Depends(get_memory_audit_repository),
) -> list[MemoryAuditEventResponse]:
    return [_audit_response(event) for event in audit.list_recent(limit=limit)]


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
    memories: MemoryRepository = Depends(get_memory_repository),
    sessions: SessionRepository = Depends(get_session_repository),
    audit: MemoryAuditRepository = Depends(get_memory_audit_repository),
    memory_embeddings: MemoryEmbeddingService | None = Depends(get_memory_embedding_service),
) -> MemoryMutationResponse:
    if request.source_session_id is not None:
        sessions.require(request.source_session_id)
    memory, conflicts = memories.create(
        content=request.content,
        memory_type=MemoryType(request.memory_type),
        source=MemorySource.MANUAL,
        source_session_id=request.source_session_id,
        importance=request.importance,
        confidence=request.confidence,
        metadata=request.metadata,
    )
    _record_conflicts(audit, memory=memory, conflicts=conflicts, operation=MemoryAuditOperation.CREATE)
    _ensure_embedding(memory_embeddings, memory)
    return MemoryMutationResponse(
        memory=_memory_response(memory),
        conflicts=[_memory_response(conflict) for conflict in conflicts],
    )


@router.patch("/{memory_id}", response_model=MemoryMutationResponse)
def update_memory(
    memory_id: str,
    request: UpdateMemoryRequest,
    memories: MemoryRepository = Depends(get_memory_repository),
    audit: MemoryAuditRepository = Depends(get_memory_audit_repository),
    memory_embeddings: MemoryEmbeddingService | None = Depends(get_memory_embedding_service),
) -> MemoryMutationResponse:
    memory, conflicts = memories.update(
        memory_id,
        content=request.content,
        memory_type=MemoryType(request.memory_type) if request.memory_type is not None else None,
        importance=request.importance,
        confidence=request.confidence,
        metadata=request.metadata,
    )
    _record_conflicts(audit, memory=memory, conflicts=conflicts, operation=MemoryAuditOperation.UPDATE)
    _ensure_embedding(memory_embeddings, memory)
    return MemoryMutationResponse(
        memory=_memory_response(memory),
        conflicts=[_memory_response(conflict) for conflict in conflicts],
    )


@router.post("/{memory_id}/confirm", response_model=MemoryMutationResponse)
def confirm_memory_candidate(
    memory_id: str,
    memories: MemoryRepository = Depends(get_memory_repository),
    audit: MemoryAuditRepository = Depends(get_memory_audit_repository),
    memory_embeddings: MemoryEmbeddingService | None = Depends(get_memory_embedding_service),
) -> MemoryMutationResponse:
    try:
        memory, conflicts = memories.confirm_candidate(memory_id)
    except ValueError as exc:
        raise ValidationAppError("只能确认待确认记忆。") from exc
    _record_conflicts(audit, memory=memory, conflicts=conflicts, operation=MemoryAuditOperation.CONFIRM_CANDIDATE)
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


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(
    memory_id: str,
    memories: MemoryRepository = Depends(get_memory_repository),
    memory_embeddings: MemoryEmbeddingService | None = Depends(get_memory_embedding_service),
) -> Response:
    memories.require(memory_id)
    memories.archive(memory_id)
    _delete_embedding(memory_embeddings, memory_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
