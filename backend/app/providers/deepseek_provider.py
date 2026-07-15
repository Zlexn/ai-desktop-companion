from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import Settings
from app.core.errors import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderInsufficientBalanceError,
    ProviderInvalidRequestError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    sanitize_error_text,
)
from app.domain.models import ChatRole
from app.providers.base import LLMMessage, LLMOptions, LLMResponse


class DeepSeekProvider:
    provider_name = "deepseek"

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
        *,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        if not settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY is required for DeepSeekProvider")
        self._settings = settings
        self._api_key = settings.deepseek_api_key
        hostname = urlparse(settings.deepseek_base_url).hostname
        trust_env = hostname not in {"127.0.0.1", "localhost", "::1"}
        self._client = client or httpx.AsyncClient(trust_env=trust_env)
        self._endpoint = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
        self._max_tokens = settings.deepseek_max_tokens if max_tokens is None else max_tokens
        self._timeout_seconds = settings.deepseek_timeout_seconds if timeout_seconds is None else timeout_seconds
        self._max_retries = settings.deepseek_max_retries if max_retries is None else max_retries

    async def aclose(self) -> None:
        await self._client.aclose()

    async def generate(self, messages: list[LLMMessage], options: LLMOptions) -> LLMResponse:
        payload = {
            "model": options.model,
            "messages": self._to_deepseek_messages(messages),
            "max_tokens": min(options.max_tokens, self._max_tokens),
            "stream": False,
            "thinking": {"type": "disabled"},
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        response = await self._post_with_retries(payload, headers)
        data = self._parse_json(response)
        text = self._extract_text(data)
        return LLMResponse(
            text=text,
            provider=self.provider_name,
            model=self._extract_model(data, options.model),
            metadata=self._extract_metadata(data),
        )

    async def _post_with_retries(self, payload: dict[str, object], headers: dict[str, str]) -> httpx.Response:
        attempts = self._max_retries + 1
        last_response: httpx.Response | None = None
        for attempt in range(attempts):
            try:
                response = await self._client.post(
                    self._endpoint,
                    json=payload,
                    headers=headers,
                    timeout=self._timeout_seconds,
                )
            except httpx.TimeoutException as exc:
                if attempt + 1 < attempts:
                    continue
                raise ProviderTimeoutError() from exc
            except httpx.RequestError as exc:
                if attempt + 1 < attempts:
                    continue
                raise ProviderUnavailableError("无法连接模型服务，请检查网络后重试。") from exc

            if response.status_code in {408, 500, 502, 503, 504} and attempt + 1 < attempts:
                last_response = response
                continue
            self._raise_for_status(response)
            return response

        if last_response is not None:
            self._raise_for_status(last_response)
        raise ProviderUnavailableError()

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        if response.status_code in {400, 422}:
            raise ProviderInvalidRequestError()
        if response.status_code == 401:
            raise ProviderAuthenticationError()
        if response.status_code == 402:
            raise ProviderInsufficientBalanceError()
        if response.status_code == 429:
            raise ProviderRateLimitError()
        if response.status_code in {500, 502, 503, 504}:
            raise ProviderUnavailableError()
        safe_message = sanitize_error_text(response.text, [self._api_key])
        raise ProviderError(f"模型服务返回错误：{safe_message}")

    def _to_deepseek_messages(self, messages: list[LLMMessage]) -> list[dict[str, str]]:
        allowed_roles = {ChatRole.SYSTEM, ChatRole.USER, ChatRole.ASSISTANT}
        return [
            {"role": message.role.value, "content": message.content}
            for message in messages
            if message.role in allowed_roles
        ]

    def _parse_json(self, response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderInvalidResponseError() from exc
        if not isinstance(data, dict):
            raise ProviderInvalidResponseError()
        return data

    def _extract_text(self, data: dict[str, Any]) -> str:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderInvalidResponseError()
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise ProviderInvalidResponseError()
        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise ProviderInvalidResponseError()
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderInvalidResponseError()
        return content.strip()

    def _extract_model(self, data: dict[str, Any], fallback: str) -> str:
        model = data.get("model")
        return model if isinstance(model, str) and model else fallback

    def _extract_metadata(self, data: dict[str, Any]) -> dict[str, object]:
        metadata: dict[str, object] = {}
        choices = data.get("choices")
        first_choice = choices[0] if isinstance(choices, list) and choices else None
        if isinstance(first_choice, dict):
            self._put_if_present(metadata, "finish_reason", first_choice.get("finish_reason"))
        self._put_if_present(metadata, "completion_id", data.get("id"))
        usage = data.get("usage")
        if isinstance(usage, dict):
            self._put_if_present(metadata, "prompt_tokens", usage.get("prompt_tokens"))
            self._put_if_present(metadata, "completion_tokens", usage.get("completion_tokens"))
            self._put_if_present(metadata, "total_tokens", usage.get("total_tokens"))
            self._put_if_present(metadata, "prompt_cache_hit_tokens", usage.get("prompt_cache_hit_tokens"))
            self._put_if_present(metadata, "prompt_cache_miss_tokens", usage.get("prompt_cache_miss_tokens"))
        return metadata

    def _put_if_present(self, metadata: dict[str, object], key: str, value: object) -> None:
        if value is not None:
            metadata[key] = value
