# Stage 2 Voice Acceptance Audit

Status: PASS on 2026-07-06.

## Scope

This audit verifies Stage 2 voice functionality before Stage 3 long-term memory begins.

It is an acceptance audit and documentation update only. It does not implement long-term memory, emotion state, wake-word listening, background listening, raw PCM AudioWorklet streaming, or production packaging for real speech providers.

## Acceptance Boundary

Stage 2 acceptance boundary from `CLAUDE.md`:

- Voice failure must not break text chat.
- ASR can be disabled or replaced.
- TTS can be disabled or replaced.
- Microphone recording, permission handling, playback, stop/replay, recoverable errors, and VAD or explicit recording boundaries must be covered.
- End-to-end latency can be recorded.

Additional Stage 2 slices completed before this audit:

- Manual recording with Fake ASR.
- Multipart transcription API.
- Real FasterWhisper ASR provider and main-app smoke.
- Real CosyVoice HTTP TTS API/UI smoke.
- Fake-provider and real-provider half-duplex voice turns.
- VAD auto-stop.
- Explicit voice interruption.
- Audio input device selection.
- Streaming/performance measurement baseline.
- Audio output device selection and browser-local device preference persistence.
- Fake and real-provider streaming TTS slices.
- Fake/default streaming ASR slice.
- Real FasterWhisper streaming ASR feasibility layer.
- Low-gap streaming TTS playback via Web Audio scheduling with HTMLAudio fallback.

## Automated Validation

| Command | Result |
|---|---|
| `python -m pytest backend/tests` | PASS — 233 passed in 9.67s |
| `npm --prefix frontend test -- --run` | PASS — 16 files passed, 140 tests passed in 35.94s |
| `npm --prefix frontend run typecheck` | PASS — `tsc -b` exited 0 |
| `npm --prefix frontend run build` | PASS — Vite built 35 modules, `✓ built in 612ms` |
| `npm --prefix frontend run test:e2e` | PASS — 5 Playwright tests passed in 8.9s |

## Manual / Real Provider Evidence

This audit did not re-run microphone, speaker, GPU FasterWhisper, DeepSeek, or local CosyVoice manual smoke tests. Those checks depend on local hardware, local provider services, API credentials, or operator audio confirmation.

Existing recorded evidence remains the basis for those real-provider/manual surfaces:

- Real ASR main-app smoke: recorded in `CLAUDE.md` and earlier Stage 2 evidence.
- CosyVoice real TTS API/UI smoke: recorded in `CLAUDE.md` and README.
- Real-provider full half-duplex voice turn: `docs/stage2c-half-duplex-voice-turn.md`.
- VAD auto-stop headed browser smoke: `docs/stage2d-vad-auto-stop.md`.
- Real CosyVoice streaming TTS vertical slice: `docs/stage2f4-real-cosyvoice-streaming-tts.md`.
- Real FasterWhisper streaming ASR feasibility smoke: `docs/stage2g2-real-fasterwhisper-streaming-asr-feasibility.md`.
- Low-gap streaming audio playback validation: `docs/stage2h-low-gap-streaming-audio.md`.

## Limitations

- Real TTS still requires a separately started local CosyVoice HTTP service.
- Real FasterWhisper streaming ASR remains an opt-in feasibility layer based on cumulative-window batch decoding, not production-grade low-latency streaming ASR.
- Low-gap playback schedules complete WAV segments; it is not raw PCM AudioWorklet streaming.
- Browser support for audio output device routing varies; HTMLAudio fallback remains part of the supported boundary.
- The project still uses text as the internal standard exchange format.
- Stage 3 long-term memory and Stage 4 emotion state remain unimplemented in this audit.

## Stage Decision

Stage 2 acceptance audit: PASS.

The Stage 2 acceptance boundary is satisfied by the recorded Stage 2 evidence plus this full automated regression run. Stage 2 can be marked completed. At the time of this audit, Stage 3 could begin with a memory foundation design task.

No Stage 3 implementation was performed in this audit.

## Historical Next Minimal Stage 3 Task

At the time of this 2026-07-06 Stage 2 audit, the recommended next task was Stage 3 memory foundation design and first vertical slice. That task has since been completed as Stage 3A, followed by 3B–3H. This section is retained only as historical audit evidence; the current next task is tracked in `CLAUDE.md` and `README.md`.

Original minimum complete loop for that task:

1. Define the long-term memory data model with source, timestamp, type, importance, confidence, and audit fields.
2. Add storage separate from chat messages and session summaries.
3. Add backend CRUD endpoints to list, create, update, and delete memories.
4. Add tests proving memories are not silently overwritten and chat history is not treated as long-term memory.
5. Add a small UI surface to view/delete manually created memories.
6. Do not implement emotion state in Stage 3.
