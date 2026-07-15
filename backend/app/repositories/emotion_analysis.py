import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.models import (
    DEFAULT_EMOTION_SCOPE_ID,
    EmotionAnalysisAudit,
    EmotionAnalysisAuditOutcome,
    EmotionAnalysisConsent,
    EmotionAnalysisConsentStatus,
    EmotionAnalysisJob,
    EmotionAnalysisJobStatus,
)


def _now() -> datetime:
    return datetime.now(UTC)


class EmotionAnalysisRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._transaction_depth = 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._transaction_depth:
            self._transaction_depth += 1
            try:
                yield
            finally:
                self._transaction_depth -= 1
            return
        self._transaction_depth = 1
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            yield
        except BaseException:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()
        finally:
            self._transaction_depth = 0

    def _commit(self) -> None:
        if not self._transaction_depth:
            self._connection.commit()

    def _rollback(self) -> None:
        if not self._transaction_depth:
            self._connection.rollback()

    def get_consent(
        self,
        scope_id: str = DEFAULT_EMOTION_SCOPE_ID,
    ) -> EmotionAnalysisConsent:
        row = self._connection.execute(
            "SELECT * FROM emotion_analysis_consents WHERE scope_id = ?",
            (scope_id,),
        ).fetchone()
        if row is None:
            now = _now()
            self._connection.execute(
                """
                INSERT OR IGNORE INTO emotion_analysis_consents (
                    scope_id, status, disclosure_version, provider,
                    policy_fingerprint, generation, updated_at
                ) VALUES (?, 'unknown', NULL, NULL, NULL, 0, ?)
                """,
                (scope_id, now.isoformat()),
            )
            self._commit()
            row = self._connection.execute(
                "SELECT * FROM emotion_analysis_consents WHERE scope_id = ?",
                (scope_id,),
            ).fetchone()
        assert row is not None
        return self._consent_from_row(row)

    def set_consent(
        self,
        *,
        status: EmotionAnalysisConsentStatus,
        disclosure_version: str,
        provider: str,
        policy_fingerprint: str,
        scope_id: str = DEFAULT_EMOTION_SCOPE_ID,
    ) -> EmotionAnalysisConsent:
        now = _now()
        self._connection.execute(
            """
            INSERT INTO emotion_analysis_consents (
                scope_id, status, disclosure_version, provider,
                policy_fingerprint, generation, updated_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(scope_id) DO UPDATE SET
                status = excluded.status,
                disclosure_version = excluded.disclosure_version,
                provider = excluded.provider,
                policy_fingerprint = excluded.policy_fingerprint,
                generation = emotion_analysis_consents.generation + 1,
                updated_at = excluded.updated_at
            """,
            (
                scope_id,
                status.value,
                disclosure_version,
                provider,
                policy_fingerprint,
                now.isoformat(),
            ),
        )
        self._commit()
        return self.get_consent(scope_id)

    def reserve_job(
        self,
        *,
        source_session_id: str,
        source_user_message_id: str,
        source_assistant_message_id: str,
        schema_version: str,
        base_emotion_version: int,
        consent_generation: int,
        scope_id: str = DEFAULT_EMOTION_SCOPE_ID,
    ) -> tuple[EmotionAnalysisJob, bool]:
        now = _now()
        job_id = str(uuid4())
        cursor = self._connection.execute(
            """
            INSERT OR IGNORE INTO emotion_analysis_jobs (
                id, scope_id, source_session_id, source_user_message_id,
                source_assistant_message_id, schema_version, base_emotion_version,
                consent_generation, status, outcome_reason, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', NULL, ?, ?)
            """,
            (
                job_id,
                scope_id,
                source_session_id,
                source_user_message_id,
                source_assistant_message_id,
                schema_version,
                base_emotion_version,
                consent_generation,
                now.isoformat(),
                now.isoformat(),
            ),
        )
        self._commit()
        row = self._connection.execute(
            """
            SELECT * FROM emotion_analysis_jobs
            WHERE source_assistant_message_id = ? AND schema_version = ?
            """,
            (source_assistant_message_id, schema_version),
        ).fetchone()
        assert row is not None
        return self._job_from_row(row), cursor.rowcount == 1

    def update_job_status(
        self,
        job_id: str,
        *,
        status: EmotionAnalysisJobStatus,
        outcome_reason: str | None,
    ) -> EmotionAnalysisJob:
        now = _now()
        cursor = self._connection.execute(
            """
            UPDATE emotion_analysis_jobs
            SET status = ?, outcome_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (status.value, outcome_reason, now.isoformat(), job_id),
        )
        if cursor.rowcount != 1:
            self._rollback()
            raise KeyError(job_id)
        self._commit()
        row = self._connection.execute(
            "SELECT * FROM emotion_analysis_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        assert row is not None
        return self._job_from_row(row)

    def recover_incomplete_jobs(self) -> int:
        now = _now()
        cursor = self._connection.execute(
            """
            UPDATE emotion_analysis_jobs
            SET status = 'failed', outcome_reason = 'interrupted', updated_at = ?
            WHERE status IN ('queued', 'running')
            """,
            (now.isoformat(),),
        )
        self._commit()
        return cursor.rowcount

    def append_audit(
        self,
        *,
        job_id: str,
        outcome: EmotionAnalysisAuditOutcome,
        source_session_id: str,
        source_user_message_id: str,
        source_assistant_message_id: str,
        schema_version: str,
        provider: str,
        model: str,
        message_count: int,
        memory_count: int,
        input_characters: int,
        redaction_count: int,
        elapsed_ms: int,
        reason_code: str,
        scope_id: str = DEFAULT_EMOTION_SCOPE_ID,
    ) -> EmotionAnalysisAudit:
        audit = EmotionAnalysisAudit(
            id=str(uuid4()),
            job_id=job_id,
            scope_id=scope_id,
            outcome=outcome,
            source_session_id=source_session_id,
            source_user_message_id=source_user_message_id,
            source_assistant_message_id=source_assistant_message_id,
            schema_version=schema_version,
            provider=provider,
            model=model,
            message_count=message_count,
            memory_count=memory_count,
            input_characters=input_characters,
            redaction_count=redaction_count,
            elapsed_ms=elapsed_ms,
            reason_code=reason_code,
            created_at=_now(),
        )
        self._connection.execute(
            """
            INSERT INTO emotion_analysis_audits (
                id, job_id, scope_id, outcome, source_session_id,
                source_user_message_id, source_assistant_message_id,
                schema_version, provider, model, message_count, memory_count,
                input_characters, redaction_count, elapsed_ms, reason_code, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit.id,
                audit.job_id,
                audit.scope_id,
                audit.outcome.value,
                audit.source_session_id,
                audit.source_user_message_id,
                audit.source_assistant_message_id,
                audit.schema_version,
                audit.provider,
                audit.model,
                audit.message_count,
                audit.memory_count,
                audit.input_characters,
                audit.redaction_count,
                audit.elapsed_ms,
                audit.reason_code,
                audit.created_at.isoformat(),
            ),
        )
        self._commit()
        return audit

    def list_audits(
        self,
        *,
        limit: int,
        scope_id: str = DEFAULT_EMOTION_SCOPE_ID,
    ) -> list[EmotionAnalysisAudit]:
        rows = self._connection.execute(
            """
            SELECT * FROM emotion_analysis_audits
            WHERE scope_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (scope_id, limit),
        ).fetchall()
        return [self._audit_from_row(row) for row in rows]

    @staticmethod
    def _consent_from_row(row: sqlite3.Row) -> EmotionAnalysisConsent:
        return EmotionAnalysisConsent(
            scope_id=str(row["scope_id"]),
            status=EmotionAnalysisConsentStatus(str(row["status"])),
            disclosure_version=row["disclosure_version"],
            provider=row["provider"],
            policy_fingerprint=row["policy_fingerprint"],
            generation=int(row["generation"]),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> EmotionAnalysisJob:
        return EmotionAnalysisJob(
            id=str(row["id"]),
            scope_id=str(row["scope_id"]),
            source_session_id=str(row["source_session_id"]),
            source_user_message_id=str(row["source_user_message_id"]),
            source_assistant_message_id=str(row["source_assistant_message_id"]),
            schema_version=str(row["schema_version"]),
            base_emotion_version=int(row["base_emotion_version"]),
            consent_generation=int(row["consent_generation"]),
            status=EmotionAnalysisJobStatus(str(row["status"])),
            outcome_reason=row["outcome_reason"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    @staticmethod
    def _audit_from_row(row: sqlite3.Row) -> EmotionAnalysisAudit:
        return EmotionAnalysisAudit(
            id=str(row["id"]),
            job_id=str(row["job_id"]),
            scope_id=str(row["scope_id"]),
            outcome=EmotionAnalysisAuditOutcome(str(row["outcome"])),
            source_session_id=str(row["source_session_id"]),
            source_user_message_id=str(row["source_user_message_id"]),
            source_assistant_message_id=str(row["source_assistant_message_id"]),
            schema_version=str(row["schema_version"]),
            provider=str(row["provider"]),
            model=str(row["model"]),
            message_count=int(row["message_count"]),
            memory_count=int(row["memory_count"]),
            input_characters=int(row["input_characters"]),
            redaction_count=int(row["redaction_count"]),
            elapsed_ms=int(row["elapsed_ms"]),
            reason_code=str(row["reason_code"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )
