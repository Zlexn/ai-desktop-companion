from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable
import time

from app.domain.models import (
    ChatRole,
    MemoryAutomationMode,
    MemoryEvidenceExtractorKind,
    MemoryExtractionConsent,
    MemoryExtractionConsentStatus,
    MemoryExtractorRoute,
    MemoryGovernorDecision,
    MemoryJob,
    MemoryJobAuditOutcome,
    MemoryJobStatus,
    MemoryType,
    MemoryWriteActivityOutcome,
)
from app.repositories.memory_automation import MemoryAutomationRepository
from app.repositories.messages import MessageRepository
from app.repositories.versioned_memories import DeletionGenerationSnapshot
from app.services.memory_extraction_dispatch import (
    MEMORY_EXTRACTION_DISCLOSED_FIELDS,
    MEMORY_EXTRACTION_DISCLOSURE_VERSION,
    MEMORY_EXTRACTION_PURPOSE,
    MemoryExtractionDispatchFence,
)
from app.services.memory_extractor import (
    MEMORY_EXTRACTION_SCHEMA_VERSION,
    MemoryExtractionInvalidOutputError,
    MemoryExtractionResult,
    MemoryExtractor,
)
from app.services.memory_governor import MEMORY_GOVERNOR_VERSION, MemoryGovernor
from app.services.memory_source_reference import MemorySourceReferenceService
from app.services.memory_gate_b_contract import (
    MEMORY_ALLOWED_AUTO_TYPES_VERSION,
    MEMORY_AUTO_ACTIVE_SCHEMA_VERSION,
    MEMORY_CANONICALIZATION_VERSION,
    MEMORY_COMMIT_POLICY_VERSION,
)
from app.services.memory_write_dispatch import (
    MemoryWriteDispatcher,
    RemoteAuthoritySnapshot,
)
from app.services.session_deletion_coordinator import SessionDeletionFence
from app.services.versioned_memory_commit import (
    VersionedMemoryCommitRequest,
    VersionedMemoryCommitResult,
    WriteAuthoritySnapshot,
)


_TERMINAL_STATUSES = {
    MemoryJobStatus.SUCCEEDED,
    MemoryJobStatus.FAILED,
    MemoryJobStatus.CANCELLED,
}


class _ActiveMemoryProviderError(RuntimeError):
    pass


class _SessionDeletedDuringDispatch(RuntimeError):
    pass


def auto_active_job_is_compatible(
    job: MemoryJob,
    *,
    route: MemoryExtractorRoute,
) -> bool:
    snapshot = job.auto_active_snapshot
    return (
        job.mode is MemoryAutomationMode.AUTO_ACTIVE
        and job.schema_version == MEMORY_AUTO_ACTIVE_SCHEMA_VERSION
        and job.extractor_route is route
        and job.governor_version == MEMORY_GOVERNOR_VERSION
        and snapshot is not None
        and snapshot.reserved_mode is MemoryAutomationMode.AUTO_ACTIVE
        and snapshot.workflow_version == MEMORY_AUTO_ACTIVE_SCHEMA_VERSION
        and snapshot.extractor_route is route
        and snapshot.governor_version == MEMORY_GOVERNOR_VERSION
        and snapshot.commit_policy_version == MEMORY_COMMIT_POLICY_VERSION
        and snapshot.canonicalization_version == MEMORY_CANONICALIZATION_VERSION
        and snapshot.allowed_memory_types_version
        == MEMORY_ALLOWED_AUTO_TYPES_VERSION
    )


def memory_job_is_compatible(
    job: MemoryJob,
    *,
    mode: MemoryAutomationMode,
    route: MemoryExtractorRoute,
) -> bool:
    if mode is MemoryAutomationMode.SHADOW_AUTO:
        return (
            job.mode is MemoryAutomationMode.SHADOW_AUTO
            and job.schema_version == MEMORY_EXTRACTION_SCHEMA_VERSION
            and job.extractor_route is route
            and job.governor_version == MEMORY_GOVERNOR_VERSION
            and job.auto_active_snapshot is None
        )
    if mode is MemoryAutomationMode.AUTO_ACTIVE:
        return auto_active_job_is_compatible(job, route=route)
    return False


class AutoActiveMemoryJobService:
    def __init__(
        self,
        *,
        automation: MemoryAutomationRepository,
        messages: MessageRepository,
        extractor: MemoryExtractor | None,
        governor: MemoryGovernor,
        route: MemoryExtractorRoute,
        dispatcher: MemoryWriteDispatcher,
        source_references: MemorySourceReferenceService,
        commit_one: Callable[
            [VersionedMemoryCommitRequest], VersionedMemoryCommitResult
        ],
        commit_targets: Callable[[], list] | None = None,
        deletion_fence: SessionDeletionFence | None = None,
    ) -> None:
        self._automation = automation
        self._messages = messages
        self._extractor = extractor
        self._governor = governor
        self._route = route
        self._dispatcher = dispatcher
        self._source_references = source_references
        self._commit_one = commit_one
        self._commit_targets = commit_targets or (lambda: [])
        self._deletion_fence = deletion_fence or SessionDeletionFence()

    async def process(self, job_id: str) -> MemoryJob:
        try:
            return await self._process(job_id)
        except asyncio.CancelledError:
            self._automation.cancel_job(job_id)
            raise

    async def _process(self, job_id: str) -> MemoryJob:
        job = self._automation.require_job(job_id)
        if job.status in _TERMINAL_STATUSES:
            return job
        if not self.is_compatible(job):
            return self._complete_empty(
                job,
                status=MemoryJobStatus.SUCCEEDED,
                outcome=MemoryJobAuditOutcome.SKIPPED_MODE_CHANGED,
            )
        snapshot = job.auto_active_snapshot
        assert snapshot is not None
        turn = self._load_validated_turn(job)
        if turn is None:
            return self._complete_empty(
                job,
                status=MemoryJobStatus.FAILED,
                outcome=MemoryJobAuditOutcome.FAILED,
                error_category="invalid_job_input",
            )
        user_message, assistant_message = turn
        snapshot = job.auto_active_snapshot
        assert snapshot is not None
        self._automation.update_job_status(job.id, status=MemoryJobStatus.RUNNING)

        preflight = self._governor.preflight_turn(
            user_text=user_message.content,
            assistant_text=assistant_message.content,
        )
        if preflight is not None:
            return self._complete_empty(
                job,
                status=MemoryJobStatus.SUCCEEDED,
                outcome=MemoryJobAuditOutcome.SKIPPED_GOVERNOR_POLICY,
                redaction_count=preflight.redaction_count,
            )
        if self._route is MemoryExtractorRoute.NONE or self._extractor is None:
            return self._complete_empty(
                job,
                status=MemoryJobStatus.SUCCEEDED,
                outcome=MemoryJobAuditOutcome.SKIPPED_NO_EXTRACTOR,
            )

        started_at = time.perf_counter()
        expected_targets = self._commit_targets()

        async def extract() -> MemoryExtractionResult:
            assert self._extractor is not None
            try:
                with self._deletion_fence.hold(
                    snapshot.source_session_reference_hash
                ):
                    current = self._automation.require_job(job.id)
                    if (
                        current.status is MemoryJobStatus.CANCELLED
                        and current.outcome
                        is MemoryJobAuditOutcome.CANCELLED_SESSION_DELETED
                    ):
                        raise _SessionDeletedDuringDispatch
                    return await self._extractor.extract(
                        user_message=user_message,
                        assistant_message=assistant_message,
                    )
            except MemoryExtractionInvalidOutputError:
                raise
            except _SessionDeletedDuringDispatch:
                raise
            except Exception as exc:
                raise _ActiveMemoryProviderError from exc

        async def prepare(extracted: MemoryExtractionResult):
            results = self._governor.evaluate_many(
                proposals=extracted.proposals,
                user_text=user_message.content,
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
            )
            return extracted, results

        async def commit(
            prepared,
            authority: WriteAuthoritySnapshot,
            _remote_authority: RemoteAuthoritySnapshot | None,
        ) -> list[VersionedMemoryCommitResult]:
            extracted, governor_results = prepared
            deletion_snapshot = DeletionGenerationSnapshot(
                global_generation=snapshot.global_deletion_generation,
                session_generation=snapshot.session_deletion_generation,
                type_generations={
                    MemoryType(key): value
                    for key, value in snapshot.type_deletion_generations.items()
                },
            )
            extractor_kind = MemoryEvidenceExtractorKind(self._route.value)
            committed: list[VersionedMemoryCommitResult] = []
            current_targets = expected_targets
            for index, (proposal, governor_result) in enumerate(
                zip(extracted.proposals, governor_results, strict=True)
            ):
                result = self._commit_one(
                    VersionedMemoryCommitRequest(
                        job_id=job.id,
                        turn_id=job.turn_id,
                        proposal_index=index,
                        proposal=proposal,
                        governor_result=governor_result,
                        session_id=job.session_id,
                        user_message_id=job.user_message_id,
                        user_text=user_message.content,
                        extractor_kind=extractor_kind,
                        provider_identifier=extracted.provider,
                        model_identifier=extracted.model,
                        authority=authority,
                        deletion_snapshot=deletion_snapshot,
                        expected_targets=current_targets,
                    )
                )
                committed.append(result)
                if result.resulting_targets is not None:
                    current_targets = result.resulting_targets
            return committed

        expected_authority = WriteAuthoritySnapshot(
            write_consent_generation=snapshot.write_consent_generation,
            remote_consent_generation=snapshot.remote_consent_generation,
            remote_authority_fingerprint=snapshot.remote_authority_fingerprint,
            turn_completed_at=snapshot.turn_completed_at,
        )
        try:
            dispatch_result = await self._dispatcher.dispatch(
                route=self._route,
                turn_completed_at=snapshot.turn_completed_at,
                extract=extract,
                prepare_for_commit=prepare,
                commit=commit,
                expected_authority=expected_authority,
            )
        except _SessionDeletedDuringDispatch:
            return self._automation.require_job(job.id)
        except MemoryExtractionInvalidOutputError:
            return self._complete_error(
                job,
                outcome=MemoryJobAuditOutcome.INVALID_OUTPUT,
                error_category="invalid_output",
                elapsed_ms=self._elapsed_ms(started_at),
            )
        except _ActiveMemoryProviderError:
            return self._complete_error(
                job,
                outcome=MemoryJobAuditOutcome.PROVIDER_ERROR,
                error_category="provider_error",
                elapsed_ms=self._elapsed_ms(started_at),
            )
        except Exception:
            return self._complete_error(
                job,
                outcome=MemoryJobAuditOutcome.FAILED,
                error_category="database_error",
                elapsed_ms=self._elapsed_ms(started_at),
            )

        if dispatch_result.outcome is not None:
            return self._complete_empty(
                job,
                status=MemoryJobStatus.SUCCEEDED,
                outcome=self._job_outcome(dispatch_result.outcome),
                elapsed_ms=self._elapsed_ms(started_at),
            )
        extracted = dispatch_result.extraction
        results = dispatch_result.commit_result
        assert extracted is not None and results is not None
        decision_counts = Counter(result.decision.value for result in results)
        reason_counts = Counter(
            result.reason_code or result.outcome.value for result in results
        )
        outcome_counts = Counter(result.outcome.value for result in results)
        accepted_count = sum(
            result.decision is not MemoryGovernorDecision.REJECT for result in results
        )
        completed, _ = self._automation.complete_job_with_audit(
            job.id,
            status=MemoryJobStatus.SUCCEEDED,
            outcome=MemoryJobAuditOutcome.COMPLETED_WITH_DECISIONS,
            decision_counts=dict(decision_counts),
            reason_counts=dict(reason_counts),
            outcome_counts=dict(outcome_counts),
            proposal_count=len(results),
            accepted_count=accepted_count,
            rejected_count=len(results) - accepted_count,
            redaction_count=0,
            provider=extracted.provider,
            model=extracted.model,
            elapsed_ms=self._elapsed_ms(started_at),
            consent_generation=snapshot.write_consent_generation,
        )
        return completed

    def is_compatible(self, job: MemoryJob) -> bool:
        return auto_active_job_is_compatible(job, route=self._route)

    def _load_validated_turn(self, job: MemoryJob):
        snapshot = job.auto_active_snapshot
        if snapshot is None:
            return None
        user_message = self._messages.get(job.user_message_id)
        assistant_message = self._messages.get(job.assistant_message_id)
        if (
            user_message is None
            or assistant_message is None
            or user_message.id != job.user_message_id
            or assistant_message.id != job.assistant_message_id
            or user_message.session_id != job.session_id
            or assistant_message.session_id != job.session_id
            or user_message.role is not ChatRole.USER
            or assistant_message.role is not ChatRole.ASSISTANT
            or job.turn_id != assistant_message.id
            or self._source_hashes_do_not_match(
                snapshot,
                session_id=job.session_id,
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
            )
            or assistant_message.created_at != snapshot.turn_completed_at
        ):
            return None
        return user_message, assistant_message

    def _source_hashes_do_not_match(
        self,
        snapshot,
        *,
        session_id: str,
        user_message_id: str,
        assistant_message_id: str,
    ) -> bool:
        return not (
            snapshot.source_session_reference_hash
            == self._source_references.session_hash(session_id)
            and snapshot.source_user_message_reference_hash
            == self._source_references.message_hash(user_message_id)
            and snapshot.source_assistant_message_reference_hash
            == self._source_references.message_hash(assistant_message_id)
        )

    @staticmethod
    def _job_outcome(outcome: MemoryWriteActivityOutcome) -> MemoryJobAuditOutcome:
        mapping = {
            MemoryWriteActivityOutcome.SKIPPED_NO_WRITE_CONSENT:
                MemoryJobAuditOutcome.SKIPPED_NO_WRITE_CONSENT,
            MemoryWriteActivityOutcome.SKIPPED_WRITE_CONSENT_CHANGED:
                MemoryJobAuditOutcome.SKIPPED_WRITE_CONSENT_CHANGED,
            MemoryWriteActivityOutcome.SKIPPED_TURN_BEFORE_WRITE_GRANT:
                MemoryJobAuditOutcome.SKIPPED_TURN_BEFORE_WRITE_GRANT,
            MemoryWriteActivityOutcome.SKIPPED_NO_CONSENT:
                MemoryJobAuditOutcome.SKIPPED_NO_CONSENT,
            MemoryWriteActivityOutcome.SKIPPED_CONSENT_CHANGED:
                MemoryJobAuditOutcome.SKIPPED_CONSENT_CHANGED,
        }
        return mapping[outcome]

    def _complete_error(
        self,
        job: MemoryJob,
        *,
        outcome: MemoryJobAuditOutcome,
        error_category: str,
        elapsed_ms: int,
    ) -> MemoryJob:
        return self._complete_empty(
            job,
            status=MemoryJobStatus.FAILED,
            outcome=outcome,
            error_category=error_category,
            elapsed_ms=elapsed_ms,
        )

    def _complete_empty(
        self,
        job: MemoryJob,
        *,
        status: MemoryJobStatus,
        outcome: MemoryJobAuditOutcome,
        error_category: str | None = None,
        redaction_count: int = 0,
        elapsed_ms: int | None = None,
    ) -> MemoryJob:
        completed, _ = self._automation.complete_job_with_audit(
            job.id,
            status=status,
            outcome=outcome,
            decision_counts={},
            reason_counts={},
            outcome_counts={},
            proposal_count=0,
            accepted_count=0,
            rejected_count=0,
            redaction_count=redaction_count,
            provider=None,
            model=None,
            elapsed_ms=elapsed_ms,
            consent_generation=(
                job.auto_active_snapshot.write_consent_generation
                if job.auto_active_snapshot is not None
                else None
            ),
            error_category=error_category,
        )
        return completed

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return max(0, int((time.perf_counter() - started_at) * 1_000))


class MemoryJobService:
    def __init__(
        self,
        *,
        automation: MemoryAutomationRepository,
        messages: MessageRepository,
        extractor: MemoryExtractor | None,
        governor: MemoryGovernor,
        route: MemoryExtractorRoute,
        provider_name: str,
        dispatch_fence: MemoryExtractionDispatchFence,
    ) -> None:
        self._automation = automation
        self._messages = messages
        self._extractor = extractor
        self._governor = governor
        self._route = route
        self._provider_name = provider_name
        self._dispatch_fence = dispatch_fence

    async def process(self, job_id: str) -> MemoryJob:
        try:
            return await self._process(job_id)
        except asyncio.CancelledError:
            self._automation.cancel_job(job_id)
            raise

    async def _process(self, job_id: str) -> MemoryJob:
        job = self._automation.require_job(job_id)
        if job.status in _TERMINAL_STATUSES:
            return job

        turn = self._load_validated_turn(job)
        if turn is None:
            return self._complete_empty(
                job,
                status=MemoryJobStatus.FAILED,
                outcome=MemoryJobAuditOutcome.FAILED,
                error_category="invalid_job_input",
            )
        user_message, assistant_message = turn

        self._automation.update_job_status(job.id, status=MemoryJobStatus.RUNNING)

        preflight = self._governor.preflight_turn(
            user_text=user_message.content,
            assistant_text=assistant_message.content,
        )
        if preflight is not None:
            return self._complete_empty(
                job,
                status=MemoryJobStatus.SUCCEEDED,
                outcome=MemoryJobAuditOutcome.SKIPPED_GOVERNOR_POLICY,
                redaction_count=preflight.redaction_count,
            )

        if self._route is MemoryExtractorRoute.NONE or self._extractor is None:
            return self._complete_empty(
                job,
                status=MemoryJobStatus.SUCCEEDED,
                outcome=MemoryJobAuditOutcome.SKIPPED_NO_EXTRACTOR,
            )

        consent: MemoryExtractionConsent | None = None
        started_at = time.perf_counter()
        if self._route is MemoryExtractorRoute.REMOTE:
            consent = self._automation.get_consent()
            if not self._has_exact_consent(consent):
                return self._complete_empty(
                    job,
                    status=MemoryJobStatus.SUCCEEDED,
                    outcome=MemoryJobAuditOutcome.SKIPPED_NO_CONSENT,
                    consent_generation=consent.generation,
                )

            async with self._dispatch_fence.hold() as may_send:
                if not may_send:
                    return self._complete_empty(
                        job,
                        status=MemoryJobStatus.SUCCEEDED,
                        outcome=MemoryJobAuditOutcome.SKIPPED_CONSENT_CHANGED,
                        consent_generation=consent.generation,
                    )
                latest = self._automation.get_consent()
                if not self._same_authority(consent, latest):
                    return self._complete_empty(
                        job,
                        status=MemoryJobStatus.SUCCEEDED,
                        outcome=MemoryJobAuditOutcome.SKIPPED_CONSENT_CHANGED,
                        consent_generation=latest.generation,
                    )
                try:
                    extracted = await self._extractor.extract(
                        user_message=user_message,
                        assistant_message=assistant_message,
                    )
                except MemoryExtractionInvalidOutputError:
                    return self._complete_error(
                        job,
                        outcome=MemoryJobAuditOutcome.INVALID_OUTPUT,
                        error_category="invalid_output",
                        elapsed_ms=self._elapsed_ms(started_at),
                        consent_generation=latest.generation,
                    )
                except Exception:
                    return self._complete_error(
                        job,
                        outcome=MemoryJobAuditOutcome.PROVIDER_ERROR,
                        error_category="provider_error",
                        elapsed_ms=self._elapsed_ms(started_at),
                        consent_generation=latest.generation,
                    )

                after = self._automation.get_consent()
                if (
                    self._dispatch_fence.has_pending_consent_mutation()
                    or not self._same_authority(latest, after)
                ):
                    return self._complete_empty(
                        job,
                        status=MemoryJobStatus.SUCCEEDED,
                        outcome=MemoryJobAuditOutcome.SKIPPED_CONSENT_CHANGED,
                        consent_generation=after.generation,
                    )
                consent = after
        else:
            try:
                extracted = await self._extractor.extract(
                    user_message=user_message,
                    assistant_message=assistant_message,
                )
            except MemoryExtractionInvalidOutputError:
                return self._complete_error(
                    job,
                    outcome=MemoryJobAuditOutcome.INVALID_OUTPUT,
                    error_category="invalid_output",
                    elapsed_ms=self._elapsed_ms(started_at),
                )
            except Exception:
                return self._complete_error(
                    job,
                    outcome=MemoryJobAuditOutcome.PROVIDER_ERROR,
                    error_category="provider_error",
                    elapsed_ms=self._elapsed_ms(started_at),
                )

        return self._record_shadow(
            job,
            extracted=extracted,
            user_text=user_message.content,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            consent_generation=consent.generation if consent is not None else None,
            elapsed_ms=self._elapsed_ms(started_at),
        )

    def _load_validated_turn(self, job: MemoryJob):
        user_message = self._messages.get(job.user_message_id)
        assistant_message = self._messages.get(job.assistant_message_id)
        if (
            user_message is None
            or assistant_message is None
            or user_message.id != job.user_message_id
            or assistant_message.id != job.assistant_message_id
            or user_message.session_id != job.session_id
            or assistant_message.session_id != job.session_id
            or user_message.role is not ChatRole.USER
            or assistant_message.role is not ChatRole.ASSISTANT
            or job.turn_id != job.assistant_message_id
            or job.extractor_route is not self._route
        ):
            return None
        return user_message, assistant_message

    def _has_exact_consent(self, consent: MemoryExtractionConsent) -> bool:
        return (
            consent.status is MemoryExtractionConsentStatus.GRANTED
            and consent.purpose == MEMORY_EXTRACTION_PURPOSE
            and consent.provider == self._provider_name
            and consent.disclosure_version == MEMORY_EXTRACTION_DISCLOSURE_VERSION
            and consent.disclosed_fields == MEMORY_EXTRACTION_DISCLOSED_FIELDS
        )

    def _same_authority(
        self,
        before: MemoryExtractionConsent,
        after: MemoryExtractionConsent,
    ) -> bool:
        return (
            before.generation == after.generation
            and before.status is after.status
            and before.purpose == after.purpose
            and before.provider == after.provider
            and before.disclosure_version == after.disclosure_version
            and before.disclosed_fields == after.disclosed_fields
            and self._has_exact_consent(after)
        )

    def _record_shadow(
        self,
        job: MemoryJob,
        *,
        extracted: MemoryExtractionResult,
        user_text: str,
        user_message_id: str,
        assistant_message_id: str,
        consent_generation: int | None,
        elapsed_ms: int,
    ) -> MemoryJob:
        results = self._governor.evaluate_many(
            proposals=extracted.proposals,
            user_text=user_text,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
        )
        decision_counts = Counter(result.decision.value for result in results)
        reason_counts = Counter(result.reason_code for result in results)
        accepted_count = sum(
            result.decision is MemoryGovernorDecision.CREATE for result in results
        )
        completed, _ = self._automation.complete_job_with_audit(
            job.id,
            status=MemoryJobStatus.SUCCEEDED,
            outcome=MemoryJobAuditOutcome.SHADOW_RECORDED,
            decision_counts=dict(decision_counts),
            reason_counts=dict(reason_counts),
            proposal_count=len(results),
            accepted_count=accepted_count,
            rejected_count=len(results) - accepted_count,
            redaction_count=sum(result.redaction_count for result in results),
            provider=extracted.provider,
            model=extracted.model,
            elapsed_ms=elapsed_ms,
            consent_generation=consent_generation,
        )
        return completed

    def _complete_error(
        self,
        job: MemoryJob,
        *,
        outcome: MemoryJobAuditOutcome,
        error_category: str,
        elapsed_ms: int,
        consent_generation: int | None = None,
    ) -> MemoryJob:
        return self._complete_empty(
            job,
            status=MemoryJobStatus.FAILED,
            outcome=outcome,
            error_category=error_category,
            elapsed_ms=elapsed_ms,
            consent_generation=consent_generation,
        )

    def _complete_empty(
        self,
        job: MemoryJob,
        *,
        status: MemoryJobStatus,
        outcome: MemoryJobAuditOutcome,
        error_category: str | None = None,
        redaction_count: int = 0,
        elapsed_ms: int | None = None,
        consent_generation: int | None = None,
    ) -> MemoryJob:
        completed, _ = self._automation.complete_job_with_audit(
            job.id,
            status=status,
            outcome=outcome,
            decision_counts={},
            reason_counts={},
            proposal_count=0,
            accepted_count=0,
            rejected_count=0,
            redaction_count=redaction_count,
            provider=None,
            model=None,
            elapsed_ms=elapsed_ms,
            consent_generation=consent_generation,
            error_category=error_category,
        )
        return completed

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return max(0, int((time.perf_counter() - started_at) * 1_000))
