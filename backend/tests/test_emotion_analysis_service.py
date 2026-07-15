import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.domain.models import (
    ChatRole,
    EmotionAnalysisAuditOutcome,
    EmotionAnalysisConsentStatus,
    EmotionEventType,
    EmotionVector,
    Message,
)
from app.repositories.emotion_analysis import EmotionAnalysisRepository
from app.repositories.emotions import EmotionRepository
from app.repositories.sqlite import managed_connection
from app.services.emotion_analysis_analyzer import EmotionAnalysisProposal
from app.services.emotion_analysis_dispatch import EmotionAnalysisDispatchFence
from app.services.emotion_analysis_input import EmotionAnalysisInputBuilder
from app.services.emotion_analysis_service import EmotionAnalysisService
from app.services.emotion_policy import EmotionPolicy


_POLICY_FINGERPRINT = "emotion-analysis-policy-v1"


def _message(message_id: str, role: ChatRole, content: str) -> Message:
    return Message(
        id=message_id,
        session_id="session-1",
        role=role,
        content=content,
        created_at=datetime.now(UTC),
        metadata={},
    )


class RecordingAnalyzer:
    def __init__(self, proposal: EmotionAnalysisProposal | None = None, error: Exception | None = None) -> None:
        self.proposal = proposal or EmotionAnalysisProposal(
            schema_version="emotion_analysis_v1",
            should_apply=True,
            signals=("distress",),
            proposed_delta=EmotionVector(-1.0, 1.0, 1.0, -1.0, -1.0, -1.0),
            source_ids=("user-1", "assistant-1"),
            reason_codes=("user_distress",),
        )
        self.error = error
        self.calls = 0

    async def analyze(self, analysis_input):
        self.calls += 1
        if self.error:
            raise self.error
        return self.proposal


class RevokingAnalyzer(RecordingAnalyzer):
    def __init__(self, repository: EmotionAnalysisRepository) -> None:
        super().__init__()
        self._repository = repository

    async def analyze(self, analysis_input):
        proposal = await super().analyze(analysis_input)
        self._repository.set_consent(
            status=EmotionAnalysisConsentStatus.REVOKED,
            disclosure_version="emotion-analysis-disclosure-v1",
            provider="deepseek",
            policy_fingerprint=_POLICY_FINGERPRINT,
        )
        return proposal


class RevokingBuilder(EmotionAnalysisInputBuilder):
    def __init__(self, repository: EmotionAnalysisRepository) -> None:
        super().__init__(
            recent_message_limit=6,
            memory_limit=3,
            max_item_characters=2_000,
            max_total_characters=8_000,
        )
        self._repository = repository

    def build(self, **kwargs):
        built = super().build(**kwargs)
        self._repository.set_consent(
            status=EmotionAnalysisConsentStatus.REVOKED,
            disclosure_version="emotion-analysis-disclosure-v1",
            provider="deepseek",
            policy_fingerprint=_POLICY_FINGERPRINT,
        )
        return built


def _service(
    connection,
    analyzer,
    *,
    enabled: bool = True,
    builder=None,
    dispatch_fence: EmotionAnalysisDispatchFence | None = None,
):
    analysis_repository = EmotionAnalysisRepository(connection)
    return EmotionAnalysisService(
        enabled=enabled,
        provider_name="deepseek",
        model="deepseek-v4-flash",
        policy_fingerprint=_POLICY_FINGERPRINT,
        analysis_repository=analysis_repository,
        emotion_repository=EmotionRepository(connection),
        policy=EmotionPolicy(),
        input_builder=builder
        or EmotionAnalysisInputBuilder(
            recent_message_limit=6,
            memory_limit=3,
            max_item_characters=2_000,
            max_total_characters=8_000,
        ),
        analyzer=analyzer,
        dispatch_fence=dispatch_fence,
    ), analysis_repository


@pytest.mark.asyncio
@pytest.mark.parametrize("consent", [
    EmotionAnalysisConsentStatus.UNKNOWN,
    EmotionAnalysisConsentStatus.DECLINED,
    EmotionAnalysisConsentStatus.REVOKED,
])
async def test_no_granted_consent_means_zero_calls_and_zero_jobs(tmp_path: Path, consent) -> None:
    with managed_connection(f"sqlite:///{tmp_path / f'{consent}.db'}") as connection:
        analyzer = RecordingAnalyzer()
        service, repository = _service(connection, analyzer)
        if consent is not EmotionAnalysisConsentStatus.UNKNOWN:
            repository.set_consent(
                status=consent,
                disclosure_version="emotion-analysis-disclosure-v1",
                provider="deepseek",
            policy_fingerprint=_POLICY_FINGERPRINT,
            )

        result = await service.process_turn(
            session_id="session-1",
            user_message=_message("user-1", ChatRole.USER, "我很难受"),
            assistant_message=_message("assistant-1", ChatRole.ASSISTANT, "我在听。"),
            recent_messages=[],
            relevant_memories=[],
        )

        assert result is None
        assert analyzer.calls == 0
        assert connection.execute("SELECT COUNT(*) FROM emotion_analysis_jobs").fetchone()[0] == 0


async def test_granted_consent_must_match_current_provider_and_disclosure(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'binding.db'}") as connection:
        analyzer = RecordingAnalyzer()
        service, repository = _service(connection, analyzer)
        repository.set_consent(
            status=EmotionAnalysisConsentStatus.GRANTED,
            disclosure_version="old-disclosure",
            provider="anthropic",
            policy_fingerprint="old-policy",
        )

        result = await service.process_turn(
            session_id="session-1",
            user_message=_message("user-1", ChatRole.USER, "hello"),
            assistant_message=_message("assistant-1", ChatRole.ASSISTANT, "hi"),
            recent_messages=[],
            relevant_memories=[],
        )

        assert result is None
        assert analyzer.calls == 0
        assert connection.execute("SELECT COUNT(*) FROM emotion_analysis_jobs").fetchone()[0] == 0


    with managed_connection(f"sqlite:///{tmp_path / 'disabled.db'}") as connection:
        analyzer = RecordingAnalyzer()
        service, repository = _service(connection, analyzer, enabled=False)
        repository.set_consent(
            status=EmotionAnalysisConsentStatus.GRANTED,
            disclosure_version="emotion-analysis-disclosure-v1",
            provider="deepseek",
            policy_fingerprint=_POLICY_FINGERPRINT,
        )
        await service.process_turn(
            session_id="session-1",
            user_message=_message("user-1", ChatRole.USER, "hello"),
            assistant_message=_message("assistant-1", ChatRole.ASSISTANT, "hi"),
            recent_messages=[],
            relevant_memories=[],
        )
        assert analyzer.calls == 0

        service, _ = _service(connection, analyzer, enabled=True)
        state = EmotionRepository(connection).get_or_create()
        EmotionRepository(connection).apply_transition(
            expected_version=state.version,
            after=state.vector,
            event_type=EmotionEventType.SETTINGS,
            reason_codes=("settings_disabled",),
            source_session_id=None,
            source_user_message_id=None,
            source_assistant_message_id=None,
            engine="rule",
            rule_version="emotion-rules-v1",
            enabled=False,
        )
        await service.process_turn(
            session_id="session-1",
            user_message=_message("user-2", ChatRole.USER, "hello"),
            assistant_message=_message("assistant-2", ChatRole.ASSISTANT, "hi"),
            recent_messages=[],
            relevant_memories=[],
        )
        assert analyzer.calls == 0


@pytest.mark.asyncio
async def test_granted_turn_calls_once_applies_local_cap_and_is_idempotent(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'granted.db'}") as connection:
        analyzer = RecordingAnalyzer()
        service, repository = _service(connection, analyzer)
        repository.set_consent(
            status=EmotionAnalysisConsentStatus.GRANTED,
            disclosure_version="emotion-analysis-disclosure-v1",
            provider="deepseek",
            policy_fingerprint=_POLICY_FINGERPRINT,
        )
        user = _message("user-1", ChatRole.USER, "我很难受")
        assistant = _message("assistant-1", ChatRole.ASSISTANT, "我在听。")

        first = await service.process_turn(
            session_id="session-1",
            user_message=user,
            assistant_message=assistant,
            recent_messages=[user, assistant],
            relevant_memories=[],
        )
        duplicate = await service.process_turn(
            session_id="session-1",
            user_message=user,
            assistant_message=assistant,
            recent_messages=[user, assistant],
            relevant_memories=[],
        )

        assert duplicate is None
        assert analyzer.calls == 1
        assert first is not None
        assert first.vector == EmotionVector(0.42, 0.44, 0.30, 0.50, 0.02, 0.54)
        assert len(repository.list_audits(limit=10)) == 1
        assert repository.list_audits(limit=10)[0].outcome is EmotionAnalysisAuditOutcome.APPLIED
        event = EmotionRepository(connection).list_events(limit=1)[0]
        assert event.engine == "llm_assisted"
        assert event.rule_version == "emotion-policy-v1+emotion-analysis-v1"


async def test_llm_proposal_cannot_reverse_same_turn_local_boundary_direction(tmp_path: Path) -> None:
    proposal = EmotionAnalysisProposal(
        schema_version="emotion_analysis_v1",
        should_apply=True,
        signals=("boundary_violation",),
        proposed_delta=EmotionVector(0.0, 0.0, 0.0, -0.05, 0.0, -0.06),
        source_ids=("user-1", "assistant-1"),
        reason_codes=("user_violated_boundary",),
    )
    with managed_connection(f"sqlite:///{tmp_path / 'local-boundary.db'}") as connection:
        emotions = EmotionRepository(connection)
        state = emotions.get_or_create()
        saturated_start = EmotionVector(
            state.vector.mood,
            state.vector.trust,
            state.vector.concern,
            0.98,
            state.vector.irritation,
            0.98,
        )
        state = emotions.apply_transition(
            expected_version=state.version,
            after=saturated_start,
            event_type=EmotionEventType.SETTINGS,
            reason_codes=("test_setup",),
            source_session_id=None,
            source_user_message_id=None,
            source_assistant_message_id=None,
            engine="test",
            rule_version="test",
        )
        local_after = EmotionPolicy().apply_delta(
            state.vector,
            EmotionVector(0.0, 0.0, 0.0, 0.03, 0.0, 0.04),
        )
        emotions.apply_transition(
            expected_version=state.version,
            after=local_after,
            event_type=EmotionEventType.TRANSITION,
            reason_codes=("user_clear_boundary",),
            source_session_id="session-1",
            source_user_message_id="user-1",
            source_assistant_message_id="assistant-1",
            engine="rule",
            rule_version="emotion-rules-v1",
        )
        analyzer = RecordingAnalyzer(proposal=proposal)
        service, repository = _service(connection, analyzer)
        repository.set_consent(
            status=EmotionAnalysisConsentStatus.GRANTED,
            disclosure_version="emotion-analysis-disclosure-v1",
            provider="deepseek",
            policy_fingerprint=_POLICY_FINGERPRINT,
        )

        result = await service.process_turn(
            session_id="session-1",
            user_message=_message("user-1", ChatRole.USER, "请不要这样"),
            assistant_message=_message("assistant-1", ChatRole.ASSISTANT, "明白。"),
            recent_messages=[],
            relevant_memories=[],
        )

        assert result is not None
        assert result.vector.distance == local_after.distance
        assert result.vector.formality == local_after.formality


@pytest.mark.asyncio
async def test_llm_proposal_shares_the_turn_delta_cap_with_local_rules(
    tmp_path: Path,
) -> None:
    proposal = EmotionAnalysisProposal(
        schema_version="emotion_analysis_v1",
        should_apply=True,
        signals=("distress",),
        proposed_delta=EmotionVector(0.0, 0.0, 1.0, 0.0, 0.0, 0.0),
        source_ids=("user-1", "assistant-1"),
        reason_codes=("user_distress",),
    )
    with managed_connection(f"sqlite:///{tmp_path / 'shared-turn-cap.db'}") as connection:
        emotions = EmotionRepository(connection)
        before = emotions.get_or_create()
        local_after = EmotionPolicy().apply_delta(
            before.vector,
            EmotionVector(0.0, 0.0, 0.08, 0.0, 0.0, 0.0),
        )
        local_state = emotions.apply_transition(
            expected_version=before.version,
            after=local_after,
            event_type=EmotionEventType.TRANSITION,
            reason_codes=("user_distress_signal",),
            source_session_id="session-1",
            source_user_message_id="user-1",
            source_assistant_message_id="assistant-1",
            engine="rule",
            rule_version="emotion-rules-v1",
        )
        analyzer = RecordingAnalyzer(proposal=proposal)
        service, repository = _service(connection, analyzer)
        repository.set_consent(
            status=EmotionAnalysisConsentStatus.GRANTED,
            disclosure_version="emotion-analysis-disclosure-v1",
            provider="deepseek",
            policy_fingerprint=_POLICY_FINGERPRINT,
        )

        result = await service.process_turn(
            session_id="session-1",
            user_message=_message("user-1", ChatRole.USER, "我很难受"),
            assistant_message=_message("assistant-1", ChatRole.ASSISTANT, "我在听。"),
            recent_messages=[],
            relevant_memories=[],
            base_emotion_version=local_state.version,
        )

        assert result is not None
        assert result.vector.concern == 0.30


    proposal = EmotionAnalysisProposal(
        schema_version="emotion_analysis_v1",
        should_apply=True,
        signals=("neutral",),
        proposed_delta=EmotionVector.zero(),
        source_ids=("user-1", "assistant-1"),
        reason_codes=("neutral_turn",),
    )
    with managed_connection(f"sqlite:///{tmp_path / 'no-change.db'}") as connection:
        analyzer = RecordingAnalyzer(proposal=proposal)
        service, repository = _service(connection, analyzer)
        repository.set_consent(
            status=EmotionAnalysisConsentStatus.GRANTED,
            disclosure_version="emotion-analysis-disclosure-v1",
            provider="deepseek",
            policy_fingerprint=_POLICY_FINGERPRINT,
        )

        await service.process_turn(
            session_id="session-1",
            user_message=_message("user-1", ChatRole.USER, "hello"),
            assistant_message=_message("assistant-1", ChatRole.ASSISTANT, "hi"),
            recent_messages=[],
            relevant_memories=[],
        )

        audit = repository.list_audits(limit=1)[0]
        assert audit.outcome is EmotionAnalysisAuditOutcome.NO_CHANGE
        assert connection.execute("SELECT outcome_reason FROM emotion_analysis_jobs").fetchone()[0] == "no_change"
        assert EmotionRepository(connection).list_events(limit=10) == []


    with managed_connection(f"sqlite:///{tmp_path / 'revoke.db'}") as connection:
        analyzer = RecordingAnalyzer()
        repository = EmotionAnalysisRepository(connection)
        repository.set_consent(
            status=EmotionAnalysisConsentStatus.GRANTED,
            disclosure_version="emotion-analysis-disclosure-v1",
            provider="deepseek",
            policy_fingerprint=_POLICY_FINGERPRINT,
        )
        service, _ = _service(connection, analyzer, builder=RevokingBuilder(repository))

        result = await service.process_turn(
            session_id="session-1",
            user_message=_message("user-1", ChatRole.USER, "hello"),
            assistant_message=_message("assistant-1", ChatRole.ASSISTANT, "hi"),
            recent_messages=[],
            relevant_memories=[],
        )

        assert result is None
        assert analyzer.calls == 0
        assert repository.list_audits(limit=1)[0].outcome is EmotionAnalysisAuditOutcome.REVOKED


@pytest.mark.asyncio
async def test_revoke_pending_blocks_queued_provider_dispatch(tmp_path: Path) -> None:
    class BlockingAnalyzer(RecordingAnalyzer):
        def __init__(self) -> None:
            super().__init__()
            self.first_started = asyncio.Event()
            self.release_first = asyncio.Event()

        async def analyze(self, analysis_input):
            self.calls += 1
            if self.calls == 1:
                self.first_started.set()
                await self.release_first.wait()
            return self.proposal

    database_url = f"sqlite:///{tmp_path / 'revoke-pending.db'}"
    fence = EmotionAnalysisDispatchFence()
    analyzer = BlockingAnalyzer()
    with managed_connection(database_url) as connection:
        service, repository = _service(
            connection,
            analyzer,
            dispatch_fence=fence,
        )
        repository.set_consent(
            status=EmotionAnalysisConsentStatus.GRANTED,
            disclosure_version="emotion-analysis-disclosure-v1",
            provider="deepseek",
            policy_fingerprint=_POLICY_FINGERPRINT,
        )
        first = asyncio.create_task(
            service.process_turn(
                session_id="session-1",
                user_message=_message("user-1", ChatRole.USER, "first"),
                assistant_message=_message("assistant-1", ChatRole.ASSISTANT, "first reply"),
                recent_messages=[],
                relevant_memories=[],
            )
        )
        await analyzer.first_started.wait()
        second = asyncio.create_task(
            service.process_turn(
                session_id="session-1",
                user_message=_message("user-2", ChatRole.USER, "second"),
                assistant_message=_message("assistant-2", ChatRole.ASSISTANT, "second reply"),
                recent_messages=[],
                relevant_memories=[],
            )
        )
        await asyncio.sleep(0)
        revoke_requested = fence.begin_consent_mutation()
        revoke = asyncio.create_task(
            _revoke_with_fence(fence, repository, revoke_requested)
        )
        await asyncio.sleep(0)
        analyzer.release_first.set()
        await asyncio.gather(first, second, revoke)

        assert analyzer.calls == 1
        outcomes = [audit.outcome for audit in repository.list_audits(limit=10)]
        assert EmotionAnalysisAuditOutcome.REVOKED in outcomes


async def _revoke_with_fence(
    fence: EmotionAnalysisDispatchFence,
    repository: EmotionAnalysisRepository,
    mutation,
) -> None:
    async with mutation:
        repository.set_consent(
            status=EmotionAnalysisConsentStatus.REVOKED,
            disclosure_version="emotion-analysis-disclosure-v1",
            provider="deepseek",
            policy_fingerprint=_POLICY_FINGERPRINT,
        )


@pytest.mark.asyncio
async def test_pending_revoke_discards_in_flight_provider_result(tmp_path: Path) -> None:
    class BlockingAnalyzer(RecordingAnalyzer):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def analyze(self, analysis_input):
            self.calls += 1
            self.started.set()
            await self.release.wait()
            return self.proposal

    fence = EmotionAnalysisDispatchFence()
    analyzer = BlockingAnalyzer()
    with managed_connection(f"sqlite:///{tmp_path / 'in-flight-revoke.db'}") as connection:
        service, repository = _service(connection, analyzer, dispatch_fence=fence)
        repository.set_consent(
            status=EmotionAnalysisConsentStatus.GRANTED,
            disclosure_version="emotion-analysis-disclosure-v1",
            provider="deepseek",
            policy_fingerprint=_POLICY_FINGERPRINT,
        )
        before = EmotionRepository(connection).get_or_create()
        analysis = asyncio.create_task(
            service.process_turn(
                session_id="session-1",
                user_message=_message("user-1", ChatRole.USER, "first"),
                assistant_message=_message("assistant-1", ChatRole.ASSISTANT, "first reply"),
                recent_messages=[],
                relevant_memories=[],
            )
        )
        await analyzer.started.wait()
        mutation = fence.begin_consent_mutation()
        revoke = asyncio.create_task(_revoke_with_fence(fence, repository, mutation))
        await asyncio.sleep(0)
        analyzer.release.set()
        result, _ = await asyncio.gather(analysis, revoke)

        assert result is None
        assert EmotionRepository(connection).get_or_create() == before
        assert repository.list_audits(limit=1)[0].outcome is EmotionAnalysisAuditOutcome.REVOKED
        assert not any(
            event.engine == "llm_assisted"
            for event in EmotionRepository(connection).list_events(limit=10)
        )


@pytest.mark.asyncio
async def test_cancelled_pending_consent_mutation_does_not_block_future_dispatch() -> None:
    fence = EmotionAnalysisDispatchFence()
    release = asyncio.Event()

    async def hold_dispatch() -> None:
        async with fence.hold():
            await release.wait()

    holder = asyncio.create_task(hold_dispatch())
    await asyncio.sleep(0)
    mutation = fence.begin_consent_mutation()

    async def wait_for_mutation() -> None:
        async with mutation:
            pass

    waiter = asyncio.create_task(wait_for_mutation())
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    release.set()
    await holder

    async with fence.hold() as dispatch_allowed:
        assert dispatch_allowed is True


@pytest.mark.asyncio
async def test_revoke_after_provider_result_prevents_state_write(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'revoke-after-provider.db'}") as connection:
        repository = EmotionAnalysisRepository(connection)
        analyzer = RevokingAnalyzer(repository)
        service, _ = _service(connection, analyzer)
        repository.set_consent(
            status=EmotionAnalysisConsentStatus.GRANTED,
            disclosure_version="emotion-analysis-disclosure-v1",
            provider="deepseek",
            policy_fingerprint=_POLICY_FINGERPRINT,
        )
        before = EmotionRepository(connection).get_or_create()

        result = await service.process_turn(
            session_id="session-1",
            user_message=_message("user-1", ChatRole.USER, "我很难受"),
            assistant_message=_message("assistant-1", ChatRole.ASSISTANT, "我在听。"),
            recent_messages=[],
            relevant_memories=[],
        )

        assert result is None
        assert EmotionRepository(connection).get_or_create() == before
        assert repository.list_audits(limit=1)[0].outcome is EmotionAnalysisAuditOutcome.REVOKED


async def test_cancelled_analysis_marks_job_interrupted(tmp_path: Path) -> None:
    class CancelledAnalyzer:
        async def analyze(self, analysis_input):
            raise asyncio.CancelledError

    with managed_connection(f"sqlite:///{tmp_path / 'cancelled.db'}") as connection:
        service, repository = _service(connection, CancelledAnalyzer())
        repository.set_consent(
            status=EmotionAnalysisConsentStatus.GRANTED,
            disclosure_version="emotion-analysis-disclosure-v1",
            provider="deepseek",
            policy_fingerprint=_POLICY_FINGERPRINT,
        )

        with pytest.raises(asyncio.CancelledError):
            await service.process_turn(
                session_id="session-1",
                user_message=_message("user-1", ChatRole.USER, "hello"),
                assistant_message=_message("assistant-1", ChatRole.ASSISTANT, "hi"),
                recent_messages=[],
                relevant_memories=[],
            )

        row = connection.execute(
            "SELECT status, outcome_reason FROM emotion_analysis_jobs"
        ).fetchone()
        assert tuple(row) == ("failed", "interrupted")
        assert repository.list_audits(limit=1)[0].outcome is EmotionAnalysisAuditOutcome.FAILED


    with managed_connection(f"sqlite:///{tmp_path / 'failure.db'}") as connection:
        analyzer = RecordingAnalyzer(error=RuntimeError("raw provider response secret"))
        service, repository = _service(connection, analyzer)
        repository.set_consent(
            status=EmotionAnalysisConsentStatus.GRANTED,
            disclosure_version="emotion-analysis-disclosure-v1",
            provider="deepseek",
            policy_fingerprint=_POLICY_FINGERPRINT,
        )
        before = EmotionRepository(connection).get_or_create()

        result = await service.process_turn(
            session_id="session-1",
            user_message=_message("user-1", ChatRole.USER, "hello"),
            assistant_message=_message("assistant-1", ChatRole.ASSISTANT, "hi"),
            recent_messages=[],
            relevant_memories=[],
        )

        assert result is None
        assert EmotionRepository(connection).get_or_create() == before
        audit = repository.list_audits(limit=1)[0]
        assert audit.outcome is EmotionAnalysisAuditOutcome.PROVIDER_ERROR
        assert "secret" not in audit.reason_code


@pytest.mark.asyncio
async def test_sqlite_operations_stay_in_the_analysis_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'no-detached-db-worker.db'}") as connection:
        analyzer = RecordingAnalyzer()
        service, repository = _service(connection, analyzer)
        repository.set_consent(
            status=EmotionAnalysisConsentStatus.GRANTED,
            disclosure_version="emotion-analysis-disclosure-v1",
            provider="deepseek",
            policy_fingerprint=_POLICY_FINGERPRINT,
        )

        async def reject_detached_worker(*_args, **_kwargs):
            raise AssertionError("SQLite work must not outlive the analysis task")

        monkeypatch.setattr(asyncio, "to_thread", reject_detached_worker)

        result = await service.process_turn(
            session_id="session-1",
            user_message=_message("user-1", ChatRole.USER, "我很难受"),
            assistant_message=_message("assistant-1", ChatRole.ASSISTANT, "我在听。"),
            recent_messages=[],
            relevant_memories=[],
        )

        assert result is not None
        assert analyzer.calls == 1
        assert repository.list_audits(limit=1)[0].outcome is EmotionAnalysisAuditOutcome.APPLIED


@pytest.mark.asyncio
async def test_applied_completion_rolls_back_when_audit_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'atomic-completion.db'}") as connection:
        analyzer = RecordingAnalyzer()
        service, repository = _service(connection, analyzer)
        repository.set_consent(
            status=EmotionAnalysisConsentStatus.GRANTED,
            disclosure_version="emotion-analysis-disclosure-v1",
            provider="deepseek",
            policy_fingerprint=_POLICY_FINGERPRINT,
        )
        before = EmotionRepository(connection).get_or_create()

        def fail_audit(**_kwargs):
            raise RuntimeError("simulated audit write failure")

        monkeypatch.setattr(repository, "append_audit", fail_audit)

        with pytest.raises(RuntimeError, match="audit write failure"):
            await service.process_turn(
                session_id="session-1",
                user_message=_message("user-1", ChatRole.USER, "我很难受"),
                assistant_message=_message("assistant-1", ChatRole.ASSISTANT, "我在听。"),
                recent_messages=[],
                relevant_memories=[],
            )

        assert EmotionRepository(connection).get_or_create() == before
        assert EmotionRepository(connection).list_events(limit=10) == []
        assert connection.execute(
            "SELECT status FROM emotion_analysis_jobs"
        ).fetchone()[0] == "running"
