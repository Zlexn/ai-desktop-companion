from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import sqlite3
import uuid
from typing import Any

from app.domain.models import ChatRole, Message
from app.domain.session_summary import (
    ChatTurn,
    SummarySnapshotMessage,
    SummarySnapshotTurn,
    SummarySourceSnapshot,
)
from app.repositories.sqlite import metadata_to_json
from app.services.session_summary_contract import canonical_summary_source_set_hash


def _now() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: datetime) -> str:
    return value.isoformat()


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


class ChatTurnRepository:
    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self._connection = connection
        self._fault_injector = fault_injector

    def append_assistant_turn(
        self,
        *,
        session_id: str,
        user_message_id: str,
        content: str,
        metadata: dict[str, Any],
    ) -> tuple[Message, ChatTurn]:
        clean_content = content.strip()
        if not clean_content:
            raise ValueError("assistant content must not be empty")
        if self._connection.in_transaction:
            raise RuntimeError("connection already has an unmanaged transaction")

        try:
            self._connection.execute("BEGIN IMMEDIATE")
            user = self._connection.execute(
                "SELECT id, session_id, role FROM messages WHERE id=?",
                (user_message_id,),
            ).fetchone()
            if (
                user is None
                or str(user["session_id"]) != session_id
                or str(user["role"]) != ChatRole.USER.value
            ):
                raise ValueError("user message must belong to the target session")
            if self._connection.execute(
                "SELECT 1 FROM chat_turns WHERE user_message_id=?",
                (user_message_id,),
            ).fetchone() is not None:
                raise ValueError("user message is already bound to a chat turn")

            now = _now()
            assistant = Message(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role=ChatRole.ASSISTANT,
                content=clean_content,
                metadata=metadata,
                created_at=now,
            )
            self._connection.execute(
                """
                INSERT INTO messages (
                    id, session_id, role, content, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    assistant.id,
                    assistant.session_id,
                    assistant.role.value,
                    assistant.content,
                    metadata_to_json(assistant.metadata),
                    _to_iso(assistant.created_at),
                ),
            )
            if self._fault_injector is not None:
                self._fault_injector("after_assistant")

            row = self._connection.execute(
                "SELECT COALESCE(MAX(turn_order), 0) + 1 AS next_order "
                "FROM chat_turns WHERE session_id=?",
                (session_id,),
            ).fetchone()
            assert row is not None
            turn = ChatTurn(
                id=str(uuid.uuid4()),
                session_id=session_id,
                user_message_id=user_message_id,
                assistant_message_id=assistant.id,
                turn_order=int(row["next_order"]),
                created_at=now,
            )
            self._connection.execute(
                """
                INSERT INTO chat_turns (
                    id, session_id, user_message_id, assistant_message_id,
                    turn_order, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    turn.id,
                    turn.session_id,
                    turn.user_message_id,
                    turn.assistant_message_id,
                    turn.turn_order,
                    _to_iso(turn.created_at),
                ),
            )
            self._connection.execute(
                "UPDATE sessions SET updated_at=? WHERE id=?",
                (_to_iso(now), session_id),
            )
        except BaseException:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()
        return assistant, turn

    def snapshot_generation_sources(
        self,
        *,
        session_id: str,
        after_turn_order: int,
        max_turns: int,
        max_messages: int,
        max_characters: int,
    ) -> SummarySourceSnapshot:
        if after_turn_order < 0:
            raise ValueError("after_turn_order must be non-negative")
        if max_turns <= 0:
            raise ValueError("max_turns must be positive")
        if max_messages <= 0 or max_messages % 2:
            raise ValueError("max_messages must be a positive even number")
        if max_characters <= 0:
            raise ValueError("max_characters must be positive")
        if self._connection.in_transaction:
            raise RuntimeError("connection already has an unmanaged transaction")

        try:
            self._connection.execute("BEGIN")
            barrier = self._connection.execute(
                "SELECT generation FROM memory_summary_barrier WHERE singleton_id=1"
            ).fetchone()
            if barrier is None:
                raise RuntimeError("memory summary barrier is unavailable")
            rows = self._connection.execute(
                """
                SELECT turn.id AS turn_id, turn.turn_order,
                       user_message.id AS user_id,
                       user_message.role AS user_role,
                       user_message.content AS user_content,
                       assistant_message.id AS assistant_id,
                       assistant_message.role AS assistant_role,
                       assistant_message.content AS assistant_content
                FROM chat_turns AS turn
                JOIN messages AS user_message
                  ON user_message.id = turn.user_message_id
                JOIN messages AS assistant_message
                  ON assistant_message.id = turn.assistant_message_id
                WHERE turn.session_id=? AND turn.turn_order>?
                  AND NOT EXISTS (
                      SELECT 1 FROM memory_summary_source_exclusions AS excluded
                      WHERE excluded.source_message_id IN (
                          turn.user_message_id, turn.assistant_message_id
                      )
                  )
                ORDER BY turn.turn_order, turn.id
                """,
                (session_id, after_turn_order),
            ).fetchall()
            candidate_turn_count = len(rows)
            maximum_turns = min(max_turns, max_messages // 2)
            selected: list[SummarySnapshotTurn] = []
            character_count = 0
            for row in rows[:maximum_turns]:
                if (
                    str(row["user_role"]) != ChatRole.USER.value
                    or str(row["assistant_role"]) != ChatRole.ASSISTANT.value
                ):
                    raise RuntimeError("chat turn source role invariant violation")
                user_content = str(row["user_content"])
                assistant_content = str(row["assistant_content"])
                turn_characters = len(user_content) + len(assistant_content)
                if character_count + turn_characters > max_characters:
                    break
                selected.append(
                    SummarySnapshotTurn(
                        id=str(row["turn_id"]),
                        turn_order=int(row["turn_order"]),
                        messages=(
                            SummarySnapshotMessage(
                                id=str(row["user_id"]),
                                role=ChatRole.USER,
                                content=user_content,
                                message_order_in_turn=0,
                            ),
                            SummarySnapshotMessage(
                                id=str(row["assistant_id"]),
                                role=ChatRole.ASSISTANT,
                                content=assistant_content,
                                message_order_in_turn=1,
                            ),
                        ),
                    )
                )
                character_count += turn_characters
            source_turns = tuple(selected)
            source_hash = (
                canonical_summary_source_set_hash(
                    session_id=session_id,
                    turns=tuple(
                        {
                            "turn_id": turn.id,
                            "turn_order": turn.turn_order,
                            "messages": tuple(
                                {
                                    "message_id": message.id,
                                    "message_order_in_turn": message.message_order_in_turn,
                                }
                                for message in turn.messages
                            ),
                        }
                        for turn in source_turns
                    ),
                )
                if source_turns
                else None
            )
            return SummarySourceSnapshot(
                session_id=session_id,
                barrier_generation=int(barrier["generation"]),
                candidate_turn_count=candidate_turn_count,
                source_character_count=character_count,
                turns=source_turns,
                source_set_hash=source_hash,
            )
        finally:
            self._connection.rollback()

    def get(self, turn_id: str) -> ChatTurn | None:
        row = self._connection.execute(
            "SELECT * FROM chat_turns WHERE id=?",
            (turn_id,),
        ).fetchone()
        if row is None:
            return None
        return ChatTurn(
            id=str(row["id"]),
            session_id=str(row["session_id"]),
            user_message_id=str(row["user_message_id"]),
            assistant_message_id=str(row["assistant_message_id"]),
            turn_order=int(row["turn_order"]),
            created_at=_from_iso(str(row["created_at"])),
        )
