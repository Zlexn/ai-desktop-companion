from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import sqlite3
from threading import Lock
from typing import Iterator
from uuid import uuid4

from app.core.errors import NotFoundError
from app.domain.models import MemoryJobAuditOutcome
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.services.memory_source_reference import MemorySourceReferenceService


class SessionDeletionFence:
    def __init__(self) -> None:
        self._locks: dict[str, Lock] = {}
        self._guard = Lock()

    @contextmanager
    def hold(self, session_reference_hash: str) -> Iterator[None]:
        with self._guard:
            lock = self._locks.setdefault(session_reference_hash, Lock())
        lock.acquire()
        try:
            yield
        finally:
            lock.release()


@dataclass(frozen=True)
class SessionDeletionResult:
    session_id: str
    session_reference_hash: str
    deletion_generation: int
    cancelled_job_ids: tuple[str, ...]


class SessionDeletionCoordinator:
    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        versioned: VersionedMemoryRepository,
        source_references: MemorySourceReferenceService,
        deletion_fence: SessionDeletionFence | None = None,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self._connection = connection
        self._versioned = versioned
        self._source_references = source_references
        self._deletion_fence = deletion_fence or SessionDeletionFence()
        self._fault_injector = fault_injector

    def delete(self, session_id: str) -> SessionDeletionResult:
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id must be a non-empty string")
        session_reference_hash = self._source_references.session_hash(session_id)
        now = datetime.now(UTC)
        with self._deletion_fence.hold(session_reference_hash):
            return self._delete_locked(
                session_id=session_id,
                session_reference_hash=session_reference_hash,
                now=now,
            )

    def _delete_locked(
        self,
        *,
        session_id: str,
        session_reference_hash: str,
        now: datetime,
    ) -> SessionDeletionResult:
        with self._versioned.write_transaction():
            session = self._connection.execute(
                "SELECT id FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if session is None:
                raise NotFoundError("会话不存在。")

            message_rows = self._connection.execute(
                "SELECT id FROM messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
            message_hashes = {
                str(row["id"]): self._source_references.message_hash(str(row["id"]))
                for row in message_rows
            }

            generation = self._increment_generation(
                session_reference_hash=session_reference_hash,
                now=now,
            )
            self._checkpoint("generation")

            cancelled_job_ids = self._terminalize_jobs(
                session_id=session_id,
                session_reference_hash=session_reference_hash,
                message_hashes=message_hashes,
                now=now,
            )
            self._checkpoint("jobs")

            self._downgrade_candidates(
                session_id=session_id,
                session_reference_hash=session_reference_hash,
            )
            self._checkpoint("candidates")

            self._downgrade_versions(
                session_id=session_id,
                session_reference_hash=session_reference_hash,
            )
            self._checkpoint("versions")

            self._downgrade_evidence(
                session_id=session_id,
                session_reference_hash=session_reference_hash,
                message_hashes=message_hashes,
                now=now,
            )
            self._checkpoint("evidence")

            self._downgrade_job_sources(
                session_id=session_id,
                session_reference_hash=session_reference_hash,
                message_hashes=message_hashes,
            )
            self._clear_activity_turn_ids(session_id=session_id)
            self._clear_emotion_analysis_sources(session_id=session_id)
            self._connection.execute(
                """
                UPDATE emotion_events
                SET source_session_id = NULL,
                    source_user_message_id = NULL,
                    source_assistant_message_id = NULL
                WHERE source_session_id = ?
                """,
                (session_id,),
            )
            self._checkpoint("sources")

            self._checkpoint("summaries")
            self._checkpoint("messages")
            cursor = self._connection.execute(
                "DELETE FROM sessions WHERE id = ?",
                (session_id,),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("session changed during deletion")
            self._checkpoint("session")

            return SessionDeletionResult(
                session_id=session_id,
                session_reference_hash=session_reference_hash,
                deletion_generation=generation,
                cancelled_job_ids=tuple(cancelled_job_ids),
            )

    def _increment_generation(
        self,
        *,
        session_reference_hash: str,
        now: datetime,
    ) -> int:
        row = self._connection.execute(
            """
            INSERT INTO memory_deletion_generations (
                scope, scope_id, generation, updated_at
            ) VALUES ('session', ?, 1, ?)
            ON CONFLICT(scope, scope_id) DO UPDATE SET
                generation = memory_deletion_generations.generation + 1,
                updated_at = excluded.updated_at
            RETURNING generation
            """,
            (session_reference_hash, now.isoformat()),
        ).fetchone()
        if row is None:
            raise RuntimeError("session deletion generation update failed")
        return int(row["generation"])

    def _terminalize_jobs(
        self,
        *,
        session_id: str,
        session_reference_hash: str,
        message_hashes: dict[str, str],
        now: datetime,
    ) -> list[str]:
        rows = self._connection.execute(
            """
            SELECT * FROM memory_jobs
            WHERE session_id = ? AND mode = 'auto_active'
              AND status IN ('pending', 'running')
            ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END,
                     created_at ASC, id ASC
            """,
            (session_id,),
        ).fetchall()
        cancelled: list[str] = []
        for row in rows:
            job_id = str(row["id"])
            session_hash = self._validated_reference_hash(
                existing=row["source_session_reference_hash"],
                computed=session_reference_hash,
                name="job session",
            )
            user_id = str(row["user_message_id"])
            assistant_id = str(row["assistant_message_id"])
            user_hash = self._validated_reference_hash(
                existing=row["source_user_message_reference_hash"],
                computed=self._required_message_hash(user_id, message_hashes),
                name="job user message",
            )
            assistant_hash = self._validated_reference_hash(
                existing=row["source_assistant_message_reference_hash"],
                computed=self._required_message_hash(assistant_id, message_hashes),
                name="job assistant message",
            )
            self._connection.execute(
                """
                UPDATE memory_jobs
                SET source_session_reference_hash = ?,
                    source_user_message_reference_hash = ?,
                    source_assistant_message_reference_hash = ?,
                    status = 'cancelled',
                    outcome = 'cancelled_session_deleted',
                    error_category = NULL,
                    finished_at = ?
                WHERE id = ? AND status IN ('pending', 'running')
                """,
                (
                    session_hash,
                    user_hash,
                    assistant_hash,
                    now.isoformat(),
                    job_id,
                ),
            )
            self._connection.execute(
                """
                INSERT INTO memory_job_audits (
                    id, job_id, outcome, decision_counts_json,
                    reason_counts_json, outcome_counts_json, proposal_count,
                    accepted_count, rejected_count, redaction_count, provider,
                    model, elapsed_ms, schema_version, governor_version,
                    consent_generation, created_at
                ) VALUES (?, ?, ?, '{}', '{}', '{}', 0, 0, 0, 0, NULL,
                          NULL, NULL, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    job_id,
                    MemoryJobAuditOutcome.CANCELLED_SESSION_DELETED.value,
                    str(row["schema_version"]),
                    str(row["governor_version"]),
                    row["consent_generation"],
                    now.isoformat(),
                ),
            )
            cancelled.append(job_id)
        return cancelled

    def _downgrade_candidates(
        self,
        *,
        session_id: str,
        session_reference_hash: str,
    ) -> None:
        rows = self._connection.execute(
            "SELECT id, source_session_reference_hash FROM memories "
            "WHERE source_session_id = ? AND status IN ('pending', 'dismissed')",
            (session_id,),
        ).fetchall()
        for row in rows:
            reference_hash = self._validated_reference_hash(
                existing=row["source_session_reference_hash"],
                computed=session_reference_hash,
                name="memory candidate session",
            )
            self._connection.execute(
                "UPDATE memories SET source_session_reference_hash = ? "
                "WHERE id = ?",
                (reference_hash, str(row["id"])),
            )

    def _downgrade_versions(
        self,
        *,
        session_id: str,
        session_reference_hash: str,
    ) -> None:
        rows = self._connection.execute(
            "SELECT id, source_session_reference_hash FROM memory_versions "
            "WHERE source_session_id = ?",
            (session_id,),
        ).fetchall()
        for row in rows:
            reference_hash = self._validated_reference_hash(
                existing=row["source_session_reference_hash"],
                computed=session_reference_hash,
                name="memory version session",
            )
            self._connection.execute(
                "UPDATE memory_versions SET source_session_reference_hash = ?, "
                "source_session_id = NULL WHERE id = ?",
                (reference_hash, str(row["id"])),
            )

    def _downgrade_evidence(
        self,
        *,
        session_id: str,
        session_reference_hash: str,
        message_hashes: dict[str, str],
        now: datetime,
    ) -> None:
        rows = self._connection.execute(
            """
            SELECT evidence_id, source_message_id,
                   source_session_reference_hash, source_message_reference_hash
            FROM memory_evidence
            WHERE source_session_id = ?
            """,
            (session_id,),
        ).fetchall()
        for row in rows:
            message_id = str(row["source_message_id"])
            session_hash = self._validated_reference_hash(
                existing=row["source_session_reference_hash"],
                computed=session_reference_hash,
                name="Evidence session",
            )
            message_hash = self._validated_reference_hash(
                existing=row["source_message_reference_hash"],
                computed=self._required_message_hash(message_id, message_hashes),
                name="Evidence message",
            )
            self._connection.execute(
                """
                UPDATE memory_evidence
                SET source_session_reference_hash = ?,
                    source_message_reference_hash = ?,
                    source_available = 0,
                    source_deleted_at = ?,
                    source_session_id = NULL,
                    source_message_id = NULL
                WHERE evidence_id = ?
                """,
                (
                    session_hash,
                    message_hash,
                    now.isoformat(),
                    str(row["evidence_id"]),
                ),
            )

    def _downgrade_job_sources(
        self,
        *,
        session_id: str,
        session_reference_hash: str,
        message_hashes: dict[str, str],
    ) -> None:
        rows = self._connection.execute(
            "SELECT * FROM memory_jobs WHERE session_id = ?",
            (session_id,),
        ).fetchall()
        for row in rows:
            user_id = str(row["user_message_id"])
            assistant_id = str(row["assistant_message_id"])
            hashes = (
                self._validated_reference_hash(
                    existing=row["source_session_reference_hash"],
                    computed=session_reference_hash,
                    name="job session",
                ),
                self._validated_reference_hash(
                    existing=row["source_user_message_reference_hash"],
                    computed=self._required_message_hash(user_id, message_hashes),
                    name="job user message",
                ),
                self._validated_reference_hash(
                    existing=row["source_assistant_message_reference_hash"],
                    computed=self._required_message_hash(assistant_id, message_hashes),
                    name="job assistant message",
                ),
                self._source_references.message_hash(str(row["turn_id"])),
            )
            self._connection.execute(
                """
                UPDATE memory_jobs
                SET source_session_reference_hash = ?,
                    source_user_message_reference_hash = ?,
                    source_assistant_message_reference_hash = ?,
                    turn_id = ?,
                    session_id = NULL,
                    user_message_id = NULL,
                    assistant_message_id = NULL
                WHERE id = ?
                """,
                (*hashes, str(row["id"])),
            )

    def _clear_activity_turn_ids(self, *, session_id: str) -> None:
        session_hash = self._source_references.session_hash(session_id)
        rows = self._connection.execute(
            """
            SELECT activity.op_id, activity.turn_id
            FROM memory_write_activities AS activity
            JOIN memory_jobs AS job ON job.id = activity.job_id
            WHERE job.source_session_reference_hash = ?
            """,
            (session_hash,),
        ).fetchall()
        for row in rows:
            self._connection.execute(
                "UPDATE memory_write_activities SET turn_id = ? WHERE op_id = ?",
                (
                    self._source_references.message_hash(str(row["turn_id"])),
                    str(row["op_id"]),
                ),
            )

    def _clear_emotion_analysis_sources(self, *, session_id: str) -> None:
        self._connection.execute(
            "DELETE FROM emotion_analysis_audits WHERE source_session_id = ?",
            (session_id,),
        )
        self._connection.execute(
            "DELETE FROM emotion_analysis_jobs WHERE source_session_id = ?",
            (session_id,),
        )

    @staticmethod
    def _required_message_hash(
        message_id: str,
        message_hashes: dict[str, str],
    ) -> str:
        try:
            return message_hashes[message_id]
        except KeyError as exc:
            raise RuntimeError("session source message is unavailable") from exc

    @staticmethod
    def _validated_reference_hash(
        *,
        existing: object,
        computed: str,
        name: str,
    ) -> str:
        if existing is None:
            return computed
        persisted = str(existing)
        if persisted != computed:
            raise RuntimeError(f"{name} reference hash mismatch")
        return persisted

    def _checkpoint(self, name: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(name)
