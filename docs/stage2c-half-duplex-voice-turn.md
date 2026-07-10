# Stage 2C Half-Duplex Voice Turn Evidence

## 2C-1 Fake-provider baseline

Status: COMPLETED on 2026-06-27.

Validation:

| Command | Result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest backend/tests -v` | PASS — 204 passed, 1 warning |
| `npm test -- --run` | PASS — 61 passed |
| `npm run typecheck` | PASS |
| `npm run build` | PASS |
| `npm run test:e2e` | PASS — 5 passed |

Behavior verified:

- Pending transcript can be sent with `发送并朗读`.
- The app selects the assistant message produced by that send using a stable post-send rule.
- The selected assistant reply is synthesized through the existing TTS playback controller.
- TTS failure after chat success keeps text messages visible and reports a recoverable voice error.
- Recording and TTS synthesis/playback are mutually exclusive through global audio busy state.
- Session switch/create/delete clears stale voice-turn state through a generation guard.
- Duplicate `发送并朗读` calls are blocked by a synchronous in-flight latch.
- E2E asserts exactly one chat send and exactly one TTS request for the fake full-turn path.
- Normal text chat remains usable.

Implementation boundary:

- Frontend orchestrates existing `/api/audio/transcriptions`, `/api/sessions/{session_id}/messages`, and `/api/audio/speech` paths.
- No backend `/voice-turns` endpoint was added.
- No database schema changes were made.
- No VAD, interruption, streaming, long-term memory, or emotion behavior was added.

## 2C-2 Real-provider full-turn smoke

Status: COMPLETED on 2026-06-28.

Validation attempts:

| Command | Result |
|---|---|
| Headed real-provider full-turn smoke after shortening the smoke's real DeepSeek reply cap to 24 tokens; operator confirmed audible playback in the Claude session on 2026-06-28 | PASS — real FasterWhisper ASR, real DeepSeek actual assistant reply (`reply_length=40`), CosyVoice HTTP TTS, browser Blob non-silence stats (`likelySilent=false`), `Audio.play()` completion, 0 console errors, and operator audible confirmation all succeeded |
| `$env:REAL_FULL_TURN_REQUIRE_AUDIO_CONFIRM='0'; $env:REAL_FULL_TURN_HEADLESS='1'; .\scripts\smoke_real_full_turn_ui.ps1` after shortening the smoke's real DeepSeek reply cap to 24 tokens on 2026-06-28 | PARTIAL PASS — real ASR, real DeepSeek actual assistant reply (`reply_length=44`, `finish_reason=length`), CosyVoice HTTP TTS, browser Blob non-silence stats (`likelySilent=false`), and `Audio.play()` completion all succeeded with 0 console errors; verdict remains FAIL only because audible confirmation was intentionally skipped |
| `$env:REAL_FULL_TURN_REQUIRE_AUDIO_CONFIRM='0'; $env:REAL_FULL_TURN_HEADLESS='1'; .\scripts\smoke_real_full_turn_ui.ps1` after Vite proxy timeout fix on 2026-06-28 | PARTIAL PASS — real FasterWhisper ASR, real DeepSeek chat, actual assistant reply CosyVoice HTTP TTS, browser Blob non-silence stats, and `Audio.play()` completion all succeeded; verdict remains FAIL only because audible confirmation was intentionally skipped |
| `$env:REAL_FULL_TURN_REQUIRE_AUDIO_CONFIRM='0'; $env:REAL_FULL_TURN_HEADLESS='1'; .\scripts\smoke_real_full_turn_ui.ps1` after starting CosyVoice on 2026-06-28 | FAIL — real FasterWhisper ASR and real DeepSeek chat completed; evidence JSON sanitization was fixed; `/api/audio/speech` returned 504 `tts_timeout`, so no audio Blob stats or audible confirmation were produced |
| `$env:REAL_FULL_TURN_REQUIRE_AUDIO_CONFIRM='0'; $env:REAL_FULL_TURN_HEADLESS='1'; .\scripts\smoke_real_full_turn_ui.ps1` on 2026-06-28 after adding WAV stats capture | BLOCKED — preflight could not connect to `http://127.0.0.1:8001/health`, so no new full-turn audio response was generated in this run |
| `Invoke-WebRequest 'http://127.0.0.1:8001/health' -TimeoutSec 5` on 2026-06-28 follow-up loop | BLOCKED — CosyVoice HTTP service was still unreachable, so the real full-turn smoke was not rerun |
| `./scripts/smoke_real_full_turn_ui.ps1` with `REAL_FULL_TURN_REQUIRE_AUDIO_CONFIRM=0`, headed browser, and post-TTS duration wait | FAIL — real ASR, real LLM, full assistant-reply CosyVoice HTTP TTS, and browser playback request path completed with console error count 0, but the operator confirmed no audible assistant playback |
| `./scripts/smoke_real_full_turn_ui.ps1` with `REAL_FULL_TURN_REQUIRE_AUDIO_CONFIRM=0` | PARTIAL PASS — real ASR, real LLM, full assistant-reply CosyVoice HTTP TTS, and browser playback request path completed with console error count 0; audible playback was intentionally not operator-confirmed in this automated diagnostic run |

Observed provider path:

- ASR: PASS — `faster-whisper` / `medium@08e178d48790749d25932bbc082711ddcfdfbc4f`; latest headed run `duration_ms=6677`, `inference_ms=3378`.
- LLM: PASS — `deepseek` / `deepseek-v4-flash`; latest headed run assistant text reply was generated and persisted (`reply_length=40`).
- TTS: PASS at HTTP and browser Blob layer after Vite proxy timeout fix and shortened smoke reply cap — `/api/audio/speech` returned HTTP 200 `audio/wav`, provider `cosyvoice-http`, model `Fun-CosyVoice3-0.5B-2512`, latest `duration_ms=9440`, `sample_rate=24000`; browser-side Blob stats were `format=pcm16`, `bytes=453164`, `peakAbs=32440`, `rms=3369.84`, `nonSilentSampleRatio=0.5943`, `likelySilent=false`.
- Browser playback event path: PASS — `Audio.play()` resolved, media `readyState` reached 4, `currentTime` advanced to 9.44s, and playback ended with console error count 0.
- Browser audible playback: PASS — operator confirmed hearing the actual assistant reply in the Claude session on 2026-06-28.

Current classification:

- Classification: `PASS` — 2C-2 real-provider full-turn smoke completed.
- Browser console error count: 0 in the latest headed audible-confirmed run.
- Audible playback confirmed: yes — operator confirmed hearing the actual assistant reply in the Claude session on 2026-06-28.
- Evidence JSON: `frontend/test-results/real-full-turn-ui-smoke.json`.
- Screenshot: `frontend/test-results/real-full-turn-ui-smoke.png`.

Root-cause and repair evidence:

- Earlier full-turn attempts failed because `/api/audio/speech` timed out for longer assistant replies. 2C-2R fixed that layer by changing the local CosyVoice smoke server to segment text, call CosyVoice with `stream=True`, collect chunks, and return one WAV.
- A later headless Playwright run failed before ASR because the synthetic recording driver could race with new-session loading and its fake `MediaStreamTrack.stop()` dispatched an `ended` event unlike a local real track stop.
- The smoke driver now waits for the new-session POST/loading state to settle before clicking `开始录音`, and the fake track no longer dispatches `ended` from local `stop()`.
- After that repair, a no-audio-confirmation diagnostic completed the full natural assistant-reply path: FasterWhisper ASR -> explicit `发送并朗读` -> DeepSeek reply -> CosyVoice HTTP full-reply TTS HTTP 200, with 0 console errors.
- A later headed diagnostic kept the browser open past the returned TTS duration (`duration_ms=12920`) and still had 0 console errors, but the operator confirmed no audible assistant playback.
- A follow-up instrumented diagnostic showed browser-level playback succeeded: `Audio.play()` was called and resolved, media `readyState` reached 4, duration was 13.28s, currentTime advanced from 0 to 13.28, and playback reached an ended/paused state with 0 console errors.
- On 2026-06-28 the smoke driver gained non-sensitive WAV PCM statistics for `/api/audio/speech` responses (`bytes`, `sampleRate`, `channels`, `sampleCount`, `peakAbs`, `rms`, `nonSilentSampleRatio`, `likelySilent`). This is intended to separate silent/invalid TTS output from browser or operating-system output routing problems without saving audio.
- The first 2026-06-28 attempt to collect those WAV stats was blocked before backend/frontend startup because the local CosyVoice HTTP service was not running at `127.0.0.1:8001`; no new conclusion about natural assistant-reply audibility was drawn from that run.
- A follow-up 2026-06-28 loop rechecked the same `/health` endpoint and found CosyVoice still unreachable; lightweight WAV stats tests and smoke driver syntax checks continued to pass.
- A later 2026-06-28 loop started the local CosyVoice HTTP server successfully (`/health` returned HTTP 200, model load about 15.8s) and reran the headless real-provider full-turn diagnostic. That run completed real ASR and real DeepSeek chat, but `/api/audio/speech` returned HTTP 504 `tts_timeout`; no audio Blob stats or audible confirmation were produced.
- The 2026-06-28 evidence-quality fix changed smoke JSON sanitization so message arrays store only `content_preview`/`content_length`, redacted IDs, and non-secret metadata; the page-level `bodyTextPreview` field was removed and replaced by `bodyTextLength` to avoid storing full visible conversation text. It also added browser-side speech Blob stats collection at the same `response.blob()` boundary used by app playback.
- Root cause for the later 504 was the frontend dev-server proxy timing out before the backend/CosyVoice path completed. Direct CosyVoice and direct backend `/api/audio/speech` calls for a similar 63-character assistant reply succeeded, while the Vite-proxied browser path returned 504 until `frontend/vite.config.ts` was changed to use explicit `/api` and `/health` proxy objects with a 300s `timeout`/`proxyTimeout`.
- After the Vite proxy timeout fix and shortened smoke reply cap, the headed real-provider smoke completed actual assistant-reply TTS with non-silent browser Blob stats, successful browser playback events, and operator audible confirmation.
- 2C-2 is complete. Stage 2 remains open for VAD, interruption, audio device management, and streaming/performance follow-up work.

Privacy and artifact notes:

- No API key values were printed in the recorded evidence.
- No raw microphone recording or generated TTS audio is committed.
- This remains a technical local TTS smoke only; it does not clone or imitate Yukinoshita Yukino, any voice actor, celebrity, or unauthorized voice.

## 2C-2T CosyVoice TTS-only stability smoke

Status: COMPLETED on 2026-06-27 as an isolation diagnostic only. This does not complete 2C-2 full-turn smoke.

Validation:

| Command | Result |
|---|---|
| Backend `/api/audio/speech` with ASCII text `OK.` and `TTS_PROVIDER=cosyvoice-http` | PASS — HTTP 200 `audio/wav`, provider `cosyvoice-http`, model `Fun-CosyVoice3-0.5B-2512`, duration 600 ms, elapsed 3369 ms, 28844 bytes |
| Backend `/api/audio/speech` with UTF-8 Chinese text `好的。` and `TTS_PROVIDER=cosyvoice-http` | PASS — HTTP 200 `audio/wav`, provider `cosyvoice-http`, model `Fun-CosyVoice3-0.5B-2512`, duration 880 ms, elapsed 2076 ms, 42284 bytes |
| Direct CosyVoice `/v1/audio/speech` with 71-character assistant-style Chinese reply after segmented synthesis fix | PASS — HTTP 200 `audio/wav`, duration 16360 ms, elapsed 19789 ms, 785324 bytes |
| Main backend `/api/audio/speech` with same 71-character assistant-style Chinese reply after segmented synthesis fix | PASS — HTTP 200 `audio/wav`, provider `cosyvoice-http`, model `Fun-CosyVoice3-0.5B-2512`, duration 16000 ms, elapsed 18423 ms, 768044 bytes |

Diagnostic conclusions:

- Main backend TTS provider wiring to CosyVoice HTTP works for short text.
- The earlier PowerShell short-Chinese request that returned `tts_unavailable` was caused by sending a non-UTF-8 JSON body; CosyVoice logged the input as `???` and returned no audio chunks.
- Explicit UTF-8 request bytes fix that diagnostic path.
- Web research against the official CosyVoice repository found that CosyVoice inference methods expose a `stream` argument and the official FastAPI example returns generated chunks through `StreamingResponse`, but the project-local OpenAI-compatible smoke server had been waiting for a whole `stream=False` generation and using only the first chunk.
- The local smoke server now splits long TTS text into bounded sentence-like segments, calls CosyVoice with `stream=True`, collects all chunks for each segment, adds short silence between segments, and returns one WAV.
- After that fix, the previous long assistant-reply timeout is resolved at both the direct CosyVoice HTTP layer and the main backend `/api/audio/speech` layer.
- Superseded by the later diagnostics in the 2C-2 section above: the synthetic recording instability and long-text proxy timeout have since been repaired for the smoke path.
- Do not mark 2C-2 complete until the real browser full-turn path produces audible playback of the intended assistant reply and records PASS.

## 2C-2S Short deterministic playback full-turn smoke

Status: COMPLETED on 2026-06-27 as a wiring diagnostic only. This does not complete natural full-reply TTS playback.

Validation:

| Command | Result |
|---|---|
| `.\scripts\smoke_real_full_turn_ui.ps1` with smoke-only `REAL_FULL_TURN_TTS_TEXT_OVERRIDE` | PASS — real FasterWhisper ASR, real DeepSeek chat, message persistence, CosyVoice HTTP TTS, and browser audio playback completed with console error count 0 |

Observed provider path:

- ASR: PASS — `faster-whisper` / `medium@08e178d48790749d25932bbc082711ddcfdfbc4f`; `duration_ms=6677`, `inference_ms=3705`.
- LLM: PASS — `deepseek` / `deepseek-v4-flash`; assistant reply was generated and persisted (`reply_length=103`).
- TTS: PASS — `/api/audio/speech` returned HTTP 200 `audio/wav`, provider `cosyvoice-http`, model `Fun-CosyVoice3-0.5B-2512`, `duration_ms=640`, `sample_rate=24000`.
- Browser playback: PASS — operator confirmed audible playback.
- Browser console error count: 0.
- Evidence JSON: `frontend/test-results/real-full-turn-ui-smoke.json`.

Important limitation:

- The heard speech was the smoke-only override text `好的。`, not the full assistant reply shown in the chat UI.
- This confirms full-turn wiring across real ASR -> real LLM -> persisted messages -> CosyVoice TTS -> browser playback.
- It does not satisfy the final user experience requirement that the assistant's actual reply text is spoken aloud.
- Superseded by the later diagnostics above: full assistant-reply TTS now succeeds through the real browser smoke path after the Vite proxy timeout fix; final 2C-2 closure only needs manual audible confirmation.
