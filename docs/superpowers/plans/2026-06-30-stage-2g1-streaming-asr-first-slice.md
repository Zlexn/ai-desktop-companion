# Stage 2G-1 Streaming ASR First Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fake/default streaming ASR first vertical slice so explicit browser recording can display provisional transcript events before a final transcript enters the existing confirmation UI.

**Architecture:** Keep the existing multipart `POST /api/audio/transcriptions` path unchanged. Add a new `POST /api/audio/transcriptions/stream` NDJSON endpoint backed by a new optional `StreamingASRProvider` protocol; fake ASR implements deterministic partial/final events while FasterWhisper remains non-streaming and fails clearly if streaming is requested. Add a frontend `streamTranscription(...)` parser and an opt-in recorder streaming mode using `MediaRecorder.start(timeslice)`; final events reuse existing `pendingTranscript` and `发送并朗读` flow.

**Tech Stack:** FastAPI `StreamingResponse`, Python async iterators, NDJSON, pytest, React/TypeScript/Vitest, Browser `MediaRecorder.start(timeslice)`, existing Vite/Playwright E2E.

---

## Scope guard

Implement only `docs/superpowers/specs/2026-06-30-stage-2g1-streaming-asr-first-slice-design.md`.

Do not implement real FasterWhisper streaming, LLM response streaming, WebSockets, always-on microphone capture, wake word, automatic spoken barge-in, long-term memory, emotion state, or final seamless low-gap audio playback.

Because this repository already has many uncommitted changes and no explicit commit authorization in this turn, every task ends with a checkpoint instead of a commit.

---

## File structure

Create:

- `backend/tests/test_asr_streaming.py`
  - Unit tests for fake streaming ASR provider and `ASRService.transcribe_stream(...)` validation.

- `backend/tests/test_api_audio_transcriptions_streaming.py`
  - API tests for `POST /api/audio/transcriptions/stream` NDJSON behavior and unsupported provider failures.

- `frontend/src/api/transcriptionStream.ts`
  - Browser NDJSON parser for streaming ASR events.

- `frontend/src/api/transcriptionStream.test.ts`
  - Parser tests for chunked NDJSON, partial/final/error events, and malformed streams.

- `frontend/.claude-stage2g1-streaming-asr-smoke.mjs`
  - Local browser smoke driver for fake/default streaming ASR, created only for runtime evidence.

- `docs/stage2g1-streaming-asr-first-slice.md`
  - Evidence document after validation.

Modify:

- `backend/app/asr/base.py`
  - Add `TranscriptionStreamEvent` dataclasses and `StreamingASRProvider` protocol.

- `backend/app/asr/fake_provider.py`
  - Add deterministic fake streaming ASR events.

- `backend/app/services/asr_service.py`
  - Add `transcribe_stream(...)` validation and unsupported-provider handling.

- `backend/app/api/routes/audio.py`
  - Add `POST /api/audio/transcriptions/stream` returning `application/x-ndjson`.

- `frontend/src/api/types.ts`
  - Add streaming ASR event TypeScript types.

- `frontend/src/api/client.ts`
  - Export `streamTranscription` via `apiClient`.

- `frontend/src/hooks/useManualAudioRecorder.ts`
  - Add optional streaming ASR mode, partial transcript state, and timeslice recording.

- `frontend/src/components/MessageInput.tsx` or `VoiceRecorder.tsx`
  - Display provisional transcript text clearly as non-final.

- `frontend/src/App.tsx`
  - Wire recorder partial transcript state and keep stale generation/session guards.

- Relevant frontend tests: `useManualAudioRecorder.test.ts`, `App.test.tsx`, `voice-turn.spec.ts`.

- `README.md`, `CLAUDE.md`
  - Update only after validation passes.

---

## Task 1: Backend streaming ASR types and fake provider

**Files:**
- Modify: `backend/app/asr/base.py`
- Modify: `backend/app/asr/fake_provider.py`
- Create: `backend/tests/test_asr_streaming.py`

- [ ] **Step 1: Write failing tests for fake streaming ASR events**

Create `backend/tests/test_asr_streaming.py`:

```py
from __future__ import annotations

import pytest

from app.asr.base import TranscriptionFinalEvent, TranscriptionPartialEvent
from app.asr.fake_provider import FakeASRProvider


@pytest.mark.asyncio
async def test_fake_asr_stream_yields_partial_and_final_events() -> None:
    provider = FakeASRProvider(
        text="语音转写文本",
        detected_language="zh",
        model="fake-asr-v1",
        mode="ok",
    )

    events = [event async for event in provider.transcribe_stream([b"chunk-1", b"chunk-2"], "audio/webm", "zh")]

    assert [event.type for event in events] == ["partial", "partial", "final"]
    assert isinstance(events[0], TranscriptionPartialEvent)
    assert events[0].index == 0
    assert events[0].text == "语音"
    assert events[0].is_final is False
    assert isinstance(events[1], TranscriptionPartialEvent)
    assert events[1].index == 1
    assert events[1].text == "语音转写文本"
    assert isinstance(events[2], TranscriptionFinalEvent)
    assert events[2].result.text == "语音转写文本"
    assert events[2].result.provider == "fake-asr"
```

- [ ] **Step 2: Run test to verify RED**

Run:

```text
python -m pytest backend/tests/test_asr_streaming.py -v
```

Expected:

```text
ImportError or AttributeError for TranscriptionPartialEvent / transcribe_stream
```

- [ ] **Step 3: Add stream event types**

Modify `backend/app/asr/base.py`:

```py
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class TranscriptionPartialEvent:
    type: Literal["partial"]
    index: int
    text: str
    is_final: bool
    audio_ms: int | None = None


@dataclass(frozen=True)
class TranscriptionFinalEvent:
    type: Literal["final"]
    result: TranscriptionResult


TranscriptionStreamEvent = TranscriptionPartialEvent | TranscriptionFinalEvent


class StreamingASRProvider(ASRProvider, Protocol):
    async def transcribe_stream(
        self,
        audio_chunks: Iterable[bytes],
        media_type: str,
        language: str | None = None,
    ) -> AsyncIterator[TranscriptionStreamEvent]:
        ...
```

Keep existing `TranscriptionSegment`, `TranscriptionResult`, and `ASRProvider.transcribe(...)` unchanged.

- [ ] **Step 4: Add fake provider streaming implementation**

Modify `backend/app/asr/fake_provider.py` by adding this method to `FakeASRProvider`:

```py
    async def transcribe_stream(
        self,
        audio_chunks: Iterable[bytes],
        media_type: str,
        language: str | None = None,
    ) -> AsyncIterator[TranscriptionStreamEvent]:
        chunks = list(audio_chunks)
        if not chunks:
            raise ASRInvalidRequestError()
        text = self._text.strip()
        if self._mode == "timeout":
            raise ASRTimeoutError()
        if self._mode == "error":
            raise ASRUnavailableError("Fake ASR streaming error")
        if self._mode == "empty":
            text = ""
        if not text:
            yield TranscriptionFinalEvent(
                type="final",
                result=TranscriptionResult(
                    text="",
                    detected_language=self._detected_language,
                    duration_ms=1000,
                    provider=self.provider_name,
                    model=self._model,
                    inference_ms=1,
                ),
            )
            return

        midpoint = max(1, min(len(text), len(text) // 2))
        yield TranscriptionPartialEvent(type="partial", index=0, text=text[:midpoint], is_final=False, audio_ms=1000)
        yield TranscriptionPartialEvent(type="partial", index=1, text=text, is_final=False, audio_ms=2000)
        yield TranscriptionFinalEvent(
            type="final",
            result=await self.transcribe(b"".join(chunks), media_type, language),
        )
```

Add needed imports:

```py
from collections.abc import AsyncIterator, Iterable
from app.asr.base import TranscriptionFinalEvent, TranscriptionPartialEvent, TranscriptionStreamEvent
```

- [ ] **Step 5: Run backend streaming unit test to verify GREEN**

Run:

```text
python -m pytest backend/tests/test_asr_streaming.py -v
```

Expected:

```text
1 passed
```

- [ ] **Step 6: Checkpoint**

Run:

```text
git status --short
```

Do not commit unless explicitly authorized.

---

## Task 2: ASR service streaming validation

**Files:**
- Modify: `backend/app/services/asr_service.py`
- Modify: `backend/tests/test_asr_streaming.py`

- [ ] **Step 1: Add failing service tests**

Append to `backend/tests/test_asr_streaming.py`:

```py
from app.core.config import Settings
from app.core.errors import ASRInvalidResponseError, ASRUnavailableError
from app.services.asr_service import ASRService


@pytest.mark.asyncio
async def test_asr_service_stream_validates_partial_and_final_events() -> None:
    settings = Settings(asr_min_duration_ms=300, asr_max_duration_ms=30_000)
    service = ASRService(FakeASRProvider(text="语音转写文本", detected_language="zh", model="fake-asr-v1", mode="ok"), settings)

    events = [event async for event in service.transcribe_stream([b"\x1a\x45\xdf\xa3chunk"], "audio/webm", "zh")]

    assert [event.type for event in events] == ["partial", "partial", "final"]
    assert events[-1].result.text == "语音转写文本"


@pytest.mark.asyncio
async def test_asr_service_stream_rejects_unsupported_provider() -> None:
    class BatchOnlyProvider:
        async def transcribe(self, audio_bytes: bytes, media_type: str, language: str | None = None):
            raise AssertionError("batch transcribe must not be called for streaming")

    service = ASRService(BatchOnlyProvider(), Settings())

    with pytest.raises(ASRUnavailableError, match="不支持流式转写"):
        _ = [event async for event in service.transcribe_stream([b"\x1a\x45\xdf\xa3chunk"], "audio/webm", "zh")]
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```text
python -m pytest backend/tests/test_asr_streaming.py -v
```

Expected:

```text
AttributeError: 'ASRService' object has no attribute 'transcribe_stream'
```

- [ ] **Step 3: Implement service method**

Add imports in `backend/app/services/asr_service.py`:

```py
from collections.abc import Iterable, AsyncIterator
from app.asr.base import TranscriptionFinalEvent, TranscriptionPartialEvent, TranscriptionStreamEvent
```

Add method to `ASRService` after `transcribe(...)`:

```py
    async def transcribe_stream(
        self,
        audio_chunks: Iterable[bytes],
        media_type: str,
        language: str | None = None,
    ) -> AsyncIterator[TranscriptionStreamEvent]:
        chunks = list(audio_chunks)
        self._validate_audio_bytes(b"".join(chunks))
        normalized_media_type = self._normalize_media_type(media_type)
        self._validate_media_type(normalized_media_type)
        clean_language = self._normalize_language(language)

        transcribe_stream = getattr(self._provider, "transcribe_stream", None)
        if transcribe_stream is None:
            raise ASRUnavailableError("当前 ASR Provider 不支持流式转写。")

        try:
            async for event in transcribe_stream(chunks, normalized_media_type, clean_language):
                if isinstance(event, TranscriptionPartialEvent):
                    text = event.text.strip()
                    if event.index < 0 or not text:
                        raise ASRInvalidResponseError()
                    yield TranscriptionPartialEvent(type="partial", index=event.index, text=text, is_final=False, audio_ms=event.audio_ms)
                elif isinstance(event, TranscriptionFinalEvent):
                    yield TranscriptionFinalEvent(type="final", result=self._validate_result(event.result))
                else:
                    raise ASRInvalidResponseError()
        except ASRTimeoutError:
            raise
        except TimeoutError as exc:
            raise ASRTimeoutError() from exc
        except ASRUnavailableError:
            raise
        except ASRError:
            raise
        except Exception as exc:
            raise ASRUnavailableError() from exc
```

Do not call `_validate_container_signature(...)` for each chunk in this first slice, because MediaRecorder fragments may not each contain a complete container header. The endpoint will remain fake/default in this slice; real provider streaming is explicitly unsupported.

- [ ] **Step 4: Run service tests to verify GREEN**

Run:

```text
python -m pytest backend/tests/test_asr_streaming.py -v
```

Expected:

```text
3 passed
```

---

## Task 3: Backend streaming transcription endpoint

**Files:**
- Modify: `backend/app/api/routes/audio.py`
- Create: `backend/tests/test_api_audio_transcriptions_streaming.py`

- [ ] **Step 1: Write failing API tests**

Create `backend/tests/test_api_audio_transcriptions_streaming.py`:

```py
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import create_app


def parse_ndjson(body: bytes) -> list[dict[str, object]]:
    return [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]


def test_transcriptions_stream_returns_start_partial_final_and_done(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'stream-asr.db'}")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("ASR_PROVIDER", "fake")
    monkeypatch.setenv("FAKE_ASR_TEXT", "语音转写文本")

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/audio/transcriptions/stream",
            files={"chunks": ("chunk.webm", b"\x1a\x45\xdf\xa3chunk", "audio/webm")},
            data={"language": "zh"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = parse_ndjson(response.content)
    assert events[0] == {"type": "start", "provider": "fake-asr", "model": "fake-asr-v1"}
    assert events[1]["type"] == "partial"
    assert events[1]["text"] == "语音"
    assert events[2]["type"] == "partial"
    assert events[2]["text"] == "语音转写文本"
    assert events[3]["type"] == "final"
    assert events[3]["text"] == "语音转写文本"
    assert events[-1] == {"type": "done"}
```

- [ ] **Step 2: Run API test to verify RED**

Run:

```text
python -m pytest backend/tests/test_api_audio_transcriptions_streaming.py -v
```

Expected:

```text
404 Not Found for /api/audio/transcriptions/stream
```

- [ ] **Step 3: Implement endpoint**

In `backend/app/api/routes/audio.py`, import ASR stream types:

```py
from app.asr.base import TranscriptionFinalEvent, TranscriptionPartialEvent
```

Add helper:

```py
async def _transcription_stream_events(
    asr_service: ASRService,
    chunks: list[UploadFile],
    language: str | None,
) -> AsyncIterator[bytes]:
    raw_chunks = []
    media_type = None
    for chunk in chunks:
        content = await chunk.read(asr_service.max_upload_bytes + 1)
        raw_chunks.append(content)
        media_type = media_type or chunk.content_type
        try:
            await chunk.close()
        except Exception:
            pass
    if not media_type:
        raise ASRContentTypeMissingError()

    started = False
    provider = None
    model = None
    async for event in asr_service.transcribe_stream(raw_chunks, media_type, language):
        if isinstance(event, TranscriptionPartialEvent):
            if not started:
                yield _ndjson_event({"type": "start", "provider": "fake-asr", "model": "fake-asr-v1"})
                started = True
            yield _ndjson_event({
                "type": "partial",
                "index": event.index,
                "text": event.text,
                "is_final": event.is_final,
                "audio_ms": event.audio_ms,
            })
        elif isinstance(event, TranscriptionFinalEvent):
            provider = event.result.provider
            model = event.result.model
            if not started:
                yield _ndjson_event({"type": "start", "provider": provider, "model": model})
                started = True
            yield _ndjson_event({
                "type": "final",
                "text": event.result.text,
                "detected_language": event.result.detected_language,
                "duration_ms": event.result.duration_ms,
                "provider": event.result.provider,
                "model": event.result.model,
                "inference_ms": event.result.inference_ms,
            })
    if not started:
        yield _ndjson_event({"type": "error", "message": "语音转写服务没有返回可用结果。"})
        return
    yield _ndjson_event({"type": "done"})
```

Add route before `/transcriptions`:

```py
@router.post("/transcriptions/stream")
async def transcribe_upload_stream(
    chunks: list[UploadFile] = File(...),
    language: str | None = Form(None),
    asr_service: ASRService = Depends(get_asr_service),
) -> StreamingResponse:
    iterator = _transcription_stream_events(asr_service, chunks, language)
    first = await anext(iterator)

    async def body() -> AsyncIterator[bytes]:
        yield first
        async for event in iterator:
            yield event

    return StreamingResponse(body(), media_type="application/x-ndjson")
```

- [ ] **Step 4: Run API tests to verify GREEN**

Run:

```text
python -m pytest backend/tests/test_api_audio_transcriptions_streaming.py backend/tests/test_api_audio_transcriptions.py -v
```

Expected:

```text
passed
```

---

## Task 4: Frontend streaming transcription parser

**Files:**
- Modify: `frontend/src/api/types.ts`
- Create: `frontend/src/api/transcriptionStream.ts`
- Create: `frontend/src/api/transcriptionStream.test.ts`
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Write parser tests**

Create `frontend/src/api/transcriptionStream.test.ts` with tests for chunked `start`, `partial`, `final`, `done`, and `error` events. Use the existing `speechStream.test.ts` style as reference.

- [ ] **Step 2: Run parser tests to verify RED**

Run:

```text
npm --prefix frontend test -- --run src/api/transcriptionStream.test.ts
```

Expected: module not found or missing export.

- [ ] **Step 3: Add TypeScript event types**

Append to `frontend/src/api/types.ts`:

```ts
export type TranscriptionStreamEvent =
  | { type: 'start'; provider: string; model: string }
  | { type: 'partial'; index: number; text: string; isFinal: boolean; audioMs: number | null }
  | { type: 'final'; text: string; detectedLanguage: string | null; durationMs: number | null; provider: string; model: string; inferenceMs: number }
  | { type: 'done' }
  | { type: 'error'; message: string };
```

- [ ] **Step 4: Implement parser/client**

Create `frontend/src/api/transcriptionStream.ts` that posts `FormData` with repeated `chunks` files to `/api/audio/transcriptions/stream`, parses `response.body` NDJSON incrementally, maps snake_case to camelCase, and yields `TranscriptionStreamEvent`.

- [ ] **Step 5: Export client method**

Modify `frontend/src/api/client.ts`:

```ts
import { streamTranscription } from './transcriptionStream';
...
  streamTranscription,
```

- [ ] **Step 6: Run parser tests to verify GREEN**

Run:

```text
npm --prefix frontend test -- --run src/api/transcriptionStream.test.ts
```

Expected:

```text
passed
```

---

## Task 5: Recorder streaming ASR UI path

**Files:**
- Modify: `frontend/src/hooks/useManualAudioRecorder.ts`
- Modify: `frontend/src/components/VoiceRecorder.tsx`
- Modify: `frontend/src/App.tsx`
- Modify/Create tests: `frontend/src/hooks/useManualAudioRecorder.test.ts`, `frontend/src/App.test.tsx`

- [ ] **Step 1: Add failing frontend tests**

Add tests proving:

```text
- MediaRecorder.start receives a 1000ms timeslice when streaming ASR is enabled.
- Partial transcript is displayed as provisional text.
- Final transcript becomes existing pendingTranscript.
- Cancel clears provisional transcript and prevents stale final updates.
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```text
npm --prefix frontend test -- --run src/hooks/useManualAudioRecorder.test.ts src/App.test.tsx
```

Expected: failures for missing streaming/provisional UI behavior.

- [ ] **Step 3: Extend recorder result type**

In `useManualAudioRecorder.ts`, add:

```ts
partialTranscript: string | null;
streamingAsrEnabled: boolean;
```

Use a local constant for this slice:

```ts
const STREAMING_ASR_ENABLED = true;
const STREAMING_ASR_TIMESLICE_MS = 1000;
```

- [ ] **Step 4: Start recorder with timeslice**

Change recorder start call from:

```ts
recorder.start();
```

to:

```ts
recorder.start(STREAMING_ASR_ENABLED ? STREAMING_ASR_TIMESLICE_MS : undefined);
```

- [ ] **Step 5: Stream chunks and update partial/final state**

Collect non-empty chunks and call `apiClient.streamTranscription(chunks, { language: 'zh', signal })` after stop for the first slice if live request-upload streaming is too risky. This still validates the backend streaming response and UI partial/final handling. If implementing live upload is practical, send chunks as they arrive. In either case, ensure partial events update `partialTranscript` and final events set `pendingTranscript`.

- [ ] **Step 6: Render provisional transcript**

In `VoiceRecorder.tsx`, render:

```tsx
{partialTranscript ? (
  <p role="status" aria-live="polite">实时转写预览：{partialTranscript}</p>
) : null}
```

Do not reuse this as a final transcript; final transcript must still use the existing confirmation UI.

- [ ] **Step 7: Run frontend tests to verify GREEN**

Run:

```text
npm --prefix frontend test -- --run src/hooks/useManualAudioRecorder.test.ts src/App.test.tsx
```

Expected: selected tests pass.

---

## Task 6: Browser E2E and smoke

**Files:**
- Modify: `frontend/e2e/voice-turn.spec.ts` or create `frontend/e2e/streaming-asr.spec.ts`
- Create: `frontend/.claude-stage2g1-streaming-asr-smoke.mjs`

- [ ] **Step 1: Add E2E for streaming ASR first slice**

Use mocked `MediaRecorder` that emits at least two chunks. Assert:

```text
- UI shows 实时转写预览 before final confirmation.
- Final transcript appears as 转写待确认.
- Clicking 发送并朗读 sends exactly one chat request.
- Streaming TTS request still occurs.
- console errors are empty.
```

- [ ] **Step 2: Run E2E to verify GREEN**

Run:

```text
npm --prefix frontend run test:e2e -- streaming-asr.spec.ts
```

Expected: new E2E passes.

- [ ] **Step 3: Create local smoke script**

Create `frontend/.claude-stage2g1-streaming-asr-smoke.mjs` modeled after the existing Stage 2F-4 smoke. It should drive the browser through explicit recording, observe provisional transcript text, final pending transcript, and `发送并朗读`.

- [ ] **Step 4: Run browser smoke**

Start fake/default backend and frontend, then run:

```text
node frontend/.claude-stage2g1-streaming-asr-smoke.mjs
```

Expected JSON includes:

```json
{
  "status": "PASS",
  "partialTranscriptObserved": true,
  "finalTranscriptObserved": true,
  "chatRequests": 1,
  "consoleErrorCount": 0
}
```

---

## Task 7: Full validation and documentation

**Files:**
- Create: `docs/stage2g1-streaming-asr-first-slice.md`
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run backend validation**

Run:

```text
python -m pytest backend/tests/test_asr_streaming.py backend/tests/test_api_audio_transcriptions_streaming.py backend/tests/test_api_audio_transcriptions.py -v
python -m pytest backend/tests -v
```

Expected: all pass; record exact counts.

- [ ] **Step 2: Run frontend validation**

Run:

```text
npm --prefix frontend test -- --run src/api/transcriptionStream.test.ts src/hooks/useManualAudioRecorder.test.ts src/App.test.tsx
npm --prefix frontend test -- --run
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

Expected: all pass; record exact counts.

- [ ] **Step 3: Write evidence doc**

Create `docs/stage2g1-streaming-asr-first-slice.md` with:

```md
# Stage 2G-1 Streaming ASR First Vertical Slice Evidence

Status: COMPLETED on 2026-06-30.

## Scope

...

## Validation

| Command | Result |
|---|---|

## Browser smoke observations

...

## Limitations

- Real FasterWhisper streaming is not implemented.
- Final seamless low-gap audio is not implemented.
- Long-term memory and emotion are not implemented.
```

Use only observed values; do not include private audio or transcript content.

- [ ] **Step 4: Update README and CLAUDE.md only after validation passes**

Add `2G-1 Streaming ASR First Vertical Slice COMPLETED` to current Stage 2 state and remove generic “Streaming ASR NOT STARTED” language only if the fake/default first slice passed. Continue to state that real FasterWhisper streaming ASR is not implemented.

---

## Self-review notes

Spec coverage:

- Preserve existing multipart ASR: Tasks 3 and 7 regression tests.
- New streaming ASR event contract: Tasks 1-4.
- Fake/default partial/final events: Tasks 1-3.
- Browser partial transcript UI: Task 5.
- Existing final confirmation and `发送并朗读`: Tasks 5-6.
- Runtime smoke and evidence: Tasks 6-7.
- Phase boundaries: scope guard and docs limitations.

Placeholder scan:

- No unresolved placeholder markers are intentionally left in implementation steps. Evidence values are captured after commands run.

Type consistency:

- Python event types: `TranscriptionPartialEvent`, `TranscriptionFinalEvent`, `TranscriptionStreamEvent`.
- TypeScript event type: `TranscriptionStreamEvent`.
- Endpoint: `POST /api/audio/transcriptions/stream`.
- Media type: `application/x-ndjson`.

Risk controls:

- Existing non-streaming ASR remains fallback.
- Real FasterWhisper streaming is explicitly unsupported in this slice.
- Partial transcript is provisional and cannot auto-send.
- Stale generation guards remain required.
