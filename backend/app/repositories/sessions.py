import sqlite3
import uuid
from datetime import UTC, datetime

from app.domain.models import Session
from app.core.errors import NotFoundError


def _now() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: datetime) -> str:
    return value.isoformat()


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _row_to_session(row: sqlite3.Row) -> Session:
    return Session(
        id=row["id"],
        title=row["title"],
        created_at=_from_iso(row["created_at"]),
        updated_at=_from_iso(row["updated_at"]),
    )


class SessionRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create(self, title: str | None = None) -> Session:
        now = _now()
        session = Session(
            id=str(uuid.uuid4()),
            title=title or "新会话",
            created_at=now,
            updated_at=now,
        )
        self._connection.execute(
            """
            INSERT INTO sessions (id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (session.id, session.title, _to_iso(session.created_at), _to_iso(session.updated_at)),
        )
        self._connection.commit()
        return session

    def list(self) -> list[Session]:
        rows = self._connection.execute(
            """
            SELECT id, title, created_at, updated_at
            FROM sessions
            ORDER BY updated_at DESC
            """
        ).fetchall()
        return [_row_to_session(row) for row in rows]

    def get(self, session_id: str) -> Session | None:
        row = self._connection.execute(
            """
            SELECT id, title, created_at, updated_at
            FROM sessions
            WHERE id = ?
            """,
            (session_id,),
        ).fetchone()
        return _row_to_session(row) if row else None

    def require(self, session_id: str) -> Session:
        session = self.get(session_id)
        if session is None:
            raise NotFoundError("会话不存在。")
        return session

    def touch(self, session_id: str) -> None:
        self._connection.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (_to_iso(_now()), session_id),
        )
        self._connection.commit()

    def delete(self, session_id: str) -> bool:
        cursor = self._connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self._connection.commit()
        return cursor.rowcount > 0
