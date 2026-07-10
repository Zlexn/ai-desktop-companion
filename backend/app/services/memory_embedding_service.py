from __future__ import annotations

import math
from typing import Protocol

from app.domain.models import Memory
from app.repositories.memory_embeddings import MemoryEmbeddingRepository, content_hash


class MemoryEmbeddingUnavailableError(RuntimeError):
    pass


class MemoryEmbeddingProvider(Protocol):
    provider_name: str
    model_name: str

    def embed_text(self, text: str) -> list[float]:
        ...


def _normalized(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0.0:
        return values
    return [value / norm for value in values]


class FakeMemoryEmbeddingProvider:
    provider_name = "fake"

    def __init__(self, model: str = "fake-memory-embedding-v1") -> None:
        self.model_name = model

    def embed_text(self, text: str) -> list[float]:
        lowered = text.lower()
        features = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        if any(token in lowered for token in ("红茶", "茶", "饮料", "喝", "喜欢什么")):
            features[0] = 1.0
        if any(token in lowered for token in ("桌宠", "项目", "ai", "本地", "构建")):
            features[1] = 1.0
        if any(token in lowered for token in ("住", "居住", "城市", "哪里")):
            features[2] = 1.0
        if any(token in lowered for token in ("职业", "工作", "工程师", "学生")):
            features[3] = 1.0
        if any(token in lowered for token in ("目标", "计划", "准备", "完成")):
            features[4] = 1.0
        features[5] = min(len(text.strip()) / 100.0, 1.0)
        return _normalized(features)


class SentenceTransformersMemoryEmbeddingProvider:
    provider_name = "sentence-transformers"

    def __init__(self, model: str) -> None:
        self.model_name = model
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise MemoryEmbeddingUnavailableError(
                "sentence-transformers is not installed; install it before enabling MEMORY_EMBEDDING_PROVIDER=sentence-transformers"
            ) from exc
        self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed_text(self, text: str) -> list[float]:
        model = self._load_model()
        try:
            vector = model.encode(text, normalize_embeddings=True)
        except Exception as exc:
            raise MemoryEmbeddingUnavailableError("failed to compute memory embedding") from exc
        return [float(value) for value in vector.tolist()]


class MemoryEmbeddingService:
    def __init__(self, repository: MemoryEmbeddingRepository, provider: MemoryEmbeddingProvider) -> None:
        self._repository = repository
        self._provider = provider

    @property
    def provider_name(self) -> str:
        return self._provider.provider_name

    @property
    def model_name(self) -> str:
        return self._provider.model_name

    def ensure_embedding(self, memory: Memory) -> None:
        digest = content_hash(memory)
        existing = self._repository.get(memory.id)
        if (
            existing is not None
            and existing.provider == self.provider_name
            and existing.model == self.model_name
            and existing.content_hash == digest
        ):
            return
        embedding = self._provider.embed_text(memory.content)
        self._repository.upsert(memory.id, self.provider_name, self.model_name, embedding, digest)

    def delete_embedding(self, memory_id: str) -> None:
        self._repository.delete(memory_id)

    def search_relevant(self, query: str, limit: int, min_score: float) -> list[Memory]:
        query_embedding = self._provider.embed_text(query)
        results = self._repository.search_active(
            query_embedding=query_embedding,
            provider=self.provider_name,
            model=self.model_name,
            limit=limit,
            min_score=min_score,
        )
        return [item.memory for item in results]
