from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol


class EmotionAnalysisScheduler(Protocol):
    def schedule(
        self,
        user_message_id: str,
        assistant_message_id: str,
        base_emotion_version: int,
    ) -> None: ...


class InProcessEmotionAnalysisScheduler:
    def __init__(self, job: Callable[[str, str, int], Awaitable[None]]) -> None:
        self._job = job
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._closing = False

    def schedule(
        self,
        user_message_id: str,
        assistant_message_id: str,
        base_emotion_version: int,
    ) -> None:
        if self._closing or assistant_message_id in self._tasks:
            return
        task = asyncio.create_task(
            self._run_safely(
                user_message_id,
                assistant_message_id,
                base_emotion_version,
            )
        )
        self._tasks[assistant_message_id] = task
        task.add_done_callback(
            lambda completed: self._discard(assistant_message_id, completed)
        )

    async def shutdown(self, timeout_seconds: float = 5.0) -> None:
        self._closing = True
        tasks = list(self._tasks.values())
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

    async def _run_safely(
        self,
        user_message_id: str,
        assistant_message_id: str,
        base_emotion_version: int,
    ) -> None:
        try:
            await self._job(
                user_message_id,
                assistant_message_id,
                base_emotion_version,
            )
        except Exception:
            # Remote analysis is best effort and cannot fail chat.
            pass

    def _discard(self, assistant_message_id: str, task: asyncio.Task[None]) -> None:
        if self._tasks.get(assistant_message_id) is task:
            self._tasks.pop(assistant_message_id, None)
