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

The recommended production chat path uses a lightweight in-process post-response scheduler. Stage 3M requires the observable behavior, not one specific framework primitive: a successful chat reply must return after the assistant message is persisted and summary work is queued, without awaiting real summary provider generation, timeout, or retries. The implementation may use FastAPI/Starlette `BackgroundTasks`, `asyncio.create_task`, or a small injectable scheduler abstraction, as long as tests can prove the chat response path does not wait for the summary provider.

## Configuration

Add summary-specific settings:

```env
SESSION_SUMMARY_ENABLED=true
SESSION_SUMMARY_PROVIDER=fake
SESSION_SUMMARY_TRIGGER_MESSAGE_COUNT=12
SESSION_SUMMARY_MAX_INPUT_MESSAGES=24
SESSION_SUMMARY_LLM_PROVIDER=deepseek
SESSION_SUMMARY_LLM_MODEL=deepseek-v4-flash
SESSION_SUMMARY_LLM_MAX_TOKENS=512
SESSION_SUMMARY_LLM_TIMEOUT_SECONDS=15
SESSION_SUMMARY_LLM_MAX_RETRIES=0
```

Validation rules:

- `SESSION_SUMMARY_PROVIDER` must be `fake` or `llm`.
- `SESSION_SUMMARY_TRIGGER_MESSAGE_COUNT` must be greater than 0.
- `SESSION_SUMMARY_MAX_INPUT_MESSAGES` must be greater than 0.
- `SESSION_SUMMARY_LLM_PROVIDER` is only used when `SESSION_SUMMARY_PROVIDER=llm`; when used, it must be a real LLM adapter supported by the backend, initially `anthropic` or `deepseek`.
- `SESSION_SUMMARY_LLM_MODEL` is only used when `SESSION_SUMMARY_PROVIDER=llm`; when used, it must be non-empty after trimming.
- `SESSION_SUMMARY_LLM_MAX_TOKENS` must be greater than 0.
- `SESSION_SUMMARY_LLM_TIMEOUT_SECONDS` must be greater than 0.
- `SESSION_SUMMARY_LLM_MAX_RETRIES` must be greater than or equal to 0.

The summary provider setting is intentionally separate from `LLM_PROVIDER`, `LLM_MODEL`, `MEMORY_CANDIDATE_PROVIDER`, and memory embedding settings. Enabling real chat or real memory extraction must not silently enable real summary API calls.

`SESSION_SUMMARY_PROVIDER=llm` is the explicit opt-in switch for real summary API calls. When that switch is enabled, the actual LLM adapter and model come from `SESSION_SUMMARY_LLM_PROVIDER` and `SESSION_SUMMARY_LLM_MODEL`, not from chat defaults. This keeps summary generation independently configurable while still allowing the LLM summary provider implementation to reuse the existing provider interfaces internally.

## Architecture

```text
ChatService
  ├─ save user message
  ├─ call chat LLM provider
  ├─ save assistant message
  ├─ try memory candidate extraction, if configured
  └─ queue session summary generation, if configured

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

For Stage 3M, "not a prerequisite" is a hard behavior requirement: `ChatService.send_message()` must not await real provider generation, provider timeout, retry sleep, or summary persistence before returning a successfully persisted assistant reply. After the assistant message is saved, the app should enqueue summary generation through a lightweight in-process background hook or equivalent best-effort scheduler. Direct `SessionSummaryService` calls remain appropriate in unit tests, internal service tests, and explicit scheduler-drain tests, but production chat handling should treat summary generation as post-response work.

The scheduler boundary should be narrow and replaceable. It only needs to accept the current `session_id` after chat success and run `SessionSummaryService.maybe_generate_for_session(session_id)` best-effort. It does not need a durable queue, distributed lock, worker process, retry daemon, or cross-process coordination in Stage 3M.

If the background summary task fails, times out, or is cancelled during shutdown, the already persisted chat messages remain valid and no chat error is surfaced to the user.

## Data flow

1. `ChatService.send_message()` validates and saves the user message.
2. `ChatService` builds the normal chat context and calls the chat provider.
3. `ChatService` saves the assistant message.
4. Existing memory candidate extraction runs and remains failure-isolated.
5. New session summary generation is queued as post-response best-effort work and remains failure-isolated.
6. `ChatService` returns the chat reply without waiting for summary provider generation, timeout, retry completion, or summary persistence.
7. The queued summary task later invokes `SessionSummaryService.maybe_generate_for_session(session_id)` and handles all provider/service errors internally.

If the chat provider fails, returns an empty reply, or the user message is invalid, no summary-generation attempt occurs.

## Trigger rule

`SessionSummaryService.maybe_generate_for_session(session_id)` performs the trigger decision.

1. If `SESSION_SUMMARY_ENABLED=false`, return without writing.
2. Load the latest summary using `SessionSummaryRepository.latest_for_session(session_id)`.
3. Load the session's persisted user/assistant messages using `MessageRepository.list(session_id)`.
4. If a latest summary exists and its `covered_message_end_id` appears in the message list, consider only messages after that ID.
5. If no latest summary exists, consider all session messages.
6. The candidate set is based on persisted messages, not inferred chat turns. If a previous chat provider failure left a user message without an assistant reply, that persisted user message remains eligible for a later summary batch. The summary prompt/provider must treat input as a raw message segment and must not imply that every user message has a paired assistant answer.
7. If the number of candidate messages is below `SESSION_SUMMARY_TRIGGER_MESSAGE_COUNT`, return without writing.
8. Take at most `SESSION_SUMMARY_MAX_INPUT_MESSAGES` messages from the candidate set for this summary batch.
9. Generate a summary from that batch.
10. Save the summary as `source=generated`.

The service should not generate multiple summaries in one chat turn even if many more than the threshold messages are unsummarized. It generates at most one summary per successful chat turn.

`SESSION_SUMMARY_MAX_INPUT_MESSAGES` may be greater than, equal to, or less than `SESSION_SUMMARY_TRIGGER_MESSAGE_COUNT`. The implementation only requires both settings to be positive. If max input is smaller than the trigger threshold, one generated summary may cover fewer messages than the threshold that triggered it; the remaining messages stay unsummarized until a later successful chat turn.

## Concurrency and duplicate prevention

The app is primarily a local single-user desktop companion, but the backend API can still receive concurrent chat requests for the same session.

Stage 3M should avoid obvious duplicate or overlapping summary writes without introducing heavy infrastructure:

- Summary generation may run outside the main chat response path, but the final coverage decision and insert should be guarded by a lightweight recheck.
- Immediately before writing, the service should reload `latest_for_session(session_id)`. If another summary already covers the proposed `covered_message_start_id` or reaches an equal/newer `covered_message_end_id`, the service should skip writing.
- If the repository later gains a uniqueness constraint for generated summaries, a duplicate insert failure should be treated as a benign skipped write, not as a chat failure.
- Stage 3M does not require distributed locks, background queues, or multi-process scheduling. It only needs best-effort duplicate prevention suitable for the current local SQLite backend.

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

Also record lightweight trigger metadata that helps audit partial batches without duplicating the full input:

- `provider`
- `model`
- `summary_schema`
- `trigger_message_count`
- `max_input_messages`
- `candidate_message_count`
- `input_message_count`

## Provider interface

`SessionSummaryProvider` should be an async boundary so fake and real providers share the same call shape:

```python
async def generate(messages: list[Message], options: SessionSummaryOptions) -> SessionSummaryProviderResult:
    ...
```

`SessionSummaryProviderResult` should include at least:

- `text`: generated summary text.
- `provider`: provider identifier such as `fake` or `deepseek`.
- `model`: resolved provider/model identifier such as `fake-session-summary-v1`.
- `metadata`: optional provider metadata safe to persist.

Provider implementations may use internal helper classes, but business services should depend on the `SessionSummaryProvider` boundary rather than direct vendor SDK calls.

## Provider behavior

### FakeSessionSummaryProvider

The fake provider must be deterministic. It can produce a compact summary such as:

```text
本段会话共有 12 条消息。用户主要提到：<sanitized first user excerpt>。助手主要回应：<sanitized first assistant excerpt>。未解决或可延续的话题：继续围绕本段会话内容展开。
```

The output must be non-empty when input messages are non-empty.

The fake provider must not store raw secrets by accident. Any excerpt copied from input messages must pass through the same lightweight summary sanitization used for LLM output, or the fake provider should avoid direct excerpts entirely. Sanitization should cover obvious API keys, bearer tokens, passwords, and token-like `key=value` or `token: value` patterns. This is not a perfect DLP system; it is a best-effort safety boundary for the default provider path.

### LLMSessionSummaryProvider

The LLM provider is opt-in only. It may reuse the existing `LLMProvider` interface internally, but it is selected only by `SESSION_SUMMARY_PROVIDER=llm`, not by the chat provider setting alone. Its adapter and model are resolved from `SESSION_SUMMARY_LLM_PROVIDER` and `SESSION_SUMMARY_LLM_MODEL`.

The LLM prompt must instruct the model that:

- It is summarizing a bounded session message segment.
- The segment may contain unmatched user or assistant messages because it is based on persisted message history rather than inferred completed turns.
- The summary is not a long-term memory.
- It must not create user facts, relationship scores, emotional state, or memory candidates.
- It must not include API keys, tokens, passwords, or credentials.
- It must write concise Chinese suitable for future conversation-continuity review.

Before any message content is sent to a real external LLM summary adapter, the input segment must pass through the same best-effort summary sanitization used for provider output. Sanitization happens before prompt construction: the LLM summary prompt is built from redacted message objects, not from raw persisted message text. This protects the opt-in LLM path from sending obvious API keys, bearer tokens, passwords, and token-like `key=value` or `token: value` patterns to an external provider by default.

The LLM summary adapter must not receive both raw and sanitized message variants. Its input contract is the sanitized segment plus summary options. Raw persisted messages remain available only inside repository/service selection logic before the sanitization boundary.

This input sanitization is intentionally best effort, not a DLP guarantee. If a future task wants to send raw unsanitized message content to improve summary quality, that must be a separate explicit opt-in design with documented privacy trade-offs.

LLM failure, empty output, or invalid output must not break chat. LLM output must pass through the same summary sanitization step before persistence; if sanitization yields an empty string, no summary record is created.

## Error handling

Scheduling failures and background execution failures must be isolated from chat. If queueing summary work raises unexpectedly, `ChatService` catches that scheduling error and still returns the already persisted assistant reply. Once the queued task starts, the scheduler or task wrapper catches `SessionSummaryService` exceptions so provider/service failures are not surfaced as chat errors.

This mirrors the existing memory-candidate failure isolation while preserving the non-blocking chat-return requirement.

`SessionSummaryService` should avoid partial writes. If provider generation fails or produces an empty summary, no summary record is created.

The service should sanitize provider output before trimming/empty-output validation and persistence. If sanitization removes all meaningful text, no summary record is created.

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
- Real LLM summary adapter/model selection is explicit through `SESSION_SUMMARY_LLM_PROVIDER` and `SESSION_SUMMARY_LLM_MODEL`.
- No API keys, tokens, passwords, or credentials should be stored in summary metadata.
- Summary prompts must instruct LLM providers not to include credentials in the summary.
- Fake and LLM provider inputs and outputs must pass through best-effort secret sanitization before external LLM calls and before persistence.
- For `SESSION_SUMMARY_PROVIDER=llm`, prompt construction must use sanitized message content only; tests must prove the LLM adapter mock receives redacted content instead of raw secrets.
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
  - Include a small sanitization boundary shared by fake output, LLM input, and persisted output paths.
- `backend/app/services/chat_service.py`
  - Inject optional summary scheduler/service and queue it after successful assistant persistence without awaiting provider work.
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
- Summary metadata records provider, model, schema, threshold, max input setting, candidate message count, and input message count.
- Summary text sanitization redacts obvious credentials from fake and LLM provider outputs.
- LLM provider input sanitization redacts obvious credentials before prompt construction; the LLM adapter mock must receive only redacted message content.
- A persisted user message left by a failed chat provider call can be included in a later summary batch without implying it had a paired assistant reply.
- A concurrent or repeated generation attempt skips writing if a recheck shows that another summary already covers the proposed message range.

### Chat integration tests

- Successful chat turn queues summary generation after the assistant message is saved when the threshold is reached.
- `ChatService.send_message()` returns the assistant reply without awaiting a slow summary provider, provider timeout, retry sleep, or summary persistence.
- Scheduler/service failures do not prevent `ChatService.send_message()` from returning the assistant reply.
- Chat provider failure does not trigger summary generation.
- Summary generation does not create or modify long-term memory rows.

### Config tests

- Invalid summary provider is rejected.
- Invalid summary LLM provider is rejected when LLM summaries are enabled.
- Empty summary LLM model is rejected when LLM summaries are enabled.
- Non-positive trigger threshold is rejected.
- Non-positive max input messages is rejected.
- Non-positive LLM max tokens is rejected.
- Non-positive LLM timeout is rejected.
- Negative LLM max retries is rejected.

## Acceptance criteria

Stage 3M is complete when:

1. A successful chat turn can automatically create a generated summary once unsummarized messages reach the configured threshold.
2. Generated summaries are stored in `session_summaries` with correct coverage fields.
3. Summary generation is independently configurable from chat LLM, memory candidates, and embeddings.
4. Default tests use a deterministic fake provider and do not call real APIs.
5. Chat responses do not wait for summary provider generation, timeout, retry sleep, or summary persistence.
6. Real LLM summary input is sanitized before prompt construction, and tests verify the external adapter sees redacted content rather than raw secrets.
7. Summary generation failure does not break chat.
8. Summaries are not written to long-term memory and are not injected into chat context by default.
9. Targeted backend tests pass.
10. Documentation records the implemented behavior and stage boundaries.

## Stage boundary check

This design stays within Stage 3 long-term memory infrastructure. It improves conversation-continuity storage but does not implement emotional state, relationship metrics, voice/emotion coordination, avatar expressions, or any Stage 4 behavior.
