# Stage 3E Conservative Semantic Conflict Detection Design

Date: 2026-07-07
Status: Design selected by recommended-default instruction; awaiting implementation planning

## Context

The project is in Stage 3: long-term memory. Stage 3A added manual long-term memory CRUD and exact duplicate conflict visibility. Stage 3B added heuristic pending memory candidates with user confirmation. Stage 3C added deterministic relevance retrieval for active memory context. Stage 3D added persistent conflict audit events and frontend conflict details.

The remaining conflict limitation is that `MemoryRepository.find_conflicts(...)` only detects exact normalized same-type duplicates. This means clear contradictions such as `用户喜欢红茶。` versus `用户不喜欢红茶。`, or single-value facts such as `用户住在上海。` versus `用户住在北京。`, can be saved without conflict visibility.

Stage 3E improves conflict detection with conservative deterministic semantic rules. It reuses the Stage 3D audit trail automatically because existing create/update/confirm API routes already audit any non-empty conflicts returned by the repository.

This design stays within Stage 3. It does not implement LLM-based contradiction detection, vector/embedding similarity, automatic conflict resolution, session summaries, LLM-based memory extraction, or Stage 4 emotion state.

## Goals

- Detect a small set of high-confidence semantic conflicts in long-term memories.
- Preserve existing exact duplicate conflict behavior.
- Reuse existing mutation responses, audit recording, and frontend conflict details.
- Keep conflict detection local, deterministic, dependency-free, and testable.
- Avoid automatic merge, overwrite, archive, or resolution behavior.

## Non-goals

- No general-purpose natural language inference.
- No LLM calls.
- No embedding provider or vector database.
- No automatic conflict resolution workflow.
- No session summary storage.
- No chat-history backfill.
- No Stage 4 mood, trust, concern, distance, irritation, formality, relationship score, affect decay, or expression strategy state.

## Recommended approach

Add a private semantic-signature helper inside `backend/app/repositories/memories.py`. The helper recognizes only memory sentences already produced by the current candidate extractor or likely manual equivalents:

- preference polarity memories,
- single-value user facts for residence and occupation,
- simple long-term goal/preparation memories.

`find_conflicts(...)` remains the only public conflict method. Callers do not need to change. Internally it should first preserve exact duplicate detection, then add conservative semantic conflict matches.

## Semantic signatures

Introduce a small frozen dataclass internal to `memories.py`:

- `kind: str`
- `value: str`
- `polarity: str | None = None`

Suggested kinds:

- `preference`
- `residence`
- `occupation`
- `goal`

### Normalization

Use deterministic local normalization:

- Strip whitespace and terminal punctuation.
- Lowercase ASCII.
- Remove common low-information Chinese particles and punctuation.
- For values, normalize full-width punctuation to simple separators where practical.
- Do not use external tokenizers.

### Preference signatures

Recognize:

- `用户喜欢{value}。` => `kind='preference'`, `polarity='like'`
- `用户不喜欢{value}。` => `kind='preference'`, `polarity='dislike'`

Conflict rule:

- Same memory type `preference`.
- Same normalized value.
- Opposite polarity.

Examples:

- Conflict: `用户喜欢红茶。` vs `用户不喜欢红茶。`
- No conflict: `用户喜欢红茶。` vs `用户喜欢咖啡。`
- No conflict: `用户喜欢红茶。` vs `用户喜欢红茶拿铁。` because value is not exactly the same in this conservative slice.

### User fact signatures

Recognize:

- `用户住在{value}。` => `kind='residence'`
- `用户的职业是{value}。` => `kind='occupation'`

Conflict rule:

- Same memory type `user_fact`.
- Same kind.
- Different normalized non-empty value.

Examples:

- Conflict: `用户住在上海。` vs `用户住在北京。`
- Conflict: `用户的职业是学生。` vs `用户的职业是工程师。`
- No conflict: `用户住在上海。` vs `用户的职业是工程师。`

### Goal signatures

Recognize:

- `用户的目标是{value}。`
- `用户正在准备{value}。`

Normalize goal values by removing a tiny fixed set of low-information action prefixes when they appear at the beginning of the value:

- `完成`
- `准备`
- `实现`
- `推进`

Conflict rule:

- Same memory type `long_term_goal`.
- Both signatures are `kind='goal'`.
- Normalized values are equal.

This is treated as conflict-like duplicate/overlap, not a contradiction. It should still be returned as `conflicts` so the user can decide whether to keep both.

Examples:

- Conflict: `用户的目标是完成桌宠项目。` vs `用户正在准备完成桌宠项目。`
- No conflict: `用户的目标是完成桌宠项目。` vs `用户正在准备考试。`

## Conflict algorithm

`find_conflicts(content, memory_type, exclude_id=None, statuses=(ACTIVE,))` should:

1. Normalize the new content with the existing `_normalize_content`.
2. Load candidate memories for the requested statuses.
3. For each existing memory of the same type and not excluded:
   - Return it if exact normalized content matches.
   - Else compute semantic signatures for new and existing memory.
   - Return it if `_semantic_conflict(new_signature, existing_signature, memory_type)` is true.
4. Preserve deterministic ordering from `list(status=...)`, which is already importance/update ordered.

This means a mutation can return multiple conflicts if several active memories are relevant.

## API and audit behavior

No route shape changes are required.

Existing routes already call `MemoryRepository.find_conflicts(...)` through create/update/confirm flows. Existing Stage 3D audit recording will record audit events when semantic conflicts are returned.

Add focused API tests to prove:

- A semantic conflict returned by `POST /api/memories` is present in `conflicts`.
- The same operation creates a `conflict_detected` audit event.
- A non-conflicting same-type memory does not create an audit event.

## Frontend behavior

No new frontend behavior is required. Stage 3D already shows conflict details returned by the API. Semantic conflicts will appear in the same conflict detail section.

Optional frontend tests are not required for this slice because the UI does not distinguish exact from semantic conflicts; backend/API tests cover the new behavior.

## Error handling and privacy

- All detection runs locally inside the repository.
- No raw chat text is persisted for conflict detection.
- No prompts, provider outputs, or API keys are logged or stored.
- Semantic conflict helpers should fail closed: unrecognized text returns no signature, not a broad conflict.
- No memory is automatically edited, archived, or replaced.

## Testing plan

### Repository tests

Add tests for:

- Opposite preference polarity on the same value returns conflict.
- Different preference values do not conflict.
- Residence single-value fact conflicts when values differ.
- Residence and occupation do not conflict with each other.
- Occupation single-value fact conflicts when values differ.
- Goal/preparation overlap returns conflict.
- Different goals do not conflict.
- Existing exact duplicate conflict tests still pass.

### API tests

Add tests for:

- Creating a semantic conflict returns `conflicts` and creates one audit event.
- Creating a same-type but non-conflicting memory returns no conflicts and creates no audit event.

### Regression tests

After implementation:

- Run focused repository and memory API tests.
- Run full backend pytest.
- Run frontend unit tests, typecheck, build, and Playwright E2E to ensure no UI or voice regression.

## Documentation updates

After verified implementation, create:

- `docs/stage3e-semantic-conflict-detection.md`

Update `CLAUDE.md` only after validation passes. The update should record Stage 3E completion, validation commands, and limitations.

## Risks and mitigations

- Risk: false positives from broad semantic matching.
  - Mitigation: only exact known sentence patterns produce signatures; unrecognized text produces no semantic conflict.

- Risk: users may intend residence history rather than current residence.
  - Mitigation: this slice treats `用户住在...` as a current single-value fact, matching existing candidate extractor behavior. Users can keep multiple records manually if desired because conflicts do not block saving.

- Risk: goal overlap may not be a true contradiction.
  - Mitigation: it is treated as conflict-like duplicate/overlap for user review, not as automatic replacement.

- Risk: scope drifts into Stage 4.
  - Mitigation: no emotional or relationship state is introduced.

## Implementation boundary

This design is ready for one implementation plan. The implementation should be test-driven and staged:

1. Add repository semantic conflict tests.
2. Add private semantic-signature helpers and extend `find_conflicts`.
3. Add API tests proving semantic conflicts flow through responses and audit events.
4. Run focused and full regressions.
5. Write evidence documentation and update `CLAUDE.md` after validation.

No product code should be written until the implementation plan is created and execution begins under TDD.
