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
            SELECT e.memory_id, e.embedding_json
            FROM memory_embeddings e
            JOIN memories m ON m.id = e.memory_id
            WHERE e.provider = ? AND e.model = ? AND m.status = ?
            """,
            (provider, model, MemoryStatus.ACTIVE.value),
        ).fetchall()
        memories = MemoryRepository(self._connection)
        scored: list[ScoredMemory] = []
        for row in rows:
            score = _cosine_similarity(query_embedding, _embedding_from_json(row["embedding_json"]))
            if score < min_score:
                continue
            scored.append(ScoredMemory(memory=memories.require(row["memory_id"]), score=score))
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
