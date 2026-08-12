from __future__ import annotations

import re
import sqlite3
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from app.core.errors import MemoryCandidateForgottenError, NotFoundError
from app.domain.models import (
    Memory,
    MemoryRecordState,
    MemorySource,
    MemoryStatus,
    MemoryType,
    MemoryVersionSourceKind,
)
from app.repositories.memory_eligibility import MEMORY_ELIGIBLE_PREDICATE
from app.repositories.sqlite import metadata_from_json, metadata_to_json
from app.services.memory_source_reference import MemorySourceReferenceService


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
class StructuredMemoryContextSource:
    memory_id: str
    current_version_id: str | None
    source_kind: MemoryVersionSourceKind
    content: str
    memory_type: MemoryType
    importance: int
    confidence: float
    updated_at: datetime
    relevance_score: float
    legacy_compat: bool


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


_HISTORICAL_MARKERS = ("以前", "之前", "过去", "曾经", "去年", "上个月", "小时候")


def _has_historical_marker(content: str) -> bool:
    return any(marker in content for marker in _HISTORICAL_MARKERS)


def _current_user_fact_signature(content: str) -> MemorySemanticSignature | None:
    clean = content.strip()
    name = re.fullmatch(r"用户(?:的)?名字是(.+?)[。.]?", clean)
    if name:
        value = _normalize_semantic_value(name.group(1))
        return MemorySemanticSignature("name", value) if value else None
    called = re.fullmatch(r"用户叫(.+?)[。.]?", clean)
    if called:
        value = _normalize_semantic_value(called.group(1))
        return MemorySemanticSignature("name", value) if value else None

    school = re.fullmatch(r"用户就读于(.+?)[。.]?", clean)
    if school:
        value = _normalize_semantic_value(school.group(1))
        return MemorySemanticSignature("school", value) if value else None
    school_study = re.fullmatch(r"用户在(.+?)读书[。.]?", clean)
    if school_study:
        value = _normalize_semantic_value(school_study.group(1))
        return MemorySemanticSignature("school", value) if value else None
    school_student = re.fullmatch(r"用户是(.+?)学生[。.]?", clean)
    if school_student:
        value = _normalize_semantic_value(school_student.group(1))
        return MemorySemanticSignature("school", value) if value else None

    company = re.fullmatch(r"用户就职于(.+?)[。.]?", clean)
    if company:
        value = _normalize_semantic_value(company.group(1))
        return MemorySemanticSignature("company", value) if value else None
    company_work = re.fullmatch(r"用户在(.+?)工作[。.]?", clean)
    if company_work:
        value = _normalize_semantic_value(company_work.group(1))
        return MemorySemanticSignature("company", value) if value else None
    company_named = re.fullmatch(r"用户的公司是(.+?)[。.]?", clean)
    if company_named:
        value = _normalize_semantic_value(company_named.group(1))
        return MemorySemanticSignature("company", value) if value else None

    return None


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
        prefer = re.fullmatch(r"用户偏好(.+?)[。.]?", clean)
        if prefer:
            value = _normalize_semantic_value(prefer.group(1))
            return MemorySemanticSignature("preference", value, "like") if value else None
        return None

    if memory_type == MemoryType.USER_FACT:
        if _has_historical_marker(clean):
            return None
        residence = re.fullmatch(r"用户住在(.+?)[。.]?", clean)
        if residence:
            value = _normalize_semantic_value(residence.group(1))
            return MemorySemanticSignature("residence", value) if value else None
        occupation = re.fullmatch(r"用户的职业是(.+?)[。.]?", clean)
        if occupation:
            value = _normalize_semantic_value(occupation.group(1))
            return MemorySemanticSignature("occupation", value) if value else None
        expanded = _current_user_fact_signature(clean)
        if expanded is not None:
            return expanded
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


_PREFERENCE_CATEGORY_PREFIXES: dict[str, tuple[str, ...]] = {
    "热饮": ("热",),
}


def _preference_values_overlap(candidate: str, existing: str) -> bool:
    if candidate == existing:
        return True
    return any(
        existing.startswith(prefix)
        for prefix in _PREFERENCE_CATEGORY_PREFIXES.get(candidate, ())
    ) or any(
        candidate.startswith(prefix)
        for prefix in _PREFERENCE_CATEGORY_PREFIXES.get(existing, ())
    )


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
        return (
            _preference_values_overlap(candidate.value, existing.value)
            and candidate.polarity != existing.polarity
        )

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
    v2_state = row["v2_state"] if "v2_state" in row.keys() else None
    v2_source_kind = (
        row["v2_source_kind"] if "v2_source_kind" in row.keys() else None
    )
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
        v2_state=MemoryRecordState(v2_state) if v2_state is not None else None,
        v2_source_kind=(
            MemoryVersionSourceKind(v2_source_kind)
            if v2_source_kind is not None
            else None
        ),
        version_count=(
            int(row["version_count"])
            if "version_count" in row.keys()
            else 0
        ),
        evidence_count=(
            int(row["evidence_count"])
            if "evidence_count" in row.keys()
            else 0
        ),
        has_open_conflict=(
            bool(row["has_open_conflict"])
            if "has_open_conflict" in row.keys()
            else False
        ),
        can_undo_latest_auto=(
            bool(row["can_undo_latest_auto"])
            if "can_undo_latest_auto" in row.keys()
            else False
        ),
        canonical_subject_code=(
            row["canonical_subject_code"]
            if "canonical_subject_code" in row.keys()
            else None
        ),
    )


class MemoryRepository:
    _SUMMARY_SELECT = """
        SELECT memory.id, memory.content, memory.memory_type, memory.source,
               memory.source_session_id, memory.importance, memory.confidence,
               memory.status, memory.metadata_json, memory.created_at,
               memory.updated_at, state.state AS v2_state,
               state.source_kind AS v2_source_kind,
               current_version.canonical_subject_code AS canonical_subject_code,
               (
                   SELECT COUNT(*) FROM memory_versions AS summary_version
                   WHERE summary_version.memory_id = memory.id
               ) AS version_count,
               (
                   SELECT COUNT(*) FROM memory_evidence AS summary_evidence
                   WHERE summary_evidence.memory_id = memory.id
               ) AS evidence_count,
               EXISTS (
                   SELECT 1 FROM memory_conflicts AS conflict
                   WHERE conflict.status = 'open'
                     AND memory.id IN (
                         conflict.left_memory_id,
                         conflict.right_memory_id
                     )
               ) AS has_open_conflict,
               EXISTS (
                   SELECT 1
                   FROM memory_write_activities AS activity
                   WHERE activity.op_id = (
                       SELECT latest.op_id
                       FROM memory_write_activities AS latest
                       WHERE latest.memory_id = memory.id
                         AND latest.outcome IN (
                             'committed_create',
                             'committed_supersede',
                             'committed_support'
                         )
                       ORDER BY latest.created_at DESC, latest.op_id DESC
                       LIMIT 1
                   )
                     AND NOT EXISTS (
                         SELECT 1 FROM memory_conflicts AS undo_conflict
                         WHERE undo_conflict.status = 'open'
                           AND memory.id IN (
                               undo_conflict.left_memory_id,
                               undo_conflict.right_memory_id
                           )
                     )
                     AND NOT EXISTS (
                         SELECT 1 FROM memory_audit_events AS audit
                         WHERE audit.event_type = 'auto_change_undone'
                           AND audit.operation = 'undo_auto'
                           AND json_extract(audit.metadata_json, '$.auto_op_id') =
                               activity.op_id
                     )
                     AND (
                         (
                             activity.outcome = 'committed_create'
                             AND state.state = 'active'
                             AND state.current_version_id = activity.result_version_id
                         )
                         OR (
                             activity.outcome = 'committed_supersede'
                             AND state.current_version_id = activity.result_version_id
                         )
                         OR (
                             activity.outcome = 'committed_support'
                             AND state.current_version_id = activity.result_version_id
                             AND EXISTS (
                                 SELECT 1 FROM memory_evidence AS evidence
                                 WHERE evidence.memory_id = activity.memory_id
                                   AND evidence.memory_version_id = activity.result_version_id
                                   AND evidence.extractor_kind = activity.extractor_kind
                                   AND COALESCE(evidence.extractor_provider, '') =
                                       COALESCE(activity.provider_identifier, '')
                                   AND COALESCE(evidence.extractor_model, '') =
                                       COALESCE(activity.model_identifier, '')
                                   AND NOT EXISTS (
                                       SELECT 1
                                       FROM memory_evidence_retractions AS retraction
                                       WHERE retraction.evidence_id = evidence.evidence_id
                                   )
                             )
                         )
                     )
               ) AS can_undo_latest_auto
        FROM memories AS memory
        LEFT JOIN memory_record_states AS state
          ON state.memory_id = memory.id
        LEFT JOIN memory_versions AS current_version
          ON current_version.memory_id = state.memory_id
         AND current_version.id = state.current_version_id
         AND current_version.version_number = state.head_version
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        source_references: MemorySourceReferenceService | None = None,
    ) -> None:
        self._connection = connection
        self._source_references = source_references

    def _versioned_mutations(self):
        from app.repositories.versioned_memories import VersionedMemoryRepository
        from app.services.versioned_memory_mutation import VersionedMemoryMutationService

        return VersionedMemoryMutationService(
            self._connection,
            memories=self,
            versioned=VersionedMemoryRepository(self._connection),
            source_references=self._source_references,
        )

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
        canonical_subject_code: str | None = None,
    ) -> tuple[Memory, list[Memory]]:
        if source is not MemorySource.MANUAL:
            raise ValueError("formal memory creation requires manual source")
        return self._versioned_mutations().create_manual(
            content=content,
            memory_type=memory_type,
            source_session_id=source_session_id,
            importance=importance,
            confidence=confidence,
            metadata=metadata,
            canonical_subject_code=canonical_subject_code,
        )

    def list(self, status: MemoryStatus = MemoryStatus.ACTIVE) -> list[Memory]:
        rows = self._connection.execute(
            f"""
            {self._SUMMARY_SELECT}
            WHERE memory.status = ?
            ORDER BY memory.importance DESC, memory.updated_at DESC
            """,
            (status.value,),
        ).fetchall()
        return [_row_to_memory(row) for row in rows]

    def get(self, memory_id: str) -> Memory | None:
        row = self._connection.execute(
            f"""
            {self._SUMMARY_SELECT}
            WHERE memory.id = ?
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
        canonical_subject_code: str | None = None,
        canonical_subject_code_provided: bool = False,
    ) -> tuple[Memory, list[Memory]]:
        return self._versioned_mutations().update(
            memory_id,
            content=content,
            memory_type=memory_type,
            importance=importance,
            confidence=confidence,
            metadata=metadata,
            canonical_subject_code=canonical_subject_code,
            canonical_subject_code_provided=canonical_subject_code_provided,
        )

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
                source_session_reference_hash, importance, confidence, status,
                metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory.id,
                memory.content,
                memory.memory_type.value,
                memory.source.value,
                memory.source_session_id,
                (
                    self._source_references.session_hash(memory.source_session_id)
                    if memory.source_session_id is not None
                    and self._source_references is not None
                    else None
                ),
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

    def confirm_candidate(
        self,
        memory_id: str,
        *,
        canonical_subject_code: str | None = None,
    ) -> tuple[Memory, list[Memory]]:
        return self._versioned_mutations().confirm_candidate(
            memory_id,
            canonical_subject_code=canonical_subject_code,
        )

    def dismiss_candidate(self, memory_id: str) -> Memory:
        current = self.require(memory_id)
        if current.metadata.get("forgotten") is True:
            raise MemoryCandidateForgottenError()
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
        return self._versioned_mutations().archive(memory_id)

    def context_sources_for_memories(
        self,
        memories: list[Memory],
    ) -> list[StructuredMemoryContextSource]:
        selected_ids = [memory.id for memory in memories]
        if not selected_ids:
            return []
        sources = self.list_context_sources(None, 1_000_000)
        by_id = {source.memory_id: source for source in sources}
        selected: list[StructuredMemoryContextSource] = []
        for rank, memory in enumerate(memories):
            source = by_id.get(memory.id)
            if source is None:
                continue
            selected.append(
                replace(source, relevance_score=float(len(memories) - rank))
            )
        return selected

    def list_context_sources(
        self,
        query: str | None,
        limit: int,
        fallback_limit: int = 3,
    ) -> list[StructuredMemoryContextSource]:
        clean_query = (query or "").strip()
        query_tokens = _tokens(clean_query) if clean_query else set()
        hinted_types = _hinted_types(clean_query) if clean_query else set()
        rows = self._connection.execute(
            f"""
            SELECT memory.id AS memory_id,
                   COALESCE(version.content, memory.content) AS content,
                   COALESCE(version.memory_type, memory.memory_type) AS memory_type,
                   COALESCE(version.importance, memory.importance) AS importance,
                   COALESCE(version.confidence, memory.confidence) AS confidence,
                   COALESCE(state.updated_at, memory.updated_at) AS updated_at,
                   state.current_version_id AS current_version_id,
                   COALESCE(version.source_kind, 'legacy') AS source_kind,
                   CASE WHEN state.memory_id IS NULL THEN 1 ELSE 0 END AS legacy_compat
            FROM memories AS memory
            LEFT JOIN memory_record_states AS state
              ON state.memory_id = memory.id
            LEFT JOIN memory_versions AS version
              ON version.memory_id = state.memory_id
             AND version.id = state.current_version_id
             AND version.version_number = state.head_version
            WHERE {MEMORY_ELIGIBLE_PREDICATE}
            """
        ).fetchall()
        sources: list[StructuredMemoryContextSource] = []
        for row in rows:
            memory = Memory(
                id=str(row["memory_id"]),
                content=str(row["content"]),
                memory_type=MemoryType(str(row["memory_type"])),
                source=MemorySource.MANUAL,
                source_session_id=None,
                importance=int(row["importance"]),
                confidence=float(row["confidence"]),
                status=MemoryStatus.ACTIVE,
                created_at=_from_iso(str(row["updated_at"])),
                updated_at=_from_iso(str(row["updated_at"])),
                metadata={},
            )
            score = (
                _relevance_score(query_tokens, hinted_types, memory)
                if clean_query
                else 0.0
            )
            sources.append(
                StructuredMemoryContextSource(
                    memory_id=memory.id,
                    current_version_id=(
                        str(row["current_version_id"])
                        if row["current_version_id"] is not None
                        else None
                    ),
                    source_kind=MemoryVersionSourceKind(str(row["source_kind"])),
                    content=memory.content,
                    memory_type=memory.memory_type,
                    importance=memory.importance,
                    confidence=memory.confidence,
                    updated_at=memory.updated_at,
                    relevance_score=score,
                    legacy_compat=bool(row["legacy_compat"]),
                )
            )
        if clean_query:
            relevant = [item for item in sources if item.relevance_score > 0.0]
            if relevant:
                sources = relevant
            else:
                limit = min(limit, fallback_limit)
        sources.sort(
            key=lambda item: (
                -item.relevance_score,
                0
                if item.source_kind.value
                in {"manual", "candidate", "user_edit", "user_revert"}
                else 1,
                -item.importance,
                -item.confidence,
                -item.updated_at.timestamp(),
                item.memory_id,
                item.current_version_id or "",
            )
        )
        return sources[:limit]

    def list_for_context(self, limit: int) -> list[Memory]:
        return self._list_context_eligible(limit)

    def _list_context_eligible(self, limit: int) -> list[Memory]:
        rows = self._connection.execute(
            f"""
            SELECT memory.id, memory.content, memory.memory_type, memory.source,
                   memory.source_session_id, memory.importance, memory.confidence,
                   memory.status, memory.metadata_json, memory.created_at,
                   memory.updated_at
            FROM memories AS memory
            LEFT JOIN memory_record_states AS state
              ON state.memory_id = memory.id
            LEFT JOIN memory_versions AS version
              ON version.memory_id = state.memory_id
             AND version.id = state.current_version_id
             AND version.version_number = state.head_version
            WHERE {MEMORY_ELIGIBLE_PREDICATE}
            ORDER BY memory.importance DESC, memory.updated_at DESC, memory.id DESC
            LIMIT ?
            """,
            (limit,),
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

        active_memories = self._list_context_eligible(limit=10000)
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
