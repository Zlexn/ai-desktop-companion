from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal


from app.domain.models import ChatRole


class SummaryPayloadState(StrEnum):
    ACTIVE = "active"
    REDACTED = "redacted"
    QUARANTINED = "quarantined"


class SummaryProvenanceState(StrEnum):
    EXACT = "exact"
    LEGACY_UNVERIFIED = "legacy_unverified"


class SummaryAuthorityStatus(StrEnum):
    UNKNOWN = "unknown"
    GRANTED = "granted"
    DECLINED = "declined"
    REVOKED = "revoked"


class SummaryJobKind(StrEnum):
    INCREMENTAL = "incremental"
    REBUILD = "rebuild"


class SummaryJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class SummarySuppressionState(StrEnum):
    SUPPRESSED = "suppressed"
    REBUILD_AUTHORIZED = "rebuild_authorized"
    REBUILD_IN_PROGRESS = "rebuild_in_progress"
    REBUILD_COMPLETED = "rebuild_completed"


class SummaryAuditOutcome(StrEnum):
    CREATED = "created"
    REDACTED = "redacted"
    QUARANTINED = "quarantined"
    REVALIDATED = "revalidated"
    MIGRATION_INVALIDATED = "migration_invalidated"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ChatTurn:
    id: str
    session_id: str
    user_message_id: str
    assistant_message_id: str
    turn_order: int
    created_at: datetime


@dataclass(frozen=True)
class SummarySuppression:
    session_id: str
    source_set_hash: str
    generation: int
    state: SummarySuppressionState
    rebuild_permit_id: str | None
    bound_job_id: str | None
    authorized_summary_id: str | None
    reason_code: str
    created_at: datetime
    updated_at: datetime

    @property
    def permit_id(self) -> str:
        if self.rebuild_permit_id is None:
            raise ValueError("suppression has no rebuild permit")
        return self.rebuild_permit_id


@dataclass(frozen=True)
class SummarySnapshotMessage:
    id: str
    role: ChatRole
    content: str
    message_order_in_turn: int


@dataclass(frozen=True)
class SummarySnapshotTurn:
    id: str
    turn_order: int
    messages: tuple[SummarySnapshotMessage, SummarySnapshotMessage]


@dataclass(frozen=True)
class SummarySourceSnapshot:
    session_id: str
    barrier_generation: int
    candidate_turn_count: int
    source_character_count: int
    turns: tuple[SummarySnapshotTurn, ...]
    source_set_hash: str | None

    @property
    def source_turn_count(self) -> int:
        return len(self.turns)

    @property
    def source_message_count(self) -> int:
        return self.source_turn_count * 2


@dataclass(frozen=True)
class SummaryJob:
    id: str
    session_id: str
    job_kind: SummaryJobKind
    status: SummaryJobStatus
    logical_source_identity: str
    attempt_epoch: str
    source_set_hash: str
    source_message_count: int
    source_turn_count: int
    captured_barrier_generation: int
    captured_processing_consent_generation: int
    captured_processing_policy_fingerprint: str | None
    captured_session_deletion_generation: int
    captured_suppression_generation: int
    captured_rebuild_authorization_generation: int
    rebuild_permit_id: str | None
    source_summary_id: str | None
    route: Literal["fake", "remote"]
    provider: str | None
    model: str | None
    summarizer_schema_version: str
    job_schema_version: str
    attempt_count: int
    reason_code: str | None
    error_category: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True)
class SummaryRecordState:
    payload_state: SummaryPayloadState
    provenance_state: SummaryProvenanceState
    source_message_count: int
    source_turn_count: int
    source_started_at: datetime | None
    source_ended_at: datetime | None
    replaces_summary_id: str | None


@dataclass(frozen=True)
class SummarySourceFragment:
    summary_id: str
    source_session_id: str
    source_kind: Literal["generated"]
    created_at: datetime
    summary_text: str
    observed_barrier_generation: int
    source_set_hash: str
    suppression_generation: int
    suppression_state: SummarySuppressionState | None
    summarizer_schema_version: str
    injection_schema_version: str
    source_turn_ids: tuple[str, ...]
    source_message_ids: tuple[str, ...]
    source_session_deletion_generation: int = 0


@dataclass(frozen=True)
class SummaryInjectionAuthoritySnapshot:
    generation: int
    policy_fingerprint: str
    disclosure_version: str
    disclosed_fields: tuple[str, ...]
    max_fragment_count: int
    max_fragment_characters: int
    max_total_characters: int
