# Stage 3 Memory Panel Refresh Acceptance Repair Design

> 日期：2026-07-13  
> 状态：设计已批准  
> 项目根：`AI桌宠/`

## 1. 背景

Stage 3 总体验收在 2026-07-13 判定 BLOCKED。后端 focused/full、前端 Vitest/typecheck/build 和隔离运行时 API 验证均通过，但 MemoryPanel Playwright E2E 的手动记忆用例失败，并出现 React console error。

调查确认三个相互独立的问题：

1. E2E 创建 `用户偏好中文回复。`，随后将其编辑为 `用户偏好简洁的中文回复。`，刷新后却错误地继续断言旧内容。后端 PATCH 和隔离 SQLite 证据已证明最新编辑内容会持久化。
2. `MemoryPanel` 使用 `event.target.valueAsNumber` 直接更新 number state。清空数字输入时该值为 `NaN`，组件随后把 `NaN` 传回受控 input 的 `value`，触发 React `Received NaN for the value attribute`。
3. `frontend/playwright.config.ts` 固定调用 `../.venv/Scripts/python.exe`；当前 checkout 不保证存在该虚拟环境，导致 E2E 无法在已有 Python 环境中启动。

## 2. 目标与阶段边界

本任务只修复 Stage 3 验收阻塞项，使长期记忆 GUI 的创建、编辑、临时无效数字输入、刷新恢复和聊天相邻流程可在真实浏览器中通过。

长期项目目标仍是：在 Windows 11 本地部署一个可实时或接近实时文字、语音交流，具备长期记忆、连续且受约束的情感表现，并最终具有桌面角色呈现的私人虚拟角色系统。目标角色风格参考雪之下雪乃，但仓库不得捆绑未经授权的角色形象、Live2D 模型、克隆声线或其他受保护素材；系统只实现角色一致性、记忆与情感表现，不宣称真实意识或真实情感。

本任务不得实现：

- 会话摘要注入；
- 自动冲突合并或解决；
- Stage 4 情感状态；
- Live2D、桌面壳或角色素材；
- 与本次验收无关的前后端重构。

## 3. 采用方案

采用最小、分层修复：

1. 修正 E2E 的刷新后断言，使其验证最新编辑内容，并验证旧内容不再出现。
2. 将 MemoryPanel 数字编辑草稿表示为 `number | ''`，避免向 React 传入 `NaN`。
3. 让 Playwright 按显式环境变量、本地 `.venv`、PATH Python 的顺序解析后端 Python 命令。
4. 增加针对数字空值和刷新持久化语义的测试。
5. 重跑前端全量和浏览器全量验证；根据观察结果更新 Stage 3 验收结论。

不采用“编辑成功后额外重新请求整个列表”，因为 PATCH 响应已经是权威持久化结果，额外请求不能修复错误断言，只会增加网络调用和状态竞争面。

## 4. 组件设计

### 4.1 MemoryPanel 数字草稿

`editImportance` 和 `editConfidence` 的状态类型改为 `number | ''`。

行为规则：

- 开始编辑时使用现有 memory 的合法数字初始化。
- 输入框为空时状态保存 `''`，input 的 `value` 也是空字符串。
- 输入框非空时读取 `valueAsNumber`；只有有限数值才写入 number，否则回退为空字符串。
- `canSaveEdit` 必须先通过 `typeof value === 'number'`，再检查整数性、有限性和范围。
- `handleUpdate` 只有在验证成功后构造 `UpdateMemoryRequest`，因此传给 API 的 importance/confidence 始终为 number。
- 空白或越界草稿只禁用保存，不自动改写为默认值；用户取消编辑后草稿被丢弃。

这样可以保留浏览器数字输入的自然编辑过程，同时避免 React controlled-input warning。

### 4.2 App 数据流

`App` 保持现有边界：

- 启动时分别请求 active memories 和 pending candidates。
- create/update/confirm/delete 成功后使用服务器响应更新本地 state。
- 页面刷新后重新从 API 加载持久化 active memories。

本任务不修改后端 API 或 SQLite 行为。E2E 的刷新恢复以服务器返回的最新编辑内容为准。

### 4.3 Playwright Python 解析

在 Playwright 配置中建立小型、确定性的 Python 命令解析：

1. 若 `E2E_PYTHON` 非空，使用其值；
2. 否则若仓库根的 `.venv/Scripts/python.exe` 存在，使用该绝对路径；
3. 否则使用 `python`，由当前 PATH 解析。

规则：

- 文件路径作为命令使用时必须加引号，以支持空格和中文路径。
- 环境变量允许 CI 或特殊本地环境显式选择解释器。
- 配置不创建环境、不安装依赖、不改变 execution policy。
- 删除临时 acceptance config 的需求另行基于归属确认；本任务不删除未知或既有文件。

## 5. 浏览器验收数据流

手动记忆 E2E 固定验证：

1. 打开应用并观察 MemoryPanel。
2. 创建 `用户偏好中文回复。`。
3. 编辑为 `用户偏好简洁的中文回复。`，并修改 importance/confidence。
4. 验证取消编辑不会保存草稿。
5. 清空数字输入，验证保存按钮禁用，且页面不产生 console error。
6. 创建会话并发送文字消息，确认相邻聊天流程正常。
7. 刷新页面。
8. 验证最新内容 `用户偏好简洁的中文回复。` 存在。
9. 验证旧内容 `用户偏好中文回复。` 不存在。
10. 验证全过程没有 HTTP 5xx、page error 或 console error。

候选记忆确认与刷新用例继续保留，防止 active/pending 状态边界回归。

## 6. 错误处理

- Memory update API 失败时继续由父组件显示共享错误，编辑草稿保持打开以便重试。
- 数字输入的临时空值属于本地无效草稿，不发送 API 请求。
- Python 显式路径错误时，Playwright webServer 应以清晰的进程启动错误失败，不静默切换到另一解释器。
- PATH 中没有 Python 时同样明确失败，不在测试配置中自动安装。
- 任一 mandatory E2E 失败都保持 Stage 3 `IMPLEMENTING`，不得以单元测试通过替代浏览器验收。

## 7. 测试设计

### 7.1 组件测试

在 `MemoryPanel.test.tsx` 覆盖：

- 清空 importance 时输入框保持空值；
- 保存按钮禁用；
- 不调用 `onUpdate`；
- 不向 console.error 输出 NaN controlled-input warning；
- 重新输入合法值后可保存正确 number；
- confidence 空值采用相同边界。

### 7.2 App 测试

保留并核对启动加载 active memories 的测试，确保 `/api/memories` 响应会显示服务器内容。若现有测试已经充分覆盖，不重复创建同义测试。

### 7.3 配置测试

优先把 Python 解析提取为可单测的小函数，覆盖：

- `E2E_PYTHON` 优先；
- `.venv` 存在时采用本地解释器；
- `.venv` 不存在时回退 `python`；
- 含空格路径正确加引号。

如果 Playwright 配置无法在现有 Vitest 边界内低成本导入，则通过实际 E2E 启动覆盖，避免为测试配置引入新的框架。

### 7.4 验证命令

从仓库根运行：

```powershell
npm --prefix frontend test -- --run
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm --prefix frontend run test:e2e -- e2e/memories.spec.ts
npm --prefix frontend run test:e2e
```

运行浏览器测试时使用唯一临时 SQLite 数据库和 fake providers。测试进程和临时数据库必须清理。

## 8. 完成标准

只有同时满足以下条件才完成本修复：

1. 数字输入清空不会产生 `value=NaN` console error。
2. 无效数字草稿不能提交。
3. 手动记忆编辑后刷新显示最新持久化内容，旧内容不再显示。
4. candidate confirm/reload E2E 继续通过。
5. 默认 Playwright 配置可在没有仓库 `.venv`、但 PATH 有 Python 的环境启动；也支持 `E2E_PYTHON` 覆盖。
6. 前端 Vitest、typecheck、build、memory E2E 和完整 E2E 全部 exit 0。
7. 无新增 HTTP 5xx、page error 或 console error。
8. 根据新鲜结果更新 `docs/stage3-memory-acceptance-audit.md`、`README.md` 和 `CLAUDE.md`：全部 mandatory 项通过才可将 Stage 3 关闭；否则如实保留 BLOCKED。

## 9. 后续路线

本修复通过并关闭 Stage 3 后，下一阶段是 Stage 4 情感系统的独立设计和实施。Stage 4 验收后，再规划 Windows 原生桌宠呈现、合法角色素材接入、表情/口型事件和本地部署打包。实时交流质量、真实 ASR/TTS 延迟、连续运行资源占用和授权边界均必须在目标 Windows 11 机器上实测，不能以功能列表代替验收。
