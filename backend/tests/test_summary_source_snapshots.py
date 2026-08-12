from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.models import ChatRole
from app.repositories.chat_turns import ChatTurnRepository
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.services.session_summary_contract import canonical_summary_source_set_hash


def _append_turn(
    connection,
    *,
    session_id: str,
    user_content: str,
    assistant_content: str,
):
    user = MessageRepository(connection).add(
        session_id,
        ChatRole.USER,
        user_content,
    )
    assistant, turn = ChatTurnRepository(connection).append_assistant_turn(
        session_id=session_id,
        user_message_id=user.id,
        content=assistant_content,
        metadata={},
    )
    return user, assistant, turn


def test_snapshot_never_selects_half_turn(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'closed-turn.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("closed")
        _append_turn(
            connection,
            session_id=session.id,
            user_content="u1",
            assistant_content="a1",
        )
        _append_turn(
            connection,
            session_id=session.id,
            user_content="u2",
            assistant_content="a2",
        )

        snapshot = ChatTurnRepository(connection).snapshot_generation_sources(
            session_id=session.id,
            after_turn_order=0,
            max_turns=2,
            max_messages=2,
            max_characters=10_000,
        )

        assert len(snapshot.turns) == 1
        assert [message.role for message in snapshot.turns[0].messages] == [
            ChatRole.USER,
            ChatRole.ASSISTANT,
        ]
        assert [message.message_order_in_turn for message in snapshot.turns[0].messages] == [
            0,
            1,
        ]
        assert snapshot.source_message_count == 2
        assert snapshot.source_turn_count == 1
        assert snapshot.candidate_turn_count == 2
        assert connection.in_transaction is False


def test_excluded_member_removes_complete_turn(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'excluded-turn.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("excluded")
        first_user, first_assistant, first_turn = _append_turn(
            connection,
            session_id=session.id,
            user_content="excluded user",
            assistant_content="excluded assistant",
        )
        second_user, second_assistant, second_turn = _append_turn(
            connection,
            session_id=session.id,
            user_content="safe user",
            assistant_content="safe assistant",
        )
        connection.execute(
            "INSERT INTO memory_summary_source_exclusions "
            "(source_message_id, reason_code, created_at) VALUES (?, ?, ?)",
            (first_assistant.id, "forgotten", first_assistant.created_at.isoformat()),
        )
        connection.commit()

        snapshot = ChatTurnRepository(connection).snapshot_generation_sources(
            session_id=session.id,
            after_turn_order=0,
            max_turns=2,
            max_messages=4,
            max_characters=10_000,
        )

        assert [turn.id for turn in snapshot.turns] == [second_turn.id]
        selected_ids = {
            message.id for turn in snapshot.turns for message in turn.messages
        }
        assert first_turn.id not in {turn.id for turn in snapshot.turns}
        assert first_user.id not in selected_ids
        assert first_assistant.id not in selected_ids
        assert selected_ids == {second_user.id, second_assistant.id}
        assert snapshot.candidate_turn_count == 1


def test_character_cap_drops_whole_turns(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'character-cap.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("characters")
        _, _, first = _append_turn(
            connection,
            session_id=session.id,
            user_content="1234",
            assistant_content="5678",
        )
        _append_turn(
            connection,
            session_id=session.id,
            user_content="abcd",
            assistant_content="efgh",
        )

        snapshot = ChatTurnRepository(connection).snapshot_generation_sources(
            session_id=session.id,
            after_turn_order=0,
            max_turns=2,
            max_messages=4,
            max_characters=12,
        )

        assert [turn.id for turn in snapshot.turns] == [first.id]
        assert snapshot.source_character_count == 8
        assert snapshot.source_message_count == 2


def test_oversized_first_turn_produces_empty_snapshot(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'oversized-first.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("oversized")
        _append_turn(
            connection,
            session_id=session.id,
            user_content="12345",
            assistant_content="67890",
        )

        snapshot = ChatTurnRepository(connection).snapshot_generation_sources(
            session_id=session.id,
            after_turn_order=0,
            max_turns=1,
            max_messages=2,
            max_characters=9,
        )

        assert snapshot.turns == ()
        assert snapshot.source_set_hash is None
        assert snapshot.source_message_count == 0


def test_after_turn_order_and_canonical_hash_are_stable(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'source-hash.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("hash")
        _append_turn(
            connection,
            session_id=session.id,
            user_content="before",
            assistant_content="before reply",
        )
        user, assistant, selected_turn = _append_turn(
            connection,
            session_id=session.id,
            user_content="selected",
            assistant_content="selected reply",
        )

        repository = ChatTurnRepository(connection)
        first = repository.snapshot_generation_sources(
            session_id=session.id,
            after_turn_order=1,
            max_turns=1,
            max_messages=2,
            max_characters=10_000,
        )
        second = repository.snapshot_generation_sources(
            session_id=session.id,
            after_turn_order=1,
            max_turns=1,
            max_messages=2,
            max_characters=10_000,
        )

        expected = canonical_summary_source_set_hash(
            session_id=session.id,
            turns=(
                {
                    "turn_id": selected_turn.id,
                    "turn_order": 2,
                    "messages": (
                        {"message_id": user.id, "message_order_in_turn": 0},
                        {"message_id": assistant.id, "message_order_in_turn": 1},
                    ),
                },
            ),
        )
        assert first.source_set_hash == second.source_set_hash == expected
        assert first.barrier_generation == 0


@pytest.mark.parametrize(
    ("max_turns", "max_messages", "max_characters"),
    [
        (0, 2, 10),
        (1, 0, 10),
        (1, 3, 10),
        (1, 2, 0),
    ],
)
def test_snapshot_rejects_invalid_limits(
    tmp_path: Path,
    max_turns: int,
    max_messages: int,
    max_characters: int,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'invalid-limits.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("invalid")
        with pytest.raises(ValueError):
            ChatTurnRepository(connection).snapshot_generation_sources(
                session_id=session.id,
                after_turn_order=0,
                max_turns=max_turns,
                max_messages=max_messages,
                max_characters=max_characters,
            )
