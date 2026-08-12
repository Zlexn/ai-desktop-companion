from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from app.domain.models import MemoryConflictResolutionKind
from app.domain.relationship import (
    RelationshipAuthorityActionKind,
    RelationshipEventType,
)
from app.repositories.relationship_ledger import RelationshipLedgerRepository
from app.repositories.sqlite import managed_connection
from app.services.relationship_authority import (
    RelationshipAuthorityService,
    StaleRelationshipAuthorityError,
)


def _insert_memory(connection, memory_id: str) -> None:
    connection.execute(
        """
        INSERT INTO memories (
            id, content, memory_type, source, source_session_id,
            importance, confidence, status, metadata_json, created_at, updated_at
        ) VALUES (?, 'metadata-only source', 'relationship_event', 'manual', NULL,
                  3, 1.0, 'active', '{}',
                  '2026-07-29T00:00:00+00:00',
                  '2026-07-29T00:00:00+00:00')
        """,
        (memory_id,),
    )


def _insert_resolved_conflict(
    connection,
    *,
    conflict_id: str,
    left_id: str,
    right_id: str,
    resolved_id: str,
) -> None:
    for memory_id in (left_id, right_id, resolved_id):
        _insert_memory(connection, memory_id)
    left_id, right_id = sorted((left_id, right_id))
    connection.execute(
        """
        INSERT INTO memory_conflicts (
            conflict_id, left_memory_id, right_memory_id, status,
            resolution_kind, resolved_memory_id, created_at, resolved_at
        ) VALUES (?, ?, ?, 'resolved', 'replace_both', ?,
                  '2026-07-29T00:00:00+00:00',
                  '2026-07-29T00:00:01+00:00')
        """,
        (conflict_id, left_id, right_id, resolved_id),
    )


def _service(connection) -> RelationshipAuthorityService:
    return RelationshipAuthorityService(
        connection,
        ledger=RelationshipLedgerRepository(connection),
    )


def _suppress(service: RelationshipAuthorityService, memory_id: str, epoch: int):
    current = service.effective(
        source_memory_id=memory_id,
        event_type=RelationshipEventType.SHARED_EXPERIENCE,
        subject_code="shared_experience",
    )
    return service.suppress(
        source_memory_id=memory_id,
        event_type=RelationshipEventType.SHARED_EXPERIENCE,
        subject_code="shared_experience",
        action_kind=RelationshipAuthorityActionKind.USER_REVOKE,
        reason_code="user_revoked",
        expected_decision_id=current.decision_id,
        expected_decision_generation=current.generation,
        expected_authority_epoch=epoch,
    )


def test_lineage_insertion_is_atomic_sorted_and_increments_epoch_per_edge(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'lineage.db'}") as connection:
        _insert_resolved_conflict(
            connection,
            conflict_id="conflict-1",
            left_id="left",
            right_id="right",
            resolved_id="resolved",
        )
        connection.commit()
        ledger = RelationshipLedgerRepository(connection)

        epoch = ledger.append_conflict_lineage(
            resolved_memory_id="resolved",
            contributing_memory_ids=("right", "left"),
            conflict_id="conflict-1",
            resolution_kind=MemoryConflictResolutionKind.REPLACE_BOTH,
        )

        assert epoch == 2
        rows = connection.execute(
            """
            SELECT contributing_memory_id
            FROM relationship_memory_lineage
            WHERE resolved_memory_id = 'resolved'
            ORDER BY contributing_memory_id
            """
        ).fetchall()
        assert [row[0] for row in rows] == ["left", "right"]
        assert ledger.lineage_closure("resolved") == ("left", "right")

        with pytest.raises(ValueError):
            ledger.append_conflict_lineage(
                resolved_memory_id="resolved",
                contributing_memory_ids=("left",),
                conflict_id="conflict-1",
                resolution_kind=MemoryConflictResolutionKind.CHOOSE_LEFT,
            )
        assert ledger.authority_epoch() == 2


def test_transitive_two_parent_suppression_and_disagreement_fail_closed(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'inherit.db'}") as connection:
        _insert_resolved_conflict(
            connection,
            conflict_id="conflict-1",
            left_id="left",
            right_id="right",
            resolved_id="middle",
        )
        _insert_memory(connection, "other")
        _insert_memory(connection, "resolved")
        connection.execute(
            """
            INSERT INTO memory_conflicts (
                conflict_id, left_memory_id, right_memory_id, status,
                resolution_kind, resolved_memory_id, created_at, resolved_at
            ) VALUES ('conflict-2', 'middle', 'other', 'resolved',
                      'replace_both', 'resolved',
                      '2026-07-29T00:00:02+00:00',
                      '2026-07-29T00:00:03+00:00')
            """
        )
        connection.commit()
        ledger = RelationshipLedgerRepository(connection)
        ledger.append_conflict_lineage(
            resolved_memory_id="middle",
            contributing_memory_ids=("left", "right"),
            conflict_id="conflict-1",
            resolution_kind=MemoryConflictResolutionKind.REPLACE_BOTH,
        )
        ledger.append_conflict_lineage(
            resolved_memory_id="resolved",
            contributing_memory_ids=("middle", "other"),
            conflict_id="conflict-2",
            resolution_kind=MemoryConflictResolutionKind.REPLACE_BOTH,
        )
        service = _service(connection)
        _suppress(service, "left", ledger.authority_epoch())

        right_enabled = service.reenable(
            source_memory_id="right",
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
            reason_code="right_enabled",
            expected_decision_id=None,
            expected_decision_generation=0,
            expected_authority_epoch=ledger.authority_epoch(),
        )
        assert right_enabled.suppressed is False

        effective = service.effective(
            source_memory_id="resolved",
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
        )
        assert ledger.lineage_closure("resolved") == (
            "left",
            "middle",
            "other",
            "right",
        )
        assert effective.decision_id is None
        assert effective.suppressed is True
        assert len(effective.inherited_authority_fingerprint) == 64


def test_resolved_key_reenable_overrides_only_exact_inherited_fingerprint(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'override.db'}") as connection:
        _insert_resolved_conflict(
            connection,
            conflict_id="conflict-1",
            left_id="left",
            right_id="right",
            resolved_id="resolved",
        )
        connection.commit()
        ledger = RelationshipLedgerRepository(connection)
        ledger.append_conflict_lineage(
            resolved_memory_id="resolved",
            contributing_memory_ids=("left", "right"),
            conflict_id="conflict-1",
            resolution_kind=MemoryConflictResolutionKind.REPLACE_BOTH,
        )
        service = _service(connection)
        _suppress(service, "left", ledger.authority_epoch())

        inherited = service.effective(
            source_memory_id="resolved",
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
        )
        assert inherited.suppressed is True and inherited.decision_id is None

        enabled = service.reenable(
            source_memory_id="resolved",
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
            reason_code="resolved_override",
            expected_decision_id=None,
            expected_decision_generation=0,
            expected_authority_epoch=inherited.authority_epoch,
        )
        assert enabled.suppressed is False
        assert enabled.inherited_authority_fingerprint == (
            inherited.inherited_authority_fingerprint
        )

        right_suppressed = _suppress(service, "right", enabled.authority_epoch)
        assert right_suppressed.suppressed is True
        invalidated = service.effective(
            source_memory_id="resolved",
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
        )
        assert invalidated.decision_id == enabled.decision_id
        assert invalidated.generation == enabled.generation
        assert invalidated.inherited_authority_fingerprint != (
            enabled.inherited_authority_fingerprint
        )
        assert invalidated.suppressed is True

        reenabled = service.reenable(
            source_memory_id="resolved",
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
            reason_code="resolved_override_refreshed",
            expected_decision_id=invalidated.decision_id,
            expected_decision_generation=invalidated.generation,
            expected_authority_epoch=invalidated.authority_epoch,
        )
        assert reenabled.suppressed is False
        assert reenabled.generation == enabled.generation + 1


def test_stale_private_fingerprint_recheck_rejects_inflight_override(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'stale-fingerprint.db'}") as connection:
        _insert_resolved_conflict(
            connection,
            conflict_id="conflict-1",
            left_id="left",
            right_id="right",
            resolved_id="resolved",
        )
        connection.commit()
        ledger = RelationshipLedgerRepository(connection)
        ledger.append_conflict_lineage(
            resolved_memory_id="resolved",
            contributing_memory_ids=("left", "right"),
            conflict_id="conflict-1",
            resolution_kind=MemoryConflictResolutionKind.REPLACE_BOTH,
        )
        service = _service(connection)
        _suppress(service, "left", ledger.authority_epoch())
        captured = service.effective(
            source_memory_id="resolved",
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
        )
        _suppress(service, "right", captured.authority_epoch)

        with pytest.raises(StaleRelationshipAuthorityError):
            service.reenable(
                source_memory_id="resolved",
                event_type=RelationshipEventType.SHARED_EXPERIENCE,
                subject_code="shared_experience",
                reason_code="stale_override",
                expected_decision_id=None,
                expected_decision_generation=0,
                expected_authority_epoch=captured.authority_epoch,
                expected_inherited_authority_fingerprint=(
                    captured.inherited_authority_fingerprint
                ),
            )


def test_cycle_or_corrupt_lineage_fails_closed(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'cycle.db'}") as connection:
        for memory_id in ("a", "b"):
            _insert_memory(connection, memory_id)
        connection.commit()
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            """
            INSERT INTO relationship_memory_lineage (
                resolved_memory_id, contributing_memory_id, conflict_id,
                resolution_kind, created_at
            ) VALUES
                ('a', 'b', 'missing-1', 'replace_both', '2026-07-29T00:00:00+00:00'),
                ('b', 'a', 'missing-2', 'replace_both', '2026-07-29T00:00:01+00:00')
            """
        )
        connection.commit()
        connection.execute("PRAGMA foreign_keys = ON")

        service = _service(connection)
        snapshot = service.effective(
            source_memory_id="a",
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
        )
        assert snapshot.suppressed is True
        assert snapshot.action is None
        assert len(snapshot.inherited_authority_fingerprint) == 64
