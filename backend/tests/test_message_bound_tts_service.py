from __future__ import annotations

import math
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from app.core.errors import NotFoundError, TTSInvalidRequestError
from app.domain.models import (
    ChatRole,
    ExpressionDelivery,
    ExpressionIntensity,
    Message,
    ResolvedExpression,
)
from app.services.message_bound_tts_service import MessageBoundTTSService
from app.tts.base import SpeechSynthesisResult, SpeechSynthesisSegment
from app.tts.expression_mapper import TTSExpressionMapper


class Messages:
    def __init__(self, message: Message | None) -> None:
        self.message = message

    def get(self, message_id: str) -> Message | None:
        return self.message if self.message is not None and self.message.id == message_id else None


class Plans:
    def __init__(self, rate: float) -> None:
        self.rate = rate
        self.ids: list[str] = []

    def resolve_compatible_or_default(self, assistant_message_id: str) -> ResolvedExpression:
        self.ids.append(assistant_message_id)
        return ResolvedExpression(
            ExpressionDelivery.WARM,
            self.rate,
            ExpressionIntensity.MEDIUM,
        )


class RecordingTTS:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, float | None, str]] = []

    async def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        speed: float | None = None,
    ) -> SpeechSynthesisResult:
        self.calls.append((text, voice_id, speed, "nonstream"))
        return SpeechSynthesisResult(b"RIFF", "audio/wav", 16_000, 100, "fake", "fake-v1")

    async def synthesize_stream(
        self,
        text: str,
        voice_id: str | None = None,
        speed: float | None = None,
    ) -> AsyncIterator[SpeechSynthesisSegment]:
        self.calls.append((text, voice_id, speed, "stream"))
        yield SpeechSynthesisSegment(b"RIFF", "audio/wav", 16_000, 100, "fake", "fake-v1", 0)


def message(role: ChatRole = ChatRole.ASSISTANT) -> Message:
    return Message("assistant-1", "session-1", role, "persisted reply", datetime.now(UTC), {})


def service(plan_rate: float = 1.0, role: ChatRole = ChatRole.ASSISTANT):
    plans = Plans(plan_rate)
    tts = RecordingTTS()
    value = MessageBoundTTSService(Messages(message(role)), plans, TTSExpressionMapper(), tts)  # type: ignore[arg-type]
    return value, plans, tts


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("plan_rate", "user_speed", "expected"),
    [(0.94, 1.5, 1.41), (1.10, 2.0, 2.0), (0.90, 0.5, 0.5), (1.0, None, 1.0)],
)
async def test_message_bound_tts_multiplies_then_clamps(
    plan_rate: float,
    user_speed: float | None,
    expected: float,
) -> None:
    value, plans, tts = service(plan_rate)

    await value.synthesize("assistant-1", voice_id="fake-default", speed=user_speed)

    assert plans.ids == ["assistant-1"]
    assert tts.calls[0][0] == "persisted reply"
    assert tts.calls[0][1] == "fake-default"
    assert tts.calls[0][2] == pytest.approx(expected)


@pytest.mark.asyncio
async def test_stream_and_nonstream_resolve_identical_inputs() -> None:
    value, _, tts = service(0.94)

    await value.synthesize("assistant-1", voice_id="fake-default", speed=1.5)
    segments = [segment async for segment in value.synthesize_stream("assistant-1", voice_id="fake-default", speed=1.5)]

    assert segments
    assert tts.calls[0][:2] == tts.calls[1][:2]
    assert tts.calls[0][2] == pytest.approx(tts.calls[1][2])


@pytest.mark.asyncio
async def test_unknown_and_user_message_are_rejected_before_tts() -> None:
    plans = Plans(1.0)
    tts = RecordingTTS()
    missing = MessageBoundTTSService(Messages(None), plans, TTSExpressionMapper(), tts)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await missing.synthesize("missing")

    user, _, user_tts = service(role=ChatRole.USER)
    with pytest.raises(TTSInvalidRequestError):
        await user.synthesize("assistant-1")
    assert plans.ids == []
    assert tts.calls == []
    assert user_tts.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("speed", [math.nan, math.inf, 0.49, 2.01])
async def test_invalid_user_speed_is_rejected_before_plan_and_provider(speed: float) -> None:
    value, plans, tts = service()

    with pytest.raises(TTSInvalidRequestError):
        await value.synthesize("assistant-1", speed=speed)

    assert plans.ids == []
    assert tts.calls == []
