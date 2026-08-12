from __future__ import annotations

import asyncio
from pathlib import Path
import threading

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.domain.models import ChatRole
from app.main import create_app
from app.repositories.chat_turns import ChatTurnRepository
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.repositories.summary_automation import SummaryAutomationRepository
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.services.memory_source_reference import MemorySourceReferenceService
from app.services.session_deletion_coordinator import SessionDeletionCoordinator
from app.services.session_summary_contract import SUMMARY_SCHEMA_VERSION
from app.services.session_summary_provider import SessionSummaryProviderResult
from app.services.session_summary_scheduler import DurableSessionSummaryScheduler
from app.services.session_summary_service import (
    SummaryJobReservationService,
    build_summary_processing_policy,
    summary_provider_policy_for_settings,
)
from app.services.summary_dispatch import SummaryProcessingFence
from app.services.summary_job_service import SummaryJobService


def _settings(database_url: str, key_path: Path) -> Settings:
    return Settings(
        database_url=database_url,
        memory_source_reference_key_path=key_path,
        llm_provider="fake",
        llm_model="test-model",
        session_summary_enabled=True,
        session_summary_provider="llm",
        session_summary_llm_provider="anthropic",
        session_summary_llm_model="fixture-model",
        anthropic_api_key="test-key",
        session_summary_trigger_turn_count=1,
        session_summary_max_input_turns=3,
        session_summary_max_input_messages=6,
        session_summary_max_input_characters=10_000,
    )


def _reserve_summary_job(
    database_url: str,
    settings: Settings,
    references: MemorySourceReferenceService,
):
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("delete source")
        user = MessageRepository(connection).add(
            session.id,
            ChatRole.USER,
            "delete while summarizing",
        )
        _, turn = ChatTurnRepository(connection).append_assistant_turn(
            session_id=session.id,
            user_message_id=user.id,
            content="summary source reply",
            metadata={},
        )
        automation = SummaryAutomationRepository(connection)
        policy = build_summary_processing_policy(settings)
        authority = automation.get_processing_authority()
        automation.mutate_processing(
            action="grant",
            expected_generation=authority.generation,
            policy=policy,
        )
        reservation = SummaryJobReservationService(
            connection,
            settings=settings,
            session_deletion_generation=(
                lambda source_session_id: VersionedMemoryRepository(
                    connection
                ).read_deletion_generations(
                    session_reference_hash=references.session_hash(
                        source_session_id
                    )
                ).session_generation
            ),
        ).reserve_for_turn(session.id, turn.id)
        assert reservation is not None
        return session.id, reservation[0]


@pytest.mark.asyncio
async def test_source_session_deleted_during_generation_discards_and_cascades(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'delete-generation.db'}"
    references = MemorySourceReferenceService(b"d" * 32)
    settings = _settings(database_url, tmp_path / "delete-generation.key")
    session_id, job = _reserve_summary_job(database_url, settings, references)
    started = asyncio.Event()
    release = asyncio.Event()

    class BlockingProvider:
        async def generate(self, messages, options):
            started.set()
            await release.wait()
            return SessionSummaryProviderResult(
                text="must be discarded",
                provider="fake",
                model="blocking",
            )

        async def aclose(self) -> None:
            return None

    worker = asyncio.create_task(
        SummaryJobService(
            database_url=database_url,
            settings=settings,
            processing_fence=SummaryProcessingFence(),
            remote_provider_factory=BlockingProvider,
            session_deletion_generation=(
                lambda source_session_id: _deletion_generation(
                    database_url,
                    references,
                    source_session_id,
                )
            ),
        ).process(job.id)
    )
    await asyncio.wait_for(started.wait(), timeout=5)

    with managed_connection(database_url) as connection:
        SessionDeletionCoordinator(
            connection,
            versioned=VersionedMemoryRepository(connection),
            source_references=references,
        ).delete(session_id)

    release.set()
    result = await asyncio.wait_for(worker, timeout=5)
    assert result is None

    with managed_connection(database_url) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM sessions WHERE id=?",
            (session_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM session_summaries WHERE session_id=?",
            (session_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM summary_jobs WHERE session_id=?",
            (session_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM summary_source_suppressions WHERE session_id=?",
            (session_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM summary_job_audits WHERE job_id=?",
            (job.id,),
        ).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_scheduler_worker_accepts_preclaim_session_cascade_without_failure(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'delete-before-claim.db'}"
    references = MemorySourceReferenceService(b"q" * 32)
    settings = _settings(database_url, tmp_path / "delete-before-claim.key")
    session_id, job = _reserve_summary_job(database_url, settings, references)
    failed_job_ids: list[str] = []
    observed_owners: list[tuple[str, str]] = []
    provider_calls = 0

    def forbidden_provider():
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("deleted session must not construct a Provider")

    service = SummaryJobService(
        database_url=database_url,
        settings=settings,
        processing_fence=SummaryProcessingFence(),
        remote_provider_factory=forbidden_provider,
        session_deletion_generation=(
            lambda source_session_id: _deletion_generation(
                database_url,
                references,
                source_session_id,
            )
        ),
    )

    async def run_job(job_id: str, expected_session_id: str) -> None:
        observed_owners.append((job_id, expected_session_id))
        result = await service.process(
            job_id,
            expected_session_id=expected_session_id,
        )
        assert result is None

    scheduler = DurableSessionSummaryScheduler(
        reserve_for_turn=lambda reserved_session_id, _turn_id: (
            (job, True) if reserved_session_id == session_id else None
        ),
        run_job=run_job,
        recover_job_ids=lambda: ([], []),
        fail_incompatible=lambda _job_id: None,
        cancel_job=lambda _job_id: None,
        fail_job=failed_job_ids.append,
    )
    assert scheduler.schedule(session_id, chat_turn_id="turn") is True

    # No event-loop yield has occurred since schedule(), so deletion commits before
    # the created worker can perform its first summary_jobs repository read.
    with managed_connection(database_url) as connection:
        SessionDeletionCoordinator(
            connection,
            versioned=VersionedMemoryRepository(connection),
            source_references=references,
        ).delete(session_id)

    await scheduler.shutdown()

    assert observed_owners == [(job.id, session_id)]
    assert failed_job_ids == []
    assert provider_calls == 0
    with managed_connection(database_url) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM sessions WHERE id=?",
            (session_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM summary_jobs WHERE id=?",
            (job.id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM session_summaries WHERE session_id=?",
            (session_id,),
        ).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_missing_job_is_not_accepted_while_expected_session_exists(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'unexpected-missing-job.db'}"
    settings = _settings(database_url, tmp_path / "unexpected-missing-job.key")
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("still present")

    service = SummaryJobService(
        database_url=database_url,
        settings=settings,
        processing_fence=SummaryProcessingFence(),
    )

    with pytest.raises(KeyError):
        await service.process(
            "missing-job",
            expected_session_id=session.id,
        )


@pytest.mark.asyncio
async def test_job_disappearance_during_provider_io_requires_deleted_session(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'unexpected-inflight-missing.db'}"
    references = MemorySourceReferenceService(b"u" * 32)
    settings = _settings(database_url, tmp_path / "unexpected-inflight-missing.key")
    session_id, job = _reserve_summary_job(database_url, settings, references)
    started = asyncio.Event()
    release = asyncio.Event()

    class InvalidBlockingProvider:
        async def generate(self, messages, options):
            started.set()
            await release.wait()
            return SessionSummaryProviderResult(
                text="   ",
                provider="fake",
                model="invalid-blocking",
            )

        async def aclose(self) -> None:
            return None

    worker = asyncio.create_task(
        SummaryJobService(
            database_url=database_url,
            settings=settings,
            processing_fence=SummaryProcessingFence(),
            remote_provider_factory=InvalidBlockingProvider,
        ).process(
            job.id,
            expected_session_id=session_id,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=5)
    with managed_connection(database_url) as connection:
        connection.execute("DELETE FROM summary_jobs WHERE id=?", (job.id,))
        connection.commit()
        assert connection.execute(
            "SELECT 1 FROM sessions WHERE id=?",
            (session_id,),
        ).fetchone() is not None
    release.set()

    with pytest.raises(KeyError):
        await asyncio.wait_for(worker, timeout=5)



def _deletion_generation(
    database_url: str,
    references: MemorySourceReferenceService,
    session_id: str,
) -> int:
    with managed_connection(database_url) as connection:
        return VersionedMemoryRepository(connection).read_deletion_generations(
            session_reference_hash=references.session_hash(session_id)
        ).session_generation


def test_session_delete_waits_for_inflight_summary_generation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'delete-summary-fence.db'}"
    settings = _settings(
        database_url,
        tmp_path / "delete-summary-fence.key",
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    class BlockingSummaryProvider:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.release = threading.Event()
            self.calls = 0

        async def generate(self, messages, options):
            self.calls += 1
            self.started.set()
            await asyncio.to_thread(self.release.wait)
            return SessionSummaryProviderResult(
                text="summary output",
                provider="fake",
                model="blocking",
            )

        async def aclose(self) -> None:
            return None

    provider = BlockingSummaryProvider()
    app = create_app(
        summary_provider_factory=lambda: provider,
        settings_override=settings,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        with managed_connection(database_url) as connection:
            automation = SummaryAutomationRepository(connection)
            policy = build_summary_processing_policy(settings)
            authority = automation.get_processing_authority()
            automation.mutate_processing(
                action="grant",
                expected_generation=authority.generation,
                policy=policy,
            )
        session = client.post(
            "/api/sessions",
            json={"title": "summary delete race"},
        ).json()
        sent = threading.Event()

        def send_turn() -> None:
            response = client.post(
                f"/api/sessions/{session['id']}/messages",
                json={"content": "start summary"},
            )
            assert response.status_code == 200
            sent.set()

        sender = threading.Thread(target=send_turn)
        sender.start()
        assert provider.started.wait(timeout=5)
        deleted = threading.Event()
        delete_status: list[int] = []

        def delete_session() -> None:
            response = client.delete(f"/api/sessions/{session['id']}")
            delete_status.append(response.status_code)
            deleted.set()

        deletion = threading.Thread(target=delete_session)
        deletion.start()
        assert deleted.wait(timeout=0.1) is False
        provider.release.set()
        sender.join(timeout=5)
        deletion.join(timeout=5)
        assert sent.is_set() and deleted.is_set()
        assert delete_status == [204]

        with managed_connection(database_url) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM sessions WHERE id=?",
                (session["id"],),
            ).fetchone()[0] == 0
            assert connection.execute(
                "SELECT COUNT(*) FROM session_summaries WHERE session_id=?",
                (session["id"],),
            ).fetchone()[0] == 0
            assert connection.execute(
                "SELECT COUNT(*) FROM summary_jobs WHERE session_id=?",
                (session["id"],),
            ).fetchone()[0] == 0


def test_session_deletion_cascades_all_summary_owned_rows(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'summary-cascade.db'}"
    references = MemorySourceReferenceService(b"c" * 32)
    settings = _settings(database_url, tmp_path / "summary-cascade.key")
    session_id, job = _reserve_summary_job(database_url, settings, references)
    with managed_connection(database_url) as connection:
        automation = SummaryAutomationRepository(connection)
        automation.claim_job(
            job.id,
            max_attempts=settings.summary_job_max_attempts,
            summarizer_schema_version=SUMMARY_SCHEMA_VERSION,
        )
        automation.commit_summary_job(
            job.id,
            summary_text="cascade summary",
            max_output_characters=8000,
            provider_policy_fingerprint=(
                summary_provider_policy_for_settings(settings)
            ),
            session_deletion_generation=0,
        )
        summary = connection.execute(
            "SELECT id, source_set_hash FROM session_summaries "
            "WHERE session_id=?",
            (session_id,),
        ).fetchone()
        assert summary is not None
    from app.services.summary_invalidation import SummaryInvalidationService

    SummaryInvalidationService(database_url).redact_summary(
        str(summary["id"]),
        expected_suppression_generation=0,
        confirmation="redact_summary_payload",
    )
    with managed_connection(database_url) as connection:
        SessionDeletionCoordinator(
            connection,
            versioned=VersionedMemoryRepository(connection),
            source_references=references,
        ).delete(session_id)

        for table in (
            "sessions",
            "messages",
            "chat_turns",
            "session_summaries",
            "session_summary_sources",
            "summary_jobs",
            "summary_job_sources",
            "summary_source_suppressions",
            "summary_suppression_audits",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM summary_job_audits"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT job_id FROM summary_job_audits"
        ).fetchone()[0] is None
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
