from app.core.errors import ProviderError, ProviderInvalidResponseError, ProviderRateLimitError, ProviderTimeoutError
from app.domain.models import ChatRole
from app.providers.base import LLMMessage, LLMOptions, LLMResponse
from app.providers.payload_normalization import (
    normalize_provider_payload,
    validate_chat_dispatch_budget,
)


class FakeProvider:
    provider_name = "fake"

    def __init__(self, mode: str = "ok") -> None:
        self.mode = mode
        self.calls: list[list[LLMMessage]] = []

    async def generate(self, messages: list[LLMMessage], options: LLMOptions) -> LLMResponse:
        payload = normalize_provider_payload(self.provider_name, messages)
        validate_chat_dispatch_budget(payload.character_count, options)
        self.calls.append(messages)
        if self.mode == "error":
            raise ProviderError()
        if self.mode == "timeout":
            raise ProviderTimeoutError()
        if self.mode == "rate_limit":
            raise ProviderRateLimitError()
        if self.mode == "invalid":
            raise ProviderInvalidResponseError()
        if self.mode == "empty":
            return LLMResponse(text="", provider="fake", model=options.model)

        user_messages = [message.content for message in messages if message.role == ChatRole.USER]
        latest = user_messages[-1] if user_messages else ""
        text = f"我听见了：{latest}。我会先陪你把这件事慢慢说清楚。"
        return LLMResponse(text=text, provider="fake", model=options.model)
