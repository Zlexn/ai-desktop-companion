from fastapi import APIRouter, Depends, Response, status

from app.api.dependencies import get_session_repository
from app.domain.schemas import CreateSessionRequest, SessionResponse
from app.repositories.sessions import SessionRepository

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
def delete_session(
    session_id: str,
    sessions: SessionRepository = Depends(get_session_repository),
) -> Response:
    sessions.require(session_id)
    sessions.delete(session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
