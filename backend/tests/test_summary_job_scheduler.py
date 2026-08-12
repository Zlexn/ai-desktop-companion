from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain.models import ChatRole
from app.domain.session_summary import SummaryJobKind, SummaryJobStatus
from app.repositories.chat_turns import ChatTurnRepository
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.repositories.summary_automation import SummaryAutomationRepository
from app.services.session_summary_contract import (
    SUMMARY_JOB_SCHEMA_VERSION,
    SUMMARY_SCHEMA_VERSION,
)
from app.services.session_summary_scheduler import DurableSessionSummaryScheduler
from app.services.session_summary_service import (
    SummaryJobReservationService,
    build_summary_processing_policy,
)
from app.core.config import Settings


@pytest.mark.asyncio
async def test_duplicate_schedule_starts_one_effective_attempt() -> None:
    started: list[str] = []
    release = asyncio.Event()

    class Job:
        id = "job-1"
        session_id = "session"

    reservations = 0

    def reserve(_session_id: str, _turn_id: str):
        nonlocal reservations
        reservations += 1
        return Job(), reservations == 1

    async def run(job_id: str, session_id: str) -> None:
        assert session_id == "session"
        started.append(job_id)
        await release.wait()

    scheduler = DurableSessionSummaryScheduler(
        reserve_for_turn=reserve,
        run_job=run,
        recover_job_ids=lambda: ([], []),
        fail_incompatible=lambda _job_id: None,
        cancel_job=lambda _job_id: None,
        fail_job=lambda _job_id: None,
    )

    assert scheduler.schedule("session", chat_turn_id="turn") is True
    assert scheduler.schedule("session", chat_turn_id="turn") is False
    release.set()
    await scheduler.shutdown()

    assert started == ["job-1"]


@pytest.mark.asyncio
async def test_schedule_requires_exact_chat_turn_id() -> None:
    scheduler = DurableSessionSummaryScheduler(
        reserve_for_turn=lambda _session_id, _turn_id: pytest.fail("must not reserve"),
        run_job=lambda _job_id, _session_id: pytest.fail("must not run"),
        recover_job_ids=lambda: ([], []),
        fail_incompatible=lambda _job_id: None,
        cancel_job=lambda _job_id: None,
        fail_job=lambda _job_id: None,
    )

    assert scheduler.schedule("session") is False
    await scheduler.shutdown()


@pytest.mark.asyncio
async def test_recovery_starts_only_compatible_jobs_and_terminalizes_others() -> None:
    started: list[str] = []
    incompatible: list[str] = []

    async def run(job_id: str, session_id: str) -> None:
        assert session_id == "recovered-session"
        started.append(job_id)

    recoverable = SimpleNamespace(
        id="compatible",
        session_id="recovered-session",
    )
    scheduler = DurableSessionSummaryScheduler(
        reserve_for_turn=lambda _session_id, _turn_id: pytest.fail("not scheduling"),
        run_job=run,
        recover_job_ids=lambda: (
            [recoverable],
            ["bad-schema", "exhausted"],
        ),
        fail_incompatible=incompatible.append,
        cancel_job=lambda _job_id: None,
        fail_job=lambda _job_id: None,
    )

    assert await scheduler.recover() == 1
    await scheduler.shutdown()

    assert started == ["compatible"]
    assert incompatible == ["bad-schema", "exhausted"]


@pytest.mark.asyncio
async def test_shutdown_cancel_is_metadata_only() -> None:
    entered = asyncio.Event()
    cancelled: list[str] = []

    class Job:
        id = "job-cancel"
        session_id = "session"

    async def run(_job_id: str, _session_id: str) -> None:
        entered.set()
        await asyncio.Event().wait()

    scheduler = DurableSessionSummaryScheduler(
        reserve_for_turn=lambda _session_id, _turn_id: (Job(), True),
        run_job=run,
        recover_job_ids=lambda: ([], []),
        fail_incompatible=lambda _job_id: None,
        cancel_job=cancelled.append,
        fail_job=lambda _job_id: None,
    )
    assert scheduler.schedule("session", chat_turn_id="turn") is True
    await entered.wait()

    await scheduler.shutdown(cancel=True)

    assert cancelled == ["job-cancel"]


@pytest.mark.asyncio
async def test_runner_exception_marks_only_summary_job_failed() -> None:
    failed: list[str] = []

    class Job:
        id = "job-failed"
        session_id = "session"

    async def run(_job_id: str, _session_id: str) -> None:
        raise RuntimeError("worker failed")

    scheduler = DurableSessionSummaryScheduler(
        reserve_for_turn=lambda _session_id, _turn_id: (Job(), True),
        run_job=run,
        recover_job_ids=lambda: ([], []),
        fail_incompatible=lambda _job_id: None,
        cancel_job=lambda _job_id: None,
        fail_job=failed.append,
    )
    assert scheduler.schedule("session", chat_turn_id="turn") is True
    await scheduler.shutdown()

    assert failed == ["job-failed"]


def _reserve_job(connection, *, schema: str = SUMMARY_SCHEMA_VERSION, attempts: int = 0):
    session = SessionRepository(connection).create("recover")
    user = MessageRepository(connection).add(session.id, ChatRole.USER, "user")
    _, turn = ChatTurnRepository(connection).append_assistant_turn(
        session_id=session.id,
        user_message_id=user.id,
        content="assistant",
        metadata={},
    )
    snapshot = ChatTurnRepository(connection).snapshot_generation_sources(
        session_id=session.id,
        after_turn_order=0,
        max_turns=1,
        max_messages=2,
        max_characters=10_000,
    )
    job, _ = SummaryAutomationRepository(connection).reserve_job(
        snapshot=snapshot,
        job_kind=SummaryJobKind.INCREMENTAL,
        route="fake",
        provider=None,
        model=None,
        summarizer_schema_version=schema,
        processing_consent_generation=0,
        processing_policy_fingerprint=None,
        provider_policy_fingerprint="fake-route-v1",
        session_deletion_generation=0,
        suppression_generation=0,
        rebuild_authorization_generation=0,
        rebuild_permit_id=None,
    )
    if attempts:
        connection.execute(
            "UPDATE summary_jobs SET attempt_count=? WHERE id=?",
            (attempts, job.id),
        )
        connection.commit()
    return job, turn


def test_repository_recovery_classifies_stale_compatible_jobs(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'recovery.db'}"
    with managed_connection(database_url) as connection:
        compatible, _ = _reserve_job(connection)
        incompatible_schema, _ = _reserve_job(connection, schema="unsupported")
        exhausted, _ = _reserve_job(connection, attempts=3)
        recent, _ = _reserve_job(connection)
        stale = (datetime.now(UTC) - timedelta(seconds=301)).isoformat()
        recent_time = datetime.now(UTC).isoformat()
        connection.execute(
            "UPDATE summary_jobs SET status='running', started_at=? "
            "WHERE id IN (?, ?, ?)",
            (stale, compatible.id, incompatible_schema.id, exhausted.id),
        )
        connection.execute(
            "UPDATE summary_jobs SET status='running', started_at=? WHERE id=?",
            (recent_time, recent.id),
        )
        connection.commit()

        repository = SummaryAutomationRepository(connection)

        recoverable, incompatible = repository.prepare_recovery_jobs(
            stale_before=datetime.now(UTC) - timedelta(seconds=300),
            job_schema_version=SUMMARY_JOB_SCHEMA_VERSION,
            summarizer_schema_version=SUMMARY_SCHEMA_VERSION,
            max_attempts=3,
        )

        assert [job.id for job in recoverable] == [compatible.id]
        assert set(incompatible) == {incompatible_schema.id, exhausted.id}
        assert repository.require_job(compatible.id).status is SummaryJobStatus.PENDING
        assert repository.require_job(compatible.id).started_at is None
        assert recent.id not in [job.id for job in recoverable] + incompatible


def test_repository_terminalization_is_metadata_only(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'terminalize.db'}"
    with managed_connection(database_url) as connection:
        job, _ = _reserve_job(connection)
        repository = SummaryAutomationRepository(connection)

        repository.fail_incompatible_job(job.id)
        terminal = repository.require_job(job.id)

        assert terminal.status is SummaryJobStatus.FAILED
        assert terminal.reason_code == "incompatible_recovery"
        assert terminal.error_category == "compatibility"
        assert terminal.finished_at is not None
        raw = "\n".join(
            str(tuple(row))
            for row in connection.execute(
                "SELECT * FROM summary_jobs WHERE id=?", (job.id,)
            )
        )
        assert "user" not in raw
        assert "assistant" not in raw


def test_repository_claims_pending_and_stale_running_jobs_atomically(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'claim.db'}"
    with managed_connection(database_url) as connection:
        pending, _ = _reserve_job(connection)
        repository = SummaryAutomationRepository(connection)

        first = repository.claim_job(pending.id, max_attempts=3)
        duplicate = repository.claim_job(pending.id, max_attempts=3)

        assert first is not None
        assert first.status is SummaryJobStatus.RUNNING
        assert first.attempt_count == 1
        assert first.started_at is not None
        assert duplicate is None

        stale = (datetime.now(UTC) - timedelta(seconds=301)).isoformat()
        connection.execute(
            "UPDATE summary_jobs SET started_at=? WHERE id=?",
            (stale, pending.id),
        )
        connection.commit()

        retried = repository.claim_job(
            pending.id,
            max_attempts=3,
            stale_before=datetime.now(UTC) - timedelta(seconds=300),
        )

        assert retried is not None
        assert retried.status is SummaryJobStatus.RUNNING
        assert retried.attempt_count == 2
        assert retried.started_at is not None


def test_repository_claim_rejects_exhausted_or_incompatible_job(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'claim-reject.db'}"
    with managed_connection(database_url) as connection:
        job, _ = _reserve_job(connection, attempts=3)
        repository = SummaryAutomationRepository(connection)

        assert repository.claim_job(job.id, max_attempts=3) is None
        assert (
            repository.claim_job(
                job.id,
                max_attempts=4,
                job_schema_version="unsupported",
            )
            is None
        )


def test_scheduler_claims_before_running_when_claim_callback_is_configured() -> None:
    async def scenario() -> None:
        events: list[tuple[str, str]] = []

        class Job:
            id = "claimed-job"
            session_id = "session"
            status = SummaryJobStatus.PENDING

        def claim(job_id: str):
            events.append(("claim", job_id))
            return Job()

        async def run(job_id: str, session_id: str) -> None:
            assert session_id == "session"
            events.append(("run", job_id))

        scheduler = DurableSessionSummaryScheduler(
            reserve_for_turn=lambda _session_id, _turn_id: (Job(), True),
            run_job=run,
            recover_job_ids=lambda: ([], []),
            fail_incompatible=lambda _job_id: None,
            cancel_job=lambda _job_id: None,
            fail_job=lambda _job_id: None,
            claim_job=claim,
        )
        assert scheduler.schedule("session", chat_turn_id="turn") is True
        await scheduler.shutdown()
        assert events == [("claim", "claimed-job"), ("run", "claimed-job")]

    asyncio.run(scenario())


def test_reservation_service_requires_exact_trigger_turn_and_complete_threshold(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'reservation-service.db'}"
    settings = Settings(
        database_url=database_url,
        session_summary_provider="fake",
        session_summary_trigger_turn_count=2,
        session_summary_max_input_turns=4,
        session_summary_max_input_messages=8,
        session_summary_max_input_characters=10_000,
    )
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("reserve")
        messages = MessageRepository(connection)
        first_user = messages.add(session.id, ChatRole.USER, "first user")
        _, first_turn = ChatTurnRepository(connection).append_assistant_turn(
            session_id=session.id,
            user_message_id=first_user.id,
            content="first assistant",
            metadata={},
        )
        service = SummaryJobReservationService(connection, settings=settings)
        automation = SummaryAutomationRepository(connection)
        local_policy = build_summary_processing_policy(settings)
        authority = automation.get_processing_authority()
        automation.mutate_processing(
            action="enable_local",
            expected_generation=authority.generation,
            policy=local_policy,
        )

        assert service.reserve_for_turn(session.id, first_turn.id) is None

        second_user = messages.add(session.id, ChatRole.USER, "second user")
        _, second_turn = ChatTurnRepository(connection).append_assistant_turn(
            session_id=session.id,
            user_message_id=second_user.id,
            content="second assistant",
            metadata={},
        )

        reserved = service.reserve_for_turn(session.id, second_turn.id)

        assert reserved is not None
        job, created = reserved
        assert created is True
        assert job.route == "fake"
        assert job.source_turn_count == 2
        assert job.captured_processing_consent_generation == 1
        assert job.captured_processing_policy_fingerprint == local_policy.fingerprint()
        assert service.reserve_for_turn(session.id, "not-the-trigger") is None


def test_disabled_generation_uses_noop_scheduler_at_lifespan(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.services.session_summary_scheduler import NoOpSessionSummaryScheduler

    app = create_app(
        settings_override=Settings(
            database_url=f"sqlite:///{tmp_path / 'disabled.db'}",
            llm_provider="fake",
            session_summary_enabled=False,
        )
    )
    with TestClient(app):
        assert isinstance(
            app.state.session_summary_scheduler,
            NoOpSessionSummaryScheduler,
        )


def test_local_reservation_without_explicit_enable_is_metadata_only_skipped_attempt(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'local-no-authority.db'}"
    settings = Settings(
        database_url=database_url,
        session_summary_provider="fake",
        session_summary_trigger_turn_count=1,
        session_summary_max_input_turns=2,
        session_summary_max_input_messages=4,
        session_summary_max_input_characters=10_000,
    )
    with managed_connection(database_url) as connection:
        _, turn = _reserve_source_turn(connection)
        service = SummaryJobReservationService(connection, settings=settings)

        skipped = service.reserve_for_turn(turn.session_id, turn.id)
        assert skipped is not None
        job, created = skipped
        assert created is True
        assert job.status is SummaryJobStatus.SKIPPED
        assert job.reason_code == "skipped_no_consent"
        assert connection.execute("SELECT COUNT(*) FROM summary_jobs").fetchone()[0] == 1


def test_remote_reservation_without_exact_authority_is_metadata_only_skipped_attempt(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'remote-no-consent.db'}"
    settings = Settings(
        database_url=database_url,
        session_summary_provider="llm",
        session_summary_trigger_turn_count=1,
        session_summary_max_input_turns=2,
        session_summary_max_input_messages=4,
        session_summary_max_input_characters=10_000,
        session_summary_llm_provider="deepseek",
        session_summary_llm_model="deepseek-chat",
    )
    with managed_connection(database_url) as connection:
        _, turn = _reserve_source_turn(connection)
        service = SummaryJobReservationService(connection, settings=settings)

        skipped = service.reserve_for_turn(turn.session_id, turn.id)
        assert skipped is not None
        job, created = skipped
        assert created is True
        assert job.status is SummaryJobStatus.SKIPPED
        assert job.reason_code == "skipped_no_consent"
        assert connection.execute("SELECT COUNT(*) FROM summary_jobs").fetchone()[0] == 1


def _reserve_source_turn(connection):
    session = SessionRepository(connection).create("source")
    user = MessageRepository(connection).add(session.id, ChatRole.USER, "user")
    _, turn = ChatTurnRepository(connection).append_assistant_turn(
        session_id=session.id,
        user_message_id=user.id,
        content="assistant",
        metadata={},
    )
    return session, turn
