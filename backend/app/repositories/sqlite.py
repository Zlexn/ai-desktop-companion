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
"""


def resolve_sqlite_path(database_url: str) -> Path:
    if not database_url.startswith("sqlite:///"):
        raise ValueError("Only sqlite:/// database URLs are supported in stage 1")
    return Path(database_url.removeprefix("sqlite:///"))


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


def init_db(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)
    _migrate_memories_candidate_constraints(connection)
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
