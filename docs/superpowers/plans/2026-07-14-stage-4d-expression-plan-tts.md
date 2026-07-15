# Stage 4D ExpressionPlan / TTS Expression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist one bounded, provider-neutral ExpressionPlan per assistant message and use it through message-bound TTS APIs without allowing expression or speech failures to affect the persisted text reply.

**Architecture:** `ChatService` reads one pre-reply emotion snapshot and supplies that exact object to both text formatting and a deterministic ExpressionPlan policy; after the assistant message commits, plan persistence runs as an isolated best-effort side effect. Message-bound TTS resolves text and the compatible plan on the server, combines its bounded rate with the user's validated speed, and invokes the existing TTS service while provider adapters remain limited to their already verified `text`, `voice_id`, and `speed` contract.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, Pydantic v2, pytest/pytest-asyncio, React, TypeScript, Vite, Vitest, Playwright, existing fake and CosyVoice HTTP TTS providers.

---

## Prerequisites and Worktree Safety

The current working tree already contains extensive uncommitted Stage 3/4A–4C work, including files that Stage 4D must also edit. Before implementation:

- Re-read `CLAUDE.md` and this plan.
- Run `git status --short` and preserve the output as the baseline.
- Do not run `git add .`, `git add -A`, `git commit -a`, `git restore`, `git reset --hard`, `git clean`, or any force operation.
- The safest execution path is to have the owner first commit/recoverably archive the existing Stage 3/4A–4C work, then implement Stage 4D on that committed baseline in a dedicated branch/worktree.
- If the existing work cannot be committed first, implementation may proceed in place, but every shared-file hunk must be reviewed before staging. If a Stage 4D hunk cannot be separated confidently from pre-existing work, do not commit it.
- Commit steps below are **authorization-gated checkpoints**. Do not stage or commit merely because a task passed. Execute a commit step only if the user explicitly authorizes commits during implementation; even then, inspect `git diff --cached` first and skip the commit if the index contains any pre-existing change.

Use the project interpreter available in the environment. Commands below use `python`; if the repository virtual environment exists, substitute its interpreter without changing test arguments.

## File Map

### New backend files

- `backend/app/repositories/expression_plans.py` — create/read immutable, versioned plans keyed by assistant message.
- `backend/app/services/expression_plan_policy.py` — pure bounded mapping from `EmotionState` to `ExpressionPlanDraft`.
- `backend/app/services/expression_plan_service.py` — assistant-role validation, idempotent creation, compatible-plan/default resolution.
- `backend/app/tts/expression_mapper.py` — provider-neutral expression request mapped to the existing speed-only provider contract.
- `backend/app/services/message_bound_tts_service.py` — server-side message/plan resolution and shared stream/non-stream TTS orchestration.
- `backend/app/api/routes/message_speech.py` — message-bound speech endpoints.

### Modified backend files

- `backend/app/domain/models.py` — expression enums, validated draft/plan types, shared emotion thresholds.
- `backend/app/domain/schemas.py` — strict message speech request and `assistant_message_id` response field.
- `backend/app/repositories/sqlite.py` — constrained `expression_plans` table.
- `backend/app/services/emotion_context.py` — shared threshold constants, formatting only.
- `backend/app/services/context_builder.py` — caller-supplied snapshot/context; no hidden production snapshot read.
- `backend/app/services/chat_service.py` — single pre-reply snapshot, best-effort plan creation, assistant ID response.
- `backend/app/services/tts_service.py` — reusable public speed validation without changing provider signatures.
- `backend/app/api/dependencies.py` — expression/message-TTS composition.
- `backend/app/api/routes/audio.py` — reusable response/NDJSON helpers only; legacy routes unchanged.
- `backend/app/main.py` — register message speech router.

### New/modified backend tests

- Create `backend/tests/test_expression_plan_models.py`
- Create `backend/tests/test_expression_plan_repository.py`
- Create `backend/tests/test_expression_plan_policy.py`
- Create `backend/tests/test_expression_plan_service.py`
- Create `backend/tests/test_tts_expression_mapper.py`
- Create `backend/tests/test_message_bound_tts_service.py`
- Create `backend/tests/test_api_message_speech.py`
- Modify `backend/tests/test_emotion_context.py`
- Modify `backend/tests/test_context_builder.py`
- Modify `backend/tests/test_chat_service.py`
- Modify `backend/tests/test_api_chat.py`
- Modify `backend/tests/test_tts_service.py`

### Frontend files

- Modify `frontend/src/api/types.ts` — require `assistant_message_id` in chat responses.
- Modify `frontend/src/api/client.ts` — add message-bound non-streaming client and preserve legacy text TTS.
- Modify `frontend/src/api/speechStream.ts` — add message-bound streaming client using the existing parser.
- Modify `frontend/src/hooks/useAudioPlaybackController.ts` — synthesize by message ID, not text.
- Modify `frontend/src/components/MessageList.tsx` — pass only assistant message IDs to playback.
- Modify `frontend/src/App.tsx` — bind voice playback directly to the chat response ID.
- Delete `frontend/src/voiceTurn.ts` and `frontend/src/voiceTurn.test.ts` only after all imports and heuristic-only branches are removed.
- Modify `frontend/src/api/client.test.ts`, `frontend/src/api/speechStream.test.ts`, `frontend/src/components/MessageList.test.tsx`, and `frontend/src/App.test.tsx`.

### Acceptance files

- Modify `frontend/e2e/voice-turn.spec.ts`, `frontend/e2e/chat.spec.ts`, `frontend/playwright.config.ts`, `frontend/playwright.global-teardown.ts`, and `frontend/playwright.global-teardown.test.ts`.
- Create `scripts/verify_stage4d_e2e_database.py` and `tests/test_verify_stage4d_e2e_database.py`.
- Create `scripts/smoke_stage4d_cosyvoice_message_tts.py` and `backend/tests/test_smoke_stage4d_cosyvoice_message_tts.py`.
- Create `docs/stage4d-expression-plan-tts.md`; update `README.md` and `CLAUDE.md` only after verified acceptance.

---

## Task 1: Lock ExpressionPlan Domain and Persistence Invariants

**Files:**
- Modify: `backend/app/domain/models.py:81-117`
- Modify: `backend/app/repositories/sqlite.py:104-188`
- Create: `backend/app/repositories/expression_plans.py`
- Create: `backend/tests/test_expression_plan_models.py`
- Create: `backend/tests/test_expression_plan_repository.py`

- [ ] **Step 1: Write failing domain-model tests**

Create tests with these exact cases:

```python
import math

import pytest

from app.domain.models import (
    EXPRESSION_PLAN_SCHEMA_VERSION,
    ExpressionDelivery,
    ExpressionIntensity,
    ExpressionPlanDraft,
)


def test_expression_plan_draft_accepts_only_bounded_v1_fields() -> None:
    draft = ExpressionPlanDraft(
        source_emotion_version=5,
        delivery=ExpressionDelivery.REASSURING,
        rate=0.94,
        intensity=ExpressionIntensity.MEDIUM,
    )

    assert EXPRESSION_PLAN_SCHEMA_VERSION == 1
    assert draft.source_emotion_version == 5
    assert draft.delivery is ExpressionDelivery.REASSURING
    assert draft.rate == 0.94
    assert draft.intensity is ExpressionIntensity.MEDIUM
    assert not hasattr(draft, "text")
    assert not hasattr(draft, "emotion_vector")
    assert not hasattr(draft, "provider_options")


@pytest.mark.parametrize("rate", [0.89, 1.11, math.nan, math.inf, -math.inf])
def test_expression_plan_draft_rejects_invalid_rate(rate: float) -> None:
    with pytest.raises(ValueError):
        ExpressionPlanDraft(
            source_emotion_version=0,
            delivery=ExpressionDelivery.NEUTRAL,
            rate=rate,
            intensity=ExpressionIntensity.LOW,
        )


def test_expression_plan_draft_rejects_negative_source_version() -> None:
    with pytest.raises(ValueError):
        ExpressionPlanDraft(
            source_emotion_version=-1,
            delivery=ExpressionDelivery.NEUTRAL,
            rate=1.0,
            intensity=ExpressionIntensity.LOW,
        )
```

Use `__post_init__` on the frozen draft so invalid objects cannot circulate between service and repository.

- [ ] **Step 2: Run the model tests and confirm RED**

Run:

```powershell
python -m pytest backend/tests/test_expression_plan_models.py -q
```

Expected: collection/import failure because the expression types do not exist.

- [ ] **Step 3: Add the minimal validated domain types**

Add shared thresholds and expression types to `models.py`:

```python
import math

EMOTION_BUCKET_LOW_MAX = 0.34
EMOTION_BUCKET_HIGH_MIN = 0.67
EXPRESSION_PLAN_SCHEMA_VERSION = 1
EXPRESSION_PLAN_MIN_RATE = 0.90
EXPRESSION_PLAN_MAX_RATE = 1.10


class ExpressionDelivery(StrEnum):
    NEUTRAL = "neutral"
    WARM = "warm"
    REASSURING = "reassuring"
    RESERVED = "reserved"
    FIRM = "firm"


class ExpressionIntensity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"


@dataclass(frozen=True)
class ExpressionPlanDraft:
    source_emotion_version: int
    delivery: ExpressionDelivery
    rate: float
    intensity: ExpressionIntensity

    def __post_init__(self) -> None:
        if self.source_emotion_version < 0:
            raise ValueError("source emotion version must be non-negative")
        if not math.isfinite(self.rate) or not EXPRESSION_PLAN_MIN_RATE <= self.rate <= EXPRESSION_PLAN_MAX_RATE:
            raise ValueError("expression rate is out of bounds")


@dataclass(frozen=True)
class ResolvedExpression:
    delivery: ExpressionDelivery
    rate: float
    intensity: ExpressionIntensity

    def __post_init__(self) -> None:
        if not math.isfinite(self.rate) or not EXPRESSION_PLAN_MIN_RATE <= self.rate <= EXPRESSION_PLAN_MAX_RATE:
            raise ValueError("expression rate is out of bounds")


@dataclass(frozen=True)
class ExpressionPlan:
    id: str
    assistant_message_id: str
    schema_version: int
    source_emotion_version: int
    delivery: ExpressionDelivery
    rate: float
    intensity: ExpressionIntensity
    created_at: datetime
```

Add `ResolvedExpression` to the same import list and assert `ResolvedExpression` rejects non-finite/out-of-range rates; it intentionally has no `source_emotion_version` because a default fallback must not pretend to come from a persisted emotion snapshot.

Do not add text, a full emotion vector, free-form style, SSML, or a provider options dictionary.

- [ ] **Step 4: Run model tests and confirm GREEN**

Run:

```powershell
python -m pytest backend/tests/test_expression_plan_models.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Write failing repository and database tests**

Use the existing temporary-file SQLite fixtures/patterns from `test_emotion_repository.py`. Add:

```python
def test_expression_plan_repository_persists_exact_message_and_version(connection) -> None:
    session = SessionRepository(connection).create("plan test")
    message = MessageRepository(connection).add(session.id, ChatRole.ASSISTANT, "persisted reply")
    repository = ExpressionPlanRepository(connection)

    created = repository.create(
        message.id,
        ExpressionPlanDraft(
            source_emotion_version=7,
            delivery=ExpressionDelivery.WARM,
            rate=1.04,
            intensity=ExpressionIntensity.MEDIUM,
        ),
    )

    assert repository.get(message.id) == created
    assert created.assistant_message_id == message.id
    assert created.schema_version == 1


def test_expression_plan_repository_enforces_one_plan_per_message_version(connection) -> None:
    session = SessionRepository(connection).create("idempotency")
    message = MessageRepository(connection).add(session.id, ChatRole.ASSISTANT, "reply")
    repository = ExpressionPlanRepository(connection)
    draft = ExpressionPlanDraft(0, ExpressionDelivery.NEUTRAL, 1.0, ExpressionIntensity.LOW)

    repository.create(message.id, draft)
    with pytest.raises(sqlite3.IntegrityError):
        repository.create(message.id, draft)


def test_expression_plan_is_deleted_with_its_message(connection) -> None:
    session = SessionRepository(connection).create("cascade")
    message = MessageRepository(connection).add(session.id, ChatRole.ASSISTANT, "reply")
    repository = ExpressionPlanRepository(connection)
    repository.create(message.id, ExpressionPlanDraft(0, ExpressionDelivery.NEUTRAL, 1.0, ExpressionIntensity.LOW))

    connection.execute("DELETE FROM messages WHERE id = ?", (message.id,))
    connection.commit()

    assert repository.get(message.id) is None
```

Also directly insert one bad row for each DB invariant: negative source version, rate below `0.90`, rate above `1.10`, unknown delivery, and `high` intensity; each must raise `sqlite3.IntegrityError`.

- [ ] **Step 6: Run repository tests and confirm RED**

Run:

```powershell
python -m pytest backend/tests/test_expression_plan_repository.py -q
```

Expected: failure because the table and repository do not exist.

- [ ] **Step 7: Add the constrained table and focused repository**

Append to `SCHEMA_SQL` before its closing delimiter:

```sql
CREATE TABLE IF NOT EXISTS expression_plans (
    id TEXT PRIMARY KEY,
    assistant_message_id TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version >= 1),
    source_emotion_version INTEGER NOT NULL CHECK (source_emotion_version >= 0),
    delivery TEXT NOT NULL CHECK (delivery IN ('neutral', 'warm', 'reassuring', 'reserved', 'firm')),
    rate REAL NOT NULL CHECK (rate >= 0.90 AND rate <= 1.10),
    intensity TEXT NOT NULL CHECK (intensity IN ('low', 'medium')),
    created_at TEXT NOT NULL,
    FOREIGN KEY (assistant_message_id) REFERENCES messages(id) ON DELETE CASCADE,
    UNIQUE (assistant_message_id, schema_version)
);

CREATE INDEX IF NOT EXISTS idx_expression_plans_message
ON expression_plans(assistant_message_id);
```

Implement `ExpressionPlanRepository` with these signatures:

```python
class ExpressionPlanRepository:
    def __init__(self, connection: sqlite3.Connection) -> None: ...

    def create(
        self,
        assistant_message_id: str,
        draft: ExpressionPlanDraft,
        *,
        schema_version: int = EXPRESSION_PLAN_SCHEMA_VERSION,
    ) -> ExpressionPlan: ...

    def get(
        self,
        assistant_message_id: str,
        *,
        schema_version: int = EXPRESSION_PLAN_SCHEMA_VERSION,
    ) -> ExpressionPlan | None: ...
```

Follow existing UUID/UTC ISO conversion conventions. Commit after insert, let `sqlite3.IntegrityError` propagate from `create`, and construct enums while reading so corrupted rows fail closed.

- [ ] **Step 8: Run the focused persistence tests**

Run:

```powershell
python -m pytest backend/tests/test_expression_plan_models.py backend/tests/test_expression_plan_repository.py -q
```

Expected: all pass.

- [ ] **Step 9: Authorization-gated domain/persistence commit checkpoint**

Stage exact paths only:

```powershell
git add -- backend/app/domain/models.py backend/app/repositories/sqlite.py backend/app/repositories/expression_plans.py backend/tests/test_expression_plan_models.py backend/tests/test_expression_plan_repository.py
git diff --cached --check
git diff --cached
```

Expected: only Stage 4D domain/table/repository hunks. If any prior work appears, unstage the affected file and skip this commit. Otherwise:

```powershell
git commit -m "feat: persist message-bound expression plans"
```

---

## Task 2: Implement Deterministic Policy and Idempotent Plan Service

**Files:**
- Create: `backend/app/services/expression_plan_policy.py`
- Create: `backend/app/services/expression_plan_service.py`
- Modify: `backend/app/services/emotion_context.py:16-21`
- Create: `backend/tests/test_expression_plan_policy.py`
- Create: `backend/tests/test_expression_plan_service.py`
- Modify: `backend/tests/test_emotion_context.py`

- [ ] **Step 1: Write the failing policy table tests**

Create a helper that builds enabled snapshots, then lock this precedence table:

```python
@pytest.mark.parametrize(
    ("vector", "expected"),
    [
        (EmotionVector(0.5, 0.8, 0.67, 0.2, 0.8, 0.8), (ExpressionDelivery.REASSURING, 0.94, ExpressionIntensity.MEDIUM)),
        (EmotionVector(0.5, 0.8, 0.2, 0.2, 0.67, 0.67), (ExpressionDelivery.FIRM, 0.94, ExpressionIntensity.MEDIUM)),
        (EmotionVector(0.5, 0.67, 0.2, 0.33, 0.1, 0.2), (ExpressionDelivery.WARM, 1.04, ExpressionIntensity.MEDIUM)),
        (EmotionVector(0.5, 0.4, 0.2, 0.67, 0.1, 0.2), (ExpressionDelivery.RESERVED, 0.94, ExpressionIntensity.LOW)),
        (EMOTION_BASELINE, (ExpressionDelivery.NEUTRAL, 1.0, ExpressionIntensity.LOW)),
    ],
)
def test_expression_plan_policy_uses_ordered_bounded_table(vector, expected) -> None:
    snapshot = EmotionState(DEFAULT_EMOTION_SCOPE_ID, True, vector, 9, now())

    draft = ExpressionPlanPolicy().create_draft(snapshot)

    assert draft is not None
    assert (draft.delivery, draft.rate, draft.intensity) == expected
    assert draft.source_emotion_version == 9
```

Add a deterministic repeat test and disabled/invalid-state tests for `nan`, `inf`, values outside `[0, 1]`, and negative version. Invalid or disabled snapshots return `None`; they are not clamped into personalized plans.

- [ ] **Step 2: Run policy tests and confirm RED**

Run:

```powershell
python -m pytest backend/tests/test_expression_plan_policy.py -q
```

Expected: import failure because the policy does not exist.

- [ ] **Step 3: Implement the pure policy and share bucket boundaries**

Implement exactly:

```python
class ExpressionPlanPolicy:
    def create_draft(self, snapshot: EmotionState) -> ExpressionPlanDraft | None:
        if not snapshot.enabled or snapshot.version < 0:
            return None
        if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in snapshot.vector.values()):
            return None

        vector = snapshot.vector
        if vector.concern >= EMOTION_BUCKET_HIGH_MIN:
            delivery, rate, intensity = ExpressionDelivery.REASSURING, 0.94, ExpressionIntensity.MEDIUM
        elif vector.irritation >= EMOTION_BUCKET_HIGH_MIN and vector.formality >= EMOTION_BUCKET_HIGH_MIN:
            delivery, rate, intensity = ExpressionDelivery.FIRM, 0.94, ExpressionIntensity.MEDIUM
        elif vector.trust >= EMOTION_BUCKET_HIGH_MIN and vector.distance < EMOTION_BUCKET_LOW_MAX:
            delivery, rate, intensity = ExpressionDelivery.WARM, 1.04, ExpressionIntensity.MEDIUM
        elif vector.distance >= EMOTION_BUCKET_HIGH_MIN or vector.formality >= EMOTION_BUCKET_HIGH_MIN:
            delivery, rate, intensity = ExpressionDelivery.RESERVED, 0.94, ExpressionIntensity.LOW
        else:
            delivery, rate, intensity = ExpressionDelivery.NEUTRAL, 1.0, ExpressionIntensity.LOW
        return ExpressionPlanDraft(snapshot.version, delivery, rate, intensity)
```

Change `emotion_context._bucket` to use `EMOTION_BUCKET_LOW_MAX` and `EMOTION_BUCKET_HIGH_MIN`, preserving the existing `< 0.34`, `< 0.67`, otherwise-high behavior.

- [ ] **Step 4: Run policy and formatter tests**

Run:

```powershell
python -m pytest backend/tests/test_expression_plan_policy.py backend/tests/test_emotion_context.py -q
```

Expected: all pass and existing formatted strings remain unchanged.

- [ ] **Step 5: Write failing plan-service tests**

Lock the service interface and behavior:

```python
DEFAULT_EXPRESSION = ResolvedExpression(
    delivery=ExpressionDelivery.NEUTRAL,
    rate=1.0,
    intensity=ExpressionIntensity.LOW,
)


def test_create_for_assistant_message_returns_existing_plan_after_race(...) -> None:
    first = service.create_for_assistant_message(assistant.id, warm_snapshot)
    second = service.create_for_assistant_message(assistant.id, reassuring_snapshot)

    assert first is not None
    assert second == first
    assert second.source_emotion_version == warm_snapshot.version
    assert second.delivery is ExpressionDelivery.WARM


def test_create_for_assistant_message_rejects_unknown_and_user_messages(...) -> None:
    with pytest.raises(NotFoundError):
        service.create_for_assistant_message("missing", snapshot)
    with pytest.raises(ValidationAppError):
        service.create_for_assistant_message(user.id, snapshot)


def test_resolve_returns_default_without_writing_for_missing_or_incompatible_plan(...) -> None:
    resolved = service.resolve_compatible_or_default(assistant.id)

    assert resolved.delivery is ExpressionDelivery.NEUTRAL
    assert resolved.rate == 1.0
    assert repository.get(assistant.id) is None
```

Also test disabled/`None` snapshot returns `None` without writing and a controlled row parse failure returns the default expression.

- [ ] **Step 6: Run plan-service tests and confirm RED**

Run:

```powershell
python -m pytest backend/tests/test_expression_plan_service.py -q
```

Expected: import failure because the service does not exist.

- [ ] **Step 7: Implement the minimal service**

Use:

```python
class ExpressionPlanService:
    def __init__(self, messages: MessageRepository, plans: ExpressionPlanRepository, policy: ExpressionPlanPolicy) -> None: ...

    def create_for_assistant_message(
        self,
        assistant_message_id: str,
        snapshot: EmotionState | None,
    ) -> ExpressionPlan | None: ...

    def resolve_compatible_or_default(self, assistant_message_id: str) -> ResolvedExpression: ...
```

Rules:

- Require the message and `ChatRole.ASSISTANT` before writing.
- Return `None` for absent/disabled/invalid snapshot.
- Return an existing v1 before creating.
- If `create` loses a unique-key race, read and return the existing v1; re-raise only if no row can be read.
- Resolution does not inspect current emotion and never persists the default.
- Catch only row decoding/value errors during resolution; do not swallow arbitrary connection failures.

- [ ] **Step 8: Run the focused service suite**

Run:

```powershell
python -m pytest backend/tests/test_expression_plan_policy.py backend/tests/test_expression_plan_service.py backend/tests/test_emotion_context.py -q
```

Expected: all pass.

- [ ] **Step 9: Authorization-gated policy/service commit checkpoint**

```powershell
git add -- backend/app/services/expression_plan_policy.py backend/app/services/expression_plan_service.py backend/app/services/emotion_context.py backend/tests/test_expression_plan_policy.py backend/tests/test_expression_plan_service.py backend/tests/test_emotion_context.py
git diff --cached --check
git diff --cached
```

Commit only a clean Stage 4D diff:

```powershell
git commit -m "feat: derive bounded expression plans"
```

---

## Task 3: Share One Pre-Reply Snapshot and Return the Assistant Message ID

**Files:**
- Modify: `backend/app/services/context_builder.py:15-103`
- Modify: `backend/app/services/chat_service.py:17-127`
- Modify: `backend/app/domain/schemas.py:39-47`
- Modify: `backend/app/api/routes/chat.py:22-29`
- Modify: `backend/app/api/dependencies.py:196-234`
- Modify: `backend/tests/test_context_builder.py`
- Modify: `backend/tests/test_chat_service.py`
- Modify: `backend/tests/test_api_chat.py`

- [ ] **Step 1: Write failing context and single-snapshot tests**

Add a test that calls `build_emotion_context(snapshot)` and verifies formatter input identity. Add a recording reader whose second call would return a different version:

```python
class RecordingSnapshotReader:
    def __init__(self, snapshot: EmotionState) -> None:
        self.snapshot = snapshot
        self.calls = 0

    def get_state(self, *, apply_decay: bool = True) -> EmotionState:
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("snapshot read more than once")
        return self.snapshot
```

The main chat test must assert:

```python
reply = await service.send_message(session.id, "hello")

assert reader.calls == 1
assert formatter.seen_state is snapshot
assert plan_service.seen_snapshot is snapshot
assert reply.assistant_message_id == messages.list(session.id)[-1].id
```

Add failure tests:

- snapshot reader raises: provider still generates, assistant persists, no plan call;
- plan service raises after assistant persistence: reply still returns, local updater and 4C scheduler still run;
- provider empty or assistant persistence failure: plan service is never called.

- [ ] **Step 2: Run focused chat tests and confirm RED**

Run:

```powershell
python -m pytest backend/tests/test_context_builder.py backend/tests/test_chat_service.py -q
```

Expected: failures because ContextBuilder reads internally, ChatReply has no ID, and ChatService has no plan side effect.

- [ ] **Step 3: Refactor ContextBuilder to format caller-supplied state**

Change the interface to:

```python
def build_emotion_context(self, snapshot: EmotionState | None) -> list[LLMMessage]:
    if snapshot is None or self._emotion_context_formatter is None:
        return []
    try:
        content = self._emotion_context_formatter.format(snapshot)
    except Exception:
        return []
    return [LLMMessage(role=ChatRole.SYSTEM, content=content)] if content else []


def build_context(
    self,
    session_id: str,
    query: str | None = None,
    *,
    emotion_context: list[LLMMessage] | None = None,
) -> list[LLMMessage]:
    return [*(emotion_context or []), *self.build_memory_context(query=query), *self.build_recent_context(session_id)]
```

Remove the production reader dependency from ContextBuilder. Do not change memory/history ordering.

- [ ] **Step 4: Refactor ChatService around one snapshot and isolated plan creation**

Extend the reply and constructor:

```python
@dataclass(frozen=True)
class ChatReply:
    reply: str
    provider: str
    model: str
    assistant_message_id: str
```

Inject `emotion_snapshot_reader` and `expression_plans`. Before context construction, attempt exactly one `get_state(apply_decay=True)`. Build emotion context from that object. After assistant persistence:

```python
if snapshot is not None and self._expression_plans is not None:
    try:
        self._expression_plans.create_for_assistant_message(assistant_message.id, snapshot)
    except Exception:
        # Expression planning must never break an already-persisted reply.
        pass
```

Place this before post-turn emotion update. Return the persisted assistant ID.

- [ ] **Step 5: Wire dependencies without introducing another snapshot reader**

In `get_chat_service`, build `ExpressionPlanService` from the current request connection's `MessageRepository`, `ExpressionPlanRepository`, and `ExpressionPlanPolicy`. Pass the existing request-scoped `EmotionService` directly to ChatService as the only reader. Keep the separate fresh-connection completed-turn updater unchanged.

- [ ] **Step 6: Run focused chat/context tests**

Run:

```powershell
python -m pytest backend/tests/test_emotion_context.py backend/tests/test_context_builder.py backend/tests/test_chat_service.py -q
```

Expected: all pass.

- [ ] **Step 7: Write and run the failing chat API ID test**

Add:

```python
def test_chat_response_returns_the_persisted_assistant_message_id(client) -> None:
    session = client.post("/api/sessions", json={"title": "message id"}).json()

    response = client.post(f"/api/sessions/{session['id']}/messages", json={"content": "hello"})
    messages = client.get(f"/api/sessions/{session['id']}/messages").json()

    assert response.status_code == 200
    assert response.json()["assistant_message_id"] == messages[-1]["id"]
    assert messages[-1]["role"] == "assistant"
```

Run:

```powershell
python -m pytest backend/tests/test_api_chat.py -q
```

Expected before schema/route update: response lacks the ID.

- [ ] **Step 8: Add the ID to schema and route, then rerun**

Add `assistant_message_id: str` to `ChatResponse` and map `reply.assistant_message_id` in the chat route. Run:

```powershell
python -m pytest backend/tests/test_api_chat.py backend/tests/test_chat_service.py backend/tests/test_context_builder.py -q
```

Expected: all pass; provider/model metadata remains unchanged.

- [ ] **Step 9: Authorization-gated shared-snapshot commit checkpoint**

Stage exact paths and inspect every shared-file hunk:

```powershell
git add -- backend/app/services/context_builder.py backend/app/services/chat_service.py backend/app/domain/schemas.py backend/app/api/routes/chat.py backend/app/api/dependencies.py backend/tests/test_context_builder.py backend/tests/test_chat_service.py backend/tests/test_api_chat.py
git diff --cached --check
git diff --cached
```

Commit only if no pre-existing work is included:

```powershell
git commit -m "feat: bind expression plans to chat replies"
```

---

## Task 4: Resolve Message-Bound TTS Through the Existing Provider Contract

**Files:**
- Create: `backend/app/tts/expression_mapper.py`
- Create: `backend/app/services/message_bound_tts_service.py`
- Modify: `backend/app/services/tts_service.py:10-81`
- Create: `backend/tests/test_tts_expression_mapper.py`
- Create: `backend/tests/test_message_bound_tts_service.py`
- Modify: `backend/tests/test_tts_service.py`

- [ ] **Step 1: Write failing mapper tests**

Lock an internal request that cannot carry arbitrary provider options:

```python
def test_expression_mapper_outputs_only_existing_tts_inputs() -> None:
    mapped = TTSExpressionMapper().map(
        TTSExpressionRequest(
            text="persisted reply",
            voice_id="fake-default",
            rate=1.04,
            delivery=ExpressionDelivery.WARM,
            intensity=ExpressionIntensity.MEDIUM,
        )
    )

    assert mapped == MappedTTSRequest("persisted reply", "fake-default", 1.04)
    assert not hasattr(mapped, "delivery")
    assert not hasattr(mapped, "intensity")
    assert not hasattr(mapped, "style")
    assert not hasattr(mapped, "provider_options")
```

- [ ] **Step 2: Run mapper test and confirm RED**

Run:

```powershell
python -m pytest backend/tests/test_tts_expression_mapper.py -q
```

Expected: import failure.

- [ ] **Step 3: Implement the narrow mapper**

Use frozen dataclasses:

```python
@dataclass(frozen=True)
class TTSExpressionRequest:
    text: str
    voice_id: str | None
    rate: float
    delivery: ExpressionDelivery
    intensity: ExpressionIntensity


@dataclass(frozen=True)
class MappedTTSRequest:
    text: str
    voice_id: str | None
    speed: float


class TTSExpressionMapper:
    def map(self, request: TTSExpressionRequest) -> MappedTTSRequest:
        return MappedTTSRequest(request.text, request.voice_id, request.rate)
```

This is the explicit Stage 4D capability boundary: both current providers support speed; delivery/intensity remain semantic and are safely ignored.

- [ ] **Step 4: Write failing message-bound service tests**

Create recording `TTSService` and plan-service doubles. Cover:

```python
@pytest.mark.parametrize(
    ("plan_rate", "user_speed", "expected"),
    [(0.94, 1.5, 1.41), (1.10, 2.0, 2.0), (0.90, 0.5, 0.5), (1.0, None, 1.0)],
)
async def test_message_bound_tts_multiplies_then_clamps(plan_rate, user_speed, expected, ...):
    await service.synthesize(assistant.id, speed=user_speed)
    assert recording_tts.last_speed == pytest.approx(expected)
```

Also assert:

- persisted assistant content is the exact text passed to TTS;
- current emotion is never read and the original stored plan is reused;
- unknown ID raises `NotFoundError`;
- user message raises `TTSInvalidRequestError`;
- `nan`, `inf`, `0.49`, and `2.01` are rejected before plan mapping/provider invocation;
- absent/incompatible/corrupt plan resolves to neutral `1.0`;
- stream and non-stream resolve identical text, voice, and final speed.

- [ ] **Step 5: Run service tests and confirm RED**

Run:

```powershell
python -m pytest backend/tests/test_message_bound_tts_service.py -q
```

Expected: import failure.

- [ ] **Step 6: Expose reusable speed validation in TTSService**

Add without changing provider signatures:

```python
@staticmethod
def validate_speed(speed: float) -> float:
    if not math.isfinite(speed) or not MIN_SPEED <= speed <= MAX_SPEED:
        raise TTSInvalidRequestError("语音语速必须在 0.5 到 2.0 之间。")
    return speed
```

Make `_validate_request` call this method. Add tests proving `0.5` and `2.0` pass and invalid values fail identically on legacy and message-bound paths.

- [ ] **Step 7: Implement MessageBoundTTSService**

Use:

```python
class MessageBoundTTSService:
    def __init__(
        self,
        messages: MessageRepository,
        expression_plans: ExpressionPlanService,
        mapper: TTSExpressionMapper,
        tts: TTSService,
    ) -> None: ...

    async def synthesize(
        self,
        assistant_message_id: str,
        voice_id: str | None = None,
        speed: float | None = None,
    ) -> SpeechSynthesisResult: ...

    async def synthesize_stream(
        self,
        assistant_message_id: str,
        voice_id: str | None = None,
        speed: float | None = None,
    ) -> AsyncIterator[SpeechSynthesisSegment]: ...
```

Resolution algorithm:

```python
message = self._messages.get(assistant_message_id)
if message is None:
    raise NotFoundError()
if message.role is not ChatRole.ASSISTANT:
    raise TTSInvalidRequestError("只能合成已保存的助手消息。")
user_speed = 1.0 if speed is None else TTSService.validate_speed(speed)
plan = self._expression_plans.resolve_compatible_or_default(message.id)
final_speed = min(MAX_SPEED, max(MIN_SPEED, plan.rate * user_speed))
mapped = self._mapper.map(TTSExpressionRequest(message.content, voice_id, final_speed, plan.delivery, plan.intensity))
```

Both methods must use one private resolver, then call the existing `TTSService`. Do not import or call a concrete provider.

- [ ] **Step 8: Run mapper/service/provider regression tests**

Run:

```powershell
python -m pytest backend/tests/test_tts_expression_mapper.py backend/tests/test_message_bound_tts_service.py backend/tests/test_tts_service.py backend/tests/test_cosyvoice_http_provider.py -q
```

Expected: all pass. Existing CosyVoice payload remains `model/input/voice/response_format/speed` (plus `stream` only for streaming).

- [ ] **Step 9: Authorization-gated TTS orchestration commit checkpoint**

```powershell
git add -- backend/app/tts/expression_mapper.py backend/app/services/message_bound_tts_service.py backend/app/services/tts_service.py backend/tests/test_tts_expression_mapper.py backend/tests/test_message_bound_tts_service.py backend/tests/test_tts_service.py
git diff --cached --check
git diff --cached
```

If clean:

```powershell
git commit -m "feat: resolve expression-aware message speech"
```

---

## Task 5: Expose Strict Message-Bound Speech APIs

**Files:**
- Modify: `backend/app/domain/schemas.py:33-47`
- Modify: `backend/app/api/routes/audio.py:19-52`
- Create: `backend/app/api/routes/message_speech.py`
- Modify: `backend/app/api/dependencies.py:51-56,174-186`
- Modify: `backend/app/main.py:14-15,154-159`
- Create: `backend/tests/test_api_message_speech.py`
- Modify: `backend/tests/test_api_audio.py`
- Modify: `backend/tests/test_api_audio_streaming.py`

- [ ] **Step 1: Write failing non-streaming API tests**

Add:

```python
def test_message_speech_synthesizes_chat_response_by_assistant_id(client) -> None:
    session = client.post("/api/sessions", json={"title": "bound speech"}).json()
    chat = client.post(f"/api/sessions/{session['id']}/messages", json={"content": "hello"}).json()

    response = client.post(f"/api/messages/{chat['assistant_message_id']}/speech", json={})

    assert response.status_code == 200
    assert response.content[:4] == b"RIFF"
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.headers["x-tts-provider"] == "fake"
```

Parameterize forbidden bodies:

```python
@pytest.mark.parametrize("body", [
    {"text": "forged"},
    {"delivery": "firm"},
    {"intensity": "medium"},
    {"style": "free-form"},
    {"ssml": "<speak>forged</speak>"},
    {"provider_options": {"pitch": 2}},
])
def test_message_speech_rejects_client_expression_injection(client, body) -> None:
    ...
    assert response.status_code == 422
```

Also test missing message 404, user message 422, missing plan default success, timeout 504, empty audio 502, and text still present through `GET /messages` after TTS failure.

- [ ] **Step 2: Write failing streaming API tests**

Verify `start`, ordered WAV `segment` events, and `done`; use the same assistant ID and assert stream/non-stream recording dependencies receive the same final speed for plan `0.94` and user speed `1.5` (`1.41`).

- [ ] **Step 3: Run API tests and confirm RED**

Run:

```powershell
python -m pytest backend/tests/test_api_message_speech.py -q
```

Expected: 404 because the router does not exist.

- [ ] **Step 4: Add strict schema and reusable audio response helpers**

Add:

```python
class MessageBoundSynthesizeSpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    voice_id: str | None = None
    speed: float | None = None
```

Extract from `audio.py` only the generic helpers needed by both route modules:

```python
def speech_response(result: SpeechSynthesisResult) -> Response: ...

async def speech_stream_events(service, *, assistant_message_id=None, text=None, voice_id=None, speed=None) -> AsyncIterator[bytes]: ...
```

Prefer a focused helper signature or a small protocol rather than weakening request validation. Legacy `/api/audio/*` must preserve its exact request/response behavior.

- [ ] **Step 5: Implement router and DI**

Create routes:

```python
router = APIRouter(prefix="/api/messages", tags=["audio"])

@router.post("/{assistant_message_id}/speech")
async def synthesize_message_speech(...): ...

@router.post("/{assistant_message_id}/speech/stream")
async def synthesize_message_speech_stream(...): ...
```

Construct `MessageBoundTTSService` from the request connection's `MessageRepository` and `ExpressionPlanRepository`, `ExpressionPlanService`, `ExpressionPlanPolicy`, `TTSExpressionMapper`, and existing `TTSService`. Register the router in `main.py`.

- [ ] **Step 6: Run new and legacy audio API tests**

Run:

```powershell
python -m pytest backend/tests/test_api_message_speech.py backend/tests/test_api_audio.py backend/tests/test_api_audio_streaming.py backend/tests/test_api_chat.py -q
```

Expected: all pass; legacy APIs remain text-based and do not create/read plans.

- [ ] **Step 7: Run provider contract regression**

Run:

```powershell
python -m pytest backend/tests/test_cosyvoice_http_provider.py backend/tests/test_api_audio_streaming_cosyvoice.py -q
```

Expected: all pass; no delivery/intensity/style/pitch/energy/emotion/SSML fields appear in provider payloads.

- [ ] **Step 8: Authorization-gated API wiring commit checkpoint**

```powershell
git add -- backend/app/domain/schemas.py backend/app/api/routes/audio.py backend/app/api/routes/message_speech.py backend/app/api/dependencies.py backend/app/main.py backend/tests/test_api_message_speech.py backend/tests/test_api_audio.py backend/tests/test_api_audio_streaming.py
git diff --cached --check
git diff --cached
```

If clean:

```powershell
git commit -m "feat: add message-bound speech APIs"
```

---

## Task 6: Add Frontend Message-Bound API Clients

**Files:**
- Modify: `frontend/src/api/types.ts:17-37`
- Modify: `frontend/src/api/client.ts:39-63,165-170`
- Modify: `frontend/src/api/speechStream.ts:1-99`
- Modify: `frontend/src/api/client.test.ts`
- Modify: `frontend/src/api/speechStream.test.ts`

- [ ] **Step 1: Write failing client tests**

Add:

```typescript
it('synthesizes persisted assistant speech without client text or expression options', async () => {
  vi.mocked(fetch).mockResolvedValueOnce(wavResponse());

  await apiClient.synthesizeMessageSpeech('assistant-42', {
    voiceId: 'fake-default',
    speed: 1.04,
  });

  expect(fetch).toHaveBeenCalledWith(
    '/api/messages/assistant-42/speech',
    expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ voice_id: 'fake-default', speed: 1.04 }),
    }),
  );
  const [, init] = vi.mocked(fetch).mock.calls[0];
  expect(String(init?.body)).not.toContain('text');
  expect(String(init?.body)).not.toContain('delivery');
  expect(String(init?.body)).not.toContain('style');
});
```

Add the streaming counterpart expecting `/api/messages/assistant-42/speech/stream`. Keep existing tests asserting legacy URLs `/api/audio/speech` and `/api/audio/speech/stream`.

- [ ] **Step 2: Run client tests and confirm RED**

Run:

```powershell
npm --prefix frontend run test -- src/api/client.test.ts src/api/speechStream.test.ts
```

Expected: failures because message-bound client methods do not exist.

- [ ] **Step 3: Add the response ID and non-streaming method**

Update:

```typescript
export interface ChatResponse {
  reply: string;
  metadata: { provider: string; model: string };
  assistant_message_id: string;
}
```

Add:

```typescript
synthesizeMessageSpeech(
  assistantMessageId: string,
  options?: SynthesizeSpeechOptions,
): Promise<SpeechSynthesisResponse>
```

The URL must encode the ID and the body must contain only `voice_id` and `speed`.

- [ ] **Step 4: Add message-bound streaming while sharing the parser**

Expose:

```typescript
export async function* streamMessageSpeech(
  assistantMessageId: string,
  options: SynthesizeSpeechOptions = {},
): AsyncGenerator<SpeechStreamEvent>
```

Refactor fetch/reader handling into a private helper shared with `streamSpeech`; do not duplicate or alter `parseEvent` semantics.

- [ ] **Step 5: Run client tests and typecheck**

Run:

```powershell
npm --prefix frontend run test -- src/api/client.test.ts src/api/speechStream.test.ts
npm --prefix frontend run typecheck
```

Expected: all pass.

- [ ] **Step 6: Authorization-gated frontend API commit checkpoint**

```powershell
git add -- frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/api/speechStream.ts frontend/src/api/client.test.ts frontend/src/api/speechStream.test.ts
git diff --cached --check
git diff --cached
```

If clean:

```powershell
git commit -m "feat: add message-bound speech clients"
```

---

## Task 7: Move Playback and Voice Turns from Text Heuristics to Message IDs

**Files:**
- Modify: `frontend/src/hooks/useAudioPlaybackController.ts:204-345,377-386`
- Modify: `frontend/src/components/MessageList.tsx:22-31`
- Modify: `frontend/src/components/MessageList.test.tsx`
- Modify: `frontend/src/App.tsx:402-459`
- Modify: `frontend/src/App.test.tsx`
- Delete: `frontend/src/voiceTurn.ts`
- Delete: `frontend/src/voiceTurn.test.ts`

- [ ] **Step 1: Write failing historical-message playback tests**

In `MessageList.test.tsx`, assert clicking the first assistant's play button requests `/api/messages/a1/speech`, the body does not contain message content or `text`, and a failed request leaves both assistant texts visible. Retry must call the same message-bound URL twice.

- [ ] **Step 2: Run MessageList tests and confirm RED**

Run:

```powershell
npm --prefix frontend run test -- src/components/MessageList.test.tsx
```

Expected: current controller calls `/api/audio/speech` with text.

- [ ] **Step 3: Narrow controller and MessageList signatures**

Change:

```typescript
play(messageId: string, options?: PlayOptions): Promise<boolean>
replay(messageId: string): Promise<boolean>
```

Use `apiClient.synthesizeMessageSpeech(messageId, ...)` and `apiClient.streamMessageSpeech(messageId, ...)`. Change MessageList to:

```tsx
onPlay={() => audioController.play(message.id)}
onReplay={() => audioController.replay(message.id)}
```

Preserve existing URL caching, replay, stream scheduler/HTMLAudio fallback, pause/resume/stop, AbortController, output-device, and reset/unmount cleanup behavior.

- [ ] **Step 4: Run MessageList and streaming-controller regression tests**

Run:

```powershell
npm --prefix frontend run test -- src/components/MessageList.test.tsx src/hooks/useAudioPlaybackController.streaming.test.tsx
```

Expected: all pass.

- [ ] **Step 5: Write failing voice-turn ID tests**

In `App.test.tsx`, return:

```typescript
{
  reply: '目标语音回复',
  metadata: { provider: 'fake', model: 'test-model' },
  assistant_message_id: 'voice-a',
}
```

Make the refreshed message list deliberately include a duplicate transcript and competing assistant before `voice-a`. Assert the only speech stream request is `/api/messages/voice-a/speech/stream`; `/api/messages/competing-a/speech/stream` is never called. Add a failing-stream test that keeps the generated text visible and shows the existing voice failure status.

- [ ] **Step 6: Run App tests and confirm RED**

Run:

```powershell
npm --prefix frontend run test -- src/App.test.tsx
```

Expected: duplicate-transcript case selects through the old `findAssistantReplyForVoiceTurn` heuristic.

- [ ] **Step 7: Bind directly to `sendMessage()` response ID**

Keep the response:

```typescript
const chatResponse = await apiClient.sendMessage(sessionId, cleanTranscript);
```

After refreshing messages and applying existing stale-session/generation guards, call:

```typescript
const played = await audioController.play(chatResponse.assistant_message_id, {
  streaming: true,
});
```

Remove before/after transcript matching and its heuristic-only “corresponding voice reply not found” branch. Preserve text refresh before TTS, stale-turn guards, session switch/reset, recording interruption, and failure status behavior.

- [ ] **Step 8: Delete the obsolete heuristic only after imports are gone**

Delete `voiceTurn.ts` and `voiceTurn.test.ts`. Run:

```powershell
npm --prefix frontend run test -- src/App.test.tsx src/components/MessageList.test.tsx
npm --prefix frontend run typecheck
```

Expected: all pass with no unresolved imports.

- [ ] **Step 9: Authorization-gated playback commit checkpoint**

```powershell
git add -- frontend/src/hooks/useAudioPlaybackController.ts frontend/src/components/MessageList.tsx frontend/src/components/MessageList.test.tsx frontend/src/App.tsx frontend/src/App.test.tsx frontend/src/voiceTurn.ts frontend/src/voiceTurn.test.ts
git diff --cached --check
git diff --cached
```

If clean:

```powershell
git commit -m "feat: bind speech playback to assistant messages"
```

---

## Task 8: Add Fake-First Browser and Database Acceptance

**Files:**
- Modify: `frontend/e2e/voice-turn.spec.ts`
- Modify: `frontend/e2e/chat.spec.ts`
- Modify: `frontend/playwright.config.ts`
- Create: `scripts/verify_stage4d_e2e_database.py`
- Create: `tests/test_verify_stage4d_e2e_database.py`
- Modify: `frontend/playwright.global-teardown.ts`
- Modify: `frontend/playwright.global-teardown.test.ts`

- [ ] **Step 1: Write failing E2E request assertions**

Capture requests matching:

```typescript
/^\/api\/messages\/[^/]+\/speech(?:\/stream)?$/
```

For voice turn, assert one stream request, no competing message ID, and a body without `text`, `delivery`, `intensity`, `style`, `ssml`, or provider options. For normal historical playback, record the assistant ID, refresh, play it again, and assert the same ID is reused.

- [ ] **Step 2: Pin automatic E2E to fake TTS**

In backend `webServer.env`, explicitly set:

```typescript
TTS_PROVIDER: 'fake',
TTS_FAKE_MODE: 'ok',
TTS_DEFAULT_VOICE: 'fake-default',
```

This prevents developer-machine CosyVoice configuration from entering automated acceptance.

- [ ] **Step 3: Run focused E2E**

Run:

```powershell
npm --prefix frontend run test:e2e -- e2e/voice-turn.spec.ts e2e/chat.spec.ts
```

Expected before full wiring: URL/body assertions fail. After Tasks 5–7: both specs pass with no browser console errors, 404s, or 5xx responses.

- [ ] **Step 4: Write verifier unit tests before the script**

In `tests/test_verify_stage4d_e2e_database.py`, create temporary SQLite databases for PASS and each failure: missing table, no plans, orphan, non-assistant relation, duplicate message/schema, invalid enum/rate/version, and forbidden columns. Assert `verify_database(path)` raises a descriptive exception for each invalid fixture.

- [ ] **Step 5: Run verifier tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_verify_stage4d_e2e_database.py -q
```

Expected: import failure.

- [ ] **Step 6: Implement the read-only database verifier**

Expose:

```python
def verify_database(database_path: Path) -> None: ...
```

Verify:

- table exists and has at least one row;
- no orphan and every related message role is assistant;
- no duplicate `(assistant_message_id, schema_version)`;
- schema version `1`, source version non-negative;
- delivery/rate/intensity values fit v1;
- columns do not include `text`, `content`, `style`, `ssml`, `provider_options`, `vendor_options`, or `emotion_vector`.

Accept only `--database <path>`. Print `PASS: Stage 4D E2E expression plans satisfy persistence invariants` on success.

- [ ] **Step 7: Add teardown ordering tests and integration**

Test exact order: Stage 4C verifier, Stage 4D verifier, database removal, WAL removal, SHM removal. If either verifier fails, cleanup still occurs and the failure propagates. Integrate the new verifier before deletion.

- [ ] **Step 8: Run verifier, teardown, and full E2E tests**

Run:

```powershell
python -m pytest tests/test_verify_stage4d_e2e_database.py -q
npm --prefix frontend run test -- playwright.global-teardown.test.ts
npm --prefix frontend run test:e2e
```

Expected: all pass; teardown prints both Stage 4C and Stage 4D PASS lines before removing the isolated database.

- [ ] **Step 9: Authorization-gated acceptance commit checkpoint**

```powershell
git add -- frontend/e2e/voice-turn.spec.ts frontend/e2e/chat.spec.ts frontend/playwright.config.ts scripts/verify_stage4d_e2e_database.py tests/test_verify_stage4d_e2e_database.py frontend/playwright.global-teardown.ts frontend/playwright.global-teardown.test.ts
git diff --cached --check
git diff --cached
```

If clean:

```powershell
git commit -m "test: verify message-bound expression speech"
```

---

## Task 9: Add an Explicit Real CosyVoice Protocol Smoke

**Files:**
- Create: `scripts/smoke_stage4d_cosyvoice_message_tts.py`
- Create: `backend/tests/test_smoke_stage4d_cosyvoice_message_tts.py`

- [ ] **Step 1: Write failing gate and transport tests**

Add:

```python
def test_smoke_refuses_real_provider_without_explicit_opt_in(monkeypatch, capsys) -> None:
    monkeypatch.delenv("STAGE4D_REAL_COSYVOICE", raising=False)

    assert main(["--backend-url", "http://127.0.0.1:18003"]) == 2
    assert "BLOCKED: set STAGE4D_REAL_COSYVOICE=1" in capsys.readouterr().out
```

Use an `httpx.MockTransport` test to simulate health, session creation, chat with `assistant_message_id`, non-stream WAV, and NDJSON `start/segment/done`. Assert no `Path.write_bytes` occurs and requests target message-bound URLs.

- [ ] **Step 2: Run smoke tests and confirm RED**

Run:

```powershell
python -m pytest backend/tests/test_smoke_stage4d_cosyvoice_message_tts.py -q
```

Expected: import failure.

- [ ] **Step 3: Implement the opt-in script**

Arguments:

```text
--backend-url  default http://127.0.0.1:18003
--voice-id     default default-zh-female
--speed        default 1.0
--timeout      default 120
```

Require `STAGE4D_REAL_COSYVOICE=1`; create a short-lived test session, send a fixed nonsensitive prompt, read the assistant ID, call both message-bound endpoints, validate nonempty WAV and at least one stream segment plus `done`, and print only protocol-level JSON diagnostics. Do not write audio, credentials, provider payloads, or database contents.

- [ ] **Step 4: Run the offline script tests**

Run:

```powershell
python -m pytest backend/tests/test_smoke_stage4d_cosyvoice_message_tts.py backend/tests/test_cosyvoice_http_provider.py -q
```

Expected: all pass without network access.

- [ ] **Step 5: Run real smoke only when explicitly configured**

After an authorized isolated backend is running with fake LLM, `TTS_PROVIDER=cosyvoice-http`, an isolated SQLite database, and the local CosyVoice URL/model/voice:

```powershell
$env:STAGE4D_REAL_COSYVOICE = '1'
python scripts/smoke_stage4d_cosyvoice_message_tts.py --backend-url http://127.0.0.1:18003 --voice-id default-zh-female --speed 1.0
```

Expected: PASS with assistant ID, non-stream WAV byte count, and stream segment count. If the service is not explicitly configured, record `BLOCKED / 未运行`; never call it PASS.

- [ ] **Step 6: Authorization-gated smoke harness commit checkpoint**

```powershell
git add -- scripts/smoke_stage4d_cosyvoice_message_tts.py backend/tests/test_smoke_stage4d_cosyvoice_message_tts.py
git diff --cached --check
git diff --cached
```

If clean:

```powershell
git commit -m "test: add opt-in message TTS smoke"
```

---

## Task 10: Full Verification, Runtime Exercise, Review, and Evidence

**Files:**
- Create: `docs/stage4d-expression-plan-tts.md`
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run focused backend Stage 4D tests**

Run:

```powershell
python -m pytest backend/tests/test_expression_plan_models.py backend/tests/test_expression_plan_repository.py backend/tests/test_expression_plan_policy.py backend/tests/test_expression_plan_service.py backend/tests/test_emotion_context.py backend/tests/test_context_builder.py backend/tests/test_chat_service.py backend/tests/test_tts_expression_mapper.py backend/tests/test_message_bound_tts_service.py backend/tests/test_tts_service.py backend/tests/test_cosyvoice_http_provider.py backend/tests/test_api_chat.py backend/tests/test_api_audio.py backend/tests/test_api_audio_streaming.py backend/tests/test_api_message_speech.py backend/tests/test_smoke_stage4d_cosyvoice_message_tts.py -q
```

Expected: all pass.

- [ ] **Step 2: Run complete automated suites**

Run:

```powershell
python -m pytest backend/tests -q
python -m pytest tests -q
npm --prefix frontend run test
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

Expected: all commands pass. Record exact test counts and durations; do not copy historical counts.

- [ ] **Step 3: Run the scoped runtime verification skill**

Invoke `AI桌宠:verify` and exercise the real fake-first runtime surface, not only mocks:

1. create a session;
2. send text and observe returned assistant ID;
3. call message-bound non-stream and stream endpoints;
4. confirm persisted text remains retrievable after a forced TTS failure;
5. drive the browser voice turn and historical replay;
6. confirm no cross-message audio binding, browser console errors, 404, or 5xx;
7. confirm teardown database invariants pass.

Expected: observed runtime behavior matches the design. If it does not, keep the task incomplete and debug before documentation.

- [ ] **Step 4: Run mandatory review and simplification passes**

Invoke `/code-review` (required before any commit/deploy), then `requesting-code-review` for completion review. Run `simplify` only for confirmed quality improvements that do not broaden scope. Fix confirmed issues and rerun affected tests plus the full relevant suite.

- [ ] **Step 5: Inspect security and compatibility invariants**

Search the changed code/tests and confirm:

- public message-bound request has no text/expression/vendor fields;
- plans/logs/audits do not contain chat text, full vectors, prompt, memory, credentials, or provider payload;
- provider interfaces and CosyVoice payload are unchanged except verified speed;
- legacy text TTS APIs still work and do not apply plans;
- no Live2D, desktop shell, background listening, audio cache, or protected asset changes;
- no `.env`, database, WAV, log, `test-results`, or credentials are staged.

Run:

```powershell
git diff --check
git status --short
git diff --cached --check
git diff --cached
```

- [ ] **Step 6: Write evidence from fresh results**

Create `docs/stage4d-expression-plan-tts.md` containing:

```text
Scope implemented
Message/snapshot binding evidence
ExpressionPlan schema and mapping table
Failure-isolation evidence
Fake provider automated results with exact counts
Real CosyVoice smoke: PASS or BLOCKED / 未运行, with reason
Runtime verification observations
Known limitations: no verified delivery/intensity acoustic support
Files changed
```

Do not mark Stage 4D complete if required fake-first runtime/tests fail. Real CosyVoice may be `BLOCKED / 未运行` without blocking fake-first completion, but it must never be represented as PASS.

- [ ] **Step 7: Update stage docs only after acceptance**

Update `README.md` and `CLAUDE.md` to mark 4D complete only if all required automatic and runtime criteria pass. Preserve the statement that emotion is an expression strategy, not real feeling. Set the next task only to the next separately approved minimal Stage 4 item; do not silently start it.

- [ ] **Step 8: Authorization-gated evidence/docs commit checkpoint**

Stage exact documentation paths only, inspect, and commit only if the index is cleanly attributable:

```powershell
git add -- docs/stage4d-expression-plan-tts.md README.md CLAUDE.md
git diff --cached --check
git diff --cached
```

If clean:

```powershell
git commit -m "docs: record stage 4d expression TTS acceptance"
```

If pre-existing Stage 3/4A–4C hunks are interleaved in README/CLAUDE, skip the commit and report the exact blocker instead of staging the whole files.

---

## Completion Checklist

- [ ] One immutable v1 plan per assistant message, with DB and domain constraints.
- [ ] Text expression and plan use the exact same pre-reply snapshot object/version.
- [ ] Plan creation is post-persistence and cannot affect chat success or later emotion side effects.
- [ ] Chat response returns the persisted assistant ID.
- [ ] Message-bound speech reads text/plan server-side and rejects client expression injection.
- [ ] Rate composition validates user speed, multiplies by plan rate, then clamps globally.
- [ ] Current providers receive only the existing text/voice/speed contract.
- [ ] Missing/disabled/corrupt/incompatible plan degrades to neutral `1.0` without dynamic recomputation.
- [ ] Stream and non-stream paths share resolution and error semantics.
- [ ] Frontend voice turn and history playback bind directly to assistant IDs.
- [ ] Legacy text TTS APIs remain compatible and plan-independent.
- [ ] Fake unit/API/frontend/E2E/runtime acceptance passes.
- [ ] Real CosyVoice result is honestly recorded as PASS or BLOCKED / 未运行.
- [ ] No unrelated phase work, secrets, databases, audio, or pre-existing changes are included in Stage 4D commits.
