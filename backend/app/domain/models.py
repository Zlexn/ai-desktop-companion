from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import math
from typing import Any


class ChatRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class Session:
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class SessionSummarySource(StrEnum):
    MANUAL = "manual"
    GENERATED = "generated"


@dataclass(frozen=True)
class SessionSummary:
    id: str
    session_id: str
    summary_text: str | None
    source: SessionSummarySource
    covered_message_start_id: str | None
    covered_message_end_id: str | None
    message_count: int
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    observed_memory_summary_barrier: int = 0
    stale: bool = False


@dataclass(frozen=True)
class Message:
    id: str
    session_id: str
    role: ChatRole
    content: str
    created_at: datetime
    metadata: dict[str, Any]


class MemoryType(StrEnum):
    USER_FACT = "user_fact"
    PREFERENCE = "preference"
    LONG_TERM_GOAL = "long_term_goal"
    IMPORTANT_EVENT = "important_event"
    RELATIONSHIP_EVENT = "relationship_event"
    OTHER = "other"


class MemorySource(StrEnum):
    MANUAL = "manual"
    CANDIDATE = "candidate"
    AUTOMATIC = "automatic"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    PENDING = "pending"
    DISMISSED = "dismissed"


class MemoryAuditEventType(StrEnum):
    CONFLICT_DETECTED = "conflict_detected"
    MEMORY_DELETED = "memory_deleted"
    CONFLICT_RESOLVED = "conflict_resolved"
    AUTO_CHANGE_UNDONE = "auto_change_undone"


class MemoryAuditOperation(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    CONFIRM_CANDIDATE = "confirm_candidate"
    FORGET = "forget"
    RESOLVE_CONFLICT = "resolve_conflict"
    UNDO_AUTO = "undo_auto"


class MemoryAutomationMode(StrEnum):
    OFF = "off"
    CANDIDATE_CONFIRMATION = "candidate_confirmation"
    SHADOW_AUTO = "shadow_auto"
    AUTO_ACTIVE = "auto_active"


class MemoryExtractorRoute(StrEnum):
    NONE = "none"
    LOCAL = "local"
    FAKE = "fake"
    REMOTE = "remote"


class MemoryExtractionConsentStatus(StrEnum):
    UNKNOWN = "unknown"
    GRANTED = "granted"
    DECLINED = "declined"
    REVOKED = "revoked"


class MemoryJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MemoryGovernorDecision(StrEnum):
    CREATE = "create"
    SUPPORT = "support"
    SUPERSEDE = "supersede"
    CONFLICT = "conflict"
    REJECT = "reject"
    NO_CHANGE = "no_change"


class MemoryJobAuditOutcome(StrEnum):
    SHADOW_RECORDED = "shadow_recorded"
    COMPLETED_WITH_DECISIONS = "completed_with_decisions"
    SKIPPED_NO_EXTRACTOR = "skipped_no_extractor"
    SKIPPED_NO_WRITE_CONSENT = "skipped_no_write_consent"
    SKIPPED_WRITE_CONSENT_CHANGED = "skipped_write_consent_changed"
    SKIPPED_TURN_BEFORE_WRITE_GRANT = "skipped_turn_before_write_grant"
    SKIPPED_MODE_CHANGED = "skipped_mode_changed"
    SKIPPED_NO_CONSENT = "skipped_no_consent"
    SKIPPED_CONSENT_CHANGED = "skipped_consent_changed"
    SKIPPED_GOVERNOR_POLICY = "skipped_governor_policy"
    INVALID_OUTPUT = "invalid_output"
    PROVIDER_ERROR = "provider_error"
    CANCELLED_SESSION_DELETED = "cancelled_session_deleted"
    CANCELLED = "cancelled"
    FAILED = "failed"


class MemoryWriteConsentStatus(StrEnum):
    UNKNOWN = "unknown"
    GRANTED = "granted"
    DECLINED = "declined"
    REVOKED = "revoked"


class MemoryRecordState(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    CONFLICTED = "conflicted"
    DELETED = "deleted"


class MemoryVersionSourceKind(StrEnum):
    LEGACY = "legacy"
    MANUAL = "manual"
    CANDIDATE = "candidate"
    AUTOMATIC = "automatic"
    USER_EDIT = "user_edit"
    USER_REVERT = "user_revert"


class MemoryEvidenceExtractorKind(StrEnum):
    LOCAL = "local"
    FAKE = "fake"
    REMOTE = "remote"
    MANUAL = "manual"
    CANDIDATE = "candidate"


class MemoryVersionOperation(StrEnum):
    BOOTSTRAP = "bootstrap"
    CREATE = "create"
    USER_EDIT = "user_edit"
    AUTO_SUPERSEDE = "auto_supersede"
    CONFLICT_CANDIDATE = "conflict_candidate"
    CONFLICT_RESOLUTION = "conflict_resolution"
    USER_REVERT = "user_revert"
    ARCHIVE = "archive"
    DELETE = "delete"


class MemoryEvidenceRelation(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CORRECTS = "corrects"


class MemoryConflictStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class MemoryConflictResolutionKind(StrEnum):
    CHOOSE_LEFT = "choose_left"
    CHOOSE_RIGHT = "choose_right"
    REPLACE_BOTH = "replace_both"
    BOTH_CONTEXTUAL = "both_contextual"
    DISMISS_BOTH = "dismiss_both"
    FORGET_LEFT = "forget_left"
    FORGET_RIGHT = "forget_right"
    FORGET_BOTH = "forget_both"


class MemoryDeletionScope(StrEnum):
    MEMORY = "memory"
    SESSION = "session"
    MEMORY_TYPE = "memory_type"
    ALL = "all"


class MemoryWriteActivityOutcome(StrEnum):
    COMMITTED_CREATE = "committed_create"
    COMMITTED_SUPPORT = "committed_support"
    COMMITTED_SUPERSEDE = "committed_supersede"
    CONFLICT_RECORDED = "conflict_recorded"
    NO_CHANGE = "no_change"
    REJECTED_GOVERNOR_POLICY = "rejected_governor_policy"
    DUPLICATE_OP = "duplicate_op"
    SKIPPED_NO_WRITE_CONSENT = "skipped_no_write_consent"
    SKIPPED_WRITE_CONSENT_CHANGED = "skipped_write_consent_changed"
    SKIPPED_NO_CONSENT = "skipped_no_consent"
    SKIPPED_CONSENT_CHANGED = "skipped_consent_changed"
    SKIPPED_DELETION_BARRIER = "skipped_deletion_barrier"
    SKIPPED_TOMBSTONE = "skipped_tombstone"
    BLOCKED_OPEN_CONFLICT = "blocked_open_conflict"
    AMBIGUOUS_EXACT_TARGET = "ambiguous_exact_target"
    AMBIGUOUS_CONFLICT_TARGET = "ambiguous_conflict_target"
    UNVERIFIED_USER_CLAIM = "unverified_user_claim"
    SKIPPED_TURN_BEFORE_WRITE_GRANT = "skipped_turn_before_write_grant"
    SKIPPED_MODE_CHANGED = "skipped_mode_changed"
    CANCELLED_SESSION_DELETED = "cancelled_session_deleted"
    STALE_HEAD = "stale_head"
    INVALID_OUTPUT = "invalid_output"
    PROVIDER_ERROR = "provider_error"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class MemoryWriteConsent:
    scope_id: str
    status: MemoryWriteConsentStatus
    purpose: str | None
    policy_version: str | None
    allowed_memory_types_version: str | None
    allowed_memory_types: tuple[MemoryType, ...]
    retention_disclosure_version: str | None
    generation: int
    granted_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class MemoryRecordStateRecord:
    memory_id: str
    state: MemoryRecordState
    current_version_id: str | None
    head_version: int
    record_generation: int
    canonical_key_hash: str | None
    subject_key_hash: str | None
    canonicalization_version: str | None
    source_kind: MemoryVersionSourceKind
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class MemoryVersion:
    id: str
    memory_id: str
    version_number: int
    parent_version_id: str | None
    operation: MemoryVersionOperation
    memory_type: MemoryType
    subject: str | None
    content: str | None
    content_hash: str
    canonical_key_hash: str | None
    subject_key_hash: str | None
    canonicalization_version: str
    confidence: float
    importance: int
    source_kind: MemoryVersionSourceKind
    source_session_id: str | None
    source_session_reference_hash: str | None
    writer_policy_version: str
    created_at: datetime
    redacted_at: datetime | None
    canonical_subject_code: str | None = None


@dataclass(frozen=True)
class MemoryEvidence:
    id: str
    memory_id: str
    memory_version_id: str
    source_session_id: str | None
    source_message_id: str | None
    source_session_reference_hash: str
    source_message_reference_hash: str
    source_available: bool
    source_deleted_at: datetime | None
    relation: MemoryEvidenceRelation
    observed_at: datetime
    extractor_kind: MemoryEvidenceExtractorKind
    extractor_provider: str | None
    extractor_model: str | None
    confidence: float
    created_at: datetime


@dataclass(frozen=True)
class MemoryConflict:
    id: str
    left_memory_id: str
    right_memory_id: str
    status: MemoryConflictStatus
    resolution_kind: MemoryConflictResolutionKind | None
    resolved_memory_id: str | None
    created_at: datetime
    resolved_at: datetime | None


@dataclass(frozen=True)
class MemoryWriteActivity:
    op_id: str
    job_id: str
    proposal_index: int
    proposal_fingerprint: str
    turn_id: str
    memory_id: str | None
    previous_version_id: str | None
    result_version_id: str | None
    conflict_id: str | None
    decision: MemoryGovernorDecision
    outcome: MemoryWriteActivityOutcome
    expected_head_version: int | None
    observed_record_generation: int | None
    write_consent_generation: int
    remote_consent_generation: int | None
    remote_authority_fingerprint: str | None
    governor_version: str
    commit_policy_version: str
    canonicalization_version: str
    extractor_kind: MemoryEvidenceExtractorKind
    provider_identifier: str | None
    model_identifier: str | None
    created_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True)
class MemoryAutoActiveJobSnapshot:
    reserved_mode: MemoryAutomationMode
    workflow_version: str
    extractor_route: MemoryExtractorRoute
    governor_version: str
    commit_policy_version: str
    canonicalization_version: str
    allowed_memory_types_version: str
    write_consent_generation: int
    remote_consent_generation: int | None
    remote_authority_fingerprint: str | None
    global_deletion_generation: int
    session_deletion_generation: int
    type_deletion_generations: dict[str, int]
    source_session_reference_hash: str
    source_user_message_reference_hash: str
    source_assistant_message_reference_hash: str
    turn_completed_at: datetime


@dataclass(frozen=True)
class MemoryExtractionConsent:
    scope_id: str
    status: MemoryExtractionConsentStatus
    purpose: str | None
    provider: str | None
    disclosure_version: str | None
    disclosed_fields: tuple[str, ...]
    generation: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class MemoryJob:
    id: str
    turn_id: str
    schema_version: str
    session_id: str | None
    user_message_id: str | None
    assistant_message_id: str | None
    mode: MemoryAutomationMode
    extractor_route: MemoryExtractorRoute
    status: MemoryJobStatus
    attempt_count: int
    outcome: MemoryJobAuditOutcome | None
    error_category: str | None
    governor_version: str
    consent_generation: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    auto_active_snapshot: MemoryAutoActiveJobSnapshot | None = None
    persona_artifact_id: str | None = None


@dataclass(frozen=True)
class MemoryJobAudit:
    id: str
    job_id: str
    outcome: MemoryJobAuditOutcome
    decision_counts: dict[str, int]
    reason_counts: dict[str, int]
    outcome_counts: dict[str, int]
    proposal_count: int
    accepted_count: int
    rejected_count: int
    redaction_count: int
    provider: str | None
    model: str | None
    elapsed_ms: int | None
    schema_version: str
    governor_version: str
    consent_generation: int | None
    created_at: datetime


@dataclass(frozen=True)
class MemoryGovernorProposal:
    memory_type: MemoryType
    subject: str
    content: str
    canonical_key_hint: str | None
    confidence: float
    source_message_ids: tuple[str, ...]


@dataclass(frozen=True)
class MemoryGovernorResult:
    decision: MemoryGovernorDecision
    reason_code: str
    canonical_key: str | None
    confidence: float
    redaction_count: int


DEFAULT_EMOTION_SCOPE_ID = "default-companion"


class EmotionEventType(StrEnum):
    TRANSITION = "transition"
    DECAY = "decay"
    SETTINGS = "settings"
    RESET = "reset"


@dataclass(frozen=True)
class EmotionVector:
    mood: float
    trust: float
    concern: float
    distance: float
    irritation: float
    formality: float

    @classmethod
    def zero(cls) -> "EmotionVector":
        return cls(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    def values(self) -> tuple[float, ...]:
        return (
            self.mood,
            self.trust,
            self.concern,
            self.distance,
            self.irritation,
            self.formality,
        )


EMOTION_BASELINE = EmotionVector(0.50, 0.40, 0.20, 0.55, 0.10, 0.60)
EMOTION_MAX_DELTA = EmotionVector(0.08, 0.04, 0.10, 0.05, 0.08, 0.06)
EMOTION_BUCKET_LOW_MAX = 0.34
EMOTION_BUCKET_HIGH_MIN = 0.67
EXPRESSION_PLAN_SCHEMA_VERSION = 1
EXPRESSION_PLAN_MIN_RATE = 0.90
EXPRESSION_PLAN_MAX_RATE = 1.10


def _validate_expression_rate(rate: float) -> None:
    if not math.isfinite(rate) or not EXPRESSION_PLAN_MIN_RATE <= rate <= EXPRESSION_PLAN_MAX_RATE:
        raise ValueError("expression rate is out of bounds")


class ExpressionDelivery(StrEnum):
    NEUTRAL = "neutral"
    WARM = "warm"
    REASSURING = "reassuring"
    RESERVED = "reserved"
    FIRM = "firm"


class ExpressionIntensity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"


@dataclass(frozen=True)
class ExpressionPlanDraft:
    source_emotion_version: int
    delivery: ExpressionDelivery
    rate: float
    intensity: ExpressionIntensity

    def __post_init__(self) -> None:
        if type(self.source_emotion_version) is not int or self.source_emotion_version < 0:
            raise ValueError("source emotion version must be a non-negative integer")
        _validate_expression_rate(self.rate)


@dataclass(frozen=True)
class ResolvedExpression:
    delivery: ExpressionDelivery
    rate: float
    intensity: ExpressionIntensity

    def __post_init__(self) -> None:
        _validate_expression_rate(self.rate)


class ExpressionPlanSource(StrEnum):
    PERSISTED_PLAN = "persisted_plan"
    DEFAULT = "default"


@dataclass(frozen=True)
class ExpressionPlanLookup:
    assistant_message_id: str
    schema_version: int
    expression: ResolvedExpression
    source: ExpressionPlanSource

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version < 1:
            raise ValueError("expression lookup schema version must be positive")


@dataclass(frozen=True)
class ExpressionPlan:
    id: str
    assistant_message_id: str
    schema_version: int
    source_emotion_version: int
    delivery: ExpressionDelivery
    rate: float
    intensity: ExpressionIntensity
    created_at: datetime

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version < 1:
            raise ValueError("expression plan schema version must be a positive integer")
        if type(self.source_emotion_version) is not int or self.source_emotion_version < 0:
            raise ValueError("source emotion version must be a non-negative integer")
        _validate_expression_rate(self.rate)


class EmotionAnalysisConsentStatus(StrEnum):
    UNKNOWN = "unknown"
    GRANTED = "granted"
    DECLINED = "declined"
    REVOKED = "revoked"


class EmotionAnalysisJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class EmotionAnalysisAuditOutcome(StrEnum):
    APPLIED = "applied"
    NO_CHANGE = "no_change"
    SKIPPED = "skipped"
    INVALID_OUTPUT = "invalid_output"
    PROVIDER_ERROR = "provider_error"
    REVOKED = "revoked"
    FAILED = "failed"


@dataclass(frozen=True)
class EmotionAnalysisConsent:
    scope_id: str
    status: EmotionAnalysisConsentStatus
    disclosure_version: str | None
    provider: str | None
    policy_fingerprint: str | None
    generation: int
    updated_at: datetime


@dataclass(frozen=True)
class EmotionAnalysisJob:
    id: str
    scope_id: str
    source_session_id: str
    source_user_message_id: str
    source_assistant_message_id: str
    schema_version: str
    base_emotion_version: int
    consent_generation: int
    status: EmotionAnalysisJobStatus
    outcome_reason: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class EmotionAnalysisAudit:
    id: str
    job_id: str
    scope_id: str
    outcome: EmotionAnalysisAuditOutcome
    source_session_id: str
    source_user_message_id: str
    source_assistant_message_id: str
    schema_version: str
    provider: str
    model: str
    message_count: int
    memory_count: int
    input_characters: int
    redaction_count: int
    elapsed_ms: int
    reason_code: str
    created_at: datetime


@dataclass(frozen=True)
class EmotionState:
    scope_id: str
    enabled: bool
    vector: EmotionVector
    version: int
    updated_at: datetime


@dataclass(frozen=True)
class EmotionEvent:
    id: str
    scope_id: str
    event_type: EmotionEventType
    before: EmotionVector
    after: EmotionVector
    applied_delta: EmotionVector
    reason_codes: tuple[str, ...]
    source_session_id: str | None
    source_user_message_id: str | None
    source_assistant_message_id: str | None
    engine: str
    rule_version: str
    created_at: datetime


@dataclass(frozen=True)
class Memory:
    id: str
    content: str
    memory_type: MemoryType
    source: MemorySource
    source_session_id: str | None
    importance: int
    confidence: float
    status: MemoryStatus
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any]
    v2_state: MemoryRecordState | None = None
    v2_source_kind: MemoryVersionSourceKind | None = None
    version_count: int = 0
    evidence_count: int = 0
    has_open_conflict: bool = False
    can_undo_latest_auto: bool = False
    canonical_subject_code: str | None = None


@dataclass(frozen=True)
class MemoryAuditEvent:
    id: str
    event_type: MemoryAuditEventType
    memory_id: str
    related_memory_ids: list[str]
    operation: MemoryAuditOperation
    metadata: dict[str, Any]
    created_at: datetime
