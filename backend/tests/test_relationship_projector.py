from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.domain.relationship import (
    RelationshipAuthorityActionKind,
    RelationshipEventType,
    RelationshipPayloadState,
)
from app.repositories.relationship_ledger import RelationshipLedgerRepository
from app.repositories.relationship_sources import RelationshipSourceRepository
from app.repositories.sqlite import managed_connection
from app.services.relationship_authority import RelationshipAuthorityService
from app.services.relationship_contract import FAMILIARITY_BASELINE
from app.services.relationship_projector import RelationshipProjector
from app.services.relationship_rules import RelationshipRuleSet

_BASE_TIME = datetime(2026, 7, 30, 8, 0, tzinfo=UTC)


def _insert_persona(
    connection: sqlite3.Connection,
    persona_id: str,
    version: int = 1,
) -> None:
    connection.execute(
        """
        INSERT INTO persona_artifacts (
            id, version, payload_state, schema_version, ruleset_version,
            template_version, compiler_version, source_content_json,
            rendered_system_prompt, content_identity_hash, behavior_fingerprint,
            created_at
        ) VALUES (?, ?, 'active', 'persona-schema-v1', 'persona-ruleset-v1',
                  'persona-template-v1', 'persona-compiler-v1', '{}', 'prompt',
                  ?, ?, ?)
        """,
        (persona_id, version, "a" * 64, "b" * 64, _BASE_TIME.isoformat()),
    )


def _insert_source(
    connection: sqlite3.Connection,
    *,
    memory_id: str,
    version_id: str,
    subject_code: str,
    content: str,
    created_at: datetime,
) -> None:
    memory_type = "preference" if subject_code == "preferred_address" else "relationship_event"
    connection.execute(
        """
        INSERT INTO memories (
            id, content, memory_type, source, source_session_id,
            importance, confidence, status, metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, 'manual', NULL, 3, 0.9, 'active', '{}', ?, ?)
        """,
        (memory_id, content, memory_type, created_at.isoformat(), created_at.isoformat()),
    )
    connection.execute(
        """
        INSERT INTO memory_versions (
            id, memory_id, version_number, parent_version_id, operation,
            memory_type, subject, content, content_hash, canonical_key_hash,
            subject_key_hash, canonicalization_version, confidence, importance,
            source_kind, source_session_id, source_session_reference_hash,
            writer_policy_version, created_at, redacted_at, canonical_subject_code
        ) VALUES (?, ?, 1, NULL, 'create', ?, ?, ?, ?, NULL, NULL,
                  'memory-canonicalization-v1', 0.9, 3, 'manual', NULL, NULL,
                  'manual-write-v1', ?, NULL, ?)
        """,
        (
            version_id,
            memory_id,
            memory_type,
            subject_code,
            content,
            f"hash-{version_id}",
            created_at.isoformat(),
            subject_code,
        ),
    )
    connection.execute(
        """
        INSERT INTO memory_record_states (
            memory_id, state, current_version_id, head_version,
            record_generation, canonical_key_hash, subject_key_hash,
            canonicalization_version, source_kind, created_at, updated_at
        ) VALUES (?, 'active', ?, 1, 0, NULL, NULL,
                  'memory-canonicalization-v1', 'manual', ?, ?)
        """,
        (memory_id, version_id, created_at.isoformat(), created_at.isoformat()),
    )


def _append_apply(
    connection: sqlite3.Connection,
    *,
    memory_id: str,
    event_type: RelationshipEventType,
    persona_id: str = "persona-1",
):
    ledger = RelationshipLedgerRepository(connection)
    authority = RelationshipAuthorityService(connection, ledger=ledger).effective(
        source_memory_id=memory_id,
        event_type=event_type,
        subject_code=event_type.value,  # type: ignore[arg-type]
    )
    source = RelationshipSourceRepository(connection).get_current(
        memory_id,
        authority=authority,
    )
    assert source is not None
    mapping = RelationshipRuleSet().map(source, persona_artifact_id=persona_id)
    with ledger.write_transaction():
        return ledger.append_apply(
            source=source,
            mapping=mapping,
            created_at=_BASE_TIME + timedelta(days=1),
        )


def _database(tmp_path: Path, name: str = "projection.db"):
    return managed_connection(f"sqlite:///{tmp_path / name}")


def _seed_complete_set(connection: sqlite3.Connection) -> dict[str, object]:
    _insert_persona(connection, "persona-1")
    _insert_persona(connection, "persona-2", 2)
    _insert_source(
        connection,
        memory_id="memory-shared",
        version_id="version-shared",
        subject_code="shared_experience",
        content="共同看过雪景",
        created_at=_BASE_TIME,
    )
    _insert_source(
        connection,
        memory_id="memory-commitment",
        version_id="version-commitment",
        subject_code="non_external_commitment",
        content="会记得一起整理书架",
        created_at=_BASE_TIME + timedelta(minutes=1),
    )
    _insert_source(
        connection,
        memory_id="memory-address",
        version_id="version-address",
        subject_code="preferred_address",
        content="小雪",
        created_at=_BASE_TIME + timedelta(minutes=2),
    )
    connection.commit()
    return {
        "shared": _append_apply(
            connection,
            memory_id="memory-shared",
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
        ),
        "commitment": _append_apply(
            connection,
            memory_id="memory-commitment",
            event_type=RelationshipEventType.NON_EXTERNAL_COMMITMENT,
        ),
        "address": _append_apply(
            connection,
            memory_id="memory-address",
            event_type=RelationshipEventType.PREFERRED_ADDRESS,
        ),
    }


def test_projection_fold_is_deterministic_bounded_and_idempotent(tmp_path: Path) -> None:
    with _database(tmp_path) as connection:
        events = _seed_complete_set(connection)
        projector = RelationshipProjector(connection)

        with projector.write_transaction():
            first = projector.project(
                persona_artifact_id="persona-1",
                computed_at=_BASE_TIME + timedelta(days=2),
            )
        with projector.write_transaction():
            duplicate = projector.project(
                persona_artifact_id="persona-1",
                computed_at=_BASE_TIME + timedelta(days=3),
            )

        assert duplicate == first
        assert first.version == 1
        assert first.familiarity == pytest.approx(FAMILIARITY_BASELINE + 0.07)
        assert first.preferred_address_event_id == events["address"].id
        assert first.relationship_summary_code.value == "steady"
        assert first.source_relationship_event_ids == tuple(
            event.id for event in events.values()
        )
        assert len(first.integrity_fingerprint) == 64
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_projections"
        ).fetchone()[0] == 1


def test_projection_excludes_revoked_and_suppressed_sources(tmp_path: Path) -> None:
    with _database(tmp_path) as connection:
        events = _seed_complete_set(connection)
        ledger = RelationshipLedgerRepository(connection)
        with ledger.write_transaction():
            ledger.append_revoke(
                apply_event_id=events["commitment"].id,
                created_at=_BASE_TIME + timedelta(days=2),
            )
        authority_service = RelationshipAuthorityService(connection, ledger=ledger)
        current = authority_service.effective(
            source_memory_id="memory-shared",
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
        )
        authority_service.suppress(
            source_memory_id="memory-shared",
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
            action_kind=RelationshipAuthorityActionKind.USER_REVOKE,
            reason_code="user_revoked",
            expected_decision_id=current.decision_id,
            expected_decision_generation=current.generation,
            expected_authority_epoch=current.authority_epoch,
        )

        projector = RelationshipProjector(connection)
        with projector.write_transaction():
            snapshot = projector.project(
                persona_artifact_id="persona-1",
                computed_at=_BASE_TIME + timedelta(days=3),
            )

        assert snapshot.familiarity == FAMILIARITY_BASELINE
        assert snapshot.source_relationship_event_ids == (events["address"].id,)
        assert snapshot.preferred_address_event_id == events["address"].id


def test_corrupt_event_fails_closed_without_projection_write(tmp_path: Path) -> None:
    with _database(tmp_path) as connection:
        events = _seed_complete_set(connection)
        connection.execute("DROP TRIGGER trg_relationship_events_append_only_update")
        connection.execute(
            "UPDATE relationship_events SET integrity_fingerprint = ? WHERE id = ?",
            ("f" * 64, events["shared"].id),
        )
        connection.commit()
        projector = RelationshipProjector(connection)

        with projector.write_transaction():
            view = projector.project_view_or_neutral(
                persona_artifact_id="persona-1",
                computed_at=_BASE_TIME + timedelta(days=2),
            )

        assert view.projection_id == "neutral"
        assert view.familiarity_bucket == "steady"
        assert view.preferred_address is None
        assert view.contributing_event_count == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_projections"
        ).fetchone()[0] == 0


def test_projection_rejects_stale_source_head(tmp_path: Path) -> None:
    with _database(tmp_path, "stale-source.db") as connection:
        _seed_complete_set(connection)
        connection.execute(
            "UPDATE memory_record_states SET state = 'archived', record_generation = 1 "
            "WHERE memory_id = 'memory-shared'"
        )
        connection.commit()
        projector = RelationshipProjector(connection)
        with projector.write_transaction():
            snapshot = projector.project(
                persona_artifact_id="persona-1",
                computed_at=_BASE_TIME + timedelta(days=2),
            )

        assert snapshot.familiarity == pytest.approx(FAMILIARITY_BASELINE + 0.03)
        assert len(snapshot.source_relationship_event_ids) == 2


def test_source_lifetime_and_total_caps_are_deterministic() -> None:
    def numeric(event_id: str, memory_id: str, delta: float):
        from app.domain.relationship import RelationshipEvent, RelationshipEventKind
        from app.services.relationship_contract import (
            RELATIONSHIP_EVENT_SCHEMA_VERSION,
            RELATIONSHIP_OBSERVED_TIME_DERIVATION_VERSION,
            RELATIONSHIP_RULE_VERSION,
        )

        return RelationshipEvent(
            id=event_id,
            scope_id="default",
            event_kind=RelationshipEventKind.APPLY,
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
            subject_code="shared_experience",
            payload_state=RelationshipPayloadState.ACTIVE,
            payload={"delta": delta},
            source_memory_id=memory_id,
            source_memory_version_id=f"version-{event_id}",
            observed_at=_BASE_TIME,
            observed_time_derivation_version=(
                RELATIONSHIP_OBSERVED_TIME_DERIVATION_VERSION
            ),
            revokes_event_id=None,
            rule_version=RELATIONSHIP_RULE_VERSION,
            persona_artifact_id="persona-1",
            event_schema_version=RELATIONSHIP_EVENT_SCHEMA_VERSION,
            integrity_fingerprint="a" * 64,
            created_at=_BASE_TIME,
        )

    events = tuple(
        numeric(f"event-{index:02d}", "same-source", 0.08)
        for index in range(4)
    ) + tuple(
        numeric(f"other-{index:02d}", f"memory-{index:02d}", 0.08)
        for index in range(10)
    )
    familiarity, _, summary, event_ids = RelationshipProjector._fold(events)

    assert familiarity == 1.0
    assert summary.value == "close"
    assert len(event_ids) == 14


def test_persona_a_b_a_creates_forward_immutable_versions(tmp_path: Path) -> None:
    with _database(tmp_path, "persona-cycle.db") as connection:
        _seed_complete_set(connection)
        projector = RelationshipProjector(connection)
        with projector.write_transaction():
            first = projector.project(
                persona_artifact_id="persona-1",
                computed_at=_BASE_TIME + timedelta(days=2),
            )
        with projector.write_transaction():
            second = projector.project(
                persona_artifact_id="persona-2",
                computed_at=_BASE_TIME + timedelta(days=3),
            )
        with projector.write_transaction():
            third = projector.project(
                persona_artifact_id="persona-1",
                computed_at=_BASE_TIME + timedelta(days=4),
            )

        assert (first.version, second.version, third.version) == (1, 2, 3)
        assert len({first.projection_id, second.projection_id, third.projection_id}) == 3
        assert third.familiarity == first.familiarity
        assert third.source_relationship_event_ids == first.source_relationship_event_ids


def test_persona_change_creates_new_snapshot_without_numeric_change(tmp_path: Path) -> None:
    with _database(tmp_path) as connection:
        _seed_complete_set(connection)
        projector = RelationshipProjector(connection)
        with projector.write_transaction():
            first = projector.project(
                persona_artifact_id="persona-1",
                computed_at=_BASE_TIME + timedelta(days=2),
            )
        with projector.write_transaction():
            second = projector.project(
                persona_artifact_id="persona-2",
                computed_at=_BASE_TIME + timedelta(days=3),
            )

        assert second.version == first.version + 1
        assert second.persona_artifact_id == "persona-2"
        assert second.familiarity == first.familiarity
        assert second.source_relationship_event_ids == first.source_relationship_event_ids
