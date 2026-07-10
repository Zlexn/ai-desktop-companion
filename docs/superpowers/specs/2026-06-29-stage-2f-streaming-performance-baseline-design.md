# Stage 2F-1 Streaming Performance Measurement Baseline Design

Date: 2026-06-29
Status: Recommended design for the next Stage 2 voice task.

## Context

Stage 2F-pre audio input device management is complete. The remaining Stage 2 work includes output device selection/persistence and streaming ASR/TTS. Before adding streaming, the project needs a repeatable baseline for the current non-streaming half-duplex voice turn.

The existing fake-provider browser E2E already drives the core path:

1. Start recording.
2. Stop recording.
3. Receive fake ASR transcript.
4. Click `发送并朗读`.
5. Send transcript through existing chat.
6. Render matching assistant reply.
7. Request TTS and trigger playback.

That path is ideal for a first measurement baseline because it exercises the real browser UI and app orchestration without requiring real ASR, real LLM, real TTS, GPU residency, or network providers.

## Goal

Create a repeatable fake-provider browser latency baseline for the existing non-streaming voice turn. The baseline should measure and record:

- recording click to stop click timing,
- stop click to transcript-ready timing,
- send-and-speak click to chat response timing,
- chat response to assistant-visible timing,
- TTS request/response timing,
- TTS response to playback-trigger timing,
- end-to-end timing for the measured voice turn,
- request count sanity checks,
- console/page error count.

This task produces measurement evidence only. It does not implement streaming.

## Non-goals

- No streaming ASR.
- No streaming TTS.
- No sentence-level TTS chunking in app code.
- No backend API changes.
- No database schema changes.
- No production telemetry pipeline.
- No UI debug panel.
- No real-provider latency claim.
- No output device selection.
- No Stage 3 long-term memory.
- No Stage 4 emotion behavior.

## Chosen approach

Add a dev-only Playwright measurement script:

```text
frontend/scripts/measure-voice-turn-latency.mjs
```

The script launches or connects through Playwright test-style browser automation against a running frontend/backend pair. It injects fake browser media primitives and drives the real UI. It records timing data with `performance.now()` inside the browser and request timing from Playwright route/request/response events.

The script should be deterministic enough for regression comparison but should not define performance thresholds yet. The first baseline records observed values and request counts. Later optimization tasks can compare against this baseline.

## Architecture

### Measurement script

Responsibilities:

- Launch Microsoft Edge/Chromium through Playwright.
- Add init script before page load:
  - fake `MediaRecorder`,
  - fake `navigator.mediaDevices.getUserMedia`,
  - fake `navigator.mediaDevices.enumerateDevices`,
  - fake `HTMLMediaElement.play/pause`,
  - browser-side arrays for playback and media call observations.
- Listen for console errors and page errors.
- Route `/api/audio/transcriptions` to return deterministic fake ASR JSON.
- Observe these request categories:
  - `POST /api/audio/transcriptions`,
  - `POST /api/sessions/{id}/messages`,
  - `POST /api/audio/speech`.
- Drive the UI for `N` iterations, default `3`:
  1. create or select a session,
  2. click `开始录音`,
  3. wait at least the frontend minimum recording duration,
  4. click `停止录音`,
  5. wait for `转写待确认`,
  6. click `发送并朗读`,
  7. wait for assistant reply,
  8. wait for one TTS request and one playback call.
- Emit a JSON object to stdout with per-run timings and aggregate statistics.

### Output shape

The JSON output should include:

```json
{
  "runCount": 3,
  "runs": [
    {
      "index": 1,
      "recordingMs": 350,
      "stopToTranscriptMs": 42,
      "sendToAssistantVisibleMs": 118,
      "chatRequestMs": 87,
      "ttsRequestMs": 31,
      "ttsResponseToPlayMs": 8,
      "sendToPlaybackMs": 160,
      "endToEndMs": 552,
      "transcriptionRequests": 1,
      "chatPostRequests": 1,
      "ttsRequests": 1,
      "playCalls": 1
    }
  ],
  "summary": {
    "stopToTranscriptMs": { "min": 0, "mean": 0, "max": 0 },
    "sendToAssistantVisibleMs": { "min": 0, "mean": 0, "max": 0 },
    "ttsRequestMs": { "min": 0, "mean": 0, "max": 0 },
    "sendToPlaybackMs": { "min": 0, "mean": 0, "max": 0 },
    "endToEndMs": { "min": 0, "mean": 0, "max": 0 }
  },
  "consoleErrors": [],
  "pageErrors": []
}
```

Exact numbers will vary by machine. The schema matters more than the initial values.

### Package script

Add an npm script:

```json
"measure:voice-turn": "node scripts/measure-voice-turn-latency.mjs"
```

It should assume the app is already running, or accept environment variables:

- `MEASURE_FRONTEND_URL`, default `http://127.0.0.1:15176`,
- `MEASURE_RUNS`, default `3`.

For automated validation, the implementation plan may launch backend/frontend manually around the script. Avoid adding new dependencies because Playwright is already present.

## Error handling

- If any run has request counts other than exactly one transcription/chat/TTS, mark that run invalid in JSON and exit non-zero.
- If console/page errors occur, include them and exit non-zero.
- If a UI step times out, include the current run index and step name in the thrown error.
- If the app is not reachable, fail fast with the URL.
- If `MEASURE_RUNS` is invalid, default to `3` rather than throwing.

## Privacy and safety

- The script uses fake media and fake providers only.
- No real microphone is opened.
- No real ASR/LLM/TTS provider is called.
- No raw audio is saved.
- No API keys or tokens are read or logged.
- Output contains timing values and deterministic fake text only.

## Testing plan

### Script-level test

Add a small Node test for pure helpers if the script exposes or duplicates simple pure functions is not worth it. Prefer validating the actual script by running it against the fake app, because the runtime browser surface is the purpose.

### Runtime validation

Run the script against a fake-provider backend/frontend pair:

1. Start backend with `APP_ENV=test`, `LLM_PROVIDER=fake`, fake TTS/ASR defaults.
2. Start frontend with Vite `--mode test`.
3. Run `npm run measure:voice-turn`.
4. Confirm JSON has:
   - `runCount >= 3`,
   - every run has exactly one transcription/chat/TTS request,
   - every run has one play call,
   - all measured durations are non-negative finite numbers,
   - no console/page errors.

### Regression validation

Run:

- `npm test -- --run src/App.test.tsx`,
- `npm test -- --run`,
- `npm run typecheck`,
- `npm run build`,
- `npm run test:e2e`.

## Documentation updates after implementation

- Add `docs/stage2f-streaming-performance-baseline.md` with:
  - scope,
  - command results,
  - measured JSON summary,
  - explicit limitation that fake-provider timings are not real-provider performance.
- Update `README.md` only after validation passes.
- Update `CLAUDE.md` only after validation passes.
- Add an addendum to `docs/stage2-voice-architecture.md`.

## Acceptance criteria

Stage 2F-1 measurement baseline is complete only when all are true:

- A repeatable script can measure the fake-provider browser voice turn.
- The script outputs per-run and summary JSON.
- The script validates exactly one ASR, chat, TTS, and play event per measured run.
- The script fails on console/page errors.
- The measurement evidence is recorded in docs.
- Existing frontend tests, typecheck, build, and E2E pass.
- Documentation states that no streaming has been implemented.
- No real provider performance claim is made.
- No memory or emotion behavior is introduced.

## Risks

| Risk | Mitigation |
|---|---|
| Fake timings are mistaken for real performance | Label the document as fake-provider baseline only |
| Script becomes flaky due to UI timing | Use role/text waits and request counters instead of fixed waits except minimum recording duration |
| Measurement script duplicates E2E too much | Keep it in `scripts/` and focused on timing output, not broad assertions |
| Scope drifts into optimization | Acceptance criteria require measurement only |
| Console noise causes false failure | Keep Vite test mode and capture raw console errors for diagnosis |

## Self-review

- Placeholder scan: no TODO/TBD placeholders remain.
- Internal consistency: the design is measurement-only and fake-provider-only.
- Scope check: focused on Stage 2F baseline; does not add streaming, output devices, memory, or emotion.
- Ambiguity check: output schema, request counts, failure behavior, and documentation limits are explicit.
