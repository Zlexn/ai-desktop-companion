# MemoryPanel Inline Memory Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Complete Stage 3 GUI CRUD by enabling accessible inline editing of active long-term memories through the existing `onUpdate` callback.

**Architecture:** Keep `App` and API ownership unchanged. `MemoryPanel` owns one ephemeral edit draft and one submitting row; successful updates close the draft, failures keep it open while the parent error remains visible.

**Tech Stack:** React, TypeScript, existing API types, Testing Library, user-event, Vitest, Vite.

---

## Scope guard

- Design: `docs/superpowers/specs/2026-07-12-memory-panel-inline-editing-design.md`.
- Modify only `MemoryPanel.tsx`, its test, and existing local CSS if controls need spacing.
- Active memories are editable. Pending candidates remain confirm/dismiss only.
- Reuse `onUpdate`; do not add API/backend work, conflict resolution, summary UI, Stage 4, modals, routing, or visual redesign.
- Preserve mixed WIP and do not commit.

### Task 1: Enter and cancel an initialized inline draft

**Files:**
- Modify: `frontend/src/components/MemoryPanel.test.tsx`
- Modify: `frontend/src/components/MemoryPanel.tsx`

- [x] Write a failing test rendering one active memory and one candidate. Click `编辑记忆`; assert fields labeled `编辑记忆内容`, `编辑记忆类型`, `编辑重要度`, `编辑可信度` initialize to the active record. Assert no edit button appears in the candidate item.
- [x] Run `npm test -- --run src/components/MemoryPanel.test.tsx`; expect failure because no edit control exists.
- [x] Destructure `onUpdate` and add state: editing ID, content, type, importance, confidence, updating ID.
- [x] Add `startEditing(memory)` to copy record fields into state and `cancelEditing()` to clear edit state.
- [x] Render read-only active rows with `编辑记忆` and `删除记忆`; render the selected row with labeled textarea/select/number inputs and `保存修改`/`取消编辑`.
- [x] Click cancel in the test; assert read-only content returns and `onUpdate` was not called.
- [x] Run the focused test and expect PASS.

### Task 2: Save typed values and handle success/failure

**Files:**
- Modify: `frontend/src/components/MemoryPanel.test.tsx`
- Modify: `frontend/src/components/MemoryPanel.tsx`

- [x] Add a failing save test. Edit content with surrounding whitespace, select a different type, set importance and confidence, click save, and assert:

```ts
expect(onUpdate).toHaveBeenCalledWith('m1', {
  content: '更新后的记忆',
  memory_type: 'user_fact',
  importance: 5,
  confidence: 0.8,
});
```

Assert successful resolution exits editing.
- [x] Run focused test; expect failure.
- [x] Add `handleUpdate(memoryId)` that trims content, sets `updatingMemoryId`, awaits `onUpdate`, closes on success, catches rejection to keep the draft open, and clears submitting state in `finally`.
- [x] Disable save for blank trimmed content or the submitting row. Disable edit/delete actions while panel `loading` is true.
- [x] Add a failure test with rejected `onUpdate` and `error="更新失败"`; assert editor remains and the role-alert error is visible.
- [x] Add a blank-content test; assert save is disabled and update is not called.
- [x] Run the complete `MemoryPanel.test.tsx`; expect all tests PASS.

### Task 3: Local styling and regression verification

**Files:**
- Modify only if needed: `frontend/src/index.css` or the existing stylesheet containing `.memory-panel*` rules.

- [x] Inspect existing memory-panel rules. Add only local layout rules for edit fields/actions if current generic form/actions rules do not suffice; reuse existing classes first.
- [x] Run:

```powershell
npm test -- --run src/components/MemoryPanel.test.tsx
npm test -- --run
npm run typecheck
npm run build
```

Expected: all frontend checks PASS.
- [x] Run backend unchanged baseline:

```powershell
python -m pytest backend/tests -q
```

Expected: 410 tests or the current increased total PASS.
- [x] Run a real UI verification via the project run/verify path: open the memory panel, create or use an isolated memory, click edit, change fields, save, observe refreshed content; probe cancel and blank-save disabling. Use only isolated local data.
- [x] Run `/code-review` on the frontend slice. Fix only confirmed in-scope findings.
- [x] Run `git diff --check` and `git status --short`; do not commit.

## Completion evidence

Implemented and verified on 2026-07-12 without committing the mixed working tree:

- focused `MemoryPanel` tests: 9 passed;
- full frontend Vitest suite: 158 passed;
- TypeScript typecheck and Vite production build: passed;
- unchanged backend regression suite: 410 passed;
- Microsoft Edge runtime flow: create, edit/save, cancel, blank guard, and invalid-number guard observed;
- isolated SQLite verification confirmed the edited active record persisted with importance `5` and confidence `0.8`;
- scoped simplify and code review completed; update failure now preserves the draft through the real `App` callback contract.

The standard Playwright runner could not start because the configured `.venv` Python path and managed browser binary were unavailable. Runtime verification instead used the available Python interpreter, isolated fake-provider backend, Vite test frontend, and installed Microsoft Edge.

## Acceptance checklist

- [x] Active memories expose inline edit; candidates do not.
- [x] Draft initializes from the selected record.
- [x] Save sends trimmed content and typed structured values.
- [x] Success exits; rejection remains open with alert.
- [x] Cancel performs no update.
- [x] Blank save is disabled.
- [x] Existing create/delete/confirm/dismiss behavior passes.
- [x] Frontend tests/typecheck/build and backend suite pass.
- [x] Actual UI flow is observed.
- [x] No Stage 4 or summary UI code is added.
