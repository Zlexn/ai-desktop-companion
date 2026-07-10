import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import ProviderInvalidResponseError
from app.domain.models import ChatRole, MemorySource, MemoryStatus, MemoryType
from app.providers.base import LLMMessage, LLMOptions, LLMResponse
from app.providers.fake_provider import FakeProvider
from app.repositories.memories import MemoryRepository
from app.repositories.memory_embeddings import MemoryEmbeddingRepository
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.services.chat_service import ChatService
from app.services.context_builder import ContextBuilder
from app.services.memory_candidate_service import MemoryCandidateService
from app.services.memory_embedding_service import FakeMemoryEmbeddingProvider, MemoryEmbeddingService, MemoryEmbeddingUnavailableError
from app.services.prompt_renderer import default_prompt_renderer


@pytest.mark.asyncio
async def test_chat_service_persists_user_and_assistant_messages(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'chat.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("聊天")
        provider = FakeProvider()
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            provider,
            Settings(llm_model="test-model"),
        )

        reply = await service.send_message(session.id, "今天有点累")

        stored = messages.list(session.id)
        assert reply.provider == "fake"
        assert reply.model == "test-model"
        assert [message.role for message in stored] == [ChatRole.USER, ChatRole.ASSISTANT]
        assert stored[0].content == "今天有点累"
        assert stored[1].content == reply.reply
        assert provider.calls[0][0].role == ChatRole.SYSTEM
        assert provider.calls[0][-1].content == "今天有点累"


@pytest.mark.asyncio
async def test_chat_service_sends_system_prompt_and_full_recent_context_on_second_turn(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'multi_turn_context.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("上下文")
        provider = FakeProvider()
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            provider,
            Settings(llm_model="test-model"),
        )

        first_reply = await service.send_message(session.id, "第一轮用户消息")
        await service.send_message(session.id, "第二轮用户消息")

        second_call = provider.calls[1]
        assert second_call[0].role == ChatRole.SYSTEM
        assert "林夕" in second_call[0].content
        assert [(message.role, message.content) for message in second_call[1:]] == [
            (ChatRole.USER, "第一轮用户消息"),
            (ChatRole.ASSISTANT, first_reply.reply),
            (ChatRole.USER, "第二轮用户消息"),
        ]


@pytest.mark.asyncio
async def test_chat_service_passes_current_user_text_for_memory_relevance(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'chat_relevant_memory.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        session = sessions.create("相关记忆聊天")
        memories.create(
            content="用户正在构建本地 AI 桌宠。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=5,
            confidence=1.0,
            metadata={},
        )
        memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=2,
            confidence=0.8,
            metadata={},
        )
        provider = FakeProvider()
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(
                messages,
                12,
                memories=memories,
                memory_context_enabled=True,
                memory_context_limit=8,
                memory_retrieval_mode="relevance",
                memory_retrieval_fallback_limit=2,
            ),
            default_prompt_renderer(),
            provider,
            Settings(llm_model="test-model"),
        )

        await service.send_message(session.id, "我喜欢什么饮料？")

        sent_contents = [message.content for message in provider.calls[0]]
        memory_context = sent_contents[1]
        assert "用户喜欢红茶。" in memory_context
        assert "用户正在构建本地 AI 桌宠。" not in memory_context


@pytest.mark.asyncio
async def test_chat_service_uses_embedding_selected_memory_context(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'chat_embedding_memory.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        embeddings = MemoryEmbeddingRepository(connection)
        embedding_service = MemoryEmbeddingService(embeddings, FakeMemoryEmbeddingProvider())
        session = sessions.create("语义记忆聊天")
        tea, _ = memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=2,
            confidence=0.8,
            metadata={},
        )
        project, _ = memories.create(
            content="用户正在构建本地 AI 桌宠。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=5,
            confidence=1.0,
            metadata={},
        )
        embedding_service.ensure_embedding(tea)
        embedding_service.ensure_embedding(project)
        provider = FakeProvider()
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(
                messages,
                12,
                memories=memories,
                memory_context_enabled=True,
                memory_context_limit=8,
                memory_retrieval_mode="embedding",
                memory_retrieval_fallback_limit=2,
                memory_embedding_service=embedding_service,
                memory_embedding_min_score=0.1,
            ),
            default_prompt_renderer(),
            provider,
            Settings(llm_model="test-model", memory_retrieval_mode="embedding"),
        )

        await service.send_message(session.id, "我喜欢什么饮料？")

        memory_context = provider.calls[0][1].content
        assert "用户喜欢红茶。" in memory_context
        assert "用户正在构建本地 AI 桌宠。" not in memory_context

    database_url = f"sqlite:///{tmp_path / 'context.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("上下文")
        for index in range(5):
            messages.add(session.id, ChatRole.USER, f"旧消息 {index}")
        provider = FakeProvider()
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 3),
            default_prompt_renderer(),
            provider,
            Settings(llm_model="test-model", recent_context_messages=3),
        )

        await service.send_message(session.id, "新消息")

        sent_contents = [message.content for message in provider.calls[0]]
        assert "旧消息 0" not in sent_contents
        assert "旧消息 1" not in sent_contents
        assert sent_contents[-3:] == ["旧消息 3", "旧消息 4", "新消息"]


@pytest.mark.asyncio
async def test_chat_service_maps_invalid_provider_response(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'invalid.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("错误")
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            FakeProvider(mode="invalid"),
            Settings(llm_model="test-model"),
        )

        with pytest.raises(ProviderInvalidResponseError):
            await service.send_message(session.id, "触发错误")


class FailingMemoryCandidateService:
    async def create_candidates_from_user_text(self, *, session_id: str | None, user_text: str):
        raise RuntimeError("candidate extraction failed")


@pytest.mark.asyncio
async def test_chat_service_ignores_memory_candidate_extraction_failure(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'candidate_failure.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("候选失败")
        provider = FakeProvider()
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            provider,
            Settings(llm_model="test-model"),
            FailingMemoryCandidateService(),
        )

        reply = await service.send_message(session.id, "我喜欢红茶。")

        stored = messages.list(session.id)
        assert reply.provider == "fake"
        assert [message.role for message in stored] == [ChatRole.USER, ChatRole.ASSISTANT]
        assert stored[-1].content == reply.reply


@pytest.mark.asyncio
async def test_chat_service_excludes_pending_candidates_from_next_turn_context(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'pending_candidate_context.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        session = sessions.create("pending 不进上下文")
        provider = FakeProvider()
        memory_candidates = MemoryCandidateService(memories, Settings(memory_candidates_enabled=True))
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(
                messages,
                12,
                memories=memories,
                memory_context_enabled=True,
                memory_context_limit=8,
                memory_retrieval_mode="relevance",
                memory_retrieval_fallback_limit=3,
            ),
            default_prompt_renderer(),
            provider,
            Settings(llm_model="test-model", memory_context_enabled=True),
            memory_candidates,
        )

        await service.send_message(session.id, "我喜欢红茶。")
        await service.send_message(session.id, "你记得我的饮料偏好吗？")

        assert len(memories.list(status=MemoryStatus.PENDING)) == 1
        second_call_contents = [message.content for message in provider.calls[1]]
        assert all("用户喜欢红茶。" not in content for content in second_call_contents)


@pytest.mark.asyncio
async def test_chat_service_prunes_old_history_before_provider_when_context_is_large(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'context_budget.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("上下文预算")
        for index in range(4):
            messages.add(session.id, ChatRole.USER, f"旧消息 {index} " + "甲" * 7000)
            messages.add(session.id, ChatRole.ASSISTANT, f"旧回复 {index} " + "乙" * 7000)
        current_text = "当前问题 " + "丙" * 1000
        provider = FakeProvider()
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            provider,
            Settings(llm_model="test-model"),
        )

        await service.send_message(session.id, current_text)

        sent = provider.calls[0]
        sent_text = "\n".join(message.content for message in sent)
        assert sent[0].role == ChatRole.SYSTEM
        assert "林夕" in sent[0].content
        assert sent[-1] == LLMMessage(role=ChatRole.USER, content=current_text)
        assert "旧消息 0" not in sent_text
        assert sum(len(message.content) for message in sent) <= 24_000


class MetadataProvider:
    async def generate(self, messages: list[LLMMessage], options: LLMOptions) -> LLMResponse:
        return LLMResponse(
            text="带指标的回复",
            provider="deepseek",
            model=options.model,
            metadata={
                "finish_reason": "stop",
                "completion_id": "chatcmpl-test",
                "total_tokens": 9,
            },
        )


@pytest.mark.asyncio
async def test_chat_service_persists_provider_metadata_without_public_shape_change(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'metadata.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("指标")
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            MetadataProvider(),
            Settings(llm_model="deepseek-v4-flash"),
        )

        reply = await service.send_message(session.id, "记录指标")

        stored = messages.list(session.id)
        assert reply.provider == "deepseek"
        assert reply.model == "deepseek-v4-flash"
        assert stored[-1].metadata == {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "finish_reason": "stop",
            "completion_id": "chatcmpl-test",
            "total_tokens": 9,
        }


class FailingMemoryEmbeddingService:
    def search_relevant(self, query: str, limit: int, min_score: float):
        raise MemoryEmbeddingUnavailableError("embedding unavailable")


@pytest.mark.asyncio
async def test_chat_service_embedding_failure_falls_back_to_relevance(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'chat_embedding_fallback.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        session = sessions.create("嵌入失败回退")
        memories.create(
            content="用户正在构建本地 AI 桌宠。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=5,
            confidence=1.0,
            metadata={},
        )
        memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=2,
            confidence=0.8,
            metadata={},
        )
        provider = FakeProvider()
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(
                messages,
                12,
                memories=memories,
                memory_context_enabled=True,
                memory_context_limit=8,
                memory_retrieval_mode="embedding",
                memory_retrieval_fallback_limit=2,
                memory_embedding_service=FailingMemoryEmbeddingService(),
                memory_embedding_min_score=0.1,
            ),
            default_prompt_renderer(),
            provider,
            Settings(llm_model="test-model", memory_retrieval_mode="embedding"),
        )

        await service.send_message(session.id, "我喜欢什么饮料？")

        memory_context = provider.calls[0][1].content
        assert "用户喜欢红茶。" in memory_context
        assert "用户正在构建本地 AI 桌宠。" not in memory_context


def test_context_builder_returns_recent_llm_messages(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'builder.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("上下文构建")
        messages.add(session.id, ChatRole.USER, "一")
        messages.add(session.id, ChatRole.ASSISTANT, "二")
        messages.add(session.id, ChatRole.USER, "三")

        context = ContextBuilder(messages, 2).build_recent_context(session.id)

        assert context == [
            LLMMessage(role=ChatRole.ASSISTANT, content="二"),
            LLMMessage(role=ChatRole.USER, content="三"),
        ]


def test_send_message_api_returns_reply_and_stores_messages(client: TestClient) -> None:
    session = client.post("/api/sessions", json={"title": "聊天"}).json()

    response = client.post(f"/api/sessions/{session['id']}/messages", json={"content": "你好"})

    assert response.status_code == 200
    body = response.json()
    assert body["reply"].startswith("我听见了：你好")
    assert body["metadata"] == {"provider": "fake", "model": "test-model"}

    messages = client.get(f"/api/sessions/{session['id']}/messages").json()
    assert [message["role"] for message in messages] == ["user", "assistant"]


def test_send_message_to_missing_session_returns_404(client: TestClient) -> None:
    response = client.post("/api/sessions/missing/messages", json={"content": "你好"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_empty_message_returns_validation_error(client: TestClient) -> None:
    session = client.post("/api/sessions", json={"title": "聊天"}).json()

    response = client.post(f"/api/sessions/{session['id']}/messages", json={"content": ""})

    assert response.status_code == 422
