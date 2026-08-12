from pathlib import Path

import pytest

from app.domain.models import MemorySource, MemoryStatus, MemoryType
from app.repositories.memories import MemoryRepository
from app.repositories.memory_embeddings import MemoryEmbeddingRepository, content_hash
from app.repositories.sqlite import managed_connection
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.services.memory_embedding_service import (
    FakeMemoryEmbeddingProvider,
    MemoryEmbeddingService,
    MemoryEmbeddingUnavailableError,
)


def test_embedding_round_trip_and_replace(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'embeddings.db'}"
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        embeddings = MemoryEmbeddingRepository(connection)
        memory, _ = memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        embeddings.upsert(
            memory_id=memory.id,
            provider="fake",
            model="fake-memory-embedding-v1",
            embedding=[1.0, 0.0, 0.0],
            content_hash="hash-1",
        )
        embeddings.upsert(
            memory_id=memory.id,
            provider="fake",
            model="fake-memory-embedding-v1",
            embedding=[0.9, 0.1, 0.0],
            content_hash="hash-2",
        )

        row = embeddings.get(memory.id)
        assert row is not None
        assert row.memory_id == memory.id
        assert row.provider == "fake"
        assert row.model == "fake-memory-embedding-v1"
        assert row.dimension == 3
        assert row.embedding == [0.9, 0.1, 0.0]
        assert row.content_hash == "hash-2"


def test_embedding_search_returns_only_active_matching_provider_model(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'embedding-search.db'}"
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        embeddings = MemoryEmbeddingRepository(connection)
        active, _ = memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )
        archived, _ = memories.create(
            content="用户喜欢咖啡。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=5,
            confidence=1.0,
            metadata={},
        )
        memories.archive(archived.id)
        pending, _ = memories.create_candidate(
            content="用户喜欢牛奶。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=0.7,
            metadata={},
        )
        assert pending is not None

        embeddings.upsert(active.id, "fake", "fake-memory-embedding-v1", [1.0, 0.0, 0.0], "a")
        embeddings.upsert(archived.id, "fake", "fake-memory-embedding-v1", [1.0, 0.0, 0.0], "b")
        embeddings.upsert(pending.id, "fake", "fake-memory-embedding-v1", [1.0, 0.0, 0.0], "c")

        results = embeddings.search_active(
            query_embedding=[1.0, 0.0, 0.0],
            provider="fake",
            model="fake-memory-embedding-v1",
            limit=5,
            min_score=0.1,
        )

        assert [(item.memory.id, round(item.score, 3)) for item in results] == [(active.id, 1.0)]
def test_embedding_search_excludes_v2_open_conflict_endpoints(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'embedding-conflict.db'}"
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        embeddings = MemoryEmbeddingRepository(connection)
        first, _ = memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
        )
        second, _ = memories.create(
            content="用户不喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
        )
        versioned = VersionedMemoryRepository(connection)
        first_state = versioned.bootstrap_legacy(first.id)
        second_state = versioned.bootstrap_legacy(second.id)
        assert first_state.current_version_id and second_state.current_version_id
        connection.execute(
            """
            INSERT INTO memory_conflicts (
                conflict_id, left_memory_id, right_memory_id, status, created_at
            ) VALUES (?, ?, ?, 'open', ?)
            """,
            (
                "conflict-1",
                min(first.id, second.id),
                max(first.id, second.id),
                first.created_at.isoformat(),
            ),
        )
        embeddings.upsert(first.id, "fake", "fake-memory-embedding-v1", [1.0, 0.0], "a")
        embeddings.upsert(second.id, "fake", "fake-memory-embedding-v1", [1.0, 0.0], "b")

        assert memories.list_for_context(limit=10) == []
        assert memories.list_relevant_for_context("红茶", limit=10, fallback_limit=10) == []
        assert embeddings.search_active(
            query_embedding=[1.0, 0.0],
            provider="fake",
            model="fake-memory-embedding-v1",
            limit=5,
            min_score=0.1,
        ) == []



def test_embedding_search_excludes_unbootstrapped_open_conflict_endpoints(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'embedding-legacy-conflict.db'}"
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        embeddings = MemoryEmbeddingRepository(connection)
        first, _ = memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
        )
        second, _ = memories.create(
            content="用户不喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
        )
        connection.execute(
            """
            INSERT INTO memory_conflicts (
                conflict_id, left_memory_id, right_memory_id, status, created_at
            ) VALUES (?, ?, ?, 'open', ?)
            """,
            (
                "legacy-conflict",
                min(first.id, second.id),
                max(first.id, second.id),
                first.created_at.isoformat(),
            ),
        )
        embeddings.upsert(first.id, "fake", "fake-memory-embedding-v1", [1.0, 0.0], "a")
        embeddings.upsert(second.id, "fake", "fake-memory-embedding-v1", [1.0, 0.0], "b")

        assert embeddings.search_active(
            query_embedding=[1.0, 0.0],
            provider="fake",
            model="fake-memory-embedding-v1",
            limit=5,
            min_score=0.1,
        ) == []


    provider = FakeMemoryEmbeddingProvider(model="fake-memory-embedding-v1")

    tea = provider.embed_text("用户喜欢红茶。")
    drink = provider.embed_text("我喜欢什么饮料？")
    project = provider.embed_text("桌宠项目进展如何？")

    assert tea == provider.embed_text("用户喜欢红茶。")
    assert sum(a * b for a, b in zip(tea, drink, strict=True)) > sum(a * b for a, b in zip(tea, project, strict=True))


def test_embedding_service_ensure_embedding_skips_matching_hash(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'embedding-service.db'}"
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        embeddings = MemoryEmbeddingRepository(connection)
        provider = FakeMemoryEmbeddingProvider(model="fake-memory-embedding-v1")
        service = MemoryEmbeddingService(embeddings, provider)
        memory, _ = memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        service.ensure_embedding(memory)
        first = embeddings.get(memory.id)
        assert first is not None
        service.ensure_embedding(memory)
        second = embeddings.get(memory.id)

        assert second is not None
        assert second.content_hash == first.content_hash
        assert second.embedding == first.embedding


def test_embedding_service_searches_related_active_memories(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'embedding-service-search.db'}"
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        embeddings = MemoryEmbeddingRepository(connection)
        provider = FakeMemoryEmbeddingProvider(model="fake-memory-embedding-v1")
        service = MemoryEmbeddingService(embeddings, provider)
        tea, _ = memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
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
        service.ensure_embedding(tea)
        service.ensure_embedding(project)

        results = service.search_relevant("我喜欢什么饮料？", limit=2, min_score=0.1)

        assert [item.id for item in results] == [tea.id]


class FailingEmbeddingProvider:
    provider_name = "fake"
    model_name = "failing"

    def embed_text(self, text: str) -> list[float]:
        raise MemoryEmbeddingUnavailableError("embedding unavailable")


def test_embedding_service_surfaces_provider_failure(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'embedding-failure.db'}"
    with managed_connection(database_url) as connection:
        embeddings = MemoryEmbeddingRepository(connection)
        service = MemoryEmbeddingService(embeddings, FailingEmbeddingProvider())

        with pytest.raises(MemoryEmbeddingUnavailableError):
            service.search_relevant("我喜欢什么饮料？", limit=2, min_score=0.1)
