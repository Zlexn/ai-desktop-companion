# Stage 2H Low-Gap Streaming Audio Playback Evidence

Status: COMPLETED on 2026-07-03.

## Scope

This slice adds a browser-side Web Audio scheduling path for existing streaming TTS segments from `POST /api/audio/speech/stream`. It preserves the existing NDJSON TTS contract and the existing HTMLAudio fallback path.

It does not implement long-term memory, emotion state, wake-word listening, background listening, LLM response streaming, or production-grade streaming ASR changes.

## Implemented behavior

- Streaming TTS segments can be decoded and scheduled on an `AudioContext` timeline.
- Each decoded segment uses a fresh `AudioBufferSourceNode`.
- Adjacent segments are scheduled by `nextStartTime` rather than waiting for an HTMLAudio `ended` event.
- Existing HTMLAudio segment playback remains available as fallback when Web Audio is unsupported or segment scheduling fails.
- Stop/reset/interruption aborts the stream and stops scheduled Web Audio sources.
- Output device preferences remain recoverable: Web Audio sink routing is attempted where supported, and HTMLAudio `setSinkId()` fallback remains available.
- Text chat remains usable if audio playback fails.
- The existing voice-turn E2E transcription mock was updated to the current streaming ASR endpoint so the test covers the app's actual Stage 2G+/2H path.

## Validation

| Command / Surface | Result |
|---|---|
| `npm --prefix frontend test -- src/audio/streamingAudioScheduler.test.ts` | PASS — 10 passed |
| `npm --prefix frontend test -- src/hooks/useAudioPlaybackController.streaming.test.tsx` | PASS — 9 passed |
| `npm --prefix frontend test -- src/audio/streamingAudioScheduler.test.ts src/hooks/useAudioPlaybackController.streaming.test.tsx src/components/MessageList.test.tsx` | PASS — 3 files, 37 tests passed |
| `npm --prefix frontend run typecheck` | PASS — `tsc -b` exited 0 |
| `npm --prefix frontend test -- src/App.test.tsx` | PASS — 21 passed |
| `npm --prefix frontend test -- --run` | PASS — 16 files, 140 tests passed |
| `npm --prefix frontend run build` | PASS — Vite built 35 modules, `✓ built in 198ms` |
| `npm --prefix frontend run test:e2e -- voice-turn.spec.ts` | PASS — 1 passed |
| `npm --prefix frontend run test:e2e` | PASS — 5 passed |

## TDD notes

- `frontend/src/audio/streamingAudioScheduler.test.ts` first failed because `streamingAudioScheduler.ts` did not exist.
- `frontend/src/hooks/useAudioPlaybackController.streaming.test.tsx` first failed because `useAudioPlaybackController` still used the older HTMLAudio-only streaming path.
- The initial full E2E run exposed a stale test route: `voice-turn.spec.ts` mocked `/api/audio/transcriptions`, while the current recorder final transcription path uses `/api/audio/transcriptions/stream`. The test was updated to mock NDJSON `start` / `final` / `done` events for the streaming endpoint.
- The E2E playback timing assertion was relaxed to tolerate Web Audio/HTMLAudio scheduling differences; low-gap ordering is covered by focused scheduler tests.

- Code review found cancellation/fallback blockers after the first implementation pass. Follow-up tests now cover stop during decode, stop during selected-output sink selection, selected-output Web Audio sink fallback, mid-stream Web Audio failure switching to active HTMLAudio fallback, and Web Audio pause/resume state correctness.

## Notes and limitations

- This is a low-gap scheduled complete-segment playback slice, not a raw PCM AudioWorklet streaming implementation.
- Real CosyVoice may return one segment for short text, so fake-provider multi-segment tests provide deterministic segment scheduling proof.
- Browser support for Web Audio output-device routing varies; fallback behavior is part of the acceptance boundary.
- FasterWhisper streaming ASR remains a feasibility layer and is not made production-grade by this slice.
- Long-term memory and emotion state remain unimplemented by project stage rule.
