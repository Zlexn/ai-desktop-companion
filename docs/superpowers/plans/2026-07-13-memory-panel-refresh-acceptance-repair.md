# Stage 3 Memory Panel Refresh Acceptance Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the Stage 3 browser-acceptance blocker by preserving valid controlled numeric drafts, asserting the latest persisted memory after reload, and making Playwright select an available Python interpreter deterministically.

**Architecture:** Keep the existing App/API data flow unchanged. Make `MemoryPanel` represent temporarily empty numeric inputs as `number | ''`, isolate Playwright Python command selection in a small configuration helper, and correct the browser test to validate the latest PATCH result after reload. Gate Stage 3 closure on fresh unit, type, build, focused E2E, full E2E, and runtime results.

**Tech Stack:** React 19, TypeScript, Vitest, Testing Library, Vite, Playwright, FastAPI/uvicorn, SQLite, PowerShell/Windows 11.

---

## File Structure

- Modify: `frontend/src/components/MemoryPanel.test.tsx` — define the controlled-number regression contract before implementation.
- Modify: `frontend/src/components/MemoryPanel.tsx` — represent empty number drafts safely and narrow them before API submission.
- Create: `frontend/playwrightPython.ts` — pure Python executable/command selection helper.
- Create: `frontend/playwrightPython.test.ts` — unit coverage for explicit override, local `.venv`, PATH fallback, and quoting.
- Modify: `frontend/playwright.config.ts` — consume the helper instead of hard-coding `.venv`.
- Modify: `frontend/e2e/memories.spec.ts` — assert the latest edited content after reload and reject the old content.
- Modify: `docs/stage3-memory-acceptance-audit.md` — append repair verification and update PASS/BLOCKED honestly.
- Modify: `README.md` — synchronize current stage and next task from the observed result.
- Modify: `CLAUDE.md` — synchronize authoritative stage status without entering Stage 4 implementation.

Do not modify backend product source. Do not delete the existing untracked `frontend/playwright.acceptance.tmp.config.ts` or unrelated `test-results/`; they predate this task and are not owned by it.

### Task 1: Lock the Controlled Numeric Draft Regression

**Files:**
- Modify: `frontend/src/components/MemoryPanel.test.tsx:204-227`
- Test: `frontend/src/components/MemoryPanel.test.tsx`

- [ ] **Step 1: Replace the current single invalid-number test with an explicit empty-draft and recovery test**

Use a `console.error` spy because the acceptance blocker includes a React warning, and test both numeric fields:

```tsx
it('keeps empty numeric drafts controlled without warning and saves after recovery', async () => {
  const onUpdate = vi.fn().mockResolvedValue(undefined);
  const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
  const user = userEvent.setup();
  render(
    <MemoryPanel
      memories={[memory]}
      candidates={[]}
      loading={false}
      error={null}
      conflicts={[]}
      onCreate={vi.fn()}
      onUpdate={onUpdate}
      onDelete={vi.fn()}
      onConfirmCandidate={vi.fn()}
      onDismissCandidate={vi.fn()}
    />,
  );

  await user.click(screen.getByRole('button', { name: '编辑记忆' }));
  const importanceInput = screen.getByLabelText('编辑重要度');
  const confidenceInput = screen.getByLabelText('编辑可信度');

  await user.clear(importanceInput);
  expect(importanceInput).toHaveValue(null);
  expect(screen.getByRole('button', { name: '保存修改' })).toBeDisabled();

  await user.type(importanceInput, '5');
  await user.clear(confidenceInput);
  expect(confidenceInput).toHaveValue(null);
  expect(screen.getByRole('button', { name: '保存修改' })).toBeDisabled();

  await user.type(confidenceInput, '0.8');
  await user.click(screen.getByRole('button', { name: '保存修改' }));

  expect(onUpdate).toHaveBeenCalledWith('m1', {
    content: memory.content,
    memory_type: memory.memory_type,
    importance: 5,
    confidence: 0.8,
  });
  expect(consoleError).not.toHaveBeenCalledWith(
    expect.stringContaining('Received NaN for the `value` attribute'),
  );
  consoleError.mockRestore();
});
```

Wrap the assertions in `try/finally` if needed so `consoleError.mockRestore()` runs after an assertion failure.

- [ ] **Step 2: Run the focused test and confirm it exposes the current warning**

Run from repository root:

```powershell
npm --prefix frontend test -- --run src/components/MemoryPanel.test.tsx
```

Expected before implementation: the test fails because clearing an input stores `NaN`; React calls `console.error` with `Received NaN for the value attribute`.

- [ ] **Step 3: Record that no commit is made**

The user authorized automatic execution but did not authorize a commit. Leave changes unstaged and continue.

### Task 2: Implement Safe `number | ''` Drafts

**Files:**
- Modify: `frontend/src/components/MemoryPanel.tsx:38-85,161-168`
- Test: `frontend/src/components/MemoryPanel.test.tsx`

- [ ] **Step 1: Change numeric draft state types and validation**

Replace the numeric declarations and `canSaveEdit` with:

```tsx
const [editImportance, setEditImportance] = useState<number | ''>(3);
const [editConfidence, setEditConfidence] = useState<number | ''>(1);
const [isUpdating, setIsUpdating] = useState(false);

const canSaveEdit = editContent.trim().length > 0
  && typeof editImportance === 'number'
  && Number.isInteger(editImportance)
  && editImportance >= 1
  && editImportance <= 5
  && typeof editConfidence === 'number'
  && Number.isFinite(editConfidence)
  && editConfidence >= 0
  && editConfidence <= 1;
```

- [ ] **Step 2: Add one local number-input parser**

Place this module-level helper below `MEMORY_TYPE_OPTIONS`:

```tsx
function numberDraftFromInput(input: HTMLInputElement): number | '' {
  if (input.value === '') return '';
  return Number.isFinite(input.valueAsNumber) ? input.valueAsNumber : '';
}
```

Do not add defaulting or clamping; invalid transient drafts must remain unsaveable.

- [ ] **Step 3: Narrow the values before constructing the update request**

After `if (!canSaveEdit) return;`, TypeScript does not reliably retain object-level boolean narrowing. Add explicit guards:

```tsx
if (typeof editImportance !== 'number' || typeof editConfidence !== 'number') return;
```

Keep the existing request body unchanged after those guards:

```tsx
await onUpdate(memoryId, {
  content: cleanContent,
  memory_type: editMemoryType,
  importance: editImportance,
  confidence: editConfidence,
});
```

- [ ] **Step 4: Update both number input handlers**

Use the helper while keeping the controlled `value` as `number | ''`:

```tsx
<input
  type="number"
  min={1}
  max={5}
  step={1}
  value={editImportance}
  onChange={(event) => setEditImportance(numberDraftFromInput(event.currentTarget))}
/>
```

```tsx
<input
  type="number"
  min={0}
  max={1}
  step={0.05}
  value={editConfidence}
  onChange={(event) => setEditConfidence(numberDraftFromInput(event.currentTarget))}
/>
```

- [ ] **Step 5: Run focused component tests**

```powershell
npm --prefix frontend test -- --run src/components/MemoryPanel.test.tsx
```

Expected: all `MemoryPanel.test.tsx` tests pass; no NaN warning is printed.

- [ ] **Step 6: Run focused TypeScript validation**

```powershell
npm --prefix frontend run typecheck
```

Expected: exit code 0; `UpdateMemoryRequest` receives numbers, not `''`.

### Task 3: Test Python Command Selection Before Wiring It Into Playwright

**Files:**
- Create: `frontend/playwrightPython.test.ts`
- Create: `frontend/playwrightPython.ts`

- [ ] **Step 1: Write failing pure-function tests**

Create `frontend/playwrightPython.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { resolvePythonCommand } from './playwrightPython';

describe('resolvePythonCommand', () => {
  it('prefers an explicit E2E_PYTHON command', () => {
    expect(resolvePythonCommand({
      explicitPython: 'py -3.12',
      localVenvPython: 'C:\\repo\\.venv\\Scripts\\python.exe',
      localVenvExists: true,
    })).toBe('py -3.12');
  });

  it('quotes an existing local venv executable', () => {
    expect(resolvePythonCommand({
      explicitPython: '',
      localVenvPython: 'C:\\Users\\Example User\\repo\\.venv\\Scripts\\python.exe',
      localVenvExists: true,
    })).toBe('"C:\\Users\\Example User\\repo\\.venv\\Scripts\\python.exe"');
  });

  it('falls back to PATH python when the local venv is absent', () => {
    expect(resolvePythonCommand({
      explicitPython: undefined,
      localVenvPython: 'C:\\repo\\.venv\\Scripts\\python.exe',
      localVenvExists: false,
    })).toBe('python');
  });
});
```

- [ ] **Step 2: Run the new test and verify it fails because the helper does not exist**

```powershell
npm --prefix frontend test -- --run playwrightPython.test.ts
```

Expected: FAIL with an import/module-not-found error for `./playwrightPython`.

- [ ] **Step 3: Implement the pure helper**

Create `frontend/playwrightPython.ts`:

```ts
interface ResolvePythonCommandOptions {
  explicitPython?: string;
  localVenvPython: string;
  localVenvExists: boolean;
}

function quoteExecutable(path: string): string {
  return `"${path.replaceAll('"', '\\"')}"`;
}

export function resolvePythonCommand({
  explicitPython,
  localVenvPython,
  localVenvExists,
}: ResolvePythonCommandOptions): string {
  const explicit = explicitPython?.trim();
  if (explicit) return explicit;
  if (localVenvExists) return quoteExecutable(localVenvPython);
  return 'python';
}
```

The explicit override is treated as a complete trusted local command so values such as `py -3.12` remain usable. The repository-derived executable path is quoted.

- [ ] **Step 4: Run helper tests**

```powershell
npm --prefix frontend test -- --run playwrightPython.test.ts
```

Expected: 3 tests pass.

### Task 4: Wire Dynamic Python Selection Into Playwright

**Files:**
- Modify: `frontend/playwright.config.ts:1-8,26-39`
- Test: `frontend/playwrightPython.test.ts`

- [ ] **Step 1: Import filesystem/path helpers and the resolver**

At the top of `frontend/playwright.config.ts` add:

```ts
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { resolvePythonCommand } from './playwrightPython';
```

- [ ] **Step 2: Resolve the repository-local interpreter relative to the config file**

After URL/port constants add:

```ts
const frontendDir = fileURLToPath(new URL('.', import.meta.url));
const localVenvPython = resolve(frontendDir, '..', '.venv', 'Scripts', 'python.exe');
const pythonCommand = resolvePythonCommand({
  explicitPython: process.env.E2E_PYTHON,
  localVenvPython,
  localVenvExists: existsSync(localVenvPython),
});
```

- [ ] **Step 3: Replace the hard-coded webServer command**

Replace:

```ts
command: `..\\.venv\\Scripts\\python.exe -m uvicorn ...`,
```

with:

```ts
command: `${pythonCommand} -m uvicorn app.main:app --app-dir ..\\backend --host 127.0.0.1 --port ${backendPort} --no-access-log`,
```

Keep the unique per-process SQLite URL and fake provider environment unchanged.

- [ ] **Step 4: Run helper tests, typecheck, and list Playwright tests**

```powershell
npm --prefix frontend test -- --run playwrightPython.test.ts
npm --prefix frontend run typecheck
npm --prefix frontend run test:e2e -- --list
```

Expected: helper tests pass; typecheck exits 0; Playwright starts configuration successfully and lists all configured E2E tests without “path not found”. If PATH has no Python, set `E2E_PYTHON` to the verified interpreter and rerun; do not hard-code the machine-specific path.

### Task 5: Correct the Browser Persistence Contract

**Files:**
- Modify: `frontend/e2e/memories.spec.ts:31-63`

- [ ] **Step 1: Name the original and updated content once**

At the beginning of the first test, after error arrays, add:

```ts
const originalContent = '用户偏好中文回复。';
const updatedContent = '用户偏好简洁的中文回复。';
```

Replace duplicate string literals in the create/edit assertions with these constants.

- [ ] **Step 2: Assert the latest persisted content after reload**

Replace the incorrect final assertion:

```ts
await expect(page.getByText('用户偏好中文回复。')).toBeVisible();
```

with:

```ts
await expect(page.getByText(updatedContent)).toBeVisible();
await expect(page.getByText(originalContent)).toHaveCount(0);
```

This must be after `await page.reload()`.

- [ ] **Step 3: Keep console and 5xx assertions unchanged**

Do not filter the NaN warning or weaken:

```ts
expect(serverErrors).toEqual([]);
expect(consoleErrors).toEqual([]);
```

The test must fail if any React warning, page error, or HTTP 5xx occurs.

- [ ] **Step 4: Run the focused memory E2E using the default config**

```powershell
npm --prefix frontend run test:e2e -- e2e/memories.spec.ts
```

Expected: 2 tests pass using `frontend/playwright.config.ts`; no temporary acceptance config is required; no console errors or 5xx responses.

If failure artifacts are produced, inspect them before changing code. Do not delete pre-existing `test-results/` wholesale.

### Task 6: Run Complete Frontend and Browser Regression

**Files:**
- No product files modified.

- [ ] **Step 1: Run all Vitest tests**

```powershell
npm --prefix frontend test -- --run
```

Expected: all test files and tests pass, including the new Playwright helper and MemoryPanel regression.

- [ ] **Step 2: Run TypeScript typecheck**

```powershell
npm --prefix frontend run typecheck
```

Expected: exit code 0.

- [ ] **Step 3: Run production build**

```powershell
npm --prefix frontend run build
```

Expected: exit code 0 and completed Vite build.

- [ ] **Step 4: Run complete configured E2E**

```powershell
npm --prefix frontend run test:e2e
```

Expected: every configured Playwright test passes; no console errors, page errors, HTTP 5xx, or webServer startup failures.

- [ ] **Step 5: Record exact fresh results**

Capture command, exit code, test count, duration, and any warnings for the acceptance report. Never substitute historical counts for this run.

### Task 7: Re-verify the Runtime Boundary and Cleanup

**Files:**
- No product files modified.
- Modify later: `docs/stage3-memory-acceptance-audit.md`

- [ ] **Step 1: Invoke the repository-scoped runtime workflow**

Use `AI桌宠:verify` with a uniquely named SQLite file, fake LLM, fake summary provider, unused port, and proxies disabled. Observe:

```text
GET /health -> 200/ok
POST /api/memories -> 201 active memory
PATCH /api/memories/{id} -> latest content persisted
GET /api/memories -> latest content returned, original content absent
malformed memory request -> 422
```

- [ ] **Step 2: Inspect the same isolated SQLite file**

Verify the row contains the updated content and valid importance/confidence, and no duplicate row was created by PATCH.

- [ ] **Step 3: Stop and clean up only task-owned resources**

Stop uvicorn and delete only the uniquely named database created by this task. Do not delete unknown or pre-existing databases.

### Task 8: Update the Acceptance Decision and Project Status

**Files:**
- Modify: `docs/stage3-memory-acceptance-audit.md`
- Modify: `README.md:3-52`
- Modify: `CLAUDE.md:3-4,69-82,98-123`

- [ ] **Step 1: Append a repair verification section to the audit**

Add:

```markdown
## Repair Verification — 2026-07-13

- Root causes: stale E2E post-reload assertion, `NaN` controlled numeric draft, fixed `.venv` path.
- Files changed: list only task-owned paths.
- Fresh validation: exact commands, counts, durations, exit codes.
- Runtime observation: updated memory content returned after reload-equivalent GET and persisted in isolated SQLite.
- Cleanup: server stopped and task-owned database deleted.
```

- [ ] **Step 2: Make the decision strictly from observed results**

If every mandatory command in Tasks 5–7 passes, change the report status to PASS and write:

```text
Stage 3 acceptance audit: PASS after repair verification on 2026-07-13. Stage 3 may close. The next eligible task is Stage 4 emotion-system design; no Stage 4 implementation was included in this repair.
```

If any mandatory command fails, keep BLOCKED and name the first concrete remaining blocker. Do not proceed to Stage 4.

- [ ] **Step 3: Synchronize `CLAUDE.md`**

On PASS, use:

```markdown
> 当前阶段：**阶段 3——长期记忆（COMPLETED；2026-07-13 总体验收修复复验 PASS；NEXT: Stage 4 Emotion System Design）**
```

and:

```markdown
| 阶段 3：长期记忆 | **COMPLETED**（2026-07-13；总体验收修复复验 PASS） | 已关闭；后续只允许维护、修复或证据补充，不得扩大阶段 3 范围 |
```

Set Stage 4 to design-next/not implemented. On BLOCKED, retain `IMPLEMENTING` and replace the next task with the observed blocker.

- [ ] **Step 4: Synchronize `README.md`**

On PASS, state that Stage 3 passed after the refresh-persistence repair and that Stage 4 design is next. Keep summary injection and automatic conflict resolution explicitly unimplemented unless a later approved plan changes their status. On BLOCKED, mirror the exact blocker from the audit.

- [ ] **Step 5: Run consistency and whitespace scans**

```powershell
git -C "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠" diff --check -- README.md CLAUDE.md docs/stage3-memory-acceptance-audit.md frontend/src/components/MemoryPanel.tsx frontend/src/components/MemoryPanel.test.tsx frontend/playwrightPython.ts frontend/playwrightPython.test.ts frontend/playwright.config.ts frontend/e2e/memories.spec.ts
git -C "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠" grep -n -E "当前执行阶段 3 总体验收|NEXT: Memory Panel Refresh Persistence Repair|阶段 3 总体验收.*BLOCKED" -- README.md CLAUDE.md docs/stage3-memory-acceptance-audit.md
```

Expected on PASS: `diff --check` exits 0 apart from possible line-ending warnings; no stale current-status BLOCKED claim remains outside the historical audit narrative. Expected on BLOCKED: current documents consistently name the new concrete blocker.

- [ ] **Step 6: Review only task-owned changes and do not commit**

```powershell
git -C "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠" status --short
git -C "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠" diff -- frontend/src/components/MemoryPanel.tsx frontend/src/components/MemoryPanel.test.tsx frontend/playwright.config.ts frontend/e2e/memories.spec.ts README.md CLAUDE.md
git -C "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠" diff --no-index -- /dev/null frontend/playwrightPython.ts
git -C "C:\Users\张乐航\Desktop\AI桌宠-主体-20260710\AI桌宠" diff --no-index -- /dev/null frontend/playwrightPython.test.ts
```

Also review the untracked audit/design/plan files directly. Do not stage or commit: explicit commit authorization was not provided.

## Self-Review

- Spec coverage: numeric drafts, latest-content reload semantics, Python resolution, focused/full frontend and E2E, runtime verification, cleanup, and status synchronization all have explicit tasks.
- Scope: no backend product change, summary injection, conflict auto-resolution, emotion implementation, desktop shell, or asset work is included.
- Type consistency: `number | ''` is narrowed before `UpdateMemoryRequest`; the resolver input and all tests use identical property names.
- No placeholders: every code-changing step includes concrete code and every validation step gives a command and expected result.
- Commit rule: the generic plan format normally recommends frequent commits, but this plan consistently leaves work unstaged because the user authorized automatic execution, not commits.
