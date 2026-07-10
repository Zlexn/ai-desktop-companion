# Stage 3 Memory Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first Stage 3 long-term memory vertical slice: manual CRUD, independent SQLite storage, conflict visibility, caveated chat-context injection, minimal React UI, tests, and docs.

**Architecture:** Add a dedicated backend memory domain/repository/API path parallel to sessions/messages, then optionally feed active memories into chat as a separate caveated system message. Add frontend API methods and a small `MemoryPanel` rendered in the existing layout without changing voice flows.

**Tech Stack:** Python 3.11+/FastAPI/SQLite/pytest backend; React/TypeScript/Vite/Vitest/Playwright frontend; Markdown evidence docs.

---

## File Structure

- Modify: `backend/app/domain/models.py` — add memory enums and `Memory` dataclass.
- Modify: `backend/app/domain/schemas.py` — add memory request/response schemas.
- Modify: `backend/app/repositories/sqlite.py` — add `memories` table and indexes.
- Create: `backend/app/repositories/memories.py` — memory persistence, archive, duplicate conflict lookup, context query.
- Modify: `backend/app/api/dependencies.py` — add `get_memory_repository` and pass it into chat context.
- Create: `backend/app/api/routes/memories.py` — `/api/memories` CRUD routes.
- Modify: `backend/app/main.py` — include memory router.
- Modify: `backend/app/core/config.py` — add `MEMORY_CONTEXT_ENABLED` and `MEMORY_CONTEXT_LIMIT`.
- Modify: `backend/app/services/context_builder.py` — add caveated memory context construction.
- Modify: `backend/app/services/chat_service.py` — include memory context before recent chat context.
- Modify: `backend/tests/test_repositories.py` — add repository tests for memory persistence, archive, and conflicts.
- Create: `backend/tests/test_api_memories.py` — API CRUD/validation tests.
- Modify: `backend/tests/test_context_builder.py` — memory context tests.
- Modify: `backend/tests/test_config.py` — memory config tests.
- Modify: `frontend/src/api/types.ts` — add memory types.
- Modify: `frontend/src/api/client.ts` — add memory client methods.
- Modify: `frontend/src/api/client.test.ts` — add memory client tests.
- Create: `frontend/src/components/MemoryPanel.tsx` — memory list/create/edit/delete UI.
- Create: `frontend/src/components/MemoryPanel.test.tsx` — panel behavior tests.
- Modify: `frontend/src/components/ChatLayout.tsx` — render `MemoryPanel`.
- Modify: `frontend/src/App.tsx` — own memory state and wire API calls.
- Modify: `frontend/src/App.test.tsx` — ensure memory panel failure does not block chat.
- Modify: `frontend/src/styles.css` — minimal memory panel styling.
- Create: `frontend/e2e/memories.spec.ts` — fake-provider E2E smoke.
- Create: `docs/stage3-memory-foundation.md` — evidence and limits.
- Modify: `CLAUDE.md` and `README.md` after validation passes.

## Task 1: Backend Memory Domain and Repository

**Files:**
- Modify: `backend/app/domain/models.py`
- Modify: `backend/app/repositories/sqlite.py`
- Create: `backend/app/repositories/memories.py`
- Test: `backend/tests/test_repositories.py`

- [ ] **Step 1: Write failing repository tests**

Append to `backend/tests/test_repositories.py`:

```python
from app.domain.models import MemorySource, MemoryStatus, MemoryType
from app.repositories.memories import MemoryRepository


def test_create_list_get_and_archive_memory(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        created, conflicts = memories.create(
            content="用户偏好中文回复。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={"note": "manual test"},
        )

        assert conflicts == []
        assert created.content == "用户偏好中文回复。"
        assert created.memory_type == MemoryType.PREFERENCE
        assert created.source == MemorySource.MANUAL
        assert created.status == MemoryStatus.ACTIVE
        assert created.importance == 3
        assert created.confidence == 1.0
        assert created.metadata == {"note": "manual test"}
        assert memories.get(created.id) == created
        assert memories.list() == [created]

        assert memories.archive(created.id) is True
        archived = memories.require(created.id)
        assert archived.status == MemoryStatus.ARCHIVED
        assert memories.list() == []
        assert memories.list(status=MemoryStatus.ARCHIVED) == [archived]


def test_memories_persist_after_reconnect(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        created, _ = memories.create(
            content="用户正在构建本地 AI 桌宠。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=5,
            confidence=1.0,
            metadata={},
        )

    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        loaded = memories.require(created.id)
        assert loaded.content == "用户正在构建本地 AI 桌宠。"
        assert loaded.memory_type == MemoryType.LONG_TERM_GOAL


def test_chat_messages_are_not_memories(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        session = sessions.create("聊天不是记忆")
        messages.add(session.id, ChatRole.USER, "我喜欢雪天。")

        assert memories.list() == []


def test_duplicate_same_type_memory_returns_conflict_without_overwrite(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        first, first_conflicts = memories.create(
            content="用户喜欢中文回复。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )
        second, second_conflicts = memories.create(
            content=" 用户喜欢中文回复。 ",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=2,
            confidence=0.8,
            metadata={},
        )

        assert first_conflicts == []
        assert [memory.id for memory in second_conflicts] == [first.id]
        assert memories.require(first.id).content == "用户喜欢中文回复。"
        assert memories.require(second.id).content == "用户喜欢中文回复。"
        assert len(memories.list()) == 2


def test_same_content_different_memory_type_is_not_conflict(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        memories.create(
            content="用户喜欢雪。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )
        _, conflicts = memories.create(
            content="用户喜欢雪。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert conflicts == []
```

- [ ] **Step 2: Run repository tests to verify RED**

Run:

```powershell
python -m pytest backend/tests/test_repositories.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.repositories.memories'` or missing memory model names.

- [ ] **Step 3: Implement memory domain models**

Modify `backend/app/domain/models.py` by adding these definitions after `Message`:

```python
class MemoryType(StrEnum):
    USER_FACT = "user_fact"
    PREFERENCE = "preference"
    LONG_TERM_GOAL = "long_term_goal"
    IMPORTANT_EVENT = "important_event"
    RELATIONSHIP_EVENT = "relationship_event"
    OTHER = "other"


class MemorySource(StrEnum):
    MANUAL = "manual"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


@dataclass(frozen=True)
class Memory:
    id: str
    content: str
    memory_type: MemoryType
    source: MemorySource
    source_session_id: str | None
    importance: int
    confidence: float
    status: MemoryStatus
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any]
```

- [ ] **Step 4: Add SQLite memory table**

Modify `backend/app/repositories/sqlite.py` `SCHEMA_SQL` by appending after the messages index:

```sql
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    memory_type TEXT NOT NULL CHECK (memory_type IN ('user_fact', 'preference', 'long_term_goal', 'important_event', 'relationship_event', 'other')),
    source TEXT NOT NULL CHECK (source IN ('manual')),
    source_session_id TEXT,
    importance INTEGER NOT NULL CHECK (importance >= 1 AND importance <= 5),
    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    status TEXT NOT NULL CHECK (status IN ('active', 'archived')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (source_session_id) REFERENCES sessions(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_memories_status_importance_updated
ON memories(status, importance DESC, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_memories_type_status
ON memories(memory_type, status);
```

- [ ] **Step 5: Create memory repository**

Create `backend/app/repositories/memories.py`:

```python
from __future__ import annotations

import sqlite3
import uuid
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

    def find_conflicts(
        self,
        content: str,
        memory_type: MemoryType,
        exclude_id: str | None = None,
    ) -> list[Memory]:
        normalized = _normalize_content(content)
        candidates = self.list(status=MemoryStatus.ACTIVE)
        return [
            memory
            for memory in candidates
            if memory.memory_type == memory_type
            and memory.id != exclude_id
            and _normalize_content(memory.content) == normalized
        ]
```

- [ ] **Step 6: Run repository tests to verify GREEN**

Run:

```powershell
python -m pytest backend/tests/test_repositories.py -q
```

Expected: PASS.

## Task 2: Backend Memory API

**Files:**
- Modify: `backend/app/domain/schemas.py`
- Modify: `backend/app/api/dependencies.py`
- Create: `backend/app/api/routes/memories.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api_memories.py`

- [ ] **Step 1: Write failing API tests**

Create `backend/tests/test_api_memories.py`:

```python
from fastapi.testclient import TestClient


def test_create_list_update_and_delete_memory_api(client: TestClient) -> None:
    create_response = client.post(
        "/api/memories",
        json={
            "content": "用户偏好中文回复。",
            "memory_type": "preference",
            "importance": 3,
            "confidence": 1.0,
        },
    )
    assert create_response.status_code == 201
    created_body = create_response.json()
    memory = created_body["memory"]
    assert created_body["conflicts"] == []
    assert memory["content"] == "用户偏好中文回复。"
    assert memory["source"] == "manual"
    assert memory["status"] == "active"

    list_response = client.get("/api/memories")
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [memory["id"]]

    update_response = client.patch(
        f"/api/memories/{memory['id']}",
        json={"content": "用户偏好简洁中文回复。", "importance": 4, "confidence": 0.9},
    )
    assert update_response.status_code == 200
    updated = update_response.json()["memory"]
    assert updated["content"] == "用户偏好简洁中文回复。"
    assert updated["importance"] == 4
    assert updated["confidence"] == 0.9

    delete_response = client.delete(f"/api/memories/{memory['id']}")
    assert delete_response.status_code == 204
    assert client.get("/api/memories").json() == []


def test_memory_api_rejects_invalid_fields(client: TestClient) -> None:
    response = client.post(
        "/api/memories",
        json={"content": "x", "memory_type": "preference", "importance": 6, "confidence": 1.0},
    )

    assert response.status_code == 422


def test_memory_api_rejects_missing_source_session(client: TestClient) -> None:
    response = client.post(
        "/api/memories",
        json={
            "content": "来自不存在会话的记忆。",
            "memory_type": "important_event",
            "source_session_id": "missing",
            "importance": 3,
            "confidence": 1.0,
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "会话不存在。"


def test_duplicate_memory_api_returns_conflicts_without_overwriting(client: TestClient) -> None:
    first = client.post(
        "/api/memories",
        json={"content": "用户喜欢雪。", "memory_type": "preference", "importance": 3, "confidence": 1.0},
    ).json()["memory"]

    second_response = client.post(
        "/api/memories",
        json={"content": " 用户喜欢雪。 ", "memory_type": "preference", "importance": 2, "confidence": 0.8},
    )

    assert second_response.status_code == 201
    second_body = second_response.json()
    assert [item["id"] for item in second_body["conflicts"]] == [first["id"]]
    assert len(client.get("/api/memories").json()) == 2
```

- [ ] **Step 2: Run API tests to verify RED**

Run:

```powershell
python -m pytest backend/tests/test_api_memories.py -q
```

Expected: FAIL with 404 for `/api/memories` because route is not implemented.

- [ ] **Step 3: Add memory schemas**

Append to `backend/app/domain/schemas.py`:

```python
class CreateMemoryRequest(BaseModel):
    content: str = Field(min_length=1, max_length=1000)
    memory_type: str
    source_session_id: str | None = None
    importance: int = Field(default=3, ge=1, le=5)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateMemoryRequest(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=1000)
    memory_type: str | None = None
    importance: int | None = Field(default=None, ge=1, le=5)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] | None = None


class MemoryResponse(BaseModel):
    id: str
    content: str
    memory_type: str
    source: str
    source_session_id: str | None
    importance: int
    confidence: float
    status: str
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryMutationResponse(BaseModel):
    memory: MemoryResponse
    conflicts: list[MemoryResponse] = Field(default_factory=list)
```

- [ ] **Step 4: Add dependency and route**

Modify `backend/app/api/dependencies.py` imports:

```python
from app.repositories.memories import MemoryRepository
```

Add:

```python
def get_memory_repository(connection: sqlite3.Connection = Depends(get_connection)) -> MemoryRepository:
    return MemoryRepository(connection)
```

Create `backend/app/api/routes/memories.py`:

```python
from fastapi import APIRouter, Depends, Response, status

from app.api.dependencies import get_memory_repository, get_session_repository
from app.domain.models import MemorySource, MemoryStatus, MemoryType
from app.domain.schemas import CreateMemoryRequest, MemoryMutationResponse, MemoryResponse, UpdateMemoryRequest
from app.repositories.memories import MemoryRepository
from app.repositories.sessions import SessionRepository

router = APIRouter(prefix="/api/memories", tags=["memories"])


def _memory_response(memory: object) -> MemoryResponse:
    return MemoryResponse.model_validate(memory, from_attributes=True)


def _memory_type(value: str) -> MemoryType:
    return MemoryType(value)


@router.get("", response_model=list[MemoryResponse])
def list_memories(
    status_filter: str = "active",
    memories: MemoryRepository = Depends(get_memory_repository),
) -> list[MemoryResponse]:
    status_value = MemoryStatus(status_filter)
    return [_memory_response(memory) for memory in memories.list(status=status_value)]


@router.post("", response_model=MemoryMutationResponse, status_code=status.HTTP_201_CREATED)
def create_memory(
    request: CreateMemoryRequest,
    memories: MemoryRepository = Depends(get_memory_repository),
    sessions: SessionRepository = Depends(get_session_repository),
) -> MemoryMutationResponse:
    if request.source_session_id is not None:
        sessions.require(request.source_session_id)
    memory, conflicts = memories.create(
        content=request.content,
        memory_type=_memory_type(request.memory_type),
        source=MemorySource.MANUAL,
        source_session_id=request.source_session_id,
        importance=request.importance,
        confidence=request.confidence,
        metadata=request.metadata,
    )
    return MemoryMutationResponse(
        memory=_memory_response(memory),
        conflicts=[_memory_response(conflict) for conflict in conflicts],
    )


@router.patch("/{memory_id}", response_model=MemoryMutationResponse)
def update_memory(
    memory_id: str,
    request: UpdateMemoryRequest,
    memories: MemoryRepository = Depends(get_memory_repository),
) -> MemoryMutationResponse:
    memory, conflicts = memories.update(
        memory_id,
        content=request.content,
        memory_type=_memory_type(request.memory_type) if request.memory_type is not None else None,
        importance=request.importance,
        confidence=request.confidence,
        metadata=request.metadata,
    )
    return MemoryMutationResponse(
        memory=_memory_response(memory),
        conflicts=[_memory_response(conflict) for conflict in conflicts],
    )


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(
    memory_id: str,
    memories: MemoryRepository = Depends(get_memory_repository),
) -> Response:
    memories.require(memory_id)
    memories.archive(memory_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

Modify `backend/app/main.py` imports:

```python
from app.api.routes import audio, chat, health, memories, sessions
```

Include router:

```python
app.include_router(memories.router)
```

- [ ] **Step 5: Run API tests to verify GREEN**

Run:

```powershell
python -m pytest backend/tests/test_api_memories.py -q
```

Expected: PASS. If invalid enum currently returns 500 instead of 422, add a validator in the Pydantic request schemas that raises `ValueError` for invalid `memory_type`.

## Task 3: Memory Context Integration

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/services/context_builder.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/app/api/dependencies.py`
- Test: `backend/tests/test_config.py`
- Test: `backend/tests/test_context_builder.py`

- [ ] **Step 1: Write failing config/context tests**

Modify `backend/tests/test_context_builder.py` to include:

```python
from app.domain.models import MemorySource, MemoryType
from app.repositories.memories import MemoryRepository


def test_memory_context_is_caveated_and_separate(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        session = sessions.create("记忆上下文")
        messages.add(session.id, ChatRole.USER, "你好")
        memories.create(
            content="用户偏好中文回复。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )
        builder = ContextBuilder(messages, 12, memories=memories, memory_context_enabled=True, memory_context_limit=8)

        context = builder.build_context(session.id)

        assert context[0].role == ChatRole.SYSTEM
        assert "长期记忆记录" in context[0].content
        assert "不得描述为绝对事实" in context[0].content
        assert "用户偏好中文回复。" in context[0].content
        assert context[1].role == ChatRole.USER
        assert context[1].content == "你好"


def test_memory_context_can_be_disabled(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        session = sessions.create("禁用记忆")
        messages.add(session.id, ChatRole.USER, "你好")
        memories.create(
            content="用户偏好中文回复。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )
        builder = ContextBuilder(messages, 12, memories=memories, memory_context_enabled=False, memory_context_limit=8)

        context = builder.build_context(session.id)

        assert [message.content for message in context] == ["你好"]
```

Add to `backend/tests/test_config.py`:

```python
def test_memory_context_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_CONTEXT_ENABLED", "false")
    monkeypatch.setenv("MEMORY_CONTEXT_LIMIT", "5")

    settings = load_settings()

    assert settings.memory_context_enabled is False
    assert settings.memory_context_limit == 5
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
python -m pytest backend/tests/test_context_builder.py backend/tests/test_config.py -q
```

Expected: FAIL because `ContextBuilder.build_context` and memory config do not exist.

- [ ] **Step 3: Add memory config**

Modify `backend/app/core/config.py`:

Add to `Settings`:

```python
memory_context_enabled: bool = True
memory_context_limit: int = 8
```

Add to `redacted()`:

```python
"memory_context_enabled": self.memory_context_enabled,
"memory_context_limit": self.memory_context_limit,
```

Add to `load_settings()` return:

```python
memory_context_enabled=_get_bool_env("MEMORY_CONTEXT_ENABLED", True),
memory_context_limit=_get_positive_int_env("MEMORY_CONTEXT_LIMIT", 8),
```

- [ ] **Step 4: Update ContextBuilder**

Replace `backend/app/services/context_builder.py` with:

```python
from app.domain.models import ChatRole, Memory
from app.providers.base import LLMMessage
from app.repositories.memories import MemoryRepository
from app.repositories.messages import MessageRepository


class ContextBuilder:
    def __init__(
        self,
        messages: MessageRepository,
        max_messages: int,
        *,
        memories: MemoryRepository | None = None,
        memory_context_enabled: bool = True,
        memory_context_limit: int = 8,
    ) -> None:
        self._messages = messages
        self._max_messages = max_messages
        self._memories = memories
        self._memory_context_enabled = memory_context_enabled
        self._memory_context_limit = memory_context_limit

    def build_recent_context(self, session_id: str) -> list[LLMMessage]:
        recent_messages = self._messages.list_recent(session_id, self._max_messages)
        return [
            LLMMessage(role=message.role, content=message.content)
            for message in recent_messages
            if message.role in {ChatRole.USER, ChatRole.ASSISTANT}
        ]

    def build_memory_context(self) -> list[LLMMessage]:
        if not self._memory_context_enabled or self._memories is None:
            return []
        memories = self._memories.list_for_context(self._memory_context_limit)
        if not memories:
            return []
        lines = [
            "以下是用户可查看、可修改、可删除的长期记忆记录，仅作为回复时的参考上下文；",
            "它们可能过时或不完整，不得描述为绝对事实，也不得声称你具有真实人类记忆。",
        ]
        lines.extend(self._format_memory(memory) for memory in memories)
        return [LLMMessage(role=ChatRole.SYSTEM, content="\n".join(lines))]

    def build_context(self, session_id: str) -> list[LLMMessage]:
        return [*self.build_memory_context(), *self.build_recent_context(session_id)]

    def _format_memory(self, memory: Memory) -> str:
        return (
            f"- [{memory.memory_type.value} | importance {memory.importance} | "
            f"confidence {memory.confidence:.2f}] {memory.content}"
        )
```

- [ ] **Step 5: Wire ChatService and dependency**

Modify `backend/app/api/dependencies.py` `get_chat_service` signature to include memories:

```python
memories: MemoryRepository = Depends(get_memory_repository),
```

Build context builder as:

```python
context_builder = ContextBuilder(
    messages,
    settings.recent_context_messages,
    memories=memories,
    memory_context_enabled=settings.memory_context_enabled,
    memory_context_limit=settings.memory_context_limit,
)
```

Modify `backend/app/services/chat_service.py`:

```python
context = self._context_builder.build_context(session_id)
```

instead of `build_recent_context`.

- [ ] **Step 6: Run context/config tests to verify GREEN**

Run:

```powershell
python -m pytest backend/tests/test_context_builder.py backend/tests/test_config.py -q
```

Expected: PASS.

## Task 4: Frontend Memory API Client

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/client.test.ts`

- [ ] **Step 1: Write failing API client tests**

Append to `frontend/src/api/client.test.ts`:

```typescript
it('creates and lists memories', async () => {
  const created = {
    memory: {
      id: 'm1',
      content: '用户偏好中文回复。',
      memory_type: 'preference',
      source: 'manual',
      source_session_id: null,
      importance: 3,
      confidence: 1,
      status: 'active',
      created_at: '2026-07-06T00:00:00Z',
      updated_at: '2026-07-06T00:00:00Z',
      metadata: {},
    },
    conflicts: [],
  };
  vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(created));

  await expect(apiClient.createMemory({ content: '用户偏好中文回复。', memory_type: 'preference' })).resolves.toEqual(created);
  expect(fetch).toHaveBeenCalledWith('/api/memories', expect.objectContaining({ method: 'POST' }));
});

it('deletes a memory', async () => {
  vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 204 }));

  await expect(apiClient.deleteMemory('m1')).resolves.toBeUndefined();
  expect(fetch).toHaveBeenCalledWith('/api/memories/m1', { method: 'DELETE' });
});
```

- [ ] **Step 2: Run client tests to verify RED**

Run:

```powershell
npm --prefix frontend test -- src/api/client.test.ts
```

Expected: FAIL because `createMemory` and `deleteMemory` do not exist.

- [ ] **Step 3: Add memory frontend types**

Append to `frontend/src/api/types.ts`:

```typescript
export type MemoryType = 'user_fact' | 'preference' | 'long_term_goal' | 'important_event' | 'relationship_event' | 'other';
export type MemoryStatus = 'active' | 'archived';

export interface MemoryRecord {
  id: string;
  content: string;
  memory_type: MemoryType;
  source: 'manual';
  source_session_id: string | null;
  importance: number;
  confidence: number;
  status: MemoryStatus;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface CreateMemoryRequest {
  content: string;
  memory_type: MemoryType;
  source_session_id?: string | null;
  importance?: number;
  confidence?: number;
  metadata?: Record<string, unknown>;
}

export interface UpdateMemoryRequest {
  content?: string;
  memory_type?: MemoryType;
  importance?: number;
  confidence?: number;
  metadata?: Record<string, unknown>;
}

export interface MemoryMutationResponse {
  memory: MemoryRecord;
  conflicts: MemoryRecord[];
}
```

- [ ] **Step 4: Add apiClient methods**

Modify `frontend/src/api/client.ts` type import to include the new memory types.

Add methods to `apiClient`:

```typescript
listMemories(): Promise<MemoryRecord[]> {
  return requestJson<MemoryRecord[]>('/api/memories');
},

createMemory(request: CreateMemoryRequest): Promise<MemoryMutationResponse> {
  return requestJson<MemoryMutationResponse>('/api/memories', {
    method: 'POST',
    body: JSON.stringify(request),
  });
},

updateMemory(memoryId: string, request: UpdateMemoryRequest): Promise<MemoryMutationResponse> {
  return requestJson<MemoryMutationResponse>(`/api/memories/${memoryId}`, {
    method: 'PATCH',
    body: JSON.stringify(request),
  });
},

deleteMemory(memoryId: string): Promise<void> {
  return requestJson<void>(`/api/memories/${memoryId}`, { method: 'DELETE' });
},
```

- [ ] **Step 5: Run client tests to verify GREEN**

Run:

```powershell
npm --prefix frontend test -- src/api/client.test.ts
```

Expected: PASS.

## Task 5: MemoryPanel UI and App Wiring

**Files:**
- Create: `frontend/src/components/MemoryPanel.tsx`
- Create: `frontend/src/components/MemoryPanel.test.tsx`
- Modify: `frontend/src/components/ChatLayout.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write failing MemoryPanel tests**

Create `frontend/src/components/MemoryPanel.test.tsx`:

```typescript
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MemoryPanel } from './MemoryPanel';
import type { MemoryRecord } from '../api/types';

const memory: MemoryRecord = {
  id: 'm1',
  content: '用户偏好中文回复。',
  memory_type: 'preference',
  source: 'manual',
  source_session_id: null,
  importance: 3,
  confidence: 1,
  status: 'active',
  created_at: '2026-07-06T00:00:00Z',
  updated_at: '2026-07-06T00:00:00Z',
  metadata: {},
};

describe('MemoryPanel', () => {
  it('renders boundary helper and empty state', () => {
    render(<MemoryPanel memories={[]} loading={false} error={null} conflicts={[]} onCreate={vi.fn()} onUpdate={vi.fn()} onDelete={vi.fn()} />);

    expect(screen.getByText('长期记忆')).toBeInTheDocument();
    expect(screen.getByText(/聊天记录不会自动变成长期记忆/)).toBeInTheDocument();
    expect(screen.getByText('暂无长期记忆。')).toBeInTheDocument();
  });

  it('submits a new memory', async () => {
    const onCreate = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<MemoryPanel memories={[]} loading={false} error={null} conflicts={[]} onCreate={onCreate} onUpdate={vi.fn()} onDelete={vi.fn()} />);

    await user.type(screen.getByLabelText('记忆内容'), '用户偏好中文回复。');
    await user.selectOptions(screen.getByLabelText('记忆类型'), 'preference');
    await user.click(screen.getByRole('button', { name: '保存记忆' }));

    expect(onCreate).toHaveBeenCalledWith({
      content: '用户偏好中文回复。',
      memory_type: 'preference',
      importance: 3,
      confidence: 1,
    });
  });

  it('renders memories, conflicts, and delete action', async () => {
    const onDelete = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<MemoryPanel memories={[memory]} loading={false} error={null} conflicts={[memory]} onCreate={vi.fn()} onUpdate={vi.fn()} onDelete={onDelete} />);

    expect(screen.getByText('用户偏好中文回复。')).toBeInTheDocument();
    expect(screen.getByText(/发现相似记忆/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '删除记忆' }));
    expect(onDelete).toHaveBeenCalledWith('m1');
  });
});
```

- [ ] **Step 2: Run panel tests to verify RED**

Run:

```powershell
npm --prefix frontend test -- src/components/MemoryPanel.test.tsx
```

Expected: FAIL because `MemoryPanel.tsx` does not exist.

- [ ] **Step 3: Implement MemoryPanel**

Create `frontend/src/components/MemoryPanel.tsx`:

```tsx
import { useState } from 'react';
import type { CreateMemoryRequest, MemoryRecord, MemoryType, UpdateMemoryRequest } from '../api/types';

const MEMORY_TYPE_OPTIONS: Array<{ value: MemoryType; label: string }> = [
  { value: 'user_fact', label: '用户事实' },
  { value: 'preference', label: '偏好' },
  { value: 'long_term_goal', label: '长期目标' },
  { value: 'important_event', label: '重要事件' },
  { value: 'relationship_event', label: '关系事件' },
  { value: 'other', label: '其他' },
];

interface MemoryPanelProps {
  memories: MemoryRecord[];
  loading: boolean;
  error: string | null;
  conflicts: MemoryRecord[];
  onCreate: (request: CreateMemoryRequest) => Promise<void>;
  onUpdate: (memoryId: string, request: UpdateMemoryRequest) => Promise<void>;
  onDelete: (memoryId: string) => Promise<void>;
}

export function MemoryPanel({ memories, loading, error, conflicts, onCreate, onUpdate, onDelete }: MemoryPanelProps) {
  const [content, setContent] = useState('');
  const [memoryType, setMemoryType] = useState<MemoryType>('preference');

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const cleanContent = content.trim();
    if (!cleanContent) return;
    await onCreate({ content: cleanContent, memory_type: memoryType, importance: 3, confidence: 1 });
    setContent('');
    setMemoryType('preference');
  }

  return (
    <section className="memory-panel" aria-label="长期记忆">
      <h2>长期记忆</h2>
      <p className="memory-panel__hint">只保存你明确创建或确认的内容；聊天记录不会自动变成长期记忆。</p>
      {error ? <p role="alert" className="memory-panel__error">{error}</p> : null}
      {loading ? <p>记忆加载中……</p> : null}
      {conflicts.length > 0 ? <p className="memory-panel__warning">发现相似记忆，请确认是否需要保留多条。</p> : null}
      <form className="memory-panel__form" onSubmit={handleSubmit}>
        <label>
          记忆内容
          <textarea value={content} onChange={(event) => setContent(event.target.value)} maxLength={1000} />
        </label>
        <label>
          记忆类型
          <select value={memoryType} onChange={(event) => setMemoryType(event.target.value as MemoryType)}>
            {MEMORY_TYPE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
        <button type="submit" disabled={!content.trim()}>保存记忆</button>
      </form>
      {memories.length === 0 ? <p>暂无长期记忆。</p> : null}
      <ul className="memory-panel__list">
        {memories.map((memory) => (
          <li key={memory.id} className="memory-panel__item">
            <p>{memory.content}</p>
            <small>{memory.memory_type} · importance {memory.importance} · confidence {memory.confidence.toFixed(2)}</small>
            <button type="button" onClick={() => void onDelete(memory.id)}>删除记忆</button>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

- [ ] **Step 4: Run panel tests to verify GREEN**

Run:

```powershell
npm --prefix frontend test -- src/components/MemoryPanel.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Wire App and ChatLayout**

Modify `ChatLayoutProps` to include memory props:

```typescript
memories: MemoryRecord[];
memoryLoading: boolean;
memoryError: string | null;
memoryConflicts: MemoryRecord[];
onCreateMemory: (request: CreateMemoryRequest) => Promise<void>;
onUpdateMemory: (memoryId: string, request: UpdateMemoryRequest) => Promise<void>;
onDeleteMemory: (memoryId: string) => Promise<void>;
```

Import `MemoryPanel` and render it under `SessionList`:

```tsx
<div className="sidebar-tools">
  <MemoryPanel
    memories={memories}
    loading={memoryLoading}
    error={memoryError}
    conflicts={memoryConflicts}
    onCreate={onCreateMemory}
    onUpdate={onUpdateMemory}
    onDelete={onDeleteMemory}
  />
</div>
```

Modify `App.tsx`:

```typescript
const [memories, setMemories] = useState<MemoryRecord[]>([]);
const [memoryLoading, setMemoryLoading] = useState(false);
const [memoryError, setMemoryError] = useState<string | null>(null);
const [memoryConflicts, setMemoryConflicts] = useState<MemoryRecord[]>([]);
```

Add handlers:

```typescript
async function loadMemories() {
  setMemoryLoading(true);
  try {
    setMemories(await apiClient.listMemories());
    setMemoryError(null);
  } catch (caught) {
    setMemoryError(errorMessage(caught));
  } finally {
    setMemoryLoading(false);
  }
}

async function handleCreateMemory(request: CreateMemoryRequest) {
  const response = await apiClient.createMemory(request);
  setMemoryConflicts(response.conflicts);
  await loadMemories();
}

async function handleUpdateMemory(memoryId: string, request: UpdateMemoryRequest) {
  const response = await apiClient.updateMemory(memoryId, request);
  setMemoryConflicts(response.conflicts);
  await loadMemories();
}

async function handleDeleteMemory(memoryId: string) {
  await apiClient.deleteMemory(memoryId);
  setMemoryConflicts([]);
  await loadMemories();
}
```

Call `void loadMemories()` in the initial `useEffect` after `loadSessions()`.

Pass memory props into `ChatLayout`.

- [ ] **Step 6: Add minimal styles**

Append to `frontend/src/styles.css`:

```css
.sidebar-tools {
  padding: 0.75rem;
}

.memory-panel {
  border-top: 1px solid #d7d7d7;
  margin-top: 0.75rem;
  padding-top: 0.75rem;
}

.memory-panel h2 {
  font-size: 1rem;
  margin: 0 0 0.5rem;
}

.memory-panel__hint,
.memory-panel small {
  color: #666;
  font-size: 0.85rem;
}

.memory-panel__form {
  display: grid;
  gap: 0.5rem;
}

.memory-panel__form textarea,
.memory-panel__form select {
  width: 100%;
}

.memory-panel__list {
  list-style: none;
  padding: 0;
}

.memory-panel__item {
  border: 1px solid #e2e2e2;
  border-radius: 0.5rem;
  margin-top: 0.5rem;
  padding: 0.5rem;
}

.memory-panel__error {
  color: #b00020;
}

.memory-panel__warning {
  color: #8a5a00;
}
```

- [ ] **Step 7: Run focused frontend tests**

Run:

```powershell
npm --prefix frontend test -- src/components/MemoryPanel.test.tsx src/App.test.tsx
```

Expected: PASS.

## Task 6: E2E, Docs, and Final Validation

**Files:**
- Create: `frontend/e2e/memories.spec.ts`
- Create: `docs/stage3-memory-foundation.md`
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: Write E2E test**

Create `frontend/e2e/memories.spec.ts`:

```typescript
import { test, expect } from '@playwright/test';

test('creates a manual memory and text chat still works', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '新建会话' }).click();
  await page.getByLabel('记忆内容').fill('用户偏好中文回复。');
  await page.getByLabel('记忆类型').selectOption('preference');
  await page.getByRole('button', { name: '保存记忆' }).click();

  await expect(page.getByText('用户偏好中文回复。')).toBeVisible();

  await page.getByPlaceholder('输入消息').fill('你好');
  await page.getByRole('button', { name: '发送' }).click();

  await expect(page.getByText(/Fake/)).toBeVisible();
});
```

Adjust selectors only if existing labels differ; keep the test intent unchanged.

- [ ] **Step 2: Run E2E RED/GREEN as applicable**

Run after implementation wiring:

```powershell
npm --prefix frontend run test:e2e -- memories.spec.ts
```

Expected: PASS.

- [ ] **Step 3: Run full validation**

Run:

```powershell
python -m pytest backend/tests
npm --prefix frontend test -- --run
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

Expected: all PASS.

- [ ] **Step 4: Write evidence doc**

Create `docs/stage3-memory-foundation.md`:

```markdown
# Stage 3 Memory Foundation Evidence

Status: COMPLETED on 2026-07-06.

## Scope

This slice implements manual long-term memory CRUD, independent SQLite storage, conflict visibility, optional caveated chat-context injection, and a minimal React memory panel.

It does not implement automatic memory extraction, vector search, session summaries, or Stage 4 emotion state.

## Implemented behavior

- Users can create, view, and delete/archive active long-term memories.
- Each memory has source, timestamps, type, importance, confidence, status, and metadata.
- Memories are stored in a dedicated `memories` table, separate from chat messages.
- Duplicate same-type content is returned as a conflict and does not silently overwrite existing memories.
- Active memories can be inserted into chat context as a separate caveated system message.
- The UI states that chat history does not automatically become long-term memory.

## Validation

| Command | Result |
|---|---|
| `python -m pytest backend/tests` | PASS |
| `npm --prefix frontend test -- --run` | PASS |
| `npm --prefix frontend run typecheck` | PASS |
| `npm --prefix frontend run build` | PASS |
| `npm --prefix frontend run test:e2e` | PASS |

## Limitations

- No automatic extraction from chat.
- No semantic contradiction detection.
- No embedding/vector retrieval.
- No emotion or relationship-state system.
```

Replace PASS rows with exact observed counts.

- [ ] **Step 5: Update CLAUDE.md and README**

Only after full validation passes:

- In `CLAUDE.md`, mark Stage 3 memory foundation first slice completed and keep Stage 4 unstarted.
- In `README.md`, add a Stage 3 memory section documenting manual CRUD and the boundary that chat history is not automatically saved as memory.

- [ ] **Step 6: Final status report**

Use the project-required report format:

```text
完成内容：
修改文件：
验证命令与结果：
未完成或受限部分：
是否改变当前阶段：否/是（附验收证据）
下一项建议任务：
```

## Self-Review

- Spec coverage: The plan covers data model, separate storage, CRUD API, conflict visibility, caveated context retrieval, UI, tests, docs, and Stage 4 exclusion.
- Placeholder scan: No TBD/TODO/fill-later placeholders remain.
- Type consistency: Backend uses `MemoryType`, `MemorySource`, `MemoryStatus`, and frontend uses matching string literal union values.
- Scope check: This is one implementation slice. Automatic extraction, semantic contradiction detection, embeddings, summaries, and emotion state are explicitly deferred.
