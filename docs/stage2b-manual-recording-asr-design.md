# Milestone 2B Manual Recording and Fake ASR Design

> Status: design only. This document does not implement code, install dependencies, download models, access the microphone, or call any real ASR/LLM API.
>
> Current phase: Stage 2 — voice features. Milestone 2A Fake TTS output loop is completed; Milestone 2B is completed.
>
> Scope lock: this design must not modify existing `ChatService` or message persistence semantics, and must not implement VAD, interruption, streaming, real ASR, long-term memory, or emotion state.

## 1. Goal and non-goals

### Goal

Milestone 2B adds the smallest safe voice-input vertical slice on top of the completed text chat and 2A Fake TTS path:

```text
explicit user click -> browser recording -> local backend upload -> Fake ASR transcript -> existing editable input box -> user manually sends if desired
```

The feature is intentionally review-first. A transcript is only a draft. It does not become a chat message until the user explicitly sends it through the existing text message flow.

### Product boundary

1. The user clicks a button to start recording.
2. The user clicks a button to stop recording.
3. The app does not continuously listen and does not use a wake word.
4. After recording stops, the browser uploads the recorded audio to the local backend.
5. Fake ASR returns deterministic test transcription.
6. The transcript only enters the existing input box.
7. The app does not auto-send by default.
8. The user can edit, clear, re-record, or manually send.
9. Existing `ChatService` and SQLite message persistence semantics remain unchanged.
10. VAD, interruption, streaming, real ASR, long-term memory, and emotion systems remain out of scope.

### Non-goals

- No real ASR provider, model download, GPU use, faster-whisper integration, FFmpeg integration, or microphone access during this design task.
- No voice-turn endpoint that calls chat and TTS together.
- No automatic chat message creation from `/api/audio/transcriptions`.
- No raw audio retention, debug archive, localStorage/IndexedDB audio cache, or SQLite audio storage.
- No changes to the Stage 1 chat request/response shape.
- No changes to the 2A Fake TTS playback contract except ensuring it still works after the frontend adds recording controls.

### Design approach considered

Recommended approach: **separate `ASRProvider` + `ASRService` + `/api/audio/transcriptions`, with frontend recorder state separate from `MessageInput` draft state but able to insert text into it after conflict handling.**

Alternative A: put ASR upload handling directly in the route. This is faster to prototype, but it mixes file validation, provider invocation, error mapping, and privacy rules into API code. It also makes future real ASR integration riskier.

Alternative B: add a combined voice-turn endpoint now. This is premature for 2B because it would couple ASR to `ChatService` and TTS before transcript review is validated. It also increases the chance of accidentally auto-creating messages.

Alternative C: put transcript state fully inside a new voice component and keep `MessageInput` isolated. This avoids touching `MessageInput`, but duplicates draft-editing behavior and makes "transcript enters the existing input box" less literal. The better 2B design is to lift or control the input draft so ASR can propose text without bypassing the existing send path.

## 2. Backend abstraction

### Package boundary

Add a new ASR-specific backend area beside, not inside, existing LLM and TTS code:

```text
backend/app/asr/base.py          # ASRProvider protocol and result dataclasses
backend/app/asr/fake_provider.py # deterministic FakeASRProvider
backend/app/asr/factory.py       # ASR provider selection; no fallback on unknown provider
backend/app/services/asr_service.py
backend/app/api/routes/audio.py  # extend existing /api/audio router with /transcriptions
backend/app/api/dependencies.py  # add get_asr_provider/get_asr_service
backend/app/core/config.py       # ASR settings only
backend/app/core/errors.py       # ASR/audio upload errors
backend/app/domain/schemas.py    # TranscriptionResponse schema
```

This deliberately keeps ASR out of:

- `LLMProvider`
- `TTSProvider` / `TTSService`
- `ChatService`
- repositories and SQLite models
- prompt rendering

The existing `audio.py` route can host both `/speech` and `/transcriptions`, but the service dependencies stay separate: `TTSService` handles 2A synthesis, `ASRService` handles 2B transcription upload validation and provider calls.

### ASRProvider protocol

The 2B interface should follow the user-requested shape:

```python
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class TranscriptionSegment:
    start_ms: int
    end_ms: int
    text: str
    confidence: float | None = None


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    detected_language: str | None
    duration_ms: int | None
    provider: str
    model: str
    inference_ms: int
    segments: list[TranscriptionSegment] = field(default_factory=list)


class ASRProvider(Protocol):
    async def transcribe(
        self,
        audio_bytes: bytes,
        media_type: str,
        language: str | None = None,
    ) -> TranscriptionResult:
        ...
```

Provider rules:

- `text` must be stripped before returning from `ASRService`.
- Success requires non-empty `text`.
- `provider` and `model` are required for observability.
- Providers must not log raw audio or full private transcript text.
- Providers must not write audio to disk unless a future real provider explicitly requires a temporary file lifecycle managed by `ASRService`.

### ASRService responsibilities

`ASRService` owns the upload and transcription boundary:

```python
class ASRService:
    async def transcribe_upload(
        self,
        *,
        filename: str | None,
        declared_media_type: str | None,
        audio_bytes: bytes,
        language: str | None,
        test_mode: str | None = None,
    ) -> TranscriptionResult:
        ...
```

Responsibilities:

1. Enforce maximum upload size before provider invocation.
2. Reject missing, empty, or too-small files.
3. Check declared MIME type against the allowlist.
4. Probe actual file signature/container and reject MIME/content conflicts.
5. Reserve minimum/maximum duration enforcement for a future reliable decoder/prober; 2B-1 must not infer actual duration from client input or container headers alone.
6. Reserve silence/near-silence rejection for a future reliable decoder/prober; 2B-1 signature checks only prove basic container-header consistency and do not prove decodability or usable speech.
7. Call only the configured `ASRProvider`.
8. Validate that provider output has non-empty transcript text.
9. Map provider and validation failures to stable `AppError` subclasses.
10. Keep temporary data in memory for 2B Fake ASR; if a later real provider needs files, write only to a temporary path and delete in `finally`.
11. Never save raw audio to SQLite, local project data folders, or logs.
12. Never call `ChatService` or create sessions/messages.

### Configuration

Recommended initial settings:

```text
ASR_PROVIDER=fake
ASR_FAKE_MODE=ok
ASR_MAX_UPLOAD_BYTES=10485760
ASR_MAX_DURATION_MS=30000
ASR_MIN_DURATION_MS=300
ASR_ALLOWED_MIME_TYPES=audio/webm;codecs=opus,audio/webm,audio/mp4,audio/wav,audio/x-wav,audio/ogg,audio/ogg;codecs=opus
ASR_ALLOW_TEST_PARAMS=false
```

Rules:

- `ASR_PROVIDER` accepts only `fake` in 2B. Unknown provider names fail startup/config validation and never silently fall back to fake.
- `ASR_FAKE_MODE` may drive deterministic test behavior outside production.
- Optional request-level test parameters are disabled by default and must be accepted only when `APP_ENV == "test"` and `ASR_ALLOW_TEST_PARAMS=true`. They must not be exposed in production mode.

## 3. API draft

### Endpoint

```http
POST /api/audio/transcriptions
Content-Type: multipart/form-data
```

### Request fields

- `file`: required single audio upload.
- `language`: optional language hint such as `zh`.
- `test_mode`: optional only in automated test mode if explicitly enabled; rejected in production/development by default.

`language` is only a hint. Fake ASR can return deterministic `detected_language="zh"` without parsing real speech.

### Success response

```json
{
  "text": "这是 Fake ASR 的确定性转写。",
  "detected_language": "zh",
  "duration_ms": null,
  "provider": "fake",
  "model": "fake-asr-v1",
  "inference_ms": 0,
  "segments": []
}
```

The response is intentionally not wrapped in chat metadata because this is not a chat message. It also does not include a session id or message id.

### Limits

Recommended initial limits:

- Maximum recording duration: **30 seconds** as the current engineering limit, not a measured optimum.
- Minimum accepted duration: **300 ms** as a frontend soft guard or future decoded-duration policy value; Fake ASR/2B-1 must not treat client-declared duration as trusted actual audio duration.
- Maximum upload size: **10 MiB** as the current engineering limit, not a measured optimum.
- One file per request.
- No raw audio persistence.

The 10 MiB cap is a conservative current engineering limit for a 30-second push-to-talk clip across WebM/Opus, MP4, Ogg/Opus, and WAV test fixtures. It is not a benchmark-derived best value. It can be reduced after real browser recording measurements, but it should not be raised without documenting privacy and latency impact.

### Supported MIME types

Initial declared MIME allowlist:

- `audio/webm;codecs=opus`
- `audio/webm`
- `audio/mp4`
- `audio/wav`
- `audio/x-wav`
- `audio/ogg`
- `audio/ogg;codecs=opus`

The backend must normalize MIME parameters where appropriate but still record the actual declared value for validation. It must not trust `Content-Type` alone.

### Signature/container checks

Planned minimum checks:

| Format | MIME examples | Actual content signal |
|---|---|---|
| WebM | `audio/webm`, `audio/webm;codecs=opus` | EBML header bytes `1A 45 DF A3` and WebM/Matroska document markers when available |
| WAV | `audio/wav`, `audio/x-wav` | `RIFF....WAVE` header; for PCM fixtures, parse channels/sample rate/sample width/data length |
| Ogg | `audio/ogg`, `audio/ogg;codecs=opus` | `OggS` capture pattern |
| MP4/M4A | `audio/mp4` | ISO BMFF `ftyp` box near file start |

If declared MIME and signature conflict, return `audio_format_mismatch`. If the signature is unsupported or cannot be probed safely, return `audio_format_unsupported`.

### Empty, short, long, and silent files

- Empty upload: `audio_empty`.
- File below a small byte threshold after multipart parsing: `audio_too_short` or `audio_empty`, depending on exact size.
- Duration below 300 ms: `audio_duration_too_short`, only after a future reliable decoder/prober can determine actual duration.
- Duration above 30 seconds: `audio_duration_too_long`, only after a future reliable decoder/prober can determine actual duration.
- PCM WAV with all-zero or near-zero amplitude: `audio_empty_or_silent`.
- Encoded containers that cannot expose duration/silence through the 2B-1 lightweight signature checks should not be described as duration- or silence-validated. A future real ASR or upload-hardening task may introduce a proper decoder/prober after dependency approval; until then, server-side checks remain limited to size, MIME normalization, and basic container-header consistency.

For 2B Fake ASR, `duration_ms` should be `null`/`None` when the provider cannot reliably decode actual audio duration. The service must not use a client-declared duration or configured limit as if it were measured media duration. Server-side actual duration validation is deferred until a future task introduces reliable decoding/probing support.

### Error code draft

| Code | HTTP status | Meaning |
|---|---:|---|
| `audio_file_missing` | 400 | Multipart request has no `file` field |
| `audio_empty` | 422 | Uploaded file has zero bytes |
| `audio_file_too_large` | 413 | Upload exceeds `ASR_MAX_UPLOAD_BYTES` |
| `audio_duration_too_short` | 422 | Future decoded duration is below minimum; not emitted by 2B-1 without reliable duration probing |
| `audio_duration_too_long` | 413 | Future decoded duration exceeds maximum; not emitted by 2B-1 without reliable duration probing |
| `audio_format_unsupported` | 415 | Declared or probed format is not supported |
| `audio_format_mismatch` | 415 | Declared MIME conflicts with detected signature/container |
| `audio_empty_or_silent` | 422 | Audio has no usable signal |
| `asr_unavailable` | 502 | Provider unavailable or configured unavailable mode |
| `asr_timeout` | 504 | Provider timeout mode/failure |
| `asr_invalid_response` | 502 | Provider returned empty/invalid transcript |
| `asr_test_mode_forbidden` | 403 | Request tried to use test-only fake mode outside test configuration |

All errors should use the existing JSON error envelope pattern:

```json
{
  "error": {
    "code": "asr_invalid_response",
    "message": "语音转写服务返回了空结果，请重新录制或手动输入。"
  }
}
```

### Message persistence rule

`POST /api/audio/transcriptions` must not:

- create a session,
- create a user message,
- create an assistant message,
- call `ChatService`,
- call DeepSeek,
- alter recent-context behavior,
- write raw audio or transcript to SQLite.

Only the existing `POST /api/sessions/{session_id}/messages` endpoint can create chat messages, and only after the user manually submits the input text.

## 4. Frontend recording state machine

### States

Use lower-case state names for the 2B recorder state machine:

```text
idle
requesting_permission
recording
stopping
uploading
transcribing
ready_to_send
error
```

Text input remains available throughout except for the existing duplicate-send disable behavior while a text chat request is in flight.

### State table

| State | Meaning | Available buttons/actions | Forbidden operations | Entry | Exit |
|---|---|---|---|---|---|
| `idle` | No recording/upload active | Start recording, type text, send existing text, clear input | Stop recording | initial state, cancel, successful cleanup | start click -> `requesting_permission` |
| `requesting_permission` | Browser permission prompt or device request is active | Cancel if UI supports it, keep typing | Start another recorder, upload | start click calls `getUserMedia` | success -> `recording`; denied/no device/unsupported -> `error` |
| `recording` | `MediaRecorder` is collecting chunks and tracks are live | Stop, cancel, type text if desired | Start second recorder, upload same chunks, send recording as message | recorder starts | stop -> `stopping`; cancel/unload/session switch -> `idle`; max timer -> `stopping` |
| `stopping` | Recorder is finalizing chunks and tracks are being stopped | Wait, cancel cleanup if safe | Start duplicate recorder, duplicate stop | stop clicked or max timer | valid Blob -> `uploading`; empty Blob -> `error`; cleanup done on cancel -> `idle` |
| `uploading` | Browser is sending multipart data | Abort upload, keep text input available | Start duplicate upload for same recording | Blob prepared | request accepted -> `transcribing`; network/server failure -> `error` |
| `transcribing` | Backend ASR is processing | Abort request if supported, keep text input available | Auto-send transcript, start duplicate upload | upload request in progress | success -> conflict check then `ready_to_send`; ASR error -> `error` |
| `ready_to_send` | Transcript has been inserted into the input or is ready for explicit insertion | Edit, clear, manually send, re-record | Auto-send | transcript success | manual send uses existing text flow; re-record -> `requesting_permission`; clear -> `idle` |
| `error` | Recoverable failure | Dismiss, retry, re-record, type manually | Duplicate failed request | permission/device/upload/ASR/format failure | dismiss -> `idle`; re-record -> `requesting_permission` |

### Required failure behavior

- Permission denied: show a clear microphone permission message, stop all partial tracks, return to a retryable state; text chat remains usable.
- Permission prompt dismissed: treat as recoverable permission failure.
- No microphone: show "未检测到麦克风" or equivalent; text chat remains usable.
- Browser does not support `navigator.mediaDevices.getUserMedia` or `MediaRecorder`: disable recording UI and show safe fallback; text chat remains usable.
- Upload failure: keep any existing typed input; allow retry/re-record/manual typing.
- ASR failure: do not clear typed input, do not create messages, and do not affect 2A playback controls.

### Input insertion and conflict handling

`MessageInput` currently owns its draft locally. 2B should adjust it minimally so the parent or a small input-draft controller can insert a transcript without bypassing the existing submit path.

Rules:

1. Successful transcript fills the existing input box.
2. If the input is empty or whitespace-only, insert the transcript directly.
3. If the input already has unsent user text, do not overwrite it silently.
4. Recommended first behavior: before recording starts, if the input is non-empty, show a lightweight confirmation such as "当前输入框已有内容，录音转写会先作为待插入文本，是否继续？".
5. If the user records anyway and a transcript returns while input content has changed, present explicit choices: append transcript, replace input, discard transcript, or copy manually. The default safe choice is discard/keep current text, not overwrite.
6. Manual send remains the existing form submission.
7. Clearing the input is a user action, not an ASR side effect.

### Session switch, unload, and cancellation

On session switch, session deletion, page unload, or component unmount:

- stop `MediaRecorder` if active,
- stop all `MediaStreamTrack`s,
- clear recording timers,
- abort active upload/transcription fetch through `AbortController`,
- discard unsent Blob chunks,
- preserve only normal typed text if the component still exists,
- do not persist audio or transcript automatically.

2A playback reset already happens on session switching; 2B cleanup should compose with that behavior without coupling recorder code to TTS internals.

## 5. MIME and browser compatibility strategy

### Browser APIs

Use:

```ts
navigator.mediaDevices.getUserMedia({ audio: true })
MediaRecorder
MediaRecorder.isTypeSupported(...)
```

Do not use deprecated `ScriptProcessorNode`.

### Permission timing

The app must call `getUserMedia` only after an explicit user action, such as clicking "开始录音". Page load must not request microphone permission.

### MIME selection order

Recommended candidate order:

```ts
const candidates = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
];
```

Selection rules:

1. If `MediaRecorder.isTypeSupported(candidate)` returns true, use the first supported candidate.
2. If none of the candidates is supported but `MediaRecorder` exists, construct without an explicit `mimeType` and use the browser default.
3. Read `recorder.mimeType` after construction and use that as the actual upload Blob type.
4. If the resulting Blob has an empty type, send `application/octet-stream` only as a last resort; backend should reject unless the signature is accepted and policy permits it.
5. Do not hardcode only `audio/webm`.

Recommended first target remains Edge/Chromium, where WebM/Opus is usually the best fit for short push-to-talk clips. MP4 is included as a compatibility candidate for browsers that support it.

### Recording lifecycle

- Maintain one active recorder ref and one active stream ref.
- Ignore or disable fast duplicate start clicks while state is not `idle` or `error`.
- Configure a max-duration timer of 30 seconds; auto-stop when reached and show that the limit was reached.
- Collect chunks in memory only.
- On stop, build one `Blob` from chunks using `recorder.mimeType` or chunk type.
- Stop all stream tracks in `finally`, regardless of success/failure.
- Do not store Blob in localStorage, IndexedDB, or React state longer than needed to upload.

## 6. Audio validation and privacy

### Frontend data boundary

- Audio exists only as in-memory `Blob` chunks until upload completes or is canceled.
- Do not write audio to localStorage, IndexedDB, Cache Storage, or downloaded files.
- Do not log raw audio Blob content.
- Do not send raw audio to DeepSeek.
- Do not auto-send transcript text to DeepSeek.

### Backend data boundary

- Prefer reading the multipart upload into memory under the configured size cap for 2B Fake ASR.
- Do not write original audio to SQLite.
- Do not write original audio to project data directories.
- Do not write production logs containing raw audio bytes, full transcript text, multipart filenames if they may contain private data, or local temporary paths.
- If future real ASR requires a temporary file, create it in an OS temp directory, pass only that file to the provider, and delete it in `finally`.

### Validation policy

Backend cannot trust client-provided `Content-Type`, filename, or recording duration. The service should validate in this order:

1. Multipart contains exactly one file.
2. File size is greater than zero and below `ASR_MAX_UPLOAD_BYTES`.
3. Declared MIME exists and is allowed, after safe normalization.
4. File signature/container matches declared MIME family.
5. Actual duration checks are skipped in 2B-1 unless a reliable decoder/prober is available; client-declared duration is never trusted as actual media duration.
6. Silence detection passes when the probe can inspect PCM samples; WAV fixture coverage should exist from 2B.
7. Provider returns non-empty transcript.

A strict fail-closed rule is preferable to accepting unknown audio. If this blocks a browser-produced format during implementation, the correct response is to add a measured parser/prober or adjust the supported MIME list, not to trust the client blindly.

### DeepSeek boundary

DeepSeek receives text only after the user manually submits the input through the existing chat endpoint. The ASR endpoint itself must never call LLM APIs.

## 7. Fake ASR design

### Purpose

`FakeASRProvider` verifies the ASR integration path without parsing real speech, accessing the network, writing files, downloading models, or depending on GPU/ASR libraries.

### Behavior

Provider metadata:

```text
provider=fake
model=fake-asr-v1
```

Default success result:

```json
{
  "text": "这是 Fake ASR 的确定性转写。",
  "detected_language": "zh",
  "duration_ms": null,
  "provider": "fake",
  "model": "fake-asr-v1",
  "inference_ms": 0,
  "segments": []
}
```

### Deterministic modes

Supported modes:

| Mode | Provider behavior | Expected service/API mapping |
|---|---|---|
| `ok` | Return fixed non-empty Chinese transcript | 200 success |
| `empty` | Return empty/whitespace text | `asr_invalid_response` |
| `error` | Raise ASR unavailable/provider error | `asr_unavailable` |
| `timeout` | Raise timeout error immediately | `asr_timeout` |

The `timeout` mode must not sleep. It should raise the timeout exception immediately so tests remain fast and deterministic.

### Test-mode control

Preferred control for automated tests:

1. Unit tests instantiate `FakeASRProvider(mode="...")` directly.
2. Route tests override dependencies or set `ASR_FAKE_MODE` in isolated settings.
3. Request-level `test_mode` form field is allowed only if `APP_ENV == "test"` and `ASR_ALLOW_TEST_PARAMS=true`; it is rejected otherwise.

This keeps deterministic failure testing available without exposing production request parameters that alter provider behavior.

### Non-behavior

Fake ASR must not:

- inspect or infer speech content,
- access the network,
- write files,
- call DeepSeek or any LLM,
- create chat messages,
- retain raw audio after return,
- pretend to be a real ASR model.

## 8. Test plan

### Backend tests

Add tests around provider, service, route, config/factory, and persistence boundaries.

Required coverage:

1. Fake ASR normal transcription returns fixed text and `provider=fake`, `model=fake-asr-v1`.
2. Multipart upload success returns the transcription JSON shape.
3. `/api/audio/transcriptions` does not create sessions or messages and does not call `ChatService`.
4. Empty file is rejected.
5. Oversized file is rejected.
6. Unsupported declared MIME is rejected.
7. Declared MIME and file signature conflict is rejected.
8. Empty provider transcript maps to `asr_invalid_response`.
9. Fake `timeout` and `error` modes map to `asr_timeout` and `asr_unavailable` without real waiting.
10. Fake ASR does not access network. Recommended method: provider has no HTTP client dependency, and tests can monkeypatch common network clients if needed.
11. Fake ASR/ASRService does not write raw audio files. Recommended method: use a temp directory sentinel/monkeypatch file creation in service tests and assert no files are created for fake mode.
12. Unknown `ASR_PROVIDER` fails config/factory validation and does not fall back to fake.
13. Test-only request parameter is rejected when not explicitly enabled.
14. WAV silence detection is a future decoder/prober test, not a 2B-1 foundation requirement.
15. Future duration too short/too long behavior maps to stable errors once reliable decoding/probing or a trusted provider-supplied duration exists; 2B-1 tests should not pretend minimal container headers prove actual audio duration.

Suggested backend test files:

```text
backend/tests/test_asr_provider.py
backend/tests/test_asr_service.py
backend/tests/test_api_audio_transcriptions.py
backend/tests/test_asr_factory.py
backend/tests/test_config.py
```

### Frontend unit/component tests

Required coverage:

1. Page load does not request microphone permission.
2. Clicking recording requests permission through `getUserMedia`.
3. Permission denial displays a clear error and keeps text chat usable.
4. Start/stop transitions are correct.
5. Stopping/canceling/unmounting closes all stream tracks.
6. MIME type selection uses `MediaRecorder.isTypeSupported()` and falls back safely.
7. Recorded Blob uploads as multipart with the actual `recorder.mimeType`/Blob type.
8. Upload/transcribing state prevents duplicate requests.
9. Successful transcription enters the existing input box.
10. Transcription does not auto-send.
11. Existing unsent input is not overwritten without explicit confirmation.
12. Cancel, unload, and session switch clean up recorder, tracks, chunks, timers, and abort controllers.
13. ASR failure does not break text chat or 2A Fake TTS playback controls.
14. Missing `MediaRecorder` or `getUserMedia` disables recording UI safely.
15. Max-duration timer auto-stops recording and cleans tracks.

Suggested frontend structure:

```text
frontend/src/hooks/useVoiceRecorderController.ts
frontend/src/hooks/useVoiceRecorderController.test.tsx
frontend/src/components/VoiceRecorderControls.tsx
frontend/src/components/VoiceRecorderControls.test.tsx
frontend/src/api/client.test.ts
frontend/src/App.test.tsx
```

The exact file names may be adjusted to match implementation style, but recorder state should be testable without real microphone access.

### E2E with Fake ASR

Use Playwright with mocked browser microphone/MediaRecorder behavior and fake backend ASR.

Scenario:

1. Open the app with fake LLM, fake TTS, and fake ASR configuration.
2. Confirm no microphone request occurs on page load.
3. Click "开始录音".
4. Mock `getUserMedia` success and `MediaRecorder` chunks.
5. Click "停止录音".
6. Upload deterministic audio fixture/Blob.
7. Receive Fake ASR text.
8. Assert the text appears in the input box.
9. Assert no new user/assistant message appears before manual send.
10. Click existing send button.
11. Assert the user message is created only after manual send.
12. Assert assistant reply appears through existing chat flow.
13. Assert 2A Fake TTS playback controls still work.
14. Assert no browser console errors and no server errors.

No E2E should require a real microphone, real ASR model, real TTS model, or real LLM API.

## 9. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Browser produces a format backend cannot probe | Upload rejected or duration cannot be enforced | Runtime MIME detection, fail-closed backend probing, fixture tests, adjust allowlist only with evidence |
| Input box already has unsent text | Transcript could overwrite user text | Pre-record warning and explicit post-transcript conflict choices |
| Fast repeated clicks | Multiple recorders/uploads, state corruption | State guards, disabled buttons, recorder refs, request IDs, AbortController |
| Permission denied or no microphone | User cannot record | Clear recoverable error and text fallback |
| Track cleanup bug | Microphone remains active | Stop tracks in `finally`, unmount/session-switch tests |
| Fake ASR hides real validation issues | Later real ASR integration surprises | Keep strict ASRService validation and provider contract tests independent of fake content |
| MIME spoofing | Invalid or dangerous content reaches provider | Validate declared MIME plus file signature/container |
| Silent audio hallucination | Bad transcript draft | Silence/empty checks, user review before send, empty transcript invalid-response mapping |
| Raw audio leakage | Privacy breach | In-memory fake path, no logs, no SQLite/localStorage/IndexedDB, temp cleanup for future providers |
| Test-only fake mode exposed | Users can alter behavior unexpectedly | Disable request-level test params outside explicit test config |
| Over-scoping into 2C | Chat/TTS coupling before transcript review | `/transcriptions` must not call `ChatService`; no voice-turn endpoint in 2B |

## 10. Real ASR follow-up benchmark plan

Real ASR must be evaluated only after the Fake ASR 2B loop passes with automated and manual validation.

The first real ASR candidate remains `faster-whisper`, but no dependency, model, or compute configuration is selected in 2B design. `faster-whisper` is based on CTranslate2 and supports GPU/CPU quantization options, but final configuration must be based on measurements on this local Windows machine with RTX 3060 rather than planning assumptions.

Minimum comparison set after 2B:

- `small`
- `medium`
- GPU `compute_type` candidates supported by the installed stack
- CPU fallback/quantized candidate if GPU setup is unstable

Metrics:

1. VRAM usage and peak memory.
2. Model first-load time.
3. Per-clip inference time.
4. Chinese accuracy on non-private test utterances.
5. Mixed Chinese/English recognition quality.
6. Robustness with short clips, quiet speech, and light background noise.
7. Error behavior when CUDA/CTranslate2 dependencies are missing.
8. Interaction with existing Fake/real TTS memory needs.

Benchmark data must not include private audio or private transcripts. Use synthetic utterances already documented in `docs/stage2-voice-architecture.md` or newly recorded non-private fixtures.

Do not declare real ASR "usable", "real-time", or "complete" until local benchmark results support it.

## 11. Recommended first coding task

Recommended first coding task for 2B:

**Backend ASR foundation with Fake provider and tests only.**

Strict scope:

1. Add `ASRProvider`, `TranscriptionResult`, optional `TranscriptionSegment`.
2. Add `FakeASRProvider` with `ok`, `empty`, `error`, and immediate `timeout` modes.
3. Add ASR config/factory with `ASR_PROVIDER=fake` only and no unknown-provider fallback.
4. Add `ASRService` validation skeleton for bytes, MIME allowlist, basic signature checks, and non-empty transcript validation.
5. Add backend unit tests for provider, factory, service validation, and error mapping.
6. Do not add browser recording yet.
7. Do not install real ASR dependencies.
8. Do not modify `ChatService` or persistence semantics.

Why this first:

- It verifies the backend provider boundary before UI complexity.
- It can run fully offline.
- It creates deterministic errors for frontend tests.
- It reduces risk before adding microphone permission and MediaRecorder state.

Second coding task after backend tests pass: add `POST /api/audio/transcriptions` multipart route and API client method, including `python-multipart` dependency if missing.

Third coding task: add frontend recorder controller and transcript-to-input flow.

## 12. Items awaiting user confirmation

The following decisions should be confirmed before implementation begins:

1. **Initial max duration:** recommend 30 seconds.
2. **Initial max upload size:** recommend 10 MiB.
3. **Transcript send behavior:** recommend manual send only in 2B; no auto-send.
4. **Input conflict behavior:** recommend warning before recording if input is non-empty, and never overwrite without explicit confirmation.
5. **Supported browser target:** recommend Edge/Chromium first, with runtime MIME detection and no hardcoded WebM-only assumption.
6. **Test-mode fake control:** recommend dependency/settings control first; request-level `test_mode` only under explicit test config.
7. **Raw audio debugging:** recommend disabled by default; do not save raw audio in 2B.
8. **Real ASR timing:** recommend only after Fake ASR backend route, frontend recorder flow, and E2E pass.
9. **Multipart dependency:** implementation will likely need `python-multipart`; this design task does not install it.
10. **Duration/silence probing strictness:** recommend fail-closed for formats the 2B lightweight probe cannot validate, then expand support with explicit parser/prober work if real browser fixtures require it.

## Dependency planning for 2B Fake ASR vertical slice

Minimum expected dependency change during implementation:

- Add `python-multipart` to backend runtime dependencies if FastAPI multipart uploads are not already supported in the environment.

Do not add during 2B Fake ASR design or first fake-provider backend task:

- `faster-whisper`
- `torch`
- `CTranslate2`
- `ffmpeg`/FFmpeg Python wrappers
- `Silero`
- `sherpa-onnx`
- any model download dependency

Real ASR dependencies are a separate task after the Fake ASR vertical slice passes.

## 13. 2B-1 Backend ASR Foundation implementation addendum — 2026-06-25

Implemented 2B-1 boundary:

- Added an independent ASR module boundary: `backend/app/asr/base.py`, `backend/app/asr/fake_provider.py`, and `backend/app/asr/factory.py`.
- Added `backend/app/services/asr_service.py` as the service boundary for in-memory bytes validation, media type normalization, lightweight container-header signature checks, provider invocation, provider-result validation, and error mapping.
- Added ASR settings for fake provider selection, upload byte cap, future duration policy values, default language, Fake ASR mode/text/detected language.
- Added dependency providers for `ASRProvider` and `ASRService`, but did not register an upload route.
- Added offline backend tests for provider modes, service validation, factory behavior, config validation, no network access, no audio file creation, and no chat persistence side effects.

Duration and media validation decision:

- `TranscriptionResult.duration_ms` is optional and remains `None` for Fake ASR by default.
- 2B-1 does not decode WebM, MP4, or WAV audio to determine actual duration.
- 2B-1 does not trust any client-declared duration as actual audio duration.
- `ASR_MIN_DURATION_MS=300` and `ASR_MAX_DURATION_MS=30000` are retained as policy/config values for future reliable decoding/probing, not as proof that current service code can measure real clip duration.
- Current signature checks only confirm basic container-header consistency: WebM EBML header, MP4 `ftyp` box near the start, and WAV `RIFF`/`WAVE`. They do not prove full media validity, decodability, duration, non-silence, or speech content.

Still not implemented after 2B-1:

- `POST /api/audio/transcriptions`.
- `UploadFile`, `File`, `Form`, or `python-multipart` integration.
- Browser `MediaRecorder` or `getUserMedia` recording.
- Frontend upload/transcript insertion flow.
- Real ASR dependencies or models.
- Actual audio duration decoding or silence detection.
- VAD, streaming, interruption, long-term memory, or emotion state.

## 14. 2B-2 Multipart Transcription API implementation addendum — 2026-06-25

Implemented 2B-2 boundary:

- Added `python-multipart>=0.0.20` to backend runtime dependencies in `pyproject.toml`.
- Added `POST /api/audio/transcriptions` multipart route in `backend/app/api/routes/audio.py`:
  - Accepts `file` (required `UploadFile`) and `language` (optional `Form` string).
  - Checks `UploadFile.size` first when available; reads at most `ASR_MAX_UPLOAD_BYTES + 1` bytes.
  - Rejects oversized uploads early via `ASRFileTooLargeError`.
  - Rejects missing `content_type` via `ASRContentTypeMissingError`.
  - Closes `UploadFile` in all success/failure paths.
  - Delegates to existing `ASRService.transcribe()` for all validation and provider invocation.
  - Returns `TranscriptionResponse` JSON (Pydantic model).
- Added `ASRFileMissingError` and `ASRContentTypeMissingError` to `backend/app/core/errors.py`.
- Added `TranscriptionResponse` Pydantic schema to `backend/app/domain/schemas.py` (no `segments` field).
- Exposed `ASRService.max_upload_bytes` property for route-level size gating.
- Added `backend/tests/test_api_audio_transcriptions.py` with 21 tests covering:
  - WebM/MP4/WAV signature fixture success paths.
  - `duration_ms` is `null` for Fake ASR.
  - `language` form field propagation.
  - Missing file → 422.
  - Empty file → 422 with `asr_file_missing`.
  - Oversized file via `size` field → 413.
  - `max+1` read guard exceeding limit → 413.
  - Unsupported media type → 415.
  - Missing `content_type` → 415.
  - MIME/signature conflict → 422.
  - Invalid language → 422.
  - Timeout/error/empty provider modes mapped to correct HTTP codes.
  - No chat sessions or messages created.
  - `/api/audio/speech` regression passes.
  - No network access (httpx.AsyncClient monkeypatched).
  - No persistent audio files written.

Size and upload boundary:

- Route checks `UploadFile.size` first when present; reads at most `ASR_MAX_UPLOAD_BYTES + 1`.
- max+1 strategy ensures true oversized content is caught regardless of whether the framework reports an accurate `size`.
- `UploadFile` is closed in `try/finally` (and after exceptional reads) to prevent resource leaks.
- Starlette/FastAPI `UploadFile` uses `SpooledTemporaryFile`, which may buffer to disk beyond a threshold. 2B-2 does not override that default; application code does not persist raw audio, but the framework may temporarily spool.
- `filename` is not used for format detection; only `content_type` and byte-level signature checks inform validation.
- The route does not log raw audio, full transcripts, filenames, or temporary paths.

Still not implemented after 2B-2:

- Browser `MediaRecorder` or `getUserMedia` recording.
- Frontend upload/transcript insertion flow.
- Real ASR dependencies or models.
- Actual audio duration decoding or silence detection.
- VAD, streaming, interruption, long-term memory, or emotion state.
