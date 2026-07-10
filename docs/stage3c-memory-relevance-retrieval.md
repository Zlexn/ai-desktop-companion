# Stage 3C Memory Relevance Retrieval Evidence

Status: COMPLETED on 2026-07-07.

## Scope

This slice implements Stage 3C long-term memory relevance retrieval:

- Active memories can be selected by relevance to the current user message.
- Relevant memories can outrank unrelated high-importance memories.
- Pending, dismissed, and archived memories remain excluded from chat context.
- Retrieval remains local, deterministic, dependency-free, and configurable.
- Existing recent/importance ordering remains available via `MEMORY_RETRIEVAL_MODE=recent`.

It does not implement vector retrieval, embeddings, LLM reranking, semantic contradiction detection, session summaries, audit-log expansion, or Stage 4 emotion state.

## Implemented behavior

- `MEMORY_RETRIEVAL_MODE=relevance` is the default.
- `MEMORY_RETRIEVAL_MODE=recent` preserves previous memory context ordering.
- `MEMORY_RETRIEVAL_FALLBACK_LIMIT` caps fallback memories when no relevant match exists.
- `ChatService` passes the current user message to `ContextBuilder` as the memory retrieval query.
- Memory context caveats remain present.

## Validation

| Command | Result |
|---|---|
| `python -m pytest backend/tests/test_config.py backend/tests/test_repositories.py backend/tests/test_context_builder.py backend/tests/test_chat_service.py -q` | PASS — 70 passed in 1.07s |
| `python -m pytest backend/tests` | PASS — 271 passed in 11.73s |
| `npm --prefix frontend test -- --run` | PASS — 17 files / 152 tests passed in 11.77s |
| `npm --prefix frontend run typecheck` | PASS |
| `npm --prefix frontend run build` | PASS — Vite transformed 36 modules, built in 263ms |
| `npm --prefix frontend run test:e2e` | PASS — 7 passed in 10.6s |

## TDD notes

- Config tests cover retrieval mode parsing, redacted settings, unknown mode rejection, and fallback-limit validation.
- Repository tests cover relevance ordering, active-only context eligibility, type-hint ranking, and small fallback behavior.
- ContextBuilder tests cover query-aware retrieval, caveated memory context, and recent-mode compatibility.
- ChatService tests cover passing the current cleaned user text into memory retrieval before provider generation.

## Privacy and safety check

Task-related secret scan checked configuration, memory retrieval, context, chat service, tests, this evidence file, and `CLAUDE.md` for likely key/secret/token strings. Matches were limited to existing configuration field names, redacted-test fake secrets such as `sk-test-secret` / `deepseek-test-secret`, and local variable names such as token sets. No real secret was found.

## Limitations

- Retrieval uses simple local token/type-hint scoring.
- Chinese tokenization is lightweight and conservative.
- No vector/embedding retrieval is implemented.
- No LLM reranker is implemented.
- No semantic contradiction detection is implemented.
- No session summaries are implemented.
- Stage 4 emotion state is not implemented.
