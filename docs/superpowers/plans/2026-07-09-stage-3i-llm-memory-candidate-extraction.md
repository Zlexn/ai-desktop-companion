# Stage 3I LLM Memory Candidate Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in LLM memory-candidate extractor that only turns the current user message into pending candidates and never bypasses user confirmation.

**Architecture:** Keep `MemoryCandidateService` as the only writer of candidate memories. Add a narrow `MemoryCandidateLLMExtractor` inside `backend/app/services/memory_candidate_service.py` that reuses the existing `LLMProvider`, parses provider-neutral JSON text, validates it defensively, and returns drafts. `ChatService` awaits extraction after a successful assistant reply; extraction remains best-effort and cannot break chat.

**Tech Stack:** Python 3.11+, FastAPI service dependencies, existing `LLMProvider` abstraction, SQLite memory repository, pytest.

---

## Scope and Boundaries

This plan implements the approved minimal backend 3I loop only.

It includes:

- `MEMORY_CANDIDATE_PROVIDER=llm` opt-in behavior.
- Default `heuristic` behavior unchanged.
- LLM extraction from the current user message only.
- `pending` memory candidates only.
- Existing user confirmation flow for active memories.
- Backend tests and Stage 3I evidence documentation.

It excludes:

- Frontend runtime changes.
- Runtime provider toggle UI.
- Conversation history backfill.
- Session summaries.
- Hybrid heuristic+LLM mode.
- Automatic active memory writes.
- Automatic conflict resolution.
- Stage 4 emotion state or emotional relationship fields.

## File Structure

- Modify `backend/app/services/memory_candidate_service.py`
  - Add `MemoryCandidateLLMExtractor`.
  - Extend `MemoryCandidateDraft` with optional `importance`, `confidence`, `source_quote`, `extraction_provider`, and `extraction_schema` fields.
  - Change candidate creation to async so LLM extraction can await `LLMProvider.generate(...)`.
  - Keep heuristic extraction synchronous internally and preserve its existing candidate metadata.

- Modify `backend/app/services/chat_service.py`
  - Await candidate extraction after the assistant reply is stored.
  - Keep the existing broad try/except around extraction so chat success is isolated from extraction failures.

- Modify `backend/app/api/dependencies.py`
  - Pass the configured `LLMProvider` into `MemoryCandidateService` so the service can construct the LLM extractor only when configured.

- Modify `backend/tests/test_memory_candidate_service.py`
  - Convert service calls to async where needed.
  - Add LLM extraction tests using the existing `StubLLMProvider`.

- Modify `backend/tests/test_chat_memory_candidates.py`
  - Add chat integration coverage for LLM extraction failure isolation.
  - Add coverage that pending candidates do not enter chat context before confirmation.

- Modify `backend/tests/test_config.py`
  - Verify existing Stage 3I config support remains covered. The current file already contains tests for `MEMORY_CANDIDATE_PROVIDER=llm`; only edit if current tests are missing or failing.

- Create `docs/stage3i-llm-memory-candidate-extraction.md`
  - Record implementation scope, configuration keys, validation commands/results, privacy limits, real-provider smoke status, user-confirmation boundary, and Stage 4 boundary.

- Modify `CLAUDE.md`
  - Only after tests pass, mark 3I complete and update the next allowed Stage 3 task.

No frontend file is planned for this minimal implementation. If a frontend file is changed by accident, stop and either revert it or add explicit frontend validation.

## Tasks

### Task 1: Write RED tests for LLM extractor behavior

**Files:**
- Modify: `backend/tests/test_memory_candidate_service.py`
- Test only; no production code in this task.

- [ ] **Step 1: Import pytest asyncio support if missing**

Ensure the top of `backend/tests/test_memory_candidate_service.py` still contains these imports:

```python
import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.errors import ProviderError
from app.domain.models import ChatRole, MemoryStatus, MemoryType
from app.providers.base import LLMMessage, LLMOptions, LLMResponse
from app.repositories.memories import MemoryRepository
from app.repositories.sqlite import managed_connection
from app.services.memory_candidate_service import MemoryCandidateService
```

- [ ] **Step 2: Convert existing sync service calls to await**

Change existing calls like this:

```python
created = service.create_candidates_from_user_text(
    session_id=None,
    user_text="我喜欢红茶。",
)
```

to this shape, and mark each affected test with `@pytest.mark.asyncio`:

```python
@pytest.mark.asyncio
async def test_heuristic_extracts_explicit_like_statement(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        service = MemoryCandidateService(memories, Settings(memory_candidates_enabled=True))

        created = await service.create_candidates_from_user_text(
            session_id=None,
            user_text="我喜欢红茶。",
        )

        assert len(created) == 1
```

Apply the same `await` conversion to all existing `create_candidates_from_user_text(...)` calls in this file.

- [ ] **Step 3: Add a valid LLM candidate test**

Append this test to `backend/tests/test_memory_candidate_service.py`:

```python
@pytest.mark.asyncio
async def test_llm_provider_creates_pending_candidate_with_safe_metadata(database_url: str) -> None:
    payload = {
        "candidates": [
            {
                "content": "用户喜欢红茶。",
                "memory_type": "preference",
                "confidence": 0.92,
                "importance": 4,
                "source_quote": "我喜欢红茶",
                "reason": "explicit_preference_statement",
                "should_create_candidate": True,
            }
        ]
    }
    provider = StubLLMProvider(json.dumps(payload, ensure_ascii=False))
    settings = Settings(memory_candidates_enabled=True, memory_candidate_provider="llm")

    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        service = MemoryCandidateService(memories, settings, llm_provider=provider)

        created = await service.create_candidates_from_user_text(
            session_id="session-1",
            user_text="我喜欢红茶，也喜欢安静的晚上。",
        )

        assert len(created) == 1
        memory = created[0]
        assert memory.content == "用户喜欢红茶。"
        assert memory.memory_type == MemoryType.PREFERENCE
        assert memory.status == MemoryStatus.PENDING
        assert memory.importance == 4
        assert memory.confidence == 0.92
        assert memory.source_session_id == "session-1"
        assert memory.metadata["candidate_reason"] == "explicit_preference_statement"
        assert memory.metadata["extraction_provider"] == "llm"
        assert memory.metadata["extraction_schema"] == "memory_extraction_schema_v1"
        assert memory.metadata["source_quote"] == "我喜欢红茶"
        assert memory.metadata["raw_confidence"] == 0.92
        assert "candidates" not in memory.metadata
        assert len(provider.calls) == 1
        messages, options = provider.calls[0]
        assert options.model == settings.llm_model
        assert options.max_tokens == settings.memory_candidate_llm_max_tokens
        assert options.timeout_seconds == settings.memory_candidate_llm_timeout_seconds
        assert messages[-1].content == "我喜欢红茶，也喜欢安静的晚上。"
```

- [ ] **Step 4: Add filtering tests**

Append this parametrized test:

```python
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "candidate",
    [
        {
            "content": "用户喜欢红茶。",
            "memory_type": "preference",
            "confidence": 0.95,
            "importance": 3,
            "source_quote": "我喜欢红茶",
            "reason": "explicit_preference_statement",
            "should_create_candidate": False,
        },
        {
            "content": "用户喜欢红茶。",
            "memory_type": "preference",
            "confidence": 0.2,
            "importance": 3,
            "source_quote": "我喜欢红茶",
            "reason": "low_confidence_statement",
            "should_create_candidate": True,
        },
        {
            "content": "用户喜欢红茶。",
            "memory_type": "emotion_state",
            "confidence": 0.95,
            "importance": 3,
            "source_quote": "我喜欢红茶",
            "reason": "invalid_memory_type",
            "should_create_candidate": True,
        },
        {
            "content": "用户喜欢红茶。",
            "memory_type": "preference",
            "confidence": 0.95,
            "importance": 6,
            "source_quote": "我喜欢红茶",
            "reason": "invalid_importance",
            "should_create_candidate": True,
        },
        {
            "content": "",
            "memory_type": "preference",
            "confidence": 0.95,
            "importance": 3,
            "source_quote": "我喜欢红茶",
            "reason": "empty_content",
            "should_create_candidate": True,
        },
        {
            "content": "用户喜欢咖啡。",
            "memory_type": "preference",
            "confidence": 0.95,
            "importance": 3,
            "source_quote": "我喜欢咖啡",
            "reason": "invented_quote",
            "should_create_candidate": True,
        },
        {
            "content": "用户的 API Key 是 sk-test-secret。",
            "memory_type": "user_fact",
            "confidence": 0.95,
            "importance": 5,
            "source_quote": "我的 API Key 是 sk-test-secret",
            "reason": "secret_statement",
            "should_create_candidate": True,
        },
        {
            "content": "助手喜欢红茶。",
            "memory_type": "preference",
            "confidence": 0.95,
            "importance": 3,
            "source_quote": "我喜欢红茶",
            "reason": "assistant_subject",
            "should_create_candidate": True,
        },
    ],
)
async def test_llm_provider_filters_invalid_candidates(database_url: str, candidate: dict[str, object]) -> None:
    provider = StubLLMProvider(json.dumps({"candidates": [candidate]}, ensure_ascii=False))
    settings = Settings(memory_candidates_enabled=True, memory_candidate_provider="llm")

    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        service = MemoryCandidateService(memories, settings, llm_provider=provider)

        created = await service.create_candidates_from_user_text(
            session_id=None,
            user_text="我喜欢红茶。我的 API Key 是 sk-test-secret。",
        )

        assert created == []
        assert memories.list(status=MemoryStatus.PENDING) == []
```

- [ ] **Step 5: Add provider failure and invalid JSON tests**

Append these tests:

```python
@pytest.mark.asyncio
async def test_llm_provider_returns_empty_on_invalid_json(database_url: str) -> None:
    provider = StubLLMProvider("not json")
    settings = Settings(memory_candidates_enabled=True, memory_candidate_provider="llm")

    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        service = MemoryCandidateService(memories, settings, llm_provider=provider)

        created = await service.create_candidates_from_user_text(session_id=None, user_text="我喜欢红茶。")

        assert created == []
        assert memories.list(status=MemoryStatus.PENDING) == []


@pytest.mark.asyncio
async def test_llm_provider_returns_empty_on_provider_error(database_url: str) -> None:
    provider = StubLLMProvider(error=ProviderError("provider unavailable"))
    settings = Settings(memory_candidates_enabled=True, memory_candidate_provider="llm")

    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        service = MemoryCandidateService(memories, settings, llm_provider=provider)

        created = await service.create_candidates_from_user_text(session_id=None, user_text="我喜欢红茶。")

        assert created == []
        assert memories.list(status=MemoryStatus.PENDING) == []
```

- [ ] **Step 6: Run tests and confirm RED**

Run:

```powershell
python -m pytest backend/tests/test_memory_candidate_service.py -q
```

Expected result: FAIL. Acceptable failures at this stage include:

- `TypeError: object list can't be used in 'await' expression` because the service method is still synchronous.
- `TypeError: MemoryCandidateService.__init__() got an unexpected keyword argument 'llm_provider'` because injection is not implemented.
- No LLM candidates are created because `memory_candidate_provider != "heuristic"` currently returns `[]`.

Do not change tests after observing the expected RED failure.

### Task 2: Implement the LLM extractor and async service path

**Files:**
- Modify: `backend/app/services/memory_candidate_service.py`
- Test: `backend/tests/test_memory_candidate_service.py`

- [ ] **Step 1: Update imports and constants**

In `backend/app/services/memory_candidate_service.py`, replace the current import section with this shape:

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.domain.models import ChatRole, Memory, MemoryType
from app.providers.base import LLMMessage, LLMOptions, LLMProvider
from app.repositories.memories import MemoryRepository


MEMORY_EXTRACTION_SCHEMA = "memory_extraction_schema_v1"
MAX_LLM_CANDIDATE_CONTENT_CHARS = 200
```

- [ ] **Step 2: Extend `MemoryCandidateDraft`**

Replace the dataclass with:

```python
@dataclass(frozen=True)
class MemoryCandidateDraft:
    content: str
    memory_type: MemoryType
    candidate_reason: str
    importance: int = 3
    confidence: float = 0.7
    extraction_provider: str = "heuristic"
    extraction_schema: str | None = None
    source_quote: str | None = None
```

- [ ] **Step 3: Add `MemoryCandidateLLMExtractor` skeleton**

Add this class above `MemoryCandidateService`:

```python
class MemoryCandidateLLMExtractor:
    def __init__(self, provider: LLMProvider, settings: Settings) -> None:
        self._provider = provider
        self._settings = settings

    async def extract(self, user_text: str) -> list[MemoryCandidateDraft]:
        clean_text = user_text.strip()
        if not clean_text:
            return []
        try:
            response = await self._provider.generate(
                self._build_messages(clean_text),
                LLMOptions(
                    model=self._settings.llm_model,
                    timeout_seconds=self._settings.memory_candidate_llm_timeout_seconds,
                    max_retries=self._settings.llm_max_retries,
                    max_tokens=self._settings.memory_candidate_llm_max_tokens,
                ),
            )
        except Exception:
            return []
        return self._parse_response(response.text, clean_text)
```

- [ ] **Step 4: Add the LLM prompt builder**

Add this method inside `MemoryCandidateLLMExtractor`:

```python
    def _build_messages(self, user_text: str) -> list[LLMMessage]:
        system_prompt = (
            "你是长期记忆候选抽取器。只根据当前用户消息抽取候选，不读取或假设旧聊天历史。"
            "只提取对未来对话稳定有用的用户事实、偏好、长期目标、重要事件或关系事件。"
            "不要提取临时情绪、寒暄、对助手的描述、阶段4情感状态、关系分数、API Key、令牌、密码或任何凭据。"
            "候选只是等待用户确认的建议，不是已经记住的事实。"
            "如果没有明确且耐久的信息，返回 {\"candidates\": []}。"
            "必须返回严格 JSON，不要返回 Markdown。"
            "JSON 结构：{\"candidates\":[{\"content\":\"用户喜欢红茶。\","
            "\"memory_type\":\"preference\",\"confidence\":0.9,\"importance\":3,"
            "\"source_quote\":\"我喜欢红茶\",\"reason\":\"explicit_preference_statement\","
            "\"should_create_candidate\":true}]}。"
            "memory_type 只能是 user_fact, preference, long_term_goal, important_event, relationship_event, other。"
        )
        return [
            LLMMessage(role=ChatRole.SYSTEM, content=system_prompt),
            LLMMessage(role=ChatRole.USER, content=user_text),
        ]
```

- [ ] **Step 5: Add response parsing**

Add these methods inside `MemoryCandidateLLMExtractor`:

```python
    def _parse_response(self, text: str, user_text: str) -> list[MemoryCandidateDraft]:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, dict):
            return []
        raw_candidates = payload.get("candidates")
        if not isinstance(raw_candidates, list):
            return []

        drafts: list[MemoryCandidateDraft] = []
        for raw in raw_candidates:
            if len(drafts) >= self._settings.memory_candidate_llm_max_candidates:
                break
            draft = self._parse_candidate(raw, user_text)
            if draft is not None:
                drafts.append(draft)
        return drafts

    def _parse_candidate(self, raw: object, user_text: str) -> MemoryCandidateDraft | None:
        if not isinstance(raw, dict):
            return None
        if raw.get("should_create_candidate") is not True:
            return None

        content = self._clean_text_field(raw.get("content"))
        if not content or len(content) > MAX_LLM_CANDIDATE_CONTENT_CHARS:
            return None
        if not content.startswith("用户"):
            return None
        if self._looks_like_secret(content):
            return None

        source_quote = self._clean_text_field(raw.get("source_quote"))
        if not source_quote or source_quote not in user_text:
            return None
        if self._looks_like_secret(source_quote):
            return None

        try:
            memory_type = MemoryType(str(raw.get("memory_type")))
        except ValueError:
            return None

        confidence = self._parse_float(raw.get("confidence"))
        if confidence is None or confidence < self._settings.memory_candidate_llm_confidence_threshold:
            return None

        importance = self._parse_int(raw.get("importance"))
        if importance is None or importance < 1 or importance > 5:
            return None

        reason = self._clean_text_field(raw.get("reason")) or "llm_candidate"
        return MemoryCandidateDraft(
            content=content,
            memory_type=memory_type,
            candidate_reason=reason,
            importance=importance,
            confidence=confidence,
            extraction_provider="llm",
            extraction_schema=MEMORY_EXTRACTION_SCHEMA,
            source_quote=source_quote,
        )
```

- [ ] **Step 6: Add primitive validation helpers**

Add these helper methods inside `MemoryCandidateLLMExtractor`:

```python
    def _clean_text_field(self, value: object) -> str:
        if not isinstance(value, str):
            return ""
        return value.strip()

    def _parse_float(self, value: object) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int | float):
            return float(value)
        return None

    def _parse_int(self, value: object) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        return None

    def _looks_like_secret(self, text: str) -> bool:
        lowered = text.lower()
        blocked_terms = (
            "api key",
            "apikey",
            "token",
            "password",
            "secret",
            "密钥",
            "令牌",
            "密码",
            "凭据",
        )
        if any(term in lowered for term in blocked_terms):
            return True
        return bool(re.search(r"\b(?:sk|pk|ghp|gho|xox[baprs])-[-_A-Za-z0-9]{8,}\b", text))
```

- [ ] **Step 7: Make `MemoryCandidateService` async and LLM-aware**

Replace the service constructor and `create_candidates_from_user_text` method with:

```python
class MemoryCandidateService:
    def __init__(self, memories: MemoryRepository, settings: Settings, llm_provider: LLMProvider | None = None) -> None:
        self._memories = memories
        self._settings = settings
        self._llm_extractor = MemoryCandidateLLMExtractor(llm_provider, settings) if llm_provider is not None else None

    async def create_candidates_from_user_text(self, *, session_id: str | None, user_text: str) -> list[Memory]:
        if not self._settings.memory_candidates_enabled:
            return []

        if self._settings.memory_candidate_provider == "heuristic":
            drafts = self._extract_heuristic_drafts(user_text)
        elif self._settings.memory_candidate_provider == "llm" and self._llm_extractor is not None:
            drafts = await self._llm_extractor.extract(user_text)
        else:
            return []

        created: list[Memory] = []
        for draft in drafts:
            metadata: dict[str, object] = {
                "candidate_reason": draft.candidate_reason,
                "extraction_provider": draft.extraction_provider,
            }
            if draft.extraction_schema is not None:
                metadata["extraction_schema"] = draft.extraction_schema
            if draft.source_quote is not None:
                metadata["source_quote"] = draft.source_quote
            if draft.extraction_provider == "llm":
                metadata["raw_confidence"] = draft.confidence

            memory, _conflicts = self._memories.create_candidate(
                content=draft.content,
                memory_type=draft.memory_type,
                source_session_id=session_id,
                importance=draft.importance,
                confidence=draft.confidence,
                metadata=metadata,
            )
            if memory is not None:
                created.append(memory)
        return created
```

Keep `_extract_heuristic_drafts(...)` and `_clean_value(...)` below this method. Do not change the heuristic regexes except for formatting required by the new dataclass defaults.

- [ ] **Step 8: Run service tests and confirm GREEN**

Run:

```powershell
python -m pytest backend/tests/test_memory_candidate_service.py -q
```

Expected result: PASS.

If a failure says `TypeError: unsupported operand type(s) for |: 'type' and 'type'` in `isinstance(value, int | float)`, replace that line with:

```python
if isinstance(value, (int, float)):
```

then rerun the same test command.

### Task 3: Integrate async extraction into chat and dependencies

**Files:**
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/tests/test_chat_memory_candidates.py`

- [ ] **Step 1: Add chat integration test for LLM extraction failure isolation**

Append this test to `backend/tests/test_chat_memory_candidates.py`:

```python
def test_chat_succeeds_when_llm_memory_candidate_extraction_fails(client: TestClient, monkeypatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("MEMORY_CANDIDATE_PROVIDER", "llm")
    monkeypatch.setenv("FAKE_PROVIDER_MODE", "ok")
    get_settings.cache_clear()
    llm_client = TestClient(client.app)
    session = llm_client.post("/api/sessions", json={"title": "LLM候选失败隔离"}).json()

    response = llm_client.post(
        f"/api/sessions/{session['id']}/messages",
        json={"content": "我喜欢红茶。"},
    )

    assert response.status_code == 200
    assert response.json()["reply"]
    assert llm_client.get("/api/memories", params={"status_filter": "pending"}).json() == []
    get_settings.cache_clear()
```

This uses the fake chat provider as the LLM extractor provider. The fake provider does not return the required JSON schema, so the extractor should fail closed with no candidates while chat still succeeds.

- [ ] **Step 2: Add pending-candidate context isolation test**

Append this test:

```python
def test_pending_llm_candidates_do_not_enter_chat_context(client: TestClient, monkeypatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("MEMORY_CANDIDATE_PROVIDER", "llm")
    monkeypatch.setenv("FAKE_PROVIDER_MODE", "ok")
    get_settings.cache_clear()
    llm_client = TestClient(client.app)
    session = llm_client.post("/api/sessions", json={"title": "候选不进上下文"}).json()

    create_response = llm_client.post(
        "/api/memories",
        json={
            "content": "用户喜欢红茶。",
            "memory_type": "preference",
            "source_session_id": session["id"],
            "importance": 3,
            "confidence": 0.8,
            "metadata": {"extraction_provider": "llm"},
        },
    )
    assert create_response.status_code == 201
    candidate_id = create_response.json()["id"]

    pending_response = llm_client.get("/api/memories", params={"status_filter": "pending"})
    assert any(memory["id"] == candidate_id for memory in pending_response.json())

    chat_response = llm_client.post(
        f"/api/sessions/{session['id']}/messages",
        json={"content": "我喜欢什么？"},
    )

    assert chat_response.status_code == 200
    assert "红茶" not in chat_response.json()["reply"]
    get_settings.cache_clear()
```

If `POST /api/memories` creates active manual memories rather than pending candidates in this project, replace the setup block with repository-level setup inside a local dependency override only after reading `backend/app/api/routes/memories.py` and `backend/app/repositories/memories.py`. The assertion must still prove `pending` candidates are excluded from chat context.

- [ ] **Step 3: Run chat tests and confirm RED**

Run:

```powershell
python -m pytest backend/tests/test_chat_memory_candidates.py -q
```

Expected result: FAIL because `ChatService` still calls the async service without `await`, or dependencies do not inject an LLM provider into `MemoryCandidateService`.

- [ ] **Step 4: Await extraction in `ChatService`**

In `backend/app/services/chat_service.py`, replace lines 70-78 with:

```python
        if self._memory_candidates is not None:
            try:
                await self._memory_candidates.create_candidates_from_user_text(
                    session_id=session_id,
                    user_text=clean_text,
                )
            except Exception:
                # Candidate extraction must never break the chat path.
                pass
```

- [ ] **Step 5: Inject LLM provider into memory candidate service**

In `backend/app/api/dependencies.py`, change `get_memory_candidate_service(...)` to depend on `get_llm_provider` and pass it to the constructor:

```python
def get_memory_candidate_service(
    settings: Settings = Depends(get_settings),
    memories: MemoryRepository = Depends(get_memory_repository),
    provider: LLMProvider = Depends(get_llm_provider),
) -> MemoryCandidateService:
    return MemoryCandidateService(memories, settings, llm_provider=provider)
```

This is acceptable even when `MEMORY_CANDIDATE_PROVIDER=heuristic`: the service does not call the LLM extractor in heuristic mode.

- [ ] **Step 6: Run chat tests and confirm GREEN**

Run:

```powershell
python -m pytest backend/tests/test_chat_memory_candidates.py -q
```

Expected result: PASS.

- [ ] **Step 7: Run targeted backend tests**

Run:

```powershell
python -m pytest backend/tests/test_config.py backend/tests/test_memory_candidate_service.py backend/tests/test_chat_memory_candidates.py -q
```

Expected result: PASS.

### Task 4: Fix context-isolation test setup if needed

**Files:**
- Read: `backend/app/api/routes/memories.py`
- Read: `backend/app/repositories/memories.py`
- Modify: `backend/tests/test_chat_memory_candidates.py` only if Task 3 Step 2 used the wrong API setup path.

- [ ] **Step 1: Read memory route and repository if Task 3 Step 2 fails during setup**

Read:

```text
backend/app/api/routes/memories.py
backend/app/repositories/memories.py
```

Look for the route or repository method that creates a pending candidate. Use the existing production path if one exists.

- [ ] **Step 2: If there is no API route for pending candidate creation, replace only the setup section**

Use repository setup in the test and keep the HTTP chat assertion. The setup should look like this inside the test before the chat request:

```python
from app.core.config import get_settings
from app.repositories.memories import MemoryRepository
from app.repositories.sqlite import managed_connection

settings = get_settings()
with managed_connection(settings.database_url) as connection:
    memories = MemoryRepository(connection)
    memory, _conflicts = memories.create_candidate(
        content="用户喜欢红茶。",
        memory_type="preference",
        source_session_id=session["id"],
        importance=3,
        confidence=0.8,
        metadata={"extraction_provider": "llm"},
    )
    assert memory is not None
    candidate_id = memory.id
```

Keep the rest of the test unchanged:

```python
pending_response = llm_client.get("/api/memories", params={"status_filter": "pending"})
assert any(memory["id"] == candidate_id for memory in pending_response.json())

chat_response = llm_client.post(
    f"/api/sessions/{session['id']}/messages",
    json={"content": "我喜欢什么？"},
)
assert chat_response.status_code == 200
assert "红茶" not in chat_response.json()["reply"]
```

- [ ] **Step 3: Rerun chat tests**

Run:

```powershell
python -m pytest backend/tests/test_chat_memory_candidates.py -q
```

Expected result: PASS.

### Task 5: Documentation and project status

**Files:**
- Create: `docs/stage3i-llm-memory-candidate-extraction.md`
- Modify: `CLAUDE.md`
- Do not modify frontend files for this minimal slice.

- [ ] **Step 1: Run full backend validation before status docs**

Run:

```powershell
python -m pytest backend/tests -q
```

Expected result: PASS.

If tests fail, stop. Do not update `CLAUDE.md` to mark 3I complete until failures are resolved.

- [ ] **Step 2: Create Stage 3I evidence document**

Create `docs/stage3i-llm-memory-candidate-extraction.md` with this structure, filling in the exact observed test output counts from the validation run:

```markdown
# Stage 3I LLM Memory Candidate Extraction

Date: 2026-07-09
Status: PASS / IMPLEMENTED

## Scope

Implemented opt-in LLM memory candidate extraction for the current user message only. The default `MEMORY_CANDIDATE_PROVIDER=heuristic` behavior remains unchanged.

## Configuration

- `MEMORY_CANDIDATE_PROVIDER=heuristic` keeps heuristic extraction as the default.
- `MEMORY_CANDIDATE_PROVIDER=llm` enables LLM candidate extraction.
- `MEMORY_CANDIDATE_LLM_MAX_TOKENS=512` bounds extraction output.
- `MEMORY_CANDIDATE_LLM_TIMEOUT_SECONDS=15` bounds extraction latency.
- `MEMORY_CANDIDATE_LLM_CONFIDENCE_THRESHOLD=0.75` filters uncertain candidates.
- `MEMORY_CANDIDATE_LLM_MAX_CANDIDATES=3` limits candidates per user message.

## Behavior

- LLM extraction reads only the current user message.
- LLM output can only create `pending` candidates.
- Candidates require explicit user confirmation before becoming active long-term memories.
- Pending, dismissed, and archived candidates remain excluded from chat context.
- Provider errors, invalid JSON, malformed schema, low confidence, invented quotes, and secret-like content fail closed with no candidates.

## Validation

```powershell
python -m pytest backend/tests/test_config.py backend/tests/test_memory_candidate_service.py backend/tests/test_chat_memory_candidates.py -q
# <paste exact result>

python -m pytest backend/tests -q
# <paste exact result>
```

## Real-provider smoke

Skipped unless explicitly run with a valid local API key. No real API key was printed or committed.

## Privacy and safety notes

Raw LLM responses are not stored in memory metadata. Candidate metadata stores only safe fields such as extraction provider, schema version, candidate reason, source quote, and numeric confidence. Secret-like content is rejected.

## Stage boundary

This did not implement session summaries, backfill, automatic conflict resolution, hybrid extraction, production embedding model selection, or Stage 4 emotion state.
```

- [ ] **Step 3: Update `CLAUDE.md` after tests pass**

In `CLAUDE.md`, update the current stage line and Stage 3 status to say 3A-3I completed. Keep Stage 4 unstarted. Set the next task to a Stage 3-only item, for example:

```markdown
> 当前阶段：**阶段 3——长期记忆（IMPLEMENTING；3A–3I COMPLETED；NEXT: independent session summary storage design OR real embedding production model selection）**
```

In the Stage 3 section, add 3I to the completed-subtasks sentence and keep the not-yet-implemented list excluding LLM candidate extraction. Do not mark Stage 3 complete.

- [ ] **Step 4: Record frontend validation decision**

Because this minimal plan does not change frontend runtime files, record in the final report and Stage 3I evidence document:

```text
Frontend tests skipped: no frontend runtime source changed in this slice.
```

If any frontend runtime source was changed, run instead:

```powershell
npm --prefix frontend test -- --run
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

Expected result for each frontend command: PASS.

### Task 6: Final verification and diff review

**Files:**
- Review all modified files with git diff.

- [ ] **Step 1: Check working tree status**

Run:

```powershell
git status --short
```

Expected: only these files should be modified or created unless an earlier task explicitly required more:

```text
 M CLAUDE.md
 M backend/app/api/dependencies.py
 M backend/app/services/chat_service.py
 M backend/app/services/memory_candidate_service.py
 M backend/tests/test_chat_memory_candidates.py
 M backend/tests/test_config.py
 M backend/tests/test_memory_candidate_service.py
?? docs/stage3i-llm-memory-candidate-extraction.md
```

Existing user-modified docs or plan files may also appear. Do not revert user work.

- [ ] **Step 2: Review diff for scope creep**

Run:

```powershell
git diff -- backend/app/services/memory_candidate_service.py backend/app/services/chat_service.py backend/app/api/dependencies.py backend/tests/test_memory_candidate_service.py backend/tests/test_chat_memory_candidates.py backend/tests/test_config.py docs/stage3i-llm-memory-candidate-extraction.md CLAUDE.md
```

Expected review findings:

- No API keys or secrets.
- No frontend changes unless explicitly validated.
- No active memory writes from LLM output.
- No conversation history backfill.
- No session summary code.
- No Stage 4 emotion fields or state.
- No vendor-specific SDK calls in business services.

- [ ] **Step 3: Final targeted validation**

Run:

```powershell
python -m pytest backend/tests/test_config.py backend/tests/test_memory_candidate_service.py backend/tests/test_chat_memory_candidates.py -q
python -m pytest backend/tests -q
```

Expected: PASS for both commands.

- [ ] **Step 4: Do not commit unless explicitly authorized**

Do not run `git commit` unless the user explicitly asks for a commit. If the user asks for a commit after validation, commit only the files in this plan and use a message like:

```text
feat: add opt-in LLM memory candidate extraction
```

---

## Self-Review

- Spec coverage: The plan implements opt-in LLM extraction, default heuristic behavior, current-message-only extraction, pending-only candidate creation, failure isolation, defensive validation, duplicate/conflict reuse through `MemoryRepository.create_candidate(...)`, documentation, and Stage 3 boundary updates.
- Scope check: One subsystem only: Stage 3 memory candidate extraction. Frontend status display from the larger design is intentionally excluded by the user-approved minimal backend plan.
- Placeholder scan: No `TBD`, `TODO`, "implement later", or unspecified test steps remain. Each code-changing step includes concrete code or exact replacement text.
- Type consistency: `MemoryCandidateLLMExtractor.extract(...)` returns `list[MemoryCandidateDraft]`; `MemoryCandidateService.create_candidates_from_user_text(...)` is async and returns `list[Memory]`; `ChatService.send_message(...)` awaits it.
- Safety: The plan rejects secrets, does not log raw LLM responses, stores only safe metadata, and keeps pending candidates out of chat context.
