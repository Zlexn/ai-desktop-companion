from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone

from app.domain.models import MemoryRecordState, MemoryType, MemoryVersionSourceKind
from app.domain.relationship import (
    RelationshipAuthoritySnapshot,
    RelationshipSourceSnapshot,
)
from app.services.relationship_contract import (
    RELATIONSHIP_RULE_VERSION,
    RELATIONSHIP_SCOPE_ID,
)


class RelationshipSourceRepository:
    """Reads and independently rechecks exact current Gate B source tuples."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_current(
        self,
        memory_id: str,
        *,
        authority: RelationshipAuthoritySnapshot,
        relationship_rule_version: str = RELATIONSHIP_RULE_VERSION,
    ) -> RelationshipSourceSnapshot | None:
        if not self._valid_authority_identity(memory_id, authority):
            return None
        row = self._read_exact_current(memory_id)
        if row is None or not self._authority_matches_source(row, authority):
            return None
        try:
            subject_code = row["canonical_subject_code"]
            memory_id_value = _required_text(row["memory_id"])
            version_id = _required_text(row["version_id"])
            head_version = _non_negative_integer(row["head_version"])
            record_generation = _non_negative_integer(row["record_generation"])
            confidence = _finite_number(row["confidence"])
            importance = _positive_integer(row["importance"])
            created_at = _utc_datetime(_required_text(row["version_created_at"]))
            content = row["content"]
            if content is not None and not isinstance(content, str):
                return None
            return RelationshipSourceSnapshot(
                scope_id=RELATIONSHIP_SCOPE_ID,
                source_memory_id=memory_id_value,
                source_memory_version_id=version_id,
                record_head_version=head_version,
                record_generation=record_generation,
                record_state=MemoryRecordState(_required_text(row["record_state"])),
                memory_type=MemoryType(_required_text(row["memory_type"])),
                canonical_subject_code=subject_code,
                version_source_kind=MemoryVersionSourceKind(
                    _required_text(row["source_kind"])
                ),
                version_confidence=confidence,
                version_importance=importance,
                version_created_at=created_at,
                open_conflict=_sqlite_boolean(row["open_conflict"]),
                payload_redacted=(
                    row["content"] is None or row["redacted_at"] is not None
                ),
                effective_authority_decision_id=authority.decision_id,
                effective_authority_generation=authority.generation,
                authority_epoch=authority.authority_epoch,
                inherited_authority_fingerprint=(
                    authority.inherited_authority_fingerprint
                ),
                authority_suppressed=authority.suppressed,
                relationship_rule_version=relationship_rule_version,
                preferred_address_candidate=(
                    content
                    if subject_code == "preferred_address"
                    and content is not None
                    else None
                ),
            )
        except (TypeError, ValueError):
            return None

    def matches_current(
        self,
        snapshot: RelationshipSourceSnapshot,
        *,
        authority: RelationshipAuthoritySnapshot,
    ) -> bool:
        current = self.get_current(
            snapshot.source_memory_id,
            authority=authority,
            relationship_rule_version=snapshot.relationship_rule_version,
        )
        return current == snapshot

    def _read_exact_current(self, memory_id: str) -> sqlite3.Row | None:
        return self._connection.execute(
            """
            SELECT
                state.memory_id,
                state.state AS record_state,
                state.current_version_id,
                state.head_version,
                state.record_generation,
                version.id AS version_id,
                version.memory_type,
                version.canonical_subject_code,
                version.source_kind,
                version.confidence,
                version.importance,
                version.created_at AS version_created_at,
                version.content,
                version.redacted_at,
                EXISTS (
                    SELECT 1
                    FROM memory_conflicts AS conflict
                    WHERE conflict.status = 'open'
                      AND state.memory_id IN (
                          conflict.left_memory_id,
                          conflict.right_memory_id
                      )
                ) AS open_conflict
            FROM memory_record_states AS state
            JOIN memory_versions AS version
              ON version.memory_id = state.memory_id
             AND version.id = state.current_version_id
             AND version.version_number = state.head_version
            JOIN memories AS memory
              ON memory.id = state.memory_id
            WHERE state.memory_id = ?
            """,
            (memory_id,),
        ).fetchone()

    @staticmethod
    def _authority_matches_source(
        row: sqlite3.Row,
        authority: RelationshipAuthoritySnapshot,
    ) -> bool:
        subject_code = row["canonical_subject_code"]
        return (
            subject_code is not None
            and authority.event_type.value == subject_code
            and authority.subject_code == subject_code
        )

    @staticmethod
    def _valid_authority_identity(
        memory_id: str,
        authority: RelationshipAuthoritySnapshot,
    ) -> bool:
        return (
            authority.scope_id == RELATIONSHIP_SCOPE_ID
            and authority.source_memory_id == memory_id
            and authority.event_type.value == authority.subject_code
            and isinstance(authority.generation, int)
            and not isinstance(authority.generation, bool)
            and authority.generation >= 0
            and isinstance(authority.authority_epoch, int)
            and not isinstance(authority.authority_epoch, bool)
            and authority.authority_epoch >= 0
            and isinstance(authority.inherited_authority_fingerprint, str)
            and len(authority.inherited_authority_fingerprint) == 64
            and all(
                character in "0123456789abcdef"
                for character in authority.inherited_authority_fingerprint
            )
        )


def _required_text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("relationship source text field is invalid")
    return value


def _non_negative_integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("relationship source integer field is invalid")
    return value


def _positive_integer(value: object) -> int:
    numeric = _non_negative_integer(value)
    if numeric < 1:
        raise ValueError("relationship source integer field is invalid")
    return numeric


def _finite_number(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise ValueError("relationship source number field is invalid")
    return float(value)


def _sqlite_boolean(value: object) -> bool:
    if type(value) is not int or value not in (0, 1):
        raise ValueError("relationship source boolean field is invalid")
    return bool(value)


def _utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
