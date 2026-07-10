# Stage 2 Acceptance Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify and record whether Stage 2 voice functionality meets its acceptance boundary before starting Stage 3 long-term memory.

**Architecture:** This is an audit/documentation slice, not a product feature. It reads the existing Stage 2 evidence, runs the established backend/frontend/E2E validation surfaces, records limitations for manual/real-provider checks, and only updates stage status if the evidence supports it.

**Tech Stack:** FastAPI/Python/pytest backend, React/TypeScript/Vite/Vitest/Playwright frontend, Markdown project documentation.

---

## File Structure

- Modify: `docs/stage2-voice-acceptance-audit.md` — Stage 2 final acceptance audit report with scope, validation commands, pass/fail status, manual limitations, and Stage 3 entry recommendation.
- Modify only if audit passes: `CLAUDE.md` — project stage state and current-status evidence.
- Modify only if audit passes: `README.md` — stage/status note if the README already tracks current milestone status.

## Task 1: Evidence and Test Surface Inventory

**Files:**
- Read: `CLAUDE.md`
- Read: `frontend/package.json`
- Read: `backend/pyproject.toml`
- Read: `docs/stage2h-low-gap-streaming-audio.md`
- Create/Modify: `docs/stage2-voice-acceptance-audit.md`

- [ ] **Step 1: Confirm stage boundary**

Record this boundary in working notes before editing docs:

```text
Current stage: Stage 2 voice functionality.
Allowed work: acceptance audit, verification, and documentation.
Disallowed work: Stage 3 long-term memory implementation, Stage 4 emotion implementation, schema changes for memory/emotion.
Next eligible task after pass: Stage 3 memory foundation design.
```

- [ ] **Step 2: Inventory verification commands**

Use these commands as the audit command set:

```powershell
python -m pytest backend/tests
npm --prefix frontend test -- --run
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

Expected: all commands exit 0. If a command fails because of environment prerequisites rather than product failure, record the exact output and keep Stage 2 open.

## Task 2: Run Automated Acceptance Validation

**Files:**
- No product files modified.
- Create/Modify: `docs/stage2-voice-acceptance-audit.md`

- [ ] **Step 1: Run backend test suite**

Run:

```powershell
python -m pytest backend/tests
```

Expected: PASS with all backend tests passing.

- [ ] **Step 2: Run frontend unit/integration tests**

Run:

```powershell
npm --prefix frontend test -- --run
```

Expected: PASS with all Vitest tests passing.

- [ ] **Step 3: Run TypeScript typecheck**

Run:

```powershell
npm --prefix frontend run typecheck
```

Expected: PASS with `tsc -b` exit 0.

- [ ] **Step 4: Run production build**

Run:

```powershell
npm --prefix frontend run build
```

Expected: PASS with Vite build completed.

- [ ] **Step 5: Run Playwright E2E**

Run:

```powershell
npm --prefix frontend run test:e2e
```

Expected: PASS with all configured E2E tests passing.

## Task 3: Write Stage 2 Acceptance Audit Report

**Files:**
- Create/Modify: `docs/stage2-voice-acceptance-audit.md`

- [ ] **Step 1: Write report skeleton**

Create the report with this exact structure:

```markdown
# Stage 2 Voice Acceptance Audit

Status: AUDITED on 2026-07-06.

## Scope

This audit verifies Stage 2 voice functionality before Stage 3 long-term memory begins.

## Acceptance Boundary

- Voice failure does not break text chat.
- ASR can be disabled or replaced.
- TTS can be disabled or replaced.
- Microphone recording, permissions, playback, stop/replay, error recovery, VAD or explicit recording boundary, interruption, device selection, streaming measurement, streaming TTS/ASR slices, and low-gap playback have recorded evidence.
- End-to-end latency can be measured.

## Automated Validation

| Command | Result |
|---|---|

## Manual / Real Provider Evidence

## Limitations

## Stage Decision

## Next Minimal Stage 3 Task
```

- [ ] **Step 2: Fill validation table**

For every command run in Task 2, paste the command and observed PASS/FAIL result. Include counts when available.

- [ ] **Step 3: Record manual/real-provider limitations**

Record that this audit does not re-run microphone, speaker, GPU FasterWhisper, or local CosyVoice service smoke unless those commands were actually executed in this audit. Reference existing evidence docs instead of claiming fresh manual verification.

- [ ] **Step 4: Decide stage state**

If all automated commands pass and existing real-provider evidence covers Stage 2 acceptance, set report stage decision to:

```text
Stage 2 acceptance audit: PASS. Stage 3 may begin with a memory foundation design task. No Stage 3 implementation was performed in this audit.
```

If any required command fails or evidence is insufficient, set report stage decision to:

```text
Stage 2 acceptance audit: BLOCKED. Stage 2 remains IMPLEMENTING until the listed failures are resolved and re-verified.
```

## Task 4: Sync Project Status If Audit Passes

**Files:**
- Modify if pass: `CLAUDE.md`
- Modify if pass and relevant: `README.md`

- [ ] **Step 1: Update CLAUDE.md only on PASS**

If the audit passes, update the current-stage line and status table to show Stage 2 acceptance audit completed and Stage 3 as the next stage. Do not mark Stage 3 implemented.

- [ ] **Step 2: Keep CLAUDE.md unchanged on BLOCKED**

If the audit is blocked, do not mark Stage 2 complete. Record blockers only in `docs/stage2-voice-acceptance-audit.md`.

- [ ] **Step 3: Update README only if it has a current-status section**

If `README.md` contains a current-stage summary, align it with the audit result. If it does not, skip README changes.

## Task 5: Final Self-Check

**Files:**
- Read: `docs/stage2-voice-acceptance-audit.md`
- Read if changed: `CLAUDE.md`
- Read if changed: `README.md`

- [ ] **Step 1: Confirm no Stage 3 code was added**

Run:

```powershell
git diff --name-only
```

Expected: No new memory implementation files, no emotion implementation files, no database schema changes for memory/emotion in this audit.

- [ ] **Step 2: Report final result**

Use the project-required format:

```text
完成内容：
修改文件：
验证命令与结果：
未完成或受限部分：
是否改变当前阶段：否/是（附验收证据）
下一项建议任务：
```

## Self-Review

- Spec coverage: The plan covers CLAUDE.md's requirement to audit Stage 2 before Stage 3, records validation commands, and avoids Stage 3/4 implementation.
- Placeholder scan: No TBD/TODO/fill-later placeholders are present.
- Type consistency: This audit plan does not define runtime types or APIs; file paths and command names are consistent across tasks.
