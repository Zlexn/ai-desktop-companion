from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from app.core.errors import NotFoundError
from app.repositories.context_sources import (
    ContextSourceRepository,
    ContextSourceSnapshot,
)
from app.services.summary_dispatch import SummaryDisclosureFence


class SummaryInjectionService:
    """Linearizes selected summary disclosure against queued mutations."""

    def __init__(
        self,
        context_sources: ContextSourceRepository,
        disclosure_fence: SummaryDisclosureFence,
    ) -> None:
        self._context_sources = context_sources
        self._disclosure_fence = disclosure_fence

    @asynccontextmanager
    async def revalidate_for_dispatch(
        self,
        *,
        session_id: str,
        current_user_message_id: str,
        current_user_text: str,
        sources: ContextSourceSnapshot,
    ) -> AsyncIterator[ContextSourceSnapshot]:
        async with self._disclosure_fence.hold_dispatch():
            current = self._context_sources.revalidate(
                session_id=session_id,
                current_user_message_id=current_user_message_id,
                query=current_user_text,
                snapshot=sources,
            )
            if current is None:
                raise NotFoundError("会话或当前消息不存在。")
            yield current
