# Fake Provider Verification Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a repeatable Stage 1 Fake Provider verification loop without real API keys or Stage 2/3/4 features.

**Architecture:** Keep frontend API calls relative and make only Vite's dev proxy configurable. Extend the existing FakeProvider and backend tests for deterministic success/error/context checks, add process-level SQLite persistence verification, and add a Playwright browser E2E through the Vite proxy. Documentation records the exact stable commands.

**Tech Stack:** FastAPI, SQLite, pytest, React, TypeScript, Vite, Vitest, Playwright with Microsoft Edge channel.

---

### Task 1: Frontend and repo verification configuration

**Files:**
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/package.json`
- Modify: `.gitignore`
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/chat.spec.ts`

- [ ] Add `BACKEND_PROXY_TARGET` defaulting to `http://127.0.0.1:8000` in Vite proxy.
- [ ] Keep frontend API client relative paths unchanged.
- [ ] Add `typecheck` script as `tsc -b` and keep `build` as `tsc -b && vite build`.
- [ ] Add `@playwright/test` dev dependency and a `test:e2e` script.
- [ ] Ignore Playwright reports and test artifacts.

### Task 2: Fake Provider error modes

**Files:**
- Modify: `backend/app/providers/fake_provider.py`
- Modify: `backend/tests/test_api_chat.py`

- [ ] Add deterministic `error` and `empty` fake provider modes.
- [ ] Test API responses for ok, generic provider error, timeout, rate limit, invalid response, and empty content.
- [ ] Assert no stack/file/key leakage appears in error responses.

### Task 3: Multi-turn context and restart persistence

**Files:**
- Modify: `backend/tests/test_chat_service.py`
- Create: `backend/tests/test_restart_persistence.py`

- [ ] Add service-level assertion that the second provider call includes system prompt, first user, first assistant, and second user messages.
- [ ] Add a cross-process persistence test that starts uvicorn twice against the same temporary SQLite file and verifies message order/content after restart.

### Task 4: Browser E2E

**Files:**
- Create: `frontend/e2e/chat.spec.ts`
- Create: `frontend/playwright.config.ts`

- [ ] Start backend and frontend via Playwright webServer using Fake Provider and isolated test DB.
- [ ] Drive real browser: create session, send two messages, refresh, verify persistence, delete session.
- [ ] Capture console errors and assert API traffic goes through `/api` on the frontend origin.

### Task 5: Documentation

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

- [ ] Document `BACKEND_PROXY_TARGET` and that it must not contain secrets.
- [ ] Replace official npm commands with `Push-Location frontend` flow if `npm --prefix` diagnostics are unreliable.
- [ ] Document backend tests, frontend tests, typecheck, build, and E2E commands.

### Task 6: Verification

- [ ] Run `npm --prefix .\frontend prefix` and `npm --prefix .\frontend pkg get name`.
- [ ] Run `.\.venv\Scripts\python.exe -m pytest backend/tests -v`.
- [ ] Run `npm test -- --run`, `npm run typecheck`, `npm run build`, and `npm run test:e2e` from `frontend`.
- [ ] Check UTF-8/meta charset and browser Chinese rendering.
- [ ] Run `git status --short` and `git diff --check`, recording failures if not a git repository.

Self-review: Scope stays inside Stage 1 Fake Provider verification. No real API key or real Anthropic call is introduced. No voice, long-term memory, or emotion system is implemented.
