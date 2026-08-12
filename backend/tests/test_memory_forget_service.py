from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.errors import MemoryCandidateForgottenError
from app.domain.models import (
    MemoryDeletionScope,
    MemoryAuditOperation,
    MemorySource,
    MemoryStatus,
    MemoryType,
    MemoryVersionOperation,
)
from app.repositories.memories import MemoryRepository
from app.repositories.memory_audit import MemoryAuditRepository
from app.repositories.sqlite import managed_connection
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.services.memory_commit_policy import canonicalize_memory_v1
from app.services.memory_forget_service import MemoryForgetService
from app.services.memory_source_reference import MemorySourceReferenceService
from app.services.session_deletion_coordinator import SessionDeletionCoordinator


_NOW = datetime(2026, 7, 20, tzinfo=UTC)


def _service(connection, *, fault_injector=None):
    return MemoryForgetService(
        connection,
        versioned=VersionedMemoryRepository(connection),
        source_references=MemorySourceReferenceService(b"f" * 32),
        fault_injector=fault_injector,
    )


def _seed_session(connection, session_id="session-1"):
    connection.execute(
        "INSERT INTO sessions VALUES (?, 'title', ?, ?)",
        (session_id, _NOW.isoformat(), _NOW.isoformat()),
    )
    connection.executemany(
        "INSERT INTO messages VALUES (?, ?, ?, ?, '{}', ?)",
        (
            (f"{session_id}-user-1", session_id, "user", "source one", _NOW.isoformat()),
            (f"{session_id}-assistant-1", session_id, "assistant", "reply", _NOW.isoformat()),
            (f"{session_id}-user-2", session_id, "user", "source two", _NOW.isoformat()),
        ),
    )
    connection.commit()


def _create_formal(connection, *, session_id="session-1", content="private payload"):
    return MemoryRepository(
        connection,
        source_references=MemorySourceReferenceService(b"f" * 32),
    ).create(
        content=content,
        memory_type=MemoryType.PREFERENCE,
        source=MemorySource.MANUAL,
        source_session_id=session_id,
        importance=3,
        confidence=0.9,
        metadata={"secret_note": "PRIVATE_METADATA"},
    )[0]


def test_true_forget_delete_head_preserves_only_explicit_classification(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'classified-delete.db'}") as connection:
        memory = MemoryRepository(connection).create(
            content="小雪",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            canonical_subject_code="preferred_address",
        )[0]

        _service(connection).forget_memory(memory.id)

        versions = VersionedMemoryRepository(connection).list_versions(
            memory.id,
            limit=10,
        ).items
        assert versions[0].operation is MemoryVersionOperation.DELETE
        assert versions[0].canonical_subject_code == "preferred_address"
        assert all(version.content is None for version in versions)


def test_single_forget_appends_delete_head_redacts_payload_and_removes_embedding(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'single.db'}") as connection:
        _seed_session(connection)
        memory = _create_formal(connection)
        state = VersionedMemoryRepository(connection).get_state(memory.id)
        assert state is not None
        connection.execute("DROP TRIGGER trg_memory_versions_append_only_update")
        connection.execute(
            """
            UPDATE memory_versions
            SET canonical_key_hash = 'old-exact', subject_key_hash = 'old-subject'
            WHERE id = ?
            """,
            (state.current_version_id,),
        )
        connection.execute(
            """
            UPDATE memory_record_states
            SET canonical_key_hash = 'old-exact', subject_key_hash = 'old-subject'
            WHERE memory_id = ?
            """,
            (memory.id,),
        )
        connection.execute(
            "INSERT INTO memory_embeddings VALUES (?, 'fake', 'm', 1, '[1]', 'h', ?, ?)",
            (memory.id, _NOW.isoformat(), _NOW.isoformat()),
        )
        connection.commit()

        result = _service(connection).forget_memory(memory.id)
        state = VersionedMemoryRepository(connection).get_state(memory.id)
        versions = VersionedMemoryRepository(connection).list_versions(
            memory.id, limit=20
        ).items
        projection = connection.execute(
            "SELECT * FROM memories WHERE id = ?", (memory.id,)
        ).fetchone()

        assert result.forgotten_memory_ids == (memory.id,)
        assert state is not None and state.state.value == "deleted"
        assert versions[0].operation is MemoryVersionOperation.DELETE
        assert versions[0].subject is None and versions[0].content is None
        assert versions[0].canonical_subject_code is None
        assert all(version.subject is None and version.content is None for version in versions)
        assert all(version.redacted_at is not None for version in versions)
        assert projection["content"] == "" and projection["status"] == "archived"
        assert "PRIVATE_METADATA" not in projection["metadata_json"]
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_embeddings WHERE memory_id = ?", (memory.id,)
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_tombstones WHERE source_memory_id = ?",
            (memory.id,),
        ).fetchone()[0] == 1
        assert connection.execute("SELECT generation FROM memory_summary_barrier").fetchone()[0] == 1
        assert "private payload" not in "\n".join(
            str(value)
            for row in connection.execute("SELECT * FROM memories").fetchall()
            for value in row
        )
        second = _service(connection).forget_memory(memory.id)
        assert second.forgotten_memory_ids == ()
        assert connection.execute("SELECT generation FROM memory_summary_barrier").fetchone()[0] == 1


def test_forget_tombstones_all_historical_canonical_identities(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'history.db'}") as connection:
        _seed_session(connection)
        memories = MemoryRepository(
            connection,
            source_references=MemorySourceReferenceService(b"f" * 32),
        )
        memory = _create_formal(connection, content="version one")
        memories.update(memory.id, content="version two")
        versions = connection.execute(
            "SELECT id, version_number FROM memory_versions WHERE memory_id = ?",
            (memory.id,),
        ).fetchall()
        connection.execute("DROP TRIGGER trg_memory_versions_append_only_update")
        for row in versions:
            connection.execute(
                "UPDATE memory_versions SET canonical_key_hash = ?, subject_key_hash = ? WHERE id = ?",
                (f"exact-{row['version_number']}", f"subject-{row['version_number']}", row["id"]),
            )
        connection.commit()

        _service(connection).forget_memory(memory.id)

        tombstones = connection.execute(
            "SELECT canonical_key_hash, subject_key_hash FROM memory_tombstones "
            "WHERE source_memory_id = ? ORDER BY canonical_key_hash",
            (memory.id,),
        ).fetchall()
        assert [tuple(row) for row in tombstones] == [
            ("exact-1", "subject-1"),
            ("exact-2", "subject-2"),
        ]


def test_session_scope_redacts_formal_candidate_and_excludes_all_messages(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'session.db'}") as connection:
        _seed_session(connection)
        formal = _create_formal(connection)
        candidate, _ = MemoryRepository(connection).create_candidate(
            content="candidate payload",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source_session_id="session-1",
            importance=3,
            confidence=0.8,
            metadata={"source_quote": "SOURCE_QUOTE_SENTINEL"},
        )
        assert candidate is not None

        result = _service(connection).forget_scope(
            scope=MemoryDeletionScope.SESSION,
            scope_id="session-1",
        )

        candidate_row = connection.execute(
            "SELECT * FROM memories WHERE id = ?", (candidate.id,)
        ).fetchone()
        excluded = connection.execute(
            "SELECT source_message_id FROM memory_summary_source_exclusions ORDER BY 1"
        ).fetchall()
        assert result.forgotten_memory_ids == (formal.id,)
        assert result.forgotten_candidate_ids == (candidate.id,)
        assert candidate_row["content"] == ""
        assert candidate_row["status"] == MemoryStatus.DISMISSED.value
        assert "SOURCE_QUOTE_SENTINEL" not in candidate_row["metadata_json"]
        assert [row[0] for row in excluded] == [
            "session-1-assistant-1",
            "session-1-user-1",
            "session-1-user-2",
        ]
        generation = MemorySourceReferenceService(b"f" * 32).session_hash("session-1")
        assert connection.execute(
            "SELECT generation FROM memory_deletion_generations "
            "WHERE scope = 'session' AND scope_id = ?",
            (generation,),
        ).fetchone()[0] == 1
        repository = MemoryRepository(connection)
        with pytest.raises(MemoryCandidateForgottenError):
            repository.confirm_candidate(candidate.id)
        with pytest.raises(MemoryCandidateForgottenError):
            repository.dismiss_candidate(candidate.id)


def test_deleted_session_original_id_matches_hmac_only_candidate_provenance(
    tmp_path: Path,
) -> None:
    references = MemorySourceReferenceService(b"f" * 32)
    with managed_connection(
        f"sqlite:///{tmp_path / 'deleted-session-candidate.db'}"
    ) as connection:
        _seed_session(connection)
        candidate, _ = MemoryRepository(
            connection,
            source_references=references,
        ).create_candidate(
            content="candidate from deleted session",
            memory_type=MemoryType.USER_FACT,
            source_session_id="session-1",
            importance=3,
            confidence=0.9,
        )
        assert candidate is not None
        SessionDeletionCoordinator(
            connection,
            versioned=VersionedMemoryRepository(connection),
            source_references=references,
        ).delete("session-1")
        projection = connection.execute(
            "SELECT source_session_id, source_session_reference_hash "
            "FROM memories WHERE id = ?",
            (candidate.id,),
        ).fetchone()
        assert projection["source_session_id"] is None
        assert projection["source_session_reference_hash"] == references.session_hash(
            "session-1"
        )

        result = _service(connection).forget_scope(
            scope=MemoryDeletionScope.SESSION,
            scope_id="session-1",
        )

        assert result.forgotten_candidate_ids == (candidate.id,)
        forgotten = MemoryRepository(connection).require(candidate.id)
        assert forgotten.content == ""
        with pytest.raises(MemoryCandidateForgottenError):
            MemoryRepository(connection).confirm_candidate(candidate.id)


def test_direct_candidate_forget_without_subject_creates_content_tombstone(
    tmp_path: Path,
) -> None:
    with managed_connection(
        f"sqlite:///{tmp_path / 'candidate-content-tombstone.db'}"
    ) as connection:
        _seed_session(connection)
        candidate, _ = MemoryRepository(connection).create_candidate(
            content="用户偏好红茶",
            memory_type=MemoryType.PREFERENCE,
            source_session_id="session-1",
            importance=3,
            confidence=0.9,
        )
        assert candidate is not None

        result = _service(connection).forget_memory(candidate.id)

        tombstone = connection.execute(
            "SELECT canonical_key_hash, subject_key_hash, content_key_hash "
            "FROM memory_tombstones WHERE source_memory_id = ?",
            (candidate.id,),
        ).fetchone()
        assert result.deletion_generation == 1
        assert tombstone is not None
        assert tombstone["canonical_key_hash"] is None
        assert tombstone["subject_key_hash"] is None
        assert tombstone["content_key_hash"] is not None
        canonical = canonicalize_memory_v1(
            memory_type=MemoryType.PREFERENCE,
            subject="饮品偏好",
            content="用户偏好红茶",
        )
        match = VersionedMemoryRepository(connection).find_tombstone(
            memory_type=MemoryType.PREFERENCE,
            canonical_key_hash=canonical.canonical_key_hash,
            subject_key_hash=canonical.subject_key_hash,
            content_key_hash=canonical.content_key_hash,
            canonicalization_version=canonical.canonicalization_version,
        )
        assert match is not None and match.matched_by == "normalized_content"

        from app.domain.models import (
            MemoryEvidenceExtractorKind,
            MemoryGovernorProposal,
        )
        from app.repositories.versioned_memories import DeletionGenerationSnapshot
        from app.services.memory_commit_policy import MemoryCommitPolicy
        from app.services.memory_gate_b_contract import MEMORY_ALLOWED_AUTO_TYPES
        from app.services.memory_governor import MemoryGovernor
        from app.services.versioned_memory_commit import (
            VersionedMemoryCommitRequest,
            VersionedMemoryCommitService,
            WriteAuthoritySnapshot,
        )

        connection.execute(
            """
            INSERT INTO memory_write_consents (
                scope_id, status, purpose, policy_version,
                allowed_memory_types_version, allowed_memory_types_json,
                retention_disclosure_version, generation, granted_at,
                created_at, updated_at
            ) VALUES ('default', 'granted',
                'write Governor-approved durable memories to local active storage',
                'memory-auto-write-policy-v1', 'memory-auto-write-types-v1',
                '["user_fact","preference","long_term_goal","important_event","relationship_event","other"]',
                'memory-auto-write-retention-v1', 1, ?, ?, ?)
            """,
            (_NOW.isoformat(), _NOW.isoformat(), _NOW.isoformat()),
        )
        connection.execute(
            """
            INSERT INTO memory_jobs (
                id, turn_id, schema_version, session_id, user_message_id,
                assistant_message_id, mode, extractor_route, status,
                governor_version, created_at
            ) VALUES ('candidate-revival-job', 'session-1-assistant-1',
                'memory-shadow-schema-v1', 'session-1', 'session-1-user-1',
                'session-1-assistant-1', 'shadow_auto', 'local', 'pending',
                'memory-governor-rules-v1', ?)
            """,
            (_NOW.isoformat(),),
        )
        connection.commit()
        proposal = MemoryGovernorProposal(
            memory_type=MemoryType.PREFERENCE,
            subject="饮品偏好",
            content="用户偏好红茶",
            canonical_key_hint=None,
            confidence=0.9,
            source_message_ids=("session-1-user-1",),
        )
        governor = MemoryGovernor(
            max_proposals=5,
            max_proposal_characters=300,
            max_total_characters=1000,
        )
        commit_result = VersionedMemoryCommitService(
            connection,
            versioned=VersionedMemoryRepository(connection),
            policy=MemoryCommitPolicy(),
            source_references=MemorySourceReferenceService(b"f" * 32),
        ).commit_one(
            VersionedMemoryCommitRequest(
                job_id="candidate-revival-job",
                turn_id="session-1-assistant-1",
                proposal_index=0,
                proposal=proposal,
                governor_result=governor.evaluate(
                    proposal=proposal,
                    user_text="我的饮品偏好是红茶。",
                    user_message_id="session-1-user-1",
                    assistant_message_id="session-1-assistant-1",
                ),
                session_id="session-1",
                user_message_id="session-1-user-1",
                user_text="我的饮品偏好是红茶。",
                extractor_kind=MemoryEvidenceExtractorKind.LOCAL,
                provider_identifier="local",
                model_identifier="memory-local-rules-v1",
                authority=WriteAuthoritySnapshot(
                    write_consent_generation=1,
                    remote_consent_generation=None,
                    remote_authority_fingerprint=None,
                ),
                deletion_snapshot=DeletionGenerationSnapshot(
                    global_generation=0,
                    session_generation=0,
                    type_generations={
                        item: (
                            result.deletion_generation
                            if item is MemoryType.PREFERENCE
                            else 0
                        )
                        for item in MEMORY_ALLOWED_AUTO_TYPES
                    },
                ),
            )
        )
        assert commit_result.outcome.value == "skipped_tombstone"
        assert connection.execute(
            "SELECT COUNT(*) FROM memories WHERE content = '用户偏好红茶' "
            "AND status = 'active'"
        ).fetchone()[0] == 0


def test_direct_candidate_forget_creates_exact_tombstone(tmp_path: Path) -> None:
    with managed_connection(
        f"sqlite:///{tmp_path / 'candidate-tombstone.db'}"
    ) as connection:
        _seed_session(connection)
        candidate, _ = MemoryRepository(connection).create_candidate(
            content="用户住在海边城市",
            memory_type=MemoryType.USER_FACT,
            source_session_id="session-1",
            importance=3,
            confidence=0.9,
            metadata={"canonical_subject": "居住地"},
        )
        assert candidate is not None

        result = _service(connection).forget_memory(candidate.id)

        tombstones = connection.execute(
            "SELECT canonical_key_hash, subject_key_hash, content_key_hash, "
            "delete_generation FROM memory_tombstones WHERE source_memory_id = ?",
            (candidate.id,),
        ).fetchall()
        assert result.forgotten_candidate_ids == (candidate.id,)
        assert result.deletion_generation == 1
        assert len(tombstones) == 1
        assert tombstones[0]["canonical_key_hash"] is not None
        assert tombstones[0]["subject_key_hash"] is not None
        assert tombstones[0]["content_key_hash"] is not None
        assert tombstones[0]["delete_generation"] == 1
        canonical = canonicalize_memory_v1(
            memory_type=MemoryType.USER_FACT,
            subject="其他主题",
            content="用户住在海边城市",
        )
        match = VersionedMemoryRepository(connection).find_tombstone(
            memory_type=MemoryType.USER_FACT,
            canonical_key_hash=canonical.canonical_key_hash,
            subject_key_hash=canonical.subject_key_hash,
            content_key_hash=canonical.content_key_hash,
            canonicalization_version=canonical.canonicalization_version,
        )
        assert match is not None and match.matched_by == "normalized_content"


def test_deleted_session_original_id_matches_hmac_only_provenance(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'deleted-session.db'}") as connection:
        memory = MemoryRepository(
            connection,
            source_references=MemorySourceReferenceService(b"f" * 32),
        ).create(
            content="payload from deleted session",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=0.9,
        )[0]
        state = VersionedMemoryRepository(connection).get_state(memory.id)
        assert state is not None
        digest = MemorySourceReferenceService(b"f" * 32).session_hash("deleted-session")
        connection.execute("DROP TRIGGER trg_memory_versions_append_only_update")
        connection.execute(
            "UPDATE memory_versions SET source_session_reference_hash = ? WHERE memory_id = ?",
            (digest, memory.id),
        )
        connection.commit()

        result = _service(connection).forget_scope(
            scope=MemoryDeletionScope.SESSION,
            scope_id="deleted-session",
        )
        assert result.forgotten_memory_ids == (memory.id,)
        assert digest not in repr(result)


def test_forget_redacts_existing_audit_metadata_and_records_metadata_only_delete(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'audit.db'}") as connection:
        _seed_session(connection)
        memory = _create_formal(connection)
        other = _create_formal(connection, content="other")
        MemoryAuditRepository(connection).record_conflict(
            memory_id=other.id,
            related_memory_ids=[memory.id],
            operation=MemoryAuditOperation.CREATE,
            metadata={"nested": {"secret": "AUDIT_SECRET_SENTINEL"}},
        )

        _service(connection).forget_memory(memory.id)

        rows = connection.execute(
            "SELECT event_type, operation, metadata_json FROM memory_audit_events ORDER BY created_at"
        ).fetchall()
        assert "AUDIT_SECRET_SENTINEL" not in "".join(row["metadata_json"] for row in rows)
        assert all("memory_true_forget" in row["metadata_json"] for row in rows)
        deleted = [row for row in rows if row["event_type"] == "memory_deleted"]
        assert len(deleted) == 1
        assert deleted[0]["operation"] == "forget"


def test_forget_closes_open_conflict_and_restores_surviving_side(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'conflict.db'}") as connection:
        _seed_session(connection)
        left = _create_formal(connection, content="left")
        right = _create_formal(connection, content="right")
        left_id, right_id = sorted((left.id, right.id))
        connection.execute(
            "UPDATE memory_record_states SET state = 'conflicted' WHERE memory_id IN (?, ?)",
            (left.id, right.id),
        )
        connection.execute(
            "INSERT INTO memory_conflicts VALUES ('conflict-1', ?, ?, 'open', NULL, NULL, ?, NULL)",
            (left_id, right_id, _NOW.isoformat()),
        )
        connection.commit()

        _service(connection).forget_memory(left.id)

        conflict = connection.execute(
            "SELECT * FROM memory_conflicts WHERE conflict_id = 'conflict-1'"
        ).fetchone()
        survivor = right.id
        survivor_state = VersionedMemoryRepository(connection).get_state(survivor)
        assert conflict["status"] == "resolved"
        assert conflict["resolution_kind"] in {"forget_left", "forget_right"}
        assert conflict["resolved_memory_id"] == survivor
        assert survivor_state is not None and survivor_state.state.value == "active"


def test_type_scope_selects_identity_by_historical_version_type(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'historical-type.db'}") as connection:
        _seed_session(connection)
        repository = MemoryRepository(
            connection,
            source_references=MemorySourceReferenceService(b"f" * 32),
        )
        memory = _create_formal(connection, content="old preference")
        repository.update(
            memory.id,
            content="current fact",
            memory_type=MemoryType.USER_FACT,
        )

        result = _service(connection).forget_scope(
            scope=MemoryDeletionScope.MEMORY_TYPE,
            scope_id=MemoryType.PREFERENCE.value,
        )

        assert result.forgotten_memory_ids == (memory.id,)
        assert VersionedMemoryRepository(connection).get_state(memory.id).state.value == "deleted"


def test_candidate_forget_removes_embedding(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'candidate-embedding.db'}") as connection:
        _seed_session(connection)
        candidate, _ = MemoryRepository(connection).create_candidate(
            content="candidate vector payload",
            memory_type=MemoryType.PREFERENCE,
            source_session_id="session-1",
            importance=3,
            confidence=0.8,
        )
        assert candidate is not None
        connection.execute(
            "INSERT INTO memory_embeddings VALUES (?, 'fake', 'm', 1, '[1]', 'h', ?, ?)",
            (candidate.id, _NOW.isoformat(), _NOW.isoformat()),
        )
        connection.commit()

        _service(connection).forget_scope(
            scope=MemoryDeletionScope.SESSION,
            scope_id="session-1",
        )

        assert connection.execute(
            "SELECT COUNT(*) FROM memory_embeddings WHERE memory_id = ?",
            (candidate.id,),
        ).fetchone()[0] == 0


def test_delayed_embedding_upsert_cannot_recreate_after_forget(tmp_path: Path) -> None:
    from app.repositories.memory_embeddings import MemoryEmbeddingRepository

    with managed_connection(f"sqlite:///{tmp_path / 'late-embedding.db'}") as connection:
        _seed_session(connection)
        memory = _create_formal(connection)
        delayed_vector = [0.25, 0.75]
        _service(connection).forget_memory(memory.id)

        MemoryEmbeddingRepository(connection).upsert(
            memory.id,
            "fake",
            "m",
            delayed_vector,
            "pre-forget-content-hash",
        )

        assert MemoryEmbeddingRepository(connection).get(memory.id) is None


def test_memory_type_forget_blocks_stale_commit_snapshot(tmp_path: Path) -> None:
    from app.domain.models import MemoryEvidenceExtractorKind, MemoryGovernorProposal
    from app.repositories.versioned_memories import DeletionGenerationSnapshot
    from app.services.memory_commit_policy import MemoryCommitPolicy
    from app.services.memory_gate_b_contract import MEMORY_ALLOWED_AUTO_TYPES
    from app.services.memory_governor import MemoryGovernor
    from app.services.versioned_memory_commit import (
        VersionedMemoryCommitRequest,
        VersionedMemoryCommitService,
        WriteAuthoritySnapshot,
    )

    with managed_connection(f"sqlite:///{tmp_path / 'stale-commit.db'}") as connection:
        _seed_session(connection)
        memory = _create_formal(connection)
        connection.execute(
            """
            INSERT INTO memory_write_consents (
                scope_id, status, purpose, policy_version,
                allowed_memory_types_version, allowed_memory_types_json,
                retention_disclosure_version, generation, granted_at,
                created_at, updated_at
            ) VALUES ('default', 'granted',
                'write Governor-approved durable memories to local active storage',
                'memory-auto-write-policy-v1', 'memory-auto-write-types-v1',
                '["user_fact","preference","long_term_goal","important_event","relationship_event","other"]',
                'memory-auto-write-retention-v1', 1, ?, ?, ?)
            """,
            (_NOW.isoformat(), _NOW.isoformat(), _NOW.isoformat()),
        )
        connection.execute(
            """
            INSERT INTO memory_jobs (
                id, turn_id, schema_version, session_id, user_message_id,
                assistant_message_id, mode, extractor_route, status,
                governor_version, created_at
            ) VALUES ('job-stale', 'session-1-assistant-1', 'memory-shadow-schema-v1',
                'session-1', 'session-1-user-1', 'session-1-assistant-1',
                'shadow_auto', 'local', 'pending', 'memory-governor-rules-v1', ?)
            """,
            (_NOW.isoformat(),),
        )
        connection.commit()
        _service(connection).forget_memory(memory.id)
        proposal = MemoryGovernorProposal(
            memory_type=MemoryType.PREFERENCE,
            subject="偏好",
            content="用户喜欢红茶",
            canonical_key_hint=None,
            confidence=0.9,
            source_message_ids=("session-1-user-1",),
        )
        governor = MemoryGovernor(
            max_proposals=5,
            max_proposal_characters=300,
            max_total_characters=1000,
        )
        result = VersionedMemoryCommitService(
            connection,
            versioned=VersionedMemoryRepository(connection),
            policy=MemoryCommitPolicy(),
            source_references=MemorySourceReferenceService(b"f" * 32),
        ).commit_one(
            VersionedMemoryCommitRequest(
                job_id="job-stale",
                turn_id="session-1-assistant-1",
                proposal_index=0,
                proposal=proposal,
                governor_result=governor.evaluate(
                    proposal=proposal,
                    user_text="我喜欢红茶。",
                    user_message_id="session-1-user-1",
                    assistant_message_id="session-1-assistant-1",
                ),
                session_id="session-1",
                user_message_id="session-1-user-1",
                user_text="我喜欢红茶。",
                extractor_kind=MemoryEvidenceExtractorKind.LOCAL,
                provider_identifier="local",
                model_identifier="memory-local-rules-v1",
                authority=WriteAuthoritySnapshot(
                    write_consent_generation=1,
                    remote_consent_generation=None,
                    remote_authority_fingerprint=None,
                ),
                deletion_snapshot=DeletionGenerationSnapshot(
                    global_generation=0,
                    session_generation=0,
                    type_generations={item: 0 for item in MEMORY_ALLOWED_AUTO_TYPES},
                ),
            )
        )
        assert result.outcome.value == "skipped_deletion_barrier"


@pytest.mark.parametrize(
    "checkpoint",
    [
        "generation",
        "tombstones",
        "delete_head",
        "state_head",
        "projection",
        "versions",
        "embedding",
        "audits",
        "summary_barrier",
        "delete_activity",
    ],
)
def test_fault_injection_rolls_back_entire_forget(
    tmp_path: Path,
    checkpoint: str,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / f'rollback-{checkpoint}.db'}") as connection:
        _seed_session(connection)
        memory = _create_formal(connection)
        state_before = VersionedMemoryRepository(connection).get_state(memory.id)
        projection_before = tuple(
            connection.execute("SELECT * FROM memories WHERE id = ?", (memory.id,)).fetchone()
        )

        def fail(name: str) -> None:
            if name == checkpoint:
                raise RuntimeError("fault")

        with pytest.raises(RuntimeError, match="fault"):
            _service(connection, fault_injector=fail).forget_memory(memory.id)

        state_after = VersionedMemoryRepository(connection).get_state(memory.id)
        projection_after = tuple(
            connection.execute("SELECT * FROM memories WHERE id = ?", (memory.id,)).fetchone()
        )
        assert state_after == state_before
        assert projection_after == projection_before
        assert connection.execute("SELECT COUNT(*) FROM memory_tombstones").fetchone()[0] == 0
        assert connection.execute("SELECT generation FROM memory_summary_barrier").fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_versions WHERE memory_id = ?", (memory.id,)
        ).fetchone()[0] == 1
