# Stage 2C-2 Real-provider Full-turn Smoke Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate and record one real-provider half-duplex voice turn using FasterWhisper ASR, a real configured LLM provider, and CosyVoice HTTP TTS.

**Architecture:** Keep the app runtime unchanged unless the smoke exposes a directly related defect. Add a focused Playwright smoke driver that reuses the existing 2C-1 UI, a PowerShell runner that starts the already implemented backend/frontend with explicit real-provider environment, and documentation updates that record pass/fail evidence without secrets or audio artifacts.

**Tech Stack:** PowerShell 5.1, Node.js ESM, Playwright, React/Vite dev server, FastAPI/Uvicorn backend, FasterWhisper ASR, existing LLM provider adapters, CosyVoice OpenAI-compatible local TTS server.

---

## File structure

### Create

- `frontend/.claude-real-full-turn-ui-smoke.mjs`
  - Browser smoke driver for the full 2C-2 path.
  - Uses a committed benchmark corpus audio file through a browser `MediaRecorder` shim by default so the ASR step is real and reproducible.
  - Collects `/api/audio/transcriptions`, `/api/sessions/*/messages`, and `/api/audio/speech` request/response metadata.
  - Writes `frontend/test-results/real-full-turn-ui-smoke.json` and `frontend/test-results/real-full-turn-ui-smoke.png`.
  - Does not write audio files, API keys, full private transcripts, or full assistant replies.
- `scripts/smoke_real_full_turn_ui.ps1`
  - PowerShell runner for 2C-2.
  - Checks that CosyVoice is already reachable, LLM credentials exist without printing them, and FasterWhisper model path exists.
  - Starts backend and frontend on isolated smoke ports, runs the browser driver, and cleans up jobs.
- `scripts/smoke_real_full_turn_ui.cmd`
  - Thin Windows wrapper that calls the PowerShell runner.

### Modify after smoke result is known

- `docs/stage2c-half-duplex-voice-turn.md`
  - Record 2C-2 commands, provider metadata, verdict, console error count, and any blocked/failure reason.
- `README.md`
  - Update Stage 2 status and usage docs only after evidence is known.
- `CLAUDE.md`
  - Update official project status only after evidence is known.

### Do not modify unless the smoke reveals a directly related bug

- `backend/app/api/routes/audio.py`
- `backend/app/api/routes/chat.py`
- `backend/app/services/asr_service.py`
- `backend/app/services/tts_service.py`
- `frontend/src/App.tsx`
- `frontend/src/components/MessageInput.tsx`
- `frontend/src/components/VoiceRecorder.tsx`
- `frontend/src/hooks/useAudioPlaybackController.ts`

---

## Task 1: Create the browser full-turn smoke driver

**Files:**
- Create: `frontend/.claude-real-full-turn-ui-smoke.mjs`

- [ ] **Step 1: Write the smoke driver**

Create `frontend/.claude-real-full-turn-ui-smoke.mjs`:

```js
import { chromium } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import readline from 'node:readline/promises';

const port = parseInt(process.env.E2E_FRONTEND_PORT ?? '16003', 10);
const frontendUrl = `http://127.0.0.1:${port}`;
const corpusAudioPath = path.resolve('..', 'asr-benchmark-corpus/clean/P001.m4a');
const resultsDir = path.resolve('test-results');
const screenshotPath = path.join(resultsDir, 'real-full-turn-ui-smoke.png');
const resultPath = path.join(resultsDir, 'real-full-turn-ui-smoke.json');
const headed = process.env.REAL_FULL_TURN_HEADLESS !== '1';
const requireAudioConfirm = process.env.REAL_FULL_TURN_REQUIRE_AUDIO_CONFIRM !== '0';

await fs.mkdir(resultsDir, { recursive: true });

const audioBytes = await fs.readFile(corpusAudioPath);
const audioBase64 = audioBytes.toString('base64');

const browser = await chromium.launch({ headless: !headed, channel: 'msedge' });
const page = await browser.newPage();
const consoleErrors = [];
const apiRequests = [];
const apiResponses = [];

function compactBody(body) {
  try {
    const json = JSON.parse(body);
    if (json.text) json.text_preview = String(json.text).slice(0, 18);
    if (json.text) json.text_length = String(json.text).length;
    delete json.text;
    if (json.reply) json.reply_preview = String(json.reply).slice(0, 18);
    if (json.reply) json.reply_length = String(json.reply).length;
    delete json.reply;
    return json;
  } catch {
    return { non_json_body_prefix: body.slice(0, 120) };
  }
}

page.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text());
});
page.on('pageerror', (error) => consoleErrors.push(error.message));
page.on('request', (request) => {
  const url = request.url();
  if (url.includes('/api/audio/transcriptions') || url.includes('/api/audio/speech') || /\/api\/sessions\/[^/]+\/messages/.test(url)) {
    apiRequests.push({ method: request.method(), url: url.replace(/sessions\/[^/]+/, 'sessions/<session-id>') });
  }
});
page.on('response', async (response) => {
  const url = response.url();
  const relevant = url.includes('/api/audio/transcriptions') || url.includes('/api/audio/speech') || /\/api\/sessions\/[^/]+\/messages/.test(url);
  if (!relevant) return;

  const headers = response.headers();
  let bodySummary = null;
  const contentType = headers['content-type'] ?? '';
  if (contentType.includes('application/json')) {
    try {
      bodySummary = compactBody(await response.text());
    } catch (error) {
      bodySummary = { read_error: error.message };
    }
  }

  apiResponses.push({
    url: url.replace(/sessions\/[^/]+/, 'sessions/<session-id>'),
    status: response.status(),
    contentType,
    provider: headers['x-tts-provider'] ?? bodySummary?.provider ?? bodySummary?.metadata?.provider,
    model: headers['x-tts-model'] ?? bodySummary?.model ?? bodySummary?.metadata?.model,
    durationMs: headers['x-audio-duration-ms'] ?? bodySummary?.duration_ms,
    inferenceMs: headers['x-tts-inference-ms'] ?? bodySummary?.inference_ms,
    sampleRate: headers['x-audio-sample-rate'],
    bodySummary,
  });
});

await page.addInitScript(({ audioBase64 }) => {
  function base64ToUint8Array(base64) {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return bytes;
  }

  class FakeTrack extends EventTarget {
    kind = 'audio';
    enabled = true;
    muted = false;
    readyState = 'live';
    stop() {
      if (this.readyState === 'ended') return;
      this.readyState = 'ended';
      this.dispatchEvent(new Event('ended'));
    }
  }

  class FakeStream {
    constructor() { this.track = new FakeTrack(); }
    getTracks() { return [this.track]; }
    getAudioTracks() { return [this.track]; }
    getVideoTracks() { return []; }
  }

  class FakeMediaRecorder extends EventTarget {
    static isTypeSupported(type) {
      return type === 'audio/mp4' || type === 'audio/webm' || type === 'audio/webm;codecs=opus';
    }
    constructor(stream) {
      super();
      this.stream = stream;
      this.mimeType = 'audio/mp4';
      this.state = 'inactive';
      this.ondataavailable = null;
      this.onstop = null;
      this.onerror = null;
    }
    start() { this.state = 'recording'; }
    stop() {
      if (this.state !== 'recording') return;
      this.state = 'inactive';
      const blob = new Blob([base64ToUint8Array(audioBase64)], { type: 'audio/mp4' });
      const dataEvent = new Event('dataavailable');
      Object.defineProperty(dataEvent, 'data', { value: blob });
      setTimeout(() => {
        this.ondataavailable?.(dataEvent);
        this.dispatchEvent(dataEvent);
        const stopEvent = new Event('stop');
        this.onstop?.(stopEvent);
        this.dispatchEvent(stopEvent);
      }, 0);
    }
  }

  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: async () => new FakeStream() },
  });
  Object.defineProperty(window, 'MediaRecorder', {
    configurable: true,
    value: FakeMediaRecorder,
  });
}, { audioBase64 });

let failure = null;
let transcript = '';
let audioConfirmed = false;

try {
  await page.goto(frontendUrl, { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: '新建会话' }).click();
  await page.getByRole('button', { name: '开始录音' }).click();
  await page.waitForTimeout(700);
  await page.getByRole('button', { name: '停止录音' }).click();
  await page.waitForResponse((response) => response.url().includes('/api/audio/transcriptions'), { timeout: 120000 });
  await page.getByText(/转写待确认：/).waitFor({ timeout: 20000 });

  const pendingText = await page.locator('body').innerText();
  const transcriptMatch = pendingText.match(/转写待确认：\s*([^\n]+)/);
  transcript = transcriptMatch?.[1]?.trim() ?? '';

  await page.getByRole('button', { name: '发送并朗读' }).click();
  await page.waitForResponse((response) => /\/api\/sessions\/[^/]+\/messages/.test(response.url()) && response.request().method() === 'POST', { timeout: 120000 });
  await page.waitForResponse((response) => response.url().includes('/api/audio/speech'), { timeout: 180000 });
  await page.waitForTimeout(2000);

  if (requireAudioConfirm) {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    const answer = await rl.question('Did you hear the assistant reply audio play? Type y or n: ');
    rl.close();
    audioConfirmed = answer.trim().toLowerCase() === 'y';
  } else {
    audioConfirmed = true;
  }
} catch (error) {
  failure = `${error.name}: ${error.message}`;
}

const bodyText = await page.locator('body').innerText().catch(() => '');
await page.screenshot({ path: screenshotPath, fullPage: true }).catch(() => undefined);
await browser.close();

const transcriptionResponse = apiResponses.find((item) => item.url.includes('/api/audio/transcriptions'));
const chatResponse = apiResponses.find((item) => /\/api\/sessions\/<session-id>\/messages/.test(item.url) && item.status < 500);
const speechResponse = apiResponses.find((item) => item.url.includes('/api/audio/speech'));
const verdict = !failure
  && transcriptionResponse?.status === 200
  && chatResponse?.status === 200
  && speechResponse?.status === 200
  && transcript.trim().length > 0
  && audioConfirmed
  ? 'PASS'
  : 'FAIL';

const result = {
  verdict,
  failure,
  transcriptLength: transcript.length,
  transcriptPreview: transcript.slice(0, 18),
  bodyContainsTranscript: transcript ? bodyText.includes(transcript) : false,
  bodyContainsSendAndSpeak: bodyText.includes('发送并朗读'),
  audioConfirmed,
  consoleErrorCount: consoleErrors.length,
  consoleErrors,
  apiRequests,
  apiResponses,
  screenshotPath,
};

await fs.writeFile(resultPath, `${JSON.stringify(result, null, 2)}\n`, 'utf8');
console.log(JSON.stringify(result, null, 2));
if (verdict !== 'PASS') process.exit(1);
```

- [ ] **Step 2: Run syntax check**

Run:

```powershell
Push-Location frontend
node --check .claude-real-full-turn-ui-smoke.mjs
Pop-Location
```

Expected: PASS with no output and exit code `0`.

- [ ] **Step 3: Commit checkpoint only if commits are authorized**

If the user explicitly authorizes commits, run:

```powershell
git add frontend/.claude-real-full-turn-ui-smoke.mjs
git commit -m "test: add real full-turn UI smoke driver"
```

If commits are not authorized, skip this step and keep the file uncommitted.

---

## Task 2: Create the PowerShell real-provider smoke runner

**Files:**
- Create: `scripts/smoke_real_full_turn_ui.ps1`
- Create: `scripts/smoke_real_full_turn_ui.cmd`

- [ ] **Step 1: Write the PowerShell runner**

Create `scripts/smoke_real_full_turn_ui.ps1`:

```powershell
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptDir
Push-Location ..

$backendPort = 18003
$frontendPort = 16003
$cosyVoiceBaseUrl = if ($env:TTS_COSYVOICE_BASE_URL) { $env:TTS_COSYVOICE_BASE_URL } else { "http://127.0.0.1:8001" }
$modelPath = if ($env:ASR_FASTER_WHISPER_MODEL_PATH) { $env:ASR_FASTER_WHISPER_MODEL_PATH } else { "$env:USERPROFILE\.cache\huggingface\hub\models--Systran--faster-whisper-medium\snapshots\08e178d48790749d25932bbc082711ddcfdfbc4f" }
$llmProvider = if ($env:LLM_PROVIDER) { $env:LLM_PROVIDER } else { "deepseek" }

function Stop-PortOwner([int]$port) {
    $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) {
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

function Wait-HttpOk([string]$url, [string]$name, [int]$maxSeconds) {
    for ($i = 1; $i -le $maxSeconds; $i++) {
        Start-Sleep 1
        try {
            $r = Invoke-WebRequest $url -TimeoutSec 2 -UseBasicParsing
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300) {
                Write-Output "$name ready after ${i}s"
                return
            }
        } catch {}
    }
    throw "$name failed to become ready at $url"
}

try {
    if (-not (Test-Path $modelPath)) {
        throw "FasterWhisper model path not found: $modelPath"
    }

    if ($llmProvider -eq "deepseek" -and -not (Test-Path Env:DEEPSEEK_API_KEY)) {
        throw "LLM_PROVIDER=deepseek requires DEEPSEEK_API_KEY in the local environment. The key value was not printed."
    }
    if ($llmProvider -eq "anthropic" -and -not (Test-Path Env:ANTHROPIC_API_KEY)) {
        throw "LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY in the local environment. The key value was not printed."
    }
    if ($llmProvider -eq "fake") {
        throw "2C-2 requires a real LLM provider. Set LLM_PROVIDER=deepseek or another real configured provider."
    }

    Write-Output "Checking CosyVoice health at $cosyVoiceBaseUrl/health"
    $cosyHealth = Invoke-WebRequest "$cosyVoiceBaseUrl/health" -TimeoutSec 5 -UseBasicParsing
    if ($cosyHealth.StatusCode -lt 200 -or $cosyHealth.StatusCode -ge 300) {
        throw "CosyVoice health returned HTTP $($cosyHealth.StatusCode)"
    }

    foreach ($p in @($backendPort, $frontendPort)) {
        Stop-PortOwner $p
    }
    Start-Sleep 2

    $env:APP_ENV = "test"
    $env:LLM_PROVIDER = $llmProvider
    $env:ASR_PROVIDER = "faster-whisper"
    $env:ASR_FASTER_WHISPER_MODEL_PATH = $modelPath
    $env:ASR_FASTER_WHISPER_MODEL_NAME = if ($env:ASR_FASTER_WHISPER_MODEL_NAME) { $env:ASR_FASTER_WHISPER_MODEL_NAME } else { "medium" }
    $env:ASR_FASTER_WHISPER_MODEL_REVISION = if ($env:ASR_FASTER_WHISPER_MODEL_REVISION) { $env:ASR_FASTER_WHISPER_MODEL_REVISION } else { "08e178d48790749d25932bbc082711ddcfdfbc4f" }
    $env:ASR_FASTER_WHISPER_DEVICE = if ($env:ASR_FASTER_WHISPER_DEVICE) { $env:ASR_FASTER_WHISPER_DEVICE } else { "cuda" }
    $env:ASR_FASTER_WHISPER_COMPUTE_TYPE = if ($env:ASR_FASTER_WHISPER_COMPUTE_TYPE) { $env:ASR_FASTER_WHISPER_COMPUTE_TYPE } else { "float16" }
    $env:ASR_FASTER_WHISPER_BEAM_SIZE = if ($env:ASR_FASTER_WHISPER_BEAM_SIZE) { $env:ASR_FASTER_WHISPER_BEAM_SIZE } else { "1" }
    $env:ASR_FASTER_WHISPER_TIMEOUT_SECONDS = if ($env:ASR_FASTER_WHISPER_TIMEOUT_SECONDS) { $env:ASR_FASTER_WHISPER_TIMEOUT_SECONDS } else { "30" }
    $env:TTS_PROVIDER = "cosyvoice-http"
    $env:TTS_DEFAULT_VOICE = if ($env:TTS_DEFAULT_VOICE) { $env:TTS_DEFAULT_VOICE } else { "default-zh-female" }
    $env:TTS_COSYVOICE_BASE_URL = $cosyVoiceBaseUrl
    $env:TTS_COSYVOICE_MODEL = if ($env:TTS_COSYVOICE_MODEL) { $env:TTS_COSYVOICE_MODEL } else { "Fun-CosyVoice3-0.5B-2512" }
    $env:TTS_COSYVOICE_TIMEOUT_SECONDS = if ($env:TTS_COSYVOICE_TIMEOUT_SECONDS) { $env:TTS_COSYVOICE_TIMEOUT_SECONDS } else { "90" }
    $env:DATABASE_URL = "sqlite:///./test-results/smoke-real-full-turn.db"

    $beJob = Start-Job -Name "be-real-full-turn-smoke" -ScriptBlock {
        Set-Location $using:PWD
        & ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port $using:backendPort
    }
    Write-Output "Backend job: $($beJob.Id)"
    Wait-HttpOk "http://127.0.0.1:$backendPort/health" "Backend" 60

    $env:BACKEND_PROXY_TARGET = "http://127.0.0.1:$backendPort"
    Push-Location frontend
    $feJob = Start-Job -Name "fe-real-full-turn-smoke" -ScriptBlock {
        Set-Location $using:PWD
        & node .\node_modules\vite\bin\vite.js --port $using:frontendPort --host 127.0.0.1
    }
    Pop-Location
    Write-Output "Frontend job: $($feJob.Id)"
    Wait-HttpOk "http://127.0.0.1:$frontendPort/" "Frontend" 60

    Push-Location frontend
    $env:E2E_FRONTEND_PORT = "$frontendPort"
    if (-not $env:REAL_FULL_TURN_HEADLESS) { $env:REAL_FULL_TURN_HEADLESS = "0" }
    if (-not $env:REAL_FULL_TURN_REQUIRE_AUDIO_CONFIRM) { $env:REAL_FULL_TURN_REQUIRE_AUDIO_CONFIRM = "1" }
    node .claude-real-full-turn-ui-smoke.mjs
    $exitCode = $LASTEXITCODE
    Pop-Location

    if ($exitCode -ne 0) {
        throw "Real full-turn smoke failed with exit code $exitCode"
    }

    Write-Output "2C-2 real full-turn smoke PASS. Evidence: frontend/test-results/real-full-turn-ui-smoke.json"
    exit 0
} finally {
    Get-Job | Where-Object { $_.Name -like "*real-full-turn-smoke*" } | Stop-Job -ErrorAction SilentlyContinue
    Get-Job | Where-Object { $_.Name -like "*real-full-turn-smoke*" } | Remove-Job -Force -ErrorAction SilentlyContinue
    Pop-Location
    Pop-Location
}
```

- [ ] **Step 2: Write the Windows command wrapper**

Create `scripts/smoke_real_full_turn_ui.cmd`:

```bat
@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0smoke_real_full_turn_ui.ps1"
exit /b %ERRORLEVEL%
```

- [ ] **Step 3: Run a script parse check**

Run:

```powershell
$null = [System.Management.Automation.PSParser]::Tokenize((Get-Content scripts/smoke_real_full_turn_ui.ps1 -Raw), [ref]$null)
cmd /c scripts\smoke_real_full_turn_ui.cmd --help
```

Expected for the parser line: no output and no exception.

Expected for the `cmd` line: it may run preflight and fail because `--help` is not handled; if it starts the real smoke, stop it with Ctrl+C. If this behavior is inconvenient, do not use the `cmd` wrapper for validation and rely on the PowerShell runner directly.

- [ ] **Step 4: Commit checkpoint only if commits are authorized**

If the user explicitly authorizes commits, run:

```powershell
git add scripts/smoke_real_full_turn_ui.ps1 scripts/smoke_real_full_turn_ui.cmd
git commit -m "test: add real full-turn smoke runner"
```

If commits are not authorized, skip this step and keep the files uncommitted.

---

## Task 3: Run the 2C-2 real-provider smoke

**Files:**
- Uses: `scripts/smoke_real_full_turn_ui.ps1`
- Reads output: `frontend/test-results/real-full-turn-ui-smoke.json`
- Reads output: `frontend/test-results/real-full-turn-ui-smoke.png`

- [ ] **Step 1: Start CosyVoice HTTP server in a separate terminal if it is not already running**

Run this manually in the project root when needed:

```powershell
.\.venv-tts\Scripts\python.exe -m uvicorn scripts.cosyvoice3_openai_server:app --host 127.0.0.1 --port 8001
```

Expected: the process stays running and eventually serves `http://127.0.0.1:8001/health`.

- [ ] **Step 2: Confirm real LLM provider environment without printing secrets**

For DeepSeek, run:

```powershell
$env:LLM_PROVIDER = "deepseek"
if (Test-Path Env:DEEPSEEK_API_KEY) { "DEEPSEEK_API_KEY exists" } else { "DEEPSEEK_API_KEY missing" }
```

Expected: `DEEPSEEK_API_KEY exists`.

For Anthropic, run:

```powershell
$env:LLM_PROVIDER = "anthropic"
if (Test-Path Env:ANTHROPIC_API_KEY) { "ANTHROPIC_API_KEY exists" } else { "ANTHROPIC_API_KEY missing" }
```

Expected: `ANTHROPIC_API_KEY exists`.

Use one real provider only. Do not use `LLM_PROVIDER=fake` for 2C-2.

- [ ] **Step 3: Run the smoke**

Run:

```powershell
.\scripts\smoke_real_full_turn_ui.ps1
```

Expected on success:

```text
Backend ready after ...s
Frontend ready after ...s
Did you hear the assistant reply audio play? Type y or n:
2C-2 real full-turn smoke PASS. Evidence: frontend/test-results/real-full-turn-ui-smoke.json
```

When prompted, type `y` only if audible assistant speech played. Type `n` if no sound was heard.

- [ ] **Step 4: Inspect the evidence JSON**

Run:

```powershell
Get-Content frontend\test-results\real-full-turn-ui-smoke.json -Raw
```

Expected success indicators in the JSON:

```json
{
  "verdict": "PASS",
  "failure": null,
  "audioConfirmed": true,
  "consoleErrorCount": 0
}
```

The JSON also includes sanitized API metadata. It must not include API keys, full `.env` contents, raw audio bytes, or generated TTS audio.

- [ ] **Step 5: If the smoke fails, classify the failure**

Use the JSON fields to classify the failure as one of these concrete outcomes:

- `CosyVoice blocked`: runner cannot reach `/health`.
- `LLM blocked`: selected real provider key is missing.
- `ASR failed`: `/api/audio/transcriptions` is missing or non-200.
- `Chat failed`: `/api/sessions/<session-id>/messages` POST is missing or non-200.
- `TTS failed`: `/api/audio/speech` is missing or non-200.
- `Playback unconfirmed`: audio response succeeded but the operator typed `n`.
- `Console error failure`: `consoleErrorCount` is above zero and the error is related to the smoke flow.

Do not mark 2C-2 complete when the verdict is `FAIL`.

---

## Task 4: Record the 2C-2 evidence

**Files:**
- Modify: `docs/stage2c-half-duplex-voice-turn.md`
- Read: `frontend/test-results/real-full-turn-ui-smoke.json`

- [ ] **Step 1: Read the existing evidence doc and smoke JSON**

Run:

```powershell
Get-Content docs\stage2c-half-duplex-voice-turn.md -Raw
Get-Content frontend\test-results\real-full-turn-ui-smoke.json -Raw
```

Expected: the evidence doc contains the existing 2C-1 section and a 2C-2 section currently marked not completed; the JSON contains either `"verdict": "PASS"` or `"verdict": "FAIL"`.

- [ ] **Step 2: Update the 2C-2 evidence section for a PASS result**

If the JSON verdict is `PASS`, replace the `## 2C-2 Real-provider full-turn smoke` section in `docs/stage2c-half-duplex-voice-turn.md` with content in this shape, using concrete values from the JSON and the runner output:

```markdown
## 2C-2 Real-provider full-turn smoke

Status: COMPLETED on 2026-06-27.

Validation:

| Command | Result |
|---|---|
| `.\scripts\smoke_real_full_turn_ui.ps1` | PASS — FasterWhisper ASR, real LLM provider, and CosyVoice HTTP TTS completed one browser half-duplex voice turn |

Observed provider path:

- ASR: `faster-whisper` with configured model metadata captured in `frontend/test-results/real-full-turn-ui-smoke.json`.
- LLM: real configured provider; key existence was checked without printing or committing the key.
- TTS: `cosyvoice-http`; `/api/audio/speech` returned audio and browser playback was manually confirmed.

Smoke observations:

- Transcript appeared in the pending transcript UI before explicit send.
- `发送并朗读` sent the transcript through the normal chat path.
- Assistant text reply appeared in the message list.
- TTS request returned successfully through the main backend.
- Audible playback was confirmed by the operator.
- Browser console error count: 0.
- Evidence JSON: `frontend/test-results/real-full-turn-ui-smoke.json`.
- Screenshot: `frontend/test-results/real-full-turn-ui-smoke.png`.

Privacy and artifact notes:

- No API key values were printed.
- No raw microphone recording or generated TTS audio was committed.
- The smoke used the existing technical CosyVoice sample prompt for local TTS validation only; it does not clone or imitate Yukinoshita Yukino, any voice actor, celebrity, or unauthorized voice.

2C full half-duplex voice turn now has fake-provider automated regression evidence and real-provider local smoke evidence. Stage 2 remains open for VAD, interruption, audio device management, and streaming/performance work.
```

If `consoleErrorCount` is not `0`, keep the status incomplete unless the errors are unrelated and explicitly documented with a short explanation.

- [ ] **Step 3: Update the 2C-2 evidence section for a FAIL or blocked result**

If the JSON verdict is `FAIL`, replace the `## 2C-2 Real-provider full-turn smoke` section with content in this shape:

```markdown
## 2C-2 Real-provider full-turn smoke

Status: NOT COMPLETED.

Validation attempted on 2026-06-27:

| Command | Result |
|---|---|
| `.\scripts\smoke_real_full_turn_ui.ps1` | FAIL — the smoke did not satisfy all 2C-2 success criteria |

Observed failure classification:

- Classification: `ASR failed`, `Chat failed`, `TTS failed`, `Playback unconfirmed`, `CosyVoice blocked`, `LLM blocked`, or `Console error failure`.
- Evidence JSON: `frontend/test-results/real-full-turn-ui-smoke.json`.
- Screenshot: `frontend/test-results/real-full-turn-ui-smoke.png`.

2C-2 remains incomplete. Do not mark full 2C complete until a real-provider browser voice turn passes and is recorded.
```

Replace the classification list with the single classification from Task 3 Step 5.

- [ ] **Step 4: Commit checkpoint only if commits are authorized**

If the user explicitly authorizes commits, run:

```powershell
git add docs/stage2c-half-duplex-voice-turn.md
git commit -m "docs: record real provider full-turn smoke"
```

If commits are not authorized, skip this step and keep the doc uncommitted.

---

## Task 5: Update README and CLAUDE status based on the smoke verdict

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Read: `docs/stage2c-half-duplex-voice-turn.md`

- [ ] **Step 1: Update README for PASS**

If 2C-2 passed, update `README.md` so the top status and Stage 2 sections say:

- 2C-1 fake-provider baseline is completed.
- 2C-2 real-provider full-turn smoke is completed.
- VAD, interruption, audio device management, and streaming/performance remain unimplemented.
- Stage 3 memory and Stage 4 emotion remain unstarted.

Add a short section after the current `Stage 2C-1 Fake-provider half-duplex voice turn` section:

```markdown
### Stage 2C-2 Real-provider full-turn smoke

Real-provider full-turn smoke is opt-in and requires local real-provider configuration:

1. Start the local CosyVoice HTTP server on `127.0.0.1:8001`.
2. Set a real `LLM_PROVIDER` and its local API key environment variable.
3. Run `.\scripts\smoke_real_full_turn_ui.ps1`.
4. Confirm audible playback only when the browser plays the assistant reply.

Verification result on 2026-06-27: **PASS** — FasterWhisper ASR, a real configured LLM provider, and CosyVoice HTTP TTS completed one browser half-duplex voice turn. Evidence is recorded in `docs/stage2c-half-duplex-voice-turn.md`. This remains a technical local smoke; it does not implement VAD, interruption, streaming, long-term memory, or emotion.
```

- [ ] **Step 2: Update README for FAIL or blocked**

If 2C-2 failed or was blocked, keep README clear that 2C-2 is not complete. Add or keep this sentence near the Stage 2C status:

```markdown
Real-provider full-turn smoke with FasterWhisper + real LLM + CosyVoice HTTP is **not yet completed** and remains tracked as 2C-2; the latest attempted result is recorded in `docs/stage2c-half-duplex-voice-turn.md`.
```

- [ ] **Step 3: Update CLAUDE.md for PASS**

If 2C-2 passed, update `CLAUDE.md` conservatively:

- In the header and Stage 2 table, add `2C-2 Real Provider Full-Turn Smoke COMPLETED`.
- In the Stage 2 completed abilities list, add a bullet with the recorded evidence from `docs/stage2c-half-duplex-voice-turn.md`.
- In the Stage 2 unimplemented list, remove the 2C-2 item and keep VAD, interruption/turn control, audio device management, and streaming ASR/TTS.
- Keep Stage 2 as `IMPLEMENTING` because later Stage 2 items remain.
- Keep Stage 3 and Stage 4 as not started.

Use this exact completed-ability wording, adjusted only for the observed real LLM provider/model name if the evidence doc recorded it:

```markdown
- 子任务 2C-2：Real-provider full half-duplex voice turn smoke 已完成（2026-06-27；浏览器完成 FasterWhisper real ASR → 显式 `发送并朗读` → real LLM 文字回复 → CosyVoice HTTP TTS 播放；operator 确认听到 assistant 语音；console error count 0；证据记录于 `docs/stage2c-half-duplex-voice-turn.md`）。完整 2C 半双工语音回合已有 fake-provider 自动化回归与 real-provider 本地 smoke 证据；VAD、打断、音频设备管理、流式识别与流式合成仍未开始。
```

- [ ] **Step 4: Update CLAUDE.md for FAIL or blocked**

If 2C-2 failed or was blocked, do not mark it complete. Add a short attempted-evidence note under Stage 2 completed/observations only if useful, and keep this item in the unimplemented list:

```markdown
- 2C-2 真实 ASR + real LLM + CosyVoice HTTP 完整半双工语音回合 smoke。
```

- [ ] **Step 5: Scan for accidental secrets or audio artifacts in git status**

Run:

```powershell
git status --short
```

Expected: changed files include source scripts and docs only. The status must not include `.env`, raw microphone recordings, generated `.wav`/`.mp3`/`.m4a` output, Hugging Face model cache files, or private data files.

- [ ] **Step 6: Commit checkpoint only if commits are authorized**

If the user explicitly authorizes commits, run:

```powershell
git add README.md CLAUDE.md
git commit -m "docs: update stage 2c real full-turn status"
```

If commits are not authorized, skip this step and keep the files uncommitted.

---

## Task 6: Final validation and report

**Files:**
- Read: `frontend/test-results/real-full-turn-ui-smoke.json`
- Read: `docs/stage2c-half-duplex-voice-turn.md`
- Read: `README.md`
- Read: `CLAUDE.md`

- [ ] **Step 1: Run lightweight validation for added scripts**

Run:

```powershell
Push-Location frontend
node --check .claude-real-full-turn-ui-smoke.mjs
Pop-Location
$null = [System.Management.Automation.PSParser]::Tokenize((Get-Content scripts/smoke_real_full_turn_ui.ps1 -Raw), [ref]$null)
```

Expected: no syntax errors.

- [ ] **Step 2: Run backend/frontend regression if runtime code changed**

If any backend or frontend runtime file changed, run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -v
Push-Location frontend
npm test -- --run
npm run typecheck
npm run build
npm run test:e2e
Pop-Location
```

Expected: all tests pass. If a command fails, record the exact failing command and output summary. Do not claim 2C-2 closure based on failing regressions unless the failure is unrelated and explicitly justified.

If only scripts/docs changed, this full regression is optional. The required validation is the real-provider smoke plus syntax checks.

- [ ] **Step 3: Produce the project task-end report**

Report in the `CLAUDE.md` required format:

```text
完成内容：
修改文件：
验证命令与结果：
未完成或受限部分：
是否改变当前阶段：否/是（附验收证据）
下一项建议任务：
```

For PASS, the next suggested task is 2D VAD. For FAIL or blocked, the next suggested task is the smallest repair for the classified failure.

- [ ] **Step 4: Do not commit evidence artifacts unless explicitly requested**

Do not add these generated files to git unless the user explicitly asks:

```text
frontend/test-results/real-full-turn-ui-smoke.json
frontend/test-results/real-full-turn-ui-smoke.png
```

They can be cited in docs as local evidence paths, but they should remain uncommitted unless the project later decides to store smoke artifacts.

---

## Self-review

- Spec coverage: Tasks cover the browser smoke driver, PowerShell runner, real-provider execution, evidence recording, README/CLAUDE status updates, and final reporting.
- Stage boundary: The plan stays within Stage 2 voice validation and does not implement memory, emotion, VAD, interruption, streaming, or a new backend voice-turn endpoint.
- Privacy: The plan checks key existence without printing values and avoids committing audio, generated speech, model cache files, or secret files.
- Runtime risk: The plan does not change backend/frontend runtime code unless the smoke exposes a directly related defect.
- Type and command consistency: The script names are consistent: `frontend/.claude-real-full-turn-ui-smoke.mjs`, `scripts/smoke_real_full_turn_ui.ps1`, and `scripts/smoke_real_full_turn_ui.cmd`.
