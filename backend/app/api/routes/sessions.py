from fastapi import APIRouter, Depends, Response, status
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import (
    get_relationship_disclosure_fence,
    get_session_deletion_coordinator,
    get_session_repository,
    get_summary_disclosure_fence,
    get_summary_processing_fence,
)
from app.domain.schemas import CreateSessionRequest, SessionResponse
from app.repositories.sessions import SessionRepository
from app.services.relationship_dispatch import RelationshipDisclosureFence
from app.services.session_deletion_coordinator import SessionDeletionCoordinator
from app.services.summary_dispatch import (
    SummaryDisclosureFence,
    SummaryProcessingFence,
)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    request: CreateSessionRequest,
    sessions: SessionRepository = Depends(get_session_repository),
) -> SessionResponse:
    return SessionResponse.model_validate(sessions.create(request.title), from_attributes=True)


@router.get("", response_model=list[SessionResponse])
def list_sessions(sessions: SessionRepository = Depends(get_session_repository)) -> list[SessionResponse]:
    return [SessionResponse.model_validate(session, from_attributes=True) for session in sessions.list()]


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(
    session_id: str,
    sessions: SessionRepository = Depends(get_session_repository),
) -> SessionResponse:
    return SessionResponse.model_validate(sessions.require(session_id), from_attributes=True)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    coordinator: SessionDeletionCoordinator = Depends(
        get_session_deletion_coordinator
    ),
    processing_fence: SummaryProcessingFence = Depends(
        get_summary_processing_fence
    ),
    relationship_fence: RelationshipDisclosureFence = Depends(
        get_relationship_disclosure_fence
    ),
    disclosure_fence: SummaryDisclosureFence = Depends(
        get_summary_disclosure_fence
    ),
) -> Response:
    # Lock order: SummaryProcessing -> RelationshipDisclosure -> SummaryDisclosure.
    async with processing_fence.begin_mutation():
        async with relationship_fence.begin_mutation():
            async with disclosure_fence.begin_mutation():
                await run_in_threadpool(coordinator.delete, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
