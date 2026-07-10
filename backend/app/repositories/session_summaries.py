from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from app.domain.models import SessionSummary, SessionSummarySource
from app.repositories.sqlite import metadata_from_json, metadata_to_json


def _now() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: datetime) -> str:
    return value.isoformat()


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _row_to_summary(row: sqlite3.Row) -> SessionSummary:
    return SessionSummary(
        id=row["id"],
        session_id=row["session_id"],
        summary_text=row["summary_text"],
        source=SessionSummarySource(row["source"]),
        covered_message_start_id=row["covered_message_start_id"],
        covered_message_end_id=row["covered_message_end_id"],
        message_count=row["message_count"],
        metadata=metadata_from_json(row["metadata_json"]),
        created_at=_from_iso(row["created_at"]),
        updated_at=_from_iso(row["updated_at"]),
    )


class SessionSummaryRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create(
        self,
        *,
        session_id: str,
        summary_text: str,
        source: SessionSummarySource = SessionSummarySource.MANUAL,
        covered_message_start_id: str | None = None,
        covered_message_end_id: str | None = None,
        message_count: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> SessionSummary:
        clean_text = summary_text.strip()
        if not clean_text:
            raise ValueError("summary_text must not be empty")
        if message_count < 0:
            raise ValueError("message_count must be non-negative")
        now = _now()
        summary = SessionSummary(
            id=str(uuid.uuid4()),
            session_id=session_id,
            summary_text=clean_text,
            source=source,
            covered_message_start_id=covered_message_start_id,
            covered_message_end_id=covered_message_end_id,
            message_count=message_count,
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )
        self._connection.execute(
            """
            INSERT INTO session_summaries (
                id, session_id, summary_text, source, covered_message_start_id,
                covered_message_end_id, message_count, metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                summary.id,
                summary.session_id,
                summary.summary_text,
                summary.source.value,
                summary.covered_message_start_id,
                summary.covered_message_end_id,
                summary.message_count,
                metadata_to_json(summary.metadata),
                _to_iso(summary.created_at),
                _to_iso(summary.updated_at),
            ),
        )
        self._connection.commit()
        return summary

    def list_for_session(self, session_id: str) -> list[SessionSummary]:
        rows = self._connection.execute(
            """
            SELECT id, session_id, summary_text, source, covered_message_start_id,
                   covered_message_end_id, message_count, metadata_json, created_at, updated_at
            FROM session_summaries
            WHERE session_id = ?
            ORDER BY created_at ASC
            """,
            (session_id,),
        ).fetchall()
        return [_row_to_summary(row) for row in rows]

    def latest_for_session(self, session_id: str) -> SessionSummary | None:
        row = self._connection.execute(
            """
            SELECT id, session_id, summary_text, source, covered_message_start_id,
                   covered_message_end_id, message_count, metadata_json, created_at, updated_at
            FROM session_summaries
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        return _row_to_summary(row) if row else None

    def delete(self, summary_id: str) -> bool:
        cursor = self._connection.execute("DELETE FROM session_summaries WHERE id = ?", (summary_id,))
        self._connection.commit()
        return cursor.rowcount > 0
