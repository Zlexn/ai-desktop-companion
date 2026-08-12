from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.domain.relationship import (
    RelationshipAuthorityActionKind,
    RelationshipEventKind,
    RelationshipEventType,
    RelationshipPayloadState,
    RelationshipSourceSnapshot,
)
from app.repositories.relationship_ledger import RelationshipLedgerRepository
from app.repositories.relationship_sources import RelationshipSourceRepository
from app.repositories.sqlite import managed_connection
from app.services.relationship_authority import RelationshipAuthorityService
from app.services.relationship_contract import (
    RELATIONSHIP_OBSERVED_TIME_DERIVATION_VERSION,
    RELATIONSHIP_RULE_VERSION,
)
from app.services.relationship_rules import RelationshipRuleSet


_VERSION_CREATED_AT = datetime(2026, 7, 29, 8, 30, tzinfo=UTC)


def _insert_source(
    connection: sqlite3.Connection,
    *,
    memory_id: str = "memory-1",
    version_id: str = "version-1",
    subject_code: str = "shared_experience",
    content: str = "共同看过雪景",
) -> None:
    memory_type = (
        "preference" if subject_code == "preferred_address" else "relationship_event"
    )
    connection.execute(
        """
        INSERT INTO memories (
            id, content, memory_type, source, source_session_id,
            importance, confidence, status, metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, 'manual', NULL, 3, 0.9, 'active', '{}', ?, ?)
        """,
        (memory_id, content, memory_type, _VERSION_CREATED_AT.isoformat(), _VERSION_CREATED_AT.isoformat()),
    )
    connection.execute(
        """
        INSERT INTO memory_versions (
            id, memory_id, version_number, parent_version_id, operation,
            memory_type, subject, content, content_hash, canonical_key_hash,
            subject_key_hash, canonicalization_version, confidence, importance,
            source_kind, source_session_id, source_session_reference_hash,
            writer_policy_version, created_at, redacted_at, canonical_subject_code
        ) VALUES (?, ?, 1, NULL, 'create', ?, ?, ?, 'content-hash', NULL, NULL,
                  'memory-canonicalization-v1', 0.9, 3, 'manual', NULL, NULL,
                  'manual-write-v1', ?, NULL, ?)
        """,
        (
            version_id,
            memory_id,
            memory_type,
            subject_code,
            content,
            _VERSION_CREATED_AT.isoformat(),
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
        (
            memory_id,
            version_id,
            _VERSION_CREATED_AT.isoformat(),
            _VERSION_CREATED_AT.isoformat(),
        ),
    )


def _insert_persona(connection: sqlite3.Connection, persona_id: str = "persona-1") -> None:
    connection.execute(
        """
        INSERT INTO persona_artifacts (
            id, version, payload_state, schema_version, ruleset_version,
            template_version, compiler_version, source_content_json,
            rendered_system_prompt, content_identity_hash, behavior_fingerprint,
            created_at
        ) VALUES (?, 1, 'active', 'persona-schema-v1', 'persona-ruleset-v1',
                  'persona-template-v1', 'persona-compiler-v1', '{}', 'prompt',
                  ?, ?, ?)
        """,
        (persona_id, "a" * 64, "b" * 64, _VERSION_CREATED_AT.isoformat()),
    )


def _mapping(source: RelationshipSourceSnapshot):
    return RelationshipRuleSet().map(source, persona_artifact_id="persona-1")


def _current_snapshot(
    connection: sqlite3.Connection,
    *,
    memory_id: str = "memory-1",
    event_type: RelationshipEventType = RelationshipEventType.SHARED_EXPERIENCE,
) -> RelationshipSourceSnapshot:
    ledger = RelationshipLedgerRepository(connection)
    authority = RelationshipAuthorityService(connection, ledger=ledger).effective(
        source_memory_id=memory_id,
        event_type=event_type,
        subject_code=event_type.value,  # type: ignore[arg-type]
    )
    snapshot = RelationshipSourceRepository(connection).get_current(
        memory_id,
        authority=authority,
    )
    assert snapshot is not None
    return snapshot


@pytest.fixture
def connection(tmp_path: Path):
    with managed_connection(f"sqlite:///{tmp_path / 'ledger.db'}") as current:
        _insert_persona(current)
        _insert_source(current)
        current.commit()
        yield current


def test_append_apply_is_idempotent_and_uses_source_observed_time(
    connection: sqlite3.Connection,
) -> None:
    ledger = RelationshipLedgerRepository(connection)
    source = _current_snapshot(connection)
    mapping = _mapping(source)
    created_at = _VERSION_CREATED_AT + timedelta(days=10)

    with ledger.write_transaction():
        first = ledger.append_apply(source=source, mapping=mapping, created_at=created_at)
    with ledger.write_transaction():
        duplicate = ledger.append_apply(
            source=source,
            mapping=mapping,
            created_at=created_at + timedelta(days=1),
        )

    assert duplicate == first
    assert first.event_kind is RelationshipEventKind.APPLY
    assert first.event_type is RelationshipEventType.SHARED_EXPERIENCE
    assert first.payload_state is RelationshipPayloadState.ACTIVE
    assert first.payload == {
        "category": "shared_experience",
        "reason_code": "allowlisted_current_memory",
        "delta": 0.04,
    }
    assert first.observed_at == _VERSION_CREATED_AT
    assert first.observed_time_derivation_version == (
        RELATIONSHIP_OBSERVED_TIME_DERIVATION_VERSION
    )
    assert first.created_at == created_at
    assert len(first.integrity_fingerprint) == 64
    assert connection.execute(
        "SELECT COUNT(*) FROM relationship_events"
    ).fetchone()[0] == 1

    row = connection.execute(
        "SELECT payload_json, observed_at, created_at FROM relationship_events"
    ).fetchone()
    assert row["payload_json"] == (
        '{"category":"shared_experience","delta":0.04,'
        '"reason_code":"allowlisted_current_memory"}'
    )
    assert row["observed_at"] == _VERSION_CREATED_AT.isoformat()
    assert row["created_at"] == created_at.isoformat()


def test_append_apply_rejects_mismatched_or_noncanonical_input(
    connection: sqlite3.Connection,
) -> None:
    ledger = RelationshipLedgerRepository(connection)
    source = _current_snapshot(connection)
    mapping = _mapping(source)

    with pytest.raises(ValueError):
        with ledger.write_transaction():
            ledger.append_apply(
                source=replace(source, source_memory_version_id="other-version"),
                mapping=mapping,
                created_at=_VERSION_CREATED_AT,
            )
    with pytest.raises(ValueError):
        with ledger.write_transaction():
            ledger.append_apply(
                source=replace(source, record_generation=1),
                mapping=_mapping(replace(source, record_generation=1)),
                created_at=_VERSION_CREATED_AT,
            )
    with pytest.raises(ValueError):
        with ledger.write_transaction():
            ledger.append_apply(
                source=source,
                mapping=replace(mapping, persona_artifact_id="missing-persona"),
                created_at=_VERSION_CREATED_AT,
            )
    with pytest.raises(ValueError):
        with ledger.write_transaction():
            ledger.append_apply(
                source=source,
                mapping=replace(mapping, payload={"delta": 0.04}),
                created_at=_VERSION_CREATED_AT,
            )
    assert connection.execute(
        "SELECT COUNT(*) FROM relationship_events"
    ).fetchone()[0] == 0


def test_append_apply_rejects_source_redacted_after_snapshot(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'stale-redaction.db'}") as connection:
        _insert_persona(connection)
        _insert_source(
            connection,
            subject_code="preferred_address",
            content="小雪",
        )
        connection.commit()
        ledger = RelationshipLedgerRepository(connection)
        source = _current_snapshot(
            connection,
            event_type=RelationshipEventType.PREFERRED_ADDRESS,
        )
        connection.execute(
            """
            UPDATE memory_versions
            SET subject = NULL, content = NULL, redacted_at = ?
            WHERE id = ?
            """,
            ((_VERSION_CREATED_AT + timedelta(minutes=1)).isoformat(), "version-1"),
        )
        connection.commit()

        with pytest.raises(ValueError):
            with ledger.write_transaction():
                ledger.append_apply(
                    source=source,
                    mapping=_mapping(source),
                    created_at=_VERSION_CREATED_AT + timedelta(minutes=2),
                )
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events"
        ).fetchone()[0] == 0


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("source_kind", "user_revert"),
        ("confidence", 0.8),
        ("importance", 2),
    ],
)
def test_append_apply_rejects_changed_source_tuple(
    connection: sqlite3.Connection,
    column: str,
    value: object,
) -> None:
    ledger = RelationshipLedgerRepository(connection)
    source = _current_snapshot(connection)
    connection.execute("DROP TRIGGER trg_memory_versions_append_only_update")
    connection.execute(
        f"UPDATE memory_versions SET {column} = ? WHERE id = ?",
        (value, "version-1"),
    )
    connection.commit()

    with pytest.raises(ValueError):
        with ledger.write_transaction():
            ledger.append_apply(
                source=source,
                mapping=_mapping(source),
                created_at=_VERSION_CREATED_AT,
            )


def test_append_apply_rejects_authority_change_after_snapshot(
    connection: sqlite3.Connection,
) -> None:
    ledger = RelationshipLedgerRepository(connection)
    source = _current_snapshot(connection)
    RelationshipAuthorityService(connection, ledger=ledger).suppress(
        source_memory_id=source.source_memory_id,
        event_type=RelationshipEventType.SHARED_EXPERIENCE,
        subject_code="shared_experience",
        action_kind=RelationshipAuthorityActionKind.USER_REVOKE,
        reason_code="user_revoked",
        expected_decision_id=source.effective_authority_decision_id,
        expected_decision_generation=source.effective_authority_generation,
        expected_authority_epoch=source.authority_epoch,
    )

    with pytest.raises(ValueError):
        with ledger.write_transaction():
            ledger.append_apply(
                source=source,
                mapping=_mapping(source),
                created_at=_VERSION_CREATED_AT,
            )
    assert connection.execute(
        "SELECT COUNT(*) FROM relationship_events"
    ).fetchone()[0] == 0


def test_existing_apply_corruption_is_rejected_by_duplicate_revoke_and_redaction(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'corrupt-apply.db'}") as connection:
        _insert_persona(connection)
        _insert_source(
            connection,
            subject_code="preferred_address",
            content="小雪",
        )
        connection.commit()
        ledger = RelationshipLedgerRepository(connection)
        source = _current_snapshot(
            connection,
            event_type=RelationshipEventType.PREFERRED_ADDRESS,
        )
        with ledger.write_transaction():
            apply = ledger.append_apply(
                source=source,
                mapping=_mapping(source),
                created_at=_VERSION_CREATED_AT,
            )
        connection.execute("DROP TRIGGER trg_relationship_events_append_only_update")
        connection.execute(
            "UPDATE relationship_events SET integrity_fingerprint = ? WHERE id = ?",
            ("f" * 64, apply.id),
        )
        connection.commit()

        with pytest.raises(ValueError):
            with ledger.write_transaction():
                ledger.append_apply(
                    source=source,
                    mapping=_mapping(source),
                    created_at=_VERSION_CREATED_AT,
                )
        with pytest.raises(ValueError):
            with ledger.write_transaction():
                ledger.append_revoke(
                    apply_event_id=apply.id,
                    created_at=_VERSION_CREATED_AT,
                )
        with pytest.raises(ValueError):
            with ledger.write_transaction():
                ledger.redact_preferred_address(
                    apply_event_id=apply.id,
                    created_at=_VERSION_CREATED_AT,
                )


def test_existing_event_rejects_noncanonical_payload_and_fixed_versions(
    connection: sqlite3.Connection,
) -> None:
    ledger = RelationshipLedgerRepository(connection)
    source = _current_snapshot(connection)
    with ledger.write_transaction():
        apply = ledger.append_apply(
            source=source,
            mapping=_mapping(source),
            created_at=_VERSION_CREATED_AT,
        )
    connection.execute("DROP TRIGGER trg_relationship_events_append_only_update")
    for assignment in (
        "payload_json = ?",
        "event_schema_version = ?",
        "observed_time_derivation_version = ?",
    ):
        original = connection.execute(
            "SELECT payload_json, event_schema_version, "
            "observed_time_derivation_version FROM relationship_events WHERE id = ?",
            (apply.id,),
        ).fetchone()
        value = (
            '{"reason_code":"allowlisted_current_memory", "delta":0.04, '
            '"category":"shared_experience"}'
            if assignment.startswith("payload_json")
            else "unsupported-version"
        )
        connection.execute(
            f"UPDATE relationship_events SET {assignment} WHERE id = ?",
            (value, apply.id),
        )
        connection.commit()
        with pytest.raises(ValueError):
            with ledger.write_transaction():
                ledger.append_revoke(
                    apply_event_id=apply.id,
                    created_at=_VERSION_CREATED_AT,
                )
        connection.execute(
            """
            UPDATE relationship_events
            SET payload_json = ?, event_schema_version = ?,
                observed_time_derivation_version = ?
            WHERE id = ?
            """,
            (*tuple(original), apply.id),
        )
        connection.commit()


def test_existing_revoke_corruption_is_rejected(
    connection: sqlite3.Connection,
) -> None:
    ledger = RelationshipLedgerRepository(connection)
    source = _current_snapshot(connection)
    with ledger.write_transaction():
        apply = ledger.append_apply(
            source=source,
            mapping=_mapping(source),
            created_at=_VERSION_CREATED_AT,
        )
    with ledger.write_transaction():
        revoke = ledger.append_revoke(
            apply_event_id=apply.id,
            created_at=_VERSION_CREATED_AT + timedelta(minutes=1),
        )
    connection.execute("DROP TRIGGER trg_relationship_events_append_only_update")
    connection.execute(
        "UPDATE relationship_events SET integrity_fingerprint = ? WHERE id = ?",
        ("e" * 64, revoke.id),
    )
    connection.commit()

    with pytest.raises(ValueError):
        with ledger.write_transaction():
            ledger.append_revoke(
                apply_event_id=apply.id,
                created_at=_VERSION_CREATED_AT + timedelta(minutes=2),
            )


def test_revoke_is_idempotent_and_contains_no_readable_payload(
    connection: sqlite3.Connection,
) -> None:
    ledger = RelationshipLedgerRepository(connection)
    source = _current_snapshot(connection)
    with ledger.write_transaction():
        apply = ledger.append_apply(
            source=source,
            mapping=_mapping(source),
            created_at=_VERSION_CREATED_AT,
        )
    with ledger.write_transaction():
        revoke = ledger.append_revoke(
            apply_event_id=apply.id,
            created_at=_VERSION_CREATED_AT + timedelta(minutes=1),
        )
    with ledger.write_transaction():
        duplicate = ledger.append_revoke(
            apply_event_id=apply.id,
            created_at=_VERSION_CREATED_AT + timedelta(minutes=2),
        )

    assert duplicate == revoke
    assert revoke.event_kind is RelationshipEventKind.REVOKE
    assert revoke.revokes_event_id == apply.id
    assert revoke.payload is None
    assert revoke.payload_state is RelationshipPayloadState.ACTIVE
    rows = connection.execute(
        """
        SELECT event_kind, payload_json, revokes_event_id
        FROM relationship_events ORDER BY created_at, id
        """
    ).fetchall()
    assert len(rows) == 2
    revoke_row = next(row for row in rows if row["event_kind"] == "revoke")
    assert revoke_row["payload_json"] is None
    assert revoke_row["revokes_event_id"] == apply.id


def test_revoke_rejects_missing_revoke_target_and_cross_scope(
    connection: sqlite3.Connection,
) -> None:
    ledger = RelationshipLedgerRepository(connection)
    with pytest.raises(ValueError):
        with ledger.write_transaction():
            ledger.append_revoke(
                apply_event_id="missing",
                created_at=_VERSION_CREATED_AT,
            )

    source = _current_snapshot(connection)
    with ledger.write_transaction():
        apply = ledger.append_apply(
            source=source,
            mapping=_mapping(source),
            created_at=_VERSION_CREATED_AT,
        )
    with ledger.write_transaction():
        revoke = ledger.append_revoke(
            apply_event_id=apply.id,
            created_at=_VERSION_CREATED_AT + timedelta(minutes=1),
        )
    with pytest.raises(ValueError):
        with ledger.write_transaction():
            ledger.append_revoke(
                apply_event_id=revoke.id,
                created_at=_VERSION_CREATED_AT + timedelta(minutes=2),
            )
    with pytest.raises(ValueError):
        with ledger.write_transaction():
            ledger.append_revoke(
                apply_event_id=apply.id,
                created_at=_VERSION_CREATED_AT + timedelta(minutes=2),
                scope_id="other",
            )


def test_preferred_address_redaction_ensures_revoke_and_consumes_guard(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'redaction.db'}") as connection:
        _insert_persona(connection)
        _insert_source(
            connection,
            subject_code="preferred_address",
            content="小雪",
        )
        connection.commit()
        ledger = RelationshipLedgerRepository(connection)
        source = _current_snapshot(
            connection,
            event_type=RelationshipEventType.PREFERRED_ADDRESS,
        )
        with ledger.write_transaction():
            apply = ledger.append_apply(
                source=source,
                mapping=_mapping(source),
                created_at=_VERSION_CREATED_AT,
            )

        with ledger.write_transaction():
            redacted, revoke = ledger.redact_preferred_address(
                apply_event_id=apply.id,
                created_at=_VERSION_CREATED_AT + timedelta(minutes=1),
            )

        assert redacted.id == apply.id
        assert redacted.payload_state is RelationshipPayloadState.REDACTED
        assert redacted.payload is None
        assert revoke.revokes_event_id == apply.id
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_redaction_guards"
        ).fetchone()[0] == 0
        raw = connection.execute(
            "SELECT payload_json, payload_state FROM relationship_events WHERE id=?",
            (apply.id,),
        ).fetchone()
        assert tuple(raw) == (None, "redacted")
        assert "小雪" not in "\n".join(
            str(tuple(row))
            for row in connection.execute(
                "SELECT payload_json FROM relationship_events"
            ).fetchall()
        )

        with ledger.write_transaction():
            again, duplicate_revoke = ledger.redact_preferred_address(
                apply_event_id=apply.id,
                created_at=_VERSION_CREATED_AT + timedelta(minutes=2),
            )
        assert again == redacted
        assert duplicate_revoke == revoke
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events"
        ).fetchone()[0] == 2
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE relationship_events SET payload_json='{}', "
                "payload_state='active' WHERE id=?",
                (apply.id,),
            )
        connection.rollback()


def test_non_address_apply_cannot_be_redacted(connection: sqlite3.Connection) -> None:
    ledger = RelationshipLedgerRepository(connection)
    source = _current_snapshot(connection)
    with ledger.write_transaction():
        apply = ledger.append_apply(
            source=source,
            mapping=_mapping(source),
            created_at=_VERSION_CREATED_AT,
        )
    with pytest.raises(ValueError):
        with ledger.write_transaction():
            ledger.redact_preferred_address(
                apply_event_id=apply.id,
                created_at=_VERSION_CREATED_AT,
            )
    assert connection.execute(
        "SELECT COUNT(*) FROM relationship_redaction_guards"
    ).fetchone()[0] == 0
