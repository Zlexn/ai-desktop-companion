# Stage 3E Conservative Semantic Conflict Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend memory conflict detection from exact duplicates to a small set of conservative deterministic semantic conflicts.

**Architecture:** Keep `MemoryRepository.find_conflicts(...)` as the single public conflict API. Add private local semantic-signature helpers inside `backend/app/repositories/memories.py`; existing create/update/confirm flows and Stage 3D audit recording automatically consume the expanded conflict results.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, pytest, React/TypeScript/Vite regression only.

---

## Stage boundary

This plan stays inside Stage 3: long-term memory. Do not implement LLM-based contradiction detection, embeddings, vector retrieval, automatic merge/replace conflict resolution, session summaries, LLM-based memory extraction, or Stage 4 emotional state. Do not add mood, trust, concern, distance, irritation, formality, relationship scores, affect decay, or expression strategy state.

## Files to create or modify

### Backend

- Modify: `backend/app/repositories/memories.py`
  - Add internal `MemorySemanticSignature` dataclass.
  - Add deterministic pattern extraction and semantic conflict helpers.
  - Extend `find_conflicts(...)` to include exact duplicates and semantic conflicts.

### Tests

- Modify: `backend/tests/test_repositories.py`
  - Add repository semantic conflict tests.

- Modify: `backend/tests/test_api_memories.py`
  - Add API tests showing semantic conflicts return `conflicts` and create audit events.

### Documentation after verification

- Create: `docs/stage3e-semantic-conflict-detection.md`
- Modify: `CLAUDE.md`

---

## Task 1: Repository semantic conflict detection

**Files:**
- Modify: `backend/app/repositories/memories.py`
- Test: `backend/tests/test_repositories.py`

- [ ] **Step 1: Write failing repository semantic conflict tests**

Add these tests to `backend/tests/test_repositories.py` after `test_same_content_different_memory_type_is_not_conflict` and before audit repository tests:

```python
def test_opposite_preference_polarity_returns_conflict(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        like, _ = memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        dislike, conflicts = memories.create(
            content="用户不喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert [memory.id for memory in conflicts] == [like.id]
        assert memories.require(dislike.id).content == "用户不喜欢红茶。"


def test_different_preference_values_do_not_conflict(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户喜欢咖啡。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert conflicts == []


def test_residence_single_value_fact_conflicts_when_value_changes(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        shanghai, _ = memories.create(
            content="用户住在上海。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户住在北京。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert [memory.id for memory in conflicts] == [shanghai.id]


def test_residence_and_occupation_do_not_conflict(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        memories.create(
            content="用户住在上海。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户的职业是工程师。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert conflicts == []


def test_occupation_single_value_fact_conflicts_when_value_changes(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        student, _ = memories.create(
            content="用户的职业是学生。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户的职业是工程师。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert [memory.id for memory in conflicts] == [student.id]


def test_goal_and_preparation_overlap_returns_conflict(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        goal, _ = memories.create(
            content="用户的目标是完成桌宠项目。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户正在准备完成桌宠项目。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert [memory.id for memory in conflicts] == [goal.id]


def test_different_goals_do_not_conflict(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        memories.create(
            content="用户的目标是完成桌宠项目。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户正在准备考试。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert conflicts == []
```

- [ ] **Step 2: Run repository semantic tests to verify RED**

Run:

```bash
python -m pytest backend/tests/test_repositories.py::test_opposite_preference_polarity_returns_conflict backend/tests/test_repositories.py::test_different_preference_values_do_not_conflict backend/tests/test_repositories.py::test_residence_single_value_fact_conflicts_when_value_changes backend/tests/test_repositories.py::test_residence_and_occupation_do_not_conflict backend/tests/test_repositories.py::test_occupation_single_value_fact_conflicts_when_value_changes backend/tests/test_repositories.py::test_goal_and_preparation_overlap_returns_conflict backend/tests/test_repositories.py::test_different_goals_do_not_conflict -q
```

Expected: FAIL for the three new conflict-positive cases because `find_conflicts(...)` only detects exact normalized duplicates. The non-conflict cases should already pass.

- [ ] **Step 3: Add semantic signature helpers**

Modify `backend/app/repositories/memories.py`.

Add this import after existing imports:

```python
from dataclasses import dataclass
```

Add this dataclass after `_TYPE_HINTS`:

```python
@dataclass(frozen=True)
class MemorySemanticSignature:
    kind: str
    value: str
    polarity: str | None = None
```

Add these helpers after `_normalize_content` or after `_tokens`:

```python
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
```

- [ ] **Step 4: Extend `find_conflicts`**

Replace `find_conflicts(...)` in `backend/app/repositories/memories.py` with:

```python
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
```

- [ ] **Step 5: Run repository semantic tests to verify GREEN**

Run:

```bash
python -m pytest backend/tests/test_repositories.py::test_opposite_preference_polarity_returns_conflict backend/tests/test_repositories.py::test_different_preference_values_do_not_conflict backend/tests/test_repositories.py::test_residence_single_value_fact_conflicts_when_value_changes backend/tests/test_repositories.py::test_residence_and_occupation_do_not_conflict backend/tests/test_repositories.py::test_occupation_single_value_fact_conflicts_when_value_changes backend/tests/test_repositories.py::test_goal_and_preparation_overlap_returns_conflict backend/tests/test_repositories.py::test_different_goals_do_not_conflict -q
```

Expected: PASS.

- [ ] **Step 6: Run repository regression**

Run:

```bash
python -m pytest backend/tests/test_repositories.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit checkpoint if commits are explicitly authorized**

Run only if the user has explicitly authorized commits:

```bash
git add backend/app/repositories/memories.py backend/tests/test_repositories.py
git commit -m "feat: detect semantic memory conflicts"
```

Expected: commit succeeds. If commits are not authorized, skip and mention it in the final report.

---

## Task 2: API semantic conflict and audit coverage

**Files:**
- Modify: `backend/tests/test_api_memories.py`

- [ ] **Step 1: Write failing API semantic conflict tests**

Add these tests to `backend/tests/test_api_memories.py` after `test_duplicate_memory_api_records_conflict_audit_event`:

```python
def test_semantic_memory_conflict_api_records_audit_event(client: TestClient) -> None:
    first = client.post(
        "/api/memories",
        json={"content": "用户喜欢红茶。", "memory_type": "preference", "importance": 3, "confidence": 1.0},
    ).json()["memory"]

    second_response = client.post(
        "/api/memories",
        json={"content": "用户不喜欢红茶。", "memory_type": "preference", "importance": 3, "confidence": 1.0},
    )

    assert second_response.status_code == 201
    second_body = second_response.json()
    assert [item["id"] for item in second_body["conflicts"]] == [first["id"]]
    events = client.get("/api/memories/audit-events").json()
    assert len(events) == 1
    assert events[0]["operation"] == "create"
    assert events[0]["memory_id"] == second_body["memory"]["id"]
    assert events[0]["related_memory_ids"] == [first["id"]]


def test_non_conflicting_same_type_memory_api_does_not_record_audit_event(client: TestClient) -> None:
    client.post(
        "/api/memories",
        json={"content": "用户喜欢红茶。", "memory_type": "preference", "importance": 3, "confidence": 1.0},
    )

    second_response = client.post(
        "/api/memories",
        json={"content": "用户喜欢咖啡。", "memory_type": "preference", "importance": 3, "confidence": 1.0},
    )

    assert second_response.status_code == 201
    assert second_response.json()["conflicts"] == []
    assert client.get("/api/memories/audit-events").json() == []
```

- [ ] **Step 2: Run API semantic tests to verify GREEN**

Run after Task 1 implementation:

```bash
python -m pytest backend/tests/test_api_memories.py::test_semantic_memory_conflict_api_records_audit_event backend/tests/test_api_memories.py::test_non_conflicting_same_type_memory_api_does_not_record_audit_event -q
```

Expected: PASS because API routes already consume repository conflicts and Stage 3D audit recording.

If this unexpectedly passes before Task 1, stop and inspect whether semantic conflict detection already exists.

- [ ] **Step 3: Run memory API regression**

Run:

```bash
python -m pytest backend/tests/test_api_memories.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit checkpoint if commits are explicitly authorized**

Run only if the user has explicitly authorized commits:

```bash
git add backend/tests/test_api_memories.py
git commit -m "test: cover semantic memory conflict API"
```

Expected: commit succeeds. If commits are not authorized, skip and mention it in the final report.

---

## Task 3: Final regression, evidence documentation, and CLAUDE.md update

**Files:**
- Create: `docs/stage3e-semantic-conflict-detection.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run focused Stage 3E backend tests**

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

Expected: no real secrets. Existing configuration names, fake test strings, and non-secret terms are acceptable.

- [ ] **Step 8: Create evidence document**

Create `docs/stage3e-semantic-conflict-detection.md` with exact command results:

```markdown
# Stage 3E Conservative Semantic Conflict Detection Evidence

Status: COMPLETED on 2026-07-07.

## Scope

This slice implements conservative local semantic conflict detection for long-term memories:

- Opposite preference polarity on the same value is detected as conflict.
- Current residence and occupation single-value facts conflict when the value changes.
- Simple goal/preparation overlap is detected as conflict-like duplicate/overlap.
- Existing exact duplicate conflict behavior remains.
- Existing Stage 3D audit recording captures these semantic conflicts through unchanged API routes.

It does not implement LLM contradiction detection, vector retrieval, embeddings, automatic conflict resolution, session summaries, LLM-based memory extraction, or Stage 4 emotion state.

## Implemented behavior

- `MemoryRepository.find_conflicts(...)` now checks exact normalized duplicates and conservative semantic signatures.
- Unrecognized memory text fails closed and does not produce semantic conflicts.
- API mutation responses return semantic conflicts through the existing `conflicts` field.
- Stage 3D audit events are recorded for semantic conflicts without route contract changes.

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

- Repository tests first failed for semantic conflict-positive cases because only exact duplicate detection existed.
- API semantic conflict tests pass through existing route/audit behavior after repository conflict detection was extended.

## Privacy and safety check

Task-related secret scan checked changed backend tests, repository code, docs, and `CLAUDE.md` files for likely key/secret/token strings. No real secret was found.

## Limitations

- Semantic detection is intentionally conservative and pattern-based.
- It is not general-purpose contradiction detection.
- Residence and occupation are treated as current single-value facts.
- Goal overlap is flagged for review but not automatically merged.
- No vector/embedding retrieval is implemented.
- No LLM-based memory extraction is implemented.
- Stage 4 emotion state is not implemented.
```

Replace all `replace with exact ...` text with real command output before saving.

- [ ] **Step 9: Update CLAUDE.md after validation**

Modify the Stage 3 current entrance section in `CLAUDE.md` to add a new bullet after Stage 3D:

```markdown
- 3E Conservative Semantic Conflict Detection 已完成（2026-07-07；新增本地 deterministic semantic signature 冲突检测，覆盖偏好极性、居住地/职业单值事实变化和简单目标/准备事项重叠；复用 3D audit event 和前端冲突明细；证据记录于 `docs/stage3e-semantic-conflict-detection.md`）。验证：后端测试 PASS；前端测试 PASS；typecheck PASS；build PASS；Playwright E2E PASS。
```

Update the pending line:

```markdown
- 当前尚未实现通用语义矛盾检测、vector/embedding retrieval、会话摘要、LLM-based 记忆抽取、自动冲突合并/解决工作流或阶段 4 情感系统。
- 下一最小完整闭环应继续阶段 3 内的 vector/embedding retrieval、更强的用户确认式 LLM 候选抽取，或会话摘要的独立存储设计；必须保持聊天历史、会话摘要和长期记忆分离；不得把最近聊天记录包装成长期记忆；不得提前实现阶段 4 情感系统。
```

Only update `CLAUDE.md` after all validation commands pass.

- [ ] **Step 10: Commit final checkpoint if commits are explicitly authorized**

Run only if the user has explicitly authorized commits:

```bash
git add backend/app/repositories/memories.py backend/tests/test_repositories.py backend/tests/test_api_memories.py docs/stage3e-semantic-conflict-detection.md CLAUDE.md
git commit -m "feat: detect semantic memory conflicts"
```

Expected: commit succeeds. If commits are not authorized, skip and mention it in the final report.

---

## Self-review checklist

- Spec coverage: Tasks cover conservative semantic signatures, preference polarity conflicts, residence/occupation single-value fact conflicts, goal/preparation overlap, API conflict/audit propagation, regressions, evidence docs, and `CLAUDE.md` update after validation.
- Placeholder scan: The plan contains no open implementation placeholders. The evidence document step intentionally requires replacing validation placeholders with exact observed command output before saving.
- Type consistency: `MemorySemanticSignature`, `_semantic_signature`, `_semantic_conflict`, `_normalize_semantic_value`, and `_strip_goal_prefix` are named consistently.
- Stage boundary: No task implements Stage 4 emotion state, embeddings, vector retrieval, LLM extraction/reranking, general semantic contradiction detection, session summaries, or automatic conflict merge/resolve.
- Commit policy: Commit steps are gated on explicit user authorization; do not commit during this session unless separately instructed.
