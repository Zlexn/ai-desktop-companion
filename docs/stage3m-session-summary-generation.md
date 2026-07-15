# Stage 3M Automatic Session Summary Generation

## Implemented behavior

- Successful chat turns schedule summary work only after the assistant message is persisted.
- Summary work is nonblocking and runs through an application-owned in-process scheduler.
- Each background job opens a fresh SQLite connection and writes append-only generated summaries.
- The fake summary provider is deterministic, offline, and the default.
- Real summary LLM providers are explicit opt-in resources owned by the FastAPI lifespan and closed at shutdown.
- Summary input and output receive best-effort credential redaction.
- Coverage uses the latest coverage-bearing summary, so newer manual summaries without coverage cannot repeat old segments.
- Same-session concurrent scheduling is coalesced; one dirty rerun is retained when a new turn arrives during an active job.
- Shutdown is bounded, cancels stuck work, suppresses dirty restarts, and then closes the provider.

## Stage boundaries

- Generated summaries remain in `session_summaries`.
- They are not injected into chat context.
- They do not create or modify long-term memories, pending/dismissed candidates, or memory embeddings.
- No summary UI or public summary API was added.
- No automatic conflict resolution, emotional state, TTS emotion control, or avatar behavior was added.

## Verification

### Existing component baseline

```text
python -m pytest backend/tests/test_config.py backend/tests/test_deepseek_provider.py
backend/tests/test_provider_factory.py backend/tests/test_session_summaries.py
backend/tests/test_session_summary_sanitizer.py
backend/tests/test_session_summary_provider.py
backend/tests/test_session_summary_service.py -q

112 passed in 3.29s
```

### Final focused Stage 3M suite

```text
python -m pytest backend/tests/test_config.py backend/tests/test_deepseek_provider.py
backend/tests/test_provider_factory.py backend/tests/test_session_summaries.py
backend/tests/test_session_summary_sanitizer.py
backend/tests/test_session_summary_provider.py
backend/tests/test_session_summary_service.py backend/tests/test_chat_service.py
backend/tests/test_api_chat.py -q

148 passed, 1 failed
```

The sole failure is the pre-existing context-pruning baseline:

```text
backend/tests/test_chat_service.py::test_chat_service_prunes_old_history_before_provider_when_context_is_large
```

This same failure was recorded before Stage 3M in the Stage 3K and 3L evidence. It is outside the session-summary change and was not modified to manufacture a green result.

### Full backend suite

```text
python -m pytest backend/tests -q

398 passed, 1 failed in 18.97s
```

The only failure is the same documented context-pruning baseline. No Stage 3M test failed.

### Frontend regression

```text
npm run typecheck
npm test -- --run
npm run build
```

Results:

- TypeScript typecheck: PASS
- Vitest: 17 files, 152 tests PASS
- Vite production build: PASS
- Locked dependency install audit: 0 vulnerabilities

### Runtime API verification

The backend was launched with a uniquely named isolated SQLite database, fake chat provider, fake summary provider, threshold 2, and no user database access. HTTP requests bypassed environment proxies.

Observed result:

```json
{
  "health": "ok",
  "first_http": 200,
  "roles": ["user", "assistant"],
  "summary_rows_after_first_turn": 1,
  "summary_source": "generated",
  "summary_message_count": 2,
  "coverage_matches": true,
  "memory_count": 0,
  "embedding_count": 0,
  "summary_absent_from_second_reply": true,
  "malformed_json_status": 422
}
```

Production-composition tests additionally used a blocking summary provider and recording chat provider to observe that:

- HTTP and assistant persistence complete while summary generation remains blocked;
- the actual background connection is not any request-scoped connection;
- full second-turn Provider messages contain no summary text;
- existing active, pending, and dismissed memories and embeddings are byte-for-byte unchanged;
- application lifespan owns one scheduler across requests;
- provider test overrides remain effective in lifespan;
- provider clients close after bounded scheduler shutdown.

### Code review

Multiple adversarial review passes found and drove fixes for:

- manual no-coverage summaries obscuring generated coverage;
- insufficient production-composition assertions;
- duplicate real-LLM calls under same-session concurrency;
- request-scoped unclosed summary clients;
- lost dirty reruns;
- provider override bypass in lifespan;
- unbounded shutdown;
- dirty task restart during shutdown.

Each confirmed issue received a failing regression test before the minimal fix. The last focused scheduler lifecycle set passed 5/5.

### Stage 3 closeout rerun after context-budget implementation

The separate chat Provider context-budget maintenance task resolved the historical pruning baseline without changing summary generation or injecting summaries into chat context.

```text
python -m pytest backend/tests/test_config.py backend/tests/test_chat_service.py -q
83 passed

python -m pytest backend/tests/test_session_summaries.py backend/tests/test_session_summary_sanitizer.py backend/tests/test_session_summary_provider.py backend/tests/test_session_summary_service.py backend/tests/test_api_chat.py -q
45 passed

python -m pytest backend/tests -q
410 passed in 18.00s
```

The former `test_chat_service_prunes_old_history_before_provider_when_context_is_large` failure is now green. The budget operates only on the final outbound Provider messages; persisted history and Stage 3M summary storage/isolation behavior remain unchanged.

## Limitations

- In-process jobs are best effort and are not durable across process crashes or forced termination.
- Shutdown waits up to five seconds, then cancels unfinished summary jobs.
- Credential sanitization is best effort, not a DLP guarantee.
- Real LLM summary quality, latency, and cost were not part of default offline acceptance.
- The historical context-pruning baseline was resolved by the separate chat Provider context-budget task; summary injection remains deliberately unimplemented.
