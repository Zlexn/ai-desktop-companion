# Stage 3M Automatic Session Summary Generation Design

Date: 2026-07-10
Status: Proposed

## Current stage

Stage 3 — long-term memory.

Stage 3K already added independent `session_summaries` storage. Stage 3M turns that storage into an automatic summary-generation loop. This task remains inside Stage 3. It does not implement Stage 4 emotion state.

## Goal

After a successful chat turn, the backend automatically checks whether the current session has accumulated enough unsummarized messages. If the threshold is reached, it generates a session summary through a dedicated summary provider and stores the result in the existing `session_summaries` table.

The summary is a conversation-continuity artifact, not a long-term memory. It must remain separate from chat messages, active memories, pending memory candidates, dismissed candidates, and embedding retrieval.

## Non-goals

- No manual summary button.
- No public manual summary-generation API.
- No frontend summary UI.
- No summary editing API.
- No summary deletion API beyond the existing repository-level delete behavior.
- No conversion of summaries into long-term memories.
- No creation of pending memory candidates from summaries.
- No embedding search over summaries.
- No automatic conflict resolution.
- No prompt/context injection of summaries by default.
- No Stage 4 emotion state.

## Recommended approach

Use automatic threshold-triggered generation with an independent summary provider boundary.

Default behavior uses a deterministic fake summary provider so tests and ordinary local development never call a real API. Real LLM summary generation is a later opt-in path behind `SESSION_SUMMARY_PROVIDER=llm` and summary-specific timeout/token settings.

## Configuration

Add summary-specific settings:

```env
SESSION_SUMMARY_ENABLED=true
SESSION_SUMMARY_PROVIDER=fake
SESSION_SUMMARY_TRIGGER_MESSAGE_COUNT=12
SESSION_SUMMARY_MAX_INPUT_MESSAGES=24
SESSION_SUMMARY_LLM_MAX_TOKENS=512
SESSION_SUMMARY_LLM_TIMEOUT_SECONDS=15
```

Validation rules:

- `SESSION_SUMMARY_PROVIDER` must be `fake` or `llm`.
- `SESSION_SUMMARY_TRIGGER_MESSAGE_COUNT` must be greater than 0.
- `SESSION_SUMMARY_MAX_INPUT_MESSAGES` must be greater than 0.
- `SESSION_SUMMARY_LLM_MAX_TOKENS` must be greater than 0.
- `SESSION_SUMMARY_LLM_TIMEOUT_SECONDS` must be greater than 0.

The summary provider setting is intentionally separate from `LLM_PROVIDER`, `MEMORY_CANDIDATE_PROVIDER`, and memory embedding settings. Enabling real chat or real memory extraction must not silently enable real summary API calls.

## Architecture

```text
ChatService
  ├─ save user message
  ├─ call chat LLM provider
  ├─ save assistant message
  ├─ try memory candidate extraction, if configured
  └─ try session summary generation, if configured

SessionSummaryService
  ├─ read latest summary for the session
  ├─ read session messages
  ├─ select messages not covered by the latest summary
  ├─ check threshold
  ├─ call SessionSummaryProvider
  └─ write generated summary through SessionSummaryRepository

SessionSummaryProvider
  ├─ FakeSessionSummaryProvider
  └─ LLMSessionSummaryProvider, opt-in only
```

The summary-generation path is a side effect after chat success. It must not be a prerequisite for returning the assistant reply.

## Data flow

1. `ChatService.send_message()` validates and saves the user message.
2. `ChatService` builds the normal chat context and calls the chat provider.
3. `ChatService` saves the assistant message.
4. Existing memory candidate extraction runs and remains failure-isolated.
5. New session summary generation runs and is also failure-isolated.
6. `ChatService` returns the chat reply regardless of summary-generation success.

If the chat provider fails, returns an empty reply, or the user message is invalid, no summary-generation attempt occurs.

## Trigger rule

`SessionSummaryService.maybe_generate_for_session(session_id)` performs the trigger decision.

1. If `SESSION_SUMMARY_ENABLED=false`, return without writing.
2. Load the latest summary using `SessionSummaryRepository.latest_for_session(session_id)`.
3. Load the session's persisted user/assistant messages using `MessageRepository.list(session_id)`.
4. If a latest summary exists and its `covered_message_end_id` appears in the message list, consider only messages after that ID.
5. If no latest summary exists, consider all session messages.
6. If the number of candidate messages is below `SESSION_SUMMARY_TRIGGER_MESSAGE_COUNT`, return without writing.
7. Take at most `SESSION_SUMMARY_MAX_INPUT_MESSAGES` messages from the candidate set for this summary batch.
8. Generate a summary from that batch.
9. Save the summary as `source=generated`.

The service should not generate multiple summaries in one chat turn even if many more than the threshold messages are unsummarized. It generates at most one summary per successful chat turn.

## Coverage model

Stage 3M uses append-only incremental summary records.

Example:

```text
summary #1 covers messages 1-12
summary #2 covers messages 13-24
summary #3 covers messages 25-36
```

This preserves auditability and avoids silently rewriting previous summaries.

A later task may design rolling summaries or prompt injection, but 3M does not update old summary records and does not synthesize a single canonical session summary.

## Stored summary fields

Each generated summary uses the existing `session_summaries` columns:

- `session_id`: current session.
- `summary_text`: provider output after trimming.
- `source`: `generated`.
- `covered_message_start_id`: first message in the summarized batch.
- `covered_message_end_id`: last message in the summarized batch.
- `message_count`: number of messages in the summarized batch.
- `metadata_json`: provider and trigger metadata.

Recommended metadata keys:

```json
{
  "provider": "fake",
  "model": "fake-session-summary-v1",
  "summary_schema": "session_summary_v1",
  "trigger_message_count": 12,
  "max_input_messages": 24
}
```

For LLM summaries, metadata should record the provider name and resolved model returned by the LLM provider response, without storing secrets or raw request payloads.

## Provider behavior

### FakeSessionSummaryProvider

The fake provider must be deterministic. It can produce a compact summary such as:

```text
本段会话共有 12 条消息。用户主要提到：<first user excerpt>。助手主要回应：<first assistant excerpt>。未解决或可延续的话题：继续围绕本段会话内容展开。
```

The output must be non-empty when input messages are non-empty.

### LLMSessionSummaryProvider

The LLM provider is opt-in only. It may reuse the existing `LLMProvider` interface internally, but it is selected only by `SESSION_SUMMARY_PROVIDER=llm`, not by the chat provider setting alone.

The LLM prompt must instruct the model that:

- It is summarizing a bounded session message segment.
- The summary is not a long-term memory.
- It must not create user facts, relationship scores, emotional state, or memory candidates.
- It must not include API keys, tokens, passwords, or credentials.
- It must write concise Chinese suitable for future conversation-continuity review.

LLM failure, empty output, or invalid output must not break chat.

## Error handling

`ChatService` wraps summary generation in `try/except Exception` and continues. This mirrors the existing memory-candidate failure isolation.

`SessionSummaryService` should avoid partial writes. If provider generation fails or produces an empty summary, no summary record is created.

The implementation may log a warning in later logging work, but 3M does not require new logging infrastructure.

## Prompt/context injection boundary

3M does not inject session summaries into chat context by default.

This is deliberate. Generating summaries is a storage and continuity foundation. Deciding how summaries affect the assistant's replies changes prompt behavior and should be designed separately so that summaries are framed as imperfect conversation context rather than absolute facts.

A future task may add a setting such as `SESSION_SUMMARY_CONTEXT_ENABLED=false` and design conservative injection rules.

## Memory boundary

Session summaries must not interact with long-term memory writes or retrieval.

Required boundaries:

- Do not write summaries to the `memories` table.
- Do not call `MemoryRepository.create_candidate()` from summary generation.
- Do not include pending, dismissed, or archived memory candidates in summary input.
- Do not update memory embeddings from summary text.
- Do not trigger conflict detection from summary text.

## Privacy and security

- Summary generation uses persisted chat messages already stored in the local SQLite database.
- Default fake provider performs no network calls.
- Real LLM summary generation is explicit opt-in through `SESSION_SUMMARY_PROVIDER=llm`.
- No API keys, tokens, passwords, or credentials should be stored in summary metadata.
- Summary prompts must instruct LLM providers not to include credentials in the summary.
- Tests must use synthetic data only.

## Files likely to change

- `backend/app/core/config.py`
  - Add summary settings and validation.
- `backend/app/domain/models.py`
  - Reuse `SessionSummary` and `SessionSummarySource`; no new model required unless a draft dataclass is useful.
- `backend/app/repositories/session_summaries.py`
  - Reuse existing repository; no schema migration expected.
- `backend/app/services/session_summary_service.py`
  - New service and provider implementations.
- `backend/app/services/chat_service.py`
  - Inject optional summary service and call it after successful assistant persistence.
- `backend/app/api/dependencies.py`
  - Wire repository, provider, and service dependencies.
- `backend/tests/test_session_summary_service.py`
  - New unit tests for threshold and generation behavior.
- `backend/tests/test_chat_service.py`
  - Add or extend tests for chat integration and failure isolation.
- `backend/tests/test_config.py`
  - Add settings validation tests.
- `docs/stage3m-session-summary-generation.md`
  - Final evidence document after implementation and validation.

## Test plan

### Service tests

- Disabled summary generation writes nothing.
- Fewer than threshold unsummarized messages writes nothing.
- Exactly threshold unsummarized messages creates one generated summary.
- More than threshold messages creates at most one summary per service call.
- Summary coverage start and end IDs match the summarized batch.
- A later call without enough new messages does not duplicate a summary.
- A later call after enough new messages creates a second summary covering only the new range.
- Provider failure creates no summary and does not raise.
- Empty provider output creates no summary and does not raise.
- Summary metadata records provider, model, schema, threshold, and max input setting.

### Chat integration tests

- Successful chat turn triggers summary generation after the assistant message is saved when the threshold is reached.
- Summary provider failure does not prevent `ChatService.send_message()` from returning the assistant reply.
- Chat provider failure does not trigger summary generation.
- Summary generation does not create or modify long-term memory rows.

### Config tests

- Invalid summary provider is rejected.
- Non-positive trigger threshold is rejected.
- Non-positive max input messages is rejected.
- Non-positive LLM max tokens is rejected.
- Non-positive LLM timeout is rejected.

## Acceptance criteria

Stage 3M is complete when:

1. A successful chat turn can automatically create a generated summary once unsummarized messages reach the configured threshold.
2. Generated summaries are stored in `session_summaries` with correct coverage fields.
3. Summary generation is independently configurable from chat LLM, memory candidates, and embeddings.
4. Default tests use a deterministic fake provider and do not call real APIs.
5. Summary generation failure does not break chat.
6. Summaries are not written to long-term memory and are not injected into chat context by default.
7. Targeted backend tests pass.
8. Documentation records the implemented behavior and stage boundaries.

## Stage boundary check

This design stays within Stage 3 long-term memory infrastructure. It improves conversation-continuity storage but does not implement emotional state, relationship metrics, voice/emotion coordination, avatar expressions, or any Stage 4 behavior.
