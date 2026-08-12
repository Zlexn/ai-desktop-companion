# Automatic Memory Gate B Versioned Write Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add consent-gated, versioned automatic active-memory writes with Evidence, conflict handling, true-forget tombstones, deletion generations, source barriers, minimum management UI, and full preservation of Gate A and Stage 1–4 behavior.

**Architecture:** Keep the Stage 3 `memories` table and APIs as a compatibility projection while adding explicit V2 state/version/Evidence/conflict/deletion tables. Route every formal-memory mutation through one versioned mutation boundary; route automatic proposals through a local commit policy and a capability-isolated commit service. Reuse Gate A extraction and scheduling, but keep `shadow_auto` metadata-only and require an independent write-consent fence before any `auto_active` extraction.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLite, asyncio, existing LLM providers and Gate A scheduler, pytest/pytest-asyncio/TestClient, React, TypeScript, Vite, Vitest, Testing Library.

---

## 0. Execution contract and frozen decisions

Authoritative specification:

- `docs/superpowers/specs/2026-07-19-automatic-memory-gate-b-versioned-write-design.md`

Gate A remains authoritative for shadow extraction:

- `docs/superpowers/specs/2026-07-18-automatic-memory-gate-a-closure-design.md`
- `docs/automatic-memory-gate-a-acceptance-2026-07-19.md`

The repository is already dirty. During execution do **not** stage, commit, amend, push, reset, restore, clean, stash, or delete unrelated files. Each task ends with tests and `git status --short`, not a commit.

Run backend commands from the repository root with:

```powershell
$env:PYTHONPATH = "$PWD;$PWD\backend"
```

Frozen Gate B constants:

```text
workflow/schema       memory-auto-active-schema-v1
write policy          memory-auto-write-policy-v1
retention disclosure memory-auto-write-retention-v1
canonicalization     memory-canonicalization-v1
commit policy         memory-commit-policy-v1
source reference     memory-source-reference-v1
allowed types set    memory-auto-write-types-v1
fixture schema        memory-gate-b-fixtures-v1
semantic retries      2 extra SQLite transaction attempts
```

The reference HMAC key lives at `backend/data/memory-source-reference-v1.key` by default. Add `MEMORY_SOURCE_REFERENCE_KEY_PATH` so tests may use a temporary path. The file contains 32 random bytes, is created atomically with exclusive creation, stays under the already ignored `backend/data/`, is never stored in SQLite or `.env.example`, and is never logged. Missing-key behavior is:

- create the key only if no HMAC references exist yet;
- if references already exist and the key is missing/invalid, fail closed at startup;
- tests inject a fixed temporary key file; no real key enters fixtures or Git.

Gate B allowed automatic types remain the ordered set:

```text
user_fact, preference, long_term_goal,
important_event, relationship_event, other
```

`commitment` stays out of Gate B.

### Planned new production files

- `backend/app/services/memory_gate_b_contract.py`
- `backend/app/services/memory_source_reference.py`
- `backend/app/repositories/versioned_memories.py`
- `backend/app/services/versioned_memory_mutation.py`
- `backend/app/services/memory_commit_policy.py`
- `backend/app/services/versioned_memory_commit.py`
- `backend/app/services/memory_write_dispatch.py`
- `backend/app/services/memory_forget_service.py`
- `backend/app/services/session_deletion_coordinator.py`
- `backend/app/services/memory_conflict_resolution.py`
- `frontend/src/components/MemoryAutomationControls.tsx`
- `frontend/src/components/MemoryConflictPanel.tsx`
- `frontend/src/components/MemoryHistoryDetails.tsx`

### Planned new test/fixture files

- `backend/tests/fixtures/memory_gate_b/commit_cases.json`
- `backend/tests/test_versioned_memory_migration.py`
- `backend/tests/test_memory_source_reference.py`
- `backend/tests/test_versioned_memory_repository.py`
- `backend/tests/test_versioned_memory_mutation.py`
- `backend/tests/test_memory_commit_policy.py`
- `backend/tests/test_versioned_memory_commit.py`
- `backend/tests/test_memory_write_dispatch.py`
- `backend/tests/test_memory_forget_service.py`
- `backend/tests/test_session_deletion_coordinator.py`
- `backend/tests/test_memory_summary_barrier.py`
- `backend/tests/test_memory_conflict_resolution.py`
- `backend/tests/test_api_memory_gate_b.py`
- `backend/tests/test_gate_b_http_smoke.py`
- `backend/tests/test_gate_b_privacy_contract.py`
- corresponding frontend component tests

---

## Task 1: Freeze Gate B contracts and fixture corpus

**Files:**
- Create: `backend/app/services/memory_gate_b_contract.py`
- Create: `backend/tests/fixtures/memory_gate_b/commit_cases.json`
- Modify: `backend/app/domain/models.py`
- Modify: `backend/app/domain/schemas.py`
- Modify: `backend/app/core/config.py`
- Modify: `.env.example`
- Modify: `backend/tests/test_config.py`

- [ ] **Step 1: Add failing config/domain tests**

Add tests proving:

```python
assert Settings(memory_automation_mode="auto_active").memory_automation_mode == "auto_active"
assert MEMORY_AUTO_ACTIVE_SCHEMA_VERSION == "memory-auto-active-schema-v1"
assert MEMORY_WRITE_POLICY_VERSION == "memory-auto-write-policy-v1"
assert MEMORY_ALLOWED_AUTO_TYPES_VERSION == "memory-auto-write-types-v1"
assert MEMORY_ALLOWED_AUTO_TYPES == (
    MemoryType.USER_FACT,
    MemoryType.PREFERENCE,
    MemoryType.LONG_TERM_GOAL,
    MemoryType.IMPORTANT_EVENT,
    MemoryType.RELATIONSHIP_EVENT,
    MemoryType.OTHER,
)
```

Also assert `commitment` is absent, semantic retries accept only `0..3` with default `2`, and `MEMORY_SOURCE_REFERENCE_KEY_PATH` defaults to `backend/data/memory-source-reference-v1.key` relative to the repository runtime.

- [ ] **Step 2: Run RED tests**

```powershell
python -W error -m pytest backend/tests/test_config.py -q
```

Expected: FAIL because `auto_active`, Gate B enums/constants, and new settings do not exist.

- [ ] **Step 3: Add exact domain types and constants**

Define strict enums/dataclasses for write consent, V2 state, version operation, Evidence relation, conflict state/resolution, deletion scope, commit decision/outcome, version, Evidence, conflict, state record, activity, and frozen job snapshots. Put all frozen strings and allowed ordered types in `memory_gate_b_contract.py`; production code must import rather than repeat literals.

- [ ] **Step 4: Create the versioned fixture corpus**

`commit_cases.json` must contain a top-level `fixture_schema_version` and cases for:

```text
safe_create, exact_support, explicit_correction,
unique_conflict, ambiguous_exact, ambiguous_conflict,
sensitive_reject, explicit_no_memory, deletion_intent,
assistant_invented_fact, exact_tombstone, subject_tombstone,
stale_user_edit, deleted_job, dual_consent
```

Use fictional test text only; no private user content or real credentials.

- [ ] **Step 5: Implement conservative config**

Keep default mode `candidate_confirmation`. `auto_active` becomes syntactically valid but still has zero write authority without the persisted grant. Add only variable names/comments to `.env.example`; do not put the HMAC key there.

- [ ] **Step 6: Run GREEN and Gate A config regression**

```powershell
python -W error -m pytest backend/tests/test_config.py backend/tests/test_memory_governor.py -q
```

---

## Task 2: Implement the source-reference key manager

**Files:**
- Create: `backend/app/services/memory_source_reference.py`
- Create: `backend/tests/test_memory_source_reference.py`
- Modify: `backend/app/core/config.py`

- [ ] **Step 1: Add failing key lifecycle tests**

Cover atomic first creation, stable HMAC output, typed separation (`session:x != message:x`), file permission best effort on Windows, no key bytes in exception/log text, invalid-size rejection, and missing-key fail-closed when a callback reports existing references.

- [ ] **Step 2: Run RED**

```powershell
python -W error -m pytest backend/tests/test_memory_source_reference.py -q
```

- [ ] **Step 3: Implement `MemorySourceReferenceService`**

The public interface is:

```python
class MemorySourceReferenceService:
    @classmethod
    def load_or_create(
        cls,
        path: Path,
        *,
        references_exist: Callable[[], bool],
    ) -> "MemorySourceReferenceService": ...

    def session_hash(self, session_id: str) -> str: ...
    def message_hash(self, message_id: str) -> str: ...
```

Use `hmac.new(key, typed_material, hashlib.sha256).hexdigest()`. Never expose the raw key.

- [ ] **Step 4: Keep Task 2 independent of application startup**

Do not modify lifespan or query Gate B tables in this task. Test the key service with explicit callbacks only. Startup ownership is deferred until Task 3 has created the reference columns, preventing existing Gate A databases from querying absent tables/columns.

- [ ] **Step 5: Run GREEN**

```powershell
python -W error -m pytest backend/tests/test_memory_source_reference.py -q
```

---

## Task 3: Build the data-preserving Gate B migration

**Files:**
- Create: `backend/tests/test_versioned_memory_migration.py`
- Modify: `backend/app/repositories/sqlite.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/tests/test_memory_automation_migration.py`
- Modify: `backend/tests/test_session_summaries.py`
- Modify: `backend/tests/test_api_chat.py`

- [ ] **Step 1: Write realistic pre-Gate-B migration fixtures**

Create databases containing sessions/messages, all four legacy memory statuses, embeddings, summaries, Gate A consent/jobs/audits, and inbound foreign keys. Do not use reduced fake DDL.

- [ ] **Step 2: Add RED migration assertions**

Assert the migration creates all approved Gate B tables and summary fields; expands `memories.source` and job/audit enums; changes job source FKs to nullable `ON DELETE SET NULL`; and leaves pending/dismissed without V2 state. Assert `memory_job_audits.job_id` is a non-cascading FK to the retained job, `UNIQUE(job_id)` and all historical count/outcome fields survive, and deleting a retained job cannot silently cascade-delete its audit.

For `auto_active`, assert `memory_jobs` adds non-null/frozen `turn_completed_at`, `reserved_mode`, `workflow_version`, `extractor_route`, `governor_version`, `commit_policy_version`, `canonicalization_version`, `allowed_memory_types_version`, write/remote authority snapshots, and global/session/type deletion snapshots. Existing Gate A rows receive explicitly documented nullable legacy values and remain valid; no current time or fabricated consent snapshot may be backfilled.

Require:

```python
assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
```

Also compare row counts and every legacy business field before/after. Inject failure midway and assert schema plus data roll back.

- [ ] **Step 3: Run RED**

```powershell
python -W error -m pytest backend/tests/test_versioned_memory_migration.py backend/tests/test_memory_automation_migration.py -q
```

- [ ] **Step 4: Implement explicit parent/child rebuild order**

Before rebuilding, read `PRAGMA foreign_key_list` for every table and verify the complete inbound graph. Rebuild constrained parents and children in one transaction. At minimum cover:

```text
memories → memory_embeddings
memory_jobs → memory_job_audits (final audit FK is non-cascading)
sessions/messages → memory_jobs, memory_versions, memory_evidence
```

Never turn `foreign_keys` off. Unexpected inbound dependencies abort and roll back.

- [ ] **Step 5: Add Gate B tables and constraints**

Create the approved state, version, Evidence/retraction, conflict, activity, write-consent, generation, tombstone, summary barrier, and summary exclusion tables. Add composite FKs and triggers/guarded constraints for same-identity linear versions, deleted→delete-head, and one-open-conflict-per-endpoint.

- [ ] **Step 6: Wire source-reference startup ownership after schema creation**

After Gate B migration completes, create `MemorySourceReferenceService` in lifespan, store it at `app.state.memory_source_reference_service`, and expose a backend-only dependency. Routes/repositories never receive raw bytes. Implement a schema-aware `references_exist()` that inspects `sqlite_master`/`PRAGMA table_info`: when all relevant tables/columns are absent it returns `False`; when any of `memory_versions`, `memory_evidence`, or `memory_jobs` reference columns exists, it strictly queries every existing column and returns `True` if any digest exists. Tests cover a plain Gate A DB, partially migrated schema, fully migrated empty schema, existing references with missing key (startup failure), and invalid key (startup failure).

- [ ] **Step 7: Run GREEN and repository/lifespan regressions**

```powershell
python -W error -m pytest backend/tests/test_versioned_memory_migration.py backend/tests/test_memory_automation_migration.py backend/tests/test_memory_source_reference.py backend/tests/test_repositories.py backend/tests/test_session_summaries.py backend/tests/test_api_chat.py -q
```

---

## Task 4: Implement V2 repository reads and guarded primitives

**Files:**
- Create: `backend/app/repositories/versioned_memories.py`
- Create: `backend/tests/test_versioned_memory_repository.py`
- Modify: `backend/app/repositories/memories.py`
- Modify: `backend/tests/test_repositories.py`

- [ ] **Step 1: Add RED database-invariant tests**

Directly attempt invalid cross-identity parent/head/Evidence links, non-contiguous versions, a deleted state pointing at a non-delete version, duplicate activity fingerprint, and a second open conflict endpoint membership. Each must fail at DB or guarded-repository level.

- [ ] **Step 2: Add RED eligibility and keyset tests**

Assert eligible means V2 active, complete current head, not deleted, and not an open-conflict endpoint. Legacy active rows remain readable until controlled bootstrap. Add 101-row version/Evidence/conflict traversal tests with no gap or duplicate.

- [ ] **Step 3: Run RED**

```powershell
python -W error -m pytest backend/tests/test_versioned_memory_repository.py backend/tests/test_repositories.py -q
```

- [ ] **Step 4: Implement repository primitives**

Keep SQL, cursor encoding/validation, bootstrap reads, generation snapshots, tombstone queries, activity lookup, and stable list operations here. Do not put policy, Provider calls, or HTTP logic in the repository.

- [ ] **Step 5: Run GREEN**

```powershell
python -W error -m pytest backend/tests/test_versioned_memory_repository.py backend/tests/test_repositories.py -q
```

---

## Task 5: Route all user mutations through V2

**Files:**
- Create: `backend/app/services/versioned_memory_mutation.py`
- Create: `backend/tests/test_versioned_memory_mutation.py`
- Modify: `backend/app/repositories/memories.py`
- Modify: `backend/app/repositories/memory_embeddings.py`
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/app/api/routes/memories.py`
- Modify: `backend/app/services/context_builder.py`
- Modify: `backend/tests/test_api_memories.py`
- Modify: `backend/tests/test_memory_candidate_service.py`
- Modify: `backend/tests/test_context_builder.py`

- [ ] **Step 1: Add RED mutation tests**

Cover manual create root version, legacy bootstrap, PATCH as `user_edit`, candidate confirmation creating its first state/version, legacy DELETE and explicit archive as archive semantics, CAS failure, and refusal to archive conflicted records.

- [ ] **Step 2: Run RED**

```powershell
python -W error -m pytest backend/tests/test_versioned_memory_mutation.py backend/tests/test_api_memories.py backend/tests/test_context_builder.py -q
```

- [ ] **Step 3: Implement `VersionedMemoryMutationService` and its shared primitive**

Define an internal transaction-scoped `VersionedMemoryMutationPrimitive` used by manual/PATCH/confirm/archive now and by forget/revert/conflict resolution later. It owns guarded state/head/version/projection/activity mutations; specialized services may orchestrate policy but may not issue direct formal-memory state SQL. Existing repository facade methods may remain for compatibility but must delegate; route code and embedding code must not mutate formal memory directly.

- [ ] **Step 4: Unify context eligibility**

Both deterministic and embedding-assisted context queries must exclude V2 archived/deleted/conflicted and every open conflict endpoint. `MemoryEmbeddingRepository.search_active()` must use the same shared V2 eligibility SQL/query primitive rather than only `memories.status='active'`. Add fixtures where the legacy projection stays active but V2 state is conflicted/open; assert both retrieval paths exclude it. Do not add summary injection.

- [ ] **Step 5: Run GREEN and Stage 3 regression**

```powershell
python -W error -m pytest backend/tests/test_versioned_memory_mutation.py backend/tests/test_api_memories.py backend/tests/test_memory_candidate_service.py backend/tests/test_context_builder.py backend/tests/test_repositories.py -q
```

---

## Task 6: Implement canonicalization, grounding, and commit policy

**Files:**
- Create: `backend/app/services/memory_commit_policy.py`
- Create: `backend/tests/test_memory_commit_policy.py`
- Modify: `backend/app/services/memory_governor.py`
- Modify: `backend/tests/test_memory_governor.py`

- [ ] **Step 1: Add RED pure-policy tests from the fixture corpus**

Test create, support, supersede, unique conflict, ambiguous exact/conflict, open-conflict block, sensitive/no-memory/deletion rejection, assistant-invented fact rejection, and exact/subject tombstones.

- [ ] **Step 2: Run RED**

```powershell
python -W error -m pytest backend/tests/test_memory_commit_policy.py backend/tests/test_memory_governor.py -q
```

- [ ] **Step 3: Implement only explicit helpers**

```python
canonicalize_memory_v1(...)
proposal_fingerprint_v1(...)
verify_explicit_user_assertion(...)
select_unique_exact_target(...)
select_unique_conflict_target(...)
```

The remote hint never participates. Assistant text is supplementary only; an automatic decision requires local grounding in the current user message.

- [ ] **Step 4: Run GREEN**

```powershell
python -W error -m pytest backend/tests/test_memory_commit_policy.py backend/tests/test_memory_governor.py -q
```

---

## Task 7: Implement proposal-level versioned commit

**Files:**
- Create: `backend/app/services/versioned_memory_commit.py`
- Create: `backend/tests/test_versioned_memory_commit.py`
- Modify: `backend/app/repositories/versioned_memories.py`

- [ ] **Step 1: Add RED transaction and crash-window tests**

Cover create/support/supersede/conflict atomicity, correct Evidence directions, proposal reordering fingerprint identity, duplicate op, zero-row CAS, busy/snapshot retries from fresh state, and no repeated Provider call.

- [ ] **Step 2: Run RED**

```powershell
python -W error -m pytest backend/tests/test_versioned_memory_commit.py -q
```

- [ ] **Step 3: Implement `commit_one`**

Each proposal gets one `BEGIN IMMEDIATE` transaction. Check activity first, re-read all authority/deletion/head state, run local policy, write one activity, and use guarded CAS. Allow two extra semantic transaction attempts; never call a Provider in this service. Inject the read-only `MemorySourceReferenceService` capability and use it to populate typed session/message HMAC columns for automatic version/Evidence records; tests use a temporary fixed key file and assert raw IDs never occupy hash fields.

- [ ] **Step 4: Run GREEN and policy/repository regression**

```powershell
python -W error -m pytest backend/tests/test_versioned_memory_commit.py backend/tests/test_memory_commit_policy.py backend/tests/test_versioned_memory_repository.py -q
```

---

## Task 8: Add write consent and dispatch fencing

**Files:**
- Create: `backend/app/services/memory_write_dispatch.py`
- Create: `backend/tests/test_memory_write_dispatch.py`
- Modify: `backend/app/repositories/memory_automation.py`
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_memory_automation_repository.py`

- [ ] **Step 1: Add RED consent/fence tests**

Cover lazy unknown, generation increments, exact authority identity, `granted_at`, pending mutation priority, revoke before/during extraction, and fixed lock order `write → remote` without deadlock. Add blocking hooks for: write revoke after local/fake extractor returns but before `commit_one`; remote-consent mutation after remote response but before commit; and a pending write mutation registered before fence acquisition. Each asserts zero version/Evidence/state/projection/embedding mutation and only fixed metadata outcomes; pending mutation also asserts zero extractor/send.

- [ ] **Step 2: Run RED**

```powershell
python -W error -m pytest backend/tests/test_memory_write_dispatch.py backend/tests/test_memory_automation_repository.py -q
```

- [ ] **Step 3: Implement the independent write fence**

Follow the proven Gate A consent-fence behavior but keep separate purpose/state. Before any extractor call, within the fence verify full write authority and `granted_at <= turn_completed_at`; recheck after extraction and in commit.

- [ ] **Step 4: Run GREEN**

```powershell
python -W error -m pytest backend/tests/test_memory_write_dispatch.py backend/tests/test_memory_automation_repository.py -q
```

---

## Task 9: Integrate `auto_active` jobs, scheduler, chat, and lifespan

**Files:**
- Modify: `backend/app/domain/models.py`
- Modify: `backend/app/repositories/memory_automation.py`
- Modify: `backend/app/services/memory_job_service.py`
- Modify: `backend/app/services/memory_job_scheduler.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_memory_job_service.py`
- Modify: `backend/tests/test_memory_job_scheduler.py`
- Modify: `backend/tests/test_chat_memory_candidates.py`
- Modify: `backend/tests/test_api_chat.py`

- [ ] **Step 1: Add RED frozen-job and mode tests**

Test all immutable reserve fields, current mode/route/policy/type-set mismatch, grant-after-old-turn rejection, startup recovery, proposal crash recovery, and all four mutually exclusive chat branches. `turn_completed_at` comes from the already persisted assistant message timestamp and is frozen at reserve; worker/job start time is forbidden. Mode/route/policy/type-set mismatch must produce zero extractor calls.

- [ ] **Step 2: Run RED**

```powershell
python -W error -m pytest backend/tests/test_memory_job_service.py backend/tests/test_memory_job_scheduler.py backend/tests/test_chat_memory_candidates.py backend/tests/test_api_chat.py -q
```

- [ ] **Step 3: Split shadow and active execution paths**

Keep Gate A shadow code incapable of receiving the V2 commit service. The active path obtains both fences as required, extracts once, then calls `commit_one` per proposal and terminalizes the job with aggregate metadata.

- [ ] **Step 4: Wire scheduler and lifespan**

Recover only compatible frozen jobs. Current config mismatch yields `skipped_mode_changed`; do not switch route/provider/policy. Compose the active worker with the lifespan-owned `MemorySourceReferenceService`. Recovery tests rerun post-extraction consent mutation scenarios and assert no provider re-send or stale proposal commit. Preserve provider close deduplication and Gate A shutdown order.

- [ ] **Step 5: Run GREEN and Gate A matrix**

```powershell
python -W error -m pytest backend/tests/test_memory_job_service.py backend/tests/test_memory_job_scheduler.py backend/tests/test_chat_memory_candidates.py backend/tests/test_api_chat.py backend/tests/test_api_memory_automation.py -q
```

---

## Task 10: Implement true forget and deletion barriers

**Files:**
- Create: `backend/app/services/memory_forget_service.py`
- Create: `backend/tests/test_memory_forget_service.py`
- Modify: `backend/app/repositories/versioned_memories.py`
- Modify: `backend/app/repositories/memory_audit.py`
- Modify: `backend/app/repositories/memory_embeddings.py`
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add RED forget/fault tests**

Cover all historical canonical tombstones, delete-head shape, candidate-layer redaction, embedding removal, audit JSON reduction, conflict forget resolution, scope generations, HMAC matching for deleted sessions, and rollback when any tombstone/redaction step fails. Construct `MemoryForgetService` with the same lifespan-owned `MemorySourceReferenceService`; use a fixed temporary key in tests. Include a deleted-session fixture where the request supplies the original session ID, the service computes the HMAC, matches version/Evidence provenance, and forgets the correct identities without a session row.

- [ ] **Step 2: Run RED**

```powershell
python -W error -m pytest backend/tests/test_memory_forget_service.py -q
```

- [ ] **Step 3: Implement one atomic forget protocol**

Compute and persist all tombstones before redacting payload. `MemoryForgetService` receives `MemorySourceReferenceService` in its constructor; session-scoped forget hashes the caller's original scope ID locally and never accepts a digest from HTTP. Append a payload-free delete head, then orchestrate the approved protocol through the shared `VersionedMemoryMutationPrimitive`: clear legacy/version/candidate/audit payloads, remove embedding, update conflicts/generations/barrier/exclusions, and write metadata-only activity in one outer transaction. The service must not issue independent state/head/projection SQL. Fault tests inject failure after each low-level operation and assert complete rollback.

- [ ] **Step 4: Run GREEN**

```powershell
python -W error -m pytest backend/tests/test_memory_forget_service.py backend/tests/test_memory_embeddings.py backend/tests/test_versioned_memory_commit.py -q
```

---

## Task 11: Coordinate session deletion

**Files:**
- Create: `backend/app/services/session_deletion_coordinator.py`
- Create: `backend/tests/test_session_deletion_coordinator.py`
- Modify: `backend/app/repositories/sessions.py`
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/app/api/routes/sessions.py`
- Modify: `backend/tests/test_api_sessions.py`

- [ ] **Step 1: Add RED deletion-order tests**

Assert terminal job plus unique audit survive, all direct source IDs become NULL, HMAC references remain, source rows disappear, `foreign_key_check` passes, scoped forget still works, and a late worker has zero side effects.

- [ ] **Step 2: Run RED**

```powershell
python -W error -m pytest backend/tests/test_session_deletion_coordinator.py backend/tests/test_api_sessions.py -q
```

- [ ] **Step 3: Replace direct API deletion**

Use one write transaction: lock/validate session, increment generation, terminalize jobs/audits, fill HMAC references with the same lifespan-owned source-reference service, null direct source IDs, mark Evidence unavailable, then delete messages/session. Do not implicitly forget long-term memories. Test that job plus its unique audit remain and that retained-job maintenance cannot silently cascade-delete the audit.

- [ ] **Step 4: Run GREEN**

```powershell
python -W error -m pytest backend/tests/test_session_deletion_coordinator.py backend/tests/test_api_sessions.py backend/tests/test_memory_forget_service.py -q
```

---

## Task 12: Enforce summary source barriers and unified eligibility

**Files:**
- Create: `backend/tests/test_memory_summary_barrier.py`
- Modify: `backend/app/repositories/session_summaries.py`
- Modify: `backend/app/services/session_summary_service.py`
- Modify: `backend/app/services/context_builder.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_session_summary_service.py`
- Modify: `backend/tests/test_session_summaries.py`
- Modify: `backend/tests/test_context_builder.py`
- Modify: `backend/tests/test_api_chat.py`

- [ ] **Step 1: Add RED pre-send and in-flight tests**

Test whole-session exclusions, conservative source-session expansion, pre-Provider filtering, empty-input skip, barrier change during Provider call, stale API redaction, and zero summary injection into chat.

- [ ] **Step 2: Run RED**

```powershell
python -W error -m pytest backend/tests/test_memory_summary_barrier.py backend/tests/test_session_summary_service.py backend/tests/test_session_summaries.py backend/tests/test_context_builder.py backend/tests/test_api_chat.py -q
```

- [ ] **Step 3: Implement barriers without Gate C behavior**

Filter source IDs before reading/serializing Provider input, freeze barrier/source set, CAS at commit, and return only stale metadata for invalid summaries. Use the same shared V2 eligible-memory query for deterministic chat retrieval, `MemoryEmbeddingRepository.search_active()`, and emotion analysis. Reuse the Task 5 conflicted/open-endpoint fixture and assert all three paths exclude it. Do not inject summaries.

- [ ] **Step 4: Run GREEN**

```powershell
python -W error -m pytest backend/tests/test_memory_summary_barrier.py backend/tests/test_session_summary_service.py backend/tests/test_session_summaries.py backend/tests/test_context_builder.py backend/tests/test_api_chat.py -q
```

---

## Task 13: Expose Gate B APIs and conflict/undo transactions

**Files:**
- Create: `backend/app/services/memory_conflict_resolution.py`
- Create: `backend/tests/test_memory_conflict_resolution.py`
- Create: `backend/tests/test_api_memory_gate_b.py`
- Modify: `backend/app/domain/schemas.py`
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/app/api/routes/memories.py`
- Modify: `backend/tests/test_api_memory_automation.py`

- [ ] **Step 1: Add RED API tests**

Cover independent write consent, strict conflict discriminators, all resolution kinds, archive/forget distinction, undo variants, redacted history, forbidden fields, and 101-item keyset traversal with filter-bound cursors.

- [ ] **Step 2: Run RED**

```powershell
python -W error -m pytest backend/tests/test_memory_conflict_resolution.py backend/tests/test_api_memory_gate_b.py backend/tests/test_api_memory_automation.py -q
```

- [ ] **Step 3: Implement routes before dynamic `/{memory_id}`**

Routes only validate/map HTTP and call services. The `get_memory_forget_service` dependency must compose `MemoryForgetService` with the exact lifespan-owned `app.state.memory_source_reference_service`; the API accepts original scope IDs and never HMAC digests. Never expose HMAC digest, prompt, raw response, hidden reasoning, secret, or deleted payload.

- [ ] **Step 4: Implement conflict and undo transactions**

`choose_*` and replacement resolutions create a third resolved identity; no fake chat Evidence is created. Forget resolution stays inside forget. Undo create/supersede/support follows the approved rules; conflict undo directs users to resolution. `MemoryConflictResolutionService` and undo orchestration must call the shared `VersionedMemoryMutationPrimitive` inside one outer transaction and may not directly update formal state/head/projection. Add fault-injection assertions that state/head/version, legacy projection, activity, and conflict closure all roll back together.

- [ ] **Step 5: Run GREEN and API regression**

```powershell
python -W error -m pytest backend/tests/test_memory_conflict_resolution.py backend/tests/test_api_memory_gate_b.py backend/tests/test_api_memory_automation.py backend/tests/test_api_memories.py backend/tests/test_api_sessions.py -q
```

---

## Task 14: Add the minimum Gate B MemoryPanel UI

**Files:**
- Create: `frontend/src/components/MemoryAutomationControls.tsx`
- Create: `frontend/src/components/MemoryAutomationControls.test.tsx`
- Create: `frontend/src/components/MemoryConflictPanel.tsx`
- Create: `frontend/src/components/MemoryConflictPanel.test.tsx`
- Create: `frontend/src/components/MemoryHistoryDetails.tsx`
- Create: `frontend/src/components/MemoryHistoryDetails.test.tsx`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.tsx`
- Modify: `frontend/src/components/ChatLayout.tsx`
- Modify: `frontend/src/components/MemoryPanel.tsx`
- Modify: `frontend/src/components/MemoryPanel.test.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Add RED component/API tests**

Test independent local write disclosure, generation-safe consent updates, source/state badges, lazy history/Evidence pagination, conflict actions, separate archive/forget controls, confirmation text, keyboard/accessibility labels, and no rendering of deleted payload/HMAC references.

- [ ] **Step 2: Run RED**

```powershell
Set-Location "<project-root>\frontend"
npm test -- --run src/components/MemoryAutomationControls.test.tsx src/components/MemoryConflictPanel.test.tsx src/components/MemoryHistoryDetails.test.tsx src/components/MemoryPanel.test.tsx src/App.test.tsx
```

- [ ] **Step 3: Implement minimum UI only**

Keep existing manual/candidate UI. Add consent, V2 badges, history/Evidence details, conflict management, archive/forget, undo, and non-blocking job state. Do not add Persona, relationship, summary injection, Electron, or visual assets.

- [ ] **Step 4: Run GREEN and frontend regression**

```powershell
npm test -- --run src/components/MemoryAutomationControls.test.tsx src/components/MemoryConflictPanel.test.tsx src/components/MemoryHistoryDetails.test.tsx src/components/MemoryPanel.test.tsx src/App.test.tsx
npm test
npm run typecheck
npm run build
```

---

## Task 15: Perform Gate B acceptance and independent review

**Files:**
- Create: `backend/tests/test_gate_b_http_smoke.py`
- Create: `backend/tests/test_gate_b_privacy_contract.py`
- Create: `docs/automatic-memory-gate-b-acceptance-2026-07-19.md`
- Modify: `CLAUDE.md` only after every acceptance condition passes

- [ ] **Step 1: Run focused warning-strict backend tests**

```powershell
Set-Location "<project-root>"
$env:PYTHONPATH = "$PWD;$PWD\backend"
python -W error -m pytest backend/tests/test_versioned_memory_migration.py backend/tests/test_memory_source_reference.py backend/tests/test_versioned_memory_repository.py backend/tests/test_versioned_memory_mutation.py backend/tests/test_memory_commit_policy.py backend/tests/test_versioned_memory_commit.py backend/tests/test_memory_write_dispatch.py backend/tests/test_memory_forget_service.py backend/tests/test_session_deletion_coordinator.py backend/tests/test_memory_summary_barrier.py backend/tests/test_memory_conflict_resolution.py backend/tests/test_api_memory_gate_b.py -q
```

- [ ] **Step 2: Run complete backend and frontend verification**

```powershell
python -W error -m pytest backend/tests -q
Set-Location frontend
npm test
npm run typecheck
npm run build
```

- [ ] **Step 3: Run reproducible HTTP smoke without cloud extraction**

Implement named `TestClient` tests in `backend/tests/test_gate_b_http_smoke.py`. Every test uses `tmp_path` for both `DATABASE_URL` and `MEMORY_SOURCE_REFERENCE_KEY_PATH`, clears real provider keys, and drives actual session/chat/consent/memory APIs. Include named tests for:

```text
no write grant                 → zero extractor, zero active mutation
local/fake + exact write grant → create/support/supersede/conflict evidence
remote consent only            → zero remote send
open conflict                  → zero chat/emotion fact input
true forget                    → no readable DB/API/log payload and no revival
shadow_auto                    → Gate A active mutation count remains zero
```

Run:

```powershell
python -W error -m pytest backend/tests/test_gate_b_http_smoke.py -q
```

No test contacts Anthropic or DeepSeek.

- [ ] **Step 4: Run automated privacy contract checks**

Implement `backend/tests/test_gate_b_privacy_contract.py`. It must inspect the isolated SQLite schema/rows, API JSON, captured logs, `.env.example`, and test-rendered frontend fixtures for forbidden names or deleted sentinel payload. It must also verify raw HMAC key bytes and resulting digest are absent from API/log/docs/Git diff text; approved metadata-only columns are allowlisted explicitly. Run:

```powershell
python -W error -m pytest backend/tests/test_gate_b_privacy_contract.py -q
Set-Location frontend
npm test -- --run src/components/MemoryPanel.test.tsx src/components/MemoryHistoryDetails.test.tsx
Set-Location ..
git diff --check
```

- [ ] **Step 5: Run independent code review**

Review the complete uncommitted Gate B diff against the approved specification and Gate A contract. Fix all confirmed critical/high findings, rerun affected suites, and obtain an explicit approval verdict.

- [ ] **Step 6: Check the diff**

```powershell
git diff --check
git status --short
```

Do not stage or commit.

- [ ] **Step 7: Record actual evidence and update stage status**

Write exact commands, counts, HTTP IDs/outcomes, DB before/after checks, review verdict, privacy scans, and unverified limits. Only then mark Gate B complete in `CLAUDE.md`. Gate C remains blocked pending a new design/plan cycle.

---

## Plan self-review

### Specification coverage

- Dual consent and zero-extractor write fence: Tasks 8–9.
- Version chain, Evidence, conflict, grounding, CAS: Tasks 3–7.
- Unified manual/candidate mutations and eligibility: Tasks 4–5.
- True forget, all historical tombstones, candidate/audit/embedding redaction: Task 10.
- Session deletion, retained job/audit, HMAC-only provenance: Tasks 2–3 and 11.
- Summary source barrier without injection: Task 12.
- API/keyset/conflict/undo: Task 13.
- Minimum UI: Task 14.
- Gate A/Stage 1–4 regression and acceptance: Task 15.

### Placeholder and type consistency scan

- No `TBD`, `TODO`, “similar to”, or undefined future helper remains.
- New helper/service names are introduced in the task that creates them before later use.
- `MemoryWriteDispatchFence` is distinct from `MemoryExtractionDispatchFence`.
- `VersionedMemoryMutationService` owns user mutations; `VersionedMemoryCommitService` owns automatic proposal commits; `MemoryForgetService` owns destructive forget.
- `memory_record_states` is authoritative for V2 eligibility; legacy `memories.status` remains compatible.
- The plan never replays Gate A shadow proposal content and never introduces Gate C behavior.
