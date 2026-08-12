from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

import pytest

from app.domain.models import (
    MemoryAutomationMode,
    MemoryExtractorRoute,
    MemoryJob,
    MemoryJobStatus,
)
from app.services.memory_job_scheduler import (
    InProcessMemoryJobScheduler,
    MemoryJobScheduler,
    NoOpMemoryJobScheduler,
)
from app.services.memory_extractor import MEMORY_EXTRACTION_SCHEMA_VERSION
from app.services.memory_governor import MEMORY_GOVERNOR_VERSION


def _ignore_job(_job_id: str) -> None:
    pass


@dataclass(frozen=True)
class Reservation:
    job: MemoryJob
    created: bool


def make_job(job_id: str, assistant_message_id: str) -> MemoryJob:
    return MemoryJob(
        id=job_id,
        turn_id=assistant_message_id,
        schema_version=MEMORY_EXTRACTION_SCHEMA_VERSION,
        session_id="session-1",
        user_message_id="user-1",
        assistant_message_id=assistant_message_id,
        mode=MemoryAutomationMode.SHADOW_AUTO,
        extractor_route=MemoryExtractorRoute.FAKE,
        status=MemoryJobStatus.PENDING,
        attempt_count=0,
        outcome=None,
        error_category=None,
        governor_version=MEMORY_GOVERNOR_VERSION,
        consent_generation=None,
        created_at=datetime(2026, 7, 18, tzinfo=UTC),
        started_at=None,
        finished_at=None,
    )


def test_noop_scheduler_is_a_protocol_implementation_and_never_schedules() -> None:
    scheduler = NoOpMemoryJobScheduler()
    cast(MemoryJobScheduler, scheduler)

    assert not scheduler.schedule(
        session_id="session-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        persona_artifact_id="persona-1",
    )


def test_in_process_scheduler_rejects_non_automatic_mode() -> None:
    with pytest.raises(ValueError, match="automatic mode"):
        InProcessMemoryJobScheduler(
            reserve_job=lambda **_kwargs: (make_job("job-1", "assistant-1"), True),
            run_job=lambda _job_id: asyncio.sleep(0),
            recover_job_ids=lambda: [],
            cancel_job=lambda _job_id: None,
            fail_job=_ignore_job,
            mode=MemoryAutomationMode.OFF,
            route=MemoryExtractorRoute.FAKE,
        )


@pytest.mark.asyncio
async def test_auto_active_scheduler_requires_timestamp_and_uses_reservation_factory() -> None:
    completed_at = datetime(2026, 7, 18, tzinfo=UTC)
    reservations: list[dict[str, object]] = []
    job = make_job("active-job", "assistant-1")

    def reservation_factory(**kwargs: object) -> dict[str, object]:
        reservations.append(kwargs)
        return {"frozen": True}

    scheduler = InProcessMemoryJobScheduler(
        reserve_job=lambda **kwargs: (job, kwargs == {"frozen": True}),
        run_job=lambda _job_id: asyncio.sleep(0),
        recover_job_ids=lambda: [],
        cancel_job=lambda _job_id: None,
        fail_job=_ignore_job,
        mode=MemoryAutomationMode.AUTO_ACTIVE,
        route=MemoryExtractorRoute.LOCAL,
        reservation_factory=reservation_factory,
    )

    assert not scheduler.schedule(
        session_id="session-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        persona_artifact_id="persona-1",
    )
    assert scheduler.schedule(
        session_id="session-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        persona_artifact_id="persona-1",
        turn_completed_at=completed_at,
    )
    assert reservations == [{
        "session_id": "session-1",
        "user_message_id": "user-1",
        "assistant_message_id": "assistant-1",
        "persona_artifact_id": "persona-1",
        "turn_completed_at": completed_at,
    }]
    await scheduler.shutdown()


@pytest.mark.asyncio
async def test_schedule_reserves_once_returns_before_worker_completion_and_deduplicates() -> None:
    release = asyncio.Event()
    started = asyncio.Event()
    reserve_calls: list[dict[str, object]] = []
    worker_calls: list[str] = []
    first_job = make_job("job-1", "assistant-1")

    def reserve_job(**kwargs: object) -> tuple[MemoryJob, bool]:
        reserve_calls.append(kwargs)
        return first_job, len(reserve_calls) == 1

    async def run_job(job_id: str) -> None:
        worker_calls.append(job_id)
        started.set()
        await release.wait()

    scheduler = InProcessMemoryJobScheduler(
        reserve_job=reserve_job,
        run_job=run_job,
        recover_job_ids=lambda: [],
        cancel_job=lambda _job_id: None,
        fail_job=_ignore_job,
        mode=MemoryAutomationMode.SHADOW_AUTO,
        route=MemoryExtractorRoute.FAKE,
    )

    assert scheduler.schedule(
        session_id="session-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        persona_artifact_id="persona-1",
    )
    assert not scheduler.schedule(
        session_id="session-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        persona_artifact_id="persona-1",
    )

    assert reserve_calls == [
        {
            "turn_id": "assistant-1",
            "schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION,
            "session_id": "session-1",
            "user_message_id": "user-1",
            "assistant_message_id": "assistant-1",
            "persona_artifact_id": "persona-1",
            "mode": MemoryAutomationMode.SHADOW_AUTO,
            "extractor_route": MemoryExtractorRoute.FAKE,
            "governor_version": MEMORY_GOVERNOR_VERSION,
        },
        {
            "turn_id": "assistant-1",
            "schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION,
            "session_id": "session-1",
            "user_message_id": "user-1",
            "assistant_message_id": "assistant-1",
            "persona_artifact_id": "persona-1",
            "mode": MemoryAutomationMode.SHADOW_AUTO,
            "extractor_route": MemoryExtractorRoute.FAKE,
            "governor_version": MEMORY_GOVERNOR_VERSION,
        },
    ]
    await asyncio.wait_for(started.wait(), timeout=1)
    assert worker_calls == ["job-1"]

    release.set()
    await scheduler.shutdown()
    assert worker_calls == ["job-1"]


@pytest.mark.asyncio
async def test_recover_enqueues_existing_pending_ids_in_repository_order() -> None:
    started: list[str] = []

    async def run_job(job_id: str) -> None:
        started.append(job_id)

    scheduler = InProcessMemoryJobScheduler(
        reserve_job=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("recovery must not reserve a second job")
        ),
        run_job=run_job,
        recover_job_ids=lambda: ["job-early", "job-late"],
        cancel_job=lambda _job_id: None,
        fail_job=_ignore_job,
        mode=MemoryAutomationMode.SHADOW_AUTO,
        route=MemoryExtractorRoute.LOCAL,
    )

    assert await scheduler.recover() == 2
    await scheduler.shutdown()
    assert started == ["job-early", "job-late"]


@pytest.mark.asyncio
async def test_recovery_and_schedule_share_one_active_runner_per_job_id() -> None:
    release = asyncio.Event()
    started = asyncio.Event()
    worker_calls: list[str] = []
    job = make_job("job-1", "assistant-1")

    async def run_job(job_id: str) -> None:
        worker_calls.append(job_id)
        started.set()
        await release.wait()

    scheduler = InProcessMemoryJobScheduler(
        reserve_job=lambda **_kwargs: (job, True),
        run_job=run_job,
        recover_job_ids=lambda: ["job-1"],
        cancel_job=lambda _job_id: None,
        fail_job=_ignore_job,
        mode=MemoryAutomationMode.SHADOW_AUTO,
        route=MemoryExtractorRoute.FAKE,
    )

    assert await scheduler.recover() == 1
    await asyncio.wait_for(started.wait(), timeout=1)
    assert scheduler.schedule(
        session_id="session-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        persona_artifact_id="persona-1",
    )
    await asyncio.sleep(0)
    assert worker_calls == ["job-1"]

    release.set()
    await scheduler.shutdown()


@pytest.mark.asyncio
async def test_worker_exception_is_consumed_terminalized_once_without_loop_exception_leak() -> None:
    loop = asyncio.get_running_loop()
    leaked: list[dict[str, object]] = []
    failed: list[str] = []
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: leaked.append(context))
    job = make_job("job-1", "assistant-1")

    async def run_job(_job_id: str) -> None:
        raise RuntimeError("SECRET_SENTINEL")

    try:
        scheduler = InProcessMemoryJobScheduler(
            reserve_job=lambda **_kwargs: (job, True),
            run_job=run_job,
            recover_job_ids=lambda: [],
            cancel_job=lambda _job_id: None,
            fail_job=failed.append,
            mode=MemoryAutomationMode.SHADOW_AUTO,
            route=MemoryExtractorRoute.FAKE,
        )
        assert scheduler.schedule(
            session_id="session-1",
            user_message_id="user-1",
            assistant_message_id="assistant-1",
        persona_artifact_id="persona-1",
        )
        await scheduler.shutdown()
        await asyncio.sleep(0)
    finally:
        loop.set_exception_handler(previous)

    assert failed == ["job-1"]
    assert all("SECRET_SENTINEL" not in str(item) for item in leaked)


@pytest.mark.asyncio
async def test_shutdown_cancel_records_each_running_job_once_and_rejects_future_scheduling() -> None:
    release = asyncio.Event()
    cancelled: list[str] = []
    failed: list[str] = []
    reserve_calls = 0
    job = make_job("job-1", "assistant-1")

    def reserve_job(**_kwargs: object) -> tuple[MemoryJob, bool]:
        nonlocal reserve_calls
        reserve_calls += 1
        return job, True

    async def run_job(_job_id: str) -> None:
        await release.wait()

    scheduler = InProcessMemoryJobScheduler(
        reserve_job=reserve_job,
        run_job=run_job,
        recover_job_ids=lambda: [],
        cancel_job=cancelled.append,
        fail_job=failed.append,
        mode=MemoryAutomationMode.SHADOW_AUTO,
        route=MemoryExtractorRoute.FAKE,
    )
    assert scheduler.schedule(
        session_id="session-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        persona_artifact_id="persona-1",
    )

    await scheduler.shutdown(cancel=True)

    assert cancelled == ["job-1"]
    assert failed == []
    assert not scheduler.schedule(
        session_id="session-1",
        user_message_id="user-2",
        assistant_message_id="assistant-2",
        persona_artifact_id="persona-2",
    )
    assert reserve_calls == 1


@pytest.mark.asyncio
async def test_shutdown_cancel_only_terminalizes_tasks_cancelled_by_shutdown() -> None:
    release = asyncio.Event()
    cancelled: list[str] = []
    jobs = iter([make_job("job-finished", "assistant-1"), make_job("job-blocked", "assistant-2")])

    async def run_job(job_id: str) -> None:
        if job_id == "job-blocked":
            await release.wait()

    scheduler = InProcessMemoryJobScheduler(
        reserve_job=lambda **_kwargs: (next(jobs), True),
        run_job=run_job,
        recover_job_ids=lambda: [],
        cancel_job=cancelled.append,
        fail_job=_ignore_job,
        mode=MemoryAutomationMode.SHADOW_AUTO,
        route=MemoryExtractorRoute.FAKE,
    )
    assert scheduler.schedule(
        session_id="session-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        persona_artifact_id="persona-1",
    )
    await asyncio.sleep(0)
    assert scheduler.schedule(
        session_id="session-1",
        user_message_id="user-2",
        assistant_message_id="assistant-2",
        persona_artifact_id="persona-2",
    )
    await asyncio.sleep(0)

    await scheduler.shutdown(cancel=True)
    assert cancelled == ["job-blocked"]


@pytest.mark.asyncio
async def test_scheduler_failure_callback_creates_safe_terminal_audit(tmp_path) -> None:
    from app.domain.models import ChatRole, MemoryJobAuditOutcome
    from app.repositories.memory_automation import MemoryAutomationRepository
    from app.repositories.messages import MessageRepository
    from app.repositories.sessions import SessionRepository
    from app.repositories.sqlite import managed_connection

    database_url = f"sqlite:///{tmp_path / 'scheduler-failure.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("scheduler failure")
        user = messages.add(session.id, ChatRole.USER, "user text")
        assistant = messages.add(session.id, ChatRole.ASSISTANT, "assistant text")
        automation = MemoryAutomationRepository(connection)
        job, created = automation.reserve_job(
            turn_id=assistant.id,
            schema_version=MEMORY_EXTRACTION_SCHEMA_VERSION,
            session_id=session.id,
            user_message_id=user.id,
            assistant_message_id=assistant.id,
            mode=MemoryAutomationMode.SHADOW_AUTO,
            extractor_route=MemoryExtractorRoute.FAKE,
            governor_version=MEMORY_GOVERNOR_VERSION,
        )
        assert created

    async def run_job(_job_id: str) -> None:
        raise RuntimeError("SECRET_SENTINEL")

    def fail_job(job_id: str) -> None:
        with managed_connection(database_url) as connection:
            MemoryAutomationRepository(connection).complete_job_with_audit(
                job_id,
                status=MemoryJobStatus.FAILED,
                outcome=MemoryJobAuditOutcome.FAILED,
                decision_counts={},
                reason_counts={},
                proposal_count=0,
                accepted_count=0,
                rejected_count=0,
                redaction_count=0,
                provider=None,
                model=None,
                elapsed_ms=None,
                consent_generation=None,
                error_category="database_error",
            )

    scheduler = InProcessMemoryJobScheduler(
        reserve_job=lambda **_kwargs: (job, True),
        run_job=run_job,
        recover_job_ids=lambda: [],
        cancel_job=_ignore_job,
        fail_job=fail_job,
        mode=MemoryAutomationMode.SHADOW_AUTO,
        route=MemoryExtractorRoute.FAKE,
    )
    assert scheduler.schedule(
        session_id="session-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        persona_artifact_id="persona-1",
    )
    await scheduler.shutdown()

    with managed_connection(database_url) as connection:
        automation = MemoryAutomationRepository(connection)
        failed = automation.require_job(job.id)
        audit = automation.list_audits(limit=1)[0]

    assert failed.status is MemoryJobStatus.FAILED
    assert failed.error_category == "database_error"
    assert audit.outcome is MemoryJobAuditOutcome.FAILED
    assert audit.decision_counts == audit.reason_counts == {}

    release = asyncio.Event()
    started = asyncio.Event()
    shutdown_complete = asyncio.Event()
    cancelled: list[str] = []
    job = make_job("job-1", "assistant-1")

    async def run_job(_job_id: str) -> None:
        started.set()
        await release.wait()

    scheduler = InProcessMemoryJobScheduler(
        reserve_job=lambda **_kwargs: (job, True),
        run_job=run_job,
        recover_job_ids=lambda: [],
        cancel_job=cancelled.append,
        fail_job=_ignore_job,
        mode=MemoryAutomationMode.SHADOW_AUTO,
        route=MemoryExtractorRoute.FAKE,
    )
    assert scheduler.schedule(
        session_id="session-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        persona_artifact_id="persona-1",
    )
    await asyncio.wait_for(started.wait(), timeout=1)

    async def shutdown() -> None:
        await scheduler.shutdown()
        shutdown_complete.set()

    shutdown_task = asyncio.create_task(shutdown())
    await asyncio.sleep(0)
    assert not shutdown_complete.is_set()
    assert cancelled == []

    release.set()
    await shutdown_task
    assert cancelled == []
