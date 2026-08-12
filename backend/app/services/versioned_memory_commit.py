from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import sqlite3
import uuid

from app.domain.models import (
    MemoryEvidenceExtractorKind,
    MemoryEvidenceRelation,
    MemoryGovernorDecision,
    MemoryGovernorProposal,
    MemoryGovernorResult,
    MemoryRecordState,
    MemoryType,
    MemoryVersionOperation,
    MemoryWriteActivityOutcome,
)
from app.repositories.sqlite import metadata_to_json
from app.repositories.versioned_memories import (
    DeletionGenerationSnapshot,
    VersionedMemoryRepository,
)
from app.services.memory_commit_policy import (
    MemoryCommitPolicy,
    MemoryCommitPolicyResult,
    MemoryCommitTarget,
    canonicalize_memory_v1,
    proposal_fingerprint_v1,
)
from app.services.memory_extraction_contract import (
    MEMORY_EXTRACTION_DISCLOSED_FIELDS,
    MEMORY_EXTRACTION_DISCLOSURE_VERSION,
    MEMORY_EXTRACTION_PURPOSE,
    memory_remote_authority_fingerprint,
)
from app.services.memory_gate_b_contract import (
    MEMORY_ALLOWED_AUTO_TYPES,
    MEMORY_ALLOWED_AUTO_TYPES_VERSION,
    MEMORY_CANONICALIZATION_VERSION,
    MEMORY_COMMIT_POLICY_VERSION,
    MEMORY_COMMIT_SEMANTIC_RETRIES_DEFAULT,
    MEMORY_WRITE_POLICY_VERSION,
    MEMORY_WRITE_PURPOSE,
    MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION,
)
from app.services.memory_governor import MEMORY_GOVERNOR_VERSION
from app.services.memory_source_reference import MemorySourceReferenceService


@dataclass(frozen=True)
class WriteAuthoritySnapshot:
    write_consent_generation: int
    remote_consent_generation: int | None
    remote_authority_fingerprint: str | None
    turn_completed_at: datetime | None = None


@dataclass(frozen=True)
class VersionedMemoryCommitRequest:
    job_id: str
    turn_id: str
    proposal_index: int
    proposal: MemoryGovernorProposal
    governor_result: MemoryGovernorResult
    session_id: str
    user_message_id: str
    user_text: str
    extractor_kind: MemoryEvidenceExtractorKind
    provider_identifier: str | None
    model_identifier: str | None
    authority: WriteAuthoritySnapshot
    deletion_snapshot: DeletionGenerationSnapshot
    expected_targets: tuple[MemoryCommitTarget, ...] | None = None


@dataclass(frozen=True)
class VersionedMemoryCommitResult:
    decision: MemoryGovernorDecision
    outcome: MemoryWriteActivityOutcome
    op_id: str
    proposal_fingerprint: str
    memory_id: str | None
    previous_version_id: str | None
    result_version_id: str | None
    conflict_id: str | None
    semantic_attempts: int = 1
    reason_code: str | None = None
    resulting_targets: tuple[MemoryCommitTarget, ...] | None = None


class _StaleHeadError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _op_id(job_id: str, fingerprint: str) -> str:
    return hashlib.sha256(
        f"{job_id}{fingerprint}{MEMORY_COMMIT_POLICY_VERSION}".encode("utf-8")
    ).hexdigest()


class VersionedMemoryCommitService:
    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        versioned: VersionedMemoryRepository,
        policy: MemoryCommitPolicy,
        source_references: MemorySourceReferenceService,
        semantic_retries: int = MEMORY_COMMIT_SEMANTIC_RETRIES_DEFAULT,
    ) -> None:
        self._connection = connection
        self._versioned = versioned
        self._policy = policy
        self._source_references = source_references
        self._semantic_retries = semantic_retries

    def commit_one(
        self,
        request: VersionedMemoryCommitRequest,
    ) -> VersionedMemoryCommitResult:
        fingerprint = proposal_fingerprint_v1(proposal=request.proposal)
        operation_id = _op_id(request.job_id, fingerprint)
        for attempt in range(self._semantic_retries + 1):
            try:
                return self._commit_attempt(
                    request,
                    fingerprint=fingerprint,
                    operation_id=operation_id,
                    semantic_attempts=attempt + 1,
                )
            except sqlite3.OperationalError as exc:
                if not self._retryable(exc) or attempt >= self._semantic_retries:
                    raise
        raise AssertionError("semantic retry loop exhausted")

    def _commit_attempt(
        self,
        request: VersionedMemoryCommitRequest,
        *,
        fingerprint: str,
        operation_id: str,
        semantic_attempts: int,
    ) -> VersionedMemoryCommitResult:
        try:
            with self._versioned.write_transaction():
                if self._job_was_cancelled_for_session_deletion(request.job_id):
                    return VersionedMemoryCommitResult(
                        decision=MemoryGovernorDecision.REJECT,
                        outcome=(
                            MemoryWriteActivityOutcome.CANCELLED_SESSION_DELETED
                        ),
                        op_id=operation_id,
                        proposal_fingerprint=fingerprint,
                        memory_id=None,
                        previous_version_id=None,
                        result_version_id=None,
                        conflict_id=None,
                        semantic_attempts=semantic_attempts,
                        reason_code=(
                            MemoryWriteActivityOutcome.CANCELLED_SESSION_DELETED.value
                        ),
                    )
                duplicate = self._versioned.get_activity(
                    job_id=request.job_id,
                    proposal_fingerprint=fingerprint,
                    commit_policy_version=MEMORY_COMMIT_POLICY_VERSION,
                )
                if duplicate is not None:
                    return VersionedMemoryCommitResult(
                        decision=MemoryGovernorDecision.NO_CHANGE,
                        outcome=MemoryWriteActivityOutcome.DUPLICATE_OP,
                        op_id=duplicate.op_id,
                        proposal_fingerprint=fingerprint,
                        memory_id=duplicate.memory_id,
                        previous_version_id=duplicate.previous_version_id,
                        result_version_id=duplicate.result_version_id,
                        conflict_id=duplicate.conflict_id,
                        semantic_attempts=semantic_attempts,
                        reason_code="duplicate_op",
                    )

                gate_outcome = self._authority_outcome(request)
                if gate_outcome is None:
                    gate_outcome = self._remote_authority_outcome(request)
                session_hash = self._source_references.session_hash(
                    request.session_id
                )
                if gate_outcome is None:
                    current_generations = self._versioned.read_deletion_generations(
                        session_reference_hash=session_hash
                    )
                    if not self._deletion_snapshot_matches(
                        request,
                        current_generations,
                    ):
                        gate_outcome = MemoryWriteActivityOutcome.SKIPPED_DELETION_BARRIER
                canonical = canonicalize_memory_v1(
                    memory_type=request.proposal.memory_type,
                    subject=request.proposal.subject,
                    content=request.proposal.content,
                )
                tombstone_match = None
                if gate_outcome is None:
                    tombstone = self._versioned.find_tombstone(
                        memory_type=request.proposal.memory_type,
                        canonical_key_hash=canonical.canonical_key_hash,
                        subject_key_hash=canonical.subject_key_hash,
                        content_key_hash=canonical.content_key_hash,
                        canonicalization_version=MEMORY_CANONICALIZATION_VERSION,
                        now=_now(),
                    )
                    tombstone_match = tombstone.matched_by if tombstone else None

                if gate_outcome is None:
                    self._versioned.bootstrap_all_active_legacy(
                        source_references=self._source_references,
                    )
                    current_targets = self._versioned.list_commit_targets()
                    if (
                        request.expected_targets is not None
                        and not self._target_snapshot_matches(
                            request.expected_targets,
                            current_targets,
                        )
                    ):
                        raise _StaleHeadError
                    policy_result = self._policy.evaluate(
                        proposal=request.proposal,
                        governor_result=request.governor_result,
                        user_text=request.user_text,
                        user_message_id=request.user_message_id,
                        current_heads=current_targets,
                        tombstone_match=tombstone_match,
                    )
                else:
                    policy_result = MemoryCommitPolicyResult(
                        decision=MemoryGovernorDecision.REJECT,
                        outcome=gate_outcome,
                        reason_code=gate_outcome.value,
                        target=None,
                        canonical=canonical,
                        proposal_fingerprint=fingerprint,
                    )

                result = self._apply_decision(
                    request,
                    policy_result,
                    operation_id=operation_id,
                    fingerprint=fingerprint,
                    semantic_attempts=semantic_attempts,
                )
                return result
        except _StaleHeadError:
            return self._record_stale(
                request,
                fingerprint=fingerprint,
                operation_id=operation_id,
                semantic_attempts=semantic_attempts,
            )

    def _apply_decision(
        self,
        request: VersionedMemoryCommitRequest,
        policy_result: MemoryCommitPolicyResult,
        *,
        operation_id: str,
        fingerprint: str,
        semantic_attempts: int,
    ) -> VersionedMemoryCommitResult:
        now = _now()
        memory_id = None
        previous_version_id = None
        result_version_id = None
        conflict_id = None
        target = policy_result.target
        if policy_result.decision is MemoryGovernorDecision.CREATE:
            memory_id = str(uuid.uuid4())
            result_version_id = self._insert_root(
                request,
                policy_result,
                memory_id=memory_id,
                operation=MemoryVersionOperation.CREATE,
                state=MemoryRecordState.ACTIVE,
                now=now,
            )
            self._insert_evidence(
                request,
                memory_id=memory_id,
                version_id=result_version_id,
                relation=MemoryEvidenceRelation.SUPPORTS,
                now=now,
            )
        elif policy_result.decision is MemoryGovernorDecision.SUPPORT:
            assert target is not None
            if not self._versioned.guarded_touch_target(target):
                raise _StaleHeadError
            memory_id = target.memory_id
            previous_version_id = target.current_version_id
            result_version_id = target.current_version_id
            self._insert_evidence(
                request,
                memory_id=target.memory_id,
                version_id=target.current_version_id,
                relation=MemoryEvidenceRelation.SUPPORTS,
                now=now,
            )
        elif policy_result.decision is MemoryGovernorDecision.SUPERSEDE:
            assert target is not None
            memory_id = target.memory_id
            previous_version_id = target.current_version_id
            result_version_id = self._insert_successor(
                request,
                policy_result,
                target=target,
                now=now,
            )
            if not self._cas_supersede(
                target,
                result_version_id=result_version_id,
                policy_result=policy_result,
                now=now,
            ):
                raise _StaleHeadError
            self._update_projection(
                memory_id=target.memory_id,
                request=request,
                now=now,
            )
            self._insert_evidence(
                request,
                memory_id=target.memory_id,
                version_id=target.current_version_id,
                relation=MemoryEvidenceRelation.CORRECTS,
                now=now,
            )
            self._insert_evidence(
                request,
                memory_id=target.memory_id,
                version_id=result_version_id,
                relation=MemoryEvidenceRelation.SUPPORTS,
                now=now,
            )
        elif policy_result.decision is MemoryGovernorDecision.CONFLICT:
            assert target is not None
            if not self._versioned.guarded_touch_target(target):
                raise _StaleHeadError
            memory_id = str(uuid.uuid4())
            previous_version_id = target.current_version_id
            result_version_id = self._insert_root(
                request,
                policy_result,
                memory_id=memory_id,
                operation=MemoryVersionOperation.CONFLICT_CANDIDATE,
                state=MemoryRecordState.CONFLICTED,
                now=now,
            )
            conflict_id = str(uuid.uuid4())
            left, right = sorted((target.memory_id, memory_id))
            self._connection.execute(
                """
                INSERT INTO memory_conflicts (
                    conflict_id, left_memory_id, right_memory_id,
                    status, created_at
                ) VALUES (?, ?, ?, 'open', ?)
                """,
                (conflict_id, left, right, now.isoformat()),
            )
            self._insert_evidence(
                request,
                memory_id=target.memory_id,
                version_id=target.current_version_id,
                relation=MemoryEvidenceRelation.CONTRADICTS,
                now=now,
            )
            self._insert_evidence(
                request,
                memory_id=memory_id,
                version_id=result_version_id,
                relation=MemoryEvidenceRelation.SUPPORTS,
                now=now,
            )

        self._insert_activity(
            request,
            policy_result=policy_result,
            operation_id=operation_id,
            fingerprint=fingerprint,
            memory_id=memory_id,
            previous_version_id=previous_version_id,
            result_version_id=result_version_id,
            conflict_id=conflict_id,
            target=target,
            now=now,
        )
        return VersionedMemoryCommitResult(
            decision=policy_result.decision,
            outcome=policy_result.outcome,
            op_id=operation_id,
            proposal_fingerprint=fingerprint,
            memory_id=memory_id,
            previous_version_id=previous_version_id,
            result_version_id=result_version_id,
            conflict_id=conflict_id,
            semantic_attempts=semantic_attempts,
            reason_code=policy_result.reason_code,
            resulting_targets=tuple(self._versioned.list_commit_targets()),
        )

    def _insert_root(
        self,
        request: VersionedMemoryCommitRequest,
        policy_result: MemoryCommitPolicyResult,
        *,
        memory_id: str,
        operation: MemoryVersionOperation,
        state: MemoryRecordState,
        now: datetime,
    ) -> str:
        canonical = policy_result.canonical
        assert canonical is not None
        version_id = str(uuid.uuid4())
        self._connection.execute(
            """
            INSERT INTO memories (
                id, content, memory_type, source, source_session_id,
                importance, confidence, status, metadata_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, 'automatic', ?, 3, ?, 'active', ?, ?, ?)
            """,
            (
                memory_id,
                request.proposal.content,
                request.proposal.memory_type.value,
                request.session_id,
                request.proposal.confidence,
                metadata_to_json({}),
                now.isoformat(),
                now.isoformat(),
            ),
        )
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
            ) VALUES (?, ?, 1, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, 3,
                      'automatic', ?, ?, ?, ?, NULL, NULL)
            """,
            (
                version_id,
                memory_id,
                operation.value,
                request.proposal.memory_type.value,
                request.proposal.subject,
                request.proposal.content,
                _hash_content(request.proposal.content),
                canonical.canonical_key_hash,
                canonical.subject_key_hash,
                MEMORY_CANONICALIZATION_VERSION,
                request.proposal.confidence,
                request.session_id,
                self._source_references.session_hash(request.session_id),
                MEMORY_WRITE_POLICY_VERSION,
                now.isoformat(),
            ),
        )
        self._connection.execute(
            """
            INSERT INTO memory_record_states (
                memory_id, state, current_version_id, head_version,
                record_generation, canonical_key_hash, subject_key_hash,
                canonicalization_version, source_kind, created_at, updated_at
            ) VALUES (?, ?, ?, 1, 0, ?, ?, ?, 'automatic', ?, ?)
            """,
            (
                memory_id,
                state.value,
                version_id,
                canonical.canonical_key_hash,
                canonical.subject_key_hash,
                MEMORY_CANONICALIZATION_VERSION,
                now.isoformat(),
                now.isoformat(),
            ),
        )
        return version_id

    def _insert_successor(
        self,
        request: VersionedMemoryCommitRequest,
        policy_result: MemoryCommitPolicyResult,
        *,
        target: MemoryCommitTarget,
        now: datetime,
    ) -> str:
        canonical = policy_result.canonical
        assert canonical is not None
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
            ) VALUES (?, ?, ?, ?, 'auto_supersede', ?, ?, ?, ?, ?, ?, ?, ?, 3,
                      'automatic', ?, ?, ?, ?, NULL, NULL)
            """,
            (
                version_id,
                target.memory_id,
                target.head_version + 1,
                target.current_version_id,
                request.proposal.memory_type.value,
                request.proposal.subject,
                request.proposal.content,
                _hash_content(request.proposal.content),
                canonical.canonical_key_hash,
                canonical.subject_key_hash,
                MEMORY_CANONICALIZATION_VERSION,
                request.proposal.confidence,
                request.session_id,
                self._source_references.session_hash(request.session_id),
                MEMORY_WRITE_POLICY_VERSION,
                now.isoformat(),
            ),
        )
        return version_id

    def _cas_supersede(
        self,
        target: MemoryCommitTarget,
        *,
        result_version_id: str,
        policy_result: MemoryCommitPolicyResult,
        now: datetime,
    ) -> bool:
        canonical = policy_result.canonical
        assert canonical is not None
        cursor = self._connection.execute(
            """
            UPDATE memory_record_states
            SET current_version_id = ?, head_version = ?,
                record_generation = record_generation + 1,
                canonical_key_hash = ?, subject_key_hash = ?,
                canonicalization_version = ?, source_kind = 'automatic',
                updated_at = ?
            WHERE memory_id = ? AND state = 'active'
              AND current_version_id = ? AND head_version = ?
              AND record_generation = ?
            """,
            (
                result_version_id,
                target.head_version + 1,
                canonical.canonical_key_hash,
                canonical.subject_key_hash,
                MEMORY_CANONICALIZATION_VERSION,
                now.isoformat(),
                target.memory_id,
                target.current_version_id,
                target.head_version,
                target.record_generation,
            ),
        )
        return cursor.rowcount == 1

    def _update_projection(
        self,
        *,
        memory_id: str,
        request: VersionedMemoryCommitRequest,
        now: datetime,
    ) -> None:
        self._connection.execute(
            """
            UPDATE memories
            SET content = ?, memory_type = ?, confidence = ?,
                source = 'automatic', status = 'active', updated_at = ?
            WHERE id = ?
            """,
            (
                request.proposal.content,
                request.proposal.memory_type.value,
                request.proposal.confidence,
                now.isoformat(),
                memory_id,
            ),
        )

    def _insert_evidence(
        self,
        request: VersionedMemoryCommitRequest,
        *,
        memory_id: str,
        version_id: str,
        relation: MemoryEvidenceRelation,
        now: datetime,
    ) -> None:
        self._versioned.insert_evidence(
            evidence_id=str(uuid.uuid4()),
            memory_id=memory_id,
            memory_version_id=version_id,
            source_session_id=request.session_id,
            source_message_id=request.user_message_id,
            source_session_reference_hash=self._source_references.session_hash(
                request.session_id
            ),
            source_message_reference_hash=self._source_references.message_hash(
                request.user_message_id
            ),
            source_available=1,
            source_deleted_at=None,
            relation=relation.value,
            observed_at=now.isoformat(),
            extractor_kind=request.extractor_kind.value,
            extractor_provider=request.provider_identifier,
            extractor_model=request.model_identifier,
            confidence=request.proposal.confidence,
            created_at=now.isoformat(),
        )

    def _insert_activity(
        self,
        request: VersionedMemoryCommitRequest,
        *,
        policy_result: MemoryCommitPolicyResult,
        operation_id: str,
        fingerprint: str,
        memory_id: str | None,
        previous_version_id: str | None,
        result_version_id: str | None,
        conflict_id: str | None,
        target: MemoryCommitTarget | None,
        now: datetime,
    ) -> None:
        self._versioned.insert_commit_activity(
            op_id=operation_id,
            job_id=request.job_id,
            proposal_index=request.proposal_index,
            proposal_fingerprint=fingerprint,
            turn_id=request.turn_id,
            memory_id=memory_id,
            previous_version_id=previous_version_id,
            result_version_id=result_version_id,
            conflict_id=conflict_id,
            decision=policy_result.decision.value,
            outcome=policy_result.outcome.value,
            expected_head_version=target.head_version if target else None,
            observed_record_generation=target.record_generation if target else None,
            write_consent_generation=request.authority.write_consent_generation,
            remote_consent_generation=request.authority.remote_consent_generation,
            remote_authority_fingerprint=request.authority.remote_authority_fingerprint,
            governor_version=MEMORY_GOVERNOR_VERSION,
            commit_policy_version=MEMORY_COMMIT_POLICY_VERSION,
            canonicalization_version=MEMORY_CANONICALIZATION_VERSION,
            extractor_kind=request.extractor_kind.value,
            provider_identifier=request.provider_identifier,
            model_identifier=request.model_identifier,
            created_at=now.isoformat(),
            finished_at=now.isoformat(),
        )

    def _record_stale(
        self,
        request: VersionedMemoryCommitRequest,
        *,
        fingerprint: str,
        operation_id: str,
        semantic_attempts: int,
    ) -> VersionedMemoryCommitResult:
        with self._versioned.write_transaction():
            now = _now()
            policy_result = MemoryCommitPolicyResult(
                decision=MemoryGovernorDecision.REJECT,
                outcome=MemoryWriteActivityOutcome.STALE_HEAD,
                reason_code="stale_head",
                target=None,
                canonical=None,
                proposal_fingerprint=fingerprint,
            )
            self._insert_activity(
                request,
                policy_result=policy_result,
                operation_id=operation_id,
                fingerprint=fingerprint,
                memory_id=None,
                previous_version_id=None,
                result_version_id=None,
                conflict_id=None,
                target=None,
                now=now,
            )
        return VersionedMemoryCommitResult(
            decision=MemoryGovernorDecision.REJECT,
            outcome=MemoryWriteActivityOutcome.STALE_HEAD,
            op_id=operation_id,
            proposal_fingerprint=fingerprint,
            memory_id=None,
            previous_version_id=None,
            result_version_id=None,
            conflict_id=None,
            semantic_attempts=semantic_attempts,
            reason_code="stale_head",
        )

    def _authority_outcome(
        self,
        request: VersionedMemoryCommitRequest,
    ) -> MemoryWriteActivityOutcome | None:
        row = self._versioned.get_write_authority()
        if row is None or str(row["status"]) != "granted":
            return MemoryWriteActivityOutcome.SKIPPED_NO_WRITE_CONSENT
        if request.authority.turn_completed_at is not None:
            if row["granted_at"] is None:
                return MemoryWriteActivityOutcome.SKIPPED_NO_WRITE_CONSENT
            granted_at = datetime.fromisoformat(str(row["granted_at"]))
            if granted_at > request.authority.turn_completed_at:
                return MemoryWriteActivityOutcome.SKIPPED_TURN_BEFORE_WRITE_GRANT
        expected_types = json.dumps(
            [memory_type.value for memory_type in MEMORY_ALLOWED_AUTO_TYPES],
            separators=(",", ":"),
        )
        exact = (
            int(row["generation"]) == request.authority.write_consent_generation
            and str(row["purpose"]) == MEMORY_WRITE_PURPOSE
            and str(row["policy_version"]) == MEMORY_WRITE_POLICY_VERSION
            and str(row["allowed_memory_types_version"])
            == MEMORY_ALLOWED_AUTO_TYPES_VERSION
            and str(row["allowed_memory_types_json"]) == expected_types
            and str(row["retention_disclosure_version"])
            == MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION
        )
        return None if exact else MemoryWriteActivityOutcome.SKIPPED_WRITE_CONSENT_CHANGED

    def _remote_authority_outcome(
        self,
        request: VersionedMemoryCommitRequest,
    ) -> MemoryWriteActivityOutcome | None:
        if request.extractor_kind is not MemoryEvidenceExtractorKind.REMOTE:
            return None
        if (
            request.authority.remote_consent_generation is None
            or request.authority.remote_authority_fingerprint is None
            or not request.provider_identifier
        ):
            return MemoryWriteActivityOutcome.SKIPPED_NO_CONSENT
        row = self._versioned.get_remote_authority()
        if row is None or str(row["status"]) != "granted":
            return MemoryWriteActivityOutcome.SKIPPED_CONSENT_CHANGED
        try:
            fields = json.loads(str(row["disclosed_fields_json"]))
            disclosed_fields = tuple(str(field) for field in fields)
        except (TypeError, ValueError, json.JSONDecodeError):
            return MemoryWriteActivityOutcome.SKIPPED_CONSENT_CHANGED
        if not (
            int(row["generation"])
            == request.authority.remote_consent_generation
            and str(row["purpose"]) == MEMORY_EXTRACTION_PURPOSE
            and str(row["provider"]) == request.provider_identifier
            and str(row["disclosure_version"])
            == MEMORY_EXTRACTION_DISCLOSURE_VERSION
            and disclosed_fields == MEMORY_EXTRACTION_DISCLOSED_FIELDS
        ):
            return MemoryWriteActivityOutcome.SKIPPED_CONSENT_CHANGED
        fingerprint = memory_remote_authority_fingerprint(
            generation=int(row["generation"]),
            purpose=str(row["purpose"]),
            provider=str(row["provider"]),
            disclosure_version=str(row["disclosure_version"]),
            disclosed_fields=disclosed_fields,
        )
        if fingerprint != request.authority.remote_authority_fingerprint:
            return MemoryWriteActivityOutcome.SKIPPED_CONSENT_CHANGED
        return None

    def _job_was_cancelled_for_session_deletion(self, job_id: str) -> bool:
        row = self._connection.execute(
            "SELECT status, outcome FROM memory_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        return row is not None and (
            str(row["status"]) == "cancelled"
            and str(row["outcome"]) == "cancelled_session_deleted"
        )

    @staticmethod
    def _deletion_snapshot_matches(
        request: VersionedMemoryCommitRequest,
        current: DeletionGenerationSnapshot,
    ) -> bool:
        return (
            current.global_generation
            == request.deletion_snapshot.global_generation
            and current.session_generation
            == request.deletion_snapshot.session_generation
            and current.type_generations.get(request.proposal.memory_type, 0)
            == request.deletion_snapshot.type_generations.get(
                request.proposal.memory_type,
                0,
            )
        )

    @staticmethod
    def _target_snapshot_matches(
        expected: tuple[MemoryCommitTarget, ...],
        current: list[MemoryCommitTarget],
    ) -> bool:
        expected_by_id = {target.memory_id: target for target in expected}
        current_by_id = {target.memory_id: target for target in current}
        return expected_by_id == current_by_id

    @staticmethod
    def _retryable(exc: sqlite3.OperationalError) -> bool:
        message = str(exc).lower()
        return "locked" in message or "busy" in message or "snapshot" in message
