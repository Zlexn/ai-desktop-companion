import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.repositories.relationship_migration import migrate_gate_c3
from app.repositories.summary_migration import migrate_gate_c2

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
    event_type TEXT NOT NULL CHECK (event_type IN (
        'conflict_detected', 'memory_deleted', 'conflict_resolved',
        'auto_change_undone'
    )),
    memory_id TEXT NOT NULL,
    related_memory_ids_json TEXT NOT NULL DEFAULT '[]',
    operation TEXT NOT NULL CHECK (operation IN (
        'create', 'update', 'confirm_candidate', 'forget',
        'resolve_conflict', 'undo_auto'
    )),
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

CREATE TABLE IF NOT EXISTS memory_extraction_consents (
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

CREATE TABLE IF NOT EXISTS memory_jobs (
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

CREATE TABLE IF NOT EXISTS memory_job_audits (
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

CREATE INDEX IF NOT EXISTS idx_memory_jobs_created_at
ON memory_jobs(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_job_audits_created_at
ON memory_job_audits(created_at DESC);
"""

_GATE_B_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memory_write_consents (
    scope_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('unknown', 'granted', 'declined', 'revoked')),
    purpose TEXT,
    policy_version TEXT,
    allowed_memory_types_version TEXT,
    allowed_memory_types_json TEXT NOT NULL DEFAULT '[]',
    retention_disclosure_version TEXT,
    generation INTEGER NOT NULL DEFAULT 0 CHECK (generation >= 0),
    granted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_versions (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    version_number INTEGER NOT NULL CHECK (version_number >= 1),
    parent_version_id TEXT UNIQUE,
    operation TEXT NOT NULL CHECK (operation IN (
        'bootstrap', 'create', 'user_edit', 'auto_supersede',
        'conflict_candidate', 'conflict_resolution', 'user_revert',
        'archive', 'delete'
    )),
    memory_type TEXT NOT NULL CHECK (memory_type IN (
        'user_fact', 'preference', 'long_term_goal', 'important_event',
        'relationship_event', 'other'
    )),
    subject TEXT,
    content TEXT,
    content_hash TEXT NOT NULL,
    canonical_key_hash TEXT,
    subject_key_hash TEXT,
    canonicalization_version TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    importance INTEGER NOT NULL CHECK (importance BETWEEN 1 AND 5),
    source_kind TEXT NOT NULL CHECK (source_kind IN (
        'legacy', 'manual', 'candidate', 'automatic', 'user_edit', 'user_revert'
    )),
    source_session_id TEXT,
    source_session_reference_hash TEXT,
    writer_policy_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    redacted_at TEXT,
    UNIQUE (memory_id, id),
    UNIQUE (memory_id, id, version_number),
    UNIQUE (memory_id, version_number),
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE RESTRICT,
    FOREIGN KEY (memory_id, parent_version_id)
        REFERENCES memory_versions(memory_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (source_session_id) REFERENCES sessions(id) ON DELETE SET NULL,
    CHECK ((operation = 'delete' AND subject IS NULL AND content IS NULL) OR operation <> 'delete'),
    CHECK (
        (version_number = 1 AND parent_version_id IS NULL) OR
        (version_number > 1 AND parent_version_id IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS memory_record_states (
    memory_id TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK (state IN ('active', 'archived', 'conflicted', 'deleted')),
    current_version_id TEXT,
    head_version INTEGER NOT NULL CHECK (head_version >= 0),
    record_generation INTEGER NOT NULL CHECK (record_generation >= 0),
    canonical_key_hash TEXT,
    subject_key_hash TEXT,
    canonicalization_version TEXT,
    source_kind TEXT NOT NULL CHECK (source_kind IN (
        'legacy', 'manual', 'candidate', 'automatic', 'user_edit', 'user_revert'
    )),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE RESTRICT,
    FOREIGN KEY (memory_id, current_version_id, head_version)
        REFERENCES memory_versions(memory_id, id, version_number) ON DELETE RESTRICT,
    CHECK (
        (head_version = 0 AND current_version_id IS NULL) OR
        (head_version > 0 AND current_version_id IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS memory_evidence (
    evidence_id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    memory_version_id TEXT NOT NULL,
    source_session_id TEXT,
    source_message_id TEXT,
    source_session_reference_hash TEXT NOT NULL,
    source_message_reference_hash TEXT NOT NULL,
    source_available INTEGER NOT NULL CHECK (source_available IN (0, 1)),
    source_deleted_at TEXT,
    relation TEXT NOT NULL CHECK (relation IN ('supports', 'contradicts', 'corrects')),
    observed_at TEXT NOT NULL,
    extractor_kind TEXT NOT NULL CHECK (extractor_kind IN ('local', 'fake', 'remote', 'manual', 'candidate')),
    extractor_provider TEXT,
    extractor_model TEXT,
    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    created_at TEXT NOT NULL,
    UNIQUE (memory_version_id, source_message_id, relation),
    FOREIGN KEY (memory_id, memory_version_id)
        REFERENCES memory_versions(memory_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (source_session_id) REFERENCES sessions(id) ON DELETE SET NULL,
    FOREIGN KEY (source_message_id) REFERENCES messages(id) ON DELETE SET NULL,
    CHECK (
        (source_available = 1 AND source_session_id IS NOT NULL AND source_message_id IS NOT NULL AND source_deleted_at IS NULL) OR
        (source_available = 0 AND source_session_id IS NULL AND source_message_id IS NULL AND source_deleted_at IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS memory_evidence_retractions (
    evidence_id TEXT PRIMARY KEY,
    reason_code TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (evidence_id) REFERENCES memory_evidence(evidence_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS memory_conflicts (
    conflict_id TEXT PRIMARY KEY,
    left_memory_id TEXT NOT NULL,
    right_memory_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'resolved')),
    resolution_kind TEXT CHECK (resolution_kind IS NULL OR resolution_kind IN (
        'choose_left', 'choose_right', 'replace_both', 'both_contextual',
        'dismiss_both', 'forget_left', 'forget_right', 'forget_both'
    )),
    resolved_memory_id TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    FOREIGN KEY (left_memory_id) REFERENCES memories(id) ON DELETE RESTRICT,
    FOREIGN KEY (right_memory_id) REFERENCES memories(id) ON DELETE RESTRICT,
    FOREIGN KEY (resolved_memory_id) REFERENCES memories(id) ON DELETE RESTRICT,
    CHECK (left_memory_id < right_memory_id),
    CHECK (
        (status = 'open' AND resolution_kind IS NULL AND resolved_memory_id IS NULL AND resolved_at IS NULL) OR
        (status = 'resolved' AND resolution_kind IS NOT NULL AND resolved_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_conflicts_open_pair
ON memory_conflicts(left_memory_id, right_memory_id) WHERE status = 'open';

CREATE TRIGGER IF NOT EXISTS trg_memory_conflicts_one_open_endpoint_insert
BEFORE INSERT ON memory_conflicts
WHEN NEW.status = 'open' AND EXISTS (
    SELECT 1 FROM memory_conflicts
    WHERE status = 'open' AND (
        left_memory_id IN (NEW.left_memory_id, NEW.right_memory_id) OR
        right_memory_id IN (NEW.left_memory_id, NEW.right_memory_id)
    )
)
BEGIN
    SELECT RAISE(ABORT, 'memory identity already has an open conflict');
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_conflicts_one_open_endpoint_update
BEFORE UPDATE OF status, left_memory_id, right_memory_id ON memory_conflicts
WHEN NEW.status = 'open' AND EXISTS (
    SELECT 1 FROM memory_conflicts
    WHERE conflict_id <> OLD.conflict_id AND status = 'open' AND (
        left_memory_id IN (NEW.left_memory_id, NEW.right_memory_id) OR
        right_memory_id IN (NEW.left_memory_id, NEW.right_memory_id)
    )
)
BEGIN
    SELECT RAISE(ABORT, 'memory identity already has an open conflict');
END;

CREATE TABLE IF NOT EXISTS memory_write_activities (
    op_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    proposal_index INTEGER NOT NULL CHECK (proposal_index >= 0),
    proposal_fingerprint TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    memory_id TEXT,
    previous_version_id TEXT,
    result_version_id TEXT,
    conflict_id TEXT,
    decision TEXT NOT NULL CHECK (decision IN ('create', 'support', 'supersede', 'conflict', 'reject', 'no_change')),
    outcome TEXT NOT NULL CHECK (outcome IN (
        'committed_create', 'committed_support', 'committed_supersede',
        'conflict_recorded', 'no_change', 'rejected_governor_policy',
        'duplicate_op',
        'skipped_no_write_consent', 'skipped_write_consent_changed',
        'skipped_no_consent', 'skipped_consent_changed',
        'skipped_deletion_barrier', 'skipped_tombstone',
        'blocked_open_conflict', 'ambiguous_exact_target',
        'ambiguous_conflict_target', 'unverified_user_claim',
        'skipped_turn_before_write_grant', 'skipped_mode_changed',
        'cancelled_session_deleted', 'stale_head', 'invalid_output',
        'provider_error', 'failed', 'cancelled'
    )),
    expected_head_version INTEGER CHECK (expected_head_version IS NULL OR expected_head_version >= 0),
    observed_record_generation INTEGER CHECK (observed_record_generation IS NULL OR observed_record_generation >= 0),
    write_consent_generation INTEGER NOT NULL CHECK (write_consent_generation >= 0),
    remote_consent_generation INTEGER CHECK (remote_consent_generation IS NULL OR remote_consent_generation >= 0),
    remote_authority_fingerprint TEXT,
    governor_version TEXT NOT NULL,
    commit_policy_version TEXT NOT NULL,
    canonicalization_version TEXT NOT NULL,
    extractor_kind TEXT NOT NULL CHECK (extractor_kind IN ('local', 'fake', 'remote', 'manual', 'candidate')),
    provider_identifier TEXT,
    model_identifier TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE (job_id, proposal_fingerprint, commit_policy_version),
    FOREIGN KEY (job_id) REFERENCES memory_jobs(id) ON DELETE RESTRICT,
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE RESTRICT,
    FOREIGN KEY (previous_version_id) REFERENCES memory_versions(id) ON DELETE RESTRICT,
    FOREIGN KEY (result_version_id) REFERENCES memory_versions(id) ON DELETE RESTRICT,
    FOREIGN KEY (conflict_id) REFERENCES memory_conflicts(conflict_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS memory_deletion_generations (
    scope TEXT NOT NULL CHECK (scope IN ('all', 'memory_type', 'session')),
    scope_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (scope, scope_id),
    CHECK ((scope = 'all' AND scope_id = '*') OR (scope <> 'all' AND scope_id <> '*'))
);

CREATE TABLE IF NOT EXISTS memory_tombstones (
    tombstone_id TEXT PRIMARY KEY,
    source_memory_id TEXT NOT NULL,
    memory_type TEXT NOT NULL CHECK (memory_type IN (
        'user_fact', 'preference', 'long_term_goal', 'important_event',
        'relationship_event', 'other'
    )),
    canonical_key_hash TEXT,
    subject_key_hash TEXT,
    content_key_hash TEXT,
    canonicalization_version TEXT NOT NULL,
    delete_generation INTEGER NOT NULL CHECK (delete_generation >= 0),
    reason_code TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    FOREIGN KEY (source_memory_id) REFERENCES memories(id) ON DELETE RESTRICT,
    CHECK (
        canonical_key_hash IS NOT NULL OR subject_key_hash IS NOT NULL OR
        content_key_hash IS NOT NULL
    ),
    UNIQUE (
        source_memory_id, memory_type, canonical_key_hash,
        subject_key_hash, canonicalization_version
    )
);

CREATE TABLE IF NOT EXISTS memory_summary_barrier (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    generation INTEGER NOT NULL CHECK (generation >= 0)
);

CREATE TABLE IF NOT EXISTS memory_summary_source_exclusions (
    source_message_id TEXT PRIMARY KEY,
    reason_code TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_versions_memory_version
ON memory_versions(memory_id, version_number DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_memory_evidence_memory_observed
ON memory_evidence(memory_id, observed_at DESC, evidence_id DESC);

CREATE INDEX IF NOT EXISTS idx_memory_conflicts_status_created
ON memory_conflicts(status, created_at DESC, conflict_id DESC);

CREATE INDEX IF NOT EXISTS idx_memory_write_activities_job_created
ON memory_write_activities(job_id, created_at);

CREATE INDEX IF NOT EXISTS idx_memory_write_activities_memory_created
ON memory_write_activities(memory_id, created_at DESC, op_id DESC)
WHERE memory_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_memory_tombstones_exact
ON memory_tombstones(memory_type, canonical_key_hash, canonicalization_version);

CREATE INDEX IF NOT EXISTS idx_memory_tombstones_subject
ON memory_tombstones(memory_type, subject_key_hash, canonicalization_version);

CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_tombstones_identity_exact
ON memory_tombstones(
    source_memory_id, memory_type, canonical_key_hash, canonicalization_version
)
WHERE canonical_key_hash IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_tombstones_identity_subject_only
ON memory_tombstones(
    source_memory_id, memory_type, subject_key_hash, canonicalization_version
)
WHERE canonical_key_hash IS NULL AND subject_key_hash IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_tombstones_identity_content_only
ON memory_tombstones(
    source_memory_id, memory_type, content_key_hash, canonicalization_version
)
WHERE canonical_key_hash IS NULL AND subject_key_hash IS NULL
  AND content_key_hash IS NOT NULL;

CREATE TRIGGER IF NOT EXISTS trg_memory_versions_contiguous_insert
BEFORE INSERT ON memory_versions
WHEN NEW.version_number > 1 AND NOT EXISTS (
    SELECT 1 FROM memory_versions AS parent
    WHERE parent.id = NEW.parent_version_id
      AND parent.memory_id = NEW.memory_id
      AND parent.version_number = NEW.version_number - 1
)
BEGIN
    SELECT RAISE(ABORT, 'memory version parent must be the previous version');
END;

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

CREATE TRIGGER IF NOT EXISTS trg_memory_versions_append_only_delete
BEFORE DELETE ON memory_versions
BEGIN
    SELECT RAISE(ABORT, 'memory versions cannot be deleted');
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_evidence_source_match_insert
BEFORE INSERT ON memory_evidence
WHEN NEW.source_available = 1 AND NOT EXISTS (
    SELECT 1 FROM messages
    WHERE id = NEW.source_message_id
      AND session_id = NEW.source_session_id
      AND role = 'user'
)
BEGIN
    SELECT RAISE(ABORT, 'memory Evidence source must be a user message in its session');
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_evidence_source_match_update
BEFORE UPDATE OF source_available, source_session_id, source_message_id ON memory_evidence
WHEN NEW.source_available = 1 AND NOT EXISTS (
    SELECT 1 FROM messages
    WHERE id = NEW.source_message_id
      AND session_id = NEW.source_session_id
      AND role = 'user'
)
BEGIN
    SELECT RAISE(ABORT, 'memory Evidence source must be a user message in its session');
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_jobs_frozen_snapshot_update
BEFORE UPDATE ON memory_jobs
WHEN
    OLD.turn_completed_at IS NOT NEW.turn_completed_at OR
    OLD.reserved_mode IS NOT NEW.reserved_mode OR
    OLD.workflow_version IS NOT NEW.workflow_version OR
    OLD.extractor_route IS NOT NEW.extractor_route OR
    OLD.governor_version IS NOT NEW.governor_version OR
    OLD.commit_policy_version IS NOT NEW.commit_policy_version OR
    OLD.canonicalization_version IS NOT NEW.canonicalization_version OR
    OLD.allowed_memory_types_version IS NOT NEW.allowed_memory_types_version OR
    OLD.write_consent_generation IS NOT NEW.write_consent_generation OR
    OLD.remote_consent_generation IS NOT NEW.remote_consent_generation OR
    OLD.remote_authority_fingerprint IS NOT NEW.remote_authority_fingerprint OR
    OLD.global_deletion_generation IS NOT NEW.global_deletion_generation OR
    OLD.session_deletion_generation IS NOT NEW.session_deletion_generation OR
    OLD.type_deletion_generations_json IS NOT NEW.type_deletion_generations_json OR
    OLD.persona_artifact_id IS NOT NEW.persona_artifact_id OR
    (
        OLD.source_session_reference_hash IS NOT NEW.source_session_reference_hash AND
        NOT (OLD.source_session_reference_hash IS NULL AND NEW.source_session_reference_hash IS NOT NULL)
    ) OR
    (
        OLD.source_user_message_reference_hash IS NOT NEW.source_user_message_reference_hash AND
        NOT (OLD.source_user_message_reference_hash IS NULL AND NEW.source_user_message_reference_hash IS NOT NULL)
    ) OR
    (
        OLD.source_assistant_message_reference_hash IS NOT NEW.source_assistant_message_reference_hash AND
        NOT (OLD.source_assistant_message_reference_hash IS NULL AND NEW.source_assistant_message_reference_hash IS NOT NULL)
    )
BEGIN
    SELECT RAISE(ABORT, 'memory job reservation snapshot is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_states_deleted_head_insert
BEFORE INSERT ON memory_record_states
WHEN NEW.state = 'deleted' AND NOT EXISTS (
    SELECT 1 FROM memory_versions
    WHERE id = NEW.current_version_id
      AND memory_id = NEW.memory_id
      AND version_number = NEW.head_version
      AND operation = 'delete'
)
BEGIN
    SELECT RAISE(ABORT, 'deleted state must point to a delete head');
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_states_deleted_head_update
BEFORE UPDATE OF state, current_version_id, head_version ON memory_record_states
WHEN NEW.state = 'deleted' AND NOT EXISTS (
    SELECT 1 FROM memory_versions
    WHERE id = NEW.current_version_id
      AND memory_id = NEW.memory_id
      AND version_number = NEW.head_version
      AND operation = 'delete'
)
BEGIN
    SELECT RAISE(ABORT, 'deleted state must point to a delete head');
END;
"""


_PERSONA_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS persona_artifacts (
    id TEXT PRIMARY KEY,
    version INTEGER NOT NULL UNIQUE CHECK (version > 0),
    payload_state TEXT NOT NULL CHECK (payload_state IN ('active', 'redacted')),
    schema_version TEXT NOT NULL,
    ruleset_version TEXT NOT NULL,
    template_version TEXT NOT NULL,
    compiler_version TEXT NOT NULL,
    source_content_json TEXT,
    rendered_system_prompt TEXT,
    content_identity_hash TEXT NOT NULL CHECK (length(content_identity_hash) = 64),
    behavior_fingerprint TEXT NOT NULL CHECK (length(behavior_fingerprint) = 64),
    created_at TEXT NOT NULL,
    redacted_at TEXT,
    redaction_reason_code TEXT,
    CHECK (
        (payload_state='active' AND source_content_json IS NOT NULL
         AND rendered_system_prompt IS NOT NULL AND redacted_at IS NULL
         AND redaction_reason_code IS NULL)
        OR
        (payload_state='redacted' AND source_content_json IS NULL
         AND rendered_system_prompt IS NULL AND redacted_at IS NOT NULL
         AND redaction_reason_code='user_privacy_redaction')
    )
);

CREATE INDEX IF NOT EXISTS idx_persona_artifacts_behavior
ON persona_artifacts(behavior_fingerprint, version DESC)
WHERE payload_state='active';

CREATE TABLE IF NOT EXISTS persona_active_state (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    artifact_id TEXT NOT NULL,
    activation_generation INTEGER NOT NULL CHECK (activation_generation >= 0),
    updated_at TEXT NOT NULL,
    FOREIGN KEY (artifact_id) REFERENCES persona_artifacts(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS persona_audits (
    id TEXT PRIMARY KEY,
    action TEXT NOT NULL CHECK (action IN (
        'bootstrap', 'created', 'no_change', 'activated',
        'activation_conflict', 'payload_redacted', 'integrity_rejected'
    )),
    artifact_id TEXT,
    artifact_version INTEGER,
    reason_code TEXT NOT NULL,
    actor_kind TEXT NOT NULL CHECK (actor_kind IN ('system', 'user')),
    created_at TEXT NOT NULL,
    FOREIGN KEY (artifact_id) REFERENCES persona_artifacts(id) ON DELETE RESTRICT,
    CHECK (artifact_version IS NULL OR artifact_version > 0)
);

CREATE INDEX IF NOT EXISTS idx_persona_audits_created
ON persona_audits(created_at DESC, id DESC);

CREATE TRIGGER IF NOT EXISTS trg_persona_artifacts_immutable_delete
BEFORE DELETE ON persona_artifacts
BEGIN SELECT RAISE(ABORT, 'persona artifact invariant violation'); END;

CREATE TRIGGER IF NOT EXISTS trg_persona_artifacts_immutable_update
BEFORE UPDATE ON persona_artifacts
WHEN NOT (
    OLD.payload_state = 'active'
    AND NEW.payload_state = 'redacted'
    AND NEW.source_content_json IS NULL
    AND NEW.rendered_system_prompt IS NULL
    AND NEW.redacted_at IS NOT NULL
    AND NEW.redaction_reason_code = 'user_privacy_redaction'
    AND NEW.id IS OLD.id
    AND NEW.version IS OLD.version
    AND NEW.schema_version IS OLD.schema_version
    AND NEW.ruleset_version IS OLD.ruleset_version
    AND NEW.template_version IS OLD.template_version
    AND NEW.compiler_version IS OLD.compiler_version
    AND NEW.content_identity_hash IS OLD.content_identity_hash
    AND NEW.behavior_fingerprint IS OLD.behavior_fingerprint
    AND NEW.created_at IS OLD.created_at
    AND NOT EXISTS (
        SELECT 1 FROM persona_active_state WHERE artifact_id = OLD.id
    )
    AND EXISTS (
        SELECT 1 FROM persona_artifacts
        WHERE id <> OLD.id AND payload_state = 'active'
    )
)
BEGIN
    SELECT RAISE(ABORT, 'persona artifact invariant violation');
END;

CREATE TRIGGER IF NOT EXISTS trg_persona_active_state_valid_insert
BEFORE INSERT ON persona_active_state
WHEN NEW.singleton_id <> 1 OR NEW.activation_generation <> 0 OR NOT EXISTS (
    SELECT 1 FROM persona_artifacts
    WHERE id=NEW.artifact_id AND payload_state='active'
)
BEGIN SELECT RAISE(ABORT, 'persona active state invariant violation'); END;

CREATE TRIGGER IF NOT EXISTS trg_persona_active_state_valid_update
BEFORE UPDATE ON persona_active_state
WHEN NEW.singleton_id IS NOT OLD.singleton_id
  OR NEW.activation_generation <> OLD.activation_generation + 1
  OR NEW.artifact_id = OLD.artifact_id
  OR NOT EXISTS (
      SELECT 1 FROM persona_artifacts
      WHERE id=NEW.artifact_id AND payload_state='active'
  )
BEGIN SELECT RAISE(ABORT, 'persona active state invariant violation'); END;

CREATE TRIGGER IF NOT EXISTS trg_persona_active_state_immutable_delete
BEFORE DELETE ON persona_active_state
BEGIN SELECT RAISE(ABORT, 'persona active state invariant violation'); END;
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


def _execute_script_in_current_transaction(
    connection: sqlite3.Connection,
    script: str,
) -> None:
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            sql = statement.strip()
            if sql:
                connection.execute(sql)
            statement = ""
    if statement.strip():
        raise ValueError("Incomplete SQLite schema statement")


def _table_sql(connection: sqlite3.Connection, table_name: str) -> str | None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return None if row is None else str(row["sql"])


def _trigger_sql(connection: sqlite3.Connection, trigger_name: str) -> str | None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?",
        (trigger_name,),
    ).fetchone()
    return None if row is None else str(row["sql"])


def _table_columns(
    connection: sqlite3.Connection,
    table_name: str,
) -> tuple[str, ...]:
    return tuple(
        str(row["name"])
        for row in connection.execute(f'PRAGMA table_info("{table_name}")')
    )


def _inbound_foreign_key_tables(
    connection: sqlite3.Connection,
    parent_table: str,
) -> set[str]:
    tables = {
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    inbound: set[str] = set()
    for table_name in tables:
        foreign_keys = connection.execute(
            f'PRAGMA foreign_key_list("{table_name}")'
        ).fetchall()
        if any(str(row["table"]) == parent_table for row in foreign_keys):
            inbound.add(table_name)
    return inbound


def _assert_expected_inbound_foreign_keys(
    connection: sqlite3.Connection,
    parent_table: str,
    expected_tables: set[str],
) -> None:
    actual_tables = _inbound_foreign_key_tables(connection, parent_table)
    unexpected = actual_tables - expected_tables
    if unexpected:
        names = ", ".join(sorted(unexpected))
        raise RuntimeError(
            f"unexpected inbound foreign keys for {parent_table}: {names}"
        )


def memory_source_references_exist(connection: sqlite3.Connection) -> bool:
    reference_columns = {
        "memory_versions": ("source_session_reference_hash",),
        "memory_evidence": (
            "source_session_reference_hash",
            "source_message_reference_hash",
        ),
        "memory_jobs": (
            "source_session_reference_hash",
            "source_user_message_reference_hash",
            "source_assistant_message_reference_hash",
        ),
    }
    for table_name, candidate_columns in reference_columns.items():
        existing_columns = set(_table_columns(connection, table_name))
        for column_name in candidate_columns:
            if column_name not in existing_columns:
                continue
            row = connection.execute(
                f'SELECT 1 FROM "{table_name}" '
                f'WHERE "{column_name}" IS NOT NULL LIMIT 1'
            ).fetchone()
            if row is not None:
                return True
    return False


def _memories_schema_needs_gate_b_migration(connection: sqlite3.Connection) -> bool:
    sql = _table_sql(connection, "memories")
    return sql is not None and "'automatic'" not in sql


def _memory_jobs_schema_needs_gate_b_migration(connection: sqlite3.Connection) -> bool:
    columns = set(_table_columns(connection, "memory_jobs"))
    return bool(columns) and "reserved_mode" not in columns


def _migrate_memories_gate_b_constraints(connection: sqlite3.Connection) -> None:
    if not _memories_schema_needs_gate_b_migration(connection):
        return
    _assert_expected_inbound_foreign_keys(
        connection,
        "memories",
        {"memory_embeddings"},
    )
    before_memories = connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    before_embeddings = connection.execute(
        "SELECT COUNT(*) FROM memory_embeddings"
    ).fetchone()[0]
    _execute_script_in_current_transaction(
        connection,
        """
        ALTER TABLE memory_embeddings RENAME TO memory_embeddings_gate_a;
        ALTER TABLE memories RENAME TO memories_gate_a;

        CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            memory_type TEXT NOT NULL CHECK (memory_type IN ('user_fact', 'preference', 'long_term_goal', 'important_event', 'relationship_event', 'other')),
            source TEXT NOT NULL CHECK (source IN ('manual', 'candidate', 'automatic')),
            source_session_id TEXT,
            importance INTEGER NOT NULL CHECK (importance >= 1 AND importance <= 5),
            confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
            status TEXT NOT NULL CHECK (status IN ('active', 'archived', 'pending', 'dismissed')),
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (source_session_id) REFERENCES sessions(id) ON DELETE SET NULL
        );

        INSERT INTO memories
        SELECT * FROM memories_gate_a;

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

        INSERT INTO memory_embeddings
        SELECT * FROM memory_embeddings_gate_a;

        DROP TABLE memory_embeddings_gate_a;
        DROP TABLE memories_gate_a;
        """,
    )
    if connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0] != before_memories:
        raise RuntimeError("memory migration row count mismatch")
    if (
        connection.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0]
        != before_embeddings
    ):
        raise RuntimeError("memory embedding migration row count mismatch")


def _migrate_memory_candidate_source_reference(
    connection: sqlite3.Connection,
) -> None:
    if "source_session_reference_hash" not in _table_columns(connection, "memories"):
        connection.execute(
            "ALTER TABLE memories ADD COLUMN source_session_reference_hash TEXT"
        )


def _memory_tombstones_need_content_migration(
    connection: sqlite3.Connection,
) -> bool:
    sql = _table_sql(connection, "memory_tombstones")
    return sql is not None and (
        "content_key_hash" not in set(_table_columns(connection, "memory_tombstones"))
        or "content_key_hash IS NOT NULL" not in sql
    )


def _migrate_memory_tombstone_content_hash(
    connection: sqlite3.Connection,
) -> None:
    if not _memory_tombstones_need_content_migration(connection):
        return
    before = connection.execute(
        "SELECT COUNT(*) FROM memory_tombstones"
    ).fetchone()[0]
    _execute_script_in_current_transaction(
        connection,
        """
        ALTER TABLE memory_tombstones RENAME TO memory_tombstones_pre_content;
        CREATE TABLE memory_tombstones (
            tombstone_id TEXT PRIMARY KEY,
            source_memory_id TEXT NOT NULL,
            memory_type TEXT NOT NULL CHECK (memory_type IN (
                'user_fact', 'preference', 'long_term_goal', 'important_event',
                'relationship_event', 'other'
            )),
            canonical_key_hash TEXT,
            subject_key_hash TEXT,
            content_key_hash TEXT,
            canonicalization_version TEXT NOT NULL,
            delete_generation INTEGER NOT NULL CHECK (delete_generation >= 0),
            reason_code TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            FOREIGN KEY (source_memory_id) REFERENCES memories(id) ON DELETE RESTRICT,
            CHECK (
                canonical_key_hash IS NOT NULL OR subject_key_hash IS NOT NULL OR
                content_key_hash IS NOT NULL
            ),
            UNIQUE (
                source_memory_id, memory_type, canonical_key_hash,
                subject_key_hash, canonicalization_version
            )
        );
        INSERT INTO memory_tombstones (
            tombstone_id, source_memory_id, memory_type, canonical_key_hash,
            subject_key_hash, content_key_hash, canonicalization_version,
            delete_generation, reason_code, created_at, expires_at
        )
        SELECT tombstone_id, source_memory_id, memory_type, canonical_key_hash,
               subject_key_hash, NULL, canonicalization_version,
               delete_generation, reason_code, created_at, expires_at
        FROM memory_tombstones_pre_content;
        DROP TABLE memory_tombstones_pre_content;
        """,
    )
    if connection.execute(
        "SELECT COUNT(*) FROM memory_tombstones"
    ).fetchone()[0] != before:
        raise RuntimeError("memory tombstone migration row count mismatch")
    _execute_script_in_current_transaction(
        connection,
        """
        CREATE INDEX IF NOT EXISTS idx_memory_tombstones_exact
        ON memory_tombstones(memory_type, canonical_key_hash, canonicalization_version);
        CREATE INDEX IF NOT EXISTS idx_memory_tombstones_subject
        ON memory_tombstones(memory_type, subject_key_hash, canonicalization_version);
        CREATE INDEX IF NOT EXISTS idx_memory_tombstones_content
        ON memory_tombstones(memory_type, content_key_hash, canonicalization_version);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_tombstones_identity_exact
        ON memory_tombstones(
            source_memory_id, memory_type, canonical_key_hash,
            canonicalization_version
        ) WHERE canonical_key_hash IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_tombstones_identity_subject_only
        ON memory_tombstones(
            source_memory_id, memory_type, subject_key_hash,
            canonicalization_version
        ) WHERE canonical_key_hash IS NULL AND subject_key_hash IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_tombstones_identity_content_only
        ON memory_tombstones(
            source_memory_id, memory_type, content_key_hash,
            canonicalization_version
        ) WHERE canonical_key_hash IS NULL AND subject_key_hash IS NULL
          AND content_key_hash IS NOT NULL;
        """,
    )


def _migrate_memory_audit_gate_b_constraints(connection: sqlite3.Connection) -> None:
    sql = _table_sql(connection, "memory_audit_events")
    if sql is None or "'conflict_resolved'" in sql:
        return
    before = connection.execute("SELECT COUNT(*) FROM memory_audit_events").fetchone()[0]
    _execute_script_in_current_transaction(
        connection,
        """
        ALTER TABLE memory_audit_events RENAME TO memory_audit_events_legacy;
        CREATE TABLE memory_audit_events (
            id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL CHECK (
                event_type IN (
                    'conflict_detected', 'memory_deleted',
                    'conflict_resolved', 'auto_change_undone'
                )
            ),
            memory_id TEXT NOT NULL,
            related_memory_ids_json TEXT NOT NULL DEFAULT '[]',
            operation TEXT NOT NULL CHECK (
                operation IN (
                    'create', 'update', 'confirm_candidate', 'forget',
                    'resolve_conflict', 'undo_auto'
                )
            ),
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        INSERT INTO memory_audit_events SELECT * FROM memory_audit_events_legacy;
        DROP TABLE memory_audit_events_legacy;
        """,
    )
    if connection.execute("SELECT COUNT(*) FROM memory_audit_events").fetchone()[0] != before:
        raise RuntimeError("memory audit migration row count mismatch")


def _migrate_memory_jobs_gate_b_constraints(connection: sqlite3.Connection) -> None:
    if not _memory_jobs_schema_needs_gate_b_migration(connection):
        return
    _assert_expected_inbound_foreign_keys(
        connection,
        "memory_jobs",
        {"memory_job_audits", "memory_write_activities"},
    )
    before_jobs = connection.execute("SELECT COUNT(*) FROM memory_jobs").fetchone()[0]
    before_audits = connection.execute(
        "SELECT COUNT(*) FROM memory_job_audits"
    ).fetchone()[0]
    _execute_script_in_current_transaction(
        connection,
        """
        ALTER TABLE memory_job_audits RENAME TO memory_job_audits_gate_a;
        ALTER TABLE memory_jobs RENAME TO memory_jobs_gate_a;

        CREATE TABLE memory_jobs (
            id TEXT PRIMARY KEY,
            turn_id TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            session_id TEXT,
            user_message_id TEXT,
            assistant_message_id TEXT,
            mode TEXT NOT NULL CHECK (mode IN ('shadow_auto', 'auto_active')),
            extractor_route TEXT NOT NULL CHECK (extractor_route IN ('none', 'local', 'fake', 'remote')),
            status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            outcome TEXT CHECK (outcome IS NULL OR outcome IN (
                'shadow_recorded', 'completed_with_decisions',
                'skipped_no_extractor', 'skipped_no_write_consent',
                'skipped_write_consent_changed', 'skipped_turn_before_write_grant',
                'skipped_mode_changed', 'skipped_no_consent',
                'skipped_consent_changed', 'skipped_governor_policy',
                'invalid_output', 'provider_error', 'cancelled_session_deleted',
                'cancelled', 'failed'
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
            turn_completed_at TEXT,
            reserved_mode TEXT CHECK (reserved_mode IS NULL OR reserved_mode IN ('shadow_auto', 'auto_active')),
            workflow_version TEXT,
            commit_policy_version TEXT,
            canonicalization_version TEXT,
            allowed_memory_types_version TEXT,
            write_consent_generation INTEGER CHECK (write_consent_generation IS NULL OR write_consent_generation >= 0),
            remote_consent_generation INTEGER CHECK (remote_consent_generation IS NULL OR remote_consent_generation >= 0),
            remote_authority_fingerprint TEXT,
            global_deletion_generation INTEGER CHECK (global_deletion_generation IS NULL OR global_deletion_generation >= 0),
            session_deletion_generation INTEGER CHECK (session_deletion_generation IS NULL OR session_deletion_generation >= 0),
            type_deletion_generations_json TEXT,
            source_session_reference_hash TEXT,
            source_user_message_reference_hash TEXT,
            source_assistant_message_reference_hash TEXT,
            UNIQUE (turn_id, schema_version),
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL,
            FOREIGN KEY (user_message_id) REFERENCES messages(id) ON DELETE SET NULL,
            FOREIGN KEY (assistant_message_id) REFERENCES messages(id) ON DELETE SET NULL,
            CHECK (
                mode <> 'auto_active' OR (
                    turn_completed_at IS NOT NULL AND
                    reserved_mode = 'auto_active' AND
                    workflow_version IS NOT NULL AND
                    commit_policy_version IS NOT NULL AND
                    canonicalization_version IS NOT NULL AND
                    allowed_memory_types_version IS NOT NULL AND
                    write_consent_generation IS NOT NULL AND
                    global_deletion_generation IS NOT NULL AND
                    session_deletion_generation IS NOT NULL AND
                    type_deletion_generations_json IS NOT NULL AND
                    source_session_reference_hash IS NOT NULL AND
                    source_user_message_reference_hash IS NOT NULL AND
                    source_assistant_message_reference_hash IS NOT NULL AND
                    (
                        extractor_route <> 'remote' OR (
                            remote_consent_generation IS NOT NULL AND
                            remote_authority_fingerprint IS NOT NULL
                        )
                    )
                )
            )
        );

        INSERT INTO memory_jobs (
            id, turn_id, schema_version, session_id, user_message_id,
            assistant_message_id, mode, extractor_route, status, attempt_count,
            outcome, error_category, governor_version, consent_generation,
            created_at, started_at, finished_at
        )
        SELECT
            id, turn_id, schema_version, session_id, user_message_id,
            assistant_message_id, mode, extractor_route, status, attempt_count,
            outcome, error_category, governor_version, consent_generation,
            created_at, started_at, finished_at
        FROM memory_jobs_gate_a;

        CREATE TABLE memory_job_audits (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            outcome TEXT NOT NULL CHECK (outcome IN (
                'shadow_recorded', 'completed_with_decisions',
                'skipped_no_extractor', 'skipped_no_write_consent',
                'skipped_write_consent_changed', 'skipped_turn_before_write_grant',
                'skipped_mode_changed', 'skipped_no_consent',
                'skipped_consent_changed', 'skipped_governor_policy',
                'invalid_output', 'provider_error', 'cancelled_session_deleted',
                'cancelled', 'failed'
            )),
            decision_counts_json TEXT NOT NULL,
            reason_counts_json TEXT NOT NULL,
            outcome_counts_json TEXT NOT NULL DEFAULT '{}',
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
            FOREIGN KEY (job_id) REFERENCES memory_jobs(id) ON DELETE RESTRICT,
            UNIQUE (job_id)
        );

        INSERT INTO memory_job_audits (
            id, job_id, outcome, decision_counts_json, reason_counts_json,
            proposal_count, accepted_count, rejected_count, redaction_count,
            provider, model, elapsed_ms, schema_version, governor_version,
            consent_generation, created_at
        )
        SELECT
            id, job_id, outcome, decision_counts_json, reason_counts_json,
            proposal_count, accepted_count, rejected_count, redaction_count,
            provider, model, elapsed_ms, schema_version, governor_version,
            consent_generation, created_at
        FROM memory_job_audits_gate_a;

        DROP TABLE memory_job_audits_gate_a;
        DROP TABLE memory_jobs_gate_a;
        """,
    )
    if connection.execute("SELECT COUNT(*) FROM memory_jobs").fetchone()[0] != before_jobs:
        raise RuntimeError("memory job migration row count mismatch")
    if (
        connection.execute("SELECT COUNT(*) FROM memory_job_audits").fetchone()[0]
        != before_audits
    ):
        raise RuntimeError("memory job audit migration row count mismatch")


def _create_gate_b_schema(connection: sqlite3.Connection) -> None:
    if "observed_memory_summary_barrier" not in set(
        _table_columns(connection, "session_summaries")
    ):
        connection.execute(
            "ALTER TABLE session_summaries ADD COLUMN "
            "observed_memory_summary_barrier INTEGER NOT NULL DEFAULT 0 "
            "CHECK (observed_memory_summary_barrier >= 0)"
        )
    version_trigger = _trigger_sql(
        connection,
        "trg_memory_versions_append_only_update",
    )
    if (
        version_trigger is not None
        and "OLD.source_session_reference_hash IS NULL" not in version_trigger
    ):
        connection.execute(
            "DROP TRIGGER IF EXISTS trg_memory_versions_append_only_update"
        )
    job_trigger = _trigger_sql(
        connection,
        "trg_memory_jobs_frozen_snapshot_update",
    )
    if (
        job_trigger is not None
        and "OLD.source_user_message_reference_hash IS NULL" not in job_trigger
    ):
        connection.execute(
            "DROP TRIGGER IF EXISTS trg_memory_jobs_frozen_snapshot_update"
        )
    _execute_script_in_current_transaction(connection, _GATE_B_SCHEMA_SQL)
    if connection.execute(
        "SELECT 1 FROM memory_summary_barrier WHERE singleton_id = 1"
    ).fetchone() is None:
        connection.execute(
            "INSERT INTO memory_summary_barrier (singleton_id, generation) VALUES (1, 0)"
        )


def _create_persona_schema(connection: sqlite3.Connection) -> None:
    if "persona_artifact_id" not in _table_columns(connection, "memory_jobs"):
        connection.execute(
            "ALTER TABLE memory_jobs ADD COLUMN persona_artifact_id TEXT"
        )
    frozen_trigger = _trigger_sql(
        connection,
        "trg_memory_jobs_frozen_snapshot_update",
    )
    if (
        frozen_trigger is not None
        and "OLD.persona_artifact_id IS NOT NEW.persona_artifact_id"
        not in frozen_trigger
    ):
        connection.execute(
            "DROP TRIGGER IF EXISTS trg_memory_jobs_frozen_snapshot_update"
        )
    _execute_script_in_current_transaction(connection, _PERSONA_SCHEMA_SQL)
    _execute_script_in_current_transaction(
        connection,
        """
        CREATE TRIGGER IF NOT EXISTS trg_memory_jobs_persona_insert
        BEFORE INSERT ON memory_jobs
        WHEN NEW.persona_artifact_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM persona_artifacts WHERE id=NEW.persona_artifact_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'memory job persona artifact invariant violation');
        END;
        """,
    )
    _execute_script_in_current_transaction(connection, _GATE_B_SCHEMA_SQL)


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
    connection.execute("PRAGMA foreign_keys = ON")
    foreign_keys_enabled = connection.execute("PRAGMA foreign_keys").fetchone()
    if foreign_keys_enabled is None or foreign_keys_enabled[0] != 1:
        raise RuntimeError("SQLite foreign key enforcement could not be enabled")

    try:
        connection.execute("BEGIN")
        _execute_script_in_current_transaction(connection, SCHEMA_SQL)
        _migrate_emotion_analysis_consent_policy(connection)
        _migrate_emotion_analysis_job_version(connection)
        _migrate_memories_gate_b_constraints(connection)
        _migrate_memory_candidate_source_reference(connection)
        _migrate_memory_audit_gate_b_constraints(connection)
        _migrate_memory_jobs_gate_b_constraints(connection)
        _create_gate_b_schema(connection)
        _migrate_memory_tombstone_content_hash(connection)
        _create_persona_schema(connection)
        migrate_gate_c2(connection)
        migrate_gate_c3(connection)
        _execute_script_in_current_transaction(
            connection,
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

            CREATE INDEX IF NOT EXISTS idx_memory_jobs_created_at
            ON memory_jobs(created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_memory_job_audits_created_at
            ON memory_job_audits(created_at DESC);
            """,
        )
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise RuntimeError("SQLite foreign key validation failed after migration")
    except Exception:
        connection.rollback()
        raise
    else:
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
