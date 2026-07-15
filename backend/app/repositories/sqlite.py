import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session_created
ON messages(session_id, created_at);

CREATE TABLE IF NOT EXISTS session_summaries (
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

CREATE INDEX IF NOT EXISTS idx_session_summaries_session_created
ON session_summaries(session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_session_summaries_session_updated
ON session_summaries(session_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS memories (
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

CREATE INDEX IF NOT EXISTS idx_memories_status_importance_updated
ON memories(status, importance DESC, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_memories_type_status
ON memories(memory_type, status);

CREATE TABLE IF NOT EXISTS memory_audit_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL CHECK (event_type IN ('conflict_detected')),
    memory_id TEXT NOT NULL,
    related_memory_ids_json TEXT NOT NULL DEFAULT '[]',
    operation TEXT NOT NULL CHECK (operation IN ('create', 'update', 'confirm_candidate')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_audit_events_created
ON memory_audit_events(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_audit_events_memory
ON memory_audit_events(memory_id);

CREATE TABLE IF NOT EXISTS memory_embeddings (
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

CREATE INDEX IF NOT EXISTS idx_memory_embeddings_provider_model
ON memory_embeddings(provider, model);

CREATE TABLE IF NOT EXISTS emotion_states (
    scope_id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    mood REAL NOT NULL CHECK (mood >= 0.0 AND mood <= 1.0),
    trust REAL NOT NULL CHECK (trust >= 0.0 AND trust <= 1.0),
    concern REAL NOT NULL CHECK (concern >= 0.0 AND concern <= 1.0),
    distance REAL NOT NULL CHECK (distance >= 0.0 AND distance <= 1.0),
    irritation REAL NOT NULL CHECK (irritation >= 0.0 AND irritation <= 1.0),
    formality REAL NOT NULL CHECK (formality >= 0.0 AND formality <= 1.0),
    version INTEGER NOT NULL CHECK (version >= 0),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS emotion_events (
    id TEXT PRIMARY KEY,
    scope_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('transition', 'decay', 'settings', 'reset')),
    before_json TEXT NOT NULL,
    after_json TEXT NOT NULL,
    applied_delta_json TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    source_session_id TEXT,
    source_user_message_id TEXT,
    source_assistant_message_id TEXT,
    engine TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (scope_id) REFERENCES emotion_states(scope_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_emotion_events_scope_created
ON emotion_events(scope_id, created_at DESC);

CREATE TABLE IF NOT EXISTS emotion_analysis_consents (
    scope_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('unknown', 'granted', 'declined', 'revoked')),
    disclosure_version TEXT,
    provider TEXT,
    policy_fingerprint TEXT,
    generation INTEGER NOT NULL DEFAULT 0 CHECK (generation >= 0),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS emotion_analysis_jobs (
    id TEXT PRIMARY KEY,
    scope_id TEXT NOT NULL,
    source_session_id TEXT NOT NULL,
    source_user_message_id TEXT NOT NULL,
    source_assistant_message_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    base_emotion_version INTEGER NOT NULL CHECK (base_emotion_version >= 0),
    consent_generation INTEGER NOT NULL DEFAULT 0 CHECK (consent_generation >= 0),
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'skipped')),
    outcome_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (source_assistant_message_id, schema_version)
);

CREATE INDEX IF NOT EXISTS idx_emotion_analysis_jobs_status_created
ON emotion_analysis_jobs(status, created_at);

CREATE TABLE IF NOT EXISTS emotion_analysis_audits (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('applied', 'no_change', 'skipped', 'invalid_output', 'provider_error', 'revoked', 'failed')),
    source_session_id TEXT NOT NULL,
    source_user_message_id TEXT NOT NULL,
    source_assistant_message_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    message_count INTEGER NOT NULL CHECK (message_count >= 0),
    memory_count INTEGER NOT NULL CHECK (memory_count >= 0),
    input_characters INTEGER NOT NULL CHECK (input_characters >= 0),
    redaction_count INTEGER NOT NULL CHECK (redaction_count >= 0),
    elapsed_ms INTEGER NOT NULL CHECK (elapsed_ms >= 0),
    reason_code TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_emotion_analysis_audits_scope_created
ON emotion_analysis_audits(scope_id, created_at DESC);

CREATE TABLE IF NOT EXISTS expression_plans (
    id TEXT PRIMARY KEY,
    assistant_message_id TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK (typeof(schema_version) = 'integer' AND schema_version >= 1),
    source_emotion_version INTEGER NOT NULL CHECK (typeof(source_emotion_version) = 'integer' AND source_emotion_version >= 0),
    delivery TEXT NOT NULL CHECK (delivery IN ('neutral', 'warm', 'reassuring', 'reserved', 'firm')),
    rate REAL NOT NULL CHECK (rate >= 0.90 AND rate <= 1.10),
    intensity TEXT NOT NULL CHECK (intensity IN ('low', 'medium')),
    created_at TEXT NOT NULL,
    FOREIGN KEY (assistant_message_id) REFERENCES messages(id) ON DELETE CASCADE,
    UNIQUE (assistant_message_id, schema_version)
);

CREATE INDEX IF NOT EXISTS idx_expression_plans_message
ON expression_plans(assistant_message_id);
"""


def resolve_sqlite_path(database_url: str) -> Path:
    if not database_url.startswith("sqlite:///"):
        raise ValueError("Only sqlite:/// database URLs are supported")
    path = Path(database_url.removeprefix("sqlite:///"))
    if path == Path(":memory:"):
        raise ValueError("sqlite:///:memory: is not supported; use an isolated temporary SQLite file")
    return path


def connect(database_url: str) -> sqlite3.Connection:
    path = resolve_sqlite_path(database_url)
    if path != Path(":memory:"):
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _table_sql(connection: sqlite3.Connection, table_name: str) -> str | None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return None if row is None else str(row["sql"])


def _memories_schema_needs_candidate_migration(connection: sqlite3.Connection) -> bool:
    sql = _table_sql(connection, "memories")
    if sql is None:
        return False
    return "'candidate'" not in sql or "'pending'" not in sql or "'dismissed'" not in sql


def _migrate_memories_candidate_constraints(connection: sqlite3.Connection) -> None:
    if not _memories_schema_needs_candidate_migration(connection):
        return

    connection.executescript(
        """
        ALTER TABLE memories RENAME TO memories_old;

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

        INSERT INTO memories (
            id, content, memory_type, source, source_session_id,
            importance, confidence, status, metadata_json, created_at, updated_at
        )
        SELECT
            id, content, memory_type, source, source_session_id,
            importance, confidence, status, metadata_json, created_at, updated_at
        FROM memories_old;

        DROP TABLE memories_old;
        """
    )


def _migrate_emotion_analysis_consent_policy(connection: sqlite3.Connection) -> None:
    sql = _table_sql(connection, "emotion_analysis_consents")
    if sql is None:
        return
    if "policy_fingerprint" not in sql:
        connection.execute(
            "ALTER TABLE emotion_analysis_consents ADD COLUMN policy_fingerprint TEXT"
        )
    if "generation" not in sql:
        connection.execute(
            "ALTER TABLE emotion_analysis_consents ADD COLUMN generation INTEGER NOT NULL DEFAULT 0"
        )


def _migrate_emotion_analysis_job_version(connection: sqlite3.Connection) -> None:
    sql = _table_sql(connection, "emotion_analysis_jobs")
    if sql is None:
        return
    if "base_emotion_version" not in sql:
        connection.execute(
            "ALTER TABLE emotion_analysis_jobs ADD COLUMN base_emotion_version INTEGER NOT NULL DEFAULT 0"
        )
    if "consent_generation" not in sql:
        connection.execute(
            "ALTER TABLE emotion_analysis_jobs ADD COLUMN consent_generation INTEGER NOT NULL DEFAULT 0"
        )


def init_db(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)
    _migrate_memories_candidate_constraints(connection)
    _migrate_emotion_analysis_consent_policy(connection)
    _migrate_emotion_analysis_job_version(connection)
    connection.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_memories_status_importance_updated
        ON memories(status, importance DESC, updated_at DESC);

        CREATE INDEX IF NOT EXISTS idx_memories_type_status
        ON memories(memory_type, status);

        CREATE INDEX IF NOT EXISTS idx_memory_audit_events_created
        ON memory_audit_events(created_at DESC);

        CREATE INDEX IF NOT EXISTS idx_memory_audit_events_memory
        ON memory_audit_events(memory_id);

        CREATE INDEX IF NOT EXISTS idx_memory_embeddings_provider_model
        ON memory_embeddings(provider, model);
        """
    )
    connection.commit()


@contextmanager
def managed_connection(database_url: str) -> Iterator[sqlite3.Connection]:
    connection = connect(database_url)
    try:
        init_db(connection)
        yield connection
    finally:
        connection.close()


def metadata_to_json(metadata: dict[str, object] | None) -> str:
    return json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)


def metadata_from_json(raw: str) -> dict[str, object]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        return {}
    return value
