from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from app.domain.relationship import (
    RelationshipReconcileJobStatus,
    RelationshipReconcileOutcome,
)
from app.services.relationship_reconciler import RelationshipReconciler
from app.services.relationship_scheduler import RelationshipScheduler

from test_relationship_projector import _BASE_TIME, _database
from test_relationship_reconciler import _seed_source


def test_scheduler_reserves_deterministic_memory_ids_once(tmp_path: Path) -> None:
    with _database(tmp_path, "scheduler.db") as connection:
        _seed_source(connection)
        scheduler = RelationshipScheduler(
            RelationshipReconciler(connection),
            persona_artifact_id="persona-1",
        )

        jobs = scheduler.schedule(
            ("memory-1", "memory-1"),
            created_at=_BASE_TIME + timedelta(days=1),
        )

        assert len(jobs) == 1
        assert jobs[0].source_memory_id == "memory-1"
        assert jobs[0].status is RelationshipReconcileJobStatus.PENDING


def test_scheduler_run_pending_is_idempotent(tmp_path: Path) -> None:
    with _database(tmp_path, "scheduler-run.db") as connection:
        _seed_source(connection)
        reconciler = RelationshipReconciler(connection)
        scheduler = RelationshipScheduler(
            reconciler,
            persona_artifact_id="persona-1",
        )
        scheduler.schedule(
            ("memory-1",),
            created_at=_BASE_TIME + timedelta(days=1),
        )

        first = scheduler.run_pending(now=_BASE_TIME + timedelta(days=2))
        second = scheduler.run_pending(now=_BASE_TIME + timedelta(days=3))

        assert len(first) == 1
        assert first[0].outcome is RelationshipReconcileOutcome.APPLIED
        assert second == ()
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events WHERE event_kind='apply'"
        ).fetchone()[0] == 1


def test_full_reconcile_enumerates_current_sources_deterministically(tmp_path: Path) -> None:
    with _database(tmp_path, "scheduler-full.db") as connection:
        _seed_source(connection)
        scheduler = RelationshipScheduler(
            RelationshipReconciler(connection),
            persona_artifact_id="persona-1",
        )

        results = scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=2))

        assert len(results) == 1
        assert results[0].source_memory_id == "memory-1"
        assert results[0].outcome is RelationshipReconcileOutcome.APPLIED


def test_scheduler_terminalizes_attempt_exhaustion(tmp_path: Path) -> None:
    with _database(tmp_path, "scheduler-exhaust.db") as connection:
        _seed_source(connection)
        reconciler = RelationshipReconciler(connection, max_attempts=1)
        scheduler = RelationshipScheduler(
            reconciler,
            persona_artifact_id="persona-1",
        )
        job = scheduler.schedule(
            ("memory-1",),
            created_at=_BASE_TIME + timedelta(days=1),
        )[0]
        with reconciler._ledger.write_transaction():
            reconciler._ledger.transition_job(
                job_id=job.id,
                expected_status=RelationshipReconcileJobStatus.PENDING,
                status=RelationshipReconcileJobStatus.FAILED,
                outcome=RelationshipReconcileOutcome.FAILED,
                attempt_count=1,
                reason_code="transient_failure",
                error_category="database_error",
                started_at=_BASE_TIME + timedelta(days=2),
                finished_at=_BASE_TIME + timedelta(days=2),
            )

        recovered = scheduler.recover(now=_BASE_TIME + timedelta(days=3))

        assert len(recovered) == 1
        assert recovered[0].status is RelationshipReconcileJobStatus.FAILED
        assert recovered[0].outcome is RelationshipReconcileOutcome.FAILED
        assert recovered[0].reason_code == "attempts_exhausted"
