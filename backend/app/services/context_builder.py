from typing import Protocol

from app.domain.models import ChatRole, Memory
from app.providers.base import LLMMessage
from app.repositories.memories import MemoryRepository
from app.repositories.messages import MessageRepository


class MemoryEmbeddingSearch(Protocol):
    def search_relevant(self, query: str, limit: int, min_score: float) -> list[Memory]:
        ...


class ContextBuilder:
    def __init__(
        self,
        messages: MessageRepository,
        max_messages: int,
        *,
        memories: MemoryRepository | None = None,
        memory_context_enabled: bool = True,
        memory_context_limit: int = 8,
        memory_retrieval_mode: str = "relevance",
        memory_retrieval_fallback_limit: int = 3,
        memory_embedding_service: MemoryEmbeddingSearch | None = None,
        memory_embedding_min_score: float = 0.35,
    ) -> None:
        self._messages = messages
        self._max_messages = max_messages
        self._memories = memories
        self._memory_context_enabled = memory_context_enabled
        self._memory_context_limit = memory_context_limit
        self._memory_retrieval_mode = memory_retrieval_mode
        self._memory_retrieval_fallback_limit = memory_retrieval_fallback_limit
        self._memory_embedding_service = memory_embedding_service
        self._memory_embedding_min_score = memory_embedding_min_score

    def build_recent_context(self, session_id: str) -> list[LLMMessage]:
        recent_messages = self._messages.list_recent(session_id, self._max_messages)
        return [
            LLMMessage(role=message.role, content=message.content)
            for message in recent_messages
            if message.role in {ChatRole.USER, ChatRole.ASSISTANT}
        ]

    def build_memory_context(self, query: str | None = None) -> list[LLMMessage]:
        if not self._memory_context_enabled or self._memories is None:
            return []
        if self._memory_retrieval_mode == "embedding" and query and query.strip() and self._memory_embedding_service is not None:
            try:
                memories = self._memory_embedding_service.search_relevant(
                    query,
                    self._memory_context_limit,
                    self._memory_embedding_min_score,
                )
            except Exception:
                memories = []
            if not memories:
                memories = self._memories.list_relevant_for_context(
                    query,
                    self._memory_context_limit,
                    self._memory_retrieval_fallback_limit,
                )
        elif self._memory_retrieval_mode == "relevance" and query and query.strip():
            memories = self._memories.list_relevant_for_context(
                query,
                self._memory_context_limit,
                self._memory_retrieval_fallback_limit,
            )
        else:
            memories = self._memories.list_for_context(self._memory_context_limit)
        if not memories:
            return []
        lines = [
            "以下是用户可查看、可修改、可删除的长期记忆记录，仅作为回复时的参考上下文；",
            "它们可能过时或不完整，不得描述为绝对事实，也不得声称你具有真实人类记忆。",
        ]
        lines.extend(self._format_memory(memory) for memory in memories)
        return [LLMMessage(role=ChatRole.SYSTEM, content="\n".join(lines))]

    def build_context(self, session_id: str, query: str | None = None) -> list[LLMMessage]:
        return [*self.build_memory_context(query=query), *self.build_recent_context(session_id)]

    def _format_memory(self, memory: Memory) -> str:
        return (
            f"- [{memory.memory_type.value} | importance {memory.importance} | "
            f"confidence {memory.confidence:.2f}] {memory.content}"
        )
