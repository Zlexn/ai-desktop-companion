from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any, Iterator

from app.domain.models import (
    ChatRole,
    Message,
    SessionSummary,
    SessionSummarySource,
)
from app.repositories.sqlite import metadata_from_json, metadata_to_json


def _now() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: datetime) -> str:
    return value.isoformat()


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


@dataclass(frozen=True)
class SummarySourceSnapshot:
    barrier_generation: int
    candidate_message_count: int
    messages: tuple[Message, ...]


class SessionSummaryRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @contextmanager
    def _write_transaction(self) -> Iterator[None]:
        if self._connection.in_transaction:
            raise RuntimeError("connection already has an unmanaged transaction")
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            yield
        except BaseException:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()

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
        observed_memory_summary_barrier: int = 0,
    ) -> SessionSummary:
        with self._write_transaction():
            return self._create_in_transaction(
                session_id=session_id,
                summary_text=summary_text,
                source=source,
                covered_message_start_id=covered_message_start_id,
                covered_message_end_id=covered_message_end_id,
                message_count=message_count,
                metadata=metadata,
                observed_memory_summary_barrier=observed_memory_summary_barrier,
            )

    def _create_in_transaction(
        self,
        *,
        session_id: str,
        summary_text: str,
        source: SessionSummarySource,
        covered_message_start_id: str | None,
        covered_message_end_id: str | None,
        message_count: int,
        metadata: dict[str, Any] | None,
        observed_memory_summary_barrier: int,
    ) -> SessionSummary:
        clean_text = summary_text.strip()
        if not clean_text:
            raise ValueError("summary_text must not be empty")
        if message_count < 0:
            raise ValueError("message_count must be non-negative")
        if observed_memory_summary_barrier < 0:
            raise ValueError("observed_memory_summary_barrier must be non-negative")
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
            observed_memory_summary_barrier=observed_memory_summary_barrier,
        )
        self._connection.execute(
            """
            INSERT INTO session_summaries (
                id, session_id, summary_text, source, covered_message_start_id,
                covered_message_end_id, message_count, metadata_json,
                created_at, updated_at, observed_memory_summary_barrier
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                summary.observed_memory_summary_barrier,
            ),
        )
        return summary

    def snapshot_generation_sources(
        self,
        *,
        session_id: str,
        after_message_id: str | None,
        limit: int,
    ) -> SummarySourceSnapshot:
        self._connection.execute("BEGIN")
        try:
            barrier_row = self._connection.execute(
                "SELECT generation FROM memory_summary_barrier WHERE singleton_id = 1"
            ).fetchone()
            if barrier_row is None:
                raise RuntimeError("memory summary barrier is unavailable")
            excluded = {
                str(row["source_message_id"])
                for row in self._connection.execute(
                    "SELECT source_message_id FROM memory_summary_source_exclusions"
                ).fetchall()
            }
            id_rows = self._connection.execute(
                "SELECT id FROM messages WHERE session_id = ? ORDER BY created_at ASC, rowid ASC",
                (session_id,),
            ).fetchall()
            ordered_ids = [str(row["id"]) for row in id_rows]
            if after_message_id is not None and after_message_id in ordered_ids:
                ordered_ids = ordered_ids[ordered_ids.index(after_message_id) + 1 :]
            filtered_ids = [message_id for message_id in ordered_ids if message_id not in excluded]
            selected_ids = filtered_ids[:limit]
            messages: list[Message] = []
            for message_id in selected_ids:
                row = self._connection.execute(
                    """
                    SELECT id, session_id, role, content, metadata_json, created_at
                    FROM messages WHERE id = ?
                    """,
                    (message_id,),
                ).fetchone()
                if row is None:
                    raise RuntimeError("summary source changed during snapshot")
                messages.append(
                    Message(
                        id=str(row["id"]),
                        session_id=str(row["session_id"]),
                        role=ChatRole(str(row["role"])),
                        content=str(row["content"]),
                        metadata=metadata_from_json(str(row["metadata_json"])),
                        created_at=_from_iso(str(row["created_at"])),
                    )
                )
            return SummarySourceSnapshot(
                barrier_generation=int(barrier_row["generation"]),
                candidate_message_count=len(filtered_ids),
                messages=tuple(messages),
            )
        finally:
            self._connection.rollback()

    def commit_generated_if_current(
        self,
        *,
        session_id: str,
        summary_text: str,
        source_message_ids: tuple[str, ...],
        observed_memory_summary_barrier: int,
        metadata: dict[str, Any],
    ) -> SessionSummary | None:
        if not source_message_ids:
            return None
        with self._write_transaction():
            current = self._current_barrier_generation()
            if current != observed_memory_summary_barrier:
                return None
            placeholders = ", ".join("?" for _ in source_message_ids)
            if self._connection.execute(
                f"SELECT 1 FROM memory_summary_source_exclusions WHERE source_message_id IN ({placeholders}) LIMIT 1",
                source_message_ids,
            ).fetchone() is not None:
                return None
            latest = self._latest_covered_raw(session_id)
            if latest is not None and latest.covered_message_end_id is not None:
                positions = {
                    str(row["id"]): index
                    for index, row in enumerate(
                        self._connection.execute(
                            "SELECT id FROM messages WHERE session_id = ? ORDER BY created_at ASC, rowid ASC",
                            (session_id,),
                        ).fetchall()
                    )
                }
                latest_end = positions.get(latest.covered_message_end_id)
                batch_start = positions.get(source_message_ids[0])
                if latest_end is not None and batch_start is not None and latest_end >= batch_start:
                    return None
            return self._create_in_transaction(
                session_id=session_id,
                summary_text=summary_text,
                source=SessionSummarySource.GENERATED,
                covered_message_start_id=source_message_ids[0],
                covered_message_end_id=source_message_ids[-1],
                message_count=len(source_message_ids),
                metadata=metadata,
                observed_memory_summary_barrier=observed_memory_summary_barrier,
            )

    def list_for_session(self, session_id: str) -> list[SessionSummary]:
        rows = self._connection.execute(
            "SELECT * FROM session_summaries WHERE session_id = ? ORDER BY created_at ASC, rowid ASC",
            (session_id,),
        ).fetchall()
        return [self._safe_summary(row) for row in rows]

    def latest_for_session(self, session_id: str) -> SessionSummary | None:
        row = self._connection.execute(
            "SELECT * FROM session_summaries WHERE session_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return self._safe_summary(row) if row else None

    def latest_covered_for_session(self, session_id: str) -> SessionSummary | None:
        raw = self._latest_covered_raw(session_id)
        if raw is None:
            return None
        row = self._connection.execute(
            "SELECT * FROM session_summaries WHERE id = ?", (raw.id,)
        ).fetchone()
        assert row is not None
        return self._safe_summary(row)

    def _latest_covered_raw(self, session_id: str) -> SessionSummary | None:
        row = self._connection.execute(
            """
            SELECT * FROM session_summaries
            WHERE session_id = ? AND covered_message_end_id IS NOT NULL
            ORDER BY created_at DESC, rowid DESC LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        return self._raw_summary(row) if row else None

    def _safe_summary(self, row: sqlite3.Row) -> SessionSummary:
        summary = self._raw_summary(row)
        current = self._current_barrier_generation()
        stale = summary.observed_memory_summary_barrier < current
        if not stale and summary.covered_message_start_id is not None:
            covered_ids = self._coverage_ids(summary)
            if covered_ids:
                placeholders = ", ".join("?" for _ in covered_ids)
                stale = self._connection.execute(
                    f"SELECT 1 FROM memory_summary_source_exclusions WHERE source_message_id IN ({placeholders}) LIMIT 1",
                    covered_ids,
                ).fetchone() is not None
        if not stale:
            return summary
        metadata = dict(summary.metadata)
        metadata["stale"] = True
        return SessionSummary(
            **{
                **summary.__dict__,
                "summary_text": None,
                "metadata": metadata,
                "stale": True,
            }
        )

    def _coverage_ids(self, summary: SessionSummary) -> tuple[str, ...]:
        rows = self._connection.execute(
            "SELECT id FROM messages WHERE session_id = ? ORDER BY created_at ASC, rowid ASC",
            (summary.session_id,),
        ).fetchall()
        ids = [str(row["id"]) for row in rows]
        try:
            start = ids.index(str(summary.covered_message_start_id))
            end = ids.index(str(summary.covered_message_end_id))
        except ValueError:
            return ()
        return tuple(ids[start : end + 1])

    def _current_barrier_generation(self) -> int:
        row = self._connection.execute(
            "SELECT generation FROM memory_summary_barrier WHERE singleton_id = 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("memory summary barrier is unavailable")
        return int(row["generation"])

    @staticmethod
    def _raw_summary(row: sqlite3.Row) -> SessionSummary:
        return SessionSummary(
            id=str(row["id"]),
            session_id=str(row["session_id"]),
            summary_text=(
                str(row["summary_text"])
                if row["summary_text"] is not None
                else None
            ),
            source=SessionSummarySource(str(row["source"])),
            covered_message_start_id=row["covered_message_start_id"],
            covered_message_end_id=row["covered_message_end_id"],
            message_count=int(row["message_count"]),
            metadata=metadata_from_json(str(row["metadata_json"])),
            created_at=_from_iso(str(row["created_at"])),
            updated_at=_from_iso(str(row["updated_at"])),
            observed_memory_summary_barrier=int(
                row["observed_memory_summary_barrier"]
            ),
        )

    def delete(self, summary_id: str) -> bool:
        row = self._connection.execute(
            "SELECT provenance_state, source_set_hash FROM session_summaries WHERE id=?",
            (summary_id,),
        ).fetchone()
        if (
            row is not None
            and str(row["provenance_state"]) == "exact"
            and row["source_set_hash"] is not None
        ):
            raise ValueError(
                "exact summaries must be redacted through the invalidation service"
            )
        now = _to_iso(_now())
        cursor = self._connection.execute(
            """
            UPDATE session_summaries
            SET summary_text=NULL, payload_state='redacted', redacted_at=?,
                redaction_reason_code='legacy_manual_redaction', updated_at=?
            WHERE id=? AND payload_state='active'
            """,
            (now, now, summary_id),
        )
        self._connection.commit()
        return cursor.rowcount > 0
