from __future__ import annotations

import asyncio
import io
import math
import struct
import wave
from collections.abc import AsyncIterator

from app.core.errors import TTSTimeoutError, TTSUnavailableError
from app.tts.base import SpeechSynthesisResult, SpeechSynthesisSegment


class FakeTTSProvider:
    provider_name = "fake"
    model_name = "fake-tone-v1"
    sample_rate = 16_000
    amplitude = 2_000
    max_duration_ms = 900

    def __init__(self, mode: str = "ok") -> None:
        self._mode = mode

    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        speed: float = 1.0,
    ) -> SpeechSynthesisResult:
        if self._mode == "error":
            raise TTSUnavailableError()
        if self._mode == "timeout":
            raise TTSTimeoutError()
        if self._mode == "empty":
            return SpeechSynthesisResult(
                audio_bytes=b"",
                media_type="audio/wav",
                sample_rate=self.sample_rate,
                duration_ms=0,
                provider=self.provider_name,
                model=self.model_name,
            )

        duration_ms = self._duration_for_text(text, speed)
        audio_bytes = self._build_wav(duration_ms, text)
        return SpeechSynthesisResult(
            audio_bytes=audio_bytes,
            media_type="audio/wav",
            sample_rate=self.sample_rate,
            duration_ms=duration_ms,
            provider=self.provider_name,
            model=self.model_name,
        )

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
            await asyncio.sleep(0.02)

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

    def _duration_for_text(self, text: str, speed: float) -> int:
        base_ms = 220 + min(len(text.strip()), 80) * 6
        adjusted_ms = int(round(base_ms / speed))
        return max(120, min(self.max_duration_ms, adjusted_ms))

    def _build_wav(self, duration_ms: int, text: str) -> bytes:
        frequency = 440 + (sum(text.encode("utf-8")) % 160)
        frame_count = int(self.sample_rate * duration_ms / 1000)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            frames = bytearray()
            fade_frames = max(1, min(frame_count // 10, self.sample_rate // 100))
            for index in range(frame_count):
                envelope = 1.0
                if index < fade_frames:
                    envelope = index / fade_frames
                elif frame_count - index < fade_frames:
                    envelope = (frame_count - index) / fade_frames
                sample = int(self.amplitude * envelope * math.sin(2 * math.pi * frequency * index / self.sample_rate))
                frames.extend(struct.pack("<h", sample))
            wav_file.writeframes(bytes(frames))
        return buffer.getvalue()
