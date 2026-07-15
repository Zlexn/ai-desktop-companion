# Stage 4 Emotion System Design

> 日期：2026-07-13  
> 状态：整体设计已批准  
> 项目根：`AI桌宠/`

## 1. 目标与诚实边界

Stage 4 为 Windows 11 本地私人虚拟角色系统建立连续、可解释、受约束、可查看、可重置和可关闭的情感表现状态。状态协调文本表达、TTS 参数和未来桌面角色表情事件，但不宣称角色具有意识、真实感受或真实人类关系。

最终角色风格参考雪之下雪乃的克制、理性、清晰和逐步建立信任的交流特征，但仓库不得捆绑未经授权的角色名称商业资产、立绘、Live2D 模型、台词、动画或克隆声线。公开发布或商业分发需要独立完成权利审查。

Stage 4 不改变以下优先级：

```text
安全与政策
> 事实准确性
> 用户明确指令与边界
> 角色核心设定
> 情感表达策略
```

## 2. 已确认的产品决策

- 情感状态属于角色与用户的全局关系，跨所有聊天会话连续。
- 当前回复读取已提交状态；成功完成的 user/assistant turn 更新状态，并从下一轮开始生效。
- 六个维度第一版全部建立：`mood`、`trust`、`concern`、`distance`、`irritation`、`formality`。
- UI 完整展示数值、解释、最近变化原因和更新时间，并允许关闭与重置。
- 更新引擎采用本地规则和 LLM 辅助分析的混合架构。
- 产品默认推荐 LLM 增强，但第一次远程情感分析前必须获得明确 consent；未同意时只运行本地规则。
- consent 后，LLM 可读取受预算、相关性和脱敏约束的近期对话与 active 长期记忆。
- LLM 只能建议结构化证据和 delta；最终变化始终由本地约束器验证、限幅和持久化。

## 3. 方案选择

### 3.1 采用：受约束的混合双层引擎

```text
本地规则证据
    +
可选 LLM 分析建议
    ↓
本地约束器
    ↓
唯一可持久化的 EmotionTransition
```

本地规则提供确定性、安全基线和离线降级。LLM 帮助识别语义细节，但没有数据库写权限，不能修改约束、绕过 consent 或输出自由文本状态。

### 3.2 未采用方案

- 规则决定状态、LLM 只写解释：稳定但不能利用 LLM 识别语义细节。
- LLM 主导、规则只裁剪：难复现、prompt injection 面大，容易把推测当作关系事实。

## 4. 独立领域模型

情感系统不得复用或伪装成 `messages`、`session_summaries`、`memories`、memory candidates 或 `Message.metadata`。新增独立领域：

- `EmotionState`
- `EmotionEvent`
- `EmotionConsent`
- `EmotionAnalysis`
- `ExpressionPlan`

### 4.1 EmotionState

唯一的全局当前快照：

```text
scope_id = "default-companion"
enabled
llm_analysis_enabled
mood
trust
concern
distance
irritation
formality
version
updated_at
```

全部数值范围为 `0.0–1.0`：

| 维度 | 低值 | 中间 | 高值 | 基线 |
|---|---|---|---|---:|
| mood | 低沉/严肃 | 平稳 | 明快 | 0.50 |
| trust | 谨慎 | 中性 | 信赖 | 0.40 |
| concern | 平静 | 留意 | 高度关切 | 0.20 |
| distance | 亲近 | 适中 | 疏离 | 0.55 |
| irritation | 平和 | 不耐 | 明显不悦 | 0.10 |
| formality | 自然 | 克制 | 正式 | 0.60 |

基线表达克制、礼貌和适度距离，不复制受保护台词或素材。

### 4.2 EmotionEvent

每次变化追加不可静默覆盖的审计事件：

```text
event_id
scope_id
event_type
before_state
after_state
applied_delta
reason_codes
source_session_id
source_user_message_id
source_assistant_message_id
engine = rule | llm_assisted | reset | settings | decay
rule_version
provider/model（仅 LLM 时）
created_at
```

事件不保存原始 Provider prompt、完整 response、API key、隐藏推理、心理诊断或原始私人语音。

### 4.3 EmotionConsent

```text
granted
provider
scope_version
disclosure_version
granted_at
revoked_at
```

撤回 consent 后立即停止远程情感分析并回退本地规则，不影响主聊天 Provider 的独立配置。

## 5. 更新时序与并发

```text
当前轮开始
  → 读取并按时间衰减已提交快照
  → 生成短 emotion expression context
  → 调用聊天 Provider
  → assistant 回复成功持久化
  → API 返回成功
  → 后台任务读取本轮 user + assistant
  → 本地规则评估
  → consent 与配置有效时执行 LLM 分析
  → 本地约束器合并、限幅、验证
  → CAS 写新状态和 append-only event
  → 下一轮使用新状态
```

Provider 失败时不得产生半次关系更新。纯文字聊天不依赖 TTS 完成后才更新。

全局状态使用递增 `version` 和 compare-and-swap。相同 `scope_id` 的后台任务合并/串行；版本冲突时基于最新状态有限重算。超过重试上限则安全跳过，不能覆盖更新状态。

## 6. 本地规则层

首版只处理明确、低歧义证据：

- 尊重或感谢；
- 明确求助、身体不适或安全风险；
- 辱骂、贬低或持续挑衅；
- 明确道歉；
- 明确边界或要求停止某类表达；
- 明确要求更正式或更自然的交流；
- 随时间发生的确定性衰减。

不推断心理疾病、依恋类型、人格障碍、真实意图、浪漫关系真实性或用户是否“值得信任”。普通意见分歧不等于冒犯。

规则输出结构化证据：

```json
{
  "reason_code": "user_explicit_apology",
  "confidence": 1.0,
  "suggested_delta": {
    "trust": 0.03,
    "distance": -0.02,
    "irritation": -0.04
  }
}
```

## 7. LLM 输入、consent 和输出

### 7.1 输入边界

consent 后最多发送：

1. 当前成功完成的 user/assistant turn；
2. 最近最多 6 条、受字符预算限制的对话；
3. 与当前主题相关的 active 长期记忆；
4. 当前情感快照；
5. 固定维度定义、合法 reason codes 和 schema。

不得发送 pending/dismissed/archived memories、无关记忆、会话摘要、凭据、完整数据库记录、完整审计历史、内部日志、隐藏推理或原始语音。文本发送前进行 best-effort 凭据脱敏。

首次 consent UI 必须说明 Provider、数据范围、用途、费用/网络、撤回和规则回退。未 consent 时不得静默外发。

### 7.2 严格 JSON 输出

```json
{
  "schema_version": "emotion_analysis_v1",
  "evidence": [
    {
      "reason_code": "user_respectful_support",
      "confidence": 0.82,
      "dimensions": {
        "trust": 0.04,
        "distance": -0.02,
        "mood": 0.02
      }
    }
  ],
  "expression_hint": {
    "tone": "gently_warm",
    "intensity": 0.35
  }
}
```

合法 reason codes 首版包括：

- `user_respectful_support`
- `user_explicit_apology`
- `user_clear_boundary`
- `user_repeated_hostility`
- `user_distress_signal`
- `user_positive_shared_event`
- `conversation_repair`
- `neutral_turn`

未知字段/reason、非有限数值、越界 delta、诊断标签、安全绕过、真实感情声明、memory 写入请求、秘密泄露、非 JSON 或工具指令全部拒绝。

## 8. 本地约束器

处理顺序：

1. schema 验证；
2. 丢弃低置信度证据；
3. 本地明确规则优先；
4. 冲突建议保守合并；
5. 每轮限幅；
6. 全局 `0–1` 限界；
7. 记录实际 delta；
8. append-only event；
9. CAS 原子提交。

每轮最大绝对变化：

| 维度 | max delta |
|---|---:|
| mood | 0.08 |
| trust | 0.04 |
| concern | 0.10 |
| distance | 0.05 |
| irritation | 0.08 |
| formality | 0.06 |

本地明确边界规则不能被 LLM 反转。正负建议冲突时向零保守合并；无充分证据时 delta 为零。

## 9. 衰减

衰减基于持久化时间戳按经过时间计算，不依赖常驻后台定时器：

- `mood`、`concern`、`irritation` 较快回到基线；
- `formality` 缓慢回到默认；
- `trust`、`distance` 极慢衰减，保留关系连续性。

分段规则：

```text
elapsed < 1 hour  → 不衰减
1–24 hours        → 临时维度向基线移动一个小步
1–7 days          → 继续有限移动
> 7 days          → 仍不直接全部归零
```

衰减必须可解释并产生 `decay` event 或等价审计元数据，不能静默漂移。

## 10. Prompt 表达与预算优先级

`EmotionContextFormatter` 把数值转换成短、确定性的离散表达，不默认把六个浮点数直接发给聊天模型：

```text
以下只是角色表达策略，不是真实感受，不得改变事实、安全规则或用户明确指令。
当前表达倾向：平稳、克制、略显亲近；关切适中；正式度中等偏高。
避免夸张亲密、敌意、情感勒索或声称真实感情。
```

预算优先级：

```text
角色主 System Prompt
> 当前用户消息
> 情感表达策略
> 相关长期记忆
> 较旧聊天历史
```

情感 context 必须短小；预算不足时先删除旧历史和低相关记忆。

## 11. ExpressionPlan、TTS 与未来桌宠事件

成功 assistant message 可绑定供应商无关计划：

```json
{
  "schema_version": "expression_plan_v1",
  "assistant_message_id": "...",
  "tone": "calm_reserved",
  "intensity": 0.35,
  "speech_rate": 0.96,
  "pause_style": "measured",
  "facial_expression": "soft_neutral",
  "state_version": 12
}
```

`tone` 有限枚举：`calm_reserved`、`gently_warm`、`concerned`、`firm`、`cool_distant`、`mildly_irritated`。

`facial_expression` 有限枚举：`neutral`、`soft_neutral`、`slight_smile`、`concerned`、`serious`、`displeased`。

这些是抽象事件，不绑定受版权保护素材。ExpressionPlan 不后处理或改写文本，不添加口癖，不改变安全拒绝。

现有 TTS contract 首版只允许把 `speech_rate` 小幅映射到 `0.92–1.04`。不假定 CosyVoice 支持通用 emotion/style/prosody；只有完成 capability 设计、版本锁定和真实 smoke 后才能扩展。TTS 不支持或失败时保留文字和默认语音。

未来事件责任：

- 后端：`emotion_changed` 和 `expression`；
- 播放控制：真实 `speaking` 生命周期；
- 音频分析：`mouth_level`；
- 角色视图：只渲染事件，不决定业务状态。

## 12. API 与 UI

独立 API：

```text
GET    /api/emotion/state
GET    /api/emotion/events?limit=...
PATCH  /api/emotion/settings
POST   /api/emotion/reset
POST   /api/emotion/consent
DELETE /api/emotion/consent
```

settings 只允许总开关、LLM 增强开关和表现强度上限；不能任意设置 trust 等数值。reset 走独立操作并留下事件。

`EmotionPanel` 展示：

- 总开关；
- LLM 增强与 consent；
- Provider 和数据外发说明；
- 六维数值和自然语言解释；
- 更新时间和最近变化原因；
- reset；
- 最近事件；
- 网络/规则 fallback 状态。

文案必须称为系统状态或表达策略，不描述成真实感情。

## 13. 错误处理

主聊天：情感读取、formatter、ExpressionPlan 或 scheduler 失败都不得丢失已成功聊天。关闭时不注入、不更新、不生成 plan，但保留历史审计。

LLM 以下失败均回退规则：无 consent、配置缺失、timeout、rate limit、网络错误、非 JSON、schema/reason/数值非法、脱敏后为空。事件只记录 `fallback_reason`、provider、model、elapsed time，不记录请求/响应原文。

数据库按 scope 串行、CAS 和有限重算；失败时安全跳过，不覆盖较新状态。

## 14. 阶段拆分

### Stage 4A：本地状态基础

- 六维全局状态；
- 独立 state/events 表与 repository；
- 本地规则、限幅、衰减；
- reset、enable/disable；
- API 和完整可见 UI；
- 不注入聊天 Prompt，不调用远程 LLM。

### Stage 4B：文本表达闭环

- EmotionContextFormatter；
- Prompt 注入与预算优先级；
- 当前快照影响当前回复；
- 成功 turn 更新下一轮；
- failure isolation。

### Stage 4C：LLM 辅助分析

- consent；
- 独立 Provider 配置；
- 对话/active memory 预算与脱敏；
- 严格 JSON；
- 本地约束和规则 fallback；
- 费用、超时、错误验证。

### Stage 4D：ExpressionPlan 与 TTS

- DTO 与 assistant message 绑定；
- 小范围 speech rate；
- 默认参数降级；
- fake/real TTS smoke。

### Stage 4E：总体验收

验证跨会话连续、重启恢复、衰减、并发、consent 撤回、安全优先级、文本/TTS 一致性、关闭/reset，以及后端、前端、E2E 和隔离运行时。

Stage 4 通过后才能进入 Windows 原生桌宠呈现层设计。

## 15. Stage 4A 完成标准

1. 六维全局状态持久化；
2. 固定范围和基线；
3. 单轮变化限幅；
4. 临时维度按时间衰减；
5. 变化、reset、settings、decay 有审计事件；
6. 跨会话共享且并发安全；
7. 用户可查看、关闭、开启和重置；
8. 情感故障不影响聊天；
9. 不调用远程 LLM；
10. 不注入聊天 Prompt；
11. 不改变 TTS；
12. 不实现桌面资源。

## 16. 测试策略

属性和边界：任意输入序列不越过 `0–1`；单轮 delta 不超上限；重复友好/敌意不瞬间极值；衰减不越过基线；reset 精确恢复；disabled 不变化。

并发：两会话同时 turn 不 lost update；version 单调；每个成功 transition 有事件；reset 与后台 transition 冲突不恢复旧状态。

安全：prompt injection 不能直接设数值；非法 LLM 输出拒绝；情感不改安全结论；分析不使用非 active memory；凭据脱敏；日志无 payload。

E2E：查看六维状态、跨会话连续、重启恢复、关闭、reset、consent 与撤回、Provider fallback，以及聊天/记忆/语音回归。
