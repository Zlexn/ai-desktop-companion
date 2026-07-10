# Stage 2 Voice Architecture Plan

> Status: planning only. This document does not implement code, install dependencies, download models, or call any ASR/TTS/LLM API.

**Current phase:** Stage 2 — voice features (`PLANNING / NOT STARTED`)

**Goal:** Add a voice layer on top of the completed Stage 1 text-chat system so the user can speak, review recognized text, send it through the existing chat flow, and hear the character reply, while keeping text chat fully usable.

**Architecture:** Keep text as the internal exchange format. Add audio-specific provider abstractions and services around the existing `ChatService`; do not put ASR/TTS logic into `ChatService`, do not change the existing message persistence model, and do not enter Stage 3 memory or Stage 4 emotion systems.

**Tech stack baseline:** Existing Python 3.11+ / FastAPI backend, React + TypeScript + Vite frontend, SQLite message persistence, pytest, Vitest, Playwright E2E, Windows desktop browser environment. Stage 2 candidates are recorded as ADRs only and are not installed by this document.

---

## 1. Existing engineering review

### 1.1 Current backend architecture

Current backend structure is a small FastAPI application with explicit layers:

- `backend/app/main.py`
  - Creates the FastAPI app.
  - Installs CORS middleware for the Vite dev server.
  - Includes route modules for health, sessions, and chat.
  - Converts `AppError` into a stable JSON error envelope.
- `backend/app/api/routes/sessions.py`
  - Provides `POST /api/sessions`, `GET /api/sessions`, `GET /api/sessions/{session_id}`, and `DELETE /api/sessions/{session_id}`.
- `backend/app/api/routes/chat.py`
  - Provides `GET /api/sessions/{session_id}/messages` and `POST /api/sessions/{session_id}/messages`.
  - The public chat response is `{"reply": str, "metadata": {"provider": str, "model": str}}`.
- `backend/app/api/dependencies.py`
  - Wires settings, SQLite connection, repositories, prompt renderer, LLM provider, context builder, and `ChatService`.
- `backend/app/services/chat_service.py`
  - Owns text-message validation, user-message persistence, system prompt rendering, recent context assembly, LLM invocation, assistant-message persistence, and safe invalid-response handling.
- `backend/app/services/context_builder.py`
  - Builds recent context from persisted messages.
- `backend/app/services/prompt_renderer.py`
  - Loads character configuration and system prompt templates outside API routes and UI components.
- `backend/app/providers/base.py`
  - Defines `LLMProvider`, `LLMMessage`, `LLMOptions`, and `LLMResponse`.
- `backend/app/providers/factory.py`
  - Selects `fake`, `anthropic`, or `deepseek` providers from settings.
- `backend/app/providers/deepseek_provider.py`
  - Implements the real DeepSeek text-chat provider via `httpx.AsyncClient`.
- `backend/app/repositories/*.py`
  - Encapsulates SQLite session/message persistence.
- `backend/app/core/config.py`
  - Reads local environment configuration, validates provider settings, and redacts secrets.
- `backend/app/core/errors.py`
  - Defines app/provider errors that map to user-facing messages.

The backend currently has no audio routes, no ASR/TTS provider boundary, no audio file handling, no media validation, and no voice turn orchestration.

### 1.2 Current frontend architecture

Current frontend structure is a simple React state tree:

- `frontend/src/App.tsx`
  - Owns session list, active session, messages, loading state, and error state.
  - Calls `apiClient` for session and message operations.
  - Refreshes messages after sending text.
- `frontend/src/api/client.ts`
  - Uses relative `/api/...` URLs.
  - Converts JSON error envelopes into `Error` messages.
  - Currently assumes JSON request/response bodies.
- `frontend/src/api/types.ts`
  - Defines `Session`, `Message`, `ChatResponse`, and error envelope types.
- `frontend/src/components/ChatLayout.tsx`
  - Arranges session list, chat header, error banner, message list, and text input.
- `frontend/src/components/MessageInput.tsx`
  - Owns the text input draft locally.
  - Sends only after explicit submit.
- `frontend/src/components/MessageList.tsx`
  - Displays persisted text messages.
- `frontend/src/components/ErrorBanner.tsx`
  - Displays user-facing errors.
- `frontend/src/components/SessionList.tsx`
  - Creates, selects, and deletes sessions.

The frontend currently has no microphone permission flow, no recorder state, no playback state, no audio element management, no audio upload client, and no voice-specific state machine.

### 1.3 Current dependencies and tests

Backend dependency baseline from `backend/pyproject.toml`:

- Runtime: `anthropic`, `fastapi`, `httpx`, `pydantic`, `pydantic-settings`, `pyyaml`, `uvicorn[standard]`.
- Dev: `pytest`, `pytest-asyncio`.
- Python requirement: `>=3.11`.
- Current recorded local Python: 3.12.6.

Frontend dependency baseline from `frontend/package.json`:

- Runtime: `@vitejs/plugin-react`, `react`, `react-dom`, `typescript`, `vite`.
- Dev: `@playwright/test`, Testing Library, `jsdom`, `vitest`.
- Current recorded local Node/npm: Node.js v22.22.3, npm 10.9.8.
- Browser E2E uses Playwright with Microsoft Edge channel.

Current test architecture:

- Backend pytest covers API routes, services, context, repositories, provider config/factory, DeepSeek provider behavior, restart persistence, and Stage 1 character evaluation script safety.
- Frontend Vitest covers API client and app/component behavior.
- Playwright E2E starts a fake-provider backend and Vite frontend, then drives browser chat through `/api` without real model calls.

### 1.4 Stage 1 components reusable in Stage 2

Reusable components:

- `ChatService` for the text conversation turn after ASR returns text.
- `ContextBuilder` and existing recent-context semantics.
- `LLMProvider` factory pattern as the model for new `ASRProvider` and `TTSProvider` abstractions.
- `Settings.redacted()` pattern for future audio configuration redaction.
- `AppError` and provider error mapping pattern for ASR/TTS failures.
- Existing `MessageRepository` and `SessionRepository` for text message persistence.
- Existing `/api/sessions/{session_id}/messages` endpoint for Stage 2B confirmed text sends.
- Existing frontend `apiClient` error handling pattern.
- Existing `ErrorBanner`, loading indicators, and text input as the fallback path.
- Existing fake-provider testing style for no-real-provider automated tests.
- Existing Playwright E2E webServer setup with fake provider and isolated SQLite DB.

### 1.5 New abstractions needed for Stage 2

Backend abstractions to add in future implementation milestones:

- `ASRProvider` and typed ASR request/result objects.
- `TTSProvider` and typed TTS request/result objects.
- `AudioService` for audio validation, temporary-file lifecycle, ASR/TTS calls, error conversion, and cancellation handling.
- `VoiceTurnService` for Stage 2C only: composing ASR, existing `ChatService`, and TTS.
- Audio-specific configuration for file size, duration, MIME allowlist, timeouts, feature enable flags, and provider selection.
- Audio route module, likely `backend/app/api/routes/audio.py`, for transcription and speech synthesis.
- Voice-turn route module or endpoint for Stage 2C, likely extending session routes with `/voice-turns`.
- Test fakes for ASR/TTS providers.
- Benchmark script design for local latency and resource measurement.

Frontend abstractions to add in future implementation milestones:

- Voice state machine separate from text input state.
- Recorder controller around `navigator.mediaDevices.getUserMedia` and `MediaRecorder`.
- Audio playback controller around `HTMLAudioElement` or Web Audio APIs that are not deprecated.
- API client methods for multipart upload and binary audio responses.
- Voice controls component for record/stop/cancel/re-record/play/stop/replay.
- Transcription review flow that places ASR text into editable input before sending.
- Device/permission diagnostics and user-visible status.

### 1.6 Interfaces that must not be broken

Do not break these existing contracts:

- `POST /api/sessions` request/response shape.
- `GET /api/sessions` and `GET /api/sessions/{session_id}` response shape.
- `DELETE /api/sessions/{session_id}` status behavior.
- `GET /api/sessions/{session_id}/messages` response shape and message ordering.
- `POST /api/sessions/{session_id}/messages` request shape: `{ "content": string }`.
- `POST /api/sessions/{session_id}/messages` response shape: `{ "reply": string, "metadata": { "provider": string, "model": string } }`.
- Existing SQLite session/message schema for Stage 1 text history.
- Existing `ChatService.send_message(session_id, user_text)` semantics.
- Existing character prompt and recent-context semantics.
- Existing `LLMProvider` interface and provider factory behavior.
- Existing frontend text input and message list behavior.
- Existing automated tests must remain able to run without real API calls.

### 1.7 Environment constraints

- OS: Windows 11 Home China.
- Shell: PowerShell primary.
- Backend target: Python 3.11+, current local Python 3.12.6.
- Frontend target: Node.js 20+, current local Node.js v22.22.3 and npm 10.9.8.
- Browser APIs: Chromium/Edge-compatible `getUserMedia`, `MediaRecorder`, `HTMLAudioElement`, and possibly `AudioContext`; do not plan around deprecated `ScriptProcessorNode`.
- E2E browser: Microsoft Edge via Playwright.
- GPU: NVIDIA RTX 3060 exists, but VRAM capacity must be detected by implementation-time code before making placement decisions.
- DeepSeek remains API-backed and does not consume local GPU.
- ASR/TTS may have CUDA/cuDNN and model binary constraints on Windows; these must be measured before declaring real-time performance.

---

## 2. Stage 2 product boundary

### 2.1 Stage 2 final target

The user can use a microphone to speak. The system converts speech to text, passes the confirmed text through the existing text-chat flow, converts the assistant reply to speech, and plays it back.

Text remains the internal standard exchange format:

```text
microphone audio -> ASR transcript -> existing text chat -> assistant text -> TTS audio -> playback
```

### 2.2 In scope for Stage 2

- Microphone permission management.
- Explicit audio recording.
- ASR.
- TTS.
- Audio playback.
- Voice turn state management.
- Cancel playback.
- VAD.
- User speech interrupting TTS.
- Latency, error, and device status display.

### 2.3 Out of scope for Stage 2

- Long-term memory.
- Relationship state.
- Emotion state machine.
- Emotion recognition.
- TTS emotion parameters.
- Live2D expression binding.
- Wake word.
- Long-running background listening.
- Multi-speaker diarization.
- Voice actor voice replication.
- Model training or fine-tuning.
- Voice cloning training.
- Unauthorized character voices or voice actor voices.

---

## 3. Recommended architecture

### 3.1 High-level flow

Milestone 2A adds output only:

```text
existing assistant text -> POST /api/audio/speech -> TTSProvider -> audio response -> frontend playback
```

Milestone 2B adds input only, with user review:

```text
button down/up -> MediaRecorder blob -> POST /api/audio/transcriptions -> ASRProvider -> transcript -> editable text input
```

Milestone 2C composes the full half-duplex voice turn:

```text
recording -> ASR -> user confirmation or explicit auto-send -> ChatService -> TTS -> playback
```

Milestone 2D adds VAD after explicit user start.

Milestone 2E adds speech interruption during TTS.

Milestone 2F evaluates streaming and performance optimizations.

### 3.2 Backend boundaries

Backend should add audio features beside the existing text chat stack:

```text
api/routes/audio.py
  -> AudioService
      -> ASRProvider
      -> TTSProvider

api/routes/voice_turns.py or sessions.py extension, Stage 2C only
  -> VoiceTurnService
      -> AudioService.transcribe
      -> ChatService.send_message
      -> AudioService.synthesize
```

Rules:

- `ChatService` remains text-only.
- `AudioService` must not render character prompts or call LLM providers.
- `VoiceTurnService` is the only future composition layer that may call both `AudioService` and `ChatService`.
- `POST /api/audio/transcriptions` must not create chat messages.
- `POST /api/audio/speech` must not write to the chat database.
- Stage 2C voice turns must persist only the ASR text as the user message and existing assistant text as the assistant message.
- Raw audio is temporary by default and deleted after processing.

### 3.3 Frontend boundaries

Frontend should add voice UI without removing the text input:

```text
App.tsx
  - existing session/message state
  - future voice controller hook state

api/client.ts
  - existing JSON chat methods
  - future multipart transcription method
  - future speech synthesis binary/resource method

components/VoiceControls.tsx
  - record/stop/cancel/re-record/play/stop/replay controls

components/MessageInput.tsx
  - remains editable fallback and receives transcript text in 2B
```

Rules:

- Text input remains usable whenever no request requires it to be disabled.
- ASR text goes into editable input first in 2B.
- No automatic send in 2B.
- No forced automatic playback in 2A.
- UI must prevent repeated rapid clicks from creating duplicate requests.

---

## 4. ADRs and alternative comparison

### ADR-2A: ASR first candidate is faster-whisper

**Status:** Proposed for benchmark, not installed.

**Recommendation:** Start ASR evaluation with `faster-whisper` using `small` as the initial model candidate and `medium` as the comparison candidate.

**Initial inference target:** local GPU.

**Compute type:** not decided in planning. `compute_type` must be chosen only after benchmark data on this Windows + RTX 3060 environment.

**Reasons:**

- Strong local ASR baseline.
- Suitable for non-streaming push-to-talk transcription in 2B/2C.
- Model size can be scaled from `small` to `medium` after latency/quality measurement.

**Risks:**

- CUDA/cuDNN packaging conflicts on Windows.
- VRAM pressure when combined with high-quality TTS.
- First-run model loading latency.

### ADR-2B: ASR backup candidate is sherpa-onnx

**Status:** Backup candidate for later evaluation, not installed.

**Recommendation:** Evaluate `sherpa-onnx` only if the project needs more native streaming recognition or a unified runtime for ASR/VAD.

**Reasons:**

- More suitable for streaming-style pipelines.
- May simplify runtime if VAD/streaming becomes central.

**Risks:**

- Different model ecosystem and quality/latency trade-offs.
- More integration work if the first target is simple push-to-talk.

### ADR-2C: VAD candidate is Silero VAD

**Status:** Proposed for Milestone 2D only, not installed.

**Recommendation:** Use Silero VAD as the first VAD candidate, CPU-first.

**Reasons:**

- VAD should not compete with ASR/TTS for GPU memory.
- VAD is not needed for Milestone 2B or 2C.
- Explicit push-to-talk must ship before VAD automation.

**Risks:**

- False starts/stops in noisy rooms.
- TTS playback echo can trigger detection without echo control.

### ADR-2D: TTS must be behind TTSProvider

**Status:** Required abstraction.

**Recommendation:** The first TTS implementation must use a `TTSProvider` interface. Choose a local lightweight Chinese-capable TTS engine with clear license and simple installation for the first implementation. Do not bind any concrete model into core business code.

**Reasons:**

- Stage 2 needs stable integration before high-quality voices.
- Provider isolation keeps future replacements possible.
- Licensing and voice authorization are first-class constraints.

**Risks:**

- Lightweight TTS quality may be less natural.
- Audio format compatibility may vary by engine.

### ADR-2E: CosyVoice is a high-quality TTS candidate, not first dependency

**Status:** Candidate for second TTS provider evaluation, not installed.

**Recommendation:** Evaluate CosyVoice after the basic TTSProvider path works. Test VRAM use, first-audio latency, stability, and licensing separately. Only use user-owned or explicitly authorized reference voices.

**Reasons:**

- Better voice quality may be possible.
- Higher integration and resource risk makes it inappropriate as the very first closed loop.

**Risks:**

- GPU memory pressure.
- Slow cold start and first-token/first-audio latency.
- Voice asset licensing and consent risks.

### ADR-2F: First recorder UX is explicit push-to-talk / press buttons

**Status:** Recommended.

**Recommendation:** First version uses explicit start/stop buttons. No continuous listening, no wake word, no background recording.

**Reasons:**

- Clear privacy boundary.
- Easier testing and error handling.
- Avoids accidental recording.
- Matches user requirement for Stage 2B.

---

## 5. Backend provider interface drafts

These are type signature drafts only. They are not implemented by this planning document.

### 5.1 ASRProvider draft

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ASRSegment:
    start_ms: int
    end_ms: int
    text: str
    confidence: float | None = None


@dataclass(frozen=True)
class ASRRequest:
    audio_path: Path | None = None
    audio_bytes: bytes | None = None
    mime_type: str = "application/octet-stream"
    language_hint: str | None = "zh"


@dataclass(frozen=True)
class ASRResult:
    transcript: str
    detected_language: str | None
    duration_ms: int
    provider: str
    model: str
    inference_ms: int
    segments: list[ASRSegment] = field(default_factory=list)


class ASRProvider(Protocol):
    async def transcribe(self, request: ASRRequest) -> ASRResult:
        ...
```

Validation rules for implementations:

- Exactly one of `audio_path` or `audio_bytes` should be supplied by `AudioService`.
- `transcript` must be stripped and non-empty for success.
- Provider metadata must not include raw audio, full private transcript logs, API keys, or filesystem paths outside safe diagnostics.

### 5.2 TTSProvider draft

```python
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TTSRequest:
    text: str
    voice_id: str
    speed: float = 1.0
    language: str | None = "zh"


@dataclass(frozen=True)
class TTSResult:
    audio_bytes: bytes
    mime_type: str
    sample_rate: int
    duration_ms: int
    provider: str
    model: str
    inference_ms: int


class TTSProvider(Protocol):
    async def synthesize(self, request: TTSRequest) -> TTSResult:
        ...
```

Validation rules for implementations:

- `text` must be non-empty after trimming.
- `voice_id` must refer to an installed and authorized voice asset.
- `speed` must be bounded, for example `0.5 <= speed <= 2.0` unless a provider has stricter limits.
- `audio_bytes` must be non-empty.
- `mime_type` must be one of the server-supported response formats.

### 5.3 AudioService draft

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AudioValidationPolicy:
    max_upload_bytes: int
    max_duration_ms: int
    allowed_mime_types: set[str]
    min_duration_ms: int


class AudioService:
    async def transcribe_upload(
        self,
        *,
        filename: str,
        declared_mime_type: str,
        content: bytes,
        language_hint: str | None,
        request_cancelled: bool = False,
    ) -> ASRResult:
        ...

    async def synthesize_text(
        self,
        *,
        text: str,
        voice_id: str,
        speed: float,
        language: str | None,
        request_cancelled: bool = False,
    ) -> TTSResult:
        ...

    def validate_audio_upload(
        self,
        *,
        filename: str,
        declared_mime_type: str,
        content_length: int,
    ) -> None:
        ...

    async def write_temp_audio(self, content: bytes, suffix: str) -> Path:
        ...

    def cleanup_temp_audio(self, path: Path) -> None:
        ...
```

Responsibilities:

- Validate upload size and allowed MIME type.
- Inspect actual audio format instead of trusting frontend declarations.
- Enforce duration limits after decoding/probing.
- Normalize or convert to provider-required format when necessary.
- Manage temporary files with `try/finally` cleanup.
- Convert ASR/TTS provider failures into `AppError` subclasses.
- Respect cancellation signals where supported.
- Avoid logging raw audio and full private transcripts.

### 5.4 VoiceTurnService draft for Milestone 2C

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceTurnResult:
    transcript: str
    reply: str
    chat_provider: str
    chat_model: str
    tts_provider: str
    tts_model: str
    audio_mime_type: str
    audio_duration_ms: int


class VoiceTurnService:
    async def run_voice_turn(
        self,
        *,
        session_id: str,
        audio_content: bytes,
        declared_mime_type: str,
        language_hint: str | None,
        voice_id: str,
        speed: float,
        auto_send: bool,
    ) -> VoiceTurnResult:
        ...
```

Rules:

- Do not implement this before Milestone 2C.
- Do not put ASR/TTS logic into `ChatService`.
- Use `ChatService.send_message(session_id, transcript)` to preserve Stage 1 message semantics.
- If TTS fails after text reply is generated, the user/assistant text messages must remain available.
- Do not introduce long-term memory or emotion state.

---

## 6. API drafts

### 6.1 `POST /api/audio/transcriptions`

Milestone: 2B.

Purpose: upload one explicit recording and receive a transcript. This endpoint must not create chat sessions or messages.

Request:

```http
POST /api/audio/transcriptions
Content-Type: multipart/form-data
```

Fields:

- `file`: required, single audio file.
- `language_hint`: optional string, initial value usually `zh`.

Recommended initial limits:

- Maximum recording duration: 30 seconds.
- Minimum accepted duration: 300 ms after decoding/probing.
- Maximum upload size: 10 MiB initial cap, to be revised after browser format benchmarks.
- Allowed declared MIME types:
  - `audio/webm`
  - `audio/webm;codecs=opus`
  - `audio/ogg`
  - `audio/ogg;codecs=opus`
  - `audio/wav`
  - `audio/x-wav`
  - `audio/mp4` only if target browsers produce it and backend probing confirms support.

Backend must not trust the declared MIME type. It must probe the actual content before invoking ASR.

Success response:

```json
{
  "transcript": "转写文本",
  "detected_language": "zh",
  "duration_ms": 3200,
  "metadata": {
    "provider": "faster-whisper",
    "model": "small",
    "inference_ms": 850
  },
  "segments": [
    {"start_ms": 0, "end_ms": 1200, "text": "你好"}
  ]
}
```

Initial implementation may omit `segments` only if the response schema defines it as an empty list by default.

Error codes:

- `audio_file_missing` — no file part.
- `audio_file_too_large` — upload exceeds configured size.
- `audio_duration_too_long` — decoded/probed duration exceeds limit.
- `audio_duration_too_short` — decoded/probed duration is too short.
- `audio_format_unsupported` — MIME/content format cannot be accepted.
- `audio_empty_or_silent` — decoded audio has no usable signal.
- `asr_unavailable` — provider/model unavailable.
- `asr_timeout` — transcription timed out.
- `asr_invalid_response` — provider returned empty or unusable transcript.
- `audio_tempfile_error` — temporary file could not be safely created/deleted.

Timeout target:

- Initial server-side ASR timeout: 30 seconds for local transcription.
- Frontend request timeout/display should show a clear “转写仍在进行/失败” state before the user retries.

Temporary file deletion:

- Write upload to a temp location only if provider needs a file path.
- Delete temp file in `finally` after transcription or failure.
- Do not persist raw audio by default.

### 6.2 `POST /api/audio/speech`

Milestone: 2A.

Purpose: synthesize audio for text. This endpoint must not write chat messages.

Request:

```json
{
  "text": "要朗读的文字",
  "voice_id": "default-zh-local",
  "speed": 1.0,
  "language": "zh"
}
```

Recommended limits:

- Maximum text length for a single request: 1,000 Chinese characters in 2A.
- Minimum text length: 1 non-whitespace character.
- `voice_id` must be selected from configured local authorized voices.
- `speed`: initial allowed range `0.5` to `2.0`.
- Timeout: initial server-side TTS timeout 30 seconds.

Response strategy recommendation:

- Milestone 2A should prefer a binary audio response for simplicity:

```http
HTTP/1.1 200 OK
Content-Type: audio/wav
X-Audio-Duration-Ms: 2400
X-TTS-Provider: local-tts-provider
X-TTS-Model: model-name
```

- A temporary audio URL/resource ID can be introduced later only if binary responses become awkward for replay, queueing, or streaming.
- If temporary URLs are introduced, they must expire quickly and must not expose arbitrary filesystem paths.

Error codes:

- `tts_text_empty` — empty text.
- `tts_text_too_long` — text exceeds configured limit.
- `tts_voice_not_found` — unknown voice ID.
- `tts_voice_not_authorized` — voice exists but is not approved for use.
- `tts_unavailable` — provider/model unavailable.
- `tts_timeout` — synthesis timed out.
- `tts_invalid_response` — provider returned empty or invalid audio.
- `audio_playback_format_unsupported` — generated MIME type is not usable by the frontend target browser.

### 6.3 `POST /api/sessions/{session_id}/voice-turns`

Milestone: 2C only.

Purpose: run a full half-duplex voice turn.

This endpoint must not be implemented in 2A or 2B.

Request shape options to decide before 2C:

- Option A: multipart upload returns JSON with transcript, assistant reply, and either binary audio metadata/resource ID.
- Option B: two-step client orchestration using `/transcriptions`, existing `/messages`, and `/speech`, with no combined endpoint.

Recommendation for 2C:

- Prefer client-orchestrated two/three-step flow first unless one-call transactional voice turns are required.
- Add `/voice-turns` only if the UI needs a single backend orchestration point for consistent cancellation and latency metrics.

Rules if implemented:

- ASR transcript becomes the user message.
- Assistant text reply is persisted by existing `ChatService`.
- TTS output is not persisted as a chat message.
- TTS failure must not roll back the text messages.
- Text mode remains usable.

---

## 7. Frontend voice state machine

### 7.1 States

```text
IDLE
RECORDING
UPLOADING
TRANSCRIBING
READY_TO_SEND
THINKING
SYNTHESIZING
PLAYING
CANCELLING
ERROR
```

### 7.2 State table

| State | Meaning | Allowed user operations | Disallowed operations | Exit conditions |
|---|---|---|---|---|
| `IDLE` | No voice operation active | Start recording, type/send text, replay last available audio if present | Stop recording | User starts recording -> `RECORDING`; user sends text -> existing text flow |
| `RECORDING` | Microphone stream active and MediaRecorder collecting chunks | Stop recording, cancel recording | Start another recording, send same audio twice, start playback | Stop -> `UPLOADING`; cancel -> `CANCELLING` then `IDLE`; max duration -> auto stop |
| `UPLOADING` | Recorded blob is being uploaded | Cancel request if supported | Start recording, send text generated by this upload | Upload accepted -> `TRANSCRIBING`; failure -> `ERROR` |
| `TRANSCRIBING` | Backend ASR is running | Cancel request if supported | Start another recording, send unconfirmed transcript | ASR success -> `READY_TO_SEND`; ASR failure -> `ERROR` |
| `READY_TO_SEND` | Transcript is in editable input | Edit text, send text, re-record, cancel transcript | Auto-send unless user enabled it | Send -> `THINKING`; re-record -> `RECORDING`; cancel -> `IDLE` |
| `THINKING` | Existing chat request is running | Cancel UI flow if safe, keep text fallback disabled only for duplicate send | Start recording/playback for same turn | Chat success -> `SYNTHESIZING` if TTS requested, otherwise `IDLE`; chat failure -> `ERROR` |
| `SYNTHESIZING` | TTS request is running for assistant reply | Cancel TTS | Start recording in half-duplex 2C | TTS success -> `PLAYING` or `IDLE` if autoplay disabled; TTS failure -> `ERROR` with text reply preserved |
| `PLAYING` | Audio element is playing | Stop, pause if supported, replay after ended | Start recording until 2E interruption exists | End -> `IDLE`; stop -> `CANCELLING` then `IDLE`; 2E speech detected -> interrupt path |
| `CANCELLING` | Cleanup is in progress | No-op or wait | Duplicate cancellation clicks | Cleanup complete -> previous safe state, usually `IDLE` |
| `ERROR` | Recoverable error shown | Dismiss error, retry relevant step, use text input | Duplicate failed request | Dismiss -> `IDLE` or `READY_TO_SEND` if transcript exists |

### 7.3 State transition rules

- Fast repeated clicks must be ignored while a transition is in progress.
- Use request IDs or `AbortController` to prevent stale responses from overwriting newer state.
- Only one active recorder or audio player may exist at a time.
- Text input remains available as a fallback except when a specific send request is already in flight.
- Stage 2C is half-duplex: recording and playback cannot be active simultaneously.
- Stage 2E is the only milestone that may stop playback because new speech begins.

### 7.4 Cancellation behavior

- Recording cancel: stop all media tracks, discard chunks, clear timers, return to `IDLE`.
- Upload/ASR cancel: abort fetch if possible; backend should still delete temporary files.
- TTS cancel: abort fetch if possible; discard any returned audio if the request completes later.
- Playback stop: pause audio, reset current time, release object URL, clear queued audio.
- Voice-turn cancel in 2C: do not delete already persisted text messages; only stop pending audio work.

### 7.5 Page refresh behavior

- Active microphone stream must stop because browser page lifecycle ends.
- In-progress recording/upload/transcription/TTS/playback is lost.
- Existing text chat messages reload from SQLite.
- Raw audio is not restored.
- Last generated audio should not be assumed available unless a future temporary audio resource mechanism explicitly supports it.

### 7.6 Permission and device failures

- Permission denied: show a clear message that microphone permission is required for voice input; remain in `IDLE`; text input remains usable.
- Permission prompt dismissed: treat as a recoverable permission error; allow retry.
- No microphone device: show “未检测到麦克风”; text input remains usable.
- Device removed during recording: stop recorder, clean up tracks, show device error.
- Unsupported `MediaRecorder` or no supported MIME type: disable voice recording UI and keep text input.

### 7.7 Playback and provider failures

- Audio playback failure: show clear playback error; preserve text reply; allow retry TTS or continue text mode.
- ASR unavailable: show transcription service unavailable; allow re-record or text entry.
- TTS unavailable: show speech synthesis unavailable; preserve text reply and text chat flow.
- TTS synthesis failure must not mark chat send as failed if text reply was already produced.

---

## 8. Audio input planning

### 8.1 First input mode

First version uses explicit button-controlled recording:

- User clicks “开始录音”.
- Browser requests microphone permission if not already granted.
- User clicks “结束录音”.
- Browser uploads the recorded blob to backend ASR.
- ASR text is placed into the editable input.
- User edits and sends manually in 2B.

No continuous listening, no wake word, no background recording.

### 8.2 Browser APIs

Recommended browser APIs:

- `navigator.mediaDevices.getUserMedia({ audio: true })`
- `MediaRecorder` for encoded chunks.
- `AudioContext` only for supported non-deprecated analysis/conversion needs.
- Do not use deprecated `ScriptProcessorNode`.

Frontend MIME strategy:

- Check `MediaRecorder.isTypeSupported()` at runtime.
- Prefer `audio/webm;codecs=opus` when supported by Edge/Chromium.
- Fall back to browser default MIME type if necessary.
- Send the actual `Blob.type`, but backend must probe content independently.

### 8.3 Backend audio validation

Initial policy:

- Maximum duration: 30 seconds.
- Maximum upload size: 10 MiB.
- Reject empty file.
- Reject decoded duration below 300 ms.
- Reject pure silence or near-silence after probing/decoding.
- Convert unsupported but decodable input to provider-required format only inside `AudioService`.

Single-channel and sample-rate strategy:

- Providers should receive mono audio unless a chosen ASR model explicitly benefits from stereo.
- Convert to 16 kHz mono PCM WAV for ASR if the provider requires it.
- Preserve original upload only as a temporary file and delete after processing.
- Do not trust frontend-provided MIME type, filename extension, or duration.

---

## 9. GPU, process, and resource strategy

User hardware includes NVIDIA RTX 3060. VRAM capacity must be detected by implementation-time code before choosing models or residency strategy.

Resource policy:

1. DeepSeek continues to use API and does not occupy local GPU.
2. ASR and TTS must use independent provider abstractions.
3. Do not assume ASR and high-quality TTS can both remain resident in VRAM.
4. Record measured VRAM for every candidate model.
5. Support lazy loading providers/models.
6. Support process isolation for heavy ASR/TTS runtimes if in-process loading destabilizes FastAPI.
7. Support either single-model residency or explicit model unload strategy after benchmark data.
8. VAD defaults to CPU.
9. Backend and frontend main request/UI paths must not block on model loading without progress/error state.
10. CUDA OOM must become a controlled user-facing error, not a full application crash.

Recommended process options to benchmark later:

- In-process provider loading for simplest 2A/2B prototypes with fake/local lightweight providers.
- Worker process per heavy model family if CUDA dependencies or cold starts make FastAPI unstable.
- Lazy-load on first request with visible “模型加载中” status and timeout guard.
- Explicit unload after idle period if ASR/TTS cannot coexist in VRAM.

---

## 10. Security and privacy

Stage 2 privacy requirements:

- Default ASR/TTS should be local.
- UI must clearly show when recording is active.
- No background recording.
- No wake word in Stage 2.
- Raw audio is not saved by default.
- Temporary audio is deleted immediately after processing.
- Audio is not sent to DeepSeek.
- DeepSeek receives ASR text only after user confirmation or explicit auto-send setting in 2C.
- Logs must not include raw audio, full private transcripts, Authorization headers, API keys, full prompts, or private audio file paths.
- User can disable voice features.
- Voice assets must be user-owned or explicitly authorized.
- No voice cloning training is allowed in Stage 2.
- Do not use unauthorized character, celebrity, or voice actor voices.

Recommended logging policy:

- Log safe event categories, durations, provider names, model names, file sizes, and error codes.
- Do not log full transcript text by default.
- If debugging transcript quality becomes necessary, require an explicit local debug flag and redaction policy before collecting samples.

---

## 11. Testing and benchmark plan

### 11.1 Automated tests by layer

Backend tests to add in implementation milestones:

- `test_audio_service.py`
  - Validates file size, MIME, duration, empty/silent file behavior, temp cleanup, provider error mapping.
- `test_asr_provider_fake.py`
  - Uses fixed fake ASR provider; no real ASR model.
- `test_tts_provider_fake.py`
  - Uses fixed fake TTS provider returning small fixture bytes; no real TTS model.
- `test_audio_routes.py`
  - Tests `/api/audio/transcriptions` and `/api/audio/speech` with fixtures and fakes.
- `test_voice_turn_service.py` in 2C only
  - Verifies ASR text becomes user message, assistant text persists through existing `ChatService`, and TTS failure does not lose text messages.

Frontend tests to add in implementation milestones:

- API client tests for multipart upload and binary audio response handling.
- Voice state reducer tests for every state transition.
- Component tests for permission denied, no microphone, ASR failure, TTS failure, and duplicate-click prevention.
- Playwright E2E with fake ASR/TTS providers and fixed audio fixture; no real microphone required for CI.

### 11.2 Benchmark script design

Create benchmark scripts only during implementation planning for a specific milestone. They must use non-private test audio.

Metrics to collect:

- Recording duration.
- Upload duration.
- ASR inference duration.
- LLM call duration.
- TTS inference duration.
- TTS first-audio time.
- End-to-end total duration.
- GPU peak VRAM.
- CPU peak utilization.
- Process memory peak.
- Error rate.

Suggested benchmark output schema:

```json
{
  "schema_version": 1,
  "started_at": "ISO-8601",
  "hardware": {
    "gpu_name": "detected GPU",
    "gpu_vram_mb": 0,
    "cpu": "detected CPU",
    "os": "Windows"
  },
  "cases": [
    {
      "id": "zh-daily-01",
      "audio_duration_ms": 3000,
      "upload_ms": 20,
      "asr_inference_ms": 800,
      "llm_ms": 1500,
      "tts_inference_ms": 900,
      "tts_first_audio_ms": 700,
      "end_to_end_ms": 4200,
      "gpu_peak_vram_mb": 0,
      "cpu_peak_percent": 0,
      "memory_peak_mb": 0,
      "error": null
    }
  ]
}
```

Do not include private transcripts or raw audio in benchmark outputs.

### 11.3 Non-private Chinese benchmark utterances

Use synthetic, non-private sentences:

1. 普通话日常句：`今天晚上我想先休息十分钟，然后再继续整理桌面。`
2. 数字：`测试数字一二三四五，订单编号是九零七二。`
3. 英文字母：`请记录字母 A B C D，以及代码 X Z Q。`
4. 中英文混合：`我今天在 VS Code 里运行了 npm test 和 pytest。`
5. 专有名词：`请识别 DeepSeek、FastAPI、SQLite 和 Playwright。`
6. 安静环境：同一句普通话在安静房间录制。
7. 轻度背景噪声：同一句普通话在低音量环境噪声下录制。

### 11.4 Initial performance targets

These are project targets to measure and revise, not achieved performance claims:

- For audio up to 5 seconds, transcript returns within 2.5 seconds after speech ends.
- After text reply is produced, first playable TTS audio segment is available within 2 seconds.
- End-to-end voice turn P95 is no more than 7 seconds.

No model should be described as “real-time enough” until local benchmark data supports it.

---

## 12. Milestones and task breakdown

Milestones must not be merged into one implementation.

### Milestone 2A — TTS output loop

Goal:

- Convert existing assistant text replies into speech.
- Provide play, stop, and replay controls.
- Do not force autoplay by default.
- Keep text chat independently usable.

Not included:

- Microphone.
- ASR.
- VAD.
- Interruption.
- Streaming TTS.

Task split:

1. Add TTS provider interfaces and fake TTS provider tests.
2. Add `AudioService.synthesize_text()` with validation and fake provider.
3. Add `POST /api/audio/speech` route using fake/local provider behind dependency injection.
4. Extend frontend API client for speech synthesis binary response.
5. Add playback controls for assistant messages or latest assistant reply.
6. Add frontend tests for play/stop/replay, TTS error, and no forced autoplay.
7. Add E2E with fake TTS bytes and no real TTS calls.

Acceptance:

- Text replies can be converted to audio.
- Playback, pause if supported, stop, and replay work.
- Text chat is unaffected.
- TTS errors show clear messages.
- Automated tests do not call real TTS.
- No audio/temp file leakage.

### Milestone 2B — Push-to-talk and ASR

Goal:

- User clicks start recording.
- User clicks end recording.
- Audio uploads to local backend.
- ASR returns transcript text.
- Transcript appears in the input box for user confirmation/editing.

Not included:

- Automatic send to LLM.
- VAD.
- Interruption.

Task split:

1. Add ASR provider interfaces and fake ASR provider tests.
2. Add upload validation and temp-file cleanup tests.
3. Add `POST /api/audio/transcriptions` route.
4. Add frontend recorder controller using `getUserMedia` and `MediaRecorder`.
5. Add transcript-to-input flow with explicit user send.
6. Add permission/device/error UI.
7. Add tests with fixed audio fixtures and fake ASR response.

Acceptance:

- Microphone permission flow is correct.
- User can record, stop, and re-record.
- ASR text enters the input box first.
- User can edit before sending.
- Silence and empty files are rejected.
- Raw audio is not retained by default.
- Automated tests use fixed audio fixture and fake ASR.

### Milestone 2C — Full half-duplex voice turn

Goal:

- Recording.
- ASR.
- User confirmation or explicit auto-send option.
- Existing DeepSeek/text reply path.
- TTS.
- Playback.

Half-duplex rule:

- The app can record or play, not both at the same time.

Task split:

1. Decide whether to orchestrate in frontend or add `POST /api/sessions/{session_id}/voice-turns`.
2. Add `VoiceTurnService` only if backend orchestration is chosen.
3. Preserve text database semantics: ASR transcript as user message, assistant text as assistant message.
4. Add TTS failure handling that preserves text reply.
5. Add optional user setting for auto-send, default off unless user explicitly enables it.
6. Add E2E with fake ASR/TTS and fake LLM provider.

Acceptance:

- Complete voice turn runs.
- Final message database structure matches text conversation.
- ASR text is the user message.
- TTS failure does not lose text reply.
- Text mode remains usable.
- No Stage 3 or Stage 4 feature is introduced.

### Milestone 2D — VAD auto-stop

Goal:

- After user explicitly starts recording, VAD detects speech start/end.
- Manual stop remains available.
- VAD false positives/negatives can be canceled or re-recorded.

Task split:

1. Add VAD abstraction and fake VAD tests.
2. Benchmark Silero VAD CPU performance.
3. Add frontend/backend strategy for VAD placement after measurements.
4. Add auto-stop behavior behind a setting or explicit mode.
5. Add tests for manual override and false-detection recovery.

Acceptance:

- VAD can end recording without removing manual stop.
- User can cancel or re-record after VAD mistakes.
- VAD does not run as background listening before explicit user start.

### Milestone 2E — Voice interruption

Goal:

- During TTS playback, detect that user started speaking.
- Stop current playback immediately.
- Clear unplayed audio queue.
- Begin a new user voice turn.

Task split:

1. Define echo/feedback mitigation assumptions.
2. Add playback interruption state transitions.
3. Add queue clearing and object URL cleanup.
4. Add tests for interruption while audio is playing.
5. Add UI indicator that interruption mode is active.

Acceptance:

- User speech can stop TTS playback.
- Pending audio queue is cleared.
- New voice turn begins cleanly.
- No background listening outside active playback interruption mode.

### Milestone 2F — Streaming and performance optimization

Goal:

- Evaluate streaming ASR.
- Evaluate sentence-level TTS or streaming TTS.
- Reduce time from speech end to first character voice audio.
- Preserve existing message persistence semantics.

Task split:

1. Run ASR/TTS benchmark suite on local hardware.
2. Compare faster-whisper vs sherpa-onnx for streaming needs.
3. Compare local lightweight TTS vs CosyVoice provider.
4. Evaluate sentence splitting for long assistant replies.
5. Add latency telemetry without private transcript/audio logs.

Acceptance:

- Optimizations are backed by local measurements.
- Message persistence remains text-first and unchanged.
- No unverified real-time claims are made.

---

## 13. Acceptance standards summary

### Milestone 2A acceptance

- Text reply can be converted to speech.
- Play, pause if supported, stop, and replay work.
- Text chat remains independent.
- TTS errors have clear UI messages.
- Automated tests do not call real TTS.
- No audio or temporary file leakage.

### Milestone 2B acceptance

- Microphone permission flow works.
- Recording, stop, and re-record work.
- ASR transcript first enters input box.
- User can edit before sending.
- Empty and pure-silence audio are rejected.
- Raw audio is not retained by default.
- Automated tests use fixed audio fixtures.

### Milestone 2C acceptance

- Full voice turn can run.
- Final message database structure matches existing text chat.
- ASR transcript is persisted as the user message.
- TTS failure does not lose the text reply.
- Text mode is always available.
- Stage 3 memory and Stage 4 emotion are not implemented.

---

## 14. Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| Browser recording format differs by platform/browser | Upload rejected or ASR cannot decode | Runtime MIME detection, backend content probing, fixture coverage for supported formats |
| Windows audio device compatibility | User cannot record or device disappears mid-recording | Clear permission/device errors, track cleanup, text fallback |
| CUDA/cuDNN/model dependency conflicts | ASR/TTS cannot load or crashes process | Isolated provider evaluation, process isolation option, benchmark before adoption |
| ASR and TTS compete for VRAM | OOM or high latency | Lazy loading, unload strategy, CPU VAD, no assumption of simultaneous residency |
| Long text TTS latency | Slow voice response | Text length cap in 2A, sentence splitting evaluation in 2F |
| Bad punctuation or sentence splitting | Robotic or confusing speech | Add text normalization provider layer later, benchmark sentence segmentation |
| Microphone echo recognizes TTS playback | Self-triggered interruption or false user speech | Half-duplex until 2E, echo mitigation analysis before interruption |
| User records while TTS plays | State corruption | State machine disallows record/play overlap until defined 2E interruption |
| Fast repeated clicks | Duplicate uploads/sends/playbacks | Transition locks, disabled controls, request IDs, AbortController |
| Model license or voice authorization issues | Legal/ethical blocker | Require license review and user-owned/authorized voice assets |
| Temporary audio leakage | Privacy breach | `try/finally` deletion, no default raw audio retention, no raw audio logs |
| Chinese and mixed Chinese/English ASR quality | Poor transcript quality | Benchmark with dedicated mixed-language utterances and user confirmation before send |
| OOM exits backend | App crash | Catch provider OOM errors, process isolation for heavy models, controlled error mapping |
| ASR hallucination on silence | Incorrect message draft | Silence detection and transcript review before sending |
| TTS format unsupported by browser | Playback fails | Use browser-supported MIME checks and fake binary response tests |

---

## 15. User decision items before implementation

1. First TTS provider preference among local Chinese-capable lightweight engines after license review.
2. Whether Milestone 2A should synthesize only the latest assistant reply or add playback controls to every assistant message.
3. Whether 2A should default to no autoplay. Recommendation: no autoplay by default.
4. Whether 2B transcript confirmation must always be manual. Recommendation: manual confirmation in 2B.
5. Whether 2C auto-send should exist as an opt-in setting. Recommendation: opt-in only, default off.
6. Preferred initial voice asset and proof that it is owned or explicitly authorized.
7. Whether raw audio can ever be saved for debugging. Recommendation: no by default; require explicit local debug opt-in if ever needed.
8. Whether heavy ASR/TTS providers may run in separate worker processes. Recommendation: allow this if benchmark or stability requires it.
9. Whether the user wants Stage 2A first, or an even smaller provider-interface-only preparation task. Recommendation: start with provider-interface + fake TTS tests as the first implementation task.

---

## 16. Recommended first implementation task

Recommended first implementation task: Milestone 2A preparation — add the TTS provider abstraction, fake TTS provider, `AudioService.synthesize_text()` boundary, and backend tests without any real TTS dependency.

Why this first:

- It does not require microphone permission or browser recording.
- It exercises the provider abstraction pattern from Stage 1.
- It keeps text chat independent.
- It can be fully tested offline with fake audio bytes.
- It creates the smallest safe Stage 2 vertical slice before choosing real TTS dependencies.

Strict first-task scope:

- Add interfaces and fake provider only.
- Add tests for validation and error mapping.
- Do not install real TTS dependencies.
- Do not download models.
- Do not modify Prompt, LLM Provider, or existing chat persistence semantics.

---

## 17. Self-review against the requested planning scope

- Stage goals and non-goals: covered in sections 2 and 13.
- Existing architecture review: covered in section 1.
- Reusable Stage 1 components: covered in section 1.4.
- New abstractions: covered in sections 1.5 and 5.
- Non-breaking interfaces: covered in section 1.6.
- Environment constraints: covered in sections 1.7 and 9.
- Gradual milestones 2A through 2F: covered in section 12.
- ASR/TTS/VAD ADR recommendations: covered in section 4.
- Backend Provider interfaces: covered in section 5.
- API drafts: covered in section 6.
- Frontend state machine: covered in section 7.
- Audio input planning: covered in section 8.
- GPU/process planning: covered in section 9.
- Security/privacy: covered in section 10.
- Benchmark design and test utterances: covered in section 11.
- Acceptance standards: covered in sections 12 and 13.
- Risk register: covered in section 14.
- User decisions and first implementation task: covered in sections 15 and 16.

## 18. Milestone 2A implementation addendum — 2026-06-25

Implemented 2A interface decisions:

- Backend uses a dedicated `TTSProvider` protocol, separate from `LLMProvider`.
- `SpeechSynthesisResult` includes `audio_bytes`, `media_type`, `sample_rate`, `duration_ms`, `provider`, and `model`.
- `TTSService` is the only service boundary for synthesis validation and provider invocation in 2A; no `AudioService.synthesize_text()` is introduced for this milestone.
- `POST /api/audio/speech` returns binary `audio/wav` with `X-TTS-Provider`, `X-TTS-Model`, `X-Audio-Duration-Ms`, and `X-Audio-Sample-Rate` headers.
- The 2A provider is `FakeTTSProvider`, which uses only Python standard library WAV generation and does not write audio files.
- Frontend playback uses a centralized controller with a single `HTMLAudioElement`, one active message, and one active `AbortController`.
- Assistant messages receive manual playback controls; user messages do not.
- No autoplay, ASR, VAD, microphone recording, streaming TTS, voice interruption, Stage 3 memory, or Stage 4 emotion feature is included.

Deviation from the planning draft:

- The planning draft mentioned `AudioService.synthesize_text()` as a possible boundary. The approved 2A implementation uses `TTSService` directly to avoid parallel service names before ASR/audio-upload exists.

Automated E2E boundary:

- E2E verifies the fake WAV response, `/api/audio/speech` request, Blob URL based playback control state, continued text chat, and absence of browser console/server errors.
- Automated tests do not prove actual speaker output. The README records a separate manual smoke step for hearing the short fake test tone.

Closure update:

- Milestone 2A status: COMPLETED.
- Automated validation: PASS.
- Manual speaker smoke: PASS. The user confirmed assistant messages show playback controls, default autoplay is off, Fake TTS short test tone is audible after clicking play, pause/resume/stop/replay work, playing another assistant message stops the previous one, switching sessions stops playback, text chat remains usable, and the browser console shows no unhandled exceptions.
- Fake TTS remains a deterministic local test tone only. It is not natural speech and does not mean real local TTS Provider integration is complete.
- Milestones 2B—2F remain NOT STARTED; the next candidate is 2B, but implementation has not begun.

## 19. Milestone 2D implementation addendum — 2026-06-29

Implemented 2D boundary:

- Browser-side Silero/ONNX VAD starts only after the user explicitly clicks `开始录音` and the recorder enters `recording`.
- VAD is a stop signal only: it calls the same existing recorder stop path as the manual `停止录音` button.
- `MediaRecorder` remains the only source of uploaded ASR audio.
- Manual stop, cancel, retry, and re-record remain available while VAD is active.
- VAD failure degrades to manual recording with the user-facing message `语音端点检测不可用，请手动停止`.
- The real VAD adapter loads local browser assets via `/vendor/onnxruntime/ort.js` and `/vendor/vad/bundle.min.js`, then uses `window.vad.MicVAD` behind the project-owned adapter boundary.
- Generated VAD/ONNX assets are copied from `node_modules` for local Vite serving and are not committed by default.

Validation update:

- Fake VAD lifecycle tests passed.
- Full frontend regression, typecheck, and build passed.
- Real VAD asset-load browser smoke passed with 0 console errors.
- Headed real VAD auto-stop smoke passed: after speech ended, the app reached pending transcript state through the existing ASR path.
- Evidence is recorded in `docs/stage2d-vad-auto-stop.md`.

Still not implemented after 2D:

- Voice interruption / barge-in.
- Audio device management UI.
- Streaming ASR/TTS and performance optimization.
- Stage 3 long-term memory.
- Stage 4 emotion system.

## 20. Milestone 2E implementation addendum — 2026-06-29

Implemented 2E boundary:

- Explicit user click on `开始录音` can interrupt assistant audio synthesis/playback.
- Interruption reuses `audioController.reset()` and the existing recorder/VAD/ASR path.
- Recording remains blocked while chat send is in flight.
- Fake-provider Playwright E2E runs Vite in test mode, so real VAD stays disabled in fake media tests while real VAD smoke remains opt-in.
- No background listening, automatic spoken barge-in, streaming, memory, or emotion behavior is introduced.

Evidence is recorded in `docs/stage2e-explicit-voice-interruption.md`.

Still not implemented after 2E:

- Audio device management UI.
- Streaming ASR/TTS and performance optimization.
- Stage 3 long-term memory.
- Stage 4 emotion system.

## 21. Stage 2F-pre implementation addendum — audio input device management — 2026-06-29

Implemented boundary:

- Browser UI shows a microphone input selector and refresh control.
- Device enumeration uses `navigator.mediaDevices.enumerateDevices()` without requesting microphone permission on page load.
- Selected audio input device is passed to recording as `deviceId: { ideal: selectedDeviceId }`.
- Enumeration failure is non-blocking and falls back to system default microphone.
- Device IDs remain frontend session state only; they are not sent to the backend or persisted.
- No output device selection, streaming, memory, or emotion behavior is introduced.

Evidence is recorded in `docs/stage2f-audio-device-management.md`.

Still not implemented after 2F-pre:

- Output device selection and device preference persistence.
- Streaming ASR/TTS and performance optimization.
- Stage 3 long-term memory.
- Stage 4 emotion system.

## 22. Stage 2F-1 implementation addendum — streaming/performance measurement baseline — 2026-06-29

Implemented boundary:

- Added `frontend/scripts/measure-voice-turn-latency.mjs` and `npm run measure:voice-turn`.
- The script drives the existing fake-provider browser voice-turn UI and measures non-streaming ASR transcript readiness, chat response, TTS response, playback trigger, and end-to-end timing.
- Each measured run validates exactly one transcription request, one chat POST, one TTS request, and one playback trigger.
- The script fails on console/page errors and fails clearly when the frontend is not reachable.
- The measurement uses fake providers only and does not claim real-provider latency.
- No streaming ASR/TTS, backend API change, database change, memory, or emotion behavior is introduced.

Evidence is recorded in `docs/stage2f-streaming-performance-baseline.md`.

Still not implemented after 2F-1:

- Streaming ASR/TTS implementation.
- Real-provider latency benchmark using the same measurement shape.
- Output device selection and device preference persistence.
- Stage 3 long-term memory.
- Stage 4 emotion system.
