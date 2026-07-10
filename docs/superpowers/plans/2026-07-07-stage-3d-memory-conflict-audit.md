# Stage 3D Memory Conflict Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist and expose an audit trail whenever long-term memory mutations detect conflicts, and show conflict details in the memory UI.

**Architecture:** Add a local SQLite `memory_audit_events` table, a focused `MemoryAuditRepository`, and lightweight domain/API schemas for audit records. Memory API mutation routes record `conflict_detected` events when existing conflict detection returns conflicts; frontend uses existing mutation `conflicts` to display details, with a read-only backend endpoint for recent audit events.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, pytest, React, TypeScript, Vite, Vitest, Playwright.

---

## Stage boundary

This plan stays inside Stage 3: long-term memory. Do not implement vector retrieval, embeddings, LLM reranking, LLM memory extraction, semantic contradiction detection, session summaries, automatic merge/replace conflict resolution, or Stage 4 emotional state. Do not add mood, trust, concern, distance, irritation, formality, relationship scores, affect decay, or expression strategy state.

## Files to create or modify

### Backend

- Modify: `backend/app/domain/models.py`
  - Add audit enums and `MemoryAuditEvent` dataclass.

- Modify: `backend/app/domain/schemas.py`
  - Add `MemoryAuditEventResponse` and bounded audit list query model if needed.

- Modify: `backend/app/repositories/sqlite.py`
  - Add `memory_audit_events` table and indexes to `SCHEMA_SQL` / `init_db`.

- Create: `backend/app/repositories/memory_audit.py`
  - Implement `MemoryAuditRepository.record_conflict(...)` and `list_recent(...)`.

- Modify: `backend/app/api/dependencies.py`
  - Add `get_memory_audit_repository(...)`.

- Modify: `backend/app/api/routes/memories.py`
  - Inject audit repository into create/update/confirm routes.
  - Add `GET /api/memories/audit-events`.

### Frontend

- Modify: `frontend/src/components/MemoryPanel.tsx`
  - Render conflict details when `conflicts` is non-empty.

### Tests

- Modify: `backend/tests/test_repositories.py`
  - Add audit repository tests.

- Modify: `backend/tests/test_api_memories.py`
  - Add audit route and mutation recording tests.

- Modify: `frontend/src/components/MemoryPanel.test.tsx`
  - Assert conflict detail rendering.

### Documentation after verification

- Create: `docs/stage3d-memory-conflict-audit.md`
- Modify: `CLAUDE.md`

---

## Task 1: Audit domain model, SQLite table, and repository

**Files:**
- Modify: `backend/app/domain/models.py`
- Modify: `backend/app/repositories/sqlite.py`
- Create: `backend/app/repositories/memory_audit.py`
- Test: `backend/tests/test_repositories.py`

- [ ] **Step 1: Write failing repository audit tests**

Add these imports near the top of `backend/tests/test_repositories.py`:

```python
from app.domain.models import MemoryAuditOperation
from app.repositories.memory_audit import MemoryAuditRepository
```

If `MemoryAuditOperation` is not yet available, this is expected to fail during RED.

Add these tests after `test_same_content_different_memory_type_is_not_conflict`:

```python
def test_memory_audit_repository_records_conflict_event(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        audit = MemoryAuditRepository(connection)

        event = audit.record_conflict(
            memory_id="target-memory",
            related_memory_ids=["existing-1", "existing-2"],
            operation=MemoryAuditOperation.CREATE,
            metadata={"source": "api_test"},
        )

        assert event.event_type == "conflict_detected"
        assert event.memory_id == "target-memory"
        assert event.related_memory_ids == ["existing-1", "existing-2"]
        assert event.operation == MemoryAuditOperation.CREATE
        assert event.metadata == {"source": "api_test"}

        loaded = audit.list_recent(limit=10)
        assert [item.id for item in loaded] == [event.id]
        assert loaded[0].related_memory_ids == ["existing-1", "existing-2"]


def test_memory_audit_repository_lists_recent_events_newest_first(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        audit = MemoryAuditRepository(connection)

        first = audit.record_conflict(
            memory_id="first",
            related_memory_ids=["a"],
            operation=MemoryAuditOperation.CREATE,
            metadata={},
        )
        second = audit.record_conflict(
            memory_id="second",
            related_memory_ids=["b"],
            operation=MemoryAuditOperation.UPDATE,
            metadata={},
        )
        third = audit.record_conflict(
            memory_id="third",
            related_memory_ids=["c"],
            operation=MemoryAuditOperation.CONFIRM_CANDIDATE,
            metadata={},
        )

        loaded = audit.list_recent(limit=2)

        assert [event.id for event in loaded] == [third.id, second.id]
        assert first.id not in [event.id for event in loaded]
```

- [ ] **Step 2: Run repository audit tests to verify RED**

Run:

```bash
python -m pytest backend/tests/test_repositories.py::test_memory_audit_repository_records_conflict_event backend/tests/test_repositories.py::test_memory_audit_repository_lists_recent_events_newest_first -q
```

Expected: FAIL because `MemoryAuditOperation` and `MemoryAuditRepository` do not exist.

- [ ] **Step 3: Add audit domain models**

Modify `backend/app/domain/models.py` after `MemoryStatus` and before `Memory`:

```python
class MemoryAuditEventType(StrEnum):
    CONFLICT_DETECTED = "conflict_detected"


class MemoryAuditOperation(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    CONFIRM_CANDIDATE = "confirm_candidate"
```

Add this dataclass after `Memory`:

```python
@dataclass(frozen=True)
class MemoryAuditEvent:
    id: str
    event_type: MemoryAuditEventType
    memory_id: str
    related_memory_ids: list[str]
    operation: MemoryAuditOperation
    metadata: dict[str, Any]
    created_at: datetime
```

- [ ] **Step 4: Add audit SQLite table and indexes**

Modify `backend/app/repositories/sqlite.py`.

Append this SQL to `SCHEMA_SQL` after the `idx_memories_type_status` index:

```sql

CREATE TABLE IF NOT EXISTS memory_audit_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL CHECK (event_type IN ('conflict_detected')),
    memory_id TEXT NOT NULL,
    related_memory_ids_json TEXT NOT NULL DEFAULT '[]',
    operation TEXT NOT NULL CHECK (operation IN ('create', 'update', 'confirm_candidate')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_audit_events_created
ON memory_audit_events(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_audit_events_memory
ON memory_audit_events(memory_id);
```

Also extend the `connection.executescript(...)` block in `init_db` to include the same two indexes:

```sql

        CREATE INDEX IF NOT EXISTS idx_memory_audit_events_created
        ON memory_audit_events(created_at DESC);

        CREATE INDEX IF NOT EXISTS idx_memory_audit_events_memory
        ON memory_audit_events(memory_id);
```

- [ ] **Step 5: Create `MemoryAuditRepository`**

Create `backend/app/repositories/memory_audit.py` with this content:

```python
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from app.domain.models import MemoryAuditEvent, MemoryAuditEventType, MemoryAuditOperation
from app.repositories.sqlite import metadata_from_json, metadata_to_json


def _now() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: datetime) -> str:
    return value.isoformat()


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _ids_to_json(memory_ids: list[str]) -> str:
    return json.dumps(memory_ids, ensure_ascii=False)


def _ids_from_json(raw: str) -> list[str]:
    value = json.loads(raw)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _row_to_event(row: sqlite3.Row) -> MemoryAuditEvent:
    return MemoryAuditEvent(
        id=row["id"],
        event_type=MemoryAuditEventType(row["event_type"]),
        memory_id=row["memory_id"],
        related_memory_ids=_ids_from_json(row["related_memory_ids_json"]),
        operation=MemoryAuditOperation(row["operation"]),
        metadata=metadata_from_json(row["metadata_json"]),
        created_at=_from_iso(row["created_at"]),
    )


class MemoryAuditRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def record_conflict(
        self,
        *,
        memory_id: str,
        related_memory_ids: list[str],
        operation: MemoryAuditOperation,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryAuditEvent:
        now = _now()
        event = MemoryAuditEvent(
            id=str(uuid.uuid4()),
            event_type=MemoryAuditEventType.CONFLICT_DETECTED,
            memory_id=memory_id,
            related_memory_ids=list(related_memory_ids),
            operation=operation,
            metadata=metadata or {},
            created_at=now,
        )
        self._connection.execute(
            """
            INSERT INTO memory_audit_events (
                id, event_type, memory_id, related_memory_ids_json,
                operation, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.event_type.value,
                event.memory_id,
                _ids_to_json(event.related_memory_ids),
                event.operation.value,
                metadata_to_json(event.metadata),
                _to_iso(event.created_at),
            ),
        )
        self._connection.commit()
        return event

    def list_recent(self, limit: int = 20) -> list[MemoryAuditEvent]:
        rows = self._connection.execute(
            """
            SELECT id, event_type, memory_id, related_memory_ids_json,
                   operation, metadata_json, created_at
            FROM memory_audit_events
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_event(row) for row in rows]
```

- [ ] **Step 6: Run repository audit tests to verify GREEN**

Run:

```bash
python -m pytest backend/tests/test_repositories.py::test_memory_audit_repository_records_conflict_event backend/tests/test_repositories.py::test_memory_audit_repository_lists_recent_events_newest_first -q
```

Expected: PASS.

- [ ] **Step 7: Run repository regression**

Run:

```bash
python -m pytest backend/tests/test_repositories.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit checkpoint if commits are explicitly authorized**

Run only if the user has explicitly authorized commits:

```bash
git add backend/app/domain/models.py backend/app/repositories/sqlite.py backend/app/repositories/memory_audit.py backend/tests/test_repositories.py
git commit -m "feat: add memory conflict audit repository"
```

Expected: commit succeeds. If commits are not authorized, skip and mention it in the final report.

---

## Task 2: API audit recording and read endpoint

**Files:**
- Modify: `backend/app/domain/schemas.py`
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/app/api/routes/memories.py`
- Test: `backend/tests/test_api_memories.py`

- [ ] **Step 1: Write failing API tests**

Add these tests to `backend/tests/test_api_memories.py` after `test_duplicate_memory_api_returns_conflicts_without_overwriting`:

```python
def test_duplicate_memory_api_records_conflict_audit_event(client: TestClient) -> None:
    first = client.post(
        "/api/memories",
        json={"content": "用户喜欢雪。", "memory_type": "preference", "importance": 3, "confidence": 1.0},
    ).json()["memory"]

    second = client.post(
        "/api/memories",
        json={"content": " 用户喜欢雪。 ", "memory_type": "preference", "importance": 2, "confidence": 0.8},
    ).json()["memory"]

    audit_response = client.get("/api/memories/audit-events")

    assert audit_response.status_code == 200
    events = audit_response.json()
    assert len(events) == 1
    assert events[0]["event_type"] == "conflict_detected"
    assert events[0]["operation"] == "create"
    assert events[0]["memory_id"] == second["id"]
    assert events[0]["related_memory_ids"] == [first["id"]]


def test_non_conflicting_memory_api_does_not_record_audit_event(client: TestClient) -> None:
    client.post(
        "/api/memories",
        json={"content": "用户喜欢雪。", "memory_type": "preference", "importance": 3, "confidence": 1.0},
    )

    audit_response = client.get("/api/memories/audit-events")

    assert audit_response.status_code == 200
    assert audit_response.json() == []


def test_update_memory_api_records_conflict_audit_event(client: TestClient) -> None:
    first = client.post(
        "/api/memories",
        json={"content": "用户喜欢雪。", "memory_type": "preference", "importance": 3, "confidence": 1.0},
    ).json()["memory"]
    second = client.post(
        "/api/memories",
        json={"content": "用户喜欢雨。", "memory_type": "preference", "importance": 3, "confidence": 1.0},
    ).json()["memory"]

    update_response = client.patch(
        f"/api/memories/{second['id']}",
        json={"content": " 用户喜欢雪。 "},
    )

    assert update_response.status_code == 200
    assert [item["id"] for item in update_response.json()["conflicts"]] == [first["id"]]
    events = client.get("/api/memories/audit-events").json()
    assert len(events) == 1
    assert events[0]["operation"] == "update"
    assert events[0]["memory_id"] == second["id"]
    assert events[0]["related_memory_ids"] == [first["id"]]


def test_confirm_candidate_conflict_records_audit_event_and_keeps_candidate_pending(client: TestClient) -> None:
    active = client.post(
        "/api/memories",
        json={"content": "用户喜欢红茶。", "memory_type": "preference", "importance": 3, "confidence": 1.0},
    ).json()["memory"]
    session = client.post("/api/sessions", json={"title": "候选冲突"}).json()
    client.post(f"/api/sessions/{session['id']}/messages", json={"content": "我喜欢红茶。"})
    candidate = client.get("/api/memories", params={"status_filter": "pending"}).json()[0]

    confirm_response = client.post(f"/api/memories/{candidate['id']}/confirm")

    assert confirm_response.status_code == 200
    confirm_body = confirm_response.json()
    assert confirm_body["memory"]["status"] == "pending"
    assert [item["id"] for item in confirm_body["conflicts"]] == [active["id"]]
    events = client.get("/api/memories/audit-events").json()
    assert len(events) == 1
    assert events[0]["operation"] == "confirm_candidate"
    assert events[0]["memory_id"] == candidate["id"]
    assert events[0]["related_memory_ids"] == [active["id"]]


def test_memory_audit_events_limit_is_bounded(client: TestClient) -> None:
    too_large = client.get("/api/memories/audit-events", params={"limit": 101})
    too_small = client.get("/api/memories/audit-events", params={"limit": 0})

    assert too_large.status_code == 422
    assert too_small.status_code == 422
```

- [ ] **Step 2: Run API audit tests to verify RED**

Run:

```bash
python -m pytest backend/tests/test_api_memories.py::test_duplicate_memory_api_records_conflict_audit_event backend/tests/test_api_memories.py::test_non_conflicting_memory_api_does_not_record_audit_event backend/tests/test_api_memories.py::test_update_memory_api_records_conflict_audit_event backend/tests/test_api_memories.py::test_confirm_candidate_conflict_records_audit_event_and_keeps_candidate_pending backend/tests/test_api_memories.py::test_memory_audit_events_limit_is_bounded -q
```

Expected: FAIL because `/api/memories/audit-events` does not exist and mutation routes do not record audit events.

- [ ] **Step 3: Add API response schema**

Modify `backend/app/domain/schemas.py`.

Add this import:

```python
from app.domain.models import MemoryAuditOperation
```

If the file currently imports only `MemoryType`, replace it with:

```python
from app.domain.models import MemoryAuditOperation, MemoryType
```

Add this schema after `MemoryMutationResponse`:

```python
class MemoryAuditEventResponse(BaseModel):
    id: str
    event_type: str
    memory_id: str
    related_memory_ids: list[str]
    operation: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
```

The `MemoryAuditOperation` import is not strictly required by this response model. If your linter flags it as unused, remove it. Keep the response schema exactly as above.

- [ ] **Step 4: Add audit dependency**

Modify `backend/app/api/dependencies.py`.

Add import near repository imports:

```python
from app.repositories.memory_audit import MemoryAuditRepository
```

Add this dependency after `get_memory_repository`:

```python
def get_memory_audit_repository(connection: sqlite3.Connection = Depends(get_connection)) -> MemoryAuditRepository:
    return MemoryAuditRepository(connection)
```

- [ ] **Step 5: Update memory routes to record audit events and expose read endpoint**

Modify `backend/app/api/routes/memories.py`.

Update imports:

```python
from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import get_memory_audit_repository, get_memory_repository, get_session_repository
from app.core.errors import ValidationAppError
from app.domain.models import Memory, MemoryAuditEvent, MemoryAuditOperation, MemorySource, MemoryStatus, MemoryType
from app.domain.schemas import CreateMemoryRequest, MemoryAuditEventResponse, MemoryMutationResponse, MemoryResponse, UpdateMemoryRequest
from app.repositories.memory_audit import MemoryAuditRepository
from app.repositories.memories import MemoryRepository
from app.repositories.sessions import SessionRepository
```

Add helper functions after `_memory_response`:

```python
def _audit_response(event: MemoryAuditEvent) -> MemoryAuditEventResponse:
    return MemoryAuditEventResponse.model_validate(event, from_attributes=True)


def _record_conflicts(
    audit: MemoryAuditRepository,
    *,
    memory: Memory,
    conflicts: list[Memory],
    operation: MemoryAuditOperation,
) -> None:
    if not conflicts:
        return
    audit.record_conflict(
        memory_id=memory.id,
        related_memory_ids=[conflict.id for conflict in conflicts],
        operation=operation,
        metadata={"conflict_count": len(conflicts)},
    )
```

Update `create_memory` signature to inject audit:

```python
def create_memory(
    request: CreateMemoryRequest,
    memories: MemoryRepository = Depends(get_memory_repository),
    sessions: SessionRepository = Depends(get_session_repository),
    audit: MemoryAuditRepository = Depends(get_memory_audit_repository),
) -> MemoryMutationResponse:
```

After `memory, conflicts = memories.create(...)`, add:

```python
    _record_conflicts(audit, memory=memory, conflicts=conflicts, operation=MemoryAuditOperation.CREATE)
```

Update `update_memory` signature:

```python
def update_memory(
    memory_id: str,
    request: UpdateMemoryRequest,
    memories: MemoryRepository = Depends(get_memory_repository),
    audit: MemoryAuditRepository = Depends(get_memory_audit_repository),
) -> MemoryMutationResponse:
```

After `memory, conflicts = memories.update(...)`, add:

```python
    _record_conflicts(audit, memory=memory, conflicts=conflicts, operation=MemoryAuditOperation.UPDATE)
```

Update `confirm_memory_candidate` signature:

```python
def confirm_memory_candidate(
    memory_id: str,
    memories: MemoryRepository = Depends(get_memory_repository),
    audit: MemoryAuditRepository = Depends(get_memory_audit_repository),
) -> MemoryMutationResponse:
```

After the try/except block assigns `memory, conflicts`, add:

```python
    _record_conflicts(audit, memory=memory, conflicts=conflicts, operation=MemoryAuditOperation.CONFIRM_CANDIDATE)
```

Add the read endpoint before `@router.get("", ...)` so the static path is registered before `/{memory_id}` routes:

```python
@router.get("/audit-events", response_model=list[MemoryAuditEventResponse])
def list_memory_audit_events(
    limit: int = Query(default=20, ge=1, le=100),
    audit: MemoryAuditRepository = Depends(get_memory_audit_repository),
) -> list[MemoryAuditEventResponse]:
    return [_audit_response(event) for event in audit.list_recent(limit=limit)]
```

- [ ] **Step 6: Run API audit tests to verify GREEN**

Run:

```bash
python -m pytest backend/tests/test_api_memories.py::test_duplicate_memory_api_records_conflict_audit_event backend/tests/test_api_memories.py::test_non_conflicting_memory_api_does_not_record_audit_event backend/tests/test_api_memories.py::test_update_memory_api_records_conflict_audit_event backend/tests/test_api_memories.py::test_confirm_candidate_conflict_records_audit_event_and_keeps_candidate_pending backend/tests/test_api_memories.py::test_memory_audit_events_limit_is_bounded -q
```

Expected: PASS.

- [ ] **Step 7: Run API memory regression**

Run:

```bash
python -m pytest backend/tests/test_api_memories.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit checkpoint if commits are explicitly authorized**

Run only if the user has explicitly authorized commits:

```bash
git add backend/app/domain/schemas.py backend/app/api/dependencies.py backend/app/api/routes/memories.py backend/tests/test_api_memories.py
git commit -m "feat: record memory conflict audit events"
```

Expected: commit succeeds. If commits are not authorized, skip and mention it in the final report.

---

## Task 3: Frontend conflict detail display

**Files:**
- Modify: `frontend/src/components/MemoryPanel.tsx`
- Test: `frontend/src/components/MemoryPanel.test.tsx`

- [ ] **Step 1: Write failing MemoryPanel conflict-detail test**

Replace the existing `renders memories, conflicts, and delete action` test in `frontend/src/components/MemoryPanel.test.tsx` with:

```tsx
  it('renders memories, conflict details, and delete action', async () => {
    const onDelete = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<MemoryPanel memories={[memory]} candidates={[]} loading={false} error={null} conflicts={[memory]} onCreate={vi.fn()} onUpdate={vi.fn()} onDelete={onDelete} onConfirmCandidate={vi.fn()} onDismissCandidate={vi.fn()} />);

    expect(screen.getByText('用户偏好中文回复。')).toBeInTheDocument();
    expect(screen.getByText(/发现相似记忆/)).toBeInTheDocument();
    expect(screen.getByRole('region', { name: '冲突记忆明细' })).toBeInTheDocument();
    expect(screen.getByText(/preference · importance 3 · confidence 1.00/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '删除记忆' }));
    expect(onDelete).toHaveBeenCalledWith('m1');
  });
```

- [ ] **Step 2: Run MemoryPanel test to verify RED**

Run:

```bash
npm --prefix frontend test -- --run src/components/MemoryPanel.test.tsx
```

Expected: FAIL because the `冲突记忆明细` region does not exist.

- [ ] **Step 3: Render conflict details**

Modify `frontend/src/components/MemoryPanel.tsx`.

Replace this line:

```tsx
      {conflicts.length > 0 ? <p className="memory-panel__warning">发现相似记忆，请确认是否需要保留多条。</p> : null}
```

with:

```tsx
      {conflicts.length > 0 ? (
        <section className="memory-panel__conflicts" aria-label="冲突记忆明细">
          <p className="memory-panel__warning">发现相似记忆，请确认是否需要保留多条。</p>
          <ul className="memory-panel__list">
            {conflicts.map((conflict) => (
              <li key={conflict.id} className="memory-panel__item memory-panel__item--conflict">
                <p>{conflict.content}</p>
                <small>{conflict.memory_type} · importance {conflict.importance} · confidence {conflict.confidence.toFixed(2)}</small>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
```

No CSS change is required for this minimal slice because the existing list/item classes already style the detail records. If the UI looks crowded in manual smoke, add small CSS only after tests are green.

- [ ] **Step 4: Run MemoryPanel test to verify GREEN**

Run:

```bash
npm --prefix frontend test -- --run src/components/MemoryPanel.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Run focused frontend tests**

Run:

```bash
npm --prefix frontend test -- --run src/components/MemoryPanel.test.tsx src/App.test.tsx src/api/client.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit checkpoint if commits are explicitly authorized**

Run only if the user has explicitly authorized commits:

```bash
git add frontend/src/components/MemoryPanel.tsx frontend/src/components/MemoryPanel.test.tsx
git commit -m "feat: show memory conflict details"
```

Expected: commit succeeds. If commits are not authorized, skip and mention it in the final report.

---

## Task 4: Final regression, evidence documentation, and CLAUDE.md update

**Files:**
- Create: `docs/stage3d-memory-conflict-audit.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run focused Stage 3D backend tests**

Run:

```bash
python -m pytest backend/tests/test_repositories.py backend/tests/test_api_memories.py -q
```

Expected: PASS. Record exact pass count and duration.

- [ ] **Step 2: Run full backend regression**

Run:

```bash
python -m pytest backend/tests
```

Expected: all backend tests pass. Record exact pass count and duration.

- [ ] **Step 3: Run frontend unit regression**

Run:

```bash
npm --prefix frontend test -- --run
```

Expected: all frontend test files and tests pass. Record exact file/test count.

- [ ] **Step 4: Run frontend typecheck**

Run:

```bash
npm --prefix frontend run typecheck
```

Expected: PASS with exit code 0.

- [ ] **Step 5: Run frontend build**

Run:

```bash
npm --prefix frontend run build
```

Expected: PASS. Record module count and build time if shown.

- [ ] **Step 6: Run Playwright E2E regression**

Run:

```bash
npm --prefix frontend run test:e2e
```

Expected: all E2E tests pass. Record exact pass count.

- [ ] **Step 7: Run task-related sensitive data scan**

Use the dedicated Grep tool over the files touched in this plan with this pattern:

```text
api[_-]?key|secret|token|sk-[a-z0-9]|password|credential
```

Expected: no real secrets. Existing configuration names and fake test strings are acceptable.

- [ ] **Step 8: Create evidence document**

Create `docs/stage3d-memory-conflict-audit.md` with exact command results:

```markdown
# Stage 3D Memory Conflict Audit Evidence

Status: COMPLETED on 2026-07-07.

## Scope

This slice implements Stage 3D memory conflict audit support:

- Memory create/update/confirm-candidate operations record audit events when conflicts are detected.
- Audit events are stored locally in SQLite in `memory_audit_events`.
- The read-only `/api/memories/audit-events` endpoint returns recent audit events.
- The memory panel shows conflict details instead of only a generic warning.

It does not implement vector retrieval, embeddings, LLM reranking, LLM-based semantic contradiction detection, automatic conflict merge/resolve, session summaries, or Stage 4 emotion state.

## Implemented behavior

- `MemoryAuditRepository.record_conflict(...)` stores `conflict_detected` events with target memory id, related memory ids, operation, metadata, and timestamp.
- `POST /api/memories`, `PATCH /api/memories/{memory_id}`, and `POST /api/memories/{memory_id}/confirm` record audit events only when conflicts are non-empty.
- `GET /api/memories/audit-events?limit=20` returns recent audit events with bounded `limit`.
- `MemoryPanel` renders conflict contents, type, importance, and confidence.

## Validation

| Command | Result |
|---|---|
| `python -m pytest backend/tests/test_repositories.py backend/tests/test_api_memories.py -q` | PASS — replace with exact count |
| `python -m pytest backend/tests` | PASS — replace with exact count |
| `npm --prefix frontend test -- --run` | PASS — replace with exact count |
| `npm --prefix frontend run typecheck` | PASS |
| `npm --prefix frontend run build` | PASS — replace with exact Vite output summary |
| `npm --prefix frontend run test:e2e` | PASS — replace with exact count |

## TDD notes

- Repository tests first failed because the audit domain model and repository did not exist.
- API tests first failed because `/api/memories/audit-events` and route-level audit recording did not exist.
- Frontend tests first failed because the conflict-detail region was not rendered.

## Privacy and safety check

Task-related secret scan checked changed backend, frontend, tests, docs, and `CLAUDE.md` files for likely key/secret/token strings. No real secret was found.

## Limitations

- Audit events record detected conflicts; they do not resolve or merge conflicts.
- Conflict detection remains the existing exact normalized same-type duplicate check.
- No semantic contradiction detection is implemented.
- No vector/embedding retrieval is implemented.
- No LLM-based memory extraction is implemented.
- Stage 4 emotion state is not implemented.
```

Replace all `replace with exact ...` text with real command output before saving.

- [ ] **Step 9: Update CLAUDE.md after validation**

Modify the Stage 3 current entrance section in `CLAUDE.md` to add a new bullet after Stage 3C:

```markdown
- 3D Memory Conflict Audit 已完成（2026-07-07；新增 memory conflict audit event SQLite 存储、`MemoryAuditRepository`、冲突 mutation 自动记录、`GET /api/memories/audit-events` 只读审计查询、前端冲突明细展示；证据记录于 `docs/stage3d-memory-conflict-audit.md`）。验证：后端测试 PASS；前端测试 PASS；typecheck PASS；build PASS；Playwright E2E PASS。
```

Update the pending line to remove plain audit enhancement as pending:

```markdown
- 当前尚未实现语义冲突检测、vector/embedding retrieval、会话摘要、LLM-based 记忆抽取、自动冲突合并/解决工作流或阶段 4 情感系统。
- 下一最小完整闭环应继续阶段 3 内的语义冲突检测、vector/embedding retrieval，或更强的用户确认式 LLM 候选抽取；必须保持聊天历史、会话摘要和长期记忆分离；不得把最近聊天记录包装成长期记忆；不得提前实现阶段 4 情感系统。
```

Only update `CLAUDE.md` after all validation commands pass.

- [ ] **Step 10: Commit final checkpoint if commits are explicitly authorized**

Run only if the user has explicitly authorized commits:

```bash
git add backend/app/domain/models.py backend/app/domain/schemas.py backend/app/repositories/sqlite.py backend/app/repositories/memory_audit.py backend/app/api/dependencies.py backend/app/api/routes/memories.py backend/tests/test_repositories.py backend/tests/test_api_memories.py frontend/src/components/MemoryPanel.tsx frontend/src/components/MemoryPanel.test.tsx docs/stage3d-memory-conflict-audit.md CLAUDE.md
git commit -m "feat: add memory conflict audit trail"
```

Expected: commit succeeds. If commits are not authorized, skip and mention it in the final report.

---

## Self-review checklist

- Spec coverage: Tasks cover audit data model, SQLite table/indexes, repository recording/listing, mutation route audit recording, read-only audit endpoint, frontend conflict details, regression, evidence docs, and `CLAUDE.md` update after validation.
- Placeholder scan: The plan contains no open implementation placeholders. The evidence document step intentionally instructs replacing validation placeholders with exact observed command output before saving.
- Type consistency: `MemoryAuditEventType`, `MemoryAuditOperation`, `MemoryAuditEvent`, `MemoryAuditRepository.record_conflict`, `list_recent`, and `MemoryAuditEventResponse` are named consistently across tasks.
- Stage boundary: No task implements Stage 4 emotion state, embeddings, vector retrieval, LLM extraction/reranking, semantic contradiction detection, session summaries, or automatic conflict merge/resolve.
- Commit policy: Commit steps are gated on explicit user authorization; do not commit during this session unless separately instructed.
