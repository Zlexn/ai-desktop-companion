import { chromium } from '@playwright/test';
import { round, summarizeVoiceTurnRuns, validateStreamingVoiceTurnRun } from './measure-voice-turn-summary.mjs';

const frontendUrl = process.env.MEASURE_FRONTEND_URL || 'http://127.0.0.1:15176';
const parsedRunCount = Number(process.env.MEASURE_RUNS);
const runCount = Number.isFinite(parsedRunCount) && parsedRunCount > 0 ? Math.floor(parsedRunCount) : 3;

function now() {
  return performance.now();
}

function jsonResponse(body, status = 200) {
  return {
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  };
}

function speechStreamResponse() {
  const bytes = Buffer.from('RIFF....WAVEfirst', 'utf8');
  const body = [
    JSON.stringify({ type: 'start', provider: 'fake', model: 'fake-tone-v1' }) + '\n',
    JSON.stringify({ type: 'segment', index: 0, audio_base64: bytes.toString('base64'), media_type: 'audio/wav', duration_ms: 100, sample_rate: 16000 }) + '\n',
    JSON.stringify({ type: 'done', segment_count: 1 }) + '\n',
  ].join('');
  return {
    status: 200,
    contentType: 'application/x-ndjson',
    body,
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
  let response;
  try {
    response = await page.request.get(url, { timeout: 10_000 });
  } catch (error) {
    throw new Error(`Frontend is not reachable at ${url}: ${error instanceof Error ? error.message : String(error)}`);
  }
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
    const streamEvents = [];
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
      playCalls.push({ called: true, at: performance.now() });
      return undefined;
    };
    HTMLMediaElement.prototype.pause = () => undefined;
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const response = await originalFetch(input, init);
      const url = new URL(typeof input === 'string' ? input : input.url, window.location.href);
      if (url.pathname !== '/api/audio/speech/stream' || !response.body) return response;

      const decoder = new TextDecoder();
      let pending = '';
      const transform = new TransformStream({
        transform(chunk, controller) {
          pending += decoder.decode(chunk, { stream: true });
          const lines = pending.split('\n');
          pending = lines.pop() ?? '';
          for (const line of lines) {
            if (!line.trim()) continue;
            try {
              const event = JSON.parse(line);
              if (event.type === 'segment') streamEvents.push({ type: 'segment', index: event.index, at: performance.now() });
              if (event.type === 'done') streamEvents.push({ type: 'done', segmentCount: event.segment_count, at: performance.now() });
            } catch {
              streamEvents.push({ type: 'parse-error', at: performance.now() });
            }
          }
          controller.enqueue(chunk);
        },
        flush() {
          pending += decoder.decode();
          if (pending.trim()) {
            try {
              const event = JSON.parse(pending);
              if (event.type === 'segment') streamEvents.push({ type: 'segment', index: event.index, at: performance.now() });
              if (event.type === 'done') streamEvents.push({ type: 'done', segmentCount: event.segment_count, at: performance.now() });
            } catch {
              streamEvents.push({ type: 'parse-error', at: performance.now() });
            }
          }
        },
      });

      return new Response(response.body.pipeThrough(transform), {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers,
      });
    };
    window.__voiceMeasurePlayCalls = playCalls;
    window.__voiceMeasureStreamEvents = streamEvents;
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
    await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: { message: 'Legacy TTS route should not be used by streaming measurement.' } }) });
    tracker.end(entry);
  });

  await page.route('**/api/audio/speech/stream', async (route) => {
    await route.fulfill(speechStreamResponse());
  });

  page.on('request', (request) => {
    const url = new URL(request.url());
    if (request.method() === 'POST' && url.pathname === '/api/audio/speech/stream') {
      request.__voiceMeasureKind = 'streamTts';
      request.__voiceMeasureStart = now();
    }
    if (request.method() === 'POST' && /^\/api\/sessions\/[^/]+\/messages$/.test(url.pathname)) {
      request.__voiceMeasureKind = 'chat';
      request.__voiceMeasureStart = now();
    }
  });
  page.on('response', (response) => {
    const request = response.request();
    if (request.__voiceMeasureKind === 'chat' || request.__voiceMeasureKind === 'streamTts') {
      tracker.requests.push({ kind: request.__voiceMeasureKind, start: request.__voiceMeasureStart, end: now() });
    }
  });

  try {
    await waitForReachable(page, frontendUrl);
    await page.goto(frontendUrl);
    await page.getByRole('button', { name: '新建会话' }).click();
    await page.getByRole('button', { name: '开始录音' }).waitFor({ state: 'visible' });

    const runs = [];
    for (let index = 1; index <= runCount; index += 1) {
      const beforeTranscription = tracker.count('transcription');
      const beforeChat = tracker.count('chat');
      const beforeTts = tracker.count('tts');
      const beforeStreamTts = tracker.count('streamTts');
      const beforeStreamEvents = await page.evaluate(() => window.__voiceMeasureStreamEvents.length);
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
      const playbackTriggered = now();
      const playCalls = await page.evaluate(() => window.__voiceMeasurePlayCalls);
      const streamEvents = await page.evaluate(() => window.__voiceMeasureStreamEvents);

      const transcriptionRequests = tracker.count('transcription') - beforeTranscription;
      const chatPostRequests = tracker.count('chat') - beforeChat;
      const ttsRequests = tracker.count('tts') - beforeTts;
      const streamTtsRequests = tracker.count('streamTts') - beforeStreamTts;
      const playCallCount = playCalls.length - beforePlayCalls;
      const chatRequestMs = tracker.duration('chat', beforeChat);
      const streamTtsEntry = tracker.requests.filter((request) => request.kind === 'streamTts')[beforeStreamTts];
      const currentStreamEvents = streamEvents.slice(beforeStreamEvents);
      const firstSegmentEvent = currentStreamEvents.find((event) => event.type === 'segment');
      const doneEvent = currentStreamEvents.find((event) => event.type === 'done');
      const streamSegmentCount = currentStreamEvents.filter((event) => event.type === 'segment').length;

      const run = {
        index,
        recordingMs: round(stopClick - recordStart),
        stopToTranscriptMs: round(transcriptReady - stopClick),
        sendToAssistantVisibleMs: round(assistantVisible - sendClick),
        chatRequestMs: chatRequestMs === null ? null : round(chatRequestMs),
        streamTtsRequestToFirstSegmentMs: streamTtsEntry?.start === undefined || firstSegmentEvent?.at === undefined ? null : round(firstSegmentEvent.at - streamTtsEntry.start),
        streamFirstSegmentToPlayMs: firstSegmentEvent?.at === undefined ? null : round(playbackTriggered - firstSegmentEvent.at),
        streamSendToFirstPlaybackMs: round(playbackTriggered - sendClick),
        streamDoneMs: doneEvent?.at === undefined ? null : round(doneEvent.at - sendClick),
        streamSegmentCount,
        endToEndMs: round(playbackTriggered - runStart),
        transcriptionRequests,
        chatPostRequests,
        ttsRequests,
        streamTtsRequests,
        playCalls: playCallCount,
      };

      const invalidReason = validateStreamingVoiceTurnRun(run);
      if (invalidReason) {
        run.invalidReason = invalidReason;
      }
      runs.push(run);
    }

    const output = {
      runCount,
      frontendUrl,
      runs,
      summary: summarizeVoiceTurnRuns(runs),
      consoleErrors,
      pageErrors,
    };

    console.log(JSON.stringify(output, null, 2));

    const invalidRun = runs.find((run) => run.invalidReason);
    if (invalidRun || consoleErrors.length > 0 || pageErrors.length > 0) {
      process.exitCode = 1;
    }
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
