from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.models import ChatRole
from app.repositories.chat_turns import ChatTurnRepository
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection


def test_append_assistant_turn_persists_message_and_turn_atomically(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'turn.db'}"

    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("turn")
        user = MessageRepository(connection).add(session.id, ChatRole.USER, "hello")
        assistant, turn = ChatTurnRepository(connection).append_assistant_turn(
            session_id=session.id,
            user_message_id=user.id,
            content="reply",
            metadata={"provider": "fake"},
        )

        assert assistant.role is ChatRole.ASSISTANT
        assert assistant.content == "reply"
        assert turn.session_id == session.id
        assert turn.user_message_id == user.id
        assert turn.assistant_message_id == assistant.id
        assert turn.turn_order == 1
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0] == 1


def test_turn_insert_failure_rolls_back_assistant_and_session_touch(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'turn-rollback.db'}"

    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        session = sessions.create("turn")
        user = MessageRepository(connection).add(session.id, ChatRole.USER, "hello")
        before_updated_at = sessions.require(session.id).updated_at
        repository = ChatTurnRepository(
            connection,
            fault_injector=lambda point: (
                (_ for _ in ()).throw(RuntimeError("turn fault"))
                if point == "after_assistant"
                else None
            ),
        )

        with pytest.raises(RuntimeError, match="turn fault"):
            repository.append_assistant_turn(
                session_id=session.id,
                user_message_id=user.id,
                content="reply",
                metadata={},
            )

        assert [message.id for message in MessageRepository(connection).list(session.id)] == [
            user.id
        ]
        assert connection.execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0] == 0
        assert sessions.require(session.id).updated_at == before_updated_at


@pytest.mark.parametrize(
    ("role", "other_session"),
    [
        (ChatRole.ASSISTANT, False),
        (ChatRole.USER, True),
    ],
)
def test_append_assistant_turn_rejects_invalid_user_binding(
    tmp_path: Path,
    role: ChatRole,
    other_session: bool,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'invalid-binding.db'}"

    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        target = sessions.create("target")
        source = sessions.create("source") if other_session else target
        message = MessageRepository(connection).add(source.id, role, "message")

        with pytest.raises(ValueError, match="user message"):
            ChatTurnRepository(connection).append_assistant_turn(
                session_id=target.id,
                user_message_id=message.id,
                content="reply",
                metadata={},
            )

        assert connection.execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0] == 0


def test_duplicate_user_binding_fails_without_extra_assistant(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'duplicate-turn.db'}"

    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("turn")
        user = MessageRepository(connection).add(session.id, ChatRole.USER, "hello")
        repository = ChatTurnRepository(connection)
        repository.append_assistant_turn(
            session_id=session.id,
            user_message_id=user.id,
            content="first",
            metadata={},
        )

        with pytest.raises(ValueError, match="already bound"):
            repository.append_assistant_turn(
                session_id=session.id,
                user_message_id=user.id,
                content="second",
                metadata={},
            )

        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0] == 1


def test_turn_order_is_allocated_independently_of_equal_timestamps(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'turn-order.db'}"

    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("turn")
        messages = MessageRepository(connection)
        first_user = messages.add(session.id, ChatRole.USER, "first")
        second_user = messages.add(session.id, ChatRole.USER, "second")
        connection.execute(
            "UPDATE messages SET created_at='2026-07-22T00:00:00+00:00' WHERE id IN (?, ?)",
            (first_user.id, second_user.id),
        )
        connection.commit()
        repository = ChatTurnRepository(connection)

        _, first_turn = repository.append_assistant_turn(
            session_id=session.id,
            user_message_id=first_user.id,
            content="first reply",
            metadata={},
        )
        _, second_turn = repository.append_assistant_turn(
            session_id=session.id,
            user_message_id=second_user.id,
            content="second reply",
            metadata={},
        )

        assert (first_turn.turn_order, second_turn.turn_order) == (1, 2)
