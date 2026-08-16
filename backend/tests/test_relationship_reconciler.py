from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from app.domain.relationship import (
    RelationshipAuthorityActionKind,
    RelationshipEventType,
    RelationshipReconcileJobStatus,
    RelationshipReconcileOutcome,
)
from app.repositories.relationship_ledger import (
    RelationshipJobIdentityMismatchError,
    RelationshipLedgerRepository,
)
from app.services.relationship_authority import RelationshipAuthorityService
from app.services.relationship_reconciler import RelationshipReconciler
from app.services.relationship_scheduler import RelationshipScheduler

from test_relationship_projector import (
    _BASE_TIME,
    _database,
    _insert_persona,
    _insert_source,
)


def _seed_source(connection, *, subject_code: str = "shared_experience") -> None:
    _insert_persona(connection, "persona-1")
    content = "小雪" if subject_code == "preferred_address" else "一起赏雪"
    _insert_source(
        connection,
        memory_id="memory-1",
        version_id="version-1",
        subject_code=subject_code,
        content=content,
        created_at=_BASE_TIME,
    )
    connection.commit()


def test_reservation_is_deduplicated_by_exact_snapshot_identity(tmp_path: Path) -> None:
    with _database(tmp_path, "reserve.db") as connection:
        _seed_source(connection)
        reconciler = RelationshipReconciler(connection)

        first = reconciler.reserve(
            memory_id="memory-1",
            persona_artifact_id="persona-1",
            created_at=_BASE_TIME + timedelta(days=1),
        )
        duplicate = reconciler.reserve(
            memory_id="memory-1",
            persona_artifact_id="persona-1",
            created_at=_BASE_TIME + timedelta(days=2),
        )

        assert duplicate == first
        assert first.status is RelationshipReconcileJobStatus.PENDING
        assert first.source_memory_version_id == "version-1"
        assert first.captured_authority_generation == 0
        assert len(first.captured_inherited_authority_fingerprint) == 64
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_reconcile_jobs"
        ).fetchone()[0] == 1


def test_eligible_job_applies_once_projects_and_writes_metadata_audit(tmp_path: Path) -> None:
    with _database(tmp_path, "apply.db") as connection:
        _seed_source(connection)
        reconciler = RelationshipReconciler(connection)
        job = reconciler.reserve(
            memory_id="memory-1",
            persona_artifact_id="persona-1",
            created_at=_BASE_TIME + timedelta(days=1),
        )

        result = reconciler.run(job.id, now=_BASE_TIME + timedelta(days=2))
        duplicate = reconciler.run(job.id, now=_BASE_TIME + timedelta(days=3))

        assert result.status is RelationshipReconcileJobStatus.SUCCEEDED
        assert result.outcome is RelationshipReconcileOutcome.APPLIED
        assert duplicate == result
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events WHERE event_kind='apply'"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_projections"
        ).fetchone()[0] == 1
        audit = connection.execute(
            "SELECT outcome, reason_code FROM relationship_job_audits WHERE job_id=?",
            (job.id,),
        ).fetchone()
        assert tuple(audit) == ("applied", "eligible_apply")
        serialized = "\n".join(
            str(tuple(row))
            for row in connection.execute(
                "SELECT * FROM relationship_reconcile_jobs"
            ).fetchall()
        )
        assert "一起赏雪" not in serialized


def test_source_change_after_reservation_terminalizes_stale_without_apply(tmp_path: Path) -> None:
    with _database(tmp_path, "stale-source.db") as connection:
        _seed_source(connection)
        reconciler = RelationshipReconciler(connection)
        job = reconciler.reserve(
            memory_id="memory-1",
            persona_artifact_id="persona-1",
            created_at=_BASE_TIME + timedelta(days=1),
        )
        connection.execute(
            "UPDATE memory_record_states SET state='archived', record_generation=1 "
            "WHERE memory_id='memory-1'"
        )
        connection.commit()

        result = reconciler.run(job.id, now=_BASE_TIME + timedelta(days=2))

        assert result.status is RelationshipReconcileJobStatus.SKIPPED
        assert result.outcome is RelationshipReconcileOutcome.STALE_SOURCE
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events"
        ).fetchone()[0] == 0


def test_authority_change_after_reservation_terminalizes_stale(tmp_path: Path) -> None:
    with _database(tmp_path, "stale-authority.db") as connection:
        _seed_source(connection)
        reconciler = RelationshipReconciler(connection)
        job = reconciler.reserve(
            memory_id="memory-1",
            persona_artifact_id="persona-1",
            created_at=_BASE_TIME + timedelta(days=1),
        )
        ledger = RelationshipLedgerRepository(connection)
        service = RelationshipAuthorityService(connection, ledger=ledger)
        current = service.effective(
            source_memory_id="memory-1",
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
        )
        service.suppress(
            source_memory_id="memory-1",
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
            action_kind=RelationshipAuthorityActionKind.USER_REVOKE,
            reason_code="user_revoked",
            expected_decision_id=current.decision_id,
            expected_decision_generation=current.generation,
            expected_authority_epoch=current.authority_epoch,
        )

        result = reconciler.run(job.id, now=_BASE_TIME + timedelta(days=2))

        assert result.status is RelationshipReconcileJobStatus.SKIPPED
        assert result.outcome is RelationshipReconcileOutcome.STALE_AUTHORITY
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events"
        ).fetchone()[0] == 0


def test_archive_after_apply_reconciles_revoke(tmp_path: Path) -> None:
    with _database(tmp_path, "archive-revoke.db") as connection:
        _seed_source(connection)
        reconciler = RelationshipReconciler(connection)
        first = reconciler.reserve(
            memory_id="memory-1",
            persona_artifact_id="persona-1",
            created_at=_BASE_TIME + timedelta(days=1),
        )
        reconciler.run(first.id, now=_BASE_TIME + timedelta(days=2))
        connection.execute(
            "UPDATE memory_record_states SET state='archived', record_generation=1 "
            "WHERE memory_id='memory-1'"
        )
        connection.commit()

        archived = reconciler.reserve(
            memory_id="memory-1",
            persona_artifact_id="persona-1",
            created_at=_BASE_TIME + timedelta(days=3),
        )
        result = reconciler.run(archived.id, now=_BASE_TIME + timedelta(days=4))

        assert result.status is RelationshipReconcileJobStatus.SUCCEEDED
        assert result.outcome is RelationshipReconcileOutcome.REVOKED
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events WHERE event_kind='revoke'"
        ).fetchone()[0] == 1


def test_captured_suppression_reconciles_existing_apply(tmp_path: Path) -> None:
    with _database(tmp_path, "suppression-revoke.db") as connection:
        _seed_source(connection)
        reconciler = RelationshipReconciler(connection)
        first = reconciler.reserve(
            memory_id="memory-1",
            persona_artifact_id="persona-1",
            created_at=_BASE_TIME + timedelta(days=1),
        )
        reconciler.run(first.id, now=_BASE_TIME + timedelta(days=2))
        ledger = RelationshipLedgerRepository(connection)
        authority = RelationshipAuthorityService(connection, ledger=ledger)
        current = authority.effective(
            source_memory_id="memory-1",
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
        )
        authority.suppress(
            source_memory_id="memory-1",
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
            action_kind=RelationshipAuthorityActionKind.USER_REVOKE,
            reason_code="user_revoked",
            expected_decision_id=current.decision_id,
            expected_decision_generation=current.generation,
            expected_authority_epoch=current.authority_epoch,
        )
        suppressed = reconciler.reserve(
            memory_id="memory-1",
            persona_artifact_id="persona-1",
            created_at=_BASE_TIME + timedelta(days=3),
        )

        result = reconciler.run(suppressed.id, now=_BASE_TIME + timedelta(days=4))

        assert result.status is RelationshipReconcileJobStatus.SUCCEEDED
        assert result.outcome is RelationshipReconcileOutcome.REVOKED
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events WHERE event_kind='revoke'"
        ).fetchone()[0] == 1


def test_new_current_version_revokes_old_apply_and_applies_new_version(tmp_path: Path) -> None:
    with _database(tmp_path, "supersede.db") as connection:
        _seed_source(connection)
        reconciler = RelationshipReconciler(connection)
        first = reconciler.reserve(
            memory_id="memory-1",
            persona_artifact_id="persona-1",
            created_at=_BASE_TIME + timedelta(days=1),
        )
        reconciler.run(first.id, now=_BASE_TIME + timedelta(days=2))
        connection.execute(
            """
            INSERT INTO memory_versions (
                id, memory_id, version_number, parent_version_id, operation,
                memory_type, subject, content, content_hash, canonical_key_hash,
                subject_key_hash, canonicalization_version, confidence, importance,
                source_kind, source_session_id, source_session_reference_hash,
                writer_policy_version, created_at, redacted_at, canonical_subject_code
            ) VALUES ('version-2', 'memory-1', 2, 'version-1', 'user_edit',
                      'relationship_event', 'shared_experience', '再一起赏雪',
                      'hash-version-2', NULL, NULL, 'memory-canonicalization-v1',
                      0.9, 3, 'user_edit', NULL, NULL, 'manual-write-v1', ?, NULL,
                      'shared_experience')
            """,
            ((_BASE_TIME + timedelta(days=3)).isoformat(),),
        )
        connection.execute(
            """
            UPDATE memory_record_states
            SET current_version_id='version-2', head_version=2,
                record_generation=1, source_kind='user_edit'
            WHERE memory_id='memory-1'
            """
        )
        connection.commit()

        second = reconciler.reserve(
            memory_id="memory-1",
            persona_artifact_id="persona-1",
            created_at=_BASE_TIME + timedelta(days=4),
        )
        result = reconciler.run(second.id, now=_BASE_TIME + timedelta(days=5))

        assert result.outcome is RelationshipReconcileOutcome.APPLIED
        rows = connection.execute(
            "SELECT event_kind, source_memory_version_id FROM relationship_events "
            "ORDER BY event_kind, source_memory_version_id"
        ).fetchall()
        assert {(row["event_kind"], row["source_memory_version_id"]) for row in rows} == {
            ("apply", "version-1"),
            ("apply", "version-2"),
            ("revoke", "version-1"),
        }


def test_fault_rolls_back_event_projection_audit_and_job_transition(tmp_path: Path) -> None:
    with _database(tmp_path, "rollback.db") as connection:
        _seed_source(connection)
        reconciler = RelationshipReconciler(connection)
        job = reconciler.reserve(
            memory_id="memory-1",
            persona_artifact_id="persona-1",
            created_at=_BASE_TIME + timedelta(days=1),
        )

        with pytest.raises(RuntimeError, match="fault_after_event"):
            reconciler.run(
                job.id,
                now=_BASE_TIME + timedelta(days=2),
                fault_point="after_event",
            )

        persisted = reconciler.job(job.id)
        assert persisted is not None
        assert persisted.status is RelationshipReconcileJobStatus.PENDING
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_projections"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_job_audits"
        ).fetchone()[0] == 0


def test_schedule_surfaces_identity_mismatch_instead_of_silently_skipping(
    tmp_path: Path,
) -> None:
    """I-2: a captured-identity mismatch (invariant violation) must fail closed
    through the scheduler rather than being silently swallowed as an ordinary
    unclassifiable source."""
    with _database(tmp_path, "identity-mismatch.db") as connection:
        _seed_source(connection)
        _insert_persona(connection, "persona-2", version=2)
        # Reserve once with persona-1 (snapshot identity captured).
        reconciler = RelationshipReconciler(connection)
        first = reconciler.reserve(
            memory_id="memory-1",
            persona_artifact_id="persona-1",
            created_at=_BASE_TIME,
        )
        # The unique identity index omits persona_artifact_id, so re-reserving
        # the same source snapshot under a different persona collides with the
        # existing job and must raise RelationshipJobIdentityMismatchError.
        scheduler = RelationshipScheduler(
            RelationshipReconciler(connection),
            persona_artifact_id="persona-2",
        )
        with pytest.raises(RelationshipJobIdentityMismatchError):
            scheduler.schedule(("memory-1",), created_at=_BASE_TIME + timedelta(days=1))
        assert first.id is not None
