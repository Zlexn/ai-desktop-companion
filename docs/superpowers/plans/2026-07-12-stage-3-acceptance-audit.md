# Stage 3 Acceptance Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct stale Stage 3 milestone text, verify the implemented 3A–3M, memory GUI CRUD, and chat-context budget against the project’s Stage 3 boundary, and record a defensible PASS or BLOCKED decision.

**Architecture:** This is an audit and documentation slice, not a product-feature slice. First establish a clean evidence inventory and preserve the already-dirty working-tree baseline, then run focused Stage 3 tests, full regressions, browser E2E, and isolated runtime API verification. Only a complete PASS may close Stage 3 in `CLAUDE.md`; any failure leaves Stage 3 open and is recorded without adding Stage 4 behavior or silently weakening acceptance criteria.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, pytest, React, TypeScript, Vite, Vitest, Playwright, Markdown documentation.

---

## File Structure

- Create: `docs/stage3-memory-acceptance-audit.md` — authoritative Stage 3 scope, evidence matrix, observed command results, limitations, and PASS/BLOCKED decision.
- Modify: `README.md:3-55` — remove stale “context budget is next” and old 3A–3H/3I milestone language; point to the audit as the current task or completed evidence.
- Modify: `CLAUDE.md:3-4,69-82,98-123` — remove the stale context-budget “下一最小完整闭环” text and, only after PASS, close Stage 3 and identify Stage 4 design as the next eligible task.
- Do not modify product source or tests during the audit. If verification finds a defect, record it as a blocker and create a separate repair plan rather than folding implementation into the audit.

## Acceptance Matrix

The audit must explicitly evaluate every Stage 3 rule from `CLAUDE.md:98-113`:

1. Memories retain source, time, type, importance, and confidence.
2. Automatic extraction creates only pending candidates; activation requires explicit confirmation.
3. Users can list, create, edit, and archive/delete active memories.
4. Only active memories may enter chat retrieval context; pending, dismissed, and archived records stay excluded.
5. Relevance retrieval works in deterministic mode; embedding retrieval remains explicit opt-in and provider-isolated.
6. Conflicts are surfaced and audited rather than silently overwriting, merging, or deleting memories.
7. Chat history, session summaries, and long-term memories remain separately stored.
8. Incremental summaries are non-blocking, independently stored, sanitized best-effort, and not injected into chat context.
9. The final Provider payload enforces the configured character budget while preserving the role system prompt and current user message.
10. Stage 4 emotion state, summary injection, and automatic conflict resolution remain absent.

### Task 1: Freeze Scope and Preserve the Dirty-Tree Baseline

**Files:**
- Read: `CLAUDE.md`
- Read: `README.md`
- Read: `docs/stage3*.md`
- Read: `docs/superpowers/specs/2026-07-12-chat-context-budget-design.md`
- Read: `docs/superpowers/plans/2026-07-12-chat-context-budget.md`
- Create: `docs/stage3-memory-acceptance-audit.md`

- [ ] **Step 1: Record task alignment before editing**

Use this exact boundary in working notes and later in the audit report:

```text
当前阶段：阶段 3——长期记忆（IMPLEMENTING；功能切片完成，待总体验收）
本次目标：修正文档状态并审计 Stage 3 是否满足关闭条件
修改范围：README.md、CLAUDE.md（仅按审计结果同步）、docs/stage3-memory-acceptance-audit.md
验证方式：Stage 3 focused pytest、后端全量 pytest、前端 Vitest/typecheck/build、memory Playwright E2E、隔离数据库运行时 API 验证
主要风险：当前工作树已有大量未提交改动；历史文档证据不能冒充本次运行结果；可选真实 Provider 不应阻塞默认离线验收
阶段边界：不实现摘要注入、自动冲突解决或阶段 4 情感系统
```

- [ ] **Step 2: Capture the pre-existing working-tree baseline**

Run:

```powershell
git status --short
git diff --name-only
git ls-files --others --exclude-standard
```

Expected: the tree is already dirty. Save the complete observed path lists in a temporary working note. During final review, attribute only these audit-owned paths to this task:

```text
README.md
CLAUDE.md
docs/stage3-memory-acceptance-audit.md
```

Do not reset, discard, stage, or overwrite any pre-existing change.

- [ ] **Step 3: Inventory evidence without treating it as fresh verification**

Read `docs/stage3*.md` and build a table mapping 3A–3M plus GUI CRUD and context budget to their evidence documents. Label all reported historical test counts as `historical evidence`; reserve `observed in this audit` for commands executed in Tasks 3–5.

### Task 2: Correct Stale Current-Task Documentation

**Files:**
- Modify: `README.md:3-55`
- Modify: `CLAUDE.md:115-123`

- [ ] **Step 1: Replace README’s stale Stage 3 status**

Update the opening status and current-task sections so they state:

```markdown
当前阶段：阶段 3——长期记忆（3A–3M、长期记忆 GUI CRUD 与聊天 Provider 上下文字符预算已完成；当前执行阶段 3 总体验收审计）。摘要注入、自动冲突合并/解决和阶段 4 情感系统尚未实现。
```

In the implemented-scope list, replace “Stage 3 下一任务：聊天 Provider 上下文字符预算” with a completed context-budget entry that links:

```markdown
- Stage 3 聊天 Provider 上下文字符预算：最终 Provider payload 已执行可配置的整条消息裁剪，保留角色 system prompt 与当前用户消息；设计与完成记录见 `docs/superpowers/specs/2026-07-12-chat-context-budget-design.md` 和 `docs/superpowers/plans/2026-07-12-chat-context-budget.md`。
```

Rename `### Stage 3 next task` to `### Stage 3 acceptance audit` and state that the audit is the next/current minimal closure task. Keep summary injection, automatic conflict resolution, and Stage 4 explicitly out of scope.

- [ ] **Step 2: Remove CLAUDE.md’s internally stale next-task block**

Replace `CLAUDE.md:115-121` with:

```markdown
### 下一最小完整闭环

阶段 3 总体验收审计：核对 3A–3M、长期记忆 GUI CRUD 与聊天 Provider 上下文字符预算的实现和证据，运行后端、前端、E2E 与隔离运行时验证，并将结论记录到 `docs/stage3-memory-acceptance-audit.md`。

该审计不实现摘要注入、自动冲突合并/解决或阶段 4。只有阶段 3 验收标准全部通过后，才能关闭阶段 3 并进入阶段 4 设计；如有失败，阶段 3 保持 IMPLEMENTING，并先另立最小修复任务。
```

Do not change the current Stage 3 status to COMPLETED in this task step.

- [ ] **Step 3: Review the documentation-only diff**

Run:

```powershell
git diff -- README.md CLAUDE.md
```

Expected: stale “context budget is next” language is gone; the documents do not claim that the audit has passed; no acceptance criterion is weakened.

### Task 3: Run Focused Stage 3 Automated Verification

**Files:**
- No product files modified.
- Create/Modify: `docs/stage3-memory-acceptance-audit.md`

- [ ] **Step 1: Run the focused memory, summary, chat-boundary, and configuration suite**

Run from the repository root:

```powershell
python -m pytest backend/tests/test_repositories.py backend/tests/test_api_memories.py backend/tests/test_context_builder.py backend/tests/test_memory_candidate_service.py backend/tests/test_chat_memory_candidates.py backend/tests/test_memory_embeddings.py backend/tests/test_memory_embedding_evaluation.py backend/tests/test_session_summaries.py backend/tests/test_session_summary_sanitizer.py backend/tests/test_session_summary_provider.py backend/tests/test_session_summary_service.py backend/tests/test_chat_service.py backend/tests/test_api_chat.py backend/tests/test_config.py -q
```

Expected: exit code 0 and all selected tests PASS. This command intentionally includes repository/audit coverage in `test_repositories.py`, memory API coverage, context assembly, candidate handling, retrieval/embedding, summary isolation/generation, chat payload budgeting, and configuration. If collection fails because the test inventory changed, record the exact error, rebuild the command from the current `backend/tests/test_*memory*.py`, `backend/tests/test_*summary*.py`, `test_repositories.py`, `test_api_memories.py`, `test_context_builder.py`, `test_chat_service.py`, `test_api_chat.py`, and `test_config.py` surfaces, then rerun without omitting an existing Stage 3 test file.

- [ ] **Step 2: Record focused results**

Add the exact command, date, exit code, pass count, duration, and any warnings to the audit report. A non-zero result makes the audit `BLOCKED` until repaired and rerun.

### Task 4: Run Full Regression and Frontend Acceptance Verification

**Files:**
- No product files modified.
- Create/Modify: `docs/stage3-memory-acceptance-audit.md`

- [ ] **Step 1: Run the full backend suite**

```powershell
python -m pytest backend/tests -q
```

Expected: exit code 0 with all backend tests passing.

- [ ] **Step 2: Run all frontend tests**

```powershell
npm --prefix frontend test -- --run
```

Expected: exit code 0 with all Vitest tests passing, including memory panel create/edit/cancel/validation behavior.

- [ ] **Step 3: Run TypeScript typecheck**

```powershell
npm --prefix frontend run typecheck
```

Expected: exit code 0.

- [ ] **Step 4: Run the production build**

```powershell
npm --prefix frontend run build
```

Expected: exit code 0 and a completed Vite build.

- [ ] **Step 5: Run the memory browser E2E slice**

```powershell
npm --prefix frontend run test:e2e -- e2e/memories.spec.ts
```

Expected: exit code 0; Playwright verifies memory create/edit/cancel/validation/persistence and candidate confirmation without console errors or HTTP 5xx responses.

- [ ] **Step 6: Run the complete configured E2E suite**

```powershell
npm --prefix frontend run test:e2e
```

Expected: exit code 0. This guards Stage 1 text and Stage 2 voice surfaces while closing Stage 3.

- [ ] **Step 7: Record every observed result**

For each command, record the exact test/build count, duration, exit code, and failure output. Do not replace an observed failure with a historical passing count.

### Task 5: Verify the Runtime API Boundary End to End

**Files:**
- No product files modified.
- Create/Modify: `docs/stage3-memory-acceptance-audit.md`

- [ ] **Step 1: Invoke the repository-scoped runtime verification workflow**

Use the `AI桌宠:verify` skill. It must launch the backend against a uniquely named temporary SQLite database and fake/default offline providers, drive the affected HTTP flow, and clean up the temporary process and database afterward.

- [ ] **Step 2: Exercise the Stage 3 runtime flow**

The runtime verification must observe all of the following in one isolated environment:

```text
GET /api/health returns 200/ok.
POST /api/memories creates an active manual memory with source, type, importance, confidence, and timestamps.
PATCH /api/memories/{id} persists an edit.
A conflicting create/update preserves both records and creates a retrievable audit event.
A chat fact produces a pending candidate under the configured offline candidate path.
POST /api/memories/{id}/confirm activates that candidate.
POST /api/memories/{id}/dismiss leaves a dismissed candidate out of active retrieval.
DELETE /api/memories/{id} archives the memory and removes it from the active list.
A later chat request receives relevant active memory context but excludes pending, dismissed, and archived content.
Generated session summary rows remain separate and their text is absent from later Provider messages.
An oversized history is pruned at the Provider boundary while the role system prompt and current user message remain present.
No memory or summary content appears in logs as a credential leak, and no Stage 4 emotion state is created.
```

If a scenario requires instrumentation not exposed by public HTTP responses, use existing fake/recording providers and repository queries in an isolated verification harness; do not add production endpoints solely for the audit.

- [ ] **Step 3: Record runtime evidence faithfully**

Record the temporary database isolation method, provider configuration, requests made, status codes, key observed fields, cleanup result, and any scenario that could not be observed. An unobserved required scenario makes the audit `BLOCKED`; optional real-provider quality checks do not.

### Task 6: Write the Stage 3 Acceptance Audit Report

**Files:**
- Create: `docs/stage3-memory-acceptance-audit.md`

- [ ] **Step 1: Create the report with this structure**

```markdown
# Stage 3 Memory Acceptance Audit

Status: AUDITED on 2026-07-12 — PASS or BLOCKED.

## Scope
## Acceptance Boundary
## Historical Evidence Inventory
## Acceptance Matrix
## Focused Stage 3 Validation
## Full Regression Validation
## Frontend and Browser Validation
## Runtime API Verification
## Security and Data-Control Review
## Limitations
## Stage Decision
## Next Minimal Task
```

- [ ] **Step 2: Populate the acceptance matrix**

Use one row per item in this plan’s Acceptance Matrix with columns:

```markdown
| Requirement | Code/test evidence | Fresh audit evidence | Result |
|---|---|---|---|
```

Every result must be `PASS`, `FAIL`, or `NOT OBSERVED`; `NOT OBSERVED` blocks closure when the requirement is mandatory.

- [ ] **Step 3: Record security and data-control checks**

Document that real secrets were not used, the runtime database was isolated, pending/dismissed/archived records were excluded from chat context, conflicts retained audit traces, summaries remained separate, and no automatic conflict resolution or emotion behavior was introduced. If any statement was not directly observed, label it as test/code evidence rather than runtime observation.

- [ ] **Step 4: Make the stage decision**

If every mandatory acceptance row and every required command passes, write:

```text
Stage 3 acceptance audit: PASS. Stage 3 may close. The next eligible work is Stage 4 emotion-system design; this audit did not implement Stage 4.
```

Otherwise write:

```text
Stage 3 acceptance audit: BLOCKED. Stage 3 remains IMPLEMENTING. The listed failures or unobserved mandatory requirements require a separate minimal repair/verification task before this audit is rerun.
```

- [ ] **Step 5: State limitations without turning them into false blockers**

Explicitly list that real LLM summary quality/cost, real embedding quality beyond recorded evaluation, summary injection, automatic conflict resolution, and Stage 4 emotion behavior are outside this audit. Optional real-provider checks are historical/operational evidence, not default offline closure requirements unless a required contract fails under the fake/provider-isolated test surfaces.

### Task 7: Synchronize Project Status from the Audit Decision

**Files:**
- Modify: `CLAUDE.md:3-4,69-82,98-123`
- Modify: `README.md:3-55`
- Read: `docs/stage3-memory-acceptance-audit.md`

- [ ] **Step 1: Update status only on PASS**

On PASS, change the project status to:

```markdown
> 当前阶段：**阶段 3——长期记忆（COMPLETED；2026-07-12 总体验收 PASS；NEXT: Stage 4 Emotion System Design）**
```

Change the stage table row to:

```markdown
| 阶段 3：长期记忆 | **COMPLETED**（2026-07-12；总体验收审计 PASS） | 已关闭；后续只允许维护、修复或证据补充，不得扩大阶段 3 范围 |
```

Add `docs/stage3-memory-acceptance-audit.md` to the acceptance evidence links. Set Stage 4 to the next design stage, but do not mark it implemented and do not add emotion code.

- [ ] **Step 2: Keep Stage 3 open on BLOCKED**

On BLOCKED, keep Stage 3 `IMPLEMENTING`. In both `CLAUDE.md` and `README.md`, replace “current audit” with the concrete first blocker from the report as the next minimal task. Do not claim Stage 4 is eligible.

- [ ] **Step 3: Check cross-document consistency**

Search:

```powershell
git grep -n -E "Stage 3 next task|聊天 Provider 上下文字符预算|阶段 3 总体验收|Stage 3 acceptance" -- README.md CLAUDE.md docs
```

Expected: historical specs/plans may describe the former sequence, but current-status sections in `README.md` and `CLAUDE.md` agree with the audit decision and do not still call the completed context budget the next task.

### Task 8: Final Review and Handoff

**Files:**
- Read: `README.md`
- Read: `CLAUDE.md`
- Read: `docs/stage3-memory-acceptance-audit.md`

- [ ] **Step 1: Review only audit-owned diffs against the baseline**

```powershell
git diff -- README.md CLAUDE.md docs/stage3-memory-acceptance-audit.md
git status --short
```

Expected: no product source or test was changed by the audit; all pre-existing unrelated modifications remain untouched. The report’s command results exactly match observed outputs.

- [ ] **Step 2: Run a documentation consistency scan**

```powershell
git grep -n -E "3A–3H|下一步是 3I|上下文字符预算.*下一|Context Budget.*NEXT" -- README.md CLAUDE.md
```

Expected: no stale current-status claim remains.

- [ ] **Step 3: Do not commit without explicit authorization**

Because the working tree already contains many unrelated modified and untracked files, leave all changes unstaged. If the user later explicitly requests a commit, stage only:

```text
README.md
CLAUDE.md
docs/stage3-memory-acceptance-audit.md
```

and review `git diff --cached` before committing.

- [ ] **Step 4: Report in the project-required format**

```text
完成内容：
修改文件：
验证命令与结果：
未完成或受限部分：
是否改变当前阶段：否/是（附验收证据）
下一项建议任务：
```

## Self-Review

- Spec coverage: The plan corrects both stale current-status documents, verifies all mandatory Stage 3 rules, runs focused/full/frontend/E2E/runtime surfaces, and gates Stage 3 closure on fresh evidence.
- Placeholder scan: Every action, expected result, and PASS/BLOCKED branch is explicit; no deferred implementation markers remain.
- Type and path consistency: Runtime endpoint paths match `backend/app/api/routes/memories.py`; commands match `frontend/package.json` and `backend/pyproject.toml`; the audit report path is consistent throughout.
- Scope check: Product fixes, summary injection, automatic conflict resolution, and Stage 4 implementation are deliberately excluded and require separate plans if needed.
