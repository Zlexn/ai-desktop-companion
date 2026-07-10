# Stage 3F Memory Embedding Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in local embedding retrieval for confirmed active long-term memories while preserving deterministic fallback and user-controlled memory writes.

**Architecture:** Add a small memory-embedding layer beside the existing memory repository: SQLite stores one embedding row per active memory, a fake provider supports deterministic tests, and ContextBuilder can use embedding retrieval when configured. The first slice uses JSON vectors plus Python cosine search, not sqlite-vec, so Windows extension packaging does not block the feature.

**Tech Stack:** Python 3.11, FastAPI, SQLite, pytest, existing React/Vite frontend regression tests. No mandatory new runtime dependency for the default path.

---

## Scope and constraints

This plan implements Stage 3F only.

It must not implement:

- Stage 4 emotion state or expression strategy;
- LLM-based memory candidate extraction;
- automatic long-term memory writes from chat history;
- session summaries;
- sqlite-vec production integration;
- mandatory sentence-transformers dependency.

Do not commit unless the user explicitly asks for a commit. The original skill template suggests frequent commits, but this project session rule is stricter: commits require explicit user authorization.

## File structure

Create:

- `backend/app/repositories/memory_embeddings.py`
  - Stores and searches memory embeddings in SQLite.
  - Owns vector JSON serialization, content hashing, cosine scoring, and active-memory filtering.

- `backend/app/services/memory_embedding_service.py`
  - Owns embedding provider abstraction, fake provider, optional lazy sentence-transformers provider, and mutation/retrieval orchestration.

- `backend/tests/test_memory_embeddings.py`
  - Repository and service tests for embedding persistence, active filtering, fake semantic retrieval, stale refresh, and failure behavior.

Modify:

- `backend/app/repositories/sqlite.py`
  - Add `memory_embeddings` table and index to `SCHEMA_SQL` / `init_db`.

- `backend/app/core/config.py`
  - Add embedding settings and allow `MEMORY_RETRIEVAL_MODE=embedding`.

- `backend/app/api/dependencies.py`
  - Wire optional `MemoryEmbeddingService` into `ContextBuilder` and memory routes.

- `backend/app/api/routes/memories.py`
  - Maintain embeddings after create/update/confirm/archive without changing public response shapes.

- `backend/app/services/context_builder.py`
  - Use embedding retrieval mode and fallback to deterministic relevance.

- `backend/tests/test_config.py`
  - Cover new settings and validation.

- `backend/tests/test_context_builder.py`
  - Cover embedding mode and fallback.

- `backend/tests/test_api_memories.py`
  - Cover create/update/confirm/archive embedding maintenance through API.

- `backend/tests/test_chat_service.py`
  - Cover chat context using embedding-selected memory and fallback on embedding failure.

- `.env.example`
  - Document opt-in embedding settings after tests pass.

- `README.md`
  - Add a short Stage 3F configuration note after implementation is verified.

- `docs/stage3f-memory-embedding-retrieval.md`
  - Record scope, validation commands, results, and limitations after verification.

---

### Task 1: Configuration for embedding retrieval

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/tests/test_config.py`

- [ ] **Step 1: Write failing config tests**

Add these tests near the existing memory retrieval tests in `backend/tests/test_config.py`:

```python
def test_memory_embedding_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_RETRIEVAL_MODE", "embedding")
    monkeypatch.setenv("MEMORY_EMBEDDING_ENABLED", "true")
    monkeypatch.setenv("MEMORY_EMBEDDING_PROVIDER", "fake")
    monkeypatch.setenv("MEMORY_EMBEDDING_MODEL", "fake-memory-embedding-v1")
    monkeypatch.setenv("MEMORY_EMBEDDING_MIN_SCORE", "0.42")

    settings = load_settings()

    assert settings.memory_retrieval_mode == "embedding"
    assert settings.memory_embedding_enabled is True
    assert settings.memory_embedding_provider == "fake"
    assert settings.memory_embedding_model == "fake-memory-embedding-v1"
    assert settings.memory_embedding_min_score == 0.42
    assert settings.redacted()["memory_embedding_enabled"] is True
    assert settings.redacted()["memory_embedding_provider"] == "fake"
    assert settings.redacted()["memory_embedding_model"] == "fake-memory-embedding-v1"
    assert settings.redacted()["memory_embedding_min_score"] == 0.42


def test_rejects_unknown_memory_embedding_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_EMBEDDING_PROVIDER", "remote")

    with pytest.raises(ValueError, match="MEMORY_EMBEDDING_PROVIDER must be one of: fake, sentence-transformers"):
        load_settings()


def test_memory_embedding_min_score_must_be_between_zero_and_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_EMBEDDING_MIN_SCORE", "1.5")

    with pytest.raises(ValueError, match="MEMORY_EMBEDDING_MIN_SCORE must be between 0.0 and 1.0"):
        load_settings()
```

Also add these names to the `clear_env` tuple:

```python
"MEMORY_EMBEDDING_ENABLED",
"MEMORY_EMBEDDING_PROVIDER",
"MEMORY_EMBEDDING_MODEL",
"MEMORY_EMBEDDING_MIN_SCORE",
```

Update the existing unknown retrieval mode test expected message from:

```python
with pytest.raises(ValueError, match="MEMORY_RETRIEVAL_MODE must be one of: relevance, recent"):
```

to:

```python
with pytest.raises(ValueError, match="MEMORY_RETRIEVAL_MODE must be one of: embedding, relevance, recent"):
```

- [ ] **Step 2: Run config tests and verify failure**

Run:

```powershell
python -m pytest backend/tests/test_config.py -q
```

Expected: FAIL because `Settings` has no `memory_embedding_*` fields and `embedding` is not an allowed retrieval mode.

- [ ] **Step 3: Implement config fields**

In `backend/app/core/config.py`, add these fields to `Settings` after existing memory candidate fields:

```python
    memory_embedding_enabled: bool = False
    memory_embedding_provider: str = "fake"
    memory_embedding_model: str = "fake-memory-embedding-v1"
    memory_embedding_min_score: float = 0.35
```

In `Settings.redacted()`, add:

```python
            "memory_embedding_enabled": self.memory_embedding_enabled,
            "memory_embedding_provider": self.memory_embedding_provider,
            "memory_embedding_model": self.memory_embedding_model,
            "memory_embedding_min_score": self.memory_embedding_min_score,
```

Add this helper below `_get_float_env`:

```python
def _get_score_env(name: str, default: float) -> float:
    parsed = _get_float_env(name, default)
    if parsed < 0.0 or parsed > 1.0:
        raise ValueError(f"{name} must be between 0.0 and 1.0")
    return parsed
```

Update retrieval mode validation:

```python
    if memory_retrieval_mode not in {"embedding", "relevance", "recent"}:
        raise ValueError("MEMORY_RETRIEVAL_MODE must be one of: embedding, relevance, recent")
```

Add provider validation before returning `Settings`:

```python
    memory_embedding_provider = _get_env("MEMORY_EMBEDDING_PROVIDER", "fake").lower()
    if memory_embedding_provider not in {"fake", "sentence-transformers"}:
        raise ValueError("MEMORY_EMBEDDING_PROVIDER must be one of: fake, sentence-transformers")
```

Add these keyword arguments to `Settings(...)`:

```python
        memory_embedding_enabled=_get_bool_env("MEMORY_EMBEDDING_ENABLED", False),
        memory_embedding_provider=memory_embedding_provider,
        memory_embedding_model=_get_stripped_env("MEMORY_EMBEDDING_MODEL", "fake-memory-embedding-v1"),
        memory_embedding_min_score=_get_score_env("MEMORY_EMBEDDING_MIN_SCORE", 0.35),
```

- [ ] **Step 4: Run config tests and verify pass**

Run:

```powershell
python -m pytest backend/tests/test_config.py -q
```

Expected: PASS.

---

### Task 2: SQLite repository for memory embeddings

**Files:**
- Create: `backend/app/repositories/memory_embeddings.py`
- Modify: `backend/app/repositories/sqlite.py`
- Create: `backend/tests/test_memory_embeddings.py`

- [ ] **Step 1: Write failing repository tests**

Create `backend/tests/test_memory_embeddings.py` with:

```python
from pathlib import Path

from app.domain.models import MemorySource, MemoryStatus, MemoryType
from app.repositories.memories import MemoryRepository
from app.repositories.memory_embeddings import MemoryEmbeddingRepository, content_hash
from app.repositories.sqlite import managed_connection


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


def test_embedding_delete_and_content_hash(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'embedding-delete.db'}"
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        embeddings = MemoryEmbeddingRepository(connection)
        memory, _ = memories.create(
            content="用户的目标是完成桌宠项目。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=5,
            confidence=1.0,
            metadata={},
        )
        digest = content_hash(memory)
        embeddings.upsert(memory.id, "fake", "fake-memory-embedding-v1", [0.0, 1.0, 0.0], digest)

        assert embeddings.get(memory.id) is not None
        embeddings.delete(memory.id)

        assert embeddings.get(memory.id) is None
        assert digest == content_hash(memory)
```

- [ ] **Step 2: Run repository tests and verify failure**

Run:

```powershell
python -m pytest backend/tests/test_memory_embeddings.py -q
```

Expected: FAIL because `app.repositories.memory_embeddings` does not exist.

- [ ] **Step 3: Add SQLite schema**

In `backend/app/repositories/sqlite.py`, append this table to `SCHEMA_SQL` after `memory_audit_events` indexes:

```sql
CREATE TABLE IF NOT EXISTS memory_embeddings (
    memory_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    dimension INTEGER NOT NULL CHECK (dimension > 0),
    embedding_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memory_embeddings_provider_model
ON memory_embeddings(provider, model);
```

Also add the same index creation to the final `connection.executescript(...)` in `init_db`:

```sql
CREATE INDEX IF NOT EXISTS idx_memory_embeddings_provider_model
ON memory_embeddings(provider, model);
```

- [ ] **Step 4: Create memory embedding repository**

Create `backend/app/repositories/memory_embeddings.py`:

```python
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from app.domain.models import Memory, MemoryStatus
from app.repositories.memories import MemoryRepository


def _now() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: datetime) -> str:
    return value.isoformat()


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def content_hash(memory: Memory) -> str:
    raw = f"{memory.memory_type.value}\n{memory.content}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _embedding_to_json(embedding: list[float]) -> str:
    return json.dumps([float(value) for value in embedding], ensure_ascii=False)


def _embedding_from_json(raw: str) -> list[float]:
    value = json.loads(raw)
    if not isinstance(value, list):
        return []
    return [float(item) for item in value]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left or not right:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


@dataclass(frozen=True)
class MemoryEmbedding:
    memory_id: str
    provider: str
    model: str
    dimension: int
    embedding: list[float]
    content_hash: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ScoredMemory:
    memory: Memory
    score: float


class MemoryEmbeddingRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, memory_id: str) -> MemoryEmbedding | None:
        row = self._connection.execute(
            """
            SELECT memory_id, provider, model, dimension, embedding_json,
                   content_hash, created_at, updated_at
            FROM memory_embeddings
            WHERE memory_id = ?
            """,
            (memory_id,),
        ).fetchone()
        if row is None:
            return None
        return MemoryEmbedding(
            memory_id=row["memory_id"],
            provider=row["provider"],
            model=row["model"],
            dimension=row["dimension"],
            embedding=_embedding_from_json(row["embedding_json"]),
            content_hash=row["content_hash"],
            created_at=_from_iso(row["created_at"]),
            updated_at=_from_iso(row["updated_at"]),
        )

    def upsert(
        self,
        memory_id: str,
        provider: str,
        model: str,
        embedding: list[float],
        content_hash: str,
    ) -> None:
        if not embedding:
            raise ValueError("embedding must not be empty")
        now = _now()
        existing = self.get(memory_id)
        created_at = existing.created_at if existing else now
        self._connection.execute(
            """
            INSERT INTO memory_embeddings (
                memory_id, provider, model, dimension, embedding_json,
                content_hash, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(memory_id) DO UPDATE SET
                provider = excluded.provider,
                model = excluded.model,
                dimension = excluded.dimension,
                embedding_json = excluded.embedding_json,
                content_hash = excluded.content_hash,
                updated_at = excluded.updated_at
            """,
            (
                memory_id,
                provider,
                model,
                len(embedding),
                _embedding_to_json(embedding),
                content_hash,
                _to_iso(created_at),
                _to_iso(now),
            ),
        )
        self._connection.commit()

    def delete(self, memory_id: str) -> None:
        self._connection.execute("DELETE FROM memory_embeddings WHERE memory_id = ?", (memory_id,))
        self._connection.commit()

    def search_active(
        self,
        *,
        query_embedding: list[float],
        provider: str,
        model: str,
        limit: int,
        min_score: float,
    ) -> list[ScoredMemory]:
        rows = self._connection.execute(
            """
            SELECT e.memory_id, e.embedding_json,
                   m.id, m.content, m.memory_type, m.source, m.source_session_id,
                   m.importance, m.confidence, m.status, m.metadata_json,
                   m.created_at, m.updated_at
            FROM memory_embeddings e
            JOIN memories m ON m.id = e.memory_id
            WHERE e.provider = ? AND e.model = ? AND m.status = ?
            """,
            (provider, model, MemoryStatus.ACTIVE.value),
        ).fetchall()
        memory_repository = MemoryRepository(self._connection)
        scored: list[ScoredMemory] = []
        for row in rows:
            score = _cosine_similarity(query_embedding, _embedding_from_json(row["embedding_json"]))
            if score < min_score:
                continue
            memory = memory_repository.require(row["memory_id"])
            scored.append(ScoredMemory(memory=memory, score=score))
        scored.sort(
            key=lambda item: (
                item.score,
                item.memory.importance,
                item.memory.confidence,
                item.memory.updated_at,
            ),
            reverse=True,
        )
        return scored[:limit]
```

- [ ] **Step 5: Run repository tests and verify pass**

Run:

```powershell
python -m pytest backend/tests/test_memory_embeddings.py -q
```

Expected: PASS.

---

### Task 3: Memory embedding service and fake provider

**Files:**
- Create/modify: `backend/app/services/memory_embedding_service.py`
- Modify: `backend/tests/test_memory_embeddings.py`

- [ ] **Step 1: Add failing service tests**

Append to `backend/tests/test_memory_embeddings.py`:

```python
import pytest

from app.services.memory_embedding_service import (
    FakeMemoryEmbeddingProvider,
    MemoryEmbeddingService,
    MemoryEmbeddingUnavailableError,
)


def test_fake_embedding_provider_is_deterministic_and_semantic() -> None:
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
```

- [ ] **Step 2: Run service tests and verify failure**

Run:

```powershell
python -m pytest backend/tests/test_memory_embeddings.py -q
```

Expected: FAIL because service classes do not exist.

- [ ] **Step 3: Implement embedding service**

Create `backend/app/services/memory_embedding_service.py`:

```python
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
```

- [ ] **Step 4: Run service tests and verify pass**

Run:

```powershell
python -m pytest backend/tests/test_memory_embeddings.py -q
```

Expected: PASS.

---

### Task 4: Wire embedding retrieval into ContextBuilder

**Files:**
- Modify: `backend/app/services/context_builder.py`
- Modify: `backend/tests/test_context_builder.py`

- [ ] **Step 1: Add failing ContextBuilder tests**

Append to `backend/tests/test_context_builder.py`:

```python
from app.repositories.memory_embeddings import MemoryEmbeddingRepository
from app.services.memory_embedding_service import FakeMemoryEmbeddingProvider, MemoryEmbeddingService, MemoryEmbeddingUnavailableError


def test_memory_context_embedding_mode_uses_embedding_service(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'memory-context-embedding.db'}"
    with managed_connection(database_url) as connection:
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        embeddings = MemoryEmbeddingRepository(connection)
        service = MemoryEmbeddingService(embeddings, FakeMemoryEmbeddingProvider())
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
        service.ensure_embedding(tea)
        service.ensure_embedding(project)
        builder = ContextBuilder(
            messages,
            12,
            memories=memories,
            memory_context_enabled=True,
            memory_context_limit=8,
            memory_retrieval_mode="embedding",
            memory_retrieval_fallback_limit=2,
            memory_embedding_service=service,
            memory_embedding_min_score=0.1,
        )

        context = builder.build_memory_context(query="我喜欢什么饮料？")

        assert len(context) == 1
        assert "用户喜欢红茶。" in context[0].content
        assert "用户正在构建本地 AI 桌宠。" not in context[0].content
        assert "不得描述为绝对事实" in context[0].content


class FailingMemoryEmbeddingService:
    def search_relevant(self, query: str, limit: int, min_score: float):
        raise MemoryEmbeddingUnavailableError("embedding unavailable")


def test_memory_context_embedding_mode_falls_back_to_relevance(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'memory-context-embedding-fallback.db'}"
    with managed_connection(database_url) as connection:
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
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
        builder = ContextBuilder(
            messages,
            12,
            memories=memories,
            memory_context_enabled=True,
            memory_context_limit=8,
            memory_retrieval_mode="embedding",
            memory_retrieval_fallback_limit=2,
            memory_embedding_service=FailingMemoryEmbeddingService(),
            memory_embedding_min_score=0.1,
        )

        context = builder.build_memory_context(query="我喜欢什么饮料？")

        assert "用户喜欢红茶。" in context[0].content
        assert "用户正在构建本地 AI 桌宠。" not in context[0].content
```

- [ ] **Step 2: Run ContextBuilder tests and verify failure**

Run:

```powershell
python -m pytest backend/tests/test_context_builder.py -q
```

Expected: FAIL because `ContextBuilder` does not accept `memory_embedding_service`.

- [ ] **Step 3: Update ContextBuilder constructor and retrieval flow**

In `backend/app/services/context_builder.py`, import the service type guarded by future annotations:

```python
from typing import Protocol
```

Add a local protocol above `ContextBuilder`:

```python
class MemoryEmbeddingSearch(Protocol):
    def search_relevant(self, query: str, limit: int, min_score: float) -> list[Memory]:
        ...
```

Update `ContextBuilder.__init__` parameters:

```python
        memory_embedding_service: MemoryEmbeddingSearch | None = None,
        memory_embedding_min_score: float = 0.35,
```

Store them:

```python
        self._memory_embedding_service = memory_embedding_service
        self._memory_embedding_min_score = memory_embedding_min_score
```

Update `build_memory_context` so the retrieval section becomes:

```python
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
```

- [ ] **Step 4: Run ContextBuilder tests and verify pass**

Run:

```powershell
python -m pytest backend/tests/test_context_builder.py -q
```

Expected: PASS.

---

### Task 5: Dependency wiring for embedding service

**Files:**
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/tests/test_chat_service.py`

- [ ] **Step 1: Add failing chat test for embedding-selected context**

Add this test to `backend/tests/test_chat_service.py` after the relevance test:

```python
from app.repositories.memory_embeddings import MemoryEmbeddingRepository
from app.services.memory_embedding_service import FakeMemoryEmbeddingProvider, MemoryEmbeddingService, MemoryEmbeddingUnavailableError


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
```

- [ ] **Step 2: Run chat service tests and verify pass with manual wiring**

Run:

```powershell
python -m pytest backend/tests/test_chat_service.py::test_chat_service_uses_embedding_selected_memory_context -q
```

Expected: PASS after Task 4. This proves the service can be manually wired.

- [ ] **Step 3: Add dependency providers**

In `backend/app/api/dependencies.py`, add imports:

```python
from app.repositories.memory_embeddings import MemoryEmbeddingRepository
from app.services.memory_embedding_service import (
    FakeMemoryEmbeddingProvider,
    MemoryEmbeddingProvider,
    MemoryEmbeddingService,
    SentenceTransformersMemoryEmbeddingProvider,
)
```

Add repository dependency after memory repository:

```python
def get_memory_embedding_repository(connection: sqlite3.Connection = Depends(get_connection)) -> MemoryEmbeddingRepository:
    return MemoryEmbeddingRepository(connection)
```

Add provider factory functions:

```python
def get_memory_embedding_provider(settings: Settings = Depends(get_settings)) -> MemoryEmbeddingProvider | None:
    if not settings.memory_embedding_enabled:
        return None
    if settings.memory_embedding_provider == "fake":
        return FakeMemoryEmbeddingProvider(settings.memory_embedding_model)
    if settings.memory_embedding_provider == "sentence-transformers":
        return SentenceTransformersMemoryEmbeddingProvider(settings.memory_embedding_model)
    return None


def get_memory_embedding_service(
    repository: MemoryEmbeddingRepository = Depends(get_memory_embedding_repository),
    provider: MemoryEmbeddingProvider | None = Depends(get_memory_embedding_provider),
) -> MemoryEmbeddingService | None:
    if provider is None:
        return None
    return MemoryEmbeddingService(repository, provider)
```

Update `get_chat_service` signature:

```python
    memory_embeddings: MemoryEmbeddingService | None = Depends(get_memory_embedding_service),
```

Pass to `ContextBuilder`:

```python
        memory_embedding_service=memory_embeddings,
        memory_embedding_min_score=settings.memory_embedding_min_score,
```

- [ ] **Step 4: Run dependency-sensitive tests**

Run:

```powershell
python -m pytest backend/tests/test_chat_service.py backend/tests/test_context_builder.py -q
```

Expected: PASS.

---

### Task 6: Maintain embeddings through memory API mutations

**Files:**
- Modify: `backend/app/api/routes/memories.py`
- Modify: `backend/tests/test_api_memories.py`

- [ ] **Step 1: Add failing API tests for mutation maintenance**

Append to `backend/tests/test_api_memories.py`:

```python
def test_memory_api_create_update_and_delete_maintains_embeddings(tmp_path, monkeypatch) -> None:
    from app.core.config import get_settings
    from app.main import create_app
    from fastapi.testclient import TestClient

    database_url = f"sqlite:///{tmp_path / 'api-embedding.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("MEMORY_EMBEDDING_ENABLED", "true")
    monkeypatch.setenv("MEMORY_EMBEDDING_PROVIDER", "fake")
    monkeypatch.setenv("MEMORY_RETRIEVAL_MODE", "embedding")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        created = client.post(
            "/api/memories",
            json={"content": "用户喜欢红茶。", "memory_type": "preference", "importance": 3, "confidence": 1.0},
        ).json()["memory"]
        chat_response = client.post("/api/sessions", json={"title": "嵌入检索"})
        session = chat_response.json()
        reply = client.post(f"/api/sessions/{session['id']}/messages", json={"content": "我喜欢什么饮料？"})
        assert reply.status_code == 200

        updated = client.patch(f"/api/memories/{created['id']}", json={"content": "用户喜欢咖啡。"}).json()["memory"]
        assert updated["content"] == "用户喜欢咖啡。"

        delete_response = client.delete(f"/api/memories/{created['id']}")
        assert delete_response.status_code == 204
        assert client.get("/api/memories").json() == []
    get_settings.cache_clear()


def test_confirm_candidate_creates_embedding_when_enabled(tmp_path, monkeypatch) -> None:
    from app.core.config import get_settings
    from app.main import create_app
    from fastapi.testclient import TestClient

    database_url = f"sqlite:///{tmp_path / 'api-confirm-embedding.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("MEMORY_EMBEDDING_ENABLED", "true")
    monkeypatch.setenv("MEMORY_EMBEDDING_PROVIDER", "fake")
    monkeypatch.setenv("MEMORY_RETRIEVAL_MODE", "embedding")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        session = client.post("/api/sessions", json={"title": "候选嵌入"}).json()
        client.post(f"/api/sessions/{session['id']}/messages", json={"content": "我喜欢红茶。"})
        candidate = client.get("/api/memories", params={"status_filter": "pending"}).json()[0]

        confirm_response = client.post(f"/api/memories/{candidate['id']}/confirm")

        assert confirm_response.status_code == 200
        assert confirm_response.json()["memory"]["status"] == "active"
        assert [item["id"] for item in client.get("/api/memories").json()] == [candidate["id"]]
    get_settings.cache_clear()
```

These tests are intentionally API-level smoke tests. They prove embedding-enabled routes still create/update/archive memories and confirm candidates without response-shape changes.

- [ ] **Step 2: Run API memory tests and verify failure**

Run:

```powershell
python -m pytest backend/tests/test_api_memories.py -q
```

Expected: FAIL because routes do not accept/use `MemoryEmbeddingService` yet.

- [ ] **Step 3: Add route maintenance helper**

In `backend/app/api/routes/memories.py`, import:

```python
from app.api.dependencies import get_memory_embedding_service
from app.services.memory_embedding_service import MemoryEmbeddingService
```

Because the existing import line already imports dependencies, update it to include `get_memory_embedding_service`.

Add helper below `_record_conflicts`:

```python
def _ensure_embedding(memory_embeddings: MemoryEmbeddingService | None, memory: Memory) -> None:
    if memory_embeddings is None or memory.status != MemoryStatus.ACTIVE:
        return
    try:
        memory_embeddings.ensure_embedding(memory)
    except Exception:
        pass


def _delete_embedding(memory_embeddings: MemoryEmbeddingService | None, memory_id: str) -> None:
    if memory_embeddings is None:
        return
    try:
        memory_embeddings.delete_embedding(memory_id)
    except Exception:
        pass
```

Update route signatures:

```python
    memory_embeddings: MemoryEmbeddingService | None = Depends(get_memory_embedding_service),
```

Add this parameter to `create_memory`, `update_memory`, `confirm_memory_candidate`, and `delete_memory`.

After create/update/confirm succeeds and conflicts are recorded, call:

```python
    _ensure_embedding(memory_embeddings, memory)
```

For `delete_memory`, after `memories.archive(memory_id)`, call:

```python
    _delete_embedding(memory_embeddings, memory_id)
```

Do not call embedding maintenance in `dismiss_memory_candidate`.

- [ ] **Step 4: Run API memory tests and verify pass**

Run:

```powershell
python -m pytest backend/tests/test_api_memories.py -q
```

Expected: PASS.

---

### Task 7: API/chat fallback behavior with embedding failure

**Files:**
- Modify: `backend/tests/test_chat_service.py`
- Modify: `backend/app/services/context_builder.py` only if tests reveal missing fallback behavior

- [ ] **Step 1: Add failing or confirming fallback test**

Add this test to `backend/tests/test_chat_service.py`:

```python
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
```

If `FailingMemoryEmbeddingService` is not already in this file, add:

```python
class FailingMemoryEmbeddingService:
    def search_relevant(self, query: str, limit: int, min_score: float):
        raise MemoryEmbeddingUnavailableError("embedding unavailable")
```

- [ ] **Step 2: Run fallback test**

Run:

```powershell
python -m pytest backend/tests/test_chat_service.py::test_chat_service_embedding_failure_falls_back_to_relevance -q
```

Expected: PASS if Task 4 fallback was implemented correctly. If it fails, update `ContextBuilder.build_memory_context` to catch embedding errors and call `list_relevant_for_context` exactly as described in Task 4.

---

### Task 8: Documentation and environment examples

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Create: `docs/stage3f-memory-embedding-retrieval.md`
- Modify: `CLAUDE.md` after validation passes

- [ ] **Step 1: Update `.env.example`**

Add near existing memory settings:

```env
# Stage 3F memory embedding retrieval is opt-in.
# Keep MEMORY_RETRIEVAL_MODE=relevance for deterministic local retrieval.
# Set MEMORY_RETRIEVAL_MODE=embedding and MEMORY_EMBEDDING_ENABLED=true to use embedding retrieval.
MEMORY_RETRIEVAL_MODE=relevance
MEMORY_EMBEDDING_ENABLED=false
MEMORY_EMBEDDING_PROVIDER=fake
MEMORY_EMBEDDING_MODEL=fake-memory-embedding-v1
MEMORY_EMBEDDING_MIN_SCORE=0.35
```

If `.env.example` already has `MEMORY_RETRIEVAL_MODE`, update the existing block instead of duplicating it.

- [ ] **Step 2: Update README**

Add a short Stage 3F note in the Stage 3 section:

```markdown
### Stage 3F memory embedding retrieval

Embedding retrieval is opt-in. By default the app keeps deterministic relevance retrieval. To test the local fake embedding path, set:

```env
MEMORY_RETRIEVAL_MODE=embedding
MEMORY_EMBEDDING_ENABLED=true
MEMORY_EMBEDDING_PROVIDER=fake
MEMORY_EMBEDDING_MODEL=fake-memory-embedding-v1
```

This only changes retrieval for confirmed active long-term memories. It does not automatically create memories, does not summarize sessions, and does not implement emotional state.
```

- [ ] **Step 3: Create validation evidence doc**

Create `docs/stage3f-memory-embedding-retrieval.md` with:

```markdown
# Stage 3F Memory Embedding Retrieval

Date: 2026-07-08
Status: IMPLEMENTED / VERIFIED after commands below pass

## Scope

Stage 3F adds opt-in local embedding retrieval for confirmed active long-term memories. It preserves manual CRUD, candidate confirmation, conflict audit, deterministic fallback, and caveated memory context injection.

## Non-goals

- No LLM-based memory extraction.
- No automatic memory writes from chat history.
- No session summaries.
- No Stage 4 emotion system.
- No mandatory external vector database.

## Configuration

```env
MEMORY_RETRIEVAL_MODE=embedding
MEMORY_EMBEDDING_ENABLED=true
MEMORY_EMBEDDING_PROVIDER=fake
MEMORY_EMBEDDING_MODEL=fake-memory-embedding-v1
MEMORY_EMBEDDING_MIN_SCORE=0.35
```

## Validation

Record the exact commands and results after running verification.

## Limitations

The first slice stores vectors as JSON in SQLite and ranks with Python cosine similarity. This is sufficient for a local vertical slice but is not a high-performance vector index. Real sentence-transformers usage remains optional and should be smoke-tested separately before being treated as production-ready.
```

- [ ] **Step 4: Update `CLAUDE.md` only after validation**

After all validation commands pass, add a Stage 3F bullet under Stage 3 current entry:

```markdown
- 3F Memory Embedding Retrieval 已完成（2026-07-08；新增 opt-in 本地 embedding retrieval，默认保留 deterministic relevance；仅 active 长期记忆参与检索；pending/dismissed/archived 不进入上下文；embedding 失败回退到现有 relevance/recent 路径；未实现 LLM-based 记忆抽取、会话摘要或阶段 4 情感系统；证据记录于 `docs/stage3f-memory-embedding-retrieval.md`）。验证：后端 focused tests PASS；后端全量测试 PASS；前端测试/typecheck/build/E2E PASS（按实际结果填写）。
```

Replace the validation sentence with actual command results before finalizing.

---

### Task 9: Verification run

**Files:**
- No source edits unless a command fails and the failure identifies a real implementation defect.

- [ ] **Step 1: Run focused backend tests**

Run:

```powershell
python -m pytest backend/tests/test_config.py backend/tests/test_memory_embeddings.py backend/tests/test_context_builder.py backend/tests/test_api_memories.py backend/tests/test_chat_service.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full backend tests**

Run:

```powershell
python -m pytest backend/tests -q
```

Expected: PASS.

- [ ] **Step 3: Run frontend unit tests**

Run:

```powershell
npm --prefix frontend test -- --run
```

Expected: PASS.

- [ ] **Step 4: Run frontend typecheck**

Run:

```powershell
npm --prefix frontend run typecheck
```

Expected: PASS.

- [ ] **Step 5: Run frontend build**

Run:

```powershell
npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 6: Run Playwright E2E**

Run:

```powershell
npm --prefix frontend run test:e2e
```

Expected: PASS. If local browser dependencies or ports fail for environmental reasons, record the exact failure and do not claim E2E pass.

- [ ] **Step 7: Update validation docs with exact results**

Update `docs/stage3f-memory-embedding-retrieval.md` and `CLAUDE.md` with exact commands and pass/fail counts.

- [ ] **Step 8: Final security/privacy check**

Inspect changed files for accidental secrets or raw private data. Confirm:

- no API keys were added;
- no raw query or embedding list is logged;
- no recent chat history is converted into long-term memory;
- Stage 4 emotion state was not implemented.

Use:

```powershell
git diff -- .env.example README.md CLAUDE.md backend/app backend/tests docs/stage3f-memory-embedding-retrieval.md
```

Expected: diff contains only Stage 3F implementation, tests, and docs.

---

## Self-review checklist

- Spec coverage: This plan covers opt-in embedding retrieval, fake provider, optional lazy real provider, SQLite storage, active-only filtering, mutation maintenance, ContextBuilder integration, fallback, config, docs, and verification.
- Placeholder scan: The plan contains no intentional placeholders or unspecified test steps.
- Type consistency: `MemoryEmbeddingRepository`, `MemoryEmbeddingService`, `FakeMemoryEmbeddingProvider`, and `MemoryEmbeddingUnavailableError` are introduced before later tasks use them.
- Scope check: The plan does not implement LLM extraction, session summaries, sqlite-vec, or Stage 4 emotion state.
