from __future__ import annotations

from app.core.config import Settings
from app.domain.models import Message, SessionSummary, SessionSummarySource
from app.repositories.messages import MessageRepository
from app.repositories.session_summaries import SessionSummaryRepository
from app.services.session_summary_provider import (
    SessionSummaryOptions,
    SessionSummaryProvider,
)
from app.services.session_summary_sanitizer import sanitize_summary_text


class SessionSummaryService:
    def __init__(
        self,
        messages: MessageRepository,
        summaries: SessionSummaryRepository,
        provider: SessionSummaryProvider,
        settings: Settings,
    ) -> None:
        self._messages = messages
        self._summaries = summaries
        self._provider = provider
        self._settings = settings

    async def maybe_generate_for_session(self, session_id: str) -> SessionSummary | None:
        if not self._settings.session_summary_enabled:
            return None

        all_messages = self._messages.list(session_id)
        candidates = self._messages_after_latest_coverage(session_id, all_messages)
        if len(candidates) < self._settings.session_summary_trigger_message_count:
            return None

        batch = candidates[: self._settings.session_summary_max_input_messages]
        try:
            result = await self._provider.generate(
                batch,
                SessionSummaryOptions(
                    max_tokens=self._settings.session_summary_llm_max_tokens,
                    timeout_seconds=self._settings.session_summary_llm_timeout_seconds,
                    max_retries=self._settings.session_summary_llm_max_retries,
                ),
            )
        except Exception:
            return None

        clean_text = sanitize_summary_text(result.text)
        if not clean_text:
            return None

        current_messages = self._messages.list(session_id)
        latest = self._summaries.latest_covered_for_session(session_id)
        if self._coverage_reached(latest, batch, current_messages):
            return None

        metadata = {
            "provider": result.provider,
            "model": result.model,
            "summary_schema": "session_summary_v1",
            "trigger_message_count": self._settings.session_summary_trigger_message_count,
            "max_input_messages": self._settings.session_summary_max_input_messages,
            "candidate_message_count": len(candidates),
            "input_message_count": len(batch),
        }
        try:
            return self._summaries.create(
                session_id=session_id,
                summary_text=clean_text,
                source=SessionSummarySource.GENERATED,
                covered_message_start_id=batch[0].id,
                covered_message_end_id=batch[-1].id,
                message_count=len(batch),
                metadata=metadata,
            )
        except Exception:
            return None

    def _messages_after_latest_coverage(
        self,
        session_id: str,
        all_messages: list[Message],
    ) -> list[Message]:
        latest = self._summaries.latest_covered_for_session(session_id)
        if latest is None or latest.covered_message_end_id is None:
            return all_messages
        for index, message in enumerate(all_messages):
            if message.id == latest.covered_message_end_id:
                return all_messages[index + 1 :]
        return all_messages

    @staticmethod
    def _coverage_reached(
        latest: SessionSummary | None,
        batch: list[Message],
        all_messages: list[Message],
    ) -> bool:
        if latest is None or latest.covered_message_end_id is None:
            return False
        positions = {message.id: index for index, message in enumerate(all_messages)}
        latest_end = positions.get(latest.covered_message_end_id)
        batch_start = positions.get(batch[0].id)
        return latest_end is not None and batch_start is not None and latest_end >= batch_start
