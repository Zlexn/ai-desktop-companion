from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import sqlite3

from app.domain.models import (
    MemoryConflictResolutionKind,
    MemoryDeletionScope,
    MemoryRecordState,
    MemoryType,
    MemoryVersionSourceKind,
)
from app.repositories.memory_audit import MemoryAuditRepository
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.services.memory_commit_policy import canonicalize_memory_v1
from app.services.memory_gate_b_contract import MEMORY_CANONICALIZATION_VERSION
from app.services.versioned_memory_mutation import VersionedMemoryMutationPrimitive
from app.services.memory_source_reference import MemorySourceReferenceService
from app.services.summary_invalidation import SummaryInvalidationPrimitive


_DELETED_METADATA_REASON = "memory_true_forget"


@dataclass(frozen=True)
class MemoryForgetResult:
    scope: MemoryDeletionScope
    scope_id: str | None
    forgotten_memory_ids: tuple[str, ...]
    forgotten_candidate_ids: tuple[str, ...]
    deletion_generation: int
    summary_barrier_generation: int


class MemoryForgetService:
    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        versioned: VersionedMemoryRepository,
        source_references: MemorySourceReferenceService,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self._connection = connection
        self._versioned = versioned
        self._source_references = source_references
        self._primitive = VersionedMemoryMutationPrimitive(connection)
        self._audits = MemoryAuditRepository(connection)
        self._fault_injector = fault_injector

    def forget_memory(self, memory_id: str) -> MemoryForgetResult:
        if not isinstance(memory_id, str) or not memory_id:
            raise ValueError("memory_id must be a non-empty string")
        return self._forget(
            scope=MemoryDeletionScope.MEMORY,
            scope_id=memory_id,
            memory_type=None,
            session_id=None,
        )

    def forget_scope(
        self,
        *,
        scope: MemoryDeletionScope,
        scope_id: str | None = None,
    ) -> MemoryForgetResult:
        if scope is MemoryDeletionScope.MEMORY:
            if scope_id is None:
                raise ValueError("memory scope requires scope_id")
            return self.forget_memory(scope_id)
        memory_type = None
        session_id = None
        if scope is MemoryDeletionScope.MEMORY_TYPE:
            if scope_id is None:
                raise ValueError("memory_type scope requires scope_id")
            memory_type = MemoryType(scope_id)
        elif scope is MemoryDeletionScope.SESSION:
            if not scope_id:
                raise ValueError("session scope requires scope_id")
            session_id = scope_id
        elif scope is MemoryDeletionScope.ALL:
            if scope_id is not None:
                raise ValueError("all scope forbids scope_id")
        else:
            raise ValueError("unsupported forget scope")
        return self._forget(
            scope=scope,
            scope_id=scope_id,
            memory_type=memory_type,
            session_id=session_id,
        )

    def _forget(
        self,
        *,
        scope: MemoryDeletionScope,
        scope_id: str | None,
        memory_type: MemoryType | None,
        session_id: str | None,
    ) -> MemoryForgetResult:
        session_hash = (
            self._source_references.session_hash(session_id)
            if session_id is not None
            else None
        )
        now = datetime.now(UTC)
        with self._versioned.write_transaction():
            formal_ids = self._versioned.list_forget_formal_ids(
                memory_id=scope_id if scope is MemoryDeletionScope.MEMORY else None,
                memory_type=memory_type,
                session_id=session_id,
                session_reference_hash=session_hash,
            )
            candidate_ids = self._versioned.list_forget_candidate_ids(
                memory_id=scope_id if scope is MemoryDeletionScope.MEMORY else None,
                memory_type=memory_type,
                session_id=session_id,
                session_reference_hash=session_hash,
            )
            if scope is MemoryDeletionScope.MEMORY and not formal_ids and not candidate_ids:
                projection = self._versioned.get_forget_projection(str(scope_id))
                if projection is None:
                    raise ValueError("memory does not exist")
                if self._is_already_forgotten(str(scope_id), projection):
                    return self._already_forgotten_result(
                        scope=scope,
                        scope_id=scope_id,
                    )
                raise ValueError("memory is not eligible for forget")

            candidate_rows = self._versioned.list_forget_candidate_payloads(
                candidate_ids
            )
            generation = self._increment_generation(
                scope=scope,
                scope_id=scope_id,
                formal_ids=formal_ids,
                candidate_rows=candidate_rows,
                memory_type=memory_type,
                session_hash=session_hash,
                now=now,
            )
            self._checkpoint("generation")

            source_messages, source_sessions = self._versioned.list_forget_source_message_ids(
                formal_ids
            )
            conflict_rows = self._open_conflicts(formal_ids)
            forgetting = set(formal_ids)
            for memory_id in formal_ids:
                self._forget_formal_memory(
                    memory_id,
                    delete_generation=generation,
                    now=now,
                )
            self._checkpoint("formal_memories")

            for candidate in candidate_rows:
                self._tombstone_candidate(
                    candidate,
                    delete_generation=generation,
                    now=now,
                )
                self._primitive.redact_candidate(
                    str(candidate["id"]),
                    updated_at=now,
                )
                self._primitive.delete_embedding(str(candidate["id"]))
            self._checkpoint("candidates")

            self._audits.redact_for_memory_ids(forgetting)
            self._checkpoint("audits")
            self._resolve_conflicts(
                conflict_rows,
                forgetting=forgetting,
                now=now,
            )
            self._checkpoint("conflicts")

            excluded_messages = set(source_messages)
            if scope is MemoryDeletionScope.SESSION and session_id is not None:
                excluded_messages.update(
                    self._versioned.list_session_message_ids({session_id})
                )
            elif scope in {MemoryDeletionScope.MEMORY_TYPE, MemoryDeletionScope.ALL}:
                excluded_messages.update(
                    self._versioned.list_session_message_ids(source_sessions)
                )
            barrier = SummaryInvalidationPrimitive(
                self._connection,
                fault_injector=self._fault_injector,
            ).invalidate_for_true_forget(
                excluded_messages,
                now=now,
            )

            for memory_id in formal_ids:
                related = self._resolved_conflict_ids(conflict_rows, memory_id)
                self._audits.record_memory_deleted(
                    memory_id=memory_id,
                    related_memory_ids=related,
                    created_at=now,
                )
            self._checkpoint("delete_activity")

            return MemoryForgetResult(
                scope=scope,
                scope_id=scope_id,
                forgotten_memory_ids=tuple(formal_ids),
                forgotten_candidate_ids=tuple(candidate_ids),
                deletion_generation=generation,
                summary_barrier_generation=barrier,
            )

    def _tombstone_candidate(
        self,
        candidate: sqlite3.Row,
        *,
        delete_generation: int,
        now: datetime,
    ) -> None:
        content = str(candidate["content"])
        metadata = self._candidate_metadata(candidate["metadata_json"])
        subject = metadata.get("canonical_subject")
        if not isinstance(subject, str) or not subject.strip():
            subject = self._candidate_subject(
                content,
                MemoryType(str(candidate["memory_type"])),
            )
        if subject is None:
            content_hash = canonicalize_memory_v1(
                memory_type=MemoryType(str(candidate["memory_type"])),
                subject="candidate-content-only",
                content=content,
            ).content_key_hash
            self._primitive.insert_tombstone(
                source_memory_id=str(candidate["id"]),
                memory_type=MemoryType(str(candidate["memory_type"])),
                canonical_key_hash=None,
                subject_key_hash=None,
                content_key_hash=content_hash,
                canonicalization_version=MEMORY_CANONICALIZATION_VERSION,
                delete_generation=delete_generation,
                reason_code=_DELETED_METADATA_REASON,
                created_at=now,
            )
            self._checkpoint("tombstones")
            return
        canonical = canonicalize_memory_v1(
            memory_type=MemoryType(str(candidate["memory_type"])),
            subject=subject,
            content=content,
        )
        self._primitive.insert_tombstone(
            source_memory_id=str(candidate["id"]),
            memory_type=canonical.memory_type,
            canonical_key_hash=canonical.canonical_key_hash,
            subject_key_hash=canonical.subject_key_hash,
            content_key_hash=canonical.content_key_hash,
            canonicalization_version=MEMORY_CANONICALIZATION_VERSION,
            delete_generation=delete_generation,
            reason_code=_DELETED_METADATA_REASON,
            created_at=now,
        )
        self._checkpoint("tombstones")

    @staticmethod
    def _candidate_metadata(raw: object) -> dict[str, object]:
        try:
            value = json.loads(str(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _candidate_subject(content: str, memory_type: MemoryType) -> str | None:
        import re

        patterns = {
            MemoryType.USER_FACT: (
                (r"^用户住在.+?[。.]?$", "居住地"),
                (r"^用户(?:的)?职业是.+?[。.]?$", "职业"),
                (r"^用户(?:的)?名字是.+?[。.]?$", "姓名"),
                (r"^用户叫.+?[。.]?$", "姓名"),
            ),
            MemoryType.PREFERENCE: (
                (r"^用户喜欢.+?[。.]?$", "偏好"),
                (r"^用户不喜欢.+?[。.]?$", "不喜欢的事物"),
            ),
            MemoryType.LONG_TERM_GOAL: (
                (r"^用户(?:的目标是|正在准备).+?[。.]?$", "长期目标"),
                (r"^用户计划.+?[。.]?$", "计划"),
            ),
        }
        for pattern, subject in patterns.get(memory_type, ()):
            if re.fullmatch(pattern, content.strip()) is not None:
                return subject
        return None

    def _forget_formal_memory(
        self,
        memory_id: str,
        *,
        delete_generation: int,
        now: datetime,
    ) -> None:
        projection = self._versioned.get_forget_projection(memory_id)
        if projection is None:
            raise RuntimeError("memory projection is unavailable")
        state = self._versioned.bootstrap_legacy(
            memory_id,
            source_references=self._source_references,
        )
        if state.state is MemoryRecordState.DELETED:
            return
        head = self._versioned.get_current_version(memory_id)
        if head is None or state.current_version_id is None:
            raise RuntimeError("memory current version is unavailable")
        versions = self._versioned.list_unredacted_forget_versions(memory_id)
        for version in versions:
            canonical_hash = version["canonical_key_hash"]
            subject_hash = version["subject_key_hash"]
            if canonical_hash is None and subject_hash is None:
                continue
            self._primitive.insert_tombstone(
                source_memory_id=memory_id,
                memory_type=MemoryType(str(version["memory_type"])),
                canonical_key_hash=(
                    str(canonical_hash) if canonical_hash is not None else None
                ),
                subject_key_hash=(
                    str(subject_hash) if subject_hash is not None else None
                ),
                canonicalization_version=str(version["canonicalization_version"]),
                delete_generation=delete_generation,
                reason_code=_DELETED_METADATA_REASON,
                created_at=now,
            )
        self._checkpoint("tombstones")

        delete_version_id = self._primitive.insert_delete_head(
            memory_id=memory_id,
            parent_version_id=head.id,
            version_number=state.head_version + 1,
            memory_type=head.memory_type,
            content_hash=head.content_hash,
            canonical_key_hash=head.canonical_key_hash,
            subject_key_hash=head.subject_key_hash,
            canonicalization_version=head.canonicalization_version,
            confidence=head.confidence,
            importance=head.importance,
            source_kind=head.source_kind,
            source_session_id=head.source_session_id,
            source_session_reference_hash=head.source_session_reference_hash,
            created_at=now,
            canonical_subject_code=head.canonical_subject_code,
        )
        self._checkpoint("delete_head")
        if not self._primitive.compare_and_set_head(
            memory_id=memory_id,
            expected_current_version_id=head.id,
            expected_head_version=state.head_version,
            expected_record_generation=state.record_generation,
            next_state=MemoryRecordState.DELETED,
            next_current_version_id=delete_version_id,
            next_head_version=state.head_version + 1,
            next_source_kind=MemoryVersionSourceKind.USER_EDIT,
            updated_at=now,
        ):
            raise RuntimeError("stale memory head")
        self._checkpoint("state_head")
        self._primitive.redact_projection(memory_id, updated_at=now)
        self._checkpoint("projection")
        self._primitive.redact_versions(memory_id, redacted_at=now)
        self._checkpoint("versions")
        self._primitive.delete_embedding(memory_id)
        self._checkpoint("embedding")

    def _increment_generation(
        self,
        *,
        scope: MemoryDeletionScope,
        scope_id: str | None,
        formal_ids: list[str],
        candidate_rows: list[sqlite3.Row],
        memory_type: MemoryType | None,
        session_hash: str | None,
        now: datetime,
    ) -> int:
        if scope is MemoryDeletionScope.ALL:
            key = ("all", "*")
        elif scope is MemoryDeletionScope.MEMORY_TYPE:
            assert memory_type is not None
            key = ("memory_type", memory_type.value)
        elif scope is MemoryDeletionScope.SESSION:
            assert session_hash is not None
            key = ("session", session_hash)
        else:
            projection = (
                self._versioned.get_forget_projection(formal_ids[0])
                if formal_ids
                else None
            )
            if projection is None and candidate_rows:
                key = ("memory_type", str(candidate_rows[0]["memory_type"]))
            elif projection is None:
                return 0
            else:
                key = ("memory_type", str(projection["memory_type"]))
        self._connection.execute(
            """
            INSERT INTO memory_deletion_generations (
                scope, scope_id, generation, updated_at
            ) VALUES (?, ?, 1, ?)
            ON CONFLICT(scope, scope_id) DO UPDATE SET
                generation = memory_deletion_generations.generation + 1,
                updated_at = excluded.updated_at
            """,
            (key[0], key[1], now.isoformat()),
        )
        row = self._connection.execute(
            "SELECT generation FROM memory_deletion_generations "
            "WHERE scope = ? AND scope_id = ?",
            key,
        ).fetchone()
        assert row is not None
        return int(row["generation"])

    def _open_conflicts(self, memory_ids: list[str]) -> list[sqlite3.Row]:
        if not memory_ids:
            return []
        placeholders = ", ".join("?" for _ in memory_ids)
        return self._connection.execute(
            f"""
            SELECT * FROM memory_conflicts
            WHERE status = 'open' AND (
                left_memory_id IN ({placeholders}) OR
                right_memory_id IN ({placeholders})
            )
            ORDER BY conflict_id ASC
            """,
            (*memory_ids, *memory_ids),
        ).fetchall()

    def _resolve_conflicts(
        self,
        conflicts: list[sqlite3.Row],
        *,
        forgetting: set[str],
        now: datetime,
    ) -> None:
        for conflict in conflicts:
            left = str(conflict["left_memory_id"])
            right = str(conflict["right_memory_id"])
            left_forgotten = left in forgetting
            right_forgotten = right in forgetting
            if left_forgotten and right_forgotten:
                resolution = MemoryConflictResolutionKind.FORGET_BOTH
                resolved_memory_id = None
            elif left_forgotten:
                resolution = MemoryConflictResolutionKind.FORGET_LEFT
                resolved_memory_id = right
            else:
                resolution = MemoryConflictResolutionKind.FORGET_RIGHT
                resolved_memory_id = left
            self._connection.execute(
                """
                UPDATE memory_conflicts
                SET status = 'resolved', resolution_kind = ?,
                    resolved_memory_id = ?, resolved_at = ?
                WHERE conflict_id = ? AND status = 'open'
                """,
                (
                    resolution.value,
                    resolved_memory_id,
                    now.isoformat(),
                    str(conflict["conflict_id"]),
                ),
            )
            if resolved_memory_id is not None:
                state = self._versioned.get_state(resolved_memory_id)
                projection = self._versioned.get_forget_projection(resolved_memory_id)
                if (
                    state is not None
                    and projection is not None
                    and state.state is MemoryRecordState.CONFLICTED
                    and str(projection["status"]) == "active"
                    and not self._has_open_conflict(resolved_memory_id)
                ):
                    self._connection.execute(
                        """
                        UPDATE memory_record_states
                        SET state = 'active', record_generation = record_generation + 1,
                            updated_at = ?
                        WHERE memory_id = ? AND state = 'conflicted'
                        """,
                        (now.isoformat(), resolved_memory_id),
                    )

    def _has_open_conflict(self, memory_id: str) -> bool:
        return self._connection.execute(
            """
            SELECT 1 FROM memory_conflicts
            WHERE status = 'open' AND ? IN (left_memory_id, right_memory_id)
            LIMIT 1
            """,
            (memory_id,),
        ).fetchone() is not None

    @staticmethod
    def _resolved_conflict_ids(
        conflicts: list[sqlite3.Row],
        memory_id: str,
    ) -> list[str]:
        return [
            str(conflict["conflict_id"])
            for conflict in conflicts
            if memory_id in {
                str(conflict["left_memory_id"]),
                str(conflict["right_memory_id"]),
            }
        ]

    def _is_already_forgotten(
        self,
        memory_id: str,
        projection: sqlite3.Row,
    ) -> bool:
        state = self._versioned.get_state(memory_id)
        if state is not None and state.state is MemoryRecordState.DELETED:
            return True
        try:
            metadata = json.loads(str(projection["metadata_json"]))
        except (TypeError, ValueError):
            return False
        return isinstance(metadata, dict) and metadata.get("forgotten") is True

    def _already_forgotten_result(
        self,
        *,
        scope: MemoryDeletionScope,
        scope_id: str | None,
    ) -> MemoryForgetResult:
        return MemoryForgetResult(
            scope=scope,
            scope_id=scope_id,
            forgotten_memory_ids=(),
            forgotten_candidate_ids=(),
            deletion_generation=0,
            summary_barrier_generation=self._versioned.get_summary_barrier_generation(),
        )

    def _checkpoint(self, name: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(name)
