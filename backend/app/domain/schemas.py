from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.models import MemoryType
from app.services.relationship_contract import canonical_relationship_subject_code
from app.services.memory_gate_b_contract import MEMORY_ALLOWED_AUTO_TYPES


class PersonaIdentityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)
    species: str = Field(min_length=1, max_length=60)
    role: str = Field(min_length=1, max_length=80)


class PersonaPersonalityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    core_traits: list[str] = Field(min_length=1, max_length=12)
    values: list[str] = Field(min_length=1, max_length=12)


class PersonaLanguageStyleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tone: str = Field(min_length=1, max_length=120)
    habits: list[str] = Field(min_length=1, max_length=12)


class PersonaRelationshipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    initial: str = Field(min_length=1, max_length=300)


class PersonaConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity: PersonaIdentityRequest
    background: str = Field(min_length=1, max_length=1_000)
    personality: PersonaPersonalityRequest
    language_style: PersonaLanguageStyleRequest
    relationship: PersonaRelationshipRequest
    additional_prohibitions: list[str] = Field(default_factory=list, max_length=20)


class PersonaCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: PersonaConfigRequest
    expected_artifact_id: str = Field(min_length=1)
    expected_generation: int = Field(ge=0)


class PersonaActivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_id: str = Field(min_length=1)
    expected_artifact_id: str = Field(min_length=1)
    expected_generation: int = Field(ge=0)


class PersonaRedactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_artifact_id: str = Field(min_length=1)
    expected_generation: int = Field(ge=0)
    replacement_artifact_id: str | None = None
    replacement_config: PersonaConfigRequest | None = None
    confirmation: Literal["redact_persona_payload"]

    @model_validator(mode="after")
    def reject_multiple_replacements(self):
        if (
            self.replacement_artifact_id is not None
            and self.replacement_config is not None
        ):
            raise ValueError("choose at most one replacement mechanism")
        return self


class PersonaArtifactResponse(BaseModel):
    id: str
    version: int
    payload_state: str
    schema_version: str
    ruleset_version: str
    template_version: str
    compiler_version: str
    config: dict[str, Any] | None
    created_at: datetime
    redacted_at: datetime | None
    active: bool
    activation_generation: int
    fingerprint_prefix: str | None
    outcome: str | None = None


class PersonaRedactResponse(BaseModel):
    redacted: PersonaArtifactResponse
    active: PersonaArtifactResponse


class PersonaCapabilitiesResponse(BaseModel):
    persona_artifacts: bool
    context_composer: bool
    summary_processing: bool
    summary_injection: bool
    relationship_projection: bool
    remote_summary: str


class SummaryCapabilitiesResponse(BaseModel):
    summary_processing: bool
    summary_injection: bool
    processing_route: str
    processing_provider: str
    processing_model: str
    injection_route: str
    injection_provider: str
    injection_model: str
    remote_summary: str


class SummaryAuthorityMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "grant",
        "decline",
        "revoke",
        "enable_local",
        "disable_local",
    ]
    expected_generation: int = Field(ge=0)


class SummaryProcessingConsentResponse(BaseModel):
    scope_id: str
    status: str
    route: str
    disclosure_version: str
    purpose: str
    provider: str
    model: str
    disclosed_fields: list[str]
    generation: int
    valid_for_current_policy: bool
    reason_code: str | None
    updated_at: datetime


class SummaryInjectionConsentResponse(BaseModel):
    scope_id: str
    status: str
    route: str
    disclosure_version: str
    purpose: str
    provider: str
    model: str
    disclosed_fields: list[str]
    generation: int
    max_fragment_count: int
    max_fragment_characters: int
    max_total_characters: int
    valid_for_current_policy: bool
    reason_code: str | None
    updated_at: datetime


class SummaryStatusResponse(BaseModel):
    summary_counts: dict[str, int]
    job_counts: dict[str, int]


class SummaryItemResponse(BaseModel):
    id: str
    session_id: str
    summary_text: str | None
    source_kind: str
    payload_state: str
    provenance_state: str
    source_message_count: int
    source_turn_count: int
    source_started_at: datetime | None
    source_ended_at: datetime | None
    replaces_summary_id: str | None
    suppression_generation: int
    suppression_state: str | None
    unavailable_label: str | None
    created_at: datetime
    updated_at: datetime


class SummaryJobResponse(BaseModel):
    id: str
    session_id: str
    job_kind: str
    status: str
    source_message_count: int
    source_turn_count: int
    route: str
    provider: str | None
    model: str | None
    summarizer_schema_version: str
    job_schema_version: str
    attempt_count: int
    reason_code: str | None
    error_category: str | None
    retryable: bool
    cancellable: bool
    suppression_generation: int | None
    suppression_state: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class SummaryAuditResponse(BaseModel):
    id: str
    kind: str
    status: str
    outcome: str | None
    session_id: str | None
    job_id: str | None
    summary_id: str | None
    generation: int | None
    source_message_count: int | None
    source_turn_count: int | None
    route: str | None
    provider: str | None
    model: str | None
    reason_code: str | None
    error_category: str | None
    created_at: datetime


class SummaryPageResponse(BaseModel):
    items: list[SummaryItemResponse]
    next_cursor: str | None


class SummaryJobPageResponse(BaseModel):
    items: list[SummaryJobResponse]
    next_cursor: str | None


class SummaryAuditPageResponse(BaseModel):
    items: list[SummaryAuditResponse]
    next_cursor: str | None


class SummaryRedactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_suppression_generation: int = Field(ge=0)
    confirmation: Literal["redact_summary_payload"]


class SummaryRebuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_suppression_generation: int = Field(ge=0)


class SummaryJobMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_status: Literal["failed", "cancelled", "skipped", "pending", "running"]
    expected_suppression_generation: int | None = Field(default=None, ge=0)
    expected_suppression_state: Literal[
        "suppressed",
        "rebuild_authorized",
        "rebuild_in_progress",
        "rebuild_completed",
    ] | None = None

    @model_validator(mode="after")
    def require_paired_suppression_snapshot(self):
        if (self.expected_suppression_generation is None) != (
            self.expected_suppression_state is None
        ):
            raise ValueError("suppression generation and state must be paired")
        return self


class SummaryMutationResponse(BaseModel):
    outcome: str
    summary_id: str | None = None
    job_id: str | None = None
    status: str | None = None
    suppression_generation: int | None = None
    suppression_state: str | None = None


class CreateSessionRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)


class SessionResponse(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class SynthesizeSpeechRequest(BaseModel):
    text: str
    voice_id: str | None = None
    speed: float | None = None


class MessageBoundSynthesizeSpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_id: str | None = None
    speed: float | None = None


class MessageExpressionResponse(BaseModel):
    assistant_message_id: str
    schema_version: Literal[1]
    delivery: Literal["neutral", "warm", "reassuring", "reserved", "firm"]
    intensity: Literal["low", "medium"]
    rate: float = Field(ge=0.90, le=1.10)
    source: Literal["persisted_plan", "default"]


class ChatMetadata(BaseModel):
    provider: str
    model: str


class ChatResponse(BaseModel):
    reply: str
    metadata: ChatMetadata
    assistant_message_id: str


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


class TranscriptionResponse(BaseModel):
    text: str
    detected_language: str | None
    duration_ms: int | None
    provider: str
    model: str
    inference_ms: int


RelationshipSubjectCode = Literal[
    "preferred_address",
    "shared_experience",
    "non_external_commitment",
]


def _validate_relationship_subject_pair(
    *,
    memory_type: str | None,
    subject_code: str | None,
) -> None:
    if subject_code is None or memory_type is None:
        return
    canonical_relationship_subject_code(
        memory_type=MemoryType(memory_type),
        explicit_subject_code=subject_code,
    )


class CreateMemoryRequest(BaseModel):
    content: str = Field(min_length=1, max_length=1000)
    memory_type: str
    source_session_id: str | None = None
    importance: int = Field(default=3, ge=1, le=5)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    canonical_subject_code: RelationshipSubjectCode | None = None

    @field_validator("memory_type")
    @classmethod
    def validate_memory_type(cls, value: str) -> str:
        MemoryType(value)
        return value

    @model_validator(mode="after")
    def validate_relationship_subject(self):
        _validate_relationship_subject_pair(
            memory_type=self.memory_type,
            subject_code=self.canonical_subject_code,
        )
        return self


class UpdateMemoryRequest(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=1000)
    memory_type: str | None = None
    importance: int | None = Field(default=None, ge=1, le=5)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] | None = None
    canonical_subject_code: RelationshipSubjectCode | None = None

    @field_validator("memory_type")
    @classmethod
    def validate_optional_memory_type(cls, value: str | None) -> str | None:
        if value is not None:
            MemoryType(value)
        return value

    @model_validator(mode="after")
    def validate_relationship_subject(self):
        _validate_relationship_subject_pair(
            memory_type=self.memory_type,
            subject_code=self.canonical_subject_code,
        )
        return self


class ConfirmMemoryCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_subject_code: RelationshipSubjectCode | None = None


class MemoryResponse(BaseModel):
    id: str
    content: str
    memory_type: str
    source: str
    source_session_id: str | None
    importance: int
    confidence: float
    status: str
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    v2_state: str | None
    v2_source_kind: str | None
    version_count: int
    evidence_count: int
    has_open_conflict: bool
    can_undo_latest_auto: bool
    canonical_subject_code: RelationshipSubjectCode | None = None


class MemoryMutationResponse(BaseModel):
    memory: MemoryResponse
    conflicts: list[MemoryResponse] = Field(default_factory=list)


class MemoryAuditEventResponse(BaseModel):
    id: str
    event_type: str
    memory_id: str
    related_memory_ids: list[str]
    operation: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class UpdateMemoryWriteConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["grant", "decline", "revoke"]
    policy_version: Literal["memory-auto-write-policy-v1"]
    retention_disclosure_version: Literal["memory-auto-write-retention-v1"]
    allowed_memory_types_version: Literal["memory-auto-write-types-v1"]
    allowed_memory_types: list[
        Literal[
            "user_fact",
            "preference",
            "long_term_goal",
            "important_event",
            "relationship_event",
            "other",
        ]
    ]

    @model_validator(mode="after")
    def validate_exact_allowed_memory_types(self):
        expected = [memory_type.value for memory_type in MEMORY_ALLOWED_AUTO_TYPES]
        if self.allowed_memory_types != expected:
            raise ValueError(
                "allowed_memory_types must exactly match the ordered Gate B set"
            )
        return self


class MemoryWriteConsentResponse(BaseModel):
    scope_id: str
    status: str
    purpose: str | None
    policy_version: str | None
    retention_disclosure_version: str | None
    allowed_memory_types_version: str | None
    allowed_memory_types: list[str]
    generation: int
    granted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MemoryVersionResponse(BaseModel):
    id: str
    memory_id: str
    version_number: int
    parent_version_id: str | None
    operation: str
    memory_type: str
    subject: str | None
    content: str | None
    confidence: float
    importance: int
    source_kind: str
    source_session_id: str | None
    created_at: datetime
    redacted_at: datetime | None
    canonical_subject_code: RelationshipSubjectCode | None = None


class MemoryEvidenceResponse(BaseModel):
    id: str
    memory_id: str
    memory_version_id: str
    source_session_id: str | None
    source_message_id: str | None
    source_available: bool
    relation: str
    observed_at: datetime
    extractor_kind: str
    extractor_provider: str | None
    extractor_model: str | None
    confidence: float
    created_at: datetime


class MemoryConflictResponse(BaseModel):
    id: str
    left_memory_id: str
    right_memory_id: str
    status: str
    resolution_kind: str | None
    resolved_memory_id: str | None
    created_at: datetime
    resolved_at: datetime | None


class MemoryVersionPageResponse(BaseModel):
    items: list[MemoryVersionResponse]
    next_cursor: str | None


class MemoryEvidencePageResponse(BaseModel):
    items: list[MemoryEvidenceResponse]
    next_cursor: str | None


class MemoryConflictPageResponse(BaseModel):
    items: list[MemoryConflictResponse]
    next_cursor: str | None


class MemoryForgetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["session", "memory_type", "all"]
    scope_id: str | None = None

    @model_validator(mode="after")
    def validate_scope_id(self):
        if self.scope == "all" and self.scope_id is not None:
            raise ValueError("all scope forbids scope_id")
        if self.scope != "all" and not self.scope_id:
            raise ValueError("selected scope requires scope_id")
        if self.scope == "memory_type":
            try:
                MemoryType(str(self.scope_id))
            except ValueError as exc:
                raise ValueError("invalid memory_type scope_id") from exc
        return self


class MemoryForgetResponse(BaseModel):
    scope: str
    scope_id: str | None
    forgotten_memory_ids: list[str]
    forgotten_candidate_ids: list[str]
    deletion_generation: int
    summary_barrier_generation: int


class ChooseLeftConflictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["choose_left"]


class ChooseRightConflictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["choose_right"]


class ReplaceConflictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["replace_both", "both_contextual"]
    content: str = Field(min_length=1, max_length=2000)
    memory_type: Literal[
        "user_fact",
        "preference",
        "long_term_goal",
        "important_event",
        "relationship_event",
        "other",
    ]
    subject: str = Field(min_length=1, max_length=200)
    importance: int = Field(default=3, ge=1, le=5)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    canonical_subject_code: RelationshipSubjectCode | None = None

    @model_validator(mode="after")
    def validate_relationship_subject(self):
        _validate_relationship_subject_pair(
            memory_type=self.memory_type,
            subject_code=self.canonical_subject_code,
        )
        return self


class DismissBothConflictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["dismiss_both"]


MemoryConflictResolutionRequest = Annotated[
    ChooseLeftConflictRequest
    | ChooseRightConflictRequest
    | ReplaceConflictRequest
    | DismissBothConflictRequest,
    Field(discriminator="kind"),
]


class MemoryConflictResolutionResponse(BaseModel):
    conflict: MemoryConflictResponse
    resolved_memory: MemoryResponse | None


class MemoryUndoResponse(BaseModel):
    memory_id: str
    action: Literal["forgotten_create", "reverted_supersede", "retracted_support"]
    memory: MemoryResponse | None = None


class UpdateMemoryExtractionConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["grant", "decline", "revoke"]
    disclosure_version: Literal["memory-extraction-disclosure-v1"]


class MemoryExtractionConsentResponse(BaseModel):
    scope_id: str
    status: str
    purpose: str | None
    provider: str | None
    disclosure_version: str | None
    disclosed_fields: list[str]
    generation: int
    deployment_route: str
    deployment_provider: str
    deployment_configured: bool
    created_at: datetime
    updated_at: datetime


class MemoryJobResponse(BaseModel):
    id: str
    turn_id: str
    schema_version: str
    session_id: str | None
    user_message_id: str | None
    assistant_message_id: str | None
    mode: str
    extractor_route: str
    status: str
    attempt_count: int
    outcome: str | None
    error_category: str | None
    governor_version: str
    consent_generation: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    persona_artifact_id: str | None


class MemoryJobAuditResponse(BaseModel):
    id: str
    job_id: str
    outcome: str
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


class EmotionVectorResponse(BaseModel):
    mood: float
    trust: float
    concern: float
    distance: float
    irritation: float
    formality: float


class EmotionStateResponse(BaseModel):
    scope_id: str
    enabled: bool
    vector: EmotionVectorResponse
    version: int
    updated_at: datetime


class EmotionEventResponse(BaseModel):
    id: str
    event_type: str
    before: EmotionVectorResponse
    after: EmotionVectorResponse
    applied_delta: EmotionVectorResponse
    reason_codes: list[str]
    source_session_id: str | None
    source_user_message_id: str | None
    source_assistant_message_id: str | None
    engine: str
    rule_version: str
    created_at: datetime


class UpdateEmotionSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class UpdateEmotionAnalysisConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["grant", "decline", "revoke"]
    disclosure_version: Literal["emotion-analysis-disclosure-v1"]


class EmotionAnalysisConsentResponse(BaseModel):
    scope_id: str
    status: str
    disclosure_version: str | None
    provider: str | None
    deployment_provider: str
    deployment_enabled: bool
    updated_at: datetime


class EmotionAnalysisAuditResponse(BaseModel):
    id: str
    job_id: str
    outcome: str
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
