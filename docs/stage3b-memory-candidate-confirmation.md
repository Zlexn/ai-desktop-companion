# Stage 3B Memory Candidate Confirmation Evidence

Status: COMPLETED on 2026-07-07.

## Scope

This slice implements Stage 3B long-term memory candidate confirmation:

- Heuristic candidate extraction from explicit user statements after successful chat turns.
- Pending candidate storage in the independent `memories` table.
- User confirmation before candidates become active long-term memories.
- User dismissal of inaccurate or unwanted candidates.
- Candidate UI in the existing memory panel.
- Candidate records excluded from chat context until confirmed.

It does not implement vector retrieval, semantic contradiction detection, session summaries, old chat-history backfill, LLM-based memory extraction, or Stage 4 emotion state.

## Implemented behavior

- Explicit statements such as `我喜欢红茶。` can create a pending `preference` candidate.
- Pending candidates use `source = candidate` and `status = pending`.
- Pending and dismissed candidates are not injected into chat context.
- Confirming a candidate changes it to `active` and records `confirmed_at` in metadata.
- Dismissing a candidate changes it to `dismissed` and records `dismissed_at` in metadata.
- Candidate extraction failure does not fail chat.
- Exact normalized duplicate active or pending memories are not duplicated by candidate extraction.
- Existing manual memory CRUD remains available.

## Validation

| Command | Result |
|---|---|
| `python -m pytest backend/tests` | PASS — 261 passed in 11.44s |
| `npm --prefix frontend test -- --run` | PASS — 17 files passed, 152 tests passed |
| `npm --prefix frontend run typecheck` | PASS — `tsc -b` exited 0 |
| `npm --prefix frontend run build` | PASS — Vite built 36 modules, `✓ built in 641ms` |
| `npm --prefix frontend run test:e2e` | PASS — 7 passed in 10.5s |

## TDD notes

- Repository candidate tests first failed because candidate source/status and lifecycle methods did not exist.
- SQLite migration tests first failed until `memories` CHECK constraints were rebuilt for existing Stage 3A databases.
- Candidate service tests first failed because `MemoryCandidateService` did not exist.
- Chat integration tests first failed because chat did not trigger candidate generation.
- API tests first failed because confirm/dismiss endpoints did not exist.
- Frontend client tests first failed because candidate APIs and status query support did not exist.
- MemoryPanel tests first failed because pending candidates were not rendered.
- App tests first failed because candidate props/state were not wired through `App -> ChatLayout -> MemoryPanel`.
- A voice-turn App regression exposed that candidate refresh could consume the mocked TTS stream response before playback; the refresh was moved after playback scheduling so it does not block or preempt the voice path.
- E2E candidate smoke was added after the focused unit and integration tests were green.

## Limitations

- Candidate extraction is heuristic and conservative.
- No LLM-based extraction provider is implemented in this slice.
- Semantic contradiction detection is not implemented.
- Vector/embedding retrieval is not implemented.
- Session summaries are not implemented.
- Stage 4 emotion state is not implemented.
