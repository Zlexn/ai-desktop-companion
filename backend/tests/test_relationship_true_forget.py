from __future__ import annotations

import secrets
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.domain.models import (
    MemoryConflictResolutionKind,
    MemorySource,
    MemoryType,
)
from app.repositories.memories import MemoryRepository
from app.repositories.sqlite import managed_connection
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.services.memory_forget_service import MemoryForgetService
from app.services.memory_source_reference import MemorySourceReferenceService
from app.services.relationship_hooks import NoOpRelationshipChangeNotifier
from app.services.relationship_privacy import RelationshipPrivacyPrimitive
from app.services.versioned_memory_mutation import VersionedMemoryMutationService

from tests.test_relationship_projector import _BASE_TIME, _insert_persona


def _sentinel() -> str:
    return f"sentinel-{secrets.token_hex(8)}"


def _seed_preferred_address(connection, memories, versioned) -> tuple[str, str]:
    """Create an eligible preferred-address memory; returns (memory_id, sentinel)."""
    _insert_persona(connection, "persona-1")
    connection.commit()
    sentinel = _sentinel()
    memory, _conflicts = memories.create(
        content=sentinel,
        memory_type=MemoryType.PREFERENCE,
        source=MemorySource.MANUAL,
        source_session_id=None,
        importance=3,
        confidence=0.9,
        canonical_subject_code="preferred_address",
    )
    connection.commit()
    return memory.id, sentinel


def test_privacy_primitive_removes_address_from_apply_and_projection(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'privacy.db'}") as connection:
        references = MemorySourceReferenceService(b"q" * 32)
        memories = MemoryRepository(connection, source_references=references)
        versioned = VersionedMemoryRepository(connection)
        memory_id, sentinel = _seed_preferred_address(connection, memories, versioned)

        # Simulate an apply event + projection for the address.
        from app.domain.relationship import (
            RelationshipEventType,
            RelationshipPayloadState,
        )
        from app.repositories.relationship_ledger import RelationshipLedgerRepository
        from app.repositories.relationship_sources import RelationshipSourceRepository
        from app.services.relationship_authority import RelationshipAuthorityService
        from app.services.relationship_rules import RelationshipRuleSet
        from app.services.relationship_contract import RELATIONSHIP_RULE_VERSION

        ledger = RelationshipLedgerRepository(connection)
        authority = RelationshipAuthorityService(connection, ledger=ledger)
        auth = authority.effective(
            source_memory_id=memory_id,
            event_type=RelationshipEventType.PREFERRED_ADDRESS,
            subject_code="preferred_address",
        )
        source = RelationshipSourceRepository(connection).get_current(
            memory_id,
            authority=auth,
            relationship_rule_version=RELATIONSHIP_RULE_VERSION,
        )
        assert source is not None
        mapping = RelationshipRuleSet().map(source, persona_artifact_id="persona-1")
        assert mapping.eligible
        with ledger.write_transaction():
            event = ledger.append_apply(
                source=source,
                mapping=mapping,
                created_at=_BASE_TIME,
            )
        assert event.payload_state is RelationshipPayloadState.ACTIVE
        assert event.payload is not None
        assert sentinel in str(event.payload)

        # True forget: relationship privacy must revoke + suppress + redact.
        primitive = RelationshipPrivacyPrimitive(connection)
        with versioned.write_transaction():
            primitive.purge_preferred_address(
                source_memory_id=memory_id,
                now=_BASE_TIME,
            )

        # The apply payload must be physically NULL and revoked.
        row = connection.execute(
            "SELECT payload_json, payload_state FROM relationship_events WHERE id=?",
            (event.id,),
        ).fetchone()
        assert row["payload_json"] is None
        assert row["payload_state"] == "redacted"
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events WHERE event_kind='revoke' "
            "AND revokes_event_id=?",
            (event.id,),
        ).fetchone()[0] == 1
        # Suppression authority must prevent revival.
        suppressed = authority.effective(
            source_memory_id=memory_id,
            event_type=RelationshipEventType.PREFERRED_ADDRESS,
            subject_code="preferred_address",
        )
        assert suppressed.suppressed is True
        # The sentinel must be gone from every readable event/projection surface.
        raw = "\n".join(
            str(tuple(row))
            for row in connection.execute(
                "SELECT payload_json FROM relationship_events"
            ).fetchall()
        )
        assert sentinel not in raw


def test_privacy_fault_rolls_back_all_writes(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'rollback.db'}") as connection:
        references = MemorySourceReferenceService(b"q" * 32)
        memories = MemoryRepository(connection, source_references=references)
        versioned = VersionedMemoryRepository(connection)
        memory_id, _sentinel = _seed_preferred_address(connection, memories, versioned)

        from app.domain.relationship import RelationshipEventType
        from app.repositories.relationship_ledger import RelationshipLedgerRepository
        from app.repositories.relationship_sources import RelationshipSourceRepository
        from app.services.relationship_authority import RelationshipAuthorityService
        from app.services.relationship_rules import RelationshipRuleSet
        from app.services.relationship_contract import RELATIONSHIP_RULE_VERSION

        ledger = RelationshipLedgerRepository(connection)
        authority = RelationshipAuthorityService(connection, ledger=ledger)
        auth = authority.effective(
            source_memory_id=memory_id,
            event_type=RelationshipEventType.PREFERRED_ADDRESS,
            subject_code="preferred_address",
        )
        source = RelationshipSourceRepository(connection).get_current(
            memory_id,
            authority=auth,
            relationship_rule_version=RELATIONSHIP_RULE_VERSION,
        )
        assert source is not None
        mapping = RelationshipRuleSet().map(source, persona_artifact_id="persona-1")
        with ledger.write_transaction():
            event = ledger.append_apply(
                source=source,
                mapping=mapping,
                created_at=_BASE_TIME,
            )
        event_id = event.id

        def fail(name: str) -> None:
            if name == "after_suppress":
                raise RuntimeError("after_suppress")

        primitive = RelationshipPrivacyPrimitive(connection, fault_injector=fail)
        with pytest.raises(RuntimeError, match="after_suppress"):
            with versioned.write_transaction():
                primitive.purge_preferred_address(
                    source_memory_id=memory_id,
                    now=_BASE_TIME,
                )

        # Rollback: apply payload still active, no revoke, no suppression.
        row = connection.execute(
            "SELECT payload_json, payload_state FROM relationship_events WHERE id=?",
            (event_id,),
        ).fetchone()
        assert row["payload_json"] is not None
        assert row["payload_state"] == "active"
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events WHERE event_kind='revoke'"
        ).fetchone()[0] == 0


def test_memory_forget_integration_purges_relationship_address(tmp_path: Path) -> None:
    """End-to-end: forgetting a preferred-address memory must purge the
    relationship apply payload, revoke, and suppress, and the sentinel must be
    absent from every readable relationship surface."""
    with managed_connection(f"sqlite:///{tmp_path / 'forget-integration.db'}") as connection:
        references = MemorySourceReferenceService(b"q" * 32)
        memories = MemoryRepository(connection, source_references=references)
        versioned = VersionedMemoryRepository(connection)
        memory_id, sentinel = _seed_preferred_address(connection, memories, versioned)

        from app.domain.relationship import RelationshipEventType
        from app.repositories.relationship_ledger import RelationshipLedgerRepository
        from app.repositories.relationship_sources import RelationshipSourceRepository
        from app.services.relationship_authority import RelationshipAuthorityService
        from app.services.relationship_rules import RelationshipRuleSet
        from app.services.relationship_contract import RELATIONSHIP_RULE_VERSION

        ledger = RelationshipLedgerRepository(connection)
        authority = RelationshipAuthorityService(connection, ledger=ledger)
        auth = authority.effective(
            source_memory_id=memory_id,
            event_type=RelationshipEventType.PREFERRED_ADDRESS,
            subject_code="preferred_address",
        )
        source = RelationshipSourceRepository(connection).get_current(
            memory_id,
            authority=auth,
            relationship_rule_version=RELATIONSHIP_RULE_VERSION,
        )
        assert source is not None
        mapping = RelationshipRuleSet().map(source, persona_artifact_id="persona-1")
        with ledger.write_transaction():
            ledger.append_apply(source=source, mapping=mapping, created_at=_BASE_TIME)
        connection.commit()

        # Forget the memory via the real service.
        forget = MemoryForgetService(
            connection,
            versioned=versioned,
            source_references=references,
        )
        forget.forget_memory(memory_id)

        # Relationship apply payload physically NULL and revoked.
        row = connection.execute(
            "SELECT payload_json, payload_state FROM relationship_events "
            "WHERE event_type='preferred_address'"
        ).fetchone()
        assert row["payload_json"] is None
        assert row["payload_state"] == "redacted"
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events WHERE event_kind='revoke'"
        ).fetchone()[0] == 1
        # Suppression prevents revival.
        assert authority.effective(
            source_memory_id=memory_id,
            event_type=RelationshipEventType.PREFERRED_ADDRESS,
            subject_code="preferred_address",
        ).suppressed is True
        # Sentinel absent from every event payload and projection.
        raw = "\n".join(
            str(tuple(row))
            for row in connection.execute(
                "SELECT payload_json FROM relationship_events"
            ).fetchall()
        )
        assert sentinel not in raw
        projection_raw = "\n".join(
            str(tuple(row))
            for row in connection.execute(
                "SELECT * FROM relationship_projections"
            ).fetchall()
        )
        assert sentinel not in projection_raw
