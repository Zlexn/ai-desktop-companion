from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.config import Settings
from app.domain.models import ChatRole, Message, SessionSummarySource
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
    def __init__(self, result: SessionSummaryProviderResult | None = None, error: Exception | None = None) -> None:
        self.calls: list[list[Message]] = []
        self.options: list[SessionSummaryOptions] = []
        self.result = result or SessionSummaryProviderResult(
            text="本段讨论已总结。",
            provider="fake",
            model="fake-session-summary-v1",
        )
        self.error = error

    async def generate(self, messages: list[Message], options: SessionSummaryOptions) -> SessionSummaryProviderResult:
        self.calls.append(messages)
        self.options.append(options)
        if self.error is not None:
            raise self.error
        return self.result


def summary_settings(**overrides: object) -> Settings:
    values = {
        "session_summary_enabled": True,
        "session_summary_trigger_message_count": 2,
        "session_summary_max_input_messages": 4,
    }
    values.update(overrides)
    return replace(Settings(), **values)


def add_messages(repository: MessageRepository, session_id: str, roles: list[ChatRole]) -> list[Message]:
    return [repository.add(session_id, role, f"message-{index}") for index, role in enumerate(roles, start=1)]


@pytest.fixture
def repositories(tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'summary-service.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        session = sessions.create("summary-test")
        yield session, MessageRepository(connection), SessionSummaryRepository(connection)


@pytest.mark.asyncio
async def test_disabled_summary_generation_writes_nothing(repositories) -> None:
    session, messages, summaries = repositories
    add_messages(messages, session.id, [ChatRole.USER, ChatRole.ASSISTANT])
    provider = RecordingProvider()
    service = SessionSummaryService(messages, summaries, provider, summary_settings(session_summary_enabled=False))

    assert await service.maybe_generate_for_session(session.id) is None
    assert provider.calls == []
    assert summaries.list_for_session(session.id) == []


@pytest.mark.asyncio
async def test_below_threshold_writes_nothing(repositories) -> None:
    session, messages, summaries = repositories
    add_messages(messages, session.id, [ChatRole.USER])
    provider = RecordingProvider()
    service = SessionSummaryService(messages, summaries, provider, summary_settings())

    assert await service.maybe_generate_for_session(session.id) is None
    assert provider.calls == []


@pytest.mark.asyncio
async def test_exact_threshold_creates_generated_summary_with_metadata(repositories) -> None:
    session, messages, summaries = repositories
    seeded = add_messages(messages, session.id, [ChatRole.USER, ChatRole.ASSISTANT])
    provider = RecordingProvider()
    settings = summary_settings()
    service = SessionSummaryService(messages, summaries, provider, settings)

    created = await service.maybe_generate_for_session(session.id)

    assert created is not None
    assert created.source is SessionSummarySource.GENERATED
    assert created.covered_message_start_id == seeded[0].id
    assert created.covered_message_end_id == seeded[-1].id
    assert created.message_count == 2
    assert provider.calls == [seeded]
    assert created.metadata == {
        "provider": "fake",
        "model": "fake-session-summary-v1",
        "summary_schema": "session_summary_v1",
        "trigger_message_count": 2,
        "max_input_messages": 4,
        "candidate_message_count": 2,
        "input_message_count": 2,
    }


@pytest.mark.asyncio
async def test_one_call_creates_at_most_one_summary(repositories) -> None:
    session, messages, summaries = repositories
    add_messages(messages, session.id, [ChatRole.USER, ChatRole.ASSISTANT] * 3)
    provider = RecordingProvider()
    service = SessionSummaryService(messages, summaries, provider, summary_settings())

    await service.maybe_generate_for_session(session.id)

    assert len(provider.calls) == 1
    assert len(summaries.list_for_session(session.id)) == 1
    assert len(provider.calls[0]) == 4


@pytest.mark.asyncio
async def test_max_input_smaller_than_threshold_leaves_remainder(repositories) -> None:
    session, messages, summaries = repositories
    seeded = add_messages(messages, session.id, [ChatRole.USER] * 5)
    provider = RecordingProvider()
    service = SessionSummaryService(
        messages,
        summaries,
        provider,
        summary_settings(session_summary_trigger_message_count=5, session_summary_max_input_messages=3),
    )

    first = await service.maybe_generate_for_session(session.id)
    second = await service.maybe_generate_for_session(session.id)

    assert first is not None and first.covered_message_end_id == seeded[2].id
    assert second is None
    assert len(summaries.list_for_session(session.id)) == 1


@pytest.mark.asyncio
async def test_incremental_summaries_cover_only_new_messages(repositories) -> None:
    session, messages, summaries = repositories
    first_batch = add_messages(messages, session.id, [ChatRole.USER, ChatRole.ASSISTANT])
    provider = RecordingProvider()
    service = SessionSummaryService(messages, summaries, provider, summary_settings())
    first = await service.maybe_generate_for_session(session.id)
    assert await service.maybe_generate_for_session(session.id) is None
    second_batch = add_messages(messages, session.id, [ChatRole.USER, ChatRole.ASSISTANT])
    second = await service.maybe_generate_for_session(session.id)

    assert first is not None and second is not None
    assert first.covered_message_start_id == first_batch[0].id
    assert first.covered_message_end_id == first_batch[-1].id
    assert second.covered_message_start_id == second_batch[0].id
    assert second.covered_message_end_id == second_batch[-1].id
    assert provider.calls == [first_batch, second_batch]


@pytest.mark.asyncio
async def test_manual_summary_without_coverage_does_not_hide_messages(repositories) -> None:
    session, messages, summaries = repositories
    seeded = add_messages(messages, session.id, [ChatRole.USER, ChatRole.ASSISTANT])
    summaries.create(session_id=session.id, summary_text="manual")
    provider = RecordingProvider()
    service = SessionSummaryService(messages, summaries, provider, summary_settings())

    created = await service.maybe_generate_for_session(session.id)

    assert created is not None
    assert provider.calls == [seeded]


@pytest.mark.asyncio
async def test_manual_summary_after_generated_coverage_does_not_repeat_old_messages(repositories) -> None:
    session, messages, summaries = repositories
    first_batch = add_messages(messages, session.id, [ChatRole.USER, ChatRole.ASSISTANT])
    provider = RecordingProvider()
    service = SessionSummaryService(messages, summaries, provider, summary_settings())
    first = await service.maybe_generate_for_session(session.id)
    summaries.create(session_id=session.id, summary_text="newer manual summary")

    repeated = await service.maybe_generate_for_session(session.id)

    assert first is not None
    assert first.covered_message_end_id == first_batch[-1].id
    assert repeated is None
    assert provider.calls == [first_batch]


@pytest.mark.asyncio
async def test_unmatched_user_message_is_passed_as_raw_segment(repositories) -> None:
    session, messages, summaries = repositories
    seeded = add_messages(messages, session.id, [ChatRole.USER, ChatRole.ASSISTANT, ChatRole.USER])
    provider = RecordingProvider()
    service = SessionSummaryService(
        messages,
        summaries,
        provider,
        summary_settings(session_summary_trigger_message_count=3),
    )

    assert await service.maybe_generate_for_session(session.id) is not None
    assert [message.role for message in provider.calls[0]] == [message.role for message in seeded]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider",
    [
        RecordingProvider(error=RuntimeError("provider failed")),
        RecordingProvider(SessionSummaryProviderResult(text=" \n ", provider="fake", model="fake")),
    ],
)
async def test_provider_failure_or_empty_output_writes_nothing(repositories, provider) -> None:
    session, messages, summaries = repositories
    add_messages(messages, session.id, [ChatRole.USER, ChatRole.ASSISTANT])
    service = SessionSummaryService(messages, summaries, provider, summary_settings())

    assert await service.maybe_generate_for_session(session.id) is None
    assert summaries.list_for_session(session.id) == []


@pytest.mark.asyncio
async def test_provider_output_is_sanitized_before_persistence(repositories) -> None:
    session, messages, summaries = repositories
    add_messages(messages, session.id, [ChatRole.USER, ChatRole.ASSISTANT])
    provider = RecordingProvider(
        SessionSummaryProviderResult(
            text="继续讨论。api_key=sk-secret-value",
            provider="custom",
            model="custom-model",
        )
    )
    service = SessionSummaryService(messages, summaries, provider, summary_settings())

    created = await service.maybe_generate_for_session(session.id)

    assert created is not None
    assert "sk-secret-value" not in created.summary_text
    assert "[REDACTED]" in created.summary_text


@pytest.mark.asyncio
async def test_same_timestamp_messages_keep_insertion_order_for_coverage(repositories) -> None:
    session, messages, summaries = repositories
    fixed_time = datetime(2026, 7, 11, 12, 0, tzinfo=UTC).isoformat()
    connection = messages._connection
    ordered_ids = ["message-z", "message-a"]
    for message_id in ordered_ids:
        connection.execute(
            """
            INSERT INTO messages (id, session_id, role, content, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (message_id, session.id, ChatRole.USER.value, message_id, "{}", fixed_time),
        )
    connection.commit()
    provider = RecordingProvider()
    service = SessionSummaryService(messages, summaries, provider, summary_settings())

    created = await service.maybe_generate_for_session(session.id)

    assert created is not None
    assert [message.id for message in provider.calls[0]] == ordered_ids
    assert created.covered_message_start_id == ordered_ids[0]
    assert created.covered_message_end_id == ordered_ids[-1]


@pytest.mark.asyncio
async def test_competing_summary_inserted_during_generation_prevents_overlap(repositories) -> None:
    session, messages, summaries = repositories
    seeded = add_messages(messages, session.id, [ChatRole.USER, ChatRole.ASSISTANT])

    class CompetingProvider(RecordingProvider):
        async def generate(self, batch, options):
            summaries.create(
                session_id=session.id,
                summary_text="competing",
                source=SessionSummarySource.GENERATED,
                covered_message_start_id=seeded[0].id,
                covered_message_end_id=seeded[-1].id,
                message_count=2,
            )
            return await super().generate(batch, options)

    service = SessionSummaryService(messages, summaries, CompetingProvider(), summary_settings())

    assert await service.maybe_generate_for_session(session.id) is None
    assert [summary.summary_text for summary in summaries.list_for_session(session.id)] == ["competing"]
