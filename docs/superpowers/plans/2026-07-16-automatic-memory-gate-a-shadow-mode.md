# Automatic Memory Gate A Shadow Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a backward-compatible, non-blocking Gate A automatic-memory foundation whose local Governor and independently consented extractor can run in shadow mode while persisting metadata-only outcomes and never changing active memories.

**Architecture:** Keep the existing candidate-confirmation path intact and select exactly one path per successful turn from `off`, `candidate_confirmation`, or `shadow_auto`; reject `auto_active` at configuration load. A lifespan-owned scheduler reserves idempotent jobs by persisted assistant-message ID, an extractor proposes transient structured data, and the local Governor classifies it before the repository atomically stores only job state and aggregate audit metadata. Remote extraction has a separate versioned consent record and a dispatch fence; no memory repository is injected into the shadow service, making active-memory mutation structurally unavailable in Gate A.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, SQLite, asyncio, existing provider-neutral `LLMProvider`, HTTPX/Anthropic adapters behind the current factory, pytest, pytest-asyncio.

---

## 0. Execution contract and frozen Gate A boundary

Execute all commands from `backend/` unless a step explicitly says “repository root”. Use test-first RED/GREEN cycles. Do not stage, commit, amend, push, or delete unrelated files: the user has not authorized Git writes. The “checkpoint” at the end of each task is a diff/test review, not a commit.

### Gate A includes

- compatible additive SQLite schema and migration coverage;
- a local Governor with explicit no-memory/deletion-intent handling, sensitive credential rejection, field/type/length validation, canonical-key normalization, and bounded decisions;
- mutually exclusive modes `off | candidate_confirmation | shadow_auto | auto_active`, with `auto_active` rejected during settings loading;
- extractor routes `none | local | fake | remote`;
- separate persisted remote-extraction consent, default `unknown`/not granted;
- one idempotent job per `(assistant_message.id, memory-shadow-schema-v1)`;
- metadata-only job/audit persistence;
- read-only job/audit endpoints as the minimum non-blocking failure visibility;
- scheduler shutdown and owned-provider closure;
- a localized repair of the pre-existing request-scoped chat-provider lifecycle leak.

### Gate A excludes

Do not add or implement active automatic writes, memory evidence/version chains, open-conflict persistence/resolution, deletion generations, tombstones, summary jobs or summary injection, Persona artifacts, relationship events/projections, frontend redesign, Electron, voice changes, character-asset import, or Live2D. Do not add `conflicted`, `deleted`, or `commitment` to the existing `memories` table in this Gate. Do not alter `MemoryRepository` or `ContextBuilder`.

### Frozen versions and budgets

| Setting / literal | Gate A value | Validation |
|---|---:|---|
| `MEMORY_AUTOMATION_MODE` | `candidate_confirmation` | one of the four modes; `auto_active` always raises |
| `MEMORY_EXTRACTOR_ROUTE` | `none` | `none | local | fake | remote` |
| `MEMORY_EXTRACTOR_PROVIDER` | `anthropic` | `anthropic | deepseek`; used only by the remote route |
| `MEMORY_EXTRACTOR_MODEL` | existing `LLM_MODEL` default | non-empty |
| `MEMORY_EXTRACTOR_MAX_TOKENS` | `512` | 64–2048 |
| `MEMORY_EXTRACTOR_TIMEOUT_SECONDS` | `15.0` | 1.0–60.0 |
| `MEMORY_EXTRACTOR_MAX_RETRIES` | `0` | exactly 0 in Gate A; no provider idempotency key exists |
| `MEMORY_EXTRACTOR_MAX_PROPOSALS` | `3` | 1–10 |
| `MEMORY_EXTRACTOR_MAX_PROPOSAL_CHARACTERS` | `200` | 20–500 |
| `MEMORY_EXTRACTOR_MAX_TOTAL_CHARACTERS` | `600` | 20–2000 and at least the single-proposal limit |
| disclosure version | `memory-extraction-disclosure-v1` | frozen literal in request schema and service |
| disclosed fields | `user_message`, `assistant_message` | exact ordered tuple; no history/database/memory payload |
| extraction schema | `memory-shadow-schema-v1` | frozen literal, part of idempotency key |
| Governor rules | `memory-governor-rules-v1` | frozen literal persisted in jobs/audits |

`candidate_confirmation` continues to obey existing `MEMORY_CANDIDATES_ENABLED` and `MEMORY_CANDIDATE_PROVIDER`; the new settings must not silently reinterpret or migrate those variables. Its existing heuristic/LLM extraction and pending-confirmation safety rules remain untouched in Gate A; the new Governor applies to the shadow path only. Deployment configuration is not consent. Setting route `remote` without a matching granted consent yields an explicit `skipped_no_consent` job and zero provider calls; it does not change the automation mode.

## 1. File structure

### New production files

- `backend/app/repositories/memory_automation.py` — consent, idempotent job, and append-only metadata audit persistence.
- `backend/app/services/memory_governor.py` — transient local proposal validation, sensitive-data rules, canonicalization, and aggregate decisions.
- `backend/app/services/memory_extractor.py` — extractor protocol, strict provider-neutral JSON parsing, conservative local extraction, deterministic fake extraction adapter, and provider-backed extraction.
- `backend/app/services/memory_extraction_dispatch.py` — memory-specific consent-mutation/remote-dispatch fence.
- `backend/app/services/memory_job_service.py` — job execution orchestration; deliberately has no `MemoryRepository` dependency.
- `backend/app/services/memory_job_scheduler.py` — non-blocking task ownership, recovery, and shutdown.

### Modified production files

- `.env.example` — document mode, route, budgets, and the consent/config distinction.
- `backend/app/core/config.py` — load and validate frozen Gate A settings; reject `auto_active`.
- `backend/app/domain/models.py` — memory-automation enums and immutable records.
- `backend/app/domain/schemas.py` — consent/job/audit response schemas and strict mutation request.
- `backend/app/repositories/sqlite.py` — additive tables, constraints, indexes, and migration entry point.
- `backend/app/providers/factory.py` — create fake or named extractor providers without weakening the existing named-provider contract.
- `backend/app/api/dependencies.py` — request-scoped automation repository, app-state scheduler/fence, and shared chat provider.
- `backend/app/api/routes/memories.py` — consent mutation plus read-only jobs/audits.
- `backend/app/services/chat_service.py` — exclusive post-turn mode routing with stable persisted IDs.
- `backend/app/main.py` — lifespan composition, recovery, shutdown ordering, provider closure.

### New test files

- `backend/tests/test_memory_governor.py`
- `backend/tests/test_memory_automation_repository.py`
- `backend/tests/test_memory_automation_migration.py`
- `backend/tests/test_memory_extractor.py`
- `backend/tests/test_memory_job_service.py`
- `backend/tests/test_memory_job_scheduler.py`
- `backend/tests/test_api_memory_automation.py`

### Modified test files

- `backend/tests/test_config.py`
- `backend/tests/test_chat_memory_candidates.py`
- `backend/tests/test_api_chat.py`
- `backend/tests/conftest.py`

---

## Task 1: Freeze modes, routes, budgets, and capability guard

**Files:**
- Modify: `.env.example`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_config.py`

- [ ] **Step 1: Add failing default and override tests**

Extend the autouse environment cleanup tuple with every `MEMORY_AUTOMATION_*`/`MEMORY_EXTRACTOR_*` name in the frozen table. Add these tests:

```python
def test_memory_automation_defaults_preserve_candidate_confirmation(monkeypatch):
    settings = load_settings()

    assert settings.memory_automation_mode == "candidate_confirmation"
    assert settings.memory_extractor_route == "none"
    assert settings.memory_extractor_provider == "anthropic"
    assert settings.memory_extractor_max_tokens == 512
    assert settings.memory_extractor_timeout_seconds == 15.0
    assert settings.memory_extractor_max_retries == 0
    assert settings.memory_extractor_max_proposals == 3
    assert settings.memory_extractor_max_proposal_characters == 200
    assert settings.memory_extractor_max_total_characters == 600


def test_memory_automation_accepts_shadow_fake_overrides(monkeypatch):
    monkeypatch.setenv("MEMORY_AUTOMATION_MODE", "shadow_auto")
    monkeypatch.setenv("MEMORY_EXTRACTOR_ROUTE", "fake")
    monkeypatch.setenv("MEMORY_EXTRACTOR_PROVIDER", "anthropic")
    monkeypatch.setenv("MEMORY_EXTRACTOR_MODEL", "memory-fixture-v1")
    monkeypatch.setenv("MEMORY_EXTRACTOR_MAX_TOKENS", "256")
    monkeypatch.setenv("MEMORY_EXTRACTOR_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("MEMORY_EXTRACTOR_MAX_RETRIES", "0")
    monkeypatch.setenv("MEMORY_EXTRACTOR_MAX_PROPOSALS", "2")
    monkeypatch.setenv("MEMORY_EXTRACTOR_MAX_PROPOSAL_CHARACTERS", "120")
    monkeypatch.setenv("MEMORY_EXTRACTOR_MAX_TOTAL_CHARACTERS", "240")

    settings = load_settings()

    assert settings.memory_automation_mode == "shadow_auto"
    assert settings.memory_extractor_route == "fake"
    assert settings.memory_extractor_provider == "anthropic"
    assert settings.memory_extractor_model == "memory-fixture-v1"
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```text
python -m pytest tests/test_config.py::test_memory_automation_defaults_preserve_candidate_confirmation tests/test_config.py::test_memory_automation_accepts_shadow_fake_overrides -q
```

Expected: both fail with `AttributeError: 'Settings' object has no attribute 'memory_automation_mode'`.

- [ ] **Step 3: Add the settings fields and exact loaders**

Add immutable fields to `Settings` and load them in `load_settings()` using the existing `_get_env`, `_get_int_env`, `_get_int_env_with_max`, and `_get_float_env` helpers plus explicit lower/upper-bound checks:

```python
memory_automation_mode: str = "candidate_confirmation"
memory_extractor_route: str = "none"
memory_extractor_provider: str = "anthropic"
memory_extractor_model: str = ""
memory_extractor_max_tokens: int = 512
memory_extractor_timeout_seconds: float = 15.0
memory_extractor_max_retries: int = 0
memory_extractor_max_proposals: int = 3
memory_extractor_max_proposal_characters: int = 200
memory_extractor_max_total_characters: int = 600
```

Use these exact validation rules before constructing `Settings`:

```python
memory_automation_mode = _get_env(
    "MEMORY_AUTOMATION_MODE", "candidate_confirmation"
).lower()
if memory_automation_mode not in {
    "off", "candidate_confirmation", "shadow_auto", "auto_active"
}:
    raise ValueError(
        "MEMORY_AUTOMATION_MODE must be one of: off, candidate_confirmation, shadow_auto, auto_active"
    )
if memory_automation_mode == "auto_active":
    raise ValueError("MEMORY_AUTOMATION_MODE=auto_active is unavailable before Gate B")

memory_extractor_route = _get_env("MEMORY_EXTRACTOR_ROUTE", "none").lower()
if memory_extractor_route not in {"none", "local", "fake", "remote"}:
    raise ValueError(
        "MEMORY_EXTRACTOR_ROUTE must be one of: none, local, fake, remote"
    )

memory_extractor_provider = _get_env("MEMORY_EXTRACTOR_PROVIDER", "anthropic").lower()
if memory_extractor_provider not in {"anthropic", "deepseek"}:
    raise ValueError(
        "MEMORY_EXTRACTOR_PROVIDER must be one of: anthropic, deepseek"
    )
```

Set `memory_extractor_model` to `MEMORY_EXTRACTOR_MODEL` when non-empty and otherwise to the already-loaded chat `model`. Validate numeric ranges from the frozen table and require total characters to be at least the per-proposal characters. Require `max_retries == 0` with error `MEMORY_EXTRACTOR_MAX_RETRIES must be 0 in Gate A`.

Do not require an API key merely because route is `remote`; application startup and no-consent shadow jobs remain available without credentials. Provider creation in Task 10 is conditional on route and configured credentials, while persisted consent remains the runtime disclosure authority. If a granted remote job has no configured provider, it ends explicitly as `skipped_no_extractor`, not semantic success.

- [ ] **Step 4: Add rejection and redaction tests**

Add parametrized cases for unknown mode/route/provider, every out-of-range budget, total less than single limit, retry `1`, and `auto_active`. Route `fake` remains valid while `MEMORY_EXTRACTOR_PROVIDER` names the dormant remote fallback (`anthropic` or `deepseek`); changing local/fake routing must not rewrite that provider choice. The capability-guard test must be exact:

```python
def test_gate_a_rejects_auto_active(monkeypatch):
    monkeypatch.setenv("MEMORY_AUTOMATION_MODE", "auto_active")

    with pytest.raises(
        ValueError,
        match="MEMORY_AUTOMATION_MODE=auto_active is unavailable before Gate B",
    ):
        load_settings()
```

Extend `Settings.redacted()` assertions so it includes mode, route, provider, model, and budgets but never includes any API key. A configured remote route must remain `remote` in `redacted()`; do not misreport it as consent.

- [ ] **Step 5: Document exact environment variables**

Replace no legacy candidate variables. Append:

```dotenv
# Gate A automatic-memory mode. auto_active is intentionally rejected until Gate B.
MEMORY_AUTOMATION_MODE=candidate_confirmation
# Extraction routing is independent from mode and from persisted remote consent.
# none = explicit skipped_no_extractor, local = conservative local rules,
# fake = deterministic development provider, remote = configured cloud provider.
MEMORY_EXTRACTOR_ROUTE=none
MEMORY_EXTRACTOR_PROVIDER=anthropic
# Empty inherits LLM_MODEL.
MEMORY_EXTRACTOR_MODEL=
MEMORY_EXTRACTOR_MAX_TOKENS=512
MEMORY_EXTRACTOR_TIMEOUT_SECONDS=15
# Gate A has no provider request idempotency key, so retries remain disabled.
MEMORY_EXTRACTOR_MAX_RETRIES=0
MEMORY_EXTRACTOR_MAX_PROPOSALS=3
MEMORY_EXTRACTOR_MAX_PROPOSAL_CHARACTERS=200
MEMORY_EXTRACTOR_MAX_TOTAL_CHARACTERS=600
# IMPORTANT: environment configuration is not remote-extraction consent.
# Consent is local, persisted, versioned, and managed through /api/memories/extraction/consent.
```

- [ ] **Step 6: Run configuration regression and review checkpoint**

Run `python -m pytest tests/test_config.py -q`.
Expected: all tests pass, including legacy candidate and Stage 4C configuration tests. Review `git diff -- .env.example backend/app/core/config.py backend/tests/test_config.py`; do not stage or commit.

---

## Task 2: Add Gate A domain records and strict API schemas

**Files:**
- Modify: `backend/app/domain/models.py`
- Modify: `backend/app/domain/schemas.py`
- Test: `backend/tests/test_api_memory_automation.py`

- [ ] **Step 1: Write failing enum and strict-request tests**

Create `tests/test_api_memory_automation.py` initially with domain/schema tests:

```python
import pytest
from pydantic import ValidationError

from app.domain.models import (
    MemoryAutomationMode,
    MemoryExtractionConsentStatus,
    MemoryGovernorDecision,
    MemoryJobStatus,
)
from app.domain.schemas import UpdateMemoryExtractionConsentRequest


def test_gate_a_domain_values_are_frozen():
    assert [item.value for item in MemoryAutomationMode] == [
        "off", "candidate_confirmation", "shadow_auto", "auto_active"
    ]
    assert [item.value for item in MemoryExtractionConsentStatus] == [
        "unknown", "granted", "declined", "revoked"
    ]
    assert [item.value for item in MemoryJobStatus] == [
        "pending", "running", "succeeded", "failed", "cancelled"
    ]
    assert [item.value for item in MemoryGovernorDecision] == [
        "create", "support", "supersede", "conflict", "reject", "no_change"
    ]


def test_memory_consent_mutation_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        UpdateMemoryExtractionConsentRequest.model_validate(
            {
                "action": "grant",
                "disclosure_version": "memory-extraction-disclosure-v1",
                "provider": "anthropic",
            }
        )
```

- [ ] **Step 2: Confirm RED**

Run `python -m pytest tests/test_api_memory_automation.py -q`.
Expected: collection error `ImportError: cannot import name 'MemoryAutomationMode'`.

- [ ] **Step 3: Add exact enums and immutable records**

Add to `domain/models.py` using the existing `StrEnum`, frozen dataclass, UUID, and UTC timestamp conventions:

```python
class MemoryAutomationMode(StrEnum):
    OFF = "off"
    CANDIDATE_CONFIRMATION = "candidate_confirmation"
    SHADOW_AUTO = "shadow_auto"
    AUTO_ACTIVE = "auto_active"


class MemoryExtractorRoute(StrEnum):
    NONE = "none"
    LOCAL = "local"
    FAKE = "fake"
    REMOTE = "remote"


class MemoryExtractionConsentStatus(StrEnum):
    UNKNOWN = "unknown"
    GRANTED = "granted"
    DECLINED = "declined"
    REVOKED = "revoked"


class MemoryJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MemoryGovernorDecision(StrEnum):
    CREATE = "create"
    SUPPORT = "support"
    SUPERSEDE = "supersede"
    CONFLICT = "conflict"
    REJECT = "reject"
    NO_CHANGE = "no_change"


class MemoryJobAuditOutcome(StrEnum):
    SHADOW_RECORDED = "shadow_recorded"
    SKIPPED_NO_EXTRACTOR = "skipped_no_extractor"
    SKIPPED_NO_CONSENT = "skipped_no_consent"
    SKIPPED_CONSENT_CHANGED = "skipped_consent_changed"
    SKIPPED_GOVERNOR_POLICY = "skipped_governor_policy"
    INVALID_OUTPUT = "invalid_output"
    PROVIDER_ERROR = "provider_error"
    CANCELLED = "cancelled"
    FAILED = "failed"
```

Add these signatures; fields named `content`, `prompt`, `response`, `user_text`, or `assistant_text` are forbidden in the three persisted records:

```python
@dataclass(frozen=True)
class MemoryExtractionConsent:
    scope_id: str
    status: MemoryExtractionConsentStatus
    purpose: str | None
    provider: str | None
    disclosure_version: str | None
    disclosed_fields: tuple[str, ...]
    generation: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class MemoryJob:
    id: str
    turn_id: str
    schema_version: str
    session_id: str
    user_message_id: str
    assistant_message_id: str
    mode: MemoryAutomationMode
    extractor_route: MemoryExtractorRoute
    status: MemoryJobStatus
    attempt_count: int
    outcome: MemoryJobAuditOutcome | None
    error_category: str | None
    governor_version: str
    consent_generation: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True)
class MemoryJobAudit:
    id: str
    job_id: str
    outcome: MemoryJobAuditOutcome
    decision_counts: dict[str, int]
    reason_counts: dict[str, int]
    proposal_count: int
    accepted_count: int
    rejected_count: int
    redaction_count: int
    provider: str | None
    model: str | None
    elapsed_ms: int | None
    schema_version: str
    governor_version: str
    consent_generation: int | None
    created_at: datetime


@dataclass(frozen=True)
class MemoryGovernorProposal:
    memory_type: MemoryType
    subject: str
    content: str
    canonical_key_hint: str | None
    confidence: float
    source_message_ids: tuple[str, ...]


@dataclass(frozen=True)
class MemoryGovernorResult:
    decision: MemoryGovernorDecision
    reason_code: str
    canonical_key: str | None
    confidence: float
    redaction_count: int
```

`MemoryGovernorProposal` and `MemoryGovernorResult` are transient service values and are never serialized into job/audit tables.

- [ ] **Step 4: Add exact request/response schemas**

Add to `domain/schemas.py`:

```python
class UpdateMemoryExtractionConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["grant", "decline", "revoke"]
    disclosure_version: Literal["memory-extraction-disclosure-v1"]


class MemoryExtractionConsentResponse(BaseModel):
    scope_id: str
    status: str
    purpose: str | None
    provider: str | None
    disclosure_version: str | None
    disclosed_fields: list[str]
    generation: int
    deployment_route: str
    deployment_provider: str
    deployment_configured: bool
    created_at: datetime
    updated_at: datetime


class MemoryJobResponse(BaseModel):
    id: str
    turn_id: str
    schema_version: str
    session_id: str
    user_message_id: str
    assistant_message_id: str
    mode: str
    extractor_route: str
    status: str
    attempt_count: int
    outcome: str | None
    error_category: str | None
    governor_version: str
    consent_generation: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class MemoryJobAuditResponse(BaseModel):
    id: str
    job_id: str
    outcome: str
    decision_counts: dict[str, int]
    reason_counts: dict[str, int]
    proposal_count: int
    accepted_count: int
    rejected_count: int
    redaction_count: int
    provider: str | None
    model: str | None
    elapsed_ms: int | None
    schema_version: str
    governor_version: str
    consent_generation: int | None
    created_at: datetime
```

- [ ] **Step 5: Run focused tests and checkpoint**

Run `python -m pytest tests/test_api_memory_automation.py -q`.
Expected: the two domain/schema tests pass. Review imports for unused names and ensure none of the response schemas exposes proposal bodies or raw Provider output.

---

## Task 3: Add compatible SQLite tables and migration proof

**Files:**
- Modify: `backend/app/repositories/sqlite.py`
- Create: `backend/tests/test_memory_automation_migration.py`
- Test: `backend/tests/test_repositories.py`

- [ ] **Step 1: Write a legacy-database migration test**

Create a temporary SQLite database using the pre-Gate-A table definitions required by existing repositories, insert one active and one pending legacy memory, call `init_db()`, then assert both rows are byte-for-byte unchanged and the new tables exist. The core assertions are:

```python
def test_init_db_adds_gate_a_tables_without_changing_legacy_memories(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    connection = connect(database_url)
    create_pre_gate_a_schema(connection)
    insert_pre_gate_a_memory_rows(connection)
    before = connection.execute(
        "SELECT id, content, source, status, metadata_json FROM memories ORDER BY id"
    ).fetchall()

    init_db(connection)

    after = connection.execute(
        "SELECT id, content, source, status, metadata_json FROM memories ORDER BY id"
    ).fetchall()
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert after == before
    assert {
        "memory_extraction_consents", "memory_jobs", "memory_job_audits"
    } <= tables
```

Copy the exact pre-Gate-A `memories`, `sessions`, and `messages` DDL from the current migration fixture in the repository rather than inventing a reduced incompatible shape. Keep the fixture helper inside this test file.

- [ ] **Step 2: Confirm RED**

Run `python -m pytest tests/test_memory_automation_migration.py -q`.
Expected: fail because the three new table names are absent.

- [ ] **Step 3: Add additive DDL with exact constraints**

In `init_db()`, create:

```sql
CREATE TABLE IF NOT EXISTS memory_extraction_consents (
    scope_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('unknown', 'granted', 'declined', 'revoked')),
    purpose TEXT,
    provider TEXT,
    disclosure_version TEXT,
    disclosed_fields_json TEXT NOT NULL DEFAULT '[]',
    generation INTEGER NOT NULL CHECK (generation >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_jobs (
    id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    session_id TEXT NOT NULL,
    user_message_id TEXT NOT NULL,
    assistant_message_id TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode = 'shadow_auto'),
    extractor_route TEXT NOT NULL CHECK (extractor_route IN ('none', 'local', 'fake', 'remote')),
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    outcome TEXT CHECK (outcome IS NULL OR outcome IN (
        'shadow_recorded', 'skipped_no_extractor', 'skipped_no_consent',
        'skipped_consent_changed', 'skipped_governor_policy',
        'invalid_output', 'provider_error', 'cancelled', 'failed'
    )),
    error_category TEXT CHECK (error_category IS NULL OR error_category IN (
        'invalid_output', 'provider_error', 'invalid_job_input',
        'interrupted', 'database_error'
    )),
    governor_version TEXT NOT NULL,
    consent_generation INTEGER,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    UNIQUE(turn_id, schema_version),
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY(user_message_id) REFERENCES messages(id) ON DELETE CASCADE,
    FOREIGN KEY(assistant_message_id) REFERENCES messages(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS memory_job_audits (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN (
        'shadow_recorded', 'skipped_no_extractor', 'skipped_no_consent',
        'skipped_consent_changed', 'skipped_governor_policy',
        'invalid_output', 'provider_error', 'cancelled', 'failed'
    )),
    decision_counts_json TEXT NOT NULL,
    reason_counts_json TEXT NOT NULL,
    proposal_count INTEGER NOT NULL CHECK (proposal_count >= 0),
    accepted_count INTEGER NOT NULL CHECK (accepted_count >= 0),
    rejected_count INTEGER NOT NULL CHECK (rejected_count >= 0),
    redaction_count INTEGER NOT NULL CHECK (redaction_count >= 0),
    provider TEXT,
    model TEXT,
    elapsed_ms INTEGER CHECK (elapsed_ms IS NULL OR elapsed_ms >= 0),
    schema_version TEXT NOT NULL,
    governor_version TEXT NOT NULL,
    consent_generation INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY(job_id) REFERENCES memory_jobs(id) ON DELETE CASCADE,
    UNIQUE(job_id)
);

CREATE INDEX IF NOT EXISTS idx_memory_jobs_created_at
    ON memory_jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_job_audits_created_at
    ON memory_job_audits(created_at DESC);
```

Do not alter existing `memories` constraints. Use the existing `init_db()` transaction behavior so failure rolls back instead of leaving a partial schema.

- [ ] **Step 4: Add schema privacy and constraint tests**

Assert `PRAGMA table_info` for all three tables has no normalized column name in this exact forbidden set:

```python
FORBIDDEN_COLUMNS = {
    "candidate_content", "content", "prompt", "prompt_text", "response",
    "response_text", "user_text", "assistant_text", "credential",
    "credentials", "authorization", "authorization_header",
}
```

`memory_job_audits.outcome` has the same CHECK set as `memory_jobs.outcome`; `memory_jobs.error_category` accepts only the fixed categories in the DDL. Do not allow arbitrary strings through model-to-row conversion. Also test duplicate `(turn_id, schema_version)` and duplicate audit `job_id` raise `sqlite3.IntegrityError`, and `mode='auto_active'` raises `sqlite3.IntegrityError`. This database guard complements configuration validation.

- [ ] **Step 5: Run migration and repository regression**

Run:

```text
python -m pytest tests/test_memory_automation_migration.py tests/test_repositories.py -q
```

Expected: all pass; legacy active/pending/dismissed/archived semantics remain unchanged.

---

## Task 4: Implement consent, idempotent jobs, and metadata-only audits repository

**Files:**
- Create: `backend/app/repositories/memory_automation.py`
- Create: `backend/tests/test_memory_automation_repository.py`

- [ ] **Step 1: Write failing consent lifecycle tests**

Use a real SQLite file with one short `managed_connection` per repository operation. Test unknown default, grant, decline, revoke, and monotonic generation:

```python
def test_consent_defaults_unknown_and_mutations_increment_generation(repository):
    initial = repository.get_consent()
    assert initial.generation == 0
    assert initial.status is MemoryExtractionConsentStatus.UNKNOWN
    assert initial.purpose is None
    assert initial.provider is None
    assert initial.disclosure_version is None
    assert initial.disclosed_fields == ()
    assert initial.created_at == initial.updated_at

    granted = repository.set_consent(
        status=MemoryExtractionConsentStatus.GRANTED,
        purpose="extract durable memory proposals from the current completed turn",
        provider="anthropic",
        disclosure_version="memory-extraction-disclosure-v1",
        disclosed_fields=("user_message", "assistant_message"),
    )
    revoked = repository.set_consent(
        status=MemoryExtractionConsentStatus.REVOKED,
        purpose=granted.purpose,
        provider="anthropic",
        disclosure_version="memory-extraction-disclosure-v1",
        disclosed_fields=("user_message", "assistant_message"),
    )

    assert granted.generation == 1
    assert revoked.generation == 2
```

- [ ] **Step 2: Confirm repository RED**

Run `python -m pytest tests/test_memory_automation_repository.py -q`.
Expected: collection error for missing `app.repositories.memory_automation`.

- [ ] **Step 3: Implement repository API and transaction boundary**

Create:

```python
DEFAULT_MEMORY_EXTRACTION_SCOPE_ID = "default"

class MemoryAutomationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None: ...

    @contextmanager
    def transaction(self) -> Iterator[None]: ...

    def get_consent(
        self, scope_id: str = DEFAULT_MEMORY_EXTRACTION_SCOPE_ID
    ) -> MemoryExtractionConsent: ...

    def set_consent(
        self,
        *,
        status: MemoryExtractionConsentStatus,
        purpose: str,
        provider: str,
        disclosure_version: str,
        disclosed_fields: tuple[str, ...],
        scope_id: str = DEFAULT_MEMORY_EXTRACTION_SCOPE_ID,
    ) -> MemoryExtractionConsent: ...

    def reserve_job(
        self,
        *,
        turn_id: str,
        schema_version: str,
        session_id: str,
        user_message_id: str,
        assistant_message_id: str,
        mode: MemoryAutomationMode,
        extractor_route: MemoryExtractorRoute,
        governor_version: str,
    ) -> tuple[MemoryJob, bool]: ...

    def require_job(self, job_id: str) -> MemoryJob: ...

    def update_job_status(
        self,
        job_id: str,
        *,
        status: MemoryJobStatus,
        outcome: MemoryJobAuditOutcome | None = None,
        error_category: str | None = None,
        consent_generation: int | None = None,
    ) -> MemoryJob: ...

    def complete_job_with_audit(
        self,
        job_id: str,
        *,
        status: MemoryJobStatus,
        outcome: MemoryJobAuditOutcome,
        decision_counts: dict[str, int],
        reason_counts: dict[str, int],
        proposal_count: int,
        accepted_count: int,
        rejected_count: int,
        redaction_count: int,
        provider: str | None,
        model: str | None,
        elapsed_ms: int | None,
        consent_generation: int | None,
        error_category: str | None = None,
    ) -> tuple[MemoryJob, MemoryJobAudit]: ...

    def cancel_job(self, job_id: str) -> MemoryJob: ...

    def recover_incomplete_jobs(self) -> list[str]: ...
    def list_jobs(self, *, limit: int = 20) -> list[MemoryJob]: ...
    def list_audits(self, *, limit: int = 20) -> list[MemoryJobAudit]: ...
```

The default-unknown row is created lazily on first `get_consent()` with status `unknown`, null purpose/provider/version, disclosed fields `[]`, generation `0`, and equal non-null timestamps. Mutations upsert policy identity and increment generation atomically. Use `BEGIN IMMEDIATE`, commit, and rollback exactly like `EmotionAnalysisRepository`. `reserve_job()` must use `INSERT ... ON CONFLICT(turn_id, schema_version) DO NOTHING`, then select the existing row and return `(job, inserted_bool)`. Reject any mode other than `SHADOW_AUTO` in Python before SQL. Enforce transitions in repository code: `pending -> running|succeeded|failed|cancelled`, `running -> pending` only through recovery, and `running -> succeeded|failed|cancelled`; every terminal state is immutable. `update_job_status(...RUNNING...)` increments `attempt_count`, sets `started_at` once, and clears neither previous values nor consent generation. Terminal statuses set `finished_at`.

Before any terminal transition, `complete_job_with_audit()` re-selects the job inside `BEGIN IMMEDIATE`, rejects terminal rows without inserting another audit, and updates with `WHERE id = ? AND status IN ('pending','running')`; a zero row count causes rollback and returns the already-terminal row. This compare-and-set behavior makes concurrent duplicate runners converge on one terminal audit. `cancel_job()` uses the same function with `CANCELLED/cancelled`, zero counts, and fixed `error_category="interrupted"`; it is idempotent for already-terminal jobs. Serialize only sorted integer-count maps with `json.dumps(..., ensure_ascii=False, sort_keys=True)`. It must validate:

```python
if proposal_count != accepted_count + rejected_count:
    raise ValueError("proposal_count must equal accepted_count + rejected_count")
if sum(decision_counts.values()) != proposal_count:
    raise ValueError("decision counts must equal proposal_count")
if sum(reason_counts.values()) != proposal_count:
    raise ValueError("reason counts must equal proposal_count")
```

For skipped/failed outcomes with no proposals, all maps/counts are empty/zero and valid.

- [ ] **Step 4: Add idempotency, atomicity, recovery, and privacy tests**

Test that 20 sequential and two barrier-synchronized concurrent `reserve_job()` calls for the same turn return one ID and exactly one `created=True`; each concurrent call uses its own SQLite connection. Same turn with a new schema version creates a second job. Race two `complete_job_with_audit()` calls and assert one terminal row/audit without uncaught `IntegrityError`. Test `recover_incomplete_jobs()` changes `running` to `pending` without increasing attempts and returns the deterministic pending job IDs (created-at ascending, ID ascending) for scheduler recovery. Inject an invalid audit count and assert both audit insert and terminal job update roll back.

Persist a proposal containing `SECRET_SENTINEL_9f40`, a raw provider response containing `RAW_RESPONSE_SENTINEL_03c1`, and an exception string containing `sk-secret` only in test-local transient variables. Complete the job using aggregate metadata, then search every textual column from all three tables:

```python
persisted = "\n".join(
    str(value)
    for table in (
        "memory_extraction_consents", "memory_jobs", "memory_job_audits"
    )
    for row in connection.execute(f"SELECT * FROM {table}").fetchall()
    for value in row
)
assert "SECRET_SENTINEL_9f40" not in persisted
assert "RAW_RESPONSE_SENTINEL_03c1" not in persisted
assert "sk-secret" not in persisted
```

- [ ] **Step 5: Run repository tests**

Run `python -m pytest tests/test_memory_automation_repository.py tests/test_memory_automation_migration.py -q`.
Expected: all pass, including rollback and forbidden-text assertions.

---

## Task 5: Implement the local Memory Governor

**Files:**
- Create: `backend/app/services/memory_governor.py`
- Create: `backend/tests/test_memory_governor.py`

- [ ] **Step 1: Write the Governor decision matrix as failing tests**

Use exact proposals and expected reason codes:

| Input | Expected decision | Reason code |
|---|---|---|
| `我喜欢黑咖啡` / preference | create | `eligible_shadow_create` |
| source user text `不要记住，我喜欢黑咖啡` | reject | `explicit_no_memory` |
| source user text `忘掉我的咖啡偏好` | reject | `deletion_intent` |
| `我的密码是 swordfish` | reject | `sensitive_password` |
| `API key: sk-ant-test-1234567890` | reject | `sensitive_api_key` |
| `验证码 493821` | reject | `sensitive_verification_code` |
| PEM private-key marker | reject | `sensitive_private_key` |
| valid Luhn full card number | reject | `sensitive_payment_credential` |
| valid 18-character PRC identity number fixture | reject | `sensitive_identity_credential` |
| empty/whitespace content | reject | `invalid_content` |
| 201-character content | reject | `proposal_too_long` |
| confidence `1.2` | reject | `invalid_confidence` |
| assistant-only source ID | reject | `invalid_source` |

A representative test:

```python
def test_governor_rejects_explicit_no_memory_for_every_proposal(governor):
    result = governor.evaluate(
        proposal=proposal(content="我喜欢黑咖啡"),
        user_text="不要记住，我喜欢黑咖啡",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
    )

    assert result.decision is MemoryGovernorDecision.REJECT
    assert result.reason_code == "explicit_no_memory"
    assert result.canonical_key is None
```

- [ ] **Step 2: Confirm Governor RED**

Run `python -m pytest tests/test_memory_governor.py -q`.
Expected: collection error for missing `app.services.memory_governor`.

- [ ] **Step 3: Implement deterministic rules and signatures**

Create constants and class:

```python
MEMORY_GOVERNOR_VERSION = "memory-governor-rules-v1"

class MemoryGovernor:
    def __init__(
        self,
        *,
        max_proposals: int,
        max_proposal_characters: int,
        max_total_characters: int,
    ) -> None: ...

    def preflight_turn(
        self,
        *,
        user_text: str,
        assistant_text: str,
    ) -> MemoryGovernorResult | None: ...

    def evaluate_many(
        self,
        *,
        proposals: list[MemoryGovernorProposal],
        user_text: str,
        user_message_id: str,
        assistant_message_id: str,
    ) -> list[MemoryGovernorResult]: ...

    def evaluate(
        self,
        *,
        proposal: MemoryGovernorProposal,
        user_text: str,
        user_message_id: str,
        assistant_message_id: str,
    ) -> MemoryGovernorResult: ...
```

Normalize with Unicode NFKC, trim, collapse whitespace, lowercase ASCII, and produce a canonical key as:

```python
normalized_subject = _normalize(proposal.subject)
normalized_content = _normalize(proposal.content)
canonical_material = f"{proposal.memory_type.value}:{normalized_subject}:{normalized_content}"
canonical_key = hashlib.sha256(canonical_material.encode("utf-8")).hexdigest()
```

Do not persist `canonical_material` or proposal text. `preflight_turn()` runs before selecting or calling any extractor. It detects explicit no-memory/deletion intent against the local original `user_text` and scans both `user_text` and `assistant_text` for credential categories; on a match it returns a `REJECT` result with no canonical key, otherwise `None`. This guarantees “不要记住”、删除意图 and detected credentials are not newly disclosed to the remote memory-extraction Provider—even if the assistant echoed sensitive input. `evaluate()` applies the user-text policy and scans proposal content with the same helpers so local/fake/remote post-extraction behavior is identical. Match credential categories in this order: private key, API key, verification code, password, payment credential, identity credential. Use category-specific compiled regexes, plus a Luhn check for 13–19 digit payment candidates. Return the first category only and `redaction_count=1`; ordinary accepted proposals return zero.

Require `source_message_ids` to contain `user_message_id` and only IDs from `{user_message_id, assistant_message_id}`. The assistant message may support extraction context but can never be the sole source of a user fact. Allowed Gate A memory types are the existing six `MemoryType` values; do not extend the enum.

`evaluate_many()` truncates neither content nor lists. It rejects proposals beyond `max_proposals` with `proposal_budget_exceeded`; after accepted-order cumulative content exceeds total characters, reject with `turn_character_budget_exceeded`. This preserves auditable counts and prevents silent truncation.

- [ ] **Step 4: Add canonicalization, ordering, and budget tests**

Add preflight tests proving every no-memory/deletion/credential matrix case returns before extractor dispatch, including an assistant reply that echoes a credential absent from its own user fixture. Assert equivalent full-width/ASCII whitespace forms produce the same 64-character hash. Assert the first three eligible proposals are evaluated and proposal 4 is rejected by count budget. Assert cumulative lengths `200 + 200 + 200` pass at 600 and the next non-empty proposal is rejected. Assert Governor outputs contain no raw content field by checking `dataclasses.asdict(result)`.

Do not test `support`, `supersede`, or `conflict` persistence: Gate A merely freezes their enum values. Since there is no Gate B versioned-memory lookup, eligible proposals are classified as shadow `create`; claiming semantic support/conflict would be false.

- [ ] **Step 5: Run Governor tests**

Run `python -m pytest tests/test_memory_governor.py -q`.
Expected: all matrix, canonicalization, source, and budget tests pass.

---

## Task 6: Add strict transient extractors and remote disclosure payload

**Files:**
- Create: `backend/app/services/memory_extractor.py`
- Create: `backend/tests/test_memory_extractor.py`
- Test: `backend/tests/test_memory_candidate_service.py`

- [ ] **Step 1: Write failing strict parser tests**

Define a stub `LLMProvider` that records `messages/options` and returns `LLMResponse`. Cover valid JSON, markdown-fenced JSON rejection, unknown top-level/candidate keys, wrong types, unknown memory type, too many proposals, oversized content, source IDs outside the current turn, and malformed JSON. Valid response fixture:

```json
{
  "schema_version": "memory-shadow-schema-v1",
  "proposals": [
    {
      "memory_type": "preference",
      "subject": "饮品偏好",
      "content": "用户喜欢黑咖啡",
      "canonical_key_hint": "drink:coffee",
      "confidence": 0.91,
      "source_message_ids": ["user-1"]
    }
  ]
}
```

Assert the captured remote payload has exactly two disclosure labels and no history/memory database fields:

```python
payload = recording_provider.messages
assert [message.role.value for message in payload] == ["system", "user"]
assert "user_message" in payload[1].content
assert "assistant_message" in payload[1].content
assert "session_summary" not in payload[1].content
assert "active_memories" not in payload[1].content
```

- [ ] **Step 2: Confirm extractor RED**

Run `python -m pytest tests/test_memory_extractor.py -q`.
Expected: collection error for missing `app.services.memory_extractor`.

- [ ] **Step 3: Implement protocol, result, and explicit invalid-output error**

Create:

```python
MEMORY_EXTRACTION_SCHEMA_VERSION = "memory-shadow-schema-v1"

class MemoryExtractionInvalidOutputError(ValueError):
    pass


@dataclass(frozen=True)
class MemoryExtractionResult:
    proposals: list[MemoryGovernorProposal]
    provider: str
    model: str
    elapsed_ms: int


class MemoryExtractor(Protocol):
    async def extract(
        self,
        *,
        user_message: Message,
        assistant_message: Message,
    ) -> MemoryExtractionResult: ...
```

`ProviderMemoryExtractor.__init__(provider, settings)` uses existing `LLMOptions` with configured model, timeout, tokens, and retries. It performs one `LLMProvider.generate()` call and parses `response.text` locally. Do not import Anthropic, HTTPX, or DeepSeek code in this service. Use `json.loads(text)` directly; do not strip markdown fences or recover a JSON substring. Require the exact top-level key set `{schema_version, proposals}` and exact candidate key set `{memory_type, subject, content, canonical_key_hint, confidence, source_message_ids}` from the fixture, exact schema version, finite confidence in `[0,1]`, and bounded proposal count/characters. `canonical_key_hint` is validated as null or a string of at most 120 characters but remains untrusted and is ignored by `MemoryGovernor`, which derives the authoritative canonical hash locally. Never return or log raw response text on parse failure.

Build a system instruction that says proposals are untrusted suggestions, current-turn fields only, no hidden reasoning, and strict JSON. The user payload is JSON made only from:

```python
{
    "disclosure_version": "memory-extraction-disclosure-v1",
    "schema_version": "memory-shadow-schema-v1",
    "user_message": {"id": user_message.id, "content": user_message.content},
    "assistant_message": {
        "id": assistant_message.id,
        "content": assistant_message.content,
    },
}
```

No session ID, prior messages, summaries, active memories, metadata, API keys, or Authorization headers are included.

- [ ] **Step 4: Implement conservative local and fake routing behavior**

Add `LocalMemoryExtractor` that extracts only explicit first-person stable statements with these anchored patterns: `我叫...`, `我喜欢...`, `我不喜欢...`, `我的目标是...`, `我计划...`. It returns at most configured proposals, uses only the user message ID, and labels provider/model `local`/`memory-local-rules-v1`. It must return an empty proposal list rather than infer identity, diagnosis, relationship state, or facts from assistant text.

`MemoryExtractionFakeProvider` is a production development adapter implementing `LLMProvider`; it returns strict schema JSON derived only from the disclosed current user message using the same conservative first-person patterns as `LocalMemoryExtractor`. Add a separate recording stub in `tests/test_memory_extractor.py` for malformed/valid parser fixtures. Both fake and remote routes pass through `ProviderMemoryExtractor._parse_response()`, so strict parsing is exercised without changing general chat `FakeProvider` behavior. Do not hard-code a user-specific memory fixture in production.

- [ ] **Step 5: Run extractor and legacy candidate regressions**

Run:

```text
python -m pytest tests/test_memory_extractor.py tests/test_memory_candidate_service.py -q
```

Expected: all pass; existing pending-candidate extraction remains unchanged.

---

## Task 7: Fence consent races and execute metadata-only shadow jobs

**Files:**
- Create: `backend/app/services/memory_extraction_dispatch.py`
- Create: `backend/app/services/memory_job_service.py`
- Create: `backend/tests/test_memory_job_service.py`

- [ ] **Step 1: Write failing service tests for each route/outcome**

Construct the service with real repositories, persisted messages, a recording extractor, Governor, and memory-specific fence. Required tests:

1. `none` → `SUCCEEDED/skipped_no_extractor`, zero extractor calls.
2. `local` → no consent read requirement, `SUCCEEDED/shadow_recorded`.
3. `fake` → no remote consent requirement, `SUCCEEDED/shadow_recorded`.
4. `remote` + unknown/declined/revoked/mismatched provider/version/fields → `SUCCEEDED/skipped_no_consent`, zero calls. For unknown consent, assert the check uses null policy fields safely.
5. `remote` + matching grant → one call and metadata-only audit.
6. invalid JSON → `FAILED/invalid_output`, sanitized `error_category="invalid_output"`.
7. provider exception with secret-bearing message → `FAILED/provider_error`, `error_category="provider_error"`, secret absent from database and captured logs.
8. Governor preflight reject → `SUCCEEDED/skipped_governor_policy`, zero extractor calls for local/fake/remote, aggregate redaction count only, and no memory write.
9. Governor post-extraction reject → successful `shadow_recorded` audit with decision/reason counts, no memory write.
10. duplicate service execution of already-terminal job → returns existing job, no second extraction/audit.
11. missing/mismatched message/session IDs → `FAILED/failed`, category `invalid_job_input`, no raw text.

Structural assertion:

```python
assert "memories" not in inspect.signature(MemoryJobService.__init__).parameters
```

- [ ] **Step 2: Confirm service RED**

Run `python -m pytest tests/test_memory_job_service.py -q`.
Expected: import errors for the two missing service modules.

- [ ] **Step 3: Implement a memory-specific priority fence**

Mirror the proven Stage 4C pattern without reusing its emotion-named class:

```python
class MemoryExtractionDispatchFence:
    def __init__(self) -> None: ...
    def begin_consent_mutation(self) -> ConsentMutation: ...
    def has_pending_consent_mutation(self) -> bool: ...

    @asynccontextmanager
    async def hold(self) -> AsyncIterator[bool]: ...
```

`begin_consent_mutation()` synchronously marks a pending mutation before awaiting the dispatch lock and returns an async context manager that clears the marker on exit. `hold()` yields `False` without beginning a send when a mutation is pending; otherwise it owns the dispatch lock. This guarantees queued consent changes beat unsent work.

- [ ] **Step 4: Implement exact job-service boundary**

Create:

```python
class MemoryJobService:
    def __init__(
        self,
        *,
        automation: MemoryAutomationRepository,
        messages: MessageRepository,
        extractor: MemoryExtractor | None,
        governor: MemoryGovernor,
        route: MemoryExtractorRoute,
        provider_name: str,
        dispatch_fence: MemoryExtractionDispatchFence,
    ) -> None: ...

    async def process(self, job_id: str) -> MemoryJob: ...
```

Rules, in order:

1. Return terminal jobs unchanged; do not append another audit.
2. Load both persisted messages and verify session IDs, roles, and IDs against the job. Only after this validation may the job be marked running; invalid input is terminalized directly from pending as `FAILED/failed` with category `invalid_job_input`.
3. Mark the job `RUNNING` in a short transaction before any normal terminal skip, preflight, or extraction branch, so every valid executed attempt increments `attempt_count` consistently.
4. Run `governor.preflight_turn(user_text=..., assistant_text=...)` before consent checks, fence acquisition, or any local/fake/remote extractor call. A match completes `SUCCEEDED/skipped_governor_policy` with zero proposal/decision/reason counts, `redaction_count` from the preflight result, Provider/model null, and no transmission. The fixed preflight reason is intentionally not persisted because reason-level credential categories could reveal sensitive data; the aggregate outcome is sufficient.
5. Route `none`, or missing remote extractor due to absent credentials, completes `SUCCEEDED/skipped_no_extractor`; neither case calls a Provider or pretends semantic extraction succeeded.
6. For remote route, read consent and require status granted, purpose, provider, disclosure version, and exact disclosed fields.
7. Acquire the fence; immediately re-read the consent and generation before sending.
8. Call extractor outside any SQLite transaction.
9. After response, if a consent mutation is pending or generation/authority changed, discard transient proposals and complete `SUCCEEDED/skipped_consent_changed` with counts zero. Raw response/proposals are not audited.
10. Otherwise run `governor.evaluate_many()` locally, aggregate only decision and reason counts, and complete success/audit atomically.
11. Catch only `MemoryExtractionInvalidOutputError` as invalid output. Map any Provider exception to fixed category `provider_error`; map invalid job inputs to `invalid_job_input`. Never persist or log `str(exc)`.

Use `time.perf_counter()` only to derive integer elapsed milliseconds. The successful audit stores Provider/model identifiers, counts, versions, and consent generation; it stores neither proposal bodies nor canonical keys.

- [ ] **Step 5: Add two deterministic consent-race tests**

Race A — revoke before send: pause immediately before `hold()`, enter `begin_consent_mutation()`, resume the job, then revoke. Assert zero extractor calls and `skipped_no_consent` or `skipped_consent_changed` according to whether the initial check had completed.

Race B — revoke while request is in flight: recording extractor signals `started`, then waits. Start a revoke mutation (which sets the pending marker), release extractor response, and await both. Assert one remote call, no Governor evaluation, zero proposal counts in audit, `SUCCEEDED/skipped_consent_changed`, and consent status `REVOKED` with incremented generation.

Use `asyncio.Event`, not sleeps, so the tests are deterministic.

- [ ] **Step 6: Prove shadow mode cannot change memories**

Use a separate observation connection for the before/after snapshots; the service connection may be in a transaction and must not be reused as the oracle. Before and after successful, preflight-rejected, post-extraction-rejected, invalid, provider-failed, and consent-race jobs, query:

```sql
SELECT id, content, source, status, metadata_json, updated_at
FROM memories
ORDER BY id
```

Assert exact row equality. Include an existing active, pending, dismissed, and archived memory fixture. Also assert no calls are made to `MemoryRepository`; the service constructor has no such dependency.

- [ ] **Step 7: Run service tests**

Run `python -m pytest tests/test_memory_job_service.py tests/test_memory_governor.py tests/test_memory_extractor.py -q`.
Expected: all pass with no unhandled task warnings.

---

## Task 8: Add an idempotent non-blocking scheduler and exclusive chat routing

**Files:**
- Create: `backend/app/services/memory_job_scheduler.py`
- Create: `backend/tests/test_memory_job_scheduler.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/tests/test_chat_memory_candidates.py`
- Test: `backend/tests/test_chat_service.py`

- [ ] **Step 1: Write failing scheduler tests**

Required behavior:

```python
@pytest.mark.asyncio
async def test_schedule_reserves_once_and_returns_without_waiting(scheduler, service):
    service.release.clear()

    first = scheduler.schedule(
        session_id="session-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
    )
    duplicate = scheduler.schedule(
        session_id="session-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
    )

    assert first is True
    assert duplicate is False
    assert service.started.is_set()
    service.release.set()
    await scheduler.shutdown()
    assert service.calls == 1
```

Also test `recover()` requeues pending/interrupted jobs once, `shutdown()` waits for tasks, `shutdown(cancel=True)` cancels tasks and uses `cancel_job(job_id)` to record one `CANCELLED/cancelled` terminal audit, task exceptions are consumed, and scheduling after shutdown returns `False` without creating a job.

- [ ] **Step 2: Confirm scheduler RED**

Run `python -m pytest tests/test_memory_job_scheduler.py -q`.
Expected: import error for missing scheduler module.

- [ ] **Step 3: Implement scheduler API**

Define `MemoryJobScheduler` as the protocol consumed by `ChatService` (`schedule(...) -> bool` only), and `InProcessMemoryJobScheduler` as the lifespan-owned implementation with recovery/shutdown:

```python
class MemoryJobScheduler(Protocol):
    def schedule(
        self,
        *,
        session_id: str,
        user_message_id: str,
        assistant_message_id: str,
    ) -> bool: ...


class InProcessMemoryJobScheduler:
    def __init__(
        self,
        *,
        reserve_job: Callable[..., tuple[MemoryJob, bool]],
        run_job: Callable[[str], Awaitable[None]],
        recover_job_ids: Callable[[], list[str]],
        cancel_job: Callable[[str], None],
        mode: MemoryAutomationMode,
        route: MemoryExtractorRoute,
    ) -> None: ...

    def schedule(
        self,
        *,
        session_id: str,
        user_message_id: str,
        assistant_message_id: str,
    ) -> bool: ...

    async def recover(self) -> int: ...
    async def shutdown(self, *, cancel: bool = False) -> None: ...
```

`reserve_job`, `recover_job_ids`, and `cancel_job` are small lifespan composition callbacks that each open/close their own `managed_connection`; `run_job(job_id)` likewise constructs the repository/message service in a fresh connection and awaits processing before closing it. The scheduler therefore owns tasks and IDs, never a SQLite connection. `turn_id = assistant_message_id`; `schedule()` invokes `reserve_job(...)` synchronously and creates an asyncio task only when the row was new. The reservation callback must remain a single short local SQLite transaction and is the only shadow work on the chat request path—no message reload, extraction, Governor processing, or Provider call occurs there. Add a latency/behavior test where `run_job` is blocked by an event and prove `schedule()` returns before release. Keep a task set and consume exceptions in a done callback without logging exception text. The constructor accepts only `SHADOW_AUTO`. `recover()` asks `recover_job_ids()` to atomically return interrupted/pending IDs and schedules those existing IDs without reserving duplicates.

- [ ] **Step 4: Write chat mode mutual-exclusion tests**

Extend chat fixtures with a recording `MemoryCandidateService` and recording `MemoryJobScheduler`. Parametrize:

| Mode | existing candidate calls | job scheduler calls |
|---|---:|---:|
| off | 0 | 0 |
| candidate_confirmation | 1 | 0 |
| shadow_auto | 0 | 1 |

For shadow mode assert scheduled values are persisted `session.id`, `user_message.id`, and `assistant_message.id`, and `assistant_message.id` is not a generated surrogate. Add a scheduler-raises test asserting chat still returns and both persisted messages exist.

- [ ] **Step 5: Modify ChatService with one exclusive branch**

Add constructor dependency:

```python
memory_job_scheduler: MemoryJobScheduler | None = None,
```

After assistant persistence and expression-plan best effort, replace the unconditional candidate block with exactly one mode branch at the current candidate hook location. Keep the existing summary and emotion ordering unchanged:

```python
if self._settings.memory_automation_mode == MemoryAutomationMode.CANDIDATE_CONFIRMATION.value:
    if self._memory_candidates is not None:
        try:
            await self._memory_candidates.create_candidates_from_user_text(
                session_id=session_id,
                user_text=clean_text,
            )
        except Exception:
            pass
elif self._settings.memory_automation_mode == MemoryAutomationMode.SHADOW_AUTO.value:
    if self._memory_job_scheduler is not None:
        try:
            self._memory_job_scheduler.schedule(
                session_id=session_id,
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
            )
        except Exception:
            pass
```

There is no `else` action for `off`. Do not add an `auto_active` branch. The memory path remains between expression-plan creation and the existing summary scheduler, exactly where candidate extraction currently runs; shadow processing itself is never awaited.

- [ ] **Step 6: Run scheduler/chat regressions**

Run:

```text
python -m pytest tests/test_memory_job_scheduler.py tests/test_chat_memory_candidates.py tests/test_chat_service.py -q
```

Expected: all pass; candidate confirmation still creates only pending candidates and shadow mode creates none. Also run `python -m pytest tests/test_chat_memory_candidates.py -q` once with `MEMORY_CANDIDATES_ENABLED=false` in the focused fixture and assert candidate mode schedules neither pending candidates nor shadow jobs, preserving the legacy candidate feature flag.

---

## Task 9: Add independent consent API and API-only failure visibility

**Files:**
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/app/api/routes/memories.py`
- Modify: `backend/tests/test_api_memory_automation.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/test_api_memories.py`

- [ ] **Step 1: Add failing API lifecycle/list tests**

Required endpoints and expectations:

- `GET /api/memories/extraction/consent` → unknown generation 0 by default.
- `PUT /api/memories/extraction/consent` with grant/decline/revoke and exact disclosure literal → 200 and monotonic generation.
- wrong disclosure literal or extra provider field → 422.
- grant when configured route is not remote → still records consent but does not change mode; response provider is configured provider.
- `GET /api/memories/jobs?limit=20` → newest-first metadata records.
- `GET /api/memories/jobs/audits?limit=20` → newest-first metadata audits.
- list limits `0` and `101` → 422.
- payload JSON never includes `content`, `prompt`, `response`, `user_text`, or `assistant_text` keys.

Representative lifecycle assertion:

```python
def test_memory_extraction_consent_is_independent_from_mode(client, settings):
    response = client.put(
        "/api/memories/extraction/consent",
        json={
            "action": "grant",
            "disclosure_version": "memory-extraction-disclosure-v1",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "granted"
    assert response.json()["provider"] == settings.memory_extractor_provider
    assert settings.memory_automation_mode == "candidate_confirmation"
```

- [ ] **Step 2: Confirm API RED**

Run `python -m pytest tests/test_api_memory_automation.py -q`.
Expected: 404 for all four new routes.

- [ ] **Step 3: Add dependencies with the existing connection ownership pattern**

Add exact dependency signatures:

```python
def get_memory_automation_repository(
    connection: sqlite3.Connection = Depends(get_connection),
) -> MemoryAutomationRepository:
    return MemoryAutomationRepository(connection)


def get_memory_extraction_dispatch_fence(
    request: Request,
) -> MemoryExtractionDispatchFence:
    return request.app.state.memory_extraction_dispatch_fence
```

This matches existing repository dependencies: each HTTP request owns its `managed_connection`, while the fence and scheduler are lifespan-owned coordination objects. Background jobs open their own short `managed_connection(settings.database_url)` inside the lifespan-defined runner; never share one `sqlite3.Connection` concurrently across request and background tasks.

- [ ] **Step 4: Add route handlers and response converters**

Define static routes before dynamic `/{memory_id}` routes:

```python
@router.get(
    "/extraction/consent",
    response_model=MemoryExtractionConsentResponse,
)
def get_memory_extraction_consent(...): ...


@router.put(
    "/extraction/consent",
    response_model=MemoryExtractionConsentResponse,
)
async def update_memory_extraction_consent(...): ...


@router.get("/jobs", response_model=list[MemoryJobResponse])
def list_memory_jobs(
    limit: int = Query(default=20, ge=1, le=100), ...
) -> list[MemoryJobResponse]: ...


@router.get("/jobs/audits", response_model=list[MemoryJobAuditResponse])
def list_memory_job_audits(
    limit: int = Query(default=20, ge=1, le=100), ...
) -> list[MemoryJobAuditResponse]: ...
```

Consent constants:

```python
MEMORY_EXTRACTION_PURPOSE = (
    "extract durable memory proposals from the current completed turn"
)
MEMORY_EXTRACTION_DISCLOSURE_VERSION = "memory-extraction-disclosure-v1"
MEMORY_EXTRACTION_DISCLOSED_FIELDS = ("user_message", "assistant_message")
```

Consent response conversion adds deployment metadata from settings, never from the persisted grant: `deployment_route`, `deployment_provider`, and `deployment_configured` (true for local/fake/none; for remote, true only when the selected Provider key exists). This mirrors Stage 4C's distinction between consent and deployment availability without coupling either to automation mode.

For mutation, call `mutation = fence.begin_consent_mutation()` before the first `await`, then `async with mutation:` persist status mapped from action. Provider comes only from settings; request cannot choose it. Decline and revoke preserve the same purpose/provider/version/fields for auditable policy identity. Do not mutate `MEMORY_AUTOMATION_MODE`, jobs, or existing memories.

- [ ] **Step 5: Add non-blocking failure visibility assertion**

Insert a failed job/audit through the repository and assert `GET /jobs` exposes `status="failed"`, `outcome="provider_error"`, `error_category="provider_error"`, timestamps, and IDs, while `GET /jobs/audits` exposes counts and provider/model only. This API-only visibility is the complete Gate A UX scope; do not change React files.

- [ ] **Step 6: Run API regressions**

Run:

```text
python -m pytest tests/test_api_memory_automation.py tests/test_api_memories.py tests/test_api_emotion.py -q
```

Expected: all pass; existing `/api/memories/audit-events`, CRUD, confirmation, dismissal, and archive routes remain unchanged.

---

## Task 10: Compose lifespan-owned providers/services and repair chat-provider closure

**Files:**
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/app/providers/factory.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_api_chat.py`
- Modify: `backend/tests/test_memory_job_scheduler.py`
- Test: `backend/tests/test_provider_factory.py`

- [ ] **Step 1: Write failing shared-provider lifecycle test**

Monkeypatch `create_provider`, `create_named_provider`, and `close_async_resource` with recording resources, open two API requests in one `TestClient` lifespan, and assert the ordinary chat provider is created once, returned by `get_llm_provider`, and closed once. For shadow remote mode, assert the separate extractor provider is created at most once and closes after scheduler shutdown. Record ordered events:

```python
assert events.index("memory_scheduler_shutdown") < events.index("memory_provider_close")
assert events.index("memory_provider_close") < events.index("chat_provider_close")
```

If remote provider construction is skipped because credentials are absent, assert the scheduler records `SUCCEEDED/skipped_no_extractor` rather than startup failure, a fake semantic success, or an unmanaged client. Provider construction itself sends no data; the consent fence still runs immediately before every actual `generate()` transmission.

- [ ] **Step 2: Confirm lifecycle RED**

Run the new focused test in `tests/test_api_chat.py`.
Expected: fail because `get_llm_provider()` creates a provider per dependency resolution and shutdown never closes it.

- [ ] **Step 3: Make the ordinary chat provider lifespan-owned**

In `main.py` lifespan, create the chat provider once, assign `app.state.llm_provider`, and close it with `close_async_resource()` at shutdown. Change the dependency to:

```python
def get_llm_provider(request: Request) -> LLMProvider:
    return request.app.state.llm_provider
```

This is the only non-memory behavioral repair in Gate A; it prevents adding a second leak on top of the pre-existing request-scoped Anthropic/DeepSeek clients. It must not change provider choice, model, retries, or chat response behavior.

- [ ] **Step 4: Compose memory automation only for shadow mode**

Add and test:

```python
def create_memory_extractor_provider(settings: Settings) -> LLMProvider:
    return create_named_provider(
        settings,
        settings.memory_extractor_provider,
        deepseek_max_tokens=settings.memory_extractor_max_tokens,
        deepseek_timeout_seconds=settings.memory_extractor_timeout_seconds,
        deepseek_max_retries=settings.memory_extractor_max_retries,
    )
```

The factory is for the `remote` route only. Its test must prove Anthropic still requires its key and DeepSeek receives extractor-specific overrides without changing chat-provider defaults; the `fake` route uses `MemoryExtractionFakeProvider` from the extractor module and never calls this factory.

In `main.py`, add `validate_memory_automation_capability(settings)` and call it before constructing any app resources. It raises the same `MEMORY_AUTOMATION_MODE=auto_active is unavailable before Gate B` error. Test this helper with `dataclasses.replace(load_settings(), memory_automation_mode="auto_active")`, which bypasses environment parsing and proves lower-level composition/DI cannot weaken the guard.

During lifespan:

1. initialize the additive schema with the existing `managed_connection` startup probe; do not keep that connection on `app.state`;
2. create one `MemoryExtractionDispatchFence` and expose it on `app.state` for consent API/background coordination;
3. if mode is not `shadow_auto`, do not create a memory scheduler or extractor provider;
4. for shadow mode, define a background runner that opens a fresh `managed_connection(settings.database_url)` per job and constructs `MemoryAutomationRepository` plus `MessageRepository` within that scope;
5. route `none`: runner/service uses `extractor=None`;
6. route `local`: `LocalMemoryExtractor(settings)` and no provider resource;
7. route `fake`: create `MemoryExtractionFakeProvider(settings)`, then wrap it in `ProviderMemoryExtractor`; this is a local deterministic development route and does not reinterpret `MEMORY_EXTRACTOR_PROVIDER` or alter the general chat `FakeProvider`;
8. route `remote`: create named Anthropic/DeepSeek provider only when the selected provider's key is present; otherwise use `extractor=None`, preserving explicit skipped visibility;
9. construct the lifespan scheduler around the per-job runner and expose it as `app.state.memory_job_scheduler` (or a no-op scheduler when mode is not shadow so `get_chat_service` remains total);
10. run repository `recover_incomplete_jobs()` in one short connection, then ask the scheduler to enqueue the returned pending job IDs without reserving duplicates.

Add a dedicated `create_memory_extractor_provider(settings)` factory in `backend/app/providers/factory.py` that delegates to `create_named_provider(...)` with extractor-specific DeepSeek token/timeout/retry overrides. It is called only for the remote route. Production composition uses this factory for Anthropic/DeepSeek and `MemoryExtractionFakeProvider` for the fake route; no Anthropic SDK import appears outside `anthropic_provider.py`, and no DeepSeek HTTP code appears outside `deepseek_provider.py`.

- [ ] **Step 5: Enforce shutdown order**

Shutdown in this order:

1. memory job scheduler;
2. existing emotion-analysis scheduler;
3. existing summary scheduler;
4. memory extractor provider;
5. existing emotion/summary providers;
6. ordinary chat provider;
7. database connection according to current lifespan ownership.

Every resource is closed exactly once even if startup only partially constructed it. Use `None` guards and `close_async_resource`; do not duplicate provider-specific close logic.

- [ ] **Step 6: Run lifecycle, factory, chat API, and scheduler tests**

Run:

```text
python -m pytest tests/test_api_chat.py tests/test_provider_factory.py tests/test_memory_job_scheduler.py -q
```

Expected: all pass, no unclosed HTTPX/Anthropic client warnings, and all fake/real provider ownership assertions pass.

---

## Task 11: End-to-end Gate A verification, security scan, and rollback evidence

**Files:**
- Modify only if a test exposes a defect: files already listed in Tasks 1–10
- Do not create acceptance claims for unrun real Provider tests

- [ ] **Step 1: Run focused Gate A suite**

Run from repository root with the project virtual environment:

```text
.\.venv\Scripts\python.exe -m pytest backend/tests/test_config.py backend/tests/test_memory_automation_migration.py backend/tests/test_memory_automation_repository.py backend/tests/test_memory_governor.py backend/tests/test_memory_extractor.py backend/tests/test_memory_job_service.py backend/tests/test_memory_job_scheduler.py backend/tests/test_api_memory_automation.py backend/tests/test_chat_memory_candidates.py backend/tests/test_api_memories.py backend/tests/test_api_chat.py -q
```

Expected: zero failures and zero warnings about destroyed pending tasks or unclosed clients. Record the actual test count; do not predict or hard-code it in documentation.

- [ ] **Step 2: Run all backend regression tests**

Run from repository root: `.\.venv\Scripts\python.exe -m pytest backend/tests -q`.
Expected: complete backend suite passes. If a real external-provider test is skipped because no key is configured, report it as skipped; fake success is not real-provider evidence.

- [ ] **Step 3: Run only configured static checks**

`backend/pyproject.toml` currently configures pytest but does not declare Ruff or mypy in development dependencies and has no Ruff/mypy sections. Therefore do not invent a mandatory static gate or install new tools. If the environment already has either tool, optional evidence may be collected with:

```text
python -m ruff check app tests
python -m mypy app
```

A missing module is recorded as `not configured` and is not a Gate A failure. The mandatory automated gates remain focused pytest, full backend pytest, migration/privacy assertions, smoke verification, and `git diff --check`.

- [ ] **Step 4: Perform explicit metadata and scope scans**

From the repository root, use dedicated search or equivalent read-only commands to verify:

- no new job/audit schema field contains raw content/prompt/response/credential names;
- `MemoryJobService` does not import or reference `MemoryRepository`;
- no new Anthropic/DeepSeek/HTTPX import appears in memory services or routes;
- no `auto_active` implementation branch exists outside the two rejection guards/tests/docs;
- no frontend, Electron, voice, asset, Live2D, summary, Persona, relationship, tombstone, Evidence, or conflict-persistence file changed;
- no API key, Authorization header, private image, or voice artifact entered the diff.

Expected: only the frozen Gate A files listed in this plan appear.

- [ ] **Step 5: Run real local API smoke test without remote consent**

Start FastAPI from repository root with the documented command and a temporary local SQLite path:

```text
$env:DATABASE_URL='sqlite:///./gate-a-smoke.db'; $env:LLM_PROVIDER='fake'; $env:MEMORY_AUTOMATION_MODE='shadow_auto'; $env:MEMORY_EXTRACTOR_ROUTE='remote'; $env:MEMORY_EXTRACTOR_PROVIDER='anthropic'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Do not grant consent and do not configure `ANTHROPIC_API_KEY`. In another terminal, create a session and one successful fake-chat turn through the actual HTTP API using the existing request shapes in `tests/test_api_chat.py`; query `/api/memories/jobs` and `/api/memories/jobs/audits`, then inspect the temporary SQLite database with a short Python read-only script. Stop the server and delete only the smoke database created by this step after recording evidence.

Required observations:

- chat returns normally;
- exactly one job exists for the assistant message ID;
- job is `skipped_no_consent`;
- remote extractor call count/network capture is zero;
- `memories` rows are unchanged;
- API job output has no conversation/proposal body.

Then repeat with `MEMORY_EXTRACTOR_ROUTE=local`; the job may be `shadow_recorded` with aggregate counts, but `memories` remains unchanged. Do not claim a real Anthropic/DeepSeek test unless a key is configured and the user has explicitly granted versioned consent through the API.

- [ ] **Step 6: Verify rollback path**

Rollback is configuration-first and data-preserving:

1. set `MEMORY_AUTOMATION_MODE=candidate_confirmation` to restore the pre-Gate-A candidate path, or `off` to disable both paths;
2. restart and verify no new shadow job is scheduled;
3. leave additive Gate A tables in place—SQLite rollback by dropping tables is not required and would destroy audit evidence;
4. if code rollback is necessary, revert only Gate A code while retaining a database backup; older code ignores additive tables;
5. never auto-promote, delete, or rewrite existing pending/dismissed/active/archived memories during rollback.

Test this by creating two isolated app instances/databases with explicit settings rather than mutating a frozen `Settings` object: one `candidate_confirmation`, one `off`. Assert the candidate instance still produces pending records, the off instance produces neither candidates nor jobs, and Gate A jobs in the first database remain readable directly from SQLite after starting code/config in fallback mode.

- [ ] **Step 7: Review diff without staging or committing**

From repository root run:

```text
git status --short
git diff --check
git diff -- .env.example backend/app backend/tests docs/superpowers/plans/2026-07-16-automatic-memory-gate-a-shadow-mode.md
```

Expected: `git diff --check` exits 0 apart from an informational LF/CRLF warning. Confirm unrelated `.claude/`, `.superpowers/`, temporary Playwright config, `test-results/`, private character images, and voice assets are not included. Do not run `git add` or `git commit`.

---

## Gate A acceptance criteria

Gate A passes only when every item below has actual evidence:

1. Existing active, pending, dismissed, and archived memories migrate unchanged; existing memory CRUD/context/candidate tests remain green.
2. `candidate_confirmation` is the default and preserves current behavior.
3. Each successful turn selects exactly one of off/candidate/shadow paths; no turn creates both pending candidates and a shadow job.
4. `auto_active` is rejected in settings and by the database mode constraint; there is no active-write code path. A second startup-unit test passes `dataclasses.replace(load_settings(), memory_automation_mode="auto_active")` directly to `validate_memory_automation_capability()` and must receive the same Gate A capability error, so lower-level composition/DI cannot bypass the guard.
5. Repeated scheduling for the same assistant message/schema yields one job and at most one extraction attempt at a time; one `UNIQUE(job_id)` terminal audit survives duplicates/recovery. If a process dies after a remote send but before terminal commit, startup recovery may call the Provider once more because Gate A has no provider request-idempotency key; it still cannot duplicate or mutate active memories, and retries within one process remain disabled.
6. Shadow success, rejection, malformed output, provider failure, restart recovery, and consent races leave the entire `memories` table byte-for-byte unchanged.
7. Passwords, API keys, verification codes, private keys, full payment credentials, and identity credentials are locally preflight-rejected before any extractor call; explicit “不要记住” and deletion intent also produce zero extraction/network calls. The same rules reject transient post-extraction proposals, and assistant-echoed credentials are covered.
8. Job/audit tables and APIs contain only IDs, versions, timestamps, provider/model, counts, fixed outcomes/reasons, and sanitized error categories—no prompts, raw responses, candidate bodies, message text, credentials, or Authorization headers.
9. Remote extraction without a matching current grant makes zero network/provider calls and records an explicit skipped outcome without changing automation mode.
10. Consent revocation wins over unsent jobs; an in-flight response after revocation/pending revocation is discarded and produces a metadata-only `SUCCEEDED/skipped_consent_changed` terminal result.
11. Scheduling, extraction, parsing, Governor, and SQLite failures never invalidate an already-persisted assistant reply.
12. Failed/skipped jobs are visible through read-only APIs without a frontend change.
13. Scheduler recovery/shutdown is deterministic; memory extractor and ordinary chat providers are lifespan-owned and closed exactly once after dependent schedulers stop.
14. Focused and full backend regressions pass; real-provider limitations/skips are reported honestly.
15. Diff contains no Gate B/C, Electron, voice, Live2D, frontend, private asset, secret, staging, or commit changes.

## Risks and mitigations

- **Consent race:** use the priority fence, generation re-check before send, pending-mutation check after response, and deterministic `asyncio.Event` tests.
- **Duplicate jobs after restart:** reserve by `(assistant_message.id, schema_version)`, recover incomplete jobs, and never rerun terminal jobs. Gate A guarantees database-effect idempotency and one terminal audit, not exactly-once remote transmission across a hard crash; retries are zero and a recovered in-flight job may transmit again because Provider request idempotency is unavailable.
- **Shadow accidentally mutates memory:** omit `MemoryRepository` from the service graph, add SQL before/after assertions, and keep DB mode constrained to `shadow_auto`.
- **Sensitive text leaks through errors:** persist fixed categories only; never persist/log exception strings or Provider response text.
- **Provider-neutral parser drift:** one constrained `LLMProvider.generate()` call plus exhaustive local JSON validation; provider SDKs remain isolated.
- **SQLite partial writes:** Provider calls occur outside transactions; terminal job state and audit append commit atomically in a short `BEGIN IMMEDIATE` transaction.
- **Resource leak:** lifespan owns chat and extractor clients; scheduler shutdown precedes provider close.
- **Legacy behavior regression:** default to candidate confirmation and run memory, chat, Stage 4C consent, provider factory, and full backend suites.
- **Scope expansion:** no changes to memory repository/context, summaries, frontend, Electron, voice, assets, or relationship/persona code.

## Plan self-review record

- **Spec coverage:** Gate A requirements in approved design sections 6.2, 7.1–7.2, 7.7–7.8, 13–16, 17, and 19 are mapped to Tasks 1–11. Gate B/C-only requirements are explicitly excluded.
- **Placeholder scan:** implementation work contains no `TBD`, `TODO`, “implement later”, or unspecified “handle errors/write tests” instruction. Python ellipses appear only in signature declarations that are immediately followed by exact behavioral rules; implementers must replace them with those rules, not ship ellipses.
- **Type consistency:** schema version is always `memory-shadow-schema-v1`; rules version is always `memory-governor-rules-v1`; stable `turn_id` is always the persisted assistant message ID; consent fields and versions match across schema, API, service, and repository; `MemoryJobService` has no memory repository dependency.
- **Privacy consistency:** transient proposal content exists only in extractor/Governor process memory and existing local message rows. New tables, audits, API output, and ordinary logs remain metadata-only.
- **Scope consistency:** minimum failure visibility is API-only; no frontend or later-Gate subsystem is planned.
