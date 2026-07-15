from fastapi import APIRouter, Depends

from app.api.dependencies import get_chat_service, get_message_repository, get_session_repository
from app.domain.schemas import ChatMetadata, ChatResponse, MessageResponse, SendMessageRequest
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.services.chat_service import ChatService

router = APIRouter(prefix="/api/sessions/{session_id}", tags=["chat"])


@router.get("/messages", response_model=list[MessageResponse])
def list_messages(
    session_id: str,
    sessions: SessionRepository = Depends(get_session_repository),
    messages: MessageRepository = Depends(get_message_repository),
) -> list[MessageResponse]:
    sessions.require(session_id)
    return [MessageResponse.model_validate(message, from_attributes=True) for message in messages.list(session_id)]


@router.post("/messages", response_model=ChatResponse)
async def send_message(
    session_id: str,
    request: SendMessageRequest,
    chat_service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    reply = await chat_service.send_message(session_id, request.content)
    return ChatResponse(
        reply=reply.reply,
        metadata=ChatMetadata(provider=reply.provider, model=reply.model),
        assistant_message_id=reply.assistant_message_id,
    )
