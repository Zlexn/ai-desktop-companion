from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from app.domain.models import MemorySource, MemoryType
from app.domain.relationship import RelationshipEventType
from app.repositories.memories import MemoryRepository
from app.repositories.sqlite import managed_connection
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.services.memory_source_reference import MemorySourceReferenceService
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


def test_rule_version_change_revokes_old_apply_without_semantic_rewrite(
    tmp_path: Path,
) -> None:
    """A simulated rule version change must append an ordinary revoke for the
    now-invalid apply and must never rewrite old event semantics."""
    with _database(tmp_path, "upgrade.db") as connection:
        _insert_persona(connection, "persona-1")
        connection.commit()
        memory_id = _seed_source(connection)
        reconciler = RelationshipReconciler(connection)
        scheduler = RelationshipScheduler(reconciler, persona_artifact_id="persona-1")
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=1))
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events WHERE event_kind='apply'"
        ).fetchone()[0] == 1

        # Simulate a v2 rule upgrade: a reconciler bound to a new rule version
        # must treat the v1 apply as stale and revoke it.
        v2_reconciler = RelationshipReconciler(
            connection,
            rule_version="relationship-rules-v2",
        )
        v2_scheduler = RelationshipScheduler(
            v2_reconciler,
            persona_artifact_id="persona-1",
        )
        v2_scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=2))

        # The old apply must be revoked (ordinary revoke, not a new event type).
        kinds = [
            row["event_kind"]
            for row in connection.execute(
                "SELECT event_kind FROM relationship_events ORDER BY created_at, id"
            )
        ]
        assert kinds.count("apply") == 1
        assert kinds.count("revoke") == 1
        # No rule_migration event type exists.
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events WHERE event_type='rule_migration'"
        ).fetchone()[0] == 0
