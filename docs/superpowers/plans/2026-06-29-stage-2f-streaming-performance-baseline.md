# Stage 2F-1 Streaming Performance Measurement Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this Claude Code session, do not create git commits unless the user explicitly asks; treat commit steps as review checkpoints only.

**Goal:** Add a repeatable fake-provider browser measurement baseline for the existing non-streaming half-duplex voice turn.

**Architecture:** Add a dev-only Playwright script under `frontend/scripts/` that drives the real browser UI, captures ASR/chat/TTS/playback timing, validates request counts and console errors, and prints JSON. Keep app runtime behavior unchanged; document the fake-provider baseline separately from real-provider performance.

**Tech Stack:** Node.js ESM, Playwright, React/Vite app, existing FastAPI fake providers, existing Playwright browser media stubs.

---

## File structure

### Create

- `frontend/scripts/measure-voice-turn-latency.mjs`
  - Runs browser automation against a running frontend/backend pair.
  - Emits per-run and aggregate latency JSON.

- `docs/stage2f-streaming-performance-baseline.md`
  - Evidence document after validation passes.

### Modify

- `frontend/package.json`
  - Add `measure:voice-turn` script.

- `README.md`, `CLAUDE.md`, `docs/stage2-voice-architecture.md`
  - Update only after validation passes.

### Do not modify

- Backend runtime code.
- Database schema.
- ASR/TTS provider interfaces.
- Frontend production UI behavior.
- Stage 3 memory files.
- Stage 4 emotion files.

---

## Task 1: Add the measurement script

**Files:**
- Create: `frontend/scripts/measure-voice-turn-latency.mjs`

- [ ] **Step 1: Create the script**

Create `frontend/scripts/measure-voice-turn-latency.mjs` with this content:

```js
import { chromium } from '@playwright/test';

const frontendUrl = process.env.MEASURE_FRONTEND_URL || 'http://127.0.0.1:15176';
const runCount = Number.isFinite(Number(process.env.MEASURE_RUNS)) && Number(process.env.MEASURE_RUNS) > 0
  ? Math.floor(Number(process.env.MEASURE_RUNS))
  : 3;

function now() {
  return performance.now();
}

function round(value) {
  return Math.round(value * 100) / 100;
}

function stats(values) {
  const finite = values.filter((value) => Number.isFinite(value));
  if (finite.length === 0) return { min: null, mean: null, max: null };
  return {
    min: round(Math.min(...finite)),
    mean: round(finite.reduce((sum, value) => sum + value, 0) / finite.length),
    max: round(Math.max(...finite)),
  };
}

function summarize(runs) {
  return {
    recordingMs: stats(runs.map((run) => run.recordingMs)),
    stopToTranscriptMs: stats(runs.map((run) => run.stopToTranscriptMs)),
    sendToAssistantVisibleMs: stats(runs.map((run) => run.sendToAssistantVisibleMs)),
    chatRequestMs: stats(runs.map((run) => run.chatRequestMs)),
    ttsRequestMs: stats(runs.map((run) => run.ttsRequestMs)),
    ttsResponseToPlayMs: stats(runs.map((run) => run.ttsResponseToPlayMs)),
    sendToPlaybackMs: stats(runs.map((run) => run.sendToPlaybackMs)),
    endToEndMs: stats(runs.map((run) => run.endToEndMs)),
  };
}

function jsonResponse(body, status = 200) {
  return {
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  };
}

function wavResponse() {
  return {
    status: 200,
    contentType: 'audio/wav',
    body: Buffer.from([82, 73, 70, 70, 0, 0, 0, 0, 87, 65, 86, 69]),
    headers: {
      'X-TTS-Provider': 'fake',
      'X-TTS-Model': 'fake-tone-v1',
      'X-Audio-Duration-Ms': '100',
      'X-Audio-Sample-Rate': '24000',
    },
  };
}

function makeRequestTracker() {
  const requests = [];
  return {
    requests,
    begin(kind) {
      const entry = { kind, start: now(), end: null };
      requests.push(entry);
      return entry;
    },
    end(entry) {
      entry.end = now();
    },
    count(kind) {
      return requests.filter((request) => request.kind === kind).length;
    },
    duration(kind, sinceIndex = 0) {
      const entry = requests.filter((request) => request.kind === kind)[sinceIndex];
      return entry && entry.end !== null ? entry.end - entry.start : null;
    },
  };
}

async function waitForReachable(page, url) {
  const response = await page.request.get(url, { timeout: 10_000 });
  if (!response.ok()) {
    throw new Error(`Frontend is not reachable at ${url}: HTTP ${response.status()}`);
  }
}

async function main() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  const tracker = makeRequestTracker();

  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await page.addInitScript(() => {
    class FakeMediaRecorder {
      static isTypeSupported() { return true; }
      state = 'inactive';
      mimeType = 'audio/webm';
      ondataavailable = null;
      onstop = null;
      onerror = null;
      start() { this.state = 'recording'; }
      stop() {
        this.state = 'inactive';
        this.ondataavailable?.({ data: new Blob(['voice'], { type: 'audio/webm' }) });
        this.onstop?.();
      }
    }

    const playCalls = [];
    Object.defineProperty(window, 'MediaRecorder', { value: FakeMediaRecorder });
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        enumerateDevices: async () => [
          { deviceId: 'default', groupId: 'g1', kind: 'audioinput', label: 'Default Mic', toJSON: () => ({}) },
        ],
        getUserMedia: async () => ({ getTracks: () => [{ stop() {}, addEventListener() {} }] }),
        addEventListener() {},
        removeEventListener() {},
      },
    });
    HTMLMediaElement.prototype.play = async () => {
      playCalls.push(performance.now());
      return undefined;
    };
    HTMLMediaElement.prototype.pause = () => undefined;
    window.__voiceMeasurePlayCalls = playCalls;
  });

  await page.route('**/api/audio/transcriptions', async (route) => {
    const entry = tracker.begin('transcription');
    await route.fulfill(jsonResponse({
      text: '语音转写文本',
      detected_language: 'zh',
      duration_ms: 1000,
      provider: 'fake-asr',
      model: 'fake-asr-v1',
      inference_ms: 1,
    }));
    tracker.end(entry);
  });

  await page.route('**/api/audio/speech', async (route) => {
    const entry = tracker.begin('tts');
    await route.fulfill(wavResponse());
    tracker.end(entry);
  });

  page.on('request', (request) => {
    const url = new URL(request.url());
    if (request.method() === 'POST' && /^\/api\/sessions\/[^/]+\/messages$/.test(url.pathname)) {
      request.__voiceMeasureKind = 'chat';
      request.__voiceMeasureStart = now();
    }
  });
  page.on('response', (response) => {
    const request = response.request();
    if (request.__voiceMeasureKind === 'chat') {
      tracker.requests.push({ kind: 'chat', start: request.__voiceMeasureStart, end: now() });
    }
  });

  await waitForReachable(page, frontendUrl);
  await page.goto(frontendUrl);
  await page.getByRole('button', { name: '新建会话' }).click();
  await page.getByRole('button', { name: '开始录音' }).waitFor({ state: 'visible' });

  const runs = [];
  for (let index = 1; index <= runCount; index += 1) {
    const beforeTranscription = tracker.count('transcription');
    const beforeChat = tracker.count('chat');
    const beforeTts = tracker.count('tts');
    const beforePlayCalls = await page.evaluate(() => window.__voiceMeasurePlayCalls.length);

    const runStart = now();
    await page.getByRole('button', { name: '开始录音' }).click();
    const recordStart = now();
    await page.waitForTimeout(350);
    await page.getByRole('button', { name: '停止录音' }).click();
    const stopClick = now();
    await page.getByText(/转写待确认/).waitFor({ state: 'visible', timeout: 5000 });
    const transcriptReady = now();

    await page.getByRole('button', { name: '发送并朗读' }).click();
    const sendClick = now();
    await page.getByText(/我听见了：语音转写文本/).last().waitFor({ state: 'visible', timeout: 5000 });
    const assistantVisible = now();
    await page.waitForFunction(
      (expected) => window.__voiceMeasurePlayCalls.length >= expected,
      beforePlayCalls + 1,
      { timeout: 5000 },
    );
    const playCalls = await page.evaluate(() => window.__voiceMeasurePlayCalls);
    const playbackTriggered = playCalls[beforePlayCalls];

    const transcriptionRequests = tracker.count('transcription') - beforeTranscription;
    const chatPostRequests = tracker.count('chat') - beforeChat;
    const ttsRequests = tracker.count('tts') - beforeTts;
    const playCallCount = playCalls.length - beforePlayCalls;
    const chatRequestMs = tracker.duration('chat', beforeChat);
    const ttsRequestMs = tracker.duration('tts', beforeTts);

    const run = {
      index,
      recordingMs: round(stopClick - recordStart),
      stopToTranscriptMs: round(transcriptReady - stopClick),
      sendToAssistantVisibleMs: round(assistantVisible - sendClick),
      chatRequestMs: chatRequestMs === null ? null : round(chatRequestMs),
      ttsRequestMs: ttsRequestMs === null ? null : round(ttsRequestMs),
      ttsResponseToPlayMs: ttsRequestMs === null ? null : round(playbackTriggered - (tracker.requests.filter((request) => request.kind === 'tts')[beforeTts]?.end ?? playbackTriggered)),
      sendToPlaybackMs: round(playbackTriggered - sendClick),
      endToEndMs: round(playbackTriggered - runStart),
      transcriptionRequests,
      chatPostRequests,
      ttsRequests,
      playCalls: playCallCount,
    };

    const validCounts = transcriptionRequests === 1 && chatPostRequests === 1 && ttsRequests === 1 && playCallCount === 1;
    if (!validCounts) {
      run.invalidReason = 'Expected exactly one transcription, chat, TTS, and playback event.';
    }
    runs.push(run);
  }

  const output = {
    runCount,
    frontendUrl,
    runs,
    summary: summarize(runs),
    consoleErrors,
    pageErrors,
  };

  console.log(JSON.stringify(output, null, 2));

  const invalidRun = runs.find((run) => run.invalidReason);
  if (invalidRun || consoleErrors.length > 0 || pageErrors.length > 0) {
    await browser.close();
    process.exit(1);
  }

  await browser.close();
}

main().catch(async (error) => {
  console.error(error);
  process.exit(1);
});
```

- [ ] **Step 2: Run script before package entry**

Run with app not running:

```powershell
Push-Location frontend
node scripts/measure-voice-turn-latency.mjs
Pop-Location
```

Expected: FAIL with a clear frontend-not-reachable error. This verifies the script fails safely when no app is running.

---

## Task 2: Add npm script

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Add package script**

In `frontend/package.json`, change the scripts block to include:

```json
"measure:voice-turn": "node scripts/measure-voice-turn-latency.mjs"
```

Keep existing scripts unchanged.

- [ ] **Step 2: Run npm script with app not running**

Run:

```powershell
Push-Location frontend
npm run measure:voice-turn
Pop-Location
```

Expected: FAIL with the same frontend-not-reachable error.

---

## Task 3: Runtime measurement validation

**Files:**
- Read/validate: `frontend/scripts/measure-voice-turn-latency.mjs`

- [ ] **Step 1: Start backend**

Run from repo root in a background terminal:

```powershell
$env:APP_ENV='test'
$env:DATABASE_URL='sqlite:///./test-results/measure-voice-turn.db'
$env:LLM_PROVIDER='fake'
$env:LLM_MODEL='test-model'
$env:FAKE_PROVIDER_MODE='ok'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 18103 --no-access-log
```

Expected: backend responds at `http://127.0.0.1:18103/health`.

- [ ] **Step 2: Start frontend**

Run from repo root in a background terminal:

```powershell
Push-Location frontend
$env:BACKEND_PROXY_TARGET='http://127.0.0.1:18103'
npm run dev -- --host 127.0.0.1 --port 15176 --mode test
Pop-Location
```

Expected: frontend responds at `http://127.0.0.1:15176`.

- [ ] **Step 3: Run measurement**

Run:

```powershell
Push-Location frontend
$env:MEASURE_FRONTEND_URL='http://127.0.0.1:15176'
$env:MEASURE_RUNS='3'
npm run measure:voice-turn
Pop-Location
```

Expected: PASS. Output JSON has `runCount: 3`, three valid runs, zero console/page errors, and every run has exactly one transcription/chat/TTS/play event.

---

## Task 4: Regression validation

**Files:**
- Read/validate only.

- [ ] **Step 1: Run App tests**

```powershell
Push-Location frontend
npm test -- --run src/App.test.tsx
Pop-Location
```

Expected: PASS.

- [ ] **Step 2: Run all frontend unit tests**

```powershell
Push-Location frontend
npm test -- --run
Pop-Location
```

Expected: PASS.

- [ ] **Step 3: Run typecheck**

```powershell
Push-Location frontend
npm run typecheck
Pop-Location
```

Expected: PASS.

- [ ] **Step 4: Run build**

```powershell
Push-Location frontend
npm run build
Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Run E2E**

```powershell
Push-Location frontend
npm run test:e2e
Pop-Location
```

Expected: PASS — 5 tests.

---

## Task 5: Record evidence and update docs

**Files:**
- Create: `docs/stage2f-streaming-performance-baseline.md`
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `docs/stage2-voice-architecture.md`

- [ ] **Step 1: Write evidence document**

Create `docs/stage2f-streaming-performance-baseline.md`:

```markdown
# Stage 2F-1 Streaming Performance Measurement Baseline Evidence

Status: COMPLETED on 2026-06-29 if and only if all validation rows below are PASS.

## Scope

This slice adds a repeatable fake-provider browser measurement baseline for the existing non-streaming half-duplex voice turn. It measures ASR, chat, TTS, playback trigger, and end-to-end timing through the real browser UI.

It does not implement streaming ASR, streaming TTS, output device selection, long-term memory, or emotion behavior.

## Validation

| Command | Result |
|---|---|
| `npm run measure:voice-turn` with fake backend/frontend | PASS |
| `npm test -- --run src/App.test.tsx` | PASS |
| `npm test -- --run` | PASS |
| `npm run typecheck` | PASS |
| `npm run build` | PASS |
| `npm run test:e2e` | PASS |

## Measurement output

Paste the JSON measurement output here.

## Notes

- This is a fake-provider browser baseline only.
- These values are useful for regression comparison and measurement shape, not for real provider latency claims.
- No real microphone, real ASR, real LLM, or real TTS provider was used.
```

- [ ] **Step 2: Update README after PASS**

Add a `Stage 2F-1 streaming/performance measurement baseline` section noting script command and fake-provider limitation.

- [ ] **Step 3: Update CLAUDE.md after PASS**

Add `2F-1 Streaming/Performance Measurement Baseline COMPLETED` in header/table and completed abilities. Keep streaming ASR/TTS itself as NOT STARTED.

- [ ] **Step 4: Update architecture doc**

Append an addendum that measurement baseline exists and streaming remains unimplemented.

- [ ] **Step 5: Check working tree**

Run:

```powershell
git status --short
```

Expected: no `.env`, raw audio, private speech artifacts, API keys, or tokens.

---

## Self-review

- Spec coverage: Plan covers script, npm entry, runtime measurement, validation, evidence, and docs.
- Placeholder scan: No TODO/TBD placeholders remain; evidence document intentionally says to paste actual measurement only during execution.
- Type consistency: Script names, env vars, JSON fields, and docs use the same names.
- Scope check: No streaming implementation, backend changes, memory, emotion, or schema changes.
