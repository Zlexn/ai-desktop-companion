import anthropic

from app.core.errors import (
    ProviderError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    sanitize_error_text,
)
from app.providers.base import LLMMessage, LLMOptions, LLMResponse
from app.providers.payload_normalization import (
    AnthropicPayloadView,
    normalize_provider_payload,
    validate_chat_dispatch_budget,
)


class AnthropicProvider:
    provider_name = "anthropic"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def aclose(self) -> None:
        await self._client.close()

    async def generate(self, messages: list[LLMMessage], options: LLMOptions) -> LLMResponse:
        payload = normalize_provider_payload(self.provider_name, messages)
        if not isinstance(payload, AnthropicPayloadView):
            raise RuntimeError("Anthropic payload normalization mismatch")
        validate_chat_dispatch_budget(payload.character_count, options)
        if not payload.conversation:
            raise ProviderInvalidResponseError()

        try:
            response = await self._client.with_options(
                timeout=options.timeout_seconds,
                max_retries=options.max_retries,
            ).messages.create(
                model=options.model,
                max_tokens=options.max_tokens,
                system=payload.system if payload.system else anthropic.NOT_GIVEN,
                messages=list(payload.conversation),
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
