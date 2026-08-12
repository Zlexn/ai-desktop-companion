from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol

from app.domain.models import (
    MemoryAutomationMode,
    MemoryExtractorRoute,
    MemoryJob,
)
from app.services.memory_extractor import MEMORY_EXTRACTION_SCHEMA_VERSION
from app.services.memory_governor import MEMORY_GOVERNOR_VERSION


class MemoryJobScheduler(Protocol):
    def schedule(
        self,
        *,
        session_id: str,
        user_message_id: str,
        assistant_message_id: str,
        persona_artifact_id: str,
        chat_turn_id: str | None = None,
        turn_completed_at: datetime | None = None,
    ) -> bool: ...


class NoOpMemoryJobScheduler:
    def schedule(
        self,
        *,
        session_id: str,
        user_message_id: str,
        assistant_message_id: str,
        persona_artifact_id: str,
        chat_turn_id: str | None = None,
        turn_completed_at: datetime | None = None,
    ) -> bool:
        del persona_artifact_id, chat_turn_id, turn_completed_at
        return False


class InProcessMemoryJobScheduler:
    def __init__(
        self,
        *,
        reserve_job: Callable[..., tuple[MemoryJob, bool]],
        run_job: Callable[[str], Awaitable[None]],
        recover_job_ids: Callable[[], list[str]],
        cancel_job: Callable[[str], None],
        fail_job: Callable[[str], None],
        mode: MemoryAutomationMode,
        route: MemoryExtractorRoute,
        reservation_factory: Callable[..., dict[str, object]] | None = None,
    ) -> None:
        if mode not in {
            MemoryAutomationMode.SHADOW_AUTO,
            MemoryAutomationMode.AUTO_ACTIVE,
        }:
            raise ValueError("memory job scheduler requires an automatic mode")

        self._reserve_job = reserve_job
        self._run_job = run_job
        self._recover_job_ids = recover_job_ids
        self._cancel_job = cancel_job
        self._fail_job = fail_job
        self._mode = mode
        self._route = route
        self._reservation_factory = reservation_factory
        self._accepting = True
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def schedule(
        self,
        *,
        session_id: str,
        user_message_id: str,
        assistant_message_id: str,
        persona_artifact_id: str,
        chat_turn_id: str | None = None,
        turn_completed_at: datetime | None = None,
    ) -> bool:
        if not self._accepting:
            return False

        if self._mode is MemoryAutomationMode.AUTO_ACTIVE:
            if turn_completed_at is None or self._reservation_factory is None:
                return False
            reservation_kwargs: dict[str, object] = {
                "session_id": session_id,
                "user_message_id": user_message_id,
                "assistant_message_id": assistant_message_id,
                "persona_artifact_id": persona_artifact_id,
                "turn_completed_at": turn_completed_at,
            }
            if chat_turn_id is not None:
                reservation_kwargs["chat_turn_id"] = chat_turn_id
            reservation = self._reservation_factory(**reservation_kwargs)
        else:
            reservation = {
                "turn_id": assistant_message_id,
                "schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION,
                "session_id": session_id,
                "user_message_id": user_message_id,
                "assistant_message_id": assistant_message_id,
                "persona_artifact_id": persona_artifact_id,
                "mode": MemoryAutomationMode.SHADOW_AUTO,
                "extractor_route": self._route,
                "governor_version": MEMORY_GOVERNOR_VERSION,
            }
        job, created = self._reserve_job(**reservation)
        if not created:
            return False

        self._start(job.id)
        return True

    async def recover(self) -> int:
        if not self._accepting:
            return 0

        started = 0
        for job_id in self._recover_job_ids():
            started += int(self._start(job_id))
        return started

    async def shutdown(self, *, cancel: bool = False) -> None:
        self._accepting = False
        tasks = list(self._tasks.items())
        cancelled_job_ids: list[str] = []

        if cancel:
            for job_id, task in tasks:
                if not task.done():
                    task.cancel()
                    cancelled_job_ids.append(job_id)

        if tasks:
            await asyncio.gather(
                *(task for _, task in tasks),
                return_exceptions=True,
            )

        for job_id in cancelled_job_ids:
            self._cancel_job(job_id)

    def _start(self, job_id: str) -> bool:
        active = self._tasks.get(job_id)
        if active is not None and not active.done():
            return False

        task = asyncio.create_task(
            self._run_job(job_id),
            name=f"memory-job-{job_id}",
        )
        self._tasks[job_id] = task
        task.add_done_callback(
            lambda completed, completed_job_id=job_id: self._consume_task(
                completed_job_id,
                completed,
            )
        )
        return True

    def _consume_task(self, job_id: str, task: asyncio.Task[None]) -> None:
        if self._tasks.get(job_id) is task:
            self._tasks.pop(job_id, None)
        if task.cancelled():
            return
        try:
            exception = task.exception()
        except asyncio.CancelledError:
            return
        if exception is not None:
            self._fail_job(job_id)
