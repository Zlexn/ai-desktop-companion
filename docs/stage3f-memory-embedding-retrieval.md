# Stage 3F Memory Embedding Retrieval

Date: 2026-07-08
Status: VERIFIED PASS

## Scope

Stage 3F adds opt-in local embedding retrieval for confirmed active long-term memories. It preserves manual memory CRUD, pending candidate confirmation/dismissal, conflict audit, deterministic fallback, and caveated memory context injection.

The first slice uses a SQLite `memory_embeddings` table plus Python cosine similarity. It includes a deterministic fake embedding provider for tests and local smoke, and an optional lazy `sentence-transformers` provider behind explicit configuration.

## Non-goals

- No LLM-based memory extraction.
- No automatic memory writes from chat history.
- No session summaries.
- No Stage 4 emotion system.
- No mandatory external vector database.
- No mandatory `sentence-transformers` runtime dependency for default tests.
- No sqlite-vec production integration in this slice.

## Configuration

Default behavior remains deterministic relevance retrieval:

```env
MEMORY_RETRIEVAL_MODE=relevance
MEMORY_EMBEDDING_ENABLED=false
```

To exercise the local fake embedding path:

```env
MEMORY_RETRIEVAL_MODE=embedding
MEMORY_EMBEDDING_ENABLED=true
MEMORY_EMBEDDING_PROVIDER=fake
MEMORY_EMBEDDING_MODEL=fake-memory-embedding-v1
MEMORY_EMBEDDING_MIN_SCORE=0.35
```

## Behavior

- Only active memories are eligible for embedding retrieval.
- Pending, dismissed, and archived memories do not enter chat context.
- Manual memory create/update and candidate confirm maintain embedding rows when embedding is enabled.
- Memory archive deletes the embedding row when embedding is enabled.
- Embedding retrieval failure falls back to existing deterministic relevance retrieval.
- Chat remains usable if embedding provider/model execution fails.
- Memory context caveats remain unchanged: retrieved memories are user-viewable, editable, deletable, may be outdated/incomplete, and must not be described as absolute facts.

## Validation

Commands run on 2026-07-08:

- `python -m pytest backend/tests/test_config.py -q` → 38 passed.
- `python -m pytest backend/tests/test_memory_embeddings.py -q` → 6 passed.
- `python -m pytest backend/tests/test_context_builder.py -q` → 8 passed.
- `python -m pytest backend/tests/test_api_memories.py -q` → 15 passed.
- `python -m pytest backend/tests/test_chat_service.py backend/tests/test_context_builder.py -q` → 18 passed.
- `python -m pytest backend/tests/test_config.py backend/tests/test_memory_embeddings.py backend/tests/test_context_builder.py backend/tests/test_api_memories.py backend/tests/test_chat_service.py -q` → 78 passed.
- `python -m pytest backend/tests -q` → 301 passed.
- `npm --prefix frontend test -- --run` → 17 files / 152 tests passed.
- `npm --prefix frontend run typecheck` → PASS.
- `npm --prefix frontend run build` → PASS; Vite built 36 modules.
- `npm --prefix frontend run test:e2e` → 7 passed.

## Limitations

This is a local vertical slice, not a final high-performance vector index. Vectors are stored as JSON in SQLite and ranked in Python. Real `sentence-transformers` usage remains optional and should be smoke-tested separately with a chosen local Chinese-capable embedding model before being treated as production-ready.

Stage 4 remains unstarted.
