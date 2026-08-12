import sqlite3
from collections.abc import Iterable
from pathlib import Path

import pytest

from app.repositories import sqlite as sqlite_repository
from app.repositories.sqlite import connect, init_db


GATE_A_TABLES = {
    "memory_extraction_consents",
    "memory_jobs",
    "memory_job_audits",
}
FORBIDDEN_COLUMNS = {
    "candidate_content",
    "content",
    "prompt",
    "prompt_text",
    "response",
    "response_text",
    "user_text",
    "assistant_text",
    "credential",
    "credentials",
    "authorization",
    "authorization_header",
}
ALLOWED_OUTCOMES = (
    "shadow_recorded",
    "skipped_no_extractor",
    "skipped_no_consent",
    "skipped_consent_changed",
    "skipped_governor_policy",
    "invalid_output",
    "provider_error",
    "cancelled",
    "failed",
)
ALLOWED_ERROR_CATEGORIES = (
    "invalid_output",
    "provider_error",
    "invalid_job_input",
    "interrupted",
    "database_error",
)


def create_pre_gate_a_schema(connection: sqlite3.Connection) -> None:
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

        CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            memory_type TEXT NOT NULL CHECK (memory_type IN ('user_fact', 'preference', 'long_term_goal', 'important_event', 'relationship_event', 'other')),
            source TEXT NOT NULL CHECK (source IN ('manual', 'candidate')),
            source_session_id TEXT,
            importance INTEGER NOT NULL CHECK (importance >= 1 AND importance <= 5),
            confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
            status TEXT NOT NULL CHECK (status IN ('active', 'archived', 'pending', 'dismissed')),
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (source_session_id) REFERENCES sessions(id) ON DELETE SET NULL
        );
        """
    )
    connection.commit()


def insert_pre_gate_a_memory_rows(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("legacy-session", "legacy", "2026-07-01T00:00:00Z", "2026-07-01T00:00:00Z"),
    )
    connection.executemany(
        """
        INSERT INTO memories (
            id, content, memory_type, source, source_session_id,
            importance, confidence, status, metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                "legacy-active",
                "用户喜欢原味咖啡。",
                "preference",
                "manual",
                "legacy-session",
                5,
                1.0,
                "active",
                '{"bytes":"active\\u0000metadata","order":1}',
                "2026-07-01T00:00:01Z",
                "2026-07-01T00:00:02Z",
            ),
            (
                "legacy-pending",
                "候选记忆保持原样。",
                "other",
                "candidate",
                "legacy-session",
                2,
                0.625,
                "pending",
                '{"order":2,"candidate_reason":"legacy"}',
                "2026-07-01T00:00:03Z",
                "2026-07-01T00:00:04Z",
            ),
        ),
    )
    connection.commit()


@pytest.fixture
def migrated_connection(tmp_path: Path) -> Iterable[sqlite3.Connection]:
    connection = connect(f"sqlite:///{tmp_path / 'legacy.db'}")
    create_pre_gate_a_schema(connection)
    insert_pre_gate_a_memory_rows(connection)
    init_db(connection)
    try:
        yield connection
    finally:
        connection.close()


def insert_turn(connection: sqlite3.Connection, suffix: str) -> tuple[str, str, str]:
    session_id = f"session-{suffix}"
    user_message_id = f"user-{suffix}"
    assistant_message_id = f"assistant-{suffix}"
    connection.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, suffix, "2026-07-16T00:00:00Z", "2026-07-16T00:00:00Z"),
    )
    connection.executemany(
        """
        INSERT INTO messages (id, session_id, role, content, metadata_json, created_at)
        VALUES (?, ?, ?, ?, '{}', ?)
        """,
        (
            (user_message_id, session_id, "user", "user", "2026-07-16T00:00:01Z"),
            (
                assistant_message_id,
                session_id,
                "assistant",
                "assistant",
                "2026-07-16T00:00:02Z",
            ),
        ),
    )
    return session_id, user_message_id, assistant_message_id


def insert_job(
    connection: sqlite3.Connection,
    suffix: str,
    *,
    turn_id: str | None = None,
    schema_version: str = "memory-shadow-schema-v1",
    mode: str = "shadow_auto",
    outcome: str | None = None,
    error_category: str | None = None,
) -> str:
    session_id, user_message_id, assistant_message_id = insert_turn(connection, suffix)
    job_id = f"job-{suffix}"
    connection.execute(
        """
        INSERT INTO memory_jobs (
            id, turn_id, schema_version, session_id, user_message_id,
            assistant_message_id, mode, extractor_route, status, attempt_count,
            outcome, error_category, governor_version, consent_generation,
            created_at, started_at, finished_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'local', 'pending', 0, ?, ?, ?, NULL, ?, NULL, NULL)
        """,
        (
            job_id,
            turn_id or assistant_message_id,
            schema_version,
            session_id,
            user_message_id,
            assistant_message_id,
            mode,
            outcome,
            error_category,
            "memory-governor-rules-v1",
            "2026-07-16T00:00:03Z",
        ),
    )
    return job_id


def insert_audit(
    connection: sqlite3.Connection,
    suffix: str,
    job_id: str,
    *,
    outcome: str = "shadow_recorded",
) -> None:
    connection.execute(
        """
        INSERT INTO memory_job_audits (
            id, job_id, outcome, decision_counts_json, reason_counts_json,
            proposal_count, accepted_count, rejected_count, redaction_count,
            provider, model, elapsed_ms, schema_version, governor_version,
            consent_generation, created_at
        ) VALUES (?, ?, ?, '{}', '{}', 0, 0, 0, 0, NULL, NULL, NULL, ?, ?, NULL, ?)
        """,
        (
            f"audit-{suffix}",
            job_id,
            outcome,
            "memory-shadow-schema-v1",
            "memory-governor-rules-v1",
            "2026-07-16T00:00:04Z",
        ),
    )


def test_init_db_adds_gate_a_tables_without_changing_legacy_memories(tmp_path: Path) -> None:
    connection = connect(f"sqlite:///{tmp_path / 'legacy.db'}")
    create_pre_gate_a_schema(connection)
    insert_pre_gate_a_memory_rows(connection)
    before = connection.execute("SELECT * FROM memories ORDER BY id").fetchall()

    init_db(connection)

    after = connection.execute("SELECT * FROM memories ORDER BY id").fetchall()
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert [tuple(row[:-1]) for row in after] == [tuple(row) for row in before]
    assert all(row[-1] is None for row in after)
    assert GATE_A_TABLES <= tables
    connection.close()


def test_init_db_rolls_back_gate_a_tables_when_a_later_migration_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = connect(f"sqlite:///{tmp_path / 'rollback.db'}")
    create_pre_gate_a_schema(connection)
    insert_pre_gate_a_memory_rows(connection)
    before = connection.execute("SELECT * FROM memories ORDER BY id").fetchall()

    def fail_later_migration(_: sqlite3.Connection) -> None:
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr(
        sqlite_repository,
        "_migrate_emotion_analysis_consent_policy",
        fail_later_migration,
    )

    with pytest.raises(RuntimeError, match="injected migration failure"):
        init_db(connection)

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    after = connection.execute("SELECT * FROM memories ORDER BY id").fetchall()
    assert GATE_A_TABLES.isdisjoint(tables)
    assert [tuple(row) for row in after] == [tuple(row) for row in before]
    connection.close()


def test_gate_a_created_at_indexes_exist(
    migrated_connection: sqlite3.Connection,
) -> None:
    indexes = {
        row[0]
        for row in migrated_connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }
    assert {
        "idx_memory_jobs_created_at",
        "idx_memory_job_audits_created_at",
    } <= indexes


def test_init_db_enables_foreign_keys_before_migration_and_retains_audits(
    tmp_path: Path,
) -> None:
    connection = sqlite3.connect(tmp_path / "foreign-keys-off.db")
    connection.row_factory = sqlite3.Row
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 0

    init_db(connection)

    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    job_id = insert_job(connection, "raw-connection")
    insert_audit(connection, "raw-connection", job_id)
    user_message_id = connection.execute(
        "SELECT user_message_id FROM memory_jobs WHERE id = ?",
        (job_id,),
    ).fetchone()[0]

    connection.execute("DELETE FROM messages WHERE id = ?", (user_message_id,))

    assert connection.execute(
        "SELECT user_message_id FROM memory_jobs WHERE id = ?", (job_id,)
    ).fetchone()[0] is None
    assert connection.execute(
        "SELECT 1 FROM memory_job_audits WHERE job_id = ?", (job_id,)
    ).fetchone() is not None
    connection.close()


def test_gate_a_tables_have_no_raw_or_sensitive_text_columns(
    migrated_connection: sqlite3.Connection,
) -> None:
    for table_name in GATE_A_TABLES:
        columns = {
            str(row[1]).strip().lower()
            for row in migrated_connection.execute(f"PRAGMA table_info({table_name})")
        }
        assert columns.isdisjoint(FORBIDDEN_COLUMNS), table_name


def test_job_and_audit_accept_only_the_frozen_outcomes(
    migrated_connection: sqlite3.Connection,
) -> None:
    for index, outcome in enumerate(ALLOWED_OUTCOMES):
        suffix = f"outcome-{index}"
        job_id = insert_job(migrated_connection, suffix, outcome=outcome)
        insert_audit(migrated_connection, suffix, job_id, outcome=outcome)

    invalid_job_id = insert_job(migrated_connection, "invalid-job-outcome")
    with pytest.raises(sqlite3.IntegrityError):
        migrated_connection.execute(
            "UPDATE memory_jobs SET outcome = 'arbitrary' WHERE id = ?",
            (invalid_job_id,),
        )

    audit_job_id = insert_job(migrated_connection, "invalid-audit-outcome")
    with pytest.raises(sqlite3.IntegrityError):
        insert_audit(
            migrated_connection,
            "invalid-audit-outcome",
            audit_job_id,
            outcome="arbitrary",
        )


def test_job_accepts_only_frozen_error_categories(
    migrated_connection: sqlite3.Connection,
) -> None:
    for index, error_category in enumerate(ALLOWED_ERROR_CATEGORIES):
        insert_job(
            migrated_connection,
            f"error-{index}",
            error_category=error_category,
        )

    with pytest.raises(sqlite3.IntegrityError):
        insert_job(
            migrated_connection,
            "invalid-error",
            error_category="secret-bearing-exception-text",
        )


def test_job_rejects_duplicate_turn_schema_and_incomplete_auto_active_snapshot(
    migrated_connection: sqlite3.Connection,
) -> None:
    insert_job(migrated_connection, "first", turn_id="stable-turn")

    with pytest.raises(sqlite3.IntegrityError):
        insert_job(migrated_connection, "duplicate", turn_id="stable-turn")

    with pytest.raises(sqlite3.IntegrityError):
        insert_job(migrated_connection, "auto-active", mode="auto_active")


def test_audit_rejects_duplicate_job_id(
    migrated_connection: sqlite3.Connection,
) -> None:
    job_id = insert_job(migrated_connection, "duplicate-audit")
    insert_audit(migrated_connection, "first", job_id)

    with pytest.raises(sqlite3.IntegrityError):
        insert_audit(migrated_connection, "second", job_id)


@pytest.mark.parametrize("deleted_parent", ["session", "user_message", "assistant_message"])
def test_job_and_audit_survive_parent_deletion_with_nullable_sources(
    migrated_connection: sqlite3.Connection,
    deleted_parent: str,
) -> None:
    job_id = insert_job(migrated_connection, deleted_parent)
    insert_audit(migrated_connection, deleted_parent, job_id)
    row = migrated_connection.execute(
        "SELECT session_id, user_message_id, assistant_message_id FROM memory_jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    assert row is not None

    if deleted_parent == "session":
        migrated_connection.execute("DELETE FROM sessions WHERE id = ?", (row["session_id"],))
    elif deleted_parent == "user_message":
        migrated_connection.execute("DELETE FROM messages WHERE id = ?", (row["user_message_id"],))
    else:
        migrated_connection.execute(
            "DELETE FROM messages WHERE id = ?", (row["assistant_message_id"],)
        )

    retained = migrated_connection.execute(
        "SELECT session_id, user_message_id, assistant_message_id "
        "FROM memory_jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    assert retained is not None
    if deleted_parent == "session":
        assert tuple(retained) == (None, None, None)
    elif deleted_parent == "user_message":
        assert retained["session_id"] is not None
        assert retained["user_message_id"] is None
        assert retained["assistant_message_id"] is not None
    else:
        assert retained["session_id"] is not None
        assert retained["user_message_id"] is not None
        assert retained["assistant_message_id"] is None
    assert (
        migrated_connection.execute(
            "SELECT 1 FROM memory_job_audits WHERE job_id = ?", (job_id,)
        ).fetchone()
        is not None
    )
