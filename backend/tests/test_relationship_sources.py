from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from app.domain.models import MemoryType
from app.domain.relationship import (
    RelationshipAuthoritySnapshot,
    RelationshipEventType,
)
from app.repositories.memories import MemoryRepository
from app.repositories.relationship_sources import RelationshipSourceRepository
from app.repositories.sqlite import managed_connection
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.services.relationship_contract import RELATIONSHIP_RULE_VERSION
from app.services.versioned_memory_mutation import VersionedMemoryMutationService


def _mutations(connection) -> VersionedMemoryMutationService:
    return VersionedMemoryMutationService(
        connection,
        memories=MemoryRepository(connection),
        versioned=VersionedMemoryRepository(connection),
    )


def _authority(memory_id: str) -> RelationshipAuthoritySnapshot:
    return RelationshipAuthoritySnapshot(
        scope_id="default",
        source_memory_id=memory_id,
        event_type=RelationshipEventType.PREFERRED_ADDRESS,
        subject_code="preferred_address",
        decision_id=None,
        generation=0,
        action=None,
        authority_epoch=0,
        inherited_authority_fingerprint="a" * 64,
        suppressed=False,
    )


def _create_preferred_address(connection, *, content: str = " 小​雪 "):
    memory, conflicts = _mutations(connection).create_manual(
        content=content,
        memory_type=MemoryType.PREFERENCE,
        source_session_id=None,
        importance=2,
        confidence=0.75,
        canonical_subject_code="preferred_address",
    )
    assert conflicts == []
    return memory


def test_reads_exact_current_source_tuple_and_rechecks_every_field(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'source.db'}") as connection:
        memory = _create_preferred_address(connection)
        authority = _authority(memory.id)
        repository = RelationshipSourceRepository(connection)

        snapshot = repository.get_current(
            memory.id,
            authority=authority,
            relationship_rule_version=RELATIONSHIP_RULE_VERSION,
        )

        assert snapshot is not None
        assert snapshot.scope_id == "default"
        assert snapshot.source_memory_id == memory.id
        assert snapshot.record_head_version == 1
        assert snapshot.record_generation == 0
        assert snapshot.memory_type is MemoryType.PREFERENCE
        assert snapshot.canonical_subject_code == "preferred_address"
        assert snapshot.version_confidence == 0.75
        assert snapshot.version_importance == 2
        assert snapshot.version_created_at.tzinfo is not None
        assert snapshot.open_conflict is False
        assert snapshot.payload_redacted is False
        assert snapshot.authority_suppressed is False
        assert snapshot.preferred_address_candidate == "小​雪"
        assert repository.matches_current(snapshot, authority=authority)

        changed_authority = replace(authority, authority_epoch=1)
        assert not repository.matches_current(snapshot, authority=changed_authority)

        updated, conflicts = _mutations(connection).update(
            memory.id,
            content="雪乃",
            memory_type=None,
            importance=None,
            confidence=None,
            metadata=None,
        )
        assert conflicts == [] and updated.id == memory.id
        assert not repository.matches_current(snapshot, authority=authority)

        current = repository.get_current(
            memory.id,
            authority=authority,
            relationship_rule_version=RELATIONSHIP_RULE_VERSION,
        )
        assert current is not None
        assert current.source_memory_version_id != snapshot.source_memory_version_id
        assert current.record_head_version == 2
        assert current.preferred_address_candidate == "雪乃"
        assert repository.matches_current(current, authority=authority)


def test_open_conflict_and_redacted_or_deleted_head_are_fail_closed(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'closed.db'}") as connection:
        left = _create_preferred_address(connection, content="小雪")
        right = _create_preferred_address(connection, content="雪乃")
        left_id, right_id = sorted((left.id, right.id))
        connection.execute(
            """
            INSERT INTO memory_conflicts (
                conflict_id, left_memory_id, right_memory_id, status,
                resolution_kind, resolved_memory_id, created_at, resolved_at
            ) VALUES ('conflict-1', ?, ?, 'open', NULL, NULL, ?, NULL)
            """,
            (left_id, right_id, datetime.now(timezone.utc).isoformat()),
        )
        connection.commit()

        repository = RelationshipSourceRepository(connection)
        conflicted = repository.get_current(
            left.id,
            authority=_authority(left.id),
            relationship_rule_version=RELATIONSHIP_RULE_VERSION,
        )
        assert conflicted is not None and conflicted.open_conflict is True

        resolved, conflicts = _mutations(connection).create_manual(
            content="共度雪夜",
            memory_type=MemoryType.RELATIONSHIP_EVENT,
            source_session_id=None,
            importance=3,
            confidence=0.9,
            canonical_subject_code="shared_experience",
        )
        assert conflicts == []
        _mutations(connection).archive(resolved.id)
        archived = repository.get_current(
            resolved.id,
            authority=replace(
                _authority(resolved.id),
                event_type=RelationshipEventType.SHARED_EXPERIENCE,
                subject_code="shared_experience",
            ),
            relationship_rule_version=RELATIONSHIP_RULE_VERSION,
        )
        assert archived is not None
        assert archived.record_state.value == "archived"


def test_source_query_excludes_evidence_summaries_messages_and_emotion(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'evidence.db'}") as connection:
        memory = _create_preferred_address(connection, content="小雪")
        version = VersionedMemoryRepository(connection).get_current_version(memory.id)
        assert version is not None
        now = datetime.now(timezone.utc).isoformat()
        connection.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES ('s1', 't', ?, ?)",
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO messages (id, session_id, role, content, metadata_json, created_at)
            VALUES ('m1', 's1', 'user', 'untrusted evidence text', '{}', ?)
            """,
            (now,),
        )
        connection.execute(
            """
            INSERT INTO memory_evidence (
                evidence_id, memory_id, memory_version_id, source_session_id,
                source_message_id, source_session_reference_hash,
                source_message_reference_hash, source_available, source_deleted_at,
                relation, observed_at, extractor_kind, extractor_provider,
                extractor_model, confidence, created_at
            ) VALUES (
                'e1', ?, ?, 's1', 'm1', 'session-ref', 'message-ref', 1, NULL,
                'supports', ?, 'manual', NULL, NULL, 1.0, ?
            )
            """,
            (memory.id, version.id, now, now),
        )
        connection.execute(
            """
            INSERT INTO memory_evidence_retractions (evidence_id, reason_code, created_at)
            VALUES ('e1', 'user_retracted', ?)
            """,
            (now,),
        )
        connection.commit()

        statements: list[str] = []
        connection.set_trace_callback(statements.append)
        try:
            snapshot = RelationshipSourceRepository(connection).get_current(
                memory.id,
                authority=_authority(memory.id),
                relationship_rule_version=RELATIONSHIP_RULE_VERSION,
            )
        finally:
            connection.set_trace_callback(None)

        assert snapshot is not None
        source_sql = "\n".join(statements).lower()
        assert "memory_record_states" in source_sql
        assert "memory_versions" in source_sql
        assert "memories" in source_sql
        assert "memory_conflicts" in source_sql
        for forbidden in (
            "memory_evidence",
            "messages",
            "session_summaries",
            "emotion_",
            "provider",
        ):
            assert forbidden not in source_sql


def test_corrupt_storage_types_fail_closed_without_semantic_coercion(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'corrupt.db'}") as connection:
        memory = _create_preferred_address(connection, content="小雪")
        version = VersionedMemoryRepository(connection).get_current_version(memory.id)
        assert version is not None
        repository = RelationshipSourceRepository(connection)
        authority = _authority(memory.id)

        connection.execute("DROP TRIGGER trg_memory_versions_append_only_update")
        connection.execute(
            "UPDATE memory_versions SET content = ? WHERE id = ?",
            (sqlite3.Binary(b"abc"), version.id),
        )
        connection.commit()
        assert repository.get_current(memory.id, authority=authority) is None

        connection.execute(
            "UPDATE memory_versions SET content = '小雪', importance = 2.5 WHERE id = ?",
            (version.id,),
        )
        connection.commit()
        assert repository.get_current(memory.id, authority=authority) is None


def test_source_requires_matching_explicit_authority_identity(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'authority.db'}") as connection:
        memory = _create_preferred_address(connection)
        repository = RelationshipSourceRepository(connection)
        authority = _authority(memory.id)

        assert repository.get_current(
            memory.id,
            authority=replace(authority, source_memory_id="different"),
        ) is None
        assert repository.get_current(
            memory.id,
            authority=replace(
                authority,
                event_type=RelationshipEventType.SHARED_EXPERIENCE,
                subject_code="shared_experience",
            ),
        ) is None
        assert repository.get_current(
            memory.id,
            authority=replace(authority, inherited_authority_fingerprint="short"),
        ) is None
        assert repository.get_current(
            memory.id,
            authority=replace(authority, inherited_authority_fingerprint="g" * 64),
        ) is None
