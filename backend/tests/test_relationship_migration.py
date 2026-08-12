from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.repositories.relationship_migration import migrate_gate_c3
from app.repositories.sqlite import connect, init_db, managed_connection


_C3_TABLES = {
    "relationship_events",
    "relationship_authority_decisions",
    "relationship_authority_epoch",
    "relationship_memory_lineage",
    "relationship_reconcile_jobs",
    "relationship_job_audits",
    "relationship_audits",
    "relationship_projections",
    "relationship_projection_active_state",
    "relationship_redaction_guards",
}


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in connection.execute(f'PRAGMA table_info("{table}")')
    }


def test_gate_c3_migration_requires_caller_owned_transaction(tmp_path: Path) -> None:
    connection = connect(f"sqlite:///{tmp_path / 'caller-owned.db'}")
    try:
        with pytest.raises(RuntimeError, match="caller-owned transaction"):
            migrate_gate_c3(connection)
    finally:
        connection.close()


def test_fresh_database_contains_transactional_gate_c3_schema(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'fresh-c3.db'}"

    with managed_connection(database_url) as connection:
        tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert _C3_TABLES <= tables
        assert "canonical_subject_code" in _columns(connection, "memory_versions")
        assert connection.execute(
            "SELECT generation FROM relationship_authority_epoch "
            "WHERE scope_id='default'"
        ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

        memory_sql = str(
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' "
                "AND name='memory_versions'"
            ).fetchone()[0]
        )
        assert "canonical_subject_code" in memory_sql
        for code in (
            "preferred_address",
            "shared_experience",
            "non_external_commitment",
        ):
            assert code in memory_sql

        trigger_sql = str(
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='trigger' "
                "AND name='trg_memory_versions_append_only_update'"
            ).fetchone()[0]
        )
        assert "OLD.canonical_subject_code IS NEW.canonical_subject_code" in trigger_sql


def test_gate_c3_migration_preserves_existing_rows_and_never_guesses_subject(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'upgrade-c3.db'}"
    with managed_connection(database_url) as connection:
        connection.execute(
            "INSERT INTO memories (id, content, memory_type, source, importance, "
            "confidence, status, metadata_json, created_at, updated_at) VALUES "
            "('memory-legacy', '用户希望被称为小雪', 'preference', 'manual', 3, "
            "1.0, 'active', '{\"canonical_subject\":\"preferred_address\"}', "
            "'2026-07-01T00:00:00+00:00', '2026-07-01T00:00:00+00:00')"
        )
        connection.execute(
            "INSERT INTO memory_versions (id, memory_id, version_number, "
            "parent_version_id, operation, memory_type, subject, content, "
            "content_hash, canonical_key_hash, subject_key_hash, "
            "canonicalization_version, confidence, importance, source_kind, "
            "source_session_id, source_session_reference_hash, "
            "writer_policy_version, created_at, redacted_at, "
            "canonical_subject_code) VALUES "
            "('version-legacy', 'memory-legacy', 1, NULL, 'create', 'preference', "
            "'preferred_address', '用户希望被称为小雪', 'hash', NULL, NULL, "
            "'memory-canonicalization-v1', 1.0, 3, 'manual', NULL, NULL, "
            "'manual-write-v1', '2026-07-01T00:00:00+00:00', NULL, NULL)"
        )
        connection.commit()

    with managed_connection(database_url) as connection:
        row = connection.execute(
            "SELECT subject, content, canonical_subject_code FROM memory_versions "
            "WHERE id='version-legacy'"
        ).fetchone()
        assert tuple(row) == (
            "preferred_address",
            "用户希望被称为小雪",
            None,
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_scrubs_experimental_projection_address_column(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'experimental-c3.db'}"
    connection = connect(database_url)
    try:
        init_db(connection)
        connection.execute(
            "ALTER TABLE relationship_projections ADD COLUMN preferred_address TEXT"
        )
        connection.execute(
            "INSERT INTO persona_artifacts (id, version, payload_state, "
            "schema_version, ruleset_version, template_version, compiler_version, "
            "source_content_json, rendered_system_prompt, content_identity_hash, "
            "behavior_fingerprint, created_at) VALUES "
            "('persona-1', 1, 'active', 'persona-schema-v1', 'persona-ruleset-v1', "
            "'persona-template-v1', 'persona-compiler-v1', '{}', 'prompt', "
            "? , ?, '2026-07-01T00:00:00+00:00')",
            ("a" * 64, "b" * 64),
        )
        connection.execute(
            "INSERT INTO relationship_projections (projection_id, version, scope_id, "
            "persona_artifact_id, projection_rule_version, familiarity, "
            "preferred_address_event_id, relationship_summary_code, "
            "source_relationship_event_ids_json, source_emotion_snapshot_id, "
            "computed_at, integrity_fingerprint, preferred_address) VALUES "
            "('projection-1', 1, 'default', 'persona-1', "
            "'relationship-projection-v1', 0.4, NULL, 'steady', '[]', NULL, "
            "'2026-07-01T00:00:00+00:00', ?, 'PRIVATE_ADDRESS')",
            ("c" * 64,),
        )
        connection.commit()

        connection.execute("BEGIN")
        migrate_gate_c3(connection)
        connection.commit()

        assert connection.execute(
            "SELECT preferred_address FROM relationship_projections"
        ).fetchone()[0] is None
    finally:
        connection.close()


def test_migration_scrubs_both_experimental_projection_address_columns(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'experimental-c3-both.db'}"
    connection = connect(database_url)
    try:
        init_db(connection)
        connection.execute(
            "ALTER TABLE relationship_projections ADD COLUMN preferred_address TEXT"
        )
        connection.execute(
            "ALTER TABLE relationship_projections ADD COLUMN preferred_address_text TEXT"
        )
        connection.execute(
            "INSERT INTO persona_artifacts (id, version, payload_state, schema_version, "
            "ruleset_version, template_version, compiler_version, source_content_json, "
            "rendered_system_prompt, content_identity_hash, behavior_fingerprint, "
            "created_at) VALUES ('persona-1', 1, 'active', 'persona-schema-v1', "
            "'persona-ruleset-v1', 'persona-template-v1', 'persona-compiler-v1', "
            "'{}', 'prompt', ?, ?, '2026-07-01T00:00:00+00:00')",
            ("a" * 64, "b" * 64),
        )
        connection.execute(
            "INSERT INTO relationship_projections (projection_id, version, scope_id, "
            "persona_artifact_id, projection_rule_version, familiarity, "
            "preferred_address_event_id, relationship_summary_code, "
            "source_relationship_event_ids_json, source_emotion_snapshot_id, "
            "computed_at, integrity_fingerprint, preferred_address, "
            "preferred_address_text) VALUES ('projection-1', 1, 'default', "
            "'persona-1', 'relationship-projection-v1', 0.4, NULL, 'steady', '[]', "
            "NULL, '2026-07-01T00:00:00+00:00', ?, 'PRIVATE_ONE', 'PRIVATE_TWO')",
            ("c" * 64,),
        )
        connection.commit()

        connection.execute("BEGIN")
        migrate_gate_c3(connection)
        connection.commit()

        assert tuple(
            connection.execute(
                "SELECT preferred_address, preferred_address_text "
                "FROM relationship_projections"
            ).fetchone()
        ) == (None, None)
    finally:
        connection.close()


def test_gate_c3_migration_fault_rolls_back_column_tables_and_scrub(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'rollback-c3.db'}"
    connection = connect(database_url)
    try:
        # Build the complete pre-C3 schema by temporarily skipping only C3.
        import app.repositories.sqlite as sqlite_module

        original = sqlite_module.migrate_gate_c3
        sqlite_module.migrate_gate_c3 = lambda _connection: None
        try:
            init_db(connection)
        finally:
            sqlite_module.migrate_gate_c3 = original
        connection.commit()
        assert "canonical_subject_code" not in _columns(
            connection, "memory_versions"
        )

        connection.execute("BEGIN")
        with pytest.raises(RuntimeError, match="Gate C3 migration fault"):
            migrate_gate_c3(
                connection,
                fault_injector=lambda point: (
                    (_ for _ in ()).throw(RuntimeError("Gate C3 migration fault"))
                    if point == "post_schema"
                    else None
                ),
            )
        connection.rollback()

        assert "canonical_subject_code" not in _columns(
            connection, "memory_versions"
        )
        tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert tables.isdisjoint(_C3_TABLES)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()
