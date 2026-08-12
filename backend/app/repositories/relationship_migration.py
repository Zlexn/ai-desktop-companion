from __future__ import annotations

import sqlite3
from collections.abc import Callable


_SUBJECT_CODE_CHECK = (
    "canonical_subject_code IS NULL OR "
    "(memory_type = 'relationship_event' AND canonical_subject_code IN "
    "('preferred_address', 'shared_experience', 'non_external_commitment')) OR "
    "(memory_type IN ('preference', 'user_fact') AND "
    "canonical_subject_code = 'preferred_address')"
)

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

_REQUIRED_C3_TRIGGERS = {
    "trg_relationship_apply_source_classification_insert",
    "trg_relationship_revoke_valid_insert",
    "trg_relationship_redaction_guard_valid_insert",
    "trg_relationship_events_append_only_update",
    "trg_relationship_events_append_only_delete",
    "trg_relationship_authority_linear_insert",
    "trg_relationship_authority_epoch_after_decision_insert",
    "trg_relationship_authority_epoch_insert_guard",
    "trg_relationship_authority_epoch_update",
    "trg_relationship_authority_epoch_delete",
    "trg_relationship_lineage_epoch_after_insert",
    "trg_relationship_lineage_append_only_update",
    "trg_relationship_lineage_append_only_delete",
    "trg_relationship_jobs_frozen_snapshot_update",
    "trg_relationship_jobs_append_only_delete",
    "trg_relationship_job_audits_append_only_update",
    "trg_relationship_job_audits_append_only_delete",
    "trg_relationship_audits_append_only_update",
    "trg_relationship_audits_append_only_delete",
    "trg_relationship_projections_immutable_update",
    "trg_relationship_projections_immutable_delete",
    "trg_relationship_projection_pointer_valid_insert",
    "trg_relationship_projection_pointer_cas_update",
    "trg_relationship_projection_pointer_delete",
}

_C3_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS relationship_authority_epoch (
    scope_id TEXT PRIMARY KEY,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS relationship_events (
    id TEXT PRIMARY KEY,
    scope_id TEXT NOT NULL,
    event_kind TEXT NOT NULL CHECK (event_kind IN ('apply', 'revoke')),
    event_type TEXT NOT NULL CHECK (event_type IN (
        'preferred_address', 'shared_experience', 'non_external_commitment'
    )),
    subject_code TEXT NOT NULL CHECK (subject_code IN (
        'preferred_address', 'shared_experience', 'non_external_commitment'
    )),
    payload_state TEXT NOT NULL CHECK (payload_state IN ('active', 'redacted')),
    payload_json TEXT,
    source_memory_id TEXT NOT NULL,
    source_memory_version_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    observed_time_derivation_version TEXT NOT NULL,
    revokes_event_id TEXT,
    rule_version TEXT NOT NULL,
    persona_artifact_id TEXT NOT NULL,
    event_schema_version TEXT NOT NULL,
    integrity_fingerprint TEXT NOT NULL CHECK (length(integrity_fingerprint) = 64),
    created_at TEXT NOT NULL,
    FOREIGN KEY (source_memory_id) REFERENCES memories(id) ON DELETE RESTRICT,
    FOREIGN KEY (source_memory_id, source_memory_version_id)
        REFERENCES memory_versions(memory_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (revokes_event_id) REFERENCES relationship_events(id) ON DELETE RESTRICT,
    FOREIGN KEY (persona_artifact_id) REFERENCES persona_artifacts(id) ON DELETE RESTRICT,
    CHECK (event_type = subject_code),
    CHECK (
        (event_kind = 'apply' AND revokes_event_id IS NULL AND
         ((payload_state = 'active' AND payload_json IS NOT NULL AND json_valid(payload_json)) OR
          (payload_state = 'redacted' AND payload_json IS NULL)))
        OR
        (event_kind = 'revoke' AND revokes_event_id IS NOT NULL AND
         payload_state = 'active' AND payload_json IS NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_relationship_apply_identity
ON relationship_events(
    scope_id, source_memory_version_id, rule_version, event_type, subject_code
) WHERE event_kind = 'apply';

CREATE UNIQUE INDEX IF NOT EXISTS idx_relationship_revoke_target
ON relationship_events(revokes_event_id) WHERE event_kind = 'revoke';

CREATE INDEX IF NOT EXISTS idx_relationship_events_semantic_order
ON relationship_events(
    scope_id, observed_at, source_memory_id, source_memory_version_id,
    event_type, subject_code, id
);

CREATE TABLE IF NOT EXISTS relationship_redaction_guards (
    event_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    FOREIGN KEY (event_id) REFERENCES relationship_events(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS relationship_authority_decisions (
    id TEXT PRIMARY KEY,
    scope_id TEXT NOT NULL,
    source_memory_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'preferred_address', 'shared_experience', 'non_external_commitment'
    )),
    subject_code TEXT NOT NULL CHECK (subject_code IN (
        'preferred_address', 'shared_experience', 'non_external_commitment'
    )),
    predecessor_decision_id TEXT UNIQUE,
    generation INTEGER NOT NULL CHECK (generation >= 1),
    action TEXT NOT NULL CHECK (action IN ('suppress', 'reenable')),
    action_kind TEXT NOT NULL CHECK (action_kind IN (
        'user_revoke', 'privacy_redact', 'user_reenable',
        'inherited_conflict_suppression'
    )),
    reason_code TEXT NOT NULL,
    inherited_authority_fingerprint TEXT CHECK (
        inherited_authority_fingerprint IS NULL OR
        length(inherited_authority_fingerprint) = 64
    ),
    created_at TEXT NOT NULL,
    FOREIGN KEY (source_memory_id) REFERENCES memories(id) ON DELETE RESTRICT,
    FOREIGN KEY (predecessor_decision_id)
        REFERENCES relationship_authority_decisions(id) ON DELETE RESTRICT,
    UNIQUE (scope_id, source_memory_id, event_type, subject_code, generation),
    CHECK (event_type = subject_code),
    CHECK (
        (generation = 1 AND predecessor_decision_id IS NULL) OR
        (generation > 1 AND predecessor_decision_id IS NOT NULL)
    ),
    CHECK (
        (action = 'reenable' AND action_kind = 'user_reenable' AND
         inherited_authority_fingerprint IS NOT NULL) OR
        (action = 'suppress' AND action_kind <> 'user_reenable' AND
         inherited_authority_fingerprint IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_relationship_authority_latest
ON relationship_authority_decisions(
    scope_id, source_memory_id, event_type, subject_code, generation DESC, id DESC
);

CREATE TABLE IF NOT EXISTS relationship_memory_lineage (
    resolved_memory_id TEXT NOT NULL,
    contributing_memory_id TEXT NOT NULL,
    conflict_id TEXT NOT NULL,
    resolution_kind TEXT NOT NULL CHECK (resolution_kind IN (
        'choose_left', 'choose_right', 'replace_both', 'both_contextual'
    )),
    created_at TEXT NOT NULL,
    PRIMARY KEY (resolved_memory_id, contributing_memory_id),
    FOREIGN KEY (resolved_memory_id) REFERENCES memories(id) ON DELETE RESTRICT,
    FOREIGN KEY (contributing_memory_id) REFERENCES memories(id) ON DELETE RESTRICT,
    FOREIGN KEY (conflict_id) REFERENCES memory_conflicts(conflict_id) ON DELETE RESTRICT,
    CHECK (resolved_memory_id <> contributing_memory_id)
);

CREATE INDEX IF NOT EXISTS idx_relationship_lineage_contributor
ON relationship_memory_lineage(contributing_memory_id, resolved_memory_id);

CREATE TABLE IF NOT EXISTS relationship_reconcile_jobs (
    id TEXT PRIMARY KEY,
    scope_id TEXT NOT NULL,
    source_memory_id TEXT NOT NULL,
    source_memory_version_id TEXT NOT NULL,
    captured_record_head_version INTEGER NOT NULL CHECK (captured_record_head_version >= 1),
    captured_record_generation INTEGER NOT NULL CHECK (captured_record_generation >= 0),
    captured_record_state TEXT NOT NULL CHECK (
        captured_record_state IN ('active', 'archived', 'conflicted', 'deleted')
    ),
    captured_event_type TEXT NOT NULL CHECK (captured_event_type IN (
        'preferred_address', 'shared_experience', 'non_external_commitment'
    )),
    captured_subject_code TEXT NOT NULL CHECK (captured_subject_code IN (
        'preferred_address', 'shared_experience', 'non_external_commitment'
    )),
    captured_authority_decision_id TEXT,
    captured_authority_generation INTEGER NOT NULL CHECK (captured_authority_generation >= 0),
    captured_authority_epoch INTEGER NOT NULL CHECK (captured_authority_epoch >= 0),
    captured_inherited_authority_fingerprint TEXT NOT NULL
        CHECK (length(captured_inherited_authority_fingerprint) = 64),
    relationship_rule_version TEXT NOT NULL,
    persona_artifact_id TEXT NOT NULL,
    job_schema_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'pending', 'running', 'succeeded', 'failed', 'cancelled', 'skipped'
    )),
    outcome TEXT CHECK (outcome IS NULL OR outcome IN (
        'applied', 'revoked', 'no_change', 'skipped_ineligible',
        'skipped_suppressed', 'stale_source', 'stale_authority',
        'incompatible_recovery', 'failed', 'cancelled'
    )),
    attempt_count INTEGER NOT NULL CHECK (attempt_count >= 0),
    reason_code TEXT,
    error_category TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    FOREIGN KEY (source_memory_id) REFERENCES memories(id) ON DELETE RESTRICT,
    FOREIGN KEY (source_memory_id, source_memory_version_id)
        REFERENCES memory_versions(memory_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (captured_authority_decision_id)
        REFERENCES relationship_authority_decisions(id) ON DELETE RESTRICT,
    FOREIGN KEY (persona_artifact_id) REFERENCES persona_artifacts(id) ON DELETE RESTRICT,
    CHECK (captured_event_type = captured_subject_code),
    CHECK (
        (captured_authority_generation = 0 AND captured_authority_decision_id IS NULL) OR
        (captured_authority_generation > 0 AND captured_authority_decision_id IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_relationship_job_attempt_identity
ON relationship_reconcile_jobs(
    scope_id, source_memory_version_id, relationship_rule_version,
    captured_authority_generation, captured_authority_epoch,
    captured_inherited_authority_fingerprint
);

CREATE INDEX IF NOT EXISTS idx_relationship_jobs_status_created
ON relationship_reconcile_jobs(status, created_at, id);

CREATE TABLE IF NOT EXISTS relationship_job_audits (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    attempt_count INTEGER NOT NULL CHECK (attempt_count >= 0),
    created_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES relationship_reconcile_jobs(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS relationship_audits (
    id TEXT PRIMARY KEY,
    action TEXT NOT NULL CHECK (action IN (
        'reconciled', 'projected', 'authority_changed',
        'payload_redacted', 'recovery_terminalized'
    )),
    outcome TEXT,
    reason_code TEXT NOT NULL,
    source_memory_id TEXT,
    event_id TEXT,
    projection_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (source_memory_id) REFERENCES memories(id) ON DELETE RESTRICT,
    FOREIGN KEY (event_id) REFERENCES relationship_events(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS relationship_projections (
    projection_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL CHECK (version >= 1),
    scope_id TEXT NOT NULL,
    persona_artifact_id TEXT NOT NULL,
    projection_rule_version TEXT NOT NULL,
    familiarity REAL NOT NULL CHECK (
        typeof(familiarity) IN ('real', 'integer') AND familiarity >= 0.0 AND familiarity <= 1.0
    ),
    preferred_address_event_id TEXT,
    relationship_summary_code TEXT NOT NULL CHECK (
        relationship_summary_code IN ('reserved', 'steady', 'familiar', 'close')
    ),
    source_relationship_event_ids_json TEXT NOT NULL
        CHECK (json_valid(source_relationship_event_ids_json) AND
               json_type(source_relationship_event_ids_json) = 'array'),
    source_emotion_snapshot_id TEXT CHECK (source_emotion_snapshot_id IS NULL),
    computed_at TEXT NOT NULL,
    integrity_fingerprint TEXT NOT NULL CHECK (length(integrity_fingerprint) = 64),
    FOREIGN KEY (persona_artifact_id) REFERENCES persona_artifacts(id) ON DELETE RESTRICT,
    FOREIGN KEY (preferred_address_event_id)
        REFERENCES relationship_events(id) ON DELETE RESTRICT,
    UNIQUE (version),
    UNIQUE (scope_id, projection_id, version)
);

CREATE INDEX IF NOT EXISTS idx_relationship_projections_scope_version
ON relationship_projections(scope_id, version DESC);

CREATE TABLE IF NOT EXISTS relationship_projection_active_state (
    scope_id TEXT PRIMARY KEY,
    projection_id TEXT NOT NULL,
    projection_version INTEGER NOT NULL CHECK (projection_version >= 1),
    generation INTEGER NOT NULL CHECK (generation >= 0),
    updated_at TEXT NOT NULL,
    FOREIGN KEY (scope_id, projection_id, projection_version)
        REFERENCES relationship_projections(scope_id, projection_id, version)
        ON DELETE RESTRICT
);

CREATE TRIGGER IF NOT EXISTS trg_relationship_apply_source_classification_insert
BEFORE INSERT ON relationship_events
WHEN NEW.event_kind = 'apply' AND NOT EXISTS (
    SELECT 1 FROM memory_versions AS source
    WHERE source.id = NEW.source_memory_version_id
      AND source.memory_id = NEW.source_memory_id
      AND source.canonical_subject_code = NEW.subject_code
      AND (
          (source.memory_type = 'relationship_event' AND NEW.subject_code IN (
              'preferred_address', 'shared_experience', 'non_external_commitment'
          )) OR
          (source.memory_type IN ('preference', 'user_fact') AND
           NEW.subject_code = 'preferred_address')
      )
)
BEGIN SELECT RAISE(ABORT, 'relationship apply source classification invariant violation'); END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_revoke_valid_insert
BEFORE INSERT ON relationship_events
WHEN NEW.event_kind = 'revoke' AND NOT EXISTS (
    SELECT 1 FROM relationship_events AS target
    WHERE target.id = NEW.revokes_event_id
      AND target.event_kind = 'apply'
      AND target.scope_id = NEW.scope_id
      AND target.event_type = NEW.event_type
      AND target.subject_code = NEW.subject_code
      AND target.source_memory_id = NEW.source_memory_id
      AND target.source_memory_version_id = NEW.source_memory_version_id
)
BEGIN SELECT RAISE(ABORT, 'relationship revoke invariant violation'); END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_redaction_guard_valid_insert
BEFORE INSERT ON relationship_redaction_guards
WHEN NOT EXISTS (
    SELECT 1 FROM relationship_events
    WHERE id = NEW.event_id AND event_kind = 'apply'
      AND event_type = 'preferred_address'
      AND payload_state = 'active' AND payload_json IS NOT NULL
)
BEGIN SELECT RAISE(ABORT, 'relationship redaction guard invariant violation'); END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_events_append_only_update
BEFORE UPDATE ON relationship_events
WHEN NOT (
    OLD.event_kind = 'apply' AND OLD.event_type = 'preferred_address'
    AND OLD.payload_state = 'active' AND NEW.payload_state = 'redacted'
    AND OLD.payload_json IS NOT NULL AND NEW.payload_json IS NULL
    AND EXISTS (SELECT 1 FROM relationship_redaction_guards WHERE event_id = OLD.id)
    AND NEW.id IS OLD.id
    AND NEW.scope_id IS OLD.scope_id
    AND NEW.event_kind IS OLD.event_kind
    AND NEW.event_type IS OLD.event_type
    AND NEW.subject_code IS OLD.subject_code
    AND NEW.source_memory_id IS OLD.source_memory_id
    AND NEW.source_memory_version_id IS OLD.source_memory_version_id
    AND NEW.observed_at IS OLD.observed_at
    AND NEW.observed_time_derivation_version IS OLD.observed_time_derivation_version
    AND NEW.revokes_event_id IS OLD.revokes_event_id
    AND NEW.rule_version IS OLD.rule_version
    AND NEW.persona_artifact_id IS OLD.persona_artifact_id
    AND NEW.event_schema_version IS OLD.event_schema_version
    AND NEW.integrity_fingerprint IS OLD.integrity_fingerprint
    AND NEW.created_at IS OLD.created_at
)
BEGIN SELECT RAISE(ABORT, 'relationship events are append-only except guarded redaction'); END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_events_append_only_delete
BEFORE DELETE ON relationship_events
BEGIN SELECT RAISE(ABORT, 'relationship events cannot be deleted'); END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_authority_linear_insert
BEFORE INSERT ON relationship_authority_decisions
WHEN NOT (
    (
        NEW.generation = 1 AND NEW.predecessor_decision_id IS NULL
        AND NOT EXISTS (
            SELECT 1 FROM relationship_authority_decisions
            WHERE scope_id = NEW.scope_id
              AND source_memory_id = NEW.source_memory_id
              AND event_type = NEW.event_type
              AND subject_code = NEW.subject_code
        )
    ) OR (
        NEW.generation > 1 AND EXISTS (
            SELECT 1 FROM relationship_authority_decisions AS predecessor
            WHERE predecessor.id = NEW.predecessor_decision_id
              AND predecessor.scope_id = NEW.scope_id
              AND predecessor.source_memory_id = NEW.source_memory_id
              AND predecessor.event_type = NEW.event_type
              AND predecessor.subject_code = NEW.subject_code
              AND predecessor.generation = NEW.generation - 1
              AND NOT EXISTS (
                  SELECT 1 FROM relationship_authority_decisions AS later
                  WHERE later.scope_id = predecessor.scope_id
                    AND later.source_memory_id = predecessor.source_memory_id
                    AND later.event_type = predecessor.event_type
                    AND later.subject_code = predecessor.subject_code
                    AND later.generation > predecessor.generation
              )
        )
    )
)
BEGIN SELECT RAISE(ABORT, 'relationship authority generation invariant violation'); END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_authority_epoch_after_decision_insert
AFTER INSERT ON relationship_authority_decisions
BEGIN
    UPDATE relationship_authority_epoch
    SET generation = generation + 1, updated_at = NEW.created_at
    WHERE scope_id = NEW.scope_id;
    SELECT CASE WHEN changes() <> 1
        THEN RAISE(ABORT, 'relationship authority epoch missing scope') END;
END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_authority_append_only_update
BEFORE UPDATE ON relationship_authority_decisions
BEGIN SELECT RAISE(ABORT, 'relationship authority decisions are append-only'); END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_authority_append_only_delete
BEFORE DELETE ON relationship_authority_decisions
BEGIN SELECT RAISE(ABORT, 'relationship authority decisions cannot be deleted'); END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_authority_epoch_insert_guard
BEFORE INSERT ON relationship_authority_epoch
WHEN NEW.generation <> 0 OR EXISTS (
    SELECT 1 FROM relationship_authority_epoch WHERE scope_id = NEW.scope_id
)
BEGIN SELECT RAISE(ABORT, 'relationship authority epoch insert invariant violation'); END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_authority_epoch_update
BEFORE UPDATE ON relationship_authority_epoch
WHEN NEW.scope_id IS NOT OLD.scope_id OR NEW.generation <> OLD.generation + 1
BEGIN SELECT RAISE(ABORT, 'relationship authority epoch CAS invariant violation'); END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_authority_epoch_delete
BEFORE DELETE ON relationship_authority_epoch
BEGIN SELECT RAISE(ABORT, 'relationship authority epoch cannot be deleted'); END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_lineage_epoch_after_insert
AFTER INSERT ON relationship_memory_lineage
BEGIN
    UPDATE relationship_authority_epoch
    SET generation = generation + 1, updated_at = NEW.created_at
    WHERE scope_id = 'default';
    SELECT CASE WHEN changes() <> 1
        THEN RAISE(ABORT, 'relationship authority epoch missing scope') END;
END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_lineage_append_only_update
BEFORE UPDATE ON relationship_memory_lineage
BEGIN SELECT RAISE(ABORT, 'relationship lineage is append-only'); END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_lineage_append_only_delete
BEFORE DELETE ON relationship_memory_lineage
BEGIN SELECT RAISE(ABORT, 'relationship lineage cannot be deleted'); END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_jobs_frozen_snapshot_update
BEFORE UPDATE ON relationship_reconcile_jobs
WHEN
    NEW.id IS NOT OLD.id OR
    NEW.scope_id IS NOT OLD.scope_id OR
    NEW.source_memory_id IS NOT OLD.source_memory_id OR
    NEW.source_memory_version_id IS NOT OLD.source_memory_version_id OR
    NEW.captured_record_head_version IS NOT OLD.captured_record_head_version OR
    NEW.captured_record_generation IS NOT OLD.captured_record_generation OR
    NEW.captured_record_state IS NOT OLD.captured_record_state OR
    NEW.captured_event_type IS NOT OLD.captured_event_type OR
    NEW.captured_subject_code IS NOT OLD.captured_subject_code OR
    NEW.captured_authority_decision_id IS NOT OLD.captured_authority_decision_id OR
    NEW.captured_authority_generation IS NOT OLD.captured_authority_generation OR
    NEW.captured_authority_epoch IS NOT OLD.captured_authority_epoch OR
    NEW.captured_inherited_authority_fingerprint IS NOT OLD.captured_inherited_authority_fingerprint OR
    NEW.relationship_rule_version IS NOT OLD.relationship_rule_version OR
    NEW.persona_artifact_id IS NOT OLD.persona_artifact_id OR
    NEW.job_schema_version IS NOT OLD.job_schema_version OR
    NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT, 'relationship job snapshot is immutable'); END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_jobs_append_only_delete
BEFORE DELETE ON relationship_reconcile_jobs
BEGIN SELECT RAISE(ABORT, 'relationship jobs cannot be deleted'); END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_job_audits_append_only_update
BEFORE UPDATE ON relationship_job_audits
BEGIN SELECT RAISE(ABORT, 'relationship job audits are append-only'); END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_job_audits_append_only_delete
BEFORE DELETE ON relationship_job_audits
BEGIN SELECT RAISE(ABORT, 'relationship job audits cannot be deleted'); END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_audits_append_only_update
BEFORE UPDATE ON relationship_audits
BEGIN SELECT RAISE(ABORT, 'relationship audits are append-only'); END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_audits_append_only_delete
BEFORE DELETE ON relationship_audits
BEGIN SELECT RAISE(ABORT, 'relationship audits cannot be deleted'); END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_projections_immutable_update
BEFORE UPDATE ON relationship_projections
BEGIN SELECT RAISE(ABORT, 'relationship projections are immutable'); END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_projections_immutable_delete
BEFORE DELETE ON relationship_projections
BEGIN SELECT RAISE(ABORT, 'relationship projections cannot be deleted'); END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_projection_pointer_valid_insert
BEFORE INSERT ON relationship_projection_active_state
WHEN NEW.generation <> 0 OR NOT EXISTS (
    SELECT 1 FROM relationship_projections
    WHERE scope_id = NEW.scope_id AND projection_id = NEW.projection_id
      AND version = NEW.projection_version
)
BEGIN SELECT RAISE(ABORT, 'relationship projection pointer invariant violation'); END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_projection_pointer_cas_update
BEFORE UPDATE ON relationship_projection_active_state
WHEN
    NEW.scope_id IS NOT OLD.scope_id OR
    NEW.generation <> OLD.generation + 1 OR
    NEW.projection_version <= OLD.projection_version OR
    NEW.projection_id = OLD.projection_id OR
    NOT EXISTS (
        SELECT 1 FROM relationship_projections
        WHERE scope_id = NEW.scope_id AND projection_id = NEW.projection_id
          AND version = NEW.projection_version
    )
BEGIN SELECT RAISE(ABORT, 'relationship projection pointer CAS invariant violation'); END;

CREATE TRIGGER IF NOT EXISTS trg_relationship_projection_pointer_delete
BEFORE DELETE ON relationship_projection_active_state
BEGIN SELECT RAISE(ABORT, 'relationship projection pointer cannot be deleted'); END;
"""

_MEMORY_VERSION_TRIGGER_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_memory_versions_append_only_update
BEFORE UPDATE ON memory_versions
WHEN NOT (
    OLD.id = NEW.id AND
    OLD.memory_id = NEW.memory_id AND
    OLD.version_number = NEW.version_number AND
    OLD.parent_version_id IS NEW.parent_version_id AND
    OLD.operation = NEW.operation AND
    OLD.memory_type = NEW.memory_type AND
    OLD.content_hash = NEW.content_hash AND
    OLD.canonical_key_hash IS NEW.canonical_key_hash AND
    OLD.subject_key_hash IS NEW.subject_key_hash AND
    OLD.canonicalization_version = NEW.canonicalization_version AND
    OLD.confidence = NEW.confidence AND
    OLD.importance = NEW.importance AND
    OLD.source_kind = NEW.source_kind AND
    OLD.canonical_subject_code IS NEW.canonical_subject_code AND
    (
        OLD.source_session_id IS NEW.source_session_id OR
        (OLD.source_session_id IS NOT NULL AND NEW.source_session_id IS NULL)
    ) AND
    (
        OLD.source_session_reference_hash IS NEW.source_session_reference_hash OR
        (OLD.source_session_reference_hash IS NULL AND NEW.source_session_reference_hash IS NOT NULL)
    ) AND
    OLD.writer_policy_version = NEW.writer_policy_version AND
    OLD.created_at = NEW.created_at AND
    (
        (OLD.subject IS NEW.subject AND OLD.content IS NEW.content AND OLD.redacted_at IS NEW.redacted_at) OR
        (NEW.subject IS NULL AND NEW.content IS NULL AND OLD.redacted_at IS NULL AND NEW.redacted_at IS NOT NULL)
    )
)
BEGIN
    SELECT RAISE(ABORT, 'memory versions are append-only except redaction');
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
        raise ValueError("incomplete Gate C3 migration SQL")


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in connection.execute(f'PRAGMA table_info("{table}")')
    }


def _table_sql(connection: sqlite3.Connection, table: str) -> str | None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return None if row is None else str(row["sql"])


def _add_memory_subject_column(connection: sqlite3.Connection) -> None:
    if "canonical_subject_code" in _columns(connection, "memory_versions"):
        return
    connection.execute(
        "ALTER TABLE memory_versions ADD COLUMN canonical_subject_code TEXT "
        f"CHECK ({_SUBJECT_CODE_CHECK})"
    )


def _replace_memory_version_trigger(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' "
        "AND name='trg_memory_versions_append_only_update'"
    ).fetchone()
    if row is not None and "OLD.canonical_subject_code IS NEW.canonical_subject_code" in str(
        row["sql"]
    ):
        return
    connection.execute("DROP TRIGGER IF EXISTS trg_memory_versions_append_only_update")
    _execute_script(connection, _MEMORY_VERSION_TRIGGER_SQL)


def _scrub_experimental_projection_text(connection: sqlite3.Connection) -> None:
    columns = _columns(connection, "relationship_projections")
    experimental_columns = tuple(
        column
        for column in ("preferred_address", "preferred_address_text")
        if column in columns
    )
    if not experimental_columns or not any(
        connection.execute(
            f'SELECT 1 FROM relationship_projections WHERE "{column}" IS NOT NULL LIMIT 1'
        ).fetchone()
        is not None
        for column in experimental_columns
    ):
        return
    connection.execute("DROP TRIGGER IF EXISTS trg_relationship_projections_immutable_update")
    try:
        for column in experimental_columns:
            connection.execute(
                f'UPDATE relationship_projections SET "{column}"=NULL '
                f'WHERE "{column}" IS NOT NULL'
            )
            if connection.execute(
                f'SELECT 1 FROM relationship_projections WHERE "{column}" IS NOT NULL LIMIT 1'
            ).fetchone() is not None:
                raise RuntimeError("Gate C3 experimental projection scrub failed")
    finally:
        _execute_script(
            connection,
            """
CREATE TRIGGER IF NOT EXISTS trg_relationship_projections_immutable_update
BEFORE UPDATE ON relationship_projections
BEGIN SELECT RAISE(ABORT, 'relationship projections are immutable'); END;
""",
        )


def _postconditions(connection: sqlite3.Connection) -> None:
    tables = {
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if not _C3_TABLES <= tables:
        raise RuntimeError("Gate C3 schema validation failed")
    triggers = {
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        )
    }
    if not _REQUIRED_C3_TRIGGERS <= triggers:
        raise RuntimeError("Gate C3 trigger validation failed")
    if "canonical_subject_code" not in _columns(connection, "memory_versions"):
        raise RuntimeError("Gate C3 memory subject migration failed")
    memory_sql = _table_sql(connection, "memory_versions")
    if memory_sql is None or any(
        value not in memory_sql
        for value in (
            "preferred_address",
            "shared_experience",
            "non_external_commitment",
            "memory_type = 'relationship_event'",
            "memory_type IN ('preference', 'user_fact')",
        )
    ):
        raise RuntimeError("Gate C3 memory subject constraint validation failed")
    trigger = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' "
        "AND name='trg_memory_versions_append_only_update'"
    ).fetchone()
    if trigger is None or "OLD.canonical_subject_code IS NEW.canonical_subject_code" not in str(trigger["sql"]):
        raise RuntimeError("Gate C3 memory version trigger validation failed")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise RuntimeError("Gate C3 foreign key validation failed")


def migrate_gate_c3(
    connection: sqlite3.Connection,
    *,
    fault_injector: Callable[[str], None] | None = None,
) -> None:
    if not connection.in_transaction:
        raise RuntimeError("Gate C3 migration requires caller-owned transaction")
    _add_memory_subject_column(connection)
    _replace_memory_version_trigger(connection)
    _execute_script(connection, _C3_SCHEMA_SQL)
    if connection.execute(
        "SELECT 1 FROM relationship_authority_epoch WHERE scope_id='default'"
    ).fetchone() is None:
        connection.execute(
            "INSERT INTO relationship_authority_epoch "
            "(scope_id, generation, updated_at) "
            "VALUES ('default', 0, '1970-01-01T00:00:00+00:00')"
        )
    _scrub_experimental_projection_text(connection)
    if fault_injector is not None:
        fault_injector("post_schema")
    _postconditions(connection)
