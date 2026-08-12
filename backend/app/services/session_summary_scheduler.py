from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol

from app.domain.session_summary import SummaryJob


class SessionSummaryScheduler(Protocol):
    def schedule(self, session_id: str, *, chat_turn_id: str | None = None) -> bool: ...

    def start_job(self, job: SummaryJob) -> bool: ...


class NoOpSessionSummaryScheduler:
    def schedule(self, session_id: str, *, chat_turn_id: str | None = None) -> bool:
        del session_id, chat_turn_id
        return False

    def start_job(self, job: SummaryJob) -> bool:
        del job
        return False

    async def recover(self) -> int:
        return 0

    async def shutdown(
        self,
        timeout_seconds: float = 5.0,
        *,
        cancel: bool = False,
    ) -> None:
        del timeout_seconds, cancel


class DurableSessionSummaryScheduler:
    def __init__(
        self,
        *,
        reserve_for_turn: Callable[
            [str, str], tuple[SummaryJob, bool] | None
        ],
        run_job: Callable[[str, str], Awaitable[None]],
        recover_job_ids: Callable[[], tuple[list[SummaryJob], list[str]]],
        fail_incompatible: Callable[[str], None],
        cancel_job: Callable[[str], None],
        fail_job: Callable[[str], None],
        claim_job: Callable[[str], SummaryJob | None] | None = None,
    ) -> None:
        self._reserve_for_turn = reserve_for_turn
        self._run_job = run_job
        self._recover_job_ids = recover_job_ids
        self._claim_job = claim_job
        self._fail_incompatible = fail_incompatible
        self._cancel_job = cancel_job
        self._fail_job = fail_job
        self._accepting = True
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def schedule(self, session_id: str, *, chat_turn_id: str | None = None) -> bool:
        if not self._accepting or chat_turn_id is None:
            return False
        reservation = self._reserve_for_turn(session_id, chat_turn_id)
        if reservation is None:
            return False
        job, created = reservation
        if not created or not self._is_pending(job):
            return False
        return self._start(job.id, job.session_id)

    def start_job(self, job: SummaryJob) -> bool:
        if not self._accepting or not self._is_pending(job):
            return False
        return self._start(job.id, job.session_id)

    async def recover(self) -> int:
        if not self._accepting:
            return 0
        recoverable, incompatible = self._recover_job_ids()
        for job_id in incompatible:
            self._fail_incompatible(job_id)
        return sum(
            int(self._start(job.id, job.session_id)) for job in recoverable
        )

    async def shutdown(
        self,
        timeout_seconds: float = 5.0,
        *,
        cancel: bool = False,
    ) -> None:
        self._accepting = False
        tasks = list(self._tasks.items())
        cancelled_job_ids: list[str] = []
        if cancel:
            for job_id, task in tasks:
                if not task.done():
                    task.cancel()
                    cancelled_job_ids.append(job_id)
        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        *(task for _, task in tasks),
                        return_exceptions=True,
                    ),
                    timeout=timeout_seconds,
                )
            except TimeoutError:
                for job_id, task in tasks:
                    if not task.done():
                        task.cancel()
                        cancelled_job_ids.append(job_id)
                await asyncio.gather(
                    *(task for _, task in tasks),
                    return_exceptions=True,
                )
        for job_id in dict.fromkeys(cancelled_job_ids):
            self._cancel_job(job_id)

    @staticmethod
    def _is_pending(job: SummaryJob) -> bool:
        status = getattr(job, "status", "pending")
        return getattr(status, "value", status) == "pending"

    async def _run_claimed(self, job_id: str, session_id: str) -> None:
        if self._claim_job is not None and self._claim_job(job_id) is None:
            return
        await self._run_job(job_id, session_id)

    def _start(self, job_id: str, session_id: str) -> bool:
        current = self._tasks.get(job_id)
        if current is not None and not current.done():
            return False
        task = asyncio.create_task(
            self._run_claimed(job_id, session_id),
            name=f"summary-job-{job_id}",
        )
        self._tasks[job_id] = task
        task.add_done_callback(
            lambda completed, completed_id=job_id: self._consume(
                completed_id,
                completed,
            )
        )
        return True

    def _consume(self, job_id: str, task: asyncio.Task[None]) -> None:
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


class InProcessSessionSummaryScheduler:
    """Legacy best-effort facade retained only for direct compatibility callers."""

    def __init__(self, job: Callable[[str], Awaitable[None]]) -> None:
        self._job = job
        self._tasks_by_session: dict[str, asyncio.Task[None]] = {}
        self._dirty_sessions: set[str] = set()
        self._closing = False

    def schedule(self, session_id: str, *, chat_turn_id: str | None = None) -> bool:
        del chat_turn_id
        if self._closing:
            return False
        existing = self._tasks_by_session.get(session_id)
        if existing is not None and not existing.done():
            self._dirty_sessions.add(session_id)
            return False
        self._start_task(session_id)
        return True

    def start_job(self, job: SummaryJob) -> bool:
        return self.schedule(job.session_id)

    async def recover(self) -> int:
        return 0

    async def shutdown(
        self,
        timeout_seconds: float = 5.0,
        *,
        cancel: bool = False,
    ) -> None:
        self._closing = True
        self._dirty_sessions.clear()
        tasks = list(self._tasks_by_session.values())
        if not tasks:
            return
        if cancel:
            for task in tasks:
                if not task.done():
                    task.cancel()
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def _start_task(self, session_id: str) -> None:
        task = asyncio.create_task(self._run_safely(session_id))
        self._tasks_by_session[session_id] = task
        task.add_done_callback(
            lambda completed: self._discard_task(session_id, completed)
        )

    async def _run_safely(self, session_id: str) -> None:
        try:
            await self._job(session_id)
        except Exception:
            pass

    def _discard_task(self, session_id: str, task: asyncio.Task[None]) -> None:
        if self._tasks_by_session.get(session_id) is task:
            self._tasks_by_session.pop(session_id, None)
        if not self._closing and session_id in self._dirty_sessions:
            self._dirty_sessions.discard(session_id)
            self._start_task(session_id)
