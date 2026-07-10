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
    fail_call_indices: set[int] = set()

    def __init__(self, model_path: str, *, device: str, compute_type: str, local_files_only: bool) -> None:
        self.model_path = model_path
        _StreamingFakeWhisperModel.calls.append({"model_path": model_path, "device": device, "compute_type": compute_type, "local_files_only": local_files_only})

    def transcribe(self, audio_path: str, *, language: str | None, beam_size: int):
        assert Path(audio_path).is_file()
        index = len([call for call in _StreamingFakeWhisperModel.calls if "audio_path" in call])
        if index in _StreamingFakeWhisperModel.fail_call_indices:
            _StreamingFakeWhisperModel.calls.append({"audio_path": audio_path, "language": language, "beam_size": beam_size, "failed": True})
            raise ValueError("partial window is not decodable yet")
        text = self.texts[min(index, len(self.texts) - 1)]
        _StreamingFakeWhisperModel.calls.append({"audio_path": audio_path, "language": language, "beam_size": beam_size, "text": text})
        return [_Segment(text)], _Info()


@pytest.fixture(autouse=True)
def reset_fake_model() -> None:
    _StreamingFakeWhisperModel.calls.clear()
    _StreamingFakeWhisperModel.texts = [" 你", " 你好", " 你好世界"]
    _StreamingFakeWhisperModel.fail_call_indices = set()


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
async def test_faster_whisper_streaming_skips_undecodable_partial_windows(tmp_path: Path, fake_faster_whisper) -> None:
    _StreamingFakeWhisperModel.fail_call_indices = {0}
    provider = make_provider(tmp_path)

    events = [event async for event in provider.transcribe_stream([b"not-yet-decodable", b"complete-enough"], "audio/webm", "zh")]

    partials = [event for event in events if isinstance(event, TranscriptionPartialEvent)]
    assert [event.text for event in partials] == ["你好"]
    assert isinstance(events[-1], TranscriptionFinalEvent)
    assert events[-1].result.text == "你好世界"


@pytest.mark.asyncio
async def test_faster_whisper_streaming_respects_max_partials(tmp_path: Path, fake_faster_whisper) -> None:
    provider = make_provider(tmp_path, max_partials=1)

    events = [event async for event in provider.transcribe_stream([b"chunk-1", b"chunk-2", b"chunk-3"], "audio/webm", "zh")]

    partials = [event for event in events if isinstance(event, TranscriptionPartialEvent)]
    assert len(partials) == 1
    assert isinstance(events[-1], TranscriptionFinalEvent)
