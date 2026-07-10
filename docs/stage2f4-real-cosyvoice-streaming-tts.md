# Stage 2F-4 Real CosyVoice Streaming TTS Evidence

Status: COMPLETED on 2026-06-30.

## Scope

This slice adds opt-in real CosyVoice streaming TTS to the existing `POST /api/audio/speech/stream` NDJSON contract. It preserves fake-provider streaming and the non-streaming `POST /api/audio/speech` path.

It does not implement streaming ASR, LLM response streaming, final seamless low-gap audio playback, long-term memory, or emotion behavior.

## Implemented behavior

- Local CosyVoice smoke server accepts `stream: true` and returns `application/x-ndjson` segment events.
- `CosyVoiceHTTPProvider.synthesize_stream(...)` requests streaming mode and yields validated `SpeechSynthesisSegment` objects.
- Backend `POST /api/audio/speech/stream` can use the explicit `TTS_PROVIDER=cosyvoice-http` provider path.
- Existing fake-provider streaming remains the default automated path.
- Existing non-streaming `POST /api/audio/speech` remains available.
- Existing browser voice-turn path can trigger real CosyVoice streaming playback through `/api/audio/speech/stream`.

## Validation

| Command | Result |
|---|---|
| `python -m pytest backend/tests/test_cosyvoice_http_streaming_provider.py backend/tests/test_api_audio_streaming_cosyvoice.py backend/tests/test_api_audio_streaming.py backend/tests/test_cosyvoice_http_provider.py backend/tests/test_tts_service.py -v` | PASS — 32 passed |
| `python -m pytest backend/tests -v` | PASS — 218 passed |
| `npm --prefix frontend test -- --run src/api/speechStream.test.ts src/components/MessageList.test.tsx src/App.test.tsx scripts/measure-voice-turn-summary.test.mjs` | PASS — 4 files, 45 tests passed |
| `npm --prefix frontend test -- --run` | PASS — 12 files, 115 tests passed |
| `npm --prefix frontend run typecheck` | PASS — `tsc -b` exited 0 |
| `npm --prefix frontend run build` | PASS — Vite built 33 modules, `✓ built in 273ms` on final rerun |
| `npm --prefix frontend run test:e2e` | PASS after E2E synchronization fix — 5 passed |
| `python scripts/smoke_cosyvoice_streaming_tts.py --url http://127.0.0.1:8000/api/audio/speech/stream --text "这是一个本地流式语音合成测试。"` | PASS — 1 segment, provider `cosyvoice-http`, model `Fun-CosyVoice3-0.5B-2512` |
| Browser voice-turn smoke through `http://127.0.0.1:15176/` with real backend/CosyVoice streaming TTS | PASS — `/api/audio/speech/stream` returned 200 `application/x-ndjson`, first audio play observed, 0 console errors |
| Blank streaming TTS request probe via `POST /api/audio/speech/stream` with blank text | PASS — HTTP 422 before streaming body, confirming pre-stream request validation |

## Real streaming API smoke observations

- Provider: `cosyvoice-http`
- Model: `Fun-CosyVoice3-0.5B-2512`
- Segment count: 1
- First backend segment received: 11707 ms
- Stream done: 11708 ms
- Segment sample rates: 24000 Hz
- Segment durations: 3240 ms
- Segment byte lengths: 155564 bytes
- Text length: 15 characters
- CosyVoice server first segment elapsed: 10610 ms
- CosyVoice server total elapsed: 10619 ms
- GPU or memory observation: not recorded; server log noted ONNX Runtime CUDA provider unavailable and CPU provider available for that component.

## Browser smoke observations

- Browser smoke status: PASS
- Surface: browser voice-turn path using mocked microphone/ASR input, real main backend, and real local CosyVoice streaming TTS.
- Request: `POST /api/audio/speech/stream`
- Response: HTTP 200, `application/x-ndjson`
- Stream segment count observed in CosyVoice server log: 2
- Browser first audio play callback: 7281 ms after smoke start
- Browser stream finished: 11095 ms after smoke start
- CosyVoice server first browser segment elapsed: 6230 ms
- CosyVoice server second browser segment elapsed: 3821 ms
- CosyVoice server browser stream total elapsed: 10057 ms
- Console error count: 0
- Playback started: yes
- First segment audible/playable: playback start was observed through the browser audio play callback; no human audible confirmation was required for this automated smoke.
- Stop/interruption checked: no; this smoke focused on real streaming TTS playback reachability.

## E2E synchronization fix during validation

The first full Playwright E2E run had one flaky failure in `frontend/e2e/voice-recorder.spec.ts`: after clicking `新建会话`, the test filled the textbox before the new session selection stabilized, and the input was reset before clicking `发送`. The neighboring E2E already waited for the `新会话` heading before typing. The validation added the same wait to the flaky test, then reran E2E successfully with 5 passed.

A later E2E rerun once timed out while waiting for Playwright `webServer` startup before any test executed. The failing single test then passed alone, and the full E2E suite passed on the next run. This was treated as a transient startup issue, not a product behavior failure.

## Limitations

- Segments are independent WAV files; this is not final seamless low-gap audio streaming.
- Streaming ASR is not implemented.
- LLM response streaming is not implemented.
- Long-term memory and emotion state are not implemented.
- Real provider streaming remains opt-in and requires the local CosyVoice service.
- The real API smoke first segment arrived after about 11.7 seconds for the short synthetic sentence; this validates real streaming plumbing, not final realtime latency.
