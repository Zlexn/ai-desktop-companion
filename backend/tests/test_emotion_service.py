from datetime import UTC, datetime
from pathlib import Path

from app.domain.models import ChatRole, EMOTION_BASELINE
from app.repositories.emotions import EmotionRepository
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.services.emotion_policy import EmotionPolicy
from app.services.emotion_service import EmotionService


def test_completed_turn_updates_global_state_and_audits_sources(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'service.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("first")
        user = messages.add(session.id, ChatRole.USER, "谢谢你认真听我说。")
        assistant = messages.add(session.id, ChatRole.ASSISTANT, "不必客气。")
        service = EmotionService(EmotionRepository(connection), EmotionPolicy())

        updated = service.apply_completed_turn(session.id, user, assistant)

        assert updated.version == 1
        assert updated.vector.trust > EMOTION_BASELINE.trust
        event = service.list_events(limit=10)[0]
        assert event.source_session_id == session.id
        assert event.source_user_message_id == user.id
        assert event.source_assistant_message_id == assistant.id


def test_disabled_state_does_not_change_on_turn(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'disabled.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("disabled")
        user = messages.add(session.id, ChatRole.USER, "谢谢你。")
        assistant = messages.add(session.id, ChatRole.ASSISTANT, "知道了。")
        service = EmotionService(EmotionRepository(connection), EmotionPolicy())
        disabled = service.set_enabled(False)

        after = service.apply_completed_turn(session.id, user, assistant)

        assert after == disabled
        assert len(service.list_events(limit=10)) == 1


def test_reset_restores_exact_baseline_and_appends_event(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'reset.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("reset")
        user = messages.add(session.id, ChatRole.USER, "你真蠢，闭嘴。")
        assistant = messages.add(session.id, ChatRole.ASSISTANT, "我会保持克制。")
        service = EmotionService(EmotionRepository(connection), EmotionPolicy())
        service.apply_completed_turn(session.id, user, assistant)

        reset = service.reset()

        assert reset.vector == EMOTION_BASELINE
        assert service.list_events(limit=10)[0].reason_codes == ("manual_reset",)


def test_get_state_persists_elapsed_decay(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'decay.db'}"
    with managed_connection(database_url) as connection:
        repository = EmotionRepository(connection)
        service = EmotionService(repository, EmotionPolicy())
        state = repository.get_or_create()
        # The injected time makes this deterministic without a timer.
        current = service.get_state(apply_decay=True, now=state.updated_at)
        assert current == state
        assert current.updated_at <= datetime.now(UTC)
