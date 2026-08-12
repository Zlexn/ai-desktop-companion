from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from app.domain.models import ChatRole, Message
from app.repositories.sqlite import metadata_from_json, metadata_to_json


def _now() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: datetime) -> str:
    return value.isoformat()


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _row_to_message(row: sqlite3.Row) -> Message:
    return Message(
        id=row["id"],
        session_id=row["session_id"],
        role=ChatRole(row["role"]),
        content=row["content"],
        created_at=_from_iso(row["created_at"]),
        metadata=metadata_from_json(row["metadata_json"]),
    )


class MessageRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(
        self,
        session_id: str,
        role: ChatRole,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> Message:
        if role == ChatRole.SYSTEM:
            raise ValueError("System prompts are not persisted as chat messages in stage 1")

        message = Message(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=role,
            content=content,
            created_at=_now(),
            metadata=metadata or {},
        )
        self._connection.execute(
            """
            INSERT INTO messages (id, session_id, role, content, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                message.id,
                message.session_id,
                message.role.value,
                message.content,
                metadata_to_json(message.metadata),
                _to_iso(message.created_at),
            ),
        )
        self._connection.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (_to_iso(message.created_at), session_id),
        )
        self._connection.commit()
        return message

    def get(self, message_id: str) -> Message | None:
        row = self._connection.execute(
            """
            SELECT id, session_id, role, content, metadata_json, created_at
            FROM messages
            WHERE id = ?
            """,
            (message_id,),
        ).fetchone()
        return _row_to_message(row) if row else None

    def list(self, session_id: str) -> list[Message]:
        rows = self._connection.execute(
            """
            SELECT id, session_id, role, content, metadata_json, created_at
            FROM messages
            WHERE session_id = ?
            ORDER BY created_at ASC, rowid ASC
            """,
            (session_id,),
        ).fetchall()
        return [_row_to_message(row) for row in rows]

    def list_recent_excluding(
        self,
        session_id: str,
        excluded_id: str,
        limit: int,
    ) -> list[Message]:
        rows = self._connection.execute(
            """
            SELECT id, session_id, role, content, metadata_json, created_at
            FROM messages
            WHERE session_id = ? AND id <> ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (session_id, excluded_id, limit),
        ).fetchall()
        return list(reversed([_row_to_message(row) for row in rows]))

    def list_recent(self, session_id: str, limit: int) -> list[Message]:
        rows = self._connection.execute(
            """
            SELECT id, session_id, role, content, metadata_json, created_at
            FROM messages
            WHERE session_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
        return list(reversed([_row_to_message(row) for row in rows]))
