# Stage 4E 消息绑定表现事件与浏览器语义预览

> 验收结论：**VERIFIED PASS（fake-first）**  
> 日期：2026-07-15  
> 范围：Stage 4E Tasks 1–12；本轮续作重点为 Tasks 6–12

## 范围与边界

Stage 4E 建立以下最小闭环：

```text
持久化 assistant 消息
→ 不可变 ExpressionPlan
→ 只读消息绑定表现 API
→ 版本化 expression / speaking 事件
→ 精确播放 run 生命周期
→ 中性浏览器语义预览
```

本阶段不实现 Windows 桌面壳、Live2D、后台监听、全双工语音、真实音频表现质量验证或任何未授权角色资源。表现字段是角色表达策略，不代表真实情感或意识。

## 已交付能力

### 只读消息绑定表现

`GET /api/messages/{assistant_message_id}/expression` 返回且仅返回六个字段：

- `assistant_message_id`
- `schema_version`
- `delivery`
- `intensity`
- `rate`
- `source`

查询依赖使用 SQLite `mode=ro` 与 `PRAGMA query_only=ON`。合法 assistant 消息返回持久计划；无计划、损坏或不兼容计划在内存中安全降级为 neutral，不写入新计划。缺失消息返回 404，非 assistant 消息返回 422，意外基础设施错误被固定 500 文案隔离。

### 精确播放生命周期

每次播放以 `(assistantMessageId, playbackRunId, generation)` 唯一绑定。新 run 在任何 speech fetch、scheduler、Blob URL 或 `audio.play()` 之前同步激活；拒绝激活时不启动异步工作。

播放器发出 `started / paused / resumed / stopped / interrupted / failed`。pause/resume 沿用同一 run，replay 分配新 run。fetch、stream event、scheduler enqueue/wait、HTML ended、`audio.play()`、pause/resume completion 都受当前 run 和 generation 保护。

本轮审计发现并修复了三个同一 run 内控制竞态：

- HTML streaming fallback 暂停期间的新 segment 不再把 UI 状态误改为 playing；
- 被更晚 pause 指令取代的旧 resume completion 不再发 `resumed`；
- 已切换到 HTML fallback 后，旧 scheduler pause rejection 不再错误终止有效 run。

### 表现 controller 与中性预览

表现 controller 维护 `Idle / Ready / Speaking / Paused` 状态：

- API 成功响应（包括服务端 default）可缓存；
- 网络、500 或解析失败产生的本地 neutral fallback 不缓存；
- replay/reselect/force reload 可重试；
- request generation、目标 message ID 和精确 playback run 拒绝迟到响应与 stale lifecycle；
- `dropSession` 只清理指定会话缓存。

浏览器预览仅使用 React 文本和中性 CSS 几何，不加载图片、远程资源、Live2D 或角色素材。它提供固定中文 delivery/phase 语义、`aria-live="polite"`、内存 display label、reduced-motion 样式和“这不是实际感情或意识”的明确说明。错误边界只包裹预览，聊天、录音与输入保持独立。

### App 与会话集成

文字发送和 voice turn 均使用后端返回的精确 `assistant_message_id`。text send、message load 和 voice turn 具有独立 generation，并同时校验活动 session。会话切换、删除、录音打断和卸载会终止播放并清理瞬时预览；display label 仅从已加载的内存消息派生。

## SQLite 不变量

新增 `scripts/verify_stage4e_e2e_database.py`，先复用 Stage 4D 不变量，再以只读连接拒绝以下运行时表现表：

- `speaking_events`
- `playback_runs`
- `expression_events`
- `animation_states`
- `preview_states`
- `expression_cache`

并拒绝 `expression_plans` 中的运行时/隐私字段：

- `display_label`
- `playback_run_id`
- `speaking_state`
- `prompt`
- `provider_payload`
- `asset_path`

Playwright teardown 顺序为 Stage 4C → 4D → 4E → DB/WAL/SHM best-effort cleanup，并保留 verifier 主要错误优先语义。

## 自动化验证

### Stage 4E 定向 Python

```text
36 passed in 1.45s
```

覆盖 expression API/service 与 Stage 4E verifier。

### 全部 Python 回归

```text
699 passed in 37.14s
```

命令范围为 `backend/tests` 与项目根 `tests`，使用项目根 `PYTHONPATH`。

### 前端

```text
Vitest: 26 files, 232 tests passed
TypeScript: tsc -b passed
Vite production build: passed（43 modules transformed）
```

Stage 4E Tasks 6–9 的定向回归为：

```text
5 files, 65 tests passed
```

### 浏览器 E2E

```text
11 passed in 17.6s
PASS: Stage 4C E2E analysis tables are metadata-only (jobs=1, audits=1, outcome=applied)
PASS: Stage 4D E2E expression plans satisfy persistence invariants
PASS: Stage 4E E2E database contains no persisted runtime presentation state
```

E2E 仅使用 fake LLM/TTS/ASR 与中性浏览器资源。新增表现测试验证：

- 精确 assistant ID 与单次初始 expression GET；
- 六字段 API 跨重复 GET 与 reload 稳定；
- Play → Pause → Continue → Stop 的 speaking 状态；
- 会话切换不残留 speaking；
- 首次 expression 500 显示本地 neutral；
- replay 重新 GET 并恢复后端持久表现；
- DB/WAL/SHM teardown 后无残留 E2E 数据库。

## 隔离运行时验证

在回环地址启动了唯一 SQLite 文件、fake LLM、fake session summary 和 fake TTS 的隔离后端，并通过 `httpx(..., trust_env=False)` 驱动：

```text
health: 200
create session: 201
chat: 200，获得精确 assistant_message_id
expression GET × 2: 200，完整响应相等且仅六字段
missing message expression: 404
user-message expression: 422
message-bound speech: 200
```

只读检查同一隔离 SQLite 文件确认：

- 存在对应 assistant message 与 ExpressionPlan；
- 不存在 Stage 4E 禁止的运行时表现表；
- `expression_plans` 不含禁止的运行时/隐私字段。

验证服务已停止；新建的隔离数据库及 sidecar 已清理。未接触用户或预先存在的数据库。

## 审查

独立 correctness/security 审查重点覆盖：

- expression GET 只读边界；
- 敏感信息与 runtime state 不持久化；
- playback run/control generation 竞态；
- activation 时序；
- local fallback 非缓存；
- App session generation 与清理；
- 局部错误边界；
- Stage 4E verifier、teardown 和 E2E。

审查结论：**未发现可复现的高或中严重度 correctness/security 问题。**

## 准确结论

Stage 4E 已在浏览器环境形成消息绑定、可恢复、失败隔离的表现闭环，并为后续 Windows 桌宠渲染器提供稳定输入契约。

不得据此声称已完成原生桌宠、Live2D、实时口型、全双工语音、真实声学表现质量或任何受保护角色资源集成。

## 工作树说明

项目仓库在 `AI桌宠/`，当前包含 Stage 3M–4E 的大量用户拥有未提交工作。本轮没有执行 reset、restore、checkout、clean、暂存或 commit，也没有覆盖或删除未知文件。最终 hygiene 以 `git diff --check` 和精确文件审查为准。
