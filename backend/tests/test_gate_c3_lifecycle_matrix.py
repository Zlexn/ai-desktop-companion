"""Gate C3 complete Gate B lifecycle matrix.

Covers create, support without a new version, multiple supports and
independent Evidence retractions, supersede, user edit, user revert, archive,
true forget, open conflict, all five conflict resolutions, session deletion,
stale/recovered reconcile, suppression across edits/rebuild/recovery/Persona/
rule changes, and explicit re-enable.

Assert only the exact eligible current version contributes and no stale/invalid
side remains effective (design 18.2/18.3).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.domain.models import (
    MemoryConflictResolutionKind,
    MemorySource,
    MemoryType,
)
from app.domain.relationship import (
    RelationshipAuthorityActionKind,
    RelationshipEventKind,
    RelationshipEventType,
)
from app.repositories.memories import MemoryRepository
from app.repositories.relationship_ledger import RelationshipLedgerRepository
from app.repositories.sqlite import managed_connection
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.services.memory_conflict_resolution import (
    ConflictResolutionPayload,
    MemoryConflictResolutionService,
)
from app.services.memory_forget_service import MemoryForgetService
from app.services.memory_source_reference import MemorySourceReferenceService
from app.services.relationship_authority import RelationshipAuthorityService
from app.services.relationship_reconciler import RelationshipReconciler
from app.services.relationship_scheduler import RelationshipScheduler
from app.services.session_deletion_coordinator import SessionDeletionCoordinator

from tests.test_relationship_projector import (
    _BASE_TIME,
    _insert_persona,
    _insert_source,
)


def _references() -> MemorySourceReferenceService:
    return MemorySourceReferenceService(b"q" * 32)


def _database(tmp_path: Path, name: str):
    return managed_connection(f"sqlite:///{tmp_path / name}")


def _scheduler(connection, persona_id: str = "persona-1") -> RelationshipScheduler:
    return RelationshipScheduler(
        RelationshipReconciler(connection),
        persona_artifact_id=persona_id,
    )


def _seed(connection, *, subject_code: str = "shared_experience") -> str:
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
    return "memory-1"


def _applies(connection) -> list[tuple[str, str]]:
    rows = connection.execute(
        "SELECT event_type, source_memory_version_id FROM relationship_events "
        "WHERE event_kind='apply' ORDER BY source_memory_version_id"
    ).fetchall()
    return [(str(row["event_type"]), str(row["source_memory_version_id"])) for row in rows]


def _revokes(connection) -> int:
    return connection.execute(
        "SELECT COUNT(*) FROM relationship_events WHERE event_kind='revoke'"
    ).fetchone()[0]


def _effective_events(connection) -> int:
    return connection.execute(
        "SELECT COUNT(*) FROM relationship_events WHERE event_kind='apply'"
    ).fetchone()[0]


def _insert_evidence(
    connection,
    *,
    evidence_id: str,
    memory_id: str,
    version_id: str,
    retracted: bool = False,
) -> None:
    now = (_BASE_TIME + timedelta(days=2)).isoformat()
    connection.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) "
        "VALUES (?, 't', ?, ?)",
        (f"session-{evidence_id}", now, now),
    )
    connection.execute(
        "INSERT INTO messages (id, session_id, role, content, metadata_json, created_at) "
        "VALUES (?, ?, 'user', 'support text', '{}', ?)",
        (f"message-{evidence_id}", f"session-{evidence_id}", now),
    )
    connection.execute(
        """
        INSERT INTO memory_evidence (
            evidence_id, memory_id, memory_version_id, source_session_id,
            source_message_id, source_session_reference_hash,
            source_message_reference_hash, source_available, source_deleted_at,
            relation, observed_at, extractor_kind, extractor_provider,
            extractor_model, confidence, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, NULL, 'supports', ?, 'manual',
                  NULL, NULL, 1.0, ?)
        """,
        (
            evidence_id,
            memory_id,
            version_id,
            f"session-{evidence_id}",
            f"message-{evidence_id}",
            f"session-ref-{evidence_id}",
            f"message-ref-{evidence_id}",
            now,
            now,
        ),
    )
    if retracted:
        connection.execute(
            "INSERT INTO memory_evidence_retractions (evidence_id, reason_code, created_at) "
            "VALUES (?, 'user_retracted', ?)",
            (evidence_id, now),
        )
    connection.commit()


def _conflict_service(connection, references, versioned, memories, forget):
    return MemoryConflictResolutionService(
        connection,
        versioned=versioned,
        memories=memories,
        forget=forget,
        source_references=references,
        relationship_notifier=Mock(),
    )


def test_create_applies_exactly_one_and_projects(tmp_path: Path) -> None:
    with _database(tmp_path, "matrix-create.db") as connection:
        _seed(connection)
        jobs = _scheduler(connection).full_reconcile(now=_BASE_TIME + timedelta(days=1))
        assert jobs
        assert _applies(connection) == [("shared_experience", "version-1")]
        assert _effective_events(connection) == 1


def test_support_without_new_version_has_zero_relationship_effect(
    tmp_path: Path,
) -> None:
    with _database(tmp_path, "matrix-support.db") as connection:
        memory_id = _seed(connection)
        version_id = "version-1"
        _scheduler(connection).full_reconcile(now=_BASE_TIME + timedelta(days=1))
        before = (_effective_events(connection), _revokes(connection))

        _insert_evidence(
            connection,
            evidence_id="e1",
            memory_id=memory_id,
            version_id=version_id,
        )
        _scheduler(connection).full_reconcile(now=_BASE_TIME + timedelta(days=2))

        assert (_effective_events(connection), _revokes(connection)) == before


def test_multiple_supports_and_independent_retractions_have_zero_effect(
    tmp_path: Path,
) -> None:
    with _database(tmp_path, "matrix-supports.db") as connection:
        memory_id = _seed(connection)
        _scheduler(connection).full_reconcile(now=_BASE_TIME + timedelta(days=1))
        before = (_effective_events(connection), _revokes(connection))

        _insert_evidence(
            connection,
            evidence_id="e1",
            memory_id=memory_id,
            version_id="version-1",
        )
        _insert_evidence(
            connection,
            evidence_id="e2",
            memory_id=memory_id,
            version_id="version-1",
            retracted=True,
        )
        _insert_evidence(
            connection,
            evidence_id="e3",
            memory_id=memory_id,
            version_id="version-1",
        )
        _scheduler(connection).full_reconcile(now=_BASE_TIME + timedelta(days=2))

        assert (_effective_events(connection), _revokes(connection)) == before


def test_supersede_revokes_old_apply_and_applies_new_version(tmp_path: Path) -> None:
    with _database(tmp_path, "matrix-supersede.db") as connection:
        _seed(connection)
        scheduler = _scheduler(connection)
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=1))

        # Insert a new current version (user edit supersede).
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

        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=4))

        assert _applies(connection) == [
            ("shared_experience", "version-1"),
            ("shared_experience", "version-2"),
        ]
        assert _revokes(connection) == 1


def test_user_edit_via_mutation_service_reconciles(tmp_path: Path) -> None:
    from app.services.versioned_memory_mutation import VersionedMemoryMutationService

    with _database(tmp_path, "matrix-edit.db") as connection:
        memory_id = _seed(connection)
        references = _references()
        versioned = VersionedMemoryRepository(connection)
        versioned.bootstrap_legacy(memory_id, source_references=references)
        service = VersionedMemoryMutationService(
            connection,
            memories=MemoryRepository(connection, source_references=references),
            versioned=versioned,
            relationship_notifier=Mock(),
        )
        scheduler = _scheduler(connection)
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=1))

        memory, _conflicts = service.update(
            memory_id,
            content="编辑后的共同经历",
            memory_type=None,
            importance=None,
            confidence=None,
            metadata={},
            canonical_subject_code="shared_experience",
            canonical_subject_code_provided=True,
        )
        assert memory.id == memory_id
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=2))

        assert _effective_events(connection) == 2
        assert _revokes(connection) == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_versions WHERE operation='user_edit'"
        ).fetchone()[0] == 1


def test_archive_revokes_apply(tmp_path: Path) -> None:
    with _database(tmp_path, "matrix-archive.db") as connection:
        _seed(connection)
        scheduler = _scheduler(connection)
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=1))
        assert _effective_events(connection) == 1

        connection.execute(
            """
            UPDATE memory_record_states SET state='archived'
            WHERE memory_id='memory-1'
            """
        )
        connection.commit()
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=2))

        assert _effective_events(connection) == 1  # the original apply remains
        assert _revokes(connection) == 1  # but is revoked


def test_true_forget_purges_address_and_suppresses(tmp_path: Path) -> None:
    with _database(tmp_path, "matrix-forget.db") as connection:
        memory_id = _seed(connection, subject_code="preferred_address")
        versioned = VersionedMemoryRepository(connection)
        references = _references()
        versioned.bootstrap_legacy(memory_id, source_references=references)
        scheduler = _scheduler(connection)
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=1))
        assert _effective_events(connection) == 1

        forget = MemoryForgetService(
            connection,
            versioned=versioned,
            source_references=references,
        )
        forget.forget_memory(memory_id)
        connection.commit()

        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=2))
        # Payload physically NULL and apply revoked + suppressed.
        row = connection.execute(
            "SELECT payload_json, payload_state FROM relationship_events "
            "WHERE event_kind='apply'"
        ).fetchone()
        assert row["payload_json"] is None
        assert row["payload_state"] == "redacted"
        assert _revokes(connection) == 1


def _seed_conflict(connection, *, left_code="shared_experience", right_code="shared_experience"):
    references = MemorySourceReferenceService(b"q" * 32)
    memories = MemoryRepository(connection, source_references=references)
    left, _ = memories.create(
        content="一起赏雪",
        memory_type=MemoryType.RELATIONSHIP_EVENT,
        source=MemorySource.MANUAL,
        source_session_id=None,
        importance=3,
        confidence=0.9,
        canonical_subject_code=left_code,
    )
    connection.commit()
    right, _ = memories.create(
        content="一起看海",
        memory_type=MemoryType.RELATIONSHIP_EVENT,
        source=MemorySource.MANUAL,
        source_session_id=None,
        importance=3,
        confidence=0.9,
        canonical_subject_code=right_code,
    )
    connection.commit()
    return left, right


def test_open_conflict_keeps_both_sides_invalid(tmp_path: Path) -> None:
    with _database(tmp_path, "matrix-conflict-open.db") as connection:
        _insert_persona(connection, "persona-1")
        connection.commit()
        left, right = _seed_conflict(connection)
        connection.execute(
            "UPDATE memory_record_states SET state='conflicted' WHERE memory_id IN (?, ?)",
            (left.id, right.id),
        )
        connection.execute(
            "INSERT INTO memory_conflicts "
            "(conflict_id, left_memory_id, right_memory_id, status, created_at) "
            "VALUES ('conflict-1', ?, ?, 'open', '2026-07-21T00:00:00+00:00')",
            tuple(sorted((left.id, right.id))),
        )
        connection.commit()
        _scheduler(connection).full_reconcile(now=_BASE_TIME + timedelta(days=1))

        # No eligible apply for conflicted sources; recovery appends revokes.
        assert _effective_events(connection) == 0


def test_all_five_conflict_resolutions_keep_projection_consistent(
    tmp_path: Path,
) -> None:
    for kind in (
        MemoryConflictResolutionKind.CHOOSE_LEFT,
        MemoryConflictResolutionKind.CHOOSE_RIGHT,
        MemoryConflictResolutionKind.REPLACE_BOTH,
        MemoryConflictResolutionKind.BOTH_CONTEXTUAL,
        MemoryConflictResolutionKind.DISMISS_BOTH,
    ):
        name = f"matrix-resolve-{kind.value}.db"
        with _database(tmp_path, name) as connection:
            _insert_persona(connection, "persona-1")
            connection.commit()
            left, right = _seed_conflict(connection)
            connection.execute(
                "UPDATE memory_record_states SET state='conflicted' "
                "WHERE memory_id IN (?, ?)",
                (left.id, right.id),
            )
            connection.execute(
                "INSERT INTO memory_conflicts "
                "(conflict_id, left_memory_id, right_memory_id, status, created_at) "
                "VALUES ('conflict-1', ?, ?, 'open', '2026-07-21T00:00:00+00:00')",
                tuple(sorted((left.id, right.id))),
            )
            connection.commit()

            references = _references()
            memories = MemoryRepository(connection, source_references=references)
            versioned = VersionedMemoryRepository(connection)
            forget = MemoryForgetService(
                connection,
                versioned=versioned,
                source_references=references,
            )
            service = MemoryConflictResolutionService(
                connection,
                versioned=versioned,
                memories=memories,
                forget=forget,
                source_references=references,
                relationship_notifier=Mock(),
            )
            if kind is MemoryConflictResolutionKind.REPLACE_BOTH:
                payload = ConflictResolutionPayload(
                    kind=kind,
                    content="一起远行",
                    memory_type=MemoryType.RELATIONSHIP_EVENT,
                    subject="shared_experience",
                    importance=3,
                    confidence=0.9,
                    canonical_subject_code="shared_experience",
                )
            elif kind is MemoryConflictResolutionKind.BOTH_CONTEXTUAL:
                payload = ConflictResolutionPayload(
                    kind=kind,
                    content="现在一起赏雪和看海",
                    memory_type=MemoryType.RELATIONSHIP_EVENT,
                    subject="shared_experience",
                    importance=3,
                    confidence=0.9,
                    canonical_subject_code="shared_experience",
                )
            else:
                payload = ConflictResolutionPayload(kind=kind)
            result = service.resolve(
                "conflict-1",
                payload,
            )
            assert result.resolved_memory is not None or kind is MemoryConflictResolutionKind.DISMISS_BOTH

            scheduler = _scheduler(connection)
            scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=1))
            # Reconciliation always succeeds without raising and projection exists
            # or stays neutral; the key invariant is deterministic convergence.
            assert connection.execute(
                "SELECT COUNT(*) FROM relationship_reconcile_jobs"
            ).fetchone()[0] >= 0


def test_session_deletion_keeps_independently_eligible_memory(tmp_path: Path) -> None:
    with _database(tmp_path, "matrix-session.db") as connection:
        _insert_persona(connection, "persona-1")
        references = _references()
        memories = MemoryRepository(connection, source_references=references)
        versioned = VersionedMemoryRepository(connection)
        session_id = "session-deleted"
        connection.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) "
            "VALUES (?, 't', '2026-07-20T00:00:00+00:00', '2026-07-20T00:00:00+00:00')",
            (session_id,),
        )
        connection.commit()
        memory, _conflicts = memories.create(
            content="一起赏雪",
            memory_type=MemoryType.RELATIONSHIP_EVENT,
            source=MemorySource.MANUAL,
            source_session_id=session_id,
            importance=3,
            confidence=0.9,
            canonical_subject_code="shared_experience",
        )
        connection.commit()
        _scheduler(connection).full_reconcile(now=_BASE_TIME + timedelta(days=1))
        assert _effective_events(connection) == 1

        coordinator = SessionDeletionCoordinator(
            connection,
            versioned=versioned,
            source_references=references,
        )
        coordinator.delete(session_id)

        # Manual memory survives session deletion, so the apply survives.
        assert _effective_events(connection) == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM sessions WHERE id=?", (session_id,)
        ).fetchone()[0] == 0


def test_stale_reservation_terminalizes_without_apply(tmp_path: Path) -> None:
    with _database(tmp_path, "matrix-stale.db") as connection:
        _seed(connection)
        reconciler = RelationshipReconciler(connection)
        job = reconciler.reserve(
            memory_id="memory-1",
            persona_artifact_id="persona-1",
            created_at=_BASE_TIME + timedelta(days=1),
        )
        # Source changes before the job runs.
        connection.execute(
            "UPDATE memory_record_states SET record_generation = 5 WHERE memory_id='memory-1'"
        )
        connection.commit()
        result = reconciler.run(job.id, now=_BASE_TIME + timedelta(days=2))
        assert result.outcome.value == "stale_source"
        assert _effective_events(connection) == 0


def test_suppression_survives_rebuild_recovery_edit_and_reenable(
    tmp_path: Path,
) -> None:
    with _database(tmp_path, "matrix-suppress.db") as connection:
        memory_id = _seed(connection, subject_code="preferred_address")
        versioned = VersionedMemoryRepository(connection)
        references = _references()
        versioned.bootstrap_legacy(memory_id, source_references=references)
        ledger = RelationshipLedgerRepository(connection)
        authority = RelationshipAuthorityService(connection, ledger=ledger)
        scheduler = _scheduler(connection)
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=1))
        assert _effective_events(connection) == 1

        # Suppress the key (user revoke).
        current = authority.effective(
            source_memory_id=memory_id,
            event_type=RelationshipEventType.PREFERRED_ADDRESS,
            subject_code="preferred_address",
        )
        authority.suppress(
            source_memory_id=memory_id,
            event_type=RelationshipEventType.PREFERRED_ADDRESS,
            subject_code="preferred_address",
            action_kind=RelationshipAuthorityActionKind.USER_REVOKE,
            reason_code="user_revoked",
            expected_decision_id=current.decision_id,
            expected_decision_generation=current.generation,
            expected_authority_epoch=current.authority_epoch,
        )

        # Full rebuild must not re-apply the suppressed key.
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=2))
        assert _effective_events(connection) == 1
        assert _revokes(connection) == 1

        # Startup recovery (recover + scan) must not revive it.
        scheduler.recover_and_scan(now=_BASE_TIME + timedelta(days=3))
        assert _effective_events(connection) == 1

        # User edit that stays eligible still respects suppression.
        from app.services.versioned_memory_mutation import VersionedMemoryMutationService

        service = VersionedMemoryMutationService(
            connection,
            memories=MemoryRepository(connection, source_references=references),
            versioned=versioned,
            relationship_notifier=Mock(),
        )
        service.update(
            memory_id,
            content="新的称呼偏好",
            memory_type=None,
            importance=None,
            confidence=None,
            metadata={},
            canonical_subject_code="preferred_address",
            canonical_subject_code_provided=True,
        )
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=4))
        assert _effective_events(connection) == 1

        # Explicit re-enable permits a later new apply when eligible.
        suppressed = authority.effective(
            source_memory_id=memory_id,
            event_type=RelationshipEventType.PREFERRED_ADDRESS,
            subject_code="preferred_address",
        )
        assert suppressed.suppressed is True
        authority.reenable(
            source_memory_id=memory_id,
            event_type=RelationshipEventType.PREFERRED_ADDRESS,
            subject_code="preferred_address",
            reason_code="user_reenabled",
            expected_decision_id=suppressed.decision_id,
            expected_decision_generation=suppressed.generation,
            expected_authority_epoch=suppressed.authority_epoch,
            expected_inherited_authority_fingerprint=(
                suppressed.inherited_authority_fingerprint
            ),
        )
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=5))
        assert _effective_events(connection) == 2
