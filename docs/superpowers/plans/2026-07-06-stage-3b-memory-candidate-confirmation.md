# Stage 3B Memory Candidate Confirmation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Stage 3 long-term-memory candidate confirmation loop: explicit user statements can create pending memory candidates, and only user-confirmed candidates become active long-term memories.

**Architecture:** Extend the existing `memories` table and `MemoryRepository` with `pending` and `dismissed` statuses plus a `candidate` source, using a minimal SQLite table rebuild migration for existing Stage 3A databases. Add a deterministic heuristic `MemoryCandidateService` that runs after successful chat replies and creates pending candidates without affecting chat success. Extend the existing memory API and React memory panel so users can confirm or dismiss candidates.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, SQLite, pytest, React, TypeScript, Vite, Vitest, Playwright.

---

## Stage boundary

This plan stays inside Stage 3: long-term memory. Do not implement Stage 4 emotional state. Do not add mood, trust, concern, distance, irritation, formality, affect decay, relationship scores, or expression strategy state. Do not backfill old chat history into memory. Do not add vector retrieval or embeddings in this slice.

## Files to create or modify

### Backend

- Modify: `backend/app/domain/models.py`
  - Add `MemorySource.CANDIDATE`, `MemoryStatus.PENDING`, and `MemoryStatus.DISMISSED`.

- Modify: `backend/app/domain/schemas.py`
  - Add candidate lifecycle response/request shapes only if needed by routes. Existing `MemoryResponse` and `MemoryMutationResponse` should remain the main response types.

- Modify: `backend/app/repositories/sqlite.py`
  - Extend schema CHECK constraints for new memory source/status values.
  - Add a focused migration that rebuilds `memories` only when the existing table does not allow new values.

- Modify: `backend/app/repositories/memories.py`
  - Add pending candidate creation, confirmation, dismissal, status-aware conflict lookup, and metadata timestamp helpers.

- Create: `backend/app/services/memory_candidate_service.py`
  - Implement deterministic heuristic candidate extraction from explicit user statements.
  - Keep service independent from routes and UI.

- Modify: `backend/app/services/chat_service.py`
  - Call candidate service after assistant reply persistence.
  - Catch candidate-service failures so chat still succeeds.

- Modify: `backend/app/api/dependencies.py`
  - Construct and inject `MemoryCandidateService` into `ChatService`.

- Modify: `backend/app/api/routes/memories.py`
  - Add `POST /api/memories/{memory_id}/confirm`.
  - Add `POST /api/memories/{memory_id}/dismiss`.
  - Keep existing CRUD routes compatible.

- Modify: `backend/app/core/config.py`
  - Add `memory_candidates_enabled: bool` and `memory_candidate_provider: str`.
  - Load `MEMORY_CANDIDATES_ENABLED` and `MEMORY_CANDIDATE_PROVIDER`.
  - Validate only `heuristic` provider in this slice.
  - Add redacted settings output entries.

- Test: `backend/tests/test_repositories.py`
  - Add candidate lifecycle and migration coverage.

- Test: `backend/tests/test_api_memories.py`
  - Add pending list, confirm, dismiss, and invalid lifecycle tests.

- Create: `backend/tests/test_memory_candidate_service.py`
  - Test heuristic extraction and duplicate suppression.

- Modify: `backend/tests/test_context_builder.py`
  - Assert pending and dismissed candidates are excluded from memory context.

- Modify or create focused chat test if already present in repo:
  - Prefer modifying existing chat-service/API test file if one exists.
  - If no focused file exists, add candidate chat assertions to `backend/tests/test_api_memories.py` only if route setup remains clear; otherwise create `backend/tests/test_chat_memory_candidates.py`.

### Frontend

- Modify: `frontend/src/api/types.ts`
  - Extend `MemoryRecord.source` to include `candidate`.
  - Extend `MemoryStatus` to include `pending` and `dismissed`.

- Modify: `frontend/src/api/client.ts`
  - Add `listMemories(status?: MemoryStatus)` or `listMemoryCandidates()`.
  - Add `confirmMemoryCandidate(memoryId)`.
  - Add `dismissMemoryCandidate(memoryId)`.

- Modify: `frontend/src/api/client.test.ts`
  - Add tests for pending list, confirm, dismiss.

- Modify: `frontend/src/components/MemoryPanel.tsx`
  - Render pending candidates separately from active memories.
  - Add confirm/dismiss actions.

- Modify: `frontend/src/components/MemoryPanel.test.tsx`
  - Add rendering and action tests for candidates.

- Modify: `frontend/src/components/ChatLayout.tsx`
  - Pass candidate props through to `MemoryPanel`.

- Modify: `frontend/src/App.tsx`
  - Load pending candidates on startup.
  - Refresh candidates after chat send and voice-turn chat send.
  - Update state after confirm/dismiss.

- Modify: `frontend/src/App.test.tsx`
  - Add unit coverage for candidate startup loading, post-send refresh, and confirm/dismiss state updates.

- Modify: `frontend/e2e/memories.spec.ts`
  - Add candidate confirmation smoke.

### Documentation

- Create after verification: `docs/stage3b-memory-candidate-confirmation.md`
  - Record scope, behavior, validation commands, limitations, and proof that Stage 4 remains unimplemented.

- Modify after verification: `CLAUDE.md`
  - Update Stage 3 current state only after tests and smoke pass.

---

## Task 1: Backend model and SQLite migration

**Files:**
- Modify: `backend/app/domain/models.py:39-45`
- Modify: `backend/app/repositories/sqlite.py:29-49`
- Test: `backend/tests/test_repositories.py`

- [ ] **Step 1: Write failing enum and migration tests**

Add these tests to `backend/tests/test_repositories.py` after `test_create_list_get_and_archive_memory`:

```python
def test_create_pending_candidate_memory(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)

        candidate, conflicts = memories.create_candidate(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=0.7,
            metadata={"candidate_reason": "explicit_like_statement"},
        )

        assert conflicts == []
        assert candidate is not None
        assert candidate.content == "用户喜欢红茶。"
        assert candidate.source == MemorySource.CANDIDATE
        assert candidate.status == MemoryStatus.PENDING
        assert candidate.metadata["candidate_reason"] == "explicit_like_statement"
        assert memories.list(status=MemoryStatus.PENDING) == [candidate]
        assert memories.list_for_context(limit=8) == []
```

Add this migration test near the other persistence tests:

```python
def test_sqlite_migrates_stage3a_memory_constraints(database_url: str) -> None:
    from app.repositories.sqlite import connect, init_db

    connection = connect(database_url)
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE memories (
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
            updated_at TEXT NOT NULL
        );
        """
    )
    connection.commit()
    init_db(connection)

    memories = MemoryRepository(connection)
    candidate, conflicts = memories.create_candidate(
        content="用户喜欢红茶。",
        memory_type=MemoryType.PREFERENCE,
        source_session_id=None,
        importance=3,
        confidence=0.7,
        metadata={},
    )

    assert conflicts == []
    assert candidate is not None
    assert candidate.status == MemoryStatus.PENDING
    connection.close()
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest backend/tests/test_repositories.py::test_create_pending_candidate_memory backend/tests/test_repositories.py::test_sqlite_migrates_stage3a_memory_constraints -q
```

Expected: FAIL because `MemoryRepository.create_candidate`, `MemorySource.CANDIDATE`, and `MemoryStatus.PENDING` do not exist.

- [ ] **Step 3: Extend memory enums**

Modify `backend/app/domain/models.py`:

```python
class MemorySource(StrEnum):
    MANUAL = "manual"
    CANDIDATE = "candidate"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    PENDING = "pending"
    DISMISSED = "dismissed"
```

- [ ] **Step 4: Update SQLite schema and add migration helpers**

Modify `backend/app/repositories/sqlite.py`.

Replace the `source` and `status` CHECK lines inside `SCHEMA_SQL` with:

```sql
    source TEXT NOT NULL CHECK (source IN ('manual', 'candidate')),
```

and:

```sql
    status TEXT NOT NULL CHECK (status IN ('active', 'archived', 'pending', 'dismissed')),
```

Add these helper functions above `init_db`:

```python
def _table_sql(connection: sqlite3.Connection, table_name: str) -> str | None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return None if row is None else str(row["sql"])


def _memories_schema_needs_candidate_migration(connection: sqlite3.Connection) -> bool:
    sql = _table_sql(connection, "memories")
    if sql is None:
        return False
    return "'candidate'" not in sql or "'pending'" not in sql or "'dismissed'" not in sql


def _migrate_memories_candidate_constraints(connection: sqlite3.Connection) -> None:
    if not _memories_schema_needs_candidate_migration(connection):
        return

    connection.executescript(
        """
        ALTER TABLE memories RENAME TO memories_old;

        CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            memory_type TEXT NOT NULL CHECK (memory_type IN ('user_fact', 'preference', 'long_term_goal', 'important_event', 'relationship_event', 'other')),
            source TEXT NOT NULL CHECK (source IN ('manual', 'candidate')),
            source_session_id TEXT,
            importance INTEGER NOT NULL CHECK (importance >= 1 AND importance <= 5),
            confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
            status TEXT NOT NULL CHECK (status IN ('active', 'archived', 'pending', 'dismissed')),
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (source_session_id) REFERENCES sessions(id) ON DELETE SET NULL
        );

        INSERT INTO memories (
            id, content, memory_type, source, source_session_id,
            importance, confidence, status, metadata_json, created_at, updated_at
        )
        SELECT
            id, content, memory_type, source, source_session_id,
            importance, confidence, status, metadata_json, created_at, updated_at
        FROM memories_old;

        DROP TABLE memories_old;
        """
    )
```

Modify `init_db` so migration runs after baseline schema creation:

```python
def init_db(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)
    _migrate_memories_candidate_constraints(connection)
    connection.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_memories_status_importance_updated
        ON memories(status, importance DESC, updated_at DESC);

        CREATE INDEX IF NOT EXISTS idx_memories_type_status
        ON memories(memory_type, status);
        """
    )
    connection.commit()
```

- [ ] **Step 5: Run tests and confirm the remaining repository method failure**

Run:

```bash
python -m pytest backend/tests/test_repositories.py::test_create_pending_candidate_memory backend/tests/test_repositories.py::test_sqlite_migrates_stage3a_memory_constraints -q
```

Expected: FAIL only because `MemoryRepository.create_candidate` does not exist.

- [ ] **Step 6: Commit checkpoint if commits are explicitly authorized**

Run only if the user has explicitly authorized commits in this session:

```bash
git add backend/app/domain/models.py backend/app/repositories/sqlite.py backend/tests/test_repositories.py
git commit -m "feat: prepare memory candidate storage"
```

Expected: commit succeeds. If commits are not authorized, skip this checkpoint and mention it in the final report.

---

## Task 2: Repository candidate lifecycle

**Files:**
- Modify: `backend/app/repositories/memories.py`
- Test: `backend/tests/test_repositories.py`

- [ ] **Step 1: Write failing lifecycle tests**

Add these tests to `backend/tests/test_repositories.py` after `test_create_pending_candidate_memory`:

```python
def test_confirm_candidate_activates_memory_and_records_metadata(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        candidate, _ = memories.create_candidate(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=0.7,
            metadata={"candidate_reason": "explicit_like_statement"},
        )
        assert candidate is not None

        confirmed, conflicts = memories.confirm_candidate(candidate.id)

        assert conflicts == []
        assert confirmed.status == MemoryStatus.ACTIVE
        assert confirmed.source == MemorySource.CANDIDATE
        assert "confirmed_at" in confirmed.metadata
        assert memories.list(status=MemoryStatus.PENDING) == []
        assert [memory.id for memory in memories.list_for_context(limit=8)] == [candidate.id]


def test_dismiss_candidate_excludes_it_from_pending_and_context(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        candidate, _ = memories.create_candidate(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=0.7,
            metadata={},
        )
        assert candidate is not None

        dismissed = memories.dismiss_candidate(candidate.id)

        assert dismissed.status == MemoryStatus.DISMISSED
        assert "dismissed_at" in dismissed.metadata
        assert memories.list(status=MemoryStatus.PENDING) == []
        assert memories.list_for_context(limit=8) == []


def test_candidate_duplicate_active_or_pending_is_not_created(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        active, _ = memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        duplicate_active, active_conflicts = memories.create_candidate(
            content=" 用户喜欢红茶。 ",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=0.7,
            metadata={},
        )

        assert duplicate_active is None
        assert [memory.id for memory in active_conflicts] == [active.id]

        pending, _ = memories.create_candidate(
            content="用户不喜欢咖啡。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=0.7,
            metadata={},
        )
        assert pending is not None

        duplicate_pending, pending_conflicts = memories.create_candidate(
            content="用户不喜欢咖啡。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=0.7,
            metadata={},
        )

        assert duplicate_pending is None
        assert [memory.id for memory in pending_conflicts] == [pending.id]
        assert len(memories.list(status=MemoryStatus.PENDING)) == 1
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest backend/tests/test_repositories.py::test_create_pending_candidate_memory backend/tests/test_repositories.py::test_confirm_candidate_activates_memory_and_records_metadata backend/tests/test_repositories.py::test_dismiss_candidate_excludes_it_from_pending_and_context backend/tests/test_repositories.py::test_candidate_duplicate_active_or_pending_is_not_created -q
```

Expected: FAIL because candidate lifecycle repository methods are missing.

- [ ] **Step 3: Add metadata timestamp and status-aware conflict helpers**

Modify `backend/app/repositories/memories.py`.

Add this helper near `_normalize_content`:

```python
def _metadata_with_timestamp(metadata: dict[str, Any], key: str, value: datetime) -> dict[str, Any]:
    next_metadata = dict(metadata)
    next_metadata[key] = _to_iso(value)
    return next_metadata
```

Replace `find_conflicts` with a status-aware implementation:

```python
    def find_conflicts(
        self,
        content: str,
        memory_type: MemoryType,
        exclude_id: str | None = None,
        statuses: tuple[MemoryStatus, ...] = (MemoryStatus.ACTIVE,),
    ) -> list[Memory]:
        normalized = _normalize_content(content)
        conflicts: list[Memory] = []
        for status in statuses:
            conflicts.extend(self.list(status=status))
        return [
            memory
            for memory in conflicts
            if memory.memory_type == memory_type
            and memory.id != exclude_id
            and _normalize_content(memory.content) == normalized
        ]
```

Confirm the existing `create` and `update` calls still work because the new `statuses` parameter defaults to active only.

- [ ] **Step 4: Implement candidate lifecycle methods**

Add these methods to `MemoryRepository` before `archive`:

```python
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
        return memory, []

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
```

- [ ] **Step 5: Run repository lifecycle tests**

Run:

```bash
python -m pytest backend/tests/test_repositories.py -q
```

Expected: PASS for all repository tests.

- [ ] **Step 6: Commit checkpoint if commits are explicitly authorized**

Run only if the user has explicitly authorized commits in this session:

```bash
git add backend/app/repositories/memories.py backend/tests/test_repositories.py
git commit -m "feat: add memory candidate lifecycle"
```

Expected: commit succeeds. If commits are not authorized, skip this checkpoint and mention it in the final report.

---

## Task 3: Candidate service with heuristic extraction

**Files:**
- Create: `backend/app/services/memory_candidate_service.py`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_memory_candidate_service.py`
- Test: `backend/tests/test_config.py`

- [ ] **Step 1: Write failing service tests**

Create `backend/tests/test_memory_candidate_service.py`:

```python
from pathlib import Path

import pytest

from app.core.config import Settings
from app.domain.models import MemoryStatus, MemoryType
from app.repositories.memories import MemoryRepository
from app.repositories.sqlite import managed_connection
from app.services.memory_candidate_service import MemoryCandidateService


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'memory-candidates.db'}"


def test_heuristic_extracts_explicit_like_statement(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        service = MemoryCandidateService(memories, Settings(memory_candidates_enabled=True))

        created = service.create_candidates_from_user_text(
            session_id=None,
            user_text="我喜欢红茶。",
        )

        assert len(created) == 1
        assert created[0].content == "用户喜欢红茶。"
        assert created[0].memory_type == MemoryType.PREFERENCE
        assert created[0].status == MemoryStatus.PENDING
        assert created[0].importance == 3
        assert created[0].confidence == 0.7
        assert created[0].metadata["candidate_reason"] == "explicit_like_statement"
        assert created[0].metadata["extraction_provider"] == "heuristic"


def test_heuristic_extracts_goal_statement(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        service = MemoryCandidateService(memories, Settings(memory_candidates_enabled=True))

        created = service.create_candidates_from_user_text(
            session_id=None,
            user_text="我的目标是本地部署一个能实时交流的桌宠。",
        )

        assert len(created) == 1
        assert created[0].content == "用户的目标是本地部署一个能实时交流的桌宠。"
        assert created[0].memory_type == MemoryType.LONG_TERM_GOAL


def test_heuristic_ignores_vague_or_disabled_candidates(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        disabled = MemoryCandidateService(memories, Settings(memory_candidates_enabled=False))
        enabled = MemoryCandidateService(memories, Settings(memory_candidates_enabled=True))

        assert disabled.create_candidates_from_user_text(session_id=None, user_text="我喜欢红茶。") == []
        assert enabled.create_candidates_from_user_text(session_id=None, user_text="你好") == []
        assert enabled.create_candidates_from_user_text(session_id=None, user_text="我现在有点开心") == []


def test_heuristic_does_not_duplicate_existing_candidate(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        service = MemoryCandidateService(memories, Settings(memory_candidates_enabled=True))

        first = service.create_candidates_from_user_text(session_id=None, user_text="我喜欢红茶。")
        second = service.create_candidates_from_user_text(session_id=None, user_text="我喜欢红茶。")

        assert len(first) == 1
        assert second == []
        assert len(memories.list(status=MemoryStatus.PENDING)) == 1
```

- [ ] **Step 2: Write failing config tests**

Add to `backend/tests/test_config.py`:

```python
def test_memory_candidate_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_CANDIDATES_ENABLED", "false")
    monkeypatch.setenv("MEMORY_CANDIDATE_PROVIDER", "heuristic")

    settings = load_settings()

    assert settings.memory_candidates_enabled is False
    assert settings.memory_candidate_provider == "heuristic"


def test_rejects_unknown_memory_candidate_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_CANDIDATE_PROVIDER", "llm")

    with pytest.raises(ValueError, match="MEMORY_CANDIDATE_PROVIDER must be one of: heuristic"):
        load_settings()
```

If `pytest` or `load_settings` is not imported at the top of `test_config.py`, add the missing imports following the file's existing style.

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
python -m pytest backend/tests/test_memory_candidate_service.py backend/tests/test_config.py -q
```

Expected: FAIL because `MemoryCandidateService` and config fields do not exist.

- [ ] **Step 4: Add memory candidate settings**

Modify `backend/app/core/config.py`.

Add fields to `Settings` after `memory_context_limit`:

```python
    memory_candidates_enabled: bool = True
    memory_candidate_provider: str = "heuristic"
```

Add to `redacted()` after memory context entries:

```python
            "memory_candidates_enabled": self.memory_candidates_enabled,
            "memory_candidate_provider": self.memory_candidate_provider,
```

In `load_settings()`, before `return Settings(...)`, add:

```python
    memory_candidate_provider = _get_env("MEMORY_CANDIDATE_PROVIDER", "heuristic").lower()
    if memory_candidate_provider not in {"heuristic"}:
        raise ValueError("MEMORY_CANDIDATE_PROVIDER must be one of: heuristic")
```

In the `Settings(...)` construction, add:

```python
        memory_candidates_enabled=_get_bool_env("MEMORY_CANDIDATES_ENABLED", True),
        memory_candidate_provider=memory_candidate_provider,
```

- [ ] **Step 5: Implement heuristic candidate service**

Create `backend/app/services/memory_candidate_service.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import Settings
from app.domain.models import Memory, MemoryType
from app.repositories.memories import MemoryRepository


@dataclass(frozen=True)
class MemoryCandidateDraft:
    content: str
    memory_type: MemoryType
    candidate_reason: str


class MemoryCandidateService:
    def __init__(self, memories: MemoryRepository, settings: Settings) -> None:
        self._memories = memories
        self._settings = settings

    def create_candidates_from_user_text(self, *, session_id: str | None, user_text: str) -> list[Memory]:
        if not self._settings.memory_candidates_enabled:
            return []
        if self._settings.memory_candidate_provider != "heuristic":
            return []

        created: list[Memory] = []
        for draft in self._extract_heuristic_drafts(user_text):
            memory, _conflicts = self._memories.create_candidate(
                content=draft.content,
                memory_type=draft.memory_type,
                source_session_id=session_id,
                importance=3,
                confidence=0.7,
                metadata={
                    "candidate_reason": draft.candidate_reason,
                    "extraction_provider": "heuristic",
                },
            )
            if memory is not None:
                created.append(memory)
        return created

    def _extract_heuristic_drafts(self, user_text: str) -> list[MemoryCandidateDraft]:
        normalized = user_text.strip().replace("，", "。").replace("!", "。").replace("！", "。")
        if not normalized:
            return []

        patterns: list[tuple[re.Pattern[str], MemoryType, str, str]] = [
            (re.compile(r"(?:^|。)我喜欢([^。]{1,40})"), MemoryType.PREFERENCE, "用户喜欢{value}。", "explicit_like_statement"),
            (re.compile(r"(?:^|。)我不喜欢([^。]{1,40})"), MemoryType.PREFERENCE, "用户不喜欢{value}。", "explicit_dislike_statement"),
            (re.compile(r"(?:^|。)我的目标是([^。]{2,80})"), MemoryType.LONG_TERM_GOAL, "用户的目标是{value}。", "explicit_goal_statement"),
            (re.compile(r"(?:^|。)我正在准备([^。]{2,80})"), MemoryType.LONG_TERM_GOAL, "用户正在准备{value}。", "explicit_goal_preparation_statement"),
            (re.compile(r"(?:^|。)我住在([^。]{2,40})"), MemoryType.USER_FACT, "用户住在{value}。", "explicit_residence_statement"),
            (re.compile(r"(?:^|。)我的职业是([^。]{2,40})"), MemoryType.USER_FACT, "用户的职业是{value}。", "explicit_occupation_statement"),
        ]

        drafts: list[MemoryCandidateDraft] = []
        seen: set[tuple[MemoryType, str]] = set()
        for pattern, memory_type, template, reason in patterns:
            for match in pattern.finditer(normalized):
                value = self._clean_value(match.group(1))
                if not value:
                    continue
                content = template.format(value=value)
                key = (memory_type, content)
                if key in seen:
                    continue
                seen.add(key)
                drafts.append(MemoryCandidateDraft(content=content, memory_type=memory_type, candidate_reason=reason))
        return drafts

    def _clean_value(self, value: str) -> str:
        cleaned = value.strip(" 。.，,；;：:、\"'“”‘’")
        if len(cleaned) < 2:
            return ""
        blocked_fragments = {"现在", "刚才", "今天", "有点开心", "有点难过", "生气", "开心"}
        if cleaned in blocked_fragments:
            return ""
        return cleaned
```

- [ ] **Step 6: Run service and config tests**

Run:

```bash
python -m pytest backend/tests/test_memory_candidate_service.py backend/tests/test_config.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit checkpoint if commits are explicitly authorized**

Run only if the user has explicitly authorized commits in this session:

```bash
git add backend/app/core/config.py backend/app/services/memory_candidate_service.py backend/tests/test_config.py backend/tests/test_memory_candidate_service.py
git commit -m "feat: add heuristic memory candidate service"
```

Expected: commit succeeds. If commits are not authorized, skip this checkpoint and mention it in the final report.

---

## Task 4: Chat service integration

**Files:**
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/app/api/dependencies.py`
- Test: create `backend/tests/test_chat_memory_candidates.py` unless an existing chat API test file is a better fit after inspection

- [ ] **Step 1: Write failing chat integration tests**

Create `backend/tests/test_chat_memory_candidates.py`:

```python
from fastapi.testclient import TestClient


def test_chat_creates_pending_memory_candidate(client: TestClient) -> None:
    session = client.post("/api/sessions", json={"title": "候选记忆"}).json()

    response = client.post(
        f"/api/sessions/{session['id']}/messages",
        json={"content": "我喜欢红茶。"},
    )

    assert response.status_code == 200
    candidates_response = client.get("/api/memories", params={"status_filter": "pending"})
    assert candidates_response.status_code == 200
    candidates = candidates_response.json()
    assert len(candidates) == 1
    assert candidates[0]["content"] == "用户喜欢红茶。"
    assert candidates[0]["memory_type"] == "preference"
    assert candidates[0]["source"] == "candidate"
    assert candidates[0]["status"] == "pending"
    assert candidates[0]["source_session_id"] == session["id"]


def test_chat_skips_memory_candidates_when_disabled(client: TestClient, monkeypatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("MEMORY_CANDIDATES_ENABLED", "false")
    get_settings.cache_clear()
    disabled_client = TestClient(client.app)
    session = disabled_client.post("/api/sessions", json={"title": "候选关闭"}).json()

    response = disabled_client.post(
        f"/api/sessions/{session['id']}/messages",
        json={"content": "我喜欢红茶。"},
    )

    assert response.status_code == 200
    assert disabled_client.get("/api/memories", params={"status_filter": "pending"}).json() == []
    get_settings.cache_clear()
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest backend/tests/test_chat_memory_candidates.py -q
```

Expected: FAIL because `ChatService` does not create candidates yet.

- [ ] **Step 3: Modify ChatService constructor and send flow**

Modify `backend/app/services/chat_service.py`.

Add import:

```python
from app.services.memory_candidate_service import MemoryCandidateService
```

Update constructor signature:

```python
    def __init__(
        self,
        sessions: SessionRepository,
        messages: MessageRepository,
        context_builder: ContextBuilder,
        prompt_renderer: PromptRenderer,
        provider: LLMProvider,
        settings: Settings,
        memory_candidates: MemoryCandidateService | None = None,
    ) -> None:
```

Add assignment:

```python
        self._memory_candidates = memory_candidates
```

After assistant message persistence in `send_message`, add the non-fatal candidate hook:

```python
        self._messages.add(
            session_id,
            ChatRole.ASSISTANT,
            reply,
            assistant_metadata,
        )
        if self._memory_candidates is not None:
            try:
                self._memory_candidates.create_candidates_from_user_text(
                    session_id=session_id,
                    user_text=clean_text,
                )
            except Exception:
                # Candidate extraction must never break the chat path.
                pass
        return ChatReply(reply=reply, provider=response.provider, model=response.model)
```

- [ ] **Step 4: Inject MemoryCandidateService**

Modify `backend/app/api/dependencies.py`.

Add import:

```python
from app.services.memory_candidate_service import MemoryCandidateService
```

Add dependency function after `get_memory_repository`:

```python
def get_memory_candidate_service(
    settings: Settings = Depends(get_settings),
    memories: MemoryRepository = Depends(get_memory_repository),
) -> MemoryCandidateService:
    return MemoryCandidateService(memories, settings)
```

Update `get_chat_service` signature to include:

```python
    memory_candidates: MemoryCandidateService = Depends(get_memory_candidate_service),
```

Update the `ChatService(...)` construction:

```python
    return ChatService(
        sessions,
        messages,
        context_builder,
        prompt_renderer,
        provider,
        settings,
        memory_candidates,
    )
```

- [ ] **Step 5: Run chat integration tests**

Run:

```bash
python -m pytest backend/tests/test_chat_memory_candidates.py -q
```

Expected: PASS.

- [ ] **Step 6: Run focused backend regression**

Run:

```bash
python -m pytest backend/tests/test_memory_candidate_service.py backend/tests/test_repositories.py backend/tests/test_chat_memory_candidates.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit checkpoint if commits are explicitly authorized**

Run only if the user has explicitly authorized commits in this session:

```bash
git add backend/app/services/chat_service.py backend/app/api/dependencies.py backend/tests/test_chat_memory_candidates.py
git commit -m "feat: suggest memory candidates after chat"
```

Expected: commit succeeds. If commits are not authorized, skip this checkpoint and mention it in the final report.

---

## Task 5: Memory API candidate actions

**Files:**
- Modify: `backend/app/api/routes/memories.py`
- Test: `backend/tests/test_api_memories.py`

- [ ] **Step 1: Write failing API lifecycle tests**

Add to `backend/tests/test_api_memories.py`:

```python
def test_memory_api_lists_confirms_and_dismisses_candidates(client: TestClient) -> None:
    session = client.post("/api/sessions", json={"title": "候选 API"}).json()
    client.post(f"/api/sessions/{session['id']}/messages", json={"content": "我喜欢红茶。"})

    pending_response = client.get("/api/memories", params={"status_filter": "pending"})
    assert pending_response.status_code == 200
    pending = pending_response.json()
    assert len(pending) == 1
    candidate = pending[0]
    assert candidate["status"] == "pending"

    confirm_response = client.post(f"/api/memories/{candidate['id']}/confirm")
    assert confirm_response.status_code == 200
    confirm_body = confirm_response.json()
    assert confirm_body["conflicts"] == []
    confirmed = confirm_body["memory"]
    assert confirmed["status"] == "active"
    assert confirmed["source"] == "candidate"
    assert "confirmed_at" in confirmed["metadata"]
    assert client.get("/api/memories", params={"status_filter": "pending"}).json() == []
    assert [item["id"] for item in client.get("/api/memories").json()] == [candidate["id"]]

    client.post(f"/api/sessions/{session['id']}/messages", json={"content": "我不喜欢咖啡。"})
    next_candidate = client.get("/api/memories", params={"status_filter": "pending"}).json()[0]
    dismiss_response = client.post(f"/api/memories/{next_candidate['id']}/dismiss")
    assert dismiss_response.status_code == 200
    dismissed = dismiss_response.json()
    assert dismissed["status"] == "dismissed"
    assert "dismissed_at" in dismissed["metadata"]
    assert client.get("/api/memories", params={"status_filter": "pending"}).json() == []


def test_memory_api_rejects_confirming_active_memory(client: TestClient) -> None:
    created = client.post(
        "/api/memories",
        json={"content": "用户喜欢雪。", "memory_type": "preference", "importance": 3, "confidence": 1.0},
    ).json()["memory"]

    response = client.post(f"/api/memories/{created['id']}/confirm")

    assert response.status_code == 400
    assert response.json()["error"]["message"] == "只能确认待确认记忆。"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest backend/tests/test_api_memories.py::test_memory_api_lists_confirms_and_dismisses_candidates backend/tests/test_api_memories.py::test_memory_api_rejects_confirming_active_memory -q
```

Expected: FAIL because confirm and dismiss endpoints do not exist or lifecycle errors are not mapped.

- [ ] **Step 3: Add route handlers**

Modify `backend/app/api/routes/memories.py`.

Add import:

```python
from app.core.errors import ValidationAppError
```

Add handlers before the `delete_memory` route so fixed paths are not confused with `{memory_id}` delete logic:

```python
@router.post("/{memory_id}/confirm", response_model=MemoryMutationResponse)
def confirm_memory_candidate(
    memory_id: str,
    memories: MemoryRepository = Depends(get_memory_repository),
) -> MemoryMutationResponse:
    try:
        memory, conflicts = memories.confirm_candidate(memory_id)
    except ValueError as exc:
        raise ValidationAppError("只能确认待确认记忆。") from exc
    return MemoryMutationResponse(
        memory=_memory_response(memory),
        conflicts=[_memory_response(conflict) for conflict in conflicts],
    )


@router.post("/{memory_id}/dismiss", response_model=MemoryResponse)
def dismiss_memory_candidate(
    memory_id: str,
    memories: MemoryRepository = Depends(get_memory_repository),
) -> MemoryResponse:
    try:
        memory = memories.dismiss_candidate(memory_id)
    except ValueError as exc:
        raise ValidationAppError("只能忽略待确认记忆。") from exc
    return _memory_response(memory)
```

- [ ] **Step 4: Run API tests**

Run:

```bash
python -m pytest backend/tests/test_api_memories.py -q
```

Expected: PASS.

- [ ] **Step 5: Run focused backend regression**

Run:

```bash
python -m pytest backend/tests/test_api_memories.py backend/tests/test_chat_memory_candidates.py backend/tests/test_repositories.py backend/tests/test_memory_candidate_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit checkpoint if commits are explicitly authorized**

Run only if the user has explicitly authorized commits in this session:

```bash
git add backend/app/api/routes/memories.py backend/tests/test_api_memories.py
git commit -m "feat: add memory candidate API actions"
```

Expected: commit succeeds. If commits are not authorized, skip this checkpoint and mention it in the final report.

---

## Task 6: Context exclusion coverage

**Files:**
- Modify: `backend/tests/test_context_builder.py`
- Modify only if needed: `backend/app/services/context_builder.py`

- [ ] **Step 1: Write failing context test if current coverage does not include pending exclusion**

Add to `backend/tests/test_context_builder.py`:

```python
def test_memory_context_excludes_pending_and_dismissed_candidates(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        session = sessions.create("候选上下文")
        active, _ = memories.create(
            content="用户偏好中文回复。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )
        pending, _ = memories.create_candidate(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=session.id,
            importance=3,
            confidence=0.7,
            metadata={},
        )
        assert pending is not None
        dismissed, _ = memories.create_candidate(
            content="用户不喜欢咖啡。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=session.id,
            importance=3,
            confidence=0.7,
            metadata={},
        )
        assert dismissed is not None
        memories.dismiss_candidate(dismissed.id)

        builder = ContextBuilder(messages, 12, memories=memories, memory_context_enabled=True, memory_context_limit=8)
        context = builder.build_memory_context()

        assert len(context) == 1
        assert active.content in context[0].content
        assert "用户喜欢红茶。" not in context[0].content
        assert "用户不喜欢咖啡。" not in context[0].content
```

If `database_url`, `managed_connection`, `SessionRepository`, `MessageRepository`, `MemoryRepository`, `MemoryType`, `MemorySource`, or `ContextBuilder` are not imported in that file, add imports consistent with its existing style.

- [ ] **Step 2: Run test**

Run:

```bash
python -m pytest backend/tests/test_context_builder.py::test_memory_context_excludes_pending_and_dismissed_candidates -q
```

Expected: PASS if `list_for_context()` already filters active only. If it fails, inspect `ContextBuilder.build_memory_context()` and `MemoryRepository.list_for_context()`.

- [ ] **Step 3: Fix only if test fails**

If the test fails because `list_for_context()` includes non-active rows, modify `backend/app/repositories/memories.py` so the query includes:

```sql
WHERE status = ?
```

and binds:

```python
(MemoryStatus.ACTIVE.value, limit)
```

This is already the intended Stage 3A behavior, so no change should be needed if previous implementation is intact.

- [ ] **Step 4: Run context tests**

Run:

```bash
python -m pytest backend/tests/test_context_builder.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit checkpoint if commits are explicitly authorized**

Run only if the user has explicitly authorized commits in this session:

```bash
git add backend/tests/test_context_builder.py backend/app/services/context_builder.py backend/app/repositories/memories.py
git commit -m "test: cover candidate memory context exclusion"
```

Expected: commit succeeds if files changed. If commits are not authorized, skip this checkpoint and mention it in the final report.

---

## Task 7: Frontend API types and client

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Test: `frontend/src/api/client.test.ts`

- [ ] **Step 1: Write failing client tests**

Add to `frontend/src/api/client.test.ts`:

```typescript
  it('lists pending memory candidates', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }));

    await expect(apiClient.listMemories('pending')).resolves.toEqual([]);

    expect(fetch).toHaveBeenCalledWith('/api/memories?status_filter=pending', expect.objectContaining({ headers: expect.any(Object) }));
  });

  it('confirms and dismisses memory candidates', async () => {
    const confirmed = {
      memory: {
        id: 'm1',
        content: '用户喜欢红茶。',
        memory_type: 'preference',
        source: 'candidate',
        source_session_id: 's1',
        importance: 3,
        confidence: 0.7,
        status: 'active',
        created_at: '2026-07-06T00:00:00Z',
        updated_at: '2026-07-06T00:00:01Z',
        metadata: { confirmed_at: '2026-07-06T00:00:01Z' },
      },
      conflicts: [],
    };
    const dismissed = {
      id: 'm2',
      content: '用户不喜欢咖啡。',
      memory_type: 'preference',
      source: 'candidate',
      source_session_id: 's1',
      importance: 3,
      confidence: 0.7,
      status: 'dismissed',
      created_at: '2026-07-06T00:00:00Z',
      updated_at: '2026-07-06T00:00:01Z',
      metadata: { dismissed_at: '2026-07-06T00:00:01Z' },
    };
    vi.mocked(fetch)
      .mockResolvedValueOnce(new Response(JSON.stringify(confirmed), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(dismissed), { status: 200 }));

    await expect(apiClient.confirmMemoryCandidate('m1')).resolves.toEqual(confirmed);
    await expect(apiClient.dismissMemoryCandidate('m2')).resolves.toEqual(dismissed);

    expect(fetch).toHaveBeenCalledWith('/api/memories/m1/confirm', expect.objectContaining({ method: 'POST' }));
    expect(fetch).toHaveBeenCalledWith('/api/memories/m2/dismiss', expect.objectContaining({ method: 'POST' }));
  });
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
npm --prefix frontend test -- src/api/client.test.ts --run
```

Expected: FAIL because `listMemories` does not accept status and candidate methods do not exist.

- [ ] **Step 3: Extend frontend types**

Modify `frontend/src/api/types.ts`:

```typescript
export type MemoryStatus = 'active' | 'archived' | 'pending' | 'dismissed';
```

Change `MemoryRecord.source` to:

```typescript
  source: 'manual' | 'candidate';
```

- [ ] **Step 4: Extend API client**

Modify `frontend/src/api/client.ts`.

Include `MemoryStatus` in the type import from `./types`.

Replace `listMemories()` with:

```typescript
  listMemories(status: MemoryStatus = 'active'): Promise<MemoryRecord[]> {
    const suffix = status === 'active' ? '' : `?status_filter=${encodeURIComponent(status)}`;
    return requestJson<MemoryRecord[]>(`/api/memories${suffix}`);
  },
```

Add methods after `updateMemory`:

```typescript
  confirmMemoryCandidate(memoryId: string): Promise<MemoryMutationResponse> {
    return requestJson<MemoryMutationResponse>(`/api/memories/${memoryId}/confirm`, { method: 'POST' });
  },

  dismissMemoryCandidate(memoryId: string): Promise<MemoryRecord> {
    return requestJson<MemoryRecord>(`/api/memories/${memoryId}/dismiss`, { method: 'POST' });
  },
```

- [ ] **Step 5: Run client tests**

Run:

```bash
npm --prefix frontend test -- src/api/client.test.ts --run
```

Expected: PASS.

- [ ] **Step 6: Commit checkpoint if commits are explicitly authorized**

Run only if the user has explicitly authorized commits in this session:

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/api/client.test.ts
git commit -m "feat: add memory candidate client API"
```

Expected: commit succeeds. If commits are not authorized, skip this checkpoint and mention it in the final report.

---

## Task 8: MemoryPanel candidate UI

**Files:**
- Modify: `frontend/src/components/MemoryPanel.tsx`
- Test: `frontend/src/components/MemoryPanel.test.tsx`

- [ ] **Step 1: Write failing MemoryPanel tests**

Modify render calls in existing tests to pass new props. Then add:

```typescript
const candidate: MemoryRecord = {
  id: 'c1',
  content: '用户喜欢红茶。',
  memory_type: 'preference',
  source: 'candidate',
  source_session_id: 's1',
  importance: 3,
  confidence: 0.7,
  status: 'pending',
  created_at: '2026-07-06T00:00:00Z',
  updated_at: '2026-07-06T00:00:00Z',
  metadata: { candidate_reason: 'explicit_like_statement' },
};
```

Add test:

```typescript
  it('renders pending candidates and candidate actions', async () => {
    const onConfirmCandidate = vi.fn().mockResolvedValue(undefined);
    const onDismissCandidate = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <MemoryPanel
        memories={[memory]}
        candidates={[candidate]}
        loading={false}
        error={null}
        conflicts={[]}
        onCreate={vi.fn()}
        onUpdate={vi.fn()}
        onDelete={vi.fn()}
        onConfirmCandidate={onConfirmCandidate}
        onDismissCandidate={onDismissCandidate}
      />,
    );

    expect(screen.getByText('待确认记忆')).toBeInTheDocument();
    expect(screen.getByText(/确认前不会用于对话/)).toBeInTheDocument();
    expect(screen.getByText('用户喜欢红茶。')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '保存为长期记忆' }));
    expect(onConfirmCandidate).toHaveBeenCalledWith('c1');

    await user.click(screen.getByRole('button', { name: '忽略' }));
    expect(onDismissCandidate).toHaveBeenCalledWith('c1');
  });
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
npm --prefix frontend test -- src/components/MemoryPanel.test.tsx --run
```

Expected: FAIL because `MemoryPanel` lacks candidate props and UI.

- [ ] **Step 3: Extend MemoryPanel props**

Modify `frontend/src/components/MemoryPanel.tsx` props:

```typescript
interface MemoryPanelProps {
  memories: MemoryRecord[];
  candidates: MemoryRecord[];
  loading: boolean;
  error: string | null;
  conflicts: MemoryRecord[];
  onCreate: (request: CreateMemoryRequest) => Promise<void>;
  onUpdate: (memoryId: string, request: UpdateMemoryRequest) => Promise<void>;
  onDelete: (memoryId: string) => Promise<void>;
  onConfirmCandidate: (memoryId: string) => Promise<void>;
  onDismissCandidate: (memoryId: string) => Promise<void>;
}
```

Update function signature:

```typescript
export function MemoryPanel({
  memories,
  candidates,
  loading,
  error,
  conflicts,
  onCreate,
  onDelete,
  onConfirmCandidate,
  onDismissCandidate,
}: MemoryPanelProps) {
```

- [ ] **Step 4: Render pending candidate section**

Add this block before the existing active memory list:

```tsx
      <section className="memory-panel__candidates" aria-label="待确认记忆">
        <h3>待确认记忆</h3>
        <p className="memory-panel__hint">以下是系统建议保存的长期记忆，确认前不会用于对话。</p>
        {candidates.length === 0 ? <p>暂无待确认记忆。</p> : null}
        <ul className="memory-panel__list">
          {candidates.map((candidate) => (
            <li key={candidate.id} className="memory-panel__item memory-panel__item--candidate">
              <p>{candidate.content}</p>
              <small>{candidate.memory_type} · importance {candidate.importance} · confidence {candidate.confidence.toFixed(2)}</small>
              <div className="memory-panel__actions">
                <button type="button" onClick={() => void onConfirmCandidate(candidate.id)}>保存为长期记忆</button>
                <button type="button" onClick={() => void onDismissCandidate(candidate.id)}>忽略</button>
              </div>
            </li>
          ))}
        </ul>
      </section>
```

Keep the existing active memory section unchanged except for any wrapper needed to keep headings valid.

- [ ] **Step 5: Update existing tests to pass new props**

For each existing render call in `MemoryPanel.test.tsx`, add:

```tsx
candidates={[]}
onConfirmCandidate={vi.fn()}
onDismissCandidate={vi.fn()}
```

- [ ] **Step 6: Run MemoryPanel tests**

Run:

```bash
npm --prefix frontend test -- src/components/MemoryPanel.test.tsx --run
```

Expected: PASS.

- [ ] **Step 7: Commit checkpoint if commits are explicitly authorized**

Run only if the user has explicitly authorized commits in this session:

```bash
git add frontend/src/components/MemoryPanel.tsx frontend/src/components/MemoryPanel.test.tsx
git commit -m "feat: render memory candidates"
```

Expected: commit succeeds. If commits are not authorized, skip this checkpoint and mention it in the final report.

---

## Task 9: App state integration

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/ChatLayout.tsx`
- Test: `frontend/src/App.test.tsx`

- [ ] **Step 1: Write failing App candidate tests**

Inspect existing `frontend/src/App.test.tsx` fetch mock helpers first. Add tests following existing style. The core expected assertions are:

```typescript
it('loads pending memory candidates on startup when memory loading is enabled', async () => {
  vi.stubEnv('VITE_ENABLE_MEMORY_LOAD_IN_TEST', '1');
  // Mock list sessions, list active memories, and list pending candidates in the order App calls them.
  // Active memories response: []
  // Pending candidates response: [{ id: 'c1', content: '用户喜欢红茶。', memory_type: 'preference', source: 'candidate', source_session_id: 's1', importance: 3, confidence: 0.7, status: 'pending', created_at: '2026-07-06T00:00:00Z', updated_at: '2026-07-06T00:00:00Z', metadata: {} }]
  // Assert screen shows '待确认记忆' and '用户喜欢红茶。'.
});
```

Replace the comment block with this concrete fetch mock if the file uses plain `fetch` mocks:

```typescript
vi.mocked(fetch)
  .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
  .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
  .mockResolvedValueOnce(new Response(JSON.stringify([candidate]), { status: 200 }));

render(<App />);

expect(await screen.findByText('用户喜欢红茶。')).toBeInTheDocument();
```

Add a second test for confirm action:

```typescript
it('confirms a pending memory candidate and moves it into active memories', async () => {
  vi.stubEnv('VITE_ENABLE_MEMORY_LOAD_IN_TEST', '1');
  const candidate = {
    id: 'c1',
    content: '用户喜欢红茶。',
    memory_type: 'preference',
    source: 'candidate',
    source_session_id: 's1',
    importance: 3,
    confidence: 0.7,
    status: 'pending',
    created_at: '2026-07-06T00:00:00Z',
    updated_at: '2026-07-06T00:00:00Z',
    metadata: {},
  };
  const confirmed = { ...candidate, status: 'active', metadata: { confirmed_at: '2026-07-06T00:00:01Z' } };
  vi.mocked(fetch)
    .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify([candidate]), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ memory: confirmed, conflicts: [] }), { status: 200 }));

  const user = userEvent.setup();
  render(<App />);
  await screen.findByText('用户喜欢红茶。');
  await user.click(screen.getByRole('button', { name: '保存为长期记忆' }));

  expect(fetch).toHaveBeenCalledWith('/api/memories/c1/confirm', expect.objectContaining({ method: 'POST' }));
});
```

Adapt only the setup style to match existing `App.test.tsx`; keep the assertions and mocked responses concrete.

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
npm --prefix frontend test -- src/App.test.tsx --run
```

Expected: FAIL because App does not load or act on pending candidates.

- [ ] **Step 3: Add App candidate state and loader**

Modify `frontend/src/App.tsx`.

Add state after memories:

```typescript
  const [memoryCandidates, setMemoryCandidates] = useState<MemoryRecord[]>([]);
```

Add loader:

```typescript
  async function loadMemoryCandidates() {
    setMemoryLoading(true);
    try {
      setMemoryCandidates(await apiClient.listMemories('pending'));
      setMemoryError(null);
    } catch (caught) {
      setMemoryError(errorMessage(caught));
    } finally {
      setMemoryLoading(false);
    }
  }
```

Modify startup effect:

```typescript
    if (import.meta.env.MODE !== 'test' || import.meta.env.VITE_ENABLE_MEMORY_LOAD_IN_TEST === '1') {
      void loadMemories();
      void loadMemoryCandidates();
    }
```

- [ ] **Step 4: Refresh candidates after chat sends**

In `handleSendMessage`, after updating sessions and messages, add:

```typescript
      void loadMemoryCandidates();
```

In `handleSendAndSpeakTranscript`, after setting updated sessions/messages and clearing pending transcript, add:

```typescript
      void loadMemoryCandidates();
```

- [ ] **Step 5: Add confirm and dismiss handlers**

Add to `App.tsx` near other memory handlers:

```typescript
  async function handleConfirmMemoryCandidate(memoryId: string) {
    setMemoryLoading(true);
    setMemoryError(null);
    try {
      const response = await apiClient.confirmMemoryCandidate(memoryId);
      setMemoryConflicts(response.conflicts);
      setMemoryCandidates((current) => current.filter((memory) => memory.id !== memoryId));
      setMemories((current) => [response.memory, ...current.filter((memory) => memory.id !== response.memory.id)]);
    } catch (caught) {
      setMemoryError(errorMessage(caught));
    } finally {
      setMemoryLoading(false);
    }
  }

  async function handleDismissMemoryCandidate(memoryId: string) {
    setMemoryLoading(true);
    setMemoryError(null);
    try {
      await apiClient.dismissMemoryCandidate(memoryId);
      setMemoryCandidates((current) => current.filter((memory) => memory.id !== memoryId));
    } catch (caught) {
      setMemoryError(errorMessage(caught));
    } finally {
      setMemoryLoading(false);
    }
  }
```

- [ ] **Step 6: Pass candidate props through ChatLayout**

Modify `frontend/src/components/ChatLayout.tsx` props:

```typescript
  memoryCandidates: MemoryRecord[];
  onConfirmMemoryCandidate: (memoryId: string) => Promise<void>;
  onDismissMemoryCandidate: (memoryId: string) => Promise<void>;
```

Destructure them in `ChatLayout(...)` and pass to `MemoryPanel`:

```tsx
          candidates={memoryCandidates}
          onConfirmCandidate={onConfirmMemoryCandidate}
          onDismissCandidate={onDismissMemoryCandidate}
```

Modify `App.tsx` `ChatLayout` call:

```tsx
      memoryCandidates={memoryCandidates}
      onConfirmMemoryCandidate={handleConfirmMemoryCandidate}
      onDismissMemoryCandidate={handleDismissMemoryCandidate}
```

- [ ] **Step 7: Run App tests**

Run:

```bash
npm --prefix frontend test -- src/App.test.tsx --run
```

Expected: PASS.

- [ ] **Step 8: Run focused frontend tests**

Run:

```bash
npm --prefix frontend test -- src/api/client.test.ts src/components/MemoryPanel.test.tsx src/App.test.tsx --run
```

Expected: PASS.

- [ ] **Step 9: Commit checkpoint if commits are explicitly authorized**

Run only if the user has explicitly authorized commits in this session:

```bash
git add frontend/src/App.tsx frontend/src/components/ChatLayout.tsx frontend/src/App.test.tsx
git commit -m "feat: wire memory candidates into app state"
```

Expected: commit succeeds. If commits are not authorized, skip this checkpoint and mention it in the final report.

---

## Task 10: E2E memory candidate smoke

**Files:**
- Modify: `frontend/e2e/memories.spec.ts`

- [ ] **Step 1: Add candidate confirmation smoke test**

Append to `frontend/e2e/memories.spec.ts`:

```typescript
test('suggests and confirms a memory candidate from chat', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '新建会话' }).click();
  await page.getByLabel('消息输入').fill('我喜欢红茶。');
  await page.getByRole('button', { name: '发送' }).click();

  await expect(page.getByText('用户喜欢红茶。')).toBeVisible();
  await expect(page.getByRole('heading', { name: '待确认记忆' })).toBeVisible();
  await page.getByRole('button', { name: '保存为长期记忆' }).click();

  await expect(page.getByRole('heading', { name: '长期记忆' })).toBeVisible();
  await expect(page.getByText('用户喜欢红茶。')).toBeVisible();

  await page.reload();
  await expect(page.getByText('用户喜欢红茶。')).toBeVisible();
});
```

If existing labels differ, use the accessible names already present in `MessageInput` and session buttons. Do not change production UI labels only to satisfy the test unless the current labels are inaccessible.

- [ ] **Step 2: Run the E2E test**

Run:

```bash
npm --prefix frontend run test:e2e -- memories.spec.ts
```

Expected: PASS. If it fails due to selector mismatch, inspect the rendered labels and update the test to match current accessible names.

- [ ] **Step 3: Commit checkpoint if commits are explicitly authorized**

Run only if the user has explicitly authorized commits in this session:

```bash
git add frontend/e2e/memories.spec.ts
git commit -m "test: cover memory candidate confirmation smoke"
```

Expected: commit succeeds. If commits are not authorized, skip this checkpoint and mention it in the final report.

---

## Task 11: Documentation and final regression

**Files:**
- Create: `docs/stage3b-memory-candidate-confirmation.md`
- Modify: `CLAUDE.md`
- Optional modify: `README.md` if configuration docs currently list memory settings

- [ ] **Step 1: Run full backend regression**

Run:

```bash
python -m pytest backend/tests
```

Expected: all backend tests pass. Record exact pass count and duration.

- [ ] **Step 2: Run full frontend unit regression**

Run:

```bash
npm --prefix frontend test -- --run
```

Expected: all frontend test files and tests pass. Record exact pass count.

- [ ] **Step 3: Run frontend typecheck**

Run:

```bash
npm --prefix frontend run typecheck
```

Expected: PASS with exit code 0.

- [ ] **Step 4: Run frontend build**

Run:

```bash
npm --prefix frontend run build
```

Expected: PASS. Record Vite module count and build time if shown.

- [ ] **Step 5: Run Playwright E2E regression**

Run:

```bash
npm --prefix frontend run test:e2e
```

Expected: all E2E tests pass. Record exact pass count.

- [ ] **Step 6: Create evidence document**

Create `docs/stage3b-memory-candidate-confirmation.md` with this structure, filling in exact command results from Steps 1-5:

```markdown
# Stage 3B Memory Candidate Confirmation Evidence

Status: COMPLETED on 2026-07-06.

## Scope

This slice implements Stage 3B long-term memory candidate confirmation:

- Heuristic candidate extraction from explicit user statements after successful chat turns.
- Pending candidate storage in the independent `memories` table.
- User confirmation before candidates become active long-term memories.
- User dismissal of inaccurate or unwanted candidates.
- Candidate UI in the existing memory panel.
- Candidate records excluded from chat context until confirmed.

It does not implement vector retrieval, semantic contradiction detection, session summaries, old chat-history backfill, or Stage 4 emotion state.

## Implemented behavior

- Explicit statements such as `我喜欢红茶。` can create a pending `preference` candidate.
- Pending candidates use `source = candidate` and `status = pending`.
- Pending and dismissed candidates are not injected into chat context.
- Confirming a candidate changes it to `active` and records `confirmed_at` in metadata.
- Dismissing a candidate changes it to `dismissed` and records `dismissed_at` in metadata.
- Candidate extraction failure does not fail chat.
- Exact normalized duplicate active or pending memories are not duplicated by candidate extraction.

## Validation

| Command | Result |
|---|---|
| `python -m pytest backend/tests` | PASS — replace with exact count |
| `npm --prefix frontend test -- --run` | PASS — replace with exact count |
| `npm --prefix frontend run typecheck` | PASS |
| `npm --prefix frontend run build` | PASS — replace with exact Vite output summary |
| `npm --prefix frontend run test:e2e` | PASS — replace with exact count |

## TDD notes

- Repository candidate tests first failed because candidate source/status and lifecycle methods did not exist.
- Candidate service tests first failed because `MemoryCandidateService` did not exist.
- Chat integration tests first failed because chat did not trigger candidate generation.
- API tests first failed because confirm/dismiss endpoints did not exist.
- Frontend client and panel tests first failed because candidate APIs and UI props did not exist.
- E2E test first failed until the full candidate confirmation path was wired.

## Limitations

- Candidate extraction is heuristic and conservative.
- No LLM-based extraction provider is implemented in this slice.
- Semantic contradiction detection is not implemented.
- Vector/embedding retrieval is not implemented.
- Session summaries are not implemented.
- Stage 4 emotion state is not implemented.
```

Use the real command results instead of `replace with exact count` lines before saving. Do not leave replacement text in the committed document.

- [ ] **Step 7: Update CLAUDE.md after verification**

Modify `CLAUDE.md` Stage 3 current entrance section to add a new bullet after the Stage 3A bullet:

```markdown
- 3B Memory Candidate Confirmation 已完成（2026-07-06；新增显式用户陈述的启发式候选记忆生成、pending/dismissed 候选状态、用户确认后转为 active 长期记忆、候选忽略、候选不进入上下文、最小候选 UI 与 E2E smoke；证据记录于 `docs/stage3b-memory-candidate-confirmation.md`）。验证：后端测试 PASS；前端测试 PASS；typecheck PASS；build PASS；Playwright E2E PASS。
```

Also update the next-step sentence so it no longer says automatic extraction is unimplemented. Use:

```markdown
- 当前尚未实现语义冲突检测、vector/embedding retrieval、会话摘要、LLM-based 记忆抽取或阶段 4 情感系统。
- 下一最小完整闭环应继续阶段 3 内的记忆检索增强、语义冲突/审计增强，或更强的用户确认式 LLM 候选抽取；不得提前实现阶段 4 情感系统。
```

Only perform this update after all validation commands pass.

- [ ] **Step 8: Run secret and scope sanity checks**

Run:

```bash
git diff -- . ':!frontend/package-lock.json'
```

Expected: diff contains no API keys, tokens, private audio, production data, or Stage 4 emotion implementation. It may contain Stage 3 memory candidate code, tests, and docs only.

- [ ] **Step 9: Commit final checkpoint if commits are explicitly authorized**

Run only if the user has explicitly authorized commits in this session:

```bash
git add backend/app backend/tests frontend/src frontend/e2e docs/stage3b-memory-candidate-confirmation.md CLAUDE.md README.md
git commit -m "feat: add memory candidate confirmation"
```

Expected: commit succeeds. If commits are not authorized, skip this checkpoint and mention it in the final report.

---

## Self-review checklist

- Spec coverage: Tasks cover storage/model migration, candidate lifecycle, heuristic extraction, chat hook, API confirm/dismiss, context exclusion, frontend client/types, UI, App state, E2E smoke, documentation, and `CLAUDE.md` update after verification.
- Placeholder scan: This plan avoids open placeholders in implementation steps. Evidence documentation requires replacing exact validation counts with real command outputs before saving the evidence file.
- Type consistency: Backend uses `MemorySource.CANDIDATE`, `MemoryStatus.PENDING`, `MemoryStatus.DISMISSED`; frontend uses source `'candidate'` and statuses `'pending' | 'dismissed'`; API methods are `confirmMemoryCandidate` and `dismissMemoryCandidate`.
- Stage boundary: No task implements Stage 4 emotion state or vector retrieval.
- Commit policy: Commit steps are included as checkpoints but are explicitly gated on separate user authorization because this session's higher-priority instructions say not to commit unless asked.
