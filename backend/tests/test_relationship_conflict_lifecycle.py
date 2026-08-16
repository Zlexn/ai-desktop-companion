from __future__ import annotations

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

from tests.test_relationship_projector import _BASE_TIME


def _references() -> MemorySourceReferenceService:
    return MemorySourceReferenceService(b"q" * 32)


def _seed_conflict_with_subject(
    connection,
    memories,
    versioned,
    *,
    left_code: str = "shared_experience",
    right_code: str = "shared_experience",
    left_type: MemoryType = MemoryType.RELATIONSHIP_EVENT,
    right_type: MemoryType = MemoryType.RELATIONSHIP_EVENT,
) -> tuple[object, object]:
    left, _ = memories.create(
        content="一起赏雪",
        memory_type=left_type,
        source=MemorySource.MANUAL,
        source_session_id=None,
        importance=3,
        confidence=0.9,
        canonical_subject_code=left_code,
    )
    right, _ = memories.create(
        content="一起看海",
        memory_type=right_type,
        source=MemorySource.MANUAL,
        source_session_id=None,
        importance=3,
        confidence=0.9,
        canonical_subject_code=right_code,
    )
    versioned.bootstrap_legacy(left.id)
    versioned.bootstrap_legacy(right.id)
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
    return left, right


def _service(connection, memories, versioned, references, forget, *, notifier=None, fault=None):
    return MemoryConflictResolutionService(
        connection,
        versioned=versioned,
        memories=memories,
        forget=forget,
        source_references=references,
        relationship_notifier=notifier,
        fault_injector=fault,
    )


def _lineage_rows(connection):
    return connection.execute(
        "SELECT resolved_memory_id, contributing_memory_id, conflict_id, resolution_kind "
        "FROM relationship_memory_lineage ORDER BY contributing_memory_id"
    ).fetchall()


def _authority(connection, ledger=None):
    return RelationshipAuthorityService(
        connection,
        ledger=ledger or RelationshipLedgerRepository(connection),
    )


def test_resolve_inserts_lineage_for_both_sides_before_scheduling(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'lifecycle.db'}") as connection:
        references = _references()
        memories = MemoryRepository(connection, source_references=references)
        versioned = VersionedMemoryRepository(connection)
        forget = MemoryForgetService(connection, versioned=versioned, source_references=references)
        left, right = _seed_conflict_with_subject(connection, memories, versioned)

        scheduled: list[tuple[str, ...]] = []
        notifier = Mock()
        notifier.schedule.side_effect = lambda ids: scheduled.append(tuple(ids))
        result = _service(
            connection, memories, versioned, references, forget, notifier=notifier
        ).resolve(
            "conflict-1",
            ConflictResolutionPayload(kind=MemoryConflictResolutionKind.CHOOSE_LEFT),
        )

        assert result.resolved_memory is not None
        resolved_id = result.resolved_memory.id
        rows = _lineage_rows(connection)
        assert {(row["resolved_memory_id"], row["contributing_memory_id"]) for row in rows} == {
            (resolved_id, left.id),
            (resolved_id, right.id),
        }
        assert all(row["conflict_id"] == "conflict-1" for row in rows)
        assert all(row["resolution_kind"] == "choose_left" for row in rows)
        # Notifier received both parents and the resolved identity after commit.
        assert scheduled, "resolution must schedule relationship change"
        notified = scheduled[0]
        assert {left.id, right.id, resolved_id} <= set(notified)


def test_resolved_identity_inherits_parent_suppression(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'inherit.db'}") as connection:
        references = _references()
        memories = MemoryRepository(connection, source_references=references)
        versioned = VersionedMemoryRepository(connection)
        forget = MemoryForgetService(connection, versioned=versioned, source_references=references)
        left, right = _seed_conflict_with_subject(connection, memories, versioned)
        authority = _authority(connection)
        left_auth = authority.effective(
            source_memory_id=left.id,
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
        )
        authority.suppress(
            source_memory_id=left.id,
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
            action_kind=RelationshipAuthorityActionKind.USER_REVOKE,
            reason_code="user_revoked",
            expected_decision_id=left_auth.decision_id,
            expected_decision_generation=left_auth.generation,
            expected_authority_epoch=left_auth.authority_epoch,
        )

        result = _service(connection, memories, versioned, references, forget).resolve(
            "conflict-1",
            ConflictResolutionPayload(kind=MemoryConflictResolutionKind.CHOOSE_RIGHT),
        )
        resolved_id = result.resolved_memory.id

        resolved_authority = authority.effective(
            source_memory_id=resolved_id,
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
        )
        assert resolved_authority.suppressed is True


def test_parent_disagreement_resolves_to_suppression(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'disagree.db'}") as connection:
        references = _references()
        memories = MemoryRepository(connection, source_references=references)
        versioned = VersionedMemoryRepository(connection)
        forget = MemoryForgetService(connection, versioned=versioned, source_references=references)
        left, right = _seed_conflict_with_subject(connection, memories, versioned)
        authority = _authority(connection)

        # Suppress the left parent.
        left_auth = authority.effective(
            source_memory_id=left.id,
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
        )
        authority.suppress(
            source_memory_id=left.id,
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
            action_kind=RelationshipAuthorityActionKind.USER_REVOKE,
            reason_code="user_revoked",
            expected_decision_id=left_auth.decision_id,
            expected_decision_generation=left_auth.generation,
            expected_authority_epoch=left_auth.authority_epoch,
        )
        # Re-enable the right parent (independent decision).
        right_auth = authority.effective(
            source_memory_id=right.id,
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
        )
        authority.reenable(
            source_memory_id=right.id,
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
            reason_code="user_reenable",
            expected_decision_id=right_auth.decision_id,
            expected_decision_generation=right_auth.generation,
            expected_authority_epoch=right_auth.authority_epoch,
        )

        result = _service(connection, memories, versioned, references, forget).resolve(
            "conflict-1",
            ConflictResolutionPayload(
                kind=MemoryConflictResolutionKind.REPLACE_BOTH,
                content="新的共同回忆",
                memory_type=MemoryType.RELATIONSHIP_EVENT,
                subject="新经历",
            ),
        )
        resolved_id = result.resolved_memory.id

        resolved_authority = authority.effective(
            source_memory_id=resolved_id,
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
        )
        # Disagreement (one suppressed side) resolves to suppression.
        assert resolved_authority.suppressed is True


def test_dismiss_both_creates_no_lineage_and_schedules_old_sides(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'dismiss.db'}") as connection:
        references = _references()
        memories = MemoryRepository(connection, source_references=references)
        versioned = VersionedMemoryRepository(connection)
        forget = MemoryForgetService(connection, versioned=versioned, source_references=references)
        left, right = _seed_conflict_with_subject(connection, memories, versioned)

        scheduled: list[tuple[str, ...]] = []
        notifier = Mock()
        notifier.schedule.side_effect = lambda ids: scheduled.append(tuple(ids))
        result = _service(
            connection, memories, versioned, references, forget, notifier=notifier
        ).resolve(
            "conflict-1",
            ConflictResolutionPayload(kind=MemoryConflictResolutionKind.DISMISS_BOTH),
        )

        assert result.resolved_memory is None
        assert _lineage_rows(connection) == []
        assert scheduled, "dismiss must schedule old sides for revoke"
        assert {left.id, right.id} <= set(scheduled[0])


@pytest.mark.parametrize(
    "checkpoint",
    ["resolved_identity", "left_archived", "right_archived", "conflict_closed", "lineage", "audit"],
)
def test_resolution_fault_rolls_back_lineage(tmp_path: Path, checkpoint: str) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'rollback.db'}") as connection:
        references = _references()
        memories = MemoryRepository(connection, source_references=references)
        versioned = VersionedMemoryRepository(connection)
        forget = MemoryForgetService(connection, versioned=versioned, source_references=references)
        left, right = _seed_conflict_with_subject(connection, memories, versioned)

        def fail(name: str) -> None:
            if name == checkpoint:
                raise RuntimeError(name)

        with pytest.raises(RuntimeError, match=checkpoint):
            _service(
                connection, memories, versioned, references, forget, fault=fail
            ).resolve(
                "conflict-1",
                ConflictResolutionPayload(kind=MemoryConflictResolutionKind.CHOOSE_LEFT),
            )

        assert _lineage_rows(connection) == []
        assert connection.execute("SELECT status FROM memory_conflicts").fetchone()[0] == "open"


def test_choose_left_copies_selected_exact_subject_code(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'choose-code.db'}") as connection:
        references = _references()
        memories = MemoryRepository(connection, source_references=references)
        versioned = VersionedMemoryRepository(connection)
        forget = MemoryForgetService(connection, versioned=versioned, source_references=references)
        left, right = _seed_conflict_with_subject(
            connection,
            memories,
            versioned,
            left_code="preferred_address",
            right_code="shared_experience",
            left_type=MemoryType.PREFERENCE,
        )
        # conflict stores sides in sorted order; read the actual left side code.
        row = connection.execute(
            "SELECT left_memory_id, right_memory_id FROM memory_conflicts "
            "WHERE conflict_id='conflict-1'"
        ).fetchone()
        left_id = str(row["left_memory_id"])
        left_code = versioned.get_current_version(left_id).canonical_subject_code

        result = _service(connection, memories, versioned, references, forget).resolve(
            "conflict-1",
            ConflictResolutionPayload(kind=MemoryConflictResolutionKind.CHOOSE_LEFT),
        )

        head = versioned.get_current_version(result.resolved_memory.id)
        assert head is not None
        assert head.canonical_subject_code == left_code
        assert result.resolved_memory.canonical_subject_code == left_code


def test_uncoded_replacement_has_no_relationship_subject(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'uncoded.db'}") as connection:
        references = _references()
        memories = MemoryRepository(connection, source_references=references)
        versioned = VersionedMemoryRepository(connection)
        forget = MemoryForgetService(connection, versioned=versioned, source_references=references)
        left, right = _seed_conflict_with_subject(connection, memories, versioned)

        result = _service(connection, memories, versioned, references, forget).resolve(
            "conflict-1",
            ConflictResolutionPayload(
                kind=MemoryConflictResolutionKind.REPLACE_BOTH,
                content="一条普通的备注",
                memory_type=MemoryType.USER_FACT,
                subject="备注",
                canonical_subject_code=None,
            ),
        )

        head = versioned.get_current_version(result.resolved_memory.id)
        assert head is not None
        assert head.canonical_subject_code is None
        assert result.resolved_memory.canonical_subject_code is None


def test_resolved_key_explicit_reenable_overrides_inherited_suppression(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'reenable.db'}") as connection:
        references = _references()
        memories = MemoryRepository(connection, source_references=references)
        versioned = VersionedMemoryRepository(connection)
        forget = MemoryForgetService(connection, versioned=versioned, source_references=references)
        left, right = _seed_conflict_with_subject(connection, memories, versioned)
        authority = _authority(connection)
        left_auth = authority.effective(
            source_memory_id=left.id,
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
        )
        authority.suppress(
            source_memory_id=left.id,
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
            action_kind=RelationshipAuthorityActionKind.USER_REVOKE,
            reason_code="user_revoked",
            expected_decision_id=left_auth.decision_id,
            expected_decision_generation=left_auth.generation,
            expected_authority_epoch=left_auth.authority_epoch,
        )

        result = _service(connection, memories, versioned, references, forget).resolve(
            "conflict-1",
            ConflictResolutionPayload(kind=MemoryConflictResolutionKind.CHOOSE_RIGHT),
        )
        resolved_id = result.resolved_memory.id
        suppressed = authority.effective(
            source_memory_id=resolved_id,
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
        )
        assert suppressed.suppressed is True

        reenabled = authority.reenable(
            source_memory_id=resolved_id,
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
            reason_code="user_reenable",
            expected_decision_id=suppressed.decision_id,
            expected_decision_generation=suppressed.generation,
            expected_authority_epoch=suppressed.authority_epoch,
            expected_inherited_authority_fingerprint=(
                suppressed.inherited_authority_fingerprint
            ),
        )
        assert reenabled.suppressed is False


def test_both_contextual_creates_lineage_and_schedules(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'contextual.db'}") as connection:
        references = _references()
        memories = MemoryRepository(connection, source_references=references)
        versioned = VersionedMemoryRepository(connection)
        forget = MemoryForgetService(connection, versioned=versioned, source_references=references)
        left, right = _seed_conflict_with_subject(connection, memories, versioned)

        scheduled: list[tuple[str, ...]] = []
        notifier = Mock()
        notifier.schedule.side_effect = lambda ids: scheduled.append(tuple(ids))
        result = _service(
            connection, memories, versioned, references, forget, notifier=notifier
        ).resolve(
            "conflict-1",
            ConflictResolutionPayload(
                kind=MemoryConflictResolutionKind.BOTH_CONTEXTUAL,
                content="工作日时一起赏雪",
                memory_type=MemoryType.RELATIONSHIP_EVENT,
                subject="工作日时的共同经历",
            ),
        )

        assert result.resolved_memory is not None
        resolved_id = result.resolved_memory.id
        rows = _lineage_rows(connection)
        assert {(row["resolved_memory_id"], row["contributing_memory_id"]) for row in rows} == {
            (resolved_id, left.id),
            (resolved_id, right.id),
        }
        assert all(row["resolution_kind"] == "both_contextual" for row in rows)
        assert {left.id, right.id, resolved_id} <= set(scheduled[0])


def test_transitive_grandparent_suppression_propagates(tmp_path: Path) -> None:
    """A suppression on a grandparent must suppress a descendant resolved
    identity through multi-level lineage closure (design §6.4)."""
    with managed_connection(f"sqlite:///{tmp_path / 'transitive.db'}") as connection:
        references = _references()
        memories = MemoryRepository(connection, source_references=references)
        versioned = VersionedMemoryRepository(connection)
        forget = MemoryForgetService(connection, versioned=versioned, source_references=references)
        left, right = _seed_conflict_with_subject(connection, memories, versioned)
        authority = _authority(connection)

        # Suppress the left parent.
        left_auth = authority.effective(
            source_memory_id=left.id,
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
        )
        authority.suppress(
            source_memory_id=left.id,
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
            action_kind=RelationshipAuthorityActionKind.USER_REVOKE,
            reason_code="user_revoked",
            expected_decision_id=left_auth.decision_id,
            expected_decision_generation=left_auth.generation,
            expected_authority_epoch=left_auth.authority_epoch,
        )
        # First resolution: child identity inherits suppression.
        child = _service(connection, memories, versioned, references, forget).resolve(
            "conflict-1",
            ConflictResolutionPayload(kind=MemoryConflictResolutionKind.CHOOSE_RIGHT),
        )
        child_id = child.resolved_memory.id
        assert authority.effective(
            source_memory_id=child_id,
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
        ).suppressed is True

        # Second conflict between the child and a fresh memory; resolution
        # creates a grandchild that must still inherit the suppression.
        fresh, _ = memories.create(
            content="一起旅行",
            memory_type=MemoryType.RELATIONSHIP_EVENT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=0.9,
            canonical_subject_code="shared_experience",
        )
        versioned.bootstrap_legacy(fresh.id)
        connection.execute(
            "UPDATE memory_record_states SET state = 'conflicted' "
            "WHERE memory_id IN (?, ?)",
            (child_id, fresh.id),
        )
        connection.execute(
            "INSERT INTO memory_conflicts "
            "(conflict_id, left_memory_id, right_memory_id, status, created_at) "
            "VALUES ('conflict-2', ?, ?, 'open', '2026-07-22T00:00:00+00:00')",
            tuple(sorted((child_id, fresh.id))),
        )
        connection.commit()

        grandchild = _service(connection, memories, versioned, references, forget).resolve(
            "conflict-2",
            ConflictResolutionPayload(kind=MemoryConflictResolutionKind.CHOOSE_LEFT),
        )
        grandchild_id = grandchild.resolved_memory.id
        assert authority.effective(
            source_memory_id=grandchild_id,
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
        ).suppressed is True


def test_rollback_does_not_schedule_relationship_change(tmp_path: Path) -> None:
    """If the resolve transaction rolls back, the notifier must not fire."""
    with managed_connection(f"sqlite:///{tmp_path / 'rollback-noop.db'}") as connection:
        references = _references()
        memories = MemoryRepository(connection, source_references=references)
        versioned = VersionedMemoryRepository(connection)
        forget = MemoryForgetService(connection, versioned=versioned, source_references=references)
        left, right = _seed_conflict_with_subject(connection, memories, versioned)

        notifier = Mock()

        def fail(name: str) -> None:
            if name == "audit":
                raise RuntimeError("audit")

        service = _service(
            connection,
            memories,
            versioned,
            references,
            forget,
            notifier=notifier,
            fault=fail,
        )

        with pytest.raises(RuntimeError, match="audit"):
            service.resolve(
                "conflict-1",
                ConflictResolutionPayload(kind=MemoryConflictResolutionKind.CHOOSE_LEFT),
            )

        notifier.schedule.assert_not_called()

