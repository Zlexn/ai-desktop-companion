# Stage 3L Semantic Conflict Detection Expansion Design

Date: 2026-07-10
Status: Approved for implementation planning

## Context

Stage 3 is the current project phase: long-term memory. Stages 1 and 2 are closed, Stage 4 emotion state is not started, and Stage 3A–3K are complete.

Stage 3E added conservative local semantic conflict detection for exact duplicates, opposite preference polarity on the same value, current residence changes, current occupation changes, and simple goal/preparation overlap. Stage 3L extends that conservative detector with a few additional high-confidence Chinese fact patterns.

## Goal

Expand semantic conflict detection for long-term memories while preserving the Stage 3 rules:

- conflicts must not silently overwrite existing memories;
- conflicts must remain auditable through the existing conflict path;
- detection must be conservative and local;
- pending/dismissed/archived candidates must not enter chat context;
- summaries and chat history remain separate from long-term memories.

## Non-goals

- No LLM contradiction detection.
- No embedding-based contradiction detection.
- No automatic conflict resolution.
- No automatic memory overwrite, merge, archive, or deletion.
- No UI changes.
- No API contract changes unless existing conflict responses naturally surface repository conflicts.
- No session summary generation or prompt injection.
- No Stage 4 emotion state.

## Recommended approach

Extend the existing pattern-based implementation in `backend/app/repositories/memories.py`:

- add a conservative history/current guard;
- add semantic signatures for a small set of current single-value user facts;
- reuse the existing `_semantic_conflict(...)` behavior for `MemoryType.USER_FACT`: same semantic kind, different normalized value means conflict;
- keep unrecognized text as `None` so it fails closed and does not produce semantic conflicts.

This keeps the implementation small and avoids new dependencies.

## New supported patterns

All patterns apply only to `MemoryType.USER_FACT`.

### 1. Name / preferred name

Detect current name facts:

- `用户的名字是张三。`
- `用户名字是张三。`
- `用户叫张三。`

Conflict behavior:

- `用户的名字是张三。` vs `用户的名字是李四。` → conflict.
- Same normalized name remains exact/semantic duplicate-like conflict through existing duplicate behavior if content matches; Stage 3L does not add overwrite behavior.

### 2. School

Detect current school facts:

- `用户就读于A大学。`
- `用户在A大学读书。`
- `用户是A大学学生。`

Conflict behavior:

- `用户就读于A大学。` vs `用户就读于B大学。` → conflict.

### 3. Company / workplace

Detect current company facts:

- `用户就职于A公司。`
- `用户在A公司工作。`
- `用户的公司是A公司。`

Conflict behavior:

- `用户就职于A公司。` vs `用户就职于B公司。` → conflict.

## Historical fact guard

If a user-fact sentence clearly describes a historical state, it must not be treated as a current single-value conflict candidate.

Initial historical markers:

- `以前`
- `之前`
- `过去`
- `曾经`
- `去年`
- `上个月`
- `小时候`

Examples:

- `用户以前住在北京。` vs `用户住在上海。` → no conflict.
- `用户曾经就读于A大学。` vs `用户就读于B大学。` → no conflict.
- `用户去年就职于A公司。` vs `用户就职于B公司。` → no conflict.

The guard should apply before residence, occupation, name, school, and company signatures.

## Explicit non-conflicting categories

Stage 3L does not add semantic conflict rules for:

- `MemoryType.IMPORTANT_EVENT`
- `MemoryType.RELATIONSHIP_EVENT`
- `MemoryType.OTHER`

These categories can contain temporally nuanced statements and should not be interpreted as current single-value facts by local pattern matching.

## Expected implementation

Likely modify:

- `backend/app/repositories/memories.py`
  - Add `_has_historical_marker(content: str) -> bool` or equivalent.
  - Extend `_semantic_signature(...)` for `MemoryType.USER_FACT` with name, school, and company signatures.
  - Keep current residence/occupation behavior but guard historical facts.

Likely modify tests:

- `backend/tests/test_repositories.py`
  - Add tests for name, school, company conflicts.
  - Add tests that historical residence/school/company facts do not conflict with current facts.
  - Add a test that important events remain non-conflicting.

Likely create:

- `docs/stage3l-semantic-conflict-expansion.md`
  - Evidence and validation record.
- `docs/superpowers/plans/2026-07-10-stage-3l-semantic-conflict-expansion.md`
  - Implementation plan.

Likely modify:

- `CLAUDE.md`
  - Update status after validation.

## Validation plan

Run focused repository tests:

```powershell
python -m pytest backend/tests/test_repositories.py -q
```

Run related memory tests:

```powershell
python -m pytest backend/tests/test_repositories.py backend/tests/test_api_memories.py backend/tests/test_memory_candidate_service.py -q
```

Run full backend tests if feasible:

```powershell
python -m pytest backend/tests -q
```

If the known unrelated chat context pruning failure remains, record it separately and do not hide it.

Frontend tests are not required unless frontend runtime source changes.

## Risks and mitigations

- Risk: false positives on historical facts.
  - Mitigation: historical marker guard returns no semantic signature for current single-value fact patterns.

- Risk: false positives on free-form names, companies, or schools.
  - Mitigation: only support explicit phrase patterns; unrecognized text returns no signature.

- Risk: scope creep into general contradiction detection.
  - Mitigation: do not add LLM/embedding contradiction logic; keep local regex/pattern signatures only.

- Risk: automatic conflict resolution accidentally appears.
  - Mitigation: only return conflicts through existing repository/API paths; never overwrite or merge.

- Risk: event memories are misclassified.
  - Mitigation: do not add semantic rules for event or relationship memory types.

## Implementation decisions

- Stage 3L remains conservative and pattern-based.
- Historical markers are a guard for current fact patterns, not a full temporal reasoning engine.
- New signatures are limited to `name`, `school`, and `company` under `MemoryType.USER_FACT`.
- Existing exact duplicate and preference/goal behavior must remain unchanged.
- Stage 3L completion means expanded conflict detection is verified, not that general contradiction detection is solved.
