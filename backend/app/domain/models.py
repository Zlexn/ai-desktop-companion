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
    summary_text: str
    source: SessionSummarySource
    covered_message_start_id: str | None
    covered_message_end_id: str | None
    message_count: int
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


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


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    PENDING = "pending"
    DISMISSED = "dismissed"


class MemoryAuditEventType(StrEnum):
    CONFLICT_DETECTED = "conflict_detected"


class MemoryAuditOperation(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    CONFIRM_CANDIDATE = "confirm_candidate"


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


@dataclass(frozen=True)
class MemoryAuditEvent:
    id: str
    event_type: MemoryAuditEventType
    memory_id: str
    related_memory_ids: list[str]
    operation: MemoryAuditOperation
    metadata: dict[str, Any]
    created_at: datetime
