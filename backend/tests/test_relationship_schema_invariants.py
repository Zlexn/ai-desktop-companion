from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.repositories.sqlite import managed_connection


def _insert_memory_version(
    connection: sqlite3.Connection,
    *,
    memory_id: str,
    version_id: str,
    canonical_subject_code: str | None,
) -> None:
    now = datetime.now(UTC).isoformat()
    connection.execute(
        "INSERT INTO memories (id, content, memory_type, source, importance, "
        "confidence, status, metadata_json, created_at, updated_at) "
        "VALUES (?, '小雪', 'preference', 'manual', 3, 1.0, 'active', '{}', ?, ?)",
        (memory_id, now, now),
    )
    connection.execute(
        "INSERT INTO memory_versions (id, memory_id, version_number, "
        "parent_version_id, operation, memory_type, subject, content, "
        "content_hash, canonical_key_hash, subject_key_hash, "
        "canonicalization_version, confidence, importance, source_kind, "
        "source_session_id, source_session_reference_hash, "
        "writer_policy_version, created_at, redacted_at, "
        "canonical_subject_code) VALUES (?, ?, 1, NULL, 'create', 'preference', "
        "'address', '小雪', 'hash', NULL, NULL, 'memory-canonicalization-v1', "
        "1.0, 3, 'manual', NULL, NULL, 'manual-write-v1', ?, NULL, ?)",
        (version_id, memory_id, now, canonical_subject_code),
    )


def _insert_persona(connection: sqlite3.Connection, persona_id: str = "persona-1") -> None:
    connection.execute(
        "INSERT INTO persona_artifacts (id, version, payload_state, schema_version, "
        "ruleset_version, template_version, compiler_version, source_content_json, "
        "rendered_system_prompt, content_identity_hash, behavior_fingerprint, "
        "created_at) VALUES (?, 1, 'active', 'persona-schema-v1', "
        "'persona-ruleset-v1', 'persona-template-v1', 'persona-compiler-v1', "
        "'{}', 'prompt', ?, ?, ?)",
        (persona_id, "a" * 64, "b" * 64, datetime.now(UTC).isoformat()),
    )


def _insert_apply(
    connection: sqlite3.Connection,
    *,
    event_id: str = "apply-1",
    scope_id: str = "default",
    memory_id: str = "memory-1",
    version_id: str = "version-1",
    event_type: str = "preferred_address",
    subject_code: str = "preferred_address",
    payload_json: str = '{"address":"小雪"}',
) -> None:
    now = datetime.now(UTC).isoformat()
    connection.execute(
        "INSERT INTO relationship_events (id, scope_id, event_kind, event_type, "
        "subject_code, payload_state, payload_json, source_memory_id, "
        "source_memory_version_id, observed_at, observed_time_derivation_version, "
        "revokes_event_id, rule_version, persona_artifact_id, event_schema_version, "
        "integrity_fingerprint, created_at) VALUES "
        "(?, ?, 'apply', ?, ?, 'active', ?, ?, ?, ?, "
        "'memory-version-created-at-utc-v1', NULL, 'relationship-rules-v1', "
        "'persona-1', 'relationship-event-v1', ?, ?)",
        (
            event_id,
            scope_id,
            event_type,
            subject_code,
            payload_json,
            memory_id,
            version_id,
            now,
            "c" * 64,
            now,
        ),
    )


@pytest.fixture
def connection(tmp_path: Path):
    with managed_connection(f"sqlite:///{tmp_path / 'c3-invariants.db'}") as current:
        _insert_persona(current)
        _insert_memory_version(
            current,
            memory_id="memory-1",
            version_id="version-1",
            canonical_subject_code="preferred_address",
        )
        current.commit()
        yield current


def test_memory_version_subject_code_is_immutable(connection: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute(
            "UPDATE memory_versions SET canonical_subject_code=NULL "
            "WHERE id='version-1'"
        )
    connection.rollback()

    with pytest.raises(sqlite3.IntegrityError):
        _insert_memory_version(
            connection,
            memory_id="memory-invalid",
            version_id="version-invalid",
            canonical_subject_code="unknown",
        )
    connection.rollback()

    now = datetime.now(UTC).isoformat()
    connection.execute(
        "INSERT INTO memories (id, content, memory_type, source, importance, "
        "confidence, status, metadata_json, created_at, updated_at) VALUES "
        "('memory-invalid-pair', 'event', 'important_event', 'manual', 3, 1.0, "
        "'active', '{}', ?, ?)",
        (now, now),
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO memory_versions (id, memory_id, version_number, "
            "parent_version_id, operation, memory_type, subject, content, "
            "content_hash, canonicalization_version, confidence, importance, "
            "source_kind, writer_policy_version, created_at, canonical_subject_code) "
            "VALUES ('version-invalid-pair', 'memory-invalid-pair', 1, NULL, "
            "'create', 'important_event', 'address', 'event', 'hash', "
            "'memory-canonicalization-v1', 1.0, 3, 'manual', 'manual-write-v1', "
            "?, 'preferred_address')",
            (now,),
        )
    connection.rollback()


def test_relationship_apply_requires_matching_explicit_source_classification(
    connection: sqlite3.Connection,
) -> None:
    _insert_memory_version(
        connection,
        memory_id="memory-uncoded",
        version_id="version-uncoded",
        canonical_subject_code=None,
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="classification"):
        _insert_apply(
            connection,
            event_id="apply-uncoded",
            memory_id="memory-uncoded",
            version_id="version-uncoded",
        )
    connection.rollback()


def test_relationship_apply_identity_is_unique(connection: sqlite3.Connection) -> None:
    _insert_apply(connection)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_apply(connection, event_id="apply-duplicate")
    connection.rollback()


def test_revoke_requires_same_scope_apply_and_has_no_payload(
    connection: sqlite3.Connection,
) -> None:
    _insert_apply(connection)
    now = datetime.now(UTC).isoformat()
    connection.execute(
        "INSERT INTO relationship_events (id, scope_id, event_kind, event_type, "
        "subject_code, payload_state, payload_json, source_memory_id, "
        "source_memory_version_id, observed_at, observed_time_derivation_version, "
        "revokes_event_id, rule_version, persona_artifact_id, event_schema_version, "
        "integrity_fingerprint, created_at) VALUES "
        "('revoke-1', 'default', 'revoke', 'preferred_address', "
        "'preferred_address', 'active', NULL, 'memory-1', 'version-1', ?, "
        "'memory-version-created-at-utc-v1', 'apply-1', 'relationship-rules-v1', "
        "'persona-1', 'relationship-event-v1', ?, ?)",
        (now, "d" * 64, now),
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO relationship_events SELECT 'revoke-2', scope_id, "
            "'revoke', event_type, subject_code, payload_state, payload_json, "
            "source_memory_id, source_memory_version_id, observed_at, "
            "observed_time_derivation_version, id, rule_version, persona_artifact_id, "
            "event_schema_version, integrity_fingerprint, created_at "
            "FROM relationship_events WHERE id='revoke-1'"
        )
    connection.rollback()

    _insert_apply(connection, event_id="apply-2")
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO relationship_events SELECT 'bad-revoke', 'other', "
            "'revoke', event_type, subject_code, payload_state, NULL, "
            "source_memory_id, source_memory_version_id, observed_at, "
            "observed_time_derivation_version, id, rule_version, persona_artifact_id, "
            "event_schema_version, integrity_fingerprint, created_at "
            "FROM relationship_events WHERE id='apply-2'"
        )
    connection.rollback()


def test_event_update_delete_and_redaction_guard_are_constrained(
    connection: sqlite3.Connection,
) -> None:
    _insert_apply(connection)
    connection.commit()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute(
            "UPDATE relationship_events SET payload_json=NULL, "
            "payload_state='redacted' WHERE id='apply-1'"
        )
    connection.rollback()

    connection.execute(
        "INSERT INTO relationship_redaction_guards (event_id, created_at) "
        "VALUES ('apply-1', ?)",
        (datetime.now(UTC).isoformat(),),
    )
    connection.execute(
        "UPDATE relationship_events SET payload_json=NULL, "
        "payload_state='redacted' WHERE id='apply-1'"
    )
    connection.execute(
        "DELETE FROM relationship_redaction_guards WHERE event_id='apply-1'"
    )
    assert tuple(
        connection.execute(
            "SELECT payload_json, payload_state FROM relationship_events "
            "WHERE id='apply-1'"
        ).fetchone()
    ) == (None, "redacted")
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE relationship_events SET payload_json='{}', "
            "payload_state='active' WHERE id='apply-1'"
        )
    connection.rollback()

    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        connection.execute("DELETE FROM relationship_events WHERE id='apply-1'")
    connection.rollback()


def test_authority_decision_requires_linear_generation_and_epoch_cas(
    connection: sqlite3.Connection,
) -> None:
    now = datetime.now(UTC).isoformat()
    connection.execute(
        "INSERT INTO relationship_authority_decisions (id, scope_id, "
        "source_memory_id, event_type, subject_code, predecessor_decision_id, "
        "generation, action, action_kind, reason_code, "
        "inherited_authority_fingerprint, created_at) VALUES "
        "('decision-1', 'default', 'memory-1', 'preferred_address', "
        "'preferred_address', NULL, 1, 'suppress', 'user_revoke', "
        "'user_relationship_revoke', NULL, ?)",
        (now,),
    )
    assert connection.execute(
        "SELECT generation FROM relationship_authority_epoch WHERE scope_id='default'"
    ).fetchone()[0] == 1
    connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO relationship_authority_decisions (id, scope_id, "
            "source_memory_id, event_type, subject_code, predecessor_decision_id, "
            "generation, action, action_kind, reason_code, "
            "inherited_authority_fingerprint, created_at) VALUES "
            "('decision-gap', 'default', 'memory-1', 'preferred_address', "
            "'preferred_address', 'decision-1', 3, 'reenable', 'user_reenable', "
            "'user_relationship_reenable', ?, ?)",
            ("e" * 64, now),
        )
    connection.rollback()

    connection.execute(
        "UPDATE relationship_authority_epoch SET generation=2, updated_at=? "
        "WHERE scope_id='default' AND generation=1",
        (now,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE relationship_authority_epoch SET generation=4, updated_at=? "
            "WHERE scope_id='default'",
            (now,),
        )
    connection.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "DELETE FROM relationship_authority_decisions WHERE id='decision-1'"
        )
    connection.rollback()


def test_lineage_and_job_snapshot_are_immutable(connection: sqlite3.Connection) -> None:
    now = datetime.now(UTC).isoformat()
    connection.execute(
        "INSERT INTO memories (id, content, memory_type, source, importance, "
        "confidence, status, metadata_json, created_at, updated_at) VALUES "
        "('memory-resolved', 'resolved', 'preference', 'manual', 3, 1.0, "
        "'active', '{}', ?, ?)",
        (now, now),
    )
    connection.execute(
        "INSERT INTO memory_conflicts (conflict_id, left_memory_id, "
        "right_memory_id, status, resolution_kind, resolved_memory_id, "
        "created_at, resolved_at) VALUES "
        "('conflict-1', 'memory-1', 'memory-resolved', 'resolved', "
        "'choose_left', 'memory-resolved', ?, ?)",
        (now, now),
    )
    connection.execute(
        "INSERT INTO relationship_memory_lineage (resolved_memory_id, "
        "contributing_memory_id, conflict_id, resolution_kind, created_at) "
        "VALUES ('memory-resolved', 'memory-1', 'conflict-1', 'choose_left', ?)",
        (now,),
    )
    assert connection.execute(
        "SELECT generation FROM relationship_authority_epoch WHERE scope_id='default'"
    ).fetchone()[0] == 1
    connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE relationship_memory_lineage SET resolution_kind='choose_right'"
        )
    connection.rollback()

    connection.execute(
        "INSERT INTO relationship_reconcile_jobs (id, scope_id, source_memory_id, "
        "source_memory_version_id, captured_record_head_version, "
        "captured_record_generation, captured_record_state, captured_event_type, "
        "captured_subject_code, captured_authority_decision_id, "
        "captured_authority_generation, captured_authority_epoch, "
        "captured_inherited_authority_fingerprint, relationship_rule_version, "
        "persona_artifact_id, job_schema_version, status, attempt_count, "
        "created_at) VALUES ('job-1', 'default', 'memory-1', 'version-1', 1, 0, "
        "'active', 'preferred_address', 'preferred_address', NULL, 0, 0, ?, "
        "'relationship-rules-v1', 'persona-1', 'relationship-reconcile-job-v1', "
        "'pending', 0, ?)",
        ("f" * 64, now),
    )
    with pytest.raises(sqlite3.IntegrityError, match="snapshot"):
        connection.execute(
            "UPDATE relationship_reconcile_jobs SET captured_record_generation=2 "
            "WHERE id='job-1'"
        )
    connection.rollback()


def test_projection_is_immutable_and_active_pointer_uses_cas(
    connection: sqlite3.Connection,
) -> None:
    now = datetime.now(UTC).isoformat()
    connection.execute(
        "INSERT INTO relationship_projections (projection_id, version, scope_id, "
        "persona_artifact_id, projection_rule_version, familiarity, "
        "preferred_address_event_id, relationship_summary_code, "
        "source_relationship_event_ids_json, source_emotion_snapshot_id, "
        "computed_at, integrity_fingerprint) VALUES "
        "('projection-1', 1, 'default', 'persona-1', "
        "'relationship-projection-v1', 0.4, NULL, 'steady', '[]', NULL, ?, ?)",
        (now, "a" * 64),
    )
    connection.execute(
        "INSERT INTO relationship_projection_active_state (scope_id, projection_id, "
        "projection_version, generation, updated_at) VALUES "
        "('default', 'projection-1', 1, 0, ?)",
        (now,),
    )
    connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE relationship_projections SET familiarity=0.5 "
            "WHERE projection_id='projection-1'"
        )
    connection.rollback()

    connection.execute(
        "INSERT INTO relationship_projections SELECT 'projection-2', 2, scope_id, "
        "persona_artifact_id, projection_rule_version, familiarity, "
        "preferred_address_event_id, relationship_summary_code, "
        "source_relationship_event_ids_json, source_emotion_snapshot_id, ?, "
        "integrity_fingerprint FROM relationship_projections "
        "WHERE projection_id='projection-1'",
        (now,),
    )
    connection.execute(
        "UPDATE relationship_projection_active_state SET projection_id='projection-2', "
        "projection_version=2, generation=1, updated_at=? "
        "WHERE scope_id='default' AND generation=0",
        (now,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE relationship_projection_active_state SET "
            "projection_id='projection-1', projection_version=1, generation=2, "
            "updated_at=? WHERE scope_id='default'",
            (now,),
        )
    connection.rollback()

    connection.execute(
        "INSERT INTO relationship_projections SELECT 'projection-2', 2, scope_id, "
        "persona_artifact_id, projection_rule_version, familiarity, "
        "preferred_address_event_id, relationship_summary_code, "
        "source_relationship_event_ids_json, source_emotion_snapshot_id, ?, "
        "integrity_fingerprint FROM relationship_projections "
        "WHERE projection_id='projection-1'",
        (now,),
    )
    connection.execute(
        "UPDATE relationship_projection_active_state SET projection_id='projection-2', "
        "projection_version=2, generation=1, updated_at=? "
        "WHERE scope_id='default' AND generation=0",
        (now,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE relationship_projection_active_state SET "
            "projection_id='projection-1', projection_version=1, generation=3, "
            "updated_at=? WHERE scope_id='default'",
            (now,),
        )
    connection.rollback()


def test_relationship_audits_are_metadata_only_and_append_only(
    connection: sqlite3.Connection,
) -> None:
    now = datetime.now(UTC).isoformat()
    connection.execute(
        "INSERT INTO relationship_audits (id, action, outcome, reason_code, "
        "source_memory_id, event_id, projection_id, created_at) VALUES "
        "('audit-1', 'reconciled', 'no_change', 'unchanged', "
        "'memory-1', NULL, NULL, ?) ",
        (now,),
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute(
            "UPDATE relationship_audits SET reason_code='changed' WHERE id='audit-1'"
        )
    connection.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        connection.execute("DELETE FROM relationship_audits WHERE id='audit-1'")
    connection.rollback()
