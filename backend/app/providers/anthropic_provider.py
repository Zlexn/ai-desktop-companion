import anthropic

from app.core.errors import (
    ProviderError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    sanitize_error_text,
)
from app.domain.models import ChatRole
from app.providers.base import LLMMessage, LLMOptions, LLMResponse


class AnthropicProvider:
    provider_name = "anthropic"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generate(self, messages: list[LLMMessage], options: LLMOptions) -> LLMResponse:
        system_messages = [message.content for message in messages if message.role == ChatRole.SYSTEM]
        conversation = [
            {"role": message.role.value, "content": message.content}
            for message in messages
            if message.role in {ChatRole.USER, ChatRole.ASSISTANT}
        ]
        if not conversation:
            raise ProviderInvalidResponseError()

        try:
            response = await self._client.with_options(
                timeout=options.timeout_seconds,
                max_retries=options.max_retries,
            ).messages.create(
                model=options.model,
                max_tokens=options.max_tokens,
                system="\n\n".join(system_messages) if system_messages else anthropic.NOT_GIVEN,
                messages=conversation,
            )
        except anthropic.APITimeoutError as exc:
            raise ProviderTimeoutError() from exc
        except anthropic.RateLimitError as exc:
            raise ProviderRateLimitError() from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError("无法连接模型服务，请检查网络后重试。") from exc
        except anthropic.APIStatusError as exc:
            safe_message = sanitize_error_text(exc.message, [self._api_key])
            raise ProviderError(f"模型服务返回错误：{safe_message}") from exc

        if response.stop_reason == "refusal":
            raise ProviderInvalidResponseError("模型拒绝了本次请求，请调整输入后重试。")

        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if not text:
            raise ProviderInvalidResponseError()
        return LLMResponse(text=text, provider=self.provider_name, model=response.model or options.model)
