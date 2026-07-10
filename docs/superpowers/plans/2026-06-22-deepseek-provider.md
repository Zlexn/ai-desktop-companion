# DeepSeek Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish Stage 1 DeepSeek text-chat Provider integration using the existing provider boundary, mocked automated tests, and one real smoke test that never exposes API key material.

**Architecture:** Keep `ChatService` provider-agnostic and isolate DeepSeek HTTP payloads, parsing, retries, and error mapping in `backend/app/providers/deepseek_provider.py`. Use `httpx.AsyncClient` directly, selected by `LLM_PROVIDER=deepseek` through `backend/app/providers/factory.py`, and reuse existing `ProviderError` subclasses for safe user-facing failures.

**Tech Stack:** Python 3.11+, FastAPI, pytest, pytest-asyncio, httpx, SQLite, existing React/Vite frontend.

---

## Scope and invariants

- Current phase remains Stage 1: role text chat only.
- Do not implement voice, long-term memory, emotion state, streaming, tools, or memory extraction.
- Do not print or log `DEEPSEEK_API_KEY`, its value, prefix, length, request `Authorization` header, full `.env`, full request payloads, or raw provider responses.
- Only check whether `DEEPSEEK_API_KEY` exists.
- Default automated tests must not call the real DeepSeek API.
- Do not add a new provider SDK. The approved design uses `httpx` directly.
- Do not change public chat API metadata beyond the existing `provider` and `model` fields.
- Do not commit changes unless the user explicitly asks for a commit.

## File structure

- Modify `backend/pyproject.toml`
  - Ensure `httpx>=0.27.0` is present.
  - Remove the OpenAI SDK dependency if it is only used by the current DeepSeek draft.
- Modify `backend/app/core/config.py`
  - Keep DeepSeek provider selection, key requirement, base URL, timeout, retry count, max token cap, Stage 1 thinking guard, and redaction.
- Modify `backend/app/core/logging.py`
  - Keep DeepSeek key redaction in app and uvicorn logs.
- Modify `backend/app/providers/base.py`
  - Keep optional `LLMResponse.metadata` for provider metrics if already present.
- Replace `backend/app/providers/deepseek_provider.py`
  - Implement the DeepSeek adapter with `httpx.AsyncClient`.
- Modify `backend/app/providers/factory.py`
  - Construct `DeepSeekProvider` for `LLM_PROVIDER=deepseek`.
- Modify `backend/app/services/chat_service.py`
  - Keep provider metrics persisted in assistant message metadata if already present; do not change public response shape.
- Modify `backend/tests/test_config.py`
  - Cover DeepSeek configuration validation and redaction.
- Replace `backend/tests/test_deepseek_provider.py`
  - Mock HTTP behavior without network calls.
- Modify `backend/tests/test_provider_factory.py`
  - Cover DeepSeek factory creation and no silent fallback.
- Modify `.env.example`
  - Document DeepSeek configuration with an empty sample key value only.
- Modify `README.md`
  - Document DeepSeek setup, tests, and safe smoke verification.
- Optionally modify `docs/`
  - Record verification commands and outcomes without secret material.

---

### Task 1: Align dependencies with the approved httpx design

**Files:**
- Modify: `backend/pyproject.toml`
- Read-check: `backend/app/providers/deepseek_provider.py`
- Read-check: `backend/tests/test_deepseek_provider.py`

- [ ] **Step 1: Confirm OpenAI SDK is only used by the DeepSeek draft**

Run:

```powershell
rg -n "openai|AsyncOpenAI|APIStatusError|RateLimitError" backend
```

Expected before this task: matches are limited to `backend/app/providers/deepseek_provider.py`, `backend/tests/test_deepseek_provider.py`, and `backend/pyproject.toml`. If another production file uses `openai`, stop and reassess before removing the dependency.

- [ ] **Step 2: Update backend dependencies**

Edit `backend/pyproject.toml` so the dependency block is:

```toml
dependencies = [
    "anthropic>=0.72.0",
    "fastapi>=0.115.0",
    "httpx>=0.27.0",
    "pydantic>=2.8.0",
    "pydantic-settings>=2.4.0",
    "pyyaml>=6.0.2",
    "uvicorn[standard]>=0.30.0",
]
```

- [ ] **Step 3: Install backend dependencies**

Run:

```powershell
.\.venv\Scripts\python.exe -m pip install -e "backend[dev]"
```

Expected: pip completes successfully. This command must not include API key material.

- [ ] **Step 4: Verify the OpenAI SDK import is gone after provider/test replacement tasks**

Run this after Task 4 replaces the provider and tests:

```powershell
rg -n "openai|AsyncOpenAI|APIStatusError|RateLimitError" backend
```

Expected after Task 4: no matches in backend source or tests.

---

### Task 2: Keep DeepSeek configuration and redaction complete

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/core/logging.py`
- Test: `backend/tests/test_config.py`

- [ ] **Step 1: Ensure config tests cover DeepSeek**

`backend/tests/test_config.py` must include these tests. Add any missing test exactly as shown and keep existing equivalent tests if they already match this behavior.

```python
def test_deepseek_provider_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")

    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY is required"):
        load_settings()


def test_deepseek_provider_accepts_defaults_and_redacts_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-secret")

    settings = load_settings()

    assert settings.llm_provider == "deepseek"
    assert settings.deepseek_api_key == "deepseek-test-secret"
    assert settings.deepseek_base_url == "https://api.deepseek.com"
    assert settings.llm_model == "deepseek-v4-flash"
    assert settings.deepseek_thinking_enabled is False
    assert settings.deepseek_max_tokens == 256
    assert settings.deepseek_timeout_seconds == 120.0
    assert settings.deepseek_max_retries == 0
    assert settings.redacted()["deepseek_api_key"] == "***"
    assert "deepseek-test-secret" not in str(settings.redacted())


def test_deepseek_settings_allow_safe_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-secret")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("LLM_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("DEEPSEEK_THINKING_ENABLED", "false")
    monkeypatch.setenv("DEEPSEEK_MAX_TOKENS", "128")
    monkeypatch.setenv("DEEPSEEK_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("DEEPSEEK_MAX_RETRIES", "0")

    settings = load_settings()

    assert settings.deepseek_base_url == "https://api.deepseek.com"
    assert settings.llm_model == "deepseek-v4-flash"
    assert settings.deepseek_thinking_enabled is False
    assert settings.deepseek_max_tokens == 128
    assert settings.deepseek_timeout_seconds == 60.0
    assert settings.deepseek_max_retries == 0


def test_deepseek_thinking_must_remain_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-secret")
    monkeypatch.setenv("DEEPSEEK_THINKING_ENABLED", "true")

    with pytest.raises(ValueError, match="DEEPSEEK_THINKING_ENABLED must be false"):
        load_settings()


def test_deepseek_max_tokens_cannot_exceed_stage_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-secret")
    monkeypatch.setenv("DEEPSEEK_MAX_TOKENS", "257")

    with pytest.raises(ValueError, match="DEEPSEEK_MAX_TOKENS must be less than or equal to 256"):
        load_settings()
```

Also ensure the `clear_env` fixture deletes these names:

```python
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_THINKING_ENABLED",
        "DEEPSEEK_MAX_TOKENS",
        "DEEPSEEK_TIMEOUT_SECONDS",
        "DEEPSEEK_MAX_RETRIES",
```

- [ ] **Step 2: Ensure `config.py` implements the tested behavior**

`backend/app/core/config.py` must contain these defaults and fields:

```python
DEFAULT_DATABASE_URL = "sqlite:///./data/app.db"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
```

```python
    deepseek_api_key: str | None = None
    deepseek_base_url: str = DEFAULT_DEEPSEEK_BASE_URL
    deepseek_thinking_enabled: bool = False
    deepseek_max_tokens: int = 256
    deepseek_timeout_seconds: float = 120.0
    deepseek_max_retries: int = 0
```

`Settings.redacted()` must include:

```python
            "deepseek_api_key": "***" if self.deepseek_api_key else None,
            "deepseek_base_url": self.deepseek_base_url,
            "deepseek_thinking_enabled": self.deepseek_thinking_enabled,
            "deepseek_max_tokens": self.deepseek_max_tokens,
            "deepseek_timeout_seconds": self.deepseek_timeout_seconds,
            "deepseek_max_retries": self.deepseek_max_retries,
```

`load_settings()` must validate DeepSeek like this:

```python
    provider = _get_env("LLM_PROVIDER", "fake").lower()
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY") or None
    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY") or None
    deepseek_thinking_enabled = _get_bool_env("DEEPSEEK_THINKING_ENABLED", False)

    if provider not in {"fake", "anthropic", "deepseek"}:
        raise ValueError("LLM_PROVIDER must be one of: fake, anthropic, deepseek")
    if provider == "anthropic" and not anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
    if provider == "deepseek" and not deepseek_api_key:
        raise ValueError("DEEPSEEK_API_KEY is required when LLM_PROVIDER=deepseek")
    if provider == "deepseek" and deepseek_thinking_enabled:
        raise ValueError("DEEPSEEK_THINKING_ENABLED must be false in stage 1")
```

The returned `Settings(...)` must pass:

```python
        deepseek_api_key=deepseek_api_key,
        deepseek_base_url=_get_env("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL),
        deepseek_thinking_enabled=deepseek_thinking_enabled,
        deepseek_max_tokens=_get_int_env_with_max("DEEPSEEK_MAX_TOKENS", 256, 256),
        deepseek_timeout_seconds=_get_float_env("DEEPSEEK_TIMEOUT_SECONDS", 120.0),
        deepseek_max_retries=_get_int_env("DEEPSEEK_MAX_RETRIES", 0),
```

- [ ] **Step 3: Ensure logging redacts DeepSeek key**

`backend/app/core/logging.py` must install the redaction filter with both provider keys:

```python
    redaction_filter = SecretRedactionFilter([settings.anthropic_api_key, settings.deepseek_api_key])
```

- [ ] **Step 4: Run config tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_config.py -v
```

Expected: all config tests pass.

---

### Task 3: Preserve provider metadata without changing the public API

**Files:**
- Modify: `backend/app/providers/base.py`
- Modify: `backend/app/services/chat_service.py`
- Test: `backend/tests/test_chat_service.py`

- [ ] **Step 1: Ensure `LLMResponse` supports internal metadata**

`backend/app/providers/base.py` must import `field` and define `LLMResponse` as:

```python
from dataclasses import dataclass, field
from typing import Protocol
```

```python
@dataclass(frozen=True)
class LLMResponse:
    text: str
    provider: str
    model: str
    metadata: dict[str, object] = field(default_factory=dict)
```

- [ ] **Step 2: Ensure `ChatService` persists provider metadata only in stored messages**

`backend/app/services/chat_service.py` must store assistant metadata like this:

```python
        assistant_metadata = {"provider": response.provider, "model": response.model}
        assistant_metadata.update(response.metadata)
        self._messages.add(
            session_id,
            ChatRole.ASSISTANT,
            reply,
            assistant_metadata,
        )
```

The returned `ChatReply` must remain:

```python
        return ChatReply(reply=reply, provider=response.provider, model=response.model)
```

- [ ] **Step 3: Add or keep a metadata persistence test**

If `backend/tests/test_chat_service.py` does not already verify metadata persistence, add this test and required imports from the existing test file helpers:

```python
class MetadataProvider:
    async def generate(self, messages: list[LLMMessage], options: LLMOptions) -> LLMResponse:
        return LLMResponse(
            text="带指标的回复",
            provider="deepseek",
            model=options.model,
            metadata={
                "finish_reason": "stop",
                "completion_id": "chatcmpl-test",
                "total_tokens": 9,
            },
        )


@pytest.mark.asyncio
async def test_chat_service_persists_provider_metadata_without_public_shape_change(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'metadata.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("指标")
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            MetadataProvider(),
            Settings(llm_model="deepseek-v4-flash"),
        )

        reply = await service.send_message(session.id, "记录指标")

        stored = messages.list(session.id)
        assert reply.provider == "deepseek"
        assert reply.model == "deepseek-v4-flash"
        assert stored[-1].metadata == {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "finish_reason": "stop",
            "completion_id": "chatcmpl-test",
            "total_tokens": 9,
        }
```

- [ ] **Step 4: Run chat service tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_chat_service.py -v
```

Expected: all chat service tests pass.

---

### Task 4: Replace DeepSeek Provider with an httpx adapter and mocked tests

**Files:**
- Replace: `backend/app/providers/deepseek_provider.py`
- Replace: `backend/tests/test_deepseek_provider.py`

- [ ] **Step 1: Replace provider tests first**

Replace `backend/tests/test_deepseek_provider.py` with:

```python
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
```

- [ ] **Step 2: Run provider tests to verify current draft fails if it still imports OpenAI SDK**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_deepseek_provider.py -v
```

Expected before implementation: tests fail if `DeepSeekProvider` still uses `openai.AsyncOpenAI` or emits the old payload shape.

- [ ] **Step 3: Replace provider implementation**

Replace `backend/app/providers/deepseek_provider.py` with:

```python
from typing import Any

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

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        if not settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY is required when LLM_PROVIDER=deepseek")
        self._settings = settings
        self._api_key = settings.deepseek_api_key
        self._client = client or httpx.AsyncClient()
        self._endpoint = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"

    async def generate(self, messages: list[LLMMessage], options: LLMOptions) -> LLMResponse:
        payload = {
            "model": options.model,
            "messages": self._to_deepseek_messages(messages),
            "max_tokens": min(options.max_tokens, self._settings.deepseek_max_tokens, 256),
            "stream": False,
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
        attempts = self._settings.deepseek_max_retries + 1
        last_response: httpx.Response | None = None
        for attempt in range(attempts):
            try:
                response = await self._client.post(
                    self._endpoint,
                    json=payload,
                    headers=headers,
                    timeout=self._settings.deepseek_timeout_seconds,
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
```

- [ ] **Step 4: Run provider tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_deepseek_provider.py -v
```

Expected: all DeepSeek provider tests pass.

---

### Task 5: Wire provider factory and prevent fallback

**Files:**
- Modify: `backend/app/providers/factory.py`
- Test: `backend/tests/test_provider_factory.py`

- [ ] **Step 1: Ensure factory tests exist**

`backend/tests/test_provider_factory.py` must include:

```python
import pytest

from app.core.config import Settings
from app.providers.deepseek_provider import DeepSeekProvider
from app.providers.factory import create_provider
from app.providers.fake_provider import FakeProvider


def test_factory_creates_fake_provider_by_default() -> None:
    provider = create_provider(Settings(llm_provider="fake"))

    assert isinstance(provider, FakeProvider)


def test_factory_creates_deepseek_provider() -> None:
    provider = create_provider(
        Settings(
            llm_provider="deepseek",
            llm_model="deepseek-v4-flash",
            deepseek_api_key="deepseek-test-secret",
        )
    )

    assert isinstance(provider, DeepSeekProvider)


def test_factory_deepseek_requires_api_key_without_fallback() -> None:
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY is required"):
        create_provider(Settings(llm_provider="deepseek", deepseek_api_key=None))


def test_factory_unknown_provider_does_not_fallback_to_fake() -> None:
    with pytest.raises(ValueError, match="Unsupported LLM_PROVIDER"):
        create_provider(Settings(llm_provider="unknown"))
```

- [ ] **Step 2: Ensure factory imports and constructs DeepSeekProvider**

`backend/app/providers/factory.py` must be:

```python
from app.core.config import Settings
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import LLMProvider
from app.providers.deepseek_provider import DeepSeekProvider
from app.providers.fake_provider import FakeProvider


def create_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "fake":
        return FakeProvider(mode=settings.fake_provider_mode)
    if settings.llm_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
        return AnthropicProvider(settings.anthropic_api_key)
    if settings.llm_provider == "deepseek":
        if not settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY is required when LLM_PROVIDER=deepseek")
        return DeepSeekProvider(settings)
    raise ValueError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")
```

- [ ] **Step 3: Run factory tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_provider_factory.py -v
```

Expected: all factory tests pass.

---

### Task 6: Update safe configuration and user documentation

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Ensure `.env.example` documents DeepSeek without secrets**

The relevant provider block in `.env.example` must include:

```dotenv
# fake | anthropic | deepseek
LLM_PROVIDER=fake
LLM_MODEL=deepseek-v4-flash
LLM_TIMEOUT_SECONDS=30
LLM_MAX_RETRIES=2
FAKE_PROVIDER_MODE=ok
RECENT_CONTEXT_MESSAGES=12

# DeepSeek Provider is optional. Leave DEEPSEEK_API_KEY empty unless using LLM_PROVIDER=deepseek locally.
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_THINKING_ENABLED=false
DEEPSEEK_MAX_TOKENS=256
DEEPSEEK_TIMEOUT_SECONDS=120
DEEPSEEK_MAX_RETRIES=0
```

Keep any existing Anthropic section, and do not add a real key.

- [ ] **Step 2: Update README DeepSeek setup text**

Add or keep a section in `README.md` with this content adapted to the surrounding heading style:

```markdown
### DeepSeek Provider

Stage 1 can use DeepSeek as a real text-chat provider through the same backend Provider interface used by the fake provider.

PowerShell example for local development:

```powershell
$env:LLM_PROVIDER = "deepseek"
$env:LLM_MODEL = "deepseek-v4-flash"
$env:DEEPSEEK_API_KEY = "set-this-in-your-local-shell-only"
$env:DEEPSEEK_BASE_URL = "https://api.deepseek.com"
$env:DEEPSEEK_THINKING_ENABLED = "false"
$env:DEEPSEEK_MAX_TOKENS = "256"
$env:DEEPSEEK_TIMEOUT_SECONDS = "120"
$env:DEEPSEEK_MAX_RETRIES = "0"
```

Do not commit real API keys. Do not place API keys in `VITE_*` variables because Vite exposes those values to frontend code.

Default automated tests use mocked provider behavior and do not call the real DeepSeek API. A manual smoke test may be run only after confirming `DEEPSEEK_API_KEY` exists without printing its value, prefix, or length.
```

- [ ] **Step 3: Add verification command text**

Add this safe verification snippet to README under backend testing or provider verification:

```markdown
Check only whether the DeepSeek key exists:

```powershell
if (Test-Path Env:DEEPSEEK_API_KEY) { "DEEPSEEK_API_KEY exists" } else { "DEEPSEEK_API_KEY missing" }
```

Run mocked backend tests:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_config.py backend/tests/test_provider_factory.py backend/tests/test_deepseek_provider.py -v
```
```

- [ ] **Step 4: Review documentation for secret leakage**

Run:

```powershell
rg -n "sk-|Bearer |DEEPSEEK_API_KEY=.+\S|set-this-in-your-local-shell-only" .env.example README.md docs
```

Expected: the only acceptable match is the README instructional sample value `set-this-in-your-local-shell-only`. `.env.example` must keep `DEEPSEEK_API_KEY=` empty.

---

### Task 7: Run full automated verification

**Files:**
- No source edits expected unless tests reveal a defect.

- [ ] **Step 1: Run focused backend tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_config.py backend/tests/test_provider_factory.py backend/tests/test_deepseek_provider.py backend/tests/test_chat_service.py -v
```

Expected: all focused tests pass.

- [ ] **Step 2: Run full backend suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -v
```

Expected: all backend tests pass.

- [ ] **Step 3: Verify no OpenAI SDK remains**

Run:

```powershell
rg -n "openai|AsyncOpenAI|APIStatusError|RateLimitError" backend
```

Expected: no matches.

- [ ] **Step 4: Verify only key existence is printed**

Run:

```powershell
if (Test-Path Env:DEEPSEEK_API_KEY) { "DEEPSEEK_API_KEY exists" } else { "DEEPSEEK_API_KEY missing" }
```

Expected: `DEEPSEEK_API_KEY exists`. Do not run commands that print the variable value, prefix, length, or full `.env` content.

---

### Task 8: Run the real DeepSeek smoke test safely

**Files:**
- Temporary file only: `$env:TEMP\deepseek_smoke.py`
- No repository source edits expected.

- [ ] **Step 1: Create and run a temporary smoke script without printing secrets**

Run:

```powershell
@'
import asyncio
import os

from app.core.config import load_settings
from app.domain.models import ChatRole
from app.providers.base import LLMMessage, LLMOptions
from app.providers.factory import create_provider


async def main() -> None:
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("DEEPSEEK_API_KEY missing")

    settings = load_settings()
    provider = create_provider(settings)
    response = await provider.generate(
        [
            LLMMessage(ChatRole.SYSTEM, "你是阶段1文字对话连通性测试助手。请用一句简短中文回复。"),
            LLMMessage(ChatRole.USER, "请回复：连接正常。"),
        ],
        LLMOptions(
            model=settings.llm_model,
            timeout_seconds=settings.deepseek_timeout_seconds,
            max_retries=settings.deepseek_max_retries,
            max_tokens=min(settings.deepseek_max_tokens, 64),
        ),
    )
    if not response.text.strip():
        raise SystemExit("DeepSeek smoke failed: empty reply")
    print({"provider": response.provider, "model": response.model, "status": "ok"})


asyncio.run(main())
'@ | Set-Content -Encoding utf8 "$env:TEMP\deepseek_smoke.py"
$env:LLM_PROVIDER = "deepseek"
.\.venv\Scripts\python.exe "$env:TEMP\deepseek_smoke.py"
Remove-Item "$env:TEMP\deepseek_smoke.py"
```

Expected: prints a small dictionary containing `provider`, `model`, and `status`. It must not print the API key, key prefix, key length, Authorization header, full prompt payload, or model reply text.

- [ ] **Step 2: If smoke fails, report only safe failure category**

Use the mapped exception category in the report:

```text
provider_authentication_failed
provider_insufficient_balance
provider_rate_limited
provider_timeout
provider_unavailable
provider_invalid_request
provider_invalid_response
```

Do not paste raw request headers, raw response bodies, full tracebacks containing local secret-bearing environment dumps, or full `.env` contents.

---

### Task 9: Record final validation outcome

**Files:**
- Modify: `README.md` or an existing verification note under `docs/` if the repository already uses one for validation records.

- [ ] **Step 1: Add safe validation summary**

Record commands and results in a concise section like:

```markdown
## DeepSeek Provider validation — 2026-06-22

- `python -m pytest backend/tests -v` — passed.
- `Test-Path Env:DEEPSEEK_API_KEY` — exists.
- Real DeepSeek smoke test — passed with provider/model/status only; no key material printed.
```

If a command fails, record the failed command and safe error category instead of claiming success.

- [ ] **Step 2: Check working tree**

Run:

```powershell
git status --short
```

Expected: shows only intentional source, test, and documentation changes. Do not commit unless the user explicitly requests it.

---

## Self-review against the spec

- Spec requirement: DeepSeek is an `LLMProvider` implementation. Covered by Tasks 4 and 5.
- Spec requirement: use `httpx`, not a new SDK. Covered by Tasks 1, 4, and 7.
- Spec requirement: provider-specific payloads and parsing remain in `deepseek_provider.py`. Covered by Task 4.
- Spec requirement: config reads key from environment and redacts it. Covered by Task 2.
- Spec requirement: error mapping and sanitization. Covered by Task 4 tests and implementation.
- Spec requirement: mocked automated tests. Covered by Tasks 2, 3, 4, 5, and 7.
- Spec requirement: real smoke test without secret leakage. Covered by Task 8.
- Spec requirement: docs and safe configuration examples. Covered by Tasks 6 and 9.
- Scope boundary: no Stage 2 voice, Stage 3 memory, or Stage 4 emotion. Enforced in Scope and invariants.
