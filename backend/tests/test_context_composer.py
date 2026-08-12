from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import Settings
from app.domain.models import ChatRole, MemoryType, MemoryVersionSourceKind, Message
from app.domain.session_summary import SummarySourceFragment
from app.domain.persona import PersonaArtifact, PersonaPayloadState
from app.repositories.memories import StructuredMemoryContextSource
from app.services.context_composer import (
    ContextComposer,
    ContextCompositionRequest,
    ContextProtectedOverflowError,
)
from app.services.context_data_encoder import ContextDataEncoder, EmotionExpressionView


NOW = datetime(2026, 7, 21, tzinfo=UTC)


def _persona(prompt: str = "persona rules") -> PersonaArtifact:
    return PersonaArtifact(
        id="persona-1",
        version=1,
        payload_state=PersonaPayloadState.ACTIVE,
        schema_version="persona-schema-v1",
        ruleset_version="persona-ruleset-v1",
        template_version="persona-template-v1",
        compiler_version="persona-compiler-v1",
        source_content={"identity": {"name": "test"}},
        rendered_system_prompt=prompt,
        content_identity_hash="a" * 64,
        behavior_fingerprint="b" * 64,
        created_at=NOW,
        redacted_at=None,
        redaction_reason_code=None,
    )


def _message(index: int, role: ChatRole, content: str | None = None) -> Message:
    return Message(
        id=f"message-{index}",
        session_id="session-1",
        role=role,
        content=content or f"message content {index}",
        created_at=NOW + timedelta(seconds=index),
        metadata={},
    )


def _memory(
    index: int,
    *,
    source_kind: MemoryVersionSourceKind = MemoryVersionSourceKind.MANUAL,
    memory_type: MemoryType = MemoryType.PREFERENCE,
    content: str | None = None,
) -> StructuredMemoryContextSource:
    return StructuredMemoryContextSource(
        memory_id=f"memory-{index}",
        current_version_id=f"version-{index}",
        source_kind=source_kind,
        content=content or f"memory content {index}",
        memory_type=memory_type,
        importance=3,
        confidence=0.8,
        updated_at=NOW + timedelta(seconds=index),
        relevance_score=float(10 - index),
        legacy_compat=False,
    )


def _summary(
    index: int,
    *,
    content: str | None = None,
) -> SummarySourceFragment:
    return SummarySourceFragment(
        summary_id=f"summary-{index}",
        source_session_id=f"source-session-{index}",
        source_kind="generated",
        created_at=NOW + timedelta(seconds=index),
        summary_text=content or f"summary content {index}",
        observed_barrier_generation=1,
        source_set_hash=f"private-hash-{index}",
        suppression_generation=0,
        suppression_state=None,
        summarizer_schema_version="session-summary-v2",
        injection_schema_version="summary-injection-v1",
        source_turn_ids=(f"turn-{index}",),
        source_message_ids=(f"user-{index}", f"assistant-{index}"),
    )


def _request(
    *,
    recent=(),
    memories=(),
    emotion=None,
    summaries=(),
    current_text="current user",
    persona=None,
) -> ContextCompositionRequest:
    return ContextCompositionRequest(
        provider_name="fake",
        session_id="session-1",
        current_user_message_id="current-id",
        current_user_text=current_text,
        persona=persona or _persona(),
        recent_messages=tuple(recent),
        memories=tuple(memories),
        emotion=emotion,
        summaries=tuple(summaries),
    )


def _composer(**settings_overrides) -> ContextComposer:
    return ContextComposer(
        Settings(**settings_overrides),
        ContextDataEncoder(),
    )


def test_persona_first_current_user_exact_once_and_last() -> None:
    result = _composer().compose(
        _request(
            recent=(
                _message(1, ChatRole.USER),
                _message(2, ChatRole.ASSISTANT),
            ),
            memories=(_memory(1),),
        )
    )

    assert result.provider_messages[0].role is ChatRole.SYSTEM
    assert result.provider_messages[0].content == "persona rules"
    assert result.provider_messages[-1].role is ChatRole.USER
    assert result.provider_messages[-1].content == "current user"
    assert sum(message.content == "current user" for message in result.provider_messages) == 1
    assert result.selected_recent_message_ids == ("message-1", "message-2")
    assert result.selected_memory_version_ids == ("version-1",)


def test_distinct_ids_with_equal_content_are_valid_and_deterministic() -> None:
    result = _composer().compose(
        _request(
            recent=(
                _message(2, ChatRole.ASSISTANT, "same"),
                _message(1, ChatRole.USER, "same"),
            )
        )
    )
    assert result.selected_recent_message_ids == ("message-1", "message-2")


@pytest.mark.parametrize(
    "composition_request",
    [
        _request(recent=(_message(1, ChatRole.USER), _message(1, ChatRole.USER))),
        ContextCompositionRequest(
            **{
                **_request().__dict__,
                "recent_messages": (
                    Message(
                        id="current-id",
                        session_id="session-1",
                        role=ChatRole.USER,
                        content="current user",
                        created_at=NOW,
                        metadata={},
                    ),
                ),
            }
        ),
        _request(memories=(_memory(1), _memory(1))),
    ],
)
def test_composer_rejects_duplicate_or_current_ids(composition_request) -> None:
    with pytest.raises(ValueError):
        _composer().compose(composition_request)


def test_memory_selection_is_stable_across_shuffled_input() -> None:
    memories = (_memory(3), _memory(1), _memory(2))
    first = _composer().compose(_request(memories=memories))
    second = _composer().compose(_request(memories=tuple(reversed(memories))))
    assert first.selected_memory_version_ids == second.selected_memory_version_ids
    assert first.provider_messages == second.provider_messages


def test_dynamic_limit_removes_automatic_before_manual() -> None:
    automatic = _memory(
        1,
        source_kind=MemoryVersionSourceKind.AUTOMATIC,
        content="A" * 250,
    )
    manual = _memory(2, content="manual")
    result = _composer(chat_dynamic_context_max_characters=512).compose(
        _request(memories=(automatic, manual))
    )
    assert result.selected_memory_version_ids == ("version-2",)


def test_soft_minimum_removes_from_type_above_its_own_minimum() -> None:
    preferences = (
        _memory(1, memory_type=MemoryType.PREFERENCE),
        _memory(2, memory_type=MemoryType.PREFERENCE),
    )
    user_fact = _memory(3, memory_type=MemoryType.USER_FACT)
    request = _request(memories=(*preferences, user_fact))
    baseline = _composer().compose(request)
    result = _composer().compose(
        request,
        max_characters=baseline.provider_character_count - 1,
    )
    assert "version-3" in result.selected_memory_version_ids
    assert len(
        [version for version in result.selected_memory_version_ids if version in {"version-1", "version-2"}]
    ) == 1


def test_same_memory_id_with_different_versions_is_rejected() -> None:
    first = _memory(1)
    second = StructuredMemoryContextSource(
        **{**first.__dict__, "current_version_id": "version-other"}
    )
    with pytest.raises(ValueError, match="duplicate memory identity"):
        _composer().compose(_request(memories=(first, second)))


def test_memory_type_item_and_character_limits_remove_whole_items() -> None:
    result = _composer(
        memory_context_preference_max_items=1,
        memory_context_preference_max_characters=200,
    ).compose(
        _request(memories=(_memory(1), _memory(2), _memory(3)))
    )

    assert result.selected_memory_version_ids == ("version-1",)
    assert result.trim_decisions[0].reason_code == "memory_type_limit"
    assert result.trim_decisions[0].count == 2


def test_automatic_memory_is_removed_before_user_memory() -> None:
    user_memory = _memory(1)
    automatic = _memory(2, source_kind=MemoryVersionSourceKind.AUTOMATIC)
    request = _request(memories=(user_memory, automatic))
    baseline = _composer().compose(request)
    maximum = baseline.provider_character_count - len(automatic.content)

    result = _composer().compose(request, max_characters=maximum)

    assert "version-1" in result.selected_memory_version_ids
    assert "version-2" not in result.selected_memory_version_ids
    assert any(
        decision.reason_code == "automatic_memory_low_rank"
        for decision in result.trim_decisions
    )


def test_oldest_history_turn_is_removed_as_whole_pair() -> None:
    recent = (
        _message(1, ChatRole.USER),
        _message(2, ChatRole.ASSISTANT),
        _message(3, ChatRole.USER),
        _message(4, ChatRole.ASSISTANT),
    )
    baseline = _composer().compose(_request(recent=recent))
    maximum = baseline.provider_character_count - len(recent[0].content)

    result = _composer().compose(_request(recent=recent), max_characters=maximum)

    assert result.selected_recent_message_ids == ("message-3", "message-4")
    assert any(decision.count == 2 for decision in result.trim_decisions)


def test_residual_overflow_removes_every_optional_layer() -> None:
    emotion = EmotionExpressionView(7, "bright", 0.8, 0.7, 0.2, 0.1, 0.3)
    request = _request(
        recent=(_message(1, ChatRole.USER),),
        memories=(_memory(1),),
        emotion=emotion,
    )
    protected_count = len("persona rules") + len("current user")

    result = _composer().compose(request, max_characters=protected_count + 1)

    assert result.selected_summary_ids == ()
    assert result.selected_memory_version_ids == ()
    assert result.selected_recent_message_ids == ()
    assert result.source_emotion_version is None
    assert result.trim_decisions[-1].reason_code == "residual_optional_overflow"
    assert result.provider_character_count <= result.max_characters
    assert len(result.provider_messages) == 2


def test_protected_overflow_rejects_without_truncation() -> None:
    request = _request(current_text="current user", persona=_persona("persona rules"))
    with pytest.raises(ContextProtectedOverflowError):
        _composer().compose(request, max_characters=len("current user"))


def test_empty_optional_layers_remove_dynamic_envelope() -> None:
    result = _composer().compose(_request())
    assert [message.role for message in result.provider_messages] == [
        ChatRole.SYSTEM,
        ChatRole.USER,
    ]
    assert "UNTRUSTED_CONTEXT" not in "".join(
        message.content for message in result.provider_messages
    )


def test_summary_fragment_limits_drop_whole_lowest_ranked_items() -> None:
    summaries = (
        _summary(1, content="A" * 20),
        _summary(2, content="B" * 20),
        _summary(3, content="C" * 20),
    )
    result = _composer(
        summary_injection_max_fragments=2,
        summary_injection_max_fragment_characters=20,
        summary_injection_max_total_characters=30,
    ).compose(_request(summaries=summaries))

    assert result.selected_summary_ids == ("summary-1",)
    assert result.trim_decisions[0].reason_code == "summary_limit"
    assert result.trim_decisions[0].count == 2
    dynamic = result.provider_messages[1].content
    assert "A" * 20 in dynamic
    assert "B" * 20 not in dynamic
    assert "C" * 20 not in dynamic


def test_summary_total_limit_preserves_ranked_prefix() -> None:
    summaries = (
        _summary(1, content="A" * 20),
        _summary(2, content="B" * 20),
        _summary(3, content="C" * 10),
    )
    result = _composer(
        summary_injection_max_fragments=3,
        summary_injection_max_fragment_characters=20,
        summary_injection_max_total_characters=30,
    ).compose(_request(summaries=summaries))

    assert result.selected_summary_ids == ("summary-1",)
    dynamic = result.provider_messages[1].content
    assert "A" * 20 in dynamic
    assert "B" * 20 not in dynamic
    assert "C" * 10 not in dynamic


def test_oversized_summary_fragment_is_dropped_without_truncation() -> None:
    oversized = _summary(1, content="X" * 21)
    result = _composer(
        summary_injection_max_fragment_characters=20,
    ).compose(_request(summaries=(oversized,)))

    assert result.selected_summary_ids == ()
    assert all("X" * 20 not in item.content for item in result.provider_messages)
    assert result.trim_decisions[0].reason_code == "summary_limit"


def test_dynamic_pressure_drops_lowest_summary_before_memory() -> None:
    summary = _summary(1, content="S" * 200)
    memory = _memory(1, content="keep-memory")
    request = _request(memories=(memory,), summaries=(summary,))
    baseline_without_summary = _composer().compose(
        _request(memories=(memory,))
    )
    result = _composer(
        chat_dynamic_context_max_characters=(
            len(baseline_without_summary.provider_messages[1].content)
        )
    ).compose(request)

    assert result.selected_summary_ids == ()
    assert result.selected_memory_version_ids == ("version-1",)
    assert result.trim_decisions[0].reason_code == "summary_dynamic_budget"


def test_global_pressure_drops_summary_before_memory_recent_or_emotion() -> None:
    emotion = EmotionExpressionView(7, "steady", 0.4, 0.2, 0.5, 0.1, 0.6)
    summary = _summary(1, content="S" * 120)
    memory = _memory(1, content="keep-memory")
    recent = (_message(1, ChatRole.USER, "keep-recent"),)
    without_summary = _composer().compose(
        _request(
            memories=(memory,),
            recent=recent,
            emotion=emotion,
        )
    )
    result = _composer().compose(
        _request(
            summaries=(summary,),
            memories=(memory,),
            recent=recent,
            emotion=emotion,
        ),
        max_characters=without_summary.provider_character_count,
    )

    assert result.selected_summary_ids == ()
    assert result.selected_memory_version_ids == ("version-1",)
    assert result.selected_recent_message_ids == ("message-1",)
    assert result.source_emotion_version == 7
    assert result.trim_decisions[0].reason_code == "summary_global_budget"


def test_selected_summary_ids_match_only_payload_fragments() -> None:
    result = _composer().compose(
        _request(summaries=(_summary(1), _summary(2)))
    )

    assert result.selected_summary_ids == ("summary-1", "summary-2")
    dynamic = result.provider_messages[1].content
    assert "summary-1" in dynamic and "summary-2" in dynamic
    assert result.composer_version == "context-composer-v2"
    assert result.encoder_version == "context-data-json-v2"


def test_duplicate_summary_ids_are_rejected() -> None:
    summary = _summary(1)
    with pytest.raises(ValueError, match="duplicate summary"):
        _composer().compose(_request(summaries=(summary, summary)))


def test_c2_accepts_summaries_but_still_rejects_relationship_input() -> None:
    result = _composer().compose(_request(summaries=(_summary(1),)))
    assert result.selected_summary_ids == ("summary-1",)

    with pytest.raises(ValueError):
        _composer().compose(
            ContextCompositionRequest(
                **{**_request().__dict__, "relationship": {"id": "relationship"}}
            )
        )
