from pathlib import Path

import pytest

from app.core.errors import MemoryConflictRequiresResolutionError
from app.domain.models import (
    MemoryRecordState,
    MemorySource,
    MemoryStatus,
    MemoryType,
    MemoryVersionOperation,
    MemoryVersionSourceKind,
)
from app.repositories.memories import MemoryRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.services.memory_source_reference import MemorySourceReferenceService
from app.services.versioned_memory_mutation import VersionedMemoryMutationService


def _service(connection, *, source_references=None):
    return VersionedMemoryMutationService(
        connection,
        memories=MemoryRepository(connection),
        versioned=VersionedMemoryRepository(connection),
        source_references=source_references,
    )


def _insert_legacy_projection(
    connection,
    *,
    memory_id: str,
    content: str,
    source_session_id: str | None = None,
):
    connection.execute(
        """
        INSERT INTO memories (
            id, content, memory_type, source, source_session_id,
            importance, confidence, status, metadata_json, created_at, updated_at
        ) VALUES (?, ?, 'other', 'manual', ?, 2, 0.7, 'active', '{}',
                  '2026-07-20T00:00:00+00:00',
                  '2026-07-20T00:00:00+00:00')
        """,
        (memory_id, content, source_session_id),
    )
    connection.commit()
    return MemoryRepository(connection).require(memory_id)


def test_manual_create_writes_projection_root_version_and_state_atomically(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'manual-create.db'}") as connection:
        memory, conflicts = _service(connection).create_manual(
            content="用户偏好中文回复。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={"visible": True},
            canonical_subject_code="preferred_address",
        )
        state = VersionedMemoryRepository(connection).get_state(memory.id)
        version = VersionedMemoryRepository(connection).get_current_version(memory.id)

        assert conflicts == []
        assert memory.source is MemorySource.MANUAL
        assert state is not None and state.state is MemoryRecordState.ACTIVE
        assert state.head_version == 1 and state.record_generation == 0
        assert state.source_kind is MemoryVersionSourceKind.MANUAL
        assert version is not None
        assert version.operation is MemoryVersionOperation.CREATE
        assert version.source_kind is MemoryVersionSourceKind.MANUAL
        assert version.content == memory.content
        assert version.subject is None
        assert version.canonical_subject_code == "preferred_address"
        assert memory.canonical_subject_code == "preferred_address"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_manual_create_rolls_back_projection_when_version_insert_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'rollback-create.db'}") as connection:
        versioned = VersionedMemoryRepository(connection)
        service = VersionedMemoryMutationService(
            connection,
            memories=MemoryRepository(connection),
            versioned=versioned,
        )

        def fail_version(*_args, **_kwargs):
            raise RuntimeError("injected version failure")

        monkeypatch.setattr(service.primitive, "insert_root", fail_version)
        with pytest.raises(RuntimeError, match="injected version failure"):
            service.create_manual(
                content="must roll back",
                memory_type=MemoryType.OTHER,
                source_session_id=None,
                importance=3,
                confidence=1.0,
            )

        assert connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM memory_versions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM memory_record_states").fetchone()[0] == 0


def test_conflict_audit_rolls_back_with_failed_manual_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'audit-rollback.db'}") as connection:
        service = _service(connection)
        existing, _ = service.create_manual(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=1.0,
        )
        original = service.primitive.record_conflict_audit

        def record_then_fail(**kwargs):
            original(**kwargs)
            raise RuntimeError("injected audit failure")

        monkeypatch.setattr(service.primitive, "record_conflict_audit", record_then_fail)
        with pytest.raises(RuntimeError, match="injected audit failure"):
            service.create_manual(
                content=" 用户喜欢红茶。 ",
                memory_type=MemoryType.PREFERENCE,
                source_session_id=None,
                importance=2,
                confidence=0.8,
            )

        assert [memory.id for memory in MemoryRepository(connection).list()] == [existing.id]
        assert connection.execute("SELECT COUNT(*) FROM memory_audit_events").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM memory_versions").fetchone()[0] == 1


def test_patch_bootstraps_legacy_and_appends_user_edit_version(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'patch.db'}") as connection:
        legacy = _insert_legacy_projection(
            connection,
            memory_id="legacy-patch",
            content="旧正文",
        )
        memory, conflicts = _service(connection).update(
            legacy.id,
            content="新正文",
            memory_type=None,
            importance=4,
            confidence=0.9,
            metadata={"edited": True},
        )
        state = VersionedMemoryRepository(connection).get_state(legacy.id)
        versions = VersionedMemoryRepository(connection).list_versions(legacy.id, limit=10)

        assert conflicts == []
        assert memory.content == "新正文"
        assert state is not None and state.head_version == 2
        assert state.record_generation == 1
        assert state.source_kind is MemoryVersionSourceKind.USER_EDIT
        assert [version.operation for version in versions.items] == [
            MemoryVersionOperation.USER_EDIT,
            MemoryVersionOperation.BOOTSTRAP,
        ]
        assert versions.items[0].parent_version_id == versions.items[1].id
        assert all(
            version.canonical_subject_code is None for version in versions.items
        )


def test_explicit_update_set_clear_and_omission_preserve_subject_code(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'subject-update.db'}") as connection:
        service = _service(connection)
        memory, _ = service.create_manual(
            content="小雪",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            canonical_subject_code="preferred_address",
        )

        service.update(
            memory.id,
            content="小雪",
            memory_type=None,
            importance=4,
            confidence=None,
            metadata=None,
        )
        preserved = VersionedMemoryRepository(connection).get_current_version(memory.id)
        assert preserved is not None
        assert preserved.canonical_subject_code == "preferred_address"

        service.update(
            memory.id,
            content="普通偏好",
            memory_type=None,
            importance=None,
            confidence=None,
            metadata=None,
            canonical_subject_code=None,
            canonical_subject_code_provided=True,
        )
        cleared = VersionedMemoryRepository(connection).get_current_version(memory.id)
        assert cleared is not None
        assert cleared.canonical_subject_code is None

        service.update(
            memory.id,
            content="小雪",
            memory_type=None,
            importance=None,
            confidence=None,
            metadata=None,
            canonical_subject_code="preferred_address",
            canonical_subject_code_provided=True,
        )
        restored = VersionedMemoryRepository(connection).get_current_version(memory.id)
        assert restored is not None
        assert restored.canonical_subject_code == "preferred_address"
        assert MemoryRepository(connection).require(memory.id).canonical_subject_code == (
            "preferred_address"
        )


def test_changing_memory_type_revalidates_preserved_subject_code(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'subject-type.db'}") as connection:
        service = _service(connection)
        memory, _ = service.create_manual(
            content="小雪",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            canonical_subject_code="preferred_address",
        )

        with pytest.raises(ValueError, match="not allowed"):
            service.update(
                memory.id,
                content=None,
                memory_type=MemoryType.OTHER,
                importance=None,
                confidence=None,
                metadata=None,
            )


def test_candidate_confirmation_explicit_classification_and_default_uncoded(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'subject-confirm.db'}") as connection:
        memories = MemoryRepository(connection)
        first, _ = memories.create_candidate(
            content="小雪",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=0.9,
        )
        assert first is not None
        _service(connection).confirm_candidate(
            first.id,
            canonical_subject_code="preferred_address",
        )
        first_version = VersionedMemoryRepository(connection).get_current_version(first.id)
        assert first_version is not None
        assert first_version.canonical_subject_code == "preferred_address"

        second, _ = memories.create_candidate(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=0.9,
        )
        assert second is not None
        _service(connection).confirm_candidate(second.id)
        second_version = VersionedMemoryRepository(connection).get_current_version(second.id)
        assert second_version is not None
        assert second_version.canonical_subject_code is None


def test_legacy_bootstrap_records_hmac_only_session_provenance(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'bootstrap-source.db'}"
    source_references = MemorySourceReferenceService(b"s" * 32)
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("legacy source")
        legacy = _insert_legacy_projection(
            connection,
            memory_id="legacy-source",
            content="旧正文",
            source_session_id=session.id,
        )

        _service(connection, source_references=source_references).update(
            legacy.id,
            content="新正文",
            memory_type=None,
            importance=None,
            confidence=None,
            metadata=None,
        )

        versions = VersionedMemoryRepository(connection).list_versions(
            legacy.id,
            limit=10,
        )
        expected_hash = source_references.session_hash(session.id)
        assert len(versions.items) == 2
        assert all(
            version.source_session_reference_hash == expected_hash
            for version in versions.items
        )
        assert expected_hash != session.id


def test_patch_cas_failure_rolls_back_projection_and_new_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'stale-patch.db'}") as connection:
        service = _service(connection)
        memory, _ = service.create_manual(
            content="before",
            memory_type=MemoryType.OTHER,
            source_session_id=None,
            importance=3,
            confidence=1.0,
        )
        before = connection.execute("SELECT * FROM memories WHERE id = ?", (memory.id,)).fetchone()
        before_version_count = connection.execute(
            "SELECT COUNT(*) FROM memory_versions WHERE memory_id = ?", (memory.id,)
        ).fetchone()[0]
        monkeypatch.setattr(service.primitive, "compare_and_set_head", lambda **_kwargs: False)

        with pytest.raises(RuntimeError, match="stale memory head"):
            service.update(
                memory.id,
                content="after",
                memory_type=None,
                importance=None,
                confidence=None,
                metadata=None,
            )

        after = connection.execute("SELECT * FROM memories WHERE id = ?", (memory.id,)).fetchone()
        assert tuple(after) == tuple(before)
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_versions WHERE memory_id = ?", (memory.id,)
        ).fetchone()[0] == before_version_count


def test_candidate_confirmation_creates_first_state_and_candidate_version(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'confirm.db'}") as connection:
        candidate, _ = MemoryRepository(connection).create_candidate(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=0.9,
        )
        assert candidate is not None
        memory, conflicts = _service(connection).confirm_candidate(candidate.id)
        state = VersionedMemoryRepository(connection).get_state(candidate.id)
        version = VersionedMemoryRepository(connection).get_current_version(candidate.id)

        assert conflicts == []
        assert memory.status is MemoryStatus.ACTIVE
        assert state is not None and state.head_version == 1
        assert state.source_kind is MemoryVersionSourceKind.CANDIDATE
        assert version is not None and version.operation is MemoryVersionOperation.CREATE
        assert version.source_kind is MemoryVersionSourceKind.CANDIDATE
        assert connection.execute("SELECT COUNT(*) FROM memory_evidence").fetchone()[0] == 0


def test_candidate_conflict_keeps_pending_and_creates_no_v2_state(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'confirm-conflict.db'}") as connection:
        service = _service(connection)
        active, _ = service.create_manual(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=1.0,
        )
        candidate_id = "candidate-conflict"
        connection.execute(
            """
            INSERT INTO memories (
                id, content, memory_type, source, source_session_id,
                importance, confidence, status, metadata_json, created_at,
                updated_at
            ) VALUES (?, '用户喜欢红茶。', 'preference', 'candidate', NULL,
                      2, 0.8, 'pending', '{}',
                      '2026-07-20T00:00:00+00:00',
                      '2026-07-20T00:00:00+00:00')
            """,
            (candidate_id,),
        )
        connection.commit()
        candidate = MemoryRepository(connection).get(candidate_id)
        assert candidate is not None

        memory, conflicts = service.confirm_candidate(candidate.id)

        assert memory.status is MemoryStatus.PENDING
        assert [item.id for item in conflicts] == [active.id]
        assert VersionedMemoryRepository(connection).get_state(candidate.id) is None
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_versions WHERE memory_id = ?", (candidate.id,)
        ).fetchone()[0] == 0


def test_archive_appends_version_deletes_embedding_and_refuses_conflicted(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'archive.db'}") as connection:
        service = _service(connection)
        memory, _ = service.create_manual(
            content="archivable",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            canonical_subject_code="preferred_address",
        )
        connection.execute(
            """
            INSERT INTO memory_embeddings (
                memory_id, provider, model, dimension, embedding_json,
                content_hash, created_at, updated_at
            ) VALUES (?, 'fake', 'fake-v1', 2, '[1,0]', 'hash', 'created', 'updated')
            """,
            (memory.id,),
        )
        connection.commit()

        assert service.archive(memory.id) is True
        state = VersionedMemoryRepository(connection).get_state(memory.id)
        version = VersionedMemoryRepository(connection).get_current_version(memory.id)
        assert state is not None and state.state is MemoryRecordState.ARCHIVED
        assert state.head_version == 2
        assert version is not None and version.operation is MemoryVersionOperation.ARCHIVE
        assert version.canonical_subject_code == "preferred_address"
        assert state.canonical_key_hash == version.canonical_key_hash
        assert state.subject_key_hash == version.subject_key_hash
        assert MemoryRepository(connection).require(memory.id).status is MemoryStatus.ARCHIVED
        assert connection.execute(
            "SELECT 1 FROM memory_embeddings WHERE memory_id = ?", (memory.id,)
        ).fetchone() is None

        conflicted, _ = service.create_manual(
            content="conflicted",
            memory_type=MemoryType.OTHER,
            source_session_id=None,
            importance=3,
            confidence=1.0,
        )
        connection.execute(
            "UPDATE memory_record_states SET state = 'conflicted' WHERE memory_id = ?",
            (conflicted.id,),
        )
        connection.commit()
        with pytest.raises(MemoryConflictRequiresResolutionError):
            service.archive(conflicted.id)
        assert MemoryRepository(connection).require(conflicted.id).status is MemoryStatus.ACTIVE


def test_memory_repository_formal_facades_delegate_to_versioned_mutations(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'repository-facades.db'}") as connection:
        memories = MemoryRepository(connection)
        created, conflicts = memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
        )
        assert conflicts == []
        state = VersionedMemoryRepository(connection).get_state(created.id)
        assert state is not None and state.head_version == 1

        updated, _ = memories.update(created.id, content="用户喜欢咖啡。")
        assert updated.content == "用户喜欢咖啡。"
        state = VersionedMemoryRepository(connection).get_state(created.id)
        assert state is not None and state.head_version == 2

        candidate, _ = memories.create_candidate(
            content="用户偏好简洁回复。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=0.8,
        )
        assert candidate is not None
        confirmed, confirm_conflicts = memories.confirm_candidate(candidate.id)
        assert confirm_conflicts == []
        assert confirmed.status is MemoryStatus.ACTIVE
        candidate_state = VersionedMemoryRepository(connection).get_state(candidate.id)
        assert candidate_state is not None and candidate_state.head_version == 1

        assert memories.archive(created.id) is True
        archived_state = VersionedMemoryRepository(connection).get_state(created.id)
        assert archived_state is not None
        assert archived_state.state is MemoryRecordState.ARCHIVED
        assert archived_state.head_version == 3


def test_legacy_delete_compatibility_uses_archive_not_true_forget(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'delete-compat.db'}") as connection:
        memory, _ = MemoryRepository(connection).create(
            content="legacy",
            memory_type=MemoryType.OTHER,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
        )
        assert _service(connection).archive(memory.id) is True
        state = VersionedMemoryRepository(connection).get_state(memory.id)
        versions = VersionedMemoryRepository(connection).list_versions(memory.id, limit=10)

        assert state is not None and state.state is MemoryRecordState.ARCHIVED
        assert all(version.operation is not MemoryVersionOperation.DELETE for version in versions.items)
        assert connection.execute("SELECT COUNT(*) FROM memory_tombstones").fetchone()[0] == 0
