# Stage 4B Emotion Text Expression Loop

Status: VERIFIED PASS on 2026-07-13.

## Scope

Stage 4B 将已提交的 Stage 4A 情感快照转换成短小、确定性的离散表达策略，并作为独立 system message 注入聊天 Provider payload。没有远程情感 LLM、consent、ExpressionPlan、TTS 或桌面资源改动。

## Formatter

`EmotionContextFormatter` 对六维状态使用低/中/高离散标签，相同 state 输出相同文本；disabled 返回 None。固定安全文本声明这是表达策略而非真实感情或意识，不能改变事实、安全、用户明确指令或角色边界。输出限制 500 字符，不发送浮点 dump、用户文本或记忆正文。

## Context and Timing

Provider payload 顺序为角色主 Prompt、emotion expression、memory、history/current user。当前请求读取此前已提交 snapshot；assistant 成功持久化后既有 updater 才更新状态，因此本轮变化从下一轮生效。reader/formatter/updater 失败均不破坏聊天。

## Character Budget

ChatService 使用显式 `protected_system_messages` 保护 emotion context。超限先移除最老 user/assistant history，再移除未保护 system context（memory）。角色主 Prompt、emotion 和当前 user 始终保留；仅保护项仍超限时允许硬溢出。

## Validation

2026-07-13 新鲜结果：

```text
Formatter/ContextBuilder/ChatService/API focused: 53 passed in 2.61s
Full backend: 433 passed in 18.75s
Frontend Vitest: 19 files, 165 tests passed in 10.71s
TypeScript typecheck: PASS
Vite build: 37 modules, 114ms
Complete Playwright E2E: 8 passed in 11.4s
```

## Security and Boundaries

- expression context 不持久化到 messages/memories/summaries；
- `sqlite:///:memory:` 现被配置和连接层明确拒绝，因为 FastAPI 的多个 request-scoped repository connection 无法共享普通内存数据库；测试和运行时必须使用唯一临时 SQLite 文件；
- 不改变静态角色 Prompt；
- 不调用远程情感分析；
- 不改变 ChatResponse 或 TTS；
- disabled 时不注入 baseline/关闭说明；
- 安全、事实和用户指令优先级写入固定 context。

## Limitations

Stage 4B 不验证 LLM 对离散表达标签的主观质量；真实 Provider 的角色一致性需要后续专门评估。尚未实现 4C LLM 辅助分析、consent、4D ExpressionPlan/TTS 或桌面表现。

## Decision

Stage 4B text expression loop: PASS. Stage 4 remains IMPLEMENTING.

## Next Minimal Task

Stage 4C LLM 辅助情感分析与 consent 设计：首次明确授权、独立 Provider 配置、近期对话与相关 active memory 的预算/脱敏、严格 JSON、规则 fallback 和费用/故障隔离。
