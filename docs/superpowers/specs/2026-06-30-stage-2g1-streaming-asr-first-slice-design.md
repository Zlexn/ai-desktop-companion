# Stage 2G-1 Streaming ASR First Vertical Slice Design

Date: 2026-06-30

## Status

Design approved by default recommendation for implementation planning. This document does not implement code.

## Current phase

Stage 2 — voice features. This task remains inside Stage 2 and does not implement long-term memory, emotion state, background wake-word listening, automatic spoken barge-in, LLM response streaming, or final seamless low-gap audio playback.

## Goal

Add the first verifiable streaming ASR vertical slice: while the user is explicitly recording, the browser sends bounded audio chunks to the backend and the UI can show incremental transcript progress before the final transcript is confirmed.

This is an application-layer streaming transport and UI-state slice. It proves the browser, backend API, ASR service boundary, and voice-turn UI can handle chunked ASR events. It does not claim true low-latency Whisper decoding quality yet.

## Non-goals

- Do not implement Stage 3 long-term memory.
- Do not implement Stage 4 emotion state.
- Do not implement background listening, wake word, or always-on microphone capture.
- Do not implement automatic spoken barge-in.
- Do not implement LLM response streaming.
- Do not replace the existing multipart `POST /api/audio/transcriptions` endpoint.
- Do not remove manual recording fallback.
- Do not store raw audio chunks or generated transcripts as long-term memory.
- Do not add a new production dependency unless the implementation plan proves it is necessary.
- Do not claim real FasterWhisper streaming is complete in this slice.

## Existing baseline

The app currently has:

- Browser manual recording with `MediaRecorder`.
- VAD auto-stop after explicit `开始录音`.
- Multipart ASR endpoint: `POST /api/audio/transcriptions`.
- Fake ASR and FasterWhisper ASR provider behind `ASRProvider` / `ASRService`.
- Half-duplex voice turn: record → transcript confirmation → `发送并朗读` → chat → streaming TTS.
- Real CosyVoice streaming TTS vertical slice through `/api/audio/speech/stream`.

Current gap:

- ASR still waits for the whole recording Blob before upload/transcription.
- There is no backend streaming-ASR event protocol.
- There is no UI state for partial transcript updates during recording.
- FasterWhisper real provider is still batch-oriented in this app.

## External feasibility notes

Browser chunking can use `MediaRecorder.start(timeslice)`, which emits `dataavailable` Blob chunks approximately every `timeslice` milliseconds and a final chunk on stop. The browser must treat chunk timing as approximate, not exact.

`faster-whisper` public core usage is primarily file/batch transcription. Real streaming ASR usually needs an additional sliding-window, context, de-duplication, and endpointing layer. Therefore this first slice should validate app-level streaming mechanics with fake/default behavior before attempting real-provider streaming.

## Recommended architecture

### 1. Preserve existing non-streaming ASR

Keep `POST /api/audio/transcriptions` unchanged. It remains the stable fallback for manual recording and real FasterWhisper batch transcription.

Streaming ASR should be additive and opt-in. Existing E2E tests that use manual recording must keep passing.

### 2. Add a backend streaming-ASR endpoint

Add a new endpoint under the existing audio route namespace:

```text
POST /api/audio/transcriptions/stream
Content-Type: multipart/form-data or application/octet-stream chunks depending on final implementation
Response: application/x-ndjson
```

For the first slice, prefer a request shape that remains easy to test and does not require WebSocket infrastructure. Two acceptable variants:

1. One request containing ordered chunk metadata and chunk blobs, with the backend emitting NDJSON events as it processes them.
2. A session-style HTTP API with `start`, `chunk`, and `finish` calls, only if one-request multipart streaming is impractical in FastAPI/browser APIs.

The implementation plan should choose the simpler option after checking current FastAPI/browser constraints. Do not add WebSockets unless HTTP cannot satisfy the vertical slice.

### 3. Define a minimal ASR streaming event protocol

Use NDJSON events consistent with the TTS streaming style:

```json
{"type":"start","provider":"fake-asr","model":"fake-asr-v1"}
{"type":"partial","index":0,"text":"语音","is_final":false,"audio_ms":1000}
{"type":"partial","index":1,"text":"语音转写文本","is_final":false,"audio_ms":2000}
{"type":"final","text":"语音转写文本","detected_language":"zh","duration_ms":2400,"provider":"fake-asr","model":"fake-asr-v1","inference_ms":1}
{"type":"done"}
```

Error event:

```json
{"type":"error","message":"语音转写失败，请重新录制或手动输入。"}
```

Rules:

- `start` must arrive before transcript events.
- `partial` text is display-only and must not be sent to chat automatically.
- `final` text becomes the existing pending transcript that the user can replace/append/discard/发送并朗读.
- If streaming fails, the UI must keep text chat usable and may fall back to existing manual non-streaming recording if available.

### 4. Add provider/service boundaries without forcing real streaming

Add a streaming capability beside the existing ASR provider interface, for example:

```py
class StreamingASRProvider(ASRProvider, Protocol):
    async def transcribe_stream(...):
        ...
```

The fake provider should implement deterministic streaming events for tests.

The FasterWhisper provider should not be forced into fake streaming in this slice. If it does not implement streaming, the service should fail clearly with a recoverable unsupported-streaming error rather than silently buffering the full audio and reporting streaming success.

### 5. Browser recording changes

Add a streaming mode to the existing recorder hook rather than replacing it.

Recommended behavior:

1. User explicitly clicks `开始录音`.
2. Browser starts `MediaRecorder` with a conservative timeslice such as 1000 ms.
3. Each non-empty chunk is queued for streaming upload.
4. UI shows a streaming status such as `正在实时转写…` and displays latest partial transcript.
5. When user stops or VAD auto-stop fires, the final chunk is flushed.
6. Backend final transcript becomes the same `pendingTranscript` state used today.
7. Existing `发送并朗读` continues to send only the final confirmed transcript.

For the first slice, it is acceptable to keep streaming ASR behind a feature flag or fake-provider-only path if that reduces risk.

### 6. Error handling and privacy

- No raw audio chunks are persisted by the app.
- Do not log transcript text by default; logs may record chunk counts, byte lengths, durations, provider/model, and timings.
- Microphone permission and device errors reuse existing recorder messages.
- Streaming upload failure shows a recoverable voice-input error and does not break text chat.
- Stale chunks from a previous recording generation must not update the current transcript.
- Session switch, new session, delete session, cancel recording, and explicit interruption must clear stale partial/final streaming state.

## Testing plan

### Backend tests

Add tests for:

- Fake streaming ASR provider yields ordered partial and final events.
- ASR service validates streaming events and maps provider errors.
- `/api/audio/transcriptions/stream` returns `application/x-ndjson` start/partial/final/done events for fake provider.
- Unsupported provider streaming returns a clear app error before claiming stream success.
- Existing `/api/audio/transcriptions` multipart tests remain green.

### Frontend tests

Add tests for:

- Recorder starts MediaRecorder with a timeslice when streaming ASR is enabled.
- Partial transcript text is shown as provisional and does not populate/send chat automatically.
- Final transcript becomes the existing pending transcript confirmation UI.
- Cancel/session switch clears stale partial transcript.
- Streaming failure keeps text chat usable and reports a recoverable recorder error.
- Existing manual recorder, VAD, device selection, explicit interruption, and voice-turn tests remain green.

### Runtime smoke

Fake/default smoke:

1. Start app with fake ASR and fake/streaming TTS defaults.
2. Browser records using mocked MediaRecorder chunks.
3. UI receives at least one partial transcript before final.
4. Final transcript appears in confirmation UI.
5. `发送并朗读` still triggers chat and TTS playback.
6. Console error count is zero.

Real-provider smoke is optional for this first slice and should be recorded as not implemented unless a later design adds real FasterWhisper streaming.

## Acceptance criteria

This task is complete only when:

1. Existing non-streaming ASR endpoint remains available and tested.
2. A new streaming ASR event contract is implemented and documented.
3. Fake/default streaming ASR path emits at least one partial event and one final event.
4. Browser UI shows partial transcript during explicit recording.
5. Final transcript flows into the existing confirmation UI.
6. Existing `发送并朗读` voice-turn path still works from the final transcript.
7. Recording cancel/session switch/stale generation guards prevent stale partial/final updates.
8. Backend and frontend automated tests pass.
9. A browser smoke records commands, observations, timings, and limitations.
10. Documentation clearly states that real FasterWhisper streaming, final low-gap audio, long-term memory, and emotion are not implemented.

## Main risks

- Browser MediaRecorder chunks may not be independently decodable, especially for WebM containers; this is why fake/default event streaming should validate transport and UI before real decoding.
- HTTP request streaming from browser to FastAPI may be more awkward than response streaming; the implementation plan must choose the simplest testable transport.
- Partial transcript UX can mislead users if it looks final; label it clearly as provisional.
- Stale async chunks can pollute the wrong recording/session unless generation guards are used consistently.
- Real FasterWhisper streaming requires algorithmic work outside this first slice.

## Phase boundary

This design stays within Stage 2 voice input optimization. It does not enter Stage 3 long-term memory or Stage 4 emotion. It moves the system toward realtime conversation by validating streaming ASR mechanics before real-provider streaming ASR quality work.
