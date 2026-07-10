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
