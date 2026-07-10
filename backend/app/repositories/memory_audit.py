from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from app.domain.models import MemoryAuditEvent, MemoryAuditEventType, MemoryAuditOperation
from app.repositories.sqlite import metadata_from_json, metadata_to_json


def _now() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: datetime) -> str:
    return value.isoformat()


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _ids_to_json(memory_ids: list[str]) -> str:
    return json.dumps(memory_ids, ensure_ascii=False)


def _ids_from_json(raw: str) -> list[str]:
    value = json.loads(raw)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _row_to_event(row: sqlite3.Row) -> MemoryAuditEvent:
    return MemoryAuditEvent(
        id=row["id"],
        event_type=MemoryAuditEventType(row["event_type"]),
        memory_id=row["memory_id"],
        related_memory_ids=_ids_from_json(row["related_memory_ids_json"]),
        operation=MemoryAuditOperation(row["operation"]),
        metadata=metadata_from_json(row["metadata_json"]),
        created_at=_from_iso(row["created_at"]),
    )


class MemoryAuditRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def record_conflict(
        self,
        *,
        memory_id: str,
        related_memory_ids: list[str],
        operation: MemoryAuditOperation,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryAuditEvent:
        now = _now()
        event = MemoryAuditEvent(
            id=str(uuid.uuid4()),
            event_type=MemoryAuditEventType.CONFLICT_DETECTED,
            memory_id=memory_id,
            related_memory_ids=list(related_memory_ids),
            operation=operation,
            metadata=metadata or {},
            created_at=now,
        )
        self._connection.execute(
            """
            INSERT INTO memory_audit_events (
                id, event_type, memory_id, related_memory_ids_json,
                operation, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.event_type.value,
                event.memory_id,
                _ids_to_json(event.related_memory_ids),
                event.operation.value,
                metadata_to_json(event.metadata),
                _to_iso(event.created_at),
            ),
        )
        self._connection.commit()
        return event

    def list_recent(self, limit: int = 20) -> list[MemoryAuditEvent]:
        rows = self._connection.execute(
            """
            SELECT id, event_type, memory_id, related_memory_ids_json,
                   operation, metadata_json, created_at
            FROM memory_audit_events
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_event(row) for row in rows]
