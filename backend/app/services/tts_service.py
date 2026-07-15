from __future__ import annotations

import math
from collections.abc import AsyncIterator

from app.core.config import Settings
from app.core.errors import TTSInvalidRequestError, TTSInvalidResponseError, TTSError, TTSTimeoutError, TTSUnavailableError
from app.tts.base import SpeechSynthesisResult, SpeechSynthesisSegment, TTSProvider

SUPPORTED_MEDIA_TYPES = {"audio/wav"}
MIN_SPEED = 0.5
MAX_SPEED = 2.0


class TTSService:
    def __init__(self, provider: TTSProvider, settings: Settings) -> None:
        self._provider = provider
        self._settings = settings

    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        speed: float | None = None,
    ) -> SpeechSynthesisResult:
        clean_text = text.strip()
        selected_voice = voice_id or self._settings.tts_default_voice
        selected_speed = self._settings.tts_default_speed if speed is None else speed
        self._validate_request(clean_text, selected_voice, selected_speed)

        try:
            result = await self._provider.synthesize(clean_text, selected_voice, selected_speed)
        except TTSTimeoutError:
            raise
        except TTSError:
            raise
        except TimeoutError as exc:
            raise TTSTimeoutError() from exc
        except Exception as exc:
            raise TTSUnavailableError() from exc

        self._validate_result(result)
        return result

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

    @staticmethod
    def validate_speed(speed: float) -> float:
        if not math.isfinite(speed) or not MIN_SPEED <= speed <= MAX_SPEED:
            raise TTSInvalidRequestError("语音语速必须在 0.5 到 2.0 之间。")
        return speed

    def _validate_request(self, text: str, voice_id: str, speed: float) -> None:
        if not text:
            raise TTSInvalidRequestError("语音合成文本不能为空。")
        if len(text) > self._settings.tts_max_text_chars:
            raise TTSInvalidRequestError(f"语音合成文本不能超过 {self._settings.tts_max_text_chars} 个字符。")
        if voice_id != self._settings.tts_default_voice:
            raise TTSInvalidRequestError("未知的语音声音配置。")
        self.validate_speed(speed)

    def _validate_result(self, result: SpeechSynthesisResult) -> None:
        if not result.audio_bytes:
            raise TTSInvalidResponseError()
        if result.media_type not in SUPPORTED_MEDIA_TYPES:
            raise TTSInvalidResponseError()
        if result.sample_rate <= 0 or result.duration_ms <= 0:
            raise TTSInvalidResponseError()
        if not result.provider or not result.model:
            raise TTSInvalidResponseError()

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
