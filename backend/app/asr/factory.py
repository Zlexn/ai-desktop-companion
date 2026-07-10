from functools import lru_cache

from app.asr.base import ASRProvider
from app.asr.fake_provider import FakeASRProvider
from app.asr.faster_whisper_provider import FasterWhisperASRProvider
from app.core.config import Settings


@lru_cache(maxsize=4)
def create_asr_provider(settings: Settings) -> ASRProvider:
    if settings.asr_provider == "fake":
        return FakeASRProvider(
            mode=settings.fake_asr_mode,
            text=settings.fake_asr_text,
            detected_language=settings.fake_asr_detected_language,
        )
    if settings.asr_provider == "faster-whisper":
        return FasterWhisperASRProvider(
            model_path=settings.asr_faster_whisper_model_path,
            model_name=settings.asr_faster_whisper_model_name,
            model_revision=settings.asr_faster_whisper_model_revision,
            device=settings.asr_faster_whisper_device,
            compute_type=settings.asr_faster_whisper_compute_type,
            beam_size=settings.asr_faster_whisper_beam_size,
            timeout_seconds=settings.asr_faster_whisper_timeout_seconds,
            streaming_enabled=settings.asr_faster_whisper_streaming_enabled,
            streaming_window_ms=settings.asr_faster_whisper_streaming_window_ms,
            streaming_step_ms=settings.asr_faster_whisper_streaming_step_ms,
            streaming_min_partial_chars=settings.asr_faster_whisper_streaming_min_partial_chars,
            streaming_max_partials=settings.asr_faster_whisper_streaming_max_partials,
        )
    raise ValueError(f"Unsupported ASR_PROVIDER: {settings.asr_provider}")
