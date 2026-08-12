from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.core.config import Settings
from app.domain.models import ChatRole, Message
from app.repositories.messages import MessageRepository
from app.repositories.session_summaries import SessionSummaryRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.services.session_summary_provider import (
    SessionSummaryOptions,
    SessionSummaryProviderResult,
)
from app.services.session_summary_service import SessionSummaryService


class RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[list[Message]] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    async def generate(
        self,
        messages: list[Message],
        options: SessionSummaryOptions,
    ) -> SessionSummaryProviderResult:
        del options
        self.calls.append(messages)
        self.started.set()
        await self.release.wait()
        return SessionSummaryProviderResult(
            text="禁止内容不应被恢复。",
            provider="fake",
            model="summary-test",
        )


def _settings(*, trigger: int = 2) -> Settings:
    return Settings(
        session_summary_enabled=True,
        session_summary_trigger_message_count=trigger,
        session_summary_max_input_messages=10,
    )


def _exclude(connection, message_id: str) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO memory_summary_source_exclusions "
        "VALUES (?, 'memory_true_forget', '2026-07-21T00:00:00+00:00')",
        (message_id,),
    )
    connection.execute(
        "UPDATE memory_summary_barrier SET generation = generation + 1 "
        "WHERE singleton_id = 1"
    )
    connection.commit()


@pytest.mark.asyncio
async def test_excluded_payload_is_filtered_before_provider_dispatch(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'pre-send.db'}") as connection:
        session = SessionRepository(connection).create("barrier")
        messages = MessageRepository(connection)
        excluded = messages.add(session.id, ChatRole.USER, "FORGOTTEN_PAYLOAD_SENTINEL")
        included = messages.add(session.id, ChatRole.ASSISTANT, "safe payload")
        _exclude(connection, excluded.id)
        provider = RecordingProvider()

        created = await SessionSummaryService(
            messages,
            SessionSummaryRepository(connection),
            provider,
            _settings(trigger=1),
        ).maybe_generate_for_session(session.id)

        assert created is not None
        assert [[message.id for message in call] for call in provider.calls] == [
            [included.id]
        ]
        assert "FORGOTTEN_PAYLOAD_SENTINEL" not in "\n".join(
            message.content for call in provider.calls for message in call
        )
        assert created.observed_memory_summary_barrier == 1


@pytest.mark.asyncio
async def test_filtering_below_threshold_skips_provider_and_persistence(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'threshold.db'}") as connection:
        session = SessionRepository(connection).create("barrier")
        messages = MessageRepository(connection)
        first = messages.add(session.id, ChatRole.USER, "forgotten")
        messages.add(session.id, ChatRole.ASSISTANT, "safe")
        _exclude(connection, first.id)
        provider = RecordingProvider()
        summaries = SessionSummaryRepository(connection)

        created = await SessionSummaryService(
            messages,
            summaries,
            provider,
            _settings(trigger=2),
        ).maybe_generate_for_session(session.id)

        assert created is None
        assert provider.calls == []
        assert summaries.list_for_session(session.id) == []


@pytest.mark.asyncio
async def test_barrier_change_during_provider_discards_returned_payload(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'in-flight.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("barrier")
        messages = MessageRepository(connection)
        first = messages.add(session.id, ChatRole.USER, "source one")
        messages.add(session.id, ChatRole.ASSISTANT, "source two")
        provider = RecordingProvider()
        provider.release.clear()
        summaries = SessionSummaryRepository(connection)
        service = SessionSummaryService(messages, summaries, provider, _settings())

        task = asyncio.create_task(service.maybe_generate_for_session(session.id))
        await provider.started.wait()
        _exclude(connection, first.id)
        provider.release.set()

        assert await task is None
        assert summaries.list_for_session(session.id) == []


def test_stale_summary_reader_redacts_payload_and_marks_metadata(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'stale.db'}") as connection:
        session = SessionRepository(connection).create("barrier")
        messages = MessageRepository(connection)
        first = messages.add(session.id, ChatRole.USER, "PRIVATE_SUMMARY_SOURCE")
        last = messages.add(session.id, ChatRole.ASSISTANT, "reply")
        summaries = SessionSummaryRepository(connection)
        summary = summaries.create(
            session_id=session.id,
            summary_text="PRIVATE_SUMMARY_PAYLOAD",
            covered_message_start_id=first.id,
            covered_message_end_id=last.id,
            message_count=2,
            observed_memory_summary_barrier=0,
        )
        _exclude(connection, first.id)

        safe = summaries.latest_for_session(session.id)

        assert safe is not None and safe.id == summary.id
        assert safe.summary_text is None
        assert safe.stale is True
        assert safe.metadata["stale"] is True
        raw = connection.execute(
            "SELECT summary_text FROM session_summaries WHERE id = ?", (summary.id,)
        ).fetchone()[0]
        assert raw == "PRIVATE_SUMMARY_PAYLOAD"
