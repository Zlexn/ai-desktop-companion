from datetime import UTC, datetime

import pytest

from app.core.errors import ContextBudgetInvariantError
from app.domain.models import ChatRole
from app.domain.session_summary import SummarySourceFragment
from app.domain.persona import PersonaArtifact, PersonaPayloadState
from app.services.context_composer import ContextComposer, ContextCompositionRequest
from app.services.context_data_encoder import ContextDataEncoder
from app.core.config import Settings
from app.providers.base import ChatDispatchBudget, LLMMessage, LLMOptions
from app.providers.fake_provider import FakeProvider
from app.providers.payload_normalization import (
    AnthropicPayloadView,
    RoleMessagePayloadView,
    normalize_provider_payload,
    provider_character_count,
)


MESSAGES = [
    LLMMessage(ChatRole.SYSTEM, "persona"),
    LLMMessage(ChatRole.SYSTEM, "dynamic"),
    LLMMessage(ChatRole.USER, "hello"),
    LLMMessage(ChatRole.ASSISTANT, "reply"),
]


def test_anthropic_count_matches_merged_system_payload() -> None:
    payload = normalize_provider_payload("anthropic", MESSAGES)

    assert isinstance(payload, AnthropicPayloadView)
    assert payload.system == "persona\n\ndynamic"
    assert payload.conversation == (
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "reply"},
    )
    assert payload.character_count == len(payload.system) + sum(
        len(item["content"]) for item in payload.conversation
    )
    assert provider_character_count("anthropic", MESSAGES) == payload.character_count


def test_deepseek_count_matches_forwarded_roles() -> None:
    payload = normalize_provider_payload("deepseek", MESSAGES)

    assert isinstance(payload, RoleMessagePayloadView)
    assert payload.messages == tuple(
        {"role": message.role.value, "content": message.content}
        for message in MESSAGES
    )
    assert payload.character_count == sum(len(message.content) for message in MESSAGES)


def test_fake_and_unknown_use_conservative_role_view() -> None:
    fake = normalize_provider_payload("fake", MESSAGES)
    unknown = normalize_provider_payload("future-provider", MESSAGES)

    assert isinstance(fake, RoleMessagePayloadView)
    assert isinstance(unknown, RoleMessagePayloadView)
    assert fake.messages == unknown.messages
    assert unknown.character_count == sum(len(message.content) for message in MESSAGES) + 2


def _summary_composition(provider_name: str):
    now = datetime(2026, 7, 23, tzinfo=UTC)
    persona = PersonaArtifact(
        id="persona",
        version=1,
        payload_state=PersonaPayloadState.ACTIVE,
        schema_version="persona-schema-v1",
        ruleset_version="persona-ruleset-v1",
        template_version="persona-template-v1",
        compiler_version="persona-compiler-v1",
        source_content={},
        rendered_system_prompt="persona",
        content_identity_hash="a" * 64,
        behavior_fingerprint="b" * 64,
        created_at=now,
        redacted_at=None,
        redaction_reason_code=None,
    )
    summary = SummarySourceFragment(
        summary_id="summary",
        source_session_id="source-session",
        source_kind="generated",
        created_at=now,
        summary_text="low trust continuity",
        observed_barrier_generation=0,
        source_set_hash="private-hash",
        suppression_generation=0,
        suppression_state=None,
        summarizer_schema_version="session-summary-v2",
        injection_schema_version="summary-injection-v1",
        source_turn_ids=("private-turn",),
        source_message_ids=("private-user", "private-assistant"),
    )
    return ContextComposer(Settings(), ContextDataEncoder()).compose(
        ContextCompositionRequest(
            provider_name=provider_name,
            session_id="session",
            current_user_message_id="current",
            current_user_text="hello",
            persona=persona,
            recent_messages=(),
            memories=(),
            emotion=None,
            summaries=(summary,),
        )
    )


@pytest.mark.parametrize("provider_name", ["anthropic", "deepseek"])
def test_summary_payload_survives_adapter_normalization_as_system_data(
    provider_name: str,
) -> None:
    composition = _summary_composition(provider_name)
    payload = normalize_provider_payload(
        provider_name,
        list(composition.provider_messages),
    )

    assert "low trust continuity" in str(payload)
    assert "low_trust_session_summary" in str(payload)
    assert "private-hash" not in str(payload)
    assert payload.character_count == composition.provider_character_count
    assert composition.selected_summary_ids == ("summary",)


@pytest.mark.asyncio
async def test_fake_provider_rejects_budget_mismatch_before_recording() -> None:
    provider = FakeProvider()
    options = LLMOptions(
        model="fake",
        timeout_seconds=1,
        max_retries=0,
        chat_dispatch_budget=ChatDispatchBudget(
            expected_normalized_characters=1,
            max_normalized_characters=1,
        ),
    )

    with pytest.raises(ContextBudgetInvariantError):
        await provider.generate(MESSAGES, options)
    assert provider.calls == []


@pytest.mark.asyncio
async def test_fake_provider_allows_non_chat_calls_without_budget_assertion() -> None:
    provider = FakeProvider()
    response = await provider.generate(
        MESSAGES,
        LLMOptions(model="fake", timeout_seconds=1, max_retries=0),
    )
    assert response.provider == "fake"
    assert provider.calls == [MESSAGES]
