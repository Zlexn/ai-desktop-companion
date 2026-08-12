from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.relationship import (
    RelationshipReconcileJob,
    RelationshipReconcileJobStatus,
    RelationshipReconcileOutcome,
)
from app.services.relationship_contract import (
    RELATIONSHIP_RECONCILE_JOB_VERSION,
    RELATIONSHIP_RECOVERY_STALE_SECONDS_DEFAULT,
)
from app.services.relationship_reconciler import RelationshipReconciler


class RelationshipScheduler:
    """Small local scheduler facade; application lifecycle wiring belongs to Task 10."""

    def __init__(
        self,
        reconciler: RelationshipReconciler,
        *,
        persona_artifact_id: str,
        recovery_stale_seconds: int = RELATIONSHIP_RECOVERY_STALE_SECONDS_DEFAULT,
    ) -> None:
        if not isinstance(persona_artifact_id, str) or not persona_artifact_id:
            raise ValueError("relationship scheduler Persona is required")
        if type(recovery_stale_seconds) is not int or recovery_stale_seconds < 1:
            raise ValueError("relationship recovery stale seconds must be positive")
        self._reconciler = reconciler
        self._persona_artifact_id = persona_artifact_id
        self._stale_seconds = recovery_stale_seconds

    def schedule(
        self,
        memory_ids: tuple[str, ...],
        *,
        created_at: datetime,
    ) -> tuple[RelationshipReconcileJob, ...]:
        jobs: list[RelationshipReconcileJob] = []
        for memory_id in sorted(set(memory_ids)):
            jobs.append(
                self._reconciler.reserve(
                    memory_id=memory_id,
                    persona_artifact_id=self._persona_artifact_id,
                    created_at=created_at,
                )
            )
        return tuple(jobs)

    def run_pending(self, *, now: datetime) -> tuple[RelationshipReconcileJob, ...]:
        return tuple(
            self._reconciler.run(job.id, now=now)
            for job in self._reconciler.pending_jobs()
        )

    def full_reconcile(self, *, now: datetime) -> tuple[RelationshipReconcileJob, ...]:
        memory_ids = self._reconciler.classified_current_memory_ids()
        self.schedule(memory_ids, created_at=now)
        return self.run_pending(now=now)

    def recover(self, *, now: datetime) -> tuple[RelationshipReconcileJob, ...]:
        results: list[RelationshipReconcileJob] = []
        stale_before = now - timedelta(seconds=self._stale_seconds)
        for job in self._reconciler.recoverable_jobs():
            if job.job_schema_version != RELATIONSHIP_RECONCILE_JOB_VERSION:
                results.append(
                    self._reconciler.terminalize_recovery(
                        job=job,
                        outcome=RelationshipReconcileOutcome.INCOMPATIBLE_RECOVERY,
                        reason_code="unsupported_job_version",
                        now=now,
                    )
                )
            elif job.status is RelationshipReconcileJobStatus.RUNNING:
                if job.started_at is not None and job.started_at <= stale_before:
                    results.append(
                        self._reconciler.terminalize_recovery(
                            job=job,
                            outcome=RelationshipReconcileOutcome.INCOMPATIBLE_RECOVERY,
                            reason_code="stale_running_job",
                            now=now,
                        )
                    )
            elif job.status is RelationshipReconcileJobStatus.FAILED:
                if job.attempt_count >= self._reconciler.max_attempts:
                    results.append(
                        self._reconciler.terminalize_recovery(
                            job=job,
                            status=RelationshipReconcileJobStatus.FAILED,
                            outcome=RelationshipReconcileOutcome.FAILED,
                            reason_code="attempts_exhausted",
                            now=now,
                        )
                    )
            else:
                results.append(self._reconciler.run(job.id, now=now))
        return tuple(results)
