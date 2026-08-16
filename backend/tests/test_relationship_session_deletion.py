from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.models import MemorySource, MemoryType
from app.repositories.memories import MemoryRepository
from app.repositories.sqlite import managed_connection
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.services.memory_source_reference import MemorySourceReferenceService
from app.services.session_deletion_coordinator import SessionDeletionCoordinator

from tests.test_relationship_projector import _BASE_TIME, _insert_persona


def test_session_deletion_keeps_relationship_event_when_memory_independently_eligible(
    tmp_path: Path,
) -> None:
    """When session deletion does not forget the source memory, its
    relationship apply event must survive."""
    with managed_connection(f"sqlite:///{tmp_path / 'session.db'}") as connection:
        references = MemorySourceReferenceService(b"q" * 32)
        memories = MemoryRepository(connection, source_references=references)
        versioned = VersionedMemoryRepository(connection)
        _insert_persona(connection, "persona-1")
        connection.commit()

        # A memory whose source session is the deleted session.
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

        # Create a relationship apply for this memory.
        from app.domain.relationship import RelationshipEventType
        from app.repositories.relationship_ledger import RelationshipLedgerRepository
        from app.repositories.relationship_sources import RelationshipSourceRepository
        from app.services.relationship_authority import RelationshipAuthorityService
        from app.services.relationship_rules import RelationshipRuleSet
        from app.services.relationship_contract import RELATIONSHIP_RULE_VERSION

        ledger = RelationshipLedgerRepository(connection)
        authority = RelationshipAuthorityService(connection, ledger=ledger)
        auth = authority.effective(
            source_memory_id=memory.id,
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
        )
        source = RelationshipSourceRepository(connection).get_current(
            memory.id,
            authority=auth,
            relationship_rule_version=RELATIONSHIP_RULE_VERSION,
        )
        assert source is not None
        mapping = RelationshipRuleSet().map(source, persona_artifact_id="persona-1")
        with ledger.write_transaction():
            ledger.append_apply(source=source, mapping=mapping, created_at=_BASE_TIME)
        connection.commit()

        # Delete the session.
        coordinator = SessionDeletionCoordinator(
            connection,
            versioned=versioned,
            source_references=references,
        )
        coordinator.delete(session_id)

        # The memory is NOT forgotten by session deletion (it was a manual
        # memory), so its relationship event must remain.
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events WHERE event_kind='apply'"
        ).fetchone()[0] == 1
        # The session no longer exists.
        assert connection.execute(
            "SELECT COUNT(*) FROM sessions WHERE id=?", (session_id,)
        ).fetchone()[0] == 0
