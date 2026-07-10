# Stage 2E Explicit Voice Interruption Evidence

Status: COMPLETED on 2026-06-29.

## Scope

Stage 2E adds explicit voice interruption: clicking `开始录音` while assistant audio is synthesizing or playing stops/aborts current audio work and starts the existing recorder/VAD/ASR flow.

This is an explicit user action only. It does not add background listening, wake word detection, automatic spoken barge-in, streaming ASR/TTS, long-term memory, or emotion behavior.

## Implementation summary

- `开始录音` is enabled while assistant-message audio is synthesizing or playing.
- Clicking `开始录音` calls the existing audio reset path before starting recording.
- Send-and-speak TTS in `synthesizing_or_playing` is explicitly interruptible.
- Voice-turn generation guards make interrupted stale TTS completion harmless.
- Recording remains blocked while voice-turn chat send is still in `sending_chat`.
- A short UI hint explains that starting recording will stop current playback.
- Playwright fake-provider E2E now starts Vite with `--mode test`, so real browser VAD is disabled by default in fake media tests. This preserves the zero-console-error expectation and keeps real VAD smoke as an opt-in path.

## Validation

| Command | Result |
|---|---|
| `npm test -- --run src/App.test.tsx -t "allows recording to explicitly interrupt assistant audio synthesis"` | PASS — 1 passed, 15 skipped |
| `npm test -- --run src/App.test.tsx -t "starts a new recording when user interrupts send-and-speak TTS"` | PASS — 1 passed, 15 skipped |
| `npm test -- --run src/App.test.tsx -t "keeps recording blocked while voice turn chat send is in flight"` | PASS — 1 passed, 15 skipped |
| `npm test -- --run src/App.test.tsx` | PASS — 16 passed |
| `npm test -- --run src/hooks/useVadAutoStop.test.ts` | PASS — 6 passed |
| `npm test -- --run` | PASS — 73 passed |
| `npm run typecheck` | PASS |
| `npm run build` | PASS |
| `npm run test:e2e` | PASS — 5 passed |

## Debug note

The first E2E run failed before the Playwright config fix: `voice-turn.spec.ts` saw a console error from real `vad-web` because Vite was running in development mode and the fake `getUserMedia` stream was not a real `MediaStream`. The root cause was the E2E server mode, not the 2E interruption logic. The fix starts the Vite web server with `--mode test`, matching the app's existing VAD test-mode gate.

## Runtime verification

A local runtime verification launched the FastAPI backend on `127.0.0.1:18101` and the Vite frontend on `127.0.0.1:15174` with fake providers and `--mode test`, then drove the browser UI through the real buttons.

Observed result:

```json
{
  "generatingVisible": true,
  "recordEnabledDuringSynthesis": true,
  "hintVisible": true,
  "stopVisible": true,
  "pendingTranscriptVisible": true,
  "staleGeneratingVisible": false,
  "speechRequests": 1,
  "consoleErrors": []
}
```

The VAD status text was not visible in this runtime smoke because VAD is intentionally disabled in Vite test mode; the VAD path is covered by the separate VAD tests and prior 2D real VAD smoke.

## Behavior verified

- `开始录音` is enabled during assistant-message TTS synthesis/playback.
- Clicking `开始录音` stops/aborts current assistant audio work and starts recording.
- `开始录音` is enabled during send-and-speak TTS synthesis/playback.
- Interrupted send-and-speak stale TTS completion does not show a false voice-turn error.
- Recording remains blocked while chat send is still in flight.
- Stage 2D VAD auto-stop/manual stop behavior remains unchanged.
- Text chat remains usable.

## Evidence notes

No raw audio, private transcript, API key, or generated speech artifact is committed by this document.
