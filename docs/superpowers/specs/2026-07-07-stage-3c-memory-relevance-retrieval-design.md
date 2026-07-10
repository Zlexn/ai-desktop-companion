# Stage 3C Memory Relevance Retrieval Design

Date: 2026-07-07
Status: Design approved for spec writing; awaiting user review before implementation planning

## Context

The project is in Stage 3: long-term memory. Stage 3A added manual long-term memory CRUD, independent SQLite storage, duplicate conflict visibility, caveated memory context injection, and a minimal memory UI. Stage 3B added heuristic pending memory candidates, user confirmation/dismissal, and ensured pending/dismissed candidates do not enter chat context.

The current memory context selection is still simple: `MemoryRepository.list_for_context(limit)` returns active memories ordered by importance and update time. This can inject high-importance but unrelated memories into chat, while more relevant memories may be excluded when the user asks about a specific topic.

Stage 3C improves retrieval within the existing local SQLite architecture. It selects active long-term memories by relevance to the current user message before injecting them into chat context.

This design stays within Stage 3. It does not implement vector/embedding retrieval, semantic contradiction detection, session summaries, LLM-based memory extraction, or Stage 4 emotion state.

## Goals

- Select active long-term memories that are relevant to the current user message.
- Preserve the caveated memory-context boundary: memories are user-editable context, may be outdated, and must not be treated as absolute facts.
- Exclude pending, dismissed, and archived memories from chat context.
- Keep retrieval deterministic, local, dependency-free, and testable.
- Preserve existing manual memory and candidate confirmation flows.
- Provide a safe fallback when no memory is clearly relevant.

## Non-goals

- No vector database.
- No embedding provider.
- No LLM reranker.
- No semantic contradiction detection.
- No audit-log expansion.
- No session summary storage.
- No automatic backfill from old chat history.
- No Stage 4 emotional state or relationship metrics.

## Recommended approach

Implement local deterministic relevance retrieval using simple token overlap, type hints, and existing memory fields. The retrieval should be good enough to avoid obvious irrelevant memory injection, while staying small and reversible.

The current context flow is:

1. `ChatService.send_message(session_id, user_text)` saves the user message.
2. `ContextBuilder.build_context(session_id)` loads memory context and recent chat context.
3. `MemoryRepository.list_for_context(limit)` returns active memories by importance/update time.

Stage 3C changes this to:

1. `ChatService.send_message(session_id, user_text)` saves the user message.
2. `ContextBuilder.build_context(session_id, query=clean_text)` receives the current user text as a retrieval query.
3. `ContextBuilder.build_memory_context(query=clean_text)` calls relevance retrieval when enabled.
4. `MemoryRepository.list_relevant_for_context(query, limit, fallback_limit)` scores active memories and returns relevant rows.
5. Recent chat context remains unchanged.

`MemoryRepository.list_for_context(limit)` remains available as the existing ordering/fallback path.

## Retrieval behavior

### Candidate scope

Only active memories are eligible:

- `status = active` is eligible.
- `status = pending` is not eligible.
- `status = dismissed` is not eligible.
- `status = archived` is not eligible.

This preserves the Stage 3B guarantee that candidates do not affect chat until confirmed.

### Query source

The query is the cleaned current user message being processed by `ChatService`. The retrieval query is not persisted separately and is not written into memory metadata.

### Token extraction

Use a small local tokenizer helper. It should be deterministic and dependency-free.

- Lowercase the text.
- Extract ASCII words and numbers as tokens.
- Extract Chinese character n-grams for CJK text, preferably 2-character grams and selected longer contiguous runs.
- Filter common low-signal tokens such as `我`, `你`, `的`, `了`, `吗`, `呢`, `什么`, `一下`, `请`, `帮我`.
- Ignore empty token sets.

The tokenizer does not need full Chinese segmentation. This slice prioritizes predictable tests over semantic completeness.

### Type hints

Add small type-hint bonuses when the query contains obvious cues:

- `preference`: `喜欢`, `偏好`, `讨厌`, `不喜欢`, `爱喝`, `爱吃`
- `long_term_goal`: `目标`, `准备`, `计划`, `打算`, `想要完成`
- `user_fact`: `住`, `职业`, `名字`, `事实`, `哪里`, `是谁`
- `important_event`: `发生`, `那次`, `事件`, `重要`, `记得那天`
- `relationship_event`: `关系`, `认识`, `一起`, `我们`, `相处`

These hints only affect ranking. They do not create memories and do not infer emotional state.

### Scoring

Each active memory receives a relevance score:

- Token overlap between query and memory content is the main signal.
- Type-hint match adds a small bonus.
- Importance adds a small tie-break bonus.
- Confidence adds a small tie-break bonus.
- Updated time remains the final database-level ordering fallback.

A memory with zero relevance score is considered unrelated for a query with usable tokens/type hints.

Suggested scoring shape for implementation:

- `overlap_count * 10`
- `type_hint_match * 3`
- `importance * 0.2`
- `confidence * 0.2`

Exact constants may be adjusted in implementation tests, but overlap must dominate importance so an unrelated high-importance memory does not outrank a clearly relevant memory.

### Fallback behavior

When no active memory has a positive relevance score:

- Return existing high-priority active memories from `list_for_context`, but only up to `fallback_limit`.
- Default `fallback_limit` should be small, such as 3.
- This avoids flooding the prompt with unrelated memories.

When there are positive relevance matches:

- Return only positively scored memories, sorted by score, then importance, confidence, and update time.
- Do not mix unrelated fallback memories into a relevant result set.

## Configuration

Add two settings:

- `MEMORY_RETRIEVAL_MODE`
  - Default: `relevance`
  - Allowed values: `relevance`, `recent`
  - `recent` preserves the Stage 3A/3B behavior using `list_for_context(limit)`.

- `MEMORY_RETRIEVAL_FALLBACK_LIMIT`
  - Default: `3`
  - Must be greater than 0.
  - Effective limit must not exceed `MEMORY_CONTEXT_LIMIT`.

No new API keys or provider credentials are needed.

## ContextBuilder changes

Extend `ContextBuilder` methods:

- `build_memory_context(query: str | None = None)`
- `build_context(session_id: str, query: str | None = None)`

Behavior:

- If memory context is disabled, return no memory context.
- If no memory repository is configured, return no memory context.
- If retrieval mode is `recent` or query is blank, use existing `list_for_context(limit)` behavior.
- If retrieval mode is `relevance`, use `list_relevant_for_context(query, limit, fallback_limit)`.
- The formatted system memory message keeps the existing caveat.
- The memory message may add one short line saying the records were selected for relevance to the current message, but it must not expose internal scores.

## ChatService changes

Pass the current cleaned user message into context building:

- Before: `context = self._context_builder.build_context(session_id)`
- After: `context = self._context_builder.build_context(session_id, query=clean_text)`

This happens after the user message is saved and before provider generation, preserving the current ordering and candidate generation behavior.

Candidate generation remains after assistant reply persistence and is not part of retrieval.

## Error handling and privacy

- Retrieval is local and deterministic; it should not call external services.
- The query text is the current user message already being processed for chat. Do not persist it separately for retrieval.
- Do not log token lists, scores, or raw user messages.
- If scoring receives malformed or empty input, it should fall back safely rather than raise.
- Existing repository/database errors can follow current backend error handling.

## Testing plan

### Repository tests

Add tests for:

- Relevant active memory outranks unrelated high-importance memory.
- Pending, dismissed, and archived memories are excluded.
- Type-hint query boosts matching memory type.
- No positive relevance returns only `fallback_limit` high-priority active memories.
- `recent` fallback behavior still returns existing `list_for_context` ordering.

### ContextBuilder tests

Add tests for:

- `build_context(session_id, query='我喜欢什么饮料？')` includes `用户喜欢红茶。`.
- The same context excludes unrelated active memories when relevant matches exist.
- Caveat text remains present.
- `memory_context_enabled=False` still disables memory context.
- Recent chat messages remain chronological and unchanged.

### ChatService/API tests

Add or update tests so the fake provider receives:

- Relevant active memory in the system context when user asks about that topic.
- No unrelated high-importance memory when a relevant memory exists.

Keep candidate generation tests intact.

### Regression tests

After implementation:

- Run focused backend tests for repositories, context builder, chat service/API, config.
- Run full backend pytest.
- Run frontend unit tests, typecheck, build, and Playwright E2E to confirm no UI or voice regression.

## Documentation updates

After verified implementation, create:

- `docs/stage3c-memory-relevance-retrieval.md`

Update `CLAUDE.md` only after validation passes. The update should record Stage 3C completion, validation commands, and limitations.

## Risks and mitigations

- Risk: simple tokenizer misses semantic matches.
  - Mitigation: acceptable for this slice; keep it conservative and dependency-free. Embeddings can be a later Stage 3 subtask.

- Risk: high-importance unrelated memories still appear.
  - Mitigation: when positive relevance matches exist, do not mix unrelated fallback memories.

- Risk: Chinese tokenization is noisy.
  - Mitigation: use tests around expected Chinese phrases and keep fallback small.

- Risk: retrieval changes provider prompt unexpectedly.
  - Mitigation: focused fake-provider tests inspect context content; full regression covers chat and voice paths.

- Risk: scope drifts into Stage 4.
  - Mitigation: no mood, trust, concern, distance, irritation, formality, relationship score, or emotional state is introduced.

## Implementation boundary

This design is ready for one implementation plan. The implementation should be test-driven and staged:

1. Config settings for retrieval mode and fallback limit.
2. Repository relevance scoring and retrieval tests.
3. ContextBuilder query-aware retrieval tests and implementation.
4. ChatService query pass-through tests and implementation.
5. Focused regression and full validation.
6. Evidence documentation and `CLAUDE.md` update after validation.

No code should be written until the user approves this written spec and an implementation plan is created.
