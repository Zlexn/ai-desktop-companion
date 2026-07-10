# Stage 3K Session Summary Independent Storage Design

Date: 2026-07-10
Status: Approved for implementation

## Context

Stage 3 is the current project phase: long-term memory. Stages 1 and 2 are closed, Stage 4 emotion state is not started, and Stage 3A–3J are complete.

The Stage 3 project rules require chat history, session summaries, and long-term memories to be stored separately. Current storage has independent `sessions`, `messages`, `memories`, `memory_audit_events`, and `memory_embeddings` tables, but no dedicated session summary storage. Stage 3K fills that storage gap without adding automatic summarization or prompt injection.

## Goal

Create a minimal, auditable, independent storage layer for session summaries.

The result should prove that session summaries can be persisted, listed, retrieved, and deleted separately from chat messages and long-term memories, while staying bound to their source session.

## Non-goals

- No LLM summary generation.
- No automatic summary trigger.
- No summary injection into chat context or prompts.
- No UI.
- No API route unless a later task explicitly asks for one.
- No conversion of summaries into long-term memories.
- No retrieval of summaries through memory relevance or embedding search.
- No automatic memory writes.
- No conversation backfill.
- No Stage 4 emotion state.

## Recommended approach

Add a backend-only storage slice:

1. A `session_summaries` SQLite table.
2. A `SessionSummarySource` enum and `SessionSummary` domain model.
3. A focused `SessionSummaryRepository`.
4. Repository tests that verify separation from messages and memories.
5. Stage evidence documentation and `CLAUDE.md` status update after validation.

This approach is intentionally narrower than summary generation. It establishes the data boundary first so future generation/context work has a safe place to write without confusing summaries with long-term memory.

## Data model

Add table `session_summaries`:

- `id TEXT PRIMARY KEY`
- `session_id TEXT NOT NULL`
- `summary_text TEXT NOT NULL`
- `source TEXT NOT NULL CHECK (source IN ('manual', 'generated'))`
- `covered_message_start_id TEXT`
- `covered_message_end_id TEXT`
- `message_count INTEGER NOT NULL CHECK (message_count >= 0)`
- `metadata_json TEXT NOT NULL DEFAULT '{}'`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`

Foreign keys:

- `session_id` references `sessions(id)` with `ON DELETE CASCADE`.
- `covered_message_start_id` references `messages(id)` with `ON DELETE SET NULL`.
- `covered_message_end_id` references `messages(id)` with `ON DELETE SET NULL`.

Indexes:

- `(session_id, created_at DESC)` for listing summaries by session.
- `(session_id, updated_at DESC)` for latest summary lookup.

Rationale:

- `source` distinguishes manually inserted test/manual summaries from later generated summaries without implementing a generator now.
- message range columns allow later summary coverage tracking but remain nullable because 3K does not decide summarization strategy.
- `message_count` records scope size without requiring a non-null covered range.
- `metadata_json` keeps the row extensible without new columns for every future summary provider detail.

## Domain model

Add to `backend/app/domain/models.py`:

- `SessionSummarySource` with values:
  - `MANUAL = "manual"`
  - `GENERATED = "generated"`
- `SessionSummary` dataclass with:
  - `id`
  - `session_id`
  - `summary_text`
  - `source`
  - `covered_message_start_id`
  - `covered_message_end_id`
  - `message_count`
  - `metadata`
  - `created_at`
  - `updated_at`

## Repository behavior

Create `backend/app/repositories/session_summaries.py`.

Required methods:

- `create(session_id, summary_text, source=SessionSummarySource.MANUAL, covered_message_start_id=None, covered_message_end_id=None, message_count=0, metadata=None) -> SessionSummary`
- `list_for_session(session_id) -> list[SessionSummary]`
- `latest_for_session(session_id) -> SessionSummary | None`
- `delete(summary_id) -> bool`

Behavior:

- Empty or whitespace-only `summary_text` is invalid and should raise `ValueError`.
- Negative `message_count` is invalid and should raise `ValueError`.
- `list_for_session` returns summaries in ascending creation order so history reads naturally.
- `latest_for_session` returns the newest summary for one session or `None`.
- Deleting a session cascades deletion of summaries.
- The repository does not read or write `memories`.

## Data and privacy boundaries

Stage 3K tests should use synthetic session/message/summary data only.

The storage layer must not read real app databases, chat history outside test fixtures, private memories, or production data. It must not send summary text to any external service.

## Product behavior after 3K

Default chat behavior remains unchanged:

- no automatic summary generation;
- no summary prompt injection;
- no summary-based memory retrieval;
- no frontend-visible summary UI.

Stage 3K creates only the safe storage boundary for future work.

## Expected files

Likely create:

- `backend/app/repositories/session_summaries.py`
- `backend/tests/test_session_summaries.py`
- `docs/stage3k-session-summary-independent-storage.md`
- `docs/superpowers/plans/2026-07-10-stage-3k-session-summary-independent-storage.md`

Likely modify:

- `backend/app/domain/models.py`
- `backend/app/repositories/sqlite.py`
- `CLAUDE.md`

## Validation plan for implementation

Run focused tests:

```powershell
python -m pytest backend/tests/test_session_summaries.py -q
```

Run related backend tests:

```powershell
python -m pytest backend/tests/test_session_summaries.py backend/tests/test_memory_candidate_service.py backend/tests/test_memory_embeddings.py backend/tests/test_config.py -q
```

Run full backend tests if feasible:

```powershell
python -m pytest backend/tests -q
```

If the known unrelated chat context pruning failure remains, record it separately and do not hide it.

Frontend tests are not required unless frontend runtime source changes.

## Risks and mitigations

- Risk: summaries become confused with long-term memories.
  - Mitigation: separate table, separate repository, tests assert memory table is unaffected.

- Risk: future summary generation assumptions leak into 3K.
  - Mitigation: store nullable coverage metadata only; no generator/provider/service in this slice.

- Risk: summary rows outlive deleted sessions.
  - Mitigation: `ON DELETE CASCADE` and a repository test.

- Risk: prompt context starts using summaries before policy is designed.
  - Mitigation: do not touch `ContextBuilder` or chat service in 3K.

- Risk: migration behavior for existing databases is incomplete.
  - Mitigation: `CREATE TABLE IF NOT EXISTS` in the existing schema initializer and indexes in `init_db`.

## Implementation decisions

- `manual` and `generated` are the only initial summary sources.
- `summary_text` must be non-empty after trimming.
- `message_count` defaults to `0` and must be non-negative.
- Repository tests will use synthetic data in temporary SQLite databases.
- Stage 3K completion means storage is available and verified, not that summary generation is implemented.
