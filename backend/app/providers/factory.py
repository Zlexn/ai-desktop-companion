from app.core.config import Settings
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import LLMProvider
from app.providers.deepseek_provider import DeepSeekProvider
from app.providers.fake_provider import FakeProvider


def create_named_provider(
    settings: Settings,
    provider_name: str,
    *,
    deepseek_max_tokens: int | None = None,
    deepseek_timeout_seconds: float | None = None,
    deepseek_max_retries: int | None = None,
) -> LLMProvider:
    if provider_name == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for AnthropicProvider")
        return AnthropicProvider(settings.anthropic_api_key)
    if provider_name == "deepseek":
        return DeepSeekProvider(
            settings,
            max_tokens=deepseek_max_tokens,
            timeout_seconds=deepseek_timeout_seconds,
            max_retries=deepseek_max_retries,
        )
    raise ValueError(f"Unsupported named LLM provider: {provider_name}")


def create_emotion_analysis_provider(settings: Settings) -> LLMProvider | None:
    if not settings.emotion_analysis_enabled:
        return None
    return create_named_provider(
        settings,
        settings.emotion_analysis_provider,
        deepseek_max_tokens=settings.emotion_analysis_max_tokens,
        deepseek_timeout_seconds=settings.emotion_analysis_timeout_seconds,
        deepseek_max_retries=settings.emotion_analysis_max_retries,
    )


def create_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "fake":
        return FakeProvider(mode=settings.fake_provider_mode)
    if settings.llm_provider in {"anthropic", "deepseek"}:
        return create_named_provider(settings, settings.llm_provider)
    raise ValueError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")
