from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import MemoryConflictStaleError
from app.domain.models import (
    MemoryConflictResolutionKind,
    MemorySource,
    MemoryType,
)
from app.repositories.memories import MemoryRepository
from app.repositories.sqlite import managed_connection
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.services.memory_conflict_resolution import (
    ConflictResolutionPayload,
    MemoryConflictResolutionService,
)
from app.services.memory_forget_service import MemoryForgetService
from app.services.memory_source_reference import MemorySourceReferenceService


@pytest.fixture
def environment(tmp_path: Path):
    with managed_connection(f"sqlite:///{tmp_path / 'resolve.db'}") as connection:
        references = MemorySourceReferenceService(b"q" * 32)
        memories = MemoryRepository(connection, source_references=references)
        versioned = VersionedMemoryRepository(connection)
        forget = MemoryForgetService(
            connection,
            versioned=versioned,
            source_references=references,
        )
        yield connection, memories, versioned, references, forget


def _seed_conflict(connection, memories, versioned):
    left, _ = memories.create(
        content="用户喜欢红茶",
        memory_type=MemoryType.PREFERENCE,
        source=MemorySource.MANUAL,
        source_session_id=None,
        importance=4,
        confidence=0.9,
    )
    right, _ = memories.create(
        content="用户不喜欢红茶",
        memory_type=MemoryType.PREFERENCE,
        source=MemorySource.MANUAL,
        source_session_id=None,
        importance=3,
        confidence=0.8,
    )
    left_state = versioned.bootstrap_legacy(left.id)
    right_state = versioned.bootstrap_legacy(right.id)
    connection.execute(
        "UPDATE memory_record_states SET state = 'conflicted' WHERE memory_id IN (?, ?)",
        (left.id, right.id),
    )
    connection.execute(
        "INSERT INTO memory_conflicts "
        "(conflict_id, left_memory_id, right_memory_id, status, created_at) "
        "VALUES ('conflict-1', ?, ?, 'open', '2026-07-21T00:00:00+00:00')",
        tuple(sorted((left.id, right.id))),
    )
    connection.commit()
    assert left_state.current_version_id and right_state.current_version_id
    return left, right


def _service(connection, memories, versioned, references, forget, *, fault=None):
    return MemoryConflictResolutionService(
        connection,
        versioned=versioned,
        memories=memories,
        forget=forget,
        source_references=references,
        fault_injector=fault,
    )


def test_replacement_resolution_persists_explicit_subject_code(environment) -> None:
    connection, memories, versioned, references, forget = environment
    _seed_conflict(connection, memories, versioned)

    result = _service(connection, memories, versioned, references, forget).resolve(
        "conflict-1",
        ConflictResolutionPayload(
            kind=MemoryConflictResolutionKind.REPLACE_BOTH,
            content="小雪",
            memory_type=MemoryType.PREFERENCE,
            subject="称呼",
            importance=3,
            confidence=0.95,
            canonical_subject_code="preferred_address",
        ),
    )

    assert result.resolved_memory is not None
    head = versioned.get_current_version(result.resolved_memory.id)
    assert head is not None
    assert head.canonical_subject_code == "preferred_address"
    assert result.resolved_memory.canonical_subject_code == "preferred_address"


@pytest.mark.parametrize(
    "kind",
    [
        MemoryConflictResolutionKind.CHOOSE_LEFT,
        MemoryConflictResolutionKind.CHOOSE_RIGHT,
        MemoryConflictResolutionKind.REPLACE_BOTH,
        MemoryConflictResolutionKind.BOTH_CONTEXTUAL,
        MemoryConflictResolutionKind.DISMISS_BOTH,
    ],
)
def test_all_user_resolution_kinds_are_atomic_and_archive_both_sides(
    environment,
    kind,
) -> None:
    connection, memories, versioned, references, forget = environment
    left, right = _seed_conflict(connection, memories, versioned)
    replacement = kind in {
        MemoryConflictResolutionKind.REPLACE_BOTH,
        MemoryConflictResolutionKind.BOTH_CONTEXTUAL,
    }
    result = _service(connection, memories, versioned, references, forget).resolve(
        "conflict-1",
        ConflictResolutionPayload(
            kind=kind,
            content="用户现在在工作时喜欢红茶" if replacement else None,
            memory_type=MemoryType.PREFERENCE if replacement else None,
            subject="现在工作时的饮品偏好" if replacement else None,
            importance=3,
            confidence=0.95,
        ),
    )

    assert result.conflict.status.value == "resolved"
    assert result.conflict.resolution_kind is kind
    assert memories.require(left.id).status.value == "archived"
    assert memories.require(right.id).status.value == "archived"
    if kind is MemoryConflictResolutionKind.DISMISS_BOTH:
        assert result.resolved_memory is None
        assert result.conflict.resolved_memory_id is None
    else:
        assert result.resolved_memory is not None
        assert result.resolved_memory.id not in {left.id, right.id}
        assert result.resolved_memory.status.value == "active"
        head = versioned.get_current_version(result.resolved_memory.id)
        assert head is not None and head.operation.value == "conflict_resolution"
    assert connection.execute(
        "SELECT COUNT(*) FROM memory_evidence"
    ).fetchone()[0] == 0
    audit = connection.execute(
        "SELECT event_type, operation, metadata_json FROM memory_audit_events "
        "WHERE event_type = 'conflict_resolved'"
    ).fetchone()
    assert audit is not None
    assert audit["operation"] == "resolve_conflict"
    assert "用户喜欢红茶" not in audit["metadata_json"]
    assert "用户不喜欢红茶" not in audit["metadata_json"]


@pytest.mark.parametrize(
    "checkpoint",
    ["resolved_identity", "left_archived", "right_archived", "conflict_closed", "audit"],
)
def test_resolution_faults_roll_back_every_mutation(environment, checkpoint) -> None:
    connection, memories, versioned, references, forget = environment
    left, right = _seed_conflict(connection, memories, versioned)
    before = connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    def fail(name: str) -> None:
        if name == checkpoint:
            raise RuntimeError(name)

    with pytest.raises(RuntimeError, match=checkpoint):
        _service(
            connection,
            memories,
            versioned,
            references,
            forget,
            fault=fail,
        ).resolve(
            "conflict-1",
            ConflictResolutionPayload(kind=MemoryConflictResolutionKind.CHOOSE_LEFT),
        )

    assert connection.execute("SELECT status FROM memory_conflicts").fetchone()[0] == "open"
    assert memories.require(left.id).status.value == "active"
    assert memories.require(right.id).status.value == "active"
    assert connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == before


def test_resolving_already_resolved_conflict_is_stale(environment) -> None:
    connection, memories, versioned, references, forget = environment
    _seed_conflict(connection, memories, versioned)
    service = _service(connection, memories, versioned, references, forget)
    service.resolve(
        "conflict-1",
        ConflictResolutionPayload(kind=MemoryConflictResolutionKind.DISMISS_BOTH),
    )
    with pytest.raises(MemoryConflictStaleError):
        service.resolve(
            "conflict-1",
            ConflictResolutionPayload(kind=MemoryConflictResolutionKind.DISMISS_BOTH),
        )
