from pathlib import Path

import pytest

from app.domain.models import DEFAULT_EMOTION_SCOPE_ID, EMOTION_BASELINE, EmotionEventType, EmotionVector
from app.repositories.emotions import EmotionRepository, EmotionVersionConflictError
from app.repositories.sqlite import managed_connection


def test_get_or_create_initializes_one_global_baseline(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'emotion.db'}"
    with managed_connection(database_url) as connection:
        repository = EmotionRepository(connection)
        first = repository.get_or_create()
        second = repository.get_or_create()

        assert first == second
        assert first.scope_id == DEFAULT_EMOTION_SCOPE_ID
        assert first.enabled is True
        assert first.vector == EMOTION_BASELINE
        assert first.version == 0
        assert connection.execute("SELECT COUNT(*) FROM emotion_states").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM emotion_events").fetchone()[0] == 0


def test_apply_transition_updates_state_and_appends_event(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'transition.db'}"
    with managed_connection(database_url) as connection:
        repository = EmotionRepository(connection)
        repository.get_or_create()
        after = EmotionVector(0.54, 0.42, 0.20, 0.53, 0.10, 0.58)
        updated = repository.apply_transition(
            expected_version=0,
            after=after,
            event_type=EmotionEventType.TRANSITION,
            reason_codes=("user_respectful_support",),
            source_session_id=None,
            source_user_message_id=None,
            source_assistant_message_id=None,
            engine="rule",
            rule_version="emotion-rules-v1",
        )

        assert updated.version == 1
        assert updated.vector == after
        event = repository.list_events(limit=10)[0]
        assert event.before == EMOTION_BASELINE
        assert event.after == after
        assert event.reason_codes == ("user_respectful_support",)


def test_stale_version_does_not_overwrite_or_append_event(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'stale.db'}"
    with managed_connection(database_url) as connection:
        repository = EmotionRepository(connection)
        repository.get_or_create()
        repository.apply_transition(
            expected_version=0,
            after=EmotionVector(0.51, 0.40, 0.20, 0.55, 0.10, 0.60),
            event_type=EmotionEventType.TRANSITION,
            reason_codes=("neutral_turn",),
            source_session_id=None,
            source_user_message_id=None,
            source_assistant_message_id=None,
            engine="rule",
            rule_version="emotion-rules-v1",
        )

        with pytest.raises(EmotionVersionConflictError):
            repository.apply_transition(
                expected_version=0,
                after=EMOTION_BASELINE,
                event_type=EmotionEventType.TRANSITION,
                reason_codes=("neutral_turn",),
                source_session_id=None,
                source_user_message_id=None,
                source_assistant_message_id=None,
                engine="rule",
                rule_version="emotion-rules-v1",
            )

        assert repository.get_or_create().version == 1
        assert len(repository.list_events(limit=10)) == 1
