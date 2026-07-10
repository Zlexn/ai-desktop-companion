# Stage 3F Opt-in Local Embedding Retrieval Design

Date: 2026-07-08
Status: Recommended design selected by user default; ready for implementation planning

## Context

The project is in Stage 3: long-term memory. Stage 3A added manual long-term memory CRUD, independent SQLite storage, caveated memory context injection, and a minimal UI. Stage 3B added heuristic pending memory candidates and explicit user confirmation/dismissal. Stage 3C added deterministic relevance retrieval. Stage 3D added persistent conflict audit events. Stage 3E added conservative deterministic semantic conflict detection.

The remaining retrieval limitation is semantic recall. The deterministic token/type-hint scorer avoids many irrelevant memories, but it can miss related Chinese conversational queries when the user's wording does not overlap with the stored memory sentence.

A deep-research pass on 2026-07-08 compared vector/embedding retrieval, LLM-based candidate extraction, and independent session summaries. The strongest recommendation for the next minimal Stage 3 loop was opt-in local embedding retrieval over confirmed active long-term memories. This changes only recall/ranking for memories the user has already confirmed, so it is safer than changing memory writes with LLM extraction and smaller than adding a separate session-summary storage lane.

This design stays within Stage 3. It does not implement automatic memory writing, LLM-based extraction, session summaries, vector database services, sqlite-vec production integration, or Stage 4 emotion state.

## Goals

- Improve semantic retrieval for confirmed active long-term memories.
- Preserve manual CRUD, pending candidate confirmation, conflict audit, and conservative conflict detection behavior.
- Keep pending, dismissed, and archived memories out of chat context.
- Keep deterministic `relevance` and `recent` retrieval modes available as fallback and compatibility paths.
- Make embedding retrieval opt-in and locally testable.
- Avoid making chat fail when embedding generation or embedding search fails.
- Keep chat history, session summaries, and long-term memories separate.

## Non-goals

- No LLM-based memory candidate extraction.
- No automatic conversion of chat history into long-term memory.
- No session-summary table or summary injection.
- No Stage 4 mood, trust, concern, distance, irritation, formality, relationship score, affect decay, or expression strategy state.
- No external vector database service.
- No mandatory sqlite-vec dependency in this first slice.
- No UI for inspecting raw embeddings or similarity scores.
- No backfill of old chat history.

## Recommended approach

Implement an opt-in local embedding retrieval vertical slice using SQLite as the storage boundary and Python cosine similarity for the first implementation.

The research pass found sqlite-vec attractive for the repo's SQLite-first architecture, but also flagged Windows extension loading and packaging as risks. Therefore, this first closed loop should avoid making sqlite-vec a hard dependency. Instead, it should introduce small provider/repository boundaries that can later be backed by sqlite-vec after a dedicated feasibility check.

The first slice should include:

1. A memory embedding provider interface.
2. A deterministic fake embedding provider for tests.
3. An optional local `sentence-transformers` provider behind explicit configuration.
4. A SQLite `memory_embeddings` table keyed by memory ID.
5. Repository methods to upsert, remove, and search embeddings.
6. ContextBuilder support for `MEMORY_RETRIEVAL_MODE=embedding`.
7. Fallback to existing deterministic relevance retrieval when embeddings are disabled, unavailable, stale, empty, or below threshold.

## Architecture

### `MemoryEmbeddingProvider`

Add a small provider abstraction under a Stage 3 memory-specific module, for example `backend/app/memory/embeddings.py` or `backend/app/services/memory_embedding_service.py`.

Interface shape:

- `embed_text(text: str) -> list[float]`
- `provider_name: str`
- `model_name: str`
- `dimension: int | None` after initialization or first embedding

Providers:

- `FakeMemoryEmbeddingProvider`
  - Used in tests and default safe paths.
  - Deterministic and dependency-free.
  - Designed so test phrases with related meaning can be made close without external models.

- `SentenceTransformersMemoryEmbeddingProvider`
  - Explicitly enabled only when configured.
  - Imports `sentence_transformers` lazily so normal backend startup and tests do not require the optional dependency.
  - Loads the configured local model name/path.
  - Raises a clear configuration/runtime error if the dependency or model is unavailable.

### `MemoryEmbeddingRepository`

Add a repository for a new SQLite table.

Suggested schema:

```sql
CREATE TABLE IF NOT EXISTS memory_embeddings (
    memory_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    dimension INTEGER NOT NULL CHECK (dimension > 0),
    embedding_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memory_embeddings_provider_model
ON memory_embeddings(provider, model);
```

Store vectors as JSON in this first slice. This is intentionally simple and auditable. It is not the final high-performance vector index.

Repository responsibilities:

- `upsert(memory_id, provider, model, embedding, content_hash)`
- `delete(memory_id)`
- `get(memory_id)`
- `list_for_active_memories(provider, model)` or equivalent active-memory join
- `search_active(query_embedding, provider, model, limit, min_score)`

`search_active` should join or filter through `memories.status = active`. It must never return pending, dismissed, or archived memories.

### `MemoryEmbeddingService`

Add a small service to coordinate provider and repository:

- `ensure_embedding(memory: Memory) -> None`
- `delete_embedding(memory_id: str) -> None`
- `search_relevant(query: str, limit: int, min_score: float) -> list[Memory]`

The service computes a stable content hash from memory content plus memory type. If the hash matches the stored row for the current provider/model, it does not recompute.

Failures should be handled differently depending on call site:

- During memory mutation, embedding failure must not roll back successful memory create/update/confirm. It can be reported in metadata or logged as a redacted warning.
- During chat context retrieval, embedding failure must fall back to deterministic relevance retrieval.

### Integration with memory mutations

Hook embedding maintenance into existing memory mutation flows after the memory mutation succeeds:

- manual create active memory: upsert embedding if embedding is enabled;
- update active memory: refresh embedding if embedding is enabled;
- confirm pending candidate: upsert embedding after status becomes active;
- dismiss pending candidate: no embedding;
- archive memory: delete embedding or rely on active-status filtering. Prefer deletion for a clearer invariant.

These hooks should not change API response shapes unless a minimal non-breaking metadata field is already consistent with existing response conventions. Prefer no response-shape change in this slice.

### Integration with `ContextBuilder`

Extend existing retrieval mode values:

- `recent`: current importance/update ordering;
- `relevance`: current deterministic token/type-hint scoring;
- `embedding`: new embedding retrieval with fallback to deterministic relevance.

When `memory_context_enabled` is false, no memory context is injected.

When mode is `embedding`:

1. If query is blank, use existing recent fallback.
2. Try embedding retrieval.
3. If embedding retrieval returns at least one result above threshold, inject those memories using the existing caveated memory context format.
4. If embedding retrieval fails or returns no result, call existing `list_relevant_for_context(query, limit, fallback_limit)`.

The system memory caveat remains unchanged: memories are user-viewable, editable, deletable, may be outdated/incomplete, and must not be described as absolute facts.

## Configuration

Add settings:

- `MEMORY_RETRIEVAL_MODE`
  - Allowed values: `embedding`, `relevance`, `recent`.
  - Default remains `relevance` to avoid changing behavior until explicitly enabled.

- `MEMORY_EMBEDDING_ENABLED`
  - Default: `false`.
  - If false, embedding maintenance and embedding retrieval are skipped even if dependencies exist.

- `MEMORY_EMBEDDING_PROVIDER`
  - Allowed values: `fake`, `sentence-transformers`.
  - Default: `fake` for tests and local smoke.

- `MEMORY_EMBEDDING_MODEL`
  - Default: `fake-memory-embedding-v1` for the fake provider.
  - For real provider, must be a local or resolvable sentence-transformers model name/path.

- `MEMORY_EMBEDDING_MIN_SCORE`
  - Default: `0.35`.
  - Must be between `0.0` and `1.0`.

No API keys are required for the first slice.

## Error handling and privacy

- Do not log raw user messages, raw memory contents, raw embeddings, or full similarity lists.
- Redact or summarize embedding provider errors in application logs.
- Embedding retrieval must not make chat fail.
- Embedding maintenance must not make memory CRUD fail after the primary memory mutation has succeeded.
- The current user query is already part of chat processing; do not persist it separately for retrieval.
- Embeddings are derived from long-term memory content and stored locally in SQLite.
- Pending and dismissed candidates must not be embedded for chat retrieval unless they are confirmed active.
- Archived memories must not be returned even if a stale embedding row exists.

## Testing plan

### Repository tests

Add tests for:

- `memory_embeddings` table is created by `init_db`.
- Upsert and get embedding round-trip.
- Updating the same memory/provider/model replaces vector and content hash.
- Deleting a memory cascades or otherwise removes embedding rows.
- `search_active` excludes pending, dismissed, and archived memories.
- `search_active` respects provider/model filters and min score.

### Provider/service tests

Add tests for:

- Fake provider returns deterministic vectors.
- Similar fake concepts can rank above unrelated concepts for controlled fixtures.
- Service skips recompute when content hash matches.
- Service refreshes embedding when content changes.
- Provider failure is surfaced to retrieval caller so fallback can happen.

### ContextBuilder tests

Add tests for:

- `MEMORY_RETRIEVAL_MODE=embedding` injects semantically relevant active memory.
- Embedding mode falls back to deterministic relevance when embedding service raises.
- Embedding mode falls back when no embedding result crosses threshold.
- Existing `relevance` and `recent` behavior remains unchanged.
- Caveat text remains present.

### API/chat tests

Add or update tests for:

- Manual memory create with embedding enabled creates an embedding row.
- Confirming a pending candidate creates an embedding row.
- Updating an active memory refreshes the row.
- Archiving a memory removes it from embedding retrieval.
- Chat fake provider receives embedding-selected memory context when mode is `embedding`.
- Chat still succeeds when embedding retrieval fails.

### Regression tests

After implementation:

- Run focused backend tests for config, repositories, memory API, context builder, and chat service.
- Run full backend pytest.
- Run frontend unit tests.
- Run frontend typecheck.
- Run frontend build.
- Run Playwright E2E if runtime dependencies are available.

## Documentation updates

After verified implementation, create `docs/stage3f-memory-embedding-retrieval.md` with:

- scope and non-goals;
- configuration;
- validation commands and results;
- limitations;
- confirmation that Stage 4 remains unstarted.

Update `CLAUDE.md` only after validation passes. The update should record Stage 3F completion and evidence.

## Risks and mitigations

- Risk: sqlite-vec would be more efficient than JSON + Python cosine.
  - Mitigation: this slice intentionally prioritizes a stable boundary. The repository/service abstraction can later be backed by sqlite-vec.

- Risk: fake embeddings may not represent real Chinese semantic quality.
  - Mitigation: fake provider only validates plumbing. Real provider smoke should be documented separately when dependency/model availability is confirmed.

- Risk: real sentence-transformers dependency is large.
  - Mitigation: keep it optional, lazy-imported, and disabled by default.

- Risk: embedding retrieval returns irrelevant memories.
  - Mitigation: use min score, active-status filtering, and fallback behavior; do not expose embeddings as facts.

- Risk: stale embeddings after memory edits.
  - Mitigation: use content hash and refresh on update/confirm/create.

- Risk: crossing into Stage 4 by using memories to infer relationship/emotion.
  - Mitigation: this slice only returns memory context. It does not create mood, trust, concern, distance, irritation, formality, or expression strategy state.

## Future work after 3F

Recommended next tasks after 3F validation:

1. 3G: LLM-based user-confirmed memory candidate extraction, still pending-only and never auto-active.
2. 3H: independent session-summary storage lane, separate from chat history and long-term memory.
3. sqlite-vec feasibility or replacement of JSON cosine search if local packaging is verified.
