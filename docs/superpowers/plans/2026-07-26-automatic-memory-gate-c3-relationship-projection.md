# Gate C3 Relationship Ledger and Deterministic Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Gate C3 as a local-only, append-only relationship ledger sourced exclusively from exact current Gate B memory versions, with durable suppression, deterministic bounded projections, privacy-safe C1 context injection, an independent RelationshipPanel, and final integrated Gate C evaluation.

**Architecture:** Add a strict C3 contract and additive SQLite migration, including an explicit immutable `canonical_subject_code` on memory versions so relationship facts are never guessed from memory prose. A local durable reconciler converts exact eligible Gate B heads into idempotent apply/revoke events, while append-only authority decisions and conflict lineage prevent reapplication across edits, recovery, resolution, and rule upgrades. Immutable projections are independently revalidated at read and pre-chat dispatch time; invalid or stale state becomes a neutral relationship view without blocking chat.

**Tech Stack:** Python 3.12, FastAPI, SQLite, asyncio, pytest/pytest-asyncio, React, TypeScript, Vite, Vitest, Testing Library.

---

## Governing documents and non-negotiable boundaries

Read these before every task:

- `CLAUDE.md`
- `docs/superpowers/specs/2026-07-21-automatic-memory-gate-c3-relationship-projection-design.md`
- `docs/superpowers/specs/2026-07-21-automatic-memory-gate-c2-controlled-summary-design.md`
- `docs/superpowers/plans/2026-07-22-automatic-memory-gate-c2-controlled-summary.md`
- `docs/automatic-memory-gate-c2-acceptance-2026-07-25.md`
- `docs/superpowers/specs/2026-07-21-automatic-memory-gate-c1-persona-context-design.md`
- `docs/superpowers/plans/2026-07-21-automatic-memory-gate-c1-persona-context.md`
- Gate B design, plan, and acceptance records referenced by `CLAUDE.md`

The working tree is already dirty. Do not run `git add`, `git commit`, `git push`, `git reset`, `git restore`, `git clean`, or `git stash`. Each task names a suggested future commit boundary, but no Git mutation is authorized.

Gate C3 is local-only and adds no extractor, model, Provider, remote route, or consent. C2 summaries, raw messages, assistant output, Provider reasoning, Evidence counts/retractions, Persona content, and Stage 4 emotion state/events can never source a relationship fact. Relationship code must not mutate memory, Persona, summary, or emotion state. Do not implement Electron, Live2D, private-media ingestion, voice cloning, packaging, distribution, or official-character/real-person/consciousness claims.

## Frozen C3 contracts

### Single local scope and versions

C3 keeps the current single-user architecture and freezes `RELATIONSHIP_SCOPE_ID = "default"`; it does not pretend to implement multi-user isolation.

Create `backend/app/services/relationship_contract.py` with:

```python
RELATIONSHIP_SCOPE_ID = "default"
RELATIONSHIP_EVENT_SCHEMA_VERSION = "relationship-event-v1"
RELATIONSHIP_RULE_VERSION = "relationship-rules-v1"
RELATIONSHIP_PROJECTION_RULE_VERSION = "relationship-projection-v1"
RELATIONSHIP_AUTHORITY_SCHEMA_VERSION = "relationship-authority-v1"
RELATIONSHIP_RECONCILE_JOB_VERSION = "relationship-reconcile-job-v1"
RELATIONSHIP_AUDIT_SCHEMA_VERSION = "relationship-audit-v1"
RELATIONSHIP_INTEGRITY_VERSION = "relationship-integrity-v1"
RELATIONSHIP_OBSERVED_TIME_DERIVATION_VERSION = "memory-version-created-at-utc-v1"
RELATIONSHIP_FIXTURE_SCHEMA_VERSION = "gate-c3-replay-v1"
CONTEXT_COMPOSER_VERSION_C3 = "context-composer-v3"
CONTEXT_DATA_ENCODER_VERSION_C3 = "context-data-json-v3"
CONTEXT_MANIFEST_VERSION_C3 = "context-manifest-v3"

CANONICAL_RELATIONSHIP_SUBJECT_CODES = (
    "preferred_address",
    "shared_experience",
    "non_external_commitment",
)

PREFERRED_ADDRESS_MAX_CHARACTERS = 32
RELATIONSHIP_MIN_CONFIDENCE = 0.75
RELATIONSHIP_MIN_IMPORTANCE = 2
FAMILIARITY_BASELINE = 0.40
FAMILIARITY_MIN = 0.0
FAMILIARITY_MAX = 1.0
FAMILIARITY_PER_EVENT_CAP = 0.08
FAMILIARITY_PER_SOURCE_LIFETIME_CAP = 0.10
SHARED_EXPERIENCE_DELTA = 0.04
NON_EXTERNAL_COMMITMENT_DELTA = 0.03
RELATIONSHIP_CONTEXT_MAX_CHARACTERS_DEFAULT = 600
RELATIONSHIP_RECONCILE_MAX_ATTEMPTS_DEFAULT = 3
RELATIONSHIP_RECOVERY_STALE_SECONDS_DEFAULT = 300
```

### Strict source classification

Add nullable `canonical_subject_code` to `memory_versions`. It is an explicit immutable source-version field, not metadata and not a derived label.

- `preferred_address` is allowed for `relationship_event`, `preference`, and `user_fact`.
- `shared_experience` and `non_external_commitment` are allowed only for `relationship_event`.
- Manual create/edit and conflict replacement accept an explicit enum field.
- Candidate confirmation accepts an explicit enum field in a new body; an omitted classification stays uncoded and is skipped. Candidate metadata never grants relationship classification.
- User edits preserve the current code when the field is omitted and set/clear it only when explicitly present.
- `choose_left`/`choose_right` copy the selected exact version's code to the new resolved version.
- Gate B automatic create/supersede versions remain uncoded (`canonical_subject_code=None`) in C3 v1. `MemoryGovernorProposal.subject`, `content`, and `canonical_key_hint` are untrusted free text and never map to a relationship code. An automatic memory can become eligible only after an explicit user edit/classification creates a `user_edit` version with the enum field.
- Legacy versions and versions without the explicit field are skipped. No migration guesses a value from `subject`, `content`, `metadata_json`, hashes, message text, summary text, or emotion state.
- For `preferred_address`, the exact memory-version `content` must itself be the intended address and pass the bounded validator. C3 never extracts a substring from a sentence.

Preferred-address validation is deterministic: NFKC normalize, remove Unicode `Cf`, collapse surrounding whitespace, reject internal newline/control characters, require 1–32 Unicode code points, and return the complete normalized value without truncation.

### Event rules and bounds

- `preferred_address` apply payload is exactly `{"address": <validated text>}` and has no delta.
- `shared_experience` payload is exactly `{"category":"shared_experience","reason_code":"allowlisted_current_memory","delta":0.04}`.
- `non_external_commitment` payload is exactly `{"category":"non_external_commitment","reason_code":"allowlisted_current_memory","delta":0.03}`.
- Eligibility requires an exact active current head, non-redacted payload, no open conflict, an allowed source kind (`manual`, `candidate`, `automatic`, `user_edit`, `user_revert`), confidence at least `0.75`, importance at least `2`, valid explicit subject code, supported rule version, and effective authority not suppressed.
- Evidence and Evidence retractions are not queried by the rule engine.
- Familiarity starts at `0.40`, each event is clamped to `[-0.08, 0.08]`, each source memory contributes at most `0.10` across all effective versions, and the total is clamped to `[0.0, 1.0]`.
- C3 v1 has only the two positive fixed numeric mappings above. Adding a negative event requires a reviewed new rule version.
- Familiarity buckets and summary codes are fixed:
  - `[0.00, 0.35)`: `reserved`
  - `[0.35, 0.55)`: `steady`
  - `[0.55, 0.75)`: `familiar`
  - `[0.75, 1.00]`: `close`

### Semantic ordering and integrity

`observed_at` is the exact source `memory_versions.created_at`, normalized to UTC. Event processing time never affects semantic order. The fold key is exactly:

```text
observed_at ASC,
source_memory_id ASC,
source_memory_version_id ASC,
event_type ASC,
subject_code ASC,
event_id ASC
```

Private SHA-256 fingerprints use canonical UTF-8 JSON with sorted keys and compact separators. They bind complete authority lineage, source snapshots, event semantics, projection inputs, rule/schema versions, and Persona provenance. Fingerprints never enter public API responses, normal logs, frontend state, acceptance docs, or context manifests.

The C3 schema resolves two implicit requirements from the approved design explicitly:

- every relationship event stores `scope_id=RELATIONSHIP_SCOPE_ID` so revoke same-scope constraints are enforceable, and stores a private `integrity_fingerprint` so event integrity can be independently checked;
- `relationship_authority_epoch(scope_id, generation, updated_at)` is a singleton-per-scope monotonic public-safe CAS epoch. Every authority decision or lineage insertion increments it in the same transaction. APIs may expose this integer as `authority_epoch`, while the complete inherited-authority fingerprint remains private. Re-enable requires expected own decision ID/generation plus expected `authority_epoch`; the server captures and transactionally rechecks the private closure fingerprint. The global epoch may conservatively reject an unrelated concurrent authority mutation, but can never permit stale work.

### Public and context boundaries

The verified internal projection snapshot may contain private fingerprints and exact event IDs. Public/API/context views may contain only:

```text
projection_id
projection_version
familiarity_bucket
preferred_address (nullable, resolved and revalidated at read time)
relationship_summary_code
persona_artifact_id
projection_rule_version
contributing_event_count
```

The assistant manifest stores only projection ID/version. It never stores preferred-address text, source-memory content, event payload, event list, authority decisions, lineage, or fingerprints.

## File responsibility map

### New backend files

- `backend/app/domain/relationship.py` — C3 enums and immutable internal/public dataclasses.
- `backend/app/repositories/relationship_migration.py` — additive transactional schema/migration and trigger postconditions.
- `backend/app/repositories/relationship_sources.py` — exact current Gate B source tuples and independent eligibility rechecks.
- `backend/app/repositories/relationship_ledger.py` — events, authority decisions, conflict lineage, jobs/audits, recovery, and safe pages.
- `backend/app/repositories/relationship_projections.py` — immutable snapshots, CAS pointer, verified read view.
- `backend/app/services/relationship_contract.py` — frozen versions, allowlist, validation, canonical fingerprints, bounds.
- `backend/app/services/relationship_rules.py` — pure strict source-to-event mapping.
- `backend/app/services/relationship_authority.py` — effective semantic authority and lineage closure.
- `backend/app/services/relationship_projector.py` — deterministic event validation/fold and immutable activation.
- `backend/app/services/relationship_reconciler.py` — reservation/commit state machine and full reconcile.
- `backend/app/services/relationship_scheduler.py` — local durable scheduling/recovery.
- `backend/app/services/relationship_dispatch.py` — priority disclosure fence and pre-send revalidation.
- `backend/app/services/relationship_hooks.py` — narrow mutation notification protocol and no-op implementation.
- `backend/app/services/relationship_privacy.py` — in-transaction revoke/suppress/address clearing/safe projection primitive.
- `backend/app/api/routes/relationships.py` — safe local projection/ledger/job/audit and mutation APIs.

### New frontend files

- `frontend/src/components/RelationshipPanel.tsx` — independent collapsible local relationship panel.
- `frontend/src/components/RelationshipPanel.test.tsx` — safe rendering, confirmations, source-link and race/error isolation tests.

### Existing files modified

- `.env.example`
- `backend/app/core/config.py`
- `backend/app/domain/schemas.py`
- `backend/app/repositories/sqlite.py`
- `backend/app/repositories/versioned_memories.py`
- `backend/app/repositories/context_sources.py`
- `backend/app/services/memory_commit_policy.py`
- `backend/app/services/versioned_memory_mutation.py`
- `backend/app/services/versioned_memory_commit.py`
- `backend/app/services/memory_conflict_resolution.py`
- `backend/app/services/memory_forget_service.py`
- `backend/app/services/session_deletion_coordinator.py`
- `backend/app/services/persona_contract.py`
- `backend/app/services/persona_service.py`
- `backend/app/services/context_data_encoder.py`
- `backend/app/services/context_composer.py`
- `backend/app/services/chat_service.py`
- `backend/app/api/dependencies.py`
- `backend/app/api/routes/memories.py`
- `backend/app/api/routes/sessions.py`
- `backend/app/main.py`
- `frontend/src/api/types.ts`
- `frontend/src/api/client.ts`
- `frontend/src/App.tsx`
- `frontend/src/App.test.tsx`
- `frontend/src/components/ChatLayout.tsx`
- `frontend/src/components/MemoryPanel.tsx`
- `frontend/src/components/MemoryPanel.test.tsx`
- `frontend/src/styles.css`
- `CLAUDE.md` only after final Gate C3 acceptance and independent approval

---

### Task 1: Freeze C3 contracts, explicit source codes, and configuration

**Files:**
- Create: `backend/app/services/relationship_contract.py`
- Modify: `backend/app/core/config.py`
- Modify: `.env.example`
- Test: `backend/tests/test_relationship_contract.py`
- Test: `backend/tests/test_config.py`

- [ ] **Step 1: Write RED contract tests**

Test the exact constants above, canonical JSON fingerprint stability, NFKC preferred-address validation, strict source-code/type matrix, familiarity thresholds, and rejection of newline/control/oversized values. Test settings defaults and bounds:

```python
assert settings.relationship_context_max_characters == 600
assert settings.relationship_reconcile_max_attempts == 3
assert settings.relationship_recovery_stale_seconds == 300
```

Require ranges `128..2000`, `1..10`, and `30..3600`; require the context cap not exceed `chat_dynamic_context_max_characters`. Verify `Settings.redacted()` contains only non-secret C3 settings and no new credential or asset path.

- [ ] **Step 2: Run RED tests**

Run:

```text
python -W error -m pytest backend/tests/test_relationship_contract.py backend/tests/test_config.py -q
```

Expected: failures because C3 contracts/settings do not exist.

- [ ] **Step 3: Implement minimal immutable contracts and settings**

Use existing `_get_bounded_int_env` and cross-field validation in `load_settings()`. Add only:

```text
RELATIONSHIP_CONTEXT_MAX_CHARACTERS=600
RELATIONSHIP_RECONCILE_MAX_ATTEMPTS=3
RELATIONSHIP_RECOVERY_STALE_SECONDS=300
```

No setting enables an unreviewed subject, event type, source kind, or delta. No setting acts as consent because C3 is local deterministic processing with explicit per-source memory/relationship actions.

- [ ] **Step 4: Run GREEN tests and static compile**

Run the RED command plus:

```text
python -m compileall -q backend/app
```

Expected: pass.

- [ ] **Step 5: Record boundary**

Suggested future commit boundary: `feat: freeze Gate C3 relationship contracts` (record only; do not mutate Git).

---

### Task 2: Add C3 domain types and explicit canonical subject to memory APIs

**Files:**
- Create: `backend/app/domain/relationship.py`
- Modify: `backend/app/domain/models.py`
- Modify: `backend/app/domain/schemas.py`
- Modify: `frontend/src/api/types.ts`
- Test: `backend/tests/test_relationship_domain.py`
- Test: `backend/tests/test_api_memories.py`

- [ ] **Step 1: Write RED domain/schema tests**

Define and test enums for event kind/type, payload state, authority action/action kind, job status/outcome, summary code, and immutable dataclasses for:

```python
RelationshipSourceSnapshot
RelationshipEvent
RelationshipAuthoritySnapshot
RelationshipProjectionSnapshot
RelationshipProjectionView
RelationshipReconcileJob
RelationshipAudit
```

Add `canonical_subject_code` to the frozen `MemoryVersion` dataclass in `backend/app/domain/models.py`, memory create/update/current/version responses, conflict replacement requests, and a `ConfirmMemoryCandidateRequest` body with the same optional field. `MemoryResponse` obtains it only by joining the exact current `MemoryVersion`; legacy/pending/no-version rows return `null`. Reject unknown values and invalid memory-type/code pairs. Verify omission and explicit `null` remain distinguishable for update requests through `request.model_fields_set`, and add create/update/list/version round-trip tests.

- [ ] **Step 2: Run RED tests**

```text
python -W error -m pytest backend/tests/test_relationship_domain.py backend/tests/test_api_memories.py -q
```

Expected: schema fields/types are missing.

- [ ] **Step 3: Implement strict models**

Use `Literal["preferred_address", "shared_experience", "non_external_commitment"] | None` in Pydantic and equivalent TypeScript unions. Public dataclasses must not include `source_set_hash`, content hashes, internal fingerprints, raw memory prose, Prompt, Provider data, HMAC, or asset paths.

- [ ] **Step 4: Run GREEN tests**

Run the RED command and frontend typecheck:

```text
npm --prefix frontend run typecheck
```

Expected: pass after TypeScript types are synchronized.

- [ ] **Step 5: Record boundary**

Suggested future commit boundary: `feat: add Gate C3 domain contracts` (record only).

---

### Task 3: Add the transactional C3 schema and append-only invariants

**Files:**
- Create: `backend/app/repositories/relationship_migration.py`
- Modify: `backend/app/repositories/sqlite.py`
- Test: `backend/tests/test_relationship_migration.py`
- Test: `backend/tests/test_relationship_schema_invariants.py`
- Test: `backend/tests/test_memory_automation_migration.py`
- Test: `backend/tests/test_summary_c2_migration.py`

- [ ] **Step 1: Write RED migration/invariant tests**

Create old Gate B/C1/C2 fixture databases, run `init_db`, and assert preservation plus these C3 tables:

```text
relationship_events
relationship_authority_decisions
relationship_authority_epoch
relationship_memory_lineage
relationship_reconcile_jobs
relationship_job_audits
relationship_audits
relationship_projections
relationship_projection_active_state
relationship_redaction_guards
```

Require `memory_versions.canonical_subject_code` nullable with a strict CHECK. Test:

- apply partial uniqueness on `(scope_id, source_memory_version_id, rule_version, event_type, subject_code)`;
- event `scope_id`, `event_schema_version`, and private `integrity_fingerprint` are required and immutable;
- one revoke per apply, same-scope/apply-only target, no revoke payload;
- ordinary event update/delete rejection;
- only guarded `active -> redacted` apply payload clearing;
- append-only linear authority generations and predecessor chain;
- authority/lineage writes monotonically increment `relationship_authority_epoch` by exact CAS;
- immutable lineage rows;
- immutable job reservation snapshot fields;
- immutable projections and projection pointer generation CAS;
- metadata-only audit/job schemas;
- foreign-key check and fault rollback.

- [ ] **Step 2: Run RED migration tests**

```text
python -W error -m pytest backend/tests/test_relationship_migration.py backend/tests/test_relationship_schema_invariants.py backend/tests/test_memory_automation_migration.py backend/tests/test_summary_c2_migration.py -q
```

Expected: C3 schema absent.

- [ ] **Step 3: Implement one-transaction migration**

`migrate_gate_c3(connection)` must run inside `init_db`'s existing transaction after `migrate_gate_c2`. Add the memory-version column, drop/recreate `trg_memory_versions_append_only_update` so the new field is immutable, then create C3 tables/triggers/indexes. If an experimental relationship projection table contains `preferred_address` or `preferred_address_text`, set every such column to `NULL` before feature availability and assert no non-null value remains. Never infer/backfill canonical subject codes.

- [ ] **Step 4: Run GREEN and full migration regression**

Run the RED command plus:

```text
python -W error -m pytest backend/tests/test_persona_migration.py backend/tests/test_summary_c2_migration.py backend/tests/test_memory_automation_migration.py -q
```

Expected: pass.

- [ ] **Step 5: Record boundary**

Suggested future commit boundary: `feat: add append-only relationship schema` (record only).

---

### Task 4: Persist explicit canonical subject codes through every Gate B version path

**Files:**
- Modify: `backend/app/services/memory_commit_policy.py`
- Modify: `backend/app/services/versioned_memory_mutation.py`
- Modify: `backend/app/services/versioned_memory_commit.py`
- Modify: `backend/app/repositories/versioned_memories.py`
- Modify: `backend/app/api/routes/memories.py`
- Test: `backend/tests/test_memory_commit_policy.py`
- Test: `backend/tests/test_versioned_memory_mutation.py`
- Test: `backend/tests/test_memory_job_service.py`
- Test: `backend/tests/test_api_memories.py`

- [ ] **Step 1: Write RED lifecycle tests**

Cover manual create, explicit update set/clear, omitted update preserve, candidate confirmation with explicit request classification, candidate confirmation without classification remaining uncoded, automatic create/supersede remaining uncoded until an explicit user edit/classification, user revert, archive, and delete-head behavior. Assert exact codes persist on immutable versions and current APIs. Assert every automatic proposal remains `None` even when `subject` is `"preferred_address"`; values such as `"称呼偏好"`, `"preferred_address:小雪"`, arbitrary prose, summary-like text, `canonical_key_hint`, and sentiment keywords must likewise have zero classification effect.

- [ ] **Step 2: Run RED tests**

```text
python -W error -m pytest backend/tests/test_memory_commit_policy.py backend/tests/test_versioned_memory_mutation.py backend/tests/test_memory_job_service.py backend/tests/test_api_memories.py -q
```

Expected: missing persistence/mapping.

- [ ] **Step 3: Implement minimal explicit propagation**

Add a pure `canonical_relationship_subject_code(memory_type, explicit_subject)` helper in the C3 contract. Pass the code through `VersionedMemoryMutationPrimitive.insert_root`, `insert_successor`, `insert_delete_head`, repository row conversion, and APIs. Preserve existing `subject` and hashes; do not repurpose free-text `subject` as the canonical code. For a coded manual version, compute existing canonical hashes with the code as the canonical subject. For uncoded legacy/manual versions, retain existing compatibility behavior and let C3 skip them.

- [ ] **Step 4: Run GREEN and Gate B regressions**

Run the RED command plus:

```text
python -W error -m pytest backend/tests/test_memory_conflict_resolution.py backend/tests/test_memory_forget_service.py backend/tests/test_gate_b_http_smoke.py backend/tests/test_gate_b_privacy_contract.py -q
```

Expected: pass; Evidence-only support still creates no version/code change.

- [ ] **Step 5: Record boundary**

Suggested future commit boundary: `feat: persist explicit relationship subjects` (record only).

---

### Task 5: Implement exact source snapshots and pure allowlisted rules

**Files:**
- Create: `backend/app/repositories/relationship_sources.py`
- Create: `backend/app/services/relationship_rules.py`
- Test: `backend/tests/test_relationship_sources.py`
- Test: `backend/tests/test_relationship_rules.py`

- [ ] **Step 1: Write RED source/rule tests**

Use exact database rows to cover every eligibility field in design Section 4.1. Require active/current/head/generation/version equality, no redaction, no open conflict, allowed source kind, thresholds, code/type matrix, and exact Persona provenance supplied separately. Assert Evidence table changes and retractions do not alter source snapshot or mapping.

Test strict payload output:

```python
assert rules.map(preferred).payload == {"address": "小雪"}
assert rules.map(shared).payload["delta"] == 0.04
assert rules.map(commitment).payload["delta"] == 0.03
```

Unknown/ambiguous/legacy/uncoded/invalid-address inputs return a metadata-only skipped reason and no event payload.

- [ ] **Step 2: Run RED tests**

```text
python -W error -m pytest backend/tests/test_relationship_sources.py backend/tests/test_relationship_rules.py -q
```

Expected: modules absent.

- [ ] **Step 3: Implement exact reads and pure mapping**

Use a single joined query over `memory_record_states`, exact `memory_versions`, `memories`, and open conflicts. Do not join messages, summaries, emotion, Evidence, memory audit prose, or Provider tables. Return immutable snapshots and recheck the same tuple for reservation, commit, projection validation, and Composer reads.

- [ ] **Step 4: Run GREEN tests**

Run the RED command with `python -m compileall -q backend/app`.

- [ ] **Step 5: Record boundary**

Suggested future commit boundary: `feat: add deterministic relationship source rules` (record only).

---

### Task 6: Implement append-only authority decisions and conflict lineage

**Files:**
- Create: `backend/app/repositories/relationship_ledger.py`
- Create: `backend/app/services/relationship_authority.py`
- Test: `backend/tests/test_relationship_authority.py`
- Test: `backend/tests/test_relationship_lineage.py`

- [ ] **Step 1: Write RED authority tests**

Cover no decision, suppress, ordinary re-enable, inherited suppression, transitive lineage, disagreement, two-parent suppression, resolved-key re-enable, parent suppression after re-enable, stale generation/decision ID, and cyclic/corrupt lineage fail-closed. Require stable sorted closure and private fingerprint but no source text or payload.

Freeze precedence:

```text
own suppress -> suppressed
own reenable bound to the exact current inherited fingerprint -> enabled
otherwise any inherited suppress -> suppressed
otherwise -> enabled
```

A later lineage/parent decision changes the private fingerprint and invalidates the resolved-key override until a new explicit re-enable.

- [ ] **Step 2: Run RED tests**

```text
python -W error -m pytest backend/tests/test_relationship_authority.py backend/tests/test_relationship_lineage.py -q
```

Expected: authority/lineage repository absent.

- [ ] **Step 3: Implement append-only authority service**

Use semantic key `(scope_id, source_memory_id, event_type, subject_code)`. `suppress` and `reenable` append generation `previous + 1` with exact predecessor. Every decision and lineage insertion increments the scope's `relationship_authority_epoch` in the same transaction. Re-enable API inputs later carry public `expected_decision_id`/`expected_decision_generation` and expected `authority_epoch`; for a resolved key with no own decision, the first inherited override uses exactly `expected_decision_id=null` and `expected_decision_generation=0`. The service captures the private inherited fingerprint at start and rechecks the own decision tuple, epoch, and fingerprint in the write transaction. Never return that fingerprint publicly. Test two-parent lineage with no own decision, first re-enable, and a later parent decision invalidating that override. Lineage inserts both conflict sides before resolved memory can reconcile.

- [ ] **Step 4: Run GREEN tests and schema checks**

Run the RED command plus `backend/tests/test_relationship_schema_invariants.py`.

- [ ] **Step 5: Record boundary**

Suggested future commit boundary: `feat: add durable relationship authority` (record only).

---

### Task 7: Implement idempotent apply/revoke ledger operations

**Files:**
- Modify: `backend/app/repositories/relationship_ledger.py`
- Test: `backend/tests/test_relationship_ledger.py`

- [ ] **Step 1: Write RED ledger tests**

Cover apply insertion, duplicate reservation/retry, stable observed time, exact payload schema, ordinary revoke, duplicate revoke, invalid/missing/cross-scope/revoke-of-revoke targets, and guarded preferred-address payload redaction. Verify revoke rows have `payload_json IS NULL`, carry no delta/readable address, and preserve target identity via `revokes_event_id` only.

- [ ] **Step 2: Run RED tests**

```text
python -W error -m pytest backend/tests/test_relationship_ledger.py backend/tests/test_relationship_schema_invariants.py -q
```

Expected: ledger methods absent.

- [ ] **Step 3: Implement transaction-bound primitives**

Append applies with `INSERT ... ON CONFLICT DO NOTHING`, then read the existing exact identity. Revoke the currently effective apply only once. Redaction requires a one-use row in `relationship_redaction_guards`, sets `payload_json=NULL,payload_state='redacted'`, consumes the guard, and can never restore payload.

- [ ] **Step 4: Run GREEN tests**

Run the RED command.

- [ ] **Step 5: Record boundary**

Suggested future commit boundary: `feat: implement append-only relationship ledger` (record only).

---

### Task 8: Build deterministic immutable projections and verified views

**Files:**
- Create: `backend/app/repositories/relationship_projections.py`
- Create: `backend/app/services/relationship_projector.py`
- Test: `backend/tests/test_relationship_projector.py`
- Test: `backend/tests/test_relationship_projection_view.py`
- Test: `backend/tests/test_relationship_determinism.py`

- [ ] **Step 1: Write RED projector tests**

Feed the same event/source/authority set in multiple insertion, reconciliation, delay, and restart orders. Require identical event order, source-event ID list, address winner ID, familiarity, bucket, summary code, and fingerprint. Test duplicate versions, per-event/per-source/total caps, revoked/redacted/stale/conflicted/deleted/suppressed sources, Persona provenance change, invalid rule/schema, corrupt payload, integrity mismatch, pointer CAS conflict, and database rollback.

Test verified address resolution joins the exact selected event and independently rechecks payload, revoke, authority, source head, and integrity. Any failure yields `preferred_address=None`; no projection row contains address text.

- [ ] **Step 2: Run RED tests**

```text
python -W error -m pytest backend/tests/test_relationship_projector.py backend/tests/test_relationship_projection_view.py backend/tests/test_relationship_determinism.py -q
```

Expected: projector absent.

- [ ] **Step 3: Implement pure fold plus immutable activation**

Sort by the frozen key, validate each source through `RelationshipSourceRepository`, validate authority through `RelationshipAuthorityService`, exclude valid revoke targets, group numeric deltas by source memory, cap and clamp, select the reverse-key newest address, and hash canonical inputs. If the current projection has identical canonical semantics and Persona, return it without inserting churn; otherwise insert the next immutable version and CAS-activate it. Unsupported/corrupt state returns a neutral view `(baseline, steady, no address)` without modifying other subsystems.

- [ ] **Step 4: Run GREEN and repeatability tests**

Run the RED command repeatedly with randomized test order controlled by fixed fixture permutations (not runtime randomness).

- [ ] **Step 5: Record boundary**

Suggested future commit boundary: `feat: add deterministic relationship projection` (record only).

---

### Task 9: Implement durable local reconcile jobs and recovery

**Files:**
- Create: `backend/app/services/relationship_reconciler.py`
- Create: `backend/app/services/relationship_scheduler.py`
- Modify: `backend/app/repositories/relationship_ledger.py`
- Test: `backend/tests/test_relationship_reconciler.py`
- Test: `backend/tests/test_relationship_scheduler.py`
- Test: `backend/tests/test_relationship_recovery.py`

- [ ] **Step 1: Write RED state-machine tests**

Cover reservation identity `(current_version_id, rule_version, effective authority generation/private lineage fingerprint)`, unchanged dedup, compatible startup recovery, stale/incompatible terminalization, attempt exhaustion, source change before commit, suppression advancing in flight, open conflict, archive/delete/redaction, eligible apply, old-version revoke, and transaction rollback. Provider/factory counters must remain zero because C3 has no Provider.

- [ ] **Step 2: Run RED tests**

```text
python -W error -m pytest backend/tests/test_relationship_reconciler.py backend/tests/test_relationship_scheduler.py backend/tests/test_relationship_recovery.py -q
```

Expected: services absent.

- [ ] **Step 3: Implement local durable reconciliation**

Reservation stores only IDs, versions, state/generations, private fingerprints, codes, attempts, and timestamps. Commit opens a short write transaction, rechecks every captured field, appends required old-version revokes and at most one new apply, writes metadata-only audit/outcome, and recomputes projection in the same transaction. Full reconcile enumerates memory IDs deterministically and uses the same per-source path; it cannot bypass suppression.

- [ ] **Step 4: Run GREEN tests**

Run the RED command plus relationship ledger/projector tests.

- [ ] **Step 5: Record boundary**

Suggested future commit boundary: `feat: add durable relationship reconciliation` (record only).

---

### Task 10: Wire startup recovery and narrow mutation notifications

**Files:**
- Create: `backend/app/services/relationship_hooks.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/app/services/versioned_memory_mutation.py`
- Modify: `backend/app/services/versioned_memory_commit.py`
- Test: `backend/tests/test_relationship_startup.py`
- Test: `backend/tests/test_relationship_mutation_hooks.py`
- Test: `backend/tests/test_memory_job_service.py`

- [ ] **Step 1: Write RED wiring tests**

Require `create_app` to build one local scheduler, recover existing jobs, perform a deterministic startup convergence scan over every current memory head plus every effective apply whose source may now be stale and every lineage-resolved identity, establish an initial neutral/current projection, expose no remote capability, and shut down cleanly. Verify manual create/update/archive/candidate confirmation and automatic create/supersede/conflict-recording schedule every affected memory ID after their Gate B transaction commits. Evidence-only support may schedule a deduplicated check but must produce zero event/projection semantic change. Inject notifier failure before job reservation, restart, and prove the startup scan reserves missing jobs and converges exactly once without duplicate effects.

- [ ] **Step 2: Run RED tests**

```text
python -W error -m pytest backend/tests/test_relationship_startup.py backend/tests/test_relationship_mutation_hooks.py backend/tests/test_memory_job_service.py -q
```

Expected: wiring absent.

- [ ] **Step 3: Implement a minimal notifier boundary**

Define:

```python
class RelationshipChangeNotifier(Protocol):
    def schedule(self, memory_ids: tuple[str, ...]) -> None: ...
```

Use `NoOpRelationshipChangeNotifier` by default so existing unit constructors remain compatible. Production dependencies inject the scheduler-backed notifier. Calls occur only after successful ordinary transactions; exceptions are caught at this non-privacy notification boundary. Eventual convergence does not rely on the failed callback: startup recovery deterministically scans every exact current head, every effective apply whose source is no longer exact/eligible, and every lineage-created resolved identity, then invokes the same idempotent reservation identity to create any missing jobs. Automatic conflict recording must enqueue both newly conflicted identities, because projection validation already excludes them immediately and recovery appends their revokes. Do not capture large lifespan closures in long-lived objects; use small service objects with explicit fields.

- [ ] **Step 4: Run GREEN and startup regressions**

Run the RED command plus persona/summary startup tests.

- [ ] **Step 5: Record boundary**

Suggested future commit boundary: `feat: wire relationship reconciliation lifecycle` (record only).

---

### Task 11: Integrate conflict lineage and conservative authority transfer atomically

**Files:**
- Modify: `backend/app/services/memory_conflict_resolution.py`
- Modify: `backend/app/services/relationship_authority.py`
- Modify: `backend/app/services/relationship_reconciler.py`
- Test: `backend/tests/test_relationship_conflict_lifecycle.py`
- Test: `backend/tests/test_memory_conflict_resolution.py`

- [ ] **Step 1: Write RED complete conflict matrix**

Cover conflict opening, `choose_left`, `choose_right`, `replace_both`, `both_contextual`, `dismiss_both`, stale work concurrent with opening/resolution, transitive parent suppression, parent disagreement, selected-code copy, explicit replacement code, uncoded replacement, and resolved-key explicit re-enable. Require both archived sides to be invalid immediately and lineage for both sides inserted in the same resolution transaction before a resolved identity can be scheduled.

- [ ] **Step 2: Run RED tests**

```text
python -W error -m pytest backend/tests/test_relationship_conflict_lifecycle.py backend/tests/test_memory_conflict_resolution.py -q
```

Expected: lineage/notification integration absent.

- [ ] **Step 3: Implement atomic lineage recording**

For every resolved identity, insert `(resolved_memory_id, left_id)` and `(resolved_memory_id, right_id)` with conflict and resolution kind before closing the conflict. Copy the selected exact version code for choose-left/right; validate explicit code for replacements. After commit, schedule both parents and resolved ID. `dismiss_both` creates no identity and only schedules old sides for revoke. No text matching may infer ancestry.

- [ ] **Step 4: Run GREEN tests and rollback injection**

Run the RED command with fault checkpoints after resolved identity, lineage, side archive, conflict close, and audit; every injected failure must roll back all of them.

- [ ] **Step 5: Record boundary**

Suggested future commit boundary: `feat: preserve relationship authority through conflicts` (record only).

---

### Task 12: Make true forget and preferred-address redaction remove all readable copies atomically

**Files:**
- Create: `backend/app/services/relationship_privacy.py`
- Create: `backend/app/services/relationship_dispatch.py`
- Modify: `backend/app/services/memory_forget_service.py`
- Modify: `backend/app/services/memory_conflict_resolution.py`
- Modify: `backend/app/services/session_deletion_coordinator.py`
- Modify: `backend/app/api/routes/memories.py`
- Modify: `backend/app/api/routes/sessions.py`
- Modify: `backend/app/api/dependencies.py`
- Test: `backend/tests/test_relationship_true_forget.py`
- Test: `backend/tests/test_relationship_privacy_transactions.py`
- Test: `backend/tests/test_relationship_session_deletion.py`

- [ ] **Step 1: Write RED privacy/race tests**

Generate a random preferred-address sentinel and assert true forget in one transaction:

- captures eligible apply before source redaction;
- appends/ensures revoke;
- appends suppress authority;
- clears apply `payload_json` physically to `NULL`;
- clears source memory/version payload through existing Gate B logic;
- activates a projection with no address;
- leaves metadata-only no-revival rows;
- removes the sentinel from every event/projection/read/API/context/log/job/audit surface.

Inject faults after each operation and prove full rollback. Race queued chat disclosure against forget/redaction and require the queued privacy mutation to win before Provider dispatch. Session deletion keeps an event only when its memory remains independently eligible; if deletion invokes forget/invalidation, relationship privacy completes before message/session deletion commits.

- [ ] **Step 2: Run RED tests**

```text
python -W error -m pytest backend/tests/test_relationship_true_forget.py backend/tests/test_relationship_privacy_transactions.py backend/tests/test_relationship_session_deletion.py -q
```

Expected: privacy primitive/fence absent.

- [ ] **Step 3: Implement in-transaction privacy primitive and fence order**

Call `RelationshipPrivacyPrimitive` inside the existing Gate B write transaction before `_primitive.redact_versions`. It must not open a nested independent connection. Reuse the C2 `PriorityAsyncFence` mechanism through `RelationshipDisclosureFence`.

Freeze lock order everywhere:

```text
SummaryProcessingFence -> RelationshipDisclosureFence -> SummaryDisclosureFence
```

Memory forget and session deletion routes acquire relationship before summary disclosure. Relationship-only mutations acquire only relationship disclosure. No code acquires these in reverse order.

- [ ] **Step 4: Run GREEN plus Gate B/C2 privacy regressions**

```text
python -W error -m pytest backend/tests/test_relationship_true_forget.py backend/tests/test_relationship_privacy_transactions.py backend/tests/test_relationship_session_deletion.py backend/tests/test_memory_forget_service.py backend/tests/test_summary_true_forget.py backend/tests/test_summary_session_deletion.py -q
```

Expected: pass.

- [ ] **Step 5: Record boundary**

Suggested future commit boundary: `feat: integrate relationship true forget` (record only).

---

### Task 13: Support Persona switches, rule upgrades, and safe full rebuild

**Files:**
- Modify: `backend/app/services/persona_service.py`
- Modify: `backend/app/services/relationship_reconciler.py`
- Modify: `backend/app/services/relationship_projector.py`
- Modify: `backend/app/api/dependencies.py`
- Test: `backend/tests/test_relationship_persona_switch.py`
- Test: `backend/tests/test_relationship_rule_upgrade.py`
- Test: `backend/tests/test_relationship_full_rebuild.py`
- Test: `backend/tests/test_persona_service.py`

- [ ] **Step 1: Write RED upgrade/rebuild tests**

Persona activation must create no event and preserve numerical state while activating a projection with new Persona provenance. Full rebuild must produce identical semantic output, not multiply delta, not restore suppressed keys, and neutralize corrupt state. A simulated v2 rule must append ordinary revokes for v1-invalid applies with metadata-only `rule_migration`, then append only eligible unsuppressed v2 applies; it must never update old event semantics or introduce `rule_migration` as an event type.

- [ ] **Step 2: Run RED tests**

```text
python -W error -m pytest backend/tests/test_relationship_persona_switch.py backend/tests/test_relationship_rule_upgrade.py backend/tests/test_relationship_full_rebuild.py backend/tests/test_persona_service.py -q
```

Expected: hooks/upgrades absent.

- [ ] **Step 3: Implement local recompute/reconcile paths**

Add an optional no-op projection notifier to Persona activation and inject it in production. Startup and activation schedule/perform projection recompute with the exact active Persona artifact. Full rebuild invokes the same source/authority/reconciler/projector functions as normal processing. Do not create a separate permissive migration path.

- [ ] **Step 4: Run GREEN tests**

Run the RED command plus projection determinism tests.

- [ ] **Step 5: Record boundary**

Suggested future commit boundary: `feat: make relationship projections recomputable` (record only).

---

### Task 14: Encode and pre-dispatch revalidate relationship context through C1

**Files:**
- Modify: `backend/app/services/persona_contract.py`
- Modify: `backend/app/repositories/context_sources.py`
- Modify: `backend/app/services/context_data_encoder.py`
- Modify: `backend/app/services/context_composer.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/app/api/dependencies.py`
- Test: `backend/tests/test_context_data_encoder.py`
- Test: `backend/tests/test_context_composer.py`
- Test: `backend/tests/test_relationship_chat_disclosure.py`
- Test: `backend/tests/test_chat_service.py`
- Test: `backend/tests/test_api_chat.py`

- [ ] **Step 1: Write RED context/disclosure tests**

Bump C1 versions to C3 constants. Require the encoder's existing `relationships` array to contain at most one object:

```json
{
  "authority": "derived_relationship_projection_not_fact",
  "projection_id": "...",
  "projection_version": 1,
  "familiarity_bucket": "steady",
  "preferred_address": "<escaped bounded value or null>",
  "relationship_summary_code": "steady",
  "persona_artifact_id": "...",
  "projection_rule_version": "relationship-projection-v1"
}
```

Verify JSON/HTML/Prompt-injection escaping across fake, Anthropic, and DeepSeek payload normalization. Assert the relationship layer never changes Persona/system rules. Test trimming order: summaries first, then relationship preferred address neutralization, then relationship removal, then structured memory/recent/emotion according to the existing C2 rules. Manifest stores projection ID/version only.

Race suppression/redaction/forget/projection corruption after initial composition but before Provider I/O. Require pre-send revalidation and recomposition to neutral/no relationship while chat succeeds. Provider sees no forgotten sentinel.

- [ ] **Step 2: Run RED tests**

```text
python -W error -m pytest backend/tests/test_context_data_encoder.py backend/tests/test_context_composer.py backend/tests/test_relationship_chat_disclosure.py backend/tests/test_chat_service.py backend/tests/test_api_chat.py -q
```

Expected: C2 rejects non-empty relationship input.

- [ ] **Step 3: Implement verified source snapshot and nested disclosure**

Extend `ContextSourceSnapshot` with an internal relationship capture selected by `RelationshipProjectionRepository`. Extend `ContextComposer` result with real projection ID/version. Add `RelationshipInjectionService` using the relationship fence and `ContextSourceRepository.revalidate()`; make it the outer context and preserve the existing summary fence as inner context. If any relationship validation fails, replace it with a neutral view or omit it and recompose before `_generate`. Chat exceptions from relationship reads remain isolated.

- [ ] **Step 4: Run GREEN and C1/C2 context regressions**

Run the RED command plus all Gate C1/C2 context/privacy tests.

- [ ] **Step 5: Record boundary**

Suggested future commit boundary: `feat: inject verified relationship projections` (record only).

---

### Task 15: Add safe local relationship APIs

**Files:**
- Create: `backend/app/api/routes/relationships.py`
- Modify: `backend/app/domain/schemas.py`
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api_relationships.py`

- [ ] **Step 1: Write RED API tests**

Implement and test:

```text
GET  /relationship/projection
GET  /relationship/events?limit=&cursor=
GET  /relationship/jobs?limit=&cursor=
GET  /relationship/audits?limit=&cursor=
POST /relationship/reconcile
POST /relationship/rebuild
POST /relationship/events/{apply_event_id}/suppress
POST /relationship/events/{apply_event_id}/redact
POST /relationship/authorities/{source_memory_id}/{event_type}/{subject_code}/reenable
```

All mutation requests use `extra="forbid"`, expected projection/authority decision ID and generation as applicable, and fixed actions/reasons. Redaction requires `confirm_irreversible: true`. Re-enable requires `expected_decision_id: str | null`, exact current decision generation (`0` when the ID is null), and expected public `authority_epoch`; the server privately captures/rechecks the inherited fingerprint without exposing it.

- [ ] **Step 2: Run RED API tests**

```text
python -W error -m pytest backend/tests/test_api_relationships.py -q
```

Expected: router absent/404.

- [ ] **Step 3: Implement bounded safe projections**

Event pages return apply/revoke metadata, bounded address only if the exact apply remains readable and eligible, and `source_memory_id` only if the existing Memory API would still return that memory as readable/eligible. Never return raw event payload JSON, source version IDs for deleted/redacted sources, lineage closure, private fingerprints, hashes/HMAC, summary/emotion data, Prompt/raw response, credentials, or asset paths. Jobs/audits are metadata-only. All operations are local and the capabilities response explicitly says no remote extraction/consent exists.

- [ ] **Step 4: Run GREEN, OpenAPI, and privacy-key tests**

Run the RED command and assert forbidden names are absent from OpenAPI/public JSON.

- [ ] **Step 5: Record boundary**

Suggested future commit boundary: `feat: add safe relationship APIs` (record only).

---

### Task 16: Add explicit memory classification UI and the independent RelationshipPanel

**Files:**
- Create: `frontend/src/components/RelationshipPanel.tsx`
- Create: `frontend/src/components/RelationshipPanel.test.tsx`
- Modify: `frontend/src/components/MemoryPanel.tsx`
- Modify: `frontend/src/components/MemoryPanel.test.tsx`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.tsx`
- Modify: `frontend/src/components/ChatLayout.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write RED frontend API/panel/state tests**

MemoryPanel must provide an optional explicit relationship-subject select for manual create/edit and candidate confirmation with fixed labels, preserve/clear semantics on edit, and explain that preferred-address content must be the exact desired address. It must not guess a code.

RelationshipPanel tests cover:

- collapsible local-only explanation;
- familiarity bucket, fixed continuity label, current readable address;
- Persona/projection/rule versions and contribution count;
- paginated apply/revoke metadata labels;
- source link only when API supplies one;
- reconcile/rebuild status;
- inline suppress confirmation explaining source memory is unchanged;
- irreversible redaction confirmation;
- explicit re-enable explanation and generation request;
- redacted/deleted/unavailable values never rendered;
- no file/URL/media/private-asset input;
- no summary/emotion/Provider/consent wording;
- stale load cannot overwrite a later mutation;
- mutation error survives failed best-effort refresh;
- relationship errors do not become chat, memory, summary, Persona, or emotion errors.

- [ ] **Step 2: Run RED frontend tests**

```text
npm --prefix frontend test -- src/api/client.test.ts src/components/MemoryPanel.test.tsx src/components/RelationshipPanel.test.tsx src/App.test.tsx
```

Expected: types/client/panel absent.

- [ ] **Step 3: Implement minimal independent state and UI**

App owns `relationshipRequestGenerationRef` and `relationshipMutationGenerationRef`, mirroring the proven SummaryPanel race pattern. Fetch projection/events/jobs/audits concurrently, refresh after mutations, preserve mutation errors on refresh failure, and use a test-only load flag consistent with existing panels. Render fixed labels, never raw reason codes or payload JSON. Do not add modals when an inline confirmation suffices.

- [ ] **Step 4: Run GREEN, full frontend, typecheck, and build**

```text
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

Expected: all pass.

- [ ] **Step 5: Record boundary**

Suggested future commit boundary: `feat: add local relationship panel` (record only).

---

### Task 17: Complete Gate B lifecycle, independence, HTTP smoke, and privacy contracts

**Files:**
- Create: `backend/tests/test_gate_c3_lifecycle_matrix.py`
- Create: `backend/tests/test_gate_c3_independence.py`
- Create: `backend/tests/test_gate_c3_http_smoke.py`
- Create: `backend/tests/test_gate_c3_privacy_contract.py`
- Modify: affected focused tests only when a genuine contract gap is found

- [ ] **Step 1: Add full lifecycle and independence matrices**

Cover create, support without version, multiple supports, independent Evidence retractions, supersede, user edit, user revert, archive, true forget, open conflict, all five conflict resolutions, session deletion, stale/recovered reconcile, suppression across edits/rebuild/recovery/Persona/rule changes, and explicit re-enable.

Snapshot row counts and contents for memory, summary, Persona, and emotion tables before relationship actions; assert relationship actions do not mutate them. Mutate Stage 4 emotion, C2 summaries, assistant text, and raw messages independently and assert zero relationship event/projection semantic change.

- [ ] **Step 2: Add generated-value privacy contract**

Generate runtime-random sentinels for preferred address, source memory prose, summary text, raw Provider output, API key, HMAC, private fingerprint, Prompt injection, and private asset path. Check public API JSON, captured logs, frontend fixtures, Composer output after forget, assistant manifests, metadata-only tables, and bounded tracked/untracked review surface. Directly assert the forgotten address is absent from every readable event/projection column and apply payload is `NULL`.

Forbidden public keys include:

```text
payload_json
source_set_hash
canonical_key_hash
subject_key_hash
content_hash
inherited_authority_fingerprint
integrity_fingerprint
source_memory_version_id
source_event_ids
prompt
raw_response
authorization
api_key
hmac
```

- [ ] **Step 3: Run warning-strict Gate C3 acceptance contracts**

```text
python -W error -m pytest backend/tests/test_relationship_contract.py backend/tests/test_relationship_domain.py backend/tests/test_relationship_migration.py backend/tests/test_relationship_schema_invariants.py backend/tests/test_relationship_sources.py backend/tests/test_relationship_rules.py backend/tests/test_relationship_authority.py backend/tests/test_relationship_lineage.py backend/tests/test_relationship_ledger.py backend/tests/test_relationship_projector.py backend/tests/test_relationship_projection_view.py backend/tests/test_relationship_determinism.py backend/tests/test_relationship_reconciler.py backend/tests/test_relationship_scheduler.py backend/tests/test_relationship_recovery.py backend/tests/test_relationship_startup.py backend/tests/test_relationship_mutation_hooks.py backend/tests/test_relationship_conflict_lifecycle.py backend/tests/test_relationship_true_forget.py backend/tests/test_relationship_privacy_transactions.py backend/tests/test_relationship_session_deletion.py backend/tests/test_relationship_persona_switch.py backend/tests/test_relationship_rule_upgrade.py backend/tests/test_relationship_full_rebuild.py backend/tests/test_relationship_chat_disclosure.py backend/tests/test_api_relationships.py backend/tests/test_gate_c3_lifecycle_matrix.py backend/tests/test_gate_c3_independence.py backend/tests/test_gate_c3_http_smoke.py backend/tests/test_gate_c3_privacy_contract.py -q
```

Expected: all pass with warnings treated as errors.

- [ ] **Step 4: Run prior Gate and affected Stage regressions**

Run Gate B/C1/C2 HTTP/privacy suites plus memory forget/conflict/session deletion, context, chat, Persona, summary, and emotion tests. Any failure blocks C3 closure.

- [ ] **Step 5: Record boundary**

Suggested future commit boundary: `test: verify Gate C3 lifecycle and privacy` (record only).

---

### Task 18: Add fixed replay fixtures and prepare the 30-reply human evaluation

**Files:**
- Create: `backend/tests/fixtures/gate_c3_replay_v1.json`
- Create: `backend/tests/test_gate_c3_fixed_replay.py`
- Create: `docs/gate-c3-evaluation-scorecard-template.md`
- Create during acceptance only: `docs/gate-c3-evaluation-2026-07-26.md`

- [ ] **Step 1: Create versioned deterministic fixtures**

Include Chinese multi-session cases for user facts, changing preferences, goals, shared experiences, non-external commitments, time, correction, unresolved/resolved conflicts, true forget/no revival, summary errors, uncertainty, Prompt injection, Persona switch, suppression, and re-enable. Store declared schema/rule/Composer/encoder versions and a fixed SHA-256 content hash checked by the test.

No fixture contains user-private data, real credentials, private media paths, third-party character assets, or cloned voice data.

- [ ] **Step 2: Write deterministic replay assertions**

Replay at least 30 fixed questions through fake/recording infrastructure and assert source eligibility, selected context manifests, no forbidden source, no revival, bounds, deterministic output identity, and chat survival under neutral relationship fallback. This automated replay is contract/privacy evidence only. Its canned fake/recording replies can never satisfy the human Persona, continuity, or natural-language quality gate.

- [ ] **Step 3: Generate a blind score packet**

The human packet must contain at least 30 actual assistant replies produced through the complete `ChatService.send_message` path with the fixed replay state and questions. Record for every run the route, provider, model, endpoint category (local/remote without credentials), Persona ID, rule/Composer/encoder versions, model parameters, and whether it is real Provider or fake/recording evidence. Fake/recording replies remain visible as automation evidence but are excluded from human quality thresholds; if no real configured chat Provider is deliberately run, the human quality gate and Gate C3 remain `PENDING`.

The scorecard blinds reply order and implementation labels and records raw reply, fixture ID, timestamps, and integer 0–2 scores for:

1. core Persona consistency;
2. factual caution;
3. relationship continuity;
4. natural language;
5. non-official/non-real-person/non-consciousness declaration behavior.

For each human pass and each category, compute `sum(category_scores) / reply_count` with no intermediate rounding; each category must be `>= 1.6`. Define each reply's aggregate as the arithmetic mean of its five category scores. A low reply is `aggregate < 1.0`. For one reviewer doing two blind-order passes, evaluate both passes independently: each must have every category average `>= 1.6`, and `low_reply_count / reply_count < 0.05` with no rounding. With exactly 30 replies this permits at most one low reply per pass. For multiple reviewers, apply those thresholds independently to every reviewer rather than pooling away a failed pass. Any prohibited behavior in any pass is immediate failure. An LLM/Agent judge may assist but cannot be the sole evidence.

- [ ] **Step 4: Run replay tests and validate score arithmetic**

```text
python -W error -m pytest backend/tests/test_gate_c3_fixed_replay.py -q
```

The test validates fixture hash and scorecard arithmetic but does not fabricate human scores. Gate C3 remains pending until the completed human scorecard passes.

- [ ] **Step 5: Record boundary**

Suggested future commit boundary: `test: add Gate C3 fixed replay evaluation` (record only).

---

### Task 19: Run complete acceptance, independent review, and close Gate C3 only on evidence

**Files:**
- Create after all evidence passes: `docs/automatic-memory-gate-c3-acceptance-2026-07-26.md`
- Modify after approval only: `CLAUDE.md`

- [ ] **Step 1: Run complete warning-strict backend and frontend verification**

```text
python -W error -m pytest backend/tests -q
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
python -m compileall -q backend/app
git diff --check
```

Record exact counts, durations, failures/retries, and the existing LF→CRLF advisory separately from real whitespace errors.

- [ ] **Step 2: Audit privacy and raw SQLite evidence**

Repeat runtime generated-sentinel checks; inspect all C3 audit/job schemas and rows; prove address payload physical clearing; prove projections never store address text; prove no API key/HMAC/private asset entered code, logs, SQLite, tests, docs, or Git review surface. Distinguish fake/recording evidence from any real Provider evidence. C3 should have zero relationship Provider calls because it adds no Provider.

- [ ] **Step 3: Complete the human scorecard**

Attach the two-pass or multi-reviewer raw scores, calculated thresholds, blind-order method, and prohibited-behavior check. Do not mark Gate C3 complete if human review is absent or below threshold.

- [ ] **Step 4: Obtain independent final technical review**

Provide the approved design, this plan, complete current diff, fresh commands/results, privacy evidence, and human scorecard to an independent reviewer. `CHANGES_REQUIRED` requires remediation, affected/full re-verification as appropriate, and re-review. Only explicit `APPROVED` with no unresolved high/critical privacy, correctness, concurrency, or acceptance-integrity finding can close C3.

- [ ] **Step 5: Write honest acceptance record and update project state**

The acceptance record must include implemented scope, claim-to-test matrix, exact commands/results, generated-value privacy evidence, true-forget proof, human evaluation scores, reviewer verdict, known limits, dirty-tree status, and no-Git-mutation statement. Update `CLAUDE.md` to Gate C3/Gate C complete only after every prior step passes. Otherwise document `PENDING` and the exact blocker.

Gate C completion does not authorize Electron, Live2D, private assets, voice cloning, packaging, commit, push, publication, or distribution.

---

## Plan self-review checklist

Before implementation begins, verify:

- Every Gate C3 design section 1–21 maps to at least one task above.
- The plan never derives relationship state from summary, messages, assistant output, emotion, Evidence count, free-text sentiment, or arbitrary metadata.
- `canonical_subject_code` is explicit, versioned, immutable, nullable for compatibility, and never guessed during migration.
- Suppression authority survives edits, conflict-created IDs, rebuild, recovery, Persona switch, and rule upgrade.
- True forget clears source and relationship readable payloads in the same transaction and activates a safe projection.
- Projections contain address event ID only; address text resolves from the one event-layer readable copy.
- Pre-chat disclosure uses the fixed lock order and cannot leak a value after a queued privacy mutation.
- Public API/frontend/manifests omit private IDs/fingerprints/payloads and unavailable text.
- Every task has a RED command, minimal implementation target, GREEN command, and non-executed commit boundary.
- No placeholder, production implementation, Git mutation, or out-of-scope desktop/media work is present in this planning step.
