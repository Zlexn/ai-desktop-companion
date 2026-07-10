# Stage 2G-2 Real FasterWhisper Streaming ASR Feasibility Design

Date: 2026-07-01

## Status

Design approved by default recommendation for implementation planning. This document does not implement code.

## Current phase

Stage 2 — voice features. Stage 2G-1 already added app-level fake/default streaming ASR plumbing and a browser provisional transcript preview. This design stays inside Stage 2 and does not implement long-term memory, emotion state, background wake-word listening, automatic spoken barge-in, LLM response streaming, or final seamless low-gap audio playback.

## Goal

Add a minimal, explicitly opt-in real FasterWhisper streaming-ASR feasibility slice that can emit partial transcript events from real local FasterWhisper inference through the existing `POST /api/audio/transcriptions/stream` NDJSON contract.

This is a feasibility slice, not final production-grade simultaneous ASR. Completion means the app can prove real-provider partial/final event plumbing with local FasterWhisper and document observed latency, correctness, and limitations.

## Non-goals

- Do not implement Stage 3 long-term memory.
- Do not implement Stage 4 emotion state.
- Do not implement always-on microphone capture, wake word, or background listening.
- Do not implement automatic spoken barge-in.
- Do not implement LLM response streaming.
- Do not implement final seamless low-gap TTS/audio playback.
- Do not replace the stable batch `POST /api/audio/transcriptions` endpoint.
- Do not remove the fake/default streaming ASR path.
- Do not add WebSockets unless the implementation plan later proves HTTP cannot satisfy this feasibility slice.
- Do not claim real FasterWhisper streaming is production-ready or low-latency until runtime evidence supports that claim.
- Do not persist raw audio chunks, transcripts, or derived memory.

## Existing baseline

The app currently has:

- Batch FasterWhisper provider behind `ASRProvider.transcribe(...)`.
- Fake streaming provider behind `StreamingASRProvider.transcribe_stream(...)`.
- Backend `/api/audio/transcriptions/stream` returning NDJSON `start`, `partial`, `final`, `done`, and `error` events.
- Browser recorder using `MediaRecorder.start(1000)` and showing `实时转写预览` for partial events.
- Final transcript confirmation UI and `发送并朗读` half-duplex voice-turn flow.
- Real FasterWhisper model benchmark data with C3 (`medium` / `cuda` / `float16`) as initial candidate and C4 (`small` / `cpu` / `int8`) as fallback candidate.

Current gap:

- `FasterWhisperASRProvider` remains batch-only.
- Real provider streaming requests fail as unsupported or cannot produce partial events.
- The app has not measured real-provider partial latency through the streaming contract.

## External feasibility notes

`faster-whisper` core usage is optimized around file/batch transcription through `WhisperModel.transcribe(...)`. True low-latency Whisper streaming usually requires an additional layer: audio buffering, sliding windows, VAD/VAC or endpointing, repeated decoding, duplicate suppression, and stability rules such as local agreement.

Therefore, this task should implement the smallest local feasibility layer inside the existing provider boundary before considering a larger dedicated streaming-ASR service.

## Recommended architecture

### 1. Keep existing contracts stable

Keep these endpoints unchanged:

- `POST /api/audio/transcriptions` — authoritative batch transcription.
- `POST /api/audio/transcriptions/stream` — existing NDJSON streaming ASR contract.

Do not change the frontend event schema from 2G-1. The real provider should emit the same event types as fake streaming ASR.

### 2. Add opt-in FasterWhisper streaming feasibility settings

Add settings with conservative defaults:

```text
ASR_FASTER_WHISPER_STREAMING_ENABLED=false
ASR_FASTER_WHISPER_STREAMING_WINDOW_MS=3000
ASR_FASTER_WHISPER_STREAMING_STEP_MS=1000
ASR_FASTER_WHISPER_STREAMING_MIN_PARTIAL_CHARS=1
ASR_FASTER_WHISPER_STREAMING_MAX_PARTIALS=8
```

Rules:

- If `ASR_PROVIDER=faster-whisper` but streaming is disabled, `/transcriptions/stream` should return the existing clear unsupported-provider error.
- Enabling streaming must be explicit. Default tests and normal local fake mode remain unaffected.
- The batch provider remains available even when streaming feasibility is enabled.

### 3. Implement provider-local sliding/buffer feasibility path

Add `FasterWhisperASRProvider.transcribe_stream(...)` only for the explicit streaming-enabled configuration.

Recommended first implementation:

1. Accept ordered `audio_chunks` from the existing service.
2. Accumulate chunks in order.
3. For each cumulative window boundary, write the cumulative audio to a temporary file.
4. Call existing `WhisperModel.transcribe(...)` in a worker thread with the same model and language settings.
5. Build normalized text from returned segments.
6. Emit `partial` only when text is non-empty and meaningfully changed from the last emitted partial.
7. Emit at most `ASR_FASTER_WHISPER_STREAMING_MAX_PARTIALS` partials.
8. After all chunks are processed, run one final transcription over the full accumulated audio and emit `final`.
9. Delete every temporary file in `finally`.

This is intentionally simple. It proves real local inference can drive the 2G-1 streaming contract without yet solving all streaming-ASR quality problems.

### 4. Avoid misleading partials

Partial events must remain provisional:

- `is_final=false` for all partial events.
- Partial text must not be sent to chat.
- Final text remains authoritative.
- Documentation must state that repeated batch decoding can revise earlier words and may be slower than true streaming ASR.

### 5. Error handling and privacy

- No raw audio is persisted beyond temporary files needed for inference.
- Temporary files must be removed even on timeout or provider errors.
- Do not log transcript text by default.
- Logs may include chunk count, byte length, window count, provider/model, inference timings, and error category.
- Provider errors map to existing ASR errors so text chat remains usable.
- Stale generation/session guards from 2G-1 remain frontend responsibilities.

## Testing plan

### Backend unit tests

Add tests for:

- FasterWhisper streaming disabled returns unsupported streaming error.
- Streaming enabled provider calls the fake `WhisperModel.transcribe(...)` on cumulative audio windows.
- Provider emits at least one `TranscriptionPartialEvent` before `TranscriptionFinalEvent` when decoded text changes.
- Duplicate unchanged partial text is not re-emitted.
- Temporary files are deleted after partial and final transcription.
- Timeout and unavailable errors map to existing ASR error types.

### Backend API tests

Add or update tests for:

- `POST /api/audio/transcriptions/stream` with `ASR_PROVIDER=faster-whisper` and streaming disabled returns a clear error.
- With a mocked FasterWhisper streaming provider enabled, the API returns NDJSON `start`, `partial`, `final`, `done` in order.
- Existing fake streaming tests remain green.
- Existing batch `/api/audio/transcriptions` tests remain green.

### Frontend tests

Prefer no frontend schema changes. Run existing 2G-1 frontend parser/recorder/App tests. Add tests only if real-provider metadata requires display changes.

### Runtime smoke

Real-provider smoke should be explicit and local-only:

1. Start backend with `ASR_PROVIDER=faster-whisper` and local model path.
2. Enable `ASR_FASTER_WHISPER_STREAMING_ENABLED=true`.
3. Send ordered chunks derived from a known local fixture such as `asr-benchmark-corpus/clean/P001.m4a` or a browser-recorded sample.
4. Observe NDJSON `start`, at least one `partial`, `final`, and `done`.
5. Record first partial latency, final latency, provider/model, chunk/window counts, and transcript observation.

Optional browser smoke:

1. Start frontend against the real-provider backend.
2. Use mocked microphone chunks or a controlled browser fixture.
3. Confirm `实时转写预览` appears from real provider metadata.
4. Confirm final transcript enters existing confirmation UI.
5. Record console error count.

## Acceptance criteria

This task is complete only when:

1. Existing batch FasterWhisper transcription remains unchanged and tested.
2. FasterWhisper streaming feasibility is explicitly configurable and disabled by default.
3. When disabled, real-provider streaming returns a clear unsupported-streaming error.
4. When enabled with mocked FasterWhisper, unit/API tests show ordered partial and final events.
5. Temporary inference files are deleted on success and error paths.
6. Fake/default streaming ASR path remains available and tested.
7. A real local smoke records whether FasterWhisper can produce at least one partial and final result through `/api/audio/transcriptions/stream`.
8. Documentation records observed latency, transcript quality caveats, and whether the slice is sufficient for later product work.
9. README and `CLAUDE.md` are updated only after validation passes.
10. Documentation clearly states that final seamless low-gap audio, long-term memory, and emotion remain unimplemented.

## Main risks

- Browser MediaRecorder chunks may not be independently decodable. The feasibility path should work on cumulative audio, not assume each chunk is standalone.
- Repeated batch transcription can be compute-heavy and may increase GPU load. Cap partial count and document latency.
- Partial text can revise earlier content; the UI must keep it visibly provisional.
- Real-time quality may be insufficient with current models/settings. If so, record evidence and use the next task to evaluate a dedicated streaming wrapper/service.
- Adding too much algorithmic complexity in this slice risks scope creep. Keep local agreement, VAC/VAD, and de-duplication minimal unless required for a meaningful smoke.

## Alternatives considered

### A. Provider-local cumulative-window feasibility path — recommended

Use existing provider boundary and endpoint. Lowest integration risk and easiest to test. It may be slower and less accurate than production streaming, but it answers the immediate feasibility question.

### B. Integrate an external streaming ASR wrapper/service first

Potentially closer to production streaming architecture, but adds dependency and operational complexity before proving the existing app contract with real provider.

### C. Skip real ASR streaming and implement final low-gap TTS playback

Improves output smoothness, but leaves the input side fake/default streaming only. This does not close the current Stage 2 ASR gap.

## Phase boundary

This design stays inside Stage 2 voice input optimization. It does not enter Stage 3 long-term memory or Stage 4 emotion. It moves the system toward realtime conversation by testing real local ASR through the streaming interface before making larger product or architecture claims.
