from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from app.domain.models import MemoryConflictResolutionKind, MemoryRecordState
from app.domain.relationship import (
    RelationshipAuthorityAction,
    RelationshipAuthorityActionKind,
    RelationshipEvent,
    RelationshipEventKind,
    RelationshipEventType,
    RelationshipPayloadState,
    RelationshipReconcileJob,
    RelationshipReconcileJobStatus,
    RelationshipReconcileOutcome,
    RelationshipSourceSnapshot,
    RelationshipSubjectCode,
)
from app.services.relationship_contract import (
    RELATIONSHIP_EVENT_SCHEMA_VERSION,
    RELATIONSHIP_OBSERVED_TIME_DERIVATION_VERSION,
    RELATIONSHIP_RECONCILE_JOB_VERSION,
    RELATIONSHIP_SCOPE_ID,
    normalize_preferred_address,
    relationship_private_fingerprint,
)
from app.services.relationship_rules import RelationshipRuleResult, RelationshipRuleSet


_LINEAGE_RESOLUTION_KINDS = frozenset(
    {
        MemoryConflictResolutionKind.CHOOSE_LEFT,
        MemoryConflictResolutionKind.CHOOSE_RIGHT,
        MemoryConflictResolutionKind.REPLACE_BOTH,
        MemoryConflictResolutionKind.BOTH_CONTEXTUAL,
    }
)


class CorruptRelationshipAuthorityError(RuntimeError):
    pass


class CorruptRelationshipLineageError(RuntimeError):
    pass


class CorruptRelationshipEventError(ValueError):
    pass


class RelationshipJobIdentityMismatchError(ValueError):
    """Raised when an existing reconcile job's captured identity semantics no
    longer match the current source snapshot. This is an invariant violation
    (fail-closed) and must not be silently swallowed by callers."""


@dataclass(frozen=True)
class RelationshipAuthorityDecisionRecord:
    id: str
    predecessor_decision_id: str | None
    generation: int
    action: RelationshipAuthorityAction
    action_kind: RelationshipAuthorityActionKind
    reason_code: str
    inherited_authority_fingerprint: str | None
    created_at: datetime


@dataclass(frozen=True)
class RelationshipLineageGraph:
    parents_by_memory_id: dict[str, tuple[str, ...]]
    edges: tuple[tuple[str, str, str, str], ...]


class RelationshipLedgerRepository:
    """Transaction-bound relationship event, authority, and lineage storage."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @contextmanager
    def write_transaction(self) -> Iterator[None]:
        if self._connection.in_transaction:
            savepoint = f"relationship_ledger_{uuid.uuid4().hex}"
            self._connection.execute(f"SAVEPOINT {savepoint}")
            try:
                yield
            except BaseException:
                self._connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                self._connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            else:
                self._connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            return
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            yield
        except BaseException:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()

    def events(self) -> tuple[RelationshipEvent, ...]:
        rows = self._connection.execute(
            """
            SELECT * FROM relationship_events
            ORDER BY observed_at, source_memory_id, source_memory_version_id,
                     event_type, subject_code, id
            """
        ).fetchall()
        return tuple(self._event_from_row(row) for row in rows)

    def event(self, event_id: str) -> RelationshipEvent | None:
        if not isinstance(event_id, str) or not event_id:
            return None
        row = self._connection.execute(
            "SELECT * FROM relationship_events WHERE id = ?",
            (event_id,),
        ).fetchone()
        return None if row is None else self._event_from_row(row)

    def append_apply(
        self,
        *,
        source: RelationshipSourceSnapshot,
        mapping: RelationshipRuleResult,
        created_at: datetime,
    ) -> RelationshipEvent:
        self._require_write_transaction()
        payload = self._validated_apply_payload(source=source, mapping=mapping)
        event_type = mapping.event_type
        subject_code = mapping.subject_code
        persona_artifact_id = mapping.persona_artifact_id
        assert event_type is not None
        assert subject_code is not None
        assert persona_artifact_id is not None
        event_id = str(uuid.uuid4())
        observed_at = _utc_datetime(source.version_created_at)
        created_at = _utc_datetime(created_at)
        integrity = relationship_private_fingerprint(
            _event_integrity_document(
                event_id=event_id,
                scope_id=source.scope_id,
                event_kind=RelationshipEventKind.APPLY,
                event_type=event_type,
                subject_code=subject_code,
                payload_state=RelationshipPayloadState.ACTIVE,
                payload=payload,
                source_memory_id=source.source_memory_id,
                source_memory_version_id=source.source_memory_version_id,
                observed_at=observed_at,
                revokes_event_id=None,
                rule_version=source.relationship_rule_version,
                persona_artifact_id=persona_artifact_id,
                created_at=created_at,
            )
        )
        payload_json = _canonical_json(payload)
        self._connection.execute(
            """
            INSERT INTO relationship_events (
                id, scope_id, event_kind, event_type, subject_code,
                payload_state, payload_json, source_memory_id,
                source_memory_version_id, observed_at,
                observed_time_derivation_version, revokes_event_id,
                rule_version, persona_artifact_id, event_schema_version,
                integrity_fingerprint, created_at
            ) VALUES (?, ?, 'apply', ?, ?, 'active', ?, ?, ?, ?, ?, NULL,
                      ?, ?, ?, ?, ?)
            ON CONFLICT DO NOTHING
            """,
            (
                event_id,
                source.scope_id,
                event_type.value,
                subject_code,
                payload_json,
                source.source_memory_id,
                source.source_memory_version_id,
                observed_at.isoformat(),
                RELATIONSHIP_OBSERVED_TIME_DERIVATION_VERSION,
                source.relationship_rule_version,
                persona_artifact_id,
                RELATIONSHIP_EVENT_SCHEMA_VERSION,
                integrity,
                created_at.isoformat(),
            ),
        )
        row = self._connection.execute(
            """
            SELECT * FROM relationship_events
            WHERE scope_id = ? AND source_memory_version_id = ?
              AND rule_version = ? AND event_type = ? AND subject_code = ?
              AND event_kind = 'apply'
            """,
            (
                source.scope_id,
                source.source_memory_version_id,
                source.relationship_rule_version,
                event_type.value,
                subject_code,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("relationship apply could not be persisted")
        event = self._event_from_row(row)
        if not _same_apply_semantics(
            event=event,
            source=source,
            mapping=mapping,
            payload=payload,
        ):
            raise ValueError("existing relationship apply identity has different semantics")
        return event

    def append_revoke(
        self,
        *,
        apply_event_id: str,
        created_at: datetime,
        scope_id: str = RELATIONSHIP_SCOPE_ID,
    ) -> RelationshipEvent:
        self._require_write_transaction()
        if not isinstance(apply_event_id, str) or not apply_event_id:
            raise ValueError("relationship apply event id is required")
        target_row = self._connection.execute(
            "SELECT * FROM relationship_events WHERE id = ?",
            (apply_event_id,),
        ).fetchone()
        if target_row is None:
            raise ValueError("relationship apply event does not exist")
        target = self._event_from_row(target_row)
        if (
            target.event_kind is not RelationshipEventKind.APPLY
            or target.scope_id != scope_id
        ):
            raise ValueError("relationship revoke target is invalid")
        existing = self._connection.execute(
            "SELECT * FROM relationship_events WHERE revokes_event_id = ?",
            (apply_event_id,),
        ).fetchone()
        if existing is not None:
            revoke = self._event_from_row(existing)
            if not _same_revoke_semantics(revoke=revoke, target=target):
                raise ValueError("relationship revoke identity is corrupt")
            return revoke

        created_at = _utc_datetime(created_at)
        event_id = str(uuid.uuid4())
        integrity = relationship_private_fingerprint(
            _event_integrity_document(
                event_id=event_id,
                scope_id=target.scope_id,
                event_kind=RelationshipEventKind.REVOKE,
                event_type=target.event_type,
                subject_code=target.subject_code,
                payload_state=RelationshipPayloadState.ACTIVE,
                payload=None,
                source_memory_id=target.source_memory_id,
                source_memory_version_id=target.source_memory_version_id,
                observed_at=target.observed_at,
                revokes_event_id=target.id,
                rule_version=target.rule_version,
                persona_artifact_id=target.persona_artifact_id,
                created_at=created_at,
            )
        )
        self._connection.execute(
            """
            INSERT INTO relationship_events (
                id, scope_id, event_kind, event_type, subject_code,
                payload_state, payload_json, source_memory_id,
                source_memory_version_id, observed_at,
                observed_time_derivation_version, revokes_event_id,
                rule_version, persona_artifact_id, event_schema_version,
                integrity_fingerprint, created_at
            ) VALUES (?, ?, 'revoke', ?, ?, 'active', NULL, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?)
            ON CONFLICT DO NOTHING
            """,
            (
                event_id,
                target.scope_id,
                target.event_type.value,
                target.subject_code,
                target.source_memory_id,
                target.source_memory_version_id,
                target.observed_at.isoformat(),
                target.observed_time_derivation_version,
                target.id,
                target.rule_version,
                target.persona_artifact_id,
                target.event_schema_version,
                integrity,
                created_at.isoformat(),
            ),
        )
        row = self._connection.execute(
            "SELECT * FROM relationship_events WHERE revokes_event_id = ?",
            (apply_event_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("relationship revoke could not be persisted")
        revoke = self._event_from_row(row)
        if not _same_revoke_semantics(revoke=revoke, target=target):
            raise ValueError("relationship revoke identity is corrupt")
        return revoke

    def redact_preferred_address(
        self,
        *,
        apply_event_id: str,
        created_at: datetime,
    ) -> tuple[RelationshipEvent, RelationshipEvent]:
        self._require_write_transaction()
        row = self._connection.execute(
            "SELECT * FROM relationship_events WHERE id = ?",
            (apply_event_id,),
        ).fetchone()
        if row is None:
            raise ValueError("relationship apply event does not exist")
        event = self._event_from_row(row)
        if (
            event.event_kind is not RelationshipEventKind.APPLY
            or event.event_type is not RelationshipEventType.PREFERRED_ADDRESS
        ):
            raise ValueError("only preferred-address applies can be redacted")
        revoke = self.append_revoke(
            apply_event_id=apply_event_id,
            created_at=created_at,
            scope_id=event.scope_id,
        )
        if event.payload_state is RelationshipPayloadState.REDACTED:
            return event, revoke
        self._connection.execute(
            """
            INSERT INTO relationship_redaction_guards (event_id, created_at)
            VALUES (?, ?)
            """,
            (apply_event_id, _utc_datetime(created_at).isoformat()),
        )
        cursor = self._connection.execute(
            """
            UPDATE relationship_events
            SET payload_json = NULL, payload_state = 'redacted'
            WHERE id = ? AND event_kind = 'apply'
              AND event_type = 'preferred_address'
              AND payload_state = 'active' AND payload_json IS NOT NULL
            """,
            (apply_event_id,),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("preferred-address payload redaction failed")
        self._connection.execute(
            "DELETE FROM relationship_redaction_guards WHERE event_id = ?",
            (apply_event_id,),
        )
        redacted_row = self._connection.execute(
            "SELECT * FROM relationship_events WHERE id = ?",
            (apply_event_id,),
        ).fetchone()
        redacted_event = self._event_from_row(redacted_row)
        if not _same_redacted_apply_semantics(
            redacted=redacted_event,
            original=event,
        ):
            raise CorruptRelationshipEventError(
                "redacted relationship event semantics changed"
            )
        return redacted_event, revoke

    def _validated_apply_payload(
        self,
        *,
        source: RelationshipSourceSnapshot,
        mapping: RelationshipRuleResult,
    ) -> dict[str, object]:
        from app.repositories.relationship_sources import RelationshipSourceRepository
        from app.services.relationship_authority import RelationshipAuthorityService

        event_type = mapping.event_type
        subject_code = mapping.subject_code
        if (
            type(event_type) is not RelationshipEventType
            or not isinstance(subject_code, str)
            or event_type.value != subject_code
        ):
            raise ValueError("relationship apply semantic key is invalid")
        effective_authority = RelationshipAuthorityService(
            self._connection,
            ledger=self,
        ).effective(
            source_memory_id=source.source_memory_id,
            event_type=event_type,
            subject_code=subject_code,
        )
        current_source = RelationshipSourceRepository(self._connection).get_current(
            source.source_memory_id,
            authority=effective_authority,
            relationship_rule_version=source.relationship_rule_version,
        )
        expected_mapping = RelationshipRuleSet().map(
            source,
            persona_artifact_id=mapping.persona_artifact_id,
        )
        if (
            current_source != source
            or effective_authority.suppressed
            or not mapping.eligible
            or mapping != expected_mapping
            or source.record_state.value != "active"
            or source.open_conflict
            or source.payload_redacted
            or source.authority_suppressed
            or mapping.event_type is None
            or mapping.subject_code is None
            or mapping.persona_artifact_id is None
            or mapping.payload is None
            or source.scope_id != RELATIONSHIP_SCOPE_ID
            or source.canonical_subject_code != mapping.subject_code
            or mapping.event_type.value != mapping.subject_code
        ):
            raise ValueError("relationship apply source or mapping is invalid")
        if self._connection.execute(
            "SELECT 1 FROM persona_artifacts WHERE id = ?",
            (mapping.persona_artifact_id,),
        ).fetchone() is None:
            raise ValueError("relationship apply Persona artifact does not exist")
        payload = dict(mapping.payload)
        if mapping.event_type is RelationshipEventType.PREFERRED_ADDRESS:
            expected = {"address": normalize_preferred_address(source.preferred_address_candidate or "")}
        elif mapping.event_type is RelationshipEventType.SHARED_EXPERIENCE:
            expected = {
                "category": "shared_experience",
                "reason_code": "allowlisted_current_memory",
                "delta": 0.04,
            }
        else:
            expected = {
                "category": "non_external_commitment",
                "reason_code": "allowlisted_current_memory",
                "delta": 0.03,
            }
        if payload != expected:
            raise ValueError("relationship apply payload is not canonical")
        return payload

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> RelationshipEvent:
        try:
            event_id = _required_event_text(row["id"])
            scope_id = _required_event_text(row["scope_id"])
            event_kind = RelationshipEventKind(_required_event_text(row["event_kind"]))
            event_type = RelationshipEventType(_required_event_text(row["event_type"]))
            subject_code = _required_event_text(row["subject_code"])
            payload_state = RelationshipPayloadState(
                _required_event_text(row["payload_state"])
            )
            source_memory_id = _required_event_text(row["source_memory_id"])
            source_version_id = _required_event_text(
                row["source_memory_version_id"]
            )
            observed_at = _stored_event_datetime(row["observed_at"])
            created_at = _stored_event_datetime(row["created_at"])
            observed_version = _required_event_text(
                row["observed_time_derivation_version"]
            )
            rule_version = _required_event_text(row["rule_version"])
            persona_artifact_id = _required_event_text(row["persona_artifact_id"])
            event_schema_version = _required_event_text(row["event_schema_version"])
            fingerprint = row["integrity_fingerprint"]
            revokes_event_id = row["revokes_event_id"]
            if revokes_event_id is not None:
                revokes_event_id = _required_event_text(revokes_event_id)
        except (KeyError, TypeError, ValueError) as exc:
            raise CorruptRelationshipEventError(
                "relationship event fields are invalid"
            ) from exc

        if (
            subject_code != event_type.value
            or event_schema_version != RELATIONSHIP_EVENT_SCHEMA_VERSION
            or observed_version != RELATIONSHIP_OBSERVED_TIME_DERIVATION_VERSION
            or not _valid_fingerprint(fingerprint)
        ):
            raise CorruptRelationshipEventError(
                "relationship event contract is invalid"
            )
        payload_raw = row["payload_json"]
        payload = _validated_event_payload(
            event_kind=event_kind,
            event_type=event_type,
            payload_state=payload_state,
            payload_raw=payload_raw,
            revokes_event_id=revokes_event_id,
        )
        event = RelationshipEvent(
            id=event_id,
            scope_id=scope_id,
            event_kind=event_kind,
            event_type=event_type,
            subject_code=subject_code,  # type: ignore[arg-type]
            payload_state=payload_state,
            payload=payload,
            source_memory_id=source_memory_id,
            source_memory_version_id=source_version_id,
            observed_at=observed_at,
            observed_time_derivation_version=observed_version,
            revokes_event_id=revokes_event_id,
            rule_version=rule_version,
            persona_artifact_id=persona_artifact_id,
            event_schema_version=event_schema_version,
            integrity_fingerprint=fingerprint,
            created_at=created_at,
        )
        if payload_state is RelationshipPayloadState.ACTIVE:
            expected = relationship_private_fingerprint(
                _event_integrity_document(
                    event_id=event.id,
                    scope_id=event.scope_id,
                    event_kind=event.event_kind,
                    event_type=event.event_type,
                    subject_code=event.subject_code,
                    payload_state=event.payload_state,
                    payload=dict(event.payload) if event.payload is not None else None,
                    source_memory_id=event.source_memory_id,
                    source_memory_version_id=event.source_memory_version_id,
                    observed_at=event.observed_at,
                    revokes_event_id=event.revokes_event_id,
                    rule_version=event.rule_version,
                    persona_artifact_id=event.persona_artifact_id,
                    created_at=event.created_at,
                )
            )
            if fingerprint != expected:
                raise CorruptRelationshipEventError(
                    "relationship event integrity fingerprint is invalid"
                )
        return event

    def _require_write_transaction(self) -> None:
        if not self._connection.in_transaction:
            raise RuntimeError("relationship ledger operation requires a write transaction")

    def reserve_job(
        self,
        *,
        source: RelationshipSourceSnapshot,
        event_type: RelationshipEventType,
        subject_code: RelationshipSubjectCode,
        persona_artifact_id: str,
        created_at: datetime,
    ) -> RelationshipReconcileJob:
        if not self._connection.in_transaction:
            raise RuntimeError("relationship job reservation requires a write transaction")
        job_id = str(uuid.uuid4())
        self._connection.execute(
            """
            INSERT INTO relationship_reconcile_jobs (
                id, scope_id, source_memory_id, source_memory_version_id,
                captured_record_head_version, captured_record_generation,
                captured_record_state, captured_event_type, captured_subject_code,
                captured_authority_decision_id, captured_authority_generation,
                captured_authority_epoch, captured_inherited_authority_fingerprint,
                relationship_rule_version, persona_artifact_id, job_schema_version,
                status, outcome, attempt_count, reason_code, error_category,
                created_at, started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      'pending', NULL, 0, NULL, NULL, ?, NULL, NULL)
            ON CONFLICT DO NOTHING
            """,
            (
                job_id,
                source.scope_id,
                source.source_memory_id,
                source.source_memory_version_id,
                source.record_head_version,
                source.record_generation,
                source.record_state.value,
                event_type.value,
                subject_code,
                source.effective_authority_decision_id,
                source.effective_authority_generation,
                source.authority_epoch,
                source.inherited_authority_fingerprint,
                source.relationship_rule_version,
                persona_artifact_id,
                RELATIONSHIP_RECONCILE_JOB_VERSION,
                _utc_datetime(created_at).isoformat(),
            ),
        )
        row = self._connection.execute(
            """
            SELECT * FROM relationship_reconcile_jobs
            WHERE scope_id=? AND source_memory_version_id=?
              AND relationship_rule_version=?
              AND captured_record_head_version=?
              AND captured_record_generation=?
              AND captured_record_state=?
              AND captured_authority_generation=?
              AND captured_authority_epoch=?
              AND captured_inherited_authority_fingerprint=?
            """,
            (
                source.scope_id,
                source.source_memory_version_id,
                source.relationship_rule_version,
                source.record_head_version,
                source.record_generation,
                source.record_state.value,
                source.effective_authority_generation,
                source.authority_epoch,
                source.inherited_authority_fingerprint,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("relationship job could not be reserved")
        job = self._job_from_row(row)
        if (
            job.source_memory_id != source.source_memory_id
            or job.captured_record_head_version != source.record_head_version
            or job.captured_record_generation != source.record_generation
            or job.captured_record_state is not source.record_state
            or job.captured_event_type is not event_type
            or job.captured_subject_code != subject_code
            or job.captured_authority_decision_id
            != source.effective_authority_decision_id
            or job.persona_artifact_id != persona_artifact_id
        ):
            raise RelationshipJobIdentityMismatchError(
                "existing relationship job identity has different semantics"
            )
        return job

    def job(self, job_id: str) -> RelationshipReconcileJob | None:
        if not isinstance(job_id, str) or not job_id:
            return None
        row = self._connection.execute(
            "SELECT * FROM relationship_reconcile_jobs WHERE id=?",
            (job_id,),
        ).fetchone()
        return None if row is None else self._job_from_row(row)

    def jobs(
        self,
        *,
        statuses: tuple[RelationshipReconcileJobStatus, ...] | None = None,
    ) -> tuple[RelationshipReconcileJob, ...]:
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            rows = self._connection.execute(
                f"SELECT * FROM relationship_reconcile_jobs "
                f"WHERE status IN ({placeholders}) ORDER BY created_at, id",
                tuple(status.value for status in statuses),
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM relationship_reconcile_jobs ORDER BY created_at, id"
            ).fetchall()
        return tuple(self._job_from_row(row) for row in rows)

    def transition_job(
        self,
        *,
        job_id: str,
        expected_status: RelationshipReconcileJobStatus,
        status: RelationshipReconcileJobStatus,
        outcome: RelationshipReconcileOutcome | None,
        attempt_count: int,
        reason_code: str | None,
        error_category: str | None,
        started_at: datetime | None,
        finished_at: datetime | None,
    ) -> RelationshipReconcileJob:
        if not self._connection.in_transaction:
            raise RuntimeError("relationship job transition requires a write transaction")
        if type(attempt_count) is not int or attempt_count < 0:
            raise ValueError("relationship job attempt count is invalid")
        cursor = self._connection.execute(
            """
            UPDATE relationship_reconcile_jobs
            SET status=?, outcome=?, attempt_count=?, reason_code=?,
                error_category=?, started_at=?, finished_at=?
            WHERE id=? AND status=?
            """,
            (
                status.value,
                outcome.value if outcome is not None else None,
                attempt_count,
                reason_code,
                error_category,
                _utc_datetime(started_at).isoformat() if started_at else None,
                _utc_datetime(finished_at).isoformat() if finished_at else None,
                job_id,
                expected_status.value,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("relationship job transition is stale")
        job = self.job(job_id)
        if job is None:
            raise RuntimeError("relationship job disappeared")
        return job

    def append_job_audit(
        self,
        *,
        job: RelationshipReconcileJob,
        outcome: RelationshipReconcileOutcome,
        reason_code: str,
        created_at: datetime,
    ) -> None:
        if not self._connection.in_transaction:
            raise RuntimeError("relationship job audit requires a write transaction")
        self._connection.execute(
            """
            INSERT INTO relationship_job_audits (
                id, job_id, outcome, reason_code, attempt_count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                job.id,
                outcome.value,
                reason_code,
                job.attempt_count,
                _utc_datetime(created_at).isoformat(),
            ),
        )

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> RelationshipReconcileJob:
        try:
            job_id = _required_event_text(row["id"])
            scope_id = _required_event_text(row["scope_id"])
            memory_id = _required_event_text(row["source_memory_id"])
            version_id = _required_event_text(row["source_memory_version_id"])
            head = row["captured_record_head_version"]
            generation = row["captured_record_generation"]
            authority_generation = row["captured_authority_generation"]
            authority_epoch = row["captured_authority_epoch"]
            attempt_count = row["attempt_count"]
            if any(
                type(value) is not int or value < minimum
                for value, minimum in (
                    (head, 1),
                    (generation, 0),
                    (authority_generation, 0),
                    (authority_epoch, 0),
                    (attempt_count, 0),
                )
            ):
                raise ValueError
            record_state = MemoryRecordState(
                _required_event_text(row["captured_record_state"])
            )
            event_type = RelationshipEventType(
                _required_event_text(row["captured_event_type"])
            )
            subject_code = _required_event_text(row["captured_subject_code"])
            if event_type.value != subject_code:
                raise ValueError
            decision_id = row["captured_authority_decision_id"]
            if decision_id is not None:
                decision_id = _required_event_text(decision_id)
            if (authority_generation == 0) != (decision_id is None):
                raise ValueError
            if scope_id != RELATIONSHIP_SCOPE_ID:
                raise ValueError
            fingerprint = _required_event_text(
                row["captured_inherited_authority_fingerprint"]
            )
            if not _valid_fingerprint(fingerprint):
                raise ValueError
            status = RelationshipReconcileJobStatus(
                _required_event_text(row["status"])
            )
            outcome_raw = row["outcome"]
            outcome = (
                RelationshipReconcileOutcome(_required_event_text(outcome_raw))
                if outcome_raw is not None
                else None
            )
            reason = row["reason_code"]
            if reason is not None:
                reason = _required_event_text(reason)
            error = row["error_category"]
            if error is not None:
                error = _required_event_text(error)
            created_at = _stored_event_datetime(row["created_at"])
            started_at = (
                _stored_event_datetime(row["started_at"])
                if row["started_at"] is not None
                else None
            )
            finished_at = (
                _stored_event_datetime(row["finished_at"])
                if row["finished_at"] is not None
                else None
            )
            if (
                (status in {RelationshipReconcileJobStatus.PENDING, RelationshipReconcileJobStatus.RUNNING} and outcome is not None)
                or (status not in {RelationshipReconcileJobStatus.PENDING, RelationshipReconcileJobStatus.RUNNING} and outcome is None)
                or (status is RelationshipReconcileJobStatus.PENDING and (started_at is not None or finished_at is not None))
                or (status is RelationshipReconcileJobStatus.RUNNING and (started_at is None or finished_at is not None))
                or (status not in {RelationshipReconcileJobStatus.PENDING, RelationshipReconcileJobStatus.RUNNING} and finished_at is None)
            ):
                raise ValueError
            relationship_rule_version = _required_event_text(
                row["relationship_rule_version"]
            )
            persona_artifact_id = _required_event_text(row["persona_artifact_id"])
            job_schema_version = _required_event_text(row["job_schema_version"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("relationship reconcile job row is invalid") from exc
        return RelationshipReconcileJob(
            id=job_id,
            scope_id=scope_id,
            source_memory_id=memory_id,
            source_memory_version_id=version_id,
            status=status,
            outcome=outcome,
            captured_record_head_version=head,
            captured_record_generation=generation,
            captured_record_state=record_state,
            captured_event_type=event_type,
            captured_subject_code=subject_code,  # type: ignore[arg-type]
            captured_authority_decision_id=decision_id,
            captured_authority_generation=authority_generation,
            captured_authority_epoch=authority_epoch,
            captured_inherited_authority_fingerprint=fingerprint,
            relationship_rule_version=relationship_rule_version,
            persona_artifact_id=persona_artifact_id,
            job_schema_version=job_schema_version,
            attempt_count=attempt_count,
            reason_code=reason,
            error_category=error,
            created_at=created_at,
            started_at=started_at,
            finished_at=finished_at,
        )

    def authority_epoch(self, *, scope_id: str = RELATIONSHIP_SCOPE_ID) -> int:
        row = self._connection.execute(
            "SELECT generation FROM relationship_authority_epoch WHERE scope_id = ?",
            (scope_id,),
        ).fetchone()
        if row is None or type(row["generation"]) is not int or row["generation"] < 0:
            raise CorruptRelationshipAuthorityError("authority epoch is invalid")
        return row["generation"]

    def decisions_for_key(
        self,
        *,
        source_memory_id: str,
        event_type: RelationshipEventType,
        subject_code: RelationshipSubjectCode,
        scope_id: str = RELATIONSHIP_SCOPE_ID,
    ) -> tuple[RelationshipAuthorityDecisionRecord, ...]:
        rows = self._connection.execute(
            """
            SELECT id, predecessor_decision_id, generation, action, action_kind,
                   reason_code, inherited_authority_fingerprint, created_at
            FROM relationship_authority_decisions
            WHERE scope_id = ? AND source_memory_id = ?
              AND event_type = ? AND subject_code = ?
            ORDER BY generation ASC, id ASC
            """,
            (scope_id, source_memory_id, event_type.value, subject_code),
        ).fetchall()
        decisions = tuple(self._decision_from_row(row) for row in rows)
        previous: RelationshipAuthorityDecisionRecord | None = None
        for expected_generation, decision in enumerate(decisions, start=1):
            if decision.generation != expected_generation:
                raise CorruptRelationshipAuthorityError(
                    "authority decision generations are not contiguous"
                )
            if expected_generation == 1:
                if decision.predecessor_decision_id is not None:
                    raise CorruptRelationshipAuthorityError(
                        "first authority decision has a predecessor"
                    )
            elif (
                previous is None
                or decision.predecessor_decision_id != previous.id
            ):
                raise CorruptRelationshipAuthorityError(
                    "authority decision predecessor chain is invalid"
                )
            previous = decision
        return decisions

    def append_decision(
        self,
        *,
        source_memory_id: str,
        event_type: RelationshipEventType,
        subject_code: RelationshipSubjectCode,
        action: RelationshipAuthorityAction,
        action_kind: RelationshipAuthorityActionKind,
        reason_code: str,
        predecessor_decision_id: str | None,
        generation: int,
        inherited_authority_fingerprint: str | None,
        created_at: datetime,
        scope_id: str = RELATIONSHIP_SCOPE_ID,
    ) -> str:
        if not self._connection.in_transaction:
            raise RuntimeError("authority append requires a write transaction")
        decision_id = str(uuid.uuid4())
        self._connection.execute(
            """
            INSERT INTO relationship_authority_decisions (
                id, scope_id, source_memory_id, event_type, subject_code,
                predecessor_decision_id, generation, action, action_kind,
                reason_code, inherited_authority_fingerprint, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision_id,
                scope_id,
                source_memory_id,
                event_type.value,
                subject_code,
                predecessor_decision_id,
                generation,
                action.value,
                action_kind.value,
                reason_code,
                inherited_authority_fingerprint,
                created_at.astimezone(UTC).isoformat(),
            ),
        )
        return decision_id

    def append_conflict_lineage(
        self,
        *,
        resolved_memory_id: str,
        contributing_memory_ids: tuple[str, ...],
        conflict_id: str,
        resolution_kind: MemoryConflictResolutionKind,
    ) -> int:
        if resolution_kind not in _LINEAGE_RESOLUTION_KINDS:
            raise ValueError("resolution kind does not create relationship lineage")
        contributors = tuple(sorted(set(contributing_memory_ids)))
        if len(contributors) != 2 or resolved_memory_id in contributors:
            raise ValueError("relationship lineage requires both distinct conflict sides")
        with self.write_transaction():
            row = self._connection.execute(
                """
                SELECT left_memory_id, right_memory_id, status, resolution_kind,
                       resolved_memory_id
                FROM memory_conflicts
                WHERE conflict_id = ?
                """,
                (conflict_id,),
            ).fetchone()
            if (
                row is None
                or row["status"] != "resolved"
                or row["resolution_kind"] != resolution_kind.value
                or row["resolved_memory_id"] != resolved_memory_id
                or contributors
                != tuple(sorted((row["left_memory_id"], row["right_memory_id"])))
            ):
                raise ValueError("conflict lineage does not match resolved conflict")
            existing = self._connection.execute(
                """
                SELECT contributing_memory_id, conflict_id, resolution_kind
                FROM relationship_memory_lineage
                WHERE resolved_memory_id = ?
                ORDER BY contributing_memory_id
                """,
                (resolved_memory_id,),
            ).fetchall()
            if existing:
                raise ValueError("relationship lineage already exists")
            if self._would_create_cycle(resolved_memory_id, contributors):
                raise ValueError("relationship lineage would create a cycle")
            now = datetime.now(UTC).isoformat()
            for contributor in contributors:
                self._connection.execute(
                    """
                    INSERT INTO relationship_memory_lineage (
                        resolved_memory_id, contributing_memory_id, conflict_id,
                        resolution_kind, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        resolved_memory_id,
                        contributor,
                        conflict_id,
                        resolution_kind.value,
                        now,
                    ),
                )
            return self.authority_epoch()

    def lineage_closure(self, source_memory_id: str) -> tuple[str, ...]:
        graph = self.lineage_graph(source_memory_id)
        closure: set[str] = set()
        visited: set[str] = set()

        def visit(memory_id: str, visiting: set[str]) -> None:
            if memory_id in visiting:
                raise CorruptRelationshipLineageError("relationship lineage contains a cycle")
            if memory_id in visited:
                return
            visiting.add(memory_id)
            for parent in graph.parents_by_memory_id.get(memory_id, ()):
                closure.add(parent)
                visit(parent, visiting)
            visiting.remove(memory_id)
            visited.add(memory_id)

        visit(source_memory_id, set())
        closure.discard(source_memory_id)
        return tuple(sorted(closure))

    def lineage_graph(self, source_memory_id: str) -> RelationshipLineageGraph:
        rows = self._connection.execute(
            """
            SELECT resolved_memory_id, contributing_memory_id, conflict_id,
                   resolution_kind
            FROM relationship_memory_lineage
            ORDER BY resolved_memory_id, contributing_memory_id
            """
        ).fetchall()
        groups: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            resolved_id = self._required_text(row["resolved_memory_id"])
            groups.setdefault(resolved_id, []).append(row)

        relevant: set[str] = set()
        stack = [source_memory_id]
        while stack:
            current = stack.pop()
            if current in relevant:
                continue
            relevant.add(current)
            for row in groups.get(current, []):
                stack.append(self._required_text(row["contributing_memory_id"]))

        parents: dict[str, tuple[str, ...]] = {}
        edges: list[tuple[str, str, str, str]] = []
        for resolved_id in sorted(relevant):
            group = groups.get(resolved_id, [])
            if not group:
                continue
            if len(group) != 2:
                raise CorruptRelationshipLineageError(
                    "resolved relationship lineage is incomplete"
                )
            conflict_ids = {self._required_text(row["conflict_id"]) for row in group}
            kinds = {self._required_text(row["resolution_kind"]) for row in group}
            contributors = tuple(
                sorted(self._required_text(row["contributing_memory_id"]) for row in group)
            )
            if (
                len(conflict_ids) != 1
                or len(kinds) != 1
                or resolved_id in contributors
                or contributors[0] == contributors[1]
            ):
                raise CorruptRelationshipLineageError(
                    "resolved relationship lineage metadata is invalid"
                )
            conflict_id = next(iter(conflict_ids))
            kind = next(iter(kinds))
            conflict = self._connection.execute(
                """
                SELECT left_memory_id, right_memory_id, status, resolution_kind,
                       resolved_memory_id
                FROM memory_conflicts WHERE conflict_id = ?
                """,
                (conflict_id,),
            ).fetchone()
            if (
                conflict is None
                or conflict["status"] != "resolved"
                or conflict["resolution_kind"] != kind
                or conflict["resolved_memory_id"] != resolved_id
                or contributors
                != tuple(sorted((conflict["left_memory_id"], conflict["right_memory_id"])))
            ):
                raise CorruptRelationshipLineageError(
                    "relationship lineage does not match its conflict"
                )
            parents[resolved_id] = contributors
            edges.extend(
                (resolved_id, contributor, conflict_id, kind)
                for contributor in contributors
            )
        return RelationshipLineageGraph(
            parents_by_memory_id=parents,
            edges=tuple(sorted(edges)),
        )

    def _would_create_cycle(
        self,
        resolved_memory_id: str,
        contributors: tuple[str, ...],
    ) -> bool:
        rows = self._connection.execute(
            """
            SELECT resolved_memory_id, contributing_memory_id
            FROM relationship_memory_lineage
            """
        ).fetchall()
        parents: dict[str, set[str]] = {}
        for row in rows:
            parents.setdefault(str(row["resolved_memory_id"]), set()).add(
                str(row["contributing_memory_id"])
            )

        def reaches(start: str, target: str, seen: set[str]) -> bool:
            if start == target:
                return True
            if start in seen:
                return False
            seen.add(start)
            return any(reaches(parent, target, seen) for parent in parents.get(start, set()))

        return any(
            reaches(contributor, resolved_memory_id, set())
            for contributor in contributors
        )

    @staticmethod
    def _decision_from_row(row: sqlite3.Row) -> RelationshipAuthorityDecisionRecord:
        decision_id = RelationshipLedgerRepository._required_text(row["id"])
        predecessor = row["predecessor_decision_id"]
        if predecessor is not None:
            predecessor = RelationshipLedgerRepository._required_text(predecessor)
        generation = row["generation"]
        if type(generation) is not int or generation < 1:
            raise CorruptRelationshipAuthorityError("authority generation is invalid")
        try:
            action = RelationshipAuthorityAction(row["action"])
            action_kind = RelationshipAuthorityActionKind(row["action_kind"])
        except (TypeError, ValueError) as exc:
            raise CorruptRelationshipAuthorityError("authority action is invalid") from exc
        fingerprint = row["inherited_authority_fingerprint"]
        if action is RelationshipAuthorityAction.REENABLE:
            if (
                action_kind is not RelationshipAuthorityActionKind.USER_REENABLE
                or not _valid_fingerprint(fingerprint)
            ):
                raise CorruptRelationshipAuthorityError("reenable authority row is invalid")
        elif (
            action_kind is RelationshipAuthorityActionKind.USER_REENABLE
            or fingerprint is not None
        ):
            raise CorruptRelationshipAuthorityError("suppress authority row is invalid")
        try:
            created_at = datetime.fromisoformat(
                RelationshipLedgerRepository._required_text(row["created_at"])
            )
        except ValueError as exc:
            raise CorruptRelationshipAuthorityError("authority timestamp is invalid") from exc
        if created_at.tzinfo is None:
            raise CorruptRelationshipAuthorityError("authority timestamp lacks timezone")
        return RelationshipAuthorityDecisionRecord(
            id=decision_id,
            predecessor_decision_id=predecessor,
            generation=generation,
            action=action,
            action_kind=action_kind,
            reason_code=RelationshipLedgerRepository._required_text(row["reason_code"]),
            inherited_authority_fingerprint=fingerprint,
            created_at=created_at.astimezone(UTC),
        )

    @staticmethod
    def _required_text(value: object) -> str:
        if not isinstance(value, str) or not value:
            raise CorruptRelationshipLineageError("relationship metadata text is invalid")
        return value


def _canonical_json(document: object) -> str:
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _required_event_text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise CorruptRelationshipEventError(
            "relationship event text field is invalid"
        )
    return value


def _stored_event_datetime(value: object) -> datetime:
    text = _required_event_text(value)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CorruptRelationshipEventError(
            "relationship event timestamp is invalid"
        ) from exc
    if parsed.tzinfo is None or parsed.isoformat() != text:
        raise CorruptRelationshipEventError(
            "relationship event timestamp is not canonical"
        )
    return parsed.astimezone(UTC)


def _validated_event_payload(
    *,
    event_kind: RelationshipEventKind,
    event_type: RelationshipEventType,
    payload_state: RelationshipPayloadState,
    payload_raw: object,
    revokes_event_id: str | None,
) -> dict[str, object] | None:
    if event_kind is RelationshipEventKind.REVOKE:
        if (
            payload_state is not RelationshipPayloadState.ACTIVE
            or payload_raw is not None
            or revokes_event_id is None
        ):
            raise CorruptRelationshipEventError(
                "relationship revoke payload contract is invalid"
            )
        return None
    if revokes_event_id is not None:
        raise CorruptRelationshipEventError(
            "relationship apply revoke target is invalid"
        )
    if payload_state is RelationshipPayloadState.REDACTED:
        if event_type is not RelationshipEventType.PREFERRED_ADDRESS or payload_raw is not None:
            raise CorruptRelationshipEventError(
                "relationship redacted payload contract is invalid"
            )
        return None
    if not isinstance(payload_raw, str):
        raise CorruptRelationshipEventError(
            "relationship apply payload is invalid"
        )
    try:
        payload = json.loads(payload_raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise CorruptRelationshipEventError(
            "relationship apply payload JSON is invalid"
        ) from exc
    if type(payload) is not dict or _canonical_json(payload) != payload_raw:
        raise CorruptRelationshipEventError(
            "relationship apply payload JSON is not canonical"
        )
    if event_type is RelationshipEventType.PREFERRED_ADDRESS:
        address = payload.get("address")
        try:
            valid = (
                set(payload) == {"address"}
                and isinstance(address, str)
                and normalize_preferred_address(address) == address
            )
        except ValueError:
            valid = False
    elif event_type is RelationshipEventType.SHARED_EXPERIENCE:
        valid = payload == {
            "category": "shared_experience",
            "reason_code": "allowlisted_current_memory",
            "delta": 0.04,
        }
    else:
        valid = payload == {
            "category": "non_external_commitment",
            "reason_code": "allowlisted_current_memory",
            "delta": 0.03,
        }
    if not valid:
        raise CorruptRelationshipEventError(
            "relationship apply payload schema is invalid"
        )
    return payload


def _utc_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("relationship event timestamp must include timezone")
    return value.astimezone(UTC)


def _event_integrity_document(
    *,
    event_id: str,
    scope_id: str,
    event_kind: RelationshipEventKind,
    event_type: RelationshipEventType,
    subject_code: RelationshipSubjectCode,
    payload_state: RelationshipPayloadState,
    payload: dict[str, object] | None,
    source_memory_id: str,
    source_memory_version_id: str,
    observed_at: datetime,
    revokes_event_id: str | None,
    rule_version: str,
    persona_artifact_id: str,
    created_at: datetime,
) -> dict[str, object]:
    return {
        "event_schema_version": RELATIONSHIP_EVENT_SCHEMA_VERSION,
        "id": event_id,
        "scope_id": scope_id,
        "event_kind": event_kind.value,
        "event_type": event_type.value,
        "subject_code": subject_code,
        "payload_state": payload_state.value,
        "payload": payload,
        "source_memory_id": source_memory_id,
        "source_memory_version_id": source_memory_version_id,
        "observed_at": observed_at.isoformat(),
        "observed_time_derivation_version": (
            RELATIONSHIP_OBSERVED_TIME_DERIVATION_VERSION
        ),
        "revokes_event_id": revokes_event_id,
        "rule_version": rule_version,
        "persona_artifact_id": persona_artifact_id,
        "created_at": created_at.isoformat(),
    }


def _same_apply_semantics(
    *,
    event: RelationshipEvent,
    source: RelationshipSourceSnapshot,
    mapping: RelationshipRuleResult,
    payload: dict[str, object],
) -> bool:
    return (
        event.event_kind is RelationshipEventKind.APPLY
        and event.scope_id == source.scope_id
        and event.event_type is mapping.event_type
        and event.subject_code == mapping.subject_code
        and event.payload_state is RelationshipPayloadState.ACTIVE
        and event.payload == payload
        and event.source_memory_id == source.source_memory_id
        and event.source_memory_version_id == source.source_memory_version_id
        and event.observed_at == _utc_datetime(source.version_created_at)
        and event.observed_time_derivation_version
        == RELATIONSHIP_OBSERVED_TIME_DERIVATION_VERSION
        and event.revokes_event_id is None
        and event.rule_version == source.relationship_rule_version
        and event.persona_artifact_id == mapping.persona_artifact_id
        and event.event_schema_version == RELATIONSHIP_EVENT_SCHEMA_VERSION
    )


def _same_redacted_apply_semantics(
    *,
    redacted: RelationshipEvent,
    original: RelationshipEvent,
) -> bool:
    return (
        redacted.id == original.id
        and redacted.scope_id == original.scope_id
        and redacted.event_kind is RelationshipEventKind.APPLY
        and redacted.event_type is RelationshipEventType.PREFERRED_ADDRESS
        and redacted.subject_code == original.subject_code
        and redacted.payload_state is RelationshipPayloadState.REDACTED
        and redacted.payload is None
        and redacted.source_memory_id == original.source_memory_id
        and redacted.source_memory_version_id == original.source_memory_version_id
        and redacted.observed_at == original.observed_at
        and redacted.observed_time_derivation_version
        == original.observed_time_derivation_version
        and redacted.revokes_event_id is None
        and redacted.rule_version == original.rule_version
        and redacted.persona_artifact_id == original.persona_artifact_id
        and redacted.event_schema_version == original.event_schema_version
        and redacted.integrity_fingerprint == original.integrity_fingerprint
        and redacted.created_at == original.created_at
    )


def _same_revoke_semantics(
    *,
    revoke: RelationshipEvent,
    target: RelationshipEvent,
) -> bool:
    return (
        revoke.event_kind is RelationshipEventKind.REVOKE
        and revoke.scope_id == target.scope_id
        and revoke.event_type is target.event_type
        and revoke.subject_code == target.subject_code
        and revoke.payload_state is RelationshipPayloadState.ACTIVE
        and revoke.payload is None
        and revoke.source_memory_id == target.source_memory_id
        and revoke.source_memory_version_id == target.source_memory_version_id
        and revoke.observed_at == target.observed_at
        and revoke.observed_time_derivation_version
        == target.observed_time_derivation_version
        and revoke.revokes_event_id == target.id
        and revoke.rule_version == target.rule_version
        and revoke.persona_artifact_id == target.persona_artifact_id
        and revoke.event_schema_version == target.event_schema_version
    )


def _valid_fingerprint(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
