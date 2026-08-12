from __future__ import annotations

import sqlite3
from datetime import datetime

from app.domain.relationship import (
    RelationshipEventKind,
    RelationshipReconcileJob,
    RelationshipReconcileJobStatus,
    RelationshipReconcileOutcome,
)
from app.repositories.relationship_ledger import RelationshipLedgerRepository
from app.repositories.relationship_sources import RelationshipSourceRepository
from app.services.relationship_authority import RelationshipAuthorityService
from app.services.relationship_contract import (
    RELATIONSHIP_RECONCILE_JOB_VERSION,
    RELATIONSHIP_RULE_VERSION,
)
from app.services.relationship_projector import RelationshipProjector
from app.services.relationship_rules import RelationshipRuleSet


class RelationshipReconciler:
    """Runs transactionally revalidated local relationship reconciliation jobs."""

    def __init__(self, connection: sqlite3.Connection, *, max_attempts: int = 3) -> None:
        if type(max_attempts) is not int or max_attempts < 1:
            raise ValueError("relationship max attempts must be positive")
        self._connection = connection
        self._ledger = RelationshipLedgerRepository(connection)
        self._sources = RelationshipSourceRepository(connection)
        self._authority = RelationshipAuthorityService(
            connection,
            ledger=self._ledger,
        )
        self._projector = RelationshipProjector(connection)
        self.max_attempts = max_attempts

    def reserve(
        self,
        *,
        memory_id: str,
        persona_artifact_id: str,
        created_at: datetime,
    ) -> RelationshipReconcileJob:
        identity = self._current_identity(memory_id)
        if identity is None:
            raise ValueError("relationship source cannot be reserved")
        authority, source = identity
        if source.canonical_subject_code is None:
            raise ValueError("relationship source is not classified")
        with self._ledger.write_transaction():
            return self._ledger.reserve_job(
                source=source,
                event_type=authority.event_type,
                subject_code=authority.subject_code,
                persona_artifact_id=persona_artifact_id,
                created_at=created_at,
            )

    def job(self, job_id: str) -> RelationshipReconcileJob | None:
        return self._ledger.job(job_id)

    def pending_jobs(self) -> tuple[RelationshipReconcileJob, ...]:
        return self._ledger.jobs(statuses=(RelationshipReconcileJobStatus.PENDING,))

    def classified_current_memory_ids(self) -> tuple[str, ...]:
        rows = self._connection.execute(
            """
            SELECT state.memory_id
            FROM memory_record_states AS state
            JOIN memory_versions AS version
              ON version.id=state.current_version_id
             AND version.memory_id=state.memory_id
             AND version.version_number=state.head_version
            WHERE version.canonical_subject_code IS NOT NULL
            ORDER BY state.memory_id
            """
        ).fetchall()
        return tuple(row["memory_id"] for row in rows)

    def recoverable_jobs(self) -> tuple[RelationshipReconcileJob, ...]:
        return self._ledger.jobs(
            statuses=(
                RelationshipReconcileJobStatus.PENDING,
                RelationshipReconcileJobStatus.RUNNING,
                RelationshipReconcileJobStatus.FAILED,
            )
        )

    def run(
        self,
        job_id: str,
        *,
        now: datetime,
        fault_point: str | None = None,
    ) -> RelationshipReconcileJob:
        existing = self._ledger.job(job_id)
        if existing is None:
            raise ValueError("relationship reconcile job does not exist")
        if existing.status in {
            RelationshipReconcileJobStatus.SUCCEEDED,
            RelationshipReconcileJobStatus.SKIPPED,
            RelationshipReconcileJobStatus.CANCELLED,
            RelationshipReconcileJobStatus.FAILED,
        }:
            return existing
        if existing.status is not RelationshipReconcileJobStatus.PENDING:
            raise ValueError("relationship reconcile job is not pending")
        with self._ledger.write_transaction():
            job = self._ledger.job(job_id)
            assert job is not None
            if job.status is not RelationshipReconcileJobStatus.PENDING:
                return job
            job = self._ledger.transition_job(
                job_id=job.id,
                expected_status=RelationshipReconcileJobStatus.PENDING,
                status=RelationshipReconcileJobStatus.RUNNING,
                outcome=None,
                attempt_count=job.attempt_count + 1,
                reason_code=None,
                error_category=None,
                started_at=now,
                finished_at=None,
            )
            current = self._current_identity(job.source_memory_id)
            if current is None:
                return self._terminalize(
                    job=job,
                    status=RelationshipReconcileJobStatus.SKIPPED,
                    outcome=RelationshipReconcileOutcome.STALE_SOURCE,
                    reason_code="source_not_current",
                    now=now,
                    expected_status=RelationshipReconcileJobStatus.RUNNING,
                )
            authority, source = current
            if not self._authority_matches_job(authority, job):
                return self._terminalize(
                    job=job,
                    status=RelationshipReconcileJobStatus.SKIPPED,
                    outcome=RelationshipReconcileOutcome.STALE_AUTHORITY,
                    reason_code="authority_changed",
                    now=now,
                    expected_status=RelationshipReconcileJobStatus.RUNNING,
                )
            if not self._source_matches_job(source, job):
                return self._terminalize(
                    job=job,
                    status=RelationshipReconcileJobStatus.SKIPPED,
                    outcome=RelationshipReconcileOutcome.STALE_SOURCE,
                    reason_code="source_changed",
                    now=now,
                    expected_status=RelationshipReconcileJobStatus.RUNNING,
                )
            mapping = RelationshipRuleSet().map(
                source,
                persona_artifact_id=job.persona_artifact_id,
            )
            events = self._ledger.events()
            revoked_ids = {
                event.revokes_event_id
                for event in events
                if event.event_kind is RelationshipEventKind.REVOKE
            }
            if not mapping.eligible:
                revoked_any = self._revoke_effective_applies(
                    events=events,
                    revoked_ids=revoked_ids,
                    source_memory_id=source.source_memory_id,
                    now=now,
                )
                if revoked_any:
                    self._projector.project(
                        persona_artifact_id=job.persona_artifact_id,
                        computed_at=now,
                    )
                    return self._terminalize(
                        job=job,
                        status=RelationshipReconcileJobStatus.SUCCEEDED,
                        outcome=RelationshipReconcileOutcome.REVOKED,
                        reason_code=mapping.reason_code,
                        now=now,
                        expected_status=RelationshipReconcileJobStatus.RUNNING,
                    )
                outcome = (
                    RelationshipReconcileOutcome.SKIPPED_SUPPRESSED
                    if source.authority_suppressed
                    else RelationshipReconcileOutcome.SKIPPED_INELIGIBLE
                )
                return self._terminalize(
                    job=job,
                    status=RelationshipReconcileJobStatus.SKIPPED,
                    outcome=outcome,
                    reason_code=mapping.reason_code,
                    now=now,
                    expected_status=RelationshipReconcileJobStatus.RUNNING,
                )
            revoked_any = False
            for event in events:
                if (
                    event.event_kind is RelationshipEventKind.APPLY
                    and event.source_memory_id == source.source_memory_id
                    and event.source_memory_version_id
                    != source.source_memory_version_id
                    and event.id not in revoked_ids
                ):
                    self._ledger.append_revoke(
                        apply_event_id=event.id,
                        created_at=now,
                        scope_id=event.scope_id,
                    )
                    revoked_any = True
            before_ids = {event.id for event in self._ledger.events()}
            applied = self._ledger.append_apply(
                source=source,
                mapping=mapping,
                created_at=now,
            )
            inserted = applied.id not in before_ids
            if fault_point == "after_event":
                raise RuntimeError("fault_after_event")
            projection = self._projector.project(
                persona_artifact_id=job.persona_artifact_id,
                computed_at=now,
            )
            if fault_point == "after_projection":
                raise RuntimeError("fault_after_projection")
            outcome = (
                RelationshipReconcileOutcome.APPLIED
                if inserted
                else RelationshipReconcileOutcome.REVOKED
                if revoked_any
                else RelationshipReconcileOutcome.NO_CHANGE
            )
            reason = (
                "eligible_apply"
                if inserted
                else "stale_apply_revoked"
                if revoked_any
                else "already_converged"
            )
            completed = self._ledger.transition_job(
                job_id=job.id,
                expected_status=RelationshipReconcileJobStatus.RUNNING,
                status=RelationshipReconcileJobStatus.SUCCEEDED,
                outcome=outcome,
                attempt_count=job.attempt_count,
                reason_code=reason,
                error_category=None,
                started_at=now,
                finished_at=now,
            )
            self._ledger.append_job_audit(
                job=completed,
                outcome=outcome,
                reason_code=reason,
                created_at=now,
            )
            if fault_point == "after_audit":
                raise RuntimeError("fault_after_audit")
            return completed

    def terminalize_recovery(
        self,
        *,
        job: RelationshipReconcileJob,
        outcome: RelationshipReconcileOutcome,
        reason_code: str,
        now: datetime,
        status: RelationshipReconcileJobStatus = RelationshipReconcileJobStatus.SKIPPED,
    ) -> RelationshipReconcileJob:
        with self._ledger.write_transaction():
            current = self._ledger.job(job.id)
            if current is None:
                raise ValueError("relationship recovery job does not exist")
            return self._terminalize(
                job=current,
                status=status,
                outcome=outcome,
                reason_code=reason_code,
                now=now,
                expected_status=current.status,
            )

    def _terminalize(
        self,
        *,
        job: RelationshipReconcileJob,
        status: RelationshipReconcileJobStatus,
        outcome: RelationshipReconcileOutcome,
        reason_code: str,
        now: datetime,
        expected_status: RelationshipReconcileJobStatus = RelationshipReconcileJobStatus.PENDING,
    ) -> RelationshipReconcileJob:
        completed = self._ledger.transition_job(
            job_id=job.id,
            expected_status=expected_status,
            status=status,
            outcome=outcome,
            attempt_count=job.attempt_count,
            reason_code=reason_code,
            error_category=None,
            started_at=job.started_at,
            finished_at=now,
        )
        self._ledger.append_job_audit(
            job=completed,
            outcome=outcome,
            reason_code=reason_code,
            created_at=now,
        )
        return completed

    def _revoke_effective_applies(
        self,
        *,
        events,
        revoked_ids: set[str | None],
        source_memory_id: str,
        now: datetime,
    ) -> bool:
        revoked_any = False
        for event in events:
            if (
                event.event_kind is RelationshipEventKind.APPLY
                and event.source_memory_id == source_memory_id
                and event.id not in revoked_ids
            ):
                self._ledger.append_revoke(
                    apply_event_id=event.id,
                    created_at=now,
                    scope_id=event.scope_id,
                )
                revoked_any = True
        return revoked_any

    def _current_identity(self, memory_id: str):
        row = self._connection.execute(
            "SELECT canonical_subject_code FROM memory_versions AS version "
            "JOIN memory_record_states AS state ON state.current_version_id=version.id "
            "WHERE state.memory_id=?",
            (memory_id,),
        ).fetchone()
        if row is None or row["canonical_subject_code"] is None:
            return None
        try:
            from app.domain.relationship import RelationshipEventType

            event_type = RelationshipEventType(row["canonical_subject_code"])
        except (TypeError, ValueError):
            return None
        authority = self._authority.effective(
            source_memory_id=memory_id,
            event_type=event_type,
            subject_code=event_type.value,  # type: ignore[arg-type]
        )
        source = self._sources.get_current(
            memory_id,
            authority=authority,
            relationship_rule_version=RELATIONSHIP_RULE_VERSION,
        )
        return None if source is None else (authority, source)

    @staticmethod
    def _authority_matches_job(authority, job: RelationshipReconcileJob) -> bool:
        return (
            authority.event_type is job.captured_event_type
            and authority.subject_code == job.captured_subject_code
            and authority.decision_id == job.captured_authority_decision_id
            and authority.generation == job.captured_authority_generation
            and authority.authority_epoch == job.captured_authority_epoch
            and authority.inherited_authority_fingerprint
            == job.captured_inherited_authority_fingerprint
        )

    @staticmethod
    def _source_matches_job(source, job: RelationshipReconcileJob) -> bool:
        return (
            source.source_memory_version_id == job.source_memory_version_id
            and source.record_head_version == job.captured_record_head_version
            and source.record_generation == job.captured_record_generation
            and source.record_state is job.captured_record_state
            and source.relationship_rule_version == job.relationship_rule_version
            and source.canonical_subject_code == job.captured_subject_code
        )
