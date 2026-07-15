import asyncio
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import (
    build_session_summary_provider,
    get_connection,
    get_llm_provider,
    get_session_summary_scheduler,
)
from app.core.config import Settings, get_settings
from app.domain.models import ChatRole, MemorySource, MemoryStatus, MemoryType
from app.providers.base import LLMMessage, LLMOptions, LLMResponse
from app.main import create_app
from app.repositories.memories import MemoryRepository
from app.repositories.memory_embeddings import MemoryEmbeddingRepository
from app.repositories.messages import MessageRepository
from app.repositories.session_summaries import SessionSummaryRepository
from app.repositories.sqlite import managed_connection
from app.services.session_summary_provider import (
    FakeSessionSummaryProvider,
    LLMSessionSummaryProvider,
    close_session_summary_provider,
)
from app.services.session_summary_service import SessionSummaryService


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


def test_lifespan_uses_explicit_summary_provider_factory() -> None:
    provider = FakeSessionSummaryProvider()
    app = create_app(summary_provider_factory=lambda: provider)

    with TestClient(app):
        assert app.state.session_summary_scheduler is not None


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

    def schedule(self, session_id: str) -> None:
        self.session_ids.append(session_id)


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
        def schedule(self, session_id: str) -> None:
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


def test_production_summary_job_is_nonblocking_and_not_in_chat_context(
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
        assert summary_provider.started.wait(timeout=1)
        with managed_connection(database_url) as connection:
            persisted = MessageRepository(connection).list(session["id"])
            assert [message.role for message in persisted] == [ChatRole.USER, ChatRole.ASSISTANT]

        summary_provider.release.set()
        for _ in range(100):
            with original_managed_connection(database_url) as connection:
                summaries = SessionSummaryRepository(connection).list_for_session(session["id"])
            if summaries:
                break
            threading.Event().wait(0.01)
        else:
            raise AssertionError("background summary did not finish")

        assert request_connections
        assert background_connections
        assert all(
            background is not request
            for background in background_connections
            for request in request_connections
        )
        second_response = test_client.post(
            f"/api/sessions/{session['id']}/messages",
            json={"content": "second turn"},
        )
        assert second_response.status_code == 200
        sent_contents = [message.content for message in chat_provider.calls[1]]
        assert all(summaries[0].summary_text not in content for content in sent_contents)

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
