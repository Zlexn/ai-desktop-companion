# Stage 2G-2 Real FasterWhisper Streaming ASR Feasibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicitly opt-in real FasterWhisper streaming-ASR feasibility path that emits partial/final NDJSON events through the existing `/api/audio/transcriptions/stream` contract.

**Architecture:** Keep the stable batch `/api/audio/transcriptions` endpoint and fake streaming ASR path unchanged. Add conservative FasterWhisper streaming settings, then implement `FasterWhisperASRProvider.transcribe_stream(...)` as a cumulative-window feasibility layer that repeatedly decodes accumulated ordered chunks and emits changed partial text before a final full decode. Validate with mocked FasterWhisper tests first, then record a local real-provider smoke.

**Tech Stack:** Python 3.11+/3.12, FastAPI `StreamingResponse`, pytest/pytest-asyncio, faster-whisper/CTranslate2, existing ASR provider/service abstractions, NDJSON, PowerShell local smoke scripts.

---

## Scope guard

Implement only `docs/superpowers/specs/2026-07-01-stage-2g2-real-fasterwhisper-streaming-asr-feasibility-design.md`.

Do not implement WebSockets, always-on listening, wake word, automatic spoken barge-in, LLM streaming, final seamless low-gap audio playback, long-term memory, or emotion state.

Because this repository already has many uncommitted changes and no explicit commit authorization in this turn, every task ends with a checkpoint instead of a commit.

---

## File structure

Create:

- `backend/tests/test_faster_whisper_streaming_asr_provider.py`
  - Unit tests for opt-in FasterWhisper streaming feasibility behavior with a mocked `WhisperModel`.

- `backend/tests/test_api_audio_transcriptions_streaming_faster_whisper.py`
  - API tests for disabled/enabled real-provider streaming behavior using mocked provider/factory paths.

- `scripts/smoke_faster_whisper_streaming_asr.py`
  - Local real-provider smoke script that posts ordered chunks to `/api/audio/transcriptions/stream` and records first partial/final timing.

- `docs/stage2g2-real-fasterwhisper-streaming-asr-feasibility.md`
  - Evidence document after validation.

Modify:

- `backend/app/core/config.py`
  - Add explicit FasterWhisper streaming feasibility settings and redacted config output.

- `backend/app/asr/factory.py`
  - Pass the new streaming settings into `FasterWhisperASRProvider`.

- `backend/app/asr/faster_whisper_provider.py`
  - Add opt-in `transcribe_stream(...)`, helper methods for cumulative-window decode, duplicate partial suppression, and temporary-file cleanup.

- `backend/tests/test_asr_factory.py`
  - Assert the factory propagates the new streaming settings.

- `backend/tests/test_api_audio_transcriptions_streaming.py`
  - Keep fake streaming regression intact; update only if helper names conflict.

- `.env.example`
  - Document new opt-in streaming settings with safe defaults.

- `README.md`, `CLAUDE.md`
  - Update only after real smoke validation passes.

---

## Task 1: Add explicit FasterWhisper streaming settings

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/tests/test_config.py` if present; otherwise create or extend nearest existing config tests.
- Modify: `.env.example`

- [ ] **Step 1: Locate config tests**

Run:

```powershell
Get-ChildItem backend/tests -Filter '*config*'
```

Expected:

```text
A config test file path, or no output if the project has no dedicated config tests.
```

If no dedicated config test exists, create `backend/tests/test_config.py` in Step 2.

- [ ] **Step 2: Write failing config tests**

Create or update `backend/tests/test_config.py` with these tests:

```py
from __future__ import annotations

import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_faster_whisper_streaming_settings_default_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ASR_FASTER_WHISPER_STREAMING_ENABLED", raising=False)
    monkeypatch.delenv("ASR_FASTER_WHISPER_STREAMING_WINDOW_MS", raising=False)
    monkeypatch.delenv("ASR_FASTER_WHISPER_STREAMING_STEP_MS", raising=False)
    monkeypatch.delenv("ASR_FASTER_WHISPER_STREAMING_MIN_PARTIAL_CHARS", raising=False)
    monkeypatch.delenv("ASR_FASTER_WHISPER_STREAMING_MAX_PARTIALS", raising=False)

    settings = get_settings()

    assert settings.asr_faster_whisper_streaming_enabled is False
    assert settings.asr_faster_whisper_streaming_window_ms == 3000
    assert settings.asr_faster_whisper_streaming_step_ms == 1000
    assert settings.asr_faster_whisper_streaming_min_partial_chars == 1
    assert settings.asr_faster_whisper_streaming_max_partials == 8


def test_faster_whisper_streaming_settings_parse_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASR_FASTER_WHISPER_STREAMING_ENABLED", "true")
    monkeypatch.setenv("ASR_FASTER_WHISPER_STREAMING_WINDOW_MS", "2500")
    monkeypatch.setenv("ASR_FASTER_WHISPER_STREAMING_STEP_MS", "500")
    monkeypatch.setenv("ASR_FASTER_WHISPER_STREAMING_MIN_PARTIAL_CHARS", "2")
    monkeypatch.setenv("ASR_FASTER_WHISPER_STREAMING_MAX_PARTIALS", "3")

    settings = get_settings()

    assert settings.asr_faster_whisper_streaming_enabled is True
    assert settings.asr_faster_whisper_streaming_window_ms == 2500
    assert settings.asr_faster_whisper_streaming_step_ms == 500
    assert settings.asr_faster_whisper_streaming_min_partial_chars == 2
    assert settings.asr_faster_whisper_streaming_max_partials == 3


def test_faster_whisper_streaming_window_must_be_at_least_step(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASR_FASTER_WHISPER_STREAMING_WINDOW_MS", "500")
    monkeypatch.setenv("ASR_FASTER_WHISPER_STREAMING_STEP_MS", "1000")

    with pytest.raises(ValueError, match="ASR_FASTER_WHISPER_STREAMING_WINDOW_MS must be greater than or equal to ASR_FASTER_WHISPER_STREAMING_STEP_MS"):
        get_settings()
```

- [ ] **Step 3: Run config tests to verify RED**

Run:

```powershell
python -m pytest backend/tests/test_config.py -v
```

Expected:

```text
FAILED with AttributeError: 'Settings' object has no attribute 'asr_faster_whisper_streaming_enabled'
```

- [ ] **Step 4: Add settings fields**

Modify `backend/app/core/config.py` `Settings` dataclass by adding fields after `asr_faster_whisper_timeout_seconds`:

```py
    asr_faster_whisper_streaming_enabled: bool = False
    asr_faster_whisper_streaming_window_ms: int = 3000
    asr_faster_whisper_streaming_step_ms: int = 1000
    asr_faster_whisper_streaming_min_partial_chars: int = 1
    asr_faster_whisper_streaming_max_partials: int = 8
```

- [ ] **Step 5: Add redacted settings output**

Modify `Settings.redacted()` in `backend/app/core/config.py` by adding:

```py
            "asr_faster_whisper_streaming_enabled": self.asr_faster_whisper_streaming_enabled,
            "asr_faster_whisper_streaming_window_ms": self.asr_faster_whisper_streaming_window_ms,
            "asr_faster_whisper_streaming_step_ms": self.asr_faster_whisper_streaming_step_ms,
            "asr_faster_whisper_streaming_min_partial_chars": self.asr_faster_whisper_streaming_min_partial_chars,
            "asr_faster_whisper_streaming_max_partials": self.asr_faster_whisper_streaming_max_partials,
```

- [ ] **Step 6: Parse and validate environment values**

In `load_settings()` after `asr_faster_whisper_timeout_seconds`, add:

```py
    asr_faster_whisper_streaming_enabled = _get_bool_env("ASR_FASTER_WHISPER_STREAMING_ENABLED", False)
    asr_faster_whisper_streaming_window_ms = _get_positive_int_env("ASR_FASTER_WHISPER_STREAMING_WINDOW_MS", 3000)
    asr_faster_whisper_streaming_step_ms = _get_positive_int_env("ASR_FASTER_WHISPER_STREAMING_STEP_MS", 1000)
    asr_faster_whisper_streaming_min_partial_chars = _get_positive_int_env("ASR_FASTER_WHISPER_STREAMING_MIN_PARTIAL_CHARS", 1)
    asr_faster_whisper_streaming_max_partials = _get_positive_int_env("ASR_FASTER_WHISPER_STREAMING_MAX_PARTIALS", 8)
    if asr_faster_whisper_streaming_window_ms < asr_faster_whisper_streaming_step_ms:
        raise ValueError("ASR_FASTER_WHISPER_STREAMING_WINDOW_MS must be greater than or equal to ASR_FASTER_WHISPER_STREAMING_STEP_MS")
```

In the `return Settings(...)` call, add:

```py
        asr_faster_whisper_streaming_enabled=asr_faster_whisper_streaming_enabled,
        asr_faster_whisper_streaming_window_ms=asr_faster_whisper_streaming_window_ms,
        asr_faster_whisper_streaming_step_ms=asr_faster_whisper_streaming_step_ms,
        asr_faster_whisper_streaming_min_partial_chars=asr_faster_whisper_streaming_min_partial_chars,
        asr_faster_whisper_streaming_max_partials=asr_faster_whisper_streaming_max_partials,
```

- [ ] **Step 7: Document env vars**

Modify `.env.example` after `ASR_FASTER_WHISPER_TIMEOUT_SECONDS=30`:

```text
# Optional Stage 2G-2 real FasterWhisper streaming feasibility. Disabled by default.
# This repeatedly decodes cumulative audio windows and is not final production-grade streaming ASR.
ASR_FASTER_WHISPER_STREAMING_ENABLED=false
ASR_FASTER_WHISPER_STREAMING_WINDOW_MS=3000
ASR_FASTER_WHISPER_STREAMING_STEP_MS=1000
ASR_FASTER_WHISPER_STREAMING_MIN_PARTIAL_CHARS=1
ASR_FASTER_WHISPER_STREAMING_MAX_PARTIALS=8
```

- [ ] **Step 8: Run config tests to verify GREEN**

Run:

```powershell
python -m pytest backend/tests/test_config.py -v
```

Expected:

```text
3 passed
```

- [ ] **Step 9: Checkpoint**

Run:

```powershell
git status --short
```

Do not commit unless explicitly authorized.

---

## Task 2: Propagate settings through ASR factory

**Files:**
- Modify: `backend/app/asr/factory.py`
- Modify: `backend/tests/test_asr_factory.py`

- [ ] **Step 1: Write failing factory propagation assertion**

In `backend/tests/test_asr_factory.py`, update the faster-whisper factory test to assert the provider receives streaming settings. If no such test exposes provider attributes, add this test:

```py
def test_faster_whisper_factory_passes_streaming_settings(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ASR_PROVIDER", "faster-whisper")
    monkeypatch.setenv("ASR_FASTER_WHISPER_MODEL_PATH", str(tmp_path))
    monkeypatch.setenv("ASR_FASTER_WHISPER_STREAMING_ENABLED", "true")
    monkeypatch.setenv("ASR_FASTER_WHISPER_STREAMING_WINDOW_MS", "2500")
    monkeypatch.setenv("ASR_FASTER_WHISPER_STREAMING_STEP_MS", "500")
    monkeypatch.setenv("ASR_FASTER_WHISPER_STREAMING_MIN_PARTIAL_CHARS", "2")
    monkeypatch.setenv("ASR_FASTER_WHISPER_STREAMING_MAX_PARTIALS", "3")
    from app.core.config import get_settings
    from app.asr.factory import create_asr_provider

    get_settings.cache_clear()
    provider = create_asr_provider(get_settings())
    get_settings.cache_clear()

    assert provider.streaming_enabled is True
    assert provider.streaming_window_ms == 2500
    assert provider.streaming_step_ms == 500
    assert provider.streaming_min_partial_chars == 2
    assert provider.streaming_max_partials == 3
```

- [ ] **Step 2: Run factory test to verify RED**

Run:

```powershell
python -m pytest backend/tests/test_asr_factory.py::test_faster_whisper_factory_passes_streaming_settings -v
```

Expected:

```text
FAILED with AttributeError for streaming_enabled or constructor TypeError
```

- [ ] **Step 3: Extend provider constructor**

Modify `backend/app/asr/faster_whisper_provider.py` `__init__` signature to include:

```py
        streaming_enabled: bool = False,
        streaming_window_ms: int = 3000,
        streaming_step_ms: int = 1000,
        streaming_min_partial_chars: int = 1,
        streaming_max_partials: int = 8,
```

Inside `__init__`, add:

```py
        self.streaming_enabled = streaming_enabled
        self.streaming_window_ms = streaming_window_ms
        self.streaming_step_ms = streaming_step_ms
        self.streaming_min_partial_chars = streaming_min_partial_chars
        self.streaming_max_partials = streaming_max_partials
```

- [ ] **Step 4: Pass settings in factory**

Modify `backend/app/asr/factory.py` where `FasterWhisperASRProvider(...)` is constructed:

```py
            streaming_enabled=settings.asr_faster_whisper_streaming_enabled,
            streaming_window_ms=settings.asr_faster_whisper_streaming_window_ms,
            streaming_step_ms=settings.asr_faster_whisper_streaming_step_ms,
            streaming_min_partial_chars=settings.asr_faster_whisper_streaming_min_partial_chars,
            streaming_max_partials=settings.asr_faster_whisper_streaming_max_partials,
```

- [ ] **Step 5: Run factory test to verify GREEN**

Run:

```powershell
python -m pytest backend/tests/test_asr_factory.py::test_faster_whisper_factory_passes_streaming_settings -v
```

Expected:

```text
1 passed
```

- [ ] **Step 6: Checkpoint**

Run:

```powershell
git status --short
```

Do not commit unless explicitly authorized.

---

## Task 3: Add FasterWhisper streaming provider unit tests

**Files:**
- Create: `backend/tests/test_faster_whisper_streaming_asr_provider.py`
- Modify: `backend/app/asr/faster_whisper_provider.py`

- [ ] **Step 1: Write failing streaming provider tests**

Create `backend/tests/test_faster_whisper_streaming_asr_provider.py`:

```py
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

from app.asr.base import TranscriptionFinalEvent, TranscriptionPartialEvent
from app.asr.faster_whisper_provider import FasterWhisperASRProvider
from app.core.errors import ASRUnavailableError


class _Info:
    language = "zh"
    duration = 1.0


class _Segment:
    def __init__(self, text: str) -> None:
        self.text = text
        self.start = 0.0
        self.end = 1.0


class _StreamingFakeWhisperModel:
    calls: list[dict[str, object]] = []
    texts = [" 你", " 你好", " 你好世界"]

    def __init__(self, model_path: str, *, device: str, compute_type: str, local_files_only: bool) -> None:
        self.model_path = model_path
        _StreamingFakeWhisperModel.calls.append({"model_path": model_path, "device": device, "compute_type": compute_type, "local_files_only": local_files_only})

    def transcribe(self, audio_path: str, *, language: str | None, beam_size: int):
        assert Path(audio_path).is_file()
        index = min(len([call for call in _StreamingFakeWhisperModel.calls if "audio_path" in call]), len(self.texts) - 1)
        text = self.texts[index]
        _StreamingFakeWhisperModel.calls.append({"audio_path": audio_path, "language": language, "beam_size": beam_size, "text": text})
        return [_Segment(text)], _Info()


@pytest.fixture(autouse=True)
def reset_fake_model() -> None:
    _StreamingFakeWhisperModel.calls.clear()
    _StreamingFakeWhisperModel.texts = [" 你", " 你好", " 你好世界"]


@pytest.fixture
def fake_faster_whisper(monkeypatch: pytest.MonkeyPatch):
    module = types.SimpleNamespace(WhisperModel=_StreamingFakeWhisperModel)
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    return module


def make_provider(tmp_path: Path, *, streaming_enabled: bool = True, max_partials: int = 8) -> FasterWhisperASRProvider:
    return FasterWhisperASRProvider(
        model_path=str(tmp_path),
        model_name="medium",
        model_revision="08e178d48790749d25932bbc082711ddcfdfbc4f",
        device="cuda",
        compute_type="float16",
        beam_size=1,
        timeout_seconds=10,
        streaming_enabled=streaming_enabled,
        streaming_window_ms=3000,
        streaming_step_ms=1000,
        streaming_min_partial_chars=1,
        streaming_max_partials=max_partials,
    )


@pytest.mark.asyncio
async def test_faster_whisper_streaming_disabled_is_unavailable(tmp_path: Path, fake_faster_whisper) -> None:
    provider = make_provider(tmp_path, streaming_enabled=False)

    with pytest.raises(ASRUnavailableError, match="当前 FasterWhisper ASR Provider 未启用流式转写"):
        _ = [event async for event in provider.transcribe_stream([b"chunk-1"], "audio/webm", "zh")]


@pytest.mark.asyncio
async def test_faster_whisper_streaming_emits_changed_partials_and_final(tmp_path: Path, fake_faster_whisper) -> None:
    provider = make_provider(tmp_path)

    events = [event async for event in provider.transcribe_stream([b"chunk-1", b"chunk-2"], "audio/webm", "zh")]

    assert [event.type for event in events] == ["partial", "partial", "final"]
    assert isinstance(events[0], TranscriptionPartialEvent)
    assert events[0].text == "你"
    assert events[0].index == 0
    assert events[0].is_final is False
    assert isinstance(events[1], TranscriptionPartialEvent)
    assert events[1].text == "你好"
    assert events[1].index == 1
    assert isinstance(events[2], TranscriptionFinalEvent)
    assert events[2].result.text == "你好世界"
    transcribe_calls = [call for call in _StreamingFakeWhisperModel.calls if "audio_path" in call]
    assert len(transcribe_calls) == 3
    for call in transcribe_calls:
        assert not Path(str(call["audio_path"])).exists()


@pytest.mark.asyncio
async def test_faster_whisper_streaming_suppresses_duplicate_partials(tmp_path: Path, fake_faster_whisper) -> None:
    _StreamingFakeWhisperModel.texts = [" 重复", " 重复", " 重复完成"]
    provider = make_provider(tmp_path)

    events = [event async for event in provider.transcribe_stream([b"chunk-1", b"chunk-2"], "audio/webm", "zh")]

    partials = [event for event in events if isinstance(event, TranscriptionPartialEvent)]
    assert [event.text for event in partials] == ["重复"]
    assert isinstance(events[-1], TranscriptionFinalEvent)
    assert events[-1].result.text == "重复完成"


@pytest.mark.asyncio
async def test_faster_whisper_streaming_respects_max_partials(tmp_path: Path, fake_faster_whisper) -> None:
    provider = make_provider(tmp_path, max_partials=1)

    events = [event async for event in provider.transcribe_stream([b"chunk-1", b"chunk-2", b"chunk-3"], "audio/webm", "zh")]

    partials = [event for event in events if isinstance(event, TranscriptionPartialEvent)]
    assert len(partials) == 1
    assert isinstance(events[-1], TranscriptionFinalEvent)
```

- [ ] **Step 2: Run new provider tests to verify RED**

Run:

```powershell
python -m pytest backend/tests/test_faster_whisper_streaming_asr_provider.py -v
```

Expected:

```text
FAILED with AttributeError: 'FasterWhisperASRProvider' object has no attribute 'transcribe_stream'
```

- [ ] **Step 3: Add streaming imports**

Modify `backend/app/asr/faster_whisper_provider.py` imports:

```py
from collections.abc import AsyncIterator, Iterable
from app.asr.base import ASRProvider, TranscriptionFinalEvent, TranscriptionPartialEvent, TranscriptionResult, TranscriptionSegment, TranscriptionStreamEvent
```

Keep existing imports that are still used.

- [ ] **Step 4: Add `transcribe_stream` implementation**

Add this method to `FasterWhisperASRProvider`:

```py
    async def transcribe_stream(
        self,
        audio_chunks: Iterable[bytes],
        media_type: str,
        language: str | None = None,
    ) -> AsyncIterator[TranscriptionStreamEvent]:
        if not self.streaming_enabled:
            raise ASRUnavailableError("当前 FasterWhisper ASR Provider 未启用流式转写。")

        chunks = [chunk for chunk in audio_chunks if chunk]
        if not chunks:
            raise ASRUnavailableError("流式转写没有收到可用音频。")

        emitted_text = ""
        partial_index = 0
        accumulated: list[bytes] = []

        for chunk in chunks:
            accumulated.append(chunk)
            if partial_index >= self.streaming_max_partials:
                continue
            partial_result = await asyncio.wait_for(
                asyncio.to_thread(self._transcribe_sync, b"".join(accumulated), media_type, language),
                timeout=self.timeout_seconds,
            )
            partial_text = partial_result.text.strip()
            if len(partial_text) < self.streaming_min_partial_chars or partial_text == emitted_text:
                continue
            emitted_text = partial_text
            yield TranscriptionPartialEvent(
                type="partial",
                index=partial_index,
                text=partial_text,
                is_final=False,
                audio_ms=None,
            )
            partial_index += 1

        final_result = await asyncio.wait_for(
            asyncio.to_thread(self._transcribe_sync, b"".join(chunks), media_type, language),
            timeout=self.timeout_seconds,
        )
        yield TranscriptionFinalEvent(type="final", result=final_result)
```

This intentionally uses cumulative chunks for feasibility and relies on `_transcribe_sync(...)` for temporary-file cleanup.

- [ ] **Step 5: Map timeout/unavailable errors consistently**

Wrap the body of `transcribe_stream(...)` in the same exception mapping style as `transcribe(...)`:

```py
        try:
            # existing generator logic
        except TimeoutError as exc:
            raise ASRTimeoutError() from exc
        except ASRTimeoutError:
            raise
        except ASRUnavailableError:
            raise
        except Exception as exc:
            raise ASRUnavailableError() from exc
```

Because this is an async generator, put the `try` inside the method around the loop and final decode.

- [ ] **Step 6: Run provider streaming tests to verify GREEN**

Run:

```powershell
python -m pytest backend/tests/test_faster_whisper_streaming_asr_provider.py -v
```

Expected:

```text
4 passed
```

- [ ] **Step 7: Run existing provider tests**

Run:

```powershell
python -m pytest backend/tests/test_faster_whisper_asr_provider.py -v
```

Expected:

```text
Existing tests pass
```

- [ ] **Step 8: Checkpoint**

Run:

```powershell
git status --short
```

Do not commit unless explicitly authorized.

---

## Task 4: Add API tests for FasterWhisper streaming path

**Files:**
- Create: `backend/tests/test_api_audio_transcriptions_streaming_faster_whisper.py`
- Modify: `backend/app/api/routes/audio.py` only if provider metadata is wrong for partial-start events.

- [ ] **Step 1: Write failing API tests**

Create `backend/tests/test_api_audio_transcriptions_streaming_faster_whisper.py`:

```py
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


def parse_ndjson(body: bytes) -> list[dict[str, object]]:
    return [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]


def test_faster_whisper_streaming_disabled_returns_clear_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'disabled.db'}")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("ASR_PROVIDER", "faster-whisper")
    monkeypatch.setenv("ASR_FASTER_WHISPER_MODEL_PATH", str(tmp_path))
    monkeypatch.setenv("ASR_FASTER_WHISPER_STREAMING_ENABLED", "false")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/audio/transcriptions/stream",
            files=[("chunks", ("chunk.webm", b"\x1a\x45\xdf\xa3chunk", "audio/webm"))],
            data={"language": "zh"},
        )

    get_settings.cache_clear()
    assert response.status_code in {503, 504}
    assert "流式" in response.text or "stream" in response.text.lower()


def test_faster_whisper_streaming_enabled_returns_partial_final_done(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'enabled.db'}")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("ASR_PROVIDER", "faster-whisper")
    monkeypatch.setenv("ASR_FASTER_WHISPER_MODEL_PATH", str(tmp_path))
    monkeypatch.setenv("ASR_FASTER_WHISPER_STREAMING_ENABLED", "true")
    get_settings.cache_clear()

    from app.asr.base import TranscriptionFinalEvent, TranscriptionPartialEvent, TranscriptionResult
    from app.asr.faster_whisper_provider import FasterWhisperASRProvider

    async def fake_stream(self, audio_chunks, media_type, language=None):
        yield TranscriptionPartialEvent(type="partial", index=0, text="真实", is_final=False, audio_ms=1000)
        yield TranscriptionFinalEvent(
            type="final",
            result=TranscriptionResult(
                text="真实转写",
                detected_language="zh",
                duration_ms=1200,
                provider="faster-whisper",
                model="medium@test",
                inference_ms=123,
            ),
        )

    monkeypatch.setattr(FasterWhisperASRProvider, "transcribe_stream", fake_stream)

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/audio/transcriptions/stream",
            files=[("chunks", ("chunk.webm", b"\x1a\x45\xdf\xa3chunk", "audio/webm"))],
            data={"language": "zh"},
        )

    get_settings.cache_clear()
    assert response.status_code == 200
    events = parse_ndjson(response.content)
    assert events[0] == {"type": "start", "provider": "faster-whisper", "model": "medium@test"}
    assert events[1] == {"type": "partial", "index": 0, "text": "真实", "is_final": False, "audio_ms": 1000}
    assert events[2]["type"] == "final"
    assert events[2]["text"] == "真实转写"
    assert events[-1] == {"type": "done"}
```

- [ ] **Step 2: Run API tests to verify RED if metadata is currently wrong**

Run:

```powershell
python -m pytest backend/tests/test_api_audio_transcriptions_streaming_faster_whisper.py -v
```

Expected before route metadata fix:

```text
The enabled test may fail because partial-start metadata is hardcoded as fake/fake-asr-v1.
```

- [ ] **Step 3: Fix start metadata if needed**

If the enabled API test fails because `_transcription_stream_events(...)` emits fake metadata before a partial, update `backend/app/asr/base.py` `TranscriptionPartialEvent` to carry optional provider/model:

```py
@dataclass(frozen=True)
class TranscriptionPartialEvent:
    type: Literal["partial"]
    index: int
    text: str
    is_final: bool
    audio_ms: int | None = None
    provider: str | None = None
    model: str | None = None
```

Update fake provider partial construction to include:

```py
provider=self.provider_name,
model=self._model,
```

Update FasterWhisper partial construction to include:

```py
provider=self.provider_name,
model=self.public_model_name,
```

Update `backend/app/api/routes/audio.py` partial start block:

```py
                yield _ndjson_event({
                    "type": "start",
                    "provider": event.provider or "unknown",
                    "model": event.model or "unknown",
                })
```

- [ ] **Step 4: Run API tests to verify GREEN**

Run:

```powershell
python -m pytest backend/tests/test_api_audio_transcriptions_streaming.py backend/tests/test_api_audio_transcriptions_streaming_faster_whisper.py -v
```

Expected:

```text
All streaming transcription API tests pass
```

- [ ] **Step 5: Checkpoint**

Run:

```powershell
git status --short
```

Do not commit unless explicitly authorized.

---

## Task 5: Add local real-provider smoke script

**Files:**
- Create: `scripts/smoke_faster_whisper_streaming_asr.py`

- [ ] **Step 1: Write smoke script**

Create `scripts/smoke_faster_whisper_streaming_asr.py`:

```py
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test FasterWhisper streaming ASR endpoint.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/audio/transcriptions/stream")
    parser.add_argument("--audio", required=True)
    parser.add_argument("--language", default="zh")
    parser.add_argument("--chunk-bytes", type=int, default=256_000)
    return parser.parse_args()


def chunks(data: bytes, size: int) -> list[bytes]:
    return [data[index:index + size] for index in range(0, len(data), size) if data[index:index + size]]


def main() -> int:
    args = parse_args()
    audio_path = Path(args.audio)
    data = audio_path.read_bytes()
    audio_chunks = chunks(data, args.chunk_bytes)
    files = [
        ("chunks", (f"chunk-{index}.m4a", chunk, "audio/mp4"))
        for index, chunk in enumerate(audio_chunks)
    ]
    started = time.perf_counter()
    first_partial_ms: int | None = None
    final_ms: int | None = None
    events: list[dict[str, object]] = []

    with requests.post(args.url, files=files, data={"language": args.language}, stream=True, timeout=120) as response:
        print(f"HTTP {response.status_code} {response.headers.get('content-type', '')}")
        response.raise_for_status()
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            event = json.loads(raw_line)
            event["elapsed_ms"] = elapsed_ms
            events.append(event)
            if event.get("type") == "partial" and first_partial_ms is None:
                first_partial_ms = elapsed_ms
            if event.get("type") == "final" and final_ms is None:
                final_ms = elapsed_ms
            print(json.dumps(event, ensure_ascii=False))

    partials = [event for event in events if event.get("type") == "partial"]
    finals = [event for event in events if event.get("type") == "final"]
    summary = {
        "audio": str(audio_path),
        "chunk_count": len(audio_chunks),
        "chunk_bytes": args.chunk_bytes,
        "partial_count": len(partials),
        "first_partial_ms": first_partial_ms,
        "final_ms": final_ms,
        "final_text": finals[-1].get("text") if finals else None,
    }
    print("SUMMARY " + json.dumps(summary, ensure_ascii=False))
    return 0 if partials and finals else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run script help**

Run:

```powershell
python scripts/smoke_faster_whisper_streaming_asr.py --help
```

Expected:

```text
usage: smoke_faster_whisper_streaming_asr.py
```

- [ ] **Step 3: Checkpoint**

Run:

```powershell
git status --short
```

Do not commit unless explicitly authorized.

---

## Task 6: Run targeted automated validation

**Files:**
- No source edits expected unless tests reveal a defect.

- [ ] **Step 1: Run backend streaming/provider tests**

Run:

```powershell
python -m pytest backend/tests/test_config.py backend/tests/test_asr_factory.py backend/tests/test_faster_whisper_asr_provider.py backend/tests/test_faster_whisper_streaming_asr_provider.py backend/tests/test_asr_streaming.py backend/tests/test_api_audio_transcriptions_streaming.py backend/tests/test_api_audio_transcriptions_streaming_faster_whisper.py -v
```

Expected:

```text
All selected backend tests pass
```

- [ ] **Step 2: Run full backend tests if targeted pass**

Run:

```powershell
python -m pytest backend/tests -v
```

Expected:

```text
All backend tests pass
```

- [ ] **Step 3: Run frontend regression for unchanged 2G-1 UI path**

Run:

```powershell
npm --prefix frontend test -- src/api/transcriptionStream.test.ts src/hooks/useManualAudioRecorder.test.ts src/components/VoiceRecorder.test.tsx src/App.test.tsx
```

Expected:

```text
All selected frontend tests pass
```

- [ ] **Step 4: Run frontend typecheck/build**

Run:

```powershell
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

Expected:

```text
tsc exits 0; Vite build succeeds
```

- [ ] **Step 5: Checkpoint**

Run:

```powershell
git status --short
```

Do not commit unless explicitly authorized.

---

## Task 7: Run real FasterWhisper streaming smoke and record evidence

**Files:**
- Create: `docs/stage2g2-real-fasterwhisper-streaming-asr-feasibility.md`
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Start backend with real FasterWhisper streaming enabled**

Use the local model path already used for 2B-6. Example:

```powershell
$env:APP_ENV='development'
$env:DATABASE_URL='sqlite:///./data/stage2g2-smoke.db'
$env:LLM_PROVIDER='fake'
$env:TTS_PROVIDER='fake'
$env:ASR_PROVIDER='faster-whisper'
$env:ASR_FASTER_WHISPER_MODEL_PATH='%USERPROFILE%\.cache\huggingface\hub\models--Systran--faster-whisper-medium\snapshots\08e178d48790749d25932bbc082711ddcfdfbc4f'
$env:ASR_FASTER_WHISPER_MODEL_NAME='medium'
$env:ASR_FASTER_WHISPER_MODEL_REVISION='08e178d48790749d25932bbc082711ddcfdfbc4f'
$env:ASR_FASTER_WHISPER_DEVICE='cuda'
$env:ASR_FASTER_WHISPER_COMPUTE_TYPE='float16'
$env:ASR_FASTER_WHISPER_BEAM_SIZE='1'
$env:ASR_FASTER_WHISPER_STREAMING_ENABLED='true'
python -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Expected:

```text
Uvicorn running on http://127.0.0.1:8000
```

- [ ] **Step 2: Run smoke against P001 fixture**

In another terminal:

```powershell
python scripts/smoke_faster_whisper_streaming_asr.py --url http://127.0.0.1:8000/api/audio/transcriptions/stream --audio asr-benchmark-corpus/clean/P001.m4a --language zh --chunk-bytes 256000
```

Expected:

```text
HTTP 200 application/x-ndjson
At least one partial event
One final event
SUMMARY ... with partial_count >= 1 and final_text not empty
```

- [ ] **Step 3: Probe disabled streaming error**

Restart backend with:

```powershell
$env:ASR_FASTER_WHISPER_STREAMING_ENABLED='false'
```

Run the same smoke command.

Expected:

```text
HTTP 503 or 504 with a clear message that FasterWhisper streaming is not enabled
```

- [ ] **Step 4: Write evidence document**

Create `docs/stage2g2-real-fasterwhisper-streaming-asr-feasibility.md`:

```md
# Stage 2G-2 Real FasterWhisper Streaming ASR Feasibility Evidence

Status: COMPLETED on YYYY-MM-DD if validation passed; otherwise PARTIAL/BLOCKED with reason.

## Scope

This slice adds opt-in real FasterWhisper streaming-ASR feasibility through the existing `/api/audio/transcriptions/stream` NDJSON contract.

It does not implement production-grade simultaneous ASR, WebSockets, always-on listening, automatic spoken barge-in, final seamless low-gap audio, long-term memory, or emotion state.

## Validation

| Command / Surface | Result |
|---|---|
| `python -m pytest ...` | PASS/FAIL — record exact counts |
| `npm --prefix frontend test ...` | PASS/FAIL — record exact counts |
| `npm --prefix frontend run typecheck` | PASS/FAIL |
| `npm --prefix frontend run build` | PASS/FAIL |
| `python scripts/smoke_faster_whisper_streaming_asr.py ...` | PASS/FAIL — record first partial/final timings |
| Disabled streaming probe | PASS/FAIL — clear error observed |

## Real smoke observations

- Provider: faster-whisper
- Model: medium@08e178d48790749d25932bbc082711ddcfdfbc4f
- Device / compute type: cuda / float16
- Fixture: `asr-benchmark-corpus/clean/P001.m4a`
- Chunk bytes: 256000
- Chunk count: VALUE
- Partial count: VALUE
- First partial latency: VALUE ms
- Final latency: VALUE ms
- Final transcript: VALUE
- Console/browser observation: not applicable unless browser smoke was also run

## Limitations

- This implementation repeatedly decodes cumulative audio windows; it is a feasibility layer, not final production streaming ASR.
- Partial text can be revised and remains provisional.
- Latency and GPU load must be evaluated before productizing.
- Final seamless low-gap audio, long-term memory, and emotion state remain unimplemented.
```

Replace every `VALUE`, `PASS/FAIL`, and `YYYY-MM-DD` before saving final evidence.

- [ ] **Step 5: Update README and CLAUDE only after smoke passes**

If real smoke passes, update:

- `README.md` current stage summary with `2G-2 real FasterWhisper streaming ASR feasibility completed`.
- `CLAUDE.md` current status and Stage 2 completed ability list.
- Keep `Final seamless low-gap audio`, Stage 3, and Stage 4 listed as unimplemented.

If smoke fails or is blocked, do not mark 2G-2 completed. Record `PARTIAL` or `BLOCKED` in the evidence document and leave `CLAUDE.md` Stage 2 status as not completed for this subtask.

- [ ] **Step 6: Final checkpoint**

Run:

```powershell
git status --short
```

Do not commit unless explicitly authorized.

---

## Plan self-review

Spec coverage:

- Explicit opt-in settings: Task 1 and Task 2.
- Provider-local cumulative-window feasibility path: Task 3.
- Existing endpoint/schema preservation: Task 4 and frontend regression in Task 6.
- Disabled clear error: Task 3 and Task 4, real probe in Task 7.
- Temporary file cleanup: Task 3 assertions.
- Fake/default path preserved: Task 4 and Task 6.
- Real local smoke and evidence: Task 5 and Task 7.
- README/CLAUDE updates only after validation: Task 7.
- Phase boundaries: Scope guard and evidence template.

Placeholder scan:

- The only `VALUE`, `PASS/FAIL`, and `YYYY-MM-DD` strings are inside the evidence-template step and explicitly instruct replacement before final evidence is saved. They are not implementation placeholders in the plan itself.
- No `TBD`, `TODO`, or unresolved function names are used.

Type consistency:

- `TranscriptionPartialEvent.provider/model` are introduced only if API metadata tests require them.
- Settings names match the spec and factory/provider constructor arguments.
- Commands use existing project paths and PowerShell syntax.
