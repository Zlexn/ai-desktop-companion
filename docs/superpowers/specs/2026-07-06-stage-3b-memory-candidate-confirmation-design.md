# Stage 3B Memory Candidate Confirmation Design

Date: 2026-07-06
Status: Draft approved for spec writing; awaiting user review before implementation planning

## Context

The project is in Stage 3: long-term memory. Stage 3A is complete and already provides manual long-term memory CRUD, a dedicated SQLite `memories` table, exact normalized duplicate conflict visibility, caveated context injection for active memories, and a minimal React memory panel.

The next smallest complete Stage 3 loop is automatic memory candidate confirmation. The system should suggest possible long-term memories from explicit user statements during chat, but it must not silently write them into active long-term memory. The user remains in control: a candidate becomes long-term memory only after explicit confirmation.

This design stays within Stage 3. It does not implement Stage 4 emotion state, session summaries, vector retrieval, semantic contradiction detection, or model training.

## Goals

- Generate conservative candidate memories after successful chat turns.
- Keep candidates separate from active long-term memories until user confirmation.
- Let the user confirm or dismiss each candidate in the UI.
- Ensure pending candidates are never injected into chat context.
- Preserve the Stage 3 rules: source, time, type, importance, confidence, user control, conflict visibility, and separation from chat history.
- Keep implementation small and compatible with existing APIs and tests.

## Non-goals

- No full LLM-based memory extraction as a required dependency for this slice.
- No vector database or embedding retrieval.
- No semantic contradiction detection.
- No session summary storage.
- No Stage 4 emotional state, relationship metrics, mood, trust, concern, or similar continuous affective state.
- No background scanning of old chat history to backfill memories.
- No automatic active-memory writes from chat.

## Recommended approach

Implement a candidate layer on top of the existing memory repository and table. A candidate is a `Memory` row with `status = pending` and `source = candidate`. Confirming a candidate changes it to `active`; dismissing it changes it to `dismissed`.

This avoids introducing a second candidate table before the data model requires it, while still keeping active memories, pending candidates, archived memories, and dismissed candidates clearly separated by status. The existing `metadata_json` field stores lightweight audit details.

## Product behavior

After a user sends a message and the assistant reply is successfully saved, the backend tries to generate zero or more pending memory candidates from the user's message. Candidate generation failure must not fail the chat request.

The frontend memory panel displays two sections:

1. `待确认记忆`
   - Shows system-suggested candidates.
   - Explains that candidates are not long-term memories yet and will not be used in conversation until confirmed.
   - Provides `保存为长期记忆` and `忽略` actions.

2. `长期记忆`
   - Shows confirmed active memories, as Stage 3A already does.
   - Keeps existing manual creation and delete/archive behavior.

First version candidate actions are deliberately small:

- Confirm: convert pending candidate to active memory.
- Dismiss: convert pending candidate to dismissed.
- Edit-before-confirm is not required in this slice. If a candidate is inaccurate, the user can dismiss it and manually create a corrected memory with the existing form.

## Domain model and storage

Extend existing enums:

- `MemorySource`
  - existing: `manual`
  - new: `candidate`

- `MemoryStatus`
  - existing: `active`, `archived`
  - new: `pending`, `dismissed`

The SQLite `memories` table remains the source of truth. Its CHECK constraints must allow the new source and status values. Because existing SQLite tables are not altered by `CREATE TABLE IF NOT EXISTS`, implementation must include a minimal migration strategy that works for an existing Stage 3A database.

Each candidate stores normal memory fields:

- content
- memory_type
- source = candidate
- source_session_id
- importance
- confidence
- status = pending
- created_at
- updated_at
- metadata_json

Candidate metadata should be small and non-sensitive. Suggested keys:

- `candidate_reason`: short reason or rule name, such as `explicit_like_statement`.
- `source_text`: optional short user text excerpt if safe and already persisted as chat text.
- `extraction_provider`: `heuristic` for this slice.
- `extraction_model`: optional; empty or omitted for heuristic extraction.
- `confirmed_at`: added when confirmed.
- `dismissed_at`: added when dismissed.

Do not store raw provider prompts, API keys, audio files, or hidden chain-of-thought.

## Repository behavior

Add or adapt repository methods around statuses:

- `create_candidate(...) -> tuple[Memory | None, list[Memory]]`
  - Creates a pending candidate when there is no duplicate active or pending memory of the same type and normalized content.
  - If a duplicate exists, does not create a second candidate and returns conflicts.

- `list(status: MemoryStatus = MemoryStatus.ACTIVE)`
  - Existing behavior remains valid and also supports `pending` and `dismissed`.

- `confirm_candidate(memory_id) -> tuple[Memory, list[Memory]]`
  - Requires the row to exist and have status `pending`.
  - Checks conflicts against active memories before activation.
  - Sets status to `active`, updates `updated_at`, and records `confirmed_at` in metadata.
  - Does not silently overwrite conflicting active memory.

- `dismiss_candidate(memory_id) -> Memory`
  - Requires the row to exist and have status `pending`.
  - Sets status to `dismissed`, updates `updated_at`, and records `dismissed_at` in metadata.

- `list_for_context(limit)`
  - Must continue to return only `active` memories.
  - Pending and dismissed candidates must never be injected into chat context.

- `find_conflicts(...)`
  - For candidate creation, compare against both active and pending rows of the same type.
  - For active confirmation, compare against active rows of the same type.
  - Exact normalized duplicate detection is enough for this slice.

## API design

Reuse the existing memory route namespace.

- `GET /api/memories?status_filter=pending`
  - Reuses existing list endpoint once new statuses are valid.

- `POST /api/memories/{memory_id}/confirm`
  - Confirms a pending candidate.
  - Response: `MemoryMutationResponse` with the resulting memory and conflicts.

- `POST /api/memories/{memory_id}/dismiss`
  - Dismisses a pending candidate.
  - Response: `MemoryResponse` or `204 No Content`. Prefer `MemoryResponse` if it helps frontend state updates; otherwise keep response minimal.

Existing endpoints remain compatible:

- `POST /api/memories` still creates active manual memories.
- `PATCH /api/memories/{memory_id}` still edits existing memories. It should not be required for candidate confirmation in this slice.
- `DELETE /api/memories/{memory_id}` still archives active memories. It does not replace candidate dismissal.

## Candidate generation service

Add a small `MemoryCandidateService` that runs after a successful chat turn. It receives at least:

- session_id
- user_text
- optional source message id if available with minimal changes

The service returns generated pending candidates or silently does nothing when disabled, when no candidate is detected, or when duplicates exist.

Configuration:

- `MEMORY_CANDIDATES_ENABLED`
  - Default: enabled for normal local use if the implementation remains deterministic and heuristic-only.
  - Tests may explicitly set it as needed.

- `MEMORY_CANDIDATE_PROVIDER`
  - Default: `heuristic`.
  - Only `heuristic` is required for this slice.

Heuristic extraction is intentionally conservative. Suggested first rules:

- `我喜欢 X` -> `preference`, content like `用户喜欢 X。`
- `我不喜欢 X` -> `preference`, content like `用户不喜欢 X。`
- `我的目标是 X` or `我正在准备 X` -> `long_term_goal`.
- `我住在 X` or `我的职业是 X` -> `user_fact`.

Rules should ignore:

- assistant replies
- vague or very short fragments
- temporary emotions or one-off requests
- statements about the character's emotional state
- anything that would implement Stage 4 emotion state

Default importance and confidence should be conservative, for example importance `3` and confidence `0.7` for heuristic candidates. Exact values can be adjusted in implementation, but must be bounded by existing schema validation.

## Chat flow

Current Stage 3A flow:

1. User message is saved.
2. Context is built from active memories and recent messages.
3. LLM provider generates assistant reply.
4. Assistant reply is saved.
5. Chat response returns.

Stage 3B adds one non-blocking step after the assistant reply is saved:

6. Candidate service attempts to create pending candidates from the user message.

Candidate generation must not change the chat response contract. If it fails, the chat response still succeeds. The frontend can refresh pending candidates after sending a message.

## Frontend design

Extend `App.tsx` state:

- `memoryCandidates: MemoryRecord[]`
- candidate loading/error state can reuse memory loading/error where simple, or use a small separate state if tests become clearer.

Loading behavior:

- On startup, load active memories and pending candidates.
- After a successful chat send, refresh pending candidates.
- After confirming a candidate, remove it from pending and add/update it in active memories.
- After dismissing a candidate, remove it from pending.

Extend `apiClient`:

- `listMemories(status?: MemoryStatus)` or a dedicated `listMemoryCandidates()`.
- `confirmMemoryCandidate(memoryId)`.
- `dismissMemoryCandidate(memoryId)`.

Extend `MemoryPanel` props:

- `candidates: MemoryRecord[]`
- `onConfirmCandidate(id)`
- `onDismissCandidate(id)`

UI text should make the safety boundary clear:

- `待确认记忆`
- `以下是系统建议保存的长期记忆，确认前不会用于对话。`
- `保存为长期记忆`
- `忽略`

## Error handling

- Candidate extraction errors are non-fatal to chat.
- Candidate API errors appear only in the memory panel error area.
- Confirming a candidate that no longer exists or is not pending returns a clear user-facing error.
- Duplicate conflicts are shown as warnings and do not overwrite existing memories.
- No provider secrets, raw prompts, or stack traces are exposed to the frontend.

## Testing plan

### Backend repository tests

- Pending candidates are listed with `status = pending`.
- Pending candidates do not appear in `list_for_context()`.
- Confirming a pending candidate makes it active and context-eligible.
- Dismissing a pending candidate removes it from pending and keeps it out of context.
- Duplicate active or pending candidates are not silently duplicated.
- Existing active/manual memory CRUD still works.

### Backend API tests

- `GET /api/memories?status_filter=pending` returns pending candidates.
- `POST /api/memories/{id}/confirm` activates a pending candidate.
- `POST /api/memories/{id}/dismiss` dismisses a pending candidate.
- Confirm/dismiss of invalid or non-pending rows returns a clear error envelope.

### Candidate service and chat tests

- `我喜欢红茶` creates a pending `preference` candidate after chat succeeds.
- Candidate generation failure does not fail chat.
- Duplicate explicit statements do not create duplicate pending candidates.
- Candidate generation can be disabled through configuration.

### Frontend unit tests

- API client sends correct confirm/dismiss requests.
- MemoryPanel renders pending candidates separately from active memories.
- Confirm and dismiss buttons call the correct handlers.
- App refreshes candidates after sending a message.
- Confirming a candidate updates pending and active memory UI state.

### E2E smoke

Using fake providers:

1. Create or use a session.
2. Send `我喜欢红茶`.
3. Verify chat still succeeds.
4. Verify a pending memory candidate appears.
5. Click `保存为长期记忆`.
6. Reload the page.
7. Verify the confirmed memory appears in the active long-term memory list.

## Documentation updates

After implementation and verification, update Stage 3 evidence documentation with:

- Implemented candidate behavior.
- Commands run and results.
- Explicit limitations.
- Confirmation that Stage 4 emotion state remains unimplemented.

`CLAUDE.md` should only be updated after verified implementation, not during this design-only step.

## Risks and mitigations

- Risk: heuristic extraction misses useful memories.
  - Mitigation: acceptable for first slice; prefer false negatives over false positives.

- Risk: candidate text is inaccurate.
  - Mitigation: candidates require user confirmation and are not injected into context before confirmation.

- Risk: SQLite CHECK constraints do not update in existing local DBs.
  - Mitigation: implement a minimal migration for the `memories` table before relying on new status/source values.

- Risk: candidate generation makes chat flaky.
  - Mitigation: run it after assistant reply persistence and catch/log failures without failing chat.

- Risk: scope drifts into emotion or relationship state.
  - Mitigation: reject mood/trust/concern/distance/irritation/formality or similar affective state in this slice.

## Implementation boundary

This design is ready for a single implementation plan. The implementation should be test-driven, small, and staged:

1. Backend status/source model and migration.
2. Repository candidate lifecycle.
3. Candidate generation service and chat hook.
4. Candidate API endpoints.
5. Frontend client and UI.
6. Focused tests, full regression, and evidence documentation.

No code should be written until the user approves this written spec and an implementation plan is created.
