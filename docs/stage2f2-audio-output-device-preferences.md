# Stage 2F-2 Audio Output Device Selection and Device Preference Persistence Evidence

Status: COMPLETED on 2026-06-29.

## Scope

This slice adds browser-local audio device preference persistence and output-device selection for assistant TTS playback.

It persists only opaque browser device IDs in localStorage. It does not persist raw audio, device labels, transcripts, messages, or provider secrets.

It does not implement streaming ASR, streaming TTS, backend storage, long-term memory, or emotion behavior.

## Implemented behavior

- Microphone selection is restored from browser-local preference when the saved device still exists.
- Stale microphone preference resets to system default after successful enumeration.
- Assistant speech playback can use a selected output device in browsers that support `HTMLMediaElement.setSinkId`.
- Output selection falls back to system default when unsupported.
- Stale output preference resets to system default after successful enumeration.
- Output-device selection failure does not break text chat, ASR, TTS synthesis, or default playback retry.

## Validation

| Command | Result |
|---|---|
| `npm --prefix frontend test -- --run src/audioDevicePreferences.test.ts` | PASS — 8 passed |
| `npm --prefix frontend test -- --run src/hooks/useAudioInputDevices.test.ts` | PASS — 9 passed |
| `npm --prefix frontend test -- --run src/hooks/useAudioOutputDevices.test.ts` | PASS — 7 passed |
| `npm --prefix frontend test -- --run src/components/MessageList.test.tsx` | PASS — 15 passed |
| `npm --prefix frontend test -- --run src/App.test.tsx` | PASS — 21 passed |
| `npm --prefix frontend run test:e2e -- voice-turn.spec.ts` | PASS — 1 passed |
| `npm --prefix frontend test -- --run` | PASS — 106 passed |
| `npm --prefix frontend run typecheck` | PASS |
| `npm --prefix frontend run build` | PASS — built in 201 ms |
| `npm --prefix frontend run test:e2e` | PASS — 5 passed |

## Browser support note

Output-device selection depends on browser support for `HTMLMediaElement.setSinkId`. When unsupported, the UI reports that the system default output device will be used. The app keeps text chat, recording, ASR, and TTS playback through the default output available.

## Phase boundary

This remains Stage 2 voice-device management. Streaming ASR/TTS, long-term memory, and emotion state remain unimplemented.
