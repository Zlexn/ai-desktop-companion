# Stage 3K Session Summary Independent Storage

Date: 2026-07-10
Status: VERIFIED WITH UNRELATED BASELINE FAILURE

## Scope

Stage 3K adds independent backend storage for session summaries. It creates a `session_summaries` table, domain model, and repository.

This is a backend storage slice only. It does not change chat behavior, prompt context, long-term memory retrieval, frontend UI, or provider configuration.

## Non-goals

- No LLM summary generation.
- No automatic summary trigger.
- No summary prompt/context injection.
- No UI or API route.
- No conversion of summaries into long-term memories.
- No summary retrieval through relevance or embedding search.
- No Stage 4 emotion state.

## Implemented storage

- Table: `session_summaries`
- Repository: `SessionSummaryRepository`
- Domain model: `SessionSummary`
- Source enum: `SessionSummarySource` with `manual` and `generated`

The table is linked to `sessions(id)` with `ON DELETE CASCADE`. Optional coverage columns can point to message IDs with `ON DELETE SET NULL`.

## Verified behavior

- Create and list summaries for a session.
- Retrieve latest summary for a session.
- Delete a summary by ID.
- Reject empty summary text.
- Reject negative message counts.
- Delete summaries automatically when a session is deleted.
- Keep summaries separate from long-term memories.
- Keep chat context and memory retrieval untouched.

## Validation

Commands run on 2026-07-10:

- `python -m pytest backend/tests/test_session_summaries.py -q` → 8 passed.
- `python -m pytest backend/tests/test_session_summaries.py backend/tests/test_memory_candidate_service.py backend/tests/test_memory_embeddings.py backend/tests/test_config.py -q` → 68 passed.
- `python -m pytest backend/tests -q` → 337 passed, 1 failed.

Full backend failure details:

- Failing test: `backend/tests/test_chat_service.py::test_chat_service_prunes_old_history_before_provider_when_context_is_large`.
- This same chat context pruning failure was observed before Stage 3K implementation during Stage 3J final validation.
- Stage 3K did not modify `ChatService`, `ContextBuilder`, prompt rendering, LLM providers, or chat tests.

Stage 3K-specific validation passed.

## Stage boundary check

Stage 3K did not implement summary generation, summary prompt injection, memory writes, vector search over summaries, automatic conflict resolution, or Stage 4 emotion state.

The tests used synthetic temporary SQLite databases and synthetic session/message/summary data only. No real app database, private chat history, production memory data, or external service was used.
