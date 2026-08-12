import pytest

from app.api.dependencies import build_session_summary_provider
from app.core.config import Settings
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.deepseek_provider import DeepSeekProvider
from app.providers.factory import (
    create_emotion_analysis_provider,
    create_memory_extractor_provider,
    create_named_provider,
    create_provider,
    memory_extractor_provider_is_configured,
)
from app.providers.fake_provider import FakeProvider


def test_direct_remote_summary_factory_misuse_fails_before_llm_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def forbidden(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("remote provider constructed")

    monkeypatch.setattr("app.providers.factory.create_named_provider", forbidden)
    with pytest.raises(ValueError, match="fenced Task 7 worker"):
        build_session_summary_provider(
            Settings(
                session_summary_provider="llm",
                session_summary_llm_provider="deepseek",
                deepseek_api_key="test-only",
            )
        )
    assert calls == 0


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


def test_memory_extractor_factory_creates_selected_anthropic_provider() -> None:
    provider = create_memory_extractor_provider(
        Settings(
            memory_extractor_provider="anthropic",
            anthropic_api_key="anthropic-test-secret",
        )
    )

    assert isinstance(provider, AnthropicProvider)


def test_memory_extractor_factory_creates_selected_deepseek_provider_with_memory_settings() -> None:
    provider = create_memory_extractor_provider(
        Settings(
            memory_extractor_provider="deepseek",
            deepseek_api_key="deepseek-test-secret",
            memory_extractor_max_tokens=768,
            memory_extractor_timeout_seconds=21.0,
            memory_extractor_max_retries=1,
        )
    )

    assert isinstance(provider, DeepSeekProvider)
    assert provider._max_tokens == 768
    assert provider._timeout_seconds == 21.0
    assert provider._max_retries == 1


@pytest.mark.parametrize(
    ("provider_name", "settings_kwargs"),
    [
        ("anthropic", {"anthropic_api_key": "anthropic-test-secret"}),
        ("deepseek", {"deepseek_api_key": "deepseek-test-secret"}),
    ],
)
def test_memory_extractor_provider_is_configured_checks_selected_provider_credential(
    provider_name: str,
    settings_kwargs: dict[str, str],
) -> None:
    assert memory_extractor_provider_is_configured(
        Settings(memory_extractor_provider=provider_name, **settings_kwargs)
    )


@pytest.mark.parametrize(
    ("provider_name", "settings_kwargs"),
    [
        ("anthropic", {"deepseek_api_key": "deepseek-test-secret"}),
        ("deepseek", {"anthropic_api_key": "anthropic-test-secret"}),
    ],
)
def test_memory_extractor_provider_is_configured_rejects_other_provider_credential(
    provider_name: str,
    settings_kwargs: dict[str, str],
) -> None:
    assert not memory_extractor_provider_is_configured(
        Settings(memory_extractor_provider=provider_name, **settings_kwargs)
    )


def test_memory_extractor_factory_fails_closed_for_unknown_provider() -> None:
    settings = Settings(memory_extractor_provider="unknown")

    with pytest.raises(ValueError, match="Unsupported named LLM provider: unknown"):
        create_memory_extractor_provider(settings)


def test_memory_extractor_configuration_check_fails_closed_for_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported memory extractor provider: unknown"):
        memory_extractor_provider_is_configured(
            Settings(memory_extractor_provider="unknown")
        )
