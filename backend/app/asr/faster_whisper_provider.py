from __future__ import annotations

import asyncio
import os
import site
import tempfile
import time
from collections.abc import AsyncIterator, Iterable
from pathlib import Path
from typing import Any

from app.asr.base import ASRProvider, TranscriptionFinalEvent, TranscriptionPartialEvent, TranscriptionResult, TranscriptionSegment, TranscriptionStreamEvent
from app.core.errors import ASRTimeoutError, ASRUnavailableError

_DLL_DIRECTORY_HANDLES: list[Any] = []


def add_windows_cuda_dll_dirs() -> list[Path]:
    """Add local NVIDIA CUDA runtime wheel DLL directories on Windows.

    Packages such as ``nvidia-cublas-cu12`` install DLLs under
    ``site-packages/nvidia/<component>/bin``. CTranslate2 may need those paths in
    the DLL search path before importing/loading CUDA components.
    """

    if os.name != "nt":
        return []

    roots: list[Path] = []
    for candidate in site.getsitepackages() + [site.getusersitepackages()]:
        if candidate:
            roots.append(Path(candidate))

    existing_path = os.environ.get("PATH", "")
    existing_parts = existing_path.split(os.pathsep) if existing_path else []
    added: list[Path] = []
    seen: set[Path] = set()

    for root in roots:
        nvidia_root = root / "nvidia"
        if not nvidia_root.is_dir():
            continue
        for bin_dir in nvidia_root.glob("*/bin"):
            resolved = bin_dir.resolve()
            if resolved in seen or not any(resolved.glob("*.dll")):
                continue
            seen.add(resolved)
            directory_text = str(resolved)
            if directory_text not in existing_parts:
                existing_parts.insert(0, directory_text)
                added.append(resolved)
            if hasattr(os, "add_dll_directory"):
                _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(directory_text))

    if added:
        os.environ["PATH"] = os.pathsep.join(existing_parts)
    return added


def _segment_text(segment: Any) -> str:
    if isinstance(segment, dict):
        return str(segment.get("text", ""))
    return str(getattr(segment, "text", ""))


def _segment_ms(segment: Any, attr: str) -> int:
    if isinstance(segment, dict):
        value = segment.get(attr)
    else:
        value = getattr(segment, attr, None)
    if value is None:
        return 0
    return max(0, int(float(value) * 1000))


def _info_attr(info: Any, attr: str) -> Any:
    if isinstance(info, dict):
        return info.get(attr)
    return getattr(info, attr, None)


class FasterWhisperASRProvider(ASRProvider):
    provider_name = "faster-whisper"

    def __init__(
        self,
        *,
        model_path: str,
        model_name: str,
        model_revision: str,
        device: str,
        compute_type: str,
        beam_size: int,
        timeout_seconds: float,
        streaming_enabled: bool = False,
        streaming_window_ms: int = 3000,
        streaming_step_ms: int = 1000,
        streaming_min_partial_chars: int = 1,
        streaming_max_partials: int = 8,
    ) -> None:
        self.model_path = model_path
        self.model_name = model_name
        self.model_revision = model_revision
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.timeout_seconds = timeout_seconds
        self.streaming_enabled = streaming_enabled
        self.streaming_window_ms = streaming_window_ms
        self.streaming_step_ms = streaming_step_ms
        self.streaming_min_partial_chars = streaming_min_partial_chars
        self.streaming_max_partials = streaming_max_partials
        self._model: Any | None = None

    @property
    def public_model_name(self) -> str:
        return f"{self.model_name}@{self.model_revision}"

    async def transcribe(
        self,
        audio_bytes: bytes,
        media_type: str,
        language: str | None = None,
    ) -> TranscriptionResult:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._transcribe_sync, audio_bytes, media_type, language),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            raise ASRTimeoutError() from exc
        except ASRTimeoutError:
            raise
        except ASRUnavailableError:
            raise
        except Exception as exc:
            raise ASRUnavailableError() from exc

    async def transcribe_stream(
        self,
        audio_chunks: Iterable[bytes],
        media_type: str,
        language: str | None = None,
    ) -> AsyncIterator[TranscriptionStreamEvent]:
        if not self.streaming_enabled:
            raise ASRUnavailableError("当前 FasterWhisper ASR Provider 未启用流式转写。")

        try:
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
                try:
                    partial_result = await asyncio.wait_for(
                        asyncio.to_thread(self._transcribe_sync, b"".join(accumulated), media_type, language),
                        timeout=self.timeout_seconds,
                    )
                except Exception:
                    continue
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
                    provider=self.provider_name,
                    model=self.public_model_name,
                )
                partial_index += 1

            final_result = await asyncio.wait_for(
                asyncio.to_thread(self._transcribe_sync, b"".join(chunks), media_type, language),
                timeout=self.timeout_seconds,
            )
            yield TranscriptionFinalEvent(type="final", result=final_result)
        except TimeoutError as exc:
            raise ASRTimeoutError() from exc
        except ASRTimeoutError:
            raise
        except ASRUnavailableError:
            raise
        except Exception as exc:
            raise ASRUnavailableError() from exc

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        if not Path(self.model_path).exists():
            raise ASRUnavailableError()
        add_windows_cuda_dll_dirs()
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:
            raise ASRUnavailableError() from exc
        try:
            self._model = WhisperModel(
                self.model_path,
                device=self.device,
                compute_type=self.compute_type,
                local_files_only=True,
            )
        except Exception as exc:
            raise ASRUnavailableError() from exc
        return self._model

    def _transcribe_sync(
        self,
        audio_bytes: bytes,
        media_type: str,
        language: str | None,
    ) -> TranscriptionResult:
        suffix = self._suffix_for_media_type(media_type)
        temp_path: Path | None = None
        start = time.perf_counter()
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_file.write(audio_bytes)
                temp_path = Path(temp_file.name)

            model = self._load_model()
            segments_iter, info = model.transcribe(
                str(temp_path),
                language=language,
                beam_size=self.beam_size,
            )
            segments = list(segments_iter)
            inference_ms = int((time.perf_counter() - start) * 1000)
            return self._build_result(segments, info, inference_ms)
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _build_result(self, segments: Iterable[Any], info: Any, inference_ms: int) -> TranscriptionResult:
        materialized = list(segments)
        text = "".join(_segment_text(segment) for segment in materialized).strip()
        duration = _info_attr(info, "duration")
        duration_ms = int(float(duration) * 1000) if duration is not None else None
        detected_language = _info_attr(info, "language")
        result_segments = tuple(
            TranscriptionSegment(
                start_ms=_segment_ms(segment, "start"),
                end_ms=_segment_ms(segment, "end"),
                text=_segment_text(segment).strip(),
            )
            for segment in materialized
        )
        return TranscriptionResult(
            text=text,
            detected_language=str(detected_language) if detected_language else None,
            duration_ms=duration_ms,
            provider=self.provider_name,
            model=self.public_model_name,
            inference_ms=inference_ms,
            segments=result_segments,
        )

    def _suffix_for_media_type(self, media_type: str) -> str:
        if media_type == "audio/webm":
            return ".webm"
        if media_type == "audio/mp4":
            return ".m4a"
        if media_type in {"audio/wav", "audio/x-wav"}:
            return ".wav"
        return ".audio"
