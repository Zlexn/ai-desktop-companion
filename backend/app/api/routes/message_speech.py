from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_message_bound_tts_service
from app.api.routes.audio import speech_response, speech_stream_events
from app.domain.schemas import MessageBoundSynthesizeSpeechRequest
from app.services.message_bound_tts_service import MessageBoundTTSService

router = APIRouter(prefix="/api/messages", tags=["audio"])


@router.post("/{assistant_message_id}/speech")
async def synthesize_message_speech(
    assistant_message_id: str,
    request: MessageBoundSynthesizeSpeechRequest,
    service: MessageBoundTTSService = Depends(get_message_bound_tts_service),
) -> Response:
    result = await service.synthesize(
        assistant_message_id,
        request.voice_id,
        request.speed,
    )
    return speech_response(result)


@router.post("/{assistant_message_id}/speech/stream")
async def synthesize_message_speech_stream(
    assistant_message_id: str,
    request: MessageBoundSynthesizeSpeechRequest,
    service: MessageBoundTTSService = Depends(get_message_bound_tts_service),
) -> StreamingResponse:
    iterator = speech_stream_events(
        service.synthesize_stream(
            assistant_message_id,
            request.voice_id,
            request.speed,
        )
    )
    first = await anext(iterator)

    async def body() -> AsyncIterator[bytes]:
        yield first
        async for event in iterator:
            yield event

    return StreamingResponse(body(), media_type="application/x-ndjson")
