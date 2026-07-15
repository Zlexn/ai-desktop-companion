# Stage 4C Acceptance Closure Design

> Date: 2026-07-14
> Status: APPROVED

## 1. Goal

Close Stage 4C with reproducible evidence that explicit consent controls every LLM-assisted emotion-analysis transmission, that the production DeepSeek HTTP adapter works through the complete browser/application path, that revocation prevents later transmission without disabling Stage 4A local rules, and that analysis persistence remains metadata-only.

This closure supports the longer-term product goal: a locally deployable Yukinoshita Yukino companion with real-time conversation, bounded emotion expression, and user-controlled long-term memory. It does not implement Stage 4D expression planning, emotion-aware TTS parameters, Live2D, a desktop shell, or character assets.

## 2. Approved Verification Strategy

Use two complementary layers.

### 2.1 Reproducible automated acceptance

Run a loopback-only fake DeepSeek HTTP server during Playwright. The standard FastAPI application remains configured with `EMOTION_ANALYSIS_PROVIDER=deepseek`; only `DEEPSEEK_BASE_URL` points to the local server. This exercises the existing `DeepSeekProvider`, background scheduler, strict parser, local policy, SQLite repositories, API, and React UI without internet access, a real key, API fees, or nondeterministic model output.

The fake server:

- listens only on `127.0.0.1`;
- implements the OpenAI-compatible `POST /chat/completions` boundary used by DeepSeek;
- accepts only a fixed inert test bearer token;
- records request count and the most recent sanitized request in memory;
- extracts the current turn message IDs from the JSON user payload;
- returns deterministic outer DeepSeek JSON whose assistant content is a valid `emotion_analysis_v1` object;
- exposes loopback-only test state/reset endpoints for Playwright assertions;
- stores no data after the process exits.

No test endpoint is added to the production FastAPI application, and no test-only provider name is added to the production provider factory.

### 2.2 Optional real DeepSeek smoke

Run one explicit, opt-in smoke against the real DeepSeek API after automated acceptance passes. The smoke:

- reads `DEEPSEEK_API_KEY` only from the current process environment;
- uses a temporary SQLite database and synthetic, non-sensitive Chinese fixtures;
- exercises explicit consent, the real HTTP request, strict `emotion_analysis_v1` parsing, local constraints, event persistence, and metadata-only audit persistence;
- does not print or persist the key, raw provider response, full prompt, or full request;
- reports `SKIPPED` when no explicit key is present rather than treating absence as success;
- may incur a small real API charge and therefore is not part of the default test suite.

## 3. Automated Browser Flow

Use one isolated E2E database and the following deterministic flow.

### 3.1 Before consent

1. Load the application and observe analysis consent `unknown` and deployment enabled.
2. Send a neutral chat turn before granting consent.
3. Assert the fake DeepSeek request count remains zero.
4. Assert analysis jobs and audits remain empty.

### 3.2 After consent

1. Complete the existing two-step grant UI.
2. Send a synthetic fixture containing an inert credential marker, for example `token=e2e-analysis-secret`.
3. Poll the audit API because analysis is intentionally non-blocking.
4. Assert exactly one fake DeepSeek request occurred.
5. Assert the received HTTP body does not contain the inert marker.
6. Assert the analysis payload respects configured recent-message, active-memory, per-item, and total budgets.
7. Assert one `applied` audit and one `llm_assisted` emotion event exist.
8. Assert all emotion dimensions remain in `[0, 1]` and the observable change follows the expected direction after local per-turn limits.
9. Refresh the panel and assert the applied result is visible.

The test must not expect the raw remote proposal delta because the Stage 4A local event may consume part of the shared per-turn budget before the remote proposal is constrained.

### 3.3 After revocation

1. Revoke analysis consent.
2. Send a second synthetic fixture that triggers an existing Stage 4A local distress rule and contains a second inert marker.
3. Assert consent is `revoked`.
4. Assert the fake DeepSeek request count remains one.
5. Assert analysis job and audit counts do not increase.
6. Assert local `concern` still increases, proving local emotion rules are independent of remote consent.
7. Assert there are no page errors, console errors, or HTTP 5xx responses.

## 4. Persistence Privacy Verification

After Playwright has stopped the backend and before deleting its database, run a focused Python verifier over only:

- `emotion_analysis_jobs`;
- `emotion_analysis_audits`.

The verifier checks:

- exactly one job and one audit were produced by the consented turn;
- the audit outcome is `applied`;
- neither table contains either inert secret marker, original message fragments, the fake bearer token, a raw prompt, or a raw provider response.

Do not scan `messages` or other product tables that intentionally persist user-authored content. Clean the main database and any `-wal` or `-shm` sidecars after successful verification. On verification failure, retain evidence long enough for Playwright to report the failure, then perform best-effort cleanup.

## 5. Backend Runtime Coverage

Retain the existing TestClient lifespan test because it can directly inspect an injected recording provider. Extend or add a runtime case to prove:

- no consent means zero provider calls;
- grant produces exactly one call and a constrained event;
- revoke followed by another local-rule turn does not increase the provider call count;
- the local emotion state still changes after revocation;
- analysis jobs and audits contain no raw fixture, prompt, response, or key.

The browser E2E verifies independent-process production composition. The TestClient runtime verifies exact in-memory call count and race-sensitive behavior. Neither replaces the other.

## 6. Error Handling and Isolation

- The fake server returns deterministic valid JSON for the main acceptance path; strict-parser rejection remains covered by focused backend tests.
- Playwright must poll asynchronous audit completion instead of assuming analysis finishes with the chat response.
- Server process failures, provider failures, or analysis failures must not alter a successful `ChatResponse` or roll back the Stage 4A local event.
- The fake service, backend, frontend, and temporary files are isolated to the acceptance run and cleaned up afterward.
- Real DeepSeek smoke failure is reported separately from deterministic automated acceptance; it must not be silently converted to PASS.

## 7. Security and Correctness Review

Before declaring Stage 4C complete, review task-owned code for:

- consent generation checks before and after provider transmission;
- revoke/regrant races and queued-job behavior;
- idempotent reservation and the one-assistant-message/schema call invariant;
- scheduler shutdown and cancellation;
- transaction consistency between job status, emotion CAS event, and metadata audit;
- sanitization before transmission;
- absence of raw provider output or sensitive payloads in persistence and logs.

Fix only confirmed Stage 4C defects and rerun focused plus full verification after each fix.

## 8. Completion Evidence

Run and record fresh results for:

- backend focused and full pytest;
- frontend Vitest;
- TypeScript typecheck;
- Vite production build;
- Playwright E2E with the loopback fake DeepSeek server and database verifier;
- isolated backend runtime;
- optional real DeepSeek smoke when an explicit environment key is available;
- `git diff --check`.

Create `docs/stage4c-llm-emotion-analysis-consent.md` with commands, counts, observed behavior, privacy checks, review findings, limitations, and a truthful `PASS` or `BLOCKED` verdict. Only on PASS update `README.md` and `CLAUDE.md` to state that Stage 4A–4C are complete and that the next task is Stage 4D ExpressionPlan/TTS expression design.

## 9. Non-Goals

This closure does not add:

- ExpressionPlan or emotion-to-TTS parameter mapping;
- Live2D, desktop-shell, or character-asset behavior;
- background microphone listening;
- automatic consent;
- storage of raw analysis prompts or responses;
- claims of real emotion or consciousness;
- unlicensed character images, voice models, or other protected assets.
