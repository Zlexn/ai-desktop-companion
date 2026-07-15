import pytest

from app.core.config import Settings
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.deepseek_provider import DeepSeekProvider
from app.providers.factory import create_emotion_analysis_provider, create_named_provider, create_provider
from app.providers.fake_provider import FakeProvider


def test_factory_creates_emotion_analysis_provider_with_independent_settings() -> None:
    settings = Settings(
        deepseek_api_key="deepseek-test-secret",
        emotion_analysis_enabled=True,
        emotion_analysis_provider="deepseek",
        emotion_analysis_max_tokens=384,
        emotion_analysis_timeout_seconds=9.0,
        emotion_analysis_max_retries=0,
    )

    provider = create_emotion_analysis_provider(settings)

    assert isinstance(provider, DeepSeekProvider)
    assert provider._max_tokens == 384
    assert provider._timeout_seconds == 9.0
    assert provider._max_retries == 0


def test_factory_does_not_create_emotion_analysis_provider_when_disabled() -> None:
    assert create_emotion_analysis_provider(Settings(emotion_analysis_enabled=False)) is None


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


def test_named_factory_creates_deepseek_with_independent_overrides() -> None:
    provider = create_named_provider(
        Settings(deepseek_api_key="deepseek-test-secret"),
        "deepseek",
        deepseek_max_tokens=512,
        deepseek_timeout_seconds=15.0,
        deepseek_max_retries=0,
    )

    assert isinstance(provider, DeepSeekProvider)


def test_named_factory_creates_anthropic_provider() -> None:
    provider = create_named_provider(
        Settings(anthropic_api_key="anthropic-test-secret"),
        "anthropic",
    )

    assert isinstance(provider, AnthropicProvider)


@pytest.mark.parametrize(
    ("provider_name", "configured_settings", "message"),
    [
        ("anthropic", Settings(anthropic_api_key=None), "ANTHROPIC_API_KEY is required"),
        ("deepseek", Settings(deepseek_api_key=None), "DEEPSEEK_API_KEY is required"),
    ],
)
def test_named_factory_requires_real_provider_credentials(
    provider_name: str,
    configured_settings: Settings,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        create_named_provider(configured_settings, provider_name)


def test_named_factory_rejects_fake_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported named LLM provider: fake"):
        create_named_provider(Settings(), "fake")
