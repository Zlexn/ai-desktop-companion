# Stage 2F-3 Streaming TTS First Vertical Slice Evidence

Status: COMPLETED on 2026-06-30.

## Scope

This slice adds a fake-provider streaming TTS path using `POST /api/audio/speech/stream` and NDJSON events with standalone WAV segments. The browser can begin assistant speech playback from the first streamed segment before the stream completes.

It preserves the existing non-streaming `/api/audio/speech` path.

It does not implement streaming ASR, real-provider streaming, WebSocket voice turns, long-term memory, or emotion behavior.

## Implemented behavior

- Backend fake TTS can yield ordered standalone WAV segments.
- Streaming speech endpoint emits `start`, ordered `segment`, and `done` NDJSON events.
- Unsupported non-streaming TTS providers return a normal app error before streaming begins.
- Frontend parses chunked NDJSON from `ReadableStream` and decodes base64 WAV segment bytes.
- Voice-turn TTS playback uses the streaming path in the fake-provider browser flow.
- Streaming playback can begin after the first segment and queue later standalone WAV segments.
- Streaming playback applies existing output-device routing through the shared audio controller path.
- Stop/reset/interruption aborts stale streaming requests and cleans up generated Blob URLs.
- Fake-provider latency measurement recognizes streaming TTS requests and records first-segment timing fields.

## Validation

| Command | Result |
|---|---|
| `python -m pytest backend/tests/test_tts_streaming.py -v` | PASS — 3 passed |
| `python -m pytest backend/tests/test_api_audio_streaming.py -v` | PASS — 3 passed |
| `npm --prefix frontend test -- --run src/api/speechStream.test.ts` | PASS — 1 test file, 3 tests passed |
| `npm --prefix frontend test -- --run src/components/MessageList.test.tsx` | PASS — 1 test file, 18 tests passed |
| `npm --prefix frontend test -- --run src/App.test.tsx` | PASS — 1 test file, 21 tests passed |
| `npm --prefix frontend run test:e2e -- voice-turn.spec.ts` | PASS — 1 passed |
| `python -m pytest backend/tests -v` | PASS — 213 passed |
| `npm --prefix frontend test -- --run scripts/measure-voice-turn-summary.test.mjs` | PASS — 1 test file, 3 tests passed |
| `npm --prefix frontend test -- --run` | PASS — 12 test files, 115 tests passed |
| `npm --prefix frontend run typecheck` | PASS — `tsc -b` exited 0 |
| `npm --prefix frontend run build` | PASS — `✓ built in 208ms` |
| `npm --prefix frontend run test:e2e` | PASS — 5 passed |
| `npm --prefix frontend run measure:voice-turn` with no app running | EXPECTED FAIL — `Frontend is not reachable at http://127.0.0.1:15176` |

## Limitations

- Segments are independent WAV files; this is not final seamless audio streaming.
- Real CosyVoice streaming is not implemented in this slice.
- LLM response streaming is not implemented in this slice.
- Streaming ASR, long-term memory, and emotion state remain unimplemented.
