import sqlite3
from pathlib import Path

import pytest

from app.repositories import sqlite as sqlite_repository
from app.repositories.sqlite import (
    connect,
    init_db,
    memory_source_references_exist,
)


GATE_B_TABLES = {
    "memory_write_consents",
    "memory_record_states",
    "memory_versions",
    "memory_evidence",
    "memory_evidence_retractions",
    "memory_conflicts",
    "memory_write_activities",
    "memory_deletion_generations",
    "memory_tombstones",
    "memory_summary_barrier",
    "memory_summary_source_exclusions",
}


def _create_gate_a_database(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );

        CREATE TABLE session_summaries (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            summary_text TEXT NOT NULL,
            source TEXT NOT NULL CHECK (source IN ('manual', 'generated')),
            covered_message_start_id TEXT,
            covered_message_end_id TEXT,
            message_count INTEGER NOT NULL CHECK (message_count >= 0),
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (covered_message_start_id) REFERENCES messages(id) ON DELETE SET NULL,
            FOREIGN KEY (covered_message_end_id) REFERENCES messages(id) ON DELETE SET NULL
        );

        CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            memory_type TEXT NOT NULL CHECK (memory_type IN ('user_fact', 'preference', 'long_term_goal', 'important_event', 'relationship_event', 'other')),
            source TEXT NOT NULL CHECK (source IN ('manual', 'candidate')),
            source_session_id TEXT,
            importance INTEGER NOT NULL CHECK (importance BETWEEN 1 AND 5),
            confidence REAL NOT NULL CHECK (confidence BETWEEN 0.0 AND 1.0),
            status TEXT NOT NULL CHECK (status IN ('active', 'archived', 'pending', 'dismissed')),
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (source_session_id) REFERENCES sessions(id) ON DELETE SET NULL
        );

        CREATE TABLE memory_embeddings (
            memory_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            dimension INTEGER NOT NULL CHECK (dimension > 0),
            embedding_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
        );

        CREATE TABLE memory_extraction_consents (
            scope_id TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK (status IN ('unknown', 'granted', 'declined', 'revoked')),
            purpose TEXT,
            provider TEXT,
            disclosure_version TEXT,
            disclosed_fields_json TEXT NOT NULL DEFAULT '[]',
            generation INTEGER NOT NULL CHECK (generation >= 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE memory_jobs (
            id TEXT PRIMARY KEY,
            turn_id TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            session_id TEXT NOT NULL,
            user_message_id TEXT NOT NULL,
            assistant_message_id TEXT NOT NULL,
            mode TEXT NOT NULL CHECK (mode = 'shadow_auto'),
            extractor_route TEXT NOT NULL CHECK (extractor_route IN ('none', 'local', 'fake', 'remote')),
            status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            outcome TEXT CHECK (outcome IS NULL OR outcome IN (
                'shadow_recorded', 'skipped_no_extractor', 'skipped_no_consent',
                'skipped_consent_changed', 'skipped_governor_policy',
                'invalid_output', 'provider_error', 'cancelled', 'failed'
            )),
            error_category TEXT CHECK (error_category IS NULL OR error_category IN (
                'invalid_output', 'provider_error', 'invalid_job_input',
                'interrupted', 'database_error'
            )),
            governor_version TEXT NOT NULL,
            consent_generation INTEGER,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            UNIQUE (turn_id, schema_version),
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (user_message_id) REFERENCES messages(id) ON DELETE CASCADE,
            FOREIGN KEY (assistant_message_id) REFERENCES messages(id) ON DELETE CASCADE
        );

        CREATE TABLE memory_job_audits (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            outcome TEXT NOT NULL CHECK (outcome IN (
                'shadow_recorded', 'skipped_no_extractor', 'skipped_no_consent',
                'skipped_consent_changed', 'skipped_governor_policy',
                'invalid_output', 'provider_error', 'cancelled', 'failed'
            )),
            decision_counts_json TEXT NOT NULL,
            reason_counts_json TEXT NOT NULL,
            proposal_count INTEGER NOT NULL CHECK (proposal_count >= 0),
            accepted_count INTEGER NOT NULL CHECK (accepted_count >= 0),
            rejected_count INTEGER NOT NULL CHECK (rejected_count >= 0),
            redaction_count INTEGER NOT NULL CHECK (redaction_count >= 0),
            provider TEXT,
            model TEXT,
            elapsed_ms INTEGER CHECK (elapsed_ms IS NULL OR elapsed_ms >= 0),
            schema_version TEXT NOT NULL,
            governor_version TEXT NOT NULL,
            consent_generation INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES memory_jobs(id) ON DELETE CASCADE,
            UNIQUE (job_id)
        );
        """
    )
    connection.execute(
        "INSERT INTO sessions VALUES (?, ?, ?, ?)",
        ("session-1", "legacy", "2026-07-01T00:00:00Z", "2026-07-01T00:00:00Z"),
    )
    connection.executemany(
        "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)",
        (
            ("user-1", "session-1", "user", "private user turn", "{}", "2026-07-01T00:00:01Z"),
            ("assistant-1", "session-1", "assistant", "private reply", "{}", "2026-07-01T00:00:02Z"),
        ),
    )
    connection.executemany(
        "INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        tuple(
            (
                f"memory-{status}",
                f"legacy-{status}\x00payload",
                "preference",
                "candidate" if status in {"pending", "dismissed"} else "manual",
                "session-1",
                index,
                0.625,
                status,
                f'{{"status":"{status}","order":{index}}}',
                f"2026-07-01T00:00:0{index}Z",
                f"2026-07-01T00:00:1{index}Z",
            )
            for index, status in enumerate(
                ("active", "archived", "pending", "dismissed"), start=1
            )
        ),
    )
    connection.execute(
        "INSERT INTO memory_embeddings VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "memory-active",
            "fake",
            "fake-v1",
            2,
            "[0.25,0.75]",
            "content-hash",
            "2026-07-01T00:00:20Z",
            "2026-07-01T00:00:21Z",
        ),
    )
    connection.execute(
        "INSERT INTO session_summaries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "summary-1",
            "session-1",
            "legacy summary",
            "generated",
            "user-1",
            "assistant-1",
            2,
            '{"legacy":true}',
            "2026-07-01T00:00:30Z",
            "2026-07-01T00:00:31Z",
        ),
    )
    connection.execute(
        "INSERT INTO memory_extraction_consents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "default",
            "granted",
            "extract durable memory proposals from the current completed turn",
            "fake",
            "memory-extraction-disclosure-v1",
            '["user_message","assistant_message"]',
            2,
            "2026-07-01T00:00:40Z",
            "2026-07-01T00:00:41Z",
        ),
    )
    connection.execute(
        "INSERT INTO memory_jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "job-1",
            "assistant-1",
            "memory-shadow-schema-v1",
            "session-1",
            "user-1",
            "assistant-1",
            "shadow_auto",
            "fake",
            "succeeded",
            1,
            "shadow_recorded",
            None,
            "memory-governor-rules-v1",
            2,
            "2026-07-01T00:00:42Z",
            "2026-07-01T00:00:43Z",
            "2026-07-01T00:00:44Z",
        ),
    )
    connection.execute(
        "INSERT INTO memory_job_audits VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "audit-1",
            "job-1",
            "shadow_recorded",
            '{"create":1}',
            '{"safe":1}',
            1,
            1,
            0,
            0,
            "fake",
            "fake-model",
            12,
            "memory-shadow-schema-v1",
            "memory-governor-rules-v1",
            2,
            "2026-07-01T00:00:45Z",
        ),
    )
    connection.commit()


def _rows(connection: sqlite3.Connection, table: str) -> list[tuple[object, ...]]:
    return [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1")]


def test_gate_b_migration_preserves_gate_a_data_and_builds_compatible_schema(
    tmp_path: Path,
) -> None:
    connection = connect(f"sqlite:///{tmp_path / 'gate-a.db'}")
    _create_gate_a_database(connection)
    preserved_tables = (
        "memories",
        "memory_embeddings",
        "memory_extraction_consents",
        "memory_jobs",
        "memory_job_audits",
    )
    before = {table: _rows(connection, table) for table in preserved_tables}

    init_db(connection)

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert GATE_B_TABLES <= tables
    after = {table: _rows(connection, table) for table in preserved_tables}
    assert [row[:-1] for row in after["memories"]] == before["memories"]
    assert all(row[-1] is None for row in after["memories"])
    assert _rows(connection, "memory_embeddings") == before["memory_embeddings"]
    assert _rows(connection, "memory_extraction_consents") == before[
        "memory_extraction_consents"
    ]
    assert [tuple(row[:17]) for row in connection.execute(
        "SELECT * FROM memory_jobs ORDER BY id"
    )] == before["memory_jobs"]
    assert tuple(
        connection.execute(
            "SELECT turn_completed_at, reserved_mode, workflow_version, "
            "commit_policy_version, write_consent_generation, persona_artifact_id "
            "FROM memory_jobs WHERE id = 'job-1'"
        ).fetchone()
    ) == (None, None, None, None, None, None)
    audit = connection.execute(
        "SELECT id, job_id, outcome, decision_counts_json, reason_counts_json, "
        "proposal_count, accepted_count, rejected_count, redaction_count, provider, "
        "model, elapsed_ms, schema_version, governor_version, consent_generation, "
        "created_at FROM memory_job_audits"
    ).fetchone()
    assert tuple(audit) == before["memory_job_audits"][0]
    assert connection.execute(
        "SELECT outcome_counts_json FROM memory_job_audits"
    ).fetchone()[0] == "{}"
    assert connection.execute("SELECT COUNT(*) FROM memory_record_states").fetchone()[0] == 0
    assert connection.execute(
        "SELECT observed_memory_summary_barrier FROM session_summaries"
    ).fetchone()[0] == 0
    assert connection.execute("SELECT generation FROM memory_summary_barrier").fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    connection.execute(
        "INSERT INTO memories (id, content, memory_type, source, "
        "source_session_id, importance, confidence, status, metadata_json, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, '{}', ?, ?)",
        (
            "memory-automatic",
            "automatic projection",
            "other",
            "automatic",
            3,
            0.8,
            "active",
            "2026-07-01T01:00:00Z",
            "2026-07-01T01:00:00Z",
        ),
    )
    connection.close()


def test_gate_b_additive_migration_adds_candidate_provenance_and_content_tombstone(
    tmp_path: Path,
) -> None:
    connection = connect(f"sqlite:///{tmp_path / 'additive-columns.db'}")
    _create_gate_a_database(connection)
    init_db(connection)

    memory_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(memories)")
    }
    tombstone_columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(memory_tombstones)")
    }
    assert "source_session_reference_hash" in memory_columns
    assert "content_key_hash" in tombstone_columns
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_gate_b_migration_retains_job_and_audit_when_sources_are_deleted(
    tmp_path: Path,
) -> None:
    connection = connect(f"sqlite:///{tmp_path / 'retention.db'}")
    _create_gate_a_database(connection)
    init_db(connection)

    connection.execute("DELETE FROM sessions WHERE id = 'session-1'")

    job = connection.execute(
        "SELECT session_id, user_message_id, assistant_message_id FROM memory_jobs"
    ).fetchone()
    assert tuple(job) == (None, None, None)
    assert connection.execute("SELECT job_id FROM memory_job_audits").fetchone()[0] == "job-1"
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("DELETE FROM memory_jobs WHERE id = 'job-1'")
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_auto_active_job_requires_complete_frozen_snapshot(tmp_path: Path) -> None:
    connection = connect(f"sqlite:///{tmp_path / 'auto-active.db'}")
    init_db(connection)
    connection.execute(
        "INSERT INTO sessions VALUES ('session-1', 'title', 'created', 'updated')"
    )
    connection.executemany(
        "INSERT INTO messages VALUES (?, 'session-1', ?, ?, '{}', ?)",
        (
            ("user-1", "user", "user", "created"),
            ("assistant-1", "assistant", "assistant", "created"),
        ),
    )

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO memory_jobs (
                id, turn_id, schema_version, session_id, user_message_id,
                assistant_message_id, mode, extractor_route, status,
                governor_version, created_at
            ) VALUES (
                'incomplete', 'turn-incomplete', 'memory-auto-active-schema-v1',
                'session-1', 'user-1', 'assistant-1', 'auto_active', 'local',
                'pending', 'memory-governor-rules-v1', 'created'
            )
            """
        )

    connection.execute(
        """
        INSERT INTO memory_jobs (
            id, turn_id, schema_version, session_id, user_message_id,
            assistant_message_id, mode, extractor_route, status,
            governor_version, created_at, turn_completed_at, reserved_mode,
            workflow_version, commit_policy_version, canonicalization_version,
            allowed_memory_types_version, write_consent_generation,
            global_deletion_generation, session_deletion_generation,
            type_deletion_generations_json, source_session_reference_hash,
            source_user_message_reference_hash,
            source_assistant_message_reference_hash
        ) VALUES (
            'complete', 'turn-complete', 'memory-auto-active-schema-v1',
            'session-1', 'user-1', 'assistant-1', 'auto_active', 'local',
            'pending', 'memory-governor-rules-v1', 'created', 'completed',
            'auto_active', 'memory-auto-active-schema-v1',
            'memory-commit-policy-v1', 'memory-canonicalization-v1',
            'memory-auto-write-types-v1', 3, 0, 0,
            '{"other":0}', 'session-hash', 'user-hash', 'assistant-hash'
        )
        """
    )
    connection.close()


def test_remote_auto_active_job_requires_remote_authority_snapshot(
    tmp_path: Path,
) -> None:
    connection = connect(f"sqlite:///{tmp_path / 'remote-auto-active.db'}")
    init_db(connection)
    connection.execute(
        "INSERT INTO sessions VALUES ('session-1', 'title', 'created', 'updated')"
    )
    connection.executemany(
        "INSERT INTO messages VALUES (?, 'session-1', ?, ?, '{}', ?)",
        (
            ("user-1", "user", "user", "created"),
            ("assistant-1", "assistant", "assistant", "created"),
        ),
    )
    sql = """
        INSERT INTO memory_jobs (
            id, turn_id, schema_version, session_id, user_message_id,
            assistant_message_id, mode, extractor_route, status,
            governor_version, created_at, turn_completed_at, reserved_mode,
            workflow_version, commit_policy_version, canonicalization_version,
            allowed_memory_types_version, write_consent_generation,
            remote_consent_generation, remote_authority_fingerprint,
            global_deletion_generation, session_deletion_generation,
            type_deletion_generations_json, source_session_reference_hash,
            source_user_message_reference_hash,
            source_assistant_message_reference_hash
        ) VALUES (
            ?, ?, 'memory-auto-active-schema-v1', 'session-1', 'user-1',
            'assistant-1', 'auto_active', 'remote', 'pending',
            'memory-governor-rules-v1', 'created', 'completed', 'auto_active',
            'memory-auto-active-schema-v1', 'memory-commit-policy-v1',
            'memory-canonicalization-v1', 'memory-auto-write-types-v1', 3,
            ?, ?, 0, 0, '{"other":0}', 'session-hash', 'user-hash',
            'assistant-hash'
        )
    """
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(sql, ("missing-remote", "turn-missing", None, None))
    connection.execute(sql, ("complete-remote", "turn-complete", 4, "authority-hash"))
    connection.close()


def test_gate_b_database_guards_evidence_versions_and_frozen_job_snapshot(
    tmp_path: Path,
) -> None:
    connection = connect(f"sqlite:///{tmp_path / 'gate-b-guards.db'}")
    init_db(connection)
    connection.executemany(
        "INSERT INTO sessions VALUES (?, ?, 'created', 'updated')",
        (("session-1", "one"), ("session-2", "two")),
    )
    connection.execute(
        "INSERT INTO messages VALUES "
        "('user-2', 'session-2', 'user', 'content', '{}', 'created')"
    )
    connection.execute(
        "INSERT INTO memories ("
        "id, content, memory_type, source, source_session_id, importance, "
        "confidence, status, metadata_json, created_at, updated_at) VALUES "
        "('memory-1', 'content', 'other', 'manual', NULL, 3, 1.0, "
        "'active', '{}', 'created', 'updated')"
    )
    connection.execute(
        """
        INSERT INTO memory_versions (
            id, memory_id, version_number, operation, memory_type, content,
            content_hash, canonicalization_version, confidence, importance,
            source_kind, writer_policy_version, created_at
        ) VALUES (
            'version-1', 'memory-1', 1, 'bootstrap', 'other', 'content',
            'content-hash', 'memory-canonicalization-v1', 1.0, 3,
            'legacy', 'memory-auto-write-policy-v1', 'created'
        )
        """
    )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute(
            "UPDATE memory_versions SET content = 'changed' WHERE id = 'version-1'"
        )
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        connection.execute("DELETE FROM memory_versions WHERE id = 'version-1'")
    with pytest.raises(sqlite3.IntegrityError, match="source must be a user message"):
        connection.execute(
            """
            INSERT INTO memory_evidence (
                evidence_id, memory_id, memory_version_id, source_session_id,
                source_message_id, source_session_reference_hash,
                source_message_reference_hash, source_available, relation,
                observed_at, extractor_kind, confidence, created_at
            ) VALUES (
                'evidence-1', 'memory-1', 'version-1', 'session-1',
                'user-2', 'session-hash', 'message-hash', 1, 'supports',
                'observed', 'local', 1.0, 'created'
            )
            """
        )

    connection.execute(
        """
        INSERT INTO memory_jobs (
            id, turn_id, schema_version, mode, extractor_route, status,
            governor_version, created_at
        ) VALUES (
            'legacy-job', 'legacy-turn', 'memory-shadow-schema-v1',
            'shadow_auto', 'local', 'pending', 'memory-governor-rules-v1',
            'created'
        )
        """
    )
    with pytest.raises(sqlite3.IntegrityError, match="snapshot is immutable"):
        connection.execute(
            "UPDATE memory_jobs SET governor_version = 'changed' WHERE id = 'legacy-job'"
        )
    connection.close()


def test_gate_b_migration_rolls_back_schema_and_data_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = connect(f"sqlite:///{tmp_path / 'rollback.db'}")
    _create_gate_a_database(connection)
    schema_before = [
        tuple(row)
        for row in connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
        )
    ]
    data_before = {
        table: _rows(connection, table)
        for table in (
            "sessions",
            "messages",
            "session_summaries",
            "memories",
            "memory_embeddings",
            "memory_jobs",
            "memory_job_audits",
        )
    }

    def fail_gate_b_schema(_: sqlite3.Connection) -> None:
        raise RuntimeError("injected Gate B migration failure")

    monkeypatch.setattr(sqlite_repository, "_create_gate_b_schema", fail_gate_b_schema)

    with pytest.raises(RuntimeError, match="injected Gate B migration failure"):
        init_db(connection)

    schema_after = [
        tuple(row)
        for row in connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
        )
    ]
    assert schema_after == schema_before
    assert {
        table: _rows(connection, table) for table in data_before
    } == data_before
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_gate_b_migration_rejects_unexpected_inbound_foreign_key(
    tmp_path: Path,
) -> None:
    connection = connect(f"sqlite:///{tmp_path / 'unexpected-fk.db'}")
    _create_gate_a_database(connection)
    connection.execute(
        "CREATE TABLE extension_reference (memory_id TEXT REFERENCES memories(id))"
    )
    connection.commit()

    with pytest.raises(RuntimeError, match="unexpected inbound foreign keys"):
        init_db(connection)

    assert "automatic" not in connection.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'memories'"
    ).fetchone()[0]
    connection.close()


def test_memory_source_reference_probe_is_schema_aware() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    assert memory_source_references_exist(connection) is False

    connection.execute(
        "CREATE TABLE memory_versions (id TEXT, source_session_reference_hash TEXT)"
    )
    assert memory_source_references_exist(connection) is False
    connection.execute(
        "INSERT INTO memory_versions VALUES ('version-1', 'session-digest')"
    )
    assert memory_source_references_exist(connection) is True

    connection.execute(
        "CREATE TABLE memory_jobs (id TEXT, source_user_message_reference_hash TEXT)"
    )
    assert memory_source_references_exist(connection) is True
    connection.close()


def test_memory_source_reference_probe_handles_full_empty_gate_b_schema(
    tmp_path: Path,
) -> None:
    connection = connect(f"sqlite:///{tmp_path / 'empty.db'}")
    init_db(connection)

    assert memory_source_references_exist(connection) is False
    connection.close()
