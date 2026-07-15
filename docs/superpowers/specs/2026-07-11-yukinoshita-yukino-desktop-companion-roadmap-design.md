# 雪之下雪乃 AI 桌宠总体路线设计

> 日期：2026-07-11  
> 状态：总体路线已批准；3M 专项设计和实施计划已存在，待用户复核后执行  
> 项目根：`AI桌宠/`

## 1. 目标与诚实边界

本项目最终在 Windows 11 本地部署一个可以进行实时或接近实时文字、语音交流，具有长期记忆、连续情感表现和桌面角色呈现的私人虚拟角色系统。目标角色风格参考“雪之下雪乃”，但系统只实现角色一致性、记忆和情感**表现**，不宣称角色具有意识或真实感情。

项目仓库不捆绑未经授权的角色立绘、Live2D 模型、动画资源或克隆声线。开发和自动测试使用原创、明确授权或中性占位素材；用户可在本机接入其有权使用的资源。任何公开发布或商业分发必须另行完成角色名称、形象、模型、SDK 和声音权利审查。

## 2. 已确认约束

- 目标平台：Windows 11。
- 目标硬件：Intel Core i7-12700H、约 16 GB RAM、RTX 3060 Laptop GPU（系统报告约 4 GB VRAM）。
- 运行方式：本地数据优先的混合架构。
- 本地保存：会话、消息、摘要、长期记忆、情感状态、配置与审计记录。
- 主对话：继续使用可替换的远程 LLM Provider，以优先保证角色一致性和回复质量。
- 离线降级：保留 llama.cpp/Qwen3 等轻量本地模型的适配入口，但不把未实测的 8B 模型性能写成承诺。
- ASR/TTS：保留现有 Provider 抽象和已实现路径；所有替换必须先在目标机器基准测试。
- 工程原则：沿用 React、TypeScript、Vite、FastAPI、Python 和 SQLite，不无理由迁移或重写。
- 阶段原则：遵守 `CLAUDE.md` 的阶段顺序；阶段 3 验收前不实现阶段 4，阶段 4 验收前不扩张桌宠表现层。

## 3. 方案比较与结论

### 方案 A：沿现有架构逐阶段收敛（采用）

顺序为：完成 3M → 阶段 3 总体验收 → 阶段 4 情感系统 → 原生桌宠呈现。

优点：保护现有未提交工作，复用已验证的聊天、语音和记忆能力；每一步可独立测试、回滚和验收；符合固定阶段顺序；适合当前硬件。缺点：看到完整桌宠外观的时间晚于“先做壳”路线。

### 方案 B：先封装桌面壳

先增加透明窗口、托盘和角色动画，再回补摘要与情感。优点是视觉进展快；缺点是会越过当前阶段边界，把尚未稳定的内核和 UI 生命周期绑定，增加返工，因此不采用。

### 方案 C：立即改成全本地模型栈

主 LLM、ASR、TTS 全部本地化。优点是断网可用、数据不外发；缺点是 16 GB RAM 与约 4 GB VRAM 很难同时保证主模型、流式 ASR、情感 TTS 和角色渲染的质量与延迟，且会打断现有架构，因此只保留为后续可测降级路径。

## 4. 总体阶段路线

### 4.1 第一子项目：3M 自动会话摘要

完成“自动、非阻塞、增量、append-only 的会话连续性摘要生成”，但暂不把摘要注入聊天上下文。

3M 的实现级契约以以下文件为唯一详细事实来源：

- [3M 专项设计](2026-07-10-stage-3m-session-summary-generation-design.md)
- [3M 实施计划](../plans/2026-07-11-stage-3m-session-summary-generation.md)

当前用户工作树已完成配置、Provider Factory、DeepSeek 独立参数、sanitizer、Fake/LLM Summary Provider、`SessionSummaryService` 及相应测试。它们是用户的未提交 WIP，后续不得 reset、checkout、机械重做或覆盖。

尚缺的最小闭环：

1. 轻量 in-process scheduler；
2. `ChatService` 在 assistant 消息持久化后调度；
3. 依赖注入层使用 fresh SQLite connection 执行后台 job；
4. 非阻塞、失败隔离和 API composition 测试；
5. fake Provider 的运行时 smoke、验证证据和阶段文档。

3M 完成后进行阶段 3 总体验收。摘要注入、自动冲突解决或摘要 UI 均是后续独立设计，不属于 3M。

### 4.2 第二子项目：阶段 4 情感系统

建立可解释、受约束、可关闭和可重置的状态模型，至少覆盖 `mood`、`trust`、`concern`、`distance`、`irritation`、`formality`。

情感状态更新必须：

- 有明确原因和来源；
- 有上下限、衰减和单轮变化限制；
- 不覆盖安全、事实准确性或用户明确指令；
- 与长期记忆分开存储；
- 协调文本表达、TTS 参数和角色表情事件；
- 允许用户查看、重置和关闭。

阶段 4 必须另写详细设计，不在本规格中预先实现数据公式或 UI。

### 4.3 第三子项目：原生桌宠呈现

在保留现有 React/FastAPI 内核的前提下增加 Windows 桌面壳，目标包括透明置顶窗口、系统托盘、可配置点击穿透、拖动、显示/隐藏、字幕、口型和表情事件。

Live2D Cubism、其他 2D 引擎或自研动画层需在该阶段单独比较许可证、Windows 支持、资源占用和打包方式。正式目标角色素材必须在本地合法提供；自动化测试继续使用占位角色。

## 5. 组件边界

### 5.1 前端与桌面层

现有 React 应用负责会话、消息、录音、播放、设备选择和记忆面板。未来桌面壳只承载窗口与系统集成，不重新实现聊天、语音或记忆业务。事件责任固定为：后端负责可审计的情感状态与表达计划；前端或桌面播放器负责实际 `speaking` 生命周期和由音频得到的 `mouth_level`；角色视图只消费已定义的 `emotion_changed`、`expression`、`speaking` 和 `mouth_level` 表现事件。事件协议、频率和断连降级由桌宠专项设计确定。

### 5.2 本地后端

FastAPI 是唯一业务编排边界，负责：

- 角色 Prompt 与上下文组装；
- LLM Provider 调用；
- 消息持久化；
- 长期记忆检索和候选管理；
- 会话摘要调度；
- 未来情感状态更新与表达计划；
- ASR/TTS Provider 适配；
- 错误隔离、配置和审计。

Provider SDK 不得散布到 UI 或通用业务层。

### 5.3 持久化

SQLite 继续分别存储聊天消息、会话摘要、长期记忆、候选、embedding、审计以及未来情感状态。摘要、记忆和情感状态不得互相伪装；每类数据都有来源、时间和删除或重置路径。

### 5.4 模型与语音 Provider

- 主 LLM：现有 Anthropic/DeepSeek 适配器与 fake 测试路径。
- 本地 LLM 候选：Qwen3 + llama.cpp，须锁定版本并实测；Qwen3-8B Q4_K_M 约 5.03 GB 仅是权重文件体积，不代表总 RAM/VRAM。
- 当前 ASR：Faster-Whisper；后续候选包括 sherpa-onnx、FunASR 和 SenseVoice。
- 当前 TTS：CosyVoice HTTP；后续以自然度、情感可辨识度、首包延迟和稳定性实测，不采用未经本机复现的“150 ms”宣传数字。

## 6. 数据流

### 6.1 同步对话路径

1. 用户输入文本，或麦克风音频经 ASR 转成标准文本。
2. 后端读取 active 长期记忆和近期 user/assistant 消息。
3. Context Builder 构造角色上下文并调用当前 LLM Provider。
4. 成功回复持久化为 assistant 消息。
5. API 返回文本；TTS 合成并播放，角色视图消费说话和口型事件。

同步路径必须快速成功或返回明确错误。摘要、记忆候选和未来情感更新不得让已经成功生成并持久化的回复丢失。

### 6.2 异步增强路径

- 达到阈值时，3M 生成一条增量会话摘要；
- 从当前用户消息抽取 pending 记忆候选，等待用户确认；
- 阶段 4 根据可审计规则更新有界情感状态；
- 后台失败不得阻塞聊天或污染其他表；若现有安全日志能力可用，只记录最小化、脱敏诊断。

### 6.3 数据外发边界

仅向选定的远程 Provider 发送生成当前任务所需的最小文本上下文。摘要 Provider 使用独立显式配置；默认 fake/offline。输入和输出进行 best-effort credential redaction，但该机制不宣称完整 DLP。私人语音、密钥和未授权素材不得进入仓库。

## 7. 3M 的总体路线边界

总体路线只锁定以下不可违反约束：

- 3M 生成自动、非阻塞、增量、append-only 的会话连续性摘要；
- 输入来自已持久化的 user/assistant 消息，输出只写独立 `session_summaries` 存储；
- 摘要不得写成 message、memory、candidate 或 embedding，也不得进入下一轮聊天 Prompt；
- assistant 消息成功持久化后才允许调度，聊天路径不得等待摘要 Provider 或落库；
- 后台工作使用独立数据库连接，失败不得反向破坏成功聊天；
- 默认 fake/offline，真实摘要 LLM 必须显式启用；
- 进程退出时允许尚未完成的 best-effort 摘要丢失，但不得损坏已提交事务；
- 3M 不新增日志或审计基础设施；若复用现有安全日志，只记录最小化、脱敏诊断。

消息排序、coverage 算法、连接生命周期、竞争写处理、Provider 适配和精确测试契约均以 3M 专项设计及实施计划为准，避免三份文档形成相互漂移的事实来源。

## 8. 错误处理

| 失败点 | 规定行为 |
|---|---|
| Chat Provider | 返回明确聊天错误，不调度摘要，不伪造 assistant 成功消息 |
| Scheduler 调度 | 吸收失败；若复用现有安全日志，只记录最小化、脱敏诊断；已持久化回复照常返回 |
| Background job | wrapper 吸收异常并清理 task registry；3M 不新增日志基础设施 |
| Summary Provider/超时 | 不写部分记录，不影响聊天 |
| Provider 空白或脱敏后为空 | 安全跳过 |
| SQLite 竞争写 | insert 前 recheck，重叠 coverage 作为 benign skip |
| Summary persistence | 记录失败，不反向破坏已成功聊天 |
| TTS/播放 | 保留文本回复，允许重试或静音降级 |
| ASR | 保留用户可编辑/重录路径，不自动发送不可信转写 |
| 应用退出 | 允许 best-effort 后台摘要丢失；不得损坏已提交事务 |

日志和 diagnostics 不得包含 API Key、原始凭据或任意 Provider payload。

## 9. 测试与验收

### 9.1 3M 完成标准

只有同时观察到以下事实，3M 才能标记完成：

1. 成功 chat 请求先返回 HTTP 200，user/assistant 消息已经持久化；
2. 达到阈值并显式 drain 后产生恰好一条 generated summary；
3. coverage start/end ID 和 message count 精确；
4. 无新消息时不重复生成；
5. 竞争情况下不产生明显重叠 coverage；
6. fake 默认零网络；
7. Provider、scheduler 和 persistence 失败不改变成功聊天结果；
8. memories/candidates/embeddings 没有因 summary 改变；
9. 下一次 Chat Provider 上下文不包含 summary；
10. recording/mock LLM adapter 证明 Bearer token、API key、password 等原文不会进入外部摘要请求，Provider 输出在持久化前再次脱敏，metadata/diagnostics 不保存原始 Prompt 或任意 Provider payload；
11. focused tests、完整后端测试和 fake API smoke 留有实际结果；
12. 已知 `test_chat_service_prunes_old_history_before_provider_when_context_is_large` 基线失败需重新确认并与新回归区分，不为追求全绿做无关重构；
13. 通过代码审查和端到端运行验证后，才更新阶段证据、README 与 `CLAUDE.md`。

### 9.2 后续阶段验收原则

- 情感系统：测试上下限、衰减、单轮变化限制、可解释原因、关闭/重置、数据库隔离，以及文本/TTS/表情映射的一致性。
- 桌宠层：实测透明窗口、置顶、拖动、点击穿透、托盘恢复、字幕、口型/表情事件、崩溃恢复、安装/卸载和连续运行资源占用。
- 语音与本地模型：在目标机器记录首字延迟、ASR 实时因子、TTS 首包延迟、峰值 RAM/VRAM、GPU/CPU 利用率和连续运行稳定性；上游功能列表不等于本机验收。

## 10. 当前工作树保护规则

- 不 reset、checkout、amend 或覆盖现有 3M 未提交工作；
- 不机械执行旧计划中已完成 Task 1–5 的逐步 commit 命令；计划中的未勾选状态不表示应重做，真实工作树里的配置、Factory、DeepSeek overrides、sanitizer、summary provider/service 及其测试均是保护对象；
- 实施前必须以 `git status` 和当前文件内容重新核对缺口，只补 scheduler、`ChatService`/DI 接线、composition/runtime 验证与证据；
- `messages.py` 的稳定排序是 3M coverage 的必要前置，不得因计划旧文案“unchanged”而回退；
- `.superpowers/brainstorm/` 是视觉讨论资产，不纳入 3M 产品提交，也不擅自删除；
- README 当前状态滞后，以 `CLAUDE.md` 和最新阶段证据为准，但只有验收后才更新状态；
- 任何跨入摘要注入、自动冲突解决、情感或桌宠实现的修改都必须另起设计和计划。

## 11. 联网调研结论与证据边界

截至 2026-07-11 的多源调研支持 Windows 11 上的模块化本地优先架构：Qwen3/llama.cpp 可作为本地 LLM 路线，sherpa-onnx、FunASR、SenseVoice 可作为中文语音输入候选，CosyVoice 可作为中文情感 TTS 候选。

但本轮证据没有完成 Live2D/桌面框架比较、长期记忆策略实证、角色一致性评测、安全防护或目标角色授权审查。因此本规格只确定阶段边界，不宣称这些后续选型已经完成。

主要来源：

- [Qwen3](https://github.com/QwenLM/Qwen3)
- [llama.cpp](https://github.com/ggml-org/llama.cpp)
- [Qwen3-8B GGUF](https://huggingface.co/Qwen/Qwen3-8B-GGUF)
- [Ollama GPU support](https://docs.ollama.com/gpu)
- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)
- [FunASR](https://github.com/modelscope/FunASR)
- [SenseVoice](https://github.com/FunAudioLLM/SenseVoice)
- [CosyVoice](https://github.com/FunAudioLLM/CosyVoice)
- [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)

## 12. 下一步

本总体路线已经批准，3M 专项设计和实施计划也已存在。用户书面复核本文件后，下一步调用 `writing-plans` 校准现有计划，而不是另起一份重复计划：以当前工作树为基线，保留 Task 1–5 WIP，只补 scheduler、`ChatService`/DI 接线、相关测试和验证证据，不跨入后续阶段。
