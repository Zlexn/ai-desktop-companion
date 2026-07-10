# Stage 2H Low-Gap Streaming Audio Playback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a browser-side Web Audio scheduler for streaming TTS segments so Stage 2 voice-turn playback can schedule adjacent audio chunks with lower gap than the current `HTMLAudioElement` ended-handler queue.

**Architecture:** Keep the existing backend `POST /api/audio/speech/stream` NDJSON contract and existing HTMLAudio playback path. Add a focused front-end scheduler module that decodes complete WAV segments into `AudioBuffer`s, schedules one `AudioBufferSourceNode` per segment on the `AudioContext` timeline, and exposes stop/dispose/idle behavior to the existing playback hook. Integrate it into `useAudioPlaybackController` only for streaming playback, with HTMLAudio fallback for unsupported Web Audio, decode failures, or output routing failures.

**Tech Stack:** React + TypeScript + Vite, Vitest + Testing Library, browser Web Audio API, existing FastAPI audio streaming backend unchanged.

---

## File structure

Create:

- `frontend/src/audio/streamingAudioScheduler.ts`
  - Pure browser audio utility. Owns `AudioContext`, output sink attempt, decoding, source scheduling, source stop, and idle resolution. No React state and no API fetching.
- `frontend/src/audio/streamingAudioScheduler.test.ts`
  - Unit tests with fake `AudioContext`, fake `AudioBufferSourceNode`, and deterministic `currentTime`.
- `frontend/src/hooks/useAudioPlaybackController.streaming.test.tsx`
  - Hook-level integration tests with a small React harness and mocked scheduler factory.
- `docs/stage2h-low-gap-streaming-audio.md`
  - Evidence document after validation.

Modify:

- `frontend/src/hooks/useAudioPlaybackController.ts`
  - Use the scheduler for streaming TTS when possible; preserve the existing HTMLAudio segment queue as fallback.
- `frontend/src/components/MessageList.test.tsx`
  - Update existing streaming playback expectations only if the new hook-level tests make the current `playMock`-based assumptions obsolete. Prefer not to remove existing coverage unless necessary.
- `README.md`
  - Add a short Stage 2H note after tests pass.
- `CLAUDE.md`
  - Update Stage 2 status only after tests and smoke evidence pass.

Do not modify backend code, ASR providers, TTS provider contracts, chat persistence, long-term memory, or emotion systems in this slice.

---

### Task 1: Add Web Audio scheduler unit tests

**Files:**
- Create: `frontend/src/audio/streamingAudioScheduler.test.ts`
- Later implementation target: `frontend/src/audio/streamingAudioScheduler.ts`

- [ ] **Step 1: Write the failing scheduler tests**

Create `frontend/src/audio/streamingAudioScheduler.test.ts` with this content:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createStreamingAudioScheduler } from './streamingAudioScheduler';

interface FakeSource {
  buffer: FakeAudioBuffer | null;
  connected: boolean;
  onended: (() => void) | null;
  start: ReturnType<typeof vi.fn<(when?: number) => void>>;
  stop: ReturnType<typeof vi.fn<() => void>>;
  connect: ReturnType<typeof vi.fn<(destination: unknown) => void>>;
  end: () => void;
}

interface FakeAudioBuffer {
  duration: number;
}

class FakeAudioContext {
  static instances: FakeAudioContext[] = [];

  currentTime = 10;
  destination = { kind: 'destination' };
  state: AudioContextState = 'running';
  decodedBuffers: FakeAudioBuffer[] = [];
  sources: FakeSource[] = [];
  sinkIds: string[] = [];
  closed = false;

  constructor(_options?: AudioContextOptions) {
    FakeAudioContext.instances.push(this);
  }

  decodeAudioData = vi.fn(async (_data: ArrayBuffer): Promise<AudioBuffer> => {
    const next = this.decodedBuffers.shift() ?? { duration: 0.1 };
    return next as AudioBuffer;
  });

  createBufferSource = vi.fn((): AudioBufferSourceNode => {
    const source: FakeSource = {
      buffer: null,
      connected: false,
      onended: null,
      start: vi.fn(),
      stop: vi.fn(),
      connect: vi.fn(() => {
        source.connected = true;
      }),
      end: () => {
        source.onended?.();
      },
    };
    this.sources.push(source);
    return source as unknown as AudioBufferSourceNode;
  });

  resume = vi.fn(async () => {
    this.state = 'running';
  });

  close = vi.fn(async () => {
    this.closed = true;
    this.state = 'closed';
  });

  setSinkId = vi.fn(async (sinkId: string) => {
    this.sinkIds.push(sinkId);
  });
}

describe('createStreamingAudioScheduler', () => {
  const originalAudioContext = globalThis.AudioContext;

  beforeEach(() => {
    FakeAudioContext.instances = [];
    Object.defineProperty(globalThis, 'AudioContext', {
      configurable: true,
      value: FakeAudioContext,
    });
  });

  afterEach(() => {
    if (originalAudioContext) {
      Object.defineProperty(globalThis, 'AudioContext', {
        configurable: true,
        value: originalAudioContext,
      });
    } else {
      delete (globalThis as Partial<typeof globalThis>).AudioContext;
    }
    vi.restoreAllMocks();
  });

  it('schedules adjacent decoded segments on the AudioContext timeline', async () => {
    const scheduler = createStreamingAudioScheduler({ initialLookaheadSeconds: 0.02 });
    const context = FakeAudioContext.instances[0];
    context.decodedBuffers.push({ duration: 0.12 }, { duration: 0.2 });

    const first = await scheduler.enqueue({
      audioBytes: new Uint8Array([82, 73, 70, 70, 87, 65, 86, 69]),
      mediaType: 'audio/wav',
      durationMs: 120,
      sampleRate: 24000,
    });
    const second = await scheduler.enqueue({
      audioBytes: new Uint8Array([82, 73, 70, 70, 87, 65, 86, 69]),
      mediaType: 'audio/wav',
      durationMs: 200,
      sampleRate: 24000,
    });

    expect(context.decodeAudioData).toHaveBeenCalledTimes(2);
    expect(context.sources).toHaveLength(2);
    expect(context.sources[0].connect).toHaveBeenCalledWith(context.destination);
    expect(context.sources[0].start).toHaveBeenCalledWith(10.02);
    expect(context.sources[1].start).toHaveBeenCalledWith(10.14);
    expect(first.queueDepth).toBe(1);
    expect(second.queueDepth).toBe(2);
    expect(second.scheduledStartTime).toBeCloseTo(first.scheduledStartTime + 0.12, 5);
  });

  it('stops all scheduled sources and resolves idle waiters', async () => {
    const scheduler = createStreamingAudioScheduler({ initialLookaheadSeconds: 0 });
    const context = FakeAudioContext.instances[0];
    context.decodedBuffers.push({ duration: 0.5 }, { duration: 0.5 });

    await scheduler.enqueue({ audioBytes: new Uint8Array([1]), mediaType: 'audio/wav', durationMs: 500, sampleRate: 24000 });
    await scheduler.enqueue({ audioBytes: new Uint8Array([2]), mediaType: 'audio/wav', durationMs: 500, sampleRate: 24000 });
    const idle = scheduler.waitForIdle();

    scheduler.stop();

    await expect(idle).resolves.toBeUndefined();
    expect(context.sources[0].stop).toHaveBeenCalledTimes(1);
    expect(context.sources[1].stop).toHaveBeenCalledTimes(1);
  });

  it('applies selected output sink when AudioContext setSinkId is available', async () => {
    const scheduler = createStreamingAudioScheduler({ audioOutputDeviceId: 'speaker-1' });
    const context = FakeAudioContext.instances[0];
    context.decodedBuffers.push({ duration: 0.1 });

    await scheduler.enqueue({ audioBytes: new Uint8Array([1]), mediaType: 'audio/wav', durationMs: 100, sampleRate: 24000 });

    expect(context.setSinkId).toHaveBeenCalledWith('speaker-1');
  });

  it('reports unsupported when AudioContext is unavailable', () => {
    delete (globalThis as Partial<typeof globalThis>).AudioContext;

    const scheduler = createStreamingAudioScheduler();

    expect(scheduler.isSupported()).toBe(false);
  });

  it('closes the AudioContext on dispose', async () => {
    const scheduler = createStreamingAudioScheduler();
    const context = FakeAudioContext.instances[0];
    context.decodedBuffers.push({ duration: 0.1 });

    await scheduler.enqueue({ audioBytes: new Uint8Array([1]), mediaType: 'audio/wav', durationMs: 100, sampleRate: 24000 });
    await scheduler.dispose();

    expect(context.close).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run the scheduler tests and verify they fail**

Run:

```powershell
npm --prefix frontend test -- src/audio/streamingAudioScheduler.test.ts
```

Expected: FAIL because `frontend/src/audio/streamingAudioScheduler.ts` does not exist.

---

### Task 2: Implement the Web Audio scheduler

**Files:**
- Create: `frontend/src/audio/streamingAudioScheduler.ts`
- Test: `frontend/src/audio/streamingAudioScheduler.test.ts`

- [ ] **Step 1: Create the scheduler implementation**

Create `frontend/src/audio/streamingAudioScheduler.ts`:

```ts
export interface StreamingAudioSegment {
  audioBytes: Uint8Array;
  mediaType: 'audio/wav';
  durationMs: number;
  sampleRate: number;
}

export interface StreamingAudioScheduleResult {
  scheduledStartTime: number;
  scheduledEndTime: number;
  decodedDurationMs: number;
  queueDepth: number;
  underrunMs: number;
}

export interface StreamingAudioScheduler {
  isSupported: () => boolean;
  enqueue: (segment: StreamingAudioSegment) => Promise<StreamingAudioScheduleResult>;
  waitForIdle: () => Promise<void>;
  stop: () => void;
  dispose: () => Promise<void>;
}

interface StreamingAudioSchedulerOptions {
  audioOutputDeviceId?: string;
  initialLookaheadSeconds?: number;
}

type AudioContextConstructor = new (options?: AudioContextOptions) => AudioContext;
type SinkCapableAudioContext = AudioContext & { setSinkId?: (sinkId: string) => Promise<void> };

const DEFAULT_LOOKAHEAD_SECONDS = 0.03;

function audioContextConstructor(): AudioContextConstructor | null {
  const maybeWindow = globalThis as typeof globalThis & { webkitAudioContext?: AudioContextConstructor };
  return globalThis.AudioContext ?? maybeWindow.webkitAudioContext ?? null;
}

function copyToArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return copy.buffer;
}

function resolveIdle(waiters: Array<() => void>): void {
  while (waiters.length > 0) {
    const resolve = waiters.shift();
    resolve?.();
  }
}

export function createStreamingAudioScheduler(options: StreamingAudioSchedulerOptions = {}): StreamingAudioScheduler {
  const ContextCtor = audioContextConstructor();
  const lookaheadSeconds = options.initialLookaheadSeconds ?? DEFAULT_LOOKAHEAD_SECONDS;
  let context: AudioContext | null = ContextCtor ? new ContextCtor({ latencyHint: 'interactive' }) : null;
  let sinkApplied = false;
  let nextStartTime = 0;
  let hasScheduled = false;
  const activeSources = new Set<AudioBufferSourceNode>();
  const idleWaiters: Array<() => void> = [];

  function isSupported(): boolean {
    return Boolean(ContextCtor && context && typeof context.decodeAudioData === 'function' && typeof context.createBufferSource === 'function');
  }

  async function ensureContext(): Promise<AudioContext> {
    if (!ContextCtor) throw new Error('当前浏览器不支持低间隙 Web Audio 播放。');
    if (!context || context.state === 'closed') {
      context = new ContextCtor({ latencyHint: 'interactive' });
      sinkApplied = false;
    }
    if (context.state === 'suspended') {
      await context.resume();
    }
    const selectedSink = options.audioOutputDeviceId ?? '';
    const sinkContext = context as SinkCapableAudioContext;
    if (selectedSink && !sinkApplied && typeof sinkContext.setSinkId === 'function') {
      await sinkContext.setSinkId(selectedSink);
      sinkApplied = true;
    }
    return context;
  }

  function notifyIdleIfNeeded(): void {
    if (activeSources.size === 0) {
      resolveIdle(idleWaiters);
    }
  }

  async function enqueue(segment: StreamingAudioSegment): Promise<StreamingAudioScheduleResult> {
    if (segment.mediaType !== 'audio/wav') {
      throw new Error('低间隙播放仅支持 WAV 语音片段。');
    }
    const audioContext = await ensureContext();
    const decoded = await audioContext.decodeAudioData(copyToArrayBuffer(segment.audioBytes));
    const source = audioContext.createBufferSource();
    source.buffer = decoded;
    source.connect(audioContext.destination);

    const now = audioContext.currentTime;
    const underrunMs = hasScheduled && nextStartTime < now ? Math.round((now - nextStartTime) * 1000) : 0;
    if (!hasScheduled || nextStartTime < now) {
      nextStartTime = now + lookaheadSeconds;
    }

    const scheduledStartTime = nextStartTime;
    const decodedDurationSeconds = decoded.duration;
    const scheduledEndTime = scheduledStartTime + decodedDurationSeconds;

    activeSources.add(source);
    source.onended = () => {
      activeSources.delete(source);
      notifyIdleIfNeeded();
    };
    source.start(scheduledStartTime);
    hasScheduled = true;
    nextStartTime = scheduledEndTime;

    return {
      scheduledStartTime,
      scheduledEndTime,
      decodedDurationMs: Math.round(decodedDurationSeconds * 1000),
      queueDepth: activeSources.size,
      underrunMs,
    };
  }

  function stop(): void {
    for (const source of Array.from(activeSources)) {
      try {
        source.stop();
      } catch {
        // Stopping an already-ended source is harmless for this controller.
      }
      activeSources.delete(source);
    }
    nextStartTime = 0;
    hasScheduled = false;
    notifyIdleIfNeeded();
  }

  function waitForIdle(): Promise<void> {
    if (activeSources.size === 0) return Promise.resolve();
    return new Promise((resolve) => {
      idleWaiters.push(resolve);
    });
  }

  async function dispose(): Promise<void> {
    stop();
    if (context && context.state !== 'closed') {
      await context.close();
    }
    context = null;
    sinkApplied = false;
  }

  return { dispose, enqueue, isSupported, stop, waitForIdle };
}
```

- [ ] **Step 2: Run the scheduler tests and verify they pass**

Run:

```powershell
npm --prefix frontend test -- src/audio/streamingAudioScheduler.test.ts
```

Expected: PASS.

- [ ] **Step 3: Run TypeScript check for scheduler typing**

Run:

```powershell
npm --prefix frontend run typecheck
```

Expected: PASS. If TypeScript does not know `AudioContext.setSinkId`, keep the local `SinkCapableAudioContext` type rather than modifying global DOM declarations.

---

### Task 3: Add playback-controller streaming scheduler tests

**Files:**
- Create: `frontend/src/hooks/useAudioPlaybackController.streaming.test.tsx`
- Modify later: `frontend/src/hooks/useAudioPlaybackController.ts`

- [ ] **Step 1: Write failing hook integration tests**

Create `frontend/src/hooks/useAudioPlaybackController.streaming.test.tsx`:

```tsx
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useAudioPlaybackController } from './useAudioPlaybackController';
import { createStreamingAudioScheduler } from '../audio/streamingAudioScheduler';

vi.mock('../audio/streamingAudioScheduler', () => ({
  createStreamingAudioScheduler: vi.fn(),
}));

const originalFetch = globalThis.fetch;
const originalCreateObjectUrl = URL.createObjectURL;
const originalRevokeObjectUrl = URL.revokeObjectURL;
const originalPlay = HTMLMediaElement.prototype.play;
const originalPause = HTMLMediaElement.prototype.pause;

function segmentLine(index: number, label: string): string {
  const bytes = new TextEncoder().encode(`RIFF....WAVE${label}`);
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return JSON.stringify({
    type: 'segment',
    index,
    audio_base64: btoa(binary),
    media_type: 'audio/wav',
    duration_ms: 100,
    sample_rate: 16000,
  }) + '\n';
}

function makeScheduler(overrides: Partial<ReturnType<typeof baseScheduler>> = {}) {
  return { ...baseScheduler(), ...overrides };
}

function baseScheduler() {
  return {
    isSupported: vi.fn(() => true),
    enqueue: vi.fn(async () => ({
      scheduledStartTime: 1,
      scheduledEndTime: 1.1,
      decodedDurationMs: 100,
      queueDepth: 1,
      underrunMs: 0,
    })),
    waitForIdle: vi.fn(async () => undefined),
    stop: vi.fn(),
    dispose: vi.fn(async () => undefined),
  };
}

function StreamingHarness({ outputDeviceId = '' }: { outputDeviceId?: string }) {
  const audioController = useAudioPlaybackController({ audioOutputDeviceId: outputDeviceId });
  const state = audioController.stateFor('a1');
  return (
    <>
      <div data-testid="state">{state.state}</div>
      <button type="button" onClick={() => { void audioController.play('a1', '第一句。第二句。', { streaming: true }); }}>
        stream play
      </button>
      <button type="button" onClick={() => audioController.stop('a1')}>
        stop stream
      </button>
    </>
  );
}

describe('useAudioPlaybackController streaming Web Audio integration', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn();
    URL.createObjectURL = vi.fn(() => 'blob:fallback-segment');
    URL.revokeObjectURL = vi.fn();
    HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(vi.fn());
  });

  afterEach(() => {
    cleanup();
    globalThis.fetch = originalFetch;
    URL.createObjectURL = originalCreateObjectUrl;
    URL.revokeObjectURL = originalRevokeObjectUrl;
    HTMLMediaElement.prototype.play = originalPlay;
    HTMLMediaElement.prototype.pause = originalPause;
    vi.restoreAllMocks();
  });

  it('uses the Web Audio scheduler for streaming TTS segments when supported', async () => {
    const user = userEvent.setup();
    const scheduler = makeScheduler();
    vi.mocked(createStreamingAudioScheduler).mockReturnValueOnce(scheduler);
    const encoder = new TextEncoder();
    vi.mocked(fetch).mockResolvedValueOnce(new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-tone-v1"}\n'));
        controller.enqueue(encoder.encode(segmentLine(0, 'first')));
        controller.enqueue(encoder.encode(segmentLine(1, 'second')));
        controller.enqueue(encoder.encode('{"type":"done","segment_count":2}\n'));
        controller.close();
      },
    }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));

    render(<StreamingHarness />);
    await user.click(screen.getByRole('button', { name: 'stream play' }));

    await waitFor(() => expect(scheduler.enqueue).toHaveBeenCalledTimes(2));
    expect(createStreamingAudioScheduler).toHaveBeenCalledWith({ audioOutputDeviceId: '' });
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(screen.getByTestId('state')).toHaveTextContent(/playing|ready/);
  });

  it('passes the selected output device to the Web Audio scheduler', async () => {
    const user = userEvent.setup();
    const scheduler = makeScheduler();
    vi.mocked(createStreamingAudioScheduler).mockReturnValueOnce(scheduler);
    const encoder = new TextEncoder();
    vi.mocked(fetch).mockResolvedValueOnce(new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-tone-v1"}\n'));
        controller.enqueue(encoder.encode(segmentLine(0, 'first')));
        controller.enqueue(encoder.encode('{"type":"done","segment_count":1}\n'));
        controller.close();
      },
    }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));

    render(<StreamingHarness outputDeviceId="speaker-1" />);
    await user.click(screen.getByRole('button', { name: 'stream play' }));

    await waitFor(() => expect(createStreamingAudioScheduler).toHaveBeenCalledWith({ audioOutputDeviceId: 'speaker-1' }));
  });

  it('falls back to HTMLAudio segment playback when the scheduler is unsupported', async () => {
    const user = userEvent.setup();
    const scheduler = makeScheduler({ isSupported: vi.fn(() => false) });
    vi.mocked(createStreamingAudioScheduler).mockReturnValueOnce(scheduler);
    const encoder = new TextEncoder();
    vi.mocked(fetch).mockResolvedValueOnce(new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-tone-v1"}\n'));
        controller.enqueue(encoder.encode(segmentLine(0, 'first')));
        controller.enqueue(encoder.encode('{"type":"done","segment_count":1}\n'));
        controller.close();
      },
    }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));

    render(<StreamingHarness />);
    await user.click(screen.getByRole('button', { name: 'stream play' }));

    await waitFor(() => expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1));
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    expect(scheduler.enqueue).not.toHaveBeenCalled();
  });

  it('stops the scheduler and aborts the stream when streaming playback is stopped', async () => {
    const user = userEvent.setup();
    const scheduler = makeScheduler();
    vi.mocked(createStreamingAudioScheduler).mockReturnValueOnce(scheduler);
    let capturedSignal: AbortSignal | undefined;
    let streamController: ReadableStreamDefaultController<Uint8Array> | null = null;
    const encoder = new TextEncoder();
    vi.mocked(fetch).mockImplementationOnce((_input, init) => {
      capturedSignal = init?.signal as AbortSignal;
      return Promise.resolve(new Response(new ReadableStream<Uint8Array>({
        start(controller) {
          streamController = controller;
        },
      }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));
    });

    render(<StreamingHarness />);
    await user.click(screen.getByRole('button', { name: 'stream play' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    if (!streamController) throw new Error('stream controller missing');
    streamController.enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-tone-v1"}\n'));
    streamController.enqueue(encoder.encode(segmentLine(0, 'first')));
    await waitFor(() => expect(scheduler.enqueue).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole('button', { name: 'stop stream' }));

    expect(capturedSignal?.aborted).toBe(true);
    expect(scheduler.stop).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run the new hook tests and verify they fail**

Run:

```powershell
npm --prefix frontend test -- src/hooks/useAudioPlaybackController.streaming.test.tsx
```

Expected: FAIL because `useAudioPlaybackController` does not yet import or use `createStreamingAudioScheduler`.

---

### Task 4: Integrate scheduler into streaming playback hook

**Files:**
- Modify: `frontend/src/hooks/useAudioPlaybackController.ts`
- Test: `frontend/src/hooks/useAudioPlaybackController.streaming.test.tsx`
- Regression Test: `frontend/src/components/MessageList.test.tsx`

- [ ] **Step 1: Import the scheduler and add refs**

At the top of `frontend/src/hooks/useAudioPlaybackController.ts`, add:

```ts
import { createStreamingAudioScheduler, type StreamingAudioScheduler } from '../audio/streamingAudioScheduler';
```

Inside `useAudioPlaybackController`, next to the existing refs, add:

```ts
const streamingSchedulerRef = useRef<StreamingAudioScheduler | null>(null);
```

- [ ] **Step 2: Stop scheduler on active stop**

In `stopActive`, immediately after `abortControllerRef.current = null;`, add:

```ts
streamingSchedulerRef.current?.stop();
```

Do not remove existing HTMLAudio pause/currentTime logic.

- [ ] **Step 3: Dispose scheduler on reset**

In `reset`, before clearing URL maps, add:

```ts
void streamingSchedulerRef.current?.dispose();
streamingSchedulerRef.current = null;
```

Keep existing URL revocation and queue cleanup.

- [ ] **Step 4: Add helper functions inside the hook**

Inside `useAudioPlaybackController`, before `const play = useCallback(...)`, add these helpers:

```ts
const queueHtmlStreamingSegment = useCallback(async (
  messageId: string,
  event: { audioBytes: Uint8Array; mediaType: 'audio/wav'; durationMs: number; sampleRate: number },
  metadata: { provider: string | null; model: string | null },
  startedPlayback: boolean,
): Promise<boolean> => {
  const audioBytes = new Uint8Array(event.audioBytes);
  const url = URL.createObjectURL(new Blob([audioBytes.buffer], { type: event.mediaType }));
  rememberUrl(messageId, url);
  updateEntry(messageId, {
    state: startedPlayback ? 'playing' : 'ready',
    url,
    error: null,
    metadata: {
      provider: metadata.provider,
      model: metadata.model,
      durationMs: event.durationMs,
      sampleRate: event.sampleRate,
    },
  });
  if (!startedPlayback) {
    return playExisting(messageId, url);
  }
  const queue = streamingQueuesRef.current.get(messageId) ?? [];
  queue.push(url);
  streamingQueuesRef.current.set(messageId, queue);
  return true;
}, [playExisting, rememberUrl, updateEntry]);
```

This keeps the old HTMLAudio segment behavior available without duplicating it throughout the streaming branch.

- [ ] **Step 5: Replace the streaming branch segment handling**

In the `if (options.streaming) { ... }` branch of `play`, replace the existing `if (event.type === 'segment') { ... }` block with:

```ts
if (event.type === 'segment') {
  const segment = {
    audioBytes: new Uint8Array(event.audioBytes),
    mediaType: event.mediaType,
    durationMs: event.durationMs,
    sampleRate: event.sampleRate,
  };

  if (streamingSchedulerRef.current?.isSupported()) {
    try {
      await streamingSchedulerRef.current.enqueue(segment);
      startedPlayback = true;
      updateEntry(messageId, {
        state: 'playing',
        url: null,
        error: null,
        metadata: {
          provider,
          model,
          durationMs: event.durationMs,
          sampleRate: event.sampleRate,
        },
      });
      continue;
    } catch {
      streamingSchedulerRef.current.stop();
      streamingSchedulerRef.current = null;
    }
  }

  const htmlStarted = await queueHtmlStreamingSegment(messageId, segment, { provider, model }, startedPlayback);
  if (!htmlStarted) {
    abortController.abort();
    revokeUrl(messageId);
    return false;
  }
  startedPlayback = true;
}
```

At the start of the streaming branch, immediately after `streamingMessageIdsRef.current.add(messageId);`, add:

```ts
streamingSchedulerRef.current?.stop();
streamingSchedulerRef.current = createStreamingAudioScheduler({ audioOutputDeviceId: audioOutputDeviceIdRef.current });
if (!streamingSchedulerRef.current.isSupported()) {
  streamingSchedulerRef.current = null;
}
```

After the `for await` loop and before `if (startedPlayback) return true;`, add:

```ts
const schedulerAtEnd = streamingSchedulerRef.current;
if (startedPlayback && schedulerAtEnd) {
  void schedulerAtEnd.waitForIdle().then(() => {
    if (activeMessageIdRef.current !== messageId || streamingSchedulerRef.current !== schedulerAtEnd) return;
    setEntries((current) => ({
      ...current,
      [messageId]: { ...(current[messageId] ?? defaultEntry), state: 'ready' },
    }));
    setActive(null);
  });
  return true;
}
```

- [ ] **Step 6: Update the `play` dependency list**

Add `queueHtmlStreamingSegment` to the dependency array of `play`.

The end of the `play` callback dependencies should include:

```ts
}, [entries, playExisting, queueHtmlStreamingSegment, revokeUrl, setActive, stopActive, updateEntry]);
```

- [ ] **Step 7: Run hook streaming tests**

Run:

```powershell
npm --prefix frontend test -- src/hooks/useAudioPlaybackController.streaming.test.tsx
```

Expected: PASS.

- [ ] **Step 8: Run existing MessageList audio tests**

Run:

```powershell
npm --prefix frontend test -- src/components/MessageList.test.tsx
```

Expected: PASS. If the existing `starts streamed playback after the first segment before stream completion` test now expects `HTMLMediaElement.play` but the Web Audio scheduler is used, update that test to either mock scheduler unsupported for the HTMLAudio path or move Web Audio assertions into `useAudioPlaybackController.streaming.test.tsx`. Do not delete coverage for HTMLAudio fallback.

---

### Task 5: Add fallback and interruption regression coverage

**Files:**
- Modify: `frontend/src/hooks/useAudioPlaybackController.streaming.test.tsx`
- Modify only if needed: `frontend/src/components/MessageList.test.tsx`

- [ ] **Step 1: Add enqueue-failure fallback test**

Append this test to `frontend/src/hooks/useAudioPlaybackController.streaming.test.tsx` inside the existing `describe` block:

```tsx
it('falls back to HTMLAudio playback when Web Audio enqueue fails', async () => {
  const user = userEvent.setup();
  const scheduler = makeScheduler({
    enqueue: vi.fn(async () => {
      throw new Error('decode failed');
    }),
  });
  vi.mocked(createStreamingAudioScheduler).mockReturnValueOnce(scheduler);
  const encoder = new TextEncoder();
  vi.mocked(fetch).mockResolvedValueOnce(new Response(new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-tone-v1"}\n'));
      controller.enqueue(encoder.encode(segmentLine(0, 'first')));
      controller.enqueue(encoder.encode('{"type":"done","segment_count":1}\n'));
      controller.close();
    },
  }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));

  render(<StreamingHarness />);
  await user.click(screen.getByRole('button', { name: 'stream play' }));

  await waitFor(() => expect(scheduler.enqueue).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1));
  expect(scheduler.stop).toHaveBeenCalledTimes(1);
  expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
});
```

- [ ] **Step 2: Add reset/dispose coverage if no existing reset test catches it**

Append:

```tsx
it('disposes the scheduler when the controller resets', async () => {
  const user = userEvent.setup();
  const scheduler = makeScheduler();
  vi.mocked(createStreamingAudioScheduler).mockReturnValueOnce(scheduler);
  const encoder = new TextEncoder();
  vi.mocked(fetch).mockResolvedValueOnce(new Response(new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-tone-v1"}\n'));
      controller.enqueue(encoder.encode(segmentLine(0, 'first')));
      controller.enqueue(encoder.encode('{"type":"done","segment_count":1}\n'));
      controller.close();
    },
  }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));

  function ResetHarness() {
    const audioController = useAudioPlaybackController();
    return (
      <>
        <button type="button" onClick={() => { void audioController.play('a1', '第一句。', { streaming: true }); }}>
          stream play
        </button>
        <button type="button" onClick={() => audioController.reset()}>
          reset audio
        </button>
      </>
    );
  }

  render(<ResetHarness />);
  await user.click(screen.getByRole('button', { name: 'stream play' }));
  await waitFor(() => expect(scheduler.enqueue).toHaveBeenCalledTimes(1));

  await user.click(screen.getByRole('button', { name: 'reset audio' }));

  expect(scheduler.dispose).toHaveBeenCalledTimes(1);
});
```

- [ ] **Step 3: Run focused streaming tests**

Run:

```powershell
npm --prefix frontend test -- src/audio/streamingAudioScheduler.test.ts src/hooks/useAudioPlaybackController.streaming.test.tsx src/components/MessageList.test.tsx
```

Expected: PASS.

---

### Task 6: Run frontend regression suite

**Files:**
- No code changes unless tests reveal regressions.

- [ ] **Step 1: Run App tests**

Run:

```powershell
npm --prefix frontend test -- src/App.test.tsx
```

Expected: PASS. This protects voice-turn orchestration, interruption, session switching, and stale state behavior.

- [ ] **Step 2: Run all frontend unit tests**

Run:

```powershell
npm --prefix frontend test -- --run
```

Expected: PASS.

- [ ] **Step 3: Run typecheck**

Run:

```powershell
npm --prefix frontend run typecheck
```

Expected: PASS.

- [ ] **Step 4: Run build**

Run:

```powershell
npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 5: Run voice-turn E2E**

Run:

```powershell
npm --prefix frontend run test:e2e -- voice-turn.spec.ts
```

Expected: PASS. If webServer startup flakes, rerun once and record both the transient failure and final result in the evidence document.

---

### Task 7: Optional local fake-provider runtime smoke

**Files:**
- No source changes.
- Evidence target: `docs/stage2h-low-gap-streaming-audio.md`

- [ ] **Step 1: Start fake-provider backend**

Run in one terminal:

```powershell
$env:APP_ENV='development'; $env:DATABASE_URL='sqlite:///./data/stage2h-smoke.db'; $env:LLM_PROVIDER='fake'; $env:TTS_PROVIDER='fake'; $env:ASR_PROVIDER='fake'; python -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Expected: Uvicorn starts on `http://127.0.0.1:8000`.

- [ ] **Step 2: Start frontend**

Run in another terminal:

```powershell
$env:BACKEND_PROXY_TARGET='http://127.0.0.1:8000'; npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

Expected: Vite starts on `http://127.0.0.1:5173`.

- [ ] **Step 3: Run existing fake voice-turn browser smoke or E2E**

If a project smoke script exists for voice turns, run it. If not, run:

```powershell
npm --prefix frontend run test:e2e -- voice-turn.spec.ts
```

Expected: PASS with no browser console errors.

Record whether Web Audio scheduling telemetry is visible. If no telemetry exists yet, record only that fake-provider voice-turn streaming playback passed through automated browser coverage.

---

### Task 8: Write evidence documentation and update status docs

**Files:**
- Create: `docs/stage2h-low-gap-streaming-audio.md`
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Create evidence document**

Create `docs/stage2h-low-gap-streaming-audio.md`:

```markdown
# Stage 2H Low-Gap Streaming Audio Playback Evidence

Status: COMPLETED on 2026-07-03.

## Scope

This slice adds a browser-side Web Audio scheduling path for existing streaming TTS segments from `POST /api/audio/speech/stream`. It preserves the existing NDJSON TTS contract and the existing HTMLAudio fallback path.

It does not implement long-term memory, emotion state, wake-word listening, background listening, LLM response streaming, or production-grade streaming ASR changes.

## Implemented behavior

- Streaming TTS segments can be decoded and scheduled on an `AudioContext` timeline.
- Each decoded segment uses a fresh `AudioBufferSourceNode`.
- Adjacent segments are scheduled by `nextStartTime` rather than waiting for an HTMLAudio `ended` event.
- Existing HTMLAudio segment playback remains available as fallback.
- Stop/reset/interruption aborts the stream and stops scheduled Web Audio sources.
- Output device preferences remain recoverable: Web Audio sink routing is attempted where supported, and HTMLAudio `setSinkId()` fallback remains available.
- Text chat remains usable if audio playback fails.

## Validation

| Command / Surface | Result |
|---|---|
| `npm --prefix frontend test -- src/audio/streamingAudioScheduler.test.ts` | PASS |
| `npm --prefix frontend test -- src/hooks/useAudioPlaybackController.streaming.test.tsx` | PASS |
| `npm --prefix frontend test -- src/components/MessageList.test.tsx` | PASS |
| `npm --prefix frontend test -- src/App.test.tsx` | PASS |
| `npm --prefix frontend test -- --run` | PASS |
| `npm --prefix frontend run typecheck` | PASS |
| `npm --prefix frontend run build` | PASS |
| `npm --prefix frontend run test:e2e -- voice-turn.spec.ts` | PASS |

## Notes

- This is a low-gap scheduled segment playback slice, not a raw PCM AudioWorklet streaming implementation.
- Real CosyVoice may return one segment for short text, so fake-provider multi-segment tests provide the deterministic segment-gap proof.
- Browser support for Web Audio output-device routing varies; fallback behavior is part of the acceptance boundary.
```

Replace any PASS row with the real observed result. If any command fails and is not fixed, do not mark status completed.

- [ ] **Step 2: Update README Stage 2 list**

In `README.md`, add one bullet near the existing Stage 2 voice bullets:

```markdown
- Stage 2H low-gap streaming audio playback：浏览器端 streaming TTS 可优先使用 Web Audio 对完整 WAV segments 进行低间隙调度播放，并保留既有 HTMLAudio 输出设备兼容回退；证据记录于 `docs/stage2h-low-gap-streaming-audio.md`。
```

Do not claim long-term memory or emotion support.

- [ ] **Step 3: Update CLAUDE.md current stage text**

In `CLAUDE.md`, update only the Stage 2 status entries related to `Final seamless low-gap audio` after validation passes:

- In the top current-stage line, append `Final seamless low-gap audio COMPLETED`.
- In the Stage 2 status table, replace `Final seamless low-gap audio：NOT STARTED` with `Final seamless low-gap audio：COMPLETED`.
- In the Stage 2 completed abilities list, add a concise Stage 2H bullet with date, tests, and scope boundaries.
- In `阶段 2 尚未实现`, remove `最终无缝低间隙音频流` only if no other Stage 2 gap remains.

Do not change Stage 3 or Stage 4 status.

- [ ] **Step 4: Run docs-sensitive smoke checks**

Run:

```powershell
npm --prefix frontend run typecheck
```

Expected: PASS. Documentation edits should not affect typecheck.

---

### Task 9: Final full validation and report

**Files:**
- No code changes unless validation reveals issues.

- [ ] **Step 1: Run focused frontend validation**

Run:

```powershell
npm --prefix frontend test -- src/audio/streamingAudioScheduler.test.ts src/hooks/useAudioPlaybackController.streaming.test.tsx src/components/MessageList.test.tsx src/App.test.tsx
```

Expected: PASS.

- [ ] **Step 2: Run full frontend validation**

Run:

```powershell
npm --prefix frontend test -- --run; npm --prefix frontend run typecheck; npm --prefix frontend run build
```

Expected: all PASS.

- [ ] **Step 3: Run E2E validation**

Run:

```powershell
npm --prefix frontend run test:e2e
```

Expected: PASS. Record count of passed tests.

- [ ] **Step 4: Check git diff for forbidden scope**

Run:

```powershell
git diff -- frontend/src/audio frontend/src/hooks/useAudioPlaybackController.ts frontend/src/components/MessageList.test.tsx frontend/src/hooks/useAudioPlaybackController.streaming.test.tsx docs/stage2h-low-gap-streaming-audio.md README.md CLAUDE.md
```

Expected: Diff only includes Stage 2H playback scheduler, tests, and docs. No long-term memory, emotion, backend provider, schema, or secret changes.

- [ ] **Step 5: Final response template**

Use this exact report structure:

```text
完成内容：
- Stage 2H Web Audio low-gap streaming playback implemented for streaming TTS segments.
- Existing HTMLAudio fallback and text-chat availability preserved.

修改文件：
- frontend/src/audio/streamingAudioScheduler.ts
- frontend/src/audio/streamingAudioScheduler.test.ts
- frontend/src/hooks/useAudioPlaybackController.ts
- frontend/src/hooks/useAudioPlaybackController.streaming.test.tsx
- docs/stage2h-low-gap-streaming-audio.md
- README.md
- CLAUDE.md

验证命令与结果：
- <paste actual commands and PASS/FAIL results>

未完成或受限部分：
- This is scheduled complete-segment playback, not AudioWorklet raw PCM streaming.
- Browser output-device routing for Web Audio depends on browser support and falls back to HTMLAudio.
- Long-term memory and emotion remain unimplemented by stage rule.

是否改变当前阶段：
- 否。仍是阶段 2；仅完成阶段 2H 子任务。只有确认阶段 2 全部验收标准后才能进入阶段 3。

下一项建议任务：
- 如果 Stage 2H 验证全部通过，执行 Stage 2 总体验收审计，确认是否可以关闭阶段 2 并准备阶段 3 长期记忆设计。
```

---

## Self-review

Spec coverage:

- Web Audio scheduled queue: covered by Tasks 1–4.
- HTMLAudio fallback: covered by Tasks 3–5.
- Output-device preservation: covered by scheduler sink test and hook selected-device test.
- Stop/reset/interruption cleanup: covered by Tasks 3–5 and App/E2E regression in Task 6.
- Evidence docs and stage status: covered by Task 8.
- No memory/emotion/background listening: stated in scope and final diff check.

Placeholder scan:

- No TBD/TODO placeholders remain.
- Optional runtime smoke is explicitly marked optional and has a concrete fallback command.

Type consistency:

- Scheduler exports `createStreamingAudioScheduler`, `StreamingAudioScheduler`, `StreamingAudioSegment`, and `StreamingAudioScheduleResult`.
- Hook tests mock the same factory and methods used by the planned hook integration.
- Playback hook fallback keeps existing `playExisting`, `rememberUrl`, `revokeUrl`, and `streamingQueuesRef` names from the current implementation.
