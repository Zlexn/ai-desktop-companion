# Stage 3L Semantic Conflict Detection Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand conservative semantic conflict detection for current user facts: name, school, and company, with a historical-fact guard.

**Architecture:** Keep conflict detection inside the existing local pattern-based `MemoryRepository` helpers. Add no providers, embeddings, LLM calls, UI, API schema changes, or automatic resolution logic; existing repository/API conflict paths surface the new conflicts.

**Tech Stack:** Python 3.12, pytest, SQLite-backed repository tests, existing `MemoryRepository` semantic signature helpers.

---

## Scope and constraints

This plan implements Stage 3L only.

It must not implement:

- LLM contradiction detection;
- embedding contradiction detection;
- automatic memory overwrite, merge, archive, delete, or conflict resolution;
- new UI;
- new API contracts;
- session summary generation/injection;
- Stage 4 emotion state.

## File structure

Modify:

- `backend/app/repositories/memories.py`
  - Add a conservative historical marker guard.
  - Extend `_semantic_signature(...)` for `MemoryType.USER_FACT` with name, school, and company signatures.
  - Keep existing residence, occupation, preference, and goal behavior compatible.

- `backend/tests/test_repositories.py`
  - Add tests for new conflict-positive and conflict-negative cases.

- `CLAUDE.md`
  - Update stage status after validation.

Create:

- `docs/stage3l-semantic-conflict-expansion.md`
  - Evidence and validation record.

No frontend files, provider files, API routes, session summary files, or chat context files should change.

---

### Task 1: Name, school, and company conflict tests

**Files:**
- Modify: `backend/tests/test_repositories.py`
- Modify: `backend/app/repositories/memories.py`

- [ ] **Step 1: Write failing tests for new current fact conflicts**

Append these tests after `test_occupation_single_value_fact_conflicts_when_value_changes` in `backend/tests/test_repositories.py`:

```python
def test_name_single_value_fact_conflicts_when_value_changes(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        zhang, _ = memories.create(
            content="用户的名字是张三。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户叫李四。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert [memory.id for memory in conflicts] == [zhang.id]


def test_school_single_value_fact_conflicts_when_value_changes(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        fudan, _ = memories.create(
            content="用户就读于复旦大学。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户在上海交通大学读书。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert [memory.id for memory in conflicts] == [fudan.id]


def test_company_single_value_fact_conflicts_when_value_changes(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        old_company, _ = memories.create(
            content="用户就职于甲公司。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户的公司是乙公司。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert [memory.id for memory in conflicts] == [old_company.id]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest backend/tests/test_repositories.py::test_name_single_value_fact_conflicts_when_value_changes backend/tests/test_repositories.py::test_school_single_value_fact_conflicts_when_value_changes backend/tests/test_repositories.py::test_company_single_value_fact_conflicts_when_value_changes -q
```

Expected: FAIL because the new semantic signatures are not implemented; `conflicts` is `[]`.

- [ ] **Step 3: Implement new current fact signatures**

In `backend/app/repositories/memories.py`, add this helper after `_strip_goal_prefix`:

```python
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
```

Then in `_semantic_signature`, inside the `MemoryType.USER_FACT` block, after occupation detection and before `return None`, add:

```python
        expanded = _current_user_fact_signature(clean)
        if expanded is not None:
            return expanded
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
python -m pytest backend/tests/test_repositories.py::test_name_single_value_fact_conflicts_when_value_changes backend/tests/test_repositories.py::test_school_single_value_fact_conflicts_when_value_changes backend/tests/test_repositories.py::test_company_single_value_fact_conflicts_when_value_changes -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/repositories/memories.py backend/tests/test_repositories.py
git commit -m "feat: detect additional user fact conflicts"
```

---

### Task 2: Historical fact guard

**Files:**
- Modify: `backend/tests/test_repositories.py`
- Modify: `backend/app/repositories/memories.py`

- [ ] **Step 1: Write failing historical guard tests**

Append after the Task 1 tests:

```python
def test_historical_residence_does_not_conflict_with_current_residence(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        memories.create(
            content="用户以前住在北京。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户住在上海。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert conflicts == []


def test_historical_school_does_not_conflict_with_current_school(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        memories.create(
            content="用户曾经就读于复旦大学。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户就读于上海交通大学。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert conflicts == []


def test_historical_company_does_not_conflict_with_current_company(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        memories.create(
            content="用户去年就职于甲公司。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户就职于乙公司。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert conflicts == []
```

- [ ] **Step 2: Run tests to verify they fail where guard is missing**

Run:

```powershell
python -m pytest backend/tests/test_repositories.py::test_historical_residence_does_not_conflict_with_current_residence backend/tests/test_repositories.py::test_historical_school_does_not_conflict_with_current_school backend/tests/test_repositories.py::test_historical_company_does_not_conflict_with_current_company -q
```

Expected: at least residence fails because `用户以前住在北京。` is currently parsed as residence value `北京`; school/company may pass or fail depending on Task 1 regex behavior. Any failing test confirms the missing guard.

- [ ] **Step 3: Implement historical marker guard**

In `backend/app/repositories/memories.py`, add after `_strip_goal_prefix`:

```python
_HISTORICAL_MARKERS = ("以前", "之前", "过去", "曾经", "去年", "上个月", "小时候")


def _has_historical_marker(content: str) -> bool:
    return any(marker in content for marker in _HISTORICAL_MARKERS)
```

Then in `_semantic_signature`, at the start of the `MemoryType.USER_FACT` block, add:

```python
        if _has_historical_marker(clean):
            return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
python -m pytest backend/tests/test_repositories.py::test_historical_residence_does_not_conflict_with_current_residence backend/tests/test_repositories.py::test_historical_school_does_not_conflict_with_current_school backend/tests/test_repositories.py::test_historical_company_does_not_conflict_with_current_company -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/repositories/memories.py backend/tests/test_repositories.py
git commit -m "feat: ignore historical facts in semantic conflicts"
```

---

### Task 3: Non-conflicting categories and regression coverage

**Files:**
- Modify: `backend/tests/test_repositories.py`

- [ ] **Step 1: Add event non-conflict regression test**

Append after the Task 2 tests:

```python
def test_important_events_do_not_use_user_fact_conflict_patterns(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        memories.create(
            content="用户去年就职于甲公司。",
            memory_type=MemoryType.IMPORTANT_EVENT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户就职于乙公司。",
            memory_type=MemoryType.IMPORTANT_EVENT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert conflicts == []
```

- [ ] **Step 2: Run regression tests**

Run:

```powershell
python -m pytest backend/tests/test_repositories.py::test_important_events_do_not_use_user_fact_conflict_patterns backend/tests/test_repositories.py::test_opposite_preference_polarity_returns_conflict backend/tests/test_repositories.py::test_goal_and_preparation_overlap_returns_conflict backend/tests/test_repositories.py::test_different_goals_do_not_conflict -q
```

Expected: PASS. If this fails, fix only the failing semantic-signature boundary.

- [ ] **Step 3: Run full repository tests**

Run:

```powershell
python -m pytest backend/tests/test_repositories.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add backend/tests/test_repositories.py
git commit -m "test: preserve semantic conflict boundaries"
```

---

### Task 4: Evidence documentation and status update

**Files:**
- Create: `docs/stage3l-semantic-conflict-expansion.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run focused and related validation**

Run:

```powershell
python -m pytest backend/tests/test_repositories.py -q
python -m pytest backend/tests/test_repositories.py backend/tests/test_api_memories.py backend/tests/test_memory_candidate_service.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full backend tests**

Run:

```powershell
python -m pytest backend/tests -q
```

Expected based on current baseline: either PASS, or the known unrelated `test_chat_service_prunes_old_history_before_provider_when_context_is_large` failure remains. Record exact result.

- [ ] **Step 3: Create evidence doc**

Create `docs/stage3l-semantic-conflict-expansion.md`:

```markdown
# Stage 3L Semantic Conflict Detection Expansion

Date: 2026-07-10
Status: VERIFIED PASS or VERIFIED WITH UNRELATED BASELINE FAILURE

## Scope

Stage 3L extends conservative local semantic conflict detection for long-term memories.

## Implemented behavior

- Current name changes conflict.
- Current school changes conflict.
- Current company changes conflict.
- Historical markers prevent current-fact conflict detection.
- Important event memories do not use user-fact conflict patterns.
- Existing exact duplicate, preference polarity, residence, occupation, and goal overlap behavior remains.

## Non-goals

- No LLM contradiction detection.
- No embedding contradiction detection.
- No automatic conflict resolution.
- No automatic overwrite/merge/delete.
- No Stage 4 emotion state.

## Validation

Record exact command outputs:

- `python -m pytest backend/tests/test_repositories.py -q` → result
- `python -m pytest backend/tests/test_repositories.py backend/tests/test_api_memories.py backend/tests/test_memory_candidate_service.py -q` → result
- `python -m pytest backend/tests -q` → result or known unrelated failure

## Stage boundary check

Stage 3L did not implement general contradiction detection, summary generation, automatic conflict resolution, or Stage 4 emotion state.
```

Replace placeholders with observed results.

- [ ] **Step 4: Update `CLAUDE.md` after validation**

Update header:

```markdown
> 当前阶段：**阶段 3——长期记忆（IMPLEMENTING；3A–3L COMPLETED；NEXT: Session Summary Generation Design or Automatic Conflict Resolution Design）**
```

Update Stage 3 row:

```markdown
| 阶段 3：长期记忆 | **IMPLEMENTING** | 当前阶段；3A–3L 已完成；下一步可在会话摘要生成设计或自动冲突解决设计中选择一个最小闭环 |
```

Update completed summary:

```markdown
已完成子任务：3A–3L。已建立手动记忆 CRUD、候选确认、相关性检索、冲突审计、保守语义冲突检测、opt-in embedding retrieval、中文检索评估、隔离真实 embedding 模型评估路径、用户确认式 opt-in LLM 记忆候选抽取、真实 embedding 模型生产选型评估、会话摘要独立存储，以及通用语义矛盾检测扩展。具体证据见 `docs/stage3*.md`。
```

Update current unimplemented line:

```markdown
当前尚未实现：会话摘要生成/注入策略、自动冲突合并/解决工作流、阶段 4 情感系统。
```

Update next minimal loop section:

```markdown
3L 已完成。下一步只能在阶段 3 范围内选择一个最小闭环，例如：

- 会话摘要生成设计：必须复用独立 summary 存储，不得把摘要包装成长期记忆，也不得未经设计直接注入对话上下文。
- 自动冲突解决设计：必须保留审计痕迹，不得静默覆盖、合并或删除冲突记忆。
```

- [ ] **Step 5: Verify status text**

Run:

```powershell
python -c "from pathlib import Path; text = Path('CLAUDE.md').read_text(encoding='utf-8'); assert '3A–3L COMPLETED' in text; assert '阶段 4：情感系统 | 未开始' in text; assert '通用语义矛盾检测扩展' in text; print('CLAUDE.md stage status check PASS')"
```

Expected: PASS.

- [ ] **Step 6: Commit evidence and status**

```powershell
git add docs/stage3l-semantic-conflict-expansion.md CLAUDE.md
git commit -m "docs: record stage 3l semantic conflict expansion"
```

---

### Task 5: Final scope and privacy check

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
python -c "from pathlib import Path; paths=[Path('backend/app/repositories/memories.py'),Path('backend/tests/test_repositories.py'),Path('docs/stage3l-semantic-conflict-expansion.md'),Path('CLAUDE.md')]; needles=['sk-','api_key=','secret=','token=','ANTHROPIC_API_KEY=','DEEPSEEK_API_KEY=']; found=False
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
python -m pytest backend/tests/test_repositories.py backend/tests/test_api_memories.py backend/tests/test_memory_candidate_service.py -q
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

- Spec coverage: Plan covers name, school, company conflicts, historical guard, event non-conflict, validation, evidence, and stage update.
- Placeholder scan: No placeholders remain; evidence doc step explicitly replaces observed command results.
- Type consistency: Uses existing `MemorySemanticSignature`, `MemoryType.USER_FACT`, `_semantic_signature`, and `_semantic_conflict` patterns.
- Scope check: No LLM, embeddings, UI, API contract changes, summary generation, automatic resolution, or Stage 4 work.
- TDD: Each behavior-changing step starts with failing tests before implementation.
