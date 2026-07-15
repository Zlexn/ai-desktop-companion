from collections.abc import AsyncIterator

from app.core.errors import NotFoundError, TTSInvalidRequestError
from app.domain.models import ChatRole
from app.repositories.messages import MessageRepository
from app.services.expression_plan_service import ExpressionPlanService
from app.services.tts_service import MAX_SPEED, MIN_SPEED, TTSService
from app.tts.base import SpeechSynthesisResult, SpeechSynthesisSegment
from app.tts.expression_mapper import (
    MappedTTSRequest,
    TTSExpressionMapper,
    TTSExpressionRequest,
)


class MessageBoundTTSService:
    def __init__(
        self,
        messages: MessageRepository,
        expression_plans: ExpressionPlanService,
        mapper: TTSExpressionMapper,
        tts: TTSService,
    ) -> None:
        self._messages = messages
        self._expression_plans = expression_plans
        self._mapper = mapper
        self._tts = tts

    def _resolve(
        self,
        assistant_message_id: str,
        voice_id: str | None,
        speed: float | None,
    ) -> MappedTTSRequest:
        message = self._messages.get(assistant_message_id)
        if message is None:
            raise NotFoundError("消息不存在。")
        if message.role is not ChatRole.ASSISTANT:
            raise TTSInvalidRequestError("只能合成已保存的助手消息。")
        user_speed = 1.0 if speed is None else TTSService.validate_speed(speed)
        plan = self._expression_plans.resolve_compatible_or_default(message.id)
        final_speed = min(MAX_SPEED, max(MIN_SPEED, plan.rate * user_speed))
        return self._mapper.map(
            TTSExpressionRequest(
                message.content,
                voice_id,
                final_speed,
                plan.delivery,
                plan.intensity,
            )
        )

    async def synthesize(
        self,
        assistant_message_id: str,
        voice_id: str | None = None,
        speed: float | None = None,
    ) -> SpeechSynthesisResult:
        request = self._resolve(assistant_message_id, voice_id, speed)
        return await self._tts.synthesize(request.text, request.voice_id, request.speed)

    async def synthesize_stream(
        self,
        assistant_message_id: str,
        voice_id: str | None = None,
        speed: float | None = None,
    ) -> AsyncIterator[SpeechSynthesisSegment]:
        request = self._resolve(assistant_message_id, voice_id, speed)
        async for segment in self._tts.synthesize_stream(
            request.text,
            request.voice_id,
            request.speed,
        ):
            yield segment
