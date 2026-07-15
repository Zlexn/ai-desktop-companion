from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from time import perf_counter
from typing import Protocol

from app.domain.models import (
    EmotionAnalysisAuditOutcome,
    EmotionAnalysisConsentStatus,
    EmotionAnalysisJobStatus,
    EMOTION_MAX_DELTA,
    EmotionEventType,
    EmotionState,
    EmotionVector,
    Memory,
    Message,
)
from app.repositories.emotion_analysis import EmotionAnalysisRepository
from app.repositories.emotions import EmotionRepository, EmotionVersionConflictError
from app.services.emotion_analysis_analyzer import (
    EMOTION_ANALYSIS_SCHEMA_VERSION,
    EmotionAnalysisParseError,
    EmotionAnalysisProposal,
)
from app.services.emotion_analysis_dispatch import EmotionAnalysisDispatchFence
from app.services.emotion_analysis_input import EmotionAnalysisInput, EmotionAnalysisInputBuilder
from app.services.emotion_policy import EmotionPolicy

_MAX_CAS_ATTEMPTS = 3
_RULE_VERSION = "emotion-policy-v1+emotion-analysis-v1"
_DISCLOSURE_VERSION = "emotion-analysis-disclosure-v1"


class EmotionAnalyzer(Protocol):
    async def analyze(self, analysis_input: EmotionAnalysisInput) -> EmotionAnalysisProposal: ...


class EmotionAnalysisService:
    def __init__(
        self,
        *,
        enabled: bool,
        provider_name: str,
        model: str,
        policy_fingerprint: str,
        analysis_repository: EmotionAnalysisRepository,
        emotion_repository: EmotionRepository,
        policy: EmotionPolicy,
        input_builder: EmotionAnalysisInputBuilder,
        analyzer: EmotionAnalyzer,
        dispatch_fence: EmotionAnalysisDispatchFence | None = None,
    ) -> None:
        self._enabled = enabled
        self._provider_name = provider_name
        self._model = model
        self._policy_fingerprint = policy_fingerprint
        self._analysis_repository = analysis_repository
        self._emotion_repository = emotion_repository
        self._policy = policy
        self._input_builder = input_builder
        self._analyzer = analyzer
        self._dispatch_fence = dispatch_fence or EmotionAnalysisDispatchFence()

    async def process_turn(
        self,
        *,
        session_id: str,
        user_message: Message,
        assistant_message: Message,
        recent_messages: list[Message],
        relevant_memories: list[Memory],
        base_emotion_version: int | None = None,
    ) -> EmotionState | None:
        if not self._enabled:
            return None
        state = self._emotion_repository.get_or_create()
        if not state.enabled:
            return None
        consent = self._analysis_repository.get_consent()
        if not self._consent_allows_dispatch(consent):
            return None

        job, created = self._analysis_repository.reserve_job(
            source_session_id=session_id,
            source_user_message_id=user_message.id,
            source_assistant_message_id=assistant_message.id,
            schema_version=EMOTION_ANALYSIS_SCHEMA_VERSION,
            base_emotion_version=(
                state.version
                if base_emotion_version is None
                else base_emotion_version
            ),
            consent_generation=consent.generation,
        )
        if not created:
            return None

        analysis_input = self._input_builder.build(
            current_user_message=user_message,
            current_assistant_message=assistant_message,
            recent_messages=recent_messages,
            relevant_memories=relevant_memories,
        )
        started = perf_counter()
        try:
            async with self._dispatch_fence.hold() as dispatch_allowed:
                if not dispatch_allowed or not self._can_dispatch(job.consent_generation):
                    self._skip_revoked(
                        job_id=job.id,
                        session_id=session_id,
                        user_message=user_message,
                        assistant_message=assistant_message,
                        analysis_input=analysis_input,
                    )
                    return None
                self._analysis_repository.update_job_status(
                    job.id,
                    status=EmotionAnalysisJobStatus.RUNNING,
                    outcome_reason=None,
                )
                proposal = await self._analyzer.analyze(analysis_input)
        except asyncio.CancelledError:
            self._fail_job(
                job_id=job.id,
                outcome=EmotionAnalysisAuditOutcome.FAILED,
                reason_code="interrupted",
                session_id=session_id,
                user_message=user_message,
                assistant_message=assistant_message,
                analysis_input=analysis_input,
                started=started,
            )
            raise
        except EmotionAnalysisParseError:
            self._fail_job(
                job_id=job.id,
                outcome=EmotionAnalysisAuditOutcome.INVALID_OUTPUT,
                reason_code="invalid_output",
                session_id=session_id,
                user_message=user_message,
                assistant_message=assistant_message,
                analysis_input=analysis_input,
                started=started,
            )
            return None
        except Exception:
            self._fail_job(
                job_id=job.id,
                outcome=EmotionAnalysisAuditOutcome.PROVIDER_ERROR,
                reason_code="provider_error",
                session_id=session_id,
                user_message=user_message,
                assistant_message=assistant_message,
                analysis_input=analysis_input,
                started=started,
            )
            return None

        if (
            self._dispatch_fence.has_pending_consent_mutation()
            or not self._can_dispatch(job.consent_generation)
        ):
            self._skip_revoked(
                job_id=job.id,
                session_id=session_id,
                user_message=user_message,
                assistant_message=assistant_message,
                analysis_input=analysis_input,
            )
            return None

        if not proposal.should_apply:
            return self._complete_no_change(
                job_id=job.id,
                session_id=session_id,
                user_message=user_message,
                assistant_message=assistant_message,
                analysis_input=analysis_input,
                started=started,
            )

        return self._complete_proposal(
            job_id=job.id,
            proposal=proposal,
            base_emotion_version=job.base_emotion_version,
            session_id=session_id,
            user_message=user_message,
            assistant_message=assistant_message,
            analysis_input=analysis_input,
            started=started,
        )

    def _complete_no_change(
        self,
        *,
        job_id: str,
        session_id: str,
        user_message: Message,
        assistant_message: Message,
        analysis_input: EmotionAnalysisInput,
        started: float,
    ) -> EmotionState:
        with self._analysis_repository.transaction():
            self._analysis_repository.update_job_status(
                job_id,
                status=EmotionAnalysisJobStatus.SUCCEEDED,
                outcome_reason="no_change",
            )
            self._append_audit(
                job_id=job_id,
                outcome=EmotionAnalysisAuditOutcome.NO_CHANGE,
                session_id=session_id,
                user_message=user_message,
                assistant_message=assistant_message,
                analysis_input=analysis_input,
                elapsed_ms=self._elapsed_ms(started),
                reason_code="no_change",
            )
        return self._emotion_repository.get_or_create()

    def _complete_proposal(
        self,
        *,
        job_id: str,
        proposal: EmotionAnalysisProposal,
        base_emotion_version: int,
        session_id: str,
        user_message: Message,
        assistant_message: Message,
        analysis_input: EmotionAnalysisInput,
        started: float,
    ) -> EmotionState:
        self._emotion_repository.begin_transaction()
        try:
            with self._analysis_repository.transaction():
                updated, applied = self._apply_proposal(
                    proposal=proposal,
                    base_emotion_version=base_emotion_version,
                    session_id=session_id,
                    user_message=user_message,
                    assistant_message=assistant_message,
                )
                outcome = EmotionAnalysisAuditOutcome.APPLIED if applied else EmotionAnalysisAuditOutcome.NO_CHANGE
                reason_code = "applied" if applied else "no_change"
                self._analysis_repository.update_job_status(
                    job_id,
                    status=EmotionAnalysisJobStatus.SUCCEEDED,
                    outcome_reason=reason_code,
                )
                self._append_audit(
                    job_id=job_id,
                    outcome=outcome,
                    session_id=session_id,
                    user_message=user_message,
                    assistant_message=assistant_message,
                    analysis_input=analysis_input,
                    elapsed_ms=self._elapsed_ms(started),
                    reason_code=reason_code,
                )
        finally:
            self._emotion_repository.end_transaction()
        return updated

    def _can_dispatch(self, expected_generation: int) -> bool:
        consent = self._analysis_repository.get_consent()
        return (
            self._consent_allows_dispatch(consent)
            and consent.generation == expected_generation
            and self._emotion_repository.get_or_create().enabled
        )

    def _skip_revoked(
        self,
        *,
        job_id: str,
        session_id: str,
        user_message: Message,
        assistant_message: Message,
        analysis_input: EmotionAnalysisInput,
    ) -> None:
        with self._analysis_repository.transaction():
            self._analysis_repository.update_job_status(
                job_id,
                status=EmotionAnalysisJobStatus.SKIPPED,
                outcome_reason="consent_revoked",
            )
            self._append_audit(
                job_id=job_id,
                outcome=EmotionAnalysisAuditOutcome.REVOKED,
                session_id=session_id,
                user_message=user_message,
                assistant_message=assistant_message,
                analysis_input=analysis_input,
                elapsed_ms=0,
                reason_code="consent_revoked",
            )

    def _consent_allows_dispatch(self, consent) -> bool:
        return (
            consent.status is EmotionAnalysisConsentStatus.GRANTED
            and consent.provider == self._provider_name
            and consent.disclosure_version == _DISCLOSURE_VERSION
            and consent.policy_fingerprint == self._policy_fingerprint
        )

    def _apply_proposal(
        self,
        *,
        proposal: EmotionAnalysisProposal,
        base_emotion_version: int,
        session_id: str,
        user_message: Message,
        assistant_message: Message,
    ) -> tuple[EmotionState, bool]:
        for _ in range(_MAX_CAS_ATTEMPTS):
            current = self._emotion_repository.get_or_create()
            if current.version != base_emotion_version:
                return current, False
            if not current.enabled:
                return current, False
            proposed_delta = self._protect_local_turn_directions(
                proposal.proposed_delta,
                user_message=user_message,
                assistant_message=assistant_message,
                current=current,
            )
            proposed_delta = self._share_turn_delta_budget(
                proposed_delta,
                assistant_message=assistant_message,
            )
            after = self._policy.apply_delta(current.vector, proposed_delta)
            if after == current.vector:
                return current, False
            try:
                return (
                    self._emotion_repository.apply_transition(
                        expected_version=current.version,
                        after=after,
                        event_type=EmotionEventType.TRANSITION,
                        reason_codes=proposal.reason_codes,
                        source_session_id=session_id,
                        source_user_message_id=user_message.id,
                        source_assistant_message_id=assistant_message.id,
                        engine="llm_assisted",
                        rule_version=_RULE_VERSION,
                    ),
                    True,
                )
            except EmotionVersionConflictError:
                continue
        return self._emotion_repository.get_or_create(), False

    def _protect_local_turn_directions(
        self,
        proposed: EmotionVector,
        *,
        user_message: Message,
        assistant_message: Message,
        current: EmotionState,
    ) -> EmotionVector:
        local = self._policy.evaluate_turn(
            state=current,
            user_text=user_message.content,
            assistant_text=assistant_message.content,
            now=datetime.now(UTC),
        ).proposed_delta
        values = tuple(
            0.0 if local_value and proposed_value * local_value < 0 else proposed_value
            for proposed_value, local_value in zip(
                proposed.values(),
                local.values(),
                strict=True,
            )
        )
        return EmotionVector(*values)

    def _share_turn_delta_budget(
        self,
        proposed: EmotionVector,
        *,
        assistant_message: Message,
    ) -> EmotionVector:
        local_event = self._emotion_repository.get_rule_event_for_assistant(
            assistant_message.id
        )
        local_values = (
            local_event.applied_delta.values()
            if local_event is not None
            else EmotionVector.zero().values()
        )
        values = tuple(
            min(max(proposed_value, -max(cap - abs(local_value), 0.0)), max(cap - abs(local_value), 0.0))
            for proposed_value, local_value, cap in zip(
                proposed.values(),
                local_values,
                EMOTION_MAX_DELTA.values(),
                strict=True,
            )
        )
        return EmotionVector(*values)

    def _fail_job(
        self,
        *,
        job_id: str,
        outcome: EmotionAnalysisAuditOutcome,
        reason_code: str,
        session_id: str,
        user_message: Message,
        assistant_message: Message,
        analysis_input: EmotionAnalysisInput,
        started: float,
    ) -> None:
        with self._analysis_repository.transaction():
            self._analysis_repository.update_job_status(
                job_id,
                status=EmotionAnalysisJobStatus.FAILED,
                outcome_reason=reason_code,
            )
            self._append_audit(
                job_id=job_id,
                outcome=outcome,
                session_id=session_id,
                user_message=user_message,
                assistant_message=assistant_message,
                analysis_input=analysis_input,
                elapsed_ms=self._elapsed_ms(started),
                reason_code=reason_code,
            )

    def _append_audit(
        self,
        *,
        job_id: str,
        outcome: EmotionAnalysisAuditOutcome,
        session_id: str,
        user_message: Message,
        assistant_message: Message,
        analysis_input: EmotionAnalysisInput,
        elapsed_ms: int,
        reason_code: str,
    ) -> None:
        self._analysis_repository.append_audit(
            job_id=job_id,
            outcome=outcome,
            source_session_id=session_id,
            source_user_message_id=user_message.id,
            source_assistant_message_id=assistant_message.id,
            schema_version=EMOTION_ANALYSIS_SCHEMA_VERSION,
            provider=self._provider_name,
            model=self._model,
            message_count=len(analysis_input.recent_messages) + 2,
            memory_count=len(analysis_input.memories),
            input_characters=analysis_input.input_characters,
            redaction_count=analysis_input.redaction_count,
            elapsed_ms=elapsed_ms,
            reason_code=reason_code,
        )

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return max(0, round((perf_counter() - started) * 1000))
