# Stage 4E Message-Bound Expression Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only, message-bound expression query and a browser preview whose expression survives reloads while speaking/paused state follows the exact browser playback run.

**Architecture:** FastAPI validates the target message, reads only the supported persisted `ExpressionPlan`, and returns a six-field v1 response or a deterministic neutral default without writing. React keeps expression mapping, preview state, display-label derivation, and playback-run orchestration in focused modules; the audio controller synchronously activates a monotonically increasing `playbackRunId` before asynchronous work and rejects every stale callback by `(assistantMessageId, playbackRunId, generation)`. The preview uses only neutral CSS geometry and text, while SQLite verification proves no runtime presentation state is persisted.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLite, pytest, React, TypeScript, Vite, Vitest, Testing Library, Playwright, existing fake LLM/TTS providers.

---

## Prerequisites and Working-Tree Safety

The repository root is `AI桌宠/`; its parent directory is not a Git repository. The current tree contains extensive uncommitted Stage 3M–4D work in files that Stage 4E must also edit.

Before every task:

```powershell
git -C "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠" status --short
git -C "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠" diff --check
```

Rules:

- Do not run `git reset`, `git restore`, `git checkout --`, `git clean`, `git add .`, `git add -A`, or `git commit -a`.
- Treat all existing changes as user-owned WIP. Read each shared file immediately before editing it.
- Commit checkpoints in this plan are intentionally replaced by diff-review checkpoints: the user has not requested commits, and shared files contain pre-existing work.
- If commits are authorized later, stage exact files or exact hunks only, inspect `git diff --cached`, and never include `.env`, SQLite/WAL/SHM files, `test-results/`, Playwright traces, audio, `.superpowers/`, credentials, or unrelated Stage 3M–4D hunks.
- Run tests from `C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠`. Commands use `.\.venv\Scripts\python.exe`; if it is absent, use the active Python interpreter with identical arguments.

## File Map

### Backend — create

- `backend/app/api/routes/message_expression.py` — read-only `GET /api/messages/{id}/expression` endpoint.
- `backend/tests/test_api_message_expression.py` — HTTP contract, minimal response, 404/422/500, injection resistance, and complete-table read-only snapshots.

### Backend — modify

- `backend/app/domain/models.py` — strict lookup source and lookup result value objects; do not change existing plan constraints.
- `backend/app/core/errors.py` — endpoint-specific 422 and sanitized internal 500 errors.
- `backend/app/domain/schemas.py` — six-field v1 response DTO.
- `backend/app/services/expression_plan_service.py` — role-aware read-only lookup preserving source and safe fallback.
- `backend/app/api/dependencies.py` — dedicated SQLite `mode=ro` + `PRAGMA query_only=ON` connection and expression-query service dependency; unlike normal request dependencies it never calls `init_db()`.
- `backend/app/main.py` — initialize/migrate the configured DB once during application startup before read-only requests can run, then register the new router; do not change unrelated providers or lifecycle work.
- `backend/tests/test_expression_plan_service.py` — lookup behavior, corruption fallback, infrastructure failure propagation, schema compatibility, and read-only stability.

`backend/app/repositories/sqlite.py`, `backend/app/repositories/expression_plans.py`, chat, emotion, provider, and TTS code do not need schema or behavior changes for this query.

### Frontend expression modules — create

- `frontend/src/expression/events.ts` — expression/playback types, strict wire parser, API mapping, and uncached local neutral factory.
- `frontend/src/expression/events.test.ts` — parser, enums, rates, source, IDs, and fallback tests.
- `frontend/src/expression/displayLabel.ts` — deterministic in-memory accessibility label.
- `frontend/src/expression/displayLabel.test.ts` — whitespace, code-point boundary, emoji, role, and empty fallback tests.
- `frontend/src/expression/previewReducer.ts` — Idle/Ready/Speaking/Paused state machine and exact-run filtering.
- `frontend/src/expression/previewReducer.test.ts` — transitions, stale message/run rejection, activation/deactivation, and clearing.
- `frontend/src/hooks/useExpressionPreviewController.ts` — API target orchestration, abort optimization, successful-response cache, local-fallback retry, and synchronous run activation.
- `frontend/src/hooks/useExpressionPreviewController.test.tsx` — stale response, API/default cache, local-fallback non-cache, retry, session clear, and exact-ID selection.
- `frontend/src/components/ExpressionPreview.tsx` — neutral renderer consuming props only.
- `frontend/src/components/ExpressionPreview.test.tsx` — labels, phases, semantics, and reduced-motion-safe output.
- `frontend/src/components/PresentationErrorBoundary.tsx` — isolates preview rendering faults.
- `frontend/src/components/PresentationErrorBoundary.test.tsx` — fallback renders while sibling chat content remains.

### Frontend existing files — modify

- `frontend/src/api/types.ts` — wire response type only.
- `frontend/src/api/client.ts` — `getMessageExpression(id, {signal})` using strict parser.
- `frontend/src/api/client.test.ts` — URL encoding, signal, valid and invalid JSON, and API error propagation.
- `frontend/src/hooks/useAudioPlaybackController.ts` — synchronous run activation, lifecycle events, generation guards, pause/resume, and reasoned reset.
- `frontend/src/hooks/useAudioPlaybackController.streaming.test.tsx` — streaming/non-streaming lifecycle order and stale callbacks.
- `frontend/src/App.tsx` — compose preview controller and audio callbacks; select exact chat response ID; clear on session lifecycle.
- `frontend/src/App.test.tsx` — exact assistant selection, late response, retry, session/delete cleanup, recording interruption, and chat failure isolation.
- `frontend/src/components/ChatLayout.tsx` — render isolated preview without embedding expression logic.
- `frontend/src/styles.css` — neutral preview geometry, text states, and `prefers-reduced-motion`.
- `frontend/src/testSetup.ts` — deterministic `matchMedia` test default if not already present.

`MessageList.tsx` and `AssistantAudioControls.tsx` already pass exact assistant message IDs and expose play/pause/resume/stop/replay. Modify them only if a failing integration test proves a callback cannot be propagated through the existing `audioController` object.

### Acceptance — create

- `frontend/e2e/expression-preview.spec.ts` — fake-only message/expression/playback/session/reload/fallback flow.
- `scripts/verify_stage4e_e2e_database.py` — static no-runtime-presentation-persistence verifier that reuses Stage 4D invariants.
- `tests/test_verify_stage4e_e2e_database.py` — verifier PASS/BLOCKED cases.
- `docs/stage4e-expression-event-browser-preview.md` — evidence written only after verification passes.

### Acceptance — modify

- `frontend/playwright.global-teardown.ts` — run 4C, 4D, then 4E verifier before best-effort DB cleanup.
- `frontend/playwright.global-teardown.test.ts` — order, primary error, and cleanup behavior.
- `frontend/e2e/voice-turn.spec.ts` — assert speaking clears after explicit recording interruption if needed by the new flow.
- `README.md` and `CLAUDE.md` — update only after all acceptance evidence passes.

---

## Task 1: Lock the Read-Only Expression Lookup Contract

**Files:**
- Modify: `backend/app/domain/models.py:120-182`
- Modify: `backend/app/core/errors.py:28-38`
- Modify: `backend/app/services/expression_plan_service.py:1-69`
- Test: `backend/tests/test_expression_plan_service.py`

- [ ] **Step 1: Write failing lookup tests**

Append tests that construct real repositories where persistence matters and small fakes where corruption is required:

```python
from app.core.errors import ExpressionMessageRoleError
from app.domain.models import ExpressionPlanSource


def test_lookup_returns_persisted_v1_plan(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'lookup.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        plans = ExpressionPlanRepository(connection)
        assistant = messages.add(sessions.create("lookup").id, ChatRole.ASSISTANT, "reply")
        service = ExpressionPlanService(messages, plans, ExpressionPlanPolicy())
        created = service.create_for_assistant_message(
            assistant.id,
            snapshot(EmotionVector(0.5, 0.8, 0.8, 0.2, 0.1, 0.2), version=7),
        )

        lookup = service.get_for_assistant_message(assistant.id)

        assert created is not None
        assert lookup.assistant_message_id == assistant.id
        assert lookup.schema_version == 1
        assert lookup.source is ExpressionPlanSource.PERSISTED_PLAN
        assert lookup.expression.delivery is created.delivery
        assert lookup.expression.rate == created.rate
        assert lookup.expression.intensity is created.intensity


def test_lookup_returns_default_without_writing(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'history.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        plans = ExpressionPlanRepository(connection)
        assistant = messages.add(sessions.create("history").id, ChatRole.ASSISTANT, "old reply")
        service = ExpressionPlanService(messages, plans, ExpressionPlanPolicy())

        first = service.get_for_assistant_message(assistant.id)
        second = service.get_for_assistant_message(assistant.id)

        assert first == second
        assert first.source is ExpressionPlanSource.DEFAULT
        assert first.expression.delivery is ExpressionDelivery.NEUTRAL
        assert first.expression.intensity is ExpressionIntensity.LOW
        assert first.expression.rate == 1.0
        assert plans.get(assistant.id) is None


def test_lookup_rejects_missing_and_user_messages(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'lookup-roles.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        user = messages.add(sessions.create("roles").id, ChatRole.USER, "hello")
        service = ExpressionPlanService(messages, ExpressionPlanRepository(connection), ExpressionPlanPolicy())

        with pytest.raises(NotFoundError):
            service.get_for_assistant_message("missing")
        with pytest.raises(ExpressionMessageRoleError):
            service.get_for_assistant_message(user.id)


def test_lookup_defaults_for_corrupt_plan_but_not_for_database_failure() -> None:
    assistant = type("Message", (), {"id": "assistant-1", "role": ChatRole.ASSISTANT})()

    class Messages:
        def get(self, _message_id: str):
            return assistant

    class CorruptPlans:
        def get(self, _message_id: str, *, schema_version: int = 1):
            assert schema_version == 1
            raise ValueError("corrupt enum")

    class BrokenPlans:
        def get(self, _message_id: str, *, schema_version: int = 1):
            assert schema_version == 1
            raise sqlite3.OperationalError("database unavailable")

    corrupt = ExpressionPlanService(Messages(), CorruptPlans(), ExpressionPlanPolicy())  # type: ignore[arg-type]
    broken = ExpressionPlanService(Messages(), BrokenPlans(), ExpressionPlanPolicy())  # type: ignore[arg-type]

    assert corrupt.get_for_assistant_message("assistant-1").source is ExpressionPlanSource.DEFAULT
    with pytest.raises(sqlite3.OperationalError):
        broken.get_for_assistant_message("assistant-1")
```

Add a future-schema test by creating a draft through the repository with `schema_version=2`; the v1 lookup must return default while leaving the v2 row unchanged.

- [ ] **Step 2: Run the tests and confirm RED**

```powershell
$env:PYTHONPATH = "backend;."
.\.venv\Scripts\python.exe -m pytest backend\tests\test_expression_plan_service.py -q
```

Expected: collection fails because `ExpressionPlanSource`, `ExpressionMessageRoleError`, and `get_for_assistant_message` do not exist.

- [ ] **Step 3: Add strict lookup value objects**

Add beside the existing expression types in `backend/app/domain/models.py`:

```python
class ExpressionPlanSource(StrEnum):
    PERSISTED_PLAN = "persisted_plan"
    DEFAULT = "default"


@dataclass(frozen=True)
class ExpressionPlanLookup:
    assistant_message_id: str
    schema_version: int
    expression: ResolvedExpression
    source: ExpressionPlanSource

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version < 1:
            raise ValueError("expression lookup schema version must be positive")
```

Do not add message text, plan ID, source emotion version, vector, reason, provider options, UI label, or playback state.

- [ ] **Step 4: Add the dedicated 422 error**

Add to `backend/app/core/errors.py` without changing `ValidationAppError`:

```python
class ExpressionMessageRoleError(AppError):
    code = "expression_message_not_assistant"
    message = "只能查询助手消息的表达。"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY


class InternalServerError(AppError):
    code = "internal_error"
    message = "请求处理失败，请稍后重试。"
    status_code = HTTPStatus.INTERNAL_SERVER_ERROR
```

- [ ] **Step 5: Implement the minimal read-only service method**

Import the new types and error, then add this method while preserving `create_for_assistant_message()` and `resolve_compatible_or_default()` unchanged:

```python
def get_for_assistant_message(self, assistant_message_id: str) -> ExpressionPlanLookup:
    message = self._messages.get(assistant_message_id)
    if message is None:
        raise NotFoundError("消息不存在。")
    if message.role is not ChatRole.ASSISTANT:
        raise ExpressionMessageRoleError()

    try:
        plan = self._plans.get(
            message.id,
            schema_version=EXPRESSION_PLAN_SCHEMA_VERSION,
        )
        if plan is None:
            expression = DEFAULT_EXPRESSION
            source = ExpressionPlanSource.DEFAULT
        else:
            expression = ResolvedExpression(plan.delivery, plan.rate, plan.intensity)
            source = ExpressionPlanSource.PERSISTED_PLAN
    except (TypeError, ValueError, OverflowError):
        expression = DEFAULT_EXPRESSION
        source = ExpressionPlanSource.DEFAULT

    return ExpressionPlanLookup(
        assistant_message_id=message.id,
        schema_version=EXPRESSION_PLAN_SCHEMA_VERSION,
        expression=expression,
        source=source,
    )
```

Do not catch `sqlite3.Error`, `OSError`, or broad `Exception`; infrastructure failures must reach the API's sanitized 500 conversion.

- [ ] **Step 6: Run focused service tests and confirm GREEN**

```powershell
$env:PYTHONPATH = "backend;."
.\.venv\Scripts\python.exe -m pytest backend\tests\test_expression_plan_service.py -q
```

Expected: all tests in the file pass, including existing Stage 4D creation/TTS-resolution tests.

- [ ] **Step 7: Review the task diff without staging**

```powershell
git diff --check -- backend/app/domain/models.py backend/app/core/errors.py backend/app/services/expression_plan_service.py backend/tests/test_expression_plan_service.py
git diff -- backend/app/domain/models.py backend/app/core/errors.py backend/app/services/expression_plan_service.py backend/tests/test_expression_plan_service.py
```

Expected: only lookup types, two errors, the read-only method, and direct tests; no provider, TTS, schema, or unrelated Stage 4D changes.

---

## Task 2: Expose the Minimal GET API and Prove It Uses a Read-Only Connection

**Files:**
- Modify: `backend/app/domain/schemas.py:19-54`
- Modify: `backend/app/api/dependencies.py:1-60,194-202`
- Create: `backend/app/api/routes/message_expression.py`
- Modify: `backend/app/main.py:42-71,153-169`
- Create: `backend/tests/test_api_message_expression.py`

- [ ] **Step 1: Write failing API contract tests**

Create helper functions using the existing `client` fixture:

```python
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.dependencies import get_expression_query_service


def create_chat(client: TestClient) -> tuple[str, str]:
    session = client.post("/api/sessions", json={"title": "expression"}).json()
    chat = client.post(
        f"/api/sessions/{session['id']}/messages",
        json={"content": "hello"},
    ).json()
    messages = client.get(f"/api/sessions/{session['id']}/messages").json()
    user_id = next(item["id"] for item in messages if item["role"] == "user")
    return user_id, chat["assistant_message_id"]


def api_database_path(tmp_path: Path) -> Path:
    return tmp_path / "api.db"


def database_snapshot(database_path: Path) -> dict[str, tuple[tuple[object, ...], ...]]:
    with sqlite3.connect(database_path) as connection:
        table_names = tuple(
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        )
        return {
            table: tuple(
                tuple(row)
                for row in connection.execute(
                    f'SELECT rowid, * FROM "{table}" ORDER BY rowid'
                )
            )
            for table in table_names
        }
```

Add these exact behavioral tests:

```python
def test_expression_get_returns_minimal_persisted_plan(client: TestClient) -> None:
    _, assistant_id = create_chat(client)

    response = client.get(f"/api/messages/{assistant_id}/expression")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "assistant_message_id", "schema_version", "delivery",
        "intensity", "rate", "source",
    }
    assert body["assistant_message_id"] == assistant_id
    assert body["schema_version"] == 1
    assert body["delivery"] in {"neutral", "warm", "reassuring", "reserved", "firm"}
    assert body["intensity"] in {"low", "medium"}
    assert 0.90 <= body["rate"] <= 1.10
    assert body["source"] == "persisted_plan"


def test_expression_get_returns_default_for_history_without_plan(
    client: TestClient,
    tmp_path: Path,
) -> None:
    _, assistant_id = create_chat(client)
    database_path = api_database_path(tmp_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "DELETE FROM expression_plans WHERE assistant_message_id = ?",
            (assistant_id,),
        )
        connection.commit()

    first = client.get(f"/api/messages/{assistant_id}/expression")
    second = client.get(f"/api/messages/{assistant_id}/expression")

    expected = {
        "assistant_message_id": assistant_id,
        "schema_version": 1,
        "delivery": "neutral",
        "intensity": "low",
        "rate": 1.0,
        "source": "default",
    }
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == expected
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM expression_plans WHERE assistant_message_id = ?",
            (assistant_id,),
        ).fetchone()[0] == 0


def test_expression_get_has_explicit_404_and_422(client: TestClient) -> None:
    user_id, _ = create_chat(client)

    missing = client.get("/api/messages/missing/expression")
    wrong_role = client.get(f"/api/messages/{user_id}/expression")

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert wrong_role.status_code == 422
    assert wrong_role.json()["error"]["code"] == "expression_message_not_assistant"


def test_expression_get_ignores_injected_query_parameters(client: TestClient) -> None:
    _, assistant_id = create_chat(client)
    original = client.get(f"/api/messages/{assistant_id}/expression").json()

    injected = client.get(
        f"/api/messages/{assistant_id}/expression",
        params={"delivery": "firm", "intensity": "medium", "rate": "1.1", "ssml": "<break/>"},
    )

    assert injected.status_code == 200
    assert injected.json() == original
```

For the read-only proof, call `database_snapshot(api_database_path(tmp_path))` before and after two persisted-plan GETs and two default GETs, then compare the complete dynamic table map. Because tables are enumerated from `sqlite_master`, the test automatically includes current tables such as `memory_embeddings` and `emotion_analysis_consents` and cannot silently ignore a future application table. Exclude only SQLite-owned tables whose names begin with `sqlite_`.

For 500 sanitization, use the existing `client` fixture and override `get_expression_query_service` with an object whose `get_for_assistant_message()` raises `sqlite3.OperationalError("private database detail")`. Dependency exceptions are handled by the route's explicit conversion and `AppError` handler, so no separate client is needed. Assert status 500 and the exact `internal_error` envelope, assert the private text is absent, and remove the dependency override in `finally`.

- [ ] **Step 2: Run API tests and confirm RED**

```powershell
$env:PYTHONPATH = "backend;."
.\.venv\Scripts\python.exe -m pytest backend\tests\test_api_message_expression.py -q
```

Expected: 404 for the absent route or import failure for `get_expression_query_service`/schema usage in the new test.

- [ ] **Step 3: Add the six-field Pydantic response**

Append to `backend/app/domain/schemas.py`:

```python
class MessageExpressionResponse(BaseModel):
    assistant_message_id: str
    schema_version: Literal[1]
    delivery: Literal["neutral", "warm", "reassuring", "reserved", "firm"]
    intensity: Literal["low", "medium"]
    rate: float = Field(ge=0.90, le=1.10)
    source: Literal["persisted_plan", "default"]
```

- [ ] **Step 4: Add a dedicated query-only dependency and startup initialization**

In `backend/app/api/dependencies.py`, import `resolve_sqlite_path` and create a connection dependency that never calls `connect()`, `managed_connection()`, or `init_db()`:

```python
def get_read_only_connection(
    settings: Settings = Depends(get_settings),
) -> Iterator[sqlite3.Connection]:
    path = resolve_sqlite_path(settings.database_url).resolve()
    connection = sqlite3.connect(
        f"file:{path.as_posix()}?mode=ro",
        uri=True,
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA query_only = ON")
    try:
        yield connection
    finally:
        connection.close()


def get_expression_query_service(
    connection: sqlite3.Connection = Depends(get_read_only_connection),
) -> ExpressionPlanService:
    return ExpressionPlanService(
        MessageRepository(connection),
        ExpressionPlanRepository(connection),
        ExpressionPlanPolicy(),
    )
```

Keep existing `get_connection` and `get_expression_plan_service` unchanged for write-capable chat/TTS behavior.

A `mode=ro` dependency requires schema initialization before the first request. In the existing FastAPI lifespan, before recovery jobs and before `yield`, add one startup block using the existing write-capable managed connection:

```python
with managed_connection(settings.database_url):
    pass
```

This centralizes creation/migrations at application startup. The expression GET itself then opens only `mode=ro` + `query_only` connections. Add a dependency test that overrides settings with an initialized temp DB, resolves `get_read_only_connection`, asserts `PRAGMA query_only` equals `1`, and asserts `CREATE TABLE`, `INSERT`, and `ALTER TABLE` fail with `sqlite3.OperationalError`. Also monkeypatch `init_db` or `managed_connection` after app startup and prove an expression GET does not call it.

- [ ] **Step 5: Implement the independent read-only route**

Create `backend/app/api/routes/message_expression.py`:

```python
from fastapi import APIRouter, Depends

from app.api.dependencies import get_expression_query_service
from app.core.errors import AppError, InternalServerError
from app.domain.schemas import MessageExpressionResponse
from app.services.expression_plan_service import ExpressionPlanService

router = APIRouter(prefix="/api/messages", tags=["expression"])


@router.get(
    "/{assistant_message_id}/expression",
    response_model=MessageExpressionResponse,
)
def get_message_expression(
    assistant_message_id: str,
    service: ExpressionPlanService = Depends(get_expression_query_service),
) -> MessageExpressionResponse:
    try:
        lookup = service.get_for_assistant_message(assistant_message_id)
    except AppError:
        raise
    except Exception as exc:
        raise InternalServerError() from exc
    return MessageExpressionResponse(
        assistant_message_id=lookup.assistant_message_id,
        schema_version=lookup.schema_version,
        delivery=lookup.expression.delivery.value,
        intensity=lookup.expression.intensity.value,
        rate=lookup.expression.rate,
        source=lookup.source.value,
    )
```

The broad conversion is intentionally restricted to this endpoint boundary. It never returns `str(exc)` and does not modify the application's global error behavior.

- [ ] **Step 6: Register only the new router**

Add `message_expression` to the route import in `backend/app/main.py`, then register it next to message-bound speech:

```python
app.include_router(message_speech.router)
app.include_router(message_expression.router)
```

Do not modify lifespan, providers, CORS, existing error handling, or TTS routes.

- [ ] **Step 7: Run API and neighboring Stage 4D tests**

```powershell
$env:PYTHONPATH = "backend;."
.\.venv\Scripts\python.exe -m pytest `
  backend\tests\test_expression_plan_service.py `
  backend\tests\test_api_message_expression.py `
  backend\tests\test_api_message_speech.py -q
```

Expected: all tests pass; GET responses have exactly six fields and POST speech behavior is unchanged.

- [ ] **Step 8: Review the backend API diff without staging**

```powershell
git diff --check -- backend/app/domain/schemas.py backend/app/api/dependencies.py backend/app/api/routes/message_expression.py backend/app/main.py backend/tests/test_api_message_expression.py
git diff -- backend/app/domain/schemas.py backend/app/api/dependencies.py backend/app/api/routes/message_expression.py backend/app/main.py backend/tests/test_api_message_expression.py
```

Expected: one response schema, one query-only connection/service dependency, startup-only schema initialization, one route, one router registration, and direct tests only.

---

## Task 3: Define Strict Frontend Expression Events and Display Labels

**Files:**
- Modify: `frontend/src/api/types.ts:16-31`
- Create: `frontend/src/expression/events.ts`
- Create: `frontend/src/expression/events.test.ts`
- Create: `frontend/src/expression/displayLabel.ts`
- Create: `frontend/src/expression/displayLabel.test.ts`

- [ ] **Step 1: Write failing event/parser tests**

Create `events.test.ts` with valid mapping and a table of invalid payloads:

```ts
import { describe, expect, it } from 'vitest';
import { expressionEventFromApi, localNeutralExpression, parseMessageExpressionResponse } from './events';

const valid = {
  assistant_message_id: 'assistant-1',
  schema_version: 1,
  delivery: 'reassuring',
  intensity: 'medium',
  rate: 0.96,
  source: 'persisted_plan',
};

describe('parseMessageExpressionResponse', () => {
  it('accepts and maps the complete v1 response', () => {
    const parsed = parseMessageExpressionResponse(valid);
    expect(expressionEventFromApi(parsed)).toEqual({
      type: 'expression',
      assistantMessageId: 'assistant-1',
      schemaVersion: 1,
      delivery: 'reassuring',
      intensity: 'medium',
      rate: 0.96,
      source: 'persisted_plan',
    });
  });

  it.each([
    null,
    {},
    { ...valid, assistant_message_id: '' },
    { ...valid, schema_version: 2 },
    { ...valid, delivery: 'excited' },
    { ...valid, intensity: 'high' },
    { ...valid, rate: Number.NaN },
    { ...valid, rate: 0.89 },
    { ...valid, rate: 1.11 },
    { ...valid, source: 'client' },
  ])('rejects an invalid wire payload %#', (payload) => {
    expect(() => parseMessageExpressionResponse(payload)).toThrow('表达服务返回了无法处理的结果。');
  });

  it('creates a neutral local fallback with a distinct internal origin', () => {
    expect(localNeutralExpression('assistant-2')).toEqual({
      origin: 'local_fallback',
      event: {
        type: 'expression', assistantMessageId: 'assistant-2', schemaVersion: 1,
        delivery: 'neutral', intensity: 'low', rate: 1, source: 'default',
      },
    });
  });
});
```

- [ ] **Step 2: Write failing display-label tests**

Create `displayLabel.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import type { Message } from '../api/types';
import { displayLabelForAssistantMessage } from './displayLabel';

function message(id: string, role: Message['role'], content: string): Message {
  return { id, session_id: 'session-1', role, content, created_at: '2026-07-14T00:00:00Z', metadata: {} };
}

describe('displayLabelForAssistantMessage', () => {
  it('folds whitespace and trims', () => {
    expect(displayLabelForAssistantMessage([message('a', 'assistant', '  第一行\n\t第二行  ')], 'a'))
      .toBe('第一行 第二行');
  });

  it('truncates by Unicode code point and appends one ellipsis', () => {
    const content = `${'雪'.repeat(79)}😀尾`;
    const label = displayLabelForAssistantMessage([message('a', 'assistant', content)], 'a');
    expect(Array.from(label.slice(0, -1))).toHaveLength(80);
    expect(Array.from(label.slice(0, -1)).at(-1)).toBe('😀');
    expect(label.endsWith('😀…')).toBe(true);
  });

  it.each([
    [[], 'a'],
    [[message('a', 'user', 'not allowed')], 'a'],
    [[message('a', 'assistant', ' \n\t ')], 'a'],
  ] as const)('uses the fixed fallback for missing, wrong-role, or empty content', (messages, id) => {
    expect(displayLabelForAssistantMessage(messages, id)).toBe('助手消息');
  });
});
```

- [ ] **Step 3: Run both test files and confirm RED**

```powershell
npm --prefix frontend run test -- src/expression/events.test.ts src/expression/displayLabel.test.ts
```

Expected: module resolution fails because both implementation files are absent.

- [ ] **Step 4: Add the wire type**

Add to `frontend/src/api/types.ts`:

```ts
export type ExpressionDelivery = 'neutral' | 'warm' | 'reassuring' | 'reserved' | 'firm';
export type ExpressionIntensity = 'low' | 'medium';

export interface MessageExpressionResponse {
  assistant_message_id: string;
  schema_version: 1;
  delivery: ExpressionDelivery;
  intensity: ExpressionIntensity;
  rate: number;
  source: 'persisted_plan' | 'default';
}
```

- [ ] **Step 5: Implement events, parser, and local fallback**

Create `events.ts` with these public types and checks:

```ts
import type {
  ExpressionDelivery,
  ExpressionIntensity,
  MessageExpressionResponse,
} from '../api/types';

const DELIVERIES = new Set<ExpressionDelivery>(['neutral', 'warm', 'reassuring', 'reserved', 'firm']);
const INTENSITIES = new Set<ExpressionIntensity>(['low', 'medium']);
const SOURCES = new Set<MessageExpressionResponse['source']>(['persisted_plan', 'default']);

export interface ExpressionEvent {
  type: 'expression';
  assistantMessageId: string;
  schemaVersion: 1;
  delivery: ExpressionDelivery;
  intensity: ExpressionIntensity;
  rate: number;
  source: MessageExpressionResponse['source'];
}

export interface PlaybackRun {
  assistantMessageId: string;
  playbackRunId: number;
}

export interface SpeakingEvent extends PlaybackRun {
  type: 'speaking';
  phase: 'started' | 'paused' | 'resumed' | 'stopped' | 'interrupted' | 'failed';
}

export interface ResolvedExpression {
  event: ExpressionEvent;
  origin: 'api' | 'local_fallback';
}

export function parseMessageExpressionResponse(value: unknown): MessageExpressionResponse {
  if (typeof value !== 'object' || value === null) throw new Error('表达服务返回了无法处理的结果。');
  const item = value as Record<string, unknown>;
  if (
    typeof item.assistant_message_id !== 'string' || item.assistant_message_id.length === 0 ||
    item.schema_version !== 1 ||
    !DELIVERIES.has(item.delivery as ExpressionDelivery) ||
    !INTENSITIES.has(item.intensity as ExpressionIntensity) ||
    typeof item.rate !== 'number' || !Number.isFinite(item.rate) || item.rate < 0.9 || item.rate > 1.1 ||
    !SOURCES.has(item.source as MessageExpressionResponse['source'])
  ) throw new Error('表达服务返回了无法处理的结果。');
  return item as unknown as MessageExpressionResponse;
}

export function expressionEventFromApi(value: MessageExpressionResponse): ExpressionEvent {
  return {
    type: 'expression',
    assistantMessageId: value.assistant_message_id,
    schemaVersion: value.schema_version,
    delivery: value.delivery,
    intensity: value.intensity,
    rate: value.rate,
    source: value.source,
  };
}

export function localNeutralExpression(assistantMessageId: string): ResolvedExpression {
  return {
    origin: 'local_fallback',
    event: {
      type: 'expression', assistantMessageId, schemaVersion: 1,
      delivery: 'neutral', intensity: 'low', rate: 1, source: 'default',
    },
  };
}
```

- [ ] **Step 6: Implement exact display-label derivation**

Create `displayLabel.ts`:

```ts
import type { Message } from '../api/types';

const FALLBACK_LABEL = '助手消息';
const MAX_CODE_POINTS = 80;

export function displayLabelForAssistantMessage(
  messages: readonly Message[],
  assistantMessageId: string,
): string {
  const message = messages.find(
    (candidate) => candidate.id === assistantMessageId && candidate.role === 'assistant',
  );
  const normalized = (message?.content ?? '').replace(/\s+/gu, ' ').trim();
  if (!normalized) return FALLBACK_LABEL;
  const codePoints = Array.from(normalized);
  return codePoints.length <= MAX_CODE_POINTS
    ? normalized
    : `${codePoints.slice(0, MAX_CODE_POINTS).join('')}…`;
}
```

- [ ] **Step 7: Run focused tests and confirm GREEN**

```powershell
npm --prefix frontend run test -- src/expression/events.test.ts src/expression/displayLabel.test.ts
```

Expected: all parser and label tests pass.

---

## Task 4: Add the Strict Frontend Expression API Client

**Files:**
- Modify: `frontend/src/api/client.ts:1-18,76-102`
- Modify: `frontend/src/api/client.test.ts`

- [ ] **Step 1: Write failing client tests**

Add tests using the existing fetch mock style:

```ts
it('gets and validates a message-bound expression with the provided signal', async () => {
  const signal = new AbortController().signal;
  vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({
    assistant_message_id: 'assistant / 1', schema_version: 1,
    delivery: 'warm', intensity: 'medium', rate: 1.04, source: 'persisted_plan',
  }), { status: 200, headers: { 'Content-Type': 'application/json' } }));

  await expect(apiClient.getMessageExpression('assistant / 1', { signal })).resolves.toMatchObject({
    assistant_message_id: 'assistant / 1', source: 'persisted_plan',
  });
  expect(fetch).toHaveBeenCalledWith(
    '/api/messages/assistant%20%2F%201/expression',
    expect.objectContaining({ signal }),
  );
});

it('rejects malformed expression JSON at the network boundary', async () => {
  vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({
    assistant_message_id: 'assistant-1', schema_version: 1,
    delivery: 'unknown', intensity: 'low', rate: 1, source: 'default',
  }), { status: 200, headers: { 'Content-Type': 'application/json' } }));

  await expect(apiClient.getMessageExpression('assistant-1'))
    .rejects.toThrow('表达服务返回了无法处理的结果。');
});
```

Also assert a 404/422 envelope is surfaced through the existing public message and an aborted fetch remains an `AbortError` rather than becoming a neutral value in the client. Neutral fallback belongs to the preview controller, not the API client.

- [ ] **Step 2: Run the focused client test and confirm RED**

```powershell
npm --prefix frontend run test -- src/api/client.test.ts
```

Expected: TypeScript/test failure because `getMessageExpression` does not exist.

- [ ] **Step 3: Implement the client method**

Import `MessageExpressionResponse` and `parseMessageExpressionResponse`, then add:

```ts
getMessageExpression(
  assistantMessageId: string,
  options: { signal?: AbortSignal } = {},
): Promise<MessageExpressionResponse> {
  return requestJson<unknown>(
    `/api/messages/${encodeURIComponent(assistantMessageId)}/expression`,
    { signal: options.signal },
  ).then(parseMessageExpressionResponse);
},
```

Do not accept delivery, intensity, rate, style, SSML, text, or provider options.

- [ ] **Step 4: Run client and expression tests**

```powershell
npm --prefix frontend run test -- src/api/client.test.ts src/expression/events.test.ts
```

Expected: all tests pass and existing speech/chat client tests remain green.

---

## Task 5: Implement the Pure Preview State Machine

**Files:**
- Create: `frontend/src/expression/previewReducer.ts`
- Create: `frontend/src/expression/previewReducer.test.ts`

- [ ] **Step 1: Write failing reducer tests**

Test target selection, expression acceptance, activation, phases, stale run rejection, terminal behavior, and clearing:

```ts
import { describe, expect, it } from 'vitest';
import {
  initialExpressionPreviewState,
  expressionPreviewReducer,
} from './previewReducer';
import type { ExpressionEvent, PlaybackRun, SpeakingEvent } from './events';

const expression: ExpressionEvent = {
  type: 'expression', assistantMessageId: 'a', schemaVersion: 1,
  delivery: 'warm', intensity: 'medium', rate: 1.04, source: 'persisted_plan',
};
const run1: PlaybackRun = { assistantMessageId: 'a', playbackRunId: 1 };
const run2: PlaybackRun = { assistantMessageId: 'a', playbackRunId: 2 };
const speaking = (run: PlaybackRun, phase: SpeakingEvent['phase']): SpeakingEvent => ({
  type: 'speaking', ...run, phase,
});

it('moves idle -> ready -> speaking -> paused -> speaking -> ready', () => {
  let state = expressionPreviewReducer(initialExpressionPreviewState, {
    type: 'targetSelected', assistantMessageId: 'a',
  });
  state = expressionPreviewReducer(state, { type: 'expressionResolved', expression });
  state = expressionPreviewReducer(state, { type: 'runActivated', run: run1 });
  state = expressionPreviewReducer(state, { type: 'speaking', event: speaking(run1, 'started') });
  expect(state.phase).toBe('speaking');
  state = expressionPreviewReducer(state, { type: 'speaking', event: speaking(run1, 'paused') });
  expect(state.phase).toBe('paused');
  state = expressionPreviewReducer(state, { type: 'speaking', event: speaking(run1, 'resumed') });
  expect(state.phase).toBe('speaking');
  state = expressionPreviewReducer(state, { type: 'speaking', event: speaking(run1, 'stopped') });
  expect(state).toMatchObject({ phase: 'ready', activeRun: null, expression });
});

it('ignores late expression and every event from an old run', () => {
  let state = expressionPreviewReducer(initialExpressionPreviewState, {
    type: 'targetSelected', assistantMessageId: 'a',
  });
  state = expressionPreviewReducer(state, { type: 'expressionResolved', expression });
  state = expressionPreviewReducer(state, { type: 'runActivated', run: run2 });
  const before = state;
  expect(expressionPreviewReducer(state, { type: 'speaking', event: speaking(run1, 'started') })).toBe(before);
  expect(expressionPreviewReducer(state, {
    type: 'expressionResolved', expression: { ...expression, assistantMessageId: 'old' },
  })).toBe(before);
});
```

Also test `failed` before `started`, `interrupted`, `runDeactivated`, selection of another message clears old expression/run, and `cleared` returns the initial state.

- [ ] **Step 2: Run and confirm RED**

```powershell
npm --prefix frontend run test -- src/expression/previewReducer.test.ts
```

Expected: module resolution failure.

- [ ] **Step 3: Implement the reducer**

```ts
import type { ExpressionEvent, PlaybackRun, SpeakingEvent } from './events';

export type PreviewPhase = 'idle' | 'ready' | 'speaking' | 'paused';

export interface ExpressionPreviewState {
  selectedAssistantMessageId: string | null;
  expression: ExpressionEvent | null;
  activeRun: PlaybackRun | null;
  phase: PreviewPhase;
}

export type PreviewAction =
  | { type: 'targetSelected'; assistantMessageId: string }
  | { type: 'expressionResolved'; expression: ExpressionEvent }
  | { type: 'runActivated'; run: PlaybackRun }
  | { type: 'speaking'; event: SpeakingEvent }
  | { type: 'runDeactivated'; run: PlaybackRun }
  | { type: 'cleared' };

export const initialExpressionPreviewState: ExpressionPreviewState = {
  selectedAssistantMessageId: null,
  expression: null,
  activeRun: null,
  phase: 'idle',
};

function sameRun(left: PlaybackRun | null, right: PlaybackRun): boolean {
  return left?.assistantMessageId === right.assistantMessageId &&
    left.playbackRunId === right.playbackRunId;
}

export function expressionPreviewReducer(
  state: ExpressionPreviewState,
  action: PreviewAction,
): ExpressionPreviewState {
  if (action.type === 'cleared') return initialExpressionPreviewState;
  if (action.type === 'targetSelected') {
    if (state.selectedAssistantMessageId === action.assistantMessageId) return state;
    return { selectedAssistantMessageId: action.assistantMessageId, expression: null, activeRun: null, phase: 'idle' };
  }
  if (action.type === 'expressionResolved') {
    if (action.expression.assistantMessageId !== state.selectedAssistantMessageId) return state;
    return { ...state, expression: action.expression, phase: state.activeRun ? state.phase : 'ready' };
  }
  if (action.type === 'runActivated') {
    const changedMessage = state.selectedAssistantMessageId !== action.run.assistantMessageId;
    return {
      selectedAssistantMessageId: action.run.assistantMessageId,
      expression: changedMessage ? null : state.expression,
      activeRun: action.run,
      phase: changedMessage || !state.expression ? 'idle' : 'ready',
    };
  }
  if (action.type === 'runDeactivated') {
    if (!sameRun(state.activeRun, action.run)) return state;
    return { ...state, activeRun: null, phase: state.expression ? 'ready' : 'idle' };
  }
  if (!sameRun(state.activeRun, action.event)) return state;
  if (action.event.phase === 'started' || action.event.phase === 'resumed') return { ...state, phase: 'speaking' };
  if (action.event.phase === 'paused') return { ...state, phase: 'paused' };
  return { ...state, activeRun: null, phase: state.expression ? 'ready' : 'idle' };
}
```

- [ ] **Step 4: Run reducer tests and confirm GREEN**

```powershell
npm --prefix frontend run test -- src/expression/previewReducer.test.ts
```

Expected: all state transitions and stale-event tests pass.

---

## Task 6: Add Playback Run Activation and Lifecycle Events

**Files:**
- Modify: `frontend/src/hooks/useAudioPlaybackController.ts:21-27,44-420`
- Modify: `frontend/src/hooks/useAudioPlaybackController.streaming.test.tsx`
- Test existing integration: `frontend/src/components/MessageList.test.tsx`

This is the highest-risk task. Keep existing public methods and audio state semantics; add run identity and callbacks without rewriting the audio stack.

- [ ] **Step 1: Write failing activation-order tests**

Extend the hook harness so it passes callback spies. Assert `onRunActivated` happens synchronously before `fetch`, `audio.play`, scheduler creation/enqueue, or the first `await` continuation:

```ts
const order: string[] = [];
const onRunActivated = vi.fn(() => { order.push('activated'); return true; });
vi.mocked(fetch).mockImplementation(async () => {
  order.push('fetch');
  return speechResponse();
});

const { result } = renderHook(() => useAudioPlaybackController({ onRunActivated }));
let playPromise!: Promise<boolean>;
act(() => { playPromise = result.current.play('assistant-1'); });
expect(order[0]).toBe('activated');
expect(onRunActivated).toHaveBeenCalledWith({ assistantMessageId: 'assistant-1', playbackRunId: 1 });
await act(async () => { await playPromise; });
```

Add an activation-refusal test where `onRunActivated` returns `false`; assert no speech request, no Blob URL, no scheduler, no audio play, and `play()` resolves `false`.

- [ ] **Step 2: Write failing lifecycle and stale-run tests**

Cover both non-streaming and streaming paths:

- first successful browser-observable start emits exactly one `started`;
- pause emits `paused`; resume emits `resumed`, never a second `started`;
- explicit stop emits `stopped` then deactivates;
- `reset('interrupted')` emits `interrupted` then deactivates;
- pre-start fetch/decode/play failure emits `failed` without `started`;
- replay of the same message allocates run 2;
- a retained old run-specific HTML `ended` closure, rejected old `audio.play()`, old stream event, or old `waitForIdle()` completion cannot update run 2 or emit a terminal event for it;
- starting message B invalidates message A before activating B.

Use deferred promises already used in the file. Capture the old run-specific ended closure before replay and invoke it after run 2 starts; expected current state remains playing and the event log contains no run-2 termination.

- [ ] **Step 3: Run focused tests and confirm RED**

```powershell
npm --prefix frontend run test -- src/hooks/useAudioPlaybackController.streaming.test.tsx
```

Expected: failures because callback options, run IDs, lifecycle events, and reasoned reset do not exist.

- [ ] **Step 4: Add callback and run types to the hook options**

Import `PlaybackRun` and `SpeakingEvent`, export the options type, and use:

```ts
export interface UseAudioPlaybackControllerOptions {
  audioOutputDeviceId?: string;
  onRunActivated?: (run: PlaybackRun) => boolean;
  onRunDeactivated?: (run: PlaybackRun) => void;
  onSpeakingEvent?: (event: SpeakingEvent) => void;
}

type TerminationPhase = Extract<SpeakingEvent['phase'], 'stopped' | 'interrupted' | 'failed'>;
```

Keep latest callbacks in refs so callback identity changes do not recreate/reset the controller:

```ts
const callbacksRef = useRef(options);
callbacksRef.current = options;
const playbackGenerationRef = useRef(0);
const nextPlaybackRunIdRef = useRef(0);
const activeRunRef = useRef<PlaybackRun | null>(null);
const runStartedRef = useRef(false);
const htmlEndedListenerRef = useRef<(() => void) | null>(null);
const schedulerRunRef = useRef<PlaybackRun | null>(null);
```

- [ ] **Step 5: Implement synchronous activation and exact-run guards**

Add focused helpers:

```ts
function sameRun(left: PlaybackRun | null, right: PlaybackRun): boolean {
  return left?.assistantMessageId === right.assistantMessageId && left.playbackRunId === right.playbackRunId;
}

const isCurrentRun = useCallback((run: PlaybackRun, generation: number) =>
  playbackGenerationRef.current === generation && sameRun(activeRunRef.current, run), []);

const emitSpeaking = useCallback((run: PlaybackRun, phase: SpeakingEvent['phase']) => {
  if (!sameRun(activeRunRef.current, run)) return;
  callbacksRef.current.onSpeakingEvent?.({ type: 'speaking', ...run, phase });
}, []);

const deactivateRun = useCallback((run: PlaybackRun) => {
  if (!sameRun(activeRunRef.current, run)) return;
  activeRunRef.current = null;
  callbacksRef.current.onRunDeactivated?.(run);
}, []);

const activateRun = useCallback((assistantMessageId: string): { run: PlaybackRun; generation: number } | null => {
  const oldRun = activeRunRef.current;
  playbackGenerationRef.current += 1;
  if (oldRun) {
    callbacksRef.current.onSpeakingEvent?.({ type: 'speaking', ...oldRun, phase: 'interrupted' });
    activeRunRef.current = null;
    callbacksRef.current.onRunDeactivated?.(oldRun);
  }
  const run = { assistantMessageId, playbackRunId: ++nextPlaybackRunIdRef.current };
  if (callbacksRef.current.onRunActivated?.(run) === false) return null;
  activeRunRef.current = run;
  runStartedRef.current = false;
  return { run, generation: playbackGenerationRef.current };
}, []);
```

The activation helper must not merely notify callbacks. Before activating the next run, call a synchronous `terminateCurrentRun('interrupted')` that performs this exact order:

```text
increment generation and capture old run
→ abort old fetch/stream
→ stop old scheduler
→ remove old run-specific HTML ended listener
→ pause/reset old HTML audio and release run-owned transient URLs/queues
→ emit interrupted for old run
→ onRunDeactivated(old run)
→ clear old active refs
→ onRunActivated(new run)
→ only then start new async work
```

This guarantees message A cannot continue sounding while B synthesizes. `play()` and `replay()` allocate exactly one run after old media is silent and before fetch/decode/play. Refactor internal `playExisting()` to accept the already activated `{run, generation}`; it must never activate a second run. Pause/resume retain the current run.

- [ ] **Step 6: Guard every asynchronous continuation**

At each continuation currently guarded only by `activeMessageIdRef`, require `isCurrentRun(run, generation)`. This includes:

- speech fetch completion/rejection;
- every stream event;
- scheduler enqueue completion/failure;
- HTML `audio.play()` completion/rejection;
- HTML queued-segment `ended` continuation;
- scheduler `waitForIdle()` completion;
- pause/resume completion.

Associate each HTML run with a dedicated closure instead of a mutable global run pointer:

```ts
function installEndedListener(run: PlaybackRun, generation: number): void {
  const audio = audioRef.current;
  if (!audio) return;
  if (htmlEndedListenerRef.current) {
    audio.removeEventListener('ended', htmlEndedListenerRef.current);
  }
  const listener = () => {
    if (!isCurrentRun(run, generation)) return;
    // advance this run's queue, or emit stopped/deactivate when it is empty
  };
  htmlEndedListenerRef.current = listener;
  audio.addEventListener('ended', listener);
}
```

Remove this exact listener before invalidating/stopping/replaying/unmounting. A retained old closure still captures old `{run, generation}` and therefore fails `isCurrentRun` after run 2 begins. Do not read a mutable `htmlRunRef.current` inside the listener and do not derive ownership from `activeMessageIdRef` alone. Scheduler completion likewise captures its own run and generation in the promise closure.

Operational start boundary:

- HTML Audio: emit `started` after `audio.play()` resolves for the first time in the run.
- Web Audio: emit `started` after the first `enqueue()` resolves, meaning a source has been accepted and scheduled on a running browser audio context. This is the strongest browser-observable boundary available without adding an audio-device callback; document it as such in acceptance evidence.

Use a `runStartedRef`/per-run check so later segments do not emit another `started`.

- [ ] **Step 7: Implement pause, resume, stop, interruption, and failure order**

For a current run:

```text
invalidate generation and synchronously silence/release old media
→ emit terminal event for old run
→ onRunDeactivated(old run)
→ clear old refs
→ optionally activate the next run
```

Pause emits `paused` only after browser/scheduler pause succeeds. Resume emits `resumed` only after resume succeeds. `started` is never reused for resume.

Change reset to retain backward compatibility while making the reason explicit:

```ts
reset(reason: 'interrupted' | 'stopped' = 'interrupted'): void
```

Explicit Stop uses `stopped`; recording, session switch/delete/create, new playback, and unmount use `interrupted`. A pre-start non-abort error emits `failed`; a deliberate abort caused by invalidation emits only the invalidation's terminal event.

- [ ] **Step 8: Run hook and message-list tests**

```powershell
npm --prefix frontend run test -- `
  src/hooks/useAudioPlaybackController.streaming.test.tsx `
  src/components/MessageList.test.tsx
```

Expected: lifecycle tests and all existing playback controls pass. No old run changes a new run.

- [ ] **Step 9: Review the high-risk diff**

```powershell
git diff --check -- frontend/src/hooks/useAudioPlaybackController.ts frontend/src/hooks/useAudioPlaybackController.streaming.test.tsx
git diff -- frontend/src/hooks/useAudioPlaybackController.ts frontend/src/hooks/useAudioPlaybackController.streaming.test.tsx
```

Verify manually that every `await`, promise callback, `ended` callback, stream event, scheduler completion, and error path has a run guard.

---

## Task 7: Build the Expression Preview Controller and Cache Rules

**Files:**
- Create: `frontend/src/hooks/useExpressionPreviewController.ts`
- Create: `frontend/src/hooks/useExpressionPreviewController.test.tsx`

- [ ] **Step 1: Write failing orchestration tests**

Use `renderHook`, deferred API promises, and a mocked `apiClient.getMessageExpression`. Cover:

```ts
it('caches successful API default but never caches local fallback', async () => {
  vi.mocked(apiClient.getMessageExpression)
    .mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValueOnce({
      assistant_message_id: 'a', schema_version: 1,
      delivery: 'warm', intensity: 'medium', rate: 1.04, source: 'persisted_plan',
    });

  const { result } = renderHook(() => useExpressionPreviewController('session-1'));
  act(() => result.current.selectAssistantMessage('session-1', 'a'));
  await waitFor(() => expect(result.current.state.expression?.delivery).toBe('neutral'));
  act(() => result.current.selectAssistantMessage('session-1', 'a', { forceReload: true }));
  await waitFor(() => expect(result.current.state.expression?.delivery).toBe('warm'));
  expect(apiClient.getMessageExpression).toHaveBeenCalledTimes(2);

  act(() => result.current.selectAssistantMessage('session-1', 'a'));
  expect(apiClient.getMessageExpression).toHaveBeenCalledTimes(2);
});
```

Also test:

- a successful server `source: 'default'` is cacheable because origin is API;
- a late response for message A is ignored after selecting B, even if abort does nothing;
- `onRunActivated(run)` synchronously establishes the active pair and uses the hook's current session ID to select the exact message only when no equal target request/value is already active;
- one voice turn performs one initial expression GET for its assistant ID; activation must not abort and duplicate an equal in-flight request;
- stale speaking events and stale deactivation do nothing through the reducer;
- `clear()` aborts, invalidates target generation, and returns idle;
- `dropSession(sessionId)` removes only cache entries indexed to that deleted session, including deletion of a non-active session;
- retry/replay after local fallback performs another GET.

- [ ] **Step 2: Run and confirm RED**

```powershell
npm --prefix frontend run test -- src/hooks/useExpressionPreviewController.test.tsx
```

Expected: module resolution failure.

- [ ] **Step 3: Implement the focused controller hook**

Use the pure reducer and these refs:

```ts
const [state, dispatch] = useReducer(expressionPreviewReducer, initialExpressionPreviewState);
const targetRef = useRef<string | null>(null);
const requestGenerationRef = useRef(0);
const requestRef = useRef<AbortController | null>(null);
const cacheRef = useRef(new Map<string, { sessionId: string; event: ExpressionEvent }>());
const activeRunRef = useRef<PlaybackRun | null>(null);
```

The selection implementation must apply this order:

```ts
const selectAssistantMessage = useCallback((
  sessionId: string,
  assistantMessageId: string,
  options: { forceReload?: boolean } = {},
) => {
  targetRef.current = assistantMessageId;
  const generation = ++requestGenerationRef.current;
  requestRef.current?.abort();
  dispatch({ type: 'targetSelected', assistantMessageId });

  const cachedEntry = options.forceReload ? undefined : cacheRef.current.get(assistantMessageId);
  if (cachedEntry) {
    dispatch({ type: 'expressionResolved', expression: cachedEntry.event });
    return;
  }

  const controller = new AbortController();
  requestRef.current = controller;
  void apiClient.getMessageExpression(assistantMessageId, { signal: controller.signal })
    .then((response) => {
      if (controller.signal.aborted || generation !== requestGenerationRef.current || targetRef.current !== assistantMessageId) return;
      const event = expressionEventFromApi(response);
      cacheRef.current.set(assistantMessageId, { sessionId, event });
      dispatch({ type: 'expressionResolved', expression: event });
    })
    .catch((error: unknown) => {
      if (controller.signal.aborted || generation !== requestGenerationRef.current || targetRef.current !== assistantMessageId) return;
      dispatch({ type: 'expressionResolved', expression: localNeutralExpression(assistantMessageId).event });
    });
}, []);
```

Do not cache the catch-path value. Abort is an optimization; generation and exact ID checks are the correctness boundary.

Expose stable callbacks:

```ts
onRunActivated(run): boolean
onRunDeactivated(run): void
onSpeakingEvent(event): void
selectAssistantMessage(sessionId, id, options?): void
clear(): void
dropSession(sessionId): void
```

`onRunActivated` must set `activeRunRef.current` and dispatch synchronously before any playback event. The hook receives the current `sessionId`; if the activated message is already the current target and either a cached API value or equal in-flight request exists, activation must reuse it instead of aborting/restarting the GET. Otherwise it calls `selectAssistantMessage(sessionId, run.assistantMessageId)`. It returns `false` only for an empty message ID or absent current session. `onRunDeactivated` only clears a matching pair. `dropSession(sessionId)` iterates the in-memory cache and deletes only entries whose stored `sessionId` matches, so deleting a non-active session cannot evict the active session's expression.

- [ ] **Step 4: Run controller and reducer tests**

```powershell
npm --prefix frontend run test -- `
  src/hooks/useExpressionPreviewController.test.tsx `
  src/expression/previewReducer.test.ts
```

Expected: all stale-response, caching, activation, and state-machine tests pass.

---

## Task 8: Render an Isolated Neutral Preview

**Files:**
- Create: `frontend/src/components/ExpressionPreview.tsx`
- Create: `frontend/src/components/ExpressionPreview.test.tsx`
- Create: `frontend/src/components/PresentationErrorBoundary.tsx`
- Create: `frontend/src/components/PresentationErrorBoundary.test.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/testSetup.ts`

- [ ] **Step 1: Write failing preview tests**

Render each phase and assert text semantics rather than protected imagery:

```tsx
render(<ExpressionPreview state={{
  selectedAssistantMessageId: 'a',
  expression: {
    type: 'expression', assistantMessageId: 'a', schemaVersion: 1,
    delivery: 'reassuring', intensity: 'medium', rate: 0.96, source: 'persisted_plan',
  },
  activeRun: { assistantMessageId: 'a', playbackRunId: 4 },
  phase: 'speaking',
}} displayLabel="我会陪你慢慢说。" />);

expect(screen.getByRole('region', { name: '角色表现预览' })).toBeInTheDocument();
expect(screen.getByText('安慰表达')).toBeInTheDocument();
expect(screen.getByText('正在说话')).toBeInTheDocument();
expect(screen.getByText('我会陪你慢慢说。')).toBeInTheDocument();
expect(document.querySelector('img')).toBeNull();
```

Test all delivery labels, `idle/ready/speaking/paused`, `aria-live="polite"`, and that display text is present with motion disabled.

- [ ] **Step 2: Write failing error-boundary isolation test**

Use a child that throws and a sibling marker:

```tsx
function Broken(): never { throw new Error('preview broke'); }

render(
  <div>
    <span>聊天仍可用</span>
    <PresentationErrorBoundary><Broken /></PresentationErrorBoundary>
  </div>,
);
expect(screen.getByText('聊天仍可用')).toBeInTheDocument();
expect(screen.getByText('角色预览暂时不可用。')).toBeInTheDocument();
```

Suppress the expected React console error locally in this test and restore the spy afterward.

- [ ] **Step 3: Run and confirm RED**

```powershell
npm --prefix frontend run test -- `
  src/components/ExpressionPreview.test.tsx `
  src/components/PresentationErrorBoundary.test.tsx
```

Expected: absent module failures.

- [ ] **Step 4: Implement the props-only preview**

`ExpressionPreview.tsx` imports only state types and maps delivery values to fixed Chinese labels:

```tsx
const DELIVERY_LABEL = {
  neutral: '中性表达', warm: '温和表达', reassuring: '安慰表达',
  reserved: '克制表达', firm: '坚定表达',
} as const;
const PHASE_LABEL = {
  idle: '等待消息', ready: '准备就绪', speaking: '正在说话', paused: '已暂停',
} as const;

export function ExpressionPreview({ state, displayLabel }: Props) {
  const delivery = state.expression?.delivery ?? 'neutral';
  return (
    <section className={`expression-preview expression-preview--${delivery}`} aria-label="角色表现预览">
      <div className="expression-preview__avatar" aria-hidden="true"><span /></div>
      <div className="expression-preview__status" aria-live="polite">
        <strong>{DELIVERY_LABEL[delivery]}</strong>
        <span>{PHASE_LABEL[state.phase]}</span>
      </div>
      <p className="expression-preview__label">{displayLabel}</p>
      <small>这是角色表达策略，不代表真实感情或意识。</small>
    </section>
  );
}
```

No `img`, remote URL, protected name, quote, Live2D asset, canvas engine, or API/TTS call belongs here.

- [ ] **Step 5: Implement the local error boundary**

Use a small class component whose fallback is only the preview region. It must not wrap `MessageList`, recorder, or input.

- [ ] **Step 6: Add neutral CSS and reduced-motion behavior**

Add scoped classes using borders, circles, CSS custom properties, and opacity only. Add:

```css
@media (prefers-reduced-motion: reduce) {
  .expression-preview,
  .expression-preview * {
    animation: none !important;
    transition: none !important;
  }
}
```

Do not use copyrighted images, remote fonts/assets, or color as the sole status channel.

- [ ] **Step 7: Add deterministic `matchMedia` test setup only if absent**

If `testSetup.ts` lacks `window.matchMedia`, define a mock returning `matches: false` and functional no-op event methods. Do not override an existing project mock.

- [ ] **Step 8: Run preview tests and typecheck**

```powershell
npm --prefix frontend run test -- `
  src/components/ExpressionPreview.test.tsx `
  src/components/PresentationErrorBoundary.test.tsx
npm --prefix frontend run typecheck
```

Expected: tests and TypeScript pass.

---

## Task 9: Integrate Exact Message Selection, Playback Events, and Session Cleanup

**Files:**
- Modify: `frontend/src/App.tsx:1-45,99-123,188-270,401-525`
- Modify: `frontend/src/components/ChatLayout.tsx:1-175`
- Modify: `frontend/src/App.test.tsx`

- [ ] **Step 1: Write failing App tests**

Extend API mocks with `getMessageExpression`. Test these externally visible behaviors:

1. `handleSendMessage` captures `sessionId` plus a dedicated `textSendGeneration`, uses the exact `chatResponse.assistant_message_id`, and applies refreshed sessions/messages/expression only if both the generation and `activeSessionIdRef.current` still match.
2. `handleSendAndSpeakTranscript` selects the exact assistant ID once; subsequent synchronous run activation reuses the equal target/in-flight request instead of issuing a duplicate GET.
3. Switching sessions aborts/invalidates old text-send, message-load, and expression requests; resolving any of them later cannot populate the new message list or preview.
4. Deleting an active or non-active session calls `dropSession(sessionId)` and clears only that session's expression cache.
5. Expression 500/network/parser failure shows local neutral but message send and audio controls still work; replay/explicit reselection performs another GET and recovers persisted expression.
6. Recording interruption calls `audioController.reset('interrupted')`; stale playback events do not restore speaking.
7. Page/session message load uses a dedicated `messageLoadGenerationRef`, selects the latest assistant message only after generation + active-session checks, and reload gets the same API expression.
8. A deferred `listMessages(A)` that resolves after switching to B cannot overwrite B's messages or display label.

Use a deferred promise for the stale response test and assert the preview's accessible text.

- [ ] **Step 2: Run App tests and confirm RED**

```powershell
npm --prefix frontend run test -- src/App.test.tsx
```

Expected: failures because preview controller and preview props are not integrated.

- [ ] **Step 3: Compose preview before the audio controller**

In `App.tsx`:

```ts
const expressionPreview = useExpressionPreviewController(activeSessionId);
const audioController = useAudioPlaybackController({
  audioOutputDeviceId: audioOutputDevices.selectedDeviceId,
  onRunActivated: expressionPreview.onRunActivated,
  onRunDeactivated: expressionPreview.onRunDeactivated,
  onSpeakingEvent: expressionPreview.onSpeakingEvent,
});
```

Ensure callback identities are stable so the audio controller is not reset on every render.

- [ ] **Step 4: Guard ordinary text sends and select by exact response ID**

Add `textSendGenerationRef`. At the start of text send, capture both values:

```ts
const sessionId = activeSessionId;
if (!sessionId) return;
const generation = ++textSendGenerationRef.current;
const chatResponse = await apiClient.sendMessage(sessionId, content);
const [updatedSessions, updatedMessages] = await Promise.all([
  apiClient.listSessions(),
  apiClient.listMessages(sessionId),
]);
if (
  generation !== textSendGenerationRef.current ||
  activeSessionIdRef.current !== sessionId
) return;
setSessions(updatedSessions);
setMessages(updatedMessages);
expressionPreview.selectAssistantMessage(sessionId, chatResponse.assistant_message_id);
```

Increment `textSendGenerationRef` during create/select/delete session before any state update. Add the same matching check after each asynchronous boundary that can apply text-send results. This prevents an old session's send/list response from replacing the new session's messages.

Give history/session loading its own generation as well:

```ts
async function loadMessages(sessionId: string) {
  const generation = ++messageLoadGenerationRef.current;
  setLoading(true);
  try {
    const loaded = await apiClient.listMessages(sessionId);
    if (
      generation !== messageLoadGenerationRef.current ||
      activeSessionIdRef.current !== sessionId
    ) return;
    setMessages(loaded);
    const latestAssistant = [...loaded].reverse().find((item) => item.role === 'assistant');
    if (latestAssistant) {
      expressionPreview.selectAssistantMessage(sessionId, latestAssistant.id);
    } else {
      expressionPreview.clear();
    }
  } finally {
    if (
      generation === messageLoadGenerationRef.current &&
      activeSessionIdRef.current === sessionId
    ) setLoading(false);
  }
}
```

Increment `messageLoadGenerationRef` synchronously in create/select/delete before changing `activeSessionIdRef`. The generation + exact session check is required even when an AbortController is later added.

In the voice path, after its existing current-generation check call `selectAssistantMessage(sessionId, assistantId)` once before `audioController.play()`. `onRunActivated` recognizes the same target/in-flight request and must not issue a second GET.

- [ ] **Step 5: Clear in the required lifecycle order**

For create/select/delete/unmount and recording interruption:

```text
audioController.reset('interrupted')
→ expression request abort/generation invalidation via expressionPreview.clear()
→ update session/message state
```

Before deleting any session, no message fetch is required: after a successful delete call `expressionPreview.dropSession(sessionId)`, which uses its internal `messageId → {sessionId, event}` cache entries. This works for non-active sessions and cannot remove the active session's entries. If the deleted session is active, also clear the preview after invalidating playback. Do not persist cache, fallback, run, phase, or label.

- [ ] **Step 6: Derive the display label in memory**

Use:

```ts
const previewDisplayLabel = expressionPreview.state.selectedAssistantMessageId
  ? displayLabelForAssistantMessage(messages, expressionPreview.state.selectedAssistantMessageId)
  : '助手消息';
```

Pass state and label to `ChatLayout`. Never add label to API requests, events, localStorage, SQLite, or logs.

- [ ] **Step 7: Render only the preview inside its error boundary**

Add props to `ChatLayout` and place:

```tsx
<PresentationErrorBoundary>
  <ExpressionPreview state={expressionPreviewState} displayLabel={expressionPreviewDisplayLabel} />
</PresentationErrorBoundary>
```

Do not wrap `MessageList`, `VoiceRecorder`, or `MessageInput` in this boundary.

- [ ] **Step 8: Run App, layout, message, and preview tests**

```powershell
npm --prefix frontend run test -- `
  src/App.test.tsx `
  src/components/MessageList.test.tsx `
  src/components/ExpressionPreview.test.tsx `
  src/hooks/useExpressionPreviewController.test.tsx
```

Expected: all pass; expression failure never prevents chat rendering or playback retry.

- [ ] **Step 9: Run complete frontend unit/type/build checks**

```powershell
npm --prefix frontend run test
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

Expected: all tests pass, `tsc -b` succeeds, and Vite production build contains no secrets, remote character assets, or test databases.

---

## Task 10: Add Stage 4E SQLite Invariant Verification

**Files:**
- Create: `scripts/verify_stage4e_e2e_database.py`
- Create: `tests/test_verify_stage4e_e2e_database.py`
- Modify: `frontend/playwright.global-teardown.ts`
- Modify: `frontend/playwright.global-teardown.test.ts`

- [ ] **Step 1: Write failing verifier tests**

Construct temporary SQLite fixtures and test:

```python
from scripts.verify_stage4e_e2e_database import VerificationError, verify_database


def test_accepts_stage4d_schema_without_runtime_presentation_state(tmp_path: Path) -> None:
    database = create_valid_stage4d_database(tmp_path / "valid.db")
    verify_database(database)


@pytest.mark.parametrize("table", [
    "speaking_events", "playback_runs", "expression_events",
    "animation_states", "preview_states", "expression_cache",
])
def test_rejects_runtime_presentation_tables(tmp_path: Path, table: str) -> None:
    database = create_valid_stage4d_database(tmp_path / "runtime.db")
    with sqlite3.connect(database) as connection:
        connection.execute(f'CREATE TABLE "{table}" (id TEXT PRIMARY KEY)')
    with pytest.raises(VerificationError, match="runtime presentation table"):
        verify_database(database)
```

Also test a forbidden `display_label`, `playback_run_id`, `speaking_state`, `prompt`, `provider_payload`, or `asset_path` column on `expression_plans`, missing DB, malformed DB, and CLI PASS/BLOCKED return values.

- [ ] **Step 2: Run and confirm RED**

```powershell
$env:PYTHONPATH = "backend;."
.\.venv\Scripts\python.exe -m pytest tests\test_verify_stage4e_e2e_database.py -q
```

Expected: import failure because the verifier does not exist.

- [ ] **Step 3: Implement the read-only verifier**

Create a verifier that first calls Stage 4D's verifier, then opens `file:{path}?mode=ro`, lists table names, rejects the exact runtime table names above, and rejects forbidden expression-plan columns. Use its own `VerificationError` and convert Stage 4D's error into Stage 4E's error without exposing DB contents.

CLI success text must be:

```text
PASS: Stage 4E E2E database contains no persisted runtime presentation state
```

The script must explicitly document that static inspection does not prove a GET caused no write; Task 2's full-table before/after API snapshot is that proof.

- [ ] **Step 4: Run verifier tests and confirm GREEN**

```powershell
$env:PYTHONPATH = "backend;."
.\.venv\Scripts\python.exe -m pytest tests\test_verify_stage4e_e2e_database.py -q
```

Expected: all PASS/BLOCKED cases pass.

- [ ] **Step 5: Write failing teardown-order tests**

Extend `TeardownDependencies` tests to inject `runStage4EVerifier`. Assert:

```ts
expect(order).toEqual(['4c', '4d', '4e', 'db', 'wal', 'shm']);
```

Also assert:

- 4E failure is rethrown after all three DB files are cleaned;
- 4C failure remains the primary error and prevents later verifiers exactly as the existing sequential contract does;
- cleanup failure is thrown only if no verifier failed.

- [ ] **Step 6: Wire 4E after 4D**

Add `runStage4EVerifier` using the same resolved Python executable and:

```ts
execFileSync(executable, [
  resolve(frontendDir, '..', 'scripts', 'verify_stage4e_e2e_database.py'),
  '--database', databasePath,
], { stdio: 'inherit' });
```

Run it after 4D and before cleanup. Preserve current primary-error-first cleanup semantics.

- [ ] **Step 7: Run root and teardown tests**

```powershell
$env:PYTHONPATH = "backend;."
.\.venv\Scripts\python.exe -m pytest `
  tests\test_verify_stage4c_e2e_database.py `
  tests\test_verify_stage4d_e2e_database.py `
  tests\test_verify_stage4e_e2e_database.py -q
npm --prefix frontend run test -- playwright.global-teardown.test.ts
```

Expected: all three verifier suites and teardown tests pass.

---

## Task 11: Add Fake-Only Browser Acceptance

**Files:**
- Create: `frontend/e2e/expression-preview.spec.ts`
- Modify only if required: `frontend/e2e/voice-turn.spec.ts`

Do not add a focused `test:e2e:stage4e` script: the current teardown expects Stage 4C's exact audit data and Stage 4D plan data. Formal acceptance must run the complete suite.

- [ ] **Step 1: Write the main E2E flow**

Use existing session/message helpers and stable accessible selectors. The test must:

1. create/select a session;
2. send deterministic fake text;
3. capture the exact assistant message ID from the chat response or expression request;
4. wait for expression preview text;
5. GET the expression endpoint twice and assert complete response equality and six-field minimality;
6. click Play, observe `正在说话`;
7. click Pause, observe `已暂停`;
8. click Continue, observe `正在说话`;
9. click Stop, observe `准备就绪` while the same delivery label remains;
10. switch to another session and assert old speaking/expression state is absent;
11. return and reload, then assert the original message obtains the same persisted expression response.

Use only fake providers and local CSS geometry. Do not load images, Live2D, remote fonts, or external URLs.

- [ ] **Step 2: Add expression-failure recovery**

Use `page.route('**/api/messages/*/expression', ...)` to fail the first matching request with 500, then allow subsequent requests. Assert:

- chat message and assistant reply still render;
- preview uses neutral text;
- playback controls remain usable;
- selecting/replaying the same message causes a second GET;
- the successful second response replaces local neutral with the persisted expression.

Local fallback must not be treated as cacheable.

- [ ] **Step 3: Add rapid same-message replay coverage**

Delay completion of the first media path using the existing browser audio mocks, Stop, immediately Replay, then release the old completion. Assert the preview remains `正在说话` for the new run until the new run ends/stops. If browser-level media control cannot deterministically expose the old callback, keep the exact race in the hook test and make the E2E assert the user-visible stop/replay result without artificial timing claims.

- [ ] **Step 4: Preserve voice interruption coverage**

In `voice-turn.spec.ts`, add only the missing assertion that starting recording exits speaking/paused and that the old run does not reappear. Do not alter existing fake ASR/TTS request contracts or Stage 4C data creation.

- [ ] **Step 5: Run the full E2E suite**

```powershell
Push-Location frontend
npm run test:e2e
Pop-Location
```

Expected:

- all Playwright specs pass;
- Stage 4C teardown prints its metadata-only PASS;
- Stage 4D teardown prints its expression-plan PASS;
- Stage 4E teardown prints `PASS: Stage 4E E2E database contains no persisted runtime presentation state`;
- E2E DB, `-wal`, and `-shm` are cleaned;
- no real model, API key, GPU, real microphone/TTS, or protected character asset is used.

---

## Task 12: Run Runtime Verification, Review, and Truthfully Close Stage 4E

**Files:**
- Create after evidence exists: `docs/stage4e-expression-event-browser-preview.md`
- Modify after evidence exists: `README.md`
- Modify after evidence exists: `CLAUDE.md`

- [ ] **Step 1: Run all focused Python tests**

```powershell
$env:PYTHONPATH = "$PWD;$PWD\backend"
.\.venv\Scripts\python.exe -m pytest `
  backend\tests\test_expression_plan_service.py `
  backend\tests\test_api_message_expression.py `
  backend\tests\test_api_message_speech.py `
  backend\tests\test_message_bound_tts_service.py `
  tests\test_verify_stage4c_e2e_database.py `
  tests\test_verify_stage4d_e2e_database.py `
  tests\test_verify_stage4e_e2e_database.py -q
```

Expected: all pass; record actual counts and duration rather than copying historical numbers.

- [ ] **Step 2: Run complete Python regression**

```powershell
$env:PYTHONPATH = "$PWD;$PWD\backend"
.\.venv\Scripts\python.exe -m pytest backend\tests -q
.\.venv\Scripts\python.exe -m pytest tests -q
```

Expected: both pass. Any pre-existing failure must be reproduced against the baseline and reported, not hidden or fixed through unrelated refactoring.

- [ ] **Step 3: Run complete frontend regression and build**

```powershell
npm --prefix frontend run test
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

Expected: Vitest, TypeScript, and Vite build pass.

- [ ] **Step 4: Run complete Playwright acceptance again**

```powershell
Push-Location frontend
npm run test:e2e
Pop-Location
```

Expected: all specs and all three DB verifiers pass.

- [ ] **Step 5: Invoke the scoped runtime verification skill**

Invoke `AI桌宠:verify` and use an isolated temporary SQLite database with fake LLM/TTS. Observe at minimum:

```text
health 200
→ create session
→ send message and capture exact assistant ID
→ GET expression twice with identical minimal response
→ user ID returns 422
→ missing ID returns 404
→ remove plan only in isolated DB
→ GET returns neutral default twice without recreating a plan
→ message-bound speech and stream still return valid fake audio/NDJSON
→ forced TTS failure leaves text and expression readable
→ before/after protected-table snapshots are unchanged by expression GET
→ Stage 4D and 4E DB verifiers pass
→ temporary DB/WAL/SHM and processes are cleaned
```

Do not claim browser speaking/paused races are covered by this backend runtime skill; those belong to Vitest/Playwright.

- [ ] **Step 6: Run mandatory code review and apply confirmed findings**

Invoke `/code-review` before any commit or closure. Review specifically:

- GET path has no plan creation, emotion read/update, Provider call, or DB mutation;
- response cannot leak content, prompt, memory, emotion vector/reason, provider payload, credentials, plan ID, or source emotion version;
- 500 response does not expose raw exception text;
- every audio async continuation checks exact run and generation;
- activation is synchronous and precedes async work;
- pause/resume and pre-start failure have honest events;
- local fallback is never cached;
- preview errors cannot take down chat/recorder/input;
- no protected asset, remote resource, arbitrary TTS style, or new persistence is introduced.

Apply only confirmed findings, rerun affected focused tests, then rerun Steps 2–5 if product code changed.

- [ ] **Step 7: Write evidence using actual results**

Create `docs/stage4e-expression-event-browser-preview.md` with:

- implemented scope and excluded scope;
- exact API and event contracts;
- browser-observable WebAudio start boundary;
- actual test commands, pass counts, durations, and runtime observations;
- SQLite read-only/static invariant distinction;
- known limits: no native shell, Live2D, lip sync, full duplex, automatic spoken barge-in, protected character resources, or verified acoustic delivery/intensity;
- code-review outcome and unresolved environmental blocks.

Do not write PASS for any command that did not actually run successfully.

- [ ] **Step 8: Update project status only after evidence is complete**

Update `README.md` and `CLAUDE.md` to mark Stage 4E complete only if all acceptance criteria passed. Set the next task to **Stage 4 overall acceptance audit**, not Windows shell implementation. Keep the statement that emotion is an expression strategy, not consciousness or genuine feeling.

Because both files contain pre-existing WIP, inspect their full diff and attribute each hunk before any later staging.

- [ ] **Step 9: Final hygiene and no-commit checkpoint**

```powershell
git diff --check
git status --short
git diff --cached --check
git diff --cached
```

Expected:

- no whitespace errors;
- no unexpected staged files (normally the index remains empty because no commit was requested);
- no secrets, `.env`, databases, WAL/SHM, audio, logs, traces, reports, `.superpowers/`, or unauthorized assets;
- every claimed Stage 4E file is present and every changed shared-file hunk is understood.

Report using the project format:

```text
完成内容：
修改文件：
验证命令与结果：
未完成或受限部分：
是否改变当前阶段：否/是（附验收证据）
下一项建议任务：Stage 4 总体验收审计
```

Do not commit unless the user explicitly asks after reviewing the final diff.
