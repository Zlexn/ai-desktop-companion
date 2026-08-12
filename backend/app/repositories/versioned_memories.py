from __future__ import annotations

import base64
import binascii
import hashlib
import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from app.domain.models import (
    MemoryConflict,
    MemoryConflictResolutionKind,
    MemoryConflictStatus,
    MemoryEvidence,
    MemoryEvidenceExtractorKind,
    MemoryEvidenceRelation,
    MemoryRecordState,
    MemoryRecordStateRecord,
    MemoryType,
    MemoryVersion,
    MemoryVersionOperation,
    MemoryVersionSourceKind,
    MemoryWriteActivity,
    MemoryWriteActivityOutcome,
    MemoryGovernorDecision,
)
from app.services.memory_commit_policy import MemoryCommitTarget
from app.services.memory_gate_b_contract import (
    MEMORY_ALLOWED_AUTO_TYPES,
    MEMORY_CANONICALIZATION_VERSION,
)
from app.services.memory_source_reference import MemorySourceReferenceService


CursorKind = Literal["versions", "evidence", "conflicts"]


@dataclass(frozen=True)
class KeysetPage:
    items: tuple[object, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class DeletionGenerationSnapshot:
    global_generation: int
    session_generation: int
    type_generations: dict[MemoryType, int]


@dataclass(frozen=True)
class MemoryTombstoneMatch:
    tombstone_id: str
    source_memory_id: str
    memory_type: MemoryType
    canonical_key_hash: str | None
    subject_key_hash: str | None
    content_key_hash: str | None
    canonicalization_version: str
    delete_generation: int
    reason_code: str
    created_at: datetime
    expires_at: datetime | None
    matched_by: Literal[
        "exact_canonical_key",
        "subject_key",
        "normalized_content",
    ]


class VersionedMemoryRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._transaction_depth = 0

    @contextmanager
    def write_transaction(self) -> Iterator[None]:
        if self._transaction_depth:
            savepoint = f"versioned_memory_sp_{self._transaction_depth}"
            self._transaction_depth += 1
            self._connection.execute(f"SAVEPOINT {savepoint}")
            try:
                yield
            except BaseException:
                self._connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                self._connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            else:
                self._connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            finally:
                self._transaction_depth -= 1
            return

        if self._connection.in_transaction:
            raise RuntimeError("connection already has an unmanaged transaction")
        self._transaction_depth = 1
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            yield
        except BaseException:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()
        finally:
            self._transaction_depth = 0

    def get_state(self, memory_id: str) -> MemoryRecordStateRecord | None:
        row = self._connection.execute(
            "SELECT * FROM memory_record_states WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
        return self._state_from_row(row) if row is not None else None

    def get_current_version(self, memory_id: str) -> MemoryVersion | None:
        row = self._connection.execute(
            """
            SELECT version.*
            FROM memory_record_states AS state
            JOIN memory_versions AS version
              ON version.memory_id = state.memory_id
             AND version.id = state.current_version_id
             AND version.version_number = state.head_version
            WHERE state.memory_id = ?
            """,
            (memory_id,),
        ).fetchone()
        return self._version_from_row(row) if row is not None else None

    def list_eligible_memory_ids(self) -> list[str]:
        rows = self._connection.execute(
            """
            SELECT memory.id
            FROM memories AS memory
            LEFT JOIN memory_record_states AS state
              ON state.memory_id = memory.id
            LEFT JOIN memory_versions AS version
              ON version.memory_id = state.memory_id
             AND version.id = state.current_version_id
             AND version.version_number = state.head_version
            WHERE (
                    state.memory_id IS NULL
                AND memory.status = 'active'
                AND NOT EXISTS (
                    SELECT 1 FROM memory_conflicts AS legacy_conflict
                    WHERE legacy_conflict.status = 'open'
                      AND memory.id IN (
                          legacy_conflict.left_memory_id,
                          legacy_conflict.right_memory_id
                      )
                )
            ) OR (
                    state.state = 'active'
                AND state.current_version_id IS NOT NULL
                AND state.head_version > 0
                AND version.id IS NOT NULL
                AND version.operation <> 'delete'
                AND version.content IS NOT NULL
                AND version.redacted_at IS NULL
                AND NOT EXISTS (
                    SELECT 1 FROM memory_conflicts AS conflict
                    WHERE conflict.status = 'open'
                      AND memory.id IN (
                          conflict.left_memory_id,
                          conflict.right_memory_id
                      )
                )
            )
            ORDER BY memory.id ASC
            """
        ).fetchall()
        return [str(row["id"]) for row in rows]

    def list_eligible_exact(
        self,
        *,
        memory_type: MemoryType,
        canonical_key_hash: str,
        canonicalization_version: str = MEMORY_CANONICALIZATION_VERSION,
    ) -> list[MemoryRecordStateRecord]:
        rows = self._connection.execute(
            """
            SELECT state.*
            FROM memory_record_states AS state
            JOIN memory_versions AS version
              ON version.memory_id = state.memory_id
             AND version.id = state.current_version_id
             AND version.version_number = state.head_version
            WHERE state.state = 'active'
              AND version.memory_type = ?
              AND state.canonical_key_hash = ?
              AND state.canonicalization_version = ?
              AND version.operation <> 'delete'
              AND version.content IS NOT NULL
              AND version.redacted_at IS NULL
              AND NOT EXISTS (
                    SELECT 1 FROM memory_conflicts AS conflict
                    WHERE conflict.status = 'open'
                      AND state.memory_id IN (
                          conflict.left_memory_id,
                          conflict.right_memory_id
                      )
              )
            ORDER BY state.memory_id ASC
            """,
            (memory_type.value, canonical_key_hash, canonicalization_version),
        ).fetchall()
        return [self._state_from_row(row) for row in rows]

    def bootstrap_legacy(
        self,
        memory_id: str,
        *,
        source_references: MemorySourceReferenceService | None = None,
    ) -> MemoryRecordStateRecord:
        if self._transaction_depth == 0:
            with self.write_transaction():
                return self._bootstrap_legacy_in_transaction(
                    memory_id,
                    source_references=source_references,
                )
        return self._bootstrap_legacy_in_transaction(
            memory_id,
            source_references=source_references,
        )

    def _bootstrap_legacy_in_transaction(
        self,
        memory_id: str,
        *,
        source_references: MemorySourceReferenceService | None = None,
    ) -> MemoryRecordStateRecord:
        existing = self.get_state(memory_id)
        if existing is not None:
            return existing
        memory = self._connection.execute(
            "SELECT * FROM memories WHERE id = ?",
            (memory_id,),
        ).fetchone()
        if memory is None:
            raise ValueError("memory does not exist")
        if str(memory["status"]) not in {"active", "archived"}:
            raise ValueError("only formal legacy memory can be bootstrapped")
        content = str(memory["content"])
        created_at = str(memory["created_at"])
        version_id = f"legacy-bootstrap:{memory_id}"
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        state_value = (
            MemoryRecordState.ACTIVE.value
            if str(memory["status"]) == "active"
            else MemoryRecordState.ARCHIVED.value
        )
        source_session_id = memory["source_session_id"]
        source_session_reference_hash = None
        if source_session_id is not None:
            if source_references is None:
                raise ValueError("memory source reference service is required")
            source_session_reference_hash = source_references.session_hash(
                str(source_session_id)
            )
        try:
            self._connection.execute(
                """
                INSERT INTO memory_versions (
                    id, memory_id, version_number, parent_version_id, operation,
                    memory_type, subject, content, content_hash,
                    canonical_key_hash, subject_key_hash,
                    canonicalization_version, confidence, importance,
                    source_kind, source_session_id,
                    source_session_reference_hash, writer_policy_version,
                    created_at, redacted_at
                ) VALUES (
                    ?, ?, 1, NULL, 'bootstrap', ?, NULL, ?, ?, NULL, NULL,
                    ?, ?, ?, 'legacy', ?, ?, 'legacy-bootstrap-v1', ?, NULL
                )
                """,
                (
                    version_id,
                    memory_id,
                    str(memory["memory_type"]),
                    content,
                    content_hash,
                    MEMORY_CANONICALIZATION_VERSION,
                    float(memory["confidence"]),
                    int(memory["importance"]),
                    source_session_id,
                    source_session_reference_hash,
                    created_at,
                ),
            )
            self._connection.execute(
                """
                INSERT INTO memory_record_states (
                    memory_id, state, current_version_id, head_version,
                    record_generation, canonical_key_hash, subject_key_hash,
                    canonicalization_version, source_kind, created_at, updated_at
                ) VALUES (?, ?, ?, 1, 0, NULL, NULL, ?, 'legacy', ?, ?)
                """,
                (
                    memory_id,
                    state_value,
                    version_id,
                    MEMORY_CANONICALIZATION_VERSION,
                    created_at,
                    str(memory["updated_at"]),
                ),
            )
        except sqlite3.IntegrityError:
            existing = self.get_state(memory_id)
            if existing is None:
                raise
            return existing
        return self.get_state(memory_id)  # type: ignore[return-value]

    def get_forget_projection(self, memory_id: str) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM memories WHERE id = ?",
            (memory_id,),
        ).fetchone()

    def list_forget_formal_ids(
        self,
        *,
        memory_id: str | None = None,
        memory_type: MemoryType | None = None,
        session_id: str | None = None,
        session_reference_hash: str | None = None,
    ) -> list[str]:
        predicates = [
            """
            (
                (state.memory_id IS NOT NULL AND state.state <> 'deleted') OR
                (state.memory_id IS NULL AND memory.status IN ('active', 'archived'))
            )
            """
        ]
        parameters: list[object] = []
        if memory_id is not None:
            predicates.append("memory.id = ?")
            parameters.append(memory_id)
        if memory_type is not None:
            predicates.append(
                """
                (
                    memory.memory_type = ? OR EXISTS (
                        SELECT 1 FROM memory_versions AS historical_type
                        WHERE historical_type.memory_id = memory.id
                          AND historical_type.memory_type = ?
                          AND historical_type.redacted_at IS NULL
                    )
                )
                """
            )
            parameters.extend((memory_type.value, memory_type.value))
        if session_id is not None and session_reference_hash is not None:
            predicates.append(
                """
                (
                    memory.source_session_id = ? OR EXISTS (
                        SELECT 1 FROM memory_versions AS version
                        WHERE version.memory_id = memory.id
                          AND (
                              version.source_session_id = ? OR
                              version.source_session_reference_hash = ?
                          )
                    ) OR EXISTS (
                        SELECT 1 FROM memory_evidence AS evidence
                        WHERE evidence.memory_id = memory.id
                          AND (
                              evidence.source_session_id = ? OR
                              evidence.source_session_reference_hash = ?
                          )
                    )
                )
                """
            )
            parameters.extend(
                (
                    session_id,
                    session_id,
                    session_reference_hash,
                    session_id,
                    session_reference_hash,
                )
            )
        rows = self._connection.execute(
            f"""
            SELECT DISTINCT memory.id
            FROM memories AS memory
            LEFT JOIN memory_record_states AS state ON state.memory_id = memory.id
            WHERE {' AND '.join(predicates)}
            ORDER BY memory.id ASC
            """,
            parameters,
        ).fetchall()
        return [str(row["id"]) for row in rows]

    def list_forget_candidate_ids(
        self,
        *,
        memory_id: str | None = None,
        memory_type: MemoryType | None = None,
        session_id: str | None = None,
        session_reference_hash: str | None = None,
    ) -> list[str]:
        predicates = [
            "memory.status IN ('pending', 'dismissed')",
            "state.memory_id IS NULL",
        ]
        parameters: list[object] = []
        if memory_id is not None:
            predicates.append("memory.id = ?")
            parameters.append(memory_id)
        if memory_type is not None:
            predicates.append("memory.memory_type = ?")
            parameters.append(memory_type.value)
        if session_id is not None:
            if session_reference_hash is None:
                predicates.append("memory.source_session_id = ?")
                parameters.append(session_id)
            else:
                predicates.append(
                    "(memory.source_session_id = ? OR "
                    "memory.source_session_reference_hash = ?)"
                )
                parameters.extend((session_id, session_reference_hash))
        rows = self._connection.execute(
            f"""
            SELECT memory.id, memory.metadata_json
            FROM memories AS memory
            LEFT JOIN memory_record_states AS state ON state.memory_id = memory.id
            WHERE {' AND '.join(predicates)}
            ORDER BY memory.id ASC
            """,
            parameters,
        ).fetchall()
        result: list[str] = []
        for row in rows:
            try:
                metadata = json.loads(str(row["metadata_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = {}
            if not isinstance(metadata, dict) or metadata.get("forgotten") is not True:
                result.append(str(row["id"]))
        return result

    def list_forget_candidate_payloads(
        self,
        memory_ids: list[str],
    ) -> list[sqlite3.Row]:
        if not memory_ids:
            return []
        placeholders = ", ".join("?" for _ in memory_ids)
        return self._connection.execute(
            f"SELECT id, content, memory_type, metadata_json FROM memories "
            f"WHERE id IN ({placeholders}) ORDER BY id ASC",
            memory_ids,
        ).fetchall()

    def list_unredacted_forget_versions(self, memory_id: str) -> list[sqlite3.Row]:
        return self._connection.execute(
            """
            SELECT * FROM memory_versions
            WHERE memory_id = ? AND redacted_at IS NULL
            ORDER BY version_number ASC, id ASC
            """,
            (memory_id,),
        ).fetchall()

    def list_forget_source_message_ids(
        self,
        memory_ids: list[str],
    ) -> tuple[set[str], set[str]]:
        if not memory_ids:
            return set(), set()
        placeholders = ", ".join("?" for _ in memory_ids)
        message_rows = self._connection.execute(
            f"""
            SELECT source_message_id FROM memory_evidence
            WHERE memory_id IN ({placeholders}) AND source_message_id IS NOT NULL
            """,
            memory_ids,
        ).fetchall()
        session_rows = self._connection.execute(
            f"""
            SELECT source_session_id FROM memory_versions
            WHERE memory_id IN ({placeholders}) AND source_session_id IS NOT NULL
            UNION
            SELECT source_session_id FROM memory_evidence
            WHERE memory_id IN ({placeholders}) AND source_session_id IS NOT NULL
            UNION
            SELECT source_session_id FROM memories
            WHERE id IN ({placeholders}) AND source_session_id IS NOT NULL
            """,
            (*memory_ids, *memory_ids, *memory_ids),
        ).fetchall()
        return (
            {str(row["source_message_id"]) for row in message_rows},
            {str(row["source_session_id"]) for row in session_rows},
        )

    def list_session_message_ids(self, session_ids: set[str]) -> set[str]:
        if not session_ids:
            return set()
        ordered = sorted(session_ids)
        placeholders = ", ".join("?" for _ in ordered)
        rows = self._connection.execute(
            f"SELECT id FROM messages WHERE session_id IN ({placeholders})",
            ordered,
        ).fetchall()
        return {str(row["id"]) for row in rows}

    def get_summary_barrier_generation(self) -> int:
        row = self._connection.execute(
            "SELECT generation FROM memory_summary_barrier WHERE singleton_id = 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("memory summary barrier is unavailable")
        return int(row["generation"])

    def list_versions(
        self,
        memory_id: str,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> KeysetPage:
        self._validate_limit(limit)
        key = self._decode_cursor(cursor, "versions", {"memory_id": memory_id})
        params: list[object] = [memory_id]
        predicate = ""
        if key is not None:
            predicate = "AND (version_number < ? OR (version_number = ? AND id < ?))"
            params.extend((int(key[0]), int(key[0]), str(key[1])))
        params.append(limit + 1)
        rows = self._connection.execute(
            f"""
            SELECT * FROM memory_versions
            WHERE memory_id = ? {predicate}
            ORDER BY version_number DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return self._page(
            rows,
            limit=limit,
            kind="versions",
            filters={"memory_id": memory_id},
            key=lambda row: (int(row["version_number"]), str(row["id"])),
            convert=self._version_from_row,
        )

    def list_evidence(
        self,
        memory_id: str,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> KeysetPage:
        self._validate_limit(limit)
        key = self._decode_cursor(cursor, "evidence", {"memory_id": memory_id})
        params: list[object] = [memory_id]
        predicate = ""
        if key is not None:
            predicate = "AND (observed_at < ? OR (observed_at = ? AND evidence_id < ?))"
            params.extend((str(key[0]), str(key[0]), str(key[1])))
        params.append(limit + 1)
        rows = self._connection.execute(
            f"""
            SELECT * FROM memory_evidence
            WHERE memory_id = ? {predicate}
            ORDER BY observed_at DESC, evidence_id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return self._page(
            rows,
            limit=limit,
            kind="evidence",
            filters={"memory_id": memory_id},
            key=lambda row: (str(row["observed_at"]), str(row["evidence_id"])),
            convert=self._evidence_from_row,
        )

    def list_conflicts(
        self,
        *,
        status: MemoryConflictStatus,
        limit: int = 20,
        cursor: str | None = None,
    ) -> KeysetPage:
        self._validate_limit(limit)
        filters = {"status": status.value}
        key = self._decode_cursor(cursor, "conflicts", filters)
        params: list[object] = [status.value]
        predicate = ""
        if key is not None:
            predicate = "AND (created_at < ? OR (created_at = ? AND conflict_id < ?))"
            params.extend((str(key[0]), str(key[0]), str(key[1])))
        params.append(limit + 1)
        rows = self._connection.execute(
            f"""
            SELECT * FROM memory_conflicts
            WHERE status = ? {predicate}
            ORDER BY created_at DESC, conflict_id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return self._page(
            rows,
            limit=limit,
            kind="conflicts",
            filters=filters,
            key=lambda row: (str(row["created_at"]), str(row["conflict_id"])),
            convert=self._conflict_from_row,
        )

    def bootstrap_all_active_legacy(
        self,
        *,
        source_references: MemorySourceReferenceService,
    ) -> None:
        rows = self._connection.execute(
            """
            SELECT memory.id
            FROM memories AS memory
            LEFT JOIN memory_record_states AS state ON state.memory_id = memory.id
            WHERE memory.status = 'active' AND state.memory_id IS NULL
            ORDER BY memory.id ASC
            """
        ).fetchall()
        for row in rows:
            self.bootstrap_legacy(
                str(row["id"]),
                source_references=source_references,
            )

    def list_commit_targets(self) -> list[MemoryCommitTarget]:
        rows = self._connection.execute(
            """
            SELECT state.memory_id, version.memory_type, version.content,
                   state.canonical_key_hash, state.subject_key_hash,
                   state.current_version_id, state.head_version,
                   state.record_generation,
                   EXISTS (
                       SELECT 1 FROM memory_conflicts AS conflict
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
            WHERE state.state = 'active'
              AND version.operation <> 'delete'
              AND version.content IS NOT NULL
              AND version.redacted_at IS NULL
            ORDER BY state.memory_id ASC
            """
        ).fetchall()
        return [
            MemoryCommitTarget(
                memory_id=str(row["memory_id"]),
                memory_type=MemoryType(str(row["memory_type"])),
                content=str(row["content"]),
                canonical_key_hash=(
                    str(row["canonical_key_hash"])
                    if row["canonical_key_hash"] is not None
                    else None
                ),
                subject_key_hash=row["subject_key_hash"],
                current_version_id=str(row["current_version_id"]),
                head_version=int(row["head_version"]),
                record_generation=int(row["record_generation"]),
                open_conflict=bool(row["open_conflict"]),
            )
            for row in rows
        ]

    def get_write_authority(self, scope_id: str = "default") -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM memory_write_consents WHERE scope_id = ?",
            (scope_id,),
        ).fetchone()

    def get_remote_authority(self, scope_id: str = "default") -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM memory_extraction_consents WHERE scope_id = ?",
            (scope_id,),
        ).fetchone()

    def insert_commit_activity(self, **values: object) -> None:
        columns = tuple(values)
        allowed = {
            "op_id", "job_id", "proposal_index", "proposal_fingerprint",
            "turn_id", "memory_id", "previous_version_id", "result_version_id",
            "conflict_id", "decision", "outcome", "expected_head_version",
            "observed_record_generation", "write_consent_generation",
            "remote_consent_generation", "remote_authority_fingerprint",
            "governor_version", "commit_policy_version", "canonicalization_version",
            "extractor_kind", "provider_identifier", "model_identifier",
            "created_at", "finished_at",
        }
        if set(columns) != allowed:
            raise ValueError("invalid memory activity columns")
        placeholders = ", ".join("?" for _ in columns)
        self._connection.execute(
            f"INSERT INTO memory_write_activities ({', '.join(columns)}) VALUES ({placeholders})",
            tuple(values[column] for column in columns),
        )

    def insert_evidence(self, **values: object) -> None:
        columns = tuple(values)
        allowed = {
            "evidence_id", "memory_id", "memory_version_id", "source_session_id",
            "source_message_id", "source_session_reference_hash",
            "source_message_reference_hash", "source_available", "source_deleted_at",
            "relation", "observed_at", "extractor_kind", "extractor_provider",
            "extractor_model", "confidence", "created_at",
        }
        if set(columns) != allowed:
            raise ValueError("invalid memory Evidence columns")
        placeholders = ", ".join("?" for _ in columns)
        self._connection.execute(
            f"INSERT INTO memory_evidence ({', '.join(columns)}) VALUES ({placeholders})",
            tuple(values[column] for column in columns),
        )

    def guarded_touch_target(self, target: MemoryCommitTarget) -> bool:
        cursor = self._connection.execute(
            """
            UPDATE memory_record_states
            SET record_generation = record_generation + 1,
                updated_at = updated_at
            WHERE memory_id = ? AND state = 'active'
              AND current_version_id = ? AND head_version = ?
              AND record_generation = ?
            """,
            (
                target.memory_id,
                target.current_version_id,
                target.head_version,
                target.record_generation,
            ),
        )
        return cursor.rowcount == 1

    def get_activity(
        self,
        *,
        job_id: str,
        proposal_fingerprint: str,
        commit_policy_version: str,
    ) -> MemoryWriteActivity | None:
        row = self._connection.execute(
            """
            SELECT * FROM memory_write_activities
            WHERE job_id = ? AND proposal_fingerprint = ?
              AND commit_policy_version = ?
            """,
            (job_id, proposal_fingerprint, commit_policy_version),
        ).fetchone()
        return self._activity_from_row(row) if row is not None else None

    def read_deletion_generations(
        self,
        *,
        session_reference_hash: str,
    ) -> DeletionGenerationSnapshot:
        rows = self._connection.execute(
            """
            SELECT scope, scope_id, generation FROM memory_deletion_generations
            WHERE (scope = 'all' AND scope_id = '*')
               OR (scope = 'session' AND scope_id = ?)
               OR scope = 'memory_type'
            """,
            (session_reference_hash,),
        ).fetchall()
        values = {(str(row["scope"]), str(row["scope_id"])): int(row["generation"]) for row in rows}
        return DeletionGenerationSnapshot(
            global_generation=values.get(("all", "*"), 0),
            session_generation=values.get(("session", session_reference_hash), 0),
            type_generations={
                memory_type: values.get(("memory_type", memory_type.value), 0)
                for memory_type in MEMORY_ALLOWED_AUTO_TYPES
            },
        )

    def find_tombstone(
        self,
        *,
        memory_type: MemoryType,
        canonical_key_hash: str | None,
        subject_key_hash: str | None,
        content_key_hash: str | None = None,
        canonicalization_version: str,
        now: datetime | None = None,
    ) -> MemoryTombstoneMatch | None:
        now_iso = now.isoformat() if now is not None else None
        row = self._connection.execute(
            """
            SELECT * FROM memory_tombstones
            WHERE memory_type = ? AND canonicalization_version = ?
              AND (? IS NULL OR expires_at IS NULL OR expires_at > ?)
              AND ? IS NOT NULL AND canonical_key_hash = ?
            ORDER BY delete_generation DESC, created_at DESC, tombstone_id DESC
            LIMIT 1
            """,
            (
                memory_type.value,
                canonicalization_version,
                now_iso,
                now_iso,
                canonical_key_hash,
                canonical_key_hash,
            ),
        ).fetchone()
        matched_by: Literal[
            "exact_canonical_key",
            "subject_key",
            "normalized_content",
        ] = "exact_canonical_key"
        if row is None:
            row = self._connection.execute(
                """
                SELECT * FROM memory_tombstones
                WHERE memory_type = ? AND canonicalization_version = ?
                  AND (? IS NULL OR expires_at IS NULL OR expires_at > ?)
                  AND ? IS NOT NULL AND subject_key_hash = ?
                ORDER BY delete_generation DESC, created_at DESC, tombstone_id DESC
                LIMIT 1
                """,
                (
                    memory_type.value,
                    canonicalization_version,
                    now_iso,
                    now_iso,
                    subject_key_hash,
                    subject_key_hash,
                ),
            ).fetchone()
            matched_by = "subject_key"
        if row is None and content_key_hash is not None:
            row = self._connection.execute(
                """
                SELECT * FROM memory_tombstones
                WHERE memory_type = ? AND canonicalization_version = ?
                  AND (? IS NULL OR expires_at IS NULL OR expires_at > ?)
                  AND content_key_hash = ?
                ORDER BY delete_generation DESC, created_at DESC,
                         tombstone_id DESC
                LIMIT 1
                """,
                (
                    memory_type.value,
                    canonicalization_version,
                    now_iso,
                    now_iso,
                    content_key_hash,
                ),
            ).fetchone()
            matched_by = "normalized_content"
        if row is None:
            return None
        return MemoryTombstoneMatch(
            tombstone_id=str(row["tombstone_id"]),
            source_memory_id=str(row["source_memory_id"]),
            memory_type=MemoryType(str(row["memory_type"])),
            canonical_key_hash=row["canonical_key_hash"],
            subject_key_hash=row["subject_key_hash"],
            content_key_hash=row["content_key_hash"],
            canonicalization_version=str(row["canonicalization_version"]),
            delete_generation=int(row["delete_generation"]),
            reason_code=str(row["reason_code"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            expires_at=(
                datetime.fromisoformat(str(row["expires_at"]))
                if row["expires_at"] is not None
                else None
            ),
            matched_by=matched_by,
        )

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")

    @classmethod
    def _page(
        cls,
        rows: list[sqlite3.Row],
        *,
        limit: int,
        kind: CursorKind,
        filters: Mapping[str, str],
        key,
        convert,
    ) -> KeysetPage:
        visible = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            next_cursor = cls._encode_cursor(kind, filters, key(visible[-1]))
        return KeysetPage(tuple(convert(row) for row in visible), next_cursor)

    @staticmethod
    def _encode_cursor(
        kind: CursorKind,
        filters: Mapping[str, str],
        key: tuple[object, object],
    ) -> str:
        payload = json.dumps(
            {"v": 1, "kind": kind, "filters": dict(filters), "key": list(key)},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_cursor(
        cursor: str | None,
        kind: CursorKind,
        filters: Mapping[str, str],
    ) -> tuple[Any, Any] | None:
        if cursor is None:
            return None
        try:
            if not isinstance(cursor, str) or not cursor:
                raise ValueError
            padding = "=" * (-len(cursor) % 4)
            decoded = base64.b64decode(
                cursor + padding,
                altchars=b"-_",
                validate=True,
            )
            payload = json.loads(decoded.decode("utf-8"))
        except (
            ValueError,
            TypeError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            binascii.Error,
        ) as exc:
            raise ValueError("invalid pagination cursor") from exc
        if (
            not isinstance(payload, dict)
            or set(payload) != {"v", "kind", "filters", "key"}
            or payload.get("v") != 1
            or payload.get("kind") != kind
            or payload.get("filters") != dict(filters)
            or not isinstance(payload.get("key"), list)
            or len(payload["key"]) != 2
        ):
            raise ValueError("pagination cursor does not match the requested filter")
        key_values = payload["key"]
        valid_id = isinstance(key_values[1], str) and bool(key_values[1])
        if kind == "versions":
            valid_position = (
                type(key_values[0]) is int and key_values[0] >= 1
            )
        else:
            valid_position = isinstance(key_values[0], str) and bool(key_values[0])
            if valid_position:
                try:
                    datetime.fromisoformat(key_values[0])
                except ValueError:
                    valid_position = False
        if not valid_position or not valid_id:
            raise ValueError("invalid pagination cursor")
        return key_values[0], key_values[1]

    @staticmethod
    def _state_from_row(row: sqlite3.Row) -> MemoryRecordStateRecord:
        return MemoryRecordStateRecord(
            memory_id=str(row["memory_id"]),
            state=MemoryRecordState(str(row["state"])),
            current_version_id=row["current_version_id"],
            head_version=int(row["head_version"]),
            record_generation=int(row["record_generation"]),
            canonical_key_hash=row["canonical_key_hash"],
            subject_key_hash=row["subject_key_hash"],
            canonicalization_version=row["canonicalization_version"],
            source_kind=MemoryVersionSourceKind(str(row["source_kind"])),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    @staticmethod
    def _version_from_row(row: sqlite3.Row) -> MemoryVersion:
        return MemoryVersion(
            id=str(row["id"]),
            memory_id=str(row["memory_id"]),
            version_number=int(row["version_number"]),
            parent_version_id=row["parent_version_id"],
            operation=MemoryVersionOperation(str(row["operation"])),
            memory_type=MemoryType(str(row["memory_type"])),
            subject=row["subject"],
            content=row["content"],
            content_hash=str(row["content_hash"]),
            canonical_key_hash=row["canonical_key_hash"],
            subject_key_hash=row["subject_key_hash"],
            canonicalization_version=str(row["canonicalization_version"]),
            confidence=float(row["confidence"]),
            importance=int(row["importance"]),
            source_kind=MemoryVersionSourceKind(str(row["source_kind"])),
            source_session_id=row["source_session_id"],
            source_session_reference_hash=row["source_session_reference_hash"],
            writer_policy_version=str(row["writer_policy_version"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            redacted_at=(datetime.fromisoformat(str(row["redacted_at"])) if row["redacted_at"] else None),
            canonical_subject_code=row["canonical_subject_code"],
        )

    @staticmethod
    def _evidence_from_row(row: sqlite3.Row) -> MemoryEvidence:
        return MemoryEvidence(
            id=str(row["evidence_id"]),
            memory_id=str(row["memory_id"]),
            memory_version_id=str(row["memory_version_id"]),
            source_session_id=row["source_session_id"],
            source_message_id=row["source_message_id"],
            source_session_reference_hash=str(row["source_session_reference_hash"]),
            source_message_reference_hash=str(row["source_message_reference_hash"]),
            source_available=bool(row["source_available"]),
            source_deleted_at=(datetime.fromisoformat(str(row["source_deleted_at"])) if row["source_deleted_at"] else None),
            relation=MemoryEvidenceRelation(str(row["relation"])),
            observed_at=datetime.fromisoformat(str(row["observed_at"])),
            extractor_kind=MemoryEvidenceExtractorKind(str(row["extractor_kind"])),
            extractor_provider=row["extractor_provider"],
            extractor_model=row["extractor_model"],
            confidence=float(row["confidence"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    @staticmethod
    def _conflict_from_row(row: sqlite3.Row) -> MemoryConflict:
        resolution = row["resolution_kind"]
        return MemoryConflict(
            id=str(row["conflict_id"]),
            left_memory_id=str(row["left_memory_id"]),
            right_memory_id=str(row["right_memory_id"]),
            status=MemoryConflictStatus(str(row["status"])),
            resolution_kind=(MemoryConflictResolutionKind(str(resolution)) if resolution else None),
            resolved_memory_id=row["resolved_memory_id"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
            resolved_at=(datetime.fromisoformat(str(row["resolved_at"])) if row["resolved_at"] else None),
        )

    @staticmethod
    def _activity_from_row(row: sqlite3.Row) -> MemoryWriteActivity:
        return MemoryWriteActivity(
            op_id=str(row["op_id"]),
            job_id=str(row["job_id"]),
            proposal_index=int(row["proposal_index"]),
            proposal_fingerprint=str(row["proposal_fingerprint"]),
            turn_id=str(row["turn_id"]),
            memory_id=row["memory_id"],
            previous_version_id=row["previous_version_id"],
            result_version_id=row["result_version_id"],
            conflict_id=row["conflict_id"],
            decision=MemoryGovernorDecision(str(row["decision"])),
            outcome=MemoryWriteActivityOutcome(str(row["outcome"])),
            expected_head_version=(int(row["expected_head_version"]) if row["expected_head_version"] is not None else None),
            observed_record_generation=(int(row["observed_record_generation"]) if row["observed_record_generation"] is not None else None),
            write_consent_generation=int(row["write_consent_generation"]),
            remote_consent_generation=(int(row["remote_consent_generation"]) if row["remote_consent_generation"] is not None else None),
            remote_authority_fingerprint=row["remote_authority_fingerprint"],
            governor_version=str(row["governor_version"]),
            commit_policy_version=str(row["commit_policy_version"]),
            canonicalization_version=str(row["canonicalization_version"]),
            extractor_kind=MemoryEvidenceExtractorKind(str(row["extractor_kind"])),
            provider_identifier=row["provider_identifier"],
            model_identifier=row["model_identifier"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
            finished_at=(datetime.fromisoformat(str(row["finished_at"])) if row["finished_at"] else None),
        )
