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


def test_recovery_runs_compatible_pending_job(tmp_path: Path) -> None:
    with _database(tmp_path, "recover-compatible.db") as connection:
        _seed_source(connection)
        reconciler = RelationshipReconciler(connection)
        scheduler = RelationshipScheduler(
            reconciler,
            persona_artifact_id="persona-1",
        )
        job = reconciler.reserve(
            memory_id="memory-1",
            persona_artifact_id="persona-1",
            created_at=_BASE_TIME + timedelta(days=1),
        )

        recovered = scheduler.recover(now=_BASE_TIME + timedelta(days=2))

        assert len(recovered) == 1
        assert recovered[0].id == job.id
        assert recovered[0].status is RelationshipReconcileJobStatus.SUCCEEDED
        assert recovered[0].outcome is RelationshipReconcileOutcome.APPLIED


def test_recovery_terminalizes_unsupported_job_version(tmp_path: Path) -> None:
    with _database(tmp_path, "recover-incompatible.db") as connection:
        _seed_source(connection)
        reconciler = RelationshipReconciler(connection)
        scheduler = RelationshipScheduler(
            reconciler,
            persona_artifact_id="persona-1",
        )
        job = reconciler.reserve(
            memory_id="memory-1",
            persona_artifact_id="persona-1",
            created_at=_BASE_TIME + timedelta(days=1),
        )
        connection.execute("DROP TRIGGER trg_relationship_jobs_frozen_snapshot_update")
        connection.execute(
            "UPDATE relationship_reconcile_jobs SET job_schema_version='old-version' "
            "WHERE id=?",
            (job.id,),
        )
        connection.commit()

        recovered = scheduler.recover(now=_BASE_TIME + timedelta(days=2))

        assert len(recovered) == 1
        assert recovered[0].status is RelationshipReconcileJobStatus.SKIPPED
        assert recovered[0].outcome is RelationshipReconcileOutcome.INCOMPATIBLE_RECOVERY
        audit = connection.execute(
            "SELECT outcome, reason_code FROM relationship_job_audits WHERE job_id=?",
            (job.id,),
        ).fetchone()
        assert tuple(audit) == ("incompatible_recovery", "unsupported_job_version")


def test_recovery_terminalizes_stale_running_job(tmp_path: Path) -> None:
    with _database(tmp_path, "recover-stale.db") as connection:
        _seed_source(connection)
        reconciler = RelationshipReconciler(connection)
        scheduler = RelationshipScheduler(
            reconciler,
            persona_artifact_id="persona-1",
        )
        job = reconciler.reserve(
            memory_id="memory-1",
            persona_artifact_id="persona-1",
            created_at=_BASE_TIME,
        )
        connection.execute(
            "UPDATE relationship_reconcile_jobs SET status='running', attempt_count=1, "
            "started_at=? WHERE id=?",
            ((_BASE_TIME + timedelta(minutes=1)).isoformat(), job.id),
        )
        connection.commit()

        recovered = scheduler.recover(now=_BASE_TIME + timedelta(days=1))

        assert len(recovered) == 1
        assert recovered[0].status is RelationshipReconcileJobStatus.SKIPPED
        assert recovered[0].outcome is RelationshipReconcileOutcome.INCOMPATIBLE_RECOVERY
        assert recovered[0].reason_code == "stale_running_job"
