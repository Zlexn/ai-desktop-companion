# Stage 3I LLM Memory Candidate Extraction Evidence

Date: 2026-07-09

## Scope

Stage 3I adds an opt-in LLM memory-candidate extraction path for the current user message only.

Implemented guarantees:

- Default candidate extraction remains `heuristic`.
- `MEMORY_CANDIDATE_PROVIDER=llm` enables the LLM extraction path.
- LLM extraction uses the existing `LLMProvider` abstraction; no vendor SDK is called directly from memory business logic.
- LLM output can only create `pending` memory candidates through `MemoryRepository.create_candidate(...)`.
- Candidates still require the existing user confirmation API before becoming active long-term memories.
- Candidate extraction runs after a successful assistant response and is best-effort.
- Provider errors and invalid JSON return no candidates and do not break chat.
- Pending candidates remain excluded from chat context.
- Extraction prompt instructs the provider to use only the current user message and not infer from old chat history.

Out of scope and not implemented:

- Conversation backfill.
- Session summaries.
- Automatic active memory writes.
- Automatic conflict resolution.
- Runtime frontend provider toggle.
- Stage 4 emotion state or relationship scoring.

## Configuration

Existing configuration keys are used:

- `MEMORY_CANDIDATES_ENABLED` — defaults to `true`.
- `MEMORY_CANDIDATE_PROVIDER` — defaults to `heuristic`; accepts `heuristic` or `llm`.
- `MEMORY_CANDIDATE_LLM_MAX_TOKENS` — defaults to `512`.
- `MEMORY_CANDIDATE_LLM_TIMEOUT_SECONDS` — defaults to `15.0`.
- `MEMORY_CANDIDATE_LLM_CONFIDENCE_THRESHOLD` — defaults to `0.75`.
- `MEMORY_CANDIDATE_LLM_MAX_CANDIDATES` — defaults to `3`.

## Validation

Focused validation:

```powershell
python -m pytest backend/tests/test_memory_candidate_service.py backend/tests/test_chat_service.py backend/tests/test_chat_memory_candidates.py backend/tests/test_context_builder.py -q
```

Result:

```text
38 passed in 1.48s
```

Full backend validation:

```powershell
python -m pytest backend/tests -q
```

Result:

```text
319 passed in 13.45s
```

## Notes

The LLM extractor defensively filters candidates that are disabled, below confidence threshold, unsupported memory types, invalid importance values, empty, not about the user, not grounded in a `source_quote` from the current user message, or likely to contain secrets.

Real-provider smoke validation was not run in this session because it would require live API credentials and external provider availability. The implemented tests use the existing provider abstraction with deterministic stub providers.
