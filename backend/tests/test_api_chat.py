import asyncio
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api.dependencies import (
    build_session_summary_provider,
    get_connection,
    get_llm_provider,
    get_memory_source_reference_service,
    get_session_summary_scheduler,
)
from app.core.config import Settings, get_settings
from app.domain.models import (
    ChatRole,
    MemoryAutomationMode,
    MemoryExtractionConsentStatus,
    MemoryExtractorRoute,
    MemoryJobAuditOutcome,
    MemoryJobStatus,
    MemorySource,
    MemoryStatus,
    MemoryType,
    MemoryWriteConsentStatus,
)
from app.providers.base import LLMMessage, LLMOptions, LLMResponse
from app.main import create_app, validate_memory_automation_capability
from app.repositories.memories import MemoryRepository
from app.repositories.memory_automation import MemoryAutomationRepository
from app.repositories.memory_embeddings import MemoryEmbeddingRepository
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.repositories.session_summaries import SessionSummaryRepository
from app.repositories.sqlite import managed_connection
from app.services.memory_extraction_dispatch import (
    MEMORY_EXTRACTION_DISCLOSED_FIELDS,
    MEMORY_EXTRACTION_DISCLOSURE_VERSION,
    MEMORY_EXTRACTION_PURPOSE,
)
from app.services.memory_extractor import MEMORY_EXTRACTION_SCHEMA_VERSION
from app.services.memory_governor import MEMORY_GOVERNOR_VERSION
from app.services.memory_gate_b_contract import (
    MEMORY_ALLOWED_AUTO_TYPES,
    MEMORY_ALLOWED_AUTO_TYPES_VERSION,
    MEMORY_WRITE_POLICY_VERSION,
    MEMORY_WRITE_PURPOSE,
    MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION,
)
from app.services.memory_source_reference import MemorySourceReferenceService
from app.services.session_summary_provider import (
    FakeSessionSummaryProvider,
    LLMSessionSummaryProvider,
    close_session_summary_provider,
)
from app.services.session_summary_scheduler import DurableSessionSummaryScheduler
from app.services.session_summary_service import SessionSummaryService



def _request_for_app(app) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "headers": [],
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "app": app,
        }
    )


def test_lifespan_owns_memory_source_reference_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    key_path = tmp_path / "private" / "memory-source.key"
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'source-reference.db'}",
        memory_source_reference_key_path=key_path,
        llm_provider="fake",
        memory_automation_mode="off",
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    app = create_app()

    with TestClient(app):
        service = get_memory_source_reference_service(_request_for_app(app))
        assert isinstance(service, MemorySourceReferenceService)
        assert service is app.state.memory_source_reference_service
        assert key_path.exists()


def test_lifespan_fails_closed_when_reference_key_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'missing-source-key.db'}"
    key_path = tmp_path / "missing.key"
    with managed_connection(database_url) as connection:
        connection.execute(
            "INSERT INTO memory_summary_source_exclusions "
            "(source_message_id, reason_code, created_at) VALUES ('message-1', 'test', 'now')"
        )
        connection.execute(
            "INSERT INTO sessions VALUES ('session-1', 'title', 'created', 'updated')"
        )
        connection.execute(
            "INSERT INTO memories (id, content, memory_type, source, "
            "source_session_id, importance, confidence, status, metadata_json, "
            "created_at, updated_at) VALUES "
            "('memory-1', 'content', 'other', 'manual', NULL, 3, 1.0, "
            "'active', '{}', 'created', 'updated')"
        )
        connection.execute(
            "INSERT INTO memory_versions ("
            "id, memory_id, version_number, parent_version_id, operation, memory_type, "
            "subject, content, content_hash, canonicalization_version, confidence, "
            "importance, source_kind, source_session_reference_hash, writer_policy_version, "
            "created_at) VALUES ("
            "'version-1', 'memory-1', 1, NULL, 'bootstrap', 'other', NULL, 'content', "
            "'hash', 'memory-canonicalization-v1', 1.0, 3, 'legacy', "
            "'persisted-reference', 'memory-auto-write-policy-v1', 'created')"
        )
        connection.commit()
    settings = Settings(
        database_url=database_url,
        memory_source_reference_key_path=key_path,
        llm_provider="fake",
        memory_automation_mode="off",
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    with pytest.raises(ValueError, match="source reference key is unavailable"):
        with TestClient(create_app()):
            raise AssertionError("lifespan must fail before yielding")


def test_lifespan_holds_writer_lock_across_reference_probe_and_key_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'locked-source-key.db'}"
    key_path = tmp_path / "locked.key"
    settings = Settings(
        database_url=database_url,
        memory_source_reference_key_path=key_path,
        llm_provider="fake",
        memory_automation_mode="off",
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    original_load_or_create = MemorySourceReferenceService.load_or_create
    writer_result: list[str] = []

    def locked_load_or_create(path, *, references_exist):
        assert references_exist() is False
        with managed_connection(database_url) as competing:
            competing.execute("PRAGMA busy_timeout = 0")
            with pytest.raises(sqlite3.OperationalError, match="database is locked"):
                competing.execute(
                    """
                    INSERT INTO memory_jobs (
                        id, turn_id, schema_version, mode, extractor_route, status,
                        governor_version, created_at, source_session_reference_hash
                    ) VALUES (
                        'competing-job', 'competing-turn', 'memory-shadow-schema-v1',
                        'shadow_auto', 'none', 'pending',
                        'memory-governor-rules-v1', 'created', 'competing-digest'
                    )
                    """
                )
            writer_result.append("blocked")
        return original_load_or_create(path, references_exist=references_exist)

    monkeypatch.setattr(
        "app.main.MemorySourceReferenceService.load_or_create",
        locked_load_or_create,
    )

    with TestClient(create_app()):
        pass

    assert writer_result == ["blocked"]
    assert len(key_path.read_bytes()) == 32


def test_auto_active_runtime_capability_is_enabled(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'guard.db'}",
        memory_automation_mode="auto_active",
    )

    assert validate_memory_automation_capability(settings) is None


    provider = object()
    app = SimpleNamespace(state=SimpleNamespace(llm_provider=provider))
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "headers": [],
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "app": app,
        }
    )

    assert get_llm_provider(request) is provider


def test_auto_active_local_chat_reserves_and_commits_memory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'auto-active-chat.db'}"
    settings = Settings(
        database_url=database_url,
        memory_source_reference_key_path=tmp_path / "auto-active.key",
        llm_provider="fake",
        llm_model="test-model",
        memory_automation_mode="auto_active",
        memory_extractor_route="local",
        memory_extractor_model="local-memory",
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    with managed_connection(database_url) as connection:
        MemoryAutomationRepository(connection).set_write_consent(
            status=MemoryWriteConsentStatus.GRANTED,
            purpose=MEMORY_WRITE_PURPOSE,
            policy_version=MEMORY_WRITE_POLICY_VERSION,
            allowed_memory_types_version=MEMORY_ALLOWED_AUTO_TYPES_VERSION,
            allowed_memory_types=MEMORY_ALLOWED_AUTO_TYPES,
            retention_disclosure_version=MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION,
        )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        session = client.post("/api/sessions", json={"title": "active"}).json()
        response = client.post(
            f"/api/sessions/{session['id']}/messages",
            json={"content": "我喜欢乌龙茶。"},
        )
        assert response.status_code == 200

    with managed_connection(database_url) as connection:
        jobs = MemoryAutomationRepository(connection).list_jobs(limit=10)
        memories = MemoryRepository(
            connection,
            source_references=app.state.memory_source_reference_service,
        ).list()
        audits = MemoryAutomationRepository(connection).list_audits(limit=10)
        memory_job_link = connection.execute(
            "SELECT chat_turn_id FROM memory_jobs WHERE id=?",
            (jobs[0].id,),
        ).fetchone()
        completed_turn = connection.execute(
            "SELECT id FROM chat_turns WHERE assistant_message_id=?",
            (jobs[0].assistant_message_id,),
        ).fetchone()

    assert len(jobs) == 1
    assert memory_job_link is not None and completed_turn is not None
    assert memory_job_link["chat_turn_id"] == completed_turn["id"]
    assert jobs[0].status is MemoryJobStatus.SUCCEEDED
    assert jobs[0].outcome is MemoryJobAuditOutcome.COMPLETED_WITH_DECISIONS
    assert jobs[0].auto_active_snapshot is not None
    assert len(memories) == 1
    assert memories[0].source is MemorySource.AUTOMATIC
    assert audits[0].outcome_counts == {"committed_create": 1}


def test_auto_active_remote_delete_waits_for_inflight_extraction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import threading

    database_url = f"sqlite:///{tmp_path / 'delete-fence.db'}"
    settings = Settings(
        database_url=database_url,
        memory_source_reference_key_path=tmp_path / "delete-fence.key",
        llm_provider="fake",
        llm_model="test-model",
        memory_automation_mode="auto_active",
        memory_extractor_route="remote",
        memory_extractor_provider="anthropic",
        memory_extractor_model="fixture-model",
        anthropic_api_key="test-key",
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    with managed_connection(database_url) as connection:
        automation = MemoryAutomationRepository(connection)
        automation.set_write_consent(
            status=MemoryWriteConsentStatus.GRANTED,
            purpose=MEMORY_WRITE_PURPOSE,
            policy_version=MEMORY_WRITE_POLICY_VERSION,
            allowed_memory_types_version=MEMORY_ALLOWED_AUTO_TYPES_VERSION,
            allowed_memory_types=MEMORY_ALLOWED_AUTO_TYPES,
            retention_disclosure_version=MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION,
        )
        automation.set_consent(
            status=MemoryExtractionConsentStatus.GRANTED,
            purpose=MEMORY_EXTRACTION_PURPOSE,
            provider="anthropic",
            disclosure_version=MEMORY_EXTRACTION_DISCLOSURE_VERSION,
            disclosed_fields=MEMORY_EXTRACTION_DISCLOSED_FIELDS,
        )

    class BlockingMemoryProvider:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.release = threading.Event()
            self.calls = 0

        async def generate(self, messages, options):
            self.calls += 1
            self.started.set()
            await asyncio.to_thread(self.release.wait)
            return LLMResponse(
                text='{"proposals":[]}',
                provider="fake",
                model=options.model,
            )

        async def aclose(self) -> None:
            pass

    provider = BlockingMemoryProvider()
    app = create_app(memory_extractor_provider_factory=lambda: provider)
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        session = client.post("/api/sessions", json={"title": "active"}).json()
        message_done = threading.Event()

        def send_turn() -> None:
            client.post(
                f"/api/sessions/{session['id']}/messages",
                json={"content": "我喜欢乌龙茶。"},
            )
            message_done.set()

        sender = threading.Thread(target=send_turn)
        sender.start()
        assert provider.started.wait(timeout=5)
        deleted = threading.Event()

        def delete_session() -> None:
            client.delete(f"/api/sessions/{session['id']}")
            deleted.set()

        deletion = threading.Thread(target=delete_session)
        deletion.start()
        assert deleted.wait(timeout=0.1) is False
        provider.release.set()
        sender.join(timeout=5)
        deletion.join(timeout=5)
        assert message_done.is_set() and deleted.is_set()
        calls_at_delete = provider.calls
        assert calls_at_delete == 1
        assert provider.calls == calls_at_delete


def test_two_chat_requests_share_one_lifespan_provider_and_close_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls = 0
    closes = 0

    class RecordingProvider:
        provider_name = "recording"

        async def generate(self, messages, options):
            nonlocal calls
            calls += 1
            return LLMResponse(
                text="recorded reply",
                provider="recording",
                model=options.model,
            )

        async def aclose(self):
            nonlocal closes
            closes += 1

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'shared-chat-provider.db'}",
        llm_provider="fake",
        llm_model="test-model",
        memory_automation_mode="off",
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    provider = RecordingProvider()
    app = create_app(chat_provider_factory=lambda: provider)

    with TestClient(app) as test_client:
        session = test_client.post(
            "/api/sessions",
            json={"title": "shared provider"},
        ).json()
        for content in ("first", "second"):
            response = test_client.post(
                f"/api/sessions/{session['id']}/messages",
                json={"content": content},
            )
            assert response.status_code == 200
        assert app.state.llm_provider is provider
        assert calls == 2
        assert closes == 0

    assert closes == 1


def test_partial_lifespan_startup_closes_chat_provider_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    closed = 0

    class ChatProvider:
        async def generate(self, messages, options):
            return LLMResponse(
                text="reply",
                provider="recording",
                model=options.model,
            )

        async def aclose(self):
            nonlocal closed
            closed += 1

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'partial-startup.db'}",
        llm_provider="fake",
        llm_model="test-model",
        memory_automation_mode="shadow_auto",
        memory_extractor_route="remote",
        memory_extractor_provider="anthropic",
        memory_extractor_model="memory-test-model",
        anthropic_api_key="test-anthropic-key",
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    app = create_app(
        chat_provider_factory=ChatProvider,
        memory_extractor_provider_factory=lambda: (_ for _ in ()).throw(
            RuntimeError("memory provider startup failed")
        ),
    )

    with pytest.raises(RuntimeError, match="memory provider startup failed"):
        with TestClient(app):
            raise AssertionError("lifespan must fail before yielding")


def test_lifespan_closes_shared_chat_and_memory_provider_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    closes = 0

    class SharedProvider:
        async def generate(self, messages, options):
            raise AssertionError("provider should not generate")

        async def aclose(self):
            nonlocal closes
            closes += 1

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'shared-provider.db'}",
        llm_provider="fake",
        llm_model="test-model",
        memory_automation_mode="shadow_auto",
        memory_extractor_route="remote",
        memory_extractor_provider="anthropic",
        memory_extractor_model="memory-test-model",
        anthropic_api_key="test-anthropic-key",
    )
    shared = SharedProvider()
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    app = create_app(
        chat_provider_factory=lambda: shared,
        memory_extractor_provider_factory=lambda: shared,
    )

    with TestClient(app):
        pass

    assert closes == 1


def test_lifespan_closes_memory_scheduler_before_memory_and_chat_providers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'lifespan-order.db'}",
        llm_provider="fake",
        llm_model="test-model",
        memory_automation_mode="shadow_auto",
        memory_extractor_route="remote",
        memory_extractor_provider="anthropic",
        memory_extractor_model="memory-test-model",
        anthropic_api_key="test-anthropic-key",
    )

    class ClosableProvider:
        async def generate(self, messages, options):
            raise AssertionError("test provider must not generate")

        async def aclose(self):
            events.append("chat_provider_close")

    class ClosableMemoryProvider:
        async def generate(self, messages, options):
            raise AssertionError("test provider must not generate")

        async def aclose(self):
            events.append("memory_provider_close")

    class RecordingScheduler:
        async def recover(self):
            return 0

        async def shutdown(self, *, cancel=False):
            events.append("memory_scheduler_shutdown")

    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.main.InProcessMemoryJobScheduler",
        lambda **kwargs: RecordingScheduler(),
    )
    app = create_app(
        chat_provider_factory=ClosableProvider,
        memory_extractor_provider_factory=ClosableMemoryProvider,
    )

    with TestClient(app):
        assert app.state.llm_provider is not None

    assert events.index("memory_scheduler_shutdown") < events.index(
        "memory_provider_close"
    )
    assert events.index("memory_provider_close") < events.index(
        "chat_provider_close"
    )




def test_off_startup_terminalizes_incomplete_automatic_jobs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'off-recovery.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("stale")
        messages = MessageRepository(connection)
        user = messages.add(session.id, ChatRole.USER, "stale user")
        assistant = messages.add(session.id, ChatRole.ASSISTANT, "stale assistant")
        job, _ = MemoryAutomationRepository(connection).reserve_job(
            turn_id=assistant.id,
            schema_version=MEMORY_EXTRACTION_SCHEMA_VERSION,
            session_id=session.id,
            user_message_id=user.id,
            assistant_message_id=assistant.id,
            mode=MemoryAutomationMode.SHADOW_AUTO,
            extractor_route=MemoryExtractorRoute.LOCAL,
            governor_version=MEMORY_GOVERNOR_VERSION,
        )

    settings = Settings(
        database_url=database_url,
        memory_source_reference_key_path=tmp_path / "off.key",
        llm_provider="fake",
        memory_automation_mode="off",
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    with TestClient(create_app()):
        pass

    with managed_connection(database_url) as connection:
        repository = MemoryAutomationRepository(connection)
        terminal = repository.require_job(job.id)
        audits = repository.list_audits(limit=10)
    assert terminal.status is MemoryJobStatus.SUCCEEDED
    assert terminal.outcome is MemoryJobAuditOutcome.SKIPPED_MODE_CHANGED
    assert len(audits) == 1


def test_shadow_startup_terminalizes_incomplete_job_from_other_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'mode-switch.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("stale active")
        messages = MessageRepository(connection)
        user = messages.add(session.id, ChatRole.USER, "user")
        assistant = messages.add(session.id, ChatRole.ASSISTANT, "assistant")
        connection.execute(
            """
            INSERT INTO memory_jobs (
                id, turn_id, schema_version, session_id, user_message_id,
                assistant_message_id, mode, extractor_route, status,
                governor_version, created_at, turn_completed_at, reserved_mode,
                workflow_version, commit_policy_version, canonicalization_version,
                allowed_memory_types_version, write_consent_generation,
                global_deletion_generation, session_deletion_generation,
                type_deletion_generations_json, source_session_reference_hash,
                source_user_message_reference_hash,
                source_assistant_message_reference_hash
            ) VALUES (
                'stale-active', ?, 'memory-auto-active-schema-v1', ?, ?, ?,
                'auto_active', 'local', 'pending', 'memory-governor-rules-v1',
                ?, ?, 'auto_active', 'memory-auto-active-schema-v1',
                'memory-commit-policy-v1', 'memory-canonicalization-v1',
                'memory-auto-write-types-v1', 0, 0, 0, '{}', 's', 'u', 'a'
            )
            """,
            (
                assistant.id,
                session.id,
                user.id,
                assistant.id,
                assistant.created_at.isoformat(),
                assistant.created_at.isoformat(),
            ),
        )
        connection.commit()

    key_path = tmp_path / "switch.key"
    key_path.write_bytes(b"x" * 32)
    settings = Settings(
        database_url=database_url,
        memory_source_reference_key_path=key_path,
        llm_provider="fake",
        memory_automation_mode="shadow_auto",
        memory_extractor_route="local",
        memory_extractor_model="local-memory",
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    with TestClient(create_app()):
        pass

    with managed_connection(database_url) as connection:
        terminal = MemoryAutomationRepository(connection).require_job("stale-active")
    assert terminal.status is MemoryJobStatus.SUCCEEDED
    assert terminal.outcome is MemoryJobAuditOutcome.SKIPPED_MODE_CHANGED


def test_lifespan_recovers_running_and_pending_shadow_jobs_without_replaying_terminal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'recovery.db'}"
    closed = 0
    calls: list[str] = []

    class RemoteProvider:
        async def generate(self, messages, options):
            calls.append(messages[1].content)
            return LLMResponse(
                text='{"schema_version":"memory-shadow-schema-v1","proposals":[]}',
                provider="recovery-provider",
                model=options.model,
            )

        async def aclose(self):
            nonlocal closed
            closed += 1

    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        automation = MemoryAutomationRepository(connection)
        jobs = []
        for title in ("running", "pending", "terminal"):
            session = sessions.create(title)
            user = messages.add(session.id, ChatRole.USER, f"{title} user")
            assistant = messages.add(session.id, ChatRole.ASSISTANT, f"{title} assistant")
            job, created = automation.reserve_job(
                turn_id=assistant.id,
                schema_version=MEMORY_EXTRACTION_SCHEMA_VERSION,
                session_id=session.id,
                user_message_id=user.id,
                assistant_message_id=assistant.id,
                mode=MemoryAutomationMode.SHADOW_AUTO,
                extractor_route=MemoryExtractorRoute.REMOTE,
                governor_version=MEMORY_GOVERNOR_VERSION,
            )
            assert created
            jobs.append(job)
        automation.update_job_status(jobs[0].id, status=MemoryJobStatus.RUNNING)
        automation.complete_job_with_audit(
            jobs[2].id,
            status=MemoryJobStatus.SUCCEEDED,
            outcome=MemoryJobAuditOutcome.SKIPPED_NO_EXTRACTOR,
            decision_counts={}, reason_counts={}, proposal_count=0,
            accepted_count=0, rejected_count=0, redaction_count=0,
            provider=None, model=None, elapsed_ms=None, consent_generation=None,
        )
        automation.set_consent(
            status=MemoryExtractionConsentStatus.GRANTED,
            purpose=MEMORY_EXTRACTION_PURPOSE,
            provider="anthropic",
            disclosure_version=MEMORY_EXTRACTION_DISCLOSURE_VERSION,
            disclosed_fields=MEMORY_EXTRACTION_DISCLOSED_FIELDS,
        )

    settings = Settings(
        database_url=database_url, llm_provider="fake", llm_model="test-model",
        memory_automation_mode="shadow_auto", memory_extractor_route="remote",
        memory_extractor_provider="anthropic", memory_extractor_model="memory-test-model",
        anthropic_api_key="test-anthropic-key",
    )
    provider = RemoteProvider()
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    app = create_app(memory_extractor_provider_factory=lambda: provider)
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app):
        for _ in range(200):
            with managed_connection(database_url) as connection:
                recovered = MemoryAutomationRepository(connection).list_jobs(limit=10)
            if all(job.status is MemoryJobStatus.SUCCEEDED for job in recovered):
                break
            threading.Event().wait(0.01)
        else:
            raise AssertionError("recovered jobs did not finish")

    by_id = {job.id: job for job in recovered}
    assert len(recovered) == 3
    assert by_id[jobs[0].id].attempt_count == 2
    assert by_id[jobs[1].id].attempt_count == 1
    assert by_id[jobs[2].id].attempt_count == 0
    assert len(calls) == 2
    assert closed == 1


def test_remote_shadow_without_selected_credential_skips_without_provider_factory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'remote-no-key.db'}"
    settings = Settings(
        database_url=database_url,
        llm_provider="fake",
        llm_model="test-model",
        memory_candidates_enabled=False,
        memory_automation_mode="shadow_auto",
        memory_extractor_route="remote",
        memory_extractor_provider="anthropic",
        memory_extractor_model="memory-test-model",
        anthropic_api_key=None,
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.dependencies.get_settings", lambda: settings)
    app = create_app(
        memory_extractor_provider_factory=lambda: (_ for _ in ()).throw(
            AssertionError("factory must not run without selected credential")
        )
    )
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as test_client:
        session = test_client.post("/api/sessions", json={"title": "no key"}).json()
        response = test_client.post(
            f"/api/sessions/{session['id']}/messages",
            json={"content": "我喜欢红茶。"},
        )
        assert response.status_code == 200
        for _ in range(100):
            with managed_connection(database_url) as connection:
                jobs = MemoryAutomationRepository(connection).list_jobs(limit=10)
            if len(jobs) == 1 and jobs[0].status is MemoryJobStatus.SUCCEEDED:
                break
            threading.Event().wait(0.01)
        else:
            raise AssertionError("shadow job did not reach terminal state")

    assert jobs[0].outcome is MemoryJobAuditOutcome.SKIPPED_NO_EXTRACTOR


def test_chat_response_returns_the_persisted_assistant_message_id(client: TestClient) -> None:
    session = client.post("/api/sessions", json={"title": "message id"}).json()

    response = client.post(
        f"/api/sessions/{session['id']}/messages",
        json={"content": "hello"},
    )
    messages = client.get(f"/api/sessions/{session['id']}/messages").json()

    assert response.status_code == 200
    assert response.json()["assistant_message_id"] == messages[-1]["id"]
    assert messages[-1]["role"] == "assistant"


def test_fake_session_summary_provider_dependency_is_offline() -> None:
    provider = build_session_summary_provider(get_settings())

    assert isinstance(provider, FakeSessionSummaryProvider)


def test_lifespan_fences_legacy_summary_provider_factory() -> None:
    provider = FakeSessionSummaryProvider()
    calls = 0

    def factory() -> FakeSessionSummaryProvider:
        nonlocal calls
        calls += 1
        return provider

    app = create_app(summary_provider_factory=factory)

    with TestClient(app):
        assert isinstance(
            app.state.session_summary_scheduler,
            DurableSessionSummaryScheduler,
        )
        assert app.state.remote_summary_capability == "local_summary_available"

    assert calls == 0


def test_app_owns_one_summary_scheduler_for_all_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SESSION_SUMMARY_PROVIDER", "fake")
    get_settings.cache_clear()
    app = create_app()

    with TestClient(app) as test_client:
        first_scheduler = app.state.session_summary_scheduler
        session = test_client.post("/api/sessions", json={"title": "shared scheduler"}).json()
        response = test_client.post(
            f"/api/sessions/{session['id']}/messages",
            json={"content": "first request"},
        )
        second_scheduler = app.state.session_summary_scheduler

    assert response.status_code == 200
    assert first_scheduler is second_scheduler
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_close_session_summary_provider_closes_wrapped_llm_client() -> None:
    class ClosableLLMProvider:
        def __init__(self) -> None:
            self.closed = False

        async def generate(self, messages, options):
            raise AssertionError("generate is not part of this test")

        async def aclose(self) -> None:
            self.closed = True

    llm = ClosableLLMProvider()
    provider = LLMSessionSummaryProvider(llm_provider=llm, model="summary-model")

    await close_session_summary_provider(provider)

    assert llm.closed is True


class RecordingSummaryScheduler:
    def __init__(self) -> None:
        self.session_ids: list[str] = []
        self.chat_turn_ids: list[str | None] = []

    def schedule(self, session_id: str, *, chat_turn_id: str | None = None) -> None:
        self.session_ids.append(session_id)
        self.chat_turn_ids.append(chat_turn_id)


def test_chat_api_composition_injects_summary_scheduler(client: TestClient) -> None:
    scheduler = RecordingSummaryScheduler()
    client.app.dependency_overrides[get_session_summary_scheduler] = lambda: scheduler
    try:
        session = client.post(
            "/api/sessions",
            json={"title": "API 摘要调度"},
        ).json()
        response = client.post(
            f"/api/sessions/{session['id']}/messages",
            json={"content": "通过 API 发送消息。"},
        )
    finally:
        client.app.dependency_overrides.pop(get_session_summary_scheduler, None)

    assert response.status_code == 200
    assert scheduler.session_ids == [session["id"]]
    assert len(scheduler.chat_turn_ids) == 1
    assert scheduler.chat_turn_ids[0]


def test_chat_api_returns_before_drained_summary_job_and_keeps_memory_separate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'summary-api.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("MEMORY_CANDIDATES_ENABLED", "false")
    monkeypatch.setenv("SESSION_SUMMARY_PROVIDER", "fake")
    monkeypatch.setenv("SESSION_SUMMARY_TRIGGER_MESSAGE_COUNT", "2")
    get_settings.cache_clear()
    settings = get_settings()
    scheduled_ids: list[str] = []

    class DrainingSummaryScheduler:
        def schedule(
            self,
            session_id: str,
            *,
            chat_turn_id: str | None = None,
        ) -> None:
            assert chat_turn_id
            scheduled_ids.append(session_id)

        async def drain(self) -> None:
            for session_id in scheduled_ids:
                with managed_connection(database_url) as connection:
                    await SessionSummaryService(
                        messages=MessageRepository(connection),
                        summaries=SessionSummaryRepository(connection),
                        provider=FakeSessionSummaryProvider(),
                        settings=settings,
                    ).maybe_generate_for_session(session_id)

    scheduler = DrainingSummaryScheduler()
    app = create_app()
    app.dependency_overrides[get_session_summary_scheduler] = lambda: scheduler
    with TestClient(app) as test_client:
        session = test_client.post(
            "/api/sessions",
            json={"title": "摘要边界"},
        ).json()
        response = test_client.post(
            f"/api/sessions/{session['id']}/messages",
            json={"content": "验证摘要保持独立。"},
        )

        assert response.status_code == 200
        with managed_connection(database_url) as connection:
            messages = MessageRepository(connection).list(session["id"])
            assert [message.role for message in messages] == [
                ChatRole.USER,
                ChatRole.ASSISTANT,
            ]
            assert SessionSummaryRepository(connection).list_for_session(session["id"]) == []
            assert MemoryRepository(connection).list() == []

        asyncio.run(scheduler.drain())

        with managed_connection(database_url) as connection:
            summaries = SessionSummaryRepository(connection).list_for_session(session["id"])
            assert len(summaries) == 1
            assert summaries[0].message_count == 2
            assert summaries[0].covered_message_start_id == messages[0].id
            assert summaries[0].covered_message_end_id == messages[1].id
            assert MemoryRepository(connection).list() == []

        second_response = test_client.post(
            f"/api/sessions/{session['id']}/messages",
            json={"content": "摘要不应进入上下文。"},
        )
        assert second_response.status_code == 200
        assert summaries[0].summary_text not in second_response.json()["reply"]

    get_settings.cache_clear()


class RecordingChatProvider:
    provider_name = "recording"

    def __init__(self) -> None:
        self.calls: list[list[LLMMessage]] = []

    async def generate(self, messages: list[LLMMessage], options: LLMOptions) -> LLMResponse:
        self.calls.append(messages)
        return LLMResponse(text="recorded reply", provider="recording", model=options.model)


class BlockingSummaryProvider(FakeSessionSummaryProvider):
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    async def generate(self, messages, options):
        self.started.set()
        await asyncio.to_thread(self.release.wait)
        return await super().generate(messages, options)


def test_production_legacy_summary_generation_is_fenced_from_chat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'production-summary.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("MEMORY_CANDIDATES_ENABLED", "false")
    monkeypatch.setenv("MEMORY_EMBEDDING_ENABLED", "true")
    monkeypatch.setenv("SESSION_SUMMARY_TRIGGER_MESSAGE_COUNT", "2")
    get_settings.cache_clear()
    summary_provider = BlockingSummaryProvider()
    chat_provider = RecordingChatProvider()
    request_connections: list[object] = []
    background_connections: list[object] = []
    app = create_app(summary_provider_factory=lambda: summary_provider)

    def request_connection():
        with managed_connection(database_url) as connection:
            request_connections.append(connection)
            yield connection

    original_managed_connection = managed_connection

    @contextmanager
    def tracked_background_connection(url: str):
        with original_managed_connection(url) as connection:
            background_connections.append(connection)
            yield connection

    monkeypatch.setattr(
        "app.main.managed_connection",
        tracked_background_connection,
    )
    app.dependency_overrides[get_connection] = request_connection
    app.dependency_overrides[get_llm_provider] = lambda: chat_provider

    with original_managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        active, _ = memories.create(
            content="existing active memory",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
        )
        pending, _ = memories.create_candidate(
            content="existing pending candidate",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=2,
            confidence=0.9,
        )
        dismissed, _ = memories.create_candidate(
            content="existing dismissed candidate",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source_session_id=None,
            importance=2,
            confidence=0.9,
        )
        assert pending is not None and dismissed is not None
        memories.dismiss_candidate(dismissed.id)
        MemoryEmbeddingRepository(connection).upsert(
            active.id,
            provider="fake",
            model="fake-memory-embedding-v1",
            embedding=[1.0, 0.0],
            content_hash="existing-hash",
        )
        before_memory_rows = connection.execute(
            "SELECT id, content, status, metadata_json FROM memories ORDER BY id"
        ).fetchall()
        before_embedding_rows = connection.execute(
            "SELECT memory_id, provider, model, embedding_json, content_hash FROM memory_embeddings ORDER BY memory_id"
        ).fetchall()

    with TestClient(app) as test_client:
        session = test_client.post("/api/sessions", json={"title": "production composition"}).json()
        first_response = test_client.post(
            f"/api/sessions/{session['id']}/messages",
            json={"content": "first turn"},
        )

        assert first_response.status_code == 200
        assert summary_provider.started.is_set() is False
        assert isinstance(
            test_client.app.state.session_summary_scheduler,
            DurableSessionSummaryScheduler,
        )
        with managed_connection(database_url) as connection:
            persisted = MessageRepository(connection).list(session["id"])
            summaries = SessionSummaryRepository(connection).list_for_session(session["id"])
            assert [message.role for message in persisted] == [ChatRole.USER, ChatRole.ASSISTANT]
            assert summaries == []

        assert background_connections
        second_response = test_client.post(
            f"/api/sessions/{session['id']}/messages",
            json={"content": "second turn"},
        )
        assert second_response.status_code == 200
        sent_contents = [message.content for message in chat_provider.calls[1]]
        assert all("summary" not in content.lower() for content in sent_contents)

        with original_managed_connection(database_url) as connection:
            after_memory_rows = connection.execute(
                "SELECT id, content, status, metadata_json FROM memories ORDER BY id"
            ).fetchall()
            after_embedding_rows = connection.execute(
                "SELECT memory_id, provider, model, embedding_json, content_hash FROM memory_embeddings ORDER BY memory_id"
            ).fetchall()
            assert [tuple(row) for row in after_memory_rows] == [tuple(row) for row in before_memory_rows]
            assert [tuple(row) for row in after_embedding_rows] == [tuple(row) for row in before_embedding_rows]
            assert len(MemoryRepository(connection).list(MemoryStatus.ACTIVE)) == 1
            assert len(MemoryRepository(connection).list(MemoryStatus.PENDING)) == 1
            assert len(MemoryRepository(connection).list(MemoryStatus.DISMISSED)) == 1

    get_settings.cache_clear()


def test_send_message_api_returns_reply_and_stores_messages(client: TestClient) -> None:
    session = client.post("/api/sessions", json={"title": "聊天"}).json()

    response = client.post(f"/api/sessions/{session['id']}/messages", json={"content": "你好"})

    assert response.status_code == 200
    body = response.json()
    assert body["reply"].startswith("我听见了：你好")
    assert body["metadata"] == {"provider": "fake", "model": "test-model"}

    messages = client.get(f"/api/sessions/{session['id']}/messages").json()
    assert [message["role"] for message in messages] == ["user", "assistant"]


@pytest.mark.parametrize(
    ("mode", "status_code", "error_code", "message"),
    [
        ("error", 502, "provider_error", "模型服务暂时不可用，请稍后重试。"),
        ("timeout", 504, "provider_timeout", "模型服务响应超时，请稍后重试。"),
        ("rate_limit", 429, "provider_rate_limited", "模型服务请求过于频繁，请稍后重试。"),
        ("invalid", 502, "provider_invalid_response", "模型服务返回了无法处理的响应。"),
        ("empty", 502, "provider_invalid_response", "模型服务返回了无法处理的响应。"),
    ],
)
def test_send_message_api_maps_fake_provider_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    status_code: int,
    error_code: str,
    message: str,
) -> None:
    monkeypatch.setenv("FAKE_PROVIDER_MODE", mode)
    get_settings.cache_clear()
    with TestClient(create_app()) as error_client:
        session = error_client.post("/api/sessions", json={"title": "错误"}).json()

        response = error_client.post(f"/api/sessions/{session['id']}/messages", json={"content": "触发错误"})

    assert response.status_code == status_code
    body = response.json()
    assert body == {"error": {"code": error_code, "message": message}}
    serialized = response.text.lower()
    assert "traceback" not in serialized
    assert "anthropic_api_key" not in serialized
    assert "c:\\" not in serialized
    assert "/backend/" not in serialized


def test_send_message_to_missing_session_returns_404(client: TestClient) -> None:
    response = client.post("/api/sessions/missing/messages", json={"content": "你好"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_empty_message_returns_validation_error(client: TestClient) -> None:
    session = client.post("/api/sessions", json={"title": "聊天"}).json()

    response = client.post(f"/api/sessions/{session['id']}/messages", json={"content": ""})

    assert response.status_code == 422
