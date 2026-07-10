# Stage 2H Low-Gap Streaming Audio Playback Design

> Date: 2026-07-03
> Status: design only; no implementation in this document.

## Alignment

Current phase: Stage 2 — voice features, implementing.

Current Stage 2 gap: `Final seamless low-gap audio` is not started. Stage 1 text chat is closed, and Stage 3 long-term memory plus Stage 4 emotion must not start until Stage 2 acceptance criteria are actually verified.

Goal of this slice: replace the current browser-side streaming TTS playback behavior for voice turns with a low-gap Web Audio scheduling path while preserving the existing segmented NDJSON TTS contract, text-chat fallback, explicit interruption, session guards, and audio-device preference behavior.

This slice supports the long-term product goal of a local, near-realtime voice companion, but it does not implement long-term memory, emotion state, background listening, wake words, voice cloning, or copyrighted/unauthorized character voice replication.

## Research summary

Deep research and direct source checks converged on these points:

- Browser playback should move from independent per-segment `HTMLAudioElement` playback to a scheduled Web Audio queue. `AudioBufferSourceNode.start(when)` schedules playback on the `AudioContext` clock, and each source node is one-shot, so a streaming queue should create one source per decoded segment.
- For decoded short segments, `AudioBufferSourceNode` scheduling is the smallest suitable step. For future raw PCM/network-streamed ultra-low-latency audio, `AudioWorklet`/ring-buffer designs are the right reference class, but they are beyond this minimal slice.
- Media Source Extensions are useful for appending compatible encoded media segments into `<audio>`, but they would require changing segment container/codec packaging. The current backend emits standalone WAV segments, so MSE is not the recommended minimum path.
- Output device support must not regress. `HTMLMediaElement.setSinkId()` is already used by the project, while Web Audio output routing depends on newer `AudioContext` sink APIs and browser support. This design therefore prefers Web Audio where supported and falls back cleanly to the existing HTMLAudio path.

Key sources:

- MDN Web Audio advanced techniques: https://developer.mozilla.org/en-US/docs/Web/API/Web_Audio_API/Advanced_techniques
- MDN AudioBufferSourceNode: https://developer.mozilla.org/en-US/docs/Web/API/AudioBufferSourceNode
- MDN AudioBufferSourceNode.start(): https://developer.mozilla.org/en-US/docs/Web/API/AudioBufferSourceNode/start
- MDN AudioContext constructor/options: https://developer.mozilla.org/en-US/docs/Web/API/AudioContext/AudioContext
- MDN AudioContext.setSinkId(): https://developer.mozilla.org/en-US/docs/Web/API/AudioContext/setSinkId
- MDN Media Source API: https://developer.mozilla.org/en-US/docs/Web/API/Media_Source_Extensions_API

## Recommended approach

Implement a front-end-only Web Audio streaming scheduler for existing TTS stream segments.

Do not change:

- `POST /api/audio/speech/stream` NDJSON event contract.
- TTS provider interfaces.
- ASR provider interfaces.
- Chat/message persistence.
- Voice turn confirmation and interruption semantics.
- Existing non-streaming `/api/audio/speech` fallback.

Add a small browser audio module, likely:

```text
frontend/src/audio/streamingAudioScheduler.ts
```

The module owns Web Audio scheduling and exposes a narrow interface to `useAudioPlaybackController`.

## Scheduler responsibilities

The scheduler should:

1. Lazily create an `AudioContext` when streaming playback begins.
2. Prefer `latencyHint: "interactive"`, but treat actual latency as measured data rather than a guarantee.
3. Decode each complete WAV segment with `AudioContext.decodeAudioData()`.
4. Create a fresh `AudioBufferSourceNode` for every decoded segment.
5. Track `nextStartTime` in `AudioContext.currentTime` coordinates.
6. Schedule each segment at `max(nextStartTime, currentTime + initialLookahead)`.
7. Increment `nextStartTime` by decoded buffer duration.
8. Track scheduled source nodes so stop/reset/interruption can stop them.
9. Report playback telemetry: first segment decode time, first scheduled time, queue depth, scheduled gap/underrun, fallback reason, stop reason.
10. Fail closed: if Web Audio is unavailable, decode fails, output routing fails, or scheduling throws, fall back to the current HTMLAudio segment queue.

The scheduler should not own React state, message IDs, TTS fetching, session generation, chat sending, or UI text. Those remain in existing hooks/components.

## Integration with `useAudioPlaybackController`

Current streaming playback in `frontend/src/hooks/useAudioPlaybackController.ts` creates Blob URLs for each segment and queues them behind one `HTMLAudioElement`. Stage 2H should keep this path as fallback but add a Web Audio primary path for streaming voice-turn playback.

Proposed integration:

1. When `play(messageId, text, { streaming: true })` begins, choose playback sink:
   - Use Web Audio scheduler if supported and appropriate.
   - Use existing HTMLAudio segment queue as fallback.
2. For each `segment` event from `apiClient.streamSpeech(...)`:
   - If using Web Audio, pass bytes/media type/duration/sample rate to scheduler.
   - If using fallback, keep current Blob URL queue behavior.
3. Preserve message state updates:
   - `synthesizing` before first playable/scheduled segment.
   - `playing` once the first segment is scheduled/started.
   - `ready` after all scheduled playback ends.
   - `error` only for unrecoverable failures.
4. Preserve cancellation:
   - `stop`, `reset`, session switch, explicit interruption, and stale generation guard must abort the fetch stream and stop scheduled sources.
5. Preserve existing non-streaming playback and replay behavior.

## Output device behavior

Output device preference must remain usable.

Stage 2H should attempt this priority order:

1. If no specific output device is selected, use Web Audio with the system default output.
2. If a specific output device is selected and browser Web Audio sink APIs are available, attempt to route the `AudioContext` to that device.
3. If Web Audio output routing is unavailable or fails, fall back to existing HTMLAudio playback, which already uses `HTMLMediaElement.setSinkId()` where supported.
4. If both routing approaches fail, keep text chat usable and show the existing recoverable audio error.

This means low-gap playback is guaranteed first for default output, and opportunistically for selected devices where the browser supports Web Audio output routing.

## Error handling

Failures must be recoverable and must not break text chat.

Cases to handle:

- Web Audio unavailable.
- `AudioContext` creation rejected or suspended.
- `decodeAudioData()` failure for a segment.
- `AudioBufferSourceNode.start()` failure.
- Output sink selection rejected.
- Stream abort due to user stop/interruption/session switch.
- TTS stream returns an `error` event or no segment.

Rules:

- User-initiated aborts should not surface as scary errors.
- Web Audio failure should fall back to HTMLAudio if possible.
- If both sinks fail, display a user-facing audio error while keeping the assistant text visible.
- Stale stream completions must not restart playback or mutate the active message state.

## Testing plan

### Unit tests

Add focused tests for the scheduler module:

- Schedules two decoded buffers with the second start time equal to the first scheduled start plus first buffer duration.
- Does not wait for an `ended` event before scheduling the second segment.
- Starts immediately or with bounded lookahead when the queue underruns.
- Stops all scheduled source nodes on `stop()`.
- Reports fallback when `AudioContext` or decoding is unavailable.
- Handles decode failure without leaking scheduled nodes.

Update playback-controller tests:

- Streaming TTS uses Web Audio scheduler when available.
- Existing HTMLAudio segment queue remains fallback.
- Selected output device falls back to HTMLAudio if Web Audio sink routing is unavailable.
- Stop/interruption aborts TTS stream and stops scheduler.
- Session reset clears scheduler state.

### Regression tests

Run at least:

```powershell
npm --prefix frontend test -- src/components/MessageList.test.tsx src/App.test.tsx
npm --prefix frontend test -- src/hooks/useAudioPlaybackController.test.ts
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm --prefix frontend run test:e2e -- voice-turn.spec.ts
```

If the actual test file names differ, run the nearest existing focused tests plus the full frontend test suite.

### Runtime smoke

Use fake-provider streaming TTS with multi-segment output and observe:

- First segment schedules/starts.
- At least one later segment is scheduled before the previous segment ends.
- Stop/interruption cancels scheduled playback.
- Browser console errors are zero.

If real CosyVoice is available, run a smoke only after fake-provider validation:

- Real `/api/audio/speech/stream` returns segments.
- Browser uses Web Audio or fallback path without console errors.
- Record observed first-audio and queue metrics.

## Documentation updates after implementation

After implementation and validation only:

- Add `docs/stage2h-low-gap-streaming-audio.md` evidence.
- Update README Stage 2 voice section.
- Update `CLAUDE.md` current status from `Final seamless low-gap audio: NOT STARTED` to the verified Stage 2H result.

Do not mark Stage 2 fully complete unless all Stage 2 acceptance boundaries are verified and recorded.

## Risks and mitigations

Risk: Web Audio output routing is not consistently available.

Mitigation: keep HTMLAudio `setSinkId()` fallback and explicitly document default-output low-gap guarantee.

Risk: `decodeAudioData()` adds latency or fails on some WAV chunks.

Mitigation: keep chunks as complete standalone WAV files, add decode failure fallback, and measure first decode/queue timings.

Risk: A single real CosyVoice segment gives no segment-gap evidence.

Mitigation: fake-provider tests must generate multiple segments; real smoke validates compatibility rather than proving gapless behavior.

Risk: The Web Audio path complicates React hook state.

Mitigation: keep scheduler as a non-React module with a narrow API and keep state orchestration in the existing hook.

Risk: This is not full duplex or production ASR streaming.

Mitigation: explicitly scope this as playback-layer low-gap Stage 2H work. Full realtime session orchestration can be a later Stage 2 acceptance or post-Stage-2 optimization only after this gap is closed.

## Self-review

Placeholder scan: no TBD/TODO placeholders remain.

Consistency check: the design keeps existing backend contracts and focuses only on the browser playback sink.

Scope check: the design is one implementation slice. It does not include ASR optimization, LLM streaming, memory, emotion, wake word, or voice cloning.

Ambiguity check: selected output device behavior is explicit: try Web Audio sink support, then fallback to existing HTMLAudio `setSinkId()` path.
