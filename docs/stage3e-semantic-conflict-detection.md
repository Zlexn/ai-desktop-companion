# Stage 3E Conservative Semantic Conflict Detection Evidence

Status: COMPLETED on 2026-07-07.

## Scope

This slice implements conservative local semantic conflict detection for long-term memories:

- Opposite preference polarity on the same value is detected as conflict.
- Current residence and occupation single-value facts conflict when the value changes.
- Simple goal/preparation overlap is detected as conflict-like duplicate/overlap.
- Existing exact duplicate conflict behavior remains.
- Existing Stage 3D audit recording captures these semantic conflicts through unchanged API routes.

It does not implement LLM contradiction detection, vector retrieval, embeddings, automatic conflict resolution, session summaries, LLM-based memory extraction, or Stage 4 emotion state.

## Implemented behavior

- `MemoryRepository.find_conflicts(...)` now checks exact normalized duplicates and conservative semantic signatures.
- Unrecognized memory text fails closed and does not produce semantic conflicts.
- API mutation responses return semantic conflicts through the existing `conflicts` field.
- Stage 3D audit events are recorded for semantic conflicts without route contract changes.

## Validation

| Command | Result |
|---|---|
| `python -m pytest backend/tests/test_repositories.py backend/tests/test_api_memories.py -q` | PASS — 41 passed in 1.44s |
| `python -m pytest backend/tests` | PASS — 287 passed in 12.13s |
| `npm --prefix frontend test -- --run` | PASS — 17 files / 152 tests passed in 10.63s |
| `npm --prefix frontend run typecheck` | PASS |
| `npm --prefix frontend run build` | PASS — Vite transformed 36 modules, built in 207ms |
| `npm --prefix frontend run test:e2e` | PASS — 7 passed in 10.1s |

## TDD notes

- Repository tests first failed for semantic conflict-positive cases because only exact duplicate detection existed.
- API semantic conflict tests pass through existing route/audit behavior after repository conflict detection was extended.

## Privacy and safety check

Task-related secret scan checked changed backend tests, repository code, docs, and `CLAUDE.md` files for likely key/secret/token strings. Matches were limited to non-secret code terminology such as `token` and the existing `token/type-hint scoring` phrase in `CLAUDE.md`; no real secret was found.

## Limitations

- Semantic detection is intentionally conservative and pattern-based.
- It is not general-purpose contradiction detection.
- Residence and occupation are treated as current single-value facts.
- Goal overlap is flagged for review but not automatically merged.
- No vector/embedding retrieval is implemented.
- No LLM-based memory extraction is implemented.
- Stage 4 emotion state is not implemented.
