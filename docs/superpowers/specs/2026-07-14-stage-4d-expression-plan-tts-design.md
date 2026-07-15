# Stage 4D ExpressionPlan / TTS 表达设计

> 日期：2026-07-14  
> 状态：已批准设计，待实施计划  
> 当前阶段：Stage 4 情感系统（4A、4B、4C 已完成）

## 1. 目标

Stage 4D 为每条已持久化的 assistant 消息生成一份受约束、可复现、供应商无关的 `ExpressionPlan`，让现有情感状态以安全、轻量、可降级的方式影响 TTS 表达。

本设计必须同时满足：

- ExpressionPlan 稳定绑定 assistant message，而不是临时绑定文本或当前 UI 状态。
- 同一条 assistant 消息的文字表达与语音表达使用同一份回复前情感快照。
- TTS 供应商只接收其明确支持的参数，供应商字段不进入领域模型或前端。
- ExpressionPlan、映射、合成或播放失败均不撤销、不隐藏、不修改已生成的文字回复。
- 情感系统关闭或任意表达能力不可用时，系统可确定性降级为当前默认 TTS 行为。

## 2. 范围与非目标

### 2.1 本次范围

- 版本化、供应商无关的 ExpressionPlan 领域模型。
- assistant message 级别的独立持久化和幂等读取。
- 回复前情感快照到受限 delivery/rate 的确定性映射。
- chat response 返回稳定的 `assistant_message_id`。
- message-bound non-streaming/streaming TTS 契约。
- provider capability 隔离和安全 mapper。
- fake/real TTS 分层验收与失败隔离。

### 2.2 非目标

- 不实现 Live2D、角色表情、动作事件或桌面壳。
- 不实现后台监听、持续唤醒或新的录音能力。
- 不引入通用 `turn_id`、消息图或事件总线。
- 不让 LLM 生成 ExpressionPlan。
- 不允许客户端提交任意 style、SSML 或供应商私有参数。
- 不宣称现有 CosyVoice 接口支持 pitch、energy、emotion 或任意 style。
- 不使用未授权角色素材或声音素材。
- 不建立持久音频缓存。

## 3. 已确认决策

1. **快照时点**：使用生成本轮文字回复之前读取的已提交情感快照。文字 expression context 与 TTS ExpressionPlan 同源；本轮 post-turn 情感更新只影响下一轮。
2. **持久化方式**：ExpressionPlan 使用独立表持久化，以 assistant message ID 和 schema version 唯一绑定；不塞入 `messages.metadata`，也不在播放时动态重算。
3. **首版表达维度**：采用受限 `delivery + rate`，并保留低风险 `intensity` 语义标签；真实 provider 首版只映射已明确支持的能力。
4. **消息标识**：chat response 返回 `assistant_message_id`；不为 Stage 4D 引入通用 turn ID。
5. **TTS 信任边界**：message-bound TTS 从服务端消息和 plan 读取文本与表达策略，客户端不能替换消息文本或提交计划。
6. **失败语义**：ExpressionPlan 是 assistant 消息落库后的 best-effort side effect。任何 plan/TTS 故障均不影响文字回复。

## 4. 总体架构与生命周期

```text
读取一次回复前已提交情感快照
        │
        ├── 格式化文本 expression context ──> LLM 生成文字
        │
        └── 生成受限 ExpressionPlanDraft
                                      │
assistant message 成功落库 ───────────┘
        │
        ├── best-effort 持久化 message-bound ExpressionPlan
        │     └── 失败：文字照常返回，播放时使用默认计划
        │
        └── 执行现有 post-turn 情感更新和 4C 调度
              └── 新状态只影响下一轮
```

### 4.1 同源快照

当前 `ContextBuilder` 会在构建 emotion context 时读取快照。实施时应把“读取快照”提升为本轮显式数据流，使文本 formatter 和 ExpressionPlan policy 接收同一个 `EmotionState` 实例，避免隐式二次读取、衰减时点变化或并发更新造成不一致。

快照读取失败时：

- 不注入 emotion context；
- 不创建个性化 ExpressionPlan；
- LLM 和文字聊天继续；
- message-bound TTS 后续使用默认计划。

### 4.2 assistant message 是计划归属键

只有 assistant 消息成功持久化后才能保存 ExpressionPlan。LLM 失败、空回复或 assistant 写入失败时不创建 plan。

ExpressionPlan 与 assistant message 的关系是稳定的一对一（每个 schema version 一份），同一消息跨页面刷新、历史回放和重复合成时都复用原计划，不随当前情感状态重算。

### 4.3 非阻塞 side effect

计划持久化应置于独立 `try/except` 边界，遵循现有 memory、summary、emotion post-turn side effect 的失败隔离方式。计划失败不得：

- 回滚 assistant message；
- 将 chat response 改为错误；
- 阻止本地 emotion update 或 4C 调度；
- 在前端隐藏文字回复。

## 5. 领域模型与持久化

### 5.1 ExpressionPlan

首版领域契约：

```text
ExpressionPlan
- id: UUID
- assistant_message_id: UUID
- schema_version: 1
- source_emotion_version: non-negative integer
- delivery: neutral | warm | reassuring | reserved | firm
- rate: float in [0.90, 1.10]
- intensity: low | medium
- created_at: UTC timestamp
```

语义：

- `delivery` 表达供应商无关的说话意图，不等于任一 provider 的 style 名称。
- `rate` 是 ExpressionPlan 的窄范围倍率，不能绕过 TTS 服务的全局速度限制。
- `intensity` 是受限语义提示，仅用于确定性 policy 和能力映射；首版不得自动转换为 pitch、energy 或 volume。
- `source_emotion_version` 用于复现和诊断计划来源，不要求保存完整情感向量。

ExpressionPlan 不保存：

- user/assistant 原文；
- 完整 emotion 浮点向量；
- memory、prompt 或远程分析 payload；
- API key、凭据或供应商请求/响应；
- 自由文本 style 或 SSML。

### 5.2 数据库约束

新增独立 `expression_plans` 表，至少包含：

- assistant message 外键；
- schema version；
- source emotion version；
- delivery、rate、intensity；
- 创建时间；
- `UNIQUE(assistant_message_id, schema_version)`；
- rate、version 和枚举值的数据库约束。

删除 session/messages 时应沿用消息生命周期删除关联 plan，不形成孤立记录。实现应遵守项目现有 SQLite 迁移和多连接测试约束。

### 5.3 幂等语义

`ExpressionPlanRepository.create(...)` 遇到唯一键冲突时，service 读取并返回已有计划，而不是覆盖或重新计算。已绑定计划不可因当前情感状态改变而静默更新。未来 schema 改版通过新的 `schema_version` 显式演进。

## 6. ExpressionPlanPolicy

`ExpressionPlanPolicy` 是纯函数、确定性、无网络访问的组件：

```text
EmotionState -> ExpressionPlanDraft | None
```

- `enabled=false` 返回 `None`，表示不创建个性化计划。
- 非 finite、越界或不满足 schema 的输入不得产生个性化计划。
- 输出必须再次经过领域校验和 clamp。
- policy 不读取消息正文、memory 或 provider capability。

### 6.1 delivery 映射

采用保守、可解释的优先级：

1. concern 高：`reassuring`
2. irritation 高且 formality 高：`firm`
3. trust 高且 distance 低：`warm`
4. distance 高或 formality 高：`reserved`
5. 其他：`neutral`

阈值应与现有离散情感 formatter 的低/中/高边界保持一致或由同一常量来源定义，避免文本和语音对同一快照采用冲突分档。

### 6.2 rate 与 intensity

首版 rate 使用少量固定档位，而不是连续放大：

- 关切、克制、严肃表达：略慢，例如 `0.94`；
- 中性表达：`1.00`；
- 温暖、轻松表达：最多略快，例如 `1.04`。

`intensity` 首版只允许 `low | medium`，不提供 `high`，防止单轮状态产生夸张表演。具体阈值和档位在实施计划中由表驱动测试锁定；所有值必须落在 `[0.90, 1.10]`。

## 7. 服务与组件边界

### 7.1 ExpressionPlanRepository

职责：

- 创建版本化 plan；
- 按 assistant message ID 和 schema version 读取；
- 依赖数据库唯一约束保证幂等；
- 不负责读取情感状态、构造 provider 参数或合成语音。

### 7.2 ExpressionPlanService

职责：

- 接收已持久化的 assistant message 和已读取的回复前 emotion snapshot；
- 验证 message role；
- 调用 policy 生成 draft；
- 持久化并处理幂等冲突；
- 暴露读取计划和安全默认解析能力。

该服务不调用 LLM 或 TTS provider。

### 7.3 ChatService / ContextBuilder

实施时调整为显式共享快照：

1. `ChatService` 在 provider 调用前读取一次情感快照；
2. `ContextBuilder`/formatter 使用调用方提供的 snapshot 构建 emotion context；
3. assistant message 落库后，`ChatService` best-effort 调用 ExpressionPlanService；
4. 随后执行现有 post-turn emotion update；
5. `ChatReply` 和 `ChatResponse` 增加 `assistant_message_id`。

不得让计划创建失败改变现有聊天成功语义。

### 7.4 MessageBoundTTSService

新增应用层编排组件，而不是把数据库查询放入 provider：

1. 按 message ID 读取并验证 assistant message；
2. 读取兼容 schema 的 ExpressionPlan；
3. 缺失、损坏或版本不兼容时使用默认 plan；
4. 组合用户显式 speed 偏好与 plan rate；
5. clamp 到 TTS 全局安全范围；
6. 交给 capability mapper 和现有 `TTSService`；
7. streaming/non-streaming 共享相同解析和映射逻辑。

## 8. API 契约与前端绑定

### 8.1 Chat response

现有 chat response 增加：

```json
{
  "reply": "...",
  "metadata": {"provider": "...", "model": "..."},
  "assistant_message_id": "uuid"
}
```

前端 voice turn 使用该 ID 直接关联音频状态。现有基于 before/after message 差集和 transcript 内容的启发式匹配不再作为主要正确性路径；可以在兼容旧响应期间暂时保留明确的降级分支，之后由测试确认是否移除。

### 8.2 Message-bound TTS

新增：

```http
POST /api/messages/{assistant_message_id}/speech
POST /api/messages/{assistant_message_id}/speech/stream
Content-Type: application/json

{
  "voice_id": "default",
  "speed": 1.0
}
```

约束：

- 服务端从持久化 assistant message 获取 TTS 文本；
- 客户端不能在此 API 中提交或覆盖 text、delivery、intensity、style、SSML 或 provider options；
- message 不存在或 role 不是 assistant 时返回明确的客户端错误；
- plan 缺失不是错误，使用默认计划；
- TTS timeout、provider error 和 invalid audio 沿用现有错误映射；
- response header/stream metadata 可暴露最终 provider/model/rate 等非敏感诊断信息，但不暴露完整情感状态或 provider payload。

现有 `/api/audio/speech` 与 `/api/audio/speech/stream` 保持兼容，继续服务裸文本、非消息绑定用例，并且不自动应用情感计划。

### 8.3 用户 speed 组合

message-bound TTS 的最终 speed：

```text
final_speed = clamp(plan.rate * user_speed, global_min_speed, global_max_speed)
```

- 未提供用户 speed 时使用 `1.0`；
- 用户 speed 仍必须先通过现有 finite 和范围校验；
- 默认 plan 的 `rate=1.0`；
- provider mapper 只能看到经过验证的最终值。

## 9. Provider 隔离与能力映射

### 9.1 标准化内部请求

应用层可构造供应商无关的受控请求：

```text
TTSExpressionRequest
- text
- voice_id
- rate
- delivery
- intensity
```

该对象是内部契约，不允许包含任意字典形式的 vendor options。

### 9.2 capability 边界

provider 或其 mapper 明确声明/实现所支持的最小能力。规则：

- 不支持某维度时忽略该维度，不报错；
- mapper 不得猜测供应商字段；
- 不发送未由真实接口测试确认的字段；
- provider 不读取数据库、消息、情感状态或 ExpressionPlan repository；
- 供应商特有转换只存在于该供应商 adapter/mapper 内。

### 9.3 首版 provider 行为

**Fake TTS**

- 确定性接受最终 rate；
- 可通过测试 double、结果 metadata 或可观测请求对象证明 delivery 被安全接受或忽略；
- 不以音高 hash 或波形差异宣称真实情感质量。

**CosyVoice HTTP**

- 首版只映射当前接口已确认支持的 `speed`；
- `delivery` 和 `intensity` 被安全忽略；
- payload 不新增未经真实 API 契约确认的 style、pitch、energy 或 emotion 字段；
- 若未来确认能力，应在该 adapter 内新增显式映射及真实 smoke 证据，不改变领域 plan。

## 10. 数据流与降级矩阵

### 10.1 聊天路径

1. 校验并持久化 user message。
2. 读取一次回复前情感快照；失败视为无个性化快照。
3. 使用同一快照构造文本 emotion context 和 ExpressionPlanDraft。
4. 调用 LLM。
5. 持久化 assistant message。
6. best-effort 创建 message-bound ExpressionPlan。
7. 执行现有本地 emotion update 和 4C 调度。
8. 返回文字和 `assistant_message_id`。

### 10.2 播放路径

1. 前端提交 assistant message ID 和受限播放偏好。
2. 后端读取并验证已持久化消息。
3. 后端读取兼容 plan；不可用时使用默认计划。
4. mapper 只保留 provider 已支持能力。
5. TTSService 执行现有输入与输出校验。
6. provider 合成失败只作为该播放请求失败。
7. 前端保留文字，显示消息级音频错误并允许重试。

### 10.3 降级矩阵

| 故障或状态 | 行为 |
|---|---|
| 回复前情感读取失败 | 继续文字生成；不创建个性化 plan |
| 情感系统关闭 | 不注入 emotion context；TTS 使用默认计划 |
| plan 生成或写入失败 | 文字回复成功；播放时默认语音 |
| plan 缺失、损坏或 schema 不兼容 | 默认计划；不动态猜测或重算 |
| provider 不支持 delivery/intensity | 忽略不支持维度；继续使用已支持 rate/voice |
| provider 拒绝已确认参数 | 按普通 TTS provider failure 处理 |
| TTS timeout/error/空音频 | 文字不受影响；显示单消息播放错误，可重试 |
| 前端切换 session 或开始录音 | 沿用现有 reset/stop，释放 Object URL，不串播 |
| 重复请求同一消息 | 复用原 plan；每次合成可独立成功或失败 |

## 11. 隐私与安全

- 情感仅是系统状态和表达策略，不描述为真实感受或意识。
- ExpressionPlan 不能覆盖安全、事实准确性、文本内容或用户明确指令。
- TTS 输入必须来自持久化 assistant message；message-bound API 不信任客户端自报文本。
- plan、日志和审计不记录原始聊天、prompt、memory、完整 emotion vector 或供应商 payload。
- 不允许自由文本 style、SSML 和任意 provider options 穿过公共 API。
- 错误响应不泄漏 traceback、密钥、内部 URL 或供应商原始错误正文。
- 真实 provider 继续由显式环境配置启用，默认 fake-first。

## 12. 测试与验收

### 12.1 Policy 单元测试

- 相同 snapshot 得到相同 plan。
- delivery 优先级和 rate 档位由表驱动测试固定。
- enabled=false、非法/non-finite 输入得到无个性化计划或默认行为。
- rate、intensity 和枚举严格受限。
- plan 不含原文、完整向量、memory 或 vendor options。

### 12.2 Repository / Service 测试

- 每个 assistant message 和 schema version 至多一份 plan。
- 重复创建返回已有 plan，不覆盖。
- user message、未知 message ID 被拒绝。
- session/message 删除不会留下孤立 plan。
- 不兼容 schema 安全退化。
- plan 创建失败不改变已持久化 assistant message。

### 12.3 Chat/API 集成测试

- chat 成功返回稳定 `assistant_message_id`。
- 文本 emotion context 与 plan 使用同一 snapshot/version。
- LLM 或 assistant 写入失败时不创建 plan。
- plan 创建失败仍返回并保留 assistant 文字。
- message-bound TTS 只读取持久化 assistant 文本。
- 客户端不能注入 text、delivery 或 provider options。
- plan 缺失/损坏、情感关闭、provider 不支持时仍可默认合成。
- streaming 与 non-streaming 共享相同计划解析、speed 和降级语义。
- 现有裸文本 TTS API 保持兼容。

### 12.4 Provider mapper 测试

- `plan.rate * user_speed` 的顺序、finite 校验和 clamp 正确。
- Fake 路径可确定性观测消息绑定和参数映射。
- CosyVoice payload 只包含已确认的字段。
- unsupported delivery/intensity 不导致请求失败，也不泄漏成未知字段。
- timeout/error/invalid audio 沿用当前 502/504 语义。

### 12.5 前端和 E2E

- voice turn 直接使用 chat response 的 assistant message ID。
- 重复 transcript、并发新增消息不会串绑。
- 历史消息重播仍使用原 plan。
- TTS 失败时文字保持可见，错误只属于对应消息并可重试。
- streaming/non-streaming、stop/replay、session switch、录音打断和 Object URL 清理维持现有行为。

### 12.6 Fake / Real 验收边界

**Fake TTS：强制自动验收**

证明：

- message ID 与计划绑定正确；
- rate 组合和 clamp 正确；
- unsupported capability 安全降级；
- streaming/non-streaming 一致；
- plan/TTS 失败不影响文字回复。

**Real CosyVoice：显式 opt-in smoke**

证明：

- 已支持的 `speed` 正确发送；
- 可返回可播放 WAV/stream；
- 未验证的 style/pitch/energy/emotion 字段未发送；
- provider 故障只影响语音请求。

不得仅凭波形 hash、单次请求成功或主观试听宣称“情感声音质量达标”。未来若要验收 delivery 的声学效果，应另立包含明确 provider 能力、授权声音素材和听测标准的任务。

## 13. 兼容性与实施约束

- 保留现有裸文本 TTS API。
- message-bound TTS 复用现有 `TTSService` 校验和错误映射，不复制 provider 调用逻辑。
- 前端继续以 message ID 作为 audio entry key，复用现有播放控制器与资源清理机制。
- 不进行与 Stage 4D 无关的消息、记忆、摘要或 4C 重构。
- 当前工作区包含大量未提交的 Stage 3/4A–4C 改动；实施与提交必须只选择 Stage 4D 相关文件，避免覆盖或混入既有用户改动。

## 14. 完成标准

Stage 4D 实施只有在以下条件均满足时才可声明完成：

1. 每条新 assistant 消息可稳定绑定一份版本化 ExpressionPlan，或在 plan side effect 失败时明确降级。
2. 文本 expression context 与 plan 使用同一回复前快照。
3. chat response 提供稳定 assistant message ID，语音主路径不再依赖 transcript 启发式匹配。
4. message-bound TTS 的文本与计划均由服务端读取，客户端无法注入供应商表达参数。
5. fake provider 自动测试覆盖映射、绑定、streaming 和失败隔离。
6. CosyVoice 只接收已验证支持的字段，真实 smoke 为 opt-in 且不夸大声学效果。
7. 任意 plan、provider、合成或播放失败均不影响已生成文字回复。
8. 后端相关测试、前端 Vitest、必要 Playwright E2E 和项目级 runtime verify 全部通过；若 real TTS 未配置，必须明确记录为未运行而非通过。
