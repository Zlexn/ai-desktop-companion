from datetime import UTC, datetime, timedelta

import pytest

from app.domain.models import (
    ChatRole,
    Memory,
    MemorySource,
    MemoryStatus,
    MemoryType,
    Message,
)
from app.services.credential_sanitizer import sanitize_credentials
from app.services.emotion_analysis_input import EmotionAnalysisInputBuilder


def _message(message_id: str, role: ChatRole, content: str, offset: int) -> Message:
    return Message(
        id=message_id,
        session_id="session-1",
        role=role,
        content=content,
        created_at=datetime(2026, 7, 13, 12, 0, tzinfo=UTC) + timedelta(seconds=offset),
        metadata={"private": "must-not-leak"},
    )


def _memory(memory_id: str, content: str, status: MemoryStatus, importance: int = 3) -> Memory:
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    return Memory(
        id=memory_id,
        content=content,
        memory_type=MemoryType.PREFERENCE,
        source=MemorySource.MANUAL,
        source_session_id=None,
        importance=importance,
        confidence=0.9,
        status=status,
        created_at=now,
        updated_at=now,
        metadata={"private": "must-not-leak"},
    )


def test_sanitize_credentials_redacts_common_secret_patterns_and_counts() -> None:
    sanitized, count = sanitize_credentials(
        "Bearer abc.def token=my-token password:secret sk-1234567890abcdef ordinary text"
    )

    assert "abc.def" not in sanitized
    assert "my-token" not in sanitized
    assert "secret" not in sanitized
    assert "sk-1234567890abcdef" not in sanitized
    assert sanitized.count("[REDACTED]") == 4
    assert count == 4


def test_sanitize_credentials_redacts_quoted_values_containing_spaces() -> None:
    sanitized, count = sanitize_credentials(
        "password=\"my secret phrase\" token='another secret'"
    )

    assert sanitized == "password=[REDACTED] token=[REDACTED]"
    assert count == 2


def test_sanitize_credentials_redacts_json_curly_bearer_and_escaped_quotes() -> None:
    cases = (
        ('{"api_key":"json-secret"}', "json-secret"),
        ("{'token':'single-secret'}", "single-secret"),
        ('token=“curly secret”', "curly secret"),
        ('Authorization: Bearer "quoted-secret"', "quoted-secret"),
        ('token="prefix\\"leaked-tail"', "leaked-tail"),
    )

    for raw, secret in cases:
        sanitized, count = sanitize_credentials(raw)
        assert secret not in sanitized
        assert count == 1


def test_input_builder_includes_current_turn_recent_messages_and_active_memories_only() -> None:
    messages = [
        _message("old-user", ChatRole.USER, "更早的消息", 0),
        _message("old-assistant", ChatRole.ASSISTANT, "更早的回复", 1),
        _message("user-current", ChatRole.USER, "我今天有点难过", 2),
        _message("assistant-current", ChatRole.ASSISTANT, "先休息一下。", 3),
    ]
    memories = [
        _memory("active-1", "用户喜欢安静的环境", MemoryStatus.ACTIVE, 5),
        _memory("pending-1", "候选秘密", MemoryStatus.PENDING, 5),
        _memory("archived-1", "归档秘密", MemoryStatus.ARCHIVED, 5),
    ]
    builder = EmotionAnalysisInputBuilder(
        recent_message_limit=3,
        memory_limit=3,
        max_item_characters=2_000,
        max_total_characters=8_000,
    )

    built = builder.build(
        current_user_message=messages[2],
        current_assistant_message=messages[3],
        recent_messages=messages,
        relevant_memories=memories,
    )

    assert built.current_turn.user_message_id == "user-current"
    assert built.current_turn.assistant_message_id == "assistant-current"
    assert [item.id for item in built.recent_messages] == ["old-assistant"]
    assert [item.id for item in built.memories] == ["active-1"]
    assert "must-not-leak" not in built.to_json()
    assert "候选秘密" not in built.to_json()
    assert "归档秘密" not in built.to_json()


def test_input_builder_rejects_total_budget_that_cannot_hold_both_current_messages() -> None:
    with pytest.raises(ValueError, match="max_total_characters must be at least 2"):
        EmotionAnalysisInputBuilder(
            recent_message_limit=6,
            memory_limit=3,
            max_item_characters=1,
            max_total_characters=1,
        )


def test_input_builder_sanitizes_before_budgeting_and_preserves_current_turn() -> None:
    user = _message("user-current", ChatRole.USER, "token=super-secret " + "用" * 100, 0)
    assistant = _message("assistant-current", ChatRole.ASSISTANT, "答" * 100, 1)
    old = _message("old", ChatRole.USER, "旧" * 100, -1)
    builder = EmotionAnalysisInputBuilder(
        recent_message_limit=6,
        memory_limit=3,
        max_item_characters=40,
        max_total_characters=100,
    )

    built = builder.build(
        current_user_message=user,
        current_assistant_message=assistant,
        recent_messages=[old, user, assistant],
        relevant_memories=[],
    )

    assert built.current_turn.user_content.startswith("token=[REDACTED]")
    assert "super-secret" not in built.to_json()
    assert len(built.current_turn.user_content) <= 40
    assert len(built.current_turn.assistant_content) <= 40
    assert built.input_characters <= 100
    assert built.redaction_count == 1
    assert built.current_turn.user_message_id == "user-current"
    assert built.current_turn.assistant_message_id == "assistant-current"


def test_input_builder_drops_old_optional_items_to_meet_total_budget() -> None:
    user = _message("user-current", ChatRole.USER, "U" * 30, 2)
    assistant = _message("assistant-current", ChatRole.ASSISTANT, "A" * 30, 3)
    old_messages = [
        _message("old-1", ChatRole.USER, "1" * 30, 0),
        _message("old-2", ChatRole.ASSISTANT, "2" * 30, 1),
    ]
    memories = [
        _memory("memory-1", "M" * 30, MemoryStatus.ACTIVE, 5),
        _memory("memory-2", "N" * 30, MemoryStatus.ACTIVE, 4),
    ]
    builder = EmotionAnalysisInputBuilder(
        recent_message_limit=6,
        memory_limit=3,
        max_item_characters=30,
        max_total_characters=90,
    )

    built = builder.build(
        current_user_message=user,
        current_assistant_message=assistant,
        recent_messages=[*old_messages, user, assistant],
        relevant_memories=memories,
    )

    assert built.input_characters <= 90
    assert built.current_turn.user_content == "U" * 30
    assert built.current_turn.assistant_content == "A" * 30
    assert len(built.recent_messages) + len(built.memories) <= 1


def test_input_builder_preserves_nonempty_content_for_both_current_turn_sides() -> None:
    builder = EmotionAnalysisInputBuilder(
        recent_message_limit=6,
        memory_limit=3,
        max_item_characters=20,
        max_total_characters=20,
    )

    built = builder.build(
        current_user_message=_message("user-current", ChatRole.USER, "U" * 20, 0),
        current_assistant_message=_message("assistant-current", ChatRole.ASSISTANT, "A" * 20, 1),
        recent_messages=[],
        relevant_memories=[],
    )

    assert built.current_turn.user_content
    assert built.current_turn.assistant_content
    assert len(built.current_turn.user_content) <= 10
    assert len(built.current_turn.assistant_content) <= 10
    assert built.input_characters <= 20


    builder = EmotionAnalysisInputBuilder(
        recent_message_limit=6,
        memory_limit=3,
        max_item_characters=100,
        max_total_characters=200,
    )

    try:
        builder.build(
            current_user_message=_message("assistant", ChatRole.ASSISTANT, "wrong", 0),
            current_assistant_message=_message("user", ChatRole.USER, "wrong", 1),
            recent_messages=[],
            relevant_memories=[],
        )
    except ValueError as exc:
        assert "current turn" in str(exc)
    else:
        raise AssertionError("expected ValueError")
