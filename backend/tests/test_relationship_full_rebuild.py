from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from app.domain.models import MemorySource, MemoryType
from app.domain.relationship import (
    RelationshipAuthorityActionKind,
    RelationshipEventType,
)
from app.repositories.memories import MemoryRepository
from app.repositories.relationship_ledger import RelationshipLedgerRepository
from app.repositories.sqlite import managed_connection
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.services.memory_source_reference import MemorySourceReferenceService
from app.services.relationship_authority import RelationshipAuthorityService
from app.services.relationship_reconciler import RelationshipReconciler
from app.services.relationship_scheduler import RelationshipScheduler

from tests.test_relationship_projector import _BASE_TIME, _insert_persona


def _database(tmp_path: Path, name: str):
    return managed_connection(f"sqlite:///{tmp_path / name}")


def _seed_source(connection) -> str:
    references = MemorySourceReferenceService(b"q" * 32)
    memories = MemoryRepository(connection, source_references=references)
    memory, _conflicts = memories.create(
        content="一起赏雪",
        memory_type=MemoryType.RELATIONSHIP_EVENT,
        source=MemorySource.MANUAL,
        source_session_id=None,
        importance=3,
        confidence=0.9,
        canonical_subject_code="shared_experience",
    )
    connection.commit()
    return memory.id


def test_full_rebuild_produces_identical_semantics_without_delta_multiply(
    tmp_path: Path,
) -> None:
    """Full rebuild must not multiply familiarity delta and must produce
    identical semantic output (design §10.3, plan Task 13)."""
    with _database(tmp_path, "rebuild.db") as connection:
        _insert_persona(connection, "persona-1")
        connection.commit()
        memory_id = _seed_source(connection)
        reconciler = RelationshipReconciler(connection)
        scheduler = RelationshipScheduler(reconciler, persona_artifact_id="persona-1")
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=1))

        projection_after_first = connection.execute(
            "SELECT familiarity FROM relationship_projections ORDER BY version DESC LIMIT 1"
        ).fetchone()[0]

        # Rebuild must produce identical semantic output (idempotent).
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=2))
        projection_after_rebuild = connection.execute(
            "SELECT familiarity FROM relationship_projections ORDER BY version DESC LIMIT 1"
        ).fetchone()[0]
        assert projection_after_rebuild == projection_after_first
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events WHERE event_kind='apply'"
        ).fetchone()[0] == 1


def test_full_rebuild_does_not_restore_suppressed_key(tmp_path: Path) -> None:
    """A user-suppressed key must remain suppressed after a full rebuild."""
    with _database(tmp_path, "rebuild-suppress.db") as connection:
        _insert_persona(connection, "persona-1")
        connection.commit()
        memory_id = _seed_source(connection)
        reconciler = RelationshipReconciler(connection)
        scheduler = RelationshipScheduler(reconciler, persona_artifact_id="persona-1")
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=1))
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events WHERE event_kind='apply'"
        ).fetchone()[0] == 1

        # Suppress the key (user revoke).
        ledger = RelationshipLedgerRepository(connection)
        authority = RelationshipAuthorityService(connection, ledger=ledger)
        current = authority.effective(
            source_memory_id=memory_id,
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
        )
        authority.suppress(
            source_memory_id=memory_id,
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
            action_kind=RelationshipAuthorityActionKind.USER_REVOKE,
            reason_code="user_revoked",
            expected_decision_id=current.decision_id,
            expected_decision_generation=current.generation,
            expected_authority_epoch=current.authority_epoch,
        )

        # Full rebuild must not re-apply the suppressed key.
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=3))
        # The original apply gets revoked; no new apply for the suppressed key.
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events WHERE event_kind='apply'"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events WHERE event_kind='revoke'"
        ).fetchone()[0] == 1
