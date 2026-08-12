from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.config import Settings
from app.domain.models import ChatRole
from app.domain.session_summary import SummaryJobStatus
from app.repositories.chat_turns import ChatTurnRepository
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.repositories.summary_automation import SummaryAutomationRepository
from app.services.session_summary_provider import (
    SessionSummaryOptions,
    SessionSummaryProviderResult,
)
from app.services.session_summary_service import (
    SummaryJobReservationService,
    build_summary_processing_policy,
)
from app.services.summary_dispatch import SummaryProcessingFence
from app.services.summary_job_service import SummaryJobService


def _settings(database_url: str, *, remote: bool = False) -> Settings:
    return Settings(
        database_url=database_url,
        session_summary_provider="llm" if remote else "fake",
        session_summary_trigger_turn_count=1,
        session_summary_max_input_turns=2,
        session_summary_max_input_messages=4,
        session_summary_max_input_characters=10_000,
        session_summary_llm_provider="deepseek",
        session_summary_llm_model="deepseek-chat",
        session_summary_max_output_characters=2_000,
        summary_job_max_attempts=3,
    )


def _reserve(
    database_url: str,
    settings: Settings,
    *,
    authorize: bool,
):
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("job")
        user = MessageRepository(connection).add(
            session.id,
            ChatRole.USER,
            "bounded user source",
        )
        _, turn = ChatTurnRepository(connection).append_assistant_turn(
            session_id=session.id,
            user_message_id=user.id,
            content="bounded assistant source",
            metadata={},
        )
        automation = SummaryAutomationRepository(connection)
        if authorize:
            policy = build_summary_processing_policy(settings)
            current = automation.get_processing_authority()
            automation.mutate_processing(
                action="grant" if remote_route(settings) else "enable_local",
                expected_generation=current.generation,
                policy=policy,
            )
        reservation = SummaryJobReservationService(
            connection,
            settings=settings,
        ).reserve_for_turn(session.id, turn.id)
        assert reservation is not None
        return reservation[0], session.id


def remote_route(settings: Settings) -> bool:
    return settings.session_summary_provider == "llm"


class RecordingProvider:
    def __init__(self, *, text: str = "安全的会话连续性摘要。") -> None:
        self.text = text
        self.calls = 0
        self.closed = False
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.block = False

    async def generate(self, messages, options: SessionSummaryOptions):
        assert messages
        assert options.max_tokens > 0
        self.calls += 1
        self.started.set()
        if self.block:
            await self.release.wait()
        return SessionSummaryProviderResult(
            text=self.text,
            provider="recording",
            model="recording-model",
        )

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_remote_without_exact_processing_authority_constructs_and_sends_nothing(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'no-authority.db'}"
    settings = _settings(database_url, remote=True)
    job, _ = _reserve(database_url, settings, authorize=False)
    factory_calls = 0

    def forbidden_factory():
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("remote Provider must not be constructed")

    service = SummaryJobService(
        database_url=database_url,
        settings=settings,
        processing_fence=SummaryProcessingFence(),
        remote_provider_factory=forbidden_factory,
    )

    result = await service.process(job.id)

    assert result.status is SummaryJobStatus.SKIPPED
    assert result.reason_code == "skipped_no_consent"
    assert factory_calls == 0
    with managed_connection(database_url) as connection:
        assert connection.execute("SELECT COUNT(*) FROM session_summaries").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_fake_job_commits_exact_summary_and_sources_atomically(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'fake-commit.db'}"
    settings = _settings(database_url)
    job, session_id = _reserve(database_url, settings, authorize=True)
    provider = RecordingProvider()
    service = SummaryJobService(
        database_url=database_url,
        settings=settings,
        processing_fence=SummaryProcessingFence(),
        fake_provider_factory=lambda: provider,
    )

    result = await service.process(job.id)

    assert result.status is SummaryJobStatus.SUCCEEDED
    assert provider.calls == 1
    assert provider.closed is True
    with managed_connection(database_url) as connection:
        summary = connection.execute(
            "SELECT * FROM session_summaries WHERE session_id=?",
            (session_id,),
        ).fetchone()
        assert summary is not None
        assert summary["summary_text"] == "安全的会话连续性摘要。"
        assert summary["payload_state"] == "active"
        assert summary["provenance_state"] == "exact"
        assert summary["source_set_hash"] == job.source_set_hash
        sources = connection.execute(
            "SELECT message_id, source_order FROM session_summary_sources "
            "WHERE summary_id=? ORDER BY source_order",
            (summary["id"],),
        ).fetchall()
        assert len(sources) == 2
        assert [row["source_order"] for row in sources] == [0, 1]


@pytest.mark.asyncio
async def test_provider_generate_runs_without_open_sqlite_transaction(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'no-transaction.db'}"
    settings = _settings(database_url)
    job, _ = _reserve(database_url, settings, authorize=True)

    class TransactionCheckingProvider(RecordingProvider):
        async def generate(self, messages, options):
            with managed_connection(database_url) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("ROLLBACK")
            return await super().generate(messages, options)

    provider = TransactionCheckingProvider()
    service = SummaryJobService(
        database_url=database_url,
        settings=settings,
        processing_fence=SummaryProcessingFence(),
        fake_provider_factory=lambda: provider,
    )

    result = await service.process(job.id)

    assert result.status is SummaryJobStatus.SUCCEEDED


@pytest.mark.asyncio
@pytest.mark.parametrize("remote", [False, True])
async def test_processing_fence_covers_local_and_remote_provider_io(
    tmp_path: Path,
    remote: bool,
) -> None:
    database_url = f"sqlite:///{tmp_path / f'provider-fence-{remote}.db'}"
    settings = _settings(database_url, remote=remote)
    job, _ = _reserve(database_url, settings, authorize=True)
    provider = RecordingProvider()
    provider.block = True
    fence = SummaryProcessingFence()
    service = SummaryJobService(
        database_url=database_url,
        settings=settings,
        processing_fence=fence,
        fake_provider_factory=lambda: provider,
        remote_provider_factory=lambda: provider,
    )

    task = asyncio.create_task(service.process(job.id))
    await provider.started.wait()
    mutation_entered = asyncio.Event()

    async def mutate() -> None:
        async with fence.begin_mutation():
            mutation_entered.set()

    mutation = asyncio.create_task(mutate())
    await asyncio.sleep(0)
    assert mutation_entered.is_set() is False
    provider.release.set()
    result = await task
    await mutation

    assert result.status is SummaryJobStatus.SUCCEEDED
    assert mutation_entered.is_set() is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    ["revoke", "barrier", "exclusion", "provider_policy"],
)
async def test_inflight_mutation_discards_remote_result(
    tmp_path: Path,
    mutation: str,
) -> None:
    database_url = f"sqlite:///{tmp_path / f'discard-{mutation}.db'}"
    settings = _settings(database_url, remote=True)
    job, _ = _reserve(database_url, settings, authorize=True)
    provider = RecordingProvider()
    provider.block = True
    fence = SummaryProcessingFence()
    service = SummaryJobService(
        database_url=database_url,
        settings=settings,
        processing_fence=fence,
        remote_provider_factory=lambda: provider,
    )

    task = asyncio.create_task(service.process(job.id))
    await provider.started.wait()
    with managed_connection(database_url) as connection:
        if mutation == "revoke":
            automation = SummaryAutomationRepository(connection)
            policy = build_summary_processing_policy(settings)
            current = automation.get_processing_authority()
            automation.mutate_processing(
                action="revoke",
                expected_generation=current.generation,
                policy=policy,
            )
        elif mutation == "barrier":
            connection.execute(
                "UPDATE memory_summary_barrier SET generation=generation+1 "
                "WHERE singleton_id=1"
            )
            connection.commit()
        elif mutation == "provider_policy":
            object.__setattr__(
                settings,
                "session_summary_llm_max_tokens",
                settings.session_summary_llm_max_tokens + 1,
            )
        else:
            source_id = connection.execute(
                "SELECT message_id FROM summary_job_sources WHERE job_id=? "
                "ORDER BY source_order LIMIT 1",
                (job.id,),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO memory_summary_source_exclusions "
                "(source_message_id, reason_code, created_at) VALUES (?, ?, ?)",
                (source_id, "test_exclusion", datetime.now(UTC).isoformat()),
            )
            connection.commit()
    provider.release.set()

    result = await task

    assert result.status is SummaryJobStatus.SKIPPED
    assert result.reason_code is not None
    assert result.reason_code.startswith("discarded_")
    assert provider.closed is True
    with managed_connection(database_url) as connection:
        assert connection.execute("SELECT COUNT(*) FROM session_summaries").fetchone()[0] == 0
        audit = connection.execute(
            "SELECT status, reason_code FROM summary_job_audits "
            "WHERE job_id=? ORDER BY created_at DESC LIMIT 1",
            (job.id,),
        ).fetchone()
        assert tuple(audit) == ("skipped", result.reason_code)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("   ", "invalid_output"),
        ("api_key=sk-secret-value", "credential_output"),
        ("x" * 2_001, "oversized_output"),
    ],
)
async def test_invalid_provider_output_never_commits(
    tmp_path: Path,
    text: str,
    reason: str,
) -> None:
    database_url = f"sqlite:///{tmp_path / f'{reason}.db'}"
    settings = _settings(database_url)
    job, _ = _reserve(database_url, settings, authorize=True)
    provider = RecordingProvider(text=text)
    service = SummaryJobService(
        database_url=database_url,
        settings=settings,
        processing_fence=SummaryProcessingFence(),
        fake_provider_factory=lambda: provider,
    )

    result = await service.process(job.id)

    assert result.status is SummaryJobStatus.FAILED
    assert result.reason_code == reason
    with managed_connection(database_url) as connection:
        assert connection.execute("SELECT COUNT(*) FROM session_summaries").fetchone()[0] == 0
        raw = "\n".join(
            str(tuple(row))
            for row in connection.execute(
                "SELECT * FROM summary_jobs WHERE id=?",
                (job.id,),
            )
        )
        assert "sk-secret-value" not in raw
