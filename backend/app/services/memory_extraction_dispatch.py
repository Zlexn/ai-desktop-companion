from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import TracebackType
from typing import AsyncIterator

from app.services.memory_extraction_contract import (
    MEMORY_EXTRACTION_DISCLOSED_FIELDS,
    MEMORY_EXTRACTION_DISCLOSURE_VERSION,
    MEMORY_EXTRACTION_PURPOSE,
)


class ConsentMutation:
    def __init__(self, fence: MemoryExtractionDispatchFence) -> None:
        self._fence = fence
        self._entered = False

    async def __aenter__(self) -> None:
        try:
            await self._fence._lock.acquire()
        except BaseException:
            self._fence._pending_consent_mutations -= 1
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
        self._fence._pending_consent_mutations -= 1


class MemoryExtractionDispatchFence:
    """Serializes remote extraction while prioritizing queued consent changes."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._pending_consent_mutations = 0

    def begin_consent_mutation(self) -> ConsentMutation:
        self._pending_consent_mutations += 1
        return ConsentMutation(self)

    def has_pending_consent_mutation(self) -> bool:
        return self._pending_consent_mutations > 0

    @asynccontextmanager
    async def hold(self) -> AsyncIterator[bool]:
        async with self._lock:
            yield self._pending_consent_mutations == 0
