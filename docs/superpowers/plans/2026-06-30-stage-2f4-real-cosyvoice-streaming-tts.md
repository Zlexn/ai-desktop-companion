# Stage 2F-4 Real CosyVoice Streaming TTS Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify and finish the opt-in real CosyVoice streaming TTS vertical slice that reuses the existing `/api/audio/speech/stream` NDJSON segment contract and records local smoke evidence.

**Architecture:** Keep the public streaming API unchanged: the main backend emits NDJSON `start` / `segment` / `done` / `error` events, where each `segment` contains one standalone base64 WAV. The local CosyVoice smoke server owns real CosyVoice inference and emits NDJSON when `stream: true`; `CosyVoiceHTTPProvider.synthesize_stream(...)` parses that stream into `SpeechSynthesisSegment` objects; existing frontend streaming playback consumes the same backend contract without UI redesign. Fake provider streaming remains the default automated path and full-WAV `/api/audio/speech` remains available.

**Tech Stack:** Python 3.11+ backend, FastAPI `StreamingResponse`, async iterators, `httpx.AsyncClient.stream`, NDJSON, base64 WAV segments, pytest with `httpx.MockTransport`, React/Vite/Vitest/Playwright existing frontend path, local Python 3.10 CosyVoice smoke server.

---

## Scope guard

Implement only the approved design in `docs/superpowers/specs/2026-06-30-stage-2f4-real-cosyvoice-streaming-tts-design.md`.

Do not implement streaming ASR, LLM response streaming, WebSockets, MediaSource, WebCodecs, raw PCM WebAudio scheduling, backend persistence changes, long-term memory, emotion state, character relationship state, voice cloning, or final seamless low-gap audio playback.

Because this repository already has many uncommitted changes and the user has not explicitly asked for a commit in this turn, every task ends with a checkpoint instead of `git commit`.

---

## Current file map

Already present and expected to be verified:

- `scripts/cosyvoice3_openai_server.py`
  - Local opt-in CosyVoice smoke server. Expected behavior: `POST /v1/audio/speech` preserves full-WAV response when `stream` is false and returns `application/x-ndjson` via `StreamingResponse` when `stream` is true.

- `backend/app/tts/cosyvoice_http_provider.py`
  - Main backend provider. Expected behavior: `synthesize(...)` still buffers a full WAV; `synthesize_stream(...)` requests `stream: true` and yields `SpeechSynthesisSegment` values parsed from upstream NDJSON.

- `backend/app/services/tts_service.py`
  - Provider-agnostic TTS validation. Expected behavior: `synthesize_stream(...)` discovers provider streaming support with `getattr(provider, "synthesize_stream", None)` and validates each segment.

- `backend/app/api/routes/audio.py`
  - Public backend audio routes. Expected behavior: `POST /api/audio/speech/stream` emits the unchanged NDJSON contract and converts provider failures after streaming begins into stream `error` events.

- `backend/tests/test_cosyvoice_http_streaming_provider.py`
  - Unit coverage for provider stream parsing and error mapping.

- `backend/tests/test_api_audio_streaming_cosyvoice.py`
  - API coverage proving `/api/audio/speech/stream` can use the mocked CosyVoice HTTP streaming provider under explicit `TTS_PROVIDER=cosyvoice-http` configuration.

- `scripts/smoke_cosyvoice_streaming_tts.py`
  - Opt-in real local smoke script for backend `/api/audio/speech/stream`.

Files to create or update after validation:

- Create: `docs/stage2f4-real-cosyvoice-streaming-tts.md`
- Modify: `CLAUDE.md`
- Modify: `README.md`

---

## Task 1: Verify current implementation matches the 2F-4 design

**Files:**
- Read: `docs/superpowers/specs/2026-06-30-stage-2f4-real-cosyvoice-streaming-tts-design.md`
- Read: `scripts/cosyvoice3_openai_server.py`
- Read: `backend/app/tts/cosyvoice_http_provider.py`
- Read: `backend/app/services/tts_service.py`
- Read: `backend/app/api/routes/audio.py`

- [ ] **Step 1: Confirm the phase and scope**

Read `CLAUDE.md` and confirm:

```text
Current phase is Stage 2 voice features.
Stage 2 remaining work includes real CosyVoice streaming TTS.
Stage 3 long-term memory is not started.
Stage 4 emotion is not started.
```

Expected: the plan remains inside Stage 2 and does not cross phase boundaries.

- [ ] **Step 2: Confirm the local CosyVoice smoke server streaming branch**

Inspect `scripts/cosyvoice3_openai_server.py`. Confirm `SpeechRequest` contains:

```py
    stream: bool = False
```

Confirm `speech(...)` contains this branch after model validation and `started = time.perf_counter()`:

```py
    if request.stream:
        return StreamingResponse(
            _speech_stream_events(request, started),
            media_type="application/x-ndjson",
        )
```

Confirm `_speech_stream_events(...)` yields:

```py
yield _ndjson_event({"type": "start", "provider": "cosyvoice-http", "model": request.model})
```

and emits segment events with these keys:

```py
{
    "type": "segment",
    "index": emitted,
    "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
    "media_type": "audio/wav",
    "duration_ms": duration_ms,
    "sample_rate": cosyvoice.sample_rate,
}
```

Expected: full-WAV non-streaming behavior is preserved and streaming is opt-in through `stream: true`.

- [ ] **Step 3: Confirm the backend provider stream parser**

Inspect `backend/app/tts/cosyvoice_http_provider.py`. Confirm `synthesize_stream(...)` sends:

```py
payload = {
    "model": self._model,
    "input": text,
    "voice": voice,
    "response_format": "wav",
    "speed": speed,
    "stream": True,
}
```

Confirm it uses:

```py
async with client.stream("POST", f"{self._base_url}/v1/audio/speech", json=payload) as response:
```

Confirm `_parse_stream_event(...)` validates `index`, `duration_ms`, `sample_rate`, `media_type == "audio/wav"`, and non-empty decoded audio bytes before returning `SpeechSynthesisSegment`.

Expected: the provider does not silently fall back to full non-streaming synthesis while claiming streaming success.

- [ ] **Step 4: Confirm public endpoint contract remains unchanged**

Inspect `backend/app/api/routes/audio.py`. Confirm `_segment_event(...)` returns:

```py
{
    "type": "segment",
    "index": segment.index,
    "audio_base64": base64.b64encode(segment.audio_bytes).decode("ascii"),
    "media_type": segment.media_type,
    "duration_ms": segment.duration_ms,
    "sample_rate": segment.sample_rate,
}
```

Confirm `synthesize_speech_stream(...)` returns:

```py
return StreamingResponse(body(), media_type="application/x-ndjson")
```

Expected: no new frontend protocol is introduced.

- [ ] **Step 5: Checkpoint**

Run:

```text
git status --short
```

Expected: no additional changes from Task 1 because it is read-only.

---

## Task 2: Run targeted backend tests for real-provider streaming wiring

**Files:**
- Test: `backend/tests/test_cosyvoice_http_streaming_provider.py`
- Test: `backend/tests/test_api_audio_streaming_cosyvoice.py`
- Test: `backend/tests/test_api_audio_streaming.py`
- Test: `backend/tests/test_cosyvoice_http_provider.py`
- Test: `backend/tests/test_tts_service.py`

- [ ] **Step 1: Run provider stream parser tests**

Run:

```text
python -m pytest backend/tests/test_cosyvoice_http_streaming_provider.py -v
```

Expected: all tests in `test_cosyvoice_http_streaming_provider.py` pass, including ordered segment parsing, malformed segment rejection, HTTP error mapping, and timeout mapping.

- [ ] **Step 2: Run API wiring test**

Run:

```text
python -m pytest backend/tests/test_api_audio_streaming_cosyvoice.py -v
```

Expected: the test passes and proves `/api/audio/speech/stream` can use a mocked `cosyvoice-http` streaming upstream when `TTS_PROVIDER=cosyvoice-http` is explicitly configured.

- [ ] **Step 3: Run existing streaming/non-streaming TTS regressions**

Run:

```text
python -m pytest backend/tests/test_api_audio_streaming.py backend/tests/test_cosyvoice_http_provider.py backend/tests/test_tts_service.py -v
```

Expected: all selected tests pass. This preserves fake streaming, full-WAV CosyVoice HTTP, and provider-agnostic TTS validation behavior.

- [ ] **Step 4: If any targeted backend test fails, stop and debug systematically**

Use the `systematic-debugging` skill before changing code. Do not patch by guesswork.

The first concrete checks are:

```text
If provider tests fail: inspect backend/app/tts/cosyvoice_http_provider.py.
If API wiring fails: inspect backend/app/api/routes/audio.py and backend/app/services/tts_service.py.
If non-streaming regressions fail: inspect whether synthesize(...) behavior or headers changed.
```

Expected: no code change is made until the failure has a reproduced cause.

- [ ] **Step 5: Checkpoint**

Run:

```text
git status --short
```

Expected: only pre-existing implementation/test files remain changed or untracked unless a deliberate fix was made after systematic debugging.

---

## Task 3: Run full automated validation

**Files:**
- No source changes expected.

- [ ] **Step 1: Run full backend test suite**

Run:

```text
python -m pytest backend/tests -v
```

Expected: full backend suite exits 0. Record the exact pass count for the evidence document.

- [ ] **Step 2: Run targeted frontend streaming regression**

Run:

```text
npm --prefix frontend test -- --run src/api/speechStream.test.ts src/components/MessageList.test.tsx src/App.test.tsx scripts/measure-voice-turn-summary.test.mjs
```

Expected: selected frontend tests exit 0. Record exact test file and test counts.

- [ ] **Step 3: Run full frontend unit tests**

Run:

```text
npm --prefix frontend test -- --run
```

Expected: frontend unit test suite exits 0. Record exact file and test counts.

- [ ] **Step 4: Run frontend typecheck and build**

Run:

```text
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

Expected: both commands exit 0. Record the build result line and build time if Vite prints one.

- [ ] **Step 5: Run Playwright E2E suite**

Run:

```text
npm --prefix frontend run test:e2e
```

Expected: Playwright exits 0. Record exact passing test count.

- [ ] **Step 6: Checkpoint**

Run:

```text
git status --short
```

Expected: validation commands did not add generated reports that should be committed. If `frontend/test-results/` changed, leave it untracked or clean it only after confirming it contains no user-created evidence.

---

## Task 4: Run opt-in real CosyVoice API streaming smoke

**Files:**
- Use: `scripts/cosyvoice3_openai_server.py`
- Use: `scripts/smoke_cosyvoice_streaming_tts.py`
- Evidence later: `docs/stage2f4-real-cosyvoice-streaming-tts.md`

- [ ] **Step 1: Confirm local real-provider prerequisites**

Run in PowerShell:

```text
Test-Path .\.venv-tts\Scripts\python.exe
Test-Path .\external\CosyVoice\pretrained_models\Fun-CosyVoice3-0.5B-2512
```

Expected:

```text
True
True
```

If either prints `False`, skip the real smoke, record the blocker, and do not mark 2F-4 complete.

- [ ] **Step 2: Start local CosyVoice smoke server**

Run in a separate terminal or a managed background task:

```text
.\.venv-tts\Scripts\python.exe -m uvicorn scripts.cosyvoice3_openai_server:app --host 127.0.0.1 --port 8001
```

Expected output includes:

```text
Uvicorn running on http://127.0.0.1:8001
```

Keep this process running for the next steps.

- [ ] **Step 3: Start the main backend with explicit real TTS provider config**

Run in a separate terminal or a managed background task:

```text
$env:LLM_PROVIDER = "fake"
$env:TTS_PROVIDER = "cosyvoice-http"
$env:TTS_COSYVOICE_BASE_URL = "http://127.0.0.1:8001"
$env:TTS_COSYVOICE_MODEL = "Fun-CosyVoice3-0.5B-2512"
$env:TTS_COSYVOICE_TIMEOUT_SECONDS = "120"
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Expected output includes:

```text
Uvicorn running on http://127.0.0.1:8000
```

- [ ] **Step 4: Run API streaming smoke**

Run:

```text
python scripts/smoke_cosyvoice_streaming_tts.py --url http://127.0.0.1:8000/api/audio/speech/stream --text "这是一个本地流式语音合成测试。"
```

Expected JSON shape:

```json
{
  "status": "PASS",
  "provider": "cosyvoice-http",
  "model": "Fun-CosyVoice3-0.5B-2512",
  "segment_count": 1,
  "first_segment_ms": 1,
  "done_ms": 1,
  "segments": [
    {
      "index": 0,
      "bytes_len": 1,
      "duration_ms": 1,
      "sample_rate": 24000,
      "received_ms": 1
    }
  ],
  "text_length": 15
}
```

The numeric values above are minimum-shape examples. The actual run must record its actual positive values in the evidence document. The command passes only if `status` is `PASS`, `segment_count` is at least 1, `provider` is `cosyvoice-http`, and every segment has `sample_rate` greater than 0, `duration_ms` greater than 0, and `bytes_len` greater than 0.

- [ ] **Step 5: Record CosyVoice server timing lines**

From the CosyVoice server terminal, record lines like:

```text
speech stream request input_len=15 voice='default-zh-female' speed=1.0 segments=1
speech stream segment 1/1 chars=15 duration_ms=<actual-duration> elapsed_ms=<actual-elapsed>
speech stream done segments=1 total_ms=<actual-total>
```

Only record timings, lengths, provider/model, and counts. Do not record private transcript content, prompt audio, API keys, or generated audio bytes.

- [ ] **Step 6: Stop real-provider processes**

Stop the CosyVoice and backend server processes started in this task. Confirm no GPU-heavy CosyVoice process remains unintentionally running.

---

## Task 5: Run browser smoke for real streaming playback

**Files:**
- Use existing frontend app and backend from Task 4.
- Evidence later: `docs/stage2f4-real-cosyvoice-streaming-tts.md`

- [ ] **Step 1: Start frontend**

Run:

```text
npm --prefix frontend run dev -- --host 127.0.0.1 --port 15176
```

Expected output includes:

```text
Local:   http://127.0.0.1:15176/
```

- [ ] **Step 2: Open the app and trigger one streaming TTS playback**

Use a non-private synthetic prompt such as:

```text
请用一句话说明今天的语音流式播放测试。
```

Trigger the existing voice-turn playback path that calls `/api/audio/speech/stream`. Do not test with private microphone recordings or private transcript content.

Expected:

```text
The assistant text remains visible.
The browser requests /api/audio/speech/stream.
Playback starts from the first real CosyVoice segment.
No console errors are produced.
Stop or interruption still stops playback if tested.
```

- [ ] **Step 3: Record browser observations**

Record these actual observations for the evidence document:

```text
Browser smoke status: PASS or FAIL
Console error count: actual count
Playback started: yes or no
First segment audible/playable: yes or no
Stop/interruption checked: yes or no
```

Do not claim PASS unless the browser smoke actually ran.

- [ ] **Step 4: Stop frontend and backend processes**

Stop frontend, backend, and CosyVoice processes if they are still running.

Expected: no long-running local servers remain unless the user explicitly wants to keep them open.

---

## Task 6: Document evidence and update project status

**Files:**
- Create: `docs/stage2f4-real-cosyvoice-streaming-tts.md`
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: Create evidence document with only observed results**

Create `docs/stage2f4-real-cosyvoice-streaming-tts.md` after Tasks 2-5 have run. The document must include these sections:

```md
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

## Validation

| Command | Result |
|---|---|
```

Then add one row per command actually run in Tasks 2-5, using exact observed results. For example, if the full backend suite printed `217 passed`, write `PASS — 217 passed`. If a real smoke was skipped because a prerequisite was missing, write `SKIPPED — <actual reason>` and do not mark the stage completed.

Add these sections using actual observations:

```md
## Real streaming API smoke observations

- Provider: cosyvoice-http
- Model: Fun-CosyVoice3-0.5B-2512
- Segment count: <actual count>
- First backend segment received: <actual ms> ms
- Stream done: <actual ms> ms
- Segment sample rates: <actual sample rates>
- Segment durations: <actual durations> ms
- Segment byte lengths: <actual lengths>
- CosyVoice server first segment elapsed: <actual ms> ms
- CosyVoice server total elapsed: <actual ms> ms
- GPU or memory observation: <actual observation or "not recorded">

## Browser smoke observations

- Browser smoke status: <PASS or FAIL>
- Console error count: <actual count>
- Playback started: <yes or no>
- First segment audible/playable: <yes or no>
- Stop/interruption checked: <yes or no>

## Limitations

- Segments are independent WAV files; this is not final seamless low-gap audio streaming.
- Streaming ASR is not implemented.
- LLM response streaming is not implemented.
- Long-term memory and emotion state are not implemented.
- Real provider streaming remains opt-in and requires the local CosyVoice service.
```

Before completing this step, ensure the evidence document contains no private transcript content, generated audio bytes, API keys, unresolved placeholders, or false completion claims.

- [ ] **Step 2: Update `CLAUDE.md` only after validation and real smoke pass**

Update the current-stage line and Stage 2 table to include:

```text
2F-4 Real CosyVoice Streaming TTS Vertical Slice COMPLETED
```

Add this completed-capability bullet under Stage 2:

```md
- 子任务 2F-4：Real CosyVoice streaming TTS vertical slice 已完成（2026-06-30；本地 CosyVoice smoke server 支持 opt-in streaming NDJSON 分段 WAV；`CosyVoiceHTTPProvider.synthesize_stream(...)` 可解析真实 provider streaming response 并通过 `/api/audio/speech/stream` 输出 segment；fake/default 自动化回归保持 PASS；真实本地 API smoke 与浏览器 smoke 结果记录于 `docs/stage2f4-real-cosyvoice-streaming-tts.md`）。未实现流式 ASR、最终无缝低间隙音频流、长期记忆或情感系统。
```

Update the remaining Stage 2 list so `真实 CosyVoice streaming TTS` is no longer listed as unimplemented. Keep these limitations listed:

```md
- 流式 ASR。
- 最终无缝低间隙音频流。
```

- [ ] **Step 3: Update `README.md`**

Add this concise section after the Stage 2F-3 section:

```md
### Stage 2F-4 real CosyVoice streaming TTS vertical slice

The opt-in real CosyVoice path can use the existing `/api/audio/speech/stream` NDJSON streaming contract to return standalone WAV segments. Existing fake streaming and non-streaming TTS paths remain available.

Verification result on 2026-06-30: **PASS** — backend CosyVoice streaming provider tests, API wiring tests, fake/default regressions, real local CosyVoice streaming API smoke, and browser streaming playback smoke passed. Evidence is recorded in `docs/stage2f4-real-cosyvoice-streaming-tts.md`.

This is a feasibility/vertical-slice smoke, not final seamless low-gap streaming, streaming ASR, long-term memory, or emotion behavior.
```

If the real browser smoke did not pass, do not use the PASS paragraph above. Instead keep README unchanged or add a clearly marked in-progress note only after user approval.

- [ ] **Step 4: Sanity-check documentation diff**

Run:

```text
git diff -- docs/stage2f4-real-cosyvoice-streaming-tts.md CLAUDE.md README.md
```

Expected:

```text
The diff records only observed validation results.
The diff does not claim streaming ASR, seamless low-gap audio, long-term memory, or emotion is complete.
The diff does not include private transcript text, API keys, prompt audio, generated audio bytes, or secrets.
```

---

## Task 7: Final review and handoff

**Files:**
- Review: all files changed during 2F-4.

- [ ] **Step 1: Run final status check**

Run:

```text
git status --short
```

Expected: changed files are limited to the 2F-4 implementation, tests, smoke script, and documentation evidence/status updates.

- [ ] **Step 2: Run final diff review**

Run:

```text
git diff -- backend/app/tts/cosyvoice_http_provider.py backend/app/api/routes/audio.py backend/app/services/tts_service.py scripts/cosyvoice3_openai_server.py scripts/smoke_cosyvoice_streaming_tts.py backend/tests/test_cosyvoice_http_streaming_provider.py backend/tests/test_api_audio_streaming_cosyvoice.py docs/stage2f4-real-cosyvoice-streaming-tts.md CLAUDE.md README.md
```

Expected:

```text
No unrelated refactor.
No provider SDK calls outside provider/smoke-server boundaries.
No secrets or raw audio bytes.
No Stage 3 memory implementation.
No Stage 4 emotion implementation.
```

- [ ] **Step 3: Prepare final report**

Report using the project-required format:

```text
完成内容：
修改文件：
验证命令与结果：
未完成或受限部分：
是否改变当前阶段：否/是（附验收证据）
下一项建议任务：
```

The next suggested task should remain inside Stage 2 unless all Stage 2 acceptance criteria are documented as passed. Based on the current project state, the likely next Stage 2 task after 2F-4 is streaming ASR or final low-gap audio playback measurement, not Stage 3 memory.

---

## Self-review notes

Spec coverage:

- Keep public streaming contract unchanged: Tasks 1-3 verify provider/API/frontend regressions.
- Local CosyVoice server opt-in streaming mode: Task 1 verifies code and Task 4 runs real server smoke.
- `CosyVoiceHTTPProvider.synthesize_stream(...)`: Tasks 1-2 verify parser and error handling.
- Backend `/api/audio/speech/stream` real-provider wiring: Task 2 verifies with mocked upstream and Task 4 verifies with real upstream.
- Browser playback proof: Task 5.
- Evidence and status updates: Task 6.
- Phase boundaries and non-goals: scope guard, Task 6 limitations, Task 7 final report.

Placeholder scan:

- The plan contains no unresolved placeholder markers. Evidence values are intentionally captured after commands run; the evidence file itself must contain actual observed values before completion.

Type consistency:

- Streaming provider method remains `synthesize_stream(...)`.
- Streaming segment type remains `SpeechSynthesisSegment`.
- Public endpoint remains `POST /api/audio/speech/stream`.
- Stream media type remains `application/x-ndjson`.
- Segment audio media type remains `audio/wav`.

Risk controls:

- Real-provider work is opt-in through explicit environment variables.
- Fake/default automated paths remain required regressions.
- Full-WAV non-streaming TTS remains required regression.
- No memory or emotion behavior is added in this plan.
