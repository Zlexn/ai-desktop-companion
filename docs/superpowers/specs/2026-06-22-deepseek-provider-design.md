# DeepSeek Provider Stage 1 Design

Date: 2026-06-22

## Context

The project is in Stage 1: text chat only. The current objective is to finish DeepSeek Provider integration so the app can use a real configurable API supplier while preserving the existing provider abstraction, recent-context chat flow, persistence, and stage boundaries. The user confirmed that `DEEPSEEK_API_KEY` is available in the parent PowerShell environment and instructed that the key may only be checked for existence; its value, prefix, length, and full `.env` content must never be output.

The intended outcome is a minimal, verified DeepSeek text-chat path that can be selected with environment configuration, is covered by mocked automated tests, and is validated by a real smoke test without leaking secrets.

## Recommended Approach

Add or complete DeepSeek as one implementation of the existing `LLMProvider` interface. Keep provider-specific HTTP payloads, response parsing, and error mapping inside `backend/app/providers/deepseek_provider.py`. Keep `backend/app/services/chat_service.py` provider-agnostic unless a compatibility issue is found.

Use the existing `httpx` dependency rather than introducing a new SDK. This keeps the Stage 1 surface small and follows the existing supplier-isolation rule.

## Components and Data Flow

1. `backend/app/core/config.py`
   - Accept `LLM_PROVIDER=deepseek`.
   - Read `DEEPSEEK_API_KEY` only from the environment.
   - Keep DeepSeek settings such as base URL, timeout, retry count, max tokens, and Stage 1 thinking-disable guard.
   - Redact the key in `Settings.redacted()` as `***` only.

2. `backend/app/providers/deepseek_provider.py`
   - Implement `LLMProvider.generate(messages, options)`.
   - Convert internal `LLMMessage` objects into DeepSeek/OpenAI-compatible chat message payloads.
   - Call the chat completions endpoint with the configured model, max tokens, timeout, and retry behavior.
   - Return `LLMResponse(text=..., provider="deepseek", model=...)`.
   - Reject empty or malformed responses with `ProviderInvalidResponseError`.

3. `backend/app/providers/factory.py`
   - Add a `deepseek` branch that constructs `DeepSeekProvider` from `Settings`.
   - Preserve existing `fake` and `anthropic` behavior.

4. `backend/app/core/errors.py`
   - Reuse existing provider error classes and sanitization helpers.
   - Ensure DeepSeek errors sanitize the DeepSeek key before surfacing messages.

5. Documentation
   - Update `.env.example` with DeepSeek placeholders only, never a real key.
   - Update `README.md` with provider selection, DeepSeek setup, tests, and smoke-test instructions.
   - If verification records are maintained under `docs/`, add the actual commands and outcomes without secret material.

## Error Handling

Map provider failures into the existing Stage 1 error model:

- Timeout: `ProviderTimeoutError`
- HTTP 429: `ProviderRateLimitError`
- Empty or malformed assistant content: `ProviderInvalidResponseError`
- Other HTTP/network failures: `ProviderError`

Error text must not include API keys or sensitive request headers. Any provider-supplied message should pass through the existing sanitization path with the DeepSeek key included in the secret list.

## Testing Plan

Automated tests should avoid real network calls.

- `backend/tests/test_config.py`
  - accepts DeepSeek when a key exists
  - rejects DeepSeek when the key is missing
  - rejects Stage 1 thinking mode for DeepSeek
  - redacts the DeepSeek key
  - keeps invalid-provider validation accurate

- `backend/tests/test_provider_factory.py`
  - creates `DeepSeekProvider` for `LLM_PROVIDER=deepseek`
  - preserves fake/Anthropic factory behavior

- `backend/tests/test_deepseek_provider.py`
  - successful response parsing
  - empty/malformed response handling
  - timeout mapping
  - rate-limit mapping
  - HTTP/network error mapping
  - secret redaction in surfaced provider errors

- Existing chat service/API tests should continue passing and should remain provider-agnostic where possible.

## End-to-End Verification

After implementation:

1. Run the backend test suite with pytest.
2. Check that `DEEPSEEK_API_KEY` exists without printing value, prefix, length, or `.env` content.
3. Run a minimal real DeepSeek smoke test through the app or backend provider path using the parent environment variable.
4. Report provider/model/status and success or failure category only; do not report any key-derived material.

## Scope Boundaries

- Do not implement Stage 2 voice, Stage 3 long-term memory, or Stage 4 emotion features.
- Do not add a new provider SDK unless `httpx` proves insufficient.
- Do not change role prompt semantics beyond what is necessary for DeepSeek compatibility.
- Do not log secrets or dump environment files.
