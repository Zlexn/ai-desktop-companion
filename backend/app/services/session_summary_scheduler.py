from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol


class SessionSummaryScheduler(Protocol):
    def schedule(self, session_id: str) -> None: ...


class InProcessSessionSummaryScheduler:
    def __init__(self, job: Callable[[str], Awaitable[None]]) -> None:
        self._job = job
        self._tasks_by_session: dict[str, asyncio.Task[None]] = {}
        self._dirty_sessions: set[str] = set()
        self._closing = False

    def schedule(self, session_id: str) -> None:
        if self._closing:
            return
        existing = self._tasks_by_session.get(session_id)
        if existing is not None and not existing.done():
            self._dirty_sessions.add(session_id)
            return
        self._start_task(session_id)

    async def shutdown(self, timeout_seconds: float = 5.0) -> None:
        self._closing = True
        self._dirty_sessions.clear()
        tasks = list(self._tasks_by_session.values())
        if not tasks:
            return
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
        task.add_done_callback(lambda completed: self._discard_task(session_id, completed))

    async def _run_safely(self, session_id: str) -> None:
        try:
            await self._job(session_id)
        except Exception:
            # Summary work is best effort and cannot fail chat.
            pass

    def _discard_task(self, session_id: str, task: asyncio.Task[None]) -> None:
        if self._tasks_by_session.get(session_id) is task:
            self._tasks_by_session.pop(session_id, None)
        if not self._closing and session_id in self._dirty_sessions:
            self._dirty_sessions.discard(session_id)
            self._start_task(session_id)
