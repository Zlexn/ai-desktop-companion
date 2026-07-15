# Stage 4E 消息绑定表现协议与浏览器语义预览设计

> 日期：2026-07-14  
> 状态：设计与文件级复核已获用户批准，可进入实施  
> 项目根：`AI桌宠/`  
> 当前阶段：阶段 4——情感系统（4A–4D 已完成）

## 1. 背景

阶段 4A 已建立本地、可解释、有界、可衰减并可由用户关闭或重置的情感状态；4B 已让已提交的情感快照影响文字表达；4C 已提供默认关闭、需明确授权的远程 LLM 辅助情感分析；4D 已使用回复前的同一情感快照，为已持久化 assistant 消息生成不可变、版本化的 `ExpressionPlan`，并让 message-bound TTS 只映射供应商已确认支持的语速参数。

目前仍缺少一条可观察的视觉表现闭环：后端已经持有消息绑定的表达计划，但前端和未来桌宠渲染层没有稳定的只读查询契约、版本化表现事件或可验证的消费者。若现在直接实现 Tauri/Electron、Live2D 或实时网络事件总线，会把尚未稳定的表现边界与具体桌面框架或资源格式绑定，增加返工风险。

Stage 4E 先建立与渲染技术无关的最小闭环：

```text
持久化 assistant 消息
→ 不可变 ExpressionPlan
→ 消息绑定的只读表达 API
→ 前端版本化 expression 事件
→ 播放器 speaking 生命周期
→ 中性占位角色预览
```

这一步完成后，浏览器环境可验证“同一消息获得同一表达结果”，并为后续 Windows 桌宠层提供稳定输入协议。

## 2. 目标与成功标准

### 2.1 目标

1. 让合法 assistant 消息对应的表达结果可通过独立、只读 API 获取。
2. 让历史无计划消息、缺失计划、损坏计划或不兼容计划安全降级为 neutral，而不影响聊天。
3. 定义版本化的前端 `expression` 与 `speaking` 事件契约。
4. 增加只消费表现事件的中性占位角色预览，用于验证表达与播放生命周期。
5. 保证消息、表达和每次播放实例始终由 `assistant_message_id + playback_run_id` 绑定，避免同一消息快速重播、异步迟到或刷新导致状态漂移。
6. 通过单元、集成、浏览器 E2E、数据库不变量和运行时验证证明失败隔离与可恢复性。

### 2.2 完成后的准确表述

Stage 4E 完成后可以声称：

> 浏览器环境已经形成消息绑定、可恢复、失败隔离的情感表现闭环，并为后续 Windows 桌宠渲染器提供稳定契约。

不得声称：

- 已完成原生 Windows 桌宠；
- 已完成 Live2D、动画引擎或实时口型；
- 已实现全双工语音或自动 spoken barge-in；
- 已集成或分发雪之下雪乃的授权形象、模型、台词或声音；
- `delivery` 或 `intensity` 已被真实 TTS 以可辨识声学效果表达。

## 3. 已确认的产品与工程决策

### 3.1 实时交流边界

最终目标仍是实时或接近实时交流。本阶段沿用已经完成并验证的稳定半双工路径：用户完成一轮输入后，系统识别、回复并朗读；用户可显式打断播放。持续监听、自动开口打断和全双工交互另立后续专项，不属于 Stage 4E。

### 3.2 本地部署定义

采用混合本地架构：应用、SQLite 数据、长期记忆、情感状态、配置、审计、可选 ASR/TTS 和未来角色渲染均在本机；主对话模型可使用用户明确配置的远程 Provider。远程情感分析继续保持部署开关与用户授权双重门槛。

### 3.3 角色资源边界

仓库和未来默认安装包只包含原创、明确授权或中性占位资源。目标角色相关形象、Live2D 模型和声音只能由用户在本机导入其有权使用的资源。Stage 4E 不新增受保护角色名称、肖像、模型、动画、原作台词或仿声资产。

### 3.4 技术方案

采用独立只读表达 API和前端进程内事件：

- 不把表达计划嵌入稳定的核心消息 DTO；
- 不在本阶段引入 SSE、WebSocket 或跨进程事件总线；
- 后端拥有持久化表达事实；
- 实际播放器拥有瞬时 speaking 事实；
- 角色视图只消费事件，没有业务写权限。

## 4. 范围

### 4.1 纳入范围

1. 消息绑定的只读 ExpressionPlan 查询服务与 HTTP API。
2. 明确区分持久化计划和 neutral 默认值的响应 DTO。
3. 前端 API client、严格类型和运行时边界校验。
4. `ExpressionEvent`、`SpeakingEvent` 及纯转换适配器。
5. 现有播放器的 speaking 生命周期通知。
6. 中性占位角色预览，包括表达语义、说话状态和由编排层传入的当前消息无障碍标签；该标签来自前端已加载消息，只在内存中存在，不进入表达 API 或表现事件。
7. 会话切换、刷新、删除、播放停止、打断、失败和异步迟到保护。
8. 后端、前端、E2E、SQLite 不变量、完整回归和运行时验证。
9. Stage 4E 验收证据与必要的阶段状态文档更新。

### 4.2 明确排除

- Electron、Tauri 或其他桌面壳；
- 透明置顶窗口、系统托盘、点击穿透、开机启动和安装器；
- Live2D、Spine、VRM 或其他动画引擎；
- 音频振幅口型、眨眼算法和动画帧协议；
- 后台监听、持续 ASR、自动 spoken barge-in 或全双工音频；
- SSE、WebSocket、跨进程 IPC 或远程表现事件总线；
- 表现状态、动画状态或 speaking 状态持久化；
- 会话摘要注入、自动记忆冲突解决、多用户或多角色 profile；
- 对真实 TTS 的 `delivery`/`intensity` 声学质量承诺；
- 未授权角色资源的导入实现、捆绑或分发。

## 5. 架构与职责边界

### 5.1 后端：持久化表达的唯一事实来源

后端负责：

- 验证消息是否存在且角色为 assistant；
- 读取该消息已经持久化的 `ExpressionPlan`；
- 校验计划是否可由当前 schema 安全消费；
- 对无计划、损坏或不兼容计划返回确定的 neutral 默认表达；
- 返回最小化、只读、版本化响应。

查询不得：

- 重新计算 ExpressionPlan；
- 读取当前情感状态以替代历史计划；
- 更新情感状态、记忆或消息；
- 调度远程分析；
- 新增 ExpressionPlan 数据库记录；
- 暴露消息正文、Prompt、记忆、情感六维向量、推理原因或 Provider 参数。

### 5.2 前端表达适配器

表达适配器负责把 API 响应转换为前端 `ExpressionEvent`。它必须是可独立测试的纯转换层，不依赖 React 生命周期，不读取业务数据库，也不调用任何写接口。

未知枚举、非有限 rate、越界 rate、未知 schema version 或结构缺失均不得直接进入角色视图。API 层原则上已完成兼容性降级；前端仍需在不可信网络边界保留本地 neutral fallback。

### 5.3 播放器：瞬时 speaking 状态的唯一事实来源

现有音频播放控制器知道浏览器是否真正开始、停止、被打断或失败，因此由它产生 `SpeakingEvent`。后端不得根据 TTS 请求成功来推断客户端正在播放。

播放器必须维持既有行为，并为每次播放创建一个前端进程内唯一、单调递增且不复用的 `playbackRunId`。实现采用同步激活协议：公开的播放入口在启动任何异步 TTS、解码或媒体操作前，同步递增 generation、使旧 run 失效，并通过 `onRunActivated({ assistantMessageId, playbackRunId })` 通知编排层；编排层先将该 pair 设为当前 active run，随后播放器才允许产生该 run 的异步生命周期事件。该通知只是前端进程内控制信号，不属于 `SpeakingEvent`，不写入数据库，也不由后端分配。播放器额外发布以下生命周期：

- `started`：该播放实例第一次实际开始输出；
- `paused`：该实例暂停输出，预览不再显示正在说话；
- `resumed`：同一实例从暂停恢复实际输出；
- `stopped`：正常结束或用户显式停止；
- `interrupted`：由于新录音、开始另一播放或其他明确打断路径终止；
- `failed`：合成、解码、调度或播放失败。

合成中但尚未开始输出不是 Speaking；若在 `started` 前失败，当前 run 发出 `failed`，编排层仅在 pair 仍匹配时清除 active run，不得伪造 `started`。`paused` 保留当前表达和播放实例，但进入 Paused；`resumed` 只对当前暂停实例有效。开始新播放时按“旧 run 失效 → 新 run 同步激活 → 启动异步工作”的顺序执行；会话切换、取消或组件卸载时先递增 generation 使旧 token 失效，再同步调用 `onRunDeactivated` 清除编排层 active run，最后释放音频资源。预览同时校验消息 ID 与 `playbackRunId`；旧实例的任何迟到事件（包括旧 `started`）均被忽略。无论何种终止，当前实例的 speaking/paused 状态都必须回到 idle；表达状态可以继续保留在当前消息上。

### 5.4 中性占位角色视图

占位角色视图只消费当前 `ExpressionEvent` 和 `SpeakingEvent`。编排层可以另行传入 `displayLabel`，其可测试派生契约固定为：来源只能是前端已加载且与当前 ID 匹配的 assistant `Message.content`；将所有连续空白（含换行和制表符）折叠为一个半角空格并去除首尾空白；按 Unicode code point 取前 80 个字符，超出时追加单字符 `…`；规范化后为空时使用固定文本“助手消息”；不得调用摘要 Provider。该值仅作为预览组件内存 prop，不是 Expression API 或表现事件字段，不写入数据库、表达缓存、持久缓存或日志。视图展示：

- 当前表达语义；
- 当前是 idle、speaking 还是 paused；
- 当前绑定的 assistant 消息无障碍标签。

预览不能：

- 修改情感状态；
- 创建记忆或消息；
- 自行调用 TTS；
- 从 delivery 推导新的业务状态；
- 使用颜色作为唯一语义载体；
- 包含受保护角色肖像或仿制素材。

### 5.5 应用编排层

`App` 或等价编排层仅负责：

- 根据明确的 assistant 消息 ID 请求表达结果；
- 保存当前选中消息及表达加载状态；
- 将播放器事件转发给预览；
- 在会话切换、会话删除和刷新时清理瞬时状态；
- 对迟到响应执行消息 ID 校验。

表达映射规则和状态机细节不得散落在主应用组件中。

## 6. 后端 API 契约

### 6.1 Endpoint

```http
GET /api/messages/{assistant_message_id}/expression
```

路由与已有 message-bound TTS 共享 `/api/messages` 资源语义，但使用独立查询依赖，不触发 TTS。

### 6.2 成功响应

有兼容持久化计划：

```json
{
  "assistant_message_id": "msg_...",
  "schema_version": 1,
  "delivery": "reassuring",
  "intensity": "medium",
  "rate": 0.96,
  "source": "persisted_plan"
}
```

合法 assistant 消息没有可消费计划：

```json
{
  "assistant_message_id": "msg_...",
  "schema_version": 1,
  "delivery": "neutral",
  "intensity": "low",
  "rate": 1.0,
  "source": "default"
}
```

### 6.3 字段约束

- `assistant_message_id`：必须与路径参数和已读取消息一致。
- `schema_version`：响应契约版本；本阶段为整数 `1`。
- `delivery`：`neutral | warm | reassuring | reserved | firm`。
- `intensity`：`low | medium`。
- `rate`：有限数字，范围沿用领域模型 `0.90–1.10`。
- `source`：`persisted_plan | default`。

响应不包含内部 ExpressionPlan ID、`source_emotion_version`、情感状态、消息正文或创建表达计划时的上下文。未来若渲染器确有可审计需求，必须另行设计，而不是隐式扩大本接口。

### 6.4 HTTP 语义

| 状态 | 条件 | 前端行为 |
|---|---|---|
| `200` | 合法 assistant 消息且有兼容计划 | 使用 `persisted_plan` |
| `200` | 合法 assistant 消息但无计划、计划损坏或版本不兼容 | 使用 `default` neutral |
| `404` | 消息不存在 | 本地 neutral，并保持聊天可用 |
| `422` | 消息存在但不是 assistant 角色（当前正常持久化模型中即 user 消息） | 本地 neutral，并记录可诊断 UI 状态 |
| `500` | 未预期的基础设施错误 | 本地 neutral；不得破坏消息列表或播放器控制 |

历史 Stage 4A–4C assistant 消息可能没有计划，因此“计划缺失”不是 404。只有消息资源本身不存在时返回 404。当前数据库只持久化 user/assistant 消息，Stage 4E 不扩大消息角色模型；非 assistant 的 API 测试仅使用可持久化的 user 消息。该 endpoint 必须显式映射为 422 的统一错误 envelope，不沿用现有通用验证错误可能产生的 400。

### 6.5 只读与幂等性

同一数据库状态下重复调用必须返回相同结果。该调用不得改变任何表的行数、版本号或更新时间。即使返回 `source="default"`，也不得借查询路径补写计划。

## 7. 前端事件契约

### 7.1 ExpressionEvent

```ts
type ExpressionDelivery =
  | "neutral"
  | "warm"
  | "reassuring"
  | "reserved"
  | "firm";

type ExpressionIntensity = "low" | "medium";

interface ExpressionEvent {
  type: "expression";
  assistantMessageId: string;
  schemaVersion: 1;
  delivery: ExpressionDelivery;
  intensity: ExpressionIntensity;
  rate: number;
  source: "persisted_plan" | "default";
}
```

`rate` 在 Stage 4E 只作为同一表达计划的一部分供观察和未来渲染适配使用；占位视图不得再次把它写入 TTS 请求。message-bound TTS 继续独立读取后端持久化计划并进行安全映射。

### 7.2 SpeakingEvent

```ts
interface SpeakingEvent {
  type: "speaking";
  assistantMessageId: string;
  playbackRunId: number;
  phase:
    | "started"
    | "paused"
    | "resumed"
    | "stopped"
    | "interrupted"
    | "failed";
}
```

事件只存在于前端运行期，不写入 SQLite。`playbackRunId` 在同一播放器组件生命周期中单调递增，每次新播放（包括同一消息重播）都分配新值；暂停/恢复沿用同一值。播放入口必须在任何异步工作前同步发出 `onRunActivated`，编排层据此建立当前 pair；若激活回调不能完成，播放不得启动。预览仅接受当前 `(assistantMessageId, playbackRunId)` 的事件。开始另一播放、取消、切换会话或组件卸载会先递增 generation 让旧 run 失效，并通过 `onRunDeactivated` 同步清除 active pair；pre-start `failed` 也仅在 pair 仍匹配时清除。随后到达的旧 `started`、`paused`、`resumed`、`stopped`、`interrupted`、`failed` 或媒体 `ended` 回调必须被忽略。若未来桌面壳需要跨进程传递，必须在桌宠专项设计中选择 IPC 或网络协议并定义顺序、重连和幂等规则。

### 7.3 本地 neutral fallback

前端对网络错误或不可信响应产生以下确定值：

```ts
{
  type: "expression",
  assistantMessageId,
  schemaVersion: 1,
  delivery: "neutral",
  intensity: "low",
  rate: 1.0,
  source: "default"
}
```

本地 fallback 不应伪装成从数据库读取的持久化计划。编排层必须在内部额外记录 `origin: "api" | "local_fallback"`；该字段不进入公共 `ExpressionEvent`，也不传给角色渲染器。只有 API 成功返回的 `persisted_plan` 或服务端 `default` 可以按消息 ID 缓存。网络、500 或解析失败产生的 `local_fallback` 不得进入长期缓存；下一次选择、重播或用户显式重试同一消息时必须重新查询。会话删除时清除该会话消息的表达缓存。

## 8. 状态模型与交互

### 8.1 角色预览状态机

```text
Idle / Neutral
    │ expression(message A)
    ▼
Ready(message A, expression A)
    │ speaking.started(message A, run 1)
    ▼
Speaking(message A, run 1, expression A)
    │ paused(run 1)              │ stopped / interrupted / failed(run 1)
    ▼                            ▼
Paused(message A, run 1)       Ready(message A, expression A)
    │ resumed(run 1)
    └──────────────→ Speaking(message A, run 1, expression A)
```

`started` 仅表示一个 run 首次开始实际输出；暂停恢复使用 `resumed`，不得重复发出 `started`。

### 8.2 状态规则

1. 未选中 assistant 消息时为 `Idle / Neutral`。
2. 收到合法 `ExpressionEvent` 后进入 `Ready`。
3. 每次新播放先同步分配新的 `playbackRunId` 并通过 `onRunActivated` 建立当前 pair，再启动异步 TTS/解码；只有同时匹配当前 `assistantMessageId` 和当前 run 的 `started` 能进入 `Speaking`。
4. 当前 run 的 `paused` 进入 `Paused`，`resumed` 回到 `Speaking`；暂停后停止、录音打断、会话切换或失败均终止该 run。
5. 当前 run 的 `stopped`、`interrupted` 或 `failed` 清除 speaking/paused，但保留 expression。
6. 不匹配当前消息 ID 或 `playbackRunId` 的事件不得改变当前预览；同一消息快速停止后重播时，旧 run 的迟到终止或媒体 `ended` 事件必须被忽略。
7. 合成中且尚无实际音频输出时保持 `Ready`；pre-start 失败不经过 `Speaking`。
8. 切换会话、删除当前会话或清除消息列表时，先使当前 run 失效，再立即清除选中消息、expression 和 speaking/paused。
9. 页面刷新只从后端恢复 expression，不恢复或猜测 speaking/paused。
10. 快速切换消息时，每次请求携带目标消息 ID；响应到达后再次核对当前目标，旧响应不得覆盖新状态。
11. 多条 assistant 消息的表达可以缓存，但缓存键必须是消息 ID，且不能将 speaking/paused 状态放入持久缓存。
12. UI 默认跟随最新成功回复；用户从历史消息触发重播时，预览切换到被重播的确切消息，并分配新 run。

### 8.3 可访问性与视觉约束

- 表达语义必须有文本标签，不仅依赖颜色或动画。
- speaking 状态提供屏幕阅读器可理解的状态文本。
- 占位资源使用简单原创几何形或中性头像，不模仿目标角色受保护外观。
- 动效遵循 `prefers-reduced-motion`；关闭动效时功能语义不丢失。
- 预览不得遮挡聊天、录音、停止播放和错误恢复等核心操作。

## 9. 数据流

### 9.1 新回复路径

1. 用户提交文本，或 ASR 产生用户确认后的文本。
2. 后端生成并持久化 assistant 消息。
3. 后端尽力创建该消息的不可变 `ExpressionPlan`；失败不影响文字回复。
4. Chat API 返回 `assistant_message_id`。
5. 前端按该 ID 调用表达查询 API。
6. 前端验证响应并生成 `ExpressionEvent`。
7. 占位角色显示该消息的表达；若查询失败则显示本地 neutral。
8. 用户触发 message-bound TTS；播放器实际开始后发出 `started`。
9. 播放结束、停止、打断或失败后发出相应终止事件。

### 9.2 历史消息路径

1. 前端加载会话消息。
2. 表达查询采用按需加载，优先获取当前最新 assistant 消息或用户明确重播的消息。
3. 不要求初始页面为全部历史 assistant 消息并发请求表达；如实施中证明需要批量预取，必须先评估 N+1 请求并在计划中选择有界并发或单独批量接口。
4. 同一消息的缓存结果必须保持消息 ID 绑定。
5. 刷新后重新读取持久化表达，结果应与刷新前一致。

Stage 4E 默认不新增批量 API，以保持最小契约。实施计划应以现有 UI 的实际展示需求决定是否仅查询当前消息；不得未经证据扩大为全历史预取。

### 9.3 会话切换与迟到响应

1. 切换会话时先清除当前瞬时预览状态。
2. 新会话选出目标 assistant 消息并发起查询。
3. 任一旧请求返回时，若其会话或消息 ID 不再是当前目标，则丢弃结果。
4. 可使用 `AbortController` 取消旧请求，但即使取消失败，ID 校验仍是最终保护。

## 10. 错误处理与失败隔离

| 失败点 | 规定行为 |
|---|---|
| ExpressionPlan 创建失败 | 沿用 4D：assistant 文字消息成功返回，查询时得到 neutral 默认值 |
| 表达查询时消息不存在 | API 404；前端 neutral，不移除其他消息 |
| 表达查询目标不是 assistant | API 422；前端 neutral，不尝试 TTS 或写入计划 |
| 计划缺失 | API 200 + `source=default` |
| 计划损坏、未知枚举、越界 rate | API 200 + `source=default`，不把损坏内容透传 |
| 计划 schema 不兼容 | API 200 + `source=default` |
| 网络超时或 API 500 | 前端本地 neutral；聊天、录音和播放控制仍可用 |
| TTS 合成失败 | 保留文字和表达，发出 `failed` 并退出 Speaking |
| 音频解码或播放失败 | 保留文字和表达，发出 `failed` |
| 用户停止播放 | 发出 `stopped`；保留当前表达 |
| 录音打断播放 | 发出 `interrupted`；不得让旧音频恢复为 Speaking |
| 会话快速切换 | 清除旧瞬时状态，迟到结果按 ID 丢弃 |
| 占位预览渲染错误 | 错误边界隔离预览；不得影响聊天主界面 |

日志和 diagnostics 不得记录消息正文、Prompt、记忆、原始 Provider payload、API Key、私人音频或未授权素材路径。可以记录最小化的消息 ID、响应类别和错误类型，但应遵循现有安全日志约束。

## 11. 数据与隐私不变量

1. `messages`、`expression_plans`、`emotion_states`、`emotion_events`、记忆和摘要继续分表存储。
2. 每个 `(assistant_message_id, schema_version)` 至多存在一个不可变的持久化 ExpressionPlan；这是 Stage 4D 的既有唯一性模型。Stage 4E 查询只消费明确支持的版本，不把该约束改成跨版本的一消息全局唯一。
3. 表达查询不得新增或更新数据库记录。
4. `speaking`、动画帧、选中消息、加载状态和 UI 错误不得持久化。
5. 表达响应不含消息正文、情感六维向量、推理原因、Prompt、记忆或 Provider payload。
6. 前端不得提交任意 `delivery`、`intensity`、`rate`、style、SSML 或自由文本 Provider 参数来改变 message-bound TTS。
7. 远程情感分析 consent 与 Stage 4E 无关；读取表达不得导致任何网络外发到模型 Provider。
8. 默认 fake/offline 验证路径保持零模型网络请求。

## 12. 测试设计

### 12.1 后端单元测试

覆盖：

- 合法 assistant 消息及兼容持久化计划；
- 合法 assistant 消息无计划，返回 neutral default；
- 历史消息无计划；
- 消息不存在；
- 当前可持久化的非 assistant 消息（user）被拒绝；
- repository 返回损坏行或领域模型校验失败；
- 未知 schema version；
- delivery、intensity 和 rate 的边界；
- 重复查询无写入且结果稳定；
- 响应不包含内部或敏感字段。

### 12.2 API 集成测试

覆盖：

- `GET /api/messages/{id}/expression` 的 200/404/422；
- `persisted_plan` 与 `default` 响应 schema；
- 查询不改变 `expression_plans`、emotion、memory 或 message 表；
- 与 message-bound speech 路由并存，不改变既有 TTS 请求契约；
- 非法路径和额外客户端输入不能注入表现参数；
- 未预期错误遵循统一错误 envelope。

### 12.3 前端单元与组件测试

覆盖：

- API 类型与运行时校验；
- 网络失败、本地 neutral fallback；
- `ExpressionEvent` 纯映射；
- `displayLabel` 的空白规范化、Unicode code point 80 字符截断、省略号和空值回退；
- `onRunActivated` 必须早于任何异步生命周期，激活失败不得启动播放；
- `SpeakingEvent` 的六种生命周期，以及 pre-start 失败不伪造 `started`；
- Idle、Ready、Speaking、Paused 状态转换；
- 同一消息停止后快速重播时，旧 `playbackRunId` 的迟到终止事件被忽略；
- 暂停、恢复、暂停后停止、暂停后录音打断和暂停后切换会话；
- 非当前消息或非当前 run 事件被忽略；
- 会话切换和删除清理；
- 迟到响应丢弃；
- `AbortController` 仅作为优化而非唯一正确性保障；
- 播放失败、停止和录音打断；
- `prefers-reduced-motion` 与文本语义；
- 占位预览异常不影响核心聊天组件。

### 12.4 Playwright E2E

fake-only 环境至少验证：

```text
创建/选择会话
→ 发送消息
→ assistant 消息成功显示
→ 获得固定 ExpressionPlan 语义
→ 播放该确切消息
→ 预览进入 Speaking
→ 显式打断或停止
→ 预览退出 Speaking 但保留表达
→ 切换到另一会话
→ 返回原会话
→ 刷新页面
→ 原消息恢复同一表达结果
```

附加场景：

- 历史无计划 assistant 消息显示 neutral；
- 表达 API 被模拟为失败时聊天仍可发送和显示；网络恢复后重新选择或重播同一消息会重新查询并恢复持久化表达；
- 快速切换会话时旧表达不出现在新会话；
- 同一 assistant 消息停止后立即重播时，旧 run 的迟到结束事件不能终止新 run；
- 暂停、恢复、暂停后停止、暂停后录音打断与暂停后会话切换具有确定状态；
- 录音打断后旧消息不重新进入 Speaking；
- E2E 使用中性占位资源，不依赖受保护素材或真实 Provider。

### 12.5 SQLite 不变量检查

验证前后快照至少证明：

- 表达读取没有新增或更新计划；
- 每个 `(assistant_message_id, schema_version)` 至多一个计划；
- 没有新增 speaking、动画或 UI 状态表；
- messages、memories、session_summaries、emotion 状态和审计没有因预览读取发生变化；
- 数据库不包含 Prompt、Provider payload 或前端占位素材。

### 12.6 完整回归与运行时验证

实施完成后应运行：

- Stage 4E focused 后端测试；
- 完整后端 pytest；
- 根目录脚本测试；
- 前端单测、typecheck 和 production build；
- Playwright E2E；
- `AI桌宠:verify` 项目专属后端 API 运行时验证；
- fake-only 浏览器真实流程验证；
- `/code-review` 或项目要求的等价代码审查。

任何未运行、受环境阻塞或失败的验证必须如实记录，不能以历史 PASS 替代当前工作树结果。

## 13. 验收标准

只有同时满足以下条件，Stage 4E 才能标记完成：

1. 合法 assistant 消息可获得版本化、最小化的表达响应。
2. 同一持久化消息跨重复查询和页面刷新获得相同表达结果。
3. 历史无计划、损坏或不兼容计划安全返回 neutral，不创建新计划。
4. 当前可持久化的非 assistant 消息（user）和不存在消息具有明确的 422/404 错误语义。
5. 表达查询失败不影响文字聊天、消息加载、录音、记忆、情感或 TTS 重试。
6. 预览表达状态始终绑定确切 assistant 消息 ID；播放状态还必须绑定当前 `playbackRunId`。
7. 快速切换、同消息快速重播、旧 run 迟到事件、暂停/恢复、停止、打断和播放失败不会造成错误 Speaking/Paused 或表达漂移。
8. speaking/paused 状态只来源于实际播放器，不由后端猜测，也不持久化。
9. 占位角色只消费事件，没有业务写权限，并满足基础可访问性要求。
10. API 与前端事件不暴露消息正文、Prompt、记忆、情感六维向量、推理原因或 Provider payload。
11. fake-only 自动化与运行时流程可完成，不需要远程模型、真实 ASR/TTS、GPU 或受保护素材。
12. focused、完整回归、E2E、数据库不变量和运行时验证有当前工作树的实际证据。
13. 独立代码审查没有未处理的高严重度正确性、安全、隐私或回归问题。
14. 文档只声明实际完成并验证的能力。

## 14. 实施顺序建议

详细实施步骤由后续 `writing-plans` 阶段确定，但顺序应保持：

1. 先以测试锁定后端只读服务和响应契约；
2. 实现 API 并验证只读不变量；
3. 先以测试定义前端事件和状态机；
4. 接入 API client 与迟到响应保护；
5. 让播放器发布 speaking 生命周期；
6. 增加中性占位角色预览；
7. 增加 E2E 和数据库不变量验证；
8. 运行完整回归、项目专属 runtime verify 和代码审查；
9. 仅在证据通过后更新 `CLAUDE.md`、README 和 Stage 4E 验收文档。

实现应遵循 TDD，修改最少文件，沿用现有模块边界，不为未来桌面壳提前引入依赖。

## 15. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 表达贴错消息 | 所有响应和事件携带消息 ID；应用结果前再次校验当前目标 |
| 页面刷新后表达漂移 | 只读取持久化计划，不按当前情感重新计算 |
| N+1 请求 | 默认按需查询当前或重播消息；不无界预取全部历史 |
| 表达故障破坏聊天 | 独立只读 API、neutral fallback、预览错误边界 |
| 后端和播放器争夺 speaking 事实 | speaking 只由实际播放器产生 |
| 计划损坏透传到 UI | 后端兼容性解析加前端边界校验双层降级 |
| 客户端借表现参数操纵 TTS | 只读 GET 不接受表现 body；message-bound TTS 继续从服务器计划解析 |
| 过早绑定桌面或动画技术 | 使用 provider-neutral、renderer-neutral 事件；不引入桌面依赖 |
| 拟人化造成“真实情感”误导 | UI 使用“表达策略/表现状态”措辞并保留免责声明 |
| 版权或声线风险 | 仅中性占位资源；目标角色资源只能合法本地导入且另行设计 |
| 当前工作树大量未提交修改 | 不 reset、checkout、clean、覆盖或机械重做；实施前重新核对 diff 和测试基线 |

## 16. 后续路线

Stage 4E 完成并通过独立验收后，先执行阶段 4 总体验收，确认本地状态、文本表达、consent、TTS 映射和浏览器表现协议组成完整且安全的情感系统。

阶段 4 总体验收通过后，才能另立“原生桌宠呈现”专项设计，比较 Tauri/Electron、渲染引擎、透明窗口、托盘、点击穿透、字幕、口型、资源许可和打包策略。届时桌面渲染器应复用 Stage 4E 的表达语义，并根据实际进程边界决定是否把前端进程内事件升级为 IPC、SSE 或 WebSocket。

全双工语音、自动 spoken barge-in、真实情感 TTS 听感评测和合法角色资源导入均为独立后续子项目，不在 Stage 4E 中顺带实现。
