import json
import re
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.models import (
    MemoryAutomationMode,
    MemoryAutoActiveJobSnapshot,
    MemoryExtractionConsent,
    MemoryExtractionConsentStatus,
    MemoryExtractorRoute,
    MemoryJob,
    MemoryJobAudit,
    MemoryJobAuditOutcome,
    MemoryJobStatus,
    MemoryWriteConsent,
    MemoryWriteConsentStatus,
    MemoryType,
)


DEFAULT_MEMORY_EXTRACTION_SCOPE_ID = "default"
DEFAULT_MEMORY_WRITE_SCOPE_ID = "default"
_TERMINAL_STATUSES = {
    MemoryJobStatus.SUCCEEDED,
    MemoryJobStatus.FAILED,
    MemoryJobStatus.CANCELLED,
}
_COUNT_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SUCCEEDED_OUTCOMES = {
    MemoryJobAuditOutcome.SHADOW_RECORDED,
    MemoryJobAuditOutcome.COMPLETED_WITH_DECISIONS,
    MemoryJobAuditOutcome.SKIPPED_NO_EXTRACTOR,
    MemoryJobAuditOutcome.SKIPPED_NO_WRITE_CONSENT,
    MemoryJobAuditOutcome.SKIPPED_WRITE_CONSENT_CHANGED,
    MemoryJobAuditOutcome.SKIPPED_TURN_BEFORE_WRITE_GRANT,
    MemoryJobAuditOutcome.SKIPPED_MODE_CHANGED,
    MemoryJobAuditOutcome.SKIPPED_NO_CONSENT,
    MemoryJobAuditOutcome.SKIPPED_CONSENT_CHANGED,
    MemoryJobAuditOutcome.SKIPPED_GOVERNOR_POLICY,
}
_FAILED_ERROR_CATEGORIES = {
    MemoryJobAuditOutcome.INVALID_OUTPUT: {"invalid_output"},
    MemoryJobAuditOutcome.PROVIDER_ERROR: {"provider_error"},
    MemoryJobAuditOutcome.FAILED: {"invalid_job_input", "database_error"},
}
_SENSITIVE_IDENTIFIER_MARKERS = ("sk-", "bearer", "private key", "private-key")


def _now() -> datetime:
    return datetime.now(UTC)


class MemoryAutomationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._transaction_depth = 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._transaction_depth:
            savepoint = f"memory_automation_sp_{self._transaction_depth}"
            self._transaction_depth += 1
            self._connection.execute(f"SAVEPOINT {savepoint}")
            try:
                yield
            except BaseException:
                self._connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                self._connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            else:
                self._connection.execute(f"RELEASE SAVEPOINT {savepoint}")
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

    def get_consent(
        self,
        scope_id: str = DEFAULT_MEMORY_EXTRACTION_SCOPE_ID,
    ) -> MemoryExtractionConsent:
        with self.transaction():
            row = self._connection.execute(
                "SELECT * FROM memory_extraction_consents WHERE scope_id = ?",
                (scope_id,),
            ).fetchone()
            if row is None:
                now = _now().isoformat()
                self._connection.execute(
                    """
                    INSERT INTO memory_extraction_consents (
                        scope_id, status, purpose, provider, disclosure_version,
                        disclosed_fields_json, generation, created_at, updated_at
                    ) VALUES (?, 'unknown', NULL, NULL, NULL, '[]', 0, ?, ?)
                    ON CONFLICT(scope_id) DO NOTHING
                    """,
                    (scope_id, now, now),
                )
                row = self._connection.execute(
                    "SELECT * FROM memory_extraction_consents WHERE scope_id = ?",
                    (scope_id,),
                ).fetchone()
            assert row is not None
            return self._consent_from_row(row)

    def set_consent(
        self,
        *,
        status: MemoryExtractionConsentStatus,
        purpose: str,
        provider: str,
        disclosure_version: str,
        disclosed_fields: tuple[str, ...],
        scope_id: str = DEFAULT_MEMORY_EXTRACTION_SCOPE_ID,
    ) -> MemoryExtractionConsent:
        disclosed_fields_json = json.dumps(
            list(disclosed_fields),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self.transaction():
            now = _now().isoformat()
            self._connection.execute(
                """
                INSERT INTO memory_extraction_consents (
                    scope_id, status, purpose, provider, disclosure_version,
                    disclosed_fields_json, generation, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(scope_id) DO UPDATE SET
                    status = excluded.status,
                    purpose = excluded.purpose,
                    provider = excluded.provider,
                    disclosure_version = excluded.disclosure_version,
                    disclosed_fields_json = excluded.disclosed_fields_json,
                    generation = memory_extraction_consents.generation + 1,
                    updated_at = excluded.updated_at
                """,
                (
                    scope_id,
                    status.value,
                    purpose,
                    provider,
                    disclosure_version,
                    disclosed_fields_json,
                    now,
                    now,
                ),
            )
            row = self._connection.execute(
                "SELECT * FROM memory_extraction_consents WHERE scope_id = ?",
                (scope_id,),
            ).fetchone()
            assert row is not None
            return self._consent_from_row(row)

    def get_write_consent(
        self,
        scope_id: str = DEFAULT_MEMORY_WRITE_SCOPE_ID,
    ) -> MemoryWriteConsent:
        with self.transaction():
            row = self._connection.execute(
                "SELECT * FROM memory_write_consents WHERE scope_id = ?",
                (scope_id,),
            ).fetchone()
            if row is None:
                now = _now().isoformat()
                self._connection.execute(
                    """
                    INSERT INTO memory_write_consents (
                        scope_id, status, purpose, policy_version,
                        allowed_memory_types_version, allowed_memory_types_json,
                        retention_disclosure_version, generation, granted_at,
                        created_at, updated_at
                    ) VALUES (?, 'unknown', NULL, NULL, NULL, '[]', NULL,
                              0, NULL, ?, ?)
                    ON CONFLICT(scope_id) DO NOTHING
                    """,
                    (scope_id, now, now),
                )
                row = self._connection.execute(
                    "SELECT * FROM memory_write_consents WHERE scope_id = ?",
                    (scope_id,),
                ).fetchone()
            assert row is not None
            return self._write_consent_from_row(row)

    def set_write_consent(
        self,
        *,
        status: MemoryWriteConsentStatus,
        purpose: str,
        policy_version: str,
        allowed_memory_types_version: str,
        allowed_memory_types: tuple[MemoryType, ...],
        retention_disclosure_version: str,
        scope_id: str = DEFAULT_MEMORY_WRITE_SCOPE_ID,
    ) -> MemoryWriteConsent:
        allowed_json = json.dumps(
            [memory_type.value for memory_type in allowed_memory_types],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self.transaction():
            now = _now().isoformat()
            granted_at = (
                now if status is MemoryWriteConsentStatus.GRANTED else None
            )
            self._connection.execute(
                """
                INSERT INTO memory_write_consents (
                    scope_id, status, purpose, policy_version,
                    allowed_memory_types_version, allowed_memory_types_json,
                    retention_disclosure_version, generation, granted_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(scope_id) DO UPDATE SET
                    status = excluded.status,
                    purpose = excluded.purpose,
                    policy_version = excluded.policy_version,
                    allowed_memory_types_version = excluded.allowed_memory_types_version,
                    allowed_memory_types_json = excluded.allowed_memory_types_json,
                    retention_disclosure_version = excluded.retention_disclosure_version,
                    generation = memory_write_consents.generation + 1,
                    granted_at = excluded.granted_at,
                    updated_at = excluded.updated_at
                """,
                (
                    scope_id,
                    status.value,
                    purpose,
                    policy_version,
                    allowed_memory_types_version,
                    allowed_json,
                    retention_disclosure_version,
                    granted_at,
                    now,
                    now,
                ),
            )
            row = self._connection.execute(
                "SELECT * FROM memory_write_consents WHERE scope_id = ?",
                (scope_id,),
            ).fetchone()
            assert row is not None
            return self._write_consent_from_row(row)

    def reserve_job(
        self,
        *,
        turn_id: str,
        schema_version: str,
        session_id: str,
        user_message_id: str,
        assistant_message_id: str,
        mode: MemoryAutomationMode,
        extractor_route: MemoryExtractorRoute,
        governor_version: str,
        persona_artifact_id: str | None = None,
        auto_active_snapshot: MemoryAutoActiveJobSnapshot | None = None,
        source_session_reference_hash: str | None = None,
        source_user_message_reference_hash: str | None = None,
        source_assistant_message_reference_hash: str | None = None,
        chat_turn_id: str | None = None,
    ) -> tuple[MemoryJob, bool]:
        if mode is MemoryAutomationMode.SHADOW_AUTO and auto_active_snapshot is not None:
            raise ValueError("shadow_auto job cannot have an auto_active snapshot")
        if mode is MemoryAutomationMode.AUTO_ACTIVE and (
            auto_active_snapshot is None
            or not source_session_reference_hash
            or not source_user_message_reference_hash
            or not source_assistant_message_reference_hash
        ):
            raise ValueError("auto_active job requires a complete frozen snapshot")
        if mode not in {
            MemoryAutomationMode.SHADOW_AUTO,
            MemoryAutomationMode.AUTO_ACTIVE,
        }:
            raise ValueError("memory automation jobs require an automatic mode")

        with self.transaction():
            job_id = str(uuid4())
            created_at = _now().isoformat()
            snapshot = auto_active_snapshot
            type_generations_json = (
                json.dumps(
                    snapshot.type_deletion_generations,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if snapshot is not None
                else None
            )
            cursor = self._connection.execute(
                """
                INSERT INTO memory_jobs (
                    id, turn_id, schema_version, session_id, user_message_id,
                    assistant_message_id, mode, extractor_route, status,
                    attempt_count, outcome, error_category, governor_version,
                    consent_generation, created_at, started_at, finished_at,
                    turn_completed_at, reserved_mode, workflow_version,
                    commit_policy_version, canonicalization_version,
                    allowed_memory_types_version, write_consent_generation,
                    remote_consent_generation, remote_authority_fingerprint,
                    global_deletion_generation, session_deletion_generation,
                    type_deletion_generations_json,
                    source_session_reference_hash,
                    source_user_message_reference_hash,
                    source_assistant_message_reference_hash,
                    persona_artifact_id, chat_turn_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, NULL, NULL,
                          ?, NULL, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(turn_id, schema_version) DO NOTHING
                """,
                (
                    job_id,
                    turn_id,
                    schema_version,
                    session_id,
                    user_message_id,
                    assistant_message_id,
                    mode.value,
                    extractor_route.value,
                    governor_version,
                    created_at,
                    snapshot.turn_completed_at.isoformat() if snapshot else None,
                    snapshot.reserved_mode.value if snapshot else None,
                    snapshot.workflow_version if snapshot else None,
                    snapshot.commit_policy_version if snapshot else None,
                    snapshot.canonicalization_version if snapshot else None,
                    snapshot.allowed_memory_types_version if snapshot else None,
                    snapshot.write_consent_generation if snapshot else None,
                    snapshot.remote_consent_generation if snapshot else None,
                    snapshot.remote_authority_fingerprint if snapshot else None,
                    snapshot.global_deletion_generation if snapshot else None,
                    snapshot.session_deletion_generation if snapshot else None,
                    type_generations_json,
                    source_session_reference_hash,
                    source_user_message_reference_hash,
                    source_assistant_message_reference_hash,
                    persona_artifact_id,
                    chat_turn_id,
                ),
            )
            row = self._connection.execute(
                "SELECT * FROM memory_jobs WHERE turn_id = ? AND schema_version = ?",
                (turn_id, schema_version),
            ).fetchone()
            assert row is not None
            return self._job_from_row(row), cursor.rowcount == 1

    def require_job(self, job_id: str) -> MemoryJob:
        row = self._connection.execute(
            "SELECT * FROM memory_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return self._job_from_row(row)

    def update_job_status(
        self,
        job_id: str,
        *,
        status: MemoryJobStatus,
        outcome: MemoryJobAuditOutcome | None = None,
        error_category: str | None = None,
        consent_generation: int | None = None,
    ) -> MemoryJob:
        if (
            status is not MemoryJobStatus.RUNNING
            or outcome is not None
            or error_category is not None
        ):
            raise ValueError("update_job_status only permits pending to running")
        if consent_generation is not None:
            self._validate_nonnegative_integer(consent_generation, "consent_generation")
        with self.transaction():
            current = self.require_job(job_id)
            if current.status is not MemoryJobStatus.PENDING:
                raise ValueError("update_job_status only permits pending to running")

            now = _now().isoformat()
            cursor = self._connection.execute(
                """
                UPDATE memory_jobs
                SET status = 'running',
                    attempt_count = attempt_count + 1,
                    consent_generation = COALESCE(?, consent_generation),
                    started_at = COALESCE(started_at, ?)
                WHERE id = ? AND status = 'pending'
                """,
                (consent_generation, now, job_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("memory job changed during status transition")
            return self.require_job(job_id)

    def complete_job_with_audit(
        self,
        job_id: str,
        *,
        status: MemoryJobStatus,
        outcome: MemoryJobAuditOutcome,
        decision_counts: dict[str, int],
        reason_counts: dict[str, int],
        outcome_counts: dict[str, int] | None = None,
        proposal_count: int,
        accepted_count: int,
        rejected_count: int,
        redaction_count: int,
        provider: str | None,
        model: str | None,
        elapsed_ms: int | None,
        consent_generation: int | None,
        error_category: str | None = None,
    ) -> tuple[MemoryJob, MemoryJobAudit]:
        if status not in _TERMINAL_STATUSES:
            raise ValueError("completion status must be terminal")
        self._validate_completion_metadata(status, outcome, error_category)
        self._validate_identifier(provider)
        self._validate_identifier(model)
        serialized_decisions = self._validate_and_serialize_counts(
            decision_counts,
            name="decision",
        )
        serialized_reasons = self._validate_and_serialize_counts(
            reason_counts,
            name="reason",
        )
        normalized_outcomes = outcome_counts or {}
        serialized_outcomes = self._validate_and_serialize_counts(
            normalized_outcomes,
            name="outcome",
        )
        self._validate_nonnegative_integer(proposal_count, "proposal_count")
        self._validate_nonnegative_integer(accepted_count, "accepted_count")
        self._validate_nonnegative_integer(rejected_count, "rejected_count")
        self._validate_nonnegative_integer(redaction_count, "redaction_count")
        if elapsed_ms is not None:
            self._validate_nonnegative_integer(elapsed_ms, "elapsed_ms")
        if consent_generation is not None:
            self._validate_nonnegative_integer(consent_generation, "consent_generation")
        if proposal_count != accepted_count + rejected_count:
            raise ValueError("proposal_count must equal accepted_count + rejected_count")
        if sum(decision_counts.values()) != proposal_count:
            raise ValueError("decision counts must equal proposal_count")
        if sum(reason_counts.values()) != proposal_count:
            raise ValueError("reason counts must equal proposal_count")
        if normalized_outcomes and sum(normalized_outcomes.values()) != proposal_count:
            raise ValueError("outcome counts must equal proposal_count")

        with self.transaction():
            current = self.require_job(job_id)
            if current.status in _TERMINAL_STATUSES:
                return current, self._require_audit_for_job(job_id)

            now = _now()
            cursor = self._connection.execute(
                """
                UPDATE memory_jobs
                SET status = ?, outcome = ?, error_category = ?,
                    consent_generation = COALESCE(?, consent_generation),
                    finished_at = ?
                WHERE id = ? AND status IN ('pending', 'running')
                """,
                (
                    status.value,
                    outcome.value,
                    error_category,
                    consent_generation,
                    now.isoformat(),
                    job_id,
                ),
            )
            if cursor.rowcount == 0:
                terminal = self.require_job(job_id)
                if terminal.status not in _TERMINAL_STATUSES:
                    raise RuntimeError("memory job could not be completed")
                return terminal, self._require_audit_for_job(job_id)

            audit_id = str(uuid4())
            self._connection.execute(
                """
                INSERT INTO memory_job_audits (
                    id, job_id, outcome, decision_counts_json,
                    reason_counts_json, outcome_counts_json, proposal_count,
                    accepted_count, rejected_count, redaction_count, provider,
                    model, elapsed_ms, schema_version, governor_version,
                    consent_generation, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    job_id,
                    outcome.value,
                    serialized_decisions,
                    serialized_reasons,
                    serialized_outcomes,
                    proposal_count,
                    accepted_count,
                    rejected_count,
                    redaction_count,
                    provider,
                    model,
                    elapsed_ms,
                    current.schema_version,
                    current.governor_version,
                    consent_generation if consent_generation is not None else current.consent_generation,
                    now.isoformat(),
                ),
            )
            return self.require_job(job_id), self._require_audit_for_job(job_id)

    def cancel_job(self, job_id: str) -> MemoryJob:
        current = self.require_job(job_id)
        if current.status in _TERMINAL_STATUSES:
            return current
        completed, _ = self.complete_job_with_audit(
            job_id,
            status=MemoryJobStatus.CANCELLED,
            outcome=MemoryJobAuditOutcome.CANCELLED,
            decision_counts={},
            reason_counts={},
            proposal_count=0,
            accepted_count=0,
            rejected_count=0,
            redaction_count=0,
            provider=None,
            model=None,
            elapsed_ms=None,
            consent_generation=None,
            error_category="interrupted",
        )
        return completed

    def recover_incomplete_jobs(
        self,
        *,
        mode: MemoryAutomationMode | None = None,
        compatible_job: Callable[[MemoryJob], bool] | None = None,
    ) -> list[str]:
        where = "status IN ('pending', 'running')"
        parameters: tuple[str, ...] = ()
        if mode is not None:
            where += " AND mode = ?"
            parameters = (mode.value,)
        with self.transaction():
            rows = self._connection.execute(
                f"""
                SELECT * FROM memory_jobs
                WHERE {where}
                ORDER BY created_at ASC, id ASC
                """,
                parameters,
            ).fetchall()
            jobs = [self._job_from_row(row) for row in rows]
            recoverable: list[str] = []
            for job in jobs:
                if compatible_job is not None and not compatible_job(job):
                    self.complete_job_with_audit(
                        job.id,
                        status=MemoryJobStatus.SUCCEEDED,
                        outcome=MemoryJobAuditOutcome.SKIPPED_MODE_CHANGED,
                        decision_counts={},
                        reason_counts={},
                        outcome_counts={},
                        proposal_count=0,
                        accepted_count=0,
                        rejected_count=0,
                        redaction_count=0,
                        provider=None,
                        model=None,
                        elapsed_ms=None,
                        consent_generation=(
                            job.auto_active_snapshot.write_consent_generation
                            if job.auto_active_snapshot is not None
                            else None
                        ),
                    )
                    continue
                self._connection.execute(
                    "UPDATE memory_jobs SET status = 'pending' "
                    "WHERE id = ? AND status = 'running'",
                    (job.id,),
                )
                recoverable.append(job.id)
            return recoverable

    def reconcile_incomplete_jobs(
        self,
        *,
        compatible_job: Callable[[MemoryJob], bool],
    ) -> list[str]:
        return self.recover_incomplete_jobs(compatible_job=compatible_job)

    def list_jobs(self, *, limit: int = 20) -> list[MemoryJob]:
        self._validate_limit(limit)
        rows = self._connection.execute(
            "SELECT * FROM memory_jobs ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def list_audits(self, *, limit: int = 20) -> list[MemoryJobAudit]:
        self._validate_limit(limit)
        rows = self._connection.execute(
            "SELECT * FROM memory_job_audits ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._audit_from_row(row) for row in rows]

    @staticmethod
    def _validate_nonnegative_integer(value: int, name: str) -> None:
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")

    @classmethod
    def _validate_and_serialize_counts(
        cls,
        counts: Mapping[str, int],
        *,
        name: str,
    ) -> str:
        for key, value in counts.items():
            if not isinstance(key, str) or _COUNT_KEY_PATTERN.fullmatch(key) is None:
                raise ValueError(f"{name} count keys must be metadata codes")
            cls._validate_nonnegative_integer(value, f"{name} count")
        return json.dumps(dict(counts), ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _validate_completion_metadata(
        status: MemoryJobStatus,
        outcome: MemoryJobAuditOutcome,
        error_category: str | None,
    ) -> None:
        valid = False
        if status is MemoryJobStatus.SUCCEEDED:
            valid = outcome in _SUCCEEDED_OUTCOMES and error_category is None
        elif status is MemoryJobStatus.FAILED:
            valid = error_category in _FAILED_ERROR_CATEGORIES.get(outcome, set())
        elif status is MemoryJobStatus.CANCELLED:
            valid = (
                outcome is MemoryJobAuditOutcome.CANCELLED
                and error_category == "interrupted"
            ) or (
                outcome is MemoryJobAuditOutcome.CANCELLED_SESSION_DELETED
                and error_category is None
            )
        if not valid:
            raise ValueError("incompatible status, outcome, and error_category")

    @staticmethod
    def _validate_identifier(identifier: str | None) -> None:
        if identifier is None:
            return
        if not isinstance(identifier, str):
            raise ValueError("invalid provider and model identifiers")
        normalized = identifier.lower()
        if (
            not 1 <= len(identifier) <= 128
            or any(character.isspace() or not character.isprintable() for character in identifier)
            or any(marker in normalized for marker in _SENSITIVE_IDENTIFIER_MARKERS)
        ):
            raise ValueError("invalid provider and model identifiers")

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")

    def _require_audit_for_job(self, job_id: str) -> MemoryJobAudit:
        row = self._connection.execute(
            "SELECT * FROM memory_job_audits WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if row is None:
            raise ValueError("terminal memory job has no audit")
        return self._audit_from_row(row)

    @staticmethod
    def _consent_from_row(row: sqlite3.Row) -> MemoryExtractionConsent:
        disclosed_fields = json.loads(str(row["disclosed_fields_json"]))
        if not isinstance(disclosed_fields, list) or not all(
            isinstance(item, str) for item in disclosed_fields
        ):
            raise ValueError("invalid persisted disclosed fields")
        return MemoryExtractionConsent(
            scope_id=str(row["scope_id"]),
            status=MemoryExtractionConsentStatus(str(row["status"])),
            purpose=row["purpose"],
            provider=row["provider"],
            disclosure_version=row["disclosure_version"],
            disclosed_fields=tuple(disclosed_fields),
            generation=int(row["generation"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    @staticmethod
    def _write_consent_from_row(row: sqlite3.Row) -> MemoryWriteConsent:
        try:
            values = json.loads(str(row["allowed_memory_types_json"]))
            if not isinstance(values, list) or not all(
                isinstance(value, str) for value in values
            ):
                raise ValueError
            memory_types = tuple(MemoryType(value) for value in values)
            granted_at = (
                datetime.fromisoformat(str(row["granted_at"]))
                if row["granted_at"] is not None
                else None
            )
            return MemoryWriteConsent(
                scope_id=str(row["scope_id"]),
                status=MemoryWriteConsentStatus(str(row["status"])),
                purpose=row["purpose"],
                policy_version=row["policy_version"],
                allowed_memory_types_version=row["allowed_memory_types_version"],
                allowed_memory_types=memory_types,
                retention_disclosure_version=row["retention_disclosure_version"],
                generation=int(row["generation"]),
                granted_at=granted_at,
                created_at=datetime.fromisoformat(str(row["created_at"])),
                updated_at=datetime.fromisoformat(str(row["updated_at"])),
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("invalid persisted memory write consent") from exc

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> MemoryJob:
        outcome = row["outcome"]
        snapshot = None
        if MemoryAutomationMode(str(row["mode"])) is MemoryAutomationMode.AUTO_ACTIVE:
            try:
                raw_type_generations = json.loads(
                    str(row["type_deletion_generations_json"])
                )
                if not isinstance(raw_type_generations, dict) or not all(
                    isinstance(key, str)
                    and type(value) is int
                    and value >= 0
                    for key, value in raw_type_generations.items()
                ):
                    raise ValueError
                snapshot = MemoryAutoActiveJobSnapshot(
                    reserved_mode=MemoryAutomationMode(str(row["reserved_mode"])),
                    workflow_version=str(row["workflow_version"]),
                    extractor_route=MemoryExtractorRoute(str(row["extractor_route"])),
                    governor_version=str(row["governor_version"]),
                    commit_policy_version=str(row["commit_policy_version"]),
                    canonicalization_version=str(row["canonicalization_version"]),
                    allowed_memory_types_version=str(row["allowed_memory_types_version"]),
                    write_consent_generation=int(row["write_consent_generation"]),
                    remote_consent_generation=(
                        int(row["remote_consent_generation"])
                        if row["remote_consent_generation"] is not None
                        else None
                    ),
                    remote_authority_fingerprint=row["remote_authority_fingerprint"],
                    global_deletion_generation=int(row["global_deletion_generation"]),
                    session_deletion_generation=int(row["session_deletion_generation"]),
                    type_deletion_generations={
                        str(key): int(value)
                        for key, value in raw_type_generations.items()
                    },
                    source_session_reference_hash=str(
                        row["source_session_reference_hash"]
                    ),
                    source_user_message_reference_hash=str(
                        row["source_user_message_reference_hash"]
                    ),
                    source_assistant_message_reference_hash=str(
                        row["source_assistant_message_reference_hash"]
                    ),
                    turn_completed_at=datetime.fromisoformat(
                        str(row["turn_completed_at"])
                    ),
                )
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError("invalid persisted auto_active job snapshot") from exc
        return MemoryJob(
            id=str(row["id"]),
            turn_id=str(row["turn_id"]),
            schema_version=str(row["schema_version"]),
            session_id=(
                str(row["session_id"]) if row["session_id"] is not None else None
            ),
            user_message_id=(
                str(row["user_message_id"])
                if row["user_message_id"] is not None
                else None
            ),
            assistant_message_id=(
                str(row["assistant_message_id"])
                if row["assistant_message_id"] is not None
                else None
            ),
            mode=MemoryAutomationMode(str(row["mode"])),
            extractor_route=MemoryExtractorRoute(str(row["extractor_route"])),
            status=MemoryJobStatus(str(row["status"])),
            attempt_count=int(row["attempt_count"]),
            outcome=MemoryJobAuditOutcome(str(outcome)) if outcome is not None else None,
            error_category=row["error_category"],
            governor_version=str(row["governor_version"]),
            consent_generation=(
                int(row["consent_generation"])
                if row["consent_generation"] is not None
                else None
            ),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            started_at=(
                datetime.fromisoformat(str(row["started_at"]))
                if row["started_at"] is not None
                else None
            ),
            finished_at=(
                datetime.fromisoformat(str(row["finished_at"]))
                if row["finished_at"] is not None
                else None
            ),
            auto_active_snapshot=snapshot,
            persona_artifact_id=(
                str(row["persona_artifact_id"])
                if "persona_artifact_id" in row.keys()
                and row["persona_artifact_id"] is not None
                else None
            ),
        )

    @staticmethod
    def _audit_from_row(row: sqlite3.Row) -> MemoryJobAudit:
        invalid_metadata = ValueError("invalid persisted memory audit metadata")
        try:
            decision_counts = MemoryAutomationRepository._parse_persisted_counts(
                row["decision_counts_json"]
            )
            reason_counts = MemoryAutomationRepository._parse_persisted_counts(
                row["reason_counts_json"]
            )
            outcome_counts = MemoryAutomationRepository._parse_persisted_counts(
                row["outcome_counts_json"]
            )
            proposal_count = MemoryAutomationRepository._persisted_nonnegative_integer(
                row["proposal_count"]
            )
            accepted_count = MemoryAutomationRepository._persisted_nonnegative_integer(
                row["accepted_count"]
            )
            rejected_count = MemoryAutomationRepository._persisted_nonnegative_integer(
                row["rejected_count"]
            )
            redaction_count = MemoryAutomationRepository._persisted_nonnegative_integer(
                row["redaction_count"]
            )
            elapsed_ms = (
                MemoryAutomationRepository._persisted_nonnegative_integer(row["elapsed_ms"])
                if row["elapsed_ms"] is not None
                else None
            )
            consent_generation = (
                MemoryAutomationRepository._persisted_nonnegative_integer(
                    row["consent_generation"]
                )
                if row["consent_generation"] is not None
                else None
            )
            if (
                proposal_count != accepted_count + rejected_count
                or sum(decision_counts.values()) != proposal_count
                or sum(reason_counts.values()) != proposal_count
                or (outcome_counts and sum(outcome_counts.values()) != proposal_count)
            ):
                raise invalid_metadata
            MemoryAutomationRepository._validate_identifier(row["provider"])
            MemoryAutomationRepository._validate_identifier(row["model"])
            outcome = MemoryJobAuditOutcome(str(row["outcome"]))
            created_at = datetime.fromisoformat(str(row["created_at"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise invalid_metadata from None

        return MemoryJobAudit(
            id=str(row["id"]),
            job_id=str(row["job_id"]),
            outcome=outcome,
            decision_counts=decision_counts,
            reason_counts=reason_counts,
            outcome_counts=outcome_counts,
            proposal_count=proposal_count,
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            redaction_count=redaction_count,
            provider=row["provider"],
            model=row["model"],
            elapsed_ms=elapsed_ms,
            schema_version=str(row["schema_version"]),
            governor_version=str(row["governor_version"]),
            consent_generation=consent_generation,
            created_at=created_at,
        )

    @staticmethod
    def _parse_persisted_counts(raw: object) -> dict[str, int]:
        value = json.loads(str(raw))
        if not isinstance(value, dict):
            raise ValueError
        parsed: dict[str, int] = {}
        for key, count in value.items():
            if (
                not isinstance(key, str)
                or _COUNT_KEY_PATTERN.fullmatch(key) is None
                or type(count) is not int
                or count < 0
            ):
                raise ValueError
            parsed[key] = count
        return parsed

    @staticmethod
    def _persisted_nonnegative_integer(value: object) -> int:
        if type(value) is not int or value < 0:
            raise ValueError
        return value
