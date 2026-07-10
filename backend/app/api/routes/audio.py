import base64
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_asr_service, get_tts_service
from app.asr.base import TranscriptionFinalEvent, TranscriptionPartialEvent
from app.core.errors import ASRContentTypeMissingError, ASRFileMissingError, ASRFileTooLargeError, TTSError
from app.domain.schemas import SynthesizeSpeechRequest, TranscriptionResponse
from app.services.asr_service import ASRService
from app.services.tts_service import TTSService
from app.tts.base import SpeechSynthesisSegment

router = APIRouter(prefix="/api/audio", tags=["audio"])


def _ndjson_event(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _segment_event(segment: SpeechSynthesisSegment) -> dict[str, object]:
    return {
        "type": "segment",
        "index": segment.index,
        "audio_base64": base64.b64encode(segment.audio_bytes).decode("ascii"),
        "media_type": segment.media_type,
        "duration_ms": segment.duration_ms,
        "sample_rate": segment.sample_rate,
    }


async def _speech_stream_events(tts_service: TTSService, request: SynthesizeSpeechRequest) -> AsyncIterator[bytes]:
    started = False
    count = 0
    try:
        async for segment in tts_service.synthesize_stream(request.text, request.voice_id, request.speed):
            if not started:
                yield _ndjson_event({"type": "start", "provider": segment.provider, "model": segment.model})
                started = True
            yield _ndjson_event(_segment_event(segment))
            count += 1
        if not started:
            yield _ndjson_event({"type": "error", "message": "语音合成服务没有返回可播放音频。"})
            return
        yield _ndjson_event({"type": "done", "segment_count": count})
    except TTSError as exc:
        if not started:
            raise
        yield _ndjson_event({"type": "error", "message": str(exc) or "语音合成失败，请稍后重试。"})


async def _transcription_stream_events(
    asr_service: ASRService,
    chunks: list[UploadFile],
    language: str | None,
) -> AsyncIterator[bytes]:
    raw_chunks: list[bytes] = []
    media_type: str | None = None
    for chunk in chunks:
        content = await chunk.read(asr_service.max_upload_bytes + 1)
        raw_chunks.append(content)
        media_type = media_type or chunk.content_type
        try:
            await chunk.close()
        except Exception:
            pass

    if not raw_chunks:
        raise ASRFileMissingError()
    if not media_type or not media_type.strip():
        raise ASRContentTypeMissingError()

    started = False
    async for event in asr_service.transcribe_stream(raw_chunks, media_type, language):
        if isinstance(event, TranscriptionPartialEvent):
            if not started:
                yield _ndjson_event({"type": "start", "provider": event.provider or "unknown", "model": event.model or "unknown"})
                started = True
            yield _ndjson_event({
                "type": "partial",
                "index": event.index,
                "text": event.text,
                "is_final": event.is_final,
                "audio_ms": event.audio_ms,
            })
        elif isinstance(event, TranscriptionFinalEvent):
            if not started:
                yield _ndjson_event({"type": "start", "provider": event.result.provider, "model": event.result.model})
                started = True
            yield _ndjson_event({
                "type": "final",
                "text": event.result.text,
                "detected_language": event.result.detected_language,
                "duration_ms": event.result.duration_ms,
                "provider": event.result.provider,
                "model": event.result.model,
                "inference_ms": event.result.inference_ms,
            })
    if not started:
        yield _ndjson_event({"type": "error", "message": "语音转写服务没有返回可用结果。"})
        return
    yield _ndjson_event({"type": "done"})


@router.post("/speech")
async def synthesize_speech(
    request: SynthesizeSpeechRequest,
    tts_service: TTSService = Depends(get_tts_service),
) -> Response:
    result = await tts_service.synthesize(request.text, request.voice_id, request.speed)
    return Response(
        content=result.audio_bytes,
        media_type=result.media_type,
        headers={
            "X-TTS-Provider": result.provider,
            "X-TTS-Model": result.model,
            "X-Audio-Duration-Ms": str(result.duration_ms),
            "X-Audio-Sample-Rate": str(result.sample_rate),
        },
    )


@router.post("/speech/stream")
async def synthesize_speech_stream(
    request: SynthesizeSpeechRequest,
    tts_service: TTSService = Depends(get_tts_service),
) -> StreamingResponse:
    iterator = _speech_stream_events(tts_service, request)
    first = await anext(iterator)

    async def body() -> AsyncIterator[bytes]:
        yield first
        async for event in iterator:
            yield event

    return StreamingResponse(body(), media_type="application/x-ndjson")


@router.post("/transcriptions/stream")
async def transcribe_upload_stream(
    chunks: list[UploadFile] = File(...),
    language: str | None = Form(None),
    asr_service: ASRService = Depends(get_asr_service),
) -> StreamingResponse:
    iterator = _transcription_stream_events(asr_service, chunks, language)
    first = await anext(iterator)

    async def body() -> AsyncIterator[bytes]:
        yield first
        async for event in iterator:
            yield event

    return StreamingResponse(body(), media_type="application/x-ndjson")


@router.post("/transcriptions")
async def transcribe_upload(
    file: UploadFile = File(...),
    language: str | None = Form(None),
    asr_service: ASRService = Depends(get_asr_service),
) -> TranscriptionResponse:
    if file is None:
        raise ASRFileMissingError()

    raw_size = file.size
    if raw_size is not None and raw_size > asr_service.max_upload_bytes:
        raise ASRFileTooLargeError()

    content_type = file.content_type
    if not content_type or not content_type.strip():
        try:
            await file.close()
        except Exception:
            pass
        raise ASRContentTypeMissingError()

    max_read = asr_service.max_upload_bytes + 1

    try:
        raw = await file.read(max_read)
    except Exception:
        try:
            await file.close()
        except Exception:
            pass
        raise

    got = len(raw)

    try:
        await file.close()
    except Exception:
        pass

    if got == 0:
        raise ASRFileMissingError()
    if got > asr_service.max_upload_bytes:
        raise ASRFileTooLargeError()

    result = await asr_service.transcribe(raw, content_type.strip(), language)

    return TranscriptionResponse(
        text=result.text,
        detected_language=result.detected_language,
        duration_ms=result.duration_ms,
        provider=result.provider,
        model=result.model,
        inference_ms=result.inference_ms,
    )
