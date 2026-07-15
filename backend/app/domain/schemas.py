from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.models import MemoryType


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


class CreateMemoryRequest(BaseModel):
    content: str = Field(min_length=1, max_length=1000)
    memory_type: str
    source_session_id: str | None = None
    importance: int = Field(default=3, ge=1, le=5)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("memory_type")
    @classmethod
    def validate_memory_type(cls, value: str) -> str:
        MemoryType(value)
        return value


class UpdateMemoryRequest(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=1000)
    memory_type: str | None = None
    importance: int | None = Field(default=None, ge=1, le=5)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] | None = None

    @field_validator("memory_type")
    @classmethod
    def validate_optional_memory_type(cls, value: str | None) -> str | None:
        if value is not None:
            MemoryType(value)
        return value


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
