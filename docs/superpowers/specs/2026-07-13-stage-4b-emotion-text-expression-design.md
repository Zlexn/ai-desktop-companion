# Stage 4B Emotion Text Expression Loop Design

> 日期：2026-07-13  
> 状态：设计已批准  
> 前置：Stage 4A 本地情感状态基础已完成

## 1. 目标

把 Stage 4A 已提交的全局六维情感快照转换成短小、确定性、不可越权的文本表达策略，并作为独立 system message 注入聊天 Provider payload。当前请求只使用请求开始时已提交的快照；本轮 user/assistant 成功持久化后更新状态，从下一轮开始生效。

Stage 4B 不实现远程情感 LLM、consent、ExpressionPlan、TTS 情感参数、Live2D、桌面壳或角色素材。

## 2. 采用方案

采用 ContextBuilder 内聚方案：

- `EmotionSnapshotReader` 提供只读已提交状态；
- `EmotionContextFormatter` 将状态映射为有限离散标签；
- `ContextBuilder` 生成 emotion → memory → recent history；
- `ChatService` 组装角色主 Prompt 并通过显式优先级裁剪；
- 既有 assistant 持久化后 emotion updater 保持不变。

不采用通用 `ChatContextBundle`，避免为当前最小切片建立过度泛化框架；不在 ChatService 中直接访问 SQLite；不修改静态角色 Prompt 模板来承载动态状态。

## 3. Formatter

输入：`EmotionState`。输出：`str | None`。

- `enabled=false` 返回 `None`。
- 六维使用离散标签，不发送浮点数。
- 相同 state 产生完全相同文本。
- 输出使用固定模板和严格长度上限。
- 不读取 user text、memory、summary、Provider response 或外部服务。

分桶：

```text
0.00–0.33 → 低
0.34–0.66 → 中
0.67–1.00 → 高
```

表达维度示例：

- mood：严肃低沉 / 平稳 / 明快
- trust：保持谨慎 / 适度信任 / 较为信赖
- concern：平静 / 适度关切 / 高度关切
- distance：较为亲近 / 距离适中 / 保持距离
- irritation：平和 / 略有不悦 / 明显不悦但保持克制
- formality：自然 / 克制得体 / 正式

固定安全边界：这是表达策略而非真实感情或意识；不得改变安全、事实、用户明确指令或角色边界；不得情感勒索、敌意报复、无依据相信信息或做医疗诊断。

## 4. 数据流和时序

```text
persist current user
→ reader.get_state(apply_decay=True)
→ formatter.format(snapshot)
→ ContextBuilder: emotion, memory, history/current user
→ ChatService budget
→ provider.generate
→ persist assistant
→ existing local emotion updater
→ next request observes updated snapshot
```

本轮用户内容导致的状态 transition 不影响同一轮回复。Provider 失败/空回复不触发 transition。post-turn updater 失败不破坏回复。

## 5. ContextBuilder 边界

新增：

```python
class EmotionSnapshotReader(Protocol):
    def get_state(self, *, apply_decay: bool = True) -> EmotionState: ...

class EmotionContextFormatter(Protocol):
    def format(self, state: EmotionState) -> str | None: ...
```

`ContextBuilder.build_context()` 返回：

```text
emotion system message（可选）
memory system message（可选）
recent user/assistant messages
```

reader 或 formatter 抛出任何异常时，emotion context 退化为空，memory/history 仍正常。ContextBuilder 不知道 SQLite、scope、CAS、规则或 Provider。

## 6. 字符预算

最终优先级：

```text
角色主 System Prompt
> 当前 user message
> emotion expression context
> memory context
> old history
```

裁剪顺序：

1. 最老 user/assistant history；
2. memory system context；
3. 其他非保护 system context。

始终保留角色主 Prompt、当前 user 和成功生成的 emotion context。仅这三项超预算时允许硬溢出，不截断内容。Formatter 必须保持短小，避免无界增长。

预算实现必须使用显式保护信息，不能依赖“emotion 恰好位于列表第几个”的隐式约定。

## 7. 故障隔离

- emotion read failure → 无 emotion context，聊天继续；
- formatter failure/空输出 → 无 emotion context，聊天继续；
- memory retrieval failure继续沿用既有 fallback；
- Provider failure保持既有错误语义，不更新 emotion；
- updater failure不撤回 assistant；
- disabled state不注入“已关闭”或 baseline 文本；
- 不将 expression context 持久化为 message/memory/summary。

## 8. 测试

Formatter：低中高映射、确定性、长度、安全边界、disabled、无浮点 dump。

ContextBuilder：emotion→memory→history 顺序；disabled；reader/formatter fault isolation；无持久化副作用。

ChatService：第一轮旧快照、第二轮新快照；Provider failure 不更新；updater failure不丢回复；Provider payload 顺序。

Budget：先删 history，再删 memory，保留 emotion；protected-only 超限硬溢出；无 emotion 时既有行为不变。

验收：focused/full backend、recording provider payload、frontend/full E2E、隔离 SQLite runtime；确认无远程情感调用、无 TTS 改动。

## 9. 完成标准

1. enabled 快照以离散表达 system message 进入当前 Provider payload；
2. disabled/failure 时不注入且聊天成功；
3. 当前快照影响当前回复，本轮 update 从下一轮生效；
4. budget 明确保留 emotion 高于 memory/history；
5. expression 不覆盖安全/事实/用户指令；
6. 不持久化 expression context；
7. 后端、前端、E2E、隔离 runtime 全部通过；
8. Stage 4 保持 IMPLEMENTING，下一步为 4C LLM 辅助分析设计。
