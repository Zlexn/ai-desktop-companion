from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, Mapping

from app.domain.models import MemoryRecordState, MemoryType, MemoryVersionSourceKind


RelationshipSubjectCode = Literal[
    "preferred_address",
    "shared_experience",
    "non_external_commitment",
]
FamiliarityBucket = Literal["reserved", "steady", "familiar", "close"]


class RelationshipEventKind(StrEnum):
    APPLY = "apply"
    REVOKE = "revoke"


class RelationshipEventType(StrEnum):
    PREFERRED_ADDRESS = "preferred_address"
    SHARED_EXPERIENCE = "shared_experience"
    NON_EXTERNAL_COMMITMENT = "non_external_commitment"


class RelationshipPayloadState(StrEnum):
    ACTIVE = "active"
    REDACTED = "redacted"


class RelationshipAuthorityAction(StrEnum):
    SUPPRESS = "suppress"
    REENABLE = "reenable"


class RelationshipAuthorityActionKind(StrEnum):
    USER_REVOKE = "user_revoke"
    PRIVACY_REDACT = "privacy_redact"
    USER_REENABLE = "user_reenable"
    INHERITED_CONFLICT_SUPPRESSION = "inherited_conflict_suppression"


class RelationshipReconcileJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class RelationshipReconcileOutcome(StrEnum):
    APPLIED = "applied"
    REVOKED = "revoked"
    NO_CHANGE = "no_change"
    SKIPPED_INELIGIBLE = "skipped_ineligible"
    SKIPPED_SUPPRESSED = "skipped_suppressed"
    STALE_SOURCE = "stale_source"
    STALE_AUTHORITY = "stale_authority"
    INCOMPATIBLE_RECOVERY = "incompatible_recovery"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RelationshipSummaryCode(StrEnum):
    RESERVED = "reserved"
    STEADY = "steady"
    FAMILIAR = "familiar"
    CLOSE = "close"


class RelationshipAuditAction(StrEnum):
    RECONCILED = "reconciled"
    PROJECTED = "projected"
    AUTHORITY_CHANGED = "authority_changed"
    PAYLOAD_REDACTED = "payload_redacted"
    RECOVERY_TERMINALIZED = "recovery_terminalized"


@dataclass(frozen=True)
class RelationshipSourceSnapshot:
    scope_id: str
    source_memory_id: str
    source_memory_version_id: str
    record_head_version: int
    record_generation: int
    record_state: MemoryRecordState
    memory_type: MemoryType
    canonical_subject_code: RelationshipSubjectCode | None
    version_source_kind: MemoryVersionSourceKind
    version_confidence: float
    version_importance: int
    version_created_at: datetime
    open_conflict: bool
    payload_redacted: bool
    effective_authority_decision_id: str | None
    effective_authority_generation: int
    authority_epoch: int
    inherited_authority_fingerprint: str
    authority_suppressed: bool
    relationship_rule_version: str
    preferred_address_candidate: str | None


@dataclass(frozen=True)
class RelationshipEvent:
    id: str
    scope_id: str
    event_kind: RelationshipEventKind
    event_type: RelationshipEventType
    subject_code: RelationshipSubjectCode
    payload_state: RelationshipPayloadState
    payload: Mapping[str, object] | None
    source_memory_id: str
    source_memory_version_id: str
    observed_at: datetime
    observed_time_derivation_version: str
    revokes_event_id: str | None
    rule_version: str
    persona_artifact_id: str
    event_schema_version: str
    integrity_fingerprint: str
    created_at: datetime


@dataclass(frozen=True)
class RelationshipAuthoritySnapshot:
    scope_id: str
    source_memory_id: str
    event_type: RelationshipEventType
    subject_code: RelationshipSubjectCode
    decision_id: str | None
    generation: int
    action: RelationshipAuthorityAction | None
    authority_epoch: int
    inherited_authority_fingerprint: str
    suppressed: bool


@dataclass(frozen=True)
class RelationshipProjectionSnapshot:
    projection_id: str
    version: int
    scope_id: str
    persona_artifact_id: str
    projection_rule_version: str
    familiarity: float
    preferred_address_event_id: str | None
    relationship_summary_code: RelationshipSummaryCode
    source_relationship_event_ids: tuple[str, ...]
    source_emotion_snapshot_id: None
    computed_at: datetime
    integrity_fingerprint: str


@dataclass(frozen=True)
class RelationshipProjectionView:
    projection_id: str
    projection_version: int
    familiarity_bucket: FamiliarityBucket
    preferred_address: str | None
    relationship_summary_code: RelationshipSummaryCode
    persona_artifact_id: str
    projection_rule_version: str
    contributing_event_count: int


@dataclass(frozen=True)
class RelationshipReconcileJob:
    id: str
    scope_id: str
    source_memory_id: str
    source_memory_version_id: str
    status: RelationshipReconcileJobStatus
    outcome: RelationshipReconcileOutcome | None
    captured_record_head_version: int
    captured_record_generation: int
    captured_record_state: MemoryRecordState
    captured_event_type: RelationshipEventType
    captured_subject_code: RelationshipSubjectCode
    captured_authority_decision_id: str | None
    captured_authority_generation: int
    captured_authority_epoch: int
    captured_inherited_authority_fingerprint: str
    relationship_rule_version: str
    persona_artifact_id: str
    job_schema_version: str
    attempt_count: int
    reason_code: str | None
    error_category: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True)
class RelationshipAudit:
    id: str
    action: RelationshipAuditAction
    outcome: RelationshipReconcileOutcome | None
    reason_code: str
    source_memory_id: str | None
    event_id: str | None
    projection_id: str | None
    created_at: datetime
