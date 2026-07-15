# Stage 3 Memory Acceptance Audit

Status: AUDITED on 2026-07-13 — **PASS after repair verification**.

## Scope

本次审计核对 Stage 3A–3M、长期记忆 GUI CRUD 和聊天 Provider 上下文字符预算。审计只修改本报告及项目状态文档，不实现摘要注入、自动冲突解决或 Stage 4 情感系统。

## Acceptance Boundary

强制验收范围来自 `CLAUDE.md` 和 `docs/superpowers/plans/2026-07-12-stage-3-acceptance-audit.md`。默认 fake/offline Provider 是关闭阶段的基线；真实 LLM、真实 embedding 的质量和费用不是本次默认离线阻塞项。

审计开始时工作树已有大量修改和未跟踪文件。本次未重置、覆盖或提交这些既有改动。

## Historical Evidence Inventory

| Slice | Historical evidence |
|---|---|
| 3A memory foundation | `docs/stage3-memory-foundation.md` |
| 3B candidate confirmation | `docs/stage3b-memory-candidate-confirmation.md` |
| 3C relevance retrieval | `docs/stage3c-memory-relevance-retrieval.md` |
| 3D conflict audit | `docs/stage3d-memory-conflict-audit.md` |
| 3E semantic conflict detection | `docs/stage3e-semantic-conflict-detection.md` |
| 3F embedding retrieval | `docs/stage3f-memory-embedding-retrieval.md` |
| 3G real embedding smoke | `docs/stage3g-real-embedding-smoke.md` |
| 3H real embedding evaluation | `docs/stage3h-real-embedding-model-evaluation.md` |
| 3I LLM candidate extraction | `docs/stage3i-llm-memory-candidate-extraction.md` |
| 3J production embedding selection | `docs/stage3j-real-embedding-production-selection.md` |
| 3K independent summary storage | `docs/stage3k-session-summary-independent-storage.md` |
| 3L semantic conflict expansion | `docs/stage3l-semantic-conflict-expansion.md` |
| 3M incremental summary generation | `docs/stage3m-session-summary-generation.md` |
| GUI CRUD | `docs/superpowers/plans/2026-07-12-memory-panel-inline-editing.md` |
| Provider context budget | `docs/superpowers/plans/2026-07-12-chat-context-budget.md` |

以上仅作为历史证据；本次结论以以下新鲜运行结果为准。

## Acceptance Matrix

| Requirement | Code/test evidence | Fresh audit evidence | Result |
|---|---|---|---|
| 记忆保留来源、时间、类型、重要度和可信度 | memory repository/API tests | 隔离 API create 返回全部字段，SQLite 持久化可见 | PASS |
| 自动抽取只创建 pending，必须明确确认后 active | candidate service/API tests | 隔离 API 观察到 pending → confirm → active | PASS |
| 用户可 list/create/edit/archive active memory | memory API、MemoryPanel tests | API create/patch/delete 通过；修复后浏览器创建、编辑、刷新恢复与候选确认均通过 | PASS |
| 只有 active memory 可进入检索上下文 | context-builder tests | focused suite 覆盖 pending/dismissed 排除；隔离库确认 dismissed/archived 状态保留 | PASS |
| deterministic relevance 可用，embedding 显式 opt-in 且 Provider 隔离 | context/embedding tests | focused suite 通过 | PASS |
| 冲突被暴露并审计，不静默覆盖/合并/删除 | conflict API/repository tests | 隔离 API 保留两条记录并生成 `conflict_detected` audit event | PASS |
| chat history、summary、long-term memory 分表存储 | schema/repository tests | 隔离 SQLite 中 `messages`、`session_summaries`、`memories` 分表可见 | PASS |
| 增量摘要非阻塞、独立存储、best-effort 脱敏且不注入聊天 | summary service/chat tests | 隔离运行生成 2 条独立 summary；focused suite 通过 | PASS |
| 最终 Provider payload 执行字符预算，并保留角色 prompt 和当前 user | chat service/API/config tests | focused suite 通过；实现级 runtime instrumentation 未另加生产端点 | PASS |
| Stage 4、summary injection、automatic conflict resolution 仍不存在 | code/config/document scan | 未观察到这些功能被引入 | PASS |

## Focused Stage 3 Validation

运行日期：2026-07-13。

计划中的相对路径命令首次从外层目录运行，因 `backend/tests/test_repositories.py` 不存在于该工作目录而以 exit 4 结束；随后使用当前仓库绝对路径重跑同一测试清单：

```text
223 passed in 7.03s
exit code 0
```

## Full Regression Validation

首次从外层目录对绝对 `backend/tests` 路径运行时，`test_cosyvoice_text.py` 因仓库根未进入 `sys.path` 而 collection error；从仓库根按计划重跑：

```text
410 passed in 17.76s
exit code 0
```

## Frontend and Browser Validation

```text
Vitest: 17 files passed, 158 tests passed, 35.57s, exit code 0
TypeScript typecheck: exit code 0
Vite production build: 36 modules transformed, built in 522ms, exit code 0
```

默认 `playwright.config.ts` 假定 `../.venv/Scripts/python.exe`，当前 checkout 没有该文件，因此默认 E2E 启动失败。使用工作树已有的 `playwright.acceptance.tmp.config.ts` 和实际 Python 后，memory E2E 确实启动并得到：

```text
2 tests total: 1 passed, 1 failed
```

失败项：`creates a manual memory and keeps text chat usable`。创建和编辑后，页面刷新，在 10 秒内找不到 `用户偏好中文回复。`。同次运行还出现 React console error：`Received NaN for the value attribute`。候选建议和确认用例通过。

因为 mandatory memory E2E 已失败，本次没有把完整 E2E 标记为通过；Stage 3 不满足关闭条件。

## Runtime API Verification

使用唯一数据库 `verify-stage3-20260713-1001.db`、端口 18137、`LLM_PROVIDER=fake`、`SESSION_SUMMARY_PROVIDER=fake`、summary trigger 2 启动 uvicorn，并通过 `httpx.Client(trust_env=False)` 驱动 HTTP：

- `GET /health` → 200 / `status=ok`。
- malformed memory importance 6 → 422。
- manual memory create → 201，source/type/importance/confidence/timestamps 齐全。
- memory patch → 200，内容、importance、confidence 持久化。
- duplicate/conflicting create → 201，原记录和新记录同时保留。
- audit events → 200，记录 `conflict_detected` 与相关 memory ID。
- chat fact → pending candidate；confirm → active。
- 第二条 chat fact → pending candidate；dismiss → dismissed。
- delete manual memory → 204；SQLite 状态为 archived，active list 排除它。
- 4 条消息生成 2 条独立增量 summary，覆盖区间各为 2 条消息。
- `messages`、`memories`、`memory_audit_events`、`session_summaries` 分表持久化。

服务随后停止，审计创建的数据库已删除。没有删除任何未知或既有数据库。

限制：项目没有公开 summaries GET API，因此摘要通过同一隔离 SQLite 文件验证；Provider payload 的精确 active-only/summary-exclusion/context-budget 内容由通过的 recording/fake provider 自动化测试验证，没有为审计增加生产端点。

## Security and Data-Control Review

- 仅使用 fake/offline Provider，没有使用真实 API key。
- 数据库使用唯一临时文件并在验证后清理。
- pending、dismissed、archived 状态被分别保留；自动化测试验证它们不进入聊天记忆上下文。
- 冲突保留审计痕迹，没有自动覆盖或合并。
- summaries 独立存储；自动化测试验证不会注入下一轮 Provider messages。
- 没有引入 Stage 4 emotion state。
- 终端输出存在 Windows 编码 mojibake，但 IDs、状态码、结构字段和数据库状态仍可判定；没有观察到凭据。

## Limitations

本审计不评价真实 LLM 摘要质量/费用、既有记录之外的真实 embedding 质量、summary injection、automatic conflict resolution 或 Stage 4 emotion behavior。真实 Provider 可选验证不是默认离线关闭条件。

## Repair Verification — 2026-07-13

根因被拆分并修复：刷新失败来自 E2E 在 PATCH 后错误断言创建时的旧内容；数值输入清空时曾把 `valueAsNumber=NaN` 写回受控 input；默认 Playwright 配置曾固定依赖不存在的仓库 `.venv`。

任务拥有的产品/测试文件：

- `frontend/src/components/MemoryPanel.tsx`
- `frontend/src/components/MemoryPanel.test.tsx`
- `frontend/playwrightPython.ts`
- `frontend/playwrightPython.test.ts`
- `frontend/playwright.config.ts`
- `frontend/e2e/memories.spec.ts`

新鲜验证结果：

```text
MemoryPanel focused Vitest: 10 passed; exit code 0
Python resolver focused Vitest: 3 passed; exit code 0
Memory Playwright E2E: 2 passed in 8.0s; exit code 0
Frontend full Vitest: 19 files, 165 tests passed in 13.76s; exit code 0
TypeScript typecheck: exit code 0
Vite production build: 36 modules transformed, built in 117ms; exit code 0
Complete Playwright E2E: 7 passed in 10.3s; exit code 0
E2E database cleanup: task-owned `cleanup-proof-94724.db` absent after global teardown
```

完整 E2E 使用修复后的默认 `frontend/playwright.config.ts` 启动，不再需要临时 acceptance 配置；当前环境没有仓库 `.venv` 时成功回退 PATH `python`，显式 `E2E_PYTHON` 的带空格 `.exe` 路径也有单元覆盖。默认配置通过 global teardown 只删除明确传入的本次 E2E 数据库，实际运行验证任务数据库在退出后不存在。手动记忆用例验证 PATCH 后刷新显示最新内容，并验证旧内容不存在。测试保留了严格的 console error、page error 和 HTTP 5xx 断言，未观察到 `value=NaN` 或其他错误。

运行时复验使用唯一数据库 `verify-memory-repair-20260713-1153.db`、端口 18153 和 fake providers：`GET /health` 为 200/ok；非法 importance 为 422；create 为 201；PATCH 为 200 并返回最新内容；后续 GET 仅返回一条更新后的 active memory，旧内容不存在；SQLite 精确保留一行，importance 5、confidence 0.8。服务已停止，任务创建的数据库已删除。

## Stage Decision

**Stage 3 acceptance audit: PASS after repair verification on 2026-07-13. Stage 3 may close.**

所有强制验收矩阵项及后端、前端、浏览器、隔离运行时验证均通过。下一项符合阶段顺序的工作是 Stage 4 情感系统设计；本次修复没有实现 Stage 4，也没有实现摘要注入或自动冲突解决。

## Next Minimal Task

为 Stage 4 情感系统建立独立设计：定义可解释、有界、可衰减、可查看/重置/关闭的情感状态，以及文本、TTS 和未来表情事件的受约束映射。设计必须继续维护角色原创/授权边界，不得把表现描述成真实意识或真实情感。
