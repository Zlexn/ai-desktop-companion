# Stage 2F-3 Streaming TTS First Vertical Slice Design

Date: 2026-06-29

## Status

Design approved for implementation planning. This document does not implement code.

## Current phase

Stage 2 — voice features. This task remains inside Stage 2 and does not implement streaming ASR, long-term memory, emotion state, background listening, wake word, or Live2D/expression behavior.

## Goal

Add the first verifiable streaming TTS vertical slice so assistant speech can begin playback after the first synthesized audio segment arrives, instead of waiting for the entire TTS response to finish.

The first slice prioritizes a stable fake-provider browser automation loop and a clean protocol boundary. It prepares for real CosyVoice streaming later but does not require real-provider streaming in this task.

## Non-goals

- Do not implement streaming ASR.
- Do not implement LLM response streaming.
- Do not implement WebSocket voice turns.
- Do not implement MediaSource, WebCodecs, or final low-gap audio playback.
- Do not remove or break the existing non-streaming `POST /api/audio/speech` path.
- Do not change chat persistence or database schema.
- Do not store generated audio.
- Do not implement long-term memory, emotion state, or character relationship state.

## Existing baseline

The app currently has:

- `POST /api/audio/speech`, returning one complete `audio/wav` response.
- `TTSService.synthesize(...)`, validating text, voice, speed, and one complete `SpeechSynthesisResult`.
- `FakeTTSProvider`, generating a deterministic WAV buffer.
- `CosyVoiceHTTPProvider`, calling a local OpenAI-compatible CosyVoice smoke server and returning one complete WAV.
- `scripts/cosyvoice3_openai_server.py`, already splitting long text and calling CosyVoice with `stream=True`, but collecting all chunks into one final WAV response.
- `apiClient.synthesizeSpeech(...)`, reading the whole response as a Blob.
- `useAudioPlaybackController`, managing one internal `HTMLAudioElement`, output-device routing, pause/resume/stop/replay, Blob URL lifecycle, and stale playback cleanup.
- `frontend/scripts/measure-voice-turn-latency.mjs`, measuring non-streaming fake-provider voice-turn timings.

Current gap:

- Browser playback cannot begin until the entire TTS response Blob has been received.

## Recommended architecture

### 1. Keep non-streaming TTS intact

The existing endpoint and frontend path remain the fallback and regression baseline:

```text
POST /api/audio/speech -> complete WAV -> Blob URL -> audio.play()
```

The streaming slice adds a separate path rather than changing this contract in place.

### 2. Add a new streaming endpoint

Add a new backend endpoint:

```text
POST /api/audio/speech/stream
```

Request body should reuse `SynthesizeSpeechRequest`:

```json
{
  "text": "assistant reply text",
  "voice_id": null,
  "speed": 1.0
}
```

Response media type:

```text
application/x-ndjson
```

Each line is one UTF-8 JSON event terminated by `\n`.

### 3. Streaming event protocol

Events:

```json
{"type":"start","provider":"fake","model":"fake-tone-v1"}
{"type":"segment","index":0,"audio_base64":"...","media_type":"audio/wav","duration_ms":320,"sample_rate":16000}
{"type":"segment","index":1,"audio_base64":"...","media_type":"audio/wav","duration_ms":280,"sample_rate":16000}
{"type":"done","segment_count":2}
```

Recoverable service errors may be sent as:

```json
{"type":"error","message":"语音合成失败，请稍后重试。"}
```

Protocol rules:

- `start` appears once before any segment.
- `segment.index` starts at `0` and increments by one.
- `segment.audio_base64` contains one complete standalone WAV segment.
- `segment.media_type` must be `audio/wav` for this first slice.
- `done.segment_count` must equal the number of emitted segment events.
- Unknown event types are ignored by the frontend but should be covered by parser tests.
- Malformed JSON, missing required segment fields, unsupported media type, or stream termination before `done` is treated as streaming playback failure.

### 4. Backend service boundary

Add streaming without weakening current `TTSService.synthesize(...)` validation.

Recommended backend types:

```py
@dataclass(frozen=True)
class SpeechSynthesisSegment:
    audio_bytes: bytes
    media_type: str
    sample_rate: int
    duration_ms: int
    provider: str
    model: str
    index: int
```

A minimal provider protocol can be introduced without forcing all providers to implement it immediately:

```py
class StreamingTTSProvider(Protocol):
    async def synthesize_stream(
        self,
        text: str,
        voice_id: str | None = None,
        speed: float = 1.0,
    ) -> AsyncIterator[SpeechSynthesisSegment]:
        ...
```

`FakeTTSProvider` should implement `synthesize_stream(...)` first. It can split text into deterministic chunks and reuse the existing WAV builder for each segment.

`CosyVoiceHTTPProvider` may remain non-streaming in this first slice. If a provider does not support streaming, `POST /api/audio/speech/stream` should return a stable app error response, not silently fake streaming by waiting for a full WAV.

### 5. Backend route behavior

The streaming route should:

1. Validate request text, voice, and speed through existing `TTSService` validation logic or a shared validation helper.
2. Check provider streaming support.
3. Return `StreamingResponse` with `application/x-ndjson`.
4. Emit `start` as soon as provider/model are known.
5. Emit each `segment` as soon as the segment WAV is available.
6. Emit `done` after all segments.
7. Convert validation errors to normal HTTP error envelopes before streaming begins.
8. Convert provider failures after streaming begins to an `error` event and end the stream.

The route must not persist audio bytes and must not log raw text beyond existing safe patterns.

### 6. Frontend API boundary

Add `apiClient.streamSpeech(text, options)` or an equivalent helper that returns an async iterator of parsed stream events.

Recommended TypeScript event types:

```ts
type SpeechStreamEvent =
  | { type: 'start'; provider: string | null; model: string | null }
  | { type: 'segment'; index: number; audioBytes: Uint8Array; mediaType: 'audio/wav'; durationMs: number; sampleRate: number }
  | { type: 'done'; segmentCount: number }
  | { type: 'error'; message: string };
```

The parser should:

- Use `fetch('/api/audio/speech/stream', { signal })`.
- Check `response.ok`.
- Require `response.body`.
- Use `ReadableStreamDefaultReader<Uint8Array>`.
- Decode UTF-8 text incrementally.
- Buffer partial lines until `\n` arrives.
- Parse each complete line as JSON.
- Convert base64 audio to `Uint8Array`.
- Throw clear user-facing errors for malformed events.
- Respect `AbortController` cancellation.

### 7. Frontend playback controller

Extend `useAudioPlaybackController` with a streaming path while preserving current controls.

Recommended public surface:

```ts
play(messageId: string, text: string, options?: { streaming?: boolean }): Promise<boolean>
```

or, if clearer:

```ts
playStreaming(messageId: string, text: string): Promise<boolean>
```

The first implementation should keep non-streaming call sites unchanged. The voice-turn path may opt into streaming only after tests prove the streaming path works.

Playback queue behavior:

1. Set message state to `synthesizing` when stream starts.
2. On first valid segment:
   - Create a Blob URL for the segment.
   - Apply selected output device with existing `setSinkId` helper.
   - Start playback immediately if no segment is currently playing.
   - Set message state to `playing` after `audio.play()` resolves.
3. While a segment is playing, queue later segment URLs.
4. On `ended`, revoke the completed segment URL and play the next queued segment.
5. On `done`, wait for queued playback to finish, then set state to `ready`.
6. On `stop`, `reset`, session switch, or explicit recording interruption:
   - abort the stream request,
   - pause/reset the audio element,
   - revoke all queued/current segment URLs,
   - clear queue state,
   - avoid stale state updates through the existing active message/generation guard pattern.

For the first slice, pause/resume may apply only to the current segment. If paused, queued segments must not start until resume.

### 8. UI behavior

Keep the UI small:

- Existing assistant message controls remain: `播放`, `生成中…`, `暂停`, `继续`, `停止`, `重播`.
- No new visible streaming toggle is required in the first slice.
- Streaming can be enabled for fake-provider test path or by an internal frontend option after parser/controller tests pass.
- If streaming fails, show a user-facing audio error and keep the assistant text visible.
- Do not automatically fallback to non-streaming in the first slice. Manual retry through existing playback controls is clearer and avoids hidden duplicate requests.

### 9. Measurement updates

Extend the fake-provider browser measurement script after streaming playback is integrated.

New metrics:

```text
streamTtsRequestToFirstSegmentMs
streamFirstSegmentToPlayMs
streamSendToFirstPlaybackMs
streamDoneMs
streamSegmentCount
```

The measurement must assert:

- exactly one chat request,
- exactly one streaming TTS request,
- at least one segment,
- first playback occurs before the stream `done` event,
- no console/page errors.

The evidence document should compare streaming fake-provider timings against the existing non-streaming baseline shape, without claiming real-provider latency improvements.

### 10. Testing plan

Backend tests:

- Fake provider streaming yields multiple valid WAV segments for multi-part text.
- Streaming service validates text, voice, and speed using the same rules as non-streaming TTS.
- Streaming endpoint returns `application/x-ndjson`.
- Streaming endpoint emits `start`, ordered `segment` events, and `done`.
- Provider failure after `start` emits an `error` event.
- Unsupported provider returns a stable app error before streaming begins.

Frontend unit tests:

- NDJSON parser handles chunks split across line boundaries.
- Parser rejects malformed JSON and invalid segment fields.
- Parser respects abort signals.
- Playback controller starts playing after first segment before `done`.
- Playback controller queues multiple segments in order.
- Stop/reset revokes all segment URLs and aborts the stream.
- Output device selection still applies to each segment.
- Streaming failure keeps assistant text visible and reports a recoverable error.

E2E tests:

- Fake half-duplex voice turn with streaming TTS produces one chat request and one streaming TTS request.
- First audio play is observed before the stream `done` event in the browser test harness.
- Explicit interruption during streaming TTS aborts the stream and starts recording.
- Existing non-streaming playback tests remain green.

Validation commands:

```text
python -m pytest backend/tests -v
npm --prefix frontend test -- --run
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

Additional targeted commands should be recorded in the implementation evidence document.

## Acceptance criteria

This task is complete only when:

1. Existing non-streaming `/api/audio/speech` still passes all current tests.
2. New streaming endpoint emits valid NDJSON events for fake TTS.
3. Frontend can parse streamed speech events from chunked `ReadableStream` data.
4. Assistant playback can begin from the first streamed segment before the stream completes.
5. Multiple segments play in order and clean up Blob URLs.
6. Stop/reset/session switch/recording interruption aborts stale streaming requests and prevents stale UI state.
7. Streaming failures keep text chat visible and show a recoverable audio error.
8. Output-device routing still applies to streamed segment playback.
9. Fake-provider E2E proves one chat request, one streaming TTS request, and first play before stream done.
10. Evidence records validation commands and explicitly states that real-provider streaming, streaming ASR, long-term memory, and emotion are not implemented.

## Phase boundary

This design stays within Stage 2 voice output optimization. It is a first streaming TTS slice, not a full realtime conversation system. Stage 3 memory and Stage 4 emotion remain blocked until Stage 2 acceptance is completed and recorded.
