# Stage 4A Local Emotion State Foundation

Status: VERIFIED PASS on 2026-07-13.

## Scope

Stage 4A 建立本地、确定性、跨会话全局的六维情感表达状态基础。它不调用远程情感 LLM、不注入聊天 Prompt、不改变 TTS，也不实现桌面壳或角色素材。

## Data Model

- 独立 `emotion_states` 表保存一个 `default-companion` 当前快照。
- 独立 `emotion_events` 表追加 transition/decay/settings/reset 审计事件。
- 六维范围均由 SQLite CHECK 与本地 policy 约束在 `0–1`。
- 状态使用递增 `version`，与 messages/memories/session_summaries 分离。

基线：mood 0.50、trust 0.40、concern 0.20、distance 0.55、irritation 0.10、formality 0.60。

## Local Policy and Bounds

本地规则只识别明确感谢/尊重、道歉、边界、敌意和求助信号。普通文本和“把 trust 设置为 1”一类数值指令为 neutral，不直接修改状态。每维变化应用固定单轮上限和全局界限；非有限值被拒绝。

## Decay

衰减根据 `updated_at` 和读取时刻计算，无常驻 timer。少于一小时不衰减；临时维度较快、trust/distance 极慢地向基线移动，且不会越过基线。实际变化记录 `time_decay` 事件。

## Concurrency and Audit

repository 使用 `WHERE version = expected_version` compare-and-swap，在同一事务中更新状态并追加事件；冲突回滚，service 最多重算三次。event 只保存结构化向量、reason codes、规则版本和来源消息 ID，不保存 Prompt 或 Provider payload。

## API and UI

API：

- `GET /api/emotion/state`
- `GET /api/emotion/events?limit=...`
- `PATCH /api/emotion/settings`
- `POST /api/emotion/reset`

settings 使用 `extra=forbid`，不能任意 PATCH trust 等数值。前端新增 `EmotionPanel`，显示六维数值、解释、版本、更新时间、开关、重置确认和最近原因，并明确文案为表达策略而非真实感情。

## Chat Failure Isolation

assistant 消息成功持久化后，Stage 4A 通过独立 fresh SQLite connection 执行本地 bounded update。任何 emotion updater 异常被隔离，不会丢失成功回复。Provider payload、ChatResponse、Prompt、TTS 均未加入情感内容。

## Automated Validation

2026-07-13 新鲜结果：

```text
Stage 4A focused backend: 62 passed in 2.67s
Full backend: 430 passed in 18.74s
Frontend Vitest: 19 files, 165 tests passed in 9.92s
TypeScript typecheck: PASS
Vite build: 37 modules transformed, built in 116ms
Focused emotion Playwright E2E: 1 passed in 5.3s
Complete Playwright E2E: 8 passed in 11.1s
```

既有 chat、memory、voice recorder 和 fake voice-turn E2E 以及新增 Stage 4A 专项浏览器用例全部通过。专项用例覆盖六维状态展示、跨会话连续、刷新持久化、关闭后停止更新、重新启用、重置与审计原因；Playwright test mode 显式启用 emotion resource load。

## Runtime Verification

使用唯一 SQLite `verify-stage4a-20260713-1340.db`、fake LLM/summary provider、端口 18164、`httpx trust_env=False`：

- health 200；
- 初始 state version 0，六维等于基线；
- 会话 A 的明确感谢 turn 后 version 1、trust 0.40 → 0.43；
- 新建会话 B 读取同一全局 state；
- disable 生成 version 2，随后敌意 turn 不改变 version/vector；
- enable 后 reset，version 4，精确恢复基线；
- 任意 trust PATCH 和 event limit 0 均为 422；
- SQLite：1 emotion state、4 emotion events、4 messages、0 memories、0 summaries，数据边界独立；
- 服务停止，任务创建的数据库已删除。

## Security and Privacy

- Stage 4A 零远程情感分析，无 consent 或隐式外发。
- 不保存原始分析 Prompt/response。
- 情感状态不伪装成长期记忆或聊天消息。
- 不宣称角色具有意识或真实感情。
- 不引入角色立绘、Live2D、台词或声线素材。

## Limitations

Stage 4A 尚未实现：聊天 Prompt 表达注入、LLM 辅助情感分析与 consent、ExpressionPlan、TTS 情感映射，以及超出 Stage 4A 的完整 Stage 4/桌面表情事件验收。当前规则词表刻意保守，不是通用中文情感分类器。

## Decision

Stage 4A local emotion state foundation: PASS. Stage 4 remains IMPLEMENTING.

## Next Minimal Task

Stage 4B 文本表达闭环设计与实现：把已提交状态格式化为短小、受预算保护且不能覆盖安全/事实/用户指令的 expression context；当前快照影响当前回复，成功 turn 更新下一轮。该切片不实现远程 LLM 情感分析、TTS ExpressionPlan 或桌面角色资源。
