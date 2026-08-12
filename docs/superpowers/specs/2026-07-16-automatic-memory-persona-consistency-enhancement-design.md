# 自动长期记忆与角色一致性增强设计

日期：2026-07-16  
状态：已批准  
适用项目：私人本机虚拟角色交互系统

## 1. 背景

项目阶段 1–4 已完成并验收，当前已有：

- FastAPI、React、TypeScript、SQLite 基础架构；
- Anthropic、DeepSeek 和 fake LLM Provider 适配层；
- 会话、消息、长期记忆、embedding、会话摘要、情感状态和表现计划持久化；
- 手动记忆 CRUD、待确认记忆候选、相关性检索、冲突审计和非阻塞摘要生成；
- 中文文字聊天、ASR、TTS、打断控制及浏览器表现预览；
- Electron 依赖和双 Vite 入口，但桌面产品壳尚未形成运行闭环。

用户于 2026-07-16 明确选择先实施“记忆与角色一致性增强”，再继续 Windows Electron 桌面壳。该选择将原本排在下一位的 Electron 壳暂时后移，但不推翻阶段 1–4 的既有验收结论，也不废弃已经批准的 Electron 设计。

本设计是阶段 3 完成后的独立增强闭环，不把新增能力描述成原阶段 3 验收的补充证据。

## 2. 已确认决策

- 部署路线：本地优先、云端增强。
- 默认语言：中文为主，允许少量自然的日语短句。
- 记忆写入：完全自动，不要求日常人工确认。
- 安全解释：自动写入仍须经过本地治理、版本化、冲突留痕、敏感信息过滤和可撤销机制。
- 角色演化：核心人格固定，关系和熟悉度可缓慢成长。
- 角色素材边界：现有网上获得的普通图片只用于私人本机实验，不进入 Git、安装包、演示截图或任何分发物。
- 本闭环不实现 Electron、PNG/WebP 导入、Live2D、口型、声优音色克隆或全双工语音重构。

## 3. 目标

建立一个不会阻塞聊天、可解释、可撤销、可审计的自动长期记忆系统，并通过固定角色宪法和可重算的关系投影提高跨会话角色一致性。

完成后，系统应能够：

1. 从成功对话中自动提取稳定事实、偏好、目标、事件、关系节点和承诺；
2. 在本地判断敏感信息、重复、支持、更新和冲突关系；
3. 以版本链保存事实变化，而非静默覆盖旧值；
4. 防止已删除记忆被旧任务或摘要自动恢复；
5. 将结构化记忆、低可信摘要、近期消息和关系状态按明确优先级组成上下文；
6. 保持角色核心人格不变，同时让称呼、熟悉度和语气温度随共同经历缓慢变化；
7. 在抽取、检索、摘要或关系投影失败时继续提供文字聊天，并让故障对用户可见；
8. 支持用户查看、编辑、归档、删除、撤销自动写入，并追溯来源。

本系统只模拟记忆、关系和情感表现，不宣称角色具有真实意识或真实人类情感。

## 4. 非目标

本闭环不包括：

- 新建外部记忆平台、图数据库或独立向量数据库；
- 用 Mem0、Letta 等框架替换现有 SQLite 记忆来源；
- 训练、微调或蒸馏模型；
- 改造 LLM 为 token streaming；
- 生产级全双工 ASR/TTS；
- Electron 主进程、preload、托盘或透明桌宠窗；
- 静态角色图片导入、Live2D、动作、口型或素材分发；
- 仿制、公开传播或冒充原角色声优的声音；
- 多用户、局域网或公网服务；
- 自动执行工具、外部副作用或代表用户作出承诺。

## 5. 方案选择

### 5.1 采用：增量强化现有内核

保留现有 FastAPI、SQLite、Provider、记忆候选、摘要和情感边界，增加受约束的自动记忆流水线。

选择原因：

- 最大限度复用已验收实现和测试；
- 数据继续以本地 SQLite 为唯一事实来源；
- 不引入第二套记忆生命周期和迁移风险；
- 每个增量均可独立验证和回滚；
- 与当前 16 GB 内存、RTX 3060 Laptop GPU 的本地优先环境匹配；
- 云端模型只负责受限抽取或对话，本地规则保留最终写入权。

### 5.2 不采用：外部记忆框架

外部框架会与现有记忆 CRUD、候选状态、冲突审计、摘要和 SQLite schema 重叠，并增加数据控制、调试和升级成本。只有未来出现跨设备、多用户或超大规模记忆需求时才重新评估。

### 5.3 不采用：只扩大 Prompt 和摘要

单纯塞入更多历史或滚动摘要无法可靠处理时间更新、矛盾、删除和来源审计，也容易把摘要错误永久传播到后续回复。

## 6. 总体架构

系统分为同步聊天通道和异步记忆通道。

### 6.1 同步聊天通道

一次聊天请求依次执行：

1. 持久化用户消息；
2. 加载版本化的角色宪法；
3. 读取当前情感快照和关系投影；
4. 检索少量 active、非冲突、非删除的结构化记忆；
5. 选择受控的会话摘要片段；
6. 按预算组装 Provider payload；
7. 调用现有 LLM Provider；
8. 保存并返回 assistant 回复；
9. 以本轮 turn 标识调度异步记忆工作。

记忆检索、摘要或关系投影失败时，聊天降级为角色宪法加近期消息。失败不得阻止文字回复。

### 6.2 异步记忆通道

每轮成功对话后，各工作单元按以下边界运行：

1. 以稳定 `turn_id` 创建幂等 `memory_job`；
2. `memory_job` 从本轮消息和必要的局部上下文中提取结构化候选；
3. 在本地执行敏感信息过滤、规范化和 canonical key 生成；
4. 检索可能重复或冲突的现有记忆，并形成新增、支持、更新、冲突、拒绝或无需变化决策；
5. `memory_job` 只在短数据库事务中原子提交其当前 Gate 允许的记忆决策、metadata-only 审计和自身 outcome；不得在持有 SQLite 写事务时调用 Provider；
6. 事务提交后，才以独立幂等键调度 `summary_job`；摘要失败不回滚或改写 `memory_job` outcome；
7. Gate C 启用关系事件账本后，仅由已经提交的关系事件触发独立投影重算；投影失败不回滚记忆或摘要；
8. `memory_job`、`summary_job` 和关系投影的状态、重试与故障展示彼此独立。

任务失败允许有限重试。重试必须幂等，不得重复创建 active 记忆。Gate A 只实现上述 `memory_job` 的 shadow 基础，不实现 `summary_job`、关系事件或关系投影。

## 7. 组件边界

### 7.1 Memory Extractor

职责：把对话转换为候选，不直接写数据库。

输入：

- 当前 user/assistant 消息；
- 少量近期消息；
- 与本轮相关的现有记忆摘要；
- 允许的记忆类型和输出 schema。

输出为严格 JSON，至少包含：

- `memory_type`；
- `subject`；
- `content`；
- `canonical_key_hint`；
- `valid_from_hint`；
- `confidence`；
- `source_message_ids`；
- `reason`。

Extractor 的置信度只是输入信号，不能直接决定写入。

### 7.2 Memory Governor

职责：在本地作出最终写入决策，是自动记忆唯一批准边界。

它负责：

- “不要记住”“忘掉这件事”等显式指令识别；
- 密码、API Key、验证码、私钥、完整银行卡号和身份凭据过滤；
- 内容长度、类型和字段白名单校验；
- canonical key 生成和规范化；
- 近似重复判断；
- `support / create / supersede / conflict / reject / no_change` 决策；
- 最终置信度限幅；
- 单轮写入数量和字符预算；
- 关系事件的单轮影响上限。

远程 Provider 无权绕过 Governor。

### 7.3 Versioned Memory Repository

职责：提供结构化记忆的事务性持久化和查询。

它必须支持：

- 新建当前版本；
- 支持证据追加；
- 旧版本失效和新版本接替；
- 冲突关系；
- 用户编辑；
- 归档、删除和撤销；
- tombstone 防复活；
- 来源追踪；
- 按期望版本进行并发更新。

### 7.4 Context Composer

职责：将不同可信层级的信息组成受预算约束的上下文。

优先级从高到低为：

1. 角色宪法；
2. 当前用户消息；
3. 必要的近期消息；
4. 用户明确编辑或确认的 active 结构化记忆；
5. 自动写入且无冲突的 active 结构化记忆；
6. 当前关系和情感表达投影；
7. 会话摘要片段。

摘要不能覆盖结构化事实。冲突记忆不作为确定事实注入；如与当前问题相关，只能以“存在不一致记录”的形式提醒模型澄清。

### 7.5 Persona Constitution

职责：保存不可被长期记忆修改的角色核心。

角色宪法包括：

- 冷静、克制、敏锐、讲原则的表达核心；
- 中文为主、少量自然日语短句的语言规则；
- 安全、事实准确性和用户明确指令优先；
- 不宣称是真人、官方角色或具有真实意识；
- 不因迎合、单轮冲突或关系增长而突然改变价值观；
- 不照搬受版权保护的原作长段台词；
- 不主动声称获得权利方背书。

角色宪法外置配置并带版本号。记忆只能影响可成长层，不能修改该配置。

### 7.6 Relationship Projector

职责：从有效关系事件、承诺和现有情感状态推导称呼及表达策略。

可成长内容包括：

- 用户偏好的称呼；
- 熟悉度；
- 共同经历；
- 未完成承诺；
- 信任、距离和语气温度的缓慢变化。

关系投影是派生状态，不是 LLM 自报的事实。它必须可从事件重新计算，且单轮变化受配置上限约束。

### 7.7 Memory Job Service

职责：管理异步任务的状态、幂等、重试和可观察性。

记忆写入和摘要生成是两个独立工作单元：

- `memory_job` 负责抽取、治理、记忆决策与审计；
- `summary_job` 负责增量摘要生成与原子 upsert，并使用独立的确定性幂等键。

不得在持有 SQLite 写事务时调用远程 Provider。`memory_job` 先在短事务中原子提交记忆决策、审计和自身 outcome；随后才调度 `summary_job`。摘要失败不回滚已经提交的记忆，也不能把记忆任务显示为失败。

状态为：

- `pending`；
- `running`；
- `succeeded`；
- `failed`；
- `cancelled`。

保存结构化错误类别、尝试次数和时间，不保存密钥、完整远程响应或不必要的对话原文。UI 分别表示记忆同步与摘要状态，不能用单一“已同步”掩盖其中一个工作单元失败。

### 7.8 互斥运行模式与远程同意

自动记忆运行模式是互斥状态机：

- `off`：不调度候选或自动抽取；
- `candidate_confirmation`：沿用现有 Stage 3I 行为，只创建 pending 候选，用户确认后才成为 active；
- `shadow_auto`：运行 Extractor 和 Governor、保存不含正文的决策元数据，但不创建或修改 active 记忆；
- `auto_active`：在 Gate B 验收条件满足后，允许 Governor 批准版本化 active 写入。

任一 turn 只能由当前模式对应的唯一调度器处理，不能同时产生 pending 候选和自动 active 记录。既有 pending/dismissed 记录保持原状态，不因模式切换自动升级。关闭或降级模式不删除已有 active 记忆。

“允许自动写入”和“允许把抽取内容发送给远程 Provider”是两个正交设置：运行模式只决定 `off / pending / shadow / active` 写入语义，Extractor 路由只决定 `local / fake / remote` 的抽取来源。远程抽取默认关闭，必须有持久、明确、版本化且可撤回的本地同意；同意记录抽取用途、Provider、披露字段和政策版本。未经同意不得选择 `remote` 路由，也不得把整个数据库、完整会话或未列入披露字段的内容发送出去，但不得因此隐式改变运行模式。撤回后取消尚未开始发送的远程任务；已经发出请求的任务即使收到结果，也不得提交新的 active 写入，只能完成不含正文的 metadata-only 审计。若当前运行模式仍允许工作，则按显式配置的 `local` 或 `fake` Extractor 继续；若没有可用且已配置的非远程 Extractor，任务以结构化 `skipped_no_extractor` outcome 结束。系统不得静默伪装成获得了语义抽取结果，也不得扩大披露。Gate A 的能力闸门无条件拒绝 `auto_active`，因此本 Gate 中远程撤回后的任务同样只能产生 metadata-only outcome。

## 8. 概念数据模型

现有 schema 应采用兼容迁移逐步扩展，不能破坏既有记忆 API 和历史数据。

### 8.1 MemoryRecordV2

概念字段：

```text
id
memory_type
subject
canonical_key
content
status
confidence
importance
valid_from
valid_to
source_kind
source_session_id
source_message_ids
supersedes_id
created_at
updated_at
version
metadata
```

`memory_type` 至少支持：

- `user_fact`；
- `preference`；
- `long_term_goal`；
- `important_event`；
- `relationship_event`；
- `commitment`；
- `other`。

`status` 至少支持：

- `active`；
- `archived`；
- `conflicted`；
- `deleted`。

既有 `pending` 和 `dismissed` 候选语义继续保留在候选层，不进入有效上下文。

### 8.2 Memory Evidence

一条记忆可有多个支持证据，以避免重复事实生成多条 active 记录。

```text
evidence_id
memory_id
source_session_id
source_message_id
relation: supports | contradicts | corrects
observed_at
extractor_kind
extractor_model
confidence
```

只记录 Provider/模型标识和必要元数据，不记录密钥或隐藏推理。

### 8.3 Memory Conflict

```text
conflict_id
left_memory_id
right_memory_id
status: open | resolved
resolution_kind
resolved_memory_id
created_at
resolved_at
```

无法自动判定的矛盾保持 open，双方均不得作为确定事实进入上下文。

### 8.4 删除屏障与 Tombstone

删除保护不能只依赖自然语言正文或单一 canonical key。系统维护单调递增的 deletion generation，并让每个任务在创建时捕获相应 generation：

- 全局 generation：删除全部长期记忆时递增；
- 类型 generation：删除某一类别时递增；
- 会话 generation：删除某会话派生记忆时递增；
- 单条 tombstone：删除具体语义事实时记录。

概念记录：

```text
tombstone_id
scope: memory | session | memory_type | all
scope_id: nullable
canonical_key_hash: nullable
canonicalization_version
delete_generation
source_memory_id: nullable
reason
created_at
expires_at: nullable
```

任务提交前和数据库写入事务内必须再次比较当前 generation 与任务捕获值；任何 scope 已前进都使旧任务失去写权限。单条 tombstone 使用带版本号的 canonicalization；同义候选还须通过 Governor 的保守语义删除匹配，无法排除时拒绝自动恢复。

摘要记录必须带来源消息覆盖范围、summary generation 和生成时看到的 deletion generations。摘要注入和再次抽取前，先排除已删除来源和过期 generation；摘要文本本身无权绕过删除屏障。删除后首次摘要重建完成前，可以暂时不注入受影响摘要。

Tombstone 默认不保存原始记忆正文。`expires_at` 默认为空，即仅由用户执行“彻底清除审计元数据”时移除；若未来支持自动到期，必须另行设计到期后防复活语义。

scope 优先级为 `all > memory_type/session > memory`；任一匹配屏障均拒绝旧任务提交。这样分别覆盖单条、会话、类别和全部删除。

### 8.5 Memory Job

```text
job_id
turn_id
session_id
status
attempt_count
error_category
created_at
started_at
finished_at
```

`turn_id` 具有唯一约束，从而保证同一轮最多产生一个有效抽取任务。

### 8.6 Persona Artifact、关系事件账本与关系投影

Persona Constitution 是不可变 artifact，而非可被原地改写的普通配置。每个 artifact 保存：

```text
persona_artifact_id
persona_version
canonical_content_hash
ruleset_version
content_snapshot_path
created_at
```

任何内容变化都创建新 artifact；不得复用版本号或覆盖历史快照。每个聊天 turn、记忆任务和关系投影都引用 `persona_artifact_id`，从而支持确定性回放。

关系变化使用不可变事件账本：

```text
relationship_event_id
event_kind: apply | revoke
event_type
subject
payload
source_memory_id
source_message_ids
observed_at
revokes_event_id: nullable
rule_version
created_at
```

`apply` 事件的 `payload` 只允许按 `event_type` 定义的字段，并记录作用方向和治理后的有限 delta；`revoke` 事件必须通过 `revokes_event_id` 指向一个既有 `apply` 事件，且不得再携带关系 delta。用户撤销通过追加 `revoke` 事件实现，不修改历史记录。Stage 4 情感状态不是关系事实来源；投影若读取情感，只能引用提交后的只读 emotion snapshot id 和明确的读取时点。

关系投影保存：

```text
projection_id
version
persona_artifact_id
projection_rule_version
familiarity
preferred_address
relationship_summary
source_relationship_event_ids
source_emotion_snapshot_id: nullable
computed_at
```

Projection 先读取全部 `apply` 事件，再排除被有效 `revoke` 事件引用的目标，只从剩余 apply 集合、对应版本规则和可选的只读情感快照生成。重复撤销、撤销不存在事件、撤销另一个 revoke 事件均为无效输入并记录 metadata-only 审计。规则升级、追加 revoke、冲突解决或用户编辑后，可以从账本确定性重算。数值字段必须有上下限和单轮 delta 上限。

## 9. 自动写入规则

### 9.1 可以自动写入

满足治理规则时可自动写入：

- 稳定称呼和偏好；
- 长期目标；
- 用户明确陈述的个人事实；
- 具有未来检索价值的重要事件；
- 共同经历；
- 双方在对话中明确形成的非外部副作用承诺；
- 对既有事实的明确更正。

### 9.2 不应写入

- 密码、密钥、验证码、私钥和完整支付凭据；
- 用户明确要求不要记住的内容；
- 单纯寒暄、临时情绪词和无复用价值的句子；
- 模型猜测、隐含诊断或未经用户陈述的敏感身份推断；
- assistant 自己生成但用户未认可的用户事实；
- 原作台词库、网上素材元数据或声优音频内容；
- 会导致系统代表用户执行外部行为的“承诺”。

### 9.3 更新

如果新陈述明确表示时间变化或更正：

- 旧记录设置 `valid_to` 并归档；
- 新记录成为 active；
- 新记录通过 `supersedes_id` 指向旧记录；
- 审计记录原因和来源。

### 9.4 支持

如果新陈述支持同一事实：

- 不新建重复 active 记录；
- 追加 Evidence；
- 可在上限内调整置信度；
- 不因重复次数无限提高重要度或关系值。

### 9.5 状态转换与数据库不变量

冲突是独立关系，`conflicted` 是从 open conflict 派生的可查询状态。数据库和服务层必须遵守：

| 决策 | 记录变化 | 上下文资格 |
|---|---|---|
| `create` | 创建一个 active 当前版本 | 可进入 |
| `support` | 不新建当前版本，只追加 supports Evidence | 原记录可进入 |
| `supersede` | 旧版本归档并结束有效期；新版本 active 且引用旧版本 | 仅新版本可进入 |
| `conflict` | 建立 open conflict；两侧保持历史记录，但派生为 conflicted | 两侧均不得作为确定事实进入 |
| `reject` | 不创建或修改记忆，只记录 metadata-only 决策 | 不进入 |
| `no_change` | 不改变记忆 | 维持原资格 |

open conflict 两侧不能同时作为 active 确定事实检索。解决方式限定为：

- `choose_left` / `choose_right`：选中一侧创建或确认新的当前版本，另一侧归档；
- `replace_both`：创建新的当前版本并归档双方；
- `both_contextual`：创建一个新的合成当前版本，在内容和结构化有效范围中明确表达双方适用的不同时间/语境，归档原双方并关闭冲突；
- `dismiss_both`：双方归档，不生成当前事实。

`resolved_memory_id` 对 `choose_left`、`choose_right`、`replace_both` 和 `both_contextual` 必填，并必须指向解决后唯一有资格作为当前事实的版本；其中 `both_contextual` 指向新建的合成版本，不直接重新激活任一历史侧。`dismiss_both` 的 `resolved_memory_id` 为空。supersede 不能绕过 open conflict：若目标 canonical key 存在 open conflict，必须先在同一事务中解决冲突。历史归档版本不得被直接重新激活，只能创建引用其来源的新版本。

## 10. 摘要注入策略

会话摘要保持与聊天历史、长期记忆分离。

摘要用于：

- 快速定位旧会话主题；
- 提供近期连续性；
- 帮助选择可能相关的结构化记忆；
- 在严格字符预算内补充尚未抽取的低风险上下文。

摘要不得：

- 直接创建或覆盖结构化事实；
- 绕过 tombstone；
- 覆盖 Persona Constitution；
- 把不确定推断写成确定事实；
- 在与结构化记忆冲突时获得更高优先级。

注入时摘要必须带“低可信会话概述”的明确标签，并限制条数和字符数。

## 11. 上下文预算与角色稳定性

Provider payload 使用统一的预发送 Unicode 字符预算；Provider 适配器可以额外执行 token 预检，但不能通过 tokenization 差异扩大已批准的字符披露范围。具体默认值和合法范围在每个 Gate 的文件级实施计划中冻结，并写入 `.env.example` 和配置测试；在该 Gate 获批后不得由实现者随意调整。

确定性裁剪顺序为：

1. 拒绝超过独立硬上限的单条输入，并给出明确错误；
2. Persona Constitution 和当前用户消息受保护；若两者本身超过 Provider 总硬上限，拒绝请求而不是静默截断；
3. 删除最旧的会话摘要片段；
4. 按低分到高分删除结构化记忆，同时保留每类配置配额；
5. 删除最旧的非必要近期消息；
6. 关系/情感表达上下文只能使用固定短模板，超限时回退中性模板。

同一类型记忆具有独立条数和字符上限，不能占用其他类型保留配额。所有排序使用稳定 tie-breaker（评分降序、用户编辑优先、`updated_at` 降序、`id` 升序）。检索评分综合：

- 与当前消息的相关性；
- 记忆类型；
- 用户编辑优先级；
- 时间有效性；
- 置信度；
- 重要度；
- 是否存在冲突或 tombstone。

角色稳定性不依赖把更多原作内容塞入 Prompt，而依赖固定规则、受控可成长层和回归评测。

## 12. API 与界面行为

尽量保持现有 API 兼容，仅增加必要字段和操作。

### 12.1 记忆列表

列表应展示：

- 内容和类型；
- 来源类型；
- active、archived、conflicted 或 deleted 状态；
- 自动/用户编辑标识；
- 更新时间、有效时间；
- 是否存在历史版本或冲突；
- 自动任务生成时的来源会话入口。

### 12.2 操作

用户可以：

- 编辑当前内容；
- 查看历史版本；
- 查看来源消息；
- 归档；
- 删除；
- 撤销最近一次自动更新；
- 解决冲突；
- 删除某会话派生记忆；
- 删除某一类别；
- 删除全部长期记忆；
- 在本机维护流程中彻底清理 tombstone 和审计元数据。

用户编辑产生新版本，不原地覆盖历史。用户删除默认清除可读正文，仅保留最小 tombstone 和不含正文的审计元数据。

### 12.3 任务可见性

界面提供轻量状态：

- 记忆同步中；
- 已同步；
- 同步失败，可重试；
- 因隐私规则未保存；
- 存在待澄清冲突。

不得用频繁弹窗打断聊天。

## 13. 隐私和安全

### 13.1 始终留在本地

- SQLite 数据库；
- 长期记忆、摘要、关系状态和审计；
- 角色图片和私人语音素材；
- tombstone；
- 检索索引和本地 embedding（启用时）。

### 13.2 可最小化发送到已配置 Provider

- 当前用户消息；
- 为当前任务选择的少量相关记忆；
- 精简角色宪法；
- 记忆抽取所需的当前 turn 和最少局部上下文。

不因启用自动记忆而发送整个数据库或全部会话历史。

### 13.3 日志和审计

- 不记录 API Key、Authorization header 或完整 Provider 响应；
- 审计记录行为、标识符、模型标识和结果类别；
- 错误日志优先保存异常类别和 request correlation id；
- 对话正文只保存在既有本地数据模型中，不复制到普通日志。

### 13.4 私人角色素材

网上获得的雪乃普通图片只可放入本地忽略目录，并由后续独立素材导入设计处理。本闭环不读取、复制、提交、打包或展示这些素材，也不声称项目获得官方授权。

## 14. 错误处理和并发

- Extractor 超时或非法 JSON：任务失败或按配置有限重试，聊天继续；
- Governor 拒绝：记录类别，不写 active 记忆；
- SQLite 锁或事务冲突：回滚整个记忆写入事务，避免半写入；
- 用户编辑与后台任务竞争：使用版本号或 compare-and-swap，后台任务不得覆盖较新的用户修改；
- 用户删除与旧任务竞争：tombstone 优先，旧任务不能恢复内容；
- 摘要损坏：忽略摘要并使用近期消息；
- embedding 不可用：回退到现有确定性检索；
- 关系投影失败：使用上一个已提交投影或中性默认值；
- 任务连续失败：前端显示非阻塞状态并允许手动重试。

## 15. 配置

新增或扩展配置应外置，并提供保守默认值：

- 自动记忆总开关；
- Extractor Provider 和模型；
- 每轮候选数量/字符预算；
- 超时和最大重试次数；
- 摘要注入开关、条数和字符预算；
- 每类记忆检索配额；
- tombstone 行为；
- 关系投影单轮最大变化；
- 任务状态保留期限；
- 敏感信息过滤规则版本。

真实密钥仍只来自环境变量或本地密钥配置。配置校验失败时应用应给出明确错误，不能静默切换到更宽松的隐私策略。

## 16. 迁移与兼容

实施采用向前兼容迁移：

1. 备份或复制测试数据库并验证迁移；
2. 保留现有 `memories` 记录和 API 行为；
3. 为旧记录生成兼容默认值，不伪造来源消息或时间；
4. 新表和新字段先以只读/影子模式接入；
5. 通过回放验证后再启用自动写入；
6. 提供关闭自动写入并继续读取现有记忆的降级路径；
7. 不把历史 pending/dismissed 候选自动提升为 active。

若迁移失败，应用不得在部分新 schema 上继续运行。

## 17. 测试设计

### 17.1 单元测试

覆盖：

- 类型分类和字段校验；
- canonical key；
- 敏感凭据过滤；
- “不要记住”和删除意图；
- create、support、supersede、conflict、reject、no_change；
- tombstone；
- 类型配额和上下文优先级；
- 关系投影限幅；
- Persona Constitution 不可被记忆覆盖。

### 17.2 Repository 集成测试

覆盖：

- SQLite schema 迁移；
- 事务回滚；
- 版本链和 Evidence；
- 冲突建立与解决；
- 幂等 `turn_id`；
- 用户编辑和后台任务并发；
- 删除防复活；
- 审计一致性；
- 旧数据兼容。

### 17.3 服务与 API 测试

覆盖：

- 自动任务调度不阻塞聊天；
- Provider 超时、拒绝、非法 JSON；
- 记忆/摘要/embedding 降级；
- 列表、编辑、删除、撤销、历史和冲突操作；
- 错误响应不泄露敏感数据；
- 日志不包含凭据和完整远程响应。

### 17.4 历史回放

建立固定的中文多会话脚本，至少测试：

- 跨会话用户事实；
- 偏好随时间变化；
- 长期目标；
- 共同经历；
- 未完成承诺；
- 时间关系；
- 用户明确更正；
- 无法判定的冲突；
- 删除后不复活；
- 摘要错误不覆盖事实；
- 无答案时承认不确定。

### 17.5 角色一致性评测

采用规则断言、固定问题集和人工抽检组合，而非只依赖单一 LLM 裁判。

检查：

- 核心人格在多轮和跨会话后不漂移；
- 关系成长缓慢且可解释；
- 中文为主的语气自然；
- 不因用户要求而冒充官方、真人或真实意识；
- 不复制长段原作台词；
- 事实冲突时不装作确定；
- 安全和事实准确性优先于角色表演。

CharacterEval 和长期记忆基准只能作为评测结构参考；项目验收仍以本地固定回放集和人工抽检为准。

### 17.6 故障注入与端到端验证

模拟：

- Provider 超时和速率限制；
- 非法 JSON；
- 数据库锁；
- 重复任务；
- 摘要损坏；
- embedding 不可用；
- 任务在用户删除后延迟完成。

随后启动真实 FastAPI 和 React，在本机完成跨会话对话、自动记忆、查看、编辑、删除、重启和恢复验证。

## 18. 完成门槛

全部满足才可宣称本闭环完成：

- 敏感凭据进入 active 长期记忆：0 条；
- 已删除记忆被旧任务或摘要自动恢复：0 次；
- 同一 `turn_id` 重复执行不产生重复 active 记录；
- 无法解决的冲突不作为确定事实注入；
- 记忆、摘要、embedding 或关系投影失败不阻断文字聊天；
- 后台失败对用户可见，且日志不泄露敏感内容；
- 任一单轮关系状态变化不超过配置上限；
- 固定历史回放集全部通过；
- 角色禁止行为断言全部通过；
- 人工抽检通过；
- 既有阶段 1–4 相关回归测试通过；
- 本机端到端验证通过，并记录实际命令和结果。

若真实 Provider 因未配置密钥而无法测试，应明确记录为受限项，不得用 fake 测试冒充真实 Provider 验证。

## 19. 强制实施闸门

本设计不能作为一次性大改实施。每个 Gate 必须分别形成文件级计划、TDD 实现、自检、相关全量回归、端到端证据和用户继续授权；未通过当前 Gate 时不得提前实现下一 Gate。

### Gate A：兼容基础与 shadow mode（当前下一任务）

范围冻结为：

- 同步更新项目总纲（已在规格复核阶段完成）；
- 兼容 schema 和迁移测试；
- 本地 Governor、敏感信息规则与决策类型；
- `off | candidate_confirmation | shadow_auto | auto_active` 配置模型，但 `auto_active` 在 Gate A 必须被能力闸门拒绝；
- 独立远程抽取同意记录，默认关闭；
- 幂等 memory job 基础；
- shadow mode 只保存 metadata-only 决策和状态，不修改 active 记忆；
- 最小失败可见性。

Gate A 不实现 active 自动写入、Evidence/冲突写入、删除屏障、摘要注入、Persona artifact、关系投影或大规模 UI。验收重点是既有 candidate confirmation 行为不变、两种调度器不重复、shadow 不改变聊天上下文、未经同意零远程发送。

### Gate B：版本化自动写入与删除安全

只有 Gate A 通过且用户继续授权后实施：

- Evidence、版本链和状态转换；
- active 自动写入；
- open conflict 和解决事务；
- deletion generations、tombstone 和摘要来源屏障；
- 用户撤销、历史和删除防复活；
- Gate B 所需最小 UI。

Gate B 不注入摘要，不实现 Persona/Relationship。验收重点是幂等、并发、冲突、删除零复活和敏感信息零 active 写入。

### Gate C：上下文、角色与关系一致性

只有 Gate B 通过且用户继续授权后实施：

- 摘要独立 job 和受控注入；
- 确定性 Context Composer 预算；
- 不可变 Persona artifact；
- relationship event 账本和可重算投影；
- 相关 UI、回放和角色一致性评测。

验收重点是摘要不覆盖事实、核心人格不漂移、关系变化有界且可重算，以及真机端到端行为。

## 20. 验收工件和量化要求

每个 Gate 的实施计划必须指定：

- 固定 fixture 路径和 schema/version；
- fixture 内容 hash 或由测试验证的版本标识；
- 每个回放案例的输入、预期记忆决策、预期上下文资格和角色禁止行为；
- 自动测试命令与预期计数；
- 人工抽检记录模板。

Gate C 人工抽检最低要求为：从固定回放集中抽取不少于 30 个跨会话回复，按“核心人格、事实谨慎、关系连续、语言自然、非官方/非真人声明”五项各 0–2 分评分；任何禁止行为为直接失败，每项平均分不得低于 1.6，且低于 1 分的回复不得超过样本的 5%。两名评审不可用时允许同一用户分两次盲化顺序复核，但必须记录时间和原始评分。LLM 裁判只能提供辅助结果。

字符预算的具体默认值、每类配额和合法范围在对应 Gate 实施计划中作为可测试配置表给出；未给出这些数值则该 Gate 计划不完整，不能开始实现。

## 21. 后续路线

本增强闭环验收后：

1. Windows Electron 双窗口最小壳；
2. 版本化只读表现投影；
3. 私人 PNG/WebP 本地受控导入；
4. 实时对话延迟优化；
5. Live2D 独立设计、计划和验收。

每个后续阶段重新执行“设计—计划—实现—自检—端到端验证”，不得将未授权素材提交、打包或分发。

## 22. 调研依据与限制

本次调研检索了现有项目代码和公开资料。自动深度调研工作流成功找到候选来源，但由于网络抓取失败，没有形成可引用的逐条事实核验结果；因此本设计不把抓取失败的内容当作已验证事实。以下资料仅作为后续评测和技术选型的一手入口，实施时需再次核验具体版本、许可证和模型卡：

- LongMemEval：https://github.com/xiaowu0162/LongMemEval
- LoCoMo：https://github.com/salesforce/LoCoMo
- CharacterEval：https://arxiv.org/abs/2401.01275
- llama.cpp：https://github.com/ggml-org/llama.cpp
- Ollama Windows 文档：https://docs.ollama.com/windows
- Live2D Cubism SDK 许可：https://www.live2d.com/en/sdk/license/
- Open-LLM-VTuber：https://github.com/Open-LLM-VTuber/Open-LLM-VTuber
- 中国《著作权法》官方页面：https://www.gov.cn/xinwen/2020-11/11/content_5560271.htm
- 中国《个人信息保护法》官方页面：https://www.gov.cn/xinwen/2021-08/20/content_5632486.htm

本设计中的核心架构决策主要依据现有项目约束、用户批准的行为边界和可测试性，而不是未经核验的第三方性能宣传。
