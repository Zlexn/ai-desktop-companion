# Stage 3C Memory Relevance Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make chat memory context select active long-term memories relevant to the current user message instead of always injecting the highest-importance recent memories.

**Architecture:** Add deterministic local relevance retrieval to `MemoryRepository`, controlled by small configuration settings and consumed by `ContextBuilder`. `ChatService` passes the current cleaned user message as the retrieval query; no frontend behavior, external provider, vector database, or Stage 4 emotion state is introduced.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, pytest, React/TypeScript/Vite regression only.

---

## Stage boundary

This plan stays inside Stage 3: long-term memory. Do not implement vector retrieval, embeddings, LLM reranking, semantic contradiction detection, session summaries, audit-log expansion, or Stage 4 emotional state. Do not add mood, trust, concern, distance, irritation, formality, relationship scores, affect decay, or expression strategy state.

## Files to create or modify

### Backend

- Modify: `backend/app/core/config.py`
  - Add `memory_retrieval_mode` and `memory_retrieval_fallback_limit` settings.
  - Validate allowed retrieval modes and fallback bounds.
  - Add redacted settings entries.

- Modify: `backend/app/repositories/memories.py`
  - Add local token/type-hint scoring helpers.
  - Add `list_relevant_for_context(query: str, limit: int, fallback_limit: int) -> list[Memory]`.
  - Keep `list_for_context(limit)` as the recent/importance fallback path.

- Modify: `backend/app/services/context_builder.py`
  - Accept retrieval mode and fallback limit in constructor.
  - Add `query` arguments to `build_memory_context` and `build_context`.
  - Use relevance retrieval when enabled and query is present.

- Modify: `backend/app/api/dependencies.py`
  - Pass new retrieval settings into `ContextBuilder`.

- Modify: `backend/app/services/chat_service.py`
  - Pass `clean_text` as `query` into `ContextBuilder.build_context(...)`.

### Tests

- Modify: `backend/tests/test_config.py`
  - Add retrieval settings parse/validation tests.

- Modify: `backend/tests/test_repositories.py`
  - Add relevance ordering, status exclusion, type-hint boost, and fallback-limit tests.

- Modify: `backend/tests/test_context_builder.py`
  - Add query-aware memory context tests.

- Modify: `backend/tests/test_chat_service.py`
  - Add provider-message assertions proving `ChatService` sends relevant memory and excludes unrelated memory.

### Documentation after verification

- Create: `docs/stage3c-memory-relevance-retrieval.md`
- Modify: `CLAUDE.md`

---

## Task 1: Retrieval configuration

**Files:**
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_config.py`

- [ ] **Step 1: Write failing config tests**

Add `MEMORY_RETRIEVAL_MODE` and `MEMORY_RETRIEVAL_FALLBACK_LIMIT` to the `clear_env` fixture tuple in `backend/tests/test_config.py`:

```python
        "MEMORY_RETRIEVAL_MODE",
        "MEMORY_RETRIEVAL_FALLBACK_LIMIT",
```

Add these tests after `test_memory_context_settings`:

```python
def test_memory_retrieval_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_RETRIEVAL_MODE", "recent")
    monkeypatch.setenv("MEMORY_RETRIEVAL_FALLBACK_LIMIT", "2")

    settings = load_settings()

    assert settings.memory_retrieval_mode == "recent"
    assert settings.memory_retrieval_fallback_limit == 2
    assert settings.redacted()["memory_retrieval_mode"] == "recent"
    assert settings.redacted()["memory_retrieval_fallback_limit"] == 2


def test_rejects_unknown_memory_retrieval_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_RETRIEVAL_MODE", "vector")

    with pytest.raises(ValueError, match="MEMORY_RETRIEVAL_MODE must be one of: relevance, recent"):
        load_settings()


def test_memory_retrieval_fallback_limit_must_not_exceed_context_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_CONTEXT_LIMIT", "2")
    monkeypatch.setenv("MEMORY_RETRIEVAL_FALLBACK_LIMIT", "3")

    with pytest.raises(ValueError, match="MEMORY_RETRIEVAL_FALLBACK_LIMIT must be less than or equal to MEMORY_CONTEXT_LIMIT"):
        load_settings()
```

- [ ] **Step 2: Run config tests to verify RED**

Run:

```bash
python -m pytest backend/tests/test_config.py::test_memory_retrieval_settings backend/tests/test_config.py::test_rejects_unknown_memory_retrieval_mode backend/tests/test_config.py::test_memory_retrieval_fallback_limit_must_not_exceed_context_limit -q
```

Expected: FAIL because `Settings.memory_retrieval_mode` and `Settings.memory_retrieval_fallback_limit` do not exist.

- [ ] **Step 3: Add settings fields and validation**

Modify `backend/app/core/config.py`.

Add fields after `memory_context_limit`:

```python
    memory_retrieval_mode: str = "relevance"
    memory_retrieval_fallback_limit: int = 3
```

Add redacted entries after `memory_context_limit`:

```python
            "memory_retrieval_mode": self.memory_retrieval_mode,
            "memory_retrieval_fallback_limit": self.memory_retrieval_fallback_limit,
```

In `load_settings()`, after memory candidate provider validation, add:

```python
    memory_context_limit = _get_positive_int_env("MEMORY_CONTEXT_LIMIT", 8)
    memory_retrieval_mode = _get_env("MEMORY_RETRIEVAL_MODE", "relevance").lower()
    if memory_retrieval_mode not in {"relevance", "recent"}:
        raise ValueError("MEMORY_RETRIEVAL_MODE must be one of: relevance, recent")
    memory_retrieval_fallback_limit = _get_positive_int_env("MEMORY_RETRIEVAL_FALLBACK_LIMIT", 3)
    if memory_retrieval_fallback_limit > memory_context_limit:
        raise ValueError("MEMORY_RETRIEVAL_FALLBACK_LIMIT must be less than or equal to MEMORY_CONTEXT_LIMIT")
```

In the `Settings(...)` construction, replace the existing direct context limit assignment:

```python
        memory_context_limit=_get_positive_int_env("MEMORY_CONTEXT_LIMIT", 8),
```

with:

```python
        memory_context_limit=memory_context_limit,
        memory_retrieval_mode=memory_retrieval_mode,
        memory_retrieval_fallback_limit=memory_retrieval_fallback_limit,
```

- [ ] **Step 4: Run config tests to verify GREEN**

Run:

```bash
python -m pytest backend/tests/test_config.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit checkpoint if commits are explicitly authorized**

Run only if the user has explicitly authorized commits:

```bash
git add backend/app/core/config.py backend/tests/test_config.py
git commit -m "feat: add memory retrieval settings"
```

Expected: commit succeeds. If commits are not authorized, skip and mention it in the final report.

---

## Task 2: Repository relevance retrieval

**Files:**
- Modify: `backend/app/repositories/memories.py`
- Test: `backend/tests/test_repositories.py`

- [ ] **Step 1: Write failing repository relevance tests**

Add these tests to `backend/tests/test_repositories.py` after the existing memory candidate lifecycle tests:

```python
def test_relevant_memory_outranks_unrelated_high_importance_memory(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        unrelated, _ = memories.create(
            content="用户正在构建本地 AI 桌宠。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=5,
            confidence=1.0,
            metadata={},
        )
        relevant, _ = memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=2,
            confidence=0.8,
            metadata={},
        )

        results = memories.list_relevant_for_context("我喜欢什么饮料？", limit=4, fallback_limit=2)

        assert [memory.id for memory in results] == [relevant.id]
        assert unrelated.id not in [memory.id for memory in results]


def test_relevant_context_excludes_non_active_memories(database_url: str) -> None:
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
        pending, _ = memories.create_candidate(
            content="用户喜欢咖啡。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=0.7,
            metadata={},
        )
        assert pending is not None
        dismissed, _ = memories.create_candidate(
            content="用户喜欢牛奶。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=0.7,
            metadata={},
        )
        assert dismissed is not None
        memories.dismiss_candidate(dismissed.id)
        archived, _ = memories.create(
            content="用户喜欢果汁。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )
        memories.archive(archived.id)

        results = memories.list_relevant_for_context("我喜欢什么？", limit=8, fallback_limit=3)

        assert [memory.id for memory in results] == [active.id]


def test_type_hint_boosts_matching_memory_type(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        preference, _ = memories.create(
            content="用户喜欢桌宠项目。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )
        goal, _ = memories.create(
            content="用户的目标是完成桌宠项目。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        results = memories.list_relevant_for_context("我的目标计划是什么？", limit=2, fallback_limit=1)

        assert [memory.id for memory in results][:2] == [goal.id, preference.id]


def test_relevance_falls_back_to_small_high_priority_set_when_no_match(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        first, _ = memories.create(
            content="用户正在构建本地 AI 桌宠。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=5,
            confidence=1.0,
            metadata={},
        )
        second, _ = memories.create(
            content="用户偏好中文回复。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=4,
            confidence=1.0,
            metadata={},
        )
        third, _ = memories.create(
            content="用户住在上海。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        results = memories.list_relevant_for_context("今天天气怎么样？", limit=8, fallback_limit=2)

        assert [memory.id for memory in results] == [first.id, second.id]
        assert third.id not in [memory.id for memory in results]
```

- [ ] **Step 2: Run repository tests to verify RED**

Run:

```bash
python -m pytest backend/tests/test_repositories.py::test_relevant_memory_outranks_unrelated_high_importance_memory backend/tests/test_repositories.py::test_relevant_context_excludes_non_active_memories backend/tests/test_repositories.py::test_type_hint_boosts_matching_memory_type backend/tests/test_relevance_falls_back_to_small_high_priority_set_when_no_match -q
```

Expected: FAIL because `MemoryRepository.list_relevant_for_context` does not exist.

- [ ] **Step 3: Add local scoring helpers**

Modify `backend/app/repositories/memories.py`.

Add imports near the top:

```python
import re
```

Add these constants and helpers after `_normalize_content`:

```python
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
```

- [ ] **Step 4: Add repository relevance method**

Add this method to `MemoryRepository` after `list_for_context`:

```python
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
```

- [ ] **Step 5: Run repository tests to verify GREEN**

Run:

```bash
python -m pytest backend/tests/test_repositories.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit checkpoint if commits are explicitly authorized**

Run only if the user has explicitly authorized commits:

```bash
git add backend/app/repositories/memories.py backend/tests/test_repositories.py
git commit -m "feat: add relevant memory retrieval"
```

Expected: commit succeeds. If commits are not authorized, skip and mention it in the final report.

---

## Task 3: ContextBuilder query-aware retrieval

**Files:**
- Modify: `backend/app/services/context_builder.py`
- Test: `backend/tests/test_context_builder.py`

- [ ] **Step 1: Write failing ContextBuilder tests**

Add these tests to `backend/tests/test_context_builder.py` after `test_memory_context_is_caveated_and_separate`:

```python
def test_memory_context_uses_query_relevance(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'memory-context-relevance.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        session = sessions.create("相关记忆")
        messages.add(session.id, ChatRole.USER, "我喜欢什么饮料？")
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
            memory_retrieval_mode="relevance",
            memory_retrieval_fallback_limit=2,
        )

        context = builder.build_memory_context(query="我喜欢什么饮料？")

        assert len(context) == 1
        assert "长期记忆记录" in context[0].content
        assert "不得描述为绝对事实" in context[0].content
        assert "用户喜欢红茶。" in context[0].content
        assert "用户正在构建本地 AI 桌宠。" not in context[0].content


def test_memory_context_recent_mode_keeps_existing_ordering(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'memory-context-recent.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        session = sessions.create("最近记忆")
        high, _ = memories.create(
            content="用户正在构建本地 AI 桌宠。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=5,
            confidence=1.0,
            metadata={},
        )
        low, _ = memories.create(
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
            memory_retrieval_mode="recent",
            memory_retrieval_fallback_limit=2,
        )

        context = builder.build_memory_context(query="我喜欢什么饮料？")

        assert high.content in context[0].content
        assert low.content in context[0].content
```

- [ ] **Step 2: Run ContextBuilder tests to verify RED**

Run:

```bash
python -m pytest backend/tests/test_context_builder.py::test_memory_context_uses_query_relevance backend/tests/test_context_builder.py::test_memory_context_recent_mode_keeps_existing_ordering -q
```

Expected: FAIL because `ContextBuilder` does not accept retrieval settings or query arguments.

- [ ] **Step 3: Update ContextBuilder constructor and methods**

Modify `backend/app/services/context_builder.py`.

Update constructor signature:

```python
        memory_context_limit: int = 8,
        memory_retrieval_mode: str = "relevance",
        memory_retrieval_fallback_limit: int = 3,
```

Add assignments:

```python
        self._memory_retrieval_mode = memory_retrieval_mode
        self._memory_retrieval_fallback_limit = memory_retrieval_fallback_limit
```

Replace `build_memory_context` and `build_context` with:

```python
    def build_memory_context(self, query: str | None = None) -> list[LLMMessage]:
        if not self._memory_context_enabled or self._memories is None:
            return []
        if self._memory_retrieval_mode == "relevance" and query and query.strip():
            memories = self._memories.list_relevant_for_context(
                query,
                self._memory_context_limit,
                self._memory_retrieval_fallback_limit,
            )
        else:
            memories = self._memories.list_for_context(self._memory_context_limit)
        if not memories:
            return []
        lines = [
            "以下是用户可查看、可修改、可删除的长期记忆记录，仅作为回复时的参考上下文；",
            "它们可能过时或不完整，不得描述为绝对事实，也不得声称你具有真实人类记忆。",
        ]
        lines.extend(self._format_memory(memory) for memory in memories)
        return [LLMMessage(role=ChatRole.SYSTEM, content="\n".join(lines))]

    def build_context(self, session_id: str, query: str | None = None) -> list[LLMMessage]:
        return [*self.build_memory_context(query=query), *self.build_recent_context(session_id)]
```

- [ ] **Step 4: Run ContextBuilder tests to verify GREEN**

Run:

```bash
python -m pytest backend/tests/test_context_builder.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit checkpoint if commits are explicitly authorized**

Run only if the user has explicitly authorized commits:

```bash
git add backend/app/services/context_builder.py backend/tests/test_context_builder.py
git commit -m "feat: use relevance retrieval in context builder"
```

Expected: commit succeeds. If commits are not authorized, skip and mention it in the final report.

---

## Task 4: Dependency wiring and ChatService query pass-through

**Files:**
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/app/services/chat_service.py`
- Test: `backend/tests/test_chat_service.py`

- [ ] **Step 1: Write failing ChatService relevance test**

Add imports at the top of `backend/tests/test_chat_service.py` if missing:

```python
from app.domain.models import MemorySource, MemoryType
from app.repositories.memories import MemoryRepository
```

Add this test after `test_chat_service_sends_system_prompt_and_full_recent_context_on_second_turn`:

```python
@pytest.mark.asyncio
async def test_chat_service_passes_current_user_text_for_memory_relevance(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'chat_relevant_memory.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        session = sessions.create("相关记忆聊天")
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
                memory_retrieval_mode="relevance",
                memory_retrieval_fallback_limit=2,
            ),
            default_prompt_renderer(),
            provider,
            Settings(llm_model="test-model"),
        )

        await service.send_message(session.id, "我喜欢什么饮料？")

        sent_contents = [message.content for message in provider.calls[0]]
        memory_context = sent_contents[1]
        assert "用户喜欢红茶。" in memory_context
        assert "用户正在构建本地 AI 桌宠。" not in memory_context
```

- [ ] **Step 2: Run ChatService test to verify RED**

Run:

```bash
python -m pytest backend/tests/test_chat_service.py::test_chat_service_passes_current_user_text_for_memory_relevance -q
```

Expected: FAIL because `ChatService` calls `build_context(session_id)` without a query.

- [ ] **Step 3: Pass query from ChatService**

Modify `backend/app/services/chat_service.py`:

```python
        context = self._context_builder.build_context(session_id, query=clean_text)
```

replacing:

```python
        context = self._context_builder.build_context(session_id)
```

- [ ] **Step 4: Pass retrieval settings from dependencies**

Modify `backend/app/api/dependencies.py` `ContextBuilder(...)` construction to include:

```python
        memory_retrieval_mode=settings.memory_retrieval_mode,
        memory_retrieval_fallback_limit=settings.memory_retrieval_fallback_limit,
```

The full construction should be:

```python
    context_builder = ContextBuilder(
        messages,
        settings.recent_context_messages,
        memories=memories,
        memory_context_enabled=settings.memory_context_enabled,
        memory_context_limit=settings.memory_context_limit,
        memory_retrieval_mode=settings.memory_retrieval_mode,
        memory_retrieval_fallback_limit=settings.memory_retrieval_fallback_limit,
    )
```

- [ ] **Step 5: Run ChatService tests to verify GREEN**

Run:

```bash
python -m pytest backend/tests/test_chat_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Run focused backend retrieval tests**

Run:

```bash
python -m pytest backend/tests/test_config.py backend/tests/test_repositories.py backend/tests/test_context_builder.py backend/tests/test_chat_service.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit checkpoint if commits are explicitly authorized**

Run only if the user has explicitly authorized commits:

```bash
git add backend/app/api/dependencies.py backend/app/services/chat_service.py backend/tests/test_chat_service.py
git commit -m "feat: pass user query to memory retrieval"
```

Expected: commit succeeds. If commits are not authorized, skip and mention it in the final report.

---

## Task 5: Final regression and evidence documentation

**Files:**
- Create: `docs/stage3c-memory-relevance-retrieval.md`
- Modify: `CLAUDE.md`

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

Create `docs/stage3c-memory-relevance-retrieval.md` with exact command results:

```markdown
# Stage 3C Memory Relevance Retrieval Evidence

Status: COMPLETED on 2026-07-07.

## Scope

This slice implements Stage 3C long-term memory relevance retrieval:

- Active memories can be selected by relevance to the current user message.
- Relevant memories can outrank unrelated high-importance memories.
- Pending, dismissed, and archived memories remain excluded from chat context.
- Retrieval remains local, deterministic, dependency-free, and configurable.
- Existing recent/importance ordering remains available via `MEMORY_RETRIEVAL_MODE=recent`.

It does not implement vector retrieval, embeddings, LLM reranking, semantic contradiction detection, session summaries, audit-log expansion, or Stage 4 emotion state.

## Implemented behavior

- `MEMORY_RETRIEVAL_MODE=relevance` is the default.
- `MEMORY_RETRIEVAL_MODE=recent` preserves previous memory context ordering.
- `MEMORY_RETRIEVAL_FALLBACK_LIMIT` caps fallback memories when no relevant match exists.
- `ChatService` passes the current user message to `ContextBuilder` as the memory retrieval query.
- Memory context caveats remain present.

## Validation

| Command | Result |
|---|---|
| `python -m pytest backend/tests` | PASS — replace with exact count |
| `npm --prefix frontend test -- --run` | PASS — replace with exact count |
| `npm --prefix frontend run typecheck` | PASS |
| `npm --prefix frontend run build` | PASS — replace with exact Vite output summary |
| `npm --prefix frontend run test:e2e` | PASS — replace with exact count |

## TDD notes

- Config tests first failed because retrieval settings did not exist.
- Repository tests first failed because `list_relevant_for_context` did not exist.
- ContextBuilder tests first failed because query-aware retrieval was not supported.
- ChatService tests first failed because the current user text was not passed to context building.

## Limitations

- Retrieval uses simple local token/type-hint scoring.
- Chinese tokenization is lightweight and conservative.
- No vector/embedding retrieval is implemented.
- No LLM reranker is implemented.
- No semantic contradiction detection is implemented.
- No session summaries are implemented.
- Stage 4 emotion state is not implemented.
```

Replace all `replace with exact ...` text with actual command output before saving.

- [ ] **Step 7: Update CLAUDE.md after verification**

Modify the Stage 3 current entrance section in `CLAUDE.md` to add a new bullet after Stage 3B:

```markdown
- 3C Memory Relevance Retrieval 已完成（2026-07-07；新增 active 长期记忆按当前用户消息相关性检索、本地 deterministic token/type-hint scoring、无相关命中时小规模 fallback、`MEMORY_RETRIEVAL_MODE=recent` 兼容路径；pending/dismissed/archived 仍不进入上下文；证据记录于 `docs/stage3c-memory-relevance-retrieval.md`）。验证：后端测试 PASS；前端测试 PASS；typecheck PASS；build PASS；Playwright E2E PASS。
```

Update the next-step bullet to remove plain retrieval enhancement as pending:

```markdown
- 当前尚未实现语义冲突检测、vector/embedding retrieval、会话摘要、LLM-based 记忆抽取或阶段 4 情感系统。
- 下一最小完整闭环应继续阶段 3 内的语义冲突/审计增强、vector/embedding retrieval，或更强的用户确认式 LLM 候选抽取；必须保持聊天历史、会话摘要和长期记忆分离；不得把最近聊天记录包装成长期记忆；不得提前实现阶段 4 情感系统。
```

Only update `CLAUDE.md` after all validation commands pass.

- [ ] **Step 8: Run task-related sensitive data scan**

Run content search on task-related files:

```bash
# Use the dedicated Grep tool if available; otherwise run ripgrep for:
# api[_-]?key|secret|token|sk-[a-z0-9]|password|credential
```

Expected: no real secrets. Configuration field names such as `anthropic_api_key` are acceptable if already existing and redacted.

- [ ] **Step 9: Commit final checkpoint if commits are explicitly authorized**

Run only if the user has explicitly authorized commits:

```bash
git add backend/app/core/config.py backend/app/repositories/memories.py backend/app/services/context_builder.py backend/app/api/dependencies.py backend/app/services/chat_service.py backend/tests/test_config.py backend/tests/test_repositories.py backend/tests/test_context_builder.py backend/tests/test_chat_service.py docs/stage3c-memory-relevance-retrieval.md CLAUDE.md
git commit -m "feat: add relevant memory retrieval"
```

Expected: commit succeeds. If commits are not authorized, skip and mention it in the final report.

---

## Self-review checklist

- Spec coverage: Tasks cover retrieval config, deterministic scoring, active-only scope, fallback behavior, ContextBuilder query support, ChatService query pass-through, regression, evidence docs, and CLAUDE.md update after validation.
- Placeholder scan: No open implementation placeholders remain. The evidence document step explicitly requires replacing validation counts with real command output before saving.
- Type consistency: Plan uses `memory_retrieval_mode`, `memory_retrieval_fallback_limit`, `list_relevant_for_context(query, limit, fallback_limit)`, `build_memory_context(query=...)`, and `build_context(session_id, query=...)` consistently.
- Stage boundary: No task implements Stage 4 emotion state, embeddings, vector retrieval, LLM reranking, semantic contradiction detection, or session summaries.
- Commit policy: Commit steps are gated on explicit user authorization; do not commit during this session unless separately instructed.
