# Stage 3K Session Summary Independent Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a backend-only storage layer for session summaries that stays separate from chat messages and long-term memories.

**Architecture:** Extend the existing SQLite schema and repository pattern. Add a small domain model and a focused `SessionSummaryRepository`; do not touch chat context building, memory retrieval, LLM providers, API routes, or frontend code.

**Tech Stack:** Python 3.12, SQLite, dataclasses, pytest, existing backend repository conventions.

---

## Scope and constraints

This plan implements Stage 3K only.

It must not implement:

- LLM summary generation;
- automatic summary triggers;
- prompt/context injection;
- frontend UI;
- API routes;
- conversion of summaries into long-term memories;
- memory retrieval over summaries;
- session backfill;
- Stage 4 emotion state.

The implementation uses synthetic test data only.

## File structure

Modify:

- `backend/app/domain/models.py`
  - Add `SessionSummarySource` and `SessionSummary`.

- `backend/app/repositories/sqlite.py`
  - Add `session_summaries` table and indexes.

- `CLAUDE.md`
  - Update status after validation to 3A–3K completed.

Create:

- `backend/app/repositories/session_summaries.py`
  - Repository for create/list/latest/delete.

- `backend/tests/test_session_summaries.py`
  - Focused storage and separation tests.

- `docs/stage3k-session-summary-independent-storage.md`
  - Evidence and stage boundary report.

Do not modify `ContextBuilder`, `ChatService`, memory repositories, providers, frontend files, or API routes.

---

### Task 1: Domain model and schema tests

**Files:**
- Modify: `backend/app/domain/models.py`
- Modify: `backend/app/repositories/sqlite.py`
- Create: `backend/tests/test_session_summaries.py`

- [ ] **Step 1: Write failing schema/domain tests**

Create `backend/tests/test_session_summaries.py`:

```python
from pathlib import Path

from app.domain.models import SessionSummary, SessionSummarySource
from app.repositories.sqlite import managed_connection


def test_session_summary_domain_model_supports_manual_source() -> None:
    assert SessionSummarySource.MANUAL.value == "manual"
    assert SessionSummarySource.GENERATED.value == "generated"
    assert SessionSummary.__name__ == "SessionSummary"


def test_session_summaries_table_is_created(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'summaries.db'}"

    with managed_connection(database_url) as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'session_summaries'"
        ).fetchone()
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(session_summaries)").fetchall()
        }

    assert table is not None
    assert columns == {
        "id",
        "session_id",
        "summary_text",
        "source",
        "covered_message_start_id",
        "covered_message_end_id",
        "message_count",
        "metadata_json",
        "created_at",
        "updated_at",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest backend/tests/test_session_summaries.py -q
```

Expected: FAIL because `SessionSummary` / `SessionSummarySource` or table do not exist.

- [ ] **Step 3: Add domain types**

In `backend/app/domain/models.py`, add after `Session`:

```python
class SessionSummarySource(StrEnum):
    MANUAL = "manual"
    GENERATED = "generated"


@dataclass(frozen=True)
class SessionSummary:
    id: str
    session_id: str
    summary_text: str
    source: SessionSummarySource
    covered_message_start_id: str | None
    covered_message_end_id: str | None
    message_count: int
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 4: Add SQLite table and indexes**

In `backend/app/repositories/sqlite.py`, add to `SCHEMA_SQL` after the `messages` index:

```sql
CREATE TABLE IF NOT EXISTS session_summaries (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    summary_text TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('manual', 'generated')),
    covered_message_start_id TEXT,
    covered_message_end_id TEXT,
    message_count INTEGER NOT NULL CHECK (message_count >= 0),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (covered_message_start_id) REFERENCES messages(id) ON DELETE SET NULL,
    FOREIGN KEY (covered_message_end_id) REFERENCES messages(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_session_summaries_session_created
ON session_summaries(session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_session_summaries_session_updated
ON session_summaries(session_id, updated_at DESC);
```

Also add the two indexes to the post-migration `connection.executescript(...)` block in `init_db`:

```sql
CREATE INDEX IF NOT EXISTS idx_session_summaries_session_created
ON session_summaries(session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_session_summaries_session_updated
ON session_summaries(session_id, updated_at DESC);
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```powershell
python -m pytest backend/tests/test_session_summaries.py -q
```

Expected: `2 passed`.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/domain/models.py backend/app/repositories/sqlite.py backend/tests/test_session_summaries.py
git commit -m "feat: add session summary schema"
```

---

### Task 2: Repository create and list

**Files:**
- Create: `backend/app/repositories/session_summaries.py`
- Modify: `backend/tests/test_session_summaries.py`

- [ ] **Step 1: Write failing repository create/list test**

Append to `backend/tests/test_session_summaries.py`:

```python
from app.domain.models import ChatRole
from app.repositories.messages import MessageRepository
from app.repositories.session_summaries import SessionSummaryRepository
from app.repositories.sessions import SessionRepository


def test_create_and_list_session_summaries(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'summaries.db'}"

    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        summaries = SessionSummaryRepository(connection)
        session = sessions.create("summary scope")
        first_message = messages.add(session.id, ChatRole.USER, "第一条消息")
        last_message = messages.add(session.id, ChatRole.ASSISTANT, "第二条消息")

        summary = summaries.create(
            session_id=session.id,
            summary_text="用户问候，助手回应。",
            covered_message_start_id=first_message.id,
            covered_message_end_id=last_message.id,
            message_count=2,
            metadata={"note": "synthetic"},
        )
        listed = summaries.list_for_session(session.id)

    assert summary.session_id == session.id
    assert summary.summary_text == "用户问候，助手回应。"
    assert summary.source == SessionSummarySource.MANUAL
    assert summary.covered_message_start_id == first_message.id
    assert summary.covered_message_end_id == last_message.id
    assert summary.message_count == 2
    assert summary.metadata == {"note": "synthetic"}
    assert listed == [summary]
```

- [ ] **Step 2: Run the new test to verify it fails**

Run:

```powershell
python -m pytest backend/tests/test_session_summaries.py::test_create_and_list_session_summaries -q
```

Expected: FAIL because `app.repositories.session_summaries` does not exist.

- [ ] **Step 3: Implement repository create/list**

Create `backend/app/repositories/session_summaries.py`:

```python
from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from app.domain.models import SessionSummary, SessionSummarySource
from app.repositories.sqlite import metadata_from_json, metadata_to_json


def _now() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: datetime) -> str:
    return value.isoformat()


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _row_to_summary(row: sqlite3.Row) -> SessionSummary:
    return SessionSummary(
        id=row["id"],
        session_id=row["session_id"],
        summary_text=row["summary_text"],
        source=SessionSummarySource(row["source"]),
        covered_message_start_id=row["covered_message_start_id"],
        covered_message_end_id=row["covered_message_end_id"],
        message_count=row["message_count"],
        metadata=metadata_from_json(row["metadata_json"]),
        created_at=_from_iso(row["created_at"]),
        updated_at=_from_iso(row["updated_at"]),
    )


class SessionSummaryRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create(
        self,
        *,
        session_id: str,
        summary_text: str,
        source: SessionSummarySource = SessionSummarySource.MANUAL,
        covered_message_start_id: str | None = None,
        covered_message_end_id: str | None = None,
        message_count: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> SessionSummary:
        clean_text = summary_text.strip()
        if not clean_text:
            raise ValueError("summary_text must not be empty")
        if message_count < 0:
            raise ValueError("message_count must be non-negative")
        now = _now()
        summary = SessionSummary(
            id=str(uuid.uuid4()),
            session_id=session_id,
            summary_text=clean_text,
            source=source,
            covered_message_start_id=covered_message_start_id,
            covered_message_end_id=covered_message_end_id,
            message_count=message_count,
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )
        self._connection.execute(
            """
            INSERT INTO session_summaries (
                id, session_id, summary_text, source, covered_message_start_id,
                covered_message_end_id, message_count, metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                summary.id,
                summary.session_id,
                summary.summary_text,
                summary.source.value,
                summary.covered_message_start_id,
                summary.covered_message_end_id,
                summary.message_count,
                metadata_to_json(summary.metadata),
                _to_iso(summary.created_at),
                _to_iso(summary.updated_at),
            ),
        )
        self._connection.commit()
        return summary

    def list_for_session(self, session_id: str) -> list[SessionSummary]:
        rows = self._connection.execute(
            """
            SELECT id, session_id, summary_text, source, covered_message_start_id,
                   covered_message_end_id, message_count, metadata_json, created_at, updated_at
            FROM session_summaries
            WHERE session_id = ?
            ORDER BY created_at ASC
            """,
            (session_id,),
        ).fetchall()
        return [_row_to_summary(row) for row in rows]
```

- [ ] **Step 4: Run the new test to verify it passes**

Run:

```powershell
python -m pytest backend/tests/test_session_summaries.py::test_create_and_list_session_summaries -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/repositories/session_summaries.py backend/tests/test_session_summaries.py
git commit -m "feat: add session summary repository"
```

---

### Task 3: Repository latest, delete, and validation behavior

**Files:**
- Modify: `backend/app/repositories/session_summaries.py`
- Modify: `backend/tests/test_session_summaries.py`

- [ ] **Step 1: Write failing tests for latest/delete/validation**

Append to `backend/tests/test_session_summaries.py`:

```python
import pytest


def test_latest_for_session_returns_newest_summary(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'summaries.db'}"

    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        summaries = SessionSummaryRepository(connection)
        session = sessions.create("latest summary")
        first = summaries.create(session_id=session.id, summary_text="第一段摘要")
        second = summaries.create(session_id=session.id, summary_text="第二段摘要")

        latest = summaries.latest_for_session(session.id)
        missing = summaries.latest_for_session("missing-session")

    assert latest == second
    assert latest != first
    assert missing is None


def test_delete_session_summary_returns_whether_row_was_deleted(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'summaries.db'}"

    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        summaries = SessionSummaryRepository(connection)
        session = sessions.create("delete summary")
        summary = summaries.create(session_id=session.id, summary_text="可删除摘要")

        assert summaries.delete(summary.id) is True
        assert summaries.delete(summary.id) is False
        assert summaries.list_for_session(session.id) == []


def test_session_summary_rejects_empty_text_and_negative_message_count(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'summaries.db'}"

    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        summaries = SessionSummaryRepository(connection)
        session = sessions.create("validation")

        with pytest.raises(ValueError, match="summary_text must not be empty"):
            summaries.create(session_id=session.id, summary_text="   ")
        with pytest.raises(ValueError, match="message_count must be non-negative"):
            summaries.create(session_id=session.id, summary_text="摘要", message_count=-1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest backend/tests/test_session_summaries.py::test_latest_for_session_returns_newest_summary backend/tests/test_session_summaries.py::test_delete_session_summary_returns_whether_row_was_deleted backend/tests/test_session_summary_rejects_empty_text_and_negative_message_count -q
```

Expected: latest/delete tests fail because methods do not exist; validation test may partially pass for create validations already implemented.

- [ ] **Step 3: Implement latest/delete**

Add to `SessionSummaryRepository` in `backend/app/repositories/session_summaries.py` after `list_for_session`:

```python
    def latest_for_session(self, session_id: str) -> SessionSummary | None:
        row = self._connection.execute(
            """
            SELECT id, session_id, summary_text, source, covered_message_start_id,
                   covered_message_end_id, message_count, metadata_json, created_at, updated_at
            FROM session_summaries
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        return _row_to_summary(row) if row else None

    def delete(self, summary_id: str) -> bool:
        cursor = self._connection.execute("DELETE FROM session_summaries WHERE id = ?", (summary_id,))
        self._connection.commit()
        return cursor.rowcount > 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
python -m pytest backend/tests/test_session_summaries.py::test_latest_for_session_returns_newest_summary backend/tests/test_session_summaries.py::test_delete_session_summary_returns_whether_row_was_deleted backend/tests/test_session_summary_rejects_empty_text_and_negative_message_count -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/repositories/session_summaries.py backend/tests/test_session_summaries.py
git commit -m "feat: complete session summary repository operations"
```

---

### Task 4: Separation and cascade behavior

**Files:**
- Modify: `backend/tests/test_session_summaries.py`

- [ ] **Step 1: Write separation and cascade tests**

Append to `backend/tests/test_session_summaries.py`:

```python
from app.domain.models import MemorySource, MemoryType
from app.repositories.memories import MemoryRepository


def test_deleting_session_cascades_session_summaries(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'summaries.db'}"

    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        summaries = SessionSummaryRepository(connection)
        session = sessions.create("cascade")
        summaries.create(session_id=session.id, summary_text="删除会话时应删除摘要")

        assert summaries.list_for_session(session.id)
        assert sessions.delete(session.id) is True
        assert summaries.list_for_session(session.id) == []


def test_session_summaries_do_not_create_long_term_memories(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'summaries.db'}"

    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        summaries = SessionSummaryRepository(connection)
        memories = MemoryRepository(connection)
        session = sessions.create("separation")

        summaries.create(session_id=session.id, summary_text="这是会话摘要，不是长期记忆。")
        memory, conflicts = memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=session.id,
            importance=3,
            confidence=0.8,
        )

        listed_summaries = summaries.list_for_session(session.id)
        listed_memories = memories.list()

    assert len(listed_summaries) == 1
    assert listed_summaries[0].summary_text == "这是会话摘要，不是长期记忆。"
    assert conflicts == []
    assert listed_memories == [memory]
```

- [ ] **Step 2: Run tests to verify behavior**

Run:

```powershell
python -m pytest backend/tests/test_session_summaries.py::test_deleting_session_cascades_session_summaries backend/tests/test_session_summaries.py::test_session_summaries_do_not_create_long_term_memories -q
```

Expected: PASS if schema/repository boundaries are correct. If cascade fails, investigate `PRAGMA foreign_keys` and schema FK before changing code.

- [ ] **Step 3: Run complete session summary test file**

Run:

```powershell
python -m pytest backend/tests/test_session_summaries.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add backend/tests/test_session_summaries.py
git commit -m "test: verify session summary storage boundaries"
```

---

### Task 5: Evidence documentation and status update

**Files:**
- Create: `docs/stage3k-session-summary-independent-storage.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run focused and related validation**

Run:

```powershell
python -m pytest backend/tests/test_session_summaries.py -q
python -m pytest backend/tests/test_session_summaries.py backend/tests/test_memory_candidate_service.py backend/tests/test_memory_embeddings.py backend/tests/test_config.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full backend tests**

Run from project root:

```powershell
python -m pytest backend/tests -q
```

Expected based on current baseline: either PASS, or the known unrelated `test_chat_service_prunes_old_history_before_provider_when_context_is_large` failure remains. Record exact result.

- [ ] **Step 3: Create evidence doc**

Create `docs/stage3k-session-summary-independent-storage.md`:

```markdown
# Stage 3K Session Summary Independent Storage

Date: 2026-07-10
Status: VERIFIED PASS or VERIFIED WITH UNRELATED BASELINE FAILURE

## Scope

Stage 3K adds independent backend storage for session summaries. It creates a `session_summaries` table, domain model, and repository.

## Non-goals

- No LLM summary generation.
- No automatic summary trigger.
- No summary prompt/context injection.
- No UI or API route.
- No conversion of summaries into long-term memories.
- No Stage 4 emotion state.

## Implemented storage

- Table: `session_summaries`
- Repository: `SessionSummaryRepository`
- Domain model: `SessionSummary`
- Source enum: `manual`, `generated`

## Verified behavior

- Create and list summaries for a session.
- Retrieve latest summary for a session.
- Delete a summary by ID.
- Reject empty summary text.
- Reject negative message counts.
- Delete summaries automatically when a session is deleted.
- Keep summaries separate from long-term memories.

## Validation

Record exact command outputs:

- `python -m pytest backend/tests/test_session_summaries.py -q` → result
- `python -m pytest backend/tests/test_session_summaries.py backend/tests/test_memory_candidate_service.py backend/tests/test_memory_embeddings.py backend/tests/test_config.py -q` → result
- `python -m pytest backend/tests -q` → result or known unrelated failure

## Stage boundary check

Stage 3K did not implement summary generation, summary prompt injection, memory writes, vector search over summaries, or Stage 4 emotion state.
```

Replace `VERIFIED PASS or VERIFIED WITH UNRELATED BASELINE FAILURE` and validation placeholders with observed results.

- [ ] **Step 4: Update `CLAUDE.md` after validation**

Update header:

```markdown
> 当前阶段：**阶段 3——长期记忆（IMPLEMENTING；3A–3K COMPLETED；NEXT: Semantic Conflict Detection Expansion or Session Summary Generation Design）**
> 更新日期：2026-07-10
```

Update Stage 3 table row:

```markdown
| 阶段 3：长期记忆 | **IMPLEMENTING** | 当前阶段；3A–3K 已完成；下一步可在通用语义矛盾检测扩展或会话摘要生成设计中选择一个最小闭环 |
```

Update completed summary:

```markdown
已完成子任务：3A–3K。已建立手动记忆 CRUD、候选确认、相关性检索、冲突审计、保守语义冲突检测、opt-in embedding retrieval、中文检索评估、隔离真实 embedding 模型评估路径、用户确认式 opt-in LLM 记忆候选抽取、真实 embedding 模型生产选型评估，以及会话摘要独立存储。具体证据见 `docs/stage3*.md`。
```

Update current unimplemented line:

```markdown
当前尚未实现：通用语义矛盾检测扩展、会话摘要生成/注入策略、自动冲突合并/解决工作流、阶段 4 情感系统。
```

Update next minimal loop section:

```markdown
3K 已完成。下一步只能在阶段 3 范围内选择一个最小闭环，例如：

- 通用语义矛盾检测扩展：必须保持保守策略、保留审计痕迹，不得自动覆盖或静默合并冲突记忆。
- 会话摘要生成设计：必须复用独立 summary 存储，不得把摘要包装成长期记忆，也不得未经设计直接注入对话上下文。
```

- [ ] **Step 5: Verify status text**

Run:

```powershell
python -c "from pathlib import Path; text = Path('CLAUDE.md').read_text(encoding='utf-8'); assert '3A–3K COMPLETED' in text; assert '阶段 4：情感系统 | 未开始' in text; assert '会话摘要独立存储' in text; print('CLAUDE.md stage status check PASS')"
```

Expected: PASS.

- [ ] **Step 6: Commit evidence and status**

```powershell
git add docs/stage3k-session-summary-independent-storage.md CLAUDE.md
git commit -m "docs: record stage 3k session summary storage"
```

---

### Task 6: Final scope and privacy check

**Files:**
- Review only

- [ ] **Step 1: Check git status**

Run:

```powershell
git status --short --branch
```

Expected: clean working tree.

- [ ] **Step 2: Scan changed files for secrets**

Run:

```powershell
python -c "from pathlib import Path; paths=[Path('backend/app/domain/models.py'),Path('backend/app/repositories/sqlite.py'),Path('backend/app/repositories/session_summaries.py'),Path('backend/tests/test_session_summaries.py'),Path('docs/stage3k-session-summary-independent-storage.md'),Path('CLAUDE.md')]; needles=['sk-','api_key=','secret=','token=','ANTHROPIC_API_KEY=','DEEPSEEK_API_KEY=']; found=False
for path in paths:
    text=path.read_text(encoding='utf-8', errors='ignore')
    for needle in needles:
        if needle.lower() in text.lower():
            print(f'{path}: {needle}'); found=True
if not found: print('secret scan PASS')"
```

Expected: `secret scan PASS`.

- [ ] **Step 3: Final focused validation**

Run:

```powershell
python -m pytest backend/tests/test_session_summaries.py backend/tests/test_memory_candidate_service.py backend/tests/test_memory_embeddings.py backend/tests/test_config.py -q
```

Expected: PASS.

- [ ] **Step 4: Final report**

Use this structure:

```text
完成内容：
修改文件：
验证命令与结果：
未完成或受限部分：
是否改变当前阶段：
下一项建议任务：
```

---

## Self-review checklist

- Spec coverage: Plan covers independent table, domain model, repository CRUD/latest/delete, cascade behavior, memory separation, evidence docs, and status update.
- Placeholder scan: No placeholders remain; evidence doc step explicitly replaces validation placeholders with observed results.
- Type consistency: Uses `SessionSummarySource`, `SessionSummary`, and `SessionSummaryRepository` consistently.
- Scope check: No API, UI, summary generation, context injection, memory retrieval, or Stage 4 work.
- TDD: Each behavior-changing step starts with failing tests before implementation.
