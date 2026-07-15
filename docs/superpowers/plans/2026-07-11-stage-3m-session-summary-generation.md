# Stage 3M Remaining Automatic Session Summary Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the existing Stage 3M WIP by scheduling append-only session-summary generation after successful chat turns without delaying or breaking chat.

**Architecture:** Preserve the already implemented configuration, sanitizer, providers, stable message ordering, and incremental summary service. Add one replaceable in-process scheduler; inject it into `ChatService`; compose a production job that opens its own SQLite connection; then prove API wiring, nonblocking behavior, isolation, and runtime behavior with fake providers.

**Tech Stack:** Python 3.11+, FastAPI dependency injection, asyncio tasks, SQLite, existing LLM Provider adapters, pytest, pytest-asyncio.

---

## Stage and scope guard

- Current stage: Stage 3 — long-term memory; 3A–3L complete; 3M is WIP.
- Source of detailed behavior: `docs/superpowers/specs/2026-07-10-stage-3m-session-summary-generation-design.md`.
- Source of overall ordering and hardware/deployment boundaries: `docs/superpowers/specs/2026-07-11-yukinoshita-yukino-desktop-companion-roadmap-design.md`.
- In scope: scheduler, `ChatService` enqueue, fresh-connection dependency wiring, focused/composition/runtime verification, and evidence after all checks pass.
- Out of scope: summary prompt injection, summary UI/API, summary-derived memory/candidates/embeddings, automatic conflict resolution, emotional state, TTS emotion control, avatar work, MCP, and agent frameworks.
- Do not reset, checkout, amend, overwrite, or mechanically recommit existing WIP. Do not commit unless the user separately requests it.
- `.superpowers/brainstorm/` is not a 3M product artifact. Do not delete or stage it.

## Current WIP baseline — verify, do not reimplement

The following work already exists in the uncommitted working tree even though the superseded plan listed it as unchecked Tasks 1–5:

- `.env.example`, `backend/app/core/config.py`, `backend/tests/conftest.py`, `backend/tests/test_config.py` — summary settings, fake/offline defaults, validation, and environment isolation.
- `backend/app/providers/factory.py`, `backend/app/providers/deepseek_provider.py`, and tests — independently configured named LLM adapters while preserving chat defaults.
- `backend/app/repositories/messages.py` — stable `created_at, rowid` ordering needed by positional coverage. Keep this change; the old plan's “reuse unchanged” note was wrong.
- `backend/app/services/session_summary_sanitizer.py` and tests — best-effort input/output credential redaction.
- `backend/app/services/session_summary_provider.py` and tests — deterministic fake and opt-in LLM summary providers.
- `backend/app/services/session_summary_service.py` and tests — threshold, incremental coverage, one-write-per-call, safe metadata, output sanitization, failure isolation, and final duplicate recheck.
- Modified 3M design and the roadmap spec — preserve current contents.

Before implementing, run `git status --short` and read current files. If this baseline has changed, update the plan before editing; do not reconstruct it from an older commit.

## Remaining file structure

### Create

- `backend/app/services/session_summary_scheduler.py` — narrow scheduler protocol and task-retaining in-process implementation.
- `docs/stage3m-session-summary-generation.md` — observed evidence only after verification.

### Modify

- `backend/app/services/chat_service.py` — inject an optional scheduler and enqueue after assistant persistence.
- `backend/app/api/dependencies.py` — select the summary provider and create a fresh-connection background job.
- `backend/tests/test_chat_service.py` — ordering, nonblocking contract, scheduling failure isolation, and no enqueue after chat-provider failure.
- `backend/tests/test_api_chat.py` — dependency-composition and real fake-background-job integration tests.
- `CLAUDE.md` and `README.md` — only after every acceptance check passes.

No schema migration and no frontend file should change.

---

### Task 1: Establish the protected baseline

**Files:**
- Read: `CLAUDE.md`
- Read: `docs/superpowers/specs/2026-07-10-stage-3m-session-summary-generation-design.md`
- Read: `docs/superpowers/specs/2026-07-11-yukinoshita-yukino-desktop-companion-roadmap-design.md`
- Read: current WIP files listed above

- [ ] **Step 1: Re-read project constraints and inspect the working tree**

Run from the project root:

```powershell
git status --short
git diff --stat
git diff -- backend/app/services/chat_service.py backend/app/api/dependencies.py backend/tests/test_chat_service.py backend/tests/test_api_chat.py
```

Expected: the first two commands show the protected 3M WIP; the final command should be empty before remaining wiring begins. If the four remaining files already contain user changes, stop and reconcile this plan against them before editing.

- [ ] **Step 2: Run existing component tests as a baseline**

```powershell
.\.venv\Scripts\python.exe -m pytest `
  backend/tests/test_config.py `
  backend/tests/test_deepseek_provider.py `
  backend/tests/test_provider_factory.py `
  backend/tests/test_session_summaries.py `
  backend/tests/test_session_summary_sanitizer.py `
  backend/tests/test_session_summary_provider.py `
  backend/tests/test_session_summary_service.py -q
```

Expected: all selected tests PASS and no real network request occurs. If a test fails, retain the exact output and determine whether the current WIP is incomplete before adding scheduler wiring.

- [ ] **Step 3: Record the baseline without committing**

Add the command and exact pass/fail count to implementation notes for the final evidence document. Do not stage or commit Task 1–5 WIP as a new slice.

---

### Task 2: Add a replaceable in-process scheduler and ChatService enqueue

**Files:**
- Create: `backend/app/services/session_summary_scheduler.py`
- Modify: `backend/app/services/chat_service.py:1-80`
- Modify: `backend/tests/test_chat_service.py`

- [ ] **Step 1: Add failing ChatService scheduler tests**

In `backend/tests/test_chat_service.py`, reuse its current repository/provider helpers and add equivalent helpers:

```python
class RecordingSummaryScheduler:
    def __init__(self, messages: MessageRepository) -> None:
        self._messages = messages
        self.session_ids: list[str] = []
        self.roles_seen_at_schedule: list[list[ChatRole]] = []

    def schedule(self, session_id: str) -> None:
        self.session_ids.append(session_id)
        self.roles_seen_at_schedule.append(
            [message.role for message in self._messages.list(session_id)]
        )


class FailingSummaryScheduler:
    def schedule(self, session_id: str) -> None:
        raise RuntimeError("summary scheduler failed")
```

Add tests following the file's existing setup idiom:

```python
@pytest.mark.asyncio
async def test_chat_service_schedules_summary_after_assistant_persistence(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'summary-after-persist.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("摘要调度")
        scheduler = RecordingSummaryScheduler(messages)
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            FakeProvider(),
            Settings(llm_model="test-model"),
            summary_scheduler=scheduler,
        )

        reply = await service.send_message(session.id, "请在回复后安排摘要。")

        assert reply.provider == "fake"
        assert scheduler.session_ids == [session.id]
        assert scheduler.roles_seen_at_schedule == [
            [ChatRole.USER, ChatRole.ASSISTANT]
        ]


@pytest.mark.asyncio
async def test_chat_service_ignores_summary_scheduling_failure(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'summary-schedule-failure.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("摘要调度失败")
        service = ChatService(
            sessions,
            messages,
            ContextBuilder(messages, 12),
            default_prompt_renderer(),
            FakeProvider(),
            Settings(llm_model="test-model"),
            summary_scheduler=FailingSummaryScheduler(),
        )

        reply = await service.send_message(session.id, "即使摘要调度失败也要回复。")

        assert reply.provider == "fake"
        assert [message.role for message in messages.list(session.id)] == [
            ChatRole.USER,
            ChatRole.ASSISTANT,
        ]
```

Extend the current provider-invalid-response test by injecting `RecordingSummaryScheduler` and asserting `scheduler.session_ids == []` after the expected exception. This proves unsuccessful chat never queues a summary.

- [ ] **Step 2: Run tests and confirm the intended failure**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_chat_service.py -k "summary or invalid_provider" -q
```

Expected: FAIL because `ChatService.__init__()` does not accept `summary_scheduler` or the scheduler module does not exist.

- [ ] **Step 3: Create the scheduler implementation**

Create `backend/app/services/session_summary_scheduler.py`:

```python
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol


_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


class SessionSummaryScheduler(Protocol):
    def schedule(self, session_id: str) -> None: ...


class InProcessSessionSummaryScheduler:
    def __init__(self, job: Callable[[str], Awaitable[None]]) -> None:
        self._job = job

    def schedule(self, session_id: str) -> None:
        task = asyncio.create_task(self._run_safely(session_id))
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_discard_task)

    async def _run_safely(self, session_id: str) -> None:
        try:
            await self._job(session_id)
        except Exception:
            # Summary work is best effort and cannot fail chat.
            pass


def _discard_task(task: asyncio.Task[None]) -> None:
    _BACKGROUND_TASKS.discard(task)
    if not task.cancelled():
        task.exception()
```

Do not add durable queue semantics, retries, shutdown orchestration, a worker, or logging infrastructure.

- [ ] **Step 4: Inject and call the scheduler from ChatService**

Add:

```python
from app.services.session_summary_scheduler import SessionSummaryScheduler
```

Extend the constructor after `memory_candidates` to preserve existing positional compatibility:

```python
summary_scheduler: SessionSummaryScheduler | None = None,
```

Store it:

```python
self._summary_scheduler = summary_scheduler
```

After the existing memory-candidate `try/except`, and before returning `ChatReply`, add:

```python
if self._summary_scheduler is not None:
    try:
        self._summary_scheduler.schedule(session_id)
    except Exception:
        # Summary scheduling must never break the chat path.
        pass
```

No `await`, summary Provider, repository, or service call is permitted in `ChatService`.

- [ ] **Step 5: Add a scheduler behavior test that does not use time**

Add a test for `InProcessSessionSummaryScheduler` in `backend/tests/test_chat_service.py` or a focused new test file if that matches current test organization:

```python
@pytest.mark.asyncio
async def test_in_process_summary_scheduler_returns_before_job_finishes() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    async def job(session_id: str) -> None:
        assert session_id == "session-1"
        started.set()
        await release.wait()
        finished.set()

    scheduler = InProcessSessionSummaryScheduler(job)

    scheduler.schedule("session-1")
    assert not finished.is_set()
    await started.wait()
    assert not finished.is_set()
    release.set()
    await finished.wait()
```

This proves `schedule()` does not await job completion without a timing threshold or arbitrary sleep.

- [ ] **Step 6: Run the complete ChatService suite**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_chat_service.py -q
```

Expected: all tests PASS. If the known context-pruning test fails with the same previously recorded failure, preserve its exact output and do not change unrelated context logic; all new scheduler tests must pass.

- [ ] **Step 7: Review the Task 2 diff without committing**

```powershell
git diff -- backend/app/services/session_summary_scheduler.py backend/app/services/chat_service.py backend/tests/test_chat_service.py
```

Expected: only the scheduler boundary, optional injection, enqueue, and directly related tests. Do not commit unless explicitly requested.

---

### Task 3: Compose a fresh-connection production job

**Files:**
- Modify: `backend/app/api/dependencies.py:1-136`
- Modify: `backend/tests/test_api_chat.py`

- [ ] **Step 1: Add a failing API dependency-composition test**

In `backend/tests/test_api_chat.py`, import:

```python
from app.api.dependencies import get_session_summary_scheduler
```

Add:

```python
class RecordingSummaryScheduler:
    def __init__(self) -> None:
        self.session_ids: list[str] = []

    def schedule(self, session_id: str) -> None:
        self.session_ids.append(session_id)


def test_chat_api_composition_injects_summary_scheduler(client: TestClient) -> None:
    scheduler = RecordingSummaryScheduler()
    client.app.dependency_overrides[get_session_summary_scheduler] = lambda: scheduler
    try:
        session = client.post(
            "/api/sessions",
            json={"title": "API 摘要调度"},
        ).json()
        response = client.post(
            f"/api/sessions/{session['id']}/messages",
            json={"content": "通过 API 发送消息。"},
        )
    finally:
        client.app.dependency_overrides.pop(get_session_summary_scheduler, None)

    assert response.status_code == 200
    assert scheduler.session_ids == [session["id"]]
```

Adapt only endpoint field names if the existing test file demonstrates different response models; keep the dependency-override seam and assertions unchanged in intent.

- [ ] **Step 2: Run the test and confirm the intended failure**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_api_chat.py -k summary_scheduler -q
```

Expected: FAIL at import because `get_session_summary_scheduler` does not yet exist, or FAIL because `get_chat_service()` does not inject it.

- [ ] **Step 3: Add summary Provider selection to dependencies**

Extend imports:

```python
from app.providers.factory import create_named_provider, create_provider
from app.repositories.session_summaries import SessionSummaryRepository
from app.services.session_summary_provider import (
    FakeSessionSummaryProvider,
    LLMSessionSummaryProvider,
    SessionSummaryProvider,
)
from app.services.session_summary_scheduler import (
    InProcessSessionSummaryScheduler,
    SessionSummaryScheduler,
)
from app.services.session_summary_service import SessionSummaryService
```

Add:

```python
def get_session_summary_provider(
    settings: Settings = Depends(get_settings),
) -> SessionSummaryProvider:
    if settings.session_summary_provider == "fake":
        return FakeSessionSummaryProvider()

    llm_provider = create_named_provider(
        settings,
        settings.session_summary_llm_provider,
        deepseek_max_tokens=settings.session_summary_llm_max_tokens,
        deepseek_timeout_seconds=settings.session_summary_llm_timeout_seconds,
        deepseek_max_retries=settings.session_summary_llm_max_retries,
    )
    return LLMSessionSummaryProvider(
        llm_provider=llm_provider,
        model=settings.session_summary_llm_model,
    )
```

Do not call `create_named_provider()` in fake mode and do not add a request-scoped summary repository dependency.

- [ ] **Step 4: Add a scheduler whose job owns its SQLite connection**

```python
def get_session_summary_scheduler(
    settings: Settings = Depends(get_settings),
    provider: SessionSummaryProvider = Depends(get_session_summary_provider),
) -> SessionSummaryScheduler:
    async def run_job(session_id: str) -> None:
        with managed_connection(settings.database_url) as connection:
            service = SessionSummaryService(
                messages=MessageRepository(connection),
                summaries=SessionSummaryRepository(connection),
                provider=provider,
                settings=settings,
            )
            await service.maybe_generate_for_session(session_id)

    return InProcessSessionSummaryScheduler(run_job)
```

The closure may share its Provider/client, but repositories must be created only inside the fresh `managed_connection` scope.

- [ ] **Step 5: Inject the scheduler into ChatService**

Add to `get_chat_service()`:

```python
summary_scheduler: SessionSummaryScheduler = Depends(get_session_summary_scheduler),
```

Use keyword arguments for the optional dependencies:

```python
return ChatService(
    sessions,
    messages,
    context_builder,
    prompt_renderer,
    provider,
    settings,
    memory_candidates=memory_candidates,
    summary_scheduler=summary_scheduler,
)
```

- [ ] **Step 6: Run API composition tests**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_api_chat.py -q
```

Expected: all API chat tests PASS with fake providers and no real network call.

- [ ] **Step 7: Review the Task 3 diff without committing**

```powershell
git diff -- backend/app/api/dependencies.py backend/tests/test_api_chat.py
```

Expected: Provider selection, fresh-connection job, injection, and direct composition tests only.

---

### Task 4: Prove runtime boundaries through the API

**Files:**
- Modify: `backend/tests/test_api_chat.py`
- Reuse: `backend/app/repositories/session_summaries.py`
- Reuse: `backend/app/repositories/memories.py`

- [ ] **Step 1: Add an explicit test scheduler drain seam**

In the API test file, define a scheduler that records job coroutines without awaiting them in `schedule()`:

```python
class DrainingSummaryScheduler:
    def __init__(self, job: Callable[[str], Awaitable[None]]) -> None:
        self._job = job
        self.session_ids: list[str] = []

    def schedule(self, session_id: str) -> None:
        self.session_ids.append(session_id)

    async def drain(self) -> None:
        for session_id in self.session_ids:
            await self._job(session_id)
```

Use FastAPI dependency overrides to inject the scheduler or its factory. The request assertion must run before `drain()` so the test proves the HTTP reply does not depend on summary generation.

- [ ] **Step 2: Write a failing fake-background-job integration test**

With settings overridden to `session_summary_provider="fake"` and trigger count `2`:

1. POST a session.
2. POST one message and assert HTTP 200 before drain.
3. Assert user and assistant messages are persisted.
4. Call `await scheduler.drain()` through the test's async seam.
5. Open a new connection to the same test database.
6. Assert one generated summary with `message_count == 2` and exact start/end message IDs.
7. Assert no new `memories` row exists.
8. Build or record the next provider context and assert summary text is absent.
9. Call drain again without new messages and assert no second summary.

Do not use `sleep()` or timing thresholds. Reuse real repositories and the existing fake summary provider.

- [ ] **Step 3: Add failure-isolation integration coverage**

Inject a summary job/provider that raises during drain. Assert:

```python
assert response.status_code == 200
assert [message.role for message in messages] == [ChatRole.USER, ChatRole.ASSISTANT]
assert summaries == []
```

The HTTP response assertion must occur before the failing drain.

- [ ] **Step 4: Run the focused API and service integration set**

```powershell
.\.venv\Scripts\python.exe -m pytest `
  backend/tests/test_api_chat.py `
  backend/tests/test_chat_service.py `
  backend/tests/test_session_summary_service.py `
  backend/tests/test_session_summaries.py -q
```

Expected: all new 3M tests PASS; no real network request occurs.

---

### Task 5: Run complete verification and offline smoke

**Files:**
- No product-file changes unless a verified 3M defect is found.

- [ ] **Step 1: Run the complete focused Stage 3M suite**

```powershell
.\.venv\Scripts\python.exe -m pytest `
  backend/tests/test_config.py `
  backend/tests/test_deepseek_provider.py `
  backend/tests/test_provider_factory.py `
  backend/tests/test_session_summaries.py `
  backend/tests/test_session_summary_sanitizer.py `
  backend/tests/test_session_summary_provider.py `
  backend/tests/test_session_summary_service.py `
  backend/tests/test_chat_service.py `
  backend/tests/test_api_chat.py -q
```

Expected: PASS with no real network calls. Record the exact count and exit status.

- [ ] **Step 2: Run the full backend suite**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
```

Expected: PASS. If `test_chat_service_prunes_old_history_before_provider_when_context_is_large` fails exactly as recorded in 3K/3L evidence, classify it explicitly as the pre-existing baseline and do not make unrelated context-pruning changes. Any other failure must be investigated as a possible regression.

- [ ] **Step 3: Run frontend regression checks because the API contract is reused**

```powershell
Push-Location frontend
npm run typecheck
npm test -- --run
npm run build
Pop-Location
```

Expected: typecheck, tests, and production build PASS. No frontend file should have changed.

- [ ] **Step 4: Start an isolated offline backend**

Use an isolated smoke database so the run does not modify the user's normal data:

```powershell
$env:DATABASE_URL = "sqlite:///./stage3m-smoke.db"
$env:LLM_PROVIDER = "fake"
$env:LLM_MODEL = "test-model"
$env:SESSION_SUMMARY_PROVIDER = "fake"
$env:SESSION_SUMMARY_TRIGGER_MESSAGE_COUNT = "2"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
$session = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/sessions" -ContentType "application/json" -Body '{"title":"3M offline smoke"}'
$reply = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/sessions/$($session.id)/messages" -ContentType "application/json" -Body '{"content":"今天先确认离线会话摘要。"}'
$messages = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/sessions/$($session.id)/messages"
$reply
$messages
```

Expected: the chat request returns successfully and the message list contains one user and one assistant message. Inspect `stage3m-smoke.db` using repository code or a short Python verification script to record:

- exactly one `source="generated"` summary after the detached job completes;
- `message_count == 2` and coverage IDs match the two persisted messages;
- zero summary-caused memory/candidate rows;
- a subsequent fake chat Provider context contains no summary text.

Do not enable `SESSION_SUMMARY_PROVIDER=llm`. Remove the isolated smoke database only after confirming it is the file created by this step; do not touch the user's configured database.

- [ ] **Step 5: Invoke end-to-end verification**

Run `/verify` for the Stage 3M chat flow. Required observation: the API returns before summary completion; the background fake job later creates the correct independent summary; no memory or context injection occurs.

- [ ] **Step 6: Invoke mandatory code review**

Run `/code-review`. Address only confirmed defects within 3M scope. Do not expand into automatic conflict resolution, Stage 4, desktop shell work, or unrelated refactoring.

- [ ] **Step 7: Review the complete diff**

```powershell
git status --short
git diff --check
git diff -- backend/app/services/session_summary_scheduler.py backend/app/services/chat_service.py backend/app/api/dependencies.py backend/tests/test_chat_service.py backend/tests/test_api_chat.py
```

Expected: no whitespace errors; remaining product diff matches the approved 3M boundaries; protected WIP remains intact.

---

### Task 6: Record evidence and update status only after acceptance

**Files:**
- Create: `docs/stage3m-session-summary-generation.md`
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: Create the evidence document from observed results**

Use this exact structure and replace every evidence field with actual output; if a check failed, record the failure instead of claiming success:

```markdown
# Stage 3M Automatic Session Summary Generation

## Implemented behavior
- Threshold-triggered append-only summaries
- Offline deterministic fake provider by default
- Explicit opt-in LLM summary provider
- Fresh-connection nonblocking background job
- Input/output credential redaction
- Failure isolation and duplicate recheck

## Stage boundaries
- No summary prompt injection
- No long-term-memory writes
- No memory candidates or embeddings from summaries
- No automatic conflict resolution
- No emotional state or avatar behavior

## Verification
- Baseline component tests: `<command, count, exit status>`
- Focused Stage 3M tests: `<command, count, exit status>`
- Full backend tests: `<command, count, exit status; identify any known baseline separately>`
- Frontend regressions: `<typecheck, test, build results>`
- Runtime smoke: `<HTTP result, summary coverage IDs/count, memory count, context observation>`
- End-to-end verify: `<observed result>`
- Code review: `<verified findings and disposition>`

## Limitations
- In-process jobs are best effort and are not durable across shutdown.
- Credential sanitization is best effort, not a DLP guarantee.
- Real LLM summary quality, latency, and cost are outside default acceptance.
```

Do not use placeholders in the saved document: retain failed/skipped status explicitly when evidence is unavailable.

- [ ] **Step 2: Update project status only if every required check passed**

Update `CLAUDE.md` and `README.md` to state only observed behavior:

- Stage 3M automatic, nonblocking, independently stored summary generation is complete.
- Summary injection remains unimplemented.
- Automatic conflict resolution remains unimplemented.
- Stage 4 remains not started.
- The next task must be separately designed within Stage 3; do not silently choose or implement it in this status update.

If required checks did not pass, do not mark 3M complete; leave the task in progress and document the blocker.

- [ ] **Step 3: Final status and diff check**

```powershell
git status --short
git diff --check
git diff -- docs/stage3m-session-summary-generation.md CLAUDE.md README.md
```

Expected: documentation reflects actual evidence only. Do not commit unless the user explicitly requests a commit.

---

## Final acceptance checklist

- [ ] Existing Task 1–5 WIP was preserved rather than recreated or reverted.
- [ ] Configuration defaults to fake/offline and real summary calls require explicit opt-in.
- [ ] Summary adapter/model/timeout/retries/token cap remain independent from chat selection.
- [ ] LLM input is sanitized before prompt construction.
- [ ] Provider output is sanitized before persistence.
- [ ] A successful chat response does not await summary generation or persistence.
- [ ] Chat-provider failures do not schedule summaries.
- [ ] Scheduler failures and background failures do not break chat.
- [ ] Background jobs own a fresh SQLite connection.
- [ ] Threshold and max-input rules use persisted message count.
- [ ] Coverage uses stable message-list position and remains append-only.
- [ ] One service call writes at most one summary.
- [ ] Final duplicate recheck prevents obvious overlap.
- [ ] Generated summaries do not write to or alter memories, candidates, or embeddings.
- [ ] Generated summaries are not injected into chat context.
- [ ] No frontend, MCP, agent framework, conflict-resolution, emotion, or avatar code was added.
- [ ] Focused tests, full backend tests, runtime verification, and code review have recorded results.
- [ ] Evidence and project status describe only observed behavior.
