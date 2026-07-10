from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

from app.asr.faster_whisper_provider import FasterWhisperASRProvider, add_windows_cuda_dll_dirs
from app.core.errors import ASRTimeoutError, ASRUnavailableError


class _FakeInfo:
    language = "zh"
    duration = 1.25


class _FakeSegment:
    text = " 测试文本"
    start = 0.0
    end = 1.25


class _FakeWhisperModel:
    calls: list[dict] = []

    def __init__(self, model_path: str, *, device: str, compute_type: str, local_files_only: bool) -> None:
        self.model_path = model_path
        self.device = device
        self.compute_type = compute_type
        self.local_files_only = local_files_only
        _FakeWhisperModel.calls.append(
            {
                "model_path": model_path,
                "device": device,
                "compute_type": compute_type,
                "local_files_only": local_files_only,
            }
        )

    def transcribe(self, audio_path: str, *, language: str | None, beam_size: int):
        assert Path(audio_path).is_file()
        _FakeWhisperModel.calls.append({"audio_path": audio_path, "language": language, "beam_size": beam_size})
        return [_FakeSegment()], _FakeInfo()


@pytest.fixture(autouse=True)
def clear_fake_calls() -> None:
    _FakeWhisperModel.calls.clear()


@pytest.fixture
def fake_faster_whisper(monkeypatch: pytest.MonkeyPatch):
    module = types.SimpleNamespace(WhisperModel=_FakeWhisperModel)
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    return module


def test_faster_whisper_provider_transcribes_with_lazy_local_model(tmp_path: Path, fake_faster_whisper) -> None:
    provider = FasterWhisperASRProvider(
        model_path=str(tmp_path),
        model_name="medium",
        model_revision="08e178d48790749d25932bbc082711ddcfdfbc4f",
        device="cuda",
        compute_type="float16",
        beam_size=1,
        timeout_seconds=10,
    )

    result = asyncio.run(provider.transcribe(b"fake audio bytes", "audio/mp4", "zh"))

    assert result.text == "测试文本"
    assert result.detected_language == "zh"
    assert result.duration_ms == 1250
    assert result.provider == "faster-whisper"
    assert result.model == "medium@08e178d48790749d25932bbc082711ddcfdfbc4f"
    assert result.inference_ms >= 0
    assert result.segments is not None
    assert result.segments[0].start_ms == 0
    assert result.segments[0].end_ms == 1250
    assert _FakeWhisperModel.calls[0] == {
        "model_path": str(tmp_path),
        "device": "cuda",
        "compute_type": "float16",
        "local_files_only": True,
    }
    assert _FakeWhisperModel.calls[1]["language"] == "zh"
    assert _FakeWhisperModel.calls[1]["beam_size"] == 1
    assert not Path(_FakeWhisperModel.calls[1]["audio_path"]).exists()


def test_faster_whisper_provider_reuses_loaded_model(tmp_path: Path, fake_faster_whisper) -> None:
    provider = FasterWhisperASRProvider(
        model_path=str(tmp_path),
        model_name="medium",
        model_revision="08e178d48790749d25932bbc082711ddcfdfbc4f",
        device="cuda",
        compute_type="float16",
        beam_size=1,
        timeout_seconds=10,
    )

    asyncio.run(provider.transcribe(b"first", "audio/wav", "zh"))
    asyncio.run(provider.transcribe(b"second", "audio/wav", "zh"))

    model_load_calls = [call for call in _FakeWhisperModel.calls if "model_path" in call]
    assert len(model_load_calls) == 1


def test_faster_whisper_provider_missing_model_path_maps_to_unavailable(tmp_path: Path, fake_faster_whisper) -> None:
    provider = FasterWhisperASRProvider(
        model_path=str(tmp_path / "missing"),
        model_name="medium",
        model_revision="08e178d48790749d25932bbc082711ddcfdfbc4f",
        device="cuda",
        compute_type="float16",
        beam_size=1,
        timeout_seconds=10,
    )

    with pytest.raises(ASRUnavailableError):
        asyncio.run(provider.transcribe(b"fake", "audio/mp4", "zh"))


def test_faster_whisper_provider_timeout_maps_to_asr_timeout(tmp_path: Path, fake_faster_whisper, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FasterWhisperASRProvider(
        model_path=str(tmp_path),
        model_name="medium",
        model_revision="08e178d48790749d25932bbc082711ddcfdfbc4f",
        device="cuda",
        compute_type="float16",
        beam_size=1,
        timeout_seconds=10,
    )

    async def raise_timeout(*args, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr(asyncio, "to_thread", raise_timeout)

    with pytest.raises(ASRTimeoutError):
        asyncio.run(provider.transcribe(b"fake", "audio/mp4", "zh"))


def test_windows_cuda_dll_discovery_adds_nvidia_runtime_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    site_packages = tmp_path / "site-packages"
    cublas_bin = site_packages / "nvidia" / "cublas" / "bin"
    empty_bin = site_packages / "nvidia" / "empty" / "bin"
    cublas_bin.mkdir(parents=True)
    empty_bin.mkdir(parents=True)
    (cublas_bin / "cublas64_12.dll").write_bytes(b"dll")
    handles: list[str] = []

    import app.asr.faster_whisper_provider as provider_module

    monkeypatch.setattr(provider_module.os, "name", "nt")
    monkeypatch.setattr(provider_module.site, "getsitepackages", lambda: [str(site_packages)])
    monkeypatch.setattr(provider_module.site, "getusersitepackages", lambda: "")
    monkeypatch.setenv("PATH", "base-path")
    monkeypatch.setattr(provider_module.os, "add_dll_directory", lambda path: handles.append(path) or f"handle:{path}", raising=False)
    provider_module._DLL_DIRECTORY_HANDLES.clear()

    added = add_windows_cuda_dll_dirs()

    assert added == [cublas_bin.resolve()]
    assert str(cublas_bin.resolve()) in provider_module.os.environ["PATH"]
    assert handles == [str(cublas_bin.resolve())]
    assert provider_module._DLL_DIRECTORY_HANDLES == [f"handle:{cublas_bin.resolve()}"]
