from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.relationship import (
    RelationshipAuthorityAction,
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


def _service(connection) -> RelationshipAuthorityService:
    return RelationshipAuthorityService(
        connection,
        ledger=RelationshipLedgerRepository(connection),
    )


def test_no_decision_then_suppress_then_explicit_reenable_is_linear(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'linear.db'}") as connection:
        _insert_memory(connection, "memory-1")
        connection.commit()
        service = _service(connection)

        initial = service.effective(
            source_memory_id="memory-1",
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
        )
        assert initial.decision_id is None
        assert initial.generation == 0
        assert initial.action is None
        assert initial.suppressed is False
        assert initial.authority_epoch == 0
        assert len(initial.inherited_authority_fingerprint) == 64

        suppressed = service.suppress(
            source_memory_id="memory-1",
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
            action_kind=RelationshipAuthorityActionKind.USER_REVOKE,
            reason_code="user_revoked",
            expected_decision_id=None,
            expected_decision_generation=0,
            expected_authority_epoch=0,
        )
        assert suppressed.generation == 1
        assert suppressed.action is RelationshipAuthorityAction.SUPPRESS
        assert suppressed.suppressed is True
        assert suppressed.authority_epoch == 1

        enabled = service.reenable(
            source_memory_id="memory-1",
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
            reason_code="user_reenabled",
            expected_decision_id=suppressed.decision_id,
            expected_decision_generation=1,
            expected_authority_epoch=1,
        )
        assert enabled.generation == 2
        assert enabled.action is RelationshipAuthorityAction.REENABLE
        assert enabled.suppressed is False
        assert enabled.authority_epoch == 2

        rows = connection.execute(
            """
            SELECT id, predecessor_decision_id, generation, action, action_kind,
                   reason_code, inherited_authority_fingerprint
            FROM relationship_authority_decisions
            ORDER BY generation
            """
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]["predecessor_decision_id"] is None
        assert rows[1]["predecessor_decision_id"] == rows[0]["id"]
        assert rows[0]["inherited_authority_fingerprint"] is None
        assert rows[1]["inherited_authority_fingerprint"] == (
            enabled.inherited_authority_fingerprint
        )


def test_stale_decision_or_epoch_cannot_append(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'stale.db'}") as connection:
        _insert_memory(connection, "memory-1")
        connection.commit()
        service = _service(connection)
        current = service.suppress(
            source_memory_id="memory-1",
            event_type=RelationshipEventType.PREFERRED_ADDRESS,
            subject_code="preferred_address",
            action_kind=RelationshipAuthorityActionKind.PRIVACY_REDACT,
            reason_code="privacy_redact",
            expected_decision_id=None,
            expected_decision_generation=0,
            expected_authority_epoch=0,
        )

        with pytest.raises(StaleRelationshipAuthorityError):
            service.reenable(
                source_memory_id="memory-1",
                event_type=RelationshipEventType.PREFERRED_ADDRESS,
                subject_code="preferred_address",
                reason_code="stale_id",
                expected_decision_id=None,
                expected_decision_generation=0,
                expected_authority_epoch=current.authority_epoch,
            )
        with pytest.raises(StaleRelationshipAuthorityError):
            service.reenable(
                source_memory_id="memory-1",
                event_type=RelationshipEventType.PREFERRED_ADDRESS,
                subject_code="preferred_address",
                reason_code="stale_epoch",
                expected_decision_id=current.decision_id,
                expected_decision_generation=current.generation,
                expected_authority_epoch=0,
            )

        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_authority_decisions"
        ).fetchone()[0] == 1


def test_action_kind_matrix_and_semantic_key_are_strict(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'strict.db'}") as connection:
        _insert_memory(connection, "memory-1")
        connection.commit()
        service = _service(connection)

        with pytest.raises(ValueError):
            service.suppress(
                source_memory_id="memory-1",
                event_type=RelationshipEventType.PREFERRED_ADDRESS,
                subject_code="shared_experience",  # type: ignore[arg-type]
                action_kind=RelationshipAuthorityActionKind.USER_REVOKE,
                reason_code="invalid_pair",
                expected_decision_id=None,
                expected_decision_generation=0,
                expected_authority_epoch=0,
            )
        with pytest.raises(ValueError):
            service.suppress(
                source_memory_id="memory-1",
                event_type=RelationshipEventType.PREFERRED_ADDRESS,
                subject_code="preferred_address",
                action_kind=RelationshipAuthorityActionKind.USER_REENABLE,
                reason_code="invalid_action_kind",
                expected_decision_id=None,
                expected_decision_generation=0,
                expected_authority_epoch=0,
            )
        with pytest.raises(ValueError):
            service.suppress(
                source_memory_id="memory-1",
                event_type=RelationshipEventType.PREFERRED_ADDRESS,
                subject_code="preferred_address",
                action_kind=RelationshipAuthorityActionKind.USER_REVOKE,
                reason_code="",
                expected_decision_id=None,
                expected_decision_generation=0,
                expected_authority_epoch=0,
            )

        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_authority_decisions"
        ).fetchone()[0] == 0


def test_corrupt_authority_chain_fails_closed(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'corrupt.db'}") as connection:
        _insert_memory(connection, "memory-1")
        connection.commit()
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("DROP TRIGGER trg_relationship_authority_linear_insert")
        connection.execute(
            """
            INSERT INTO relationship_authority_decisions (
                id, scope_id, source_memory_id, event_type, subject_code,
                predecessor_decision_id, generation, action, action_kind,
                reason_code, inherited_authority_fingerprint, created_at
            ) VALUES (
                'corrupt-2', 'default', 'memory-1', 'shared_experience',
                'shared_experience', 'missing-predecessor', 2, 'reenable',
                'user_reenable', 'corrupt', ?, '2026-07-29T00:00:01+00:00'
            )
            """,
            ("f" * 64,),
        )
        connection.commit()
        connection.execute("PRAGMA foreign_keys = ON")

        snapshot = _service(connection).effective(
            source_memory_id="memory-1",
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
        )
        assert snapshot.suppressed is True
        assert snapshot.action is None
        assert snapshot.decision_id is None
        assert len(snapshot.inherited_authority_fingerprint) == 64


def test_authority_tables_retain_metadata_only(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'columns.db'}") as connection:
        authority_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(relationship_authority_decisions)"
            )
        }
        lineage_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(relationship_memory_lineage)"
            )
        }
        forbidden = {
            "content",
            "address",
            "payload_json",
            "source_hash",
            "hmac",
            "prompt",
            "raw_response",
        }
        assert authority_columns.isdisjoint(forbidden)
        assert lineage_columns.isdisjoint(forbidden)
