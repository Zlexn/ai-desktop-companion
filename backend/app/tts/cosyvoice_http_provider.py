from __future__ import annotations

import base64
import json
import time
from collections.abc import AsyncIterator

import httpx

from app.core.errors import TTSInvalidResponseError, TTSTimeoutError, TTSUnavailableError
from app.tts.base import SpeechSynthesisResult, SpeechSynthesisSegment


class CosyVoiceHTTPProvider:
    provider_name = "cosyvoice-http"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        default_voice: str,
        timeout_seconds: float,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._default_voice = default_voice
        self._timeout_seconds = timeout_seconds

    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        speed: float = 1.0,
    ) -> SpeechSynthesisResult:
        started = time.perf_counter()
        voice = voice_id or self._default_voice
        payload = {
            "model": self._model,
            "input": text,
            "voice": voice,
            "response_format": "wav",
            "speed": speed,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds, trust_env=False) as client:
                response = await client.post(f"{self._base_url}/v1/audio/speech", json=payload)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise TTSTimeoutError() from exc
        except httpx.HTTPError as exc:
            raise TTSUnavailableError("CosyVoice TTS 服务不可用。") from exc

        inference_ms = max(1, round((time.perf_counter() - started) * 1000))
        sample_rate = _parse_positive_int(response.headers.get("X-Audio-Sample-Rate"), default=24_000)
        duration_ms = _parse_positive_int(response.headers.get("X-Audio-Duration-Ms"), default=inference_ms)
        media_type = response.headers.get("content-type", "audio/wav").split(";", 1)[0]
        return SpeechSynthesisResult(
            audio_bytes=response.content,
            media_type=media_type,
            sample_rate=sample_rate,
            duration_ms=duration_ms,
            provider=self.provider_name,
            model=self._model,
        )

    async def synthesize_stream(
        self,
        text: str,
        voice_id: str | None = None,
        speed: float = 1.0,
    ) -> AsyncIterator[SpeechSynthesisSegment]:
        voice = voice_id or self._default_voice
        payload = {
            "model": self._model,
            "input": text,
            "voice": voice,
            "response_format": "wav",
            "speed": speed,
            "stream": True,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds, trust_env=False) as client:
                async with client.stream("POST", f"{self._base_url}/v1/audio/speech", json=payload) as response:
                    response.raise_for_status()
                    pending = ""
                    async for chunk in response.aiter_text():
                        pending += chunk
                        lines = pending.split("\n")
                        pending = lines.pop() or ""
                        for line in lines:
                            event = line.strip()
                            if event:
                                segment = self._parse_stream_event(event)
                                if segment is not None:
                                    yield segment
                    if pending.strip():
                        segment = self._parse_stream_event(pending.strip())
                        if segment is not None:
                            yield segment
        except httpx.TimeoutException as exc:
            raise TTSTimeoutError() from exc
        except httpx.HTTPStatusError as exc:
            raise TTSUnavailableError("CosyVoice TTS 服务不可用。") from exc
        except httpx.HTTPError as exc:
            raise TTSUnavailableError("CosyVoice TTS 服务不可用。") from exc
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            raise TTSInvalidResponseError() from exc

    def _parse_stream_event(self, line: str) -> SpeechSynthesisSegment | None:
        payload = json.loads(line)
        event_type = payload.get("type")
        if event_type in {"start", "done"}:
            return None
        if event_type == "error":
            raise TTSUnavailableError(str(payload.get("message") or "CosyVoice TTS 服务不可用。"))
        if event_type != "segment":
            return None

        index = int(payload["index"])
        duration_ms = int(payload["duration_ms"])
        sample_rate = int(payload["sample_rate"])
        media_type = str(payload["media_type"])
        audio_base64 = str(payload["audio_base64"])
        audio_bytes = base64.b64decode(audio_base64)
        if index < 0 or duration_ms <= 0 or sample_rate <= 0 or media_type != "audio/wav" or not audio_bytes:
            raise TTSInvalidResponseError()
        return SpeechSynthesisSegment(
            audio_bytes=audio_bytes,
            media_type=media_type,
            sample_rate=sample_rate,
            duration_ms=duration_ms,
            provider=self.provider_name,
            model=self._model,
            index=index,
        )


def _parse_positive_int(value: str | None, *, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default
