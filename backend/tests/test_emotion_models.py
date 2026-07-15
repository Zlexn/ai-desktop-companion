from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from app.domain.models import (
    DEFAULT_EMOTION_SCOPE_ID,
    EMOTION_BASELINE,
    EmotionEvent,
    EmotionEventType,
    EmotionState,
    EmotionVector,
)


def test_emotion_baseline_has_all_six_bounded_dimensions() -> None:
    assert DEFAULT_EMOTION_SCOPE_ID == "default-companion"
    assert EMOTION_BASELINE == EmotionVector(
        mood=0.50,
        trust=0.40,
        concern=0.20,
        distance=0.55,
        irritation=0.10,
        formality=0.60,
    )
    assert all(0.0 <= value <= 1.0 for value in EMOTION_BASELINE.values())


def test_emotion_state_is_immutable() -> None:
    state = EmotionState(
        scope_id=DEFAULT_EMOTION_SCOPE_ID,
        enabled=True,
        vector=EMOTION_BASELINE,
        version=0,
        updated_at=datetime.now(UTC),
    )
    with pytest.raises(FrozenInstanceError):
        state.version = 1  # type: ignore[misc]


def test_emotion_event_keeps_structured_reason_and_sources() -> None:
    now = datetime.now(UTC)
    event = EmotionEvent(
        id="event-1",
        scope_id=DEFAULT_EMOTION_SCOPE_ID,
        event_type=EmotionEventType.TRANSITION,
        before=EMOTION_BASELINE,
        after=EMOTION_BASELINE,
        applied_delta=EmotionVector.zero(),
        reason_codes=("neutral_turn",),
        source_session_id="session-1",
        source_user_message_id="user-1",
        source_assistant_message_id="assistant-1",
        engine="rule",
        rule_version="emotion-rules-v1",
        created_at=now,
    )
    assert event.reason_codes == ("neutral_turn",)
