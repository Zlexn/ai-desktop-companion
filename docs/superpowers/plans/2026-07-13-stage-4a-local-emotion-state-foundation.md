# Stage 4A Local Emotion State Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local, deterministic, globally shared six-dimensional emotion-state foundation with append-only audit events, bounded/decaying transitions, optimistic concurrency, management API, and an auditable frontend panel.

**Architecture:** Emotion data lives in dedicated SQLite tables and immutable domain models, never in messages, memories, summaries, or provider metadata. A pure `EmotionPolicy` computes bounded deterministic transitions and decay; `EmotionService` coordinates repository CAS writes and settings/reset operations. Stage 4A exposes independent HTTP/UI management while deliberately avoiding chat Prompt injection, remote LLM analysis, TTS changes, ExpressionPlan, and desktop assets.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, Pydantic, pytest, Hypothesis (only if already installable in backend test extra; otherwise deterministic parameterized properties), React 19, TypeScript, Vitest, Testing Library, Playwright.

---

## File Structure

### Backend domain and persistence

- Modify: `backend/app/domain/models.py` — add immutable `EmotionState`, `EmotionEvent`, enums, and `EmotionVector`.
- Modify: `backend/app/domain/schemas.py` — add state/event/settings/reset API schemas.
- Modify: `backend/app/repositories/sqlite.py` — create independent `emotion_states` and `emotion_events` tables plus indexes.
- Create: `backend/app/repositories/emotions.py` — current-state reads, append-only event reads, compare-and-swap transition/settings/reset writes.
- Test: `backend/tests/test_emotion_repository.py` — initialization, persistence, event audit, CAS conflict, ordering, and global scope.

### Backend policy and service

- Create: `backend/app/services/emotion_policy.py` — pure baselines, clamps, local reason detection, bounded transition, and elapsed-time decay.
- Create: `backend/app/services/emotion_service.py` — get/list/update settings/reset/apply-turn orchestration with finite CAS retries.
- Test: `backend/tests/test_emotion_policy.py` — dimension bounds, per-turn caps, conservative rules, decay, reset baseline, disabled behavior.
- Test: `backend/tests/test_emotion_service.py` — repository integration, cross-session global continuity, CAS retry/no lost update, audit reason/source linkage.

### Backend composition and API

- Create: `backend/app/api/routes/emotion.py` — GET state/events, PATCH settings, POST reset.
- Modify: `backend/app/api/routes/__init__.py` — export router only if current package convention requires it.
- Modify: `backend/app/api/dependencies.py` — construct emotion repository/service through centralized DI.
- Modify: `backend/app/main.py` — include emotion router.
- Test: `backend/tests/test_api_emotion.py` — HTTP contract, validation, enable/disable/reset, event limits, persistence.
- Modify: `backend/app/services/chat_service.py` — Stage 4A only schedules or invokes local post-turn emotion update after assistant persistence; no Prompt context and no response shape change.
- Modify: `backend/app/api/dependencies.py` — inject a best-effort emotion updater into ChatService.
- Test: `backend/tests/test_chat_service.py` and `backend/tests/test_api_chat.py` — successful turns update global state; emotion failure does not lose assistant response; disabled mode does not transition.

### Frontend

- Modify: `frontend/src/api/types.ts` — add state/event/settings types.
- Modify: `frontend/src/api/client.ts` — add state/events/settings/reset methods.
- Create: `frontend/src/components/EmotionPanel.tsx` — six dimensions, explanations, enable switch, reset, recent reasons/events, loading/error.
- Create: `frontend/src/components/EmotionPanel.test.tsx` — rendering, settings, reset confirmation, error retention, truthful wording.
- Modify: `frontend/src/App.tsx` — load and mutate emotion resource independently from sessions/memories.
- Modify: `frontend/src/App.test.tsx` — startup load, enable/disable/reset, chat remains usable on emotion API errors.
- Create: `frontend/e2e/emotion.spec.ts` — cross-session global continuity, reload persistence, disable and reset, no console/5xx.

### Evidence and state

- Create: `docs/stage4a-local-emotion-state-foundation.md` — fresh commands, API/runtime observations, limitations, PASS/BLOCKED.
- Modify: `README.md` — Stage 4A scope and current status.
- Modify: `CLAUDE.md` — Stage 4 implementing status and next slice only after observed evidence.

Do not modify Prompt templates, LLM providers, memory retrieval, summary injection, TTS contracts/providers, voice orchestration, Live2D, desktop shell, or copyrighted assets.

## Fixed Contracts

Use one global scope constant:

```python
DEFAULT_EMOTION_SCOPE_ID = "default-companion"
```

Six-dimensional baseline:

```python
EMOTION_BASELINE = EmotionVector(
    mood=0.50,
    trust=0.40,
    concern=0.20,
    distance=0.55,
    irritation=0.10,
    formality=0.60,
)
```

Per-turn absolute caps:

```python
EMOTION_MAX_DELTA = EmotionVector(
    mood=0.08,
    trust=0.04,
    concern=0.10,
    distance=0.05,
    irritation=0.08,
    formality=0.06,
)
```

Stage 4A local reason codes:

```text
neutral_turn
user_respectful_support
user_explicit_apology
user_clear_boundary
user_repeated_hostility
user_distress_signal
user_positive_shared_event
settings_enabled
settings_disabled
manual_reset
time_decay
```

Stage 4A never calls an LLM and never includes an emotion system message in provider payloads.

### Task 1: Define Immutable Emotion Domain Models

**Files:**
- Modify: `backend/app/domain/models.py:1-105`
- Create: `backend/tests/test_emotion_models.py`

- [ ] **Step 1: Write failing baseline and immutability tests**

Create `backend/tests/test_emotion_models.py`:

```python
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from app.domain.models import (
    DEFAULT_EMOTION_SCOPE_ID,
    EMOTION_BASELINE,
    EmotionEvent,
    EmotionEventType,
    EmotionState,
    EmotionVector,
)


def test_emotion_baseline_has_all_six_bounded_dimensions() -> None:
    assert DEFAULT_EMOTION_SCOPE_ID == "default-companion"
    assert EMOTION_BASELINE == EmotionVector(
        mood=0.50,
        trust=0.40,
        concern=0.20,
        distance=0.55,
        irritation=0.10,
        formality=0.60,
    )
    assert all(0.0 <= value <= 1.0 for value in EMOTION_BASELINE.values())


def test_emotion_state_is_immutable() -> None:
    state = EmotionState(
        scope_id=DEFAULT_EMOTION_SCOPE_ID,
        enabled=True,
        vector=EMOTION_BASELINE,
        version=0,
        updated_at=datetime.now(UTC),
    )
    with pytest.raises(FrozenInstanceError):
        state.version = 1  # type: ignore[misc]


def test_emotion_event_keeps_structured_reason_and_sources() -> None:
    now = datetime.now(UTC)
    event = EmotionEvent(
        id="event-1",
        scope_id=DEFAULT_EMOTION_SCOPE_ID,
        event_type=EmotionEventType.TRANSITION,
        before=EMOTION_BASELINE,
        after=EMOTION_BASELINE,
        applied_delta=EmotionVector.zero(),
        reason_codes=("neutral_turn",),
        source_session_id="session-1",
        source_user_message_id="user-1",
        source_assistant_message_id="assistant-1",
        engine="rule",
        rule_version="emotion-rules-v1",
        created_at=now,
    )
    assert event.reason_codes == ("neutral_turn",)
```

- [ ] **Step 2: Run the tests and verify missing imports fail**

```powershell
python -m pytest backend/tests/test_emotion_models.py -q
```

Expected: collection fails because the emotion models do not exist.

- [ ] **Step 3: Add the minimal immutable models and constants**

Append to `backend/app/domain/models.py`:

```python
DEFAULT_EMOTION_SCOPE_ID = "default-companion"


class EmotionEventType(StrEnum):
    TRANSITION = "transition"
    DECAY = "decay"
    SETTINGS = "settings"
    RESET = "reset"


@dataclass(frozen=True)
class EmotionVector:
    mood: float
    trust: float
    concern: float
    distance: float
    irritation: float
    formality: float

    @classmethod
    def zero(cls) -> "EmotionVector":
        return cls(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    def values(self) -> tuple[float, ...]:
        return (
            self.mood,
            self.trust,
            self.concern,
            self.distance,
            self.irritation,
            self.formality,
        )


EMOTION_BASELINE = EmotionVector(0.50, 0.40, 0.20, 0.55, 0.10, 0.60)
EMOTION_MAX_DELTA = EmotionVector(0.08, 0.04, 0.10, 0.05, 0.08, 0.06)


@dataclass(frozen=True)
class EmotionState:
    scope_id: str
    enabled: bool
    vector: EmotionVector
    version: int
    updated_at: datetime


@dataclass(frozen=True)
class EmotionEvent:
    id: str
    scope_id: str
    event_type: EmotionEventType
    before: EmotionVector
    after: EmotionVector
    applied_delta: EmotionVector
    reason_codes: tuple[str, ...]
    source_session_id: str | None
    source_user_message_id: str | None
    source_assistant_message_id: str | None
    engine: str
    rule_version: str
    created_at: datetime
```

- [ ] **Step 4: Run model tests**

```powershell
python -m pytest backend/tests/test_emotion_models.py -q
```

Expected: 3 tests pass.

### Task 2: Create Dedicated SQLite Tables and Repository Initialization

**Files:**
- Modify: `backend/app/repositories/sqlite.py:7-103,174-195`
- Create: `backend/app/repositories/emotions.py`
- Create: `backend/tests/test_emotion_repository.py`

- [ ] **Step 1: Write failing repository initialization test**

Start `backend/tests/test_emotion_repository.py`:

```python
from pathlib import Path

from app.domain.models import DEFAULT_EMOTION_SCOPE_ID, EMOTION_BASELINE
from app.repositories.emotions import EmotionRepository
from app.repositories.sqlite import managed_connection


def test_get_or_create_initializes_one_global_baseline(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'emotion.db'}"
    with managed_connection(database_url) as connection:
        repository = EmotionRepository(connection)
        first = repository.get_or_create()
        second = repository.get_or_create()

        assert first == second
        assert first.scope_id == DEFAULT_EMOTION_SCOPE_ID
        assert first.enabled is True
        assert first.vector == EMOTION_BASELINE
        assert first.version == 0
        assert connection.execute("SELECT COUNT(*) FROM emotion_states").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM emotion_events").fetchone()[0] == 0
```

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/test_emotion_repository.py::test_get_or_create_initializes_one_global_baseline -q
```

Expected: import or missing-table failure.

- [ ] **Step 3: Add independent tables to `SCHEMA_SQL`**

Before the closing triple quote add:

```sql
CREATE TABLE IF NOT EXISTS emotion_states (
    scope_id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    mood REAL NOT NULL CHECK (mood >= 0.0 AND mood <= 1.0),
    trust REAL NOT NULL CHECK (trust >= 0.0 AND trust <= 1.0),
    concern REAL NOT NULL CHECK (concern >= 0.0 AND concern <= 1.0),
    distance REAL NOT NULL CHECK (distance >= 0.0 AND distance <= 1.0),
    irritation REAL NOT NULL CHECK (irritation >= 0.0 AND irritation <= 1.0),
    formality REAL NOT NULL CHECK (formality >= 0.0 AND formality <= 1.0),
    version INTEGER NOT NULL CHECK (version >= 0),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS emotion_events (
    id TEXT PRIMARY KEY,
    scope_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('transition', 'decay', 'settings', 'reset')),
    before_json TEXT NOT NULL,
    after_json TEXT NOT NULL,
    applied_delta_json TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    source_session_id TEXT,
    source_user_message_id TEXT,
    source_assistant_message_id TEXT,
    engine TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (scope_id) REFERENCES emotion_states(scope_id) ON DELETE CASCADE,
    FOREIGN KEY (source_session_id) REFERENCES sessions(id) ON DELETE SET NULL,
    FOREIGN KEY (source_user_message_id) REFERENCES messages(id) ON DELETE SET NULL,
    FOREIGN KEY (source_assistant_message_id) REFERENCES messages(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_emotion_events_scope_created
ON emotion_events(scope_id, created_at DESC);
```

- [ ] **Step 4: Implement repository mapping and `get_or_create`**

Create `backend/app/repositories/emotions.py` with:

```python
import json
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.models import (
    DEFAULT_EMOTION_SCOPE_ID,
    EMOTION_BASELINE,
    EmotionEvent,
    EmotionEventType,
    EmotionState,
    EmotionVector,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _vector_dict(vector: EmotionVector) -> dict[str, float]:
    return {
        "mood": vector.mood,
        "trust": vector.trust,
        "concern": vector.concern,
        "distance": vector.distance,
        "irritation": vector.irritation,
        "formality": vector.formality,
    }


def _vector_from_mapping(value: dict[str, object]) -> EmotionVector:
    return EmotionVector(**{key: float(value[key]) for key in _vector_dict(EMOTION_BASELINE)})


class EmotionVersionConflictError(RuntimeError):
    pass


class EmotionRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_or_create(self, scope_id: str = DEFAULT_EMOTION_SCOPE_ID) -> EmotionState:
        row = self._connection.execute(
            "SELECT * FROM emotion_states WHERE scope_id = ?", (scope_id,)
        ).fetchone()
        if row is None:
            now = _now()
            self._connection.execute(
                """
                INSERT OR IGNORE INTO emotion_states (
                    scope_id, enabled, mood, trust, concern, distance,
                    irritation, formality, version, updated_at
                ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (scope_id, *EMOTION_BASELINE.values(), now.isoformat()),
            )
            self._connection.commit()
            row = self._connection.execute(
                "SELECT * FROM emotion_states WHERE scope_id = ?", (scope_id,)
            ).fetchone()
        assert row is not None
        return self._state_from_row(row)

    @staticmethod
    def _state_from_row(row: sqlite3.Row) -> EmotionState:
        return EmotionState(
            scope_id=str(row["scope_id"]),
            enabled=bool(row["enabled"]),
            vector=EmotionVector(
                mood=float(row["mood"]), trust=float(row["trust"]),
                concern=float(row["concern"]), distance=float(row["distance"]),
                irritation=float(row["irritation"]), formality=float(row["formality"]),
            ),
            version=int(row["version"]),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )
```

Imports for event/CAS methods are intentionally present because the same focused repository receives them in the next task.

- [ ] **Step 5: Run the initialization test**

```powershell
python -m pytest backend/tests/test_emotion_repository.py::test_get_or_create_initializes_one_global_baseline -q
```

Expected: PASS.

### Task 3: Add Atomic CAS Mutation and Append-Only Events

**Files:**
- Modify: `backend/app/repositories/emotions.py`
- Modify: `backend/tests/test_emotion_repository.py`

- [ ] **Step 1: Add failing transition, event ordering, and stale-version tests**

Append tests that call:

```python
updated = repository.apply_transition(
    expected_version=0,
    after=EmotionVector(0.54, 0.42, 0.20, 0.53, 0.10, 0.58),
    event_type=EmotionEventType.TRANSITION,
    reason_codes=("user_respectful_support",),
    source_session_id=None,
    source_user_message_id=None,
    source_assistant_message_id=None,
    engine="rule",
    rule_version="emotion-rules-v1",
)
assert updated.version == 1
assert repository.list_events(limit=10)[0].after == updated.vector

with pytest.raises(EmotionVersionConflictError):
    repository.apply_transition(
        expected_version=0,
        after=EMOTION_BASELINE,
        event_type=EmotionEventType.TRANSITION,
        reason_codes=("neutral_turn",),
        source_session_id=None,
        source_user_message_id=None,
        source_assistant_message_id=None,
        engine="rule",
        rule_version="emotion-rules-v1",
    )
```

Also assert the state update and event insertion occur in one transaction: force an invalid source message FK and confirm neither state version nor event count changes.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/test_emotion_repository.py -q
```

Expected: failures for missing `apply_transition` and `list_events`.

- [ ] **Step 3: Implement CAS update in one transaction**

Add `apply_transition` to `EmotionRepository`:

```python
def apply_transition(
    self,
    *,
    expected_version: int,
    after: EmotionVector,
    event_type: EmotionEventType,
    reason_codes: tuple[str, ...],
    source_session_id: str | None,
    source_user_message_id: str | None,
    source_assistant_message_id: str | None,
    engine: str,
    rule_version: str,
    scope_id: str = DEFAULT_EMOTION_SCOPE_ID,
) -> EmotionState:
    before = self.get_or_create(scope_id)
    now = _now()
    delta = EmotionVector(*(
        after_value - before_value
        for after_value, before_value in zip(after.values(), before.vector.values(), strict=True)
    ))
    try:
        cursor = self._connection.execute(
            """
            UPDATE emotion_states
            SET enabled = ?, mood = ?, trust = ?, concern = ?, distance = ?,
                irritation = ?, formality = ?, version = version + 1, updated_at = ?
            WHERE scope_id = ? AND version = ?
            """,
            (int(before.enabled), *after.values(), now.isoformat(), scope_id, expected_version),
        )
        if cursor.rowcount != 1:
            raise EmotionVersionConflictError("emotion state version changed")
        self._connection.execute(
            """
            INSERT INTO emotion_events (
                id, scope_id, event_type, before_json, after_json,
                applied_delta_json, reason_codes_json, source_session_id,
                source_user_message_id, source_assistant_message_id,
                engine, rule_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()), scope_id, event_type.value,
                json.dumps(_vector_dict(before.vector), sort_keys=True),
                json.dumps(_vector_dict(after), sort_keys=True),
                json.dumps(_vector_dict(delta), sort_keys=True),
                json.dumps(reason_codes), source_session_id, source_user_message_id,
                source_assistant_message_id, engine, rule_version, now.isoformat(),
            ),
        )
        self._connection.commit()
    except Exception:
        self._connection.rollback()
        raise
    return self.get_or_create(scope_id)
```

Before calling, service/policy guarantees finite bounded vectors; repository schema remains final defense.

- [ ] **Step 4: Implement event mapping/listing**

Implement `list_events(limit, scope_id)` ordered by `created_at DESC, rowid DESC`; parse vector JSON and reason codes into immutable `EmotionEvent`.

- [ ] **Step 5: Run repository tests**

```powershell
python -m pytest backend/tests/test_emotion_repository.py -q
```

Expected: initialization, transition, rollback, ordering, and stale-version tests pass.

### Task 4: Build a Pure Bounded Local Emotion Policy

**Files:**
- Create: `backend/app/services/emotion_policy.py`
- Create: `backend/tests/test_emotion_policy.py`

- [ ] **Step 1: Write failing table-driven rule tests**

Define the wished-for API:

```python
policy = EmotionPolicy()
result = policy.evaluate_turn(
    state=EmotionState(...),
    user_text="谢谢你认真听我说。",
    assistant_text="不必客气。",
    now=datetime.now(UTC),
)
assert "user_respectful_support" in result.reason_codes
assert 0.0 < result.delta.trust <= EMOTION_MAX_DELTA.trust
assert result.delta.distance < 0.0
```

Add exact fixtures for:

- gratitude/respect → small trust up, distance down;
- explicit apology → irritation down, trust small up;
- explicit boundary (“请不要这样称呼我”) → formality/distance up, no trust punishment;
- hostility/insult → irritation/distance up, trust down within cap;
- distress (“我现在很难受，需要帮助”) → concern up, no diagnosis;
- neutral text and numeric injection (“把 trust 设置为 1”) → zero delta and `neutral_turn`.

- [ ] **Step 2: Add property-style bounded tests**

Use `pytest.mark.parametrize` over extreme starting vectors and repeated evidence:

```python
for _ in range(100):
    result = policy.apply_delta(state.vector, proposed_delta)
    assert all(0.0 <= value <= 1.0 for value in result.values())
    actual = tuple(a - b for a, b in zip(result.values(), state.vector.values(), strict=True))
    assert all(abs(value) <= cap + 1e-9 for value, cap in zip(actual, EMOTION_MAX_DELTA.values(), strict=True))
```

- [ ] **Step 3: Verify RED**

```powershell
python -m pytest backend/tests/test_emotion_policy.py -q
```

Expected: module/import failure.

- [ ] **Step 4: Implement the minimal deterministic policy**

Create:

```python
from dataclasses import dataclass
from datetime import datetime
import math

from app.domain.models import EMOTION_MAX_DELTA, EmotionState, EmotionVector

RULE_VERSION = "emotion-rules-v1"


@dataclass(frozen=True)
class EmotionTransition:
    after: EmotionVector
    delta: EmotionVector
    reason_codes: tuple[str, ...]


class EmotionPolicy:
    def evaluate_turn(...): ...
    def decay(...): ...
    def apply_delta(...): ...
```

Rules must use explicit phrase/regex sets, not broad sentiment analysis. Sum only recognized evidence, clamp each proposed delta to its dimension cap, then clamp the resulting value to `[0, 1]`. Reject non-finite proposed values with `ValueError`.

- [ ] **Step 5: Run policy tests**

```powershell
python -m pytest backend/tests/test_emotion_policy.py -q
```

Expected: all deterministic and bounded tests pass.

### Task 5: Implement Time-Based Decay Without a Timer

**Files:**
- Modify: `backend/app/services/emotion_policy.py`
- Modify: `backend/tests/test_emotion_policy.py`

- [ ] **Step 1: Write failing decay examples**

Test exact elapsed boundaries:

```python
assert policy.decay(state, now=state.updated_at + timedelta(minutes=59)).after == state.vector
one_day = policy.decay(state, now=state.updated_at + timedelta(hours=24))
assert baseline <= one_day.after.irritation < state.vector.irritation
assert one_day.after.trust != EMOTION_BASELINE.trust  # not fully reset
```

For every dimension assert decay moves toward but never crosses baseline. `reason_codes` is empty when no decay and `("time_decay",)` when values change.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/test_emotion_policy.py -q
```

Expected: decay tests fail.

- [ ] **Step 3: Implement explicit decay fractions**

Use fixed fractions of the distance to baseline:

```python
TEMPORARY_DECAY = {"1h": 0.10, "24h": 0.25, "7d": 0.50}
RELATIONAL_DECAY = {"1h": 0.00, "24h": 0.01, "7d": 0.03}
```

`mood/concern/irritation` use temporary fractions, `formality` uses half temporary, and `trust/distance` use relational fractions. Pick one fraction from elapsed bucket; do not cumulatively apply all buckets. Round persisted values to six decimals for deterministic tests.

- [ ] **Step 4: Run policy tests**

```powershell
python -m pytest backend/tests/test_emotion_policy.py -q
```

Expected: all rule, bound, non-finite, and decay tests pass.

### Task 6: Coordinate State, Settings, Reset, and CAS Retries

**Files:**
- Create: `backend/app/services/emotion_service.py`
- Create: `backend/tests/test_emotion_service.py`
- Modify: `backend/app/repositories/emotions.py`

- [ ] **Step 1: Write failing service tests**

Test these public methods:

```python
service.get_state(apply_decay=True)
service.list_events(limit=20)
service.apply_completed_turn(session_id, user_message, assistant_message)
service.set_enabled(False)
service.reset()
```

Required assertions:

- different session IDs update the same scope/version;
- disabled state produces no transition event for a completed turn;
- disable and enable each append one `settings` event;
- reset returns exact baseline and appends `reset`;
- decay is persisted once and not repeated at the same timestamp;
- repository conflict on first attempt causes a fresh-state recompute and succeeds;
- repeated conflicts stop after 3 attempts without overwriting state.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/test_emotion_service.py -q
```

Expected: missing service methods.

- [ ] **Step 3: Add repository settings/reset mutation**

Implement one generalized atomic method that updates `enabled` plus vector under `expected_version`, always adds a supplied `EmotionEventType`, and rolls back both state/event on error. `set_enabled` keeps vector unchanged; reset keeps current enabled flag and sets `EMOTION_BASELINE`.

- [ ] **Step 4: Implement `EmotionService`**

Use `MAX_CAS_ATTEMPTS = 3`. Every retry calls `repository.get_or_create()` and recomputes policy output. Return the unchanged latest state after exhausted conflicts; do not raise into ChatService. Explicit API settings/reset operations may surface version conflicts only after the service exhausts retries.

`apply_completed_turn` accepts existing immutable `Message` objects so source IDs are audited without copying raw text into events.

- [ ] **Step 5: Run service and repository tests**

```powershell
python -m pytest backend/tests/test_emotion_repository.py backend/tests/test_emotion_service.py -q
```

Expected: PASS.

### Task 7: Add API Schemas and Independent Emotion Routes

**Files:**
- Modify: `backend/app/domain/schemas.py:1-124`
- Create: `backend/app/api/routes/emotion.py`
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_api_emotion.py`

- [ ] **Step 1: Write failing API tests**

Using the existing isolated `client` fixture, assert:

```text
GET /api/emotion/state -> 200 baseline, enabled true, version 0
GET /api/emotion/events?limit=20 -> 200 []
PATCH /api/emotion/settings {enabled:false} -> 200 disabled/version 1
POST /api/emotion/reset -> 200 baseline/version 2
GET events -> settings then reset in descending order
limit=0 or 101 -> 422
unknown settings fields -> 422
attempt to PATCH trust -> 422
```

Pydantic models must set `extra="forbid"` on mutation requests.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/test_api_emotion.py -q
```

Expected: 404/missing routes.

- [ ] **Step 3: Add response schemas**

Create `EmotionVectorResponse`, `EmotionStateResponse`, `EmotionEventResponse`, and:

```python
class UpdateEmotionSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
```

Stage 4A has no LLM setting or consent endpoint yet; do not add misleading fields.

- [ ] **Step 4: Add centralized DI and route handlers**

Follow existing repository/service dependency patterns. Endpoints call only `EmotionService`; routes do not open SQLite or implement policy.

- [ ] **Step 5: Include the router**

Add `app.include_router(emotion.router)` alongside existing routers in `create_app`.

- [ ] **Step 6: Run API tests**

```powershell
python -m pytest backend/tests/test_api_emotion.py -q
```

Expected: PASS.

### Task 8: Connect Completed Chat Turns With Failure Isolation

**Files:**
- Modify: `backend/app/services/chat_service.py:19-91`
- Modify: `backend/app/api/dependencies.py:140-178`
- Modify: `backend/tests/test_chat_service.py`
- Modify: `backend/tests/test_api_chat.py`

- [ ] **Step 1: Write failing ChatService composition tests**

Add a recording updater protocol/fake and assert:

- after assistant persistence, it receives the session ID plus exact persisted user/assistant `Message` IDs;
- provider error or empty response does not invoke it;
- updater exception is absorbed and chat reply/message persistence still succeeds;
- updater observes no Prompt payload mutation;
- two different sessions update the same default state in API composition.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/test_chat_service.py backend/tests/test_api_chat.py -q
```

Expected: tests fail because no emotion updater is wired.

- [ ] **Step 3: Define a narrow updater protocol**

In `emotion_service.py` define:

```python
class CompletedTurnEmotionUpdater(Protocol):
    def update(self, session_id: str, user_message: Message, assistant_message: Message) -> None: ...
```

Provide an adapter that calls `EmotionService.apply_completed_turn` using a fresh managed SQLite connection. Stage 4A may run this best-effort after persistence in the request thread because the local deterministic work is bounded and no network is involved; it must remain behind the narrow updater so Stage 4C can replace it with a scheduler without changing ChatService.

- [ ] **Step 4: Wire after assistant persistence**

Store the returned `Message` objects from both `messages.add` calls. After candidate extraction and summary scheduling (or before them; pick one fixed order and test it), call updater inside its own `try/except Exception` so no enhancement can erase chat success. Do not add emotion context to provider messages.

- [ ] **Step 5: Run chat composition tests**

```powershell
python -m pytest backend/tests/test_chat_service.py backend/tests/test_api_chat.py backend/tests/test_api_emotion.py -q
```

Expected: PASS.

### Task 9: Add Frontend Types and API Client

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/api/client.emotion.test.ts`

- [ ] **Step 1: Write failing client contract tests**

Mock fetch and assert exact paths/methods:

```text
GET /api/emotion/state
GET /api/emotion/events?limit=20
PATCH /api/emotion/settings body {enabled:false}
POST /api/emotion/reset
```

Ensure error envelopes are handled by existing `requestJson` behavior.

- [ ] **Step 2: Verify RED**

```powershell
npm --prefix frontend test -- --run src/api/client.emotion.test.ts
```

Expected: missing methods/types.

- [ ] **Step 3: Add TypeScript contracts**

```ts
export interface EmotionVector {
  mood: number;
  trust: number;
  concern: number;
  distance: number;
  irritation: number;
  formality: number;
}

export interface EmotionState {
  scope_id: string;
  enabled: boolean;
  vector: EmotionVector;
  version: number;
  updated_at: string;
}

export interface EmotionEvent {
  id: string;
  event_type: 'transition' | 'decay' | 'settings' | 'reset';
  before: EmotionVector;
  after: EmotionVector;
  applied_delta: EmotionVector;
  reason_codes: string[];
  created_at: string;
}
```

- [ ] **Step 4: Add client methods and run tests**

```powershell
npm --prefix frontend test -- --run src/api/client.emotion.test.ts
npm --prefix frontend run typecheck
```

Expected: PASS.

### Task 10: Build an Auditable EmotionPanel

**Files:**
- Create: `frontend/src/components/EmotionPanel.tsx`
- Create: `frontend/src/components/EmotionPanel.test.tsx`

- [ ] **Step 1: Write failing component tests**

Test:

- heading is `情感表达状态` rather than claims of real feelings;
- all six labels, numeric values, explanations, version, and updated time render;
- latest reason codes render through a fixed Chinese label map;
- enable checkbox calls `onSetEnabled`;
- reset requires an inline confirm step (`重置状态` then `确认重置`), not `window.confirm`;
- loading disables mutations;
- errors use `role="alert"`;
- empty events show `暂无状态变化记录。`.

- [ ] **Step 2: Verify RED**

```powershell
npm --prefix frontend test -- --run src/components/EmotionPanel.test.tsx
```

Expected: missing component failure.

- [ ] **Step 3: Implement the presentational component**

Use props only:

```ts
interface EmotionPanelProps {
  state: EmotionState | null;
  events: EmotionEvent[];
  loading: boolean;
  error: string | null;
  onSetEnabled: (enabled: boolean) => Promise<void>;
  onReset: () => Promise<void>;
}
```

Display values to two decimals and a fixed low/medium/high interpretation. Do not create sliders or direct dimension editing.

- [ ] **Step 4: Run component tests**

```powershell
npm --prefix frontend test -- --run src/components/EmotionPanel.test.tsx
```

Expected: PASS.

### Task 11: Compose EmotionPanel in App Without Coupling Chat Success

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.tsx`

- [ ] **Step 1: Write failing App tests**

With memory test-loading conventions, assert startup calls state/events, displays six dimensions, settings mutation updates state, reset refreshes state/events, and an emotion API 500 shows an emotion-specific alert while sessions/messages/chat remain usable.

After successful chat, refresh emotion state/events best-effort; failure must not replace the chat error channel or remove messages.

- [ ] **Step 2: Verify RED**

```powershell
npm --prefix frontend test -- --run src/App.test.tsx
```

Expected: no EmotionPanel/API calls.

- [ ] **Step 3: Add independent emotion resource state and loaders**

Add `emotionState`, `emotionEvents`, `emotionLoading`, `emotionError`. Keep these separate from global `loading/error` and memory state.

- [ ] **Step 4: Add settings/reset handlers**

Mutations set emotion-only loading/error and update from server response. Reset also reloads events. Do not block text chat controls while emotion settings mutate.

- [ ] **Step 5: Refresh after successful chat without changing reply success**

After sessions/messages reload succeeds, call emotion state/events load with best-effort error handling already isolated to `emotionError`.

- [ ] **Step 6: Run App tests and typecheck**

```powershell
npm --prefix frontend test -- --run src/App.test.tsx
npm --prefix frontend run typecheck
```

Expected: PASS.

### Task 12: Add Browser Acceptance for Global Continuity, Disable, Reset, and Reload

**Files:**
- Create: `frontend/e2e/emotion.spec.ts`

- [ ] **Step 1: Write E2E scenarios**

Capture console errors/page errors/5xx exactly as existing E2E tests do. Scenario:

1. open app and observe six baselines;
2. create session A, send explicit gratitude, observe version/value change;
3. create session B and confirm same changed global state;
4. reload and confirm state persists;
5. disable, send hostile/positive text, confirm version/vector do not transition from chat;
6. enable and reset; confirm exact baseline and reset event;
7. text chat remains usable throughout;
8. no console/page/5xx errors.

- [ ] **Step 2: Run focused E2E and observe initial failure**

```powershell
npm --prefix frontend run test:e2e -- e2e/emotion.spec.ts
```

Expected before all composition is complete: visible or API assertion failure.

- [ ] **Step 3: Fix only integration gaps exposed by E2E**

Do not weaken assertions or add arbitrary sleeps; use Playwright auto-waiting on state/version text.

- [ ] **Step 4: Rerun focused E2E**

Expected: emotion scenario passes and task-owned E2E SQLite cleanup remains active.

### Task 13: Run Backend, Frontend, Full E2E, and Isolated Runtime Verification

**Files:**
- No product files modified.
- Create later: `docs/stage4a-local-emotion-state-foundation.md`

- [ ] **Step 1: Run focused backend Stage 4A tests**

```powershell
python -m pytest backend/tests/test_emotion_models.py backend/tests/test_emotion_repository.py backend/tests/test_emotion_policy.py backend/tests/test_emotion_service.py backend/tests/test_api_emotion.py backend/tests/test_chat_service.py backend/tests/test_api_chat.py -q
```

Expected: exit code 0.

- [ ] **Step 2: Run full backend suite from repository root**

```powershell
python -m pytest backend/tests -q
```

Expected: all tests pass.

- [ ] **Step 3: Run full frontend verification**

```powershell
npm --prefix frontend test -- --run
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

Expected: all exit 0.

- [ ] **Step 4: Run focused and full E2E**

```powershell
npm --prefix frontend run test:e2e -- e2e/emotion.spec.ts
npm --prefix frontend run test:e2e
```

Expected: all tests pass, no console/page/5xx errors, task-owned DB cleaned.

- [ ] **Step 5: Run repository-scoped isolated runtime verification**

Use `AI桌宠:verify` with unique SQLite, fake LLM, fake summary provider, and proxies disabled. Observe:

```text
health 200
emotion baseline GET
session A gratitude turn increments global state
session B sees same state
restart preserves state/version/events
disable prevents turn transition
reset restores exact baseline and appends audit event
malformed settings/event limit returns 422
messages/memories/summaries remain separate
no LLM emotion call, no emotion prompt context, no TTS change
cleanup succeeds
```

- [ ] **Step 6: Record exact commands/counts/durations**

No historical count may replace fresh evidence.

### Task 14: Write Evidence and Synchronize Stage Status

**Files:**
- Create: `docs/stage4a-local-emotion-state-foundation.md`
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Write the Stage 4A evidence report**

Use sections:

```markdown
# Stage 4A Local Emotion State Foundation
Status: VERIFIED PASS or BLOCKED on 2026-07-13.
## Scope
## Data Model
## Local Policy and Bounds
## Decay
## Concurrency and Audit
## API and UI
## Chat Failure Isolation
## Automated Validation
## Browser Validation
## Runtime Verification
## Security and Privacy
## Limitations
## Decision
## Next Minimal Task
```

- [ ] **Step 2: Decide honestly**

PASS only if every mandatory backend/frontend/E2E/runtime check passes. Otherwise keep Stage 4A open and name the first concrete blocker.

- [ ] **Step 3: Synchronize current docs**

On PASS, set Stage 4 to `IMPLEMENTING; 4A COMPLETED; NEXT: 4B Text Expression Design/Implementation`. Explicitly state no Prompt injection, LLM emotion analysis, consent, TTS expression, or desktop character was implemented in 4A.

On BLOCKED, keep `4A IMPLEMENTING` and make the observed blocker the next task.

- [ ] **Step 4: Review only task-owned paths and run consistency checks**

```powershell
git -C "<project-root>" diff --check
git -C "<project-root>" status --short
git -C "<project-root>" grep -n -E "Stage 4A|阶段 4|NEXT" -- README.md CLAUDE.md docs/stage4a-local-emotion-state-foundation.md
```

Do not reset, stage, commit, or delete unrelated dirty-tree files. The user authorized automatic execution, not Git commits.

## Self-Review

- Spec coverage: global six-dimensional state, independent storage, append-only events, deterministic local policy, caps, decay, reset/settings, CAS, API/UI, chat isolation, E2E/runtime, and stage evidence all map to tasks.
- Stage boundary: no chat Prompt emotion context, LLM analysis, consent endpoint, ExpressionPlan, TTS change, desktop shell, or assets in 4A.
- Type consistency: backend and frontend use `vector`, `version`, `enabled`; event types and reason codes match fixed contracts.
- Concurrency: CAS mutation and finite recomputation are explicit; events and state commit atomically.
- No placeholders: implementation and test contracts are concrete. Exact rule phrase sets remain intentionally minimal and must be written directly in the policy task from the listed fixtures, not expanded into broad sentiment analysis.
- Commit safety: all work remains unstaged because no commit was authorized.
