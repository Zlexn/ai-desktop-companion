# Stage 4C LLM-Assisted Emotion Analysis and Consent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit persistent consent and a non-blocking, idempotent, budgeted, sanitized, strictly validated DeepSeek-assisted emotion proposal path that always falls back to Stage 4A local rules.

**Architecture:** Separate consent/jobs/audit persistence, input building, strict parsing, provider analysis, and background orchestration. Chat success schedules one idempotent job per assistant message; execution re-checks consent, sends only minimized untrusted data through the existing provider abstraction, validates locally, constrains with EmotionPolicy, and writes a CAS `llm_assisted` event plus metadata-only audit.

**Tech Stack:** FastAPI, SQLite, Pydantic/config env, existing LLMProvider/DeepSeek adapter, pytest, React/TypeScript/Vitest/Playwright.

---

## Task 1 — Configuration
- Add independent `EMOTION_ANALYSIS_*` settings with default disabled, provider `deepseek`, retry 0, token/timeout/message/memory budgets.
- TDD default, override, invalid provider/budget and `redacted()` tests.
- Wire provider with `create_named_provider`; no SDK calls in services.

## Task 2 — Consent, Job, Audit Persistence
- Add immutable domain models/enums.
- Add SQLite tables:
  - consent keyed by global scope;
  - jobs unique `(source_assistant_message_id, schema_version)`;
  - metadata-only analysis audit.
- Repository TDD: unknown→grant/decline/revoke/regrant; idempotent job reservation; audit contains counts/classification but no body; restart persistence.

## Task 3 — Sanitizer and Input Builder
- Generalize credential sanitizer without claiming PII/DLP.
- Build deterministic input from current turn, at most six recent messages, at most three query-relevant active memories.
- Enforce per-item and total character budgets after sanitization; current turn required; exclude non-active memory, metadata, summary, embeddings and audits.
- TDD secret patterns, stable order, budgets, active-only and redaction count.

## Task 4 — Strict Parser and Analyzer
- Define exact `emotion_analysis_v1` output with no extra fields.
- Reject fences/natural-language wrappers, wrong schema/types, bool-as-number, NaN/Infinity, unknown signal/reason, forged IDs, nonzero delta when `should_apply=false`.
- Implement `LLMEmotionAnalyzer` over existing `LLMProvider.generate`; system message marks payload untrusted and forbids diagnosis/commands/credential output; user message is serialized JSON only.
- TDD valid/invalid output, empty response, provider failure and no raw output persistence.

## Task 5 — Analysis Service and Scheduler
- Service gates config + consent, reserves idempotent job, rechecks consent immediately before provider call, builds input, invokes analyzer, constrains proposal with local `EmotionPolicy.apply_delta`, writes CAS `llm_assisted` event, and metadata audit.
- Keep existing local rule event; remote failure never rolls it back.
- Add in-process scheduler keyed by assistant ID; schedule returns immediately; shutdown drains/cancels like summary scheduler.
- TDD no consent zero calls, granted one call, duplicate one charge, revoke race zero calls, invalid output/failure fallback, local cap, audit redaction and CAS retry.

## Task 6 — Chat/Lifespan Composition
- Schedule only after assistant persistence and local rule update.
- Build provider/scheduler in app lifespan with fresh SQLite connection jobs.
- Scheduler errors cannot alter ChatResponse.
- TDD successful/failed provider, scheduler failure isolation and app shutdown.

## Task 7 — API and UI
- Add GET/PUT consent (`grant|decline|revoke`) and GET audit with strict extra-field rejection.
- Extend EmotionPanel with separate LLM analysis section: provider/data disclosure, best-effort redaction limitation, network/cost notice, two-step grant, decline, revoke, regrant, recent result categories.
- Keep local emotion enabled switch independent.
- TDD API and component/App behavior, initial/retry errors and stale request protection.

## Task 8 — E2E and Runtime
- E2E: before grant zero analysis audit/provider job; grant disclosure; successful fake analyzer produces safe audit and bounded state; revoke prevents later job; local rules continue; no console/5xx.
- Full backend/frontend/typecheck/build/E2E.
- Isolated runtime with fake recording analyzer; optional real DeepSeek smoke only with explicit existing key and no sensitive fixture.
- Verify database has no raw prompt/response/text in analysis audit/jobs; no TTS/ExpressionPlan changes; clean resources.

## Task 9 — Evidence and Review
- Create `docs/stage4c-llm-emotion-analysis-consent.md` with fresh counts and PASS/BLOCKED.
- Code review security/correctness/privacy; fix confirmed findings and rerun.
- On PASS update README/CLAUDE: 4A–4C completed, next 4D ExpressionPlan/TTS design.
- `git diff --check`; do not stage/commit.

## Safety invariants

- `enabled` is not consent.
- No `granted` consent means zero provider calls.
- Every queued job rechecks consent before transmission.
- One assistant message/schema means at most one provider call.
- Raw conversation, memory, prompt and response never enter analysis audit/jobs.
- LLM only proposes; local caps/clamp/CAS decide state.
- Remote failure never affects ChatResponse or local rule transition.
- No ExpressionPlan, TTS, Live2D, desktop shell or protected assets.
