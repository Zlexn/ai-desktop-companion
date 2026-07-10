# Stage 2F-4 Real CosyVoice Streaming TTS Vertical Slice Design

Date: 2026-06-30

## Status

Design approved by default recommendation for implementation planning. This document does not implement code.

## Current phase

Stage 2 — voice features. This task remains inside Stage 2 and does not implement streaming ASR, long-term memory, emotion state, background listening, wake word, automatic spoken barge-in, or final seamless low-gap audio playback.

## Goal

Add the first verifiable real-provider streaming TTS vertical slice using local CosyVoice. The slice should prove whether real CosyVoice streaming chunks can flow through the existing 2F-3 `POST /api/audio/speech/stream` NDJSON contract and reach browser playback from the first segment.

This is a feasibility and vertical-slice task. It records real local timing and playability evidence; it does not claim final realtime or seamless streaming quality.

## Non-goals

- Do not implement streaming ASR.
- Do not implement LLM response streaming.
- Do not implement WebSocket voice turns.
- Do not replace the existing non-streaming `POST /api/audio/speech` path.
- Do not remove fake-provider streaming; fake remains the default automated path.
- Do not implement MediaSource, WebCodecs, raw PCM WebAudio scheduling, or final low-gap playback.
- Do not change chat persistence or database schema.
- Do not store generated audio.
- Do not implement long-term memory, emotion state, relationship state, or expression behavior.
- Do not clone, imitate, or claim any unauthorized voice, character voice, actor voice, celebrity voice, or copyrighted performance.

## Existing baseline

The app currently has:

- A non-streaming TTS endpoint: `POST /api/audio/speech` returning one complete WAV.
- A streaming TTS endpoint: `POST /api/audio/speech/stream` returning `application/x-ndjson` events.
- Streaming event protocol:
  - `start`
  - ordered `segment` events containing standalone WAV bytes as base64
  - `done`
  - recoverable `error`
- Fake streaming TTS provider and automated tests.
- Frontend `streamSpeech(...)` parser for chunked NDJSON.
- Frontend audio playback controller that can play the first streamed segment, queue later segment URLs, abort stale streams, and clean up Blob URLs.
- Local CosyVoice OpenAI-compatible smoke server that can synthesize real TTS but currently returns one final WAV to the main backend.

Current gap:

- Real CosyVoice does not yet implement the 2F-3 streaming provider path.
- The main backend `CosyVoiceHTTPProvider` currently waits for a full response body.
- The browser has not proven playback from real CosyVoice streaming chunks.

## Recommended architecture

### 1. Keep the public streaming contract unchanged

Reuse the 2F-3 endpoint and frontend parser:

```text
POST /api/audio/speech/stream
Content-Type: application/x-ndjson
```

The backend should emit the same event shape used by fake streaming:

```json
{"type":"start","provider":"cosyvoice-http","model":"Fun-CosyVoice3-0.5B-2512"}
{"type":"segment","index":0,"audio_base64":"...","media_type":"audio/wav","duration_ms":320,"sample_rate":24000}
{"type":"done","segment_count":1}
```

This avoids a second frontend streaming protocol and keeps the slice small.

### 2. Add streaming support to the local CosyVoice smoke server

Extend `scripts/cosyvoice3_openai_server.py` with an opt-in streaming response mode compatible with the backend provider.

Recommended server behavior:

1. Accept the existing OpenAI-compatible `/v1/audio/speech` request body.
2. If `stream` or a local query/header flag is false or absent, preserve the current full-WAV response.
3. If streaming is requested:
   - split input text using the existing bounded text splitting helper,
   - call CosyVoice with `stream=True`,
   - as soon as each CosyVoice chunk or bounded text segment is available, convert it to a standalone WAV segment,
   - emit NDJSON segment events or an internal server-side streaming format that the main backend can parse.

For the first slice, standalone WAV segments are acceptable even if they are not seamless. The goal is first real-provider streaming proof, not final gapless playback.

### 3. Add real streaming support to `CosyVoiceHTTPProvider`

Add `synthesize_stream(...)` to the existing `CosyVoiceHTTPProvider` without changing its existing `synthesize(...)` behavior.

Provider responsibilities:

- Use `httpx.AsyncClient.stream(...)` or another non-buffering HTTP path.
- Request the local CosyVoice server streaming mode explicitly.
- Parse the streaming response incrementally.
- Yield validated `SpeechSynthesisSegment` objects as soon as complete segment audio is available.
- Preserve provider/model metadata.
- Map timeout, network, and HTTP failures to existing TTS error types.
- Avoid logging raw text or audio bytes.

If the local server can only emit complete WAV segments after sentence-level chunks, that is still acceptable for this vertical slice. It must not wait for the entire assistant text to synthesize before yielding the first segment.

### 4. Keep frontend changes minimal

The frontend should not introduce a new visible control or playback mode in this task.

Existing voice-turn playback can continue calling:

```ts
audioController.play(messageId, text, { streaming: true })
```

The main difference is backend/provider configuration:

- fake provider path remains default and automated.
- real provider smoke uses `TTS_PROVIDER=cosyvoice-http` and the local CosyVoice server streaming mode.

### 5. Measurement and evidence

The task must record real local evidence using non-private synthetic Chinese text. Evidence should include:

- provider and model name,
- time to first CosyVoice server chunk,
- time to first backend NDJSON segment,
- time to first browser playback trigger when a browser smoke is run,
- total stream duration,
- segment count,
- output sample rate and approximate audio duration,
- GPU memory observation if available without adding new dependencies,
- whether the first segment is audible/playable,
- limitations and whether gaps between segments are expected.

Do not record private transcript content, prompt audio, API keys, or generated audio files in git.

## Error handling

- Validation errors before streaming begins should still use normal HTTP app error envelopes.
- Provider failures after streaming begins should emit a streaming `error` event and end the response.
- Unsupported real streaming should fail clearly; it must not silently fall back to full non-streaming synthesis while reporting streaming success.
- Frontend streaming failure must keep assistant text visible and report a recoverable audio error.
- Stop/reset/session switch/explicit recording interruption must abort stale streams and clean Blob URLs, reusing 2F-3 behavior.

## Testing plan

### Backend unit/API tests

Automated tests should remain fake/default where possible and use mocked HTTP streams for CosyVoice provider tests.

Add targeted tests for:

- `CosyVoiceHTTPProvider.synthesize_stream(...)` parses server NDJSON or streaming segment responses incrementally.
- provider yields ordered `SpeechSynthesisSegment` objects with `audio/wav`, sample rate, duration, provider, model, and index.
- provider maps HTTP errors, timeouts, and malformed stream events to existing TTS errors.
- `/api/audio/speech/stream` works with `TTS_PROVIDER=cosyvoice-http` when the provider stream is mocked.
- existing `/api/audio/speech` non-streaming tests remain green.

### Frontend tests

No broad frontend redesign is expected. Run existing 2F-3 tests to prove the streaming contract remains compatible:

- `speechStream.test.ts`
- `MessageList.test.tsx`
- `App.test.tsx`
- `voice-turn.spec.ts`

Only add frontend tests if the public frontend behavior changes.

### Real local smoke

Real smoke is opt-in and not a default CI path.

Suggested commands:

1. Start local CosyVoice server in `.venv-tts`.
2. Start backend with:
   - `TTS_PROVIDER=cosyvoice-http`
   - `TTS_COSYVOICE_BASE_URL=http://127.0.0.1:8001`
   - `TTS_COSYVOICE_MODEL=Fun-CosyVoice3-0.5B-2512`
3. Call `/api/audio/speech/stream` with a short non-private Chinese sentence.
4. Verify at least one segment arrives before stream completion.
5. Run a browser smoke that triggers assistant streaming playback and records no console errors.

## Acceptance criteria

This task is complete only when:

1. Existing fake/default automated tests pass.
2. Existing non-streaming CosyVoice HTTP path still works or is not modified.
3. `CosyVoiceHTTPProvider.synthesize_stream(...)` can parse a mocked streaming response and yield valid segments.
4. Backend `/api/audio/speech/stream` can use the CosyVoice HTTP provider streaming path under explicit real-provider configuration.
5. A real local CosyVoice streaming API smoke with non-private text produces at least one valid `audio/wav` segment event.
6. A browser smoke confirms the existing streaming playback path can attempt/play the real first segment without breaking text chat.
7. Evidence records commands, observed results, timings, and limitations.
8. Documentation clearly states that streaming ASR, final seamless audio streaming, long-term memory, and emotion are not implemented.

## Main risks

- CosyVoice `stream=True` chunks may not be directly usable as standalone WAV without buffering or conversion.
- The first chunk may not be much faster than full synthesis; measurement must report this honestly.
- HTTP streaming may accidentally buffer at the local server, backend, or frontend layer.
- Real local GPU memory pressure may vary; do not assume simultaneous ASR/TTS residency.
- Segment playback may have gaps because this slice uses independent WAV segments.
- Logging text or audio for debugging could leak private content; telemetry must use lengths/timings/provider/model instead.

## Phase boundary

This design stays within Stage 2 voice output optimization. It is the real-provider follow-up to the fake streaming TTS slice, not a full realtime conversation system. Stage 3 memory and Stage 4 emotion remain blocked until Stage 2 acceptance is completed and recorded.
