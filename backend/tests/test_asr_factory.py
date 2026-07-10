from __future__ import annotations

import pytest

from app.asr.factory import create_asr_provider
from app.asr.fake_provider import FakeASRProvider
from app.core.config import Settings


def test_asr_factory_creates_fake_provider() -> None:
    provider = create_asr_provider(Settings(asr_provider="fake", fake_asr_text="工厂测试"))

    assert isinstance(provider, FakeASRProvider)
    assert provider.text == "工厂测试"


def test_asr_factory_rejects_unknown_provider_without_fallback() -> None:
    with pytest.raises(ValueError, match="Unsupported ASR_PROVIDER"):
        create_asr_provider(Settings(asr_provider="unknown"))


def test_asr_factory_creates_faster_whisper_provider(tmp_path) -> None:
    from app.asr.faster_whisper_provider import FasterWhisperASRProvider

    create_asr_provider.cache_clear()
    provider = create_asr_provider(
        Settings(
            asr_provider="faster-whisper",
            asr_faster_whisper_model_path=str(tmp_path),
            asr_faster_whisper_model_name="medium",
            asr_faster_whisper_model_revision="08e178d48790749d25932bbc082711ddcfdfbc4f",
            asr_faster_whisper_device="cuda",
            asr_faster_whisper_compute_type="float16",
            asr_faster_whisper_beam_size=1,
        )
    )

    assert isinstance(provider, FasterWhisperASRProvider)
    assert provider.model_path == str(tmp_path)
    assert provider.public_model_name == "medium@08e178d48790749d25932bbc082711ddcfdfbc4f"




def test_asr_factory_passes_faster_whisper_streaming_settings(tmp_path) -> None:
    from app.asr.faster_whisper_provider import FasterWhisperASRProvider

    create_asr_provider.cache_clear()
    provider = create_asr_provider(
        Settings(
            asr_provider="faster-whisper",
            asr_faster_whisper_model_path=str(tmp_path),
            asr_faster_whisper_streaming_enabled=True,
            asr_faster_whisper_streaming_window_ms=2500,
            asr_faster_whisper_streaming_step_ms=500,
            asr_faster_whisper_streaming_min_partial_chars=2,
            asr_faster_whisper_streaming_max_partials=3,
        )
    )

    assert isinstance(provider, FasterWhisperASRProvider)
    assert provider.streaming_enabled is True
    assert provider.streaming_window_ms == 2500
    assert provider.streaming_step_ms == 500
    assert provider.streaming_min_partial_chars == 2
    assert provider.streaming_max_partials == 3


def test_asr_factory_caches_provider_for_same_settings(tmp_path) -> None:
    create_asr_provider.cache_clear()
    settings = Settings(
        asr_provider="faster-whisper",
        asr_faster_whisper_model_path=str(tmp_path),
    )

    assert create_asr_provider(settings) is create_asr_provider(settings)
