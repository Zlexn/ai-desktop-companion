import httpx
import pytest

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
)
from app.domain.models import ChatRole
from app.providers.base import LLMMessage, LLMOptions
from app.providers.deepseek_provider import DeepSeekProvider


def settings(**overrides: object) -> Settings:
    values = {
        "llm_provider": "deepseek",
        "llm_model": "deepseek-v4-flash",
        "deepseek_api_key": "deepseek-test-secret",
        "deepseek_base_url": "https://api.deepseek.com",
        "deepseek_thinking_enabled": False,
        "deepseek_max_tokens": 128,
        "deepseek_timeout_seconds": 60.0,
        "deepseek_max_retries": 0,
    }
    values.update(overrides)
    return Settings(**values)


def options(**overrides: object) -> LLMOptions:
    values = {
        "model": "deepseek-v4-flash",
        "timeout_seconds": 30.0,
        "max_retries": 2,
        "max_tokens": 1024,
    }
    values.update(overrides)
    return LLMOptions(**values)


def messages() -> list[LLMMessage]:
    return [
        LLMMessage(ChatRole.SYSTEM, "系统提示"),
        LLMMessage(ChatRole.USER, "第一轮"),
        LLMMessage(ChatRole.ASSISTANT, "已记录"),
        LLMMessage(ChatRole.USER, "第二轮"),
    ]


def success_payload(content: str | None = "好的") -> dict[str, object]:
    return {
        "id": "chatcmpl-test",
        "model": "deepseek-v4-flash",
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 7,
            "completion_tokens": 2,
            "total_tokens": 9,
            "prompt_cache_hit_tokens": 3,
            "prompt_cache_miss_tokens": 4,
        },
    }


def make_provider(handler, **setting_overrides: object) -> tuple[DeepSeekProvider, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(recording_handler))
    return DeepSeekProvider(settings(**setting_overrides), client=client), requests


@pytest.mark.asyncio
async def test_deepseek_provider_sends_chat_completion_payload() -> None:
    provider, requests = make_provider(lambda request: httpx.Response(200, json=success_payload("  已记录  ")))

    result = await provider.generate(messages(), options(max_tokens=64))

    assert result.text == "已记录"
    assert result.provider == "deepseek"
    assert result.model == "deepseek-v4-flash"
    assert result.metadata == {
        "finish_reason": "stop",
        "completion_id": "chatcmpl-test",
        "prompt_tokens": 7,
        "completion_tokens": 2,
        "total_tokens": 9,
        "prompt_cache_hit_tokens": 3,
        "prompt_cache_miss_tokens": 4,
    }
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.deepseek.com/chat/completions"
    assert request.headers["authorization"] == "Bearer deepseek-test-secret"
    payload = request.read()
    assert b"deepseek-test-secret" not in payload
    assert request.content == payload


@pytest.mark.asyncio
async def test_deepseek_provider_request_body_contains_allowed_stage1_fields() -> None:
    provider, requests = make_provider(lambda request: httpx.Response(200, json=success_payload("ok")))

    await provider.generate(messages(), options(max_tokens=512))

    payload = __import__("json").loads(requests[0].content.decode("utf-8"))
    assert payload == {
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": "系统提示"},
            {"role": "user", "content": "第一轮"},
            {"role": "assistant", "content": "已记录"},
            {"role": "user", "content": "第二轮"},
        ],
        "max_tokens": 128,
        "stream": False,
        "thinking": {"type": "disabled"},
    }


@pytest.mark.asyncio
async def test_deepseek_provider_clamps_max_tokens_to_stage_limit() -> None:
    provider, requests = make_provider(
        lambda request: httpx.Response(200, json=success_payload("ok")),
        deepseek_max_tokens=256,
    )

    await provider.generate(messages(), options(max_tokens=1024))

    payload = __import__("json").loads(requests[0].content.decode("utf-8"))
    assert payload["max_tokens"] == 256


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"model": "deepseek-v4-flash", "choices": []},
        {"model": "deepseek-v4-flash", "choices": [{"message": None}]},
        success_payload(None),
        success_payload(""),
        success_payload("   "),
    ],
)
async def test_deepseek_provider_rejects_invalid_responses(payload: dict[str, object] | None) -> None:
    provider, _ = make_provider(lambda request: httpx.Response(200, json=payload))

    with pytest.raises(ProviderInvalidResponseError):
        await provider.generate(messages(), options())


def test_deepseek_provider_requires_api_key() -> None:
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY is required"):
        DeepSeekProvider(settings(deepseek_api_key=None))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (400, ProviderInvalidRequestError),
        (401, ProviderAuthenticationError),
        (402, ProviderInsufficientBalanceError),
        (422, ProviderInvalidRequestError),
        (429, ProviderRateLimitError),
        (500, ProviderUnavailableError),
        (503, ProviderUnavailableError),
    ],
)
async def test_deepseek_provider_maps_http_status_errors(status_code: int, expected: type[Exception]) -> None:
    provider, _ = make_provider(lambda request: httpx.Response(status_code, text="upstream failed"))

    with pytest.raises(expected) as raised:
        await provider.generate(messages(), options())

    serialized = str(raised.value).lower()
    assert "deepseek-test-secret" not in serialized
    assert "authorization" not in serialized
    assert "traceback" not in serialized


@pytest.mark.asyncio
async def test_deepseek_provider_sanitizes_unexpected_status_body() -> None:
    provider, _ = make_provider(lambda request: httpx.Response(418, text="token deepseek-test-secret failed"))

    with pytest.raises(ProviderError) as raised:
        await provider.generate(messages(), options())

    serialized = str(raised.value)
    assert "deepseek-test-secret" not in serialized
    assert "***" in serialized


@pytest.mark.asyncio
async def test_deepseek_provider_maps_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    provider, _ = make_provider(handler)

    with pytest.raises(ProviderTimeoutError):
        await provider.generate(messages(), options())


@pytest.mark.asyncio
async def test_deepseek_provider_maps_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connect failed", request=request)

    provider, _ = make_provider(handler)

    with pytest.raises(ProviderUnavailableError):
        await provider.generate(messages(), options())


@pytest.mark.asyncio
async def test_deepseek_provider_retries_retryable_errors() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, text="try again")
        return httpx.Response(200, json=success_payload("重试成功"))

    provider, _ = make_provider(handler, deepseek_max_retries=1)

    result = await provider.generate(messages(), options())

    assert attempts == 2
    assert result.text == "重试成功"
