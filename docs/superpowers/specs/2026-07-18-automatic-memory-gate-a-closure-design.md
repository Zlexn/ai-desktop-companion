# 自动长期记忆与角色一致性增强：Gate A 收尾设计

> 日期：2026-07-18  
> 状态：用户已逐节批准设计，等待书面规格复核  
> 所属项目：本地虚拟角色交互系统  
> 当前阶段：阶段 1–4 已关闭后的独立增强闭环——Gate A

## 1. 背景与决策

项目已完成并验收文字角色聊天、语音、长期记忆和受约束的情感表现。当前工作树存在尚未完成、尚未提交的 Gate A 实现：已经具备兼容 schema、本地 Memory Governor、抽取器、metadata-only repository、dispatch fence 与 job service；尚缺 `MemoryJobScheduler`、聊天互斥模式路由、scheduler 依赖注入、API 可观测性、FastAPI lifespan 组合和完整验收。

用户的最终目标是本地部署一个可实时交流、具有情感表现和长期记忆的雪之下雪乃桌宠。用户允许聊天上下文发送给云端 LLM API；用户将自行从视频和图片制作仅在本机使用的形象与声音参考素材，项目不内置或分发这些素材。第一版视觉方案采用分层图片状态机，语音入口采用点击桌宠或快捷键开始、VAD 自动停止并允许打断播放。上述桌面呈现与真实音色接入均排在自动记忆增强 Gate A–C 之后。

本设计选择沿用现有 FastAPI、React、SQLite、Electron tooling、ASR/TTS 和 Provider 抽象，不迁移到新的全本地一体化栈。llama.cpp、Ollama 和 whisper.cpp 保留为未来可选本地 Provider，不作为当前重构理由。

## 2. 本阶段目标

完成“自动长期记忆与角色一致性增强——Gate A”的最小完整闭环：

1. 成功聊天后，根据互斥模式选择关闭、现有候选确认或 shadow 自动抽取。
2. `shadow_auto` 通过后台 scheduler 非阻塞执行。
3. 本地 Governor 在抽取前后实施删除意图、敏感信息、预算和规范化约束。
4. 远程抽取使用独立、持久、明确、可撤回的 consent，并在发送前和回包后双重检查。
5. 任务和审计只保存元数据，通过 API 可诊断。
6. 应用启动将 `running` 原子恢复为 `pending` 并按确定顺序重排 pending job；关闭可按规定顺序停止 scheduler、终结或取消任务并释放 Provider。
7. 结构上和测试上证明 Gate A 不创建、修改或删除 active memory。

## 3. 范围边界

### 3.1 范围内

- 兼容性增量 schema 与迁移验证。
- `off | candidate_confirmation | shadow_auto` 互斥运行模式。
- 对未知模式及 `auto_active` 的 fail-closed 配置拒绝。
- `none | local | fake | remote` extractor route。
- 本地 Governor 的确定性预检查与后检查。
- 每轮一个幂等 shadow job。
- 后台 scheduler 的调度、拥有、启动恢复与关闭。
- 远程抽取独立 consent 及 generation fence。
- metadata-only job/audit 持久化。
- consent mutation、job list 和 audit list API。
- 聊天 Provider 与远程抽取 Provider 的 lifespan 管理。
- 与改动直接相关的测试、HTTP smoke、隐私检查和验收文档。

### 3.2 范围外

- 自动创建、修改、合并、归档或删除 active memory。
- Gate B 的 Evidence、版本链、冲突状态机、tombstone 和防复活。
- Gate C 的摘要受控注入、Persona artifact、关系事件账本/投影及 UI。
- 前端 Gate A 状态 UI。
- Electron 主进程、preload、透明悬浮窗、托盘与 IPC。
- 分层图片素材导入、动画、口型或 Live2D。
- 真实声音参考导入、声音克隆模型打包或对外分发。
- ASR/TTS 架构迁移、持续监听或唤醒词。
- llama.cpp、Ollama、whisper.cpp 或 vLLM 的迁移。

## 4. 架构

### 4.1 聊天与自动记忆的隔离

`ChatService` 必须先完成助手回复持久化。表达计划、会话摘要、情感更新与自动记忆均保持 best-effort；自动记忆失败不得回滚已保存的文字回复，也不得把异常传播为聊天失败。

记忆路径只能选择一个分支：

```python
if mode == "off":
    pass
elif mode == "candidate_confirmation":
    create_pending_candidates()
elif mode == "shadow_auto":
    scheduler.schedule(...)
```

配置加载阶段拒绝未知模式与 `auto_active`，不得静默降级或并行执行两条路径。

### 4.2 Shadow 数据流

```text
ChatService（已保存 assistant message）
  → 互斥模式路由
  → MemoryJobScheduler（非阻塞）
  → 本地 Governor 预检查
  → Extractor（local / fake / remote）
  → 本地 Governor 后检查
  → metadata-only Job + Audit
```

Gate A 的 scheduler、dispatch fence 与 job service 不注入 active `MemoryRepository`。这一能力隔离与数据库前后对比测试共同证明 shadow 路径不能写正式记忆。

## 5. 组件设计

### 5.1 `MemoryJobScheduler`

职责：

- 接收已持久化的 user/assistant message 标识符；`turn_id` 固定为 `assistant_message.id`。
- 使用 `(turn_id, schema_version)` 建立或复用幂等任务；schema version 固定为 `memory-shadow-schema-v1`，数据库以 `UNIQUE(turn_id, schema_version)` 强制约束。
- 用受控后台 task 执行 `MemoryJobService`，调度后立即返回。
- 避免并发重复调度产生重复 job；同一进程内每个 job 最多一个执行者。
- 应用启动时将 `running` 原子恢复为 `pending`，按 `created_at, id` 顺序重新入队所有 pending job；不得新建幂等记录或重跑终态 job。
- 关闭时停止接收新任务并等待已有任务完成；显式取消时以唯一的 `CANCELLED/cancelled` terminal audit 结束。
- 捕获异常并转成可诊断任务状态，不向聊天请求传播。Gate A 的 Provider `max_retries` 固定为 `0`；若进程在 remote send 后、terminal commit 前崩溃，恢复后允许再次发送一次，因为没有供应商请求幂等键，但数据库仍只能保留一个 job 和一个 terminal audit。

scheduler 不决定记忆价值，不保存 proposal，不访问 active memory。

### 5.2 `MemoryJobService`

job status 与 audit outcome 分离：

```text
pending → running → succeeded | failed | cancelled
             └────→ pending（仅限启动恢复）
```

- `succeeded` 的 audit outcome 可为 `shadow_recorded`、`skipped_no_extractor`、`skipped_no_consent`、`skipped_consent_changed` 或 `skipped_governor_policy`。
- `failed` 的 audit outcome 可为 `invalid_output`、`provider_error` 或 `failed`。
- `cancelled` 只对应 `cancelled` outcome。

每个终态均以原子事务写入 job 与唯一 terminal audit；终态不可变。重复执行或恢复复用原幂等任务，不能产生第二次 terminal audit。失败只记录固定的安全原因码、计数与时间，不记录正文、prompt、proposal、异常文本或原始响应。

### 5.3 `MemoryExtractionDispatchFence`

远程抽取流程：

1. 确认当前 route 为 `remote`。
2. 读取并验证当前 consent generation。
3. 只披露当前 user/assistant 两条消息及严格所需字段。
4. 调用远程 extractor。
5. 回包后再次读取 consent generation。
6. 若授权已撤回、generation 改变或能力已关闭，丢弃结果并写入安全原因码。
7. 不保存 prompt、原始响应或抽取正文。

聊天 LLM API 的使用许可与远程记忆抽取授权相互独立；前者不能隐式开启后者。

### 5.4 `MemoryGovernor`

Governor 是纯本地、确定性、可单元测试的策略组件：

- 抽取前拒绝“不要记住”、删除意图和明显敏感内容。
- 敏感内容至少覆盖密码、API key、验证码、私钥、支付凭据和身份凭据。
- 抽取后执行规范化、canonical hash、数量预算与字符预算。
- Gate A 的去重仅限当前 extractor 回包内的 transient proposal：按规范化 canonical hash 保留首次出现项并维持原顺序；不查询 active memory，也不进行跨轮重复或冲突判断。跨轮去重与冲突处理属于 Gate B。
- 输出结构化决定、原因码和安全计数。
- Gate A 中即使判定为可创建，也只计数和审计，不写 active memory。

### 5.5 Extractor

route 语义：

- `none`：不调用 extractor，任务以 `SUCCEEDED/skipped_no_extractor` 结束。
- `local`：确定性本地规则抽取，不读取 remote consent。
- `fake`：测试用可控实现，不读取 remote consent。
- `remote`：通过命名 Provider adapter 和 dispatch fence 调用；仅在对应凭据已配置时创建 Provider。

所有实现遵循统一严格 schema。不从 Markdown 中宽松恢复 JSON，不把供应商 SDK 调用散布到业务层，不记录原始响应。

### 5.6 冻结版本、授权身份与预算

Gate A 冻结以下值，实施不得自行漂移：

| 项目 | 固定值或范围 |
|---|---|
| 默认 automation mode | `candidate_confirmation`；允许 `off | candidate_confirmation | shadow_auto`，`auto_active` 永远拒绝 |
| 默认 extractor route | `none`；允许 `none | local | fake | remote` |
| remote provider | `anthropic | deepseek`，默认 `anthropic` |
| extraction schema | `memory-shadow-schema-v1` |
| Governor rules | `memory-governor-rules-v1` |
| disclosure version | `memory-extraction-disclosure-v1` |
| purpose | `extract durable memory proposals from the current completed turn` |
| disclosed fields | 精确有序元组 `("user_message", "assistant_message")` |
| max tokens | 默认 512，范围 64–2048 |
| timeout | 默认 15.0 秒，范围 1.0–60.0 |
| max retries | 固定 0 |
| max proposals | 默认 3，范围 1–10 |
| max proposal characters | 默认 200，范围 20–500 |
| max total characters | 默认 600，范围 20–2000，且不小于单条上限 |

remote grant 必须同时精确匹配 status=`granted`、purpose、当前 provider、disclosure version 和有序 disclosed fields；部署配置或聊天 API 授权不能替代这一 grant。

## 6. API 与数据契约

新增或补齐：

```http
GET /api/memories/extraction/consent
PUT /api/memories/extraction/consent
GET /api/memories/jobs
GET /api/memories/jobs/audits
```

要求：

- consent mutation 使用严格 schema，并更新 generation。
- 撤回授权即时生效；在途结果受回包后二次检查约束。
- job/audit 仅返回标识符、状态、route、schema version、安全计数、原因码和时间。
- job/audit list 的 `limit` 默认 20、最小 1、最大 100，并使用稳定排序；禁止无界读取。
- 响应不包含对话正文、proposal、prompt、供应商原始响应、密钥或授权令牌。
- Gate A 不提供批准 shadow proposal、手动重放正文或自动写 active memory 的接口。

数据库采用 additive schema，升级不破坏现有会话、消息、候选、active memory、摘要或情感数据。

## 7. 错误处理

- 聊天 LLM 失败：沿用现有错误行为，不创建 shadow job。
- 任务重复调度：返回已有幂等任务，不重复执行或持久化。
- 敏感信息/删除意图：远程调用前跳过。
- route=`none`：零 extractor/Provider 调用，`SUCCEEDED/skipped_no_extractor`。
- route=`local|fake`：不读取 remote consent；按本地结果形成 `SUCCEEDED/shadow_recorded` 或对应 Governor outcome。
- route=`remote` 且 Provider 因凭据缺失未创建：不发送，`SUCCEEDED/skipped_no_extractor`；缺少凭据不阻止应用启动。
- route=`remote`、Provider 已就绪但 grant 为 unknown/declined/revoked，或 purpose/provider/disclosure version/disclosed fields 任一不精确匹配：Provider 调用次数为零，`SUCCEEDED/skipped_no_consent`。
- route=`remote`、初始 grant 匹配，但排队发送前或请求在途期间授权发生 mutation/generation 变化：发送前变化保持零调用；在途变化允许已经发生一次调用，但丢弃返回值，均以 `SUCCEEDED/skipped_consent_changed`（若首次 authority 检查已失效则可为 `skipped_no_consent`）结束。
- extractor JSON/schema 无效：任务进入 `FAILED/invalid_output`，仅保存固定安全原因码。
- Provider 超时或断网：任务进入 `FAILED/provider_error`，不自动改走另一个远程 Provider。
- job/audit 数据库写入失败：回滚该状态转换，不影响已保存聊天回复。
- 启动恢复：把 `running` 原子回置 `pending`，随后按确定顺序重新入队所有 pending job；不得新建幂等 row、增加 attempt count 或重跑终态 job。
- 关闭：停止接收新任务并默认等待在途任务；显式取消写入唯一 `CANCELLED/cancelled` terminal audit。迟到结果不得覆盖终态。

## 8. 生命周期与配置

聊天 Provider 与远程 extractor Provider 在 FastAPI lifespan 中创建和共享，不再为每个请求临时创建无法统一关闭的网络客户端。

关闭顺序：

```text
memory scheduler
→ emotion-analysis scheduler
→ summary scheduler
→ memory extractor provider
→ existing emotion-analysis provider and summary provider
→ chat provider
→ database resource（按现有 lifespan ownership）
```

每个资源只关闭一次。`none/local/fake` route 不创建不必要的远程客户端。

配置策略：

- 默认模式保持 `candidate_confirmation`，避免升级后行为突变。
- `shadow_auto` 必须显式启用。
- `auto_active` 在 Gate A 永远非法。
- `.env.example` 仅包含变量名、注释和安全默认值。
- 回滚使用 `candidate_confirmation` 或 `off`；新增表保留，不做破坏性降级。

## 9. 测试与验证

### 9.1 单元测试

- 三种模式互斥。
- 未知模式和 `auto_active` fail closed。
- scheduler 幂等、并发重复、恢复与关闭。
- Governor 删除意图与敏感信息预过滤，以及仅限当前回包的稳定顺序 transient 去重。
- extractor 严格 schema、冻结版本、预算、数量与规范化。
- consent generation 的发送前/回包后检查，以及 purpose/provider/version/有序 fields 的精确匹配。
- job/audit 原子终态写入、唯一 terminal audit、`running → pending` 恢复与 `CANCELLED/cancelled` 关闭语义。
- metadata-only schema 无正文和原始响应字段。

### 9.2 服务/API 集成测试

- 默认 `candidate_confirmation` 行为不回归。
- `off` 不创建候选或 job。
- `shadow_auto` 不创建 pending candidate。
- 聊天快速返回，后台任务独立完成。
- 后台失败不影响已保存 assistant message。
- remote Provider 已就绪但 consent 未精确匹配时，调用次数为零；remote 凭据缺失时明确产生 `skipped_no_extractor`。
- consent/job/audit API 的严格输入、安全输出、分页与排序。
- lifespan 只创建并关闭一次共享 Provider。

### 9.3 完整回归与运行时验证

1. 运行 Gate A 针对性后端测试。
2. 运行完整后端测试集，确认阶段 1–4 无回归。
3. 启动真实 FastAPI 应用执行 HTTP smoke。
4. 比较 `shadow_auto` 前后 active `memories` 表，变化数必须为零。
5. 分别验证 remote Provider 已配置但未授权时零调用，以及未配置凭据时 `skipped_no_extractor` 且应用可启动。
6. 检查 job/audit/API/日志不包含正文、proposal、prompt、raw response 或密钥。
7. 验证 scheduler 和 job service 的依赖图不存在 active `MemoryRepository`。
8. 执行代码简化、独立代码审查与端到端验证。
9. 运行 `git diff --check`。
10. 更新验收文档，记录实际命令、结果和未验证范围。

Gate A 不修改前端，因此前端测试默认不作为阻塞项；若实现意外影响前端接口契约，则运行相关 Vitest、TypeScript 类型检查和构建。

## 10. 通过条件

只有以下条件全部满足，Gate A 才可标记完成并建议 Gate B：

- 所有针对性测试和完整后端回归通过。
- shadow mode 对 active memory 的变更数为零。
- remote Provider 已就绪但授权未精确匹配时调用数为零；无凭据时得到 `skipped_no_extractor`，不伪装为语义成功。
- job/audit/API/日志无正文或秘密泄露。
- 幂等调度、启动恢复与关闭过程有实际证据。
- 聊天响应不被后台抽取阻塞。
- Provider 生命周期由 lifespan 统一管理且每个资源只关闭一次。
- 独立代码审查没有未解决的高严重度问题。
- 验收文档记录实际验证结果，不把未执行项写成通过。

任何测试失败或证据不足时，Gate A 保持未完成并继续修复，不自动进入 Gate B。

## 11. 后续顺序

Gate A 通过并获得继续授权后，下一独立设计/计划为 Gate B；Gate B 通过后才进入 Gate C。Gate C 验收后，再按已批准的 Electron 双窗口桌面壳设计推进。第一版桌面形象使用用户选择的分层图片状态机；用户本地素材不进入 Git、测试快照或发行包。真实参考音频仅由用户本机导入，项目不内置、不上传、不公开分发，并在桌面壳和视觉闭环后作为独立切片验证。
