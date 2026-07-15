# Chat Provider Context Character Budget Design

> Date: 2026-07-12  
> Status: Implemented and verified

## Goal

Bound the final text sent to the chat LLM so large historical messages cannot grow Provider input without limit. This is the sole Stage 3 closeout blocker; it must not introduce session-summary injection, conflict automation, emotion state, or Provider-specific tokenization.

## Current failure

`ContextBuilder` limits recent history by message count only. `ChatService` later prepends the role system prompt, so no component currently sees or limits the complete Provider payload. The existing regression test requires the final payload to retain the role system prompt and current user message while staying within 24,000 characters.

## Alternatives

1. **Final-boundary character budget in `ChatService` — chosen.** It sees the role prompt, memory system context, recent history, and current user message together. It is deterministic and Provider-independent.
2. **Budget only in `ContextBuilder` — rejected.** It cannot account for the role system prompt, so it cannot guarantee a final limit.
3. **Provider-specific tokenizers — rejected for this slice.** More precise, but adds dependencies, model-specific behavior, and supplier coupling. A character budget is a conservative deterministic guard.

## Architecture

Add an externally configured positive integer `CHAT_CONTEXT_MAX_CHARACTERS`, default `24000`, to `Settings`, `.env.example`, validation, and redacted diagnostics.

`ChatService` continues to obtain memory and recent-history messages from `ContextBuilder`. Immediately before `LLMProvider.generate()`, it applies one private final-boundary helper to the complete ordered list:

1. role system prompt;
2. optional long-term-memory system message;
3. historical user/assistant messages;
4. current user message.

No repository or Provider adapter changes are required.

## Retention and trimming rules

The helper receives the final ordered `LLMMessage` list and the budget.

Hard-preserved messages:

- the first role system prompt;
- the final current user message.

Soft messages are removed whole; message text is never truncated.

Removal order:

1. remove oldest historical user/assistant messages one at a time;
2. if still over budget, remove optional system context blocks between the role prompt and conversation history, including long-term-memory context;
3. stop when the payload fits or only the two hard-preserved messages remain.

If the role prompt plus current user message alone exceed the configured budget, send both unchanged. This is an explicit overflow exception: preserving current intent and role boundary is safer than silently truncating either. The helper must terminate deterministically and preserve original order among retained messages.

This slice does not enforce conversational pair removal. A historical message is an independent persisted segment, consistent with Stage 3M's existing non-pairing rule.

## Data flow

1. Persist current user message.
2. Render role system prompt.
3. Build active-memory context and recent persisted messages.
4. Form the complete Provider message list.
5. Apply the character budget to that final list.
6. Call the configured chat Provider.
7. Persist a valid assistant response and continue existing memory-candidate and summary scheduling behavior.

The budget helper changes only outbound Provider context. It does not delete or modify persisted messages, memories, summaries, or embeddings.

## Error handling

- Invalid configuration (`<= 0` or non-integer) fails at settings load with a clear environment-variable error.
- Trimming performs no I/O and raises no expected domain error.
- Provider and chat error behavior remains unchanged.
- The hard-preserved overflow exception is observable through tests and documented, not logged with message content.

## Tests

Configuration tests:

- default is 24,000;
- explicit positive override loads;
- zero, negative, and non-integer values are rejected;
- redacted diagnostics include the non-secret value.

ChatService tests:

- the existing large-history regression becomes green;
- first role system prompt and final current user message remain;
- oldest history is removed before newer history;
- memory system context remains when dropping history is sufficient;
- memory system context is removed if history removal is insufficient;
- retained messages preserve order;
- no message content is truncated;
- role prompt plus current user overflow is allowed unchanged;
- persisted history remains intact after outbound trimming;
- summary remains absent from context, and memory candidate/summary scheduling behavior is unchanged.

Verification:

- focused config and ChatService tests pass;
- full backend suite becomes fully green (expected current total: 399 plus any new tests);
- Stage 3M production-composition tests remain green;
- real fake-provider API smoke still returns normally;
- no frontend file changes in this slice.

## Out of scope

- exact tokenizer accounting;
- per-Provider budgets;
- truncating individual messages;
- summary injection or summary-based replacement;
- automatic conflict resolution;
- Stage 4 emotional state;
- fixing the separate MemoryPanel editing UI gap.
