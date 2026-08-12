from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import TracebackType
from typing import AsyncIterator


class _PriorityMutation:
    def __init__(self, fence: PriorityAsyncFence) -> None:
        self._fence = fence
        self._entered = False
        self._finished = False

    async def __aenter__(self) -> None:
        try:
            await self._fence._lock.acquire()
        except BaseException:
            self._finish()
            raise
        self._entered = True

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        if self._entered:
            self._fence._lock.release()
            self._entered = False
        self._finish()

    def _finish(self) -> None:
        if not self._finished:
            self._fence._pending_mutations -= 1
            self._finished = True


class PriorityAsyncFence:
    """Serializes dispatch while giving already-queued mutations priority."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._pending_mutations = 0

    def begin_mutation(self) -> _PriorityMutation:
        self._pending_mutations += 1
        return _PriorityMutation(self)

    def has_pending_mutation(self) -> bool:
        return self._pending_mutations > 0

    @asynccontextmanager
    async def hold_dispatch(self) -> AsyncIterator[bool]:
        mutation_was_queued = self._pending_mutations > 0
        async with self._lock:
            yield not mutation_was_queued and self._pending_mutations == 0


class SummaryProcessingFence(PriorityAsyncFence):
    pass


class SummaryDisclosureFence(PriorityAsyncFence):
    pass
