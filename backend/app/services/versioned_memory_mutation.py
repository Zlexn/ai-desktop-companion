from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.errors import (
    MemoryCandidateForgottenError,
    MemoryConflictRequiresResolutionError,
)
from app.domain.models import (
    Memory,
    MemoryAuditOperation,
    MemoryRecordState,
    MemorySource,
    MemoryStatus,
    MemoryType,
    MemoryVersionOperation,
    MemoryVersionSourceKind,
)
from app.repositories.memories import MemoryRepository
from app.repositories.sqlite import metadata_to_json
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.services.memory_gate_b_contract import MEMORY_CANONICALIZATION_VERSION
from app.services.memory_commit_policy import canonicalize_memory_v1
from app.services.memory_source_reference import MemorySourceReferenceService
from app.services.relationship_contract import canonical_relationship_subject_code
from app.services.relationship_hooks import (
    NoOpRelationshipChangeNotifier,
    RelationshipChangeNotifier,
)


_MANUAL_WRITER_POLICY_VERSION = "memory-manual-write-v1"


def _now() -> datetime:
    return datetime.now(UTC)


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class VersionedMemoryMutationPrimitive:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def insert_projection(
        self,
        *,
        memory_id: str,
        content: str,
        memory_type: MemoryType,
        source: MemorySource,
        source_session_id: str | None,
        importance: int,
        confidence: float,
        status: MemoryStatus,
        metadata: dict[str, Any],
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO memories (
                id, content, memory_type, source, source_session_id,
                importance, confidence, status, metadata_json, created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                content,
                memory_type.value,
                source.value,
                source_session_id,
                importance,
                confidence,
                status.value,
                metadata_to_json(metadata),
                created_at.isoformat(),
                updated_at.isoformat(),
            ),
        )

    def update_projection(
        self,
        *,
        memory_id: str,
        content: str,
        memory_type: MemoryType,
        importance: int,
        confidence: float,
        status: MemoryStatus,
        metadata: dict[str, Any],
        updated_at: datetime,
    ) -> None:
        cursor = self._connection.execute(
            """
            UPDATE memories
            SET content = ?, memory_type = ?, importance = ?, confidence = ?,
                status = ?, metadata_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                content,
                memory_type.value,
                importance,
                confidence,
                status.value,
                metadata_to_json(metadata),
                updated_at.isoformat(),
                memory_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("memory projection update failed")

    def insert_root(
        self,
        *,
        memory_id: str,
        content: str,
        memory_type: MemoryType,
        importance: int,
        confidence: float,
        source_kind: MemoryVersionSourceKind,
        source_session_id: str | None,
        source_session_reference_hash: str | None,
        created_at: datetime,
        operation: MemoryVersionOperation = MemoryVersionOperation.CREATE,
        subject: str | None = None,
        canonical_key_hash: str | None = None,
        subject_key_hash: str | None = None,
        canonical_subject_code: str | None = None,
    ) -> tuple[str, int]:
        canonical_subject_code = canonical_relationship_subject_code(
            memory_type=memory_type,
            explicit_subject_code=canonical_subject_code,
        )
        version_id = str(uuid.uuid4())
        self._connection.execute(
            """
            INSERT INTO memory_versions (
                id, memory_id, version_number, parent_version_id, operation,
                memory_type, subject, content, content_hash,
                canonical_key_hash, subject_key_hash,
                canonicalization_version, confidence, importance, source_kind,
                source_session_id, source_session_reference_hash,
                writer_policy_version, created_at, redacted_at,
                canonical_subject_code
            ) VALUES (?, ?, 1, NULL, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                version_id,
                memory_id,
                operation.value,
                memory_type.value,
                subject,
                content,
                _content_hash(content),
                canonical_key_hash,
                subject_key_hash,
                MEMORY_CANONICALIZATION_VERSION,
                confidence,
                importance,
                source_kind.value,
                source_session_id,
                source_session_reference_hash,
                _MANUAL_WRITER_POLICY_VERSION,
                created_at.isoformat(),
                canonical_subject_code,
            ),
        )
        self._connection.execute(
            """
            INSERT INTO memory_record_states (
                memory_id, state, current_version_id, head_version,
                record_generation, canonical_key_hash, subject_key_hash,
                canonicalization_version, source_kind, created_at, updated_at
            ) VALUES (?, 'active', ?, 1, 0, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                version_id,
                canonical_key_hash,
                subject_key_hash,
                MEMORY_CANONICALIZATION_VERSION,
                source_kind.value,
                created_at.isoformat(),
                created_at.isoformat(),
            ),
        )
        return version_id, 1

    def insert_successor(
        self,
        *,
        memory_id: str,
        parent_version_id: str,
        version_number: int,
        operation: MemoryVersionOperation,
        content: str,
        memory_type: MemoryType,
        importance: int,
        confidence: float,
        source_kind: MemoryVersionSourceKind,
        source_session_id: str | None,
        source_session_reference_hash: str | None,
        created_at: datetime,
        subject: str | None = None,
        canonical_key_hash: str | None = None,
        subject_key_hash: str | None = None,
        canonical_subject_code: str | None = None,
    ) -> str:
        canonical_subject_code = canonical_relationship_subject_code(
            memory_type=memory_type,
            explicit_subject_code=canonical_subject_code,
        )
        version_id = str(uuid.uuid4())
        self._connection.execute(
            """
            INSERT INTO memory_versions (
                id, memory_id, version_number, parent_version_id, operation,
                memory_type, subject, content, content_hash,
                canonical_key_hash, subject_key_hash,
                canonicalization_version, confidence, importance, source_kind,
                source_session_id, source_session_reference_hash,
                writer_policy_version, created_at, redacted_at,
                canonical_subject_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                version_id,
                memory_id,
                version_number,
                parent_version_id,
                operation.value,
                memory_type.value,
                subject,
                content,
                _content_hash(content),
                canonical_key_hash,
                subject_key_hash,
                MEMORY_CANONICALIZATION_VERSION,
                confidence,
                importance,
                source_kind.value,
                source_session_id,
                source_session_reference_hash,
                _MANUAL_WRITER_POLICY_VERSION,
                created_at.isoformat(),
                canonical_subject_code,
            ),
        )
        return version_id

    def compare_and_set_head(
        self,
        *,
        memory_id: str,
        expected_current_version_id: str,
        expected_head_version: int,
        expected_record_generation: int,
        next_state: MemoryRecordState,
        next_current_version_id: str,
        next_head_version: int,
        next_source_kind: MemoryVersionSourceKind,
        updated_at: datetime,
        canonical_key_hash: str | None = None,
        subject_key_hash: str | None = None,
    ) -> bool:
        cursor = self._connection.execute(
            """
            UPDATE memory_record_states
            SET state = ?, current_version_id = ?, head_version = ?,
                record_generation = record_generation + 1,
                canonical_key_hash = ?, subject_key_hash = ?,
                canonicalization_version = ?, source_kind = ?, updated_at = ?
            WHERE memory_id = ? AND current_version_id = ?
              AND head_version = ? AND record_generation = ?
            """,
            (
                next_state.value,
                next_current_version_id,
                next_head_version,
                canonical_key_hash,
                subject_key_hash,
                MEMORY_CANONICALIZATION_VERSION,
                next_source_kind.value,
                updated_at.isoformat(),
                memory_id,
                expected_current_version_id,
                expected_head_version,
                expected_record_generation,
            ),
        )
        return cursor.rowcount == 1

    def touch_head(
        self,
        *,
        memory_id: str,
        expected_current_version_id: str,
        expected_head_version: int,
        expected_record_generation: int,
        updated_at: datetime,
    ) -> bool:
        cursor = self._connection.execute(
            """
            UPDATE memory_record_states
            SET record_generation = record_generation + 1, updated_at = ?
            WHERE memory_id = ? AND state = 'active'
              AND current_version_id = ? AND head_version = ?
              AND record_generation = ?
            """,
            (
                updated_at.isoformat(),
                memory_id,
                expected_current_version_id,
                expected_head_version,
                expected_record_generation,
            ),
        )
        return cursor.rowcount == 1

    def record_conflict_audit(
        self,
        *,
        memory_id: str,
        related_memory_ids: list[str],
        operation: MemoryAuditOperation,
        created_at: datetime,
    ) -> None:
        if not related_memory_ids:
            return
        self._connection.execute(
            """
            INSERT INTO memory_audit_events (
                id, event_type, memory_id, related_memory_ids_json,
                operation, metadata_json, created_at
            ) VALUES (?, 'conflict_detected', ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                memory_id,
                json.dumps(related_memory_ids, ensure_ascii=False),
                operation.value,
                metadata_to_json({"conflict_count": len(related_memory_ids)}),
                created_at.isoformat(),
            ),
        )

    def insert_delete_head(
        self,
        *,
        memory_id: str,
        parent_version_id: str,
        version_number: int,
        memory_type: MemoryType,
        content_hash: str,
        canonical_key_hash: str | None,
        subject_key_hash: str | None,
        canonicalization_version: str,
        confidence: float,
        importance: int,
        source_kind: MemoryVersionSourceKind,
        source_session_id: str | None,
        source_session_reference_hash: str | None,
        created_at: datetime,
        canonical_subject_code: str | None = None,
    ) -> str:
        canonical_subject_code = canonical_relationship_subject_code(
            memory_type=memory_type,
            explicit_subject_code=canonical_subject_code,
        )
        version_id = str(uuid.uuid4())
        self._connection.execute(
            """
            INSERT INTO memory_versions (
                id, memory_id, version_number, parent_version_id, operation,
                memory_type, subject, content, content_hash,
                canonical_key_hash, subject_key_hash,
                canonicalization_version, confidence, importance, source_kind,
                source_session_id, source_session_reference_hash,
                writer_policy_version, created_at, redacted_at,
                canonical_subject_code
            ) VALUES (?, ?, ?, ?, 'delete', ?, NULL, NULL, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, 'memory-true-forget-v1', ?, NULL, ?)
            """,
            (
                version_id,
                memory_id,
                version_number,
                parent_version_id,
                memory_type.value,
                content_hash,
                canonical_key_hash,
                subject_key_hash,
                canonicalization_version,
                confidence,
                importance,
                source_kind.value,
                source_session_id,
                source_session_reference_hash,
                created_at.isoformat(),
                canonical_subject_code,
            ),
        )
        return version_id

    def insert_tombstone(
        self,
        *,
        source_memory_id: str,
        memory_type: MemoryType,
        canonical_key_hash: str | None,
        subject_key_hash: str | None,
        canonicalization_version: str,
        delete_generation: int,
        reason_code: str,
        created_at: datetime,
        content_key_hash: str | None = None,
    ) -> None:
        cursor = self._connection.execute(
            """
            INSERT INTO memory_tombstones (
                tombstone_id, source_memory_id, memory_type,
                canonical_key_hash, subject_key_hash, content_key_hash,
                canonicalization_version, delete_generation, reason_code,
                created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT DO NOTHING
            """,
            (
                str(uuid.uuid4()),
                source_memory_id,
                memory_type.value,
                canonical_key_hash,
                subject_key_hash,
                content_key_hash,
                canonicalization_version,
                delete_generation,
                reason_code,
                created_at.isoformat(),
            ),
        )
        if cursor.rowcount == 0:
            existing = self._connection.execute(
                """
                SELECT 1 FROM memory_tombstones
                WHERE source_memory_id = ? AND memory_type = ?
                  AND canonical_key_hash IS ? AND subject_key_hash IS ?
                  AND content_key_hash IS ? AND canonicalization_version = ?
                """,
                (
                    source_memory_id,
                    memory_type.value,
                    canonical_key_hash,
                    subject_key_hash,
                    content_key_hash,
                    canonicalization_version,
                ),
            ).fetchone()
            if existing is None:
                raise RuntimeError("memory tombstone insertion failed")

    def redact_projection(self, memory_id: str, *, updated_at: datetime) -> None:
        cursor = self._connection.execute(
            """
            UPDATE memories
            SET content = '', status = 'archived',
                metadata_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                metadata_to_json(
                    {"payload_redacted": True, "reason_code": "memory_true_forget"}
                ),
                updated_at.isoformat(),
                memory_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("memory projection redaction failed")

    def redact_versions(self, memory_id: str, *, redacted_at: datetime) -> None:
        self._connection.execute(
            """
            UPDATE memory_versions
            SET subject = NULL, content = NULL, redacted_at = ?
            WHERE memory_id = ? AND redacted_at IS NULL
            """,
            (redacted_at.isoformat(), memory_id),
        )

    def redact_candidate(self, memory_id: str, *, updated_at: datetime) -> None:
        cursor = self._connection.execute(
            """
            UPDATE memories
            SET content = '', status = 'dismissed',
                metadata_json = ?, updated_at = ?
            WHERE id = ? AND status IN ('pending', 'dismissed')
            """,
            (
                metadata_to_json(
                    {
                        "forgotten": True,
                        "payload_redacted": True,
                        "reason_code": "memory_true_forget",
                    }
                ),
                updated_at.isoformat(),
                memory_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("memory candidate redaction failed")

    def delete_embedding(self, memory_id: str) -> None:
        self._connection.execute(
            "DELETE FROM memory_embeddings WHERE memory_id = ?",
            (memory_id,),
        )


class VersionedMemoryMutationService:
    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        memories: MemoryRepository,
        versioned: VersionedMemoryRepository,
        source_references: MemorySourceReferenceService | None = None,
        relationship_notifier: RelationshipChangeNotifier | None = None,
    ) -> None:
        self._connection = connection
        self._memories = memories
        self._versioned = versioned
        self._source_references = source_references
        self._relationship_notifier = (
            relationship_notifier or NoOpRelationshipChangeNotifier()
        )
        self.primitive = VersionedMemoryMutationPrimitive(connection)

    def _notify_relationship_change(self, memory_ids: tuple[str, ...]) -> None:
        """Best-effort post-commit notification; never raises into callers.

        This is a non-privacy boundary: a failed callback must not affect the
        already-committed Gate B mutation. Startup recovery guarantees eventual
        reconciliation convergence independently of this notification.
        """
        try:
            self._relationship_notifier.schedule(memory_ids)
        except Exception:
            # Notification is best-effort; convergence relies on startup scan.
            pass

    def _notify_relationship_change_for_memory(self, memory_id: str) -> None:
        self._notify_relationship_change((memory_id,))

    def create_manual(
        self,
        *,
        content: str,
        memory_type: MemoryType,
        source_session_id: str | None,
        importance: int,
        confidence: float,
        metadata: dict[str, Any] | None = None,
        canonical_subject_code: str | None = None,
    ) -> tuple[Memory, list[Memory]]:
        canonical_subject_code = canonical_relationship_subject_code(
            memory_type=memory_type,
            explicit_subject_code=canonical_subject_code,
        )
        clean_content = content.strip()
        canonical = (
            canonicalize_memory_v1(
                memory_type=memory_type,
                subject=canonical_subject_code,
                content=clean_content,
            )
            if canonical_subject_code is not None
            else None
        )
        now = _now()
        with self._versioned.write_transaction():
            conflicts = self._memories.find_conflicts(clean_content, memory_type)
            memory_id = str(uuid.uuid4())
            self.primitive.insert_projection(
                memory_id=memory_id,
                content=clean_content,
                memory_type=memory_type,
                source=MemorySource.MANUAL,
                source_session_id=source_session_id,
                importance=importance,
                confidence=confidence,
                status=MemoryStatus.ACTIVE,
                metadata=metadata or {},
                created_at=now,
                updated_at=now,
            )
            self.primitive.insert_root(
                memory_id=memory_id,
                content=clean_content,
                memory_type=memory_type,
                importance=importance,
                confidence=confidence,
                source_kind=MemoryVersionSourceKind.MANUAL,
                source_session_id=source_session_id,
                source_session_reference_hash=self._session_reference(
                    source_session_id
                ),
                created_at=now,
                canonical_key_hash=(
                    canonical.canonical_key_hash if canonical is not None else None
                ),
                subject_key_hash=(
                    canonical.subject_key_hash if canonical is not None else None
                ),
                canonical_subject_code=canonical_subject_code,
            )
            self.primitive.record_conflict_audit(
                memory_id=memory_id,
                related_memory_ids=[conflict.id for conflict in conflicts],
                operation=MemoryAuditOperation.CREATE,
                created_at=now,
            )
            memory = self._memories.require(memory_id)
        self._notify_relationship_change_for_memory(memory_id)
        return memory, conflicts

    def update(
        self,
        memory_id: str,
        *,
        content: str | None,
        memory_type: MemoryType | None,
        importance: int | None,
        confidence: float | None,
        metadata: dict[str, Any] | None,
        canonical_subject_code: str | None = None,
        canonical_subject_code_provided: bool = False,
    ) -> tuple[Memory, list[Memory]]:
        with self._versioned.write_transaction():
            current = self._memories.require(memory_id)
            if current.status not in {MemoryStatus.ACTIVE, MemoryStatus.ARCHIVED}:
                raise ValueError("only formal memory can be updated")
            state = self._versioned.bootstrap_legacy(
                memory_id,
                source_references=self._source_references,
            )
            if state.state is MemoryRecordState.CONFLICTED:
                raise MemoryConflictRequiresResolutionError()
            if state.state is MemoryRecordState.DELETED:
                raise ValueError("deleted memory cannot be updated")
            current_version = self._versioned.get_current_version(memory_id)
            if current_version is None or state.current_version_id is None:
                raise RuntimeError("memory current version is unavailable")
            next_content = current.content if content is None else content.strip()
            next_type = current.memory_type if memory_type is None else memory_type
            next_subject_code = (
                canonical_subject_code
                if canonical_subject_code_provided
                else current_version.canonical_subject_code
            )
            next_subject_code = canonical_relationship_subject_code(
                memory_type=next_type,
                explicit_subject_code=next_subject_code,
            )
            next_canonical = (
                canonicalize_memory_v1(
                    memory_type=next_type,
                    subject=next_subject_code,
                    content=next_content,
                )
                if next_subject_code is not None
                else None
            )
            next_importance = current.importance if importance is None else importance
            next_confidence = current.confidence if confidence is None else confidence
            next_metadata = current.metadata if metadata is None else metadata
            conflicts = self._memories.find_conflicts(
                next_content,
                next_type,
                exclude_id=memory_id,
            )
            now = _now()
            next_version_id = self.primitive.insert_successor(
                memory_id=memory_id,
                parent_version_id=current_version.id,
                version_number=state.head_version + 1,
                operation=MemoryVersionOperation.USER_EDIT,
                content=next_content,
                memory_type=next_type,
                importance=next_importance,
                confidence=next_confidence,
                source_kind=MemoryVersionSourceKind.USER_EDIT,
                source_session_id=current.source_session_id,
                source_session_reference_hash=self._session_reference(
                    current.source_session_id
                ),
                created_at=now,
                canonical_key_hash=(
                    next_canonical.canonical_key_hash
                    if next_canonical is not None
                    else None
                ),
                subject_key_hash=(
                    next_canonical.subject_key_hash
                    if next_canonical is not None
                    else None
                ),
                canonical_subject_code=next_subject_code,
            )
            self.primitive.update_projection(
                memory_id=memory_id,
                content=next_content,
                memory_type=next_type,
                importance=next_importance,
                confidence=next_confidence,
                status=current.status,
                metadata=next_metadata,
                updated_at=now,
            )
            if not self.primitive.compare_and_set_head(
                memory_id=memory_id,
                expected_current_version_id=current_version.id,
                expected_head_version=state.head_version,
                expected_record_generation=state.record_generation,
                next_state=state.state,
                next_current_version_id=next_version_id,
                next_head_version=state.head_version + 1,
                next_source_kind=MemoryVersionSourceKind.USER_EDIT,
                updated_at=now,
                canonical_key_hash=(
                    next_canonical.canonical_key_hash
                    if next_canonical is not None
                    else None
                ),
                subject_key_hash=(
                    next_canonical.subject_key_hash
                    if next_canonical is not None
                    else None
                ),
            ):
                raise RuntimeError("stale memory head")
            self.primitive.record_conflict_audit(
                memory_id=memory_id,
                related_memory_ids=[conflict.id for conflict in conflicts],
                operation=MemoryAuditOperation.UPDATE,
                created_at=now,
            )
            memory = self._memories.require(memory_id)
        self._notify_relationship_change_for_memory(memory_id)
        return memory, conflicts

    def confirm_candidate(
        self,
        memory_id: str,
        *,
        canonical_subject_code: str | None = None,
    ) -> tuple[Memory, list[Memory]]:
        with self._versioned.write_transaction():
            current = self._memories.require(memory_id)
            if current.metadata.get("forgotten") is True:
                raise MemoryCandidateForgottenError()
            if current.status is not MemoryStatus.PENDING:
                raise ValueError("only pending memory candidates can be confirmed")
            canonical_subject_code = canonical_relationship_subject_code(
                memory_type=current.memory_type,
                explicit_subject_code=canonical_subject_code,
            )
            canonical = (
                canonicalize_memory_v1(
                    memory_type=current.memory_type,
                    subject=canonical_subject_code,
                    content=current.content,
                )
                if canonical_subject_code is not None
                else None
            )
            conflicts = self._memories.find_conflicts(
                current.content,
                current.memory_type,
                exclude_id=memory_id,
                statuses=(MemoryStatus.ACTIVE,),
            )
            if conflicts:
                now = _now()
                self.primitive.record_conflict_audit(
                    memory_id=memory_id,
                    related_memory_ids=[conflict.id for conflict in conflicts],
                    operation=MemoryAuditOperation.CONFIRM_CANDIDATE,
                    created_at=now,
                )
                result = (current, conflicts)
            else:
                now = _now()
                next_metadata = dict(current.metadata)
                next_metadata["confirmed_at"] = now.isoformat()
                self.primitive.update_projection(
                    memory_id=memory_id,
                    content=current.content,
                    memory_type=current.memory_type,
                    importance=current.importance,
                    confidence=current.confidence,
                    status=MemoryStatus.ACTIVE,
                    metadata=next_metadata,
                    updated_at=now,
                )
                self.primitive.insert_root(
                    memory_id=memory_id,
                    content=current.content,
                    memory_type=current.memory_type,
                    importance=current.importance,
                    confidence=current.confidence,
                    source_kind=MemoryVersionSourceKind.CANDIDATE,
                    source_session_id=current.source_session_id,
                    source_session_reference_hash=self._session_reference(
                        current.source_session_id
                    ),
                    created_at=now,
                    canonical_key_hash=(
                        canonical.canonical_key_hash if canonical is not None else None
                    ),
                    subject_key_hash=(
                        canonical.subject_key_hash if canonical is not None else None
                    ),
                    canonical_subject_code=canonical_subject_code,
                )
                memory = self._memories.require(memory_id)
                result = (memory, [])
        # Post-commit notification; the conflicts branch also schedules so the
        # projection is recomputed against the now-conflicted candidate.
        self._notify_relationship_change_for_memory(memory_id)
        return result

    def archive(self, memory_id: str) -> bool:
        with self._versioned.write_transaction():
            current = self._memories.require(memory_id)
            state = self._versioned.bootstrap_legacy(
                memory_id,
                source_references=self._source_references,
            )
            if state.state is MemoryRecordState.CONFLICTED or self._connection.execute(
                "SELECT 1 FROM memory_conflicts WHERE status = 'open' "
                "AND ? IN (left_memory_id, right_memory_id) LIMIT 1",
                (memory_id,),
            ).fetchone() is not None:
                raise MemoryConflictRequiresResolutionError()
            if state.state is MemoryRecordState.DELETED:
                raise ValueError("deleted memory cannot be archived")
            if state.state is MemoryRecordState.ARCHIVED:
                self.primitive.delete_embedding(memory_id)
                return True
            current_version = self._versioned.get_current_version(memory_id)
            if current_version is None or state.current_version_id is None:
                raise RuntimeError("memory current version is unavailable")
            now = _now()
            next_version_id = self.primitive.insert_successor(
                memory_id=memory_id,
                parent_version_id=current_version.id,
                version_number=state.head_version + 1,
                operation=MemoryVersionOperation.ARCHIVE,
                content=current.content,
                memory_type=current.memory_type,
                importance=current.importance,
                confidence=current.confidence,
                source_kind=MemoryVersionSourceKind.USER_EDIT,
                source_session_id=current.source_session_id,
                source_session_reference_hash=self._session_reference(
                    current.source_session_id
                ),
                created_at=now,
                canonical_key_hash=current_version.canonical_key_hash,
                subject_key_hash=current_version.subject_key_hash,
                canonical_subject_code=current_version.canonical_subject_code,
            )
            self.primitive.update_projection(
                memory_id=memory_id,
                content=current.content,
                memory_type=current.memory_type,
                importance=current.importance,
                confidence=current.confidence,
                status=MemoryStatus.ARCHIVED,
                metadata=current.metadata,
                updated_at=now,
            )
            if not self.primitive.compare_and_set_head(
                memory_id=memory_id,
                expected_current_version_id=current_version.id,
                expected_head_version=state.head_version,
                expected_record_generation=state.record_generation,
                next_state=MemoryRecordState.ARCHIVED,
                next_current_version_id=next_version_id,
                next_head_version=state.head_version + 1,
                next_source_kind=MemoryVersionSourceKind.USER_EDIT,
                updated_at=now,
                canonical_key_hash=current_version.canonical_key_hash,
                subject_key_hash=current_version.subject_key_hash,
            ):
                raise RuntimeError("stale memory head")
            self.primitive.delete_embedding(memory_id)
        self._notify_relationship_change_for_memory(memory_id)
        return True

    def _session_reference(self, session_id: str | None) -> str | None:
        if session_id is None:
            return None
        if self._source_references is None:
            raise ValueError("memory source reference service is required")
        return self._source_references.session_hash(session_id)
