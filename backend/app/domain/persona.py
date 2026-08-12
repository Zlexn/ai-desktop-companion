from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class PersonaPayloadState(StrEnum):
    ACTIVE = "active"
    REDACTED = "redacted"


@dataclass(frozen=True)
class PersonaArtifact:
    id: str
    version: int
    payload_state: PersonaPayloadState
    schema_version: str
    ruleset_version: str
    template_version: str
    compiler_version: str
    source_content: dict[str, Any] | None
    rendered_system_prompt: str | None
    content_identity_hash: str
    behavior_fingerprint: str
    created_at: datetime
    redacted_at: datetime | None
    redaction_reason_code: str | None


@dataclass(frozen=True)
class PersonaActiveState:
    artifact_id: str
    activation_generation: int
    updated_at: datetime


@dataclass(frozen=True)
class PersonaStartupState:
    artifact_count: int
    active_state: PersonaActiveState | None
