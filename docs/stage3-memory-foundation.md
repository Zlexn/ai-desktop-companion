# Stage 3 Memory Foundation Evidence

Status: COMPLETED on 2026-07-06.

## Scope

This slice implements the first Stage 3 long-term memory foundation:

- Manual long-term memory CRUD.
- Independent SQLite storage in a dedicated `memories` table.
- Duplicate same-type memory conflict visibility without silent overwrite.
- Optional caveated chat-context injection.
- Minimal React memory panel.
- E2E smoke proving manual memory creation does not break text chat and persists across reload.

It does not implement automatic memory extraction, vector search, semantic contradiction detection, session summaries, or Stage 4 emotion state.

## Implemented behavior

- Users can create, view, and delete/archive active long-term memories.
- Each memory has source, timestamps, type, importance, confidence, status, and metadata.
- Memories are stored separately from chat messages and sessions.
- Chat messages do not automatically become long-term memories.
- Duplicate same-type normalized content is returned as a conflict and does not overwrite existing memory rows.
- Active memories can be inserted into chat context as a separate system message that explicitly says memories are user-editable context, may be outdated or incomplete, and must not be described as absolute facts or real human memory.
- Memory loading is enabled in non-test frontend mode by default. Frontend unit tests enable startup loading explicitly with `VITE_ENABLE_MEMORY_LOAD_IN_TEST=1` to keep existing test fetch ordering stable.
- Playwright E2E test mode enables memory loading so persistence across reload is covered.

## Validation

| Command | Result |
|---|---|
| `python -m pytest backend/tests/test_repositories.py -q` | PASS — 10 passed |
| `python -m pytest backend/tests/test_api_memories.py -q` | PASS — 4 passed |
| `python -m pytest backend/tests/test_context_builder.py backend/tests/test_config.py -q` | PASS — 33 passed |
| `npm --prefix frontend test -- src/api/client.test.ts` | PASS — 6 passed |
| `npm --prefix frontend test -- src/components/MemoryPanel.test.tsx` | PASS — 3 passed |
| `npm --prefix frontend test -- src/App.test.tsx -t "loads existing memories"` | PASS — 1 passed, 22 skipped |
| `npm --prefix frontend test -- src/App.test.tsx` | PASS — 23 passed |
| `npm --prefix frontend run test:e2e -- memories.spec.ts` | PASS — 1 passed |
| `python -m pytest backend/tests` | PASS — 245 passed in 10.40s |
| `npm --prefix frontend test -- --run` | PASS — 17 files passed, 147 tests passed |
| `npm --prefix frontend run typecheck` | PASS — `tsc -b` exited 0 |
| `npm --prefix frontend run build` | PASS — Vite built 36 modules, `✓ built in 272ms` |
| `npm --prefix frontend run test:e2e` | PASS — 6 passed in 9.0s |

## TDD notes

- Repository tests first failed because memory domain models and `MemoryRepository` did not exist.
- API tests first failed because `/api/memories` returned 404.
- Context/config tests first failed because `ContextBuilder` did not accept memory dependencies and `Settings` lacked memory context fields.
- Frontend client tests first failed because memory API methods did not exist.
- `MemoryPanel` tests first failed because `MemoryPanel.tsx` did not exist.
- App memory loading test first failed because startup did not load `/api/memories`.

## Limitations

- Automatic memory extraction from chat is not implemented.
- Semantic contradiction detection is not implemented.
- Vector/embedding retrieval is not implemented.
- Session summaries are not implemented.
- Stage 4 emotion state is not implemented.
- The first conflict rule only detects exact normalized duplicate content within the same memory type.
