# Stage 3I LLM Memory Candidate Extraction Design

Date: 2026-07-09
Status: Approved design; awaiting user review of updated spec before implementation planning

## Context

Stage 3 long-term memory is currently implementing independent, user-controlled long-term memory. The completed slices are:

- 3A manual long-term memory CRUD and memory context injection.
- 3B heuristic pending memory candidate confirmation.
- 3C relevance retrieval.
- 3D conflict audit events.
- 3E conservative semantic conflict detection.
- 3F optional embedding retrieval.
- 3G embedding evaluation script and fake-provider baseline.
- 3H isolated real embedding model evaluation.

The current implementation already has:

- `LLMProvider` as the provider-neutral chat model interface in `backend/app/providers/base.py`.
- Concrete providers selected by `LLM_PROVIDER` in `backend/app/providers/factory.py`: `fake`, `anthropic`, and `deepseek`.
- Existing candidate extraction in `backend/app/services/memory_candidate_service.py`, currently limited to `MEMORY_CANDIDATE_PROVIDER=heuristic`.
- Existing chat integration in `backend/app/services/chat_service.py`, where candidate extraction happens after a successful assistant reply and is already isolated from the chat success path.
- Existing pending candidate storage through `MemoryRepository.create_candidate(...)`, which preserves `status=pending`, duplicate/conflict checks, and the user-confirmation boundary.

The next minimal loop is **3I User-Confirmed LLM Memory Candidate Extraction**: add an opt-in LLM-based candidate extractor beside the existing heuristic path. It must improve candidate discovery without weakening the rule that long-term memories become active only after user confirmation.

This design stays within Stage 3. It does not implement Stage 4 emotion state, relationship scoring, mood/trust/concern/distance/irritation/formality, or emotional expression strategy.

## Goals

- Add an opt-in LLM-based memory candidate extraction path.
- Keep the existing heuristic provider as the default and regression-safe path.
- Reuse the existing `LLMProvider` abstraction and current configured provider, rather than introducing vendor calls into routes, repositories, or UI code.
- Convert only the current user message into structured pending memory candidates.
- Keep pending candidates out of chat context until the user confirms them.
- Reuse existing `MemoryRepository.create_candidate(...)`, duplicate checks, conflict detection, and confirmation flow.
- Ensure LLM extraction failure never breaks the chat path.
- Record implementation evidence and limitations after validation.

## Non-goals

- No automatic active long-term memory writes.
- No backfill from old chat history.
- No session summaries.
- No conversation-history summarization disguised as memory.
- No automatic conflict resolution or memory merge workflow.
- No new vector database or production embedding model selection.
- No Stage 4 emotion system or emotional state persistence.
- No provider-specific SDK calls scattered into routes, UI components, or repositories.
- No redesign of the MemoryPanel UI.
- No frontend runtime provider switching; switching remains backend configuration via environment variables for this slice.

## Approved approach

Use **Approach A: backend opt-in with frontend read-only status visibility**.

The backend remains the source of truth for the extraction provider. The user opts in by setting `MEMORY_CANDIDATE_PROVIDER=llm`; the default remains `heuristic`. The frontend will not mutate this setting at runtime in 3I. Instead, it will display the current backend-reported mode and a safety note that LLM candidates still require confirmation before becoming long-term memory.

Supported provider modes after this slice:

```text
MEMORY_CANDIDATE_PROVIDER=heuristic  # default, existing behavior
MEMORY_CANDIDATE_PROVIDER=llm        # opt-in Stage 3I behavior
```

The LLM mode will call a narrow extraction component from `MemoryCandidateService`. The extractor returns `MemoryCandidateDraft` objects; `MemoryCandidateService` remains the only service that creates pending memory records.

Do not implement a `hybrid` mode in this slice. A future task can combine heuristic and LLM outputs after the LLM-only path is validated. Starting with one opt-in LLM mode keeps the configuration, tests, and failure modes small.

## Data flow

1. User sends a chat message.
2. `ChatService.send_message(...)` stores the user message, builds context, calls the chat LLM provider, stores the assistant reply, and then triggers memory candidate extraction.
3. If `MEMORY_CANDIDATES_ENABLED=false`, no extraction runs.
4. If `MEMORY_CANDIDATE_PROVIDER=heuristic`, the current heuristic extraction runs unchanged.
5. If `MEMORY_CANDIDATE_PROVIDER=llm`, the extractor receives only:
   - the current user message;
   - the current `session_id` for source metadata;
   - a bounded instruction/schema prompt.
6. The extractor asks the configured `LLMProvider` for JSON text using a small max-token budget and timeout.
7. Application-side policy parses and validates the JSON response.
8. Passing drafts are written as `status=pending`, `source=candidate` memories.
9. A small read-only frontend status endpoint reports the active candidate provider and whether candidates are enabled.
10. Existing UI shows pending candidates and labels the extraction mode.
11. Only explicit user confirmation changes a candidate to `active`.

## LLM extraction response contract

Use a stable schema version recorded in metadata as `memory_extraction_schema_v1`.

Top-level response shape:

```json
{
  "candidates": [
    {
      "content": "用户喜欢红茶。",
      "memory_type": "preference",
      "confidence": 0.9,
      "importance": 3,
      "source_quote": "我喜欢红茶。",
      "reason": "explicit_preference_statement",
      "should_create_candidate": true
    }
  ]
}
```

Candidate fields:

- `content`: concise Chinese third-person memory candidate, e.g. `用户喜欢红茶。`
- `memory_type`: one of existing `MemoryType` values:
  - `user_fact`
  - `preference`
  - `long_term_goal`
  - `important_event`
  - `relationship_event`
  - `other`
- `confidence`: numeric confidence from the extractor.
- `importance`: suggested importance, expected range `1..5`.
- `source_quote`: short quote or excerpt from the current user message.
- `reason`: short machine-readable reason string.
- `should_create_candidate`: boolean; false means the model considered the text but does not recommend a candidate.

Because the current provider abstraction returns plain text and DeepSeek may not share Anthropic native structured-output semantics, this slice uses strict prompt + JSON parsing rather than changing every provider implementation to support native structured outputs.

## Application-side validation

The service must treat LLM output as untrusted.

Validation rules:

- JSON parse failure returns no candidates.
- Missing or non-list `candidates` returns no candidates.
- `should_create_candidate=false` entries are ignored.
- At most 3 candidates are accepted from one user message.
- `memory_type` must map to an existing `MemoryType` value.
- `content` must be non-empty after trimming.
- `content` must be bounded to a conservative length, initially 200 characters.
- `content` should describe the user, preferably beginning with `用户`; entries that describe the assistant or system are rejected.
- `confidence` must be numeric and meet the configured threshold, initially `>= 0.75`.
- `importance` must be numeric and within `1..5`; otherwise the entry is rejected. This avoids silently promoting malformed model output into a stored candidate.
- `source_quote` must be non-empty and should be a substring of the current user message after trimming; invented quotes are rejected.
- Secrets and credentials must not be accepted as candidate content.

Passing drafts are still subject to `MemoryRepository.create_candidate(...)`, which handles duplicate/conflict behavior across active and pending memories.

## Prompt policy

The LLM extractor prompt should be conservative:

- Extract only durable information useful in future conversations.
- Prefer explicit user statements over inference.
- Do not create candidates for temporary moods, one-off small talk, or information about the assistant.
- Do not create candidates for Stage 4 emotion fields or relationship scores.
- Do not treat recent chat history as long-term memory.
- Do not store secrets, credentials, API keys, tokens, passwords, or private voice/audio details.
- Mark uncertain items with `should_create_candidate=false` instead of forcing a memory.
- Return an empty candidate list when nothing durable is present.

The prompt must not claim that candidates are already remembered. They are only suggestions awaiting user confirmation.

## Provider boundary

The implementation should add a narrow `MemoryCandidateLLMExtractor` that depends on the existing `LLMProvider` and `Settings`.

Expected behavior:

- Use `LLMProvider.generate(...)` rather than calling DeepSeek, Anthropic, or any other vendor directly.
- Use a memory-specific prompt and `LLMOptions` with bounded `max_tokens` and timeout.
- Default to the existing `LLM_MODEL` unless an optional memory-candidate model override is added.
- Keep fake tests network-free by injecting a fake provider or fake extractor.

This avoids changing all provider implementations immediately. If later providers support native structured output, `MemoryCandidateLLMExtractor` can use that internally without changing `MemoryCandidateService` or `ChatService`.

## Configuration

Minimal required config change:

```text
MEMORY_CANDIDATE_PROVIDER=heuristic|llm
```

Optional small config keys if implementation needs them:

```text
MEMORY_CANDIDATE_LLM_MAX_TOKENS=512
MEMORY_CANDIDATE_LLM_TIMEOUT_SECONDS=15
MEMORY_CANDIDATE_LLM_CONFIDENCE_THRESHOLD=0.75
MEMORY_CANDIDATE_LLM_MAX_CANDIDATES=3
```

Defer `MEMORY_CANDIDATE_LLM_PROVIDER` and provider-specific API keys. The approved implementation reuses the current `LLMProvider` rather than creating a separate provider stack.

## Error handling

LLM candidate extraction must be best-effort:

- Provider timeout, rate limit, refusal, invalid response, JSON parse error, schema validation failure, or max-token truncation returns no candidates.
- Chat reply remains successful.
- Do not log raw user text or raw candidate JSON in application logs.
- Do not expose extraction failures to the frontend as chat failures.
- Do not store full raw model responses in memory metadata.

Metadata on created candidates may include safe fields:

- `candidate_reason`
- `extraction_provider = "llm"`
- `extraction_schema = "memory_extraction_schema_v1"`
- `source_quote`
- `raw_confidence` if numeric

## Conflict and duplicate behavior

Reuse existing repository behavior for duplicate and conflict detection. LLM-generated candidates must not silently overwrite existing active memories. If a candidate conflicts with active or pending memory, it should be skipped according to existing `create_candidate(...)` behavior.

This slice does not add automatic conflict resolution.

## UI impact

Add a small read-only status display to the existing MemoryPanel flow. The UI will not switch provider modes at runtime.

Backend status endpoint:

```text
GET /api/memory-candidate-settings
```

Response shape:

```json
{
  "enabled": true,
  "provider": "heuristic",
  "llm_opt_in": false,
  "pending_candidates_require_confirmation": true
}
```

Frontend behavior:

- Display `候选抽取：启发式` when provider is `heuristic`.
- Display `候选抽取：LLM（需确认）` when provider is `llm`.
- Always show that suggested candidates are not used in conversation until confirmed.
- If the status endpoint fails, keep the memory panel usable and show a non-blocking fallback such as `候选抽取状态暂不可用`.
- Existing pending candidate rendering remains the main review/confirmation surface.

Optional small candidate display improvement is acceptable:

- Show `source_quote` or reason in existing candidate details when available.
- Label provider as `LLM candidate` based on metadata.

Do not redesign MemoryPanel in this slice and do not add a frontend runtime toggle.

## Testing strategy

Backend first:

- Config tests:
  - accepts `MEMORY_CANDIDATE_PROVIDER=llm`;
  - rejects unknown provider values;
  - default remains `heuristic`.

- Extractor tests:
  - parses a valid structured response into drafts;
  - filters `should_create_candidate=false`;
  - filters confidence below threshold;
  - rejects invalid memory type;
  - rejects malformed importance outside `1..5`;
  - rejects empty content/source quote;
  - rejects invented source quotes;
  - returns empty list on provider error or invalid JSON.

- Candidate service tests:
  - LLM provider creates pending candidates with `source=candidate` and `status=pending`;
  - metadata records `extraction_provider=llm` and schema version;
  - duplicates are not created;
  - extraction failure returns no candidates.

- Chat integration tests:
  - successful chat still returns assistant reply when LLM extraction fails;
  - pending LLM candidates are not injected into context;
  - confirmed candidates still enter context through existing retrieval paths.

- Frontend status tests:
  - renders heuristic mode from the read-only status endpoint;
  - renders LLM opt-in mode and confirmation note;
  - keeps the memory panel usable if status loading fails.

E2E can be a minimal fake-provider smoke if implementation touches the visible candidate flow.

## Validation plan

Expected implementation validation commands:

```powershell
python -m pytest backend/tests/test_config.py backend/tests/test_memory_candidate_service.py backend/tests/test_chat_memory_candidates.py -q
python -m pytest backend/tests -q
```

If frontend files change:

```powershell
npm --prefix frontend test -- --run
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

If frontend files do not change, record that frontend tests were skipped because no frontend runtime code changed.

A real DeepSeek smoke can be performed only if the local environment has a valid `DEEPSEEK_API_KEY` and the user explicitly wants a real-provider check. It should use a non-sensitive fixed prompt and must not print or log the key.

## Documentation requirements

Create `docs/stage3i-llm-memory-candidate-extraction.md` after implementation. It must record:

- exact scope;
- configuration keys;
- test commands and results;
- whether a real LLM smoke was performed or skipped;
- privacy and safety limitations;
- confirmation that candidates still require user confirmation;
- confirmation that Stage 4 remains unstarted.

Update `CLAUDE.md` only after validation evidence exists. Do not mark 3I complete before tests/evidence pass.

## Risks and mitigations

- Risk: LLM over-extracts casual statements.
  - Mitigation: conservative prompt, confidence threshold, `should_create_candidate`, user confirmation.

- Risk: LLM invents source facts.
  - Mitigation: require `source_quote`; validate against current user message.

- Risk: extraction adds latency after every chat turn.
  - Mitigation: opt-in provider, bounded max candidates, small max-token budget, failure isolation.

- Risk: provider-specific structured output differences.
  - Mitigation: start with provider-neutral JSON parsing behind a narrow extractor; add native structured output later.

- Risk: privacy leakage through logs or metadata.
  - Mitigation: no raw response logging; no API keys; no full raw user text in candidate metadata.

- Risk: scope creep into emotional memory or relationship state.
  - Mitigation: explicitly reject Stage 4 emotion fields and temporary mood statements.

## Future work after 3I

- Add optional Anthropic-native structured output path using `output_config.format` after provider interface design is stable.
- Add a real-provider smoke using a non-sensitive fixed prompt if the user wants evidence with a real model.
- Design independent session summary storage as a separate Stage 3 slice.
- Revisit deeper real embedding production-model selection as a separate Stage 3 task.
