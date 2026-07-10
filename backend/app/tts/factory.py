from app.core.config import Settings
from app.tts.base import TTSProvider
from app.tts.cosyvoice_http_provider import CosyVoiceHTTPProvider
from app.tts.fake_provider import FakeTTSProvider


def create_tts_provider(settings: Settings) -> TTSProvider:
    if settings.tts_provider == "fake":
        return FakeTTSProvider(mode=settings.tts_fake_mode)
    if settings.tts_provider == "cosyvoice-http":
        return CosyVoiceHTTPProvider(
            base_url=settings.tts_cosyvoice_base_url,
            model=settings.tts_cosyvoice_model,
            default_voice=settings.tts_default_voice,
            timeout_seconds=settings.tts_cosyvoice_timeout_seconds,
        )
    raise ValueError(f"Unsupported TTS_PROVIDER: {settings.tts_provider}")
