from __future__ import annotations

import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.errors import NotFoundError
from app.domain.models import Memory, MemorySource, MemoryStatus, MemoryType
from app.repositories.sqlite import metadata_from_json, metadata_to_json


def _now() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: datetime) -> str:
    return value.isoformat()


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _normalize_content(value: str) -> str:
    return " ".join(value.strip().lower().split())


_LOW_SIGNAL_TOKENS = {
    "我", "你", "他", "她", "它", "的", "了", "吗", "呢", "啊", "呀",
    "什么", "一下", "请", "帮我", "用户", "the", "a", "an", "is", "are",
}

_TYPE_HINTS: dict[MemoryType, tuple[str, ...]] = {
    MemoryType.PREFERENCE: ("喜欢", "偏好", "讨厌", "不喜欢", "爱喝", "爱吃"),
    MemoryType.LONG_TERM_GOAL: ("目标", "准备", "计划", "打算", "想要完成"),
    MemoryType.USER_FACT: ("住", "职业", "名字", "事实", "哪里", "是谁"),
    MemoryType.IMPORTANT_EVENT: ("发生", "那次", "事件", "重要", "记得那天"),
    MemoryType.RELATIONSHIP_EVENT: ("关系", "认识", "一起", "我们", "相处"),
}


@dataclass(frozen=True)
class MemorySemanticSignature:
    kind: str
    value: str
    polarity: str | None = None


def _normalize_semantic_value(value: str) -> str:
    normalized = value.strip().lower()
    normalized = normalized.strip(" 。.，,；;：:、\"'“”‘’")
    normalized = re.sub(r"[\s。。，,；;：:、]+", "", normalized)
    return normalized


def _strip_goal_prefix(value: str) -> str:
    normalized = _normalize_semantic_value(value)
    for prefix in ("完成", "准备", "实现", "推进"):
        if normalized.startswith(prefix) and len(normalized) > len(prefix):
            return normalized[len(prefix):]
    return normalized


def _semantic_signature(content: str, memory_type: MemoryType) -> MemorySemanticSignature | None:
    clean = content.strip()
    if memory_type == MemoryType.PREFERENCE:
        dislike = re.fullmatch(r"用户不喜欢(.+?)[。.]?", clean)
        if dislike:
            value = _normalize_semantic_value(dislike.group(1))
            return MemorySemanticSignature("preference", value, "dislike") if value else None
        like = re.fullmatch(r"用户喜欢(.+?)[。.]?", clean)
        if like:
            value = _normalize_semantic_value(like.group(1))
            return MemorySemanticSignature("preference", value, "like") if value else None
        return None

    if memory_type == MemoryType.USER_FACT:
        residence = re.fullmatch(r"用户住在(.+?)[。.]?", clean)
        if residence:
            value = _normalize_semantic_value(residence.group(1))
            return MemorySemanticSignature("residence", value) if value else None
        occupation = re.fullmatch(r"用户的职业是(.+?)[。.]?", clean)
        if occupation:
            value = _normalize_semantic_value(occupation.group(1))
            return MemorySemanticSignature("occupation", value) if value else None
        return None

    if memory_type == MemoryType.LONG_TERM_GOAL:
        goal = re.fullmatch(r"用户的目标是(.+?)[。.]?", clean)
        if goal:
            value = _strip_goal_prefix(goal.group(1))
            return MemorySemanticSignature("goal", value) if value else None
        preparation = re.fullmatch(r"用户正在准备(.+?)[。.]?", clean)
        if preparation:
            value = _strip_goal_prefix(preparation.group(1))
            return MemorySemanticSignature("goal", value) if value else None
        return None

    return None


def _semantic_conflict(
    candidate: MemorySemanticSignature | None,
    existing: MemorySemanticSignature | None,
    memory_type: MemoryType,
) -> bool:
    if candidate is None or existing is None:
        return False
    if candidate.kind != existing.kind:
        return False

    if memory_type == MemoryType.PREFERENCE:
        return candidate.value == existing.value and candidate.polarity != existing.polarity

    if memory_type == MemoryType.USER_FACT:
        return candidate.value != existing.value

    if memory_type == MemoryType.LONG_TERM_GOAL:
        return candidate.value == existing.value

    return False


def _ascii_tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if token not in _LOW_SIGNAL_TOKENS}


def _cjk_runs(text: str) -> list[str]:
    return re.findall(r"[一-鿿]+", text)


def _cjk_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for run in _cjk_runs(text):
        if run not in _LOW_SIGNAL_TOKENS and len(run) >= 2:
            tokens.add(run)
        for size in (2, 3):
            for index in range(0, max(0, len(run) - size + 1)):
                token = run[index:index + size]
                if token not in _LOW_SIGNAL_TOKENS:
                    tokens.add(token)
    return tokens


def _tokens(text: str) -> set[str]:
    return _ascii_tokens(text) | _cjk_tokens(text)


def _hinted_types(query: str) -> set[MemoryType]:
    return {
        memory_type
        for memory_type, hints in _TYPE_HINTS.items()
        if any(hint in query for hint in hints)
    }


def _relevance_score(query_tokens: set[str], hinted_types: set[MemoryType], memory: Memory) -> float:
    memory_tokens = _tokens(memory.content)
    overlap = len(query_tokens & memory_tokens)
    type_bonus = 3.0 if memory.memory_type in hinted_types else 0.0
    if overlap == 0 and type_bonus == 0.0:
        return 0.0
    return (overlap * 10.0) + type_bonus + (memory.importance * 0.2) + (memory.confidence * 0.2)


def _metadata_with_timestamp(metadata: dict[str, Any], key: str, value: datetime) -> dict[str, Any]:
    next_metadata = dict(metadata)
    next_metadata[key] = _to_iso(value)
    return next_metadata


def _row_to_memory(row: sqlite3.Row) -> Memory:
    return Memory(
        id=row["id"],
        content=row["content"],
        memory_type=MemoryType(row["memory_type"]),
        source=MemorySource(row["source"]),
        source_session_id=row["source_session_id"],
        importance=row["importance"],
        confidence=row["confidence"],
        status=MemoryStatus(row["status"]),
        created_at=_from_iso(row["created_at"]),
        updated_at=_from_iso(row["updated_at"]),
        metadata=metadata_from_json(row["metadata_json"]),
    )


class MemoryRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create(
        self,
        *,
        content: str,
        memory_type: MemoryType,
        source: MemorySource,
        source_session_id: str | None,
        importance: int,
        confidence: float,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[Memory, list[Memory]]:
        clean_content = content.strip()
        conflicts = self.find_conflicts(clean_content, memory_type)
        now = _now()
        memory = Memory(
            id=str(uuid.uuid4()),
            content=clean_content,
            memory_type=memory_type,
            source=source,
            source_session_id=source_session_id,
            importance=importance,
            confidence=confidence,
            status=MemoryStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
        self._connection.execute(
            """
            INSERT INTO memories (
                id, content, memory_type, source, source_session_id,
                importance, confidence, status, metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory.id,
                memory.content,
                memory.memory_type.value,
                memory.source.value,
                memory.source_session_id,
                memory.importance,
                memory.confidence,
                memory.status.value,
                metadata_to_json(memory.metadata),
                _to_iso(memory.created_at),
                _to_iso(memory.updated_at),
            ),
        )
        self._connection.commit()
        return memory, conflicts

    def list(self, status: MemoryStatus = MemoryStatus.ACTIVE) -> list[Memory]:
        rows = self._connection.execute(
            """
            SELECT id, content, memory_type, source, source_session_id, importance,
                   confidence, status, metadata_json, created_at, updated_at
            FROM memories
            WHERE status = ?
            ORDER BY importance DESC, updated_at DESC
            """,
            (status.value,),
        ).fetchall()
        return [_row_to_memory(row) for row in rows]

    def get(self, memory_id: str) -> Memory | None:
        row = self._connection.execute(
            """
            SELECT id, content, memory_type, source, source_session_id, importance,
                   confidence, status, metadata_json, created_at, updated_at
            FROM memories
            WHERE id = ?
            """,
            (memory_id,),
        ).fetchone()
        return _row_to_memory(row) if row else None

    def require(self, memory_id: str) -> Memory:
        memory = self.get(memory_id)
        if memory is None:
            raise NotFoundError("长期记忆不存在。")
        return memory

    def update(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        memory_type: MemoryType | None = None,
        importance: int | None = None,
        confidence: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[Memory, list[Memory]]:
        current = self.require(memory_id)
        next_content = current.content if content is None else content.strip()
        next_type = current.memory_type if memory_type is None else memory_type
        next_importance = current.importance if importance is None else importance
        next_confidence = current.confidence if confidence is None else confidence
        next_metadata = current.metadata if metadata is None else metadata
        conflicts = self.find_conflicts(next_content, next_type, exclude_id=memory_id)
        updated_at = _now()
        self._connection.execute(
            """
            UPDATE memories
            SET content = ?, memory_type = ?, importance = ?, confidence = ?,
                metadata_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                next_content,
                next_type.value,
                next_importance,
                next_confidence,
                metadata_to_json(next_metadata),
                _to_iso(updated_at),
                memory_id,
            ),
        )
        self._connection.commit()
        return self.require(memory_id), conflicts

    def create_candidate(
        self,
        *,
        content: str,
        memory_type: MemoryType,
        source_session_id: str | None,
        importance: int,
        confidence: float,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[Memory | None, list[Memory]]:
        clean_content = content.strip()
        conflicts = self.find_conflicts(
            clean_content,
            memory_type,
            statuses=(MemoryStatus.ACTIVE, MemoryStatus.PENDING),
        )
        if conflicts:
            return None, conflicts
        now = _now()
        memory = Memory(
            id=str(uuid.uuid4()),
            content=clean_content,
            memory_type=memory_type,
            source=MemorySource.CANDIDATE,
            source_session_id=source_session_id,
            importance=importance,
            confidence=confidence,
            status=MemoryStatus.PENDING,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
        self._connection.execute(
            """
            INSERT INTO memories (
                id, content, memory_type, source, source_session_id,
                importance, confidence, status, metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory.id,
                memory.content,
                memory.memory_type.value,
                memory.source.value,
                memory.source_session_id,
                memory.importance,
                memory.confidence,
                memory.status.value,
                metadata_to_json(memory.metadata),
                _to_iso(memory.created_at),
                _to_iso(memory.updated_at),
            ),
        )
        self._connection.commit()
        return memory, conflicts

    def confirm_candidate(self, memory_id: str) -> tuple[Memory, list[Memory]]:
        current = self.require(memory_id)
        if current.status != MemoryStatus.PENDING:
            raise ValueError("Only pending memory candidates can be confirmed")
        conflicts = self.find_conflicts(
            current.content,
            current.memory_type,
            exclude_id=memory_id,
            statuses=(MemoryStatus.ACTIVE,),
        )
        if conflicts:
            return current, conflicts
        updated_at = _now()
        next_metadata = _metadata_with_timestamp(current.metadata, "confirmed_at", updated_at)
        self._connection.execute(
            """
            UPDATE memories
            SET status = ?, metadata_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                MemoryStatus.ACTIVE.value,
                metadata_to_json(next_metadata),
                _to_iso(updated_at),
                memory_id,
            ),
        )
        self._connection.commit()
        return self.require(memory_id), []

    def dismiss_candidate(self, memory_id: str) -> Memory:
        current = self.require(memory_id)
        if current.status != MemoryStatus.PENDING:
            raise ValueError("Only pending memory candidates can be dismissed")
        updated_at = _now()
        next_metadata = _metadata_with_timestamp(current.metadata, "dismissed_at", updated_at)
        self._connection.execute(
            """
            UPDATE memories
            SET status = ?, metadata_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                MemoryStatus.DISMISSED.value,
                metadata_to_json(next_metadata),
                _to_iso(updated_at),
                memory_id,
            ),
        )
        self._connection.commit()
        return self.require(memory_id)

    def archive(self, memory_id: str) -> bool:
        cursor = self._connection.execute(
            "UPDATE memories SET status = ?, updated_at = ? WHERE id = ?",
            (MemoryStatus.ARCHIVED.value, _to_iso(_now()), memory_id),
        )
        self._connection.commit()
        return cursor.rowcount > 0

    def list_for_context(self, limit: int) -> list[Memory]:
        rows = self._connection.execute(
            """
            SELECT id, content, memory_type, source, source_session_id, importance,
                   confidence, status, metadata_json, created_at, updated_at
            FROM memories
            WHERE status = ?
            ORDER BY importance DESC, updated_at DESC
            LIMIT ?
            """,
            (MemoryStatus.ACTIVE.value, limit),
        ).fetchall()
        return [_row_to_memory(row) for row in rows]

    def list_relevant_for_context(self, query: str, limit: int, fallback_limit: int) -> list[Memory]:
        clean_query = query.strip()
        if not clean_query:
            return self.list_for_context(min(limit, fallback_limit))

        query_tokens = _tokens(clean_query)
        hinted_types = _hinted_types(clean_query)
        if not query_tokens and not hinted_types:
            return self.list_for_context(min(limit, fallback_limit))

        active_memories = self.list(status=MemoryStatus.ACTIVE)
        scored = [
            (_relevance_score(query_tokens, hinted_types, memory), memory)
            for memory in active_memories
        ]
        relevant = [(score, memory) for score, memory in scored if score > 0.0]
        if not relevant:
            return self.list_for_context(min(limit, fallback_limit))

        relevant.sort(
            key=lambda item: (
                item[0],
                item[1].importance,
                item[1].confidence,
                item[1].updated_at,
            ),
            reverse=True,
        )
        return [memory for _score, memory in relevant[:limit]]

    def find_conflicts(
        self,
        content: str,
        memory_type: MemoryType,
        exclude_id: str | None = None,
        statuses: tuple[MemoryStatus, ...] = (MemoryStatus.ACTIVE,),
    ) -> list[Memory]:
        normalized = _normalize_content(content)
        signature = _semantic_signature(content, memory_type)
        conflicts: list[Memory] = []
        for status in statuses:
            conflicts.extend(self.list(status=status))
        return [
            memory
            for memory in conflicts
            if memory.memory_type == memory_type
            and memory.id != exclude_id
            and (
                _normalize_content(memory.content) == normalized
                or _semantic_conflict(signature, _semantic_signature(memory.content, memory.memory_type), memory_type)
            )
        ]
