# 🐱 AI 桌宠 — 虚拟角色交互系统

一个具备文字对话、语音交互、长期记忆与情感表达能力的 AI 虚拟角色全栈系统。

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19+-61dafb.svg)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.x-3178c6.svg)](https://www.typescriptlang.org/)
[![Electron](https://img.shields.io/badge/Electron-43+-9feaf9.svg)](https://www.electronjs.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 概述

本项目构建一个**可持续演进的私人虚拟角色交互系统**，核心能力包括：

- 🗣️ **文字角色对话** — 多 LLM 供应商（Anthropic / DeepSeek / Fake），可替换适配器
- 🎤 **语音输入输出** — ASR 语音识别（FasterWhisper）+ TTS 语音合成（CosyVoice）+ 浏览器端 VAD
- 🧠 **长期记忆** — 可审计、可编辑的记忆管理，支持候选确认、冲突检测、embedding 检索
- 💭 **情感系统** — 有界、可解释的情感状态机，协调文本表达与语音表现
- 🔒 **隐私优先** — 所有远程处理需持久明确授权，本地数据可控，密钥不入库

系统按严格的工程流程推进：设计规格 → 实施计划 → 自动化测试 → 独立验收 → 终审闭环。每个阶段均有完整的设计文档、测试覆盖和验收证据。

---

## 架构概览

```
┌──────────────────────────────────────────────────────┐
│                    Frontend (Electron)                 │
│  React 19 + TypeScript + Vite + Playwright E2E        │
│  ├─ 文字聊天 UI                                       │
│  ├─ 语音录制 / VAD / 设备管理                          │
│  ├─ 记忆管理面板                                       │
│  ├─ 情感控制面板                                       │
│  └─ Streaming Audio Playback (Web Audio API)          │
├──────────────────────────────────────────────────────┤
│                  Backend (FastAPI)                     │
│  Python 3.11+ / SQLite / pytest                       │
│  ├─ /api/chat          → 文字对话 (ChatService)        │
│  ├─ /api/audio/*       → ASR + TTS (Provider 适配)    │
│  ├─ /api/memories/*    → 长期记忆 CRUD + 检索          │
│  ├─ /api/emotion/*     → 情感状态 + 分析               │
│  ├─ /api/persona/*     → 角色身份投影                  │
│  └─ /api/sessions/*    → 会话管理 + 摘要               │
├──────────────────────────────────────────────────────┤
│                 Provider Adapters                      │
│  LLM: Anthropic / DeepSeek / Fake                     │
│  ASR: FasterWhisper / Fake                            │
│  TTS: CosyVoice / Fake                                │
│  Embedding: Sentence-Transformers / Fake               │
└──────────────────────────────────────────────────────┘
```

**核心设计原则**：模块解耦 · 供应商隔离 · 配置外置 · 密钥安全 · 数据可控

---

## 当前进度

| 阶段 | 内容 | 状态 |
|---|---|---|
| Stage 1 | 角色文字对话系统 | ✅ 已关闭 |
| Stage 2 | 语音功能（ASR + TTS + VAD + Streaming） | ✅ 已关闭 |
| Stage 3 | 长期记忆（CRUD + 检索 + 冲突审计 + 摘要） | ✅ 已关闭 |
| Stage 4 | 情感系统（状态机 + 表达 + LLM 辅助分析） | ✅ 已关闭 |
| Gate A | 自动记忆 Governor + Shadow Mode | ✅ 已通过 |
| Gate B | 版本化自动写入 + Evidence + 冲突状态机 | ✅ 已通过 |
| Gate C1 | Persona Artifact + Context Composer | ✅ 已通过 |
| Gate C2 | 摘要生成/注入 + Consent + Redaction | ✅ 已通过 |
| Gate C3 | 关系投影（Tasks 1–8 完成；Tasks 9–11 已通过最终验收，Task 12 隐私原子化、Task 13 Persona/rule/rebuild、Task 14 关系上下文注入、Task 15 safe relationship APIs 已实现） | 🟡 进行中 |
| Electron 桌面壳 | Windows 双窗口开发态桌面壳 | ⏳ 设计已批准 |
| Live2D | 角色动画与表情 | ⏳ 待设计 |

---

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 20+
- npm 10+

### 安装

```bash
# 后端
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e backend[dev]

# 前端
cd frontend
npm install
```

### 配置

```bash
cp .env.example .env
# 默认使用 fake provider，无需 API Key 即可本地运行
```

### 启动

```bash
# 后端 (http://127.0.0.1:8000)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload

# 前端 (http://127.0.0.1:5173)
cd frontend
npm run dev
```

### 测试

```bash
# 后端测试
.\.venv\Scripts\python.exe -m pytest backend/tests -v

# 前端测试
cd frontend
npm test -- --run
npm run typecheck
npm run build
npm run test:e2e
```

### 启用真实 Provider

所有真实 Provider 均需显式配置，默认 Fake Provider 无需模型下载：

```bash
# LLM: DeepSeek
$env:LLM_PROVIDER = "deepseek"
$env:DEEPSEEK_API_KEY = "your-key"

# LLM: Anthropic
$env:LLM_PROVIDER = "anthropic"
$env:ANTHROPIC_API_KEY = "your-key"

# ASR: FasterWhisper (需安装 backend[asr])
$env:ASR_PROVIDER = "faster-whisper"

# TTS: CosyVoice (需单独启动本地服务)
$env:TTS_PROVIDER = "cosyvoice-http"
```

---

## 文档索引

### 设计规格与计划

所有功能的设计规格和详细实施计划归档于 `docs/superpowers/specs/` 和 `docs/superpowers/plans/`。

### 阶段验收

- Stage 2 总体验收：`docs/stage2-voice-acceptance-audit.md`
- Stage 3 总体验收：`docs/stage3-memory-acceptance-audit.md`
- Stage 4 总体验收：`docs/stage4-emotion-acceptance-audit.md`

### Gate 验收

- Gate A：`docs/automatic-memory-gate-a-acceptance-2026-07-19.md`
- Gate B：`docs/automatic-memory-gate-b-acceptance-2026-07-21.md`
- Gate C1：`docs/automatic-memory-gate-c1-acceptance-2026-07-22.md`
- Gate C2：`docs/automatic-memory-gate-c2-acceptance-2026-07-25.md`
- Gate C3 Tasks 9–11（实现与独立审阅）：`docs/automatic-memory-gate-c3-task9-fix-acceptance-2026-08-15.md`、`docs/automatic-memory-gate-c3-task10-acceptance-2026-08-15.md`、`docs/automatic-memory-gate-c3-task11-acceptance-2026-08-15.md`
- Gate C3 Task 12（隐私原子化）：`docs/automatic-memory-gate-c3-task12-acceptance-2026-08-16.md`
- Gate C3 Task 13（Persona 切换 / rule 升级 / rebuild）：`docs/automatic-memory-gate-c3-task13-acceptance-2026-08-16.md`
- Gate C3 Task 14（关系上下文编码与 pre-dispatch 重验证注入）：`docs/automatic-memory-gate-c3-task14-acceptance-2026-08-16.md`
- Gate C3 Task 15（safe local relationship APIs）：`docs/automatic-memory-gate-c3-task15-acceptance-2026-08-16.md`

### 项目总纲

- `CLAUDE.md` — 强制执行协议、阶段状态、工程原则、禁止事项

---

## 技术栈

| 层 | 技术 |
|---|---|
| 后端框架 | FastAPI 0.115+ |
| 前端框架 | React 19, TypeScript 5, Vite |
| 桌面壳 | Electron 43（开发中） |
| 数据库 | SQLite（aiosqlite） |
| LLM | Anthropic Messages API, DeepSeek Chat Completions |
| ASR | FasterWhisper (CTranslate2) |
| TTS | CosyVoice 3 (HTTP OpenAI-compatible) |
| VAD | Silero VAD (ONNX, 浏览器端) |
| Embedding | Sentence-Transformers (可选, 隔离环境) |
| 测试 | pytest + pytest-asyncio, Vitest, Playwright |

---

## 工程亮点

- **供应商隔离**：所有外部服务通过 Provider 适配器接入，可替换、可 mock
- **隐私契约**：远程记忆抽取、情感分析、摘要处理均需独立持久明确授权，环境变量不等同于 consent
- **冲突审计**：记忆冲突不静默覆盖，保留完整审计日志与冲突状态机
- **情感约束**：状态更新有上下限、衰减函数和 CAS；单轮输入不造成极端跳变
- **确定性测试**：Fake Provider 全覆盖，CI 不依赖外部 API
- **文档驱动**：142 篇设计/计划/验收文档，可追溯每个功能的决策依据

---

## ⚠️ 注意事项

- 本项目实现的是角色一致性、记忆和情感**表现**，不宣称角色具有真实意识或情感
- 角色设定、语音和形象必须原创或已获授权
- 生产级打包（安装程序、自动更新）尚未实现
- 后台监听（持续麦克风监听）不在当前范围内

---

## 许可

MIT License — 详见 [LICENSE](LICENSE)
