# Stage 3D Memory Conflict Audit Design

Date: 2026-07-07
Status: Design selected by recommended-default instruction; awaiting implementation planning

## Context

The project is in Stage 3: long-term memory. Stage 3A added manual long-term memory CRUD, independent SQLite storage, duplicate conflict visibility, caveated context injection, and a minimal memory UI. Stage 3B added heuristic pending memory candidates with user confirmation/dismissal. Stage 3C added deterministic local relevance retrieval so active memories are selected by relevance to the current user message.

The remaining Stage 3 rule with the highest risk is conflict handling: conflicting memories must not be silently overwritten, and conflicts must retain an audit trail or require user handling. The current implementation returns `conflicts` from create/update/confirm operations and shows a generic warning in the UI, but it does not persist a separate audit event and does not show conflict details in the memory panel.

Stage 3D adds a minimal local audit trail for detected memory conflicts and makes the latest conflict details visible to the user.

This design stays within Stage 3. It does not implement vector retrieval, embeddings, LLM-based semantic contradiction detection, session summaries, LLM-based memory extraction, automatic merge/resolve workflows, or Stage 4 emotion state.

## Goals

- Persist an audit event whenever a memory create, update, or candidate confirmation detects conflicts.
- Preserve current behavior: conflicts do not silently overwrite existing memories.
- Show current conflict details in the memory UI instead of only a generic warning.
- Provide a minimal read-only API for recent memory audit events.
- Keep the implementation local, deterministic, dependency-free, and testable.
- Avoid storing raw chat history, provider prompts, API keys, or emotional state in audit events.

## Non-goals

- No vector database or embedding provider.
- No LLM contradiction detector.
- No LLM memory extractor.
- No automatic conflict merge, replacement, or resolution workflow.
- No session summary storage.
- No Stage 4 mood, trust, concern, distance, irritation, formality, relationship score, affect decay, or expression strategy state.
- No background processing or external service calls.

## Recommended approach

Add a small `memory_audit_events` SQLite table and a focused repository for audit events. Memory mutation routes will record `conflict_detected` events after operations that return non-empty conflicts. The UI will display the current conflict records already returned by mutation responses and, if practical in the same slice, a short recent audit list from the new read-only endpoint.

This is preferable to vector retrieval or LLM candidate extraction because it directly closes a Stage 3 safety/audit requirement before adding more powerful memory creation or retrieval mechanisms.

## Data model

Create a new table during database initialization:

- `id TEXT PRIMARY KEY`
- `event_type TEXT NOT NULL CHECK (event_type IN ('conflict_detected'))`
- `memory_id TEXT NOT NULL`
- `related_memory_ids_json TEXT NOT NULL DEFAULT '[]'`
- `operation TEXT NOT NULL CHECK (operation IN ('create', 'update', 'confirm_candidate'))`
- `metadata_json TEXT NOT NULL DEFAULT '{}'`
- `created_at TEXT NOT NULL`

Indexes:

- `idx_memory_audit_events_created` on `created_at DESC`
- `idx_memory_audit_events_memory` on `memory_id`

Do not add foreign keys for `memory_id` or `related_memory_ids_json`. Audit events should remain readable even if a memory is later archived or removed by a future hard-delete feature. The project currently archives memories rather than hard-deleting them, but the audit design should not depend on active records existing forever.

## Domain model

Add these domain concepts:

- `MemoryAuditEventType` with `CONFLICT_DETECTED` / `conflict_detected`.
- `MemoryAuditOperation` with `CREATE`, `UPDATE`, and `CONFIRM_CANDIDATE`.
- `MemoryAuditEvent` dataclass with id, event_type, memory_id, related_memory_ids, operation, metadata, created_at.

These are audit records, not chat context and not long-term memories. They must never be injected into LLM prompts by ContextBuilder.

## Repository design

Create `backend/app/repositories/memory_audit.py`.

Responsibilities:

- `record_conflict(memory_id, related_memory_ids, operation, metadata=None) -> MemoryAuditEvent`
  - Store one `conflict_detected` event.
  - Preserve the related ids order returned by conflict detection.
  - Store only ids and low-sensitivity metadata.

- `list_recent(limit=20) -> list[MemoryAuditEvent]`
  - Return newest events first.
  - Enforce a positive limit at the API/schema layer; repository can assume a valid limit.

Keep conflict detection itself in `MemoryRepository`. `MemoryAuditRepository` only records and reads events.

## API design

Extend memory dependencies with `get_memory_audit_repository`.

Update existing mutation routes:

- `POST /api/memories`
  - After `memories.create(...)`, if `conflicts` is non-empty, call `audit.record_conflict(...)` with operation `create`.
  - Return the existing `MemoryMutationResponse` shape unchanged.

- `PATCH /api/memories/{memory_id}`
  - After `memories.update(...)`, if `conflicts` is non-empty, record operation `update`.

- `POST /api/memories/{memory_id}/confirm`
  - After `memories.confirm_candidate(...)`, if `conflicts` is non-empty, record operation `confirm_candidate`.
  - Preserve current behavior where a conflicting pending candidate remains pending and is returned with conflicts.

Add a read-only endpoint:

- `GET /api/memories/audit-events?limit=20`
  - Returns recent audit events newest first.
  - Response model: `list[MemoryAuditEventResponse]`.
  - `limit` should be bounded, for example `1 <= limit <= 100`.

Do not change the existing `MemoryMutationResponse` contract in this slice; frontend conflict details can use the existing `conflicts` field.

## Frontend design

Update `MemoryPanel` so current conflicts are visible:

- Replace the generic-only warning with a conflict section.
- Show each conflict memory content, type, importance, and confidence.
- Keep the warning text that multiple similar memories may be valid and should be reviewed by the user.

Optionally, if implementation remains small, add a recent audit section:

- Add `MemoryAuditEvent` type and API client method.
- Load recent audit events in `App` alongside memories.
- Show the operation, event type, target memory id, related ids, and created time.
- If this increases scope too much, keep recent audit visibility backend/API-only for Stage 3D and defer richer UI browsing to a later Stage 3 slice.

The recommended minimum frontend requirement for this slice is conflict-detail display from the existing mutation response. The recommended minimum backend requirement is persistent audit event storage and a read API.

## Error handling and privacy

- Audit recording should happen inside the same request path after memory mutation. If audit recording fails, return a normal server error rather than pretending the conflict was audited.
- Do not log raw memory content beyond existing application behavior.
- Audit event metadata should not include full chat transcripts or provider prompts.
- The audit read API should expose ids and metadata, not hidden scoring internals or prompt content.
- Archived memories may still appear in historical audit event ids. UI should tolerate missing related records in later slices.

## Testing plan

### Database and repository tests

Add tests that:

- `init_db` creates the `memory_audit_events` table and indexes.
- `MemoryAuditRepository.record_conflict(...)` persists a conflict event with target id, related ids, operation, metadata, and timestamp.
- `list_recent(limit)` returns newest events first and respects limit.

### API tests

Add tests that:

- Creating a duplicate same-type memory returns conflicts and creates one audit event.
- Updating a memory into a duplicate returns conflicts and creates one audit event.
- Confirming a pending candidate that conflicts with active memory creates one audit event and keeps the candidate pending.
- Creating a non-conflicting memory creates no audit event.
- `GET /api/memories/audit-events?limit=...` returns recent audit events and validates limit bounds.

### Frontend tests

Add or update tests that:

- `MemoryPanel` renders conflict memory details when `conflicts` is non-empty.
- Existing memory create/candidate flows still work.
- If recent audit events are added to UI, API client and App tests cover loading/displaying the list.

### Regression tests

After implementation:

- Run focused backend tests for repository, API memories, schemas if changed.
- Run full backend pytest.
- Run frontend unit tests.
- Run frontend typecheck.
- Run frontend build.
- Run Playwright E2E.

## Documentation updates

After verified implementation, create:

- `docs/stage3d-memory-conflict-audit.md`

Update `CLAUDE.md` only after validation passes. The update should record Stage 3D completion, validation commands, and limitations.

## Risks and mitigations

- Risk: audit events duplicate when users retry the same conflicting action.
  - Mitigation: acceptable for an audit trail; each mutation attempt is a distinct event.

- Risk: audit table becomes a second memory store.
  - Mitigation: audit events store ids and metadata, not prompt context, and are never injected into chat.

- Risk: frontend scope expands into conflict resolution UX.
  - Mitigation: show details only; no merge/replace/resolve workflow in this slice.

- Risk: schema migration grows complex.
  - Mitigation: add `CREATE TABLE IF NOT EXISTS` and indexes; no existing data migration is required for new installs/current dev DBs.

- Risk: scope drifts into Stage 4.
  - Mitigation: no emotional state, relationship metrics, expression strategy, or affect decay is introduced.

## Implementation boundary

This design is ready for one implementation plan. The implementation should be test-driven and staged:

1. Add audit domain models and SQLite table/index initialization.
2. Add `MemoryAuditRepository` with repository tests.
3. Add API dependency, response schema, route recording, and read endpoint tests.
4. Update frontend conflict-detail rendering tests and implementation.
5. Run focused and full regressions.
6. Write evidence documentation and update `CLAUDE.md` after validation.

No product code should be written until the implementation plan is created and execution begins under TDD.
