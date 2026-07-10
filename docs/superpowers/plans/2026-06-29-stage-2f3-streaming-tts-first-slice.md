# Stage 2F-3 Streaming TTS First Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first verifiable streaming TTS path where fake-provider assistant speech begins playback from the first streamed WAV segment before the TTS stream completes.

**Architecture:** Preserve the existing complete-WAV `/api/audio/speech` path. Add a separate `/api/audio/speech/stream` NDJSON endpoint, a fake streaming provider path that emits complete standalone WAV segments, a frontend stream parser, and an opt-in playback-controller streaming queue. The first slice proves fake-provider browser streaming; real CosyVoice streaming, streaming ASR, memory, and emotion remain out of scope.

**Tech Stack:** FastAPI `StreamingResponse`, Python async iterators, base64 NDJSON, React, TypeScript, Fetch `ReadableStream`, Vitest, Testing Library, Playwright, existing `HTMLAudioElement` playback controller.

---

## Scope guard

Implement only `docs/superpowers/specs/2026-06-29-stage-2f3-streaming-tts-first-slice-design.md`.

Do not implement streaming ASR, LLM streaming, WebSockets, MediaSource/WebCodecs, backend persistence changes, long-term memory, or emotion state.

Because the current session has not received explicit authorization to create git commits and the repository already has many uncommitted changes, every task ends with a checkpoint instead of a commit. If the user explicitly authorizes commits later, use the commit commands shown in each task.

## File structure

Create:

- `backend/tests/test_tts_streaming.py`
  - Backend unit tests for streaming dataclasses, fake streaming segmentation, and TTS service validation.

- `backend/tests/test_api_audio_streaming.py`
  - API tests for `POST /api/audio/speech/stream` NDJSON events and unsupported-provider behavior.

- `frontend/src/api/speechStream.ts`
  - Frontend streaming TTS event parser and `streamSpeech(...)` async generator.

- `frontend/src/api/speechStream.test.ts`
  - Parser tests for chunk boundaries, invalid events, abort, and base64 audio conversion.

Modify:

- `backend/app/tts/base.py`
  - Add `SpeechSynthesisSegment` dataclass and `StreamingTTSProvider` protocol.

- `backend/app/tts/fake_provider.py`
  - Add `synthesize_stream(...)` yielding deterministic WAV segments.

- `backend/app/services/tts_service.py`
  - Add `synthesize_stream(...)`, reusing request validation and segment validation.

- `backend/app/api/routes/audio.py`
  - Add `POST /api/audio/speech/stream` returning NDJSON `StreamingResponse`.

- `frontend/src/api/client.ts`
  - Export `streamSpeech(...)` through `apiClient`.

- `frontend/src/api/types.ts`
  - Add stream event and streaming options types if not kept entirely in `speechStream.ts`.

- `frontend/src/hooks/useAudioPlaybackController.ts`
  - Add opt-in streaming playback queue while preserving current non-streaming `play(...)` behavior.

- `frontend/src/components/MessageList.test.tsx`
  - Add tests for first segment playback before done, segment order, cleanup, and output-device routing.

- `frontend/src/App.tsx`
  - Opt the send-and-speak path into streaming only after controller tests pass, or pass a streaming flag through message playback if the implementation chooses manual assistant playback first.

- `frontend/src/App.test.tsx`
  - Cover streaming voice-turn success and interruption failure cleanup.

- `frontend/e2e/voice-turn.spec.ts`
  - Route `/api/audio/speech/stream`, assert one streaming request, first play before done, and no duplicate chat/TTS requests.

- `frontend/scripts/measure-voice-turn-latency.mjs`
  - Record streaming TTS first-segment and done timings in fake-provider measurement.

- `docs/stage2f3-streaming-tts-first-slice.md`
  - Evidence document after validation.

- `CLAUDE.md` and `README.md`
  - Update only after validation passes.

---

## Task 1: Add backend streaming TTS primitives

**Files:**
- Modify: `backend/app/tts/base.py`
- Modify: `backend/app/tts/fake_provider.py`
- Modify: `backend/app/services/tts_service.py`
- Create: `backend/tests/test_tts_streaming.py`

- [ ] **Step 1: Write failing backend streaming tests**

Create `backend/tests/test_tts_streaming.py`:

```py
from __future__ import annotations

import wave
from io import BytesIO

import pytest

from app.core.config import Settings
from app.core.errors import TTSInvalidRequestError, TTSInvalidResponseError
from app.services.tts_service import TTSService
from app.tts.base import SpeechSynthesisSegment
from app.tts.fake_provider import FakeTTSProvider


def wav_duration_ms(audio_bytes: bytes) -> int:
    with wave.open(BytesIO(audio_bytes), "rb") as wav_file:
        return round(wav_file.getnframes() / wav_file.getframerate() * 1000)


@pytest.mark.asyncio
async def test_fake_tts_stream_yields_ordered_wav_segments() -> None:
    provider = FakeTTSProvider()

    segments = [segment async for segment in provider.synthesize_stream("第一句。第二句。第三句。", "fake-default", 1.0)]

    assert [segment.index for segment in segments] == [0, 1, 2]
    assert all(segment.media_type == "audio/wav" for segment in segments)
    assert all(segment.audio_bytes.startswith(b"RIFF") for segment in segments)
    assert all(segment.audio_bytes[8:12] == b"WAVE" for segment in segments)
    assert all(segment.sample_rate == 16000 for segment in segments)
    assert all(segment.duration_ms == wav_duration_ms(segment.audio_bytes) for segment in segments)
    assert all(segment.provider == "fake" for segment in segments)
    assert all(segment.model == "fake-tone-v1" for segment in segments)


@pytest.mark.asyncio
async def test_tts_service_stream_reuses_request_validation() -> None:
    service = TTSService(FakeTTSProvider(), Settings(tts_provider="fake", llm_provider="fake"))

    with pytest.raises(TTSInvalidRequestError):
        _ = [segment async for segment in service.synthesize_stream("   ")]


class InvalidStreamingProvider(FakeTTSProvider):
    async def synthesize_stream(self, text: str, voice_id: str | None = None, speed: float = 1.0):
        yield SpeechSynthesisSegment(
            audio_bytes=b"not a wav",
            media_type="audio/mpeg",
            sample_rate=0,
            duration_ms=0,
            provider="fake",
            model="fake-tone-v1",
            index=0,
        )


@pytest.mark.asyncio
async def test_tts_service_stream_validates_segments() -> None:
    service = TTSService(InvalidStreamingProvider(), Settings(tts_provider="fake", llm_provider="fake"))

    with pytest.raises(TTSInvalidResponseError):
        _ = [segment async for segment in service.synthesize_stream("测试")]
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```text
python -m pytest backend/tests/test_tts_streaming.py -v
```

Expected:

```text
FAILED backend/tests/test_tts_streaming.py::test_fake_tts_stream_yields_ordered_wav_segments
AttributeError: 'FakeTTSProvider' object has no attribute 'synthesize_stream'
```

- [ ] **Step 3: Add streaming dataclass and protocol**

Modify `backend/app/tts/base.py`:

```py
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SpeechSynthesisResult:
    audio_bytes: bytes
    media_type: str
    sample_rate: int
    duration_ms: int
    provider: str
    model: str


@dataclass(frozen=True)
class SpeechSynthesisSegment:
    audio_bytes: bytes
    media_type: str
    sample_rate: int
    duration_ms: int
    provider: str
    model: str
    index: int


class TTSProvider(Protocol):
    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        speed: float = 1.0,
    ) -> SpeechSynthesisResult:
        ...


class StreamingTTSProvider(TTSProvider, Protocol):
    async def synthesize_stream(
        self,
        text: str,
        voice_id: str | None = None,
        speed: float = 1.0,
    ) -> AsyncIterator[SpeechSynthesisSegment]:
        ...
```

- [ ] **Step 4: Add fake provider streaming**

Modify `backend/app/tts/fake_provider.py` imports:

```py
from collections.abc import AsyncIterator

from app.tts.base import SpeechSynthesisResult, SpeechSynthesisSegment
```

Add methods inside `FakeTTSProvider`:

```py
    async def synthesize_stream(
        self,
        text: str,
        voice_id: str | None = None,
        speed: float = 1.0,
    ) -> AsyncIterator[SpeechSynthesisSegment]:
        if self._mode == "error":
            raise TTSUnavailableError()
        if self._mode == "timeout":
            raise TTSTimeoutError()
        if self._mode == "empty":
            return

        for index, segment_text in enumerate(self._split_stream_text(text)):
            duration_ms = self._duration_for_text(segment_text, speed)
            audio_bytes = self._build_wav(duration_ms, segment_text)
            yield SpeechSynthesisSegment(
                audio_bytes=audio_bytes,
                media_type="audio/wav",
                sample_rate=self.sample_rate,
                duration_ms=duration_ms,
                provider=self.provider_name,
                model=self.model_name,
                index=index,
            )

    def _split_stream_text(self, text: str) -> list[str]:
        clean = text.strip()
        if not clean:
            return []
        parts: list[str] = []
        current = ""
        for char in clean:
            current += char
            if char in "。！？!?\n" or len(current) >= 18:
                piece = current.strip()
                if piece:
                    parts.append(piece)
                current = ""
        tail = current.strip()
        if tail:
            parts.append(tail)
        return parts or [clean]
```

- [ ] **Step 5: Add service streaming method**

Modify `backend/app/services/tts_service.py` imports:

```py
from collections.abc import AsyncIterator

from app.tts.base import SpeechSynthesisResult, SpeechSynthesisSegment, TTSProvider
```

Add method inside `TTSService` after `synthesize(...)`:

```py
    async def synthesize_stream(
        self,
        text: str,
        voice_id: str | None = None,
        speed: float | None = None,
    ) -> AsyncIterator[SpeechSynthesisSegment]:
        clean_text = text.strip()
        selected_voice = voice_id or self._settings.tts_default_voice
        selected_speed = self._settings.tts_default_speed if speed is None else speed
        self._validate_request(clean_text, selected_voice, selected_speed)

        synthesize_stream = getattr(self._provider, "synthesize_stream", None)
        if synthesize_stream is None:
            raise TTSUnavailableError("当前 TTS Provider 不支持流式合成。")

        try:
            async for segment in synthesize_stream(clean_text, selected_voice, selected_speed):
                self._validate_segment(segment)
                yield segment
        except TTSTimeoutError:
            raise
        except TTSError:
            raise
        except TimeoutError as exc:
            raise TTSTimeoutError() from exc
        except Exception as exc:
            raise TTSUnavailableError() from exc
```

Add segment validation near `_validate_result`:

```py
    def _validate_segment(self, segment: SpeechSynthesisSegment) -> None:
        if segment.index < 0:
            raise TTSInvalidResponseError()
        if not segment.audio_bytes:
            raise TTSInvalidResponseError()
        if segment.media_type not in SUPPORTED_MEDIA_TYPES:
            raise TTSInvalidResponseError()
        if segment.sample_rate <= 0 or segment.duration_ms <= 0:
            raise TTSInvalidResponseError()
        if not segment.provider or not segment.model:
            raise TTSInvalidResponseError()
```

- [ ] **Step 6: Run tests to verify GREEN**

Run:

```text
python -m pytest backend/tests/test_tts_streaming.py -v
```

Expected:

```text
3 passed
```

- [ ] **Step 7: Checkpoint**

Run:

```text
git status --short
```

If commit authorization is active:

```text
git add backend/app/tts/base.py backend/app/tts/fake_provider.py backend/app/services/tts_service.py backend/tests/test_tts_streaming.py
git commit -m "feat: add fake streaming tts primitives"
```

---

## Task 2: Add `/api/audio/speech/stream` NDJSON endpoint

**Files:**
- Modify: `backend/app/api/routes/audio.py`
- Create: `backend/tests/test_api_audio_streaming.py`

- [ ] **Step 1: Write failing API tests**

Create `backend/tests/test_api_audio_streaming.py`:

```py
from __future__ import annotations

import base64
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


def parse_ndjson(body: bytes) -> list[dict[str, object]]:
    return [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]


def test_speech_stream_api_emits_start_segments_and_done(client: TestClient) -> None:
    response = client.post("/api/audio/speech/stream", json={"text": "第一句。第二句。", "voice_id": "fake-default", "speed": 1.0})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = parse_ndjson(response.content)
    assert events[0] == {"type": "start", "provider": "fake", "model": "fake-tone-v1"}
    segments = [event for event in events if event["type"] == "segment"]
    assert [segment["index"] for segment in segments] == [0, 1]
    for segment in segments:
        audio_bytes = base64.b64decode(segment["audio_base64"])
        assert audio_bytes.startswith(b"RIFF")
        assert audio_bytes[8:12] == b"WAVE"
        assert segment["media_type"] == "audio/wav"
        assert segment["sample_rate"] == 16000
        assert int(segment["duration_ms"]) > 0
    assert events[-1] == {"type": "done", "segment_count": 2}


def test_speech_stream_api_rejects_blank_text_before_streaming(client: TestClient) -> None:
    response = client.post("/api/audio/speech/stream", json={"text": "   "})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "tts_invalid_request"


def make_client_with_tts_provider(tmp_path: Path, monkeypatch, provider: str) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / f'{provider}.db'}")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("TTS_PROVIDER", provider)
    if provider == "cosyvoice-http":
        monkeypatch.setenv("TTS_COSYVOICE_BASE_URL", "http://127.0.0.1:1")
        monkeypatch.setenv("TTS_COSYVOICE_MODEL", "test-model")
    get_settings.cache_clear()
    return TestClient(create_app())


def test_speech_stream_api_reports_unsupported_provider_before_streaming(tmp_path: Path, monkeypatch) -> None:
    with make_client_with_tts_provider(tmp_path, monkeypatch, "cosyvoice-http") as client:
        response = client.post("/api/audio/speech/stream", json={"text": "测试"})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "tts_unavailable"
    get_settings.cache_clear()
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```text
python -m pytest backend/tests/test_api_audio_streaming.py -v
```

Expected:

```text
FAILED ... status_code == 404
```

- [ ] **Step 3: Implement route and NDJSON encoder**

Modify `backend/app/api/routes/audio.py` imports:

```py
import base64
import json
from collections.abc import AsyncIterator

from fastapi.responses import StreamingResponse
from app.core.errors import TTSError
from app.tts.base import SpeechSynthesisSegment
```

Add helpers after `router = ...`:

```py
def _ndjson_event(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _segment_event(segment: SpeechSynthesisSegment) -> dict[str, object]:
    return {
        "type": "segment",
        "index": segment.index,
        "audio_base64": base64.b64encode(segment.audio_bytes).decode("ascii"),
        "media_type": segment.media_type,
        "duration_ms": segment.duration_ms,
        "sample_rate": segment.sample_rate,
    }


async def _speech_stream_events(tts_service: TTSService, request: SynthesizeSpeechRequest) -> AsyncIterator[bytes]:
    started = False
    count = 0
    try:
        async for segment in tts_service.synthesize_stream(request.text, request.voice_id, request.speed):
            if not started:
                yield _ndjson_event({"type": "start", "provider": segment.provider, "model": segment.model})
                started = True
            yield _ndjson_event(_segment_event(segment))
            count += 1
        if not started:
            yield _ndjson_event({"type": "error", "message": "语音合成服务没有返回可播放音频。"})
            return
        yield _ndjson_event({"type": "done", "segment_count": count})
    except TTSError as exc:
        if not started:
            raise
        yield _ndjson_event({"type": "error", "message": str(exc) or "语音合成失败，请稍后重试。"})
```

Add endpoint before `/transcriptions`:

```py
@router.post("/speech/stream")
async def synthesize_speech_stream(
    request: SynthesizeSpeechRequest,
    tts_service: TTSService = Depends(get_tts_service),
) -> StreamingResponse:
    # Pull the first item before returning StreamingResponse so validation and unsupported-provider
    # errors still use the normal FastAPI app error envelope.
    iterator = _speech_stream_events(tts_service, request)
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
python -m pytest backend/tests/test_api_audio_streaming.py -v
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Run existing audio API regression**

Run:

```text
python -m pytest backend/tests/test_api_audio.py backend/tests/test_tts_service.py backend/tests/test_tts_provider.py -v
```

Expected:

```text
passed
```

- [ ] **Step 6: Checkpoint**

If commit authorization is active:

```text
git add backend/app/api/routes/audio.py backend/tests/test_api_audio_streaming.py
git commit -m "feat: add streaming speech endpoint"
```

---

## Task 3: Add frontend speech stream parser

**Files:**
- Create: `frontend/src/api/speechStream.ts`
- Create: `frontend/src/api/speechStream.test.ts`
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Write failing parser tests**

Create `frontend/src/api/speechStream.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from 'vitest';
import { streamSpeech } from './speechStream';

const originalFetch = globalThis.fetch;

function streamFromChunks(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

async function collect<T>(iterable: AsyncIterable<T>): Promise<T[]> {
  const items: T[] = [];
  for await (const item of iterable) items.push(item);
  return items;
}

describe('streamSpeech', () => {
  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it('parses NDJSON events split across network chunks', async () => {
    const wavBase64 = btoa(String.fromCharCode(82, 73, 70, 70, 0, 0, 0, 0, 87, 65, 86, 69));
    globalThis.fetch = vi.fn().mockResolvedValue(new Response(streamFromChunks([
      '{"type":"start","provider":"fake","model":"fake-tone-v1"}\n{"type":"seg',
      `ment","index":0,"audio_base64":"${wavBase64}","media_type":"audio/wav","duration_ms":100,"sample_rate":16000}\n`,
      '{"type":"done","segment_count":1}\n',
    ]), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));

    const events = await collect(streamSpeech('hello'));

    expect(events[0]).toEqual({ type: 'start', provider: 'fake', model: 'fake-tone-v1' });
    expect(events[1]).toMatchObject({ type: 'segment', index: 0, mediaType: 'audio/wav', durationMs: 100, sampleRate: 16000 });
    expect(Array.from(events[1].type === 'segment' ? events[1].audioBytes : [])).toEqual([82, 73, 70, 70, 0, 0, 0, 0, 87, 65, 86, 69]);
    expect(events[2]).toEqual({ type: 'done', segmentCount: 1 });
  });

  it('throws a user-facing error for malformed segment events', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response(streamFromChunks([
      '{"type":"segment","index":0,"audio_base64":"","media_type":"audio/wav","duration_ms":0,"sample_rate":0}\n',
    ]), { status: 200 }));

    await expect(collect(streamSpeech('hello'))).rejects.toThrow('语音流返回了无法播放的音频片段。');
  });

  it('uses the normal error envelope for HTTP failures', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { message: '流式语音不可用。' } }), {
      status: 502,
      headers: { 'Content-Type': 'application/json' },
    }));

    await expect(collect(streamSpeech('hello'))).rejects.toThrow('流式语音不可用。');
  });
});
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```text
npm --prefix frontend test -- --run src/api/speechStream.test.ts
```

Expected:

```text
FAIL ... Failed to resolve import "./speechStream"
```

- [ ] **Step 3: Implement stream parser**

Create `frontend/src/api/speechStream.ts`:

```ts
import type { ApiErrorEnvelope, SynthesizeSpeechOptions } from './types';

export type SpeechStreamEvent =
  | { type: 'start'; provider: string | null; model: string | null }
  | { type: 'segment'; index: number; audioBytes: Uint8Array; mediaType: 'audio/wav'; durationMs: number; sampleRate: number }
  | { type: 'done'; segmentCount: number }
  | { type: 'error'; message: string };

async function responseErrorMessage(response: Response): Promise<string> {
  let message = '请求失败，请稍后重试。';
  try {
    const body = (await response.json()) as ApiErrorEnvelope;
    message = body.error?.message || message;
  } catch {
    // Keep generic message.
  }
  return message;
}

function base64ToBytes(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function parseEvent(line: string): SpeechStreamEvent {
  const raw = JSON.parse(line) as Record<string, unknown>;
  if (raw.type === 'start') {
    return {
      type: 'start',
      provider: typeof raw.provider === 'string' ? raw.provider : null,
      model: typeof raw.model === 'string' ? raw.model : null,
    };
  }
  if (raw.type === 'segment') {
    const index = Number(raw.index);
    const durationMs = Number(raw.duration_ms);
    const sampleRate = Number(raw.sample_rate);
    const audioBase64 = typeof raw.audio_base64 === 'string' ? raw.audio_base64 : '';
    if (!Number.isInteger(index) || index < 0 || !audioBase64 || raw.media_type !== 'audio/wav' || durationMs <= 0 || sampleRate <= 0) {
      throw new Error('语音流返回了无法播放的音频片段。');
    }
    return {
      type: 'segment',
      index,
      audioBytes: base64ToBytes(audioBase64),
      mediaType: 'audio/wav',
      durationMs,
      sampleRate,
    };
  }
  if (raw.type === 'done') {
    const segmentCount = Number(raw.segment_count);
    return { type: 'done', segmentCount: Number.isInteger(segmentCount) ? segmentCount : 0 };
  }
  if (raw.type === 'error') {
    return { type: 'error', message: typeof raw.message === 'string' ? raw.message : '语音合成失败，请稍后重试。' };
  }
  return { type: 'error', message: '语音流返回了未知事件。' };
}

export async function* streamSpeech(text: string, options: SynthesizeSpeechOptions = {}): AsyncGenerator<SpeechStreamEvent> {
  const response = await fetch('/api/audio/speech/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice_id: options.voiceId, speed: options.speed }),
    signal: options.signal,
  });

  if (!response.ok) {
    throw new Error(await responseErrorMessage(response));
  }
  if (!response.body) {
    throw new Error('当前浏览器不支持流式语音播放。');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = '';
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      pending += decoder.decode(value, { stream: true });
      const lines = pending.split('\n');
      pending = lines.pop() ?? '';
      for (const line of lines) {
        if (line.trim()) yield parseEvent(line);
      }
    }
    pending += decoder.decode();
    if (pending.trim()) yield parseEvent(pending);
  } finally {
    reader.releaseLock();
  }
}
```

Modify `frontend/src/api/client.ts`:

```ts
import { streamSpeech } from './speechStream';
```

Add to `apiClient`:

```ts
  streamSpeech,
```

- [ ] **Step 4: Run parser tests to verify GREEN**

Run:

```text
npm --prefix frontend test -- --run src/api/speechStream.test.ts
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Checkpoint**

If commit authorization is active:

```text
git add frontend/src/api/speechStream.ts frontend/src/api/speechStream.test.ts frontend/src/api/client.ts
git commit -m "feat: add speech stream parser"
```

---

## Task 4: Add streaming queue to playback controller

**Files:**
- Modify: `frontend/src/hooks/useAudioPlaybackController.ts`
- Modify: `frontend/src/components/MessageList.test.tsx`

- [ ] **Step 1: Write failing controller tests**

Append tests to `frontend/src/components/MessageList.test.tsx`. Use the existing `messages`, `wavResponse`, `playMock`, and `pauseMock` helpers. Add a stream response helper near `wavResponse`:

```ts
function streamResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  return new Response(new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } });
}

function segmentLine(index: number, label: string): string {
  const bytes = new TextEncoder().encode(`RIFF....WAVE${label}`);
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return JSON.stringify({
    type: 'segment',
    index,
    audio_base64: btoa(binary),
    media_type: 'audio/wav',
    duration_ms: 100,
    sample_rate: 16000,
  }) + '\n';
}
```

Add a streaming harness:

```tsx
function StreamingHarness() {
  const audioController = useAudioPlaybackController();
  return (
    <button type="button" onClick={() => { void audioController.play('a1', '我听见了：你好', { streaming: true }); }}>
      stream play
    </button>
  );
}
```

Add tests:

```ts
  it('starts streamed playback from the first segment before done', async () => {
    const user = userEvent.setup();
    let controllerRef: ReadableStreamDefaultController<Uint8Array> | null = null;
    const encoder = new TextEncoder();
    vi.mocked(fetch).mockResolvedValueOnce(new Response(new ReadableStream({
      start(controller) { controllerRef = controller; },
    }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));

    render(<StreamingHarness />);
    await user.click(screen.getByRole('button', { name: 'stream play' }));

    controllerRef?.enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-tone-v1"}\n'));
    controllerRef?.enqueue(encoder.encode(segmentLine(0, 'first')));

    await waitFor(() => expect(playMock).toHaveBeenCalledTimes(1));
    expect(fetch).toHaveBeenCalledWith('/api/audio/speech/stream', expect.objectContaining({ method: 'POST' }));
    controllerRef?.enqueue(encoder.encode('{"type":"done","segment_count":1}\n'));
    controllerRef?.close();
  });

  it('aborts streamed playback and revokes segment URLs on unmount', async () => {
    const user = userEvent.setup();
    let capturedSignal: AbortSignal | undefined;
    let controllerRef: ReadableStreamDefaultController<Uint8Array> | null = null;
    const encoder = new TextEncoder();
    vi.mocked(fetch).mockImplementationOnce((_input, init) => {
      capturedSignal = init?.signal as AbortSignal;
      return Promise.resolve(new Response(new ReadableStream({ start(controller) { controllerRef = controller; } }), { status: 200 }));
    });

    const { unmount } = render(<StreamingHarness />);
    await user.click(screen.getByRole('button', { name: 'stream play' }));
    controllerRef?.enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-tone-v1"}\n'));
    controllerRef?.enqueue(encoder.encode(segmentLine(0, 'first')));
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled());

    unmount();

    expect(capturedSignal?.aborted).toBe(true);
    expect(URL.revokeObjectURL).toHaveBeenCalled();
  });
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```text
npm --prefix frontend test -- --run src/components/MessageList.test.tsx
```

Expected:

```text
FAIL ... Expected 1 arguments, but got 3
```

or runtime failure because `play(..., { streaming: true })` is not implemented.

- [ ] **Step 3: Implement minimal streaming play support**

Modify imports in `frontend/src/hooks/useAudioPlaybackController.ts`:

```ts
import type { SpeechStreamEvent } from '../api/speechStream';
```

Add queue refs inside hook:

```ts
  const streamUrlsRef = useRef<Map<string, string[]>>(new Map());
```

Change `play` signature:

```ts
  const play = useCallback(async (messageId: string, text: string, playOptions: { streaming?: boolean } = {}): Promise<boolean> => {
    if (playOptions.streaming) return playStreaming(messageId, text);
```

Add helper callbacks before `play`:

```ts
  const rememberStreamUrl = useCallback((messageId: string, url: string) => {
    const urls = streamUrlsRef.current.get(messageId) ?? [];
    urls.push(url);
    streamUrlsRef.current.set(messageId, urls);
  }, []);

  const revokeStreamUrls = useCallback((messageId: string) => {
    const urls = streamUrlsRef.current.get(messageId) ?? [];
    for (const url of urls) URL.revokeObjectURL(url);
    streamUrlsRef.current.delete(messageId);
  }, []);
```

Add `playStreaming` before `play`:

```ts
  const playStreaming = useCallback(async (messageId: string, text: string): Promise<boolean> => {
    if (activeMessageIdRef.current && activeMessageIdRef.current !== messageId) stopActive();
    abortControllerRef.current?.abort();
    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    setActive(messageId);
    updateEntry(messageId, { state: 'synthesizing', error: null });
    revokeStreamUrls(messageId);

    let playedFirstSegment = false;
    try {
      for await (const event of apiClient.streamSpeech(text, { signal: abortController.signal }) as AsyncIterable<SpeechStreamEvent>) {
        if (abortController.signal.aborted || activeMessageIdRef.current !== messageId) return false;
        if (event.type === 'error') throw new Error(event.message);
        if (event.type !== 'segment') continue;
        const url = URL.createObjectURL(new Blob([event.audioBytes], { type: event.mediaType }));
        rememberStreamUrl(messageId, url);
        if (!playedFirstSegment) {
          playedFirstSegment = await playExisting(messageId, url);
          if (!playedFirstSegment) return false;
        }
      }
      if (!playedFirstSegment) throw new Error('语音流没有返回可播放音频。');
      updateEntry(messageId, { state: 'ready', error: null });
      return true;
    } catch (caught) {
      if (abortController.signal.aborted) return false;
      updateEntry(messageId, { state: 'error', error: errorMessage(caught) });
      setActive(null);
      return false;
    } finally {
      if (abortControllerRef.current === abortController) abortControllerRef.current = null;
    }
  }, [playExisting, rememberStreamUrl, revokeStreamUrls, setActive, stopActive, updateEntry]);
```

Update `reset` to revoke stream URLs:

```ts
    for (const urls of streamUrlsRef.current.values()) {
      for (const url of urls) URL.revokeObjectURL(url);
    }
    streamUrlsRef.current.clear();
```

- [ ] **Step 4: Run controller tests to verify GREEN**

Run:

```text
npm --prefix frontend test -- --run src/components/MessageList.test.tsx
```

Expected:

```text
passed
```

- [ ] **Step 5: Checkpoint**

If commit authorization is active:

```text
git add frontend/src/hooks/useAudioPlaybackController.ts frontend/src/components/MessageList.test.tsx
git commit -m "feat: play streamed tts segments"
```

---

## Task 5: Wire streaming into fake voice turn and E2E

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.tsx`
- Modify: `frontend/e2e/voice-turn.spec.ts`

- [ ] **Step 1: Write failing App test for streaming send-and-speak**

Add to `frontend/src/App.test.tsx`:

```ts
  it('send-and-speak uses streaming TTS and keeps one chat request', async () => {
    const user = userEvent.setup();
    URL.createObjectURL = vi.fn(() => 'blob:stream-segment');
    URL.revokeObjectURL = vi.fn();
    const playMock = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);

    class FakeMediaRecorder {
      static isTypeSupported() { return true; }
      state = 'inactive';
      mimeType = 'audio/webm';
      ondataavailable: ((event: BlobEvent) => void) | null = null;
      onstop: (() => void) | null = null;
      start() { this.state = 'recording'; }
      stop() {
        this.state = 'inactive';
        this.ondataavailable?.({ data: new Blob(['voice'], { type: 'audio/webm' }) } as BlobEvent);
        this.onstop?.();
      }
    }
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder);
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn(), addEventListener: vi.fn() }] }) },
    });

    const bytes = new TextEncoder().encode('RIFF....WAVEfirst');
    let binary = '';
    for (const byte of bytes) binary += String.fromCharCode(byte);
    const body = [
      '{"type":"start","provider":"fake","model":"fake-tone-v1"}\n',
      JSON.stringify({ type: 'segment', index: 0, audio_base64: btoa(binary), media_type: 'audio/wav', duration_ms: 100, sample_rate: 16000 }) + '\n',
      '{"type":"done","segment_count":1}\n',
    ].join('');

    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '' }]))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse({ text: '语音转写文本', detected_language: 'zh', duration_ms: 1000, provider: 'fake-asr', model: 'fake', inference_ms: 1 }))
      .mockResolvedValueOnce(jsonResponse({ reply: '语音回合回复', metadata: { provider: 'fake', model: 'test' } }))
      .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '3' }]))
      .mockResolvedValueOnce(jsonResponse([
        { id: 'u1', session_id: 's1', role: 'user', content: '语音转写文本', created_at: '1', metadata: {} },
        { id: 'a1', session_id: 's1', role: 'assistant', content: '语音回合回复', created_at: '2', metadata: {} },
      ]))
      .mockResolvedValueOnce(new Response(body, { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));

    render(<App />);
    await user.click(await screen.findByRole('button', { name: '开始录音' }));
    await new Promise((resolve) => setTimeout(resolve, 350));
    await user.click(await screen.findByRole('button', { name: '停止录音' }));
    await user.click(await screen.findByRole('button', { name: '发送并朗读' }));

    await waitFor(() => expect(playMock).toHaveBeenCalledTimes(1));
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input) === '/api/audio/speech/stream')).toBe(true);
    const chatCalls = vi.mocked(fetch).mock.calls.filter(([input, init]) => String(input) === '/api/sessions/s1/messages' && init?.method === 'POST');
    expect(chatCalls).toHaveLength(1);
  });
```

- [ ] **Step 2: Run App test to verify RED**

Run:

```text
npm --prefix frontend test -- --run src/App.test.tsx -t "send-and-speak uses streaming TTS"
```

Expected:

```text
FAIL ... expected /api/audio/speech/stream call
```

- [ ] **Step 3: Opt send-and-speak into streaming playback**

Modify `frontend/src/App.tsx` in `handleSendAndSpeakTranscript`:

```ts
      const played = await audioController.play(assistantMessage.id, assistantMessage.content, { streaming: true });
```

- [ ] **Step 4: Run App streaming test to verify GREEN**

Run:

```text
npm --prefix frontend test -- --run src/App.test.tsx -t "send-and-speak uses streaming TTS"
```

Expected:

```text
1 passed
```

- [ ] **Step 5: Update E2E route and assertions**

Modify `frontend/e2e/voice-turn.spec.ts`:

- Track `streamSpeechRequests` instead of `speechRequests` for `/api/audio/speech/stream`.
- Add route:

```ts
  let streamDoneObserved = false;
  await page.route('**/api/audio/speech/stream', async (route) => {
    const bytes = Buffer.from('RIFF....WAVEfirst', 'utf8');
    const body = [
      JSON.stringify({ type: 'start', provider: 'fake', model: 'fake-tone-v1' }) + '\n',
      JSON.stringify({ type: 'segment', index: 0, audio_base64: bytes.toString('base64'), media_type: 'audio/wav', duration_ms: 100, sample_rate: 16000 }) + '\n',
      JSON.stringify({ type: 'done', segment_count: 1 }) + '\n',
    ].join('');
    streamDoneObserved = true;
    await route.fulfill({ status: 200, contentType: 'application/x-ndjson', body });
  });
```

- Assert:

```ts
  await expect.poll(() => streamSpeechRequests.length).toBe(1);
  expect(chatPostRequests).toHaveLength(1);
  expect(streamDoneObserved).toBe(true);
```

- [ ] **Step 6: Run E2E test**

Run:

```text
npm --prefix frontend run test:e2e -- voice-turn.spec.ts
```

Expected:

```text
1 passed
```

- [ ] **Step 7: Checkpoint**

If commit authorization is active:

```text
git add frontend/src/App.tsx frontend/src/App.test.tsx frontend/e2e/voice-turn.spec.ts
git commit -m "feat: use streaming tts for voice turns"
```

---

## Task 6: Extend fake latency measurement for streaming TTS

**Files:**
- Modify: `frontend/scripts/measure-voice-turn-latency.mjs`
- Optional test if existing script test coverage is present: `frontend/.claude-audio-stats.test.mjs`

- [ ] **Step 1: Update fake stream route in measurement script**

Replace the `/api/audio/speech` route with `/api/audio/speech/stream` and add timestamps:

```js
let streamDoneAt = null;
await page.route('**/api/audio/speech/stream', async (route) => {
  const entry = tracker.begin('stream-tts');
  const bytes = Buffer.from('RIFF....WAVEfirst', 'utf8');
  const body = [
    JSON.stringify({ type: 'start', provider: 'fake', model: 'fake-tone-v1' }) + '\n',
    JSON.stringify({ type: 'segment', index: 0, audio_base64: bytes.toString('base64'), media_type: 'audio/wav', duration_ms: 100, sample_rate: 16000 }) + '\n',
    JSON.stringify({ type: 'done', segment_count: 1 }) + '\n',
  ].join('');
  await route.fulfill({ status: 200, contentType: 'application/x-ndjson', body });
  streamDoneAt = now();
  tracker.end(entry);
});
```

Update run object fields:

```js
const streamTtsEntry = tracker.requests.filter((request) => request.kind === 'stream-tts')[beforeTts];
streamTtsRequestMs: streamTtsEntry?.end === null || streamTtsEntry?.end === undefined ? null : round(streamTtsEntry.end - streamTtsEntry.start),
streamSendToFirstPlaybackMs: round(playbackTriggered - sendClick),
streamDoneMs: streamDoneAt === null ? null : round(streamDoneAt - sendClick),
streamSegmentCount: 1,
```

- [ ] **Step 2: Run measurement script against not-running app failure path**

Run:

```text
npm --prefix frontend run measure:voice-turn
```

Expected when app is not running:

```text
Frontend is not reachable
```

Exit code should be non-zero. This verifies failure path still works.

- [ ] **Step 3: Leave full measurement execution for final validation**

Full measurement requires local fake backend/frontend. Do not claim measurement PASS until Task 8 runs it or records why it was skipped.

---

## Task 7: Full validation

**Files:**
- No code changes expected.

- [ ] **Step 1: Run backend tests**

Run:

```text
python -m pytest backend/tests -v
```

Expected:

```text
passed
```

- [ ] **Step 2: Run frontend unit tests**

Run:

```text
npm --prefix frontend test -- --run
```

Expected:

```text
passed
```

- [ ] **Step 3: Run typecheck**

Run:

```text
npm --prefix frontend run typecheck
```

Expected: exits 0 with no TypeScript errors.

- [ ] **Step 4: Run build**

Run:

```text
npm --prefix frontend run build
```

Expected: exits 0 and prints `built in`.

- [ ] **Step 5: Run E2E**

Run:

```text
npm --prefix frontend run test:e2e
```

Expected:

```text
passed
```

- [ ] **Step 6: Capture exact counts**

Record exact pass counts and any targeted command counts for Task 8 evidence.

---

## Task 8: Document Stage 2F-3 evidence and update status

**Files:**
- Create: `docs/stage2f3-streaming-tts-first-slice.md`
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: Write evidence document**

Create `docs/stage2f3-streaming-tts-first-slice.md`:

```md
# Stage 2F-3 Streaming TTS First Vertical Slice Evidence

Status: COMPLETED on 2026-06-29.

## Scope

This slice adds a fake-provider streaming TTS path using `POST /api/audio/speech/stream` and NDJSON events with standalone WAV segments. The browser can begin assistant speech playback from the first streamed segment before the stream completes.

It preserves the existing non-streaming `/api/audio/speech` path.

It does not implement streaming ASR, real-provider streaming, WebSocket voice turns, long-term memory, or emotion behavior.

## Implemented behavior

- Backend fake TTS can yield ordered standalone WAV segments.
- Streaming speech endpoint emits `start`, ordered `segment`, and `done` NDJSON events.
- Frontend parses chunked NDJSON from `ReadableStream`.
- Voice-turn TTS playback can use the streaming path.
- Streaming playback applies existing output-device routing.
- Stop/reset/interruption aborts stale streaming requests and cleans up segment Blob URLs.

## Validation

After running validation, include one row per command with the exact observed result. Use this format:

| Command | Result |
|---|---|
| `python -m pytest backend/tests/test_tts_streaming.py -v` | PASS — 3 passed |

Required commands to record:

- `python -m pytest backend/tests/test_tts_streaming.py -v`
- `python -m pytest backend/tests/test_api_audio_streaming.py -v`
- `npm --prefix frontend test -- --run src/api/speechStream.test.ts`
- `npm --prefix frontend test -- --run src/components/MessageList.test.tsx`
- `npm --prefix frontend test -- --run src/App.test.tsx`
- `npm --prefix frontend run test:e2e -- voice-turn.spec.ts`
- `python -m pytest backend/tests -v`
- `npm --prefix frontend test -- --run`
- `npm --prefix frontend run typecheck`
- `npm --prefix frontend run build`
- `npm --prefix frontend run test:e2e`

## Limitations

- Segments are independent WAV files; this is not final seamless audio streaming.
- Real CosyVoice streaming is not implemented in this slice.
- Streaming ASR, long-term memory, and emotion state remain unimplemented.
```

- [ ] **Step 2: Fill the validation table with observed outputs**

Use the exact outputs from Task 7. Every validation row in the evidence document must include the observed pass count or build result. Example:

```md
| `python -m pytest backend/tests/test_tts_streaming.py -v` | PASS — 3 passed |
| `npm --prefix frontend run build` | PASS — built in 240 ms |
```

- [ ] **Step 3: Update `CLAUDE.md` only after validation passes**

Add `2F-3 Streaming TTS First Vertical Slice COMPLETED` to the top current-stage line and Stage 2 table. Add a Stage 2 completed bullet:

```md
- 子任务 2F-3：Streaming TTS first vertical slice 已完成（2026-06-29；新增 fake-provider `POST /api/audio/speech/stream` NDJSON 分段 WAV 流式 TTS 路径；前端可在首个 segment 到达后开始 assistant 音频播放；保留既有非流式 `/api/audio/speech`；stream stop/reset/interruption 会 abort stale stream 并清理 Blob URL；自动化验证 PASS；证据记录于 `docs/stage2f3-streaming-tts-first-slice.md`）。未实现流式 ASR、真实 CosyVoice streaming、长期记忆或情感系统。
```

- [ ] **Step 4: Update README**

Add a concise Stage 2F-3 section after 2F-2:

```md
### Stage 2F-3 streaming TTS first vertical slice

The fake-provider browser voice-turn path now supports a streaming TTS endpoint that emits NDJSON events with standalone WAV segments. The browser can begin playback from the first segment before the stream completes. Existing non-streaming TTS remains available.

This is not real-provider streaming, streaming ASR, long-term memory, or emotion behavior.
```

- [ ] **Step 5: Sanity check docs**

Run:

```text
git diff -- docs/stage2f3-streaming-tts-first-slice.md CLAUDE.md README.md
```

Expected:

- No placeholders remain.
- No claim that real-provider streaming, streaming ASR, memory, or emotion is complete.

---

## Self-review notes

Spec coverage:

- Separate streaming endpoint and NDJSON protocol: Tasks 1-2.
- Frontend parser with chunked `ReadableStream`: Task 3.
- Playback queue, first segment playback, cleanup, output routing: Task 4.
- Voice-turn integration and fake E2E: Task 5.
- Measurement updates: Task 6.
- Full validation and evidence docs: Tasks 7-8.

Placeholder scan:

- The plan includes template text in Task 8 that explicitly must be replaced during implementation. This is acceptable only because Task 8 Step 2 requires removing those phrases before completion. No implementation code step contains placeholder instructions.

Type consistency:

- Backend names: `SpeechSynthesisSegment`, `StreamingTTSProvider`, `synthesize_stream`.
- Frontend names: `SpeechStreamEvent`, `streamSpeech`, `play(..., { streaming: true })`.
- Endpoint name: `/api/audio/speech/stream`.
