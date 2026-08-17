from __future__ import annotations

from collections.abc import Callable
import sqlite3
from uuid import uuid5, NAMESPACE_URL

from app.services.session_summary_contract import (
    SUMMARY_INJECTION_SCHEMA_VERSION,
    SUMMARY_SCHEMA_VERSION,
    canonical_summary_source_set_hash,
)


_C2_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS chat_turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_message_id TEXT NOT NULL UNIQUE,
    assistant_message_id TEXT NOT NULL UNIQUE,
    turn_order INTEGER NOT NULL CHECK (turn_order > 0),
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (user_message_id) REFERENCES messages(id) ON DELETE CASCADE,
    FOREIGN KEY (assistant_message_id) REFERENCES messages(id) ON DELETE CASCADE,
    UNIQUE (session_id, turn_order)
);

CREATE TABLE IF NOT EXISTS session_summary_sources (
    summary_id TEXT NOT NULL,
    chat_turn_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    turn_order INTEGER NOT NULL CHECK (turn_order > 0),
    message_order_in_turn INTEGER NOT NULL CHECK (message_order_in_turn IN (0, 1)),
    source_order INTEGER NOT NULL CHECK (source_order >= 0),
    PRIMARY KEY (summary_id, message_id),
    UNIQUE (summary_id, source_order),
    FOREIGN KEY (summary_id) REFERENCES session_summaries(id) ON DELETE CASCADE,
    FOREIGN KEY (chat_turn_id) REFERENCES chat_turns(id) ON DELETE CASCADE,
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS summary_processing_consents (
    scope_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('unknown', 'granted', 'declined', 'revoked')),
    disclosure_version TEXT,
    purpose TEXT,
    provider TEXT,
    disclosed_fields_json TEXT NOT NULL DEFAULT '[]',
    policy_fingerprint TEXT,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS summary_injection_consents (
    scope_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('unknown', 'granted', 'declined', 'revoked')),
    disclosure_version TEXT,
    chat_provider_fingerprint TEXT,
    disclosed_fields_json TEXT NOT NULL DEFAULT '[]',
    generation INTEGER NOT NULL CHECK (generation >= 0),
    max_fragment_count INTEGER NOT NULL CHECK (max_fragment_count > 0),
    max_fragment_characters INTEGER NOT NULL CHECK (max_fragment_characters > 0),
    max_total_characters INTEGER NOT NULL CHECK (max_total_characters > 0),
    updated_at TEXT NOT NULL,
    CHECK (max_fragment_characters <= max_total_characters)
);

CREATE TABLE IF NOT EXISTS summary_authority_audits (
    id TEXT PRIMARY KEY,
    authority_kind TEXT NOT NULL CHECK (authority_kind IN ('processing', 'injection')),
    scope_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('grant', 'decline', 'revoke', 'enable_local', 'disable_local')),
    generation INTEGER NOT NULL CHECK (generation >= 0),
    disclosure_version TEXT,
    provider TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS summary_jobs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    job_kind TEXT NOT NULL CHECK (job_kind IN ('incremental', 'rebuild')),
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled', 'skipped')),
    logical_source_identity TEXT NOT NULL,
    attempt_epoch TEXT NOT NULL,
    source_set_hash TEXT NOT NULL,
    source_message_count INTEGER NOT NULL CHECK (source_message_count >= 0),
    source_turn_count INTEGER NOT NULL CHECK (source_turn_count >= 0),
    captured_barrier_generation INTEGER NOT NULL CHECK (captured_barrier_generation >= 0),
    captured_processing_consent_generation INTEGER NOT NULL CHECK (captured_processing_consent_generation >= 0),
    captured_processing_policy_fingerprint TEXT,
    captured_session_deletion_generation INTEGER NOT NULL CHECK (captured_session_deletion_generation >= 0),
    captured_suppression_generation INTEGER NOT NULL CHECK (captured_suppression_generation >= 0),
    captured_rebuild_authorization_generation INTEGER NOT NULL DEFAULT 0 CHECK (captured_rebuild_authorization_generation >= 0),
    rebuild_permit_id TEXT,
    source_summary_id TEXT,
    route TEXT NOT NULL CHECK (route IN ('fake', 'remote')),
    provider TEXT,
    model TEXT,
    summarizer_schema_version TEXT NOT NULL,
    job_schema_version TEXT NOT NULL DEFAULT 'summary-job-v1',
    source_manifest_sealed INTEGER NOT NULL DEFAULT 0
        CHECK (source_manifest_sealed IN (0, 1)),
    attempt_count INTEGER NOT NULL CHECK (attempt_count >= 0),
    reason_code TEXT,
    error_category TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (source_summary_id) REFERENCES session_summaries(id) ON DELETE RESTRICT,
    UNIQUE (logical_source_identity, attempt_epoch)
);

CREATE TABLE IF NOT EXISTS summary_job_sources (
    job_id TEXT NOT NULL,
    chat_turn_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    turn_order INTEGER NOT NULL CHECK (turn_order > 0),
    message_order_in_turn INTEGER NOT NULL CHECK (message_order_in_turn IN (0, 1)),
    source_order INTEGER NOT NULL CHECK (source_order >= 0),
    PRIMARY KEY (job_id, message_id),
    UNIQUE (job_id, source_order),
    FOREIGN KEY (job_id) REFERENCES summary_jobs(id) ON DELETE CASCADE,
    FOREIGN KEY (chat_turn_id) REFERENCES chat_turns(id) ON DELETE CASCADE,
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS summary_commit_guards (
    job_id TEXT PRIMARY KEY,
    summary_id TEXT NOT NULL UNIQUE,
    FOREIGN KEY (job_id) REFERENCES summary_jobs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS summary_redaction_guards (
    summary_id TEXT PRIMARY KEY,
    FOREIGN KEY (summary_id) REFERENCES session_summaries(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS summary_suppression_transition_guards (
    session_id TEXT NOT NULL,
    source_set_hash TEXT NOT NULL,
    expected_generation INTEGER NOT NULL CHECK (expected_generation >= 0),
    target_generation INTEGER NOT NULL CHECK (target_generation > expected_generation),
    target_state TEXT NOT NULL CHECK (target_state IN (
        'suppressed', 'rebuild_authorized',
        'rebuild_in_progress', 'rebuild_completed'
    )),
    PRIMARY KEY (session_id, source_set_hash),
    FOREIGN KEY (session_id, source_set_hash)
        REFERENCES summary_source_suppressions(session_id, source_set_hash)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS summary_job_audits (
    id TEXT PRIMARY KEY,
    job_id TEXT,
    status TEXT NOT NULL,
    outcome TEXT NOT NULL,
    source_message_count INTEGER NOT NULL CHECK (source_message_count >= 0),
    source_turn_count INTEGER NOT NULL CHECK (source_turn_count >= 0),
    consent_generation INTEGER NOT NULL CHECK (consent_generation >= 0),
    barrier_generation INTEGER NOT NULL CHECK (barrier_generation >= 0),
    route TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    elapsed_ms INTEGER,
    reason_code TEXT,
    error_category TEXT,
    schema_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES summary_jobs(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS summary_source_suppressions (
    session_id TEXT NOT NULL,
    source_set_hash TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    state TEXT NOT NULL CHECK (state IN ('suppressed', 'rebuild_authorized', 'rebuild_in_progress', 'rebuild_completed')),
    rebuild_permit_id TEXT,
    bound_job_id TEXT,
    authorized_summary_id TEXT,
    reason_code TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (session_id, source_set_hash),
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (bound_job_id) REFERENCES summary_jobs(id) ON DELETE SET NULL,
    FOREIGN KEY (authorized_summary_id) REFERENCES session_summaries(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS summary_suppression_audits (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    state TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS summary_payload_audits (
    id TEXT PRIMARY KEY,
    summary_id TEXT,
    action TEXT NOT NULL CHECK (action IN ('migration_invalidated', 'redacted', 'quarantined', 'revalidated', 'created')),
    payload_state TEXT NOT NULL CHECK (payload_state IN ('active', 'redacted', 'quarantined')),
    reason_code TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (summary_id) REFERENCES session_summaries(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_turns_session_order
ON chat_turns(session_id, turn_order);
CREATE INDEX IF NOT EXISTS idx_summary_sources_turn
ON session_summary_sources(chat_turn_id, source_order);
CREATE INDEX IF NOT EXISTS idx_summary_jobs_status_created
ON summary_jobs(status, created_at, id);
CREATE INDEX IF NOT EXISTS idx_summary_jobs_session_created
ON summary_jobs(session_id, created_at DESC, id DESC);

CREATE TRIGGER IF NOT EXISTS trg_chat_turns_valid_insert
BEFORE INSERT ON chat_turns
WHEN NOT EXISTS (
    SELECT 1 FROM messages AS user_message
    JOIN messages AS assistant_message
      ON assistant_message.id = NEW.assistant_message_id
    WHERE user_message.id = NEW.user_message_id
      AND user_message.session_id = NEW.session_id
      AND assistant_message.session_id = NEW.session_id
      AND user_message.role = 'user'
      AND assistant_message.role = 'assistant'
)
BEGIN
    SELECT RAISE(ABORT, 'chat turn message invariant violation');
END;
CREATE TRIGGER IF NOT EXISTS trg_chat_turns_append_only_update
BEFORE UPDATE ON chat_turns
BEGIN
    SELECT RAISE(ABORT, 'chat turns are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_summary_sources_valid_insert
BEFORE INSERT ON session_summary_sources
WHEN NOT EXISTS (
    SELECT 1 FROM session_summaries AS summary
    JOIN chat_turns AS turn ON turn.id = NEW.chat_turn_id
    WHERE summary.id = NEW.summary_id
      AND summary.session_id = turn.session_id
      AND NEW.turn_order = turn.turn_order
      AND (
          (NEW.message_order_in_turn = 0 AND NEW.message_id = turn.user_message_id)
          OR
          (NEW.message_order_in_turn = 1 AND NEW.message_id = turn.assistant_message_id)
      )
)
BEGIN
    SELECT RAISE(ABORT, 'summary source invariant violation');
END;
CREATE TRIGGER IF NOT EXISTS trg_summary_sources_append_only_update
BEFORE UPDATE ON session_summary_sources
BEGIN
    SELECT RAISE(ABORT, 'summary sources are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_summary_job_sources_valid_insert
BEFORE INSERT ON summary_job_sources
WHEN NOT EXISTS (
    SELECT 1 FROM summary_jobs AS job
    JOIN chat_turns AS turn ON turn.id = NEW.chat_turn_id
    WHERE job.id = NEW.job_id
      AND job.session_id = turn.session_id
      AND NEW.turn_order = turn.turn_order
      AND (
          (NEW.message_order_in_turn = 0 AND NEW.message_id = turn.user_message_id)
          OR
          (NEW.message_order_in_turn = 1 AND NEW.message_id = turn.assistant_message_id)
      )
)
BEGIN
    SELECT RAISE(ABORT, 'summary job source invariant violation');
END;
CREATE TRIGGER IF NOT EXISTS trg_summary_job_sources_sealed_insert
BEFORE INSERT ON summary_job_sources
WHEN COALESCE((
    SELECT source_manifest_sealed FROM summary_jobs WHERE id=NEW.job_id
), 1) = 1
BEGIN
    SELECT RAISE(ABORT, 'summary job source manifest is sealed');
END;
CREATE TRIGGER IF NOT EXISTS trg_summary_job_sources_sealed_delete
AFTER DELETE ON summary_job_sources
WHEN EXISTS (
    SELECT 1 FROM summary_jobs AS job
    JOIN sessions AS session ON session.id=job.session_id
    WHERE job.id=OLD.job_id AND job.source_manifest_sealed=1
)
BEGIN
    SELECT RAISE(ABORT, 'summary job source manifest is sealed');
END;
CREATE TRIGGER IF NOT EXISTS trg_summary_job_sources_append_only_update
BEFORE UPDATE ON summary_job_sources
BEGIN
    SELECT RAISE(ABORT, 'summary job sources are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_summary_jobs_frozen_snapshot_update_v4
BEFORE UPDATE ON summary_jobs
WHEN NOT (
    NEW.id IS OLD.id
    AND NEW.session_id IS OLD.session_id
    AND NEW.job_kind IS OLD.job_kind
    AND NEW.logical_source_identity IS OLD.logical_source_identity
    AND NEW.attempt_epoch IS OLD.attempt_epoch
    AND NEW.source_set_hash IS OLD.source_set_hash
    AND NEW.source_message_count IS OLD.source_message_count
    AND NEW.source_turn_count IS OLD.source_turn_count
    AND NEW.captured_barrier_generation IS OLD.captured_barrier_generation
    AND NEW.captured_processing_consent_generation IS OLD.captured_processing_consent_generation
    AND NEW.captured_processing_policy_fingerprint IS OLD.captured_processing_policy_fingerprint
    AND NEW.captured_session_deletion_generation IS OLD.captured_session_deletion_generation
    AND NEW.captured_suppression_generation IS OLD.captured_suppression_generation
    AND NEW.captured_rebuild_authorization_generation IS OLD.captured_rebuild_authorization_generation
    AND NEW.rebuild_permit_id IS OLD.rebuild_permit_id
    AND NEW.source_summary_id IS OLD.source_summary_id
    AND NEW.route IS OLD.route
    AND NEW.provider IS OLD.provider
    AND NEW.model IS OLD.model
    AND NEW.summarizer_schema_version IS OLD.summarizer_schema_version
    AND NEW.job_schema_version IS OLD.job_schema_version
    AND (
        NEW.source_manifest_sealed IS OLD.source_manifest_sealed
        OR (
            OLD.source_manifest_sealed = 0
            AND NEW.source_manifest_sealed = 1
            AND NEW.status = 'pending'
            AND OLD.status = 'pending'
        )
    )
    AND NEW.created_at IS OLD.created_at
    AND OLD.status IN ('pending', 'running')
)
BEGIN
    SELECT RAISE(ABORT, 'summary job snapshot invariant violation');
END;
CREATE TRIGGER IF NOT EXISTS trg_summary_exact_generated_requires_atomic_repository_v3
BEFORE INSERT ON session_summaries
WHEN NEW.source = 'generated' AND NEW.provenance_state = 'exact'
  AND NOT EXISTS (
      SELECT 1 FROM summary_commit_guards AS guard
      JOIN summary_jobs AS job ON job.id = guard.job_id
      WHERE guard.summary_id = NEW.id
        AND job.status = 'running'
        AND job.session_id = NEW.session_id
        AND job.source_set_hash = NEW.source_set_hash
        AND job.summarizer_schema_version = NEW.summarizer_schema_version
  )
BEGIN
    SELECT RAISE(ABORT, 'exact generated summaries require atomic repository commit');
END;
CREATE TRIGGER IF NOT EXISTS trg_summary_exact_redaction_requires_atomic_service
BEFORE UPDATE OF summary_text, payload_state ON session_summaries
WHEN OLD.provenance_state='exact'
  AND OLD.payload_state='active'
  AND NEW.payload_state='redacted'
  AND NEW.summary_text IS NULL
  AND NOT EXISTS (
      SELECT 1 FROM summary_redaction_guards AS guard
      WHERE guard.summary_id=OLD.id
  )
BEGIN
    SELECT RAISE(ABORT, 'exact summary redaction requires atomic service');
END;
CREATE TRIGGER IF NOT EXISTS trg_summary_exact_delete_requires_session_cascade
BEFORE DELETE ON session_summaries
WHEN OLD.provenance_state='exact'
  AND EXISTS (SELECT 1 FROM sessions WHERE id=OLD.session_id)
BEGIN
    SELECT RAISE(ABORT, 'exact summaries cannot be directly deleted');
END;
CREATE TRIGGER IF NOT EXISTS trg_summary_replacement_valid_insert
BEFORE INSERT ON session_summaries
WHEN NEW.replaces_summary_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM session_summaries AS replaced
    WHERE replaced.id = NEW.replaces_summary_id
      AND replaced.session_id = NEW.session_id
      AND replaced.created_at < NEW.created_at
)
BEGIN
    SELECT RAISE(ABORT, 'summary replacement invariant violation');
END;
CREATE TRIGGER IF NOT EXISTS trg_summary_replacement_valid_update
BEFORE UPDATE OF replaces_summary_id, session_id, created_at ON session_summaries
WHEN NEW.replaces_summary_id IS NOT OLD.replaces_summary_id
   OR NEW.session_id IS NOT OLD.session_id
   OR NEW.created_at IS NOT OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'summary replacement invariant violation');
END;
CREATE TRIGGER IF NOT EXISTS trg_summary_suppression_state_shape_insert_v2
BEFORE INSERT ON summary_source_suppressions
WHEN NEW.state <> 'suppressed' OR NOT (
    (NEW.state='suppressed' AND NEW.rebuild_permit_id IS NULL
     AND NEW.bound_job_id IS NULL AND NEW.authorized_summary_id IS NULL)
    OR
    (NEW.state='rebuild_authorized' AND NEW.rebuild_permit_id IS NOT NULL
     AND NEW.bound_job_id IS NULL AND NEW.authorized_summary_id IS NOT NULL)
    OR
    (NEW.state='rebuild_in_progress' AND NEW.rebuild_permit_id IS NOT NULL
     AND NEW.bound_job_id IS NOT NULL AND NEW.authorized_summary_id IS NOT NULL)
    OR
    (NEW.state='rebuild_completed' AND NEW.rebuild_permit_id IS NULL
     AND NEW.bound_job_id IS NULL AND NEW.authorized_summary_id IS NULL)
)
BEGIN
    SELECT RAISE(ABORT, 'summary suppression state invariant violation');
END;
CREATE TRIGGER IF NOT EXISTS trg_summary_suppression_state_shape_update
BEFORE UPDATE OF state, rebuild_permit_id, bound_job_id, authorized_summary_id
ON summary_source_suppressions
WHEN NOT (
    (NEW.state='suppressed' AND NEW.rebuild_permit_id IS NULL
     AND NEW.bound_job_id IS NULL AND NEW.authorized_summary_id IS NULL)
    OR
    (NEW.state='rebuild_authorized' AND NEW.rebuild_permit_id IS NOT NULL
     AND NEW.bound_job_id IS NULL AND NEW.authorized_summary_id IS NOT NULL)
    OR
    (NEW.state='rebuild_in_progress' AND NEW.rebuild_permit_id IS NOT NULL
     AND NEW.bound_job_id IS NOT NULL AND NEW.authorized_summary_id IS NOT NULL)
    OR
    (NEW.state='rebuild_completed' AND NEW.rebuild_permit_id IS NULL
     AND NEW.bound_job_id IS NULL AND NEW.authorized_summary_id IS NULL)
)
BEGIN
    SELECT RAISE(ABORT, 'summary suppression state invariant violation');
END;
CREATE TRIGGER IF NOT EXISTS trg_summary_suppression_transition_requires_atomic_service
BEFORE UPDATE ON summary_source_suppressions
WHEN NOT (
    NEW.session_id IS OLD.session_id
    AND NEW.source_set_hash IS OLD.source_set_hash
    AND NEW.generation = OLD.generation + 1
    AND (
        (OLD.state='suppressed' AND NEW.state IN (
            'suppressed', 'rebuild_authorized'
        ))
        OR
        (OLD.state='rebuild_authorized' AND NEW.state IN (
            'suppressed', 'rebuild_in_progress'
        ))
        OR
        (OLD.state='rebuild_in_progress' AND NEW.state IN (
            'suppressed', 'rebuild_completed'
        ))
        OR
        (OLD.state='rebuild_completed' AND NEW.state='suppressed')
    )
    AND EXISTS (
        SELECT 1 FROM summary_suppression_transition_guards AS guard
        WHERE guard.session_id=OLD.session_id
          AND guard.source_set_hash=OLD.source_set_hash
          AND guard.expected_generation=OLD.generation
          AND guard.target_generation=NEW.generation
          AND guard.target_state=NEW.state
    )
)
BEGIN
    SELECT RAISE(ABORT, 'summary suppression transition requires atomic service');
END;
CREATE TRIGGER IF NOT EXISTS trg_summary_suppression_delete_requires_session_cascade
BEFORE DELETE ON summary_source_suppressions
WHEN EXISTS (SELECT 1 FROM sessions WHERE id=OLD.session_id)
BEGIN
    SELECT RAISE(ABORT, 'summary suppressions cannot be directly deleted');
END;
"""

_C2_SUMMARY_STATE_TRIGGERS_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_session_summaries_controlled_update
BEFORE UPDATE ON session_summaries
WHEN NOT (
    OLD.id IS NEW.id
    AND OLD.session_id IS NEW.session_id
    AND OLD.source IS NEW.source
    AND OLD.covered_message_start_id IS NEW.covered_message_start_id
    AND OLD.covered_message_end_id IS NEW.covered_message_end_id
    AND OLD.message_count IS NEW.message_count
    AND OLD.metadata_json IS NEW.metadata_json
    AND OLD.created_at IS NEW.created_at
    AND OLD.replaces_summary_id IS NEW.replaces_summary_id
    AND (
        (
            OLD.payload_state = 'active'
            AND NEW.payload_state IN ('redacted', 'quarantined')
            AND NEW.summary_text IS NULL
            AND NEW.redacted_at IS NOT NULL
            AND NEW.redaction_reason_code IS NOT NULL
        )
        OR
        (
            OLD.payload_state = 'active'
            AND NEW.payload_state = 'active'
            AND OLD.summary_text IS NEW.summary_text
            AND OLD.provenance_state IS NEW.provenance_state
            AND OLD.source_set_hash IS NEW.source_set_hash
            AND OLD.summarizer_schema_version IS NEW.summarizer_schema_version
            AND OLD.injection_schema_version IS NEW.injection_schema_version
            AND OLD.redacted_at IS NEW.redacted_at
            AND OLD.redaction_reason_code IS NEW.redaction_reason_code
            AND OLD.observed_memory_summary_barrier <> NEW.observed_memory_summary_barrier
        )
    )
)
BEGIN
    SELECT RAISE(ABORT, 'summary payload invariant violation');
END;
"""


def _execute_script(connection: sqlite3.Connection, script: str) -> None:
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            sql = statement.strip()
            if sql:
                connection.execute(sql)
            statement = ""
    if statement.strip():
        raise ValueError("incomplete Gate C2 migration SQL")


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in connection.execute(f'PRAGMA table_info("{table}")')
    }


def _turn_id(session_id: str, user_id: str, assistant_id: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"gate-c2-turn:{session_id}:{user_id}:{assistant_id}",
        )
    )


def _source_hash(
    *,
    session_id: str,
    turns: list[sqlite3.Row],
) -> str:
    return canonical_summary_source_set_hash(
        session_id=session_id,
        turns=[
            {
                "turn_id": str(turn["id"]),
                "turn_order": int(turn["turn_order"]),
                "messages": [
                    {
                        "message_id": str(turn["user_message_id"]),
                        "message_order_in_turn": 0,
                    },
                    {
                        "message_id": str(turn["assistant_message_id"]),
                        "message_order_in_turn": 1,
                    },
                ],
            }
            for turn in turns
        ],
    )


def _inbound_foreign_keys(
    connection: sqlite3.Connection,
    table: str,
) -> list[tuple[str, str, str]]:
    inbound: list[tuple[str, str, str]] = []
    tables = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for table_row in tables:
        child_table = str(table_row["name"])
        if child_table == table:
            continue
        foreign_keys = connection.execute(
            f'PRAGMA foreign_key_list("{child_table}")'
        ).fetchall()
        for foreign_key in foreign_keys:
            if str(foreign_key["table"]) == table:
                inbound.append(
                    (
                        child_table,
                        str(foreign_key["from"]),
                        str(foreign_key["to"]),
                    )
                )
    return inbound


def _rebuild_summary_table(connection: sqlite3.Connection) -> None:
    columns = _columns(connection, "session_summaries")
    if "payload_state" in columns:
        return
    inbound_foreign_keys = _inbound_foreign_keys(connection, "session_summaries")
    if inbound_foreign_keys:
        raise RuntimeError(
            "Gate C2 cannot safely rebuild session_summaries with inbound foreign keys"
        )
    _execute_script(
        connection,
        """
        ALTER TABLE session_summaries RENAME TO session_summaries_pre_c2;
        CREATE TABLE session_summaries (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            summary_text TEXT,
            source TEXT NOT NULL CHECK (source IN ('manual', 'generated')),
            covered_message_start_id TEXT,
            covered_message_end_id TEXT,
            message_count INTEGER NOT NULL CHECK (message_count >= 0),
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            observed_memory_summary_barrier INTEGER NOT NULL DEFAULT 0 CHECK (observed_memory_summary_barrier >= 0),
            payload_state TEXT NOT NULL DEFAULT 'active' CHECK (payload_state IN ('active', 'redacted', 'quarantined')),
            source_set_hash TEXT,
            summarizer_schema_version TEXT,
            injection_schema_version TEXT,
            replaces_summary_id TEXT,
            provenance_state TEXT NOT NULL DEFAULT 'legacy_unverified' CHECK (provenance_state IN ('exact', 'legacy_unverified')),
            redacted_at TEXT,
            redaction_reason_code TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (covered_message_start_id) REFERENCES messages(id) ON DELETE SET NULL,
            FOREIGN KEY (covered_message_end_id) REFERENCES messages(id) ON DELETE SET NULL,
            FOREIGN KEY (replaces_summary_id) REFERENCES session_summaries(id) ON DELETE RESTRICT,
            CHECK (
                (payload_state = 'active' AND summary_text IS NOT NULL AND length(trim(summary_text)) > 0
                 AND length(summary_text) <= 8000
                 AND redacted_at IS NULL AND redaction_reason_code IS NULL)
                OR
                (payload_state IN ('redacted', 'quarantined') AND summary_text IS NULL
                 AND redacted_at IS NOT NULL AND redaction_reason_code IS NOT NULL)
            ),
            CHECK (replaces_summary_id IS NULL OR replaces_summary_id <> id)
        );
        INSERT INTO session_summaries (
            id, session_id, summary_text, source, covered_message_start_id,
            covered_message_end_id, message_count, metadata_json, created_at,
            updated_at, observed_memory_summary_barrier, payload_state,
            provenance_state, redacted_at, redaction_reason_code
        )
        SELECT id, session_id,
               CASE
                   WHEN length(trim(summary_text)) = 0
                     OR length(summary_text) > 8000 THEN NULL
                   ELSE summary_text
               END,
               source, covered_message_start_id, covered_message_end_id,
               message_count, '{}', created_at, updated_at,
               observed_memory_summary_barrier,
               CASE
                   WHEN length(trim(summary_text)) = 0
                     OR length(summary_text) > 8000 THEN 'quarantined'
                   ELSE 'active'
               END,
               'legacy_unverified',
               CASE
                   WHEN length(trim(summary_text)) = 0
                     OR length(summary_text) > 8000 THEN updated_at
                   ELSE NULL
               END,
               CASE
                   WHEN length(trim(summary_text)) = 0
                       THEN 'migration_corrupt_payload'
                   WHEN length(summary_text) > 8000
                       THEN 'migration_oversized_payload'
                   ELSE NULL
               END
        FROM session_summaries_pre_c2;
        DROP TABLE session_summaries_pre_c2;
        CREATE INDEX IF NOT EXISTS idx_session_summaries_session_created
        ON session_summaries(session_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_session_summaries_session_updated
        ON session_summaries(session_id, updated_at DESC);
        """,
    )


def _reconstruct_turns(connection: sqlite3.Connection) -> None:
    sessions = connection.execute(
        "SELECT id FROM sessions ORDER BY created_at, id"
    ).fetchall()
    for session in sessions:
        session_id = str(session["id"])
        rows = connection.execute(
            "SELECT id, role, created_at FROM messages WHERE session_id=? "
            "ORDER BY created_at, rowid",
            (session_id,),
        ).fetchall()
        turn_order = 1
        index = 0
        while index + 1 < len(rows):
            user = rows[index]
            assistant = rows[index + 1]
            previous_role = str(rows[index - 1]["role"]) if index > 0 else None
            following_role = (
                str(rows[index + 2]["role"])
                if index + 2 < len(rows)
                else None
            )
            deterministic_pair = (
                str(user["role"]) == "user"
                and str(assistant["role"]) == "assistant"
                and previous_role != "user"
                and following_role != "assistant"
            )
            if deterministic_pair:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO chat_turns (
                        id, session_id, user_message_id, assistant_message_id,
                        turn_order, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _turn_id(session_id, str(user["id"]), str(assistant["id"])),
                        session_id,
                        str(user["id"]),
                        str(assistant["id"]),
                        turn_order,
                        str(assistant["created_at"]),
                    ),
                )
                turn_order += 1
                index += 2
            else:
                index += 1


def _expand_exclusions(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        "SELECT source_message_id, reason_code, created_at "
        "FROM memory_summary_source_exclusions"
    ).fetchall()
    for row in rows:
        message_id = str(row["source_message_id"])
        turn = connection.execute(
            "SELECT user_message_id, assistant_message_id FROM chat_turns "
            "WHERE user_message_id=? OR assistant_message_id=?",
            (message_id, message_id),
        ).fetchone()
        if turn is None:
            continue
        for member in (str(turn["user_message_id"]), str(turn["assistant_message_id"])):
            connection.execute(
                "INSERT OR IGNORE INTO memory_summary_source_exclusions "
                "(source_message_id, reason_code, created_at) VALUES (?, ?, ?)",
                (member, str(row["reason_code"]), str(row["created_at"])),
            )


def _covered_message_ids(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> list[str] | None:
    start_id = row["covered_message_start_id"]
    end_id = row["covered_message_end_id"]
    if start_id is None or end_id is None:
        return None
    messages = connection.execute(
        "SELECT id FROM messages WHERE session_id=? ORDER BY created_at, rowid",
        (str(row["session_id"]),),
    ).fetchall()
    ids = [str(message["id"]) for message in messages]
    try:
        start = ids.index(str(start_id))
        end = ids.index(str(end_id))
    except ValueError:
        return None
    if start > end:
        return None
    covered = ids[start : end + 1]
    if len(covered) != int(row["message_count"]):
        return None
    return covered


def _mapped_turns_for_coverage(
    connection: sqlite3.Connection,
    session_id: str,
    covered_ids: list[str],
) -> list[sqlite3.Row] | None:
    if len(covered_ids) % 2:
        return None
    turns: list[sqlite3.Row] = []
    for index in range(0, len(covered_ids), 2):
        user_id, assistant_id = covered_ids[index : index + 2]
        row = connection.execute(
            "SELECT * FROM chat_turns WHERE session_id=? "
            "AND user_message_id=? AND assistant_message_id=?",
            (session_id, user_id, assistant_id),
        ).fetchone()
        if row is None:
            return None
        turns.append(row)
    if any(
        int(right["turn_order"]) != int(left["turn_order"]) + 1
        for left, right in zip(turns, turns[1:])
    ):
        return None
    return turns


def _invalidate_summary(
    connection: sqlite3.Connection,
    summary_id: str,
    *,
    state: str,
    reason: str,
    timestamp: str,
) -> None:
    action = "quarantined" if state == "quarantined" else "migration_invalidated"
    connection.execute(
        """
        UPDATE session_summaries
        SET summary_text=NULL, metadata_json='{}', payload_state=?,
            provenance_state='legacy_unverified', source_set_hash=NULL,
            summarizer_schema_version=NULL, injection_schema_version=NULL,
            redacted_at=?, redaction_reason_code=?
        WHERE id=?
        """,
        (state, timestamp, reason, summary_id),
    )
    connection.execute(
        """
        INSERT INTO summary_payload_audits (
            id, summary_id, action, payload_state, reason_code, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid5(NAMESPACE_URL, f"gate-c2-migration-audit:{summary_id}:{reason}")),
            summary_id,
            action,
            state,
            reason,
            timestamp,
        ),
    )


def _redact_summary(
    connection: sqlite3.Connection,
    summary_id: str,
    *,
    reason: str,
    timestamp: str,
) -> None:
    _invalidate_summary(
        connection,
        summary_id,
        state="redacted",
        reason=reason,
        timestamp=timestamp,
    )


def _reconcile_summaries(connection: sqlite3.Connection) -> None:
    barrier_row = connection.execute(
        "SELECT generation FROM memory_summary_barrier WHERE singleton_id=1"
    ).fetchone()
    current_barrier = int(barrier_row["generation"]) if barrier_row is not None else 0
    exclusions = {
        str(row["source_message_id"])
        for row in connection.execute(
            "SELECT source_message_id FROM memory_summary_source_exclusions"
        )
    }
    rows = connection.execute(
        "SELECT * FROM session_summaries ORDER BY created_at, id"
    ).fetchall()
    for row in rows:
        summary_id = str(row["id"])
        timestamp = str(row["updated_at"])
        payload_state = str(row["payload_state"])
        if payload_state == "quarantined":
            _invalidate_summary(
                connection,
                summary_id,
                state="quarantined",
                reason=str(row["redaction_reason_code"]),
                timestamp=timestamp,
            )
            continue
        summary_text = row["summary_text"]
        if summary_text is None or not str(summary_text).strip():
            _invalidate_summary(
                connection,
                summary_id,
                state="quarantined",
                reason="migration_corrupt_payload",
                timestamp=timestamp,
            )
            continue
        if len(str(summary_text)) > 8_000:
            _invalidate_summary(
                connection,
                summary_id,
                state="quarantined",
                reason="migration_oversized_payload",
                timestamp=timestamp,
            )
            continue
        covered_ids = _covered_message_ids(connection, row)
        if covered_ids is None:
            _redact_summary(
                connection,
                summary_id,
                reason="migration_unmappable_provenance",
                timestamp=timestamp,
            )
            continue
        turns = _mapped_turns_for_coverage(
            connection,
            str(row["session_id"]),
            covered_ids,
        )
        if turns is None:
            _redact_summary(
                connection,
                summary_id,
                reason="migration_legacy_unverified",
                timestamp=timestamp,
            )
            continue
        if int(row["observed_memory_summary_barrier"]) != current_barrier:
            _redact_summary(
                connection,
                summary_id,
                reason="migration_stale_barrier",
                timestamp=timestamp,
            )
            continue
        if exclusions.intersection(covered_ids):
            _redact_summary(
                connection,
                summary_id,
                reason="migration_excluded_turn",
                timestamp=timestamp,
            )
            continue
        source_set_hash = _source_hash(
            session_id=str(row["session_id"]),
            turns=turns,
        )
        connection.execute(
            """
            UPDATE session_summaries
            SET payload_state='active', provenance_state='exact',
                source_set_hash=?, summarizer_schema_version=?,
                injection_schema_version=?, redacted_at=NULL,
                redaction_reason_code=NULL
            WHERE id=?
            """,
            (
                source_set_hash,
                SUMMARY_SCHEMA_VERSION,
                SUMMARY_INJECTION_SCHEMA_VERSION,
                summary_id,
            ),
        )
        source_order = 0
        for turn in turns:
            for message_order, message_id in enumerate(
                (str(turn["user_message_id"]), str(turn["assistant_message_id"]))
            ):
                connection.execute(
                    """
                    INSERT INTO session_summary_sources (
                        summary_id, chat_turn_id, message_id, turn_order,
                        message_order_in_turn, source_order
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        summary_id,
                        str(turn["id"]),
                        message_id,
                        int(turn["turn_order"]),
                        message_order,
                        source_order,
                    ),
                )
                source_order += 1


def _drop_obsolete_gate_c2_triggers(connection: sqlite3.Connection) -> None:
    obsolete = (
        "trg_summary_exact_generated_requires_atomic_repository",
    )
    for name in obsolete:
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?",
            (name,),
        ).fetchone() is not None:
            connection.execute(f'DROP TRIGGER "{name}"')


def _add_summary_suppression_runtime_columns(
    connection: sqlite3.Connection,
) -> None:
    columns = _columns(connection, "summary_source_suppressions")
    if "authorized_summary_id" not in columns:
        connection.execute(
            "ALTER TABLE summary_source_suppressions "
            "ADD COLUMN authorized_summary_id TEXT"
        )


def _add_summary_job_runtime_columns(connection: sqlite3.Connection) -> None:
    columns = _columns(connection, "summary_jobs")
    if "job_schema_version" not in columns:
        connection.execute(
            "ALTER TABLE summary_jobs ADD COLUMN job_schema_version TEXT "
            "NOT NULL DEFAULT 'summary-job-v1'"
        )
    if "captured_rebuild_authorization_generation" not in columns:
        connection.execute(
            "ALTER TABLE summary_jobs ADD COLUMN "
            "captured_rebuild_authorization_generation INTEGER NOT NULL DEFAULT 0 "
            "CHECK (captured_rebuild_authorization_generation >= 0)"
        )
    if "source_summary_id" not in columns:
        connection.execute(
            "ALTER TABLE summary_jobs ADD COLUMN source_summary_id TEXT"
        )
    if "source_manifest_sealed" not in columns:
        connection.execute(
            "ALTER TABLE summary_jobs ADD COLUMN source_manifest_sealed INTEGER "
            "NOT NULL DEFAULT 0 CHECK (source_manifest_sealed IN (0, 1))"
        )
        connection.execute(
            "UPDATE summary_jobs SET source_manifest_sealed=1"
        )


def _add_memory_job_chat_turn_link(connection: sqlite3.Connection) -> None:
    memory_jobs_exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_jobs'"
    ).fetchone()
    if memory_jobs_exists is None:
        return
    if "chat_turn_id" not in _columns(connection, "memory_jobs"):
        connection.execute(
            "ALTER TABLE memory_jobs ADD COLUMN chat_turn_id TEXT"
        )
    _execute_script(
        connection,
        """
        CREATE TRIGGER IF NOT EXISTS trg_memory_jobs_chat_turn_valid_insert
        BEFORE INSERT ON memory_jobs
        WHEN NEW.chat_turn_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM chat_turns
            WHERE id=NEW.chat_turn_id
              AND session_id=NEW.session_id
              AND user_message_id=NEW.user_message_id
              AND assistant_message_id=NEW.assistant_message_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'memory job chat turn invariant violation');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_memory_jobs_chat_turn_frozen_update
        BEFORE UPDATE OF chat_turn_id ON memory_jobs
        WHEN OLD.chat_turn_id IS NOT NEW.chat_turn_id
        BEGIN
            SELECT RAISE(ABORT, 'memory job chat turn is immutable');
        END;
        """,
    )


def _postconditions(connection: sqlite3.Connection) -> None:
    if connection.execute(
        "SELECT 1 FROM session_summaries WHERE payload_state IN ('redacted', 'quarantined') "
        "AND summary_text IS NOT NULL LIMIT 1"
    ).fetchone() is not None:
        raise RuntimeError("redacted summary retained payload")
    if connection.execute(
        "SELECT 1 FROM session_summaries WHERE payload_state='active' "
        "AND (summary_text IS NULL OR length(trim(summary_text))=0 OR length(summary_text)>8000) "
        "LIMIT 1"
    ).fetchone() is not None:
        raise RuntimeError("active summary payload invariant failed")
    exact_rows = connection.execute(
        "SELECT id, session_id, source_set_hash FROM session_summaries "
        "WHERE payload_state='active' AND provenance_state='exact'"
    ).fetchall()
    for row in exact_rows:
        sources = connection.execute(
            """
            SELECT source.chat_turn_id, source.message_id, source.turn_order,
                   source.message_order_in_turn, source.source_order,
                   turn.user_message_id, turn.assistant_message_id
            FROM session_summary_sources AS source
            JOIN chat_turns AS turn ON turn.id=source.chat_turn_id
            WHERE source.summary_id=?
            ORDER BY source.source_order
            """,
            (str(row["id"]),),
        ).fetchall()
        if not sources or len(sources) % 2:
            raise RuntimeError("Gate C2 exact summary source map validation failed")
        mapped_turns: list[sqlite3.Row] = []
        for index in range(0, len(sources), 2):
            user_source = sources[index]
            assistant_source = sources[index + 1]
            if (
                int(user_source["source_order"]) != index
                or int(assistant_source["source_order"]) != index + 1
                or str(user_source["chat_turn_id"])
                != str(assistant_source["chat_turn_id"])
                or int(user_source["turn_order"])
                != int(assistant_source["turn_order"])
                or int(user_source["message_order_in_turn"]) != 0
                or int(assistant_source["message_order_in_turn"]) != 1
                or str(user_source["message_id"])
                != str(user_source["user_message_id"])
                or str(assistant_source["message_id"])
                != str(assistant_source["assistant_message_id"])
            ):
                raise RuntimeError("Gate C2 exact summary source map validation failed")
            turn = connection.execute(
                "SELECT * FROM chat_turns WHERE id=? AND session_id=?",
                (str(user_source["chat_turn_id"]), str(row["session_id"])),
            ).fetchone()
            if turn is None:
                raise RuntimeError("Gate C2 exact summary source map validation failed")
            mapped_turns.append(turn)
        expected_hash = _source_hash(
            session_id=str(row["session_id"]),
            turns=mapped_turns,
        )
        if str(row["source_set_hash"]) != expected_hash:
            raise RuntimeError("Gate C2 exact summary source map hash validation failed")
    foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        raise RuntimeError("Gate C2 foreign key validation failed")


def migrate_gate_c2(
    connection: sqlite3.Connection,
    *,
    fault_injector: Callable[[str], None] | None = None,
) -> None:
    if not connection.in_transaction:
        raise RuntimeError("Gate C2 migration requires caller-owned transaction")
    already_migrated = "payload_state" in _columns(
        connection,
        "session_summaries",
    )
    _rebuild_summary_table(connection)
    _drop_obsolete_gate_c2_triggers(connection)
    _execute_script(connection, _C2_TABLES_SQL)
    _add_summary_job_runtime_columns(connection)
    _add_summary_suppression_runtime_columns(connection)
    _add_memory_job_chat_turn_link(connection)
    if already_migrated:
        _execute_script(connection, _C2_SUMMARY_STATE_TRIGGERS_SQL)
        _postconditions(connection)
        return
    _reconstruct_turns(connection)
    _expand_exclusions(connection)
    _reconcile_summaries(connection)
    _execute_script(connection, _C2_SUMMARY_STATE_TRIGGERS_SQL)
    if fault_injector is not None:
        fault_injector("post_scrub")
    _postconditions(connection)
