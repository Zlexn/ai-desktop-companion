from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import sqlite3
import uuid

from app.core.errors import (
    MemoryConflictRequiresResolutionError,
    MemoryConflictStaleError,
    MemoryNoUndoableAutoOperationError,
    NotFoundError,
    ValidationAppError,
)
from app.domain.models import (
    Memory,
    MemoryAuditEventType,
    MemoryAuditOperation,
    MemoryConflict,
    MemoryConflictResolutionKind,
    MemoryConflictStatus,
    MemoryRecordState,
    MemorySource,
    MemoryStatus,
    MemoryType,
    MemoryVersionOperation,
    MemoryVersionSourceKind,
)
from app.repositories.memories import MemoryRepository
from app.repositories.relationship_ledger import RelationshipLedgerRepository
from app.repositories.sqlite import metadata_to_json
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.services.memory_commit_policy import canonicalize_memory_v1
from app.services.memory_forget_service import MemoryForgetService
from app.services.memory_governor import memory_payload_policy_reason
from app.services.memory_source_reference import MemorySourceReferenceService
from app.services.relationship_contract import canonical_relationship_subject_code
from app.services.relationship_hooks import (
    NoOpRelationshipChangeNotifier,
    RelationshipChangeNotifier,
)
from app.services.versioned_memory_mutation import VersionedMemoryMutationPrimitive


@dataclass(frozen=True)
class ConflictResolutionPayload:
    kind: MemoryConflictResolutionKind
    content: str | None = None
    memory_type: MemoryType | None = None
    subject: str | None = None
    importance: int = 3
    confidence: float = 1.0
    canonical_subject_code: str | None = None


@dataclass(frozen=True)
class ConflictResolutionResult:
    conflict: MemoryConflict
    resolved_memory: Memory | None


@dataclass(frozen=True)
class MemoryUndoResult:
    memory_id: str
    action: str
    memory: Memory | None


class MemoryConflictResolutionService:
    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        versioned: VersionedMemoryRepository,
        memories: MemoryRepository,
        forget: MemoryForgetService,
        source_references: MemorySourceReferenceService,
        fault_injector: Callable[[str], None] | None = None,
        relationship_notifier: RelationshipChangeNotifier | None = None,
    ) -> None:
        self._connection = connection
        self._versioned = versioned
        self._memories = memories
        self._forget = forget
        self._source_references = source_references
        self._primitive = VersionedMemoryMutationPrimitive(connection)
        self._fault_injector = fault_injector
        self._relationship_notifier = (
            relationship_notifier or NoOpRelationshipChangeNotifier()
        )

    def _notify_relationship_change(self, memory_ids: tuple[str, ...]) -> None:
        """Best-effort post-commit notification; never raises into callers."""
        try:
            self._relationship_notifier.schedule(memory_ids)
        except Exception:
            # Notification is best-effort; startup recovery guarantees convergence.
            pass

    def resolve(
        self,
        conflict_id: str,
        payload: ConflictResolutionPayload,
    ) -> ConflictResolutionResult:
        if payload.kind not in {
            MemoryConflictResolutionKind.CHOOSE_LEFT,
            MemoryConflictResolutionKind.CHOOSE_RIGHT,
            MemoryConflictResolutionKind.REPLACE_BOTH,
            MemoryConflictResolutionKind.BOTH_CONTEXTUAL,
            MemoryConflictResolutionKind.DISMISS_BOTH,
        }:
            raise ValidationAppError("不支持该冲突解决方式。")
        now = datetime.now(UTC)
        with self._versioned.write_transaction():
            row = self._require_open_conflict_row(conflict_id)
            left_id = str(row["left_memory_id"])
            right_id = str(row["right_memory_id"])
            left = self._require_conflicted_side(left_id)
            right = self._require_conflicted_side(right_id)
            resolved_memory_id = None
            selected_version_id = None
            if payload.kind is not MemoryConflictResolutionKind.DISMISS_BOTH:
                if payload.kind is MemoryConflictResolutionKind.CHOOSE_LEFT:
                    selected_id = left_id
                    selected = left
                    selected_version = self._versioned.get_current_version(selected_id)
                    assert selected_version is not None
                    selected_version_id = selected_version.id
                    content = selected[0].content
                    memory_type = selected[0].memory_type
                    subject = selected_version.subject or selected[0].content[:200]
                    importance = selected[0].importance
                    confidence = selected[0].confidence
                    canonical_subject_code = selected_version.canonical_subject_code
                elif payload.kind is MemoryConflictResolutionKind.CHOOSE_RIGHT:
                    selected_id = right_id
                    selected = right
                    selected_version = self._versioned.get_current_version(selected_id)
                    assert selected_version is not None
                    selected_version_id = selected_version.id
                    content = selected[0].content
                    memory_type = selected[0].memory_type
                    subject = selected_version.subject or selected[0].content[:200]
                    importance = selected[0].importance
                    confidence = selected[0].confidence
                    canonical_subject_code = selected_version.canonical_subject_code
                else:
                    (
                        content,
                        memory_type,
                        subject,
                        importance,
                        confidence,
                        canonical_subject_code,
                    ) = self._validated_replacement(payload)
                resolved_memory_id = self._create_resolved_identity(
                    content=content,
                    memory_type=memory_type,
                    subject=subject,
                    importance=importance,
                    confidence=confidence,
                    canonical_subject_code=canonical_subject_code,
                    now=now,
                )
                self._checkpoint("resolved_identity")
            self._archive_side(left, now=now)
            self._checkpoint("left_archived")
            self._archive_side(right, now=now)
            self._checkpoint("right_archived")
            cursor = self._connection.execute(
                """
                UPDATE memory_conflicts
                SET status = 'resolved', resolution_kind = ?,
                    resolved_memory_id = ?, resolved_at = ?
                WHERE conflict_id = ? AND status = 'open'
                """,
                (
                    payload.kind.value,
                    resolved_memory_id,
                    now.isoformat(),
                    conflict_id,
                ),
            )
            if cursor.rowcount != 1:
                raise MemoryConflictStaleError()
            self._checkpoint("conflict_closed")
            if resolved_memory_id is not None:
                RelationshipLedgerRepository(self._connection).append_conflict_lineage(
                    resolved_memory_id=resolved_memory_id,
                    contributing_memory_ids=(left_id, right_id),
                    conflict_id=conflict_id,
                    resolution_kind=payload.kind,
                )
                self._checkpoint("lineage")
            audit_memory_id = resolved_memory_id or left_id
            self._insert_audit(
                event_type=MemoryAuditEventType.CONFLICT_RESOLVED,
                memory_id=audit_memory_id,
                related_memory_ids=[left_id, right_id],
                operation=MemoryAuditOperation.RESOLVE_CONFLICT,
                metadata={
                    "resolution_kind": payload.kind.value,
                    "conflict_id": conflict_id,
                    "selected_version_id": selected_version_id,
                },
                now=now,
            )
            self._checkpoint("audit")
            conflict = self._conflict_by_id(conflict_id)
            resolved = (
                self._memories.require(resolved_memory_id)
                if resolved_memory_id is not None
                else None
            )
            result = ConflictResolutionResult(
                conflict=conflict,
                resolved_memory=resolved,
            )
        # Post-commit notification: schedule both old sides and the resolved
        # identity (when created) for relationship reconciliation. dismiss_both
        # schedules only the archived sides so their old applies get revoked.
        affected: list[str] = [left_id, right_id]
        if resolved_memory_id is not None:
            affected.append(resolved_memory_id)
        self._notify_relationship_change(tuple(dict.fromkeys(affected)))
        return result

    def undo_latest_auto(self, memory_id: str) -> MemoryUndoResult:
        self._memories.require(memory_id)
        open_conflict = self._connection.execute(
            "SELECT 1 FROM memory_conflicts WHERE status = 'open' "
            "AND ? IN (left_memory_id, right_memory_id)",
            (memory_id,),
        ).fetchone()
        if open_conflict is not None:
            raise MemoryConflictRequiresResolutionError()
        latest = self._connection.execute(
            """
            SELECT * FROM memory_write_activities
            WHERE memory_id = ? AND outcome IN (
                'committed_create', 'committed_supersede', 'committed_support'
            )
            ORDER BY created_at DESC, op_id DESC LIMIT 1
            """,
            (memory_id,),
        ).fetchone()
        if latest is None:
            raise MemoryNoUndoableAutoOperationError()
        if self._activity_already_undone(str(latest["op_id"])):
            raise MemoryNoUndoableAutoOperationError()
        outcome = str(latest["outcome"])
        if outcome == "committed_create":
            return self._undo_create(memory_id, latest)
        if outcome == "committed_support":
            return self._undo_support(memory_id, latest)
        return self._undo_supersede(memory_id, latest)

    def _undo_create(self, memory_id: str, activity: sqlite3.Row) -> MemoryUndoResult:
        now = datetime.now(UTC)
        with self._versioned.write_transaction():
            if self._activity_already_undone(str(activity["op_id"])):
                raise MemoryNoUndoableAutoOperationError()
            state = self._versioned.get_state(memory_id)
            head = self._versioned.get_current_version(memory_id)
            if (
                state is None
                or head is None
                or state.state is not MemoryRecordState.ACTIVE
                or state.current_version_id != activity["result_version_id"]
                or head.id != activity["result_version_id"]
                or head.operation is not MemoryVersionOperation.CREATE
                or head.source_kind is not MemoryVersionSourceKind.AUTOMATIC
                or head.parent_version_id is not None
            ):
                raise MemoryConflictStaleError()
            self._forget.forget_memory(memory_id)
            self._insert_audit(
                event_type=MemoryAuditEventType.AUTO_CHANGE_UNDONE,
                memory_id=memory_id,
                related_memory_ids=[],
                operation=MemoryAuditOperation.UNDO_AUTO,
                metadata={
                    "action": "forgotten_create",
                    "auto_op_id": str(activity["op_id"]),
                },
                now=now,
            )
            return MemoryUndoResult(memory_id, "forgotten_create", None)

    def _undo_support(self, memory_id: str, activity: sqlite3.Row) -> MemoryUndoResult:
        now = datetime.now(UTC)
        with self._versioned.write_transaction():
            if self._activity_already_undone(str(activity["op_id"])):
                raise MemoryNoUndoableAutoOperationError()
            evidence = self._connection.execute(
                """
                SELECT evidence.* FROM memory_evidence AS evidence
                WHERE evidence.memory_id = ?
                  AND evidence.memory_version_id = ?
                  AND evidence.source_message_reference_hash = ?
                  AND evidence.extractor_kind = ?
                  AND COALESCE(evidence.extractor_provider, '') = COALESCE(?, '')
                  AND COALESCE(evidence.extractor_model, '') = COALESCE(?, '')
                  AND evidence.extractor_kind IN ('local', 'fake', 'remote')
                  AND NOT EXISTS (
                      SELECT 1 FROM memory_evidence_retractions AS retraction
                      WHERE retraction.evidence_id = evidence.evidence_id
                  )
                ORDER BY evidence.created_at DESC, evidence.evidence_id DESC
                LIMIT 1
                """,
                (
                    memory_id,
                    activity["result_version_id"],
                    self._activity_source_message_reference_hash(activity),
                    activity["extractor_kind"],
                    activity["provider_identifier"],
                    activity["model_identifier"],
                ),
            ).fetchone()
            if evidence is None:
                raise MemoryNoUndoableAutoOperationError()
            state = self._versioned.get_state(memory_id)
            if (
                state is None
                or state.current_version_id != activity["result_version_id"]
                or not self._primitive.touch_head(
                    memory_id=memory_id,
                    expected_current_version_id=str(state.current_version_id),
                    expected_head_version=state.head_version,
                    expected_record_generation=state.record_generation,
                    updated_at=now,
                )
            ):
                raise MemoryConflictStaleError()
            self._connection.execute(
                "INSERT INTO memory_evidence_retractions "
                "(evidence_id, reason_code, created_at) VALUES (?, ?, ?)",
                (
                    str(evidence["evidence_id"]),
                    "user_undo_auto_support",
                    now.isoformat(),
                ),
            )
            self._insert_audit(
                event_type=MemoryAuditEventType.AUTO_CHANGE_UNDONE,
                memory_id=memory_id,
                related_memory_ids=[],
                operation=MemoryAuditOperation.UNDO_AUTO,
                metadata={
                    "action": "retracted_support",
                    "auto_op_id": str(activity["op_id"]),
                },
                now=now,
            )
            return MemoryUndoResult(
                memory_id,
                "retracted_support",
                self._memories.require(memory_id),
            )

    def _undo_supersede(
        self,
        memory_id: str,
        activity: sqlite3.Row,
    ) -> MemoryUndoResult:
        now = datetime.now(UTC)
        with self._versioned.write_transaction():
            if self._activity_already_undone(str(activity["op_id"])):
                raise MemoryNoUndoableAutoOperationError()
            state = self._versioned.get_state(memory_id)
            head = self._versioned.get_current_version(memory_id)
            if (
                state is None
                or head is None
                or head.id != activity["result_version_id"]
                or head.operation is not MemoryVersionOperation.AUTO_SUPERSEDE
                or head.parent_version_id is None
            ):
                raise MemoryConflictStaleError()
            previous = self._connection.execute(
                "SELECT * FROM memory_versions WHERE id = ? AND memory_id = ?",
                (head.parent_version_id, memory_id),
            ).fetchone()
            if previous is None or previous["content"] is None or previous["redacted_at"] is not None:
                raise MemoryNoUndoableAutoOperationError()
            next_version_id = self._primitive.insert_successor(
                memory_id=memory_id,
                parent_version_id=head.id,
                version_number=state.head_version + 1,
                operation=MemoryVersionOperation.USER_REVERT,
                content=str(previous["content"]),
                memory_type=MemoryType(str(previous["memory_type"])),
                importance=int(previous["importance"]),
                confidence=float(previous["confidence"]),
                source_kind=MemoryVersionSourceKind.USER_REVERT,
                source_session_id=previous["source_session_id"],
                source_session_reference_hash=previous["source_session_reference_hash"],
                created_at=now,
                subject=previous["subject"],
                canonical_key_hash=previous["canonical_key_hash"],
                subject_key_hash=previous["subject_key_hash"],
                canonical_subject_code=previous["canonical_subject_code"],
            )
            if not self._primitive.compare_and_set_head(
                memory_id=memory_id,
                expected_current_version_id=head.id,
                expected_head_version=state.head_version,
                expected_record_generation=state.record_generation,
                next_state=MemoryRecordState.ACTIVE,
                next_current_version_id=next_version_id,
                next_head_version=state.head_version + 1,
                next_source_kind=MemoryVersionSourceKind.USER_REVERT,
                updated_at=now,
                canonical_key_hash=previous["canonical_key_hash"],
                subject_key_hash=previous["subject_key_hash"],
            ):
                raise MemoryConflictStaleError()
            current = self._memories.require(memory_id)
            self._primitive.update_projection(
                memory_id=memory_id,
                content=str(previous["content"]),
                memory_type=MemoryType(str(previous["memory_type"])),
                importance=int(previous["importance"]),
                confidence=float(previous["confidence"]),
                status=MemoryStatus.ACTIVE,
                metadata=current.metadata,
                updated_at=now,
            )
            if head.canonical_key_hash is not None or head.subject_key_hash is not None:
                generation = self._memory_type_generation(head.memory_type, now=now)
                self._primitive.insert_tombstone(
                    source_memory_id=memory_id,
                    memory_type=head.memory_type,
                    canonical_key_hash=head.canonical_key_hash,
                    subject_key_hash=head.subject_key_hash,
                    canonicalization_version=head.canonicalization_version,
                    delete_generation=generation,
                    reason_code="user_undo_auto_supersede",
                    created_at=now,
                )
            self._insert_audit(
                event_type=MemoryAuditEventType.AUTO_CHANGE_UNDONE,
                memory_id=memory_id,
                related_memory_ids=[],
                operation=MemoryAuditOperation.UNDO_AUTO,
                metadata={
                    "action": "reverted_supersede",
                    "auto_op_id": str(activity["op_id"]),
                },
                now=now,
            )
            return MemoryUndoResult(
                memory_id,
                "reverted_supersede",
                self._memories.require(memory_id),
            )

    def _activity_source_message_reference_hash(self, activity: sqlite3.Row) -> str:
        row = self._connection.execute(
            "SELECT source_user_message_reference_hash, user_message_id "
            "FROM memory_jobs WHERE id = ?",
            (str(activity["job_id"]),),
        ).fetchone()
        if row is None:
            raise MemoryNoUndoableAutoOperationError()
        if row["source_user_message_reference_hash"] is not None:
            return str(row["source_user_message_reference_hash"])
        if row["user_message_id"] is not None:
            return self._source_references.message_hash(str(row["user_message_id"]))
        raise MemoryNoUndoableAutoOperationError()

    def _activity_already_undone(self, operation_id: str) -> bool:
        rows = self._connection.execute(
            "SELECT metadata_json FROM memory_audit_events "
            "WHERE event_type = ? AND operation = ?",
            (
                MemoryAuditEventType.AUTO_CHANGE_UNDONE.value,
                MemoryAuditOperation.UNDO_AUTO.value,
            ),
        ).fetchall()
        for row in rows:
            try:
                metadata = json.loads(str(row["metadata_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(metadata, dict) and metadata.get("auto_op_id") == operation_id:
                return True
        return False

    def _create_resolved_identity(
        self,
        *,
        content: str,
        memory_type: MemoryType,
        subject: str,
        importance: int,
        confidence: float,
        canonical_subject_code: str | None,
        now: datetime,
    ) -> str:
        canonical = canonicalize_memory_v1(
            memory_type=memory_type,
            subject=canonical_subject_code or subject,
            content=content,
        )
        memory_id = str(uuid.uuid4())
        self._primitive.insert_projection(
            memory_id=memory_id,
            content=content,
            memory_type=memory_type,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=importance,
            confidence=confidence,
            status=MemoryStatus.ACTIVE,
            metadata={},
            created_at=now,
            updated_at=now,
        )
        self._primitive.insert_root(
            memory_id=memory_id,
            content=content,
            memory_type=memory_type,
            importance=importance,
            confidence=confidence,
            source_kind=MemoryVersionSourceKind.USER_EDIT,
            source_session_id=None,
            source_session_reference_hash=None,
            created_at=now,
            operation=MemoryVersionOperation.CONFLICT_RESOLUTION,
            subject=subject,
            canonical_key_hash=canonical.canonical_key_hash,
            subject_key_hash=canonical.subject_key_hash,
            canonical_subject_code=canonical_subject_code,
        )
        return memory_id

    def _archive_side(self, side, *, now: datetime) -> None:
        memory, state, head = side
        next_id = self._primitive.insert_successor(
            memory_id=memory.id,
            parent_version_id=head.id,
            version_number=state.head_version + 1,
            operation=MemoryVersionOperation.ARCHIVE,
            content=memory.content,
            memory_type=memory.memory_type,
            importance=memory.importance,
            confidence=memory.confidence,
            source_kind=MemoryVersionSourceKind.USER_EDIT,
            source_session_id=head.source_session_id,
            source_session_reference_hash=head.source_session_reference_hash,
            created_at=now,
            subject=head.subject,
            canonical_key_hash=head.canonical_key_hash,
            subject_key_hash=head.subject_key_hash,
            canonical_subject_code=head.canonical_subject_code,
        )
        if not self._primitive.compare_and_set_head(
            memory_id=memory.id,
            expected_current_version_id=head.id,
            expected_head_version=state.head_version,
            expected_record_generation=state.record_generation,
            next_state=MemoryRecordState.ARCHIVED,
            next_current_version_id=next_id,
            next_head_version=state.head_version + 1,
            next_source_kind=MemoryVersionSourceKind.USER_EDIT,
            updated_at=now,
            canonical_key_hash=head.canonical_key_hash,
            subject_key_hash=head.subject_key_hash,
        ):
            raise MemoryConflictStaleError()
        self._primitive.update_projection(
            memory_id=memory.id,
            content=memory.content,
            memory_type=memory.memory_type,
            importance=memory.importance,
            confidence=memory.confidence,
            status=MemoryStatus.ARCHIVED,
            metadata=memory.metadata,
            updated_at=now,
        )
        self._primitive.delete_embedding(memory.id)

    def _require_conflicted_side(self, memory_id: str):
        memory = self._memories.require(memory_id)
        state = self._versioned.get_state(memory_id)
        head = self._versioned.get_current_version(memory_id)
        if (
            state is None
            or head is None
            or memory.status is not MemoryStatus.ACTIVE
            or state.state not in {MemoryRecordState.ACTIVE, MemoryRecordState.CONFLICTED}
            or state.current_version_id != head.id
        ):
            raise MemoryConflictStaleError()
        return memory, state, head

    def _require_open_conflict_row(self, conflict_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM memory_conflicts WHERE conflict_id = ?",
            (conflict_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError("冲突不存在。")
        if str(row["status"]) != "open":
            raise MemoryConflictStaleError()
        return row

    def _validated_replacement(self, payload: ConflictResolutionPayload):
        if payload.content is None or payload.memory_type is None or payload.subject is None:
            raise ValidationAppError("替换式解决需要完整记忆内容。")
        content = payload.content.strip()
        subject = payload.subject.strip()
        if not content or not subject:
            raise ValidationAppError("记忆内容和主题不能为空。")
        if memory_payload_policy_reason(content, subject) is not None:
            raise ValidationAppError("记忆内容包含不允许持久化的敏感凭据。")
        if payload.kind is MemoryConflictResolutionKind.BOTH_CONTEXTUAL:
            markers = ("时", "期间", "曾经", "现在", "在", "情况下", "场景", "语境")
            if not any(marker in content or marker in subject for marker in markers):
                raise ValidationAppError("语境化解决必须明确区分时间或语境。")
        canonical_relationship_subject_code(
            memory_type=payload.memory_type,
            explicit_subject_code=payload.canonical_subject_code,
        )
        canonicalize_memory_v1(
            memory_type=payload.memory_type,
            subject=subject,
            content=content,
        )
        return (
            content,
            payload.memory_type,
            subject,
            payload.importance,
            payload.confidence,
            payload.canonical_subject_code,
        )

    def _memory_type_generation(self, memory_type: MemoryType, *, now: datetime) -> int:
        row = self._connection.execute(
            """
            INSERT INTO memory_deletion_generations (
                scope, scope_id, generation, updated_at
            ) VALUES ('memory_type', ?, 1, ?)
            ON CONFLICT(scope, scope_id) DO UPDATE SET
                generation = generation + 1, updated_at = excluded.updated_at
            RETURNING generation
            """,
            (memory_type.value, now.isoformat()),
        ).fetchone()
        assert row is not None
        return int(row["generation"])

    def _insert_audit(
        self,
        *,
        event_type: MemoryAuditEventType,
        memory_id: str,
        related_memory_ids: list[str],
        operation: MemoryAuditOperation,
        metadata: dict[str, object],
        now: datetime,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO memory_audit_events (
                id, event_type, memory_id, related_memory_ids_json,
                operation, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                event_type.value,
                memory_id,
                json.dumps(related_memory_ids, ensure_ascii=False),
                operation.value,
                metadata_to_json(metadata),
                now.isoformat(),
            ),
        )

    def _conflict_by_id(self, conflict_id: str) -> MemoryConflict:
        row = self._connection.execute(
            "SELECT * FROM memory_conflicts WHERE conflict_id = ?",
            (conflict_id,),
        ).fetchone()
        assert row is not None
        return MemoryConflict(
            id=str(row["conflict_id"]),
            left_memory_id=str(row["left_memory_id"]),
            right_memory_id=str(row["right_memory_id"]),
            status=MemoryConflictStatus(str(row["status"])),
            resolution_kind=(
                MemoryConflictResolutionKind(str(row["resolution_kind"]))
                if row["resolution_kind"] is not None
                else None
            ),
            resolved_memory_id=row["resolved_memory_id"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
            resolved_at=(
                datetime.fromisoformat(str(row["resolved_at"]))
                if row["resolved_at"] is not None
                else None
            ),
        )

    def _checkpoint(self, name: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(name)
