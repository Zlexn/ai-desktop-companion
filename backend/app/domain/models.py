from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
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
