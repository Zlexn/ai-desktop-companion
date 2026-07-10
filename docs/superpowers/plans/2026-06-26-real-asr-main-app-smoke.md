# Real ASR Main App Smoke Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify and document that the existing FasterWhisper ASR provider works through the main `.venv`, main FastAPI app, and current browser recording UI.

**Architecture:** Keep the current Stage 2B API and UI boundary unchanged. Fake ASR remains the default automated path; FasterWhisper is opt-in via environment variables and is validated with smoke commands plus documentation updates.

**Tech Stack:** Python 3.12 local `.venv`, FastAPI, pytest, faster-whisper optional extra, React/Vite/Vitest/Playwright, PowerShell on Windows.

---

## File Structure

Modify these files only unless a verification blocker requires a tiny helper:

- `README.md`
  - Update Stage 2 status text and real ASR setup/smoke instructions.
- `docs/stage2b5-real-asr-provider.md`
  - Add a 2B-6 addendum with exact verification results.
- `CLAUDE.md`
  - Update current Stage 2 status after evidence exists.
- Optional create: `scripts/smoke_real_asr_api.py`
  - Only create if direct PowerShell multipart upload is unreliable. The helper posts a local audio file to `/api/audio/transcriptions` and prints redacted metadata plus transcript length, not private transcript content.

Do not modify provider code unless smoke exposes a real defect. If code changes become necessary, stop and write a focused follow-up plan for that defect.

---

### Task 1: Baseline Checks

**Files:**
- Read: `CLAUDE.md`
- Read: `README.md`
- Read: `docs/stage2b5-real-asr-provider.md`
- Read: `backend/pyproject.toml`

- [ ] **Step 1: Confirm project alignment**

Output this exact alignment block before work:

```text
当前阶段：阶段 2——语音功能（IMPLEMENTING）
本次目标：执行 2B-6 真实 ASR 主应用 smoke 与文档记录
修改范围：主 .venv 依赖验证、真实 ASR API/UI smoke、README/docs/CLAUDE 状态记录；不进入 2C/2D/阶段3/阶段4
验证方式：Fake ASR 自动化回归 + 主后端 FasterWhisper API smoke + 浏览器手动录音 UI smoke
```

- [ ] **Step 2: Check working tree**

Run:

```powershell
git status --short
```

Expected: existing unrelated untracked files may include `.claude-smoke-ui.mjs` and `docs/superpowers/plans/`. Do not delete them.

- [ ] **Step 3: List pinned model cache paths**

Run:

```powershell
.\.venv-asr-bench\Scripts\python.exe scripts\download_asr_models.py --list-only
```

Expected: output lists `small` and `medium` pinned snapshot paths. Record whether `medium` and `small` are present.

---

### Task 2: Run Default Fake ASR Regression

**Files:**
- No file edits.

- [ ] **Step 1: Run backend tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -v
```

Expected: all backend tests pass. Previously expected count was 200; accept a different count only if every test passes.

- [ ] **Step 2: Run frontend unit tests**

Run:

```powershell
Push-Location frontend
npm test -- --run
Pop-Location
```

Expected: all Vitest tests pass.

- [ ] **Step 3: Run frontend typecheck**

Run:

```powershell
Push-Location frontend
npm run typecheck
Pop-Location
```

Expected: TypeScript exits successfully.

- [ ] **Step 4: Run frontend build**

Run:

```powershell
Push-Location frontend
npm run build
Pop-Location
```

Expected: Vite build exits successfully.

- [ ] **Step 5: Run fake E2E**

Run:

```powershell
Push-Location frontend
npm run test:e2e
Pop-Location
```

Expected: all Playwright E2E tests pass without real ASR or real LLM calls.

---

### Task 3: Install or Verify Main `.venv` ASR Extras

**Files:**
- No file edits unless documenting a blocker later.

- [ ] **Step 1: Install optional ASR dependencies into main `.venv`**

Run:

```powershell
.\.venv\Scripts\python.exe -m pip install -e "backend[asr]"
```

Expected: install succeeds. If permission policy blocks the command, stop implementation and ask the user to run:

```powershell
! .\.venv\Scripts\python.exe -m pip install -e "backend[asr]"
```

- [ ] **Step 2: Verify imports in main `.venv`**

Run:

```powershell
.\.venv\Scripts\python.exe -c "import faster_whisper, ctranslate2; print('faster_whisper import ok'); print('ctranslate2 import ok')"
```

Expected:

```text
faster_whisper import ok
ctranslate2 import ok
```

- [ ] **Step 3: Verify provider can be constructed**

Replace `<medium_snapshot_path>` with the path from Task 1.

Run:

```powershell
$env:ASR_PROVIDER = "faster-whisper"
$env:ASR_FASTER_WHISPER_MODEL_PATH = "<medium_snapshot_path>"
$env:ASR_FASTER_WHISPER_MODEL_NAME = "medium"
$env:ASR_FASTER_WHISPER_MODEL_REVISION = "08e178d48790749d25932bbc082711ddcfdfbc4f"
$env:ASR_FASTER_WHISPER_DEVICE = "cuda"
$env:ASR_FASTER_WHISPER_COMPUTE_TYPE = "float16"
$env:ASR_FASTER_WHISPER_BEAM_SIZE = "1"
$env:ASR_FASTER_WHISPER_TIMEOUT_SECONDS = "30"
.\.venv\Scripts\python.exe -c "from app.core.config import load_settings; from app.asr.factory import create_asr_provider; s=load_settings(); p=create_asr_provider(s); print(p.provider_name); print(p.public_model_name)"
```

Expected:

```text
faster-whisper
medium@08e178d48790749d25932bbc082711ddcfdfbc4f
```

---

### Task 4: Run Real ASR API Smoke Through Main FastAPI

**Files:**
- Optional create: `scripts/smoke_real_asr_api.py` only if needed.

- [ ] **Step 1: Choose non-private audio**

Use one existing pilot recording if available and non-private, such as the previously used `P001.m4a`. If no non-private file exists, record a short synthetic sentence manually:

```text
今天晚上我想先休息十分钟，然后再继续整理桌面。
```

Do not commit the audio file.

- [ ] **Step 2: Start backend with real ASR**

Run in a background terminal or background task:

```powershell
$env:LLM_PROVIDER = "fake"
$env:TTS_PROVIDER = "fake"
$env:ASR_PROVIDER = "faster-whisper"
$env:ASR_FASTER_WHISPER_MODEL_PATH = "<medium_snapshot_path>"
$env:ASR_FASTER_WHISPER_MODEL_NAME = "medium"
$env:ASR_FASTER_WHISPER_MODEL_REVISION = "08e178d48790749d25932bbc082711ddcfdfbc4f"
$env:ASR_FASTER_WHISPER_DEVICE = "cuda"
$env:ASR_FASTER_WHISPER_COMPUTE_TYPE = "float16"
$env:ASR_FASTER_WHISPER_BEAM_SIZE = "1"
$env:ASR_FASTER_WHISPER_TIMEOUT_SECONDS = "30"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Expected: backend starts and stays running.

- [ ] **Step 3: Post audio to transcription endpoint**

If `curl.exe` is available, run:

```powershell
curl.exe -s -X POST "http://127.0.0.1:8000/api/audio/transcriptions" -F "language=zh" -F "file=@<audio_path>;type=audio/mp4"
```

Expected JSON fields:

```json
{
  "text": "<non-empty>",
  "detected_language": "zh",
  "duration_ms": 0,
  "provider": "faster-whisper",
  "model": "medium@08e178d48790749d25932bbc082711ddcfdfbc4f",
  "inference_ms": 0
}
```

`duration_ms` and `inference_ms` must be positive or non-null if provided by the model. Do not paste a private transcript into docs; record transcript length and whether it is recognizably correct.

- [ ] **Step 4: If GPU smoke fails, try CPU fallback once**

Only after recording the GPU error, run the backend with:

```powershell
$env:ASR_FASTER_WHISPER_MODEL_PATH = "<small_snapshot_path>"
$env:ASR_FASTER_WHISPER_MODEL_NAME = "small"
$env:ASR_FASTER_WHISPER_MODEL_REVISION = "536b0662742c02347bc0e980a01041f333bce120"
$env:ASR_FASTER_WHISPER_DEVICE = "cpu"
$env:ASR_FASTER_WHISPER_COMPUTE_TYPE = "int8"
```

Expected: CPU fallback returns non-empty transcript, slower than GPU. If both fail, document both failures and do not mark 2B-6 complete.

---

### Task 5: Run Browser UI Smoke

**Files:**
- No file edits until documenting results.

- [ ] **Step 1: Start frontend dev server**

Keep the real-ASR backend running. Then run:

```powershell
Push-Location frontend
npm run dev
Pop-Location
```

Expected: Vite serves the app and proxies `/api` to `http://127.0.0.1:8000`.

- [ ] **Step 2: Manual browser smoke**

In the browser:

1. Open the Vite URL.
2. Create or select a session.
3. Click the recording control.
4. Record a short non-private Chinese sentence.
5. Stop recording.
6. Wait for transcription.
7. Confirm the transcript appears in the editable input.
8. Edit if needed and send.
9. Confirm the text chat still produces a fake LLM reply.
10. Confirm no unhandled browser console error appears.

Expected: transcript enters the input, no automatic send happens, and text mode remains usable.

- [ ] **Step 3: Record smoke result**

Record:

```text
UI smoke: PASS/FAIL
Backend provider: faster-whisper
Model: medium@08e178d48790749d25932bbc082711ddcfdfbc4f or CPU fallback
Transcript handling: entered editable input before manual send
Text fallback: PASS/FAIL
Console/server errors: none / list exact errors
```

---

### Task 6: Update Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/stage2b5-real-asr-provider.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update README Stage 2 summary**

Replace obsolete statements that say browser recording or real ASR are not available. Use precise wording:

```markdown
当前阶段：阶段 2——语音功能（Milestone 2A Fake TTS、2B 手动录音/Fake ASR、2B-5 FasterWhisper Provider baseline 已完成；2B-6 主应用真实 ASR smoke 状态见下文）。
```

- [ ] **Step 2: Add real ASR setup section to README**

Add this section after the Fake ASR section, adjusting verification results to actual evidence:

```markdown
### Stage 2B-6 Real ASR main-app smoke

Real ASR remains opt-in. Default tests and normal local development still use `ASR_PROVIDER=fake`.

Install optional ASR dependencies into the main backend environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -e "backend[asr]"
```

GPU candidate configuration:

```powershell
$env:ASR_PROVIDER = "faster-whisper"
$env:ASR_FASTER_WHISPER_MODEL_PATH = "<local faster-whisper-medium snapshot>"
$env:ASR_FASTER_WHISPER_MODEL_NAME = "medium"
$env:ASR_FASTER_WHISPER_MODEL_REVISION = "08e178d48790749d25932bbc082711ddcfdfbc4f"
$env:ASR_FASTER_WHISPER_DEVICE = "cuda"
$env:ASR_FASTER_WHISPER_COMPUTE_TYPE = "float16"
$env:ASR_FASTER_WHISPER_BEAM_SIZE = "1"
$env:ASR_FASTER_WHISPER_TIMEOUT_SECONDS = "30"
```

CPU fallback candidate:

```powershell
$env:ASR_FASTER_WHISPER_MODEL_PATH = "<local faster-whisper-small snapshot>"
$env:ASR_FASTER_WHISPER_MODEL_NAME = "small"
$env:ASR_FASTER_WHISPER_MODEL_REVISION = "536b0662742c02347bc0e980a01041f333bce120"
$env:ASR_FASTER_WHISPER_DEVICE = "cpu"
$env:ASR_FASTER_WHISPER_COMPUTE_TYPE = "int8"
```

Verification result on 2026-06-26: `<replace with actual PASS/blocked/failed result>`.
```

- [ ] **Step 3: Add 2B-6 addendum to provider doc**

Append to `docs/stage2b5-real-asr-provider.md`:

```markdown
## 2B-6 main application smoke — 2026-06-26

Status: `<PASS / BLOCKED / FAIL>`

Verification:

- Main `.venv` ASR extra install: `<result>`
- Main `.venv` import check: `<result>`
- Backend regression with Fake ASR: `<result>`
- Frontend regression: `<result>`
- Real ASR API smoke: `<result>`
- Browser manual recording UI smoke: `<result>`

Notes:

- Real ASR remains opt-in through `ASR_PROVIDER=faster-whisper`.
- Fake ASR remains the default automated test path.
- This smoke does not decide final production ASR selection.
- This smoke does not implement real TTS, 2C, VAD, interruption, streaming, memory, or emotion.
```

Replace placeholders with actual evidence before saving.

- [ ] **Step 4: Update CLAUDE.md status**

Only if smoke actually passes, update Stage 2 status lines to include:

```markdown
- 子任务 2B-6：Real ASR Main-App Smoke 已完成（2026-06-26；主 `.venv` 可加载 FasterWhisper；真实 ASR API smoke PASS；浏览器手动录音 UI smoke PASS；Fake ASR 默认自动化回归保持 PASS）。真实 ASR 仍需显式 `ASR_PROVIDER=faster-whisper` 启用；Production ASR Selection 仍未最终决定。
```

If blocked or failed, write the blocker instead and leave the task incomplete.

---

### Task 7: Final Verification and Report

**Files:**
- No additional file edits unless documentation has inaccuracies.

- [ ] **Step 1: Check git diff**

Run:

```powershell
git diff -- README.md docs/stage2b5-real-asr-provider.md CLAUDE.md
```

Expected: documentation matches actual evidence and contains no private transcript or local secret.

- [ ] **Step 2: Check status**

Run:

```powershell
git status --short
```

Expected: only intended documentation files and pre-existing unrelated untracked files are present.

- [ ] **Step 3: Commit documentation updates**

Run:

```powershell
git add README.md docs/stage2b5-real-asr-provider.md CLAUDE.md
git commit -m "docs: record real ASR main app smoke"
```

Expected: commit succeeds.

- [ ] **Step 4: Final report**

Report using the project-required format:

```text
完成内容：
修改文件：
验证命令与结果：
未完成或受限部分：
是否改变当前阶段：否（阶段 2 仍在 IMPLEMENTING；未进入阶段 3/4）
下一项建议任务：
```

Next recommended task after a PASS: begin real local TTS provider selection/integration planning, because ASR input is then validated in the main app and Stage 2 still lacks natural output speech.
