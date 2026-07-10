# Stage 3I LLM Memory Candidate Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in LLM-based memory candidate extraction path that creates pending long-term memory candidates only after conservative validation and never breaks chat.

**Architecture:** Keep `MemoryCandidateService` as the only writer of pending memories. Add a narrow extractor boundary: the heuristic path remains default, while `MEMORY_CANDIDATE_PROVIDER=llm` uses the existing `LLMProvider` to extract structured JSON drafts from only the current user message. FastAPI dependency injection supplies the extractor without scattering vendor details into routes or repositories.

**Tech Stack:** Python 3.11+, FastAPI dependencies, existing `LLMProvider`, SQLite `MemoryRepository`, pytest.

---

## Scope Guard

This plan is Stage 3 only. Do not implement automatic active memory writes, extraction from old chat history, session summaries, Stage 4 emotion fields, automatic memory merging, or new vector storage. Every LLM-generated candidate remains `pending` until the existing user confirmation flow activates it.

## Files

- Modify `backend/app/core/config.py`: add LLM candidate settings and validation.
- Modify `backend/app/services/memory_candidate_service.py`: add extractor classes, JSON parsing, validation, and LLM mode.
- Modify `backend/app/api/dependencies.py`: inject the LLM provider into the candidate service.
- Modify `backend/tests/test_config.py`: cover new settings.
- Modify `backend/tests/test_memory_candidate_service.py`: cover extractor and service behavior.
- Modify `backend/tests/test_chat_memory_candidates.py`: cover chat failure isolation and pending-not-in-context behavior.
- Create `docs/stage3i-llm-memory-candidate-extraction.md`: record evidence after validation.

## Tasks

### Task 1: Config

**Files:**
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_config.py`

- [ ] Step 1: Add failing config tests for `MEMORY_CANDIDATE_PROVIDER=llm`, unknown provider rejection, `MEMORY_CANDIDATE_LLM_CONFIDENCE_THRESHOLD`, and `MEMORY_CANDIDATE_LLM_MAX_CANDIDATES`.
- [ ] Step 2: Run `python -m pytest backend/tests/test_config.py -q`; expect the new llm-provider test to fail because only `heuristic` is currently accepted.
- [ ] Step 3: Add fields to `Settings`: `memory_candidate_llm_confidence_threshold: float = 0.75` and `memory_candidate_llm_max_candidates: int = 3`.
- [ ] Step 4: Change provider validation to accept `heuristic` and `llm`; parse threshold with `_get_score_env`; parse max candidates with `_get_positive_int_env`; reject max candidates above 5 with a clear message.
- [ ] Step 5: Include the new safe values in `Settings.redacted()`.
- [ ] Step 6: Re-run `python -m pytest backend/tests/test_config.py -q`; expect PASS.

### Task 2: Extractor boundary and LLM validation

**Files:**
- Modify: `backend/app/services/memory_candidate_service.py`
- Test: `backend/tests/test_memory_candidate_service.py`

- [ ] Step 1: Add tests with a fake async provider for valid JSON, low confidence filtering, `should_create_candidate=false`, invalid memory type, invalid JSON, provider errors, empty `content`, and source quote not found in the current user message.
- [ ] Step 2: Run `python -m pytest backend/tests/test_memory_candidate_service.py -q`; expect failures because the LLM extractor does not exist.
- [ ] Step 3: Add `MemoryCandidateExtractor` protocol with `async extract(user_text: str) -> list[MemoryCandidateDraft]`.
- [ ] Step 4: Add `HeuristicMemoryCandidateExtractor` by moving the existing regex extraction logic into it without changing behavior.
- [ ] Step 5: Extend `MemoryCandidateDraft` with `confidence: float = 0.7`, `importance: int = 3`, `source_quote: str | None = None`, and `metadata: dict[str, object] | None = None`.
- [ ] Step 6: Add `LLMMemoryCandidateExtractor` that calls `LLMProvider.generate(...)`, parses JSON shaped as `{"candidates": [...]}`, validates application rules, and returns only safe drafts.
- [ ] Step 7: Ensure validation rejects secrets by dropping candidates whose content or source quote contains `api key`, `token`, `password`, `密码`, `密钥`, or `令牌`.
- [ ] Step 8: Re-run `python -m pytest backend/tests/test_memory_candidate_service.py -q`; expect PASS.

### Task 3: Candidate service async integration

**Files:**
- Modify: `backend/app/services/memory_candidate_service.py`
- Modify: `backend/app/services/chat_service.py`
- Test: `backend/tests/test_memory_candidate_service.py`
- Test: `backend/tests/test_chat_memory_candidates.py`

- [ ] Step 1: Update service tests to await `create_candidates_from_user_text(...)` and verify LLM-created memories have `status=pending`, `source=candidate`, metadata `extraction_provider=llm`, and schema `memory_extraction_schema_v1`.
- [ ] Step 2: Update chat tests to verify chat succeeds when LLM extraction raises, and pending candidates are not injected into context.
- [ ] Step 3: Run `python -m pytest backend/tests/test_memory_candidate_service.py backend/tests/test_chat_memory_candidates.py -q`; expect failures because the service is still synchronous.
- [ ] Step 4: Make `MemoryCandidateService.create_candidates_from_user_text(...)` async and call `await self._extractor.extract(user_text)`.
- [ ] Step 5: In `ChatService.send_message(...)`, change the candidate call to `await self._memory_candidates.create_candidates_from_user_text(...)` inside the existing try/except.
- [ ] Step 6: Keep duplicate behavior by using existing `MemoryRepository.create_candidate(...)` and skipping `None` returns.
- [ ] Step 7: Re-run the two focused test files; expect PASS.

### Task 4: Dependency injection

**Files:**
- Modify: `backend/app/api/dependencies.py`
- Test: existing backend tests

- [ ] Step 1: Update `get_memory_candidate_service(...)` to depend on `get_llm_provider`.
- [ ] Step 2: Build `HeuristicMemoryCandidateExtractor()` when `settings.memory_candidate_provider == "heuristic"`.
- [ ] Step 3: Build `LLMMemoryCandidateExtractor(provider, settings)` when `settings.memory_candidate_provider == "llm"`.
- [ ] Step 4: Return `MemoryCandidateService(memories, settings, extractor)`.
- [ ] Step 5: Run `python -m pytest backend/tests/test_memory_candidate_service.py backend/tests/test_chat_memory_candidates.py backend/tests/test_config.py -q`; expect PASS.

### Task 5: Documentation and verification

**Files:**
- Create: `docs/stage3i-llm-memory-candidate-extraction.md`
- Modify: `CLAUDE.md`

- [ ] Step 1: Run `python -m pytest backend/tests/test_config.py backend/tests/test_memory_candidate_service.py backend/tests/test_chat_memory_candidates.py -q`; expect PASS.
- [ ] Step 2: Run `python -m pytest backend/tests -q`; expect PASS.
- [ ] Step 3: If frontend files were not changed, record frontend validation as skipped because no frontend runtime code changed.
- [ ] Step 4: Create `docs/stage3i-llm-memory-candidate-extraction.md` with scope, config keys, validation results, privacy limits, and confirmation that Stage 4 remains unstarted.
- [ ] Step 5: Update `CLAUDE.md` Stage 3 current status only after validation passes.
- [ ] Step 6: Commit the implementation and docs with `git add backend/app/core/config.py backend/app/services/memory_candidate_service.py backend/app/services/chat_service.py backend/app/api/dependencies.py backend/tests/test_config.py backend/tests/test_memory_candidate_service.py backend/tests/test_chat_memory_candidates.py docs/stage3i-llm-memory-candidate-extraction.md CLAUDE.md && git commit -m "feat: add llm memory candidate extraction"`.

## Self-Review

- Spec coverage: config, opt-in LLM path, conservative validation, pending-only writes, failure isolation, duplicate reuse, docs, and no Stage 4 scope are covered.
- Placeholder scan: no TBD/TODO placeholders remain.
- Type consistency: the extractor returns `MemoryCandidateDraft`; the service is the only writer; chat awaits the async service call.
