# AI 桌宠：虚拟角色交互系统

当前状态：阶段 1–4 均已完成并关闭。Stage 4 情感系统于 2026-07-15 完成总体验收并 **VERIFIED PASS（fake-first）**；4A–4E 已建立有界本地情感状态、文本表达、需要明确授权的辅助分析、消息绑定 ExpressionPlan/TTS，以及精确 playback run 的浏览器表现闭环。下一最小任务是已批准设计的 Windows 11 Electron 双窗口开发态桌面壳；Live2D、生产打包和受保护角色素材仍不在已完成范围。阶段 3 摘要注入和自动冲突合并/解决仍是未实现的非阻塞增强项。

本项目按 `CLAUDE.md` 的固定阶段推进。阶段 1 已关闭；阶段 2 语音功能已完成总体验收审计并关闭。2A 完成对既有文字回复生成 Fake TTS 测试音并在前端手动播放。2B-1 完成后端 ASR Foundation。2B-2 完成 `POST /api/audio/transcriptions` multipart 上传接口。2B-3 完成浏览器手动录音 UI。2B-4 完成真实 ASR 基准测试（C1-C4）。2B-5 完成 FasterWhisper ASR Provider 集成。2B-6 验证真实 ASR 在主应用端到端可用。2B-7 验证 CosyVoice HTTP TTS API/UI smoke。2C-1 完成 fake-provider 半双工语音回合 baseline：显式 `发送并朗读` 会把 ASR 转写通过现有文字对话发送，并对匹配的 assistant 回复触发 TTS 播放。2C-2R 已修复 CosyVoice 长 assistant 回复 TTS 超时：本地 CosyVoice smoke server 对长文本分段、`stream=True` 合成并拼接 WAV，direct CosyVoice 与 main backend 长文本 TTS smoke 均 PASS。2C-2 已完成真实 ASR + 真实 LLM + CosyVoice HTTP 的完整浏览器半双工语音回合 smoke。2D 已完成浏览器端 VAD auto-stop：仅在用户显式点击 `开始录音` 后加载并监听语音结束，检测到 speech end 后调用现有录音停止路径。2E 已完成显式语音打断：assistant 音频合成或播放中点击 `开始录音` 会停止/取消当前音频并启动现有录音/VAD/ASR 路径。2F-pre 已完成浏览器端麦克风输入设备管理：可选择系统默认或枚举麦克风并刷新设备，录音时以 `deviceId: { ideal }` 作为偏好传给 `getUserMedia`。2F-1 已完成 fake-provider 浏览器语音回合测量基线：记录 ASR、chat、TTS、playback trigger 和端到端耗时。2F-2 已完成浏览器端输出设备选择和设备偏好持久化：麦克风/输出设备偏好仅以 opaque deviceId 存入 localStorage，支持 `setSinkId` 的浏览器可为 assistant TTS 播放选择扬声器/耳机，不支持时回退系统默认输出。2F-3 已完成 fake-provider 流式 TTS 首个垂直切片：新增 `POST /api/audio/speech/stream` NDJSON 分段 WAV 路径，浏览器语音回合可在首个 segment 到达后开始播放。2F-4 已完成真实 CosyVoice streaming TTS 垂直切片：显式 `TTS_PROVIDER=cosyvoice-http` 时，真实本地 CosyVoice 可通过既有 `/api/audio/speech/stream` NDJSON 分段 WAV 合成路径触达浏览器语音回合播放。2G-1 已完成 app-level streaming ASR 首个垂直切片：显式录音中可显示 fake/default partial 转写预览，停止后 final transcript 仍进入既有确认与 `发送并朗读` 路径。2G-2 已完成 real FasterWhisper streaming ASR feasibility：显式 opt-in 后，真实本地 FasterWhisper 可通过 `/api/audio/transcriptions/stream` 输出 partial/final NDJSON events；这是 cumulative-window feasibility layer，不是最终生产级低延迟 ASR。2H 已完成浏览器端低间隙 streaming audio playback：streaming TTS segments 可优先通过 Web Audio `AudioContext` / `AudioBufferSourceNode` 调度播放，并保留既有 HTMLAudio 输出设备兼容回退。Stage 2 Voice Acceptance Audit 于 2026-07-06 PASS，记录于 `docs/stage2-voice-acceptance-audit.md`。阶段 3 已完成 3A–3M、长期记忆 GUI CRUD 与聊天 Provider 上下文字符预算，并于 2026-07-13 在修复 MemoryPanel 数值草稿和刷新后最新内容验收契约后完成总体验收复验 PASS；证据记录于 `docs/stage3-memory-acceptance-audit.md`。阶段 4 已完成 4A–4E，并于 2026-07-15 完成总体验收 VERIFIED PASS（fake-first）后关闭；证据记录于 `docs/stage4-emotion-acceptance-audit.md`。下一工作是独立的 Windows 桌面呈现层。摘要注入和自动冲突合并/解决工作流尚未实现；文字仍是内部标准交换格式。

## 阶段边界

已规划/实现范围：

- 文字聊天界面。
- 会话创建、继续、删除。
- SQLite 保存会话和消息。
- 最近对话上下文。
- 独立角色配置和 System Prompt 模板。
- 可替换 LLM Provider，默认可使用 fake provider 本地运行。
- Anthropic Provider 适配器，真实密钥只从环境变量读取。
- DeepSeek Provider 适配器，使用 DeepSeek 官方 OpenAI-compatible Chat Completions 接口；真实密钥只从环境变量读取。
- Stage 2A Fake TTS Provider：使用 Python 标准库生成短促、确定性的 WAV 测试音；这不是自然语音。
- Stage 2B-1 Backend ASR Foundation：独立 ASR Provider 抽象、Fake ASR Provider、ASRService、Factory 和配置；Fake ASR 只返回确定性测试文本，不识别真实语音。
- Stage 2B-2 Multipart Transcription API：`POST /api/audio/transcriptions` 接收 multipart/form-data 上传，使用 Fake ASR 返回确定性转写 JSON；不识别真实语音，不保存原始音频（框架可能使用临时 spooled file）。
- Stage 2B-7 CosyVoice HTTP TTS Provider smoke：真实 TTS 可通过单独启动的本地 CosyVoice HTTP 服务和 `TTS_PROVIDER=cosyvoice-http` 显式启用；默认测试仍使用 Fake TTS。
- Stage 2C-1 Fake-provider 半双工语音回合 baseline：前端编排 ASR → 显式 `发送并朗读` → 现有文字对话 → TTS 播放；稳定匹配本轮 assistant message；TTS 失败不丢失文字回复；录音与播放/合成互斥。
- Stage 2C-2R CosyVoice 长回复 TTS timeout 修复：本地 CosyVoice OpenAI-compatible smoke server 对长 assistant 回复分段、`stream=True` 合成并拼接 WAV；direct CosyVoice 与 main backend 长文本 TTS smoke 均 PASS。
- Stage 2C-2 Real-provider full-turn smoke：真实 FasterWhisper ASR + 真实 DeepSeek LLM + CosyVoice HTTP 完整浏览器半双工语音回合 smoke 已完成。
- Stage 2D VAD auto-stop：浏览器端 Silero/ONNX VAD 仅在用户显式点击 `开始录音` 后运行，检测到语音结束后调用现有录音停止路径；手动停止、取消和重录仍可用。
- Stage 2E explicit voice interruption：assistant 音频合成或播放中，用户点击 `开始录音` 会停止/取消当前音频并启动现有录音/VAD/ASR 路径；这不是后台监听或自动 spoken barge-in。
- Stage 2F-pre audio input device management：浏览器 UI 提供 `系统默认麦克风`、枚举麦克风选项和刷新设备；选择的麦克风以 `deviceId: { ideal }` 作为录音设备偏好。
- Stage 2F-1 streaming/performance measurement baseline：新增 fake-provider 浏览器语音回合测量脚本，记录 ASR、chat、TTS、playback trigger 和端到端耗时；这不是流式实现或真实 provider 性能结论。
- Stage 2F-2 audio output device selection and device preference persistence：浏览器 UI 提供系统默认输出设备和可枚举/授权的扬声器或耳机选择；麦克风与输出设备偏好仅保存在浏览器 localStorage。
- Stage 2F-3 streaming TTS first vertical slice：新增 fake-provider `POST /api/audio/speech/stream` NDJSON 分段 WAV 路径；浏览器语音回合可在首个 segment 到达后开始播放，既有非流式 `/api/audio/speech` 保持可用。
- Stage 2F-4 real CosyVoice streaming TTS vertical slice：显式启用 `TTS_PROVIDER=cosyvoice-http` 时，真实本地 CosyVoice 可复用 `/api/audio/speech/stream` NDJSON 分段 WAV contract；浏览器 voice-turn smoke 已观察到真实 streaming response 和首段播放触发。
- Stage 2G-1 streaming ASR first vertical slice：新增 fake/default `POST /api/audio/transcriptions/stream` NDJSON contract；显式录音中可显示 `实时转写预览`，停止后 final transcript 仍进入既有确认 UI。
- Stage 2G-2 real FasterWhisper streaming ASR feasibility：显式启用 `ASR_PROVIDER=faster-whisper` 与 `ASR_FASTER_WHISPER_STREAMING_ENABLED=true` 时，真实本地 FasterWhisper 可通过 `/api/audio/transcriptions/stream` 输出 partial/final NDJSON events；这是 feasibility layer，不是最终生产级低延迟 ASR。
- Stage 2H low-gap streaming audio playback：浏览器端 streaming TTS 可优先使用 Web Audio 对完整 WAV segments 进行低间隙调度播放，并保留既有 HTMLAudio 输出设备兼容回退；证据记录于 `docs/stage2h-low-gap-streaming-audio.md`。
- Stage 2 Voice Acceptance Audit：2026-07-06 总体验收 PASS；后端 233 测试、前端 140 测试、typecheck、build、Playwright E2E 5 测试均通过；证据记录于 `docs/stage2-voice-acceptance-audit.md`。
- Stage 3A–3M 与长期记忆 GUI CRUD 收尾：长期记忆 foundation、候选确认、相关性/embedding 检索、冲突审计、LLM 候选抽取、真实 embedding 选型评估、独立会话摘要存储、自动非阻塞增量摘要生成及活跃记忆行内编辑均已完成；3M 证据记录于 `docs/stage3m-session-summary-generation.md`，行内编辑证据记录于 `docs/superpowers/plans/2026-07-12-memory-panel-inline-editing.md`。
- Stage 3 聊天 Provider 上下文字符预算：最终 Provider payload 已执行可配置的整条消息裁剪，保留角色 system prompt 与当前用户消息；设计与完成记录见 `docs/superpowers/specs/2026-07-12-chat-context-budget-design.md` 和 `docs/superpowers/plans/2026-07-12-chat-context-budget.md`。
- Stage 4A–4E 情感系统：已完成可查看/重置/关闭的有界本地情感状态、确定性文本表达 context、默认关闭且需要持久明确授权的 LLM 辅助分析、绑定 assistant message 的版本化 ExpressionPlan/message-bound TTS，以及消息绑定的只读表现 API、精确 playback run speaking 生命周期和中性浏览器语义预览。远程输入经过预算限制和明显凭据脱敏，输出使用严格 `emotion_analysis_v1` 校验并由本地 policy/CAS 决定是否应用；未授权、拒绝或撤回时不发送。文字与语音计划使用同一回复前快照；供应商只接收已验证的 text/voice/speed 子集，任何 plan/TTS/表现查询/播放/预览失败不影响文字回复。Stage 4E 不持久化 speaking、playback、preview 或 display label。阶段 4 总体验收于 2026-07-15 **VERIFIED PASS（fake-first）** 并正式关闭；总证据见 `docs/stage4-emotion-acceptance-audit.md`，子任务证据见 `docs/stage4a-local-emotion-state-foundation.md`、`docs/stage4b-emotion-text-expression-loop.md`、`docs/stage4c-llm-emotion-analysis-consent.md`、`docs/stage4d-expression-plan-tts.md` 和 `docs/stage4e-expression-event-browser-preview.md`。

未实现范围：

- 真实 TTS 生产化打包与完整资源驻留策略。
- 阶段 3：摘要注入策略、自动冲突合并/解决工作流（均不属于已关闭的 Stage 3 验收范围）。
- 后续展示层：Windows 11 Electron 双窗口开发态桌面壳、Live2D/角色动画、口型与生产角色素材集成；桌面壳设计已批准但尚未实施，Live2D 必须另行设计。真实 provider 的 delivery/intensity 声学能力尚未验证。

聊天历史在阶段 1 中仅作为会话消息保存，不视为长期记忆。

### Stage 3 acceptance audit

阶段 3 总体验收于 2026-07-13 完成修复复验并 **PASS**。后端 focused/full、前端 Vitest/typecheck/build、完整 Playwright E2E 和隔离运行时 API 验证全部通过；MemoryPanel 数值空草稿不再产生 `value=NaN`，手动记忆编辑后刷新可恢复最新持久化内容。完整证据见 `docs/stage3-memory-acceptance-audit.md`。

### Stage 4 acceptance audit

阶段 4 总体验收于 2026-07-15 **VERIFIED PASS（fake-first）**。4A–4E 共同满足有界、可解释、可衰减、可查看/重置/关闭的情感状态，以及文本、message-bound TTS/ExpressionPlan 和精确 playback run 表现消费的一致性要求；完整 Python、前端、浏览器 E2E、隔离 runtime、数据库不变量和独立审查证据见 `docs/stage4-emotion-acceptance-audit.md`。

Stage 4 已关闭。Windows 11 Electron 双窗口桌面壳是独立的下一展示层任务；其设计已批准，将在阶段 4 关闭提交后单独形成书面规格并进入用户复核，目前尚未实施。不得据此声称 Live2D、生产打包、后台监听、真实声学表现质量或受保护角色素材已经完成。

### Stage 3F memory embedding retrieval

Embedding retrieval is opt-in. By default the app keeps deterministic relevance retrieval. To test the local fake embedding path, set:

```env
MEMORY_RETRIEVAL_MODE=embedding
MEMORY_EMBEDDING_ENABLED=true
MEMORY_EMBEDDING_PROVIDER=fake
MEMORY_EMBEDDING_MODEL=fake-memory-embedding-v1
```

This only changes retrieval for confirmed active long-term memories. It does not automatically create memories, does not summarize sessions, and does not implement emotional state.

### Stage 3G real embedding smoke

A standalone smoke/evaluation script checks Chinese memory retrieval quality without touching the app database:

```powershell
python scripts/evaluate_memory_embeddings.py --provider fake --details
python scripts/evaluate_memory_embeddings.py --provider sentence-transformers --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --details
```

The real provider command is optional and requires `sentence-transformers` plus model download availability. This smoke does not create memories, summarize sessions, or implement emotional state.

### Stage 3H isolated real embedding evaluation

Real embedding evaluation is isolated from the main backend environment:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_memory_embedding_env.ps1
.\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --details
```

If PowerShell execution policy blocks the helper, run the same setup steps manually in `.venv-memory-embed` or inspect `scripts/setup_memory_embedding_env.ps1` and execute its commands without changing product dependencies.

This remains an evaluation path only. It does not change default retrieval, does not create memories, does not summarize sessions, and does not implement emotional state.

2026-07-09 validation result: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` PASS on the fixed Chinese fixture (`top1_accuracy=0.75`, `top3_recall=1.0`, `case_count=8`). Evidence is recorded in `docs/stage3h-real-embedding-model-evaluation.md`.

## 环境要求

- Python 3.11+
- Node.js 20+
- npm 10+

当前开发环境已检测到 Python 3.12.6、Node.js v22.22.3、npm 10.9.8。

## 后端配置

复制 `.env.example` 为 `.env`，按需设置：

```powershell
Copy-Item .env.example .env
```

默认使用 fake provider，无需真实 API Key 即可本地验证 UI 和后端闭环。

如需使用 Anthropic Provider：

```powershell
$env:LLM_PROVIDER = "anthropic"
$env:ANTHROPIC_API_KEY = "你的真实 API Key"
$env:LLM_MODEL = "claude-opus-4-8"
```

如需使用 DeepSeek Provider（可选）：

```powershell
$env:LLM_PROVIDER = "deepseek"
$env:LLM_MODEL = "deepseek-v4-flash"
$env:DEEPSEEK_API_KEY = "set-this-in-your-local-shell-only"
$env:DEEPSEEK_BASE_URL = "https://api.deepseek.com"
$env:DEEPSEEK_THINKING_ENABLED = "false"
$env:DEEPSEEK_MAX_TOKENS = "256"
$env:DEEPSEEK_TIMEOUT_SECONDS = "120"
$env:DEEPSEEK_MAX_RETRIES = "0"
```

DeepSeek Provider 使用 OpenAI-compatible Chat Completions 接口，通过后端 `LLMProvider` 适配器接入。阶段 1 默认关闭思考模式、关闭流式输出，不使用 tools、视觉输入、JSON mode 或其他非必要功能。默认测试仍使用 mocked provider 行为，不会调用真实 DeepSeek API，也不会产生真实费用。

Stage 2A 的 TTS 输出闭环默认使用 Fake TTS：

```powershell
$env:TTS_PROVIDER = "fake"
$env:TTS_FAKE_MODE = "ok"
$env:TTS_MAX_TEXT_CHARS = "1000"
$env:TTS_DEFAULT_VOICE = "fake-default"
$env:TTS_DEFAULT_SPEED = "1.0"
```

Fake TTS 只生成本地测试用短音，不是真实自然语音，不需要模型下载，不保存音频文件。前端默认不会自动播放；用户必须点击 assistant 消息上的“播放”按钮。Milestone 2A 的自动化验证和人工扬声器 smoke 均已通过：可以听到短测试音，暂停、继续、停止、重播、切换会话停止播放和继续文字聊天均正常。2B-7 已完成 CosyVoice 3 真实 TTS API smoke；真实 TTS 仍需单独启动本地 CosyVoice 服务并显式设置 `TTS_PROVIDER=cosyvoice-http`。

Stage 2B-1 的 ASR Foundation 默认使用 Fake ASR：

```powershell
$env:ASR_PROVIDER = "fake"
$env:ASR_MAX_UPLOAD_BYTES = "10485760"
$env:ASR_MAX_DURATION_MS = "30000"
$env:ASR_MIN_DURATION_MS = "300"
$env:ASR_DEFAULT_LANGUAGE = "zh"
$env:FAKE_ASR_MODE = "ok"
$env:FAKE_ASR_TEXT = "这是 Fake ASR 测试转写。"
$env:FAKE_ASR_DETECTED_LANGUAGE = "zh"
```

Fake ASR 不识别真实语音，不访问网络，不写音频文件，不下载模型，默认返回确定性测试转写。2B-2 已提供 `POST /api/audio/transcriptions` multipart 上传 API，接收 `file`（必填，UploadFile）和 `language`（可选 Form 字段），返回 `TranscriptionResponse` JSON（字段：`text`、`detected_language`、`duration_ms`、`provider`、`model`、`inference_ms`）。上传大小限制 `ASR_MAX_UPLOAD_BYTES`（默认 10 MiB），路由检查 `UploadFile.size` 后再最多读取 `max+1` 字节以确认超限。`UploadFile` 在所有路径关闭。应用不持久化原始音频，但底层 Starlette/FastAPI `SpooledTemporaryFile` 可能临时磁盘缓冲超过阈值。2B-3 已在浏览器中实现手动录音 UI，使用 `MediaRecorder` + `getUserMedia` 录制 M4A/WebM 音频，停止后调用转写 API。2B-5/2B-6 已集成 FasterWhisper 真实 ASR Provider 并通过端到端验证。服务端只做大小、媒体类型和基础容器头签名校验；实际音频时长、可解码性和静音检测留到具备可靠解码/probe 能力后的后续任务。

### Stage 2B-6 Real ASR main-app smoke

Real ASR remains opt-in. Default tests and normal local development still use `ASR_PROVIDER=fake`.

Install optional ASR dependencies into the main backend environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -e "backend[asr]"
```

GPU candidate configuration (C3):

```powershell
$env:ASR_PROVIDER = "faster-whisper"
$env:ASR_FASTER_WHISPER_MODEL_PATH = "$env:USERPROFILE\.cache\huggingface\hub\models--Systran--faster-whisper-medium\snapshots\08e178d48790749d25932bbc082711ddcfdfbc4f"
$env:ASR_FASTER_WHISPER_MODEL_NAME = "medium"
$env:ASR_FASTER_WHISPER_MODEL_REVISION = "08e178d48790749d25932bbc082711ddcfdfbc4f"
$env:ASR_FASTER_WHISPER_DEVICE = "cuda"
$env:ASR_FASTER_WHISPER_COMPUTE_TYPE = "float16"
$env:ASR_FASTER_WHISPER_BEAM_SIZE = "1"
$env:ASR_FASTER_WHISPER_TIMEOUT_SECONDS = "30"
```

CPU fallback candidate (C4):

```powershell
$env:ASR_FASTER_WHISPER_MODEL_PATH = "$env:USERPROFILE\.cache\huggingface\hub\models--Systran--faster-whisper-small\snapshots\536b0662742c02347bc0e980a01041f333bce120"
$env:ASR_FASTER_WHISPER_MODEL_NAME = "small"
$env:ASR_FASTER_WHISPER_MODEL_REVISION = "536b0662742c02347bc0e980a01041f333bce120"
$env:ASR_FASTER_WHISPER_DEVICE = "cpu"
$env:ASR_FASTER_WHISPER_COMPUTE_TYPE = "int8"
```

Verification result on 2026-06-27: **PASS** — backend API smoke and browser UI smoke both confirmed correct transcription with real faster-whisper medium GPU model.

### Stage 2B-7 Real TTS API smoke

Real TTS remains opt-in. Default tests and normal local development still use `TTS_PROVIDER=fake`.

CosyVoice runs in a separate Python 3.10 environment because the main backend `.venv` uses Python 3.12:

```powershell
C:\Users\张乐航\AppData\Local\Programs\Python\Python310\python.exe -m venv .venv-tts
.\.venv-tts\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
$env:PIP_CONSTRAINT = "C:\Users\张乐航\Desktop\AI桌宠\scripts\pip-build-constraints-tts.txt"
.\.venv-tts\Scripts\python.exe -m pip install -r external\CosyVoice\requirements.txt
```

Start the local CosyVoice OpenAI-compatible smoke server:

```powershell
.\.venv-tts\Scripts\python.exe -m uvicorn scripts.cosyvoice3_openai_server:app --host 127.0.0.1 --port 8001
```

Configure the main backend to call it:

```powershell
$env:TTS_PROVIDER = "cosyvoice-http"
$env:TTS_DEFAULT_VOICE = "default-zh-female"
$env:TTS_COSYVOICE_BASE_URL = "http://127.0.0.1:8001"
$env:TTS_COSYVOICE_MODEL = "Fun-CosyVoice3-0.5B-2512"
$env:TTS_COSYVOICE_TIMEOUT_SECONDS = "90"
```

Verification result on 2026-06-27: **PASS** — local CosyVoice3 synthesis smoke generated a 24 kHz WAV, main backend `/api/audio/speech` returned real `audio/wav` through `TTS_PROVIDER=cosyvoice-http`, and browser UI playback smoke confirmed assistant-message `播放` calls real CosyVoice audio with 0 console errors. This uses the official CosyVoice sample prompt audio for technical smoke only; it does not clone or imitate Yukinoshita Yukino, any voice actor, celebrity, or unauthorized voice.

### Stage 2C-1 Fake-provider half-duplex voice turn

The app supports a fake-provider half-duplex voice-turn baseline:

1. Record with the manual microphone UI.
2. Review the ASR transcript.
3. Click `发送并朗读` to send the transcript through the existing text-chat path.
4. The assistant reply produced by that send is selected by a stable post-send matching rule.
5. The matching assistant reply is synthesized through the existing TTS path and played back.

This baseline keeps confirmation explicit, keeps text chat usable, and does not add VAD, interruption, streaming, long-term memory, or emotion. TTS failure after chat success keeps the text user/assistant messages visible and reports a recoverable voice error. Recording and TTS synthesis/playback are mutually exclusive in the UI.

Verification result on 2026-06-27: **PASS** — backend regression 204 passed; frontend unit tests 61 passed; `npm run typecheck` PASS; `npm run build` PASS; Playwright E2E 5 passed including `voice-turn.spec.ts`. Real-provider full-turn smoke with FasterWhisper + real LLM + CosyVoice HTTP is completed separately as 2C-2.

### Stage 2C-2R CosyVoice long assistant-reply TTS timeout fix

The local CosyVoice OpenAI-compatible smoke server now handles longer assistant replies by splitting text into bounded sentence-like segments, calling CosyVoice with `stream=True`, collecting all generated chunks, inserting short silence between segments, and returning one WAV. This is still a local smoke-server implementation, not a packaged production TTS service.

Verification result on 2026-06-27: **PASS** — direct CosyVoice `/v1/audio/speech` with a 71-character Chinese assistant-style reply returned HTTP 200 `audio/wav` in 19789 ms; main backend `/api/audio/speech` with the same text returned HTTP 200 `audio/wav` through `TTS_PROVIDER=cosyvoice-http` in 18423 ms. The previous long assistant-reply `tts_timeout` blocker is resolved.

### Stage 2C-2 Real-provider full-turn smoke

Real-provider full-turn smoke with FasterWhisper + real LLM + CosyVoice HTTP is completed as a local opt-in smoke. It requires local real-provider configuration and does not run in default tests.

Final verification result on 2026-06-28: **PASS** — headed browser smoke completed FasterWhisper real ASR, explicit `发送并朗读`, real DeepSeek assistant reply, CosyVoice HTTP full assistant-reply TTS, non-silent browser Blob stats, successful `Audio.play()` completion, 0 console errors, and operator audible confirmation. Evidence and limitations are recorded in `docs/stage2c-half-duplex-voice-turn.md`.

### Stage 2D VAD auto-stop

Stage 2D adds browser-side Silero/ONNX VAD auto-stop after the user explicitly clicks `开始录音`. Manual stop and cancel remain available, VAD failure falls back to manual recording, and VAD does not run as background listening.

Verification result on 2026-06-29: **PASS** — fake VAD lifecycle tests, frontend regression, typecheck, build, real VAD asset-load smoke, and headed real VAD auto-stop browser smoke passed. Evidence is recorded in `docs/stage2d-vad-auto-stop.md`.

### Stage 2E explicit voice interruption

Stage 2E adds explicit voice interruption: when assistant audio is synthesizing or playing, clicking `开始录音` stops/aborts the current audio and starts the existing recorder/VAD/ASR flow. This is not background listening or automatic spoken barge-in.

Verification result on 2026-06-29: **PASS** — focused interruption tests, frontend unit tests, VAD regression, typecheck, build, and Playwright E2E passed. Evidence is recorded in `docs/stage2e-explicit-voice-interruption.md`.

### Stage 2F-pre audio input device management

The browser UI now includes a microphone selector with `系统默认麦克风`, enumerated audio input devices, and a refresh control. A selected microphone is passed to `getUserMedia` as an ideal device constraint when recording starts. Device enumeration failure remains non-blocking and page load does not request microphone permission.

Verification result on 2026-06-29: **PASS** — hook tests, App tests, VAD regression, full frontend unit tests, typecheck, build, Playwright E2E, and runtime UI verification passed. Evidence is recorded in `docs/stage2f-audio-device-management.md`.

### Stage 2F-1 streaming/performance measurement baseline

A fake-provider browser measurement script now records the current non-streaming half-duplex voice turn latency shape, including ASR transcript readiness, chat response, TTS request/response, playback trigger, and end-to-end timing. Run it against a local fake-provider backend/frontend with `npm run measure:voice-turn` from `frontend/`.

Verification result on 2026-06-29: **PASS** — app-not-running failure path, 3-run fake-provider measurement, frontend unit tests, typecheck, build, and Playwright E2E passed. Evidence is recorded in `docs/stage2f-streaming-performance-baseline.md`. This is not a streaming implementation and not a real-provider performance claim.

### Stage 2F-2 audio output device selection and device preference persistence

The browser UI now stores microphone and output-device preferences locally as opaque browser `deviceId` values only. In browsers that support `HTMLMediaElement.setSinkId`, assistant TTS playback can be routed to a selected speaker/headphone output. When output-device selection is unsupported, the app reports that it will use the system default output and keeps text chat, recording, ASR, and TTS playback available.

Verification result on 2026-06-29: **PASS** — audio device preference tests, input/output device hook tests, playback routing tests, App tests, full frontend unit tests, typecheck, build, and Playwright E2E passed. Evidence is recorded in `docs/stage2f2-audio-output-device-preferences.md`. This is not a streaming ASR/TTS implementation and does not add long-term memory or emotion behavior.

### Stage 2F-3 streaming TTS first vertical slice

The fake-provider browser voice-turn path now supports a streaming TTS endpoint that emits NDJSON events with standalone WAV segments. The browser can begin playback from the first segment before the stream completes. Existing non-streaming TTS remains available.

Verification result on 2026-06-30: **PASS** — backend streaming tests, frontend parser/playback/App tests, typecheck, build, and Playwright E2E passed. Evidence is recorded in `docs/stage2f3-streaming-tts-first-slice.md`. This is not real-provider streaming, streaming ASR, long-term memory, or emotion behavior.

### Stage 2F-4 real CosyVoice streaming TTS vertical slice

The opt-in real CosyVoice path can use the existing `/api/audio/speech/stream` NDJSON streaming contract to return standalone WAV segments. Existing fake streaming and non-streaming TTS paths remain available.

Verification result on 2026-06-30: **PASS** — backend CosyVoice streaming provider tests, API wiring tests, fake/default regressions, real local CosyVoice streaming API smoke, and browser voice-turn streaming playback smoke passed. Evidence is recorded in `docs/stage2f4-real-cosyvoice-streaming-tts.md`.

This is a feasibility/vertical-slice smoke, not final seamless low-gap streaming, streaming ASR, long-term memory, or emotion behavior.

不要把 `.env` 或真实密钥提交入库。

## 安装依赖

```powershell
python -m pip install -e backend[dev]
Push-Location frontend
npm install
Pop-Location
```

## 运行测试

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -v
Push-Location frontend
npm test -- --run
npm run typecheck
npm run build
npm run test:e2e
Pop-Location
```

`npm run build` 会先执行 `tsc -b`，因此生产构建包含 TypeScript 类型检查；`npm run typecheck` 可单独运行类型检查。

真实 DeepSeek 冒烟验证必须显式选择 `LLM_PROVIDER=deepseek`，并且只应在确认 `.env` 被 Git 忽略、`DEEPSEEK_API_KEY` 仅存在于本地环境后执行。普通 `pytest`、`npm test`、`npm run test:e2e` 不得调用真实 API。

只检查 DeepSeek key 是否存在，不输出值、前缀、长度或完整 `.env`：

```powershell
if (Test-Path Env:DEEPSEEK_API_KEY) { "DEEPSEEK_API_KEY exists" } else { "DEEPSEEK_API_KEY missing" }
```

运行 DeepSeek mocked 后端测试：

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_config.py backend/tests/test_provider_factory.py backend/tests/test_deepseek_provider.py -v
```

## 启动应用

后端：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload
```

前端：

```powershell
Push-Location frontend
npm run dev
Pop-Location
```

默认前端开发服务器会通过 Vite proxy 访问后端 `http://127.0.0.1:8000`。如需改后端地址，只设置供 Vite 配置读取的本地环境变量：

```powershell
$env:BACKEND_PROXY_TARGET = "http://127.0.0.1:8000"
Push-Location frontend
npm run dev
Pop-Location
```

前端业务代码继续使用 `/api/...` 相对路径。不要把 API Key 或其他密钥放入 `VITE_*` 环境变量；真实密钥只应保存在本机环境变量或 `.env` 中，且不得提交。

## 手动验收建议

1. 启动后端和前端。
2. 新建会话。
3. 发送第一条文字消息。
4. 收到角色风格回复。
5. 发送第二条消息，确认回复能参考近期上下文。
6. 重启后端，确认既有会话仍可读取。
7. 删除会话，确认会话消失且不可再访问。
8. 切换 fake provider 错误模式或断开真实 Provider，确认 UI 显示可理解错误且应用不崩溃。

## Stage 2A 人工 Fake TTS smoke 建议

自动化 E2E 只验证 WAV 响应、请求、Blob URL 和播放控制状态，不证明扬声器实际发声。如需人工确认可听性：

1. 使用 fake LLM / fake TTS 配置启动后端。
2. 启动前端。
3. 创建会话并发送一条文字消息。
4. 点击 assistant 消息上的“播放”。
5. 确认能听到短测试音。
6. 测试暂停、继续、停止和重播。
7. 再发送一条文字消息，确认文字聊天仍可继续。
